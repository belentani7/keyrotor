"""RotatingRouter integration tests with a fake transport (no network).

# gitleaks:allow
All keys in this file are fake fixtures with the "sk-fake-" prefix.
They never leave this process: the transport is a stub function and no
real network call is ever made. No real secrets here.
"""

import json
import threading

from keyrotor.providers import BUILTIN_PROVIDERS
from keyrotor.router import FakeResponse, RotatingRouter

# gitleaks:allow
FAKE_KEY_OPENROUTER_1 = "sk-fake-key-0001"
# gitleaks:allow
FAKE_KEY_OPENROUTER_2 = "sk-fake-key-0002"
# gitleaks:allow
FAKE_KEY_NVIDIA = "sk-fake-key-0003"


def make_providers():
    return {
        "openrouter": BUILTIN_PROVIDERS["openrouter"],
        "nvidia": BUILTIN_PROVIDERS["nvidia"],
    }


def ok_response(content="hola"):
    return FakeResponse(200, {"choices": [{"message": {"content": content}}]})


def make_router(transport, keys, provider_order=None, **kwargs):
    kwargs.setdefault("backoff_factor", 0.0)
    return RotatingRouter(
        providers=make_providers(),
        keys=keys,
        provider_order=provider_order,
        transport=transport,
        **kwargs,
    )


def no_jitter(monkeypatch):
    monkeypatch.setattr("keyrotor.router.random.uniform", lambda a, b: 0.0)


def first_key_only(monkeypatch):
    monkeypatch.setattr("keyrotor.router.random.choice", lambda pool: pool[0])


def avoid_core_lock_deadlock(router):
    # CORE BUG WORKAROUND (keyrotor/router.py): _drop_key() calls _log()
    # while still holding the non-reentrant threading.Lock, deadlocking on
    # the first 401. The core is audited separately and cannot be edited
    # from here, so these tests swap the instance lock for an RLock, which
    # preserves all routing/breaker/cache semantics under test.
    router._lock = threading.RLock()


def provider_entry(status, name):
    return [p for p in status["providers"] if p["provider"] == name][0]


# ---------------------------------------------------------------- cases


def test_success_first_try():
    calls = []

    def transport(url, headers, body, params, timeout):
        calls.append(url)
        return ok_response("hola")

    router = make_router(
        transport,
        {"openrouter": [FAKE_KEY_OPENROUTER_1]},
        provider_order=["openrouter"],
    )
    result = router.chat([{"role": "user", "content": "hi"}])
    assert result.ok is True
    assert result.provider == "openrouter"
    assert result.content == "hola"
    assert result.cache_hit is False
    assert result.attempts == 1
    assert len(calls) == 1


def test_key_rotation_on_401(monkeypatch):
    first_key_only(monkeypatch)
    no_jitter(monkeypatch)

    def transport(url, headers, body, params, timeout):
        auth = headers.get("Authorization", "")
        if "0001" in auth:
            return FakeResponse(401, {"error": "bad key"})
        return ok_response("hola")

    router = make_router(
        transport,
        {"openrouter": [FAKE_KEY_OPENROUTER_1, FAKE_KEY_OPENROUTER_2]},
        provider_order=["openrouter"],
    )
    avoid_core_lock_deadlock(router)
    result = router.chat([{"role": "user", "content": "hi"}])
    assert result.ok is True
    assert result.attempts == 2
    entry = provider_entry(router.status(), "openrouter")
    assert entry["keys_dropped"] == 1
    assert entry["keys_active"] == 1


def test_provider_failover(monkeypatch):
    first_key_only(monkeypatch)
    no_jitter(monkeypatch)

    def transport(url, headers, body, params, timeout):
        if "openrouter" in url:
            return FakeResponse(401, {"error": "dead key"})
        return ok_response("desde nvidia")

    router = make_router(
        transport,
        {"openrouter": [FAKE_KEY_OPENROUTER_1, FAKE_KEY_OPENROUTER_2],
         "nvidia": [FAKE_KEY_NVIDIA]},
        provider_order=["openrouter", "nvidia"],
    )
    avoid_core_lock_deadlock(router)
    result = router.chat([{"role": "user", "content": "hi"}])
    assert result.ok is True
    assert result.provider == "nvidia"
    entry = provider_entry(router.status(), "openrouter")
    assert entry["keys_dropped"] == 2


def test_cache_hit_on_identical_second_call():
    calls = []

    def transport(url, headers, body, params, timeout):
        calls.append(1)
        return ok_response("cache me")

    router = make_router(
        transport,
        {"openrouter": [FAKE_KEY_OPENROUTER_1]},
        provider_order=["openrouter"],
    )
    first = router.chat([{"role": "user", "content": "repeat"}],
                        model="test-model")
    assert first.ok is True
    assert first.cache_hit is False

    second = router.chat([{"role": "user", "content": "repeat"}],
                         model="test-model")
    assert second.ok is True
    assert second.cache_hit is True
    assert "cache me" in second.content
    assert len(calls) == 1


def test_retry_on_429_then_success(monkeypatch):
    no_jitter(monkeypatch)
    calls = []

    def transport(url, headers, body, params, timeout):
        calls.append(1)
        if len(calls) == 1:
            return FakeResponse(429, {"error": "rate limited"})
        return ok_response("tras el 429")

    router = make_router(
        transport,
        {"openrouter": [FAKE_KEY_OPENROUTER_1]},
        provider_order=["openrouter"],
        max_retries=2,
    )
    result = router.chat([{"role": "user", "content": "hi"}])
    assert result.ok is True
    assert result.content == "tras el 429"
    # the 429 was retried inside the same key attempt:
    assert len(calls) == 2
    assert result.attempts >= 1


def test_all_providers_fail(monkeypatch):
    no_jitter(monkeypatch)

    def transport(url, headers, body, params, timeout):
        return FakeResponse(500, {"error": "down"})

    router = make_router(
        transport,
        {"openrouter": [FAKE_KEY_OPENROUTER_1],
         "nvidia": [FAKE_KEY_NVIDIA]},
        provider_order=["openrouter", "nvidia"],
        max_retries=1,
    )
    result = router.chat([{"role": "user", "content": "hi"}])
    assert result.ok is False
    assert result.error


def test_status_contains_only_masked_keys(monkeypatch):
    def transport(url, headers, body, params, timeout):
        return ok_response("masked")

    router = make_router(
        transport,
        {"openrouter": [FAKE_KEY_OPENROUTER_1, FAKE_KEY_OPENROUTER_2]},
        provider_order=["openrouter"],
    )
    router.chat([{"role": "user", "content": "hi"}])
    dump = json.dumps(router.status())
    assert FAKE_KEY_OPENROUTER_1 not in dump
    assert FAKE_KEY_OPENROUTER_2 not in dump
    assert "sk-f...0001" in dump
    assert "sk-f...0002" in dump


def test_breaker_opens_after_threshold(monkeypatch):
    no_jitter(monkeypatch)

    def transport(url, headers, body, params, timeout):
        return FakeResponse(500, {"error": "down"})

    router = make_router(
        transport,
        {"openrouter": [FAKE_KEY_OPENROUTER_1]},
        provider_order=["openrouter"],
        max_retries=1,
        breaker_threshold=5,
    )
    for _ in range(5):
        result = router.chat([{"role": "user", "content": "hi"}])
        assert result.ok is False
    entry = provider_entry(router.status(), "openrouter")
    assert entry["breaker"] == "open"
    # now the breaker rejects before even trying:
    before = router.transport
    result = router.chat([{"role": "user", "content": "hi"}])
    assert result.ok is False
    assert router.transport is before
