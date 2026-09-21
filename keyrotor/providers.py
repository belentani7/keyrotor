"""Provider definitions (LiteLLM-inspired).

Each provider declares: base URL, auth style, default model, retry
policy and how to build its payload from an OpenAI-style request.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

PayloadBuilder = Callable[[Dict[str, Any], str], Dict[str, Any]]


@dataclass
class Provider:
    name: str
    base_url: str
    auth_type: str = "bearer"          # "bearer" | "query" | "header"
    auth_param: str = "Authorization"
    timeout: float = 30.0
    max_retries: int = 3
    backoff_factor: float = 0.5
    cache_ttl: float = 300.0           # 0 = no cache
    default_model: str = ""
    catalog_url: str = ""              # GET /models endpoint ("" = unknown)
    build_payload: Optional[PayloadBuilder] = None  # custom body builder

    def payload(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Build the provider-specific request body."""
        if self.build_payload is not None:
            model = request.get("model") or self.default_model
            return self.build_payload(request, model)
        body = dict(request)
        if not body.get("model"):
            body["model"] = self.default_model
        return body


def _gemini_payload(request: Dict[str, Any], model: str) -> Dict[str, Any]:
    """OpenAI-style messages -> Gemini generateContent format."""
    contents: List[Dict[str, Any]] = []
    system_parts: List[str] = []
    for msg in request.get("messages", []):
        role = msg.get("role", "user")
        content = msg.get("content") or ""
        if isinstance(content, list):  # multimodal parts
            content = " ".join(
                str(p.get("text", "")) for p in content if isinstance(p, dict)
            )
        if role == "system":
            system_parts.append(str(content))
            continue
        gemini_role = "model" if role == "assistant" else "user"
        contents.append({"role": gemini_role, "parts": [{"text": str(content)}]})
    body: Dict[str, Any] = {"contents": contents}
    if system_parts:
        body["systemInstruction"] = {"parts": [{"text": "\n".join(system_parts)}]}
    if request.get("max_tokens"):
        body["generationConfig"] = {"maxOutputTokens": request["max_tokens"]}
    return body


def _chat_url(base: str, model: str) -> str:
    if "{model}" in base:
        return base.replace("{model}", model)
    return base


def _env_model(var: str, default: str) -> str:
    """Default model, overridable per provider from the environment."""
    return os.environ.get(var) or default


BUILTIN_PROVIDERS: Dict[str, Provider] = {
    "openrouter": Provider(
        name="openrouter",
        base_url="https://openrouter.ai/api/v1/chat/completions",
        default_model=_env_model(
            "OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free"
        ),
        timeout=30.0,
        max_retries=3,
        backoff_factor=1.0,
        cache_ttl=300.0,
    ),
    "nvidia": Provider(
        name="nvidia",
        base_url="https://integrate.api.nvidia.com/v1/chat/completions",
        default_model=_env_model(
            "NVIDIA_MODEL", "nvidia/nemotron-3-super-120b-a12b"
        ),
        timeout=30.0,
        max_retries=2,
        cache_ttl=300.0,
    ),
    "google": Provider(
        name="google",
        base_url="https://generativelanguage.googleapis.com/v1beta/models/"
        "{model}:generateContent",
        auth_type="query",
        auth_param="key",
        default_model=_env_model("GOOGLE_MODEL", "gemini-3.6-flash"),
        timeout=20.0,
        max_retries=2,
        cache_ttl=600.0,
        build_payload=_gemini_payload,
    ),
    "opencode": Provider(
        name="opencode",
        base_url=_env_model(
            "OPENCODE_BASE_URL", "https://opencode.ai/zen/v1/chat/completions"
        ),
        default_model=_env_model("OPENCODE_MODEL", "deepseek-v4-flash-free"),
        timeout=25.0,
        max_retries=2,
        cache_ttl=300.0,
    ),
    # --- Gateways free-friendly (2026-09) ---
    # Groq: TPM POR MODELO; compound-mini es el unico con 70K TPM capaz de
    # tragarse el system prompt de un agente CLI sin 413.
    "groq": Provider(
        name="groq",
        base_url="https://api.groq.com/openai/v1/chat/completions",
        default_model=_env_model("GROQ_MODEL", "groq/compound-mini"),
        timeout=25.0,
        max_retries=2,
        cache_ttl=300.0,
    ),
    "cerebras": Provider(
        name="cerebras",
        base_url="https://api.cerebras.ai/v1/chat/completions",
        default_model=_env_model("CEREBRAS_MODEL", "gpt-oss-120b"),
        timeout=25.0,
        max_retries=2,
        cache_ttl=300.0,
    ),
    "mistral": Provider(
        name="mistral",
        base_url="https://api.mistral.ai/v1/chat/completions",
        default_model=_env_model("MISTRAL_MODEL", "mistral-small-latest"),
        timeout=25.0,
        max_retries=2,
        cache_ttl=300.0,
    ),
    "deepseek": Provider(
        name="deepseek",
        base_url="https://api.deepseek.com/chat/completions",
        default_model=_env_model("DEEPSEEK_MODEL", "deepseek-chat"),
        timeout=40.0,
        max_retries=2,
        cache_ttl=300.0,
    ),
    "huggingface": Provider(
        name="huggingface",
        base_url="https://router.huggingface.co/v1/chat/completions",
        default_model=_env_model(
            "HUGGINGFACE_MODEL", "meta-llama/Llama-3.3-70B-Instruct"
        ),
        timeout=40.0,
        max_retries=2,
        cache_ttl=0.0,
    ),
}

# Endpoints GET /models para saber QUÉ modelos sirve cada gateway antes de
# gastar cuota: si el modelo pedido no está en el catálogo, se salta el
# proveedor sin hacer ninguna llamada de chat.
_CATALOG_URLS = {
    "openrouter": "https://openrouter.ai/api/v1/models",
    "nvidia": "https://integrate.api.nvidia.com/v1/models",
    "google": "https://generativelanguage.googleapis.com/v1beta/models",
    "groq": "https://api.groq.com/openai/v1/models",
    "cerebras": "https://api.cerebras.ai/v1/models",
    "mistral": "https://api.mistral.ai/v1/models",
    "deepseek": "https://api.deepseek.com/models",
    "huggingface": "https://router.huggingface.co/v1/models",
}
for _p in BUILTIN_PROVIDERS.values():
    _p.catalog_url = _CATALOG_URLS.get(_p.name, "")


def resolve_url(provider: Provider, request: Dict[str, Any]) -> str:
    model = request.get("model") or provider.default_model
    return _chat_url(provider.base_url, model)
