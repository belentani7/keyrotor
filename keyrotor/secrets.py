"""Environment-only provider credentials and deterministic routing order.

No dotenv parsing, logging or persistence occurs here. An example .env file is
documentation until the operator explicitly exports its values to the process.
"""
from __future__ import annotations

import os
from typing import Dict, List, Mapping, Optional, Sequence

# Canonical provider IDs correspond exactly to keyrotor.providers.BUILTIN_PROVIDERS.
_KEY_VARS = {
    "openrouter": ("OPENROUTER_API_KEYS", "OPENROUTER_API_KEY"),
    "nvidia": ("NVIDIA_API_KEYS", "NVIDIA_API_KEY"),
    "google": ("GOOGLE_API_KEYS", "GOOGLE_API_KEY", "GEMINI_API_KEY"),
    "opencode": ("OPENCODE_API_KEYS", "OPENCODE_API_KEY"),
    "groq": ("GROQ_API_KEYS", "GROQ_API_KEY"),
    "cerebras": ("CEREBRAS_API_KEYS", "CEREBRAS_API_KEY"),
    "mistral": ("MISTRAL_API_KEYS", "MISTRAL_API_KEY"),
    "deepseek": ("DEEPSEEK_API_KEYS", "DEEPSEEK_API_KEY"),
    "huggingface": ("HUGGINGFACE_API_KEYS", "HUGGINGFACE_API_KEY", "HF_TOKEN"),
}


def load_keys(env: Optional[Mapping[str, str]] = None) -> Dict[str, List[str]]:
    """Read provider key pools solely from process environment.

    Comma-separated keys are de-duplicated without changing their order. Blank,
    example and newline-bearing values are ignored rather than sent upstream.
    Never log or echo the returned credentials.
    """
    source = os.environ if env is None else env
    result: Dict[str, List[str]] = {}
    for provider, names in _KEY_VARS.items():
        pool: List[str] = []
        seen = set()
        for name in names:
            value = source.get(name, "")
            if not isinstance(value, str):
                continue
            for item in value.split(","):
                key = item.strip()
                if (not key or "\n" in key or "\r" in key
                        or "EXAMPLE" in key.upper() or key in seen):
                    continue
                seen.add(key)
                pool.append(key)
        result[provider] = pool
    return result


def provider_order_from_env(
    default: Sequence[str], env: Optional[Mapping[str, str]] = None
) -> List[str]:
    """Preserve explicitly ordered, known provider IDs; fall back if empty."""
    source = os.environ if env is None else env
    raw = source.get("KEYROTOR_PROVIDER_ORDER", "")
    allowed = set(default)
    if not raw:
        return list(default)
    names = []
    for piece in raw.split(","):
        name = piece.strip().lower()
        if name in allowed and name not in names:
            names.append(name)
    return names or list(default)
