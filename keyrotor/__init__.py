"""keyrotor - zero-secret multi-provider LLM key rotation router.

Inspired by the real-world LiteLLM gateway (BerriAI/litellm) and the
2026 AI API integration best practices:

- Key rotation with automatic failover (401/403 -> rotate key,
  exhausted provider -> failover to next provider).
- Exact-match response cache (SHA-256 + TTL) to cut cost and latency.
- Circuit breaker (closed / open / half-open) per provider.
- Exponential backoff with jitter on 429 / 5xx.
- Zero-downtime key rotation pattern (primary + fallback pools).
- Backend-proxy pattern: the frontend never sees a secret.
- Keys load ONLY from environment variables and are always redacted
  in logs, metrics and the dashboard.
"""

__version__ = "1.0.0"

from keyrotor.breaker import CircuitBreaker
from keyrotor.cache import TTLCache
from keyrotor.providers import BUILTIN_PROVIDERS, Provider
from keyrotor.redact import Redactor, redact
from keyrotor.router import RotatingRouter, RouterResult

__all__ = [
    "BUILTIN_PROVIDERS",
    "CircuitBreaker",
    "Provider",
    "Redactor",
    "RotatingRouter",
    "RouterResult",
    "TTLCache",
    "__version__",
    "redact",
]
