"""RotatingRouter - the heart of keyrotor.

Implements the 2026 zero-downtime key rotation pattern over multiple
providers (inspired by LiteLLM's Router):

- per-key rotation: 401/403 -> drop key, retry with the next key of
  the same provider;
- per-provider failover: provider exhausted or breaker open -> move to
  the next provider in `provider_order`;
- retry policy: 429/5xx -> exponential backoff with jitter, without
  dropping the key; network errors -> retry, never drop the key;
- circuit breaker: 5 consecutive failures open the circuit for 60s
  (half-open probe afterwards);
- exact-match cache: SHA-256(provider+url+payload) with per-provider
  TTL - repeat requests cost zero tokens and zero money;
- everything that leaves this module is REDACTED: keys are always
  masked (first4...last4) in logs, metrics and events.

The HTTP transport is injectable (`transport`), so tests and custom
stacks can run the full router without network access.
"""

from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from keyrotor.breaker import CircuitBreaker
from keyrotor.cache import TTLCache
from keyrotor.providers import Provider, resolve_url
from keyrotor.redact import Redactor

# Transport signature: (url, headers, body, params, timeout) -> FakeResponse
Transport = Callable[..., Any]

# Status codes that mean "this key is dead": drop and rotate.
_KEY_KILLERS = (401, 403)
# Status codes that mean "temporary": retry with backoff, keep the key.
_RETRYABLE = (429, 408, 500, 502, 503, 504)


class FakeResponse:
    """Minimal response object so transports don't need `requests`."""

    def __init__(self, status_code: int, json_data: Any = None, text: str = ""):
        self.status_code = status_code
        self._json = json_data
        self.text = text

    def json(self) -> Any:
        if self._json is None:
            raise ValueError("no json")
        return self._json


def _requests_transport(url, headers, body, params, timeout):
    """Default transport built on `requests` (only external dependency)."""
    import requests  # local import keeps the router importable without it

    response = requests.post(
        url,
        headers=headers,
        json=body,
        params=params,
        timeout=timeout,
        proxies={"http": None, "https": None},  # direct connection, no proxy
    )
    try:
        return FakeResponse(response.status_code, response.json(), response.text)
    except ValueError:
        return FakeResponse(response.status_code, None, response.text)


@dataclass
class RouterResult:
    ok: bool
    provider: str = ""
    model: str = ""
    content: str = ""
    data: Optional[Dict[str, Any]] = None
    cache_hit: bool = False
    attempts: int = 0
    error: str = ""


@dataclass
class _ProviderStats:
    requests: int = 0
    successes: int = 0
    failures: int = 0
    keys_dropped: int = 0
    cache_hits: int = 0
    breaker: CircuitBreaker = field(default_factory=CircuitBreaker)


class RotatingRouter:
    def __init__(
        self,
        providers: Dict[str, Provider],
        keys: Optional[Dict[str, List[str]]] = None,
        provider_order: Optional[List[str]] = None,
        transport: Optional[Transport] = None,
        cache_ttl: Optional[float] = None,
        max_retries: Optional[int] = None,
        backoff_factor: Optional[float] = None,
        breaker_threshold: int = 5,
        breaker_cooldown: float = 60.0,
    ) -> None:
        self.providers = providers
        self._keys: Dict[str, List[str]] = {
            name: [k for k in ks if k] for name, ks in (keys or {}).items()
        }
        self.provider_order = provider_order or list(providers.keys())
        self.transport = transport or _requests_transport
        self.cache = TTLCache()
        self.redactor = Redactor()
        self._lock = threading.RLock()  # reentrant: _drop_key logs while locked
        self._stats: Dict[str, _ProviderStats] = {
            name: _ProviderStats(
                breaker=CircuitBreaker(breaker_threshold, breaker_cooldown)
            )
            for name in providers
        }
        self._events: List[Dict[str, Any]] = []
        self.cache_ttl = cache_ttl
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor

    # ---------------------------------------------------------- keys
    def _get_key(self, provider: str) -> Optional[str]:
        with self._lock:
            pool = self._keys.get(provider, [])
            return random.choice(pool) if pool else None

    def _drop_key(self, provider: str, bad_key: str) -> None:
        with self._lock:
            pool = self._keys.get(provider, [])
            if bad_key in pool:
                pool.remove(bad_key)
                self._stats[provider].keys_dropped += 1
                self._log("key_dropped", provider,
                          f"key {self.redactor.mask(bad_key)} removed (401/403)")

    def _auth_headers(
        self, provider: Provider, key: str, base_headers: Dict[str, str]
    ) -> Dict[str, str]:
        headers = dict(base_headers)
        if provider.auth_type == "bearer":
            headers[provider.auth_param] = f"Bearer {key}"
        elif provider.auth_type == "header":
            headers[provider.auth_param] = key
        return headers

    def _auth_params(self, provider: Provider, key: str) -> Dict[str, str]:
        if provider.auth_type == "query":
            return {provider.auth_param: key}
        return {}

    # ---------------------------------------------------------- events
    def _log(self, event: str, provider: str, message: str) -> None:
        with self._lock:
            self._events.append(
                {
                    "ts": round(time.time(), 3),
                    "event": event,
                    "provider": provider,
                    "message": self.redactor.clean(message),
                }
            )
            if len(self._events) > 100:
                self._events = self._events[-100:]

    @property
    def events(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._events)

    # ---------------------------------------------------------- request
    def _attempt(
        self,
        provider_name: str,
        provider: Provider,
        key: str,
        url: str,
        headers: Dict[str, str],
        body: Dict[str, Any],
    ) -> Optional[FakeResponse]:
        cfg_retries = self.max_retries if self.max_retries is not None else provider.max_retries
        factor = self.backoff_factor if self.backoff_factor is not None else provider.backoff_factor

        for attempt in range(cfg_retries):
            try:
                response = self.transport(
                    url,
                    self._auth_headers(provider, key, headers),
                    body,
                    self._auth_params(provider, key),
                    provider.timeout,
                )
            except Exception as exc:  # network-level failure
                self._log("network_error", provider_name, f"{exc}")
                if attempt < cfg_retries - 1:
                    time.sleep(factor * (2 ** attempt) + random.uniform(0, 0.1))
                    continue
                return None

            if response.status_code in _KEY_KILLERS:
                return response
            if response.status_code in _RETRYABLE:
                wait = factor * (2 ** attempt) + random.uniform(0, 0.2)
                self._log("retry", provider_name,
                          f"HTTP {response.status_code}, intento {attempt + 1}/{cfg_retries}, espera {wait:.2f}s")
                time.sleep(wait)
                continue
            if response.status_code >= 400:
                return response  # 4xx client error: give up on this key
            return response
        return None

    def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        provider_order: Optional[List[str]] = None,
        use_cache: bool = True,
        cache_ttl: Optional[float] = None,
        **request_kwargs: Any,
    ) -> RouterResult:
        request = {"messages": messages, **request_kwargs}
        if model:
            request["model"] = model

        order = provider_order or self.provider_order
        headers = {"Content-Type": "application/json"}
        attempts = 0

        for provider_name in order:
            provider = self.providers.get(provider_name)
            if provider is None:
                self._log("skip", provider_name, "provider not registered")
                continue

            stats = self._stats[provider_name]

            url = resolve_url(provider, request)
            body = provider.payload(request)
            ttl = cache_ttl if cache_ttl is not None else (
                self.cache_ttl if self.cache_ttl is not None else provider.cache_ttl
            )

            # cache is served BEFORE the breaker gate: cache hits are free
            cache_key = self.cache.digest(provider_name, url, body)
            if use_cache and ttl > 0:
                cached = self.cache.get(cache_key, ttl)
                if cached is not None:
                    with self._lock:
                        stats.cache_hits += 1
                    self._log("cache_hit", provider_name, "served from cache")
                    return RouterResult(
                        ok=True, provider=provider_name,
                        model=request.get("model", provider.default_model),
                        content=self._extract_content(cached)
                        if isinstance(cached, dict) else str(cached),
                        data=cached, cache_hit=True, attempts=attempts,
                    )

            if not stats.breaker.allow():
                self._log("breaker_open", provider_name, "circuit open, skip")
                continue

            while True:
                key = self._get_key(provider_name)
                if key is None:
                    self._log("provider_empty", provider_name, "no keys left")
                    break

                with self._lock:
                    stats.requests += 1
                attempts += 1
                self._log("attempt", provider_name,
                          f"key {self.redactor.mask(key)} -> {url}")

                response = self._attempt(
                    provider_name, provider, key, url, headers, body
                )

                if response is None:
                    # network exhausted retries: keep key, failover provider
                    with self._lock:
                        stats.failures += 1
                    stats.breaker.record_failure()
                    break

                if response.status_code in _KEY_KILLERS:
                    # the KEY is dead, not the provider: drop and rotate,
                    # never trip the circuit breaker for a bad key
                    self._drop_key(provider_name, key)
                    with self._lock:
                        stats.failures += 1
                    continue  # rotate to the next key of the same provider

                if response.status_code >= 400:
                    # client/config error: provider is reachable
                    with self._lock:
                        stats.failures += 1
                    self._log("provider_error", provider_name,
                              f"HTTP {response.status_code}")
                    break  # failover to the next provider

                # success
                try:
                    data = response.json()
                except Exception:
                    data = {"raw": self.redactor.clean(response.text)}
                with self._lock:
                    stats.successes += 1
                stats.breaker.record_success()
                if use_cache and ttl > 0:
                    self.cache.set(cache_key, data)
                return RouterResult(
                    ok=True, provider=provider_name,
                    model=request.get("model", provider.default_model),
                    content=self._extract_content(data),
                    data=data, attempts=attempts,
                )

        return RouterResult(
            ok=False,
            error="all providers failed or exhausted",
            attempts=attempts,
        )

    @staticmethod
    def _extract_content(data: Dict[str, Any]) -> str:
        """Best-effort content extraction across OpenAI/Gemini shapes."""
        if not isinstance(data, dict):
            return ""
        choices = data.get("choices")
        if choices and choices[0].get("message", {}).get("content"):
            return str(choices[0]["message"]["content"])
        candidates = data.get("candidates")
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            return "".join(str(p.get("text", "")) for p in parts)
        return ""

    # ---------------------------------------------------------- status
    def status(self) -> Dict[str, Any]:
        with self._lock:
            providers_out = []
            for name in sorted(self.providers):
                stats = self._stats[name]
                providers_out.append(
                    {
                        "provider": name,
                        "keys_active": len(self._keys.get(name, [])),
                        "keys_masked": [
                            self.redactor.mask(k) for k in self._keys.get(name, [])
                        ],
                        "requests": stats.requests,
                        "successes": stats.successes,
                        "failures": stats.failures,
                        "keys_dropped": stats.keys_dropped,
                        "cache_hits": stats.cache_hits,
                        "breaker": stats.breaker.state.value,
                        "breaker_failures": stats.breaker.failures,
                    }
                )
            return {
                "cache": {
                    "size": self.cache.size,
                    "hits": self.cache.hits,
                    "misses": self.cache.misses,
                    "hit_rate": round(self.cache.hit_rate, 4),
                },
                "providers": providers_out,
                "events": list(self._events)[-30:],
            }
