"""Bounded OpenAI-shaped request validation for local-only Keyrotor proxy.

The gateway implements JSON chat completions, NOT SSE streaming.
Validation never inspects or logs provider secrets or user message content.
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Optional

_ROLES = frozenset(("system", "user", "assistant"))


def validate_chat_request(payload: Mapping[str, Any]) -> Optional[str]:
    messages = payload.get("messages")
    if not isinstance(messages, list) or not 1 <= len(messages) <= 64:
        return "messages must contain 1 to 64 entries"
    for message in messages:
        if not isinstance(message, dict) or message.get("role") not in _ROLES:
            return "invalid chat message role"
        content = message.get("content")
        if not isinstance(content, str) or not content.strip() or len(content) > 8000:
            return "message content must be non-empty text of at most 8000 characters"

    model = payload.get("model")
    if model is not None and (not isinstance(model, str) or len(model) > 150):
        return "model must be a string of at most 150 characters"
    # This gateway produces one ordinary JSON response. Never forward SSE mode
    # upstream and then misinterpret provider chunks as a normal completion.
    if "stream" in payload and payload["stream"] is not False:
        return "streaming is not supported; use stream=false"
    max_tokens = payload.get("max_tokens")
    if max_tokens is not None and (type(max_tokens) is not int or not 1 <= max_tokens <= 8192):
        return "max_tokens must be an integer between 1 and 8192"

    for name, low, high in (("temperature", 0.0, 2.0), ("top_p", 0.0, 1.0)):
        if name not in payload:
            continue
        value = payload[name]
        if (type(value) not in (int, float) or not math.isfinite(value) or
                not low <= value <= high):
            return name + " must be a finite value within provider limits"
    stop = payload.get("stop")
    if stop is not None:
        if isinstance(stop, str):
            if not 1 <= len(stop) <= 100:
                return "stop must be 1 to 100 characters"
        elif isinstance(stop, list):
            if not 1 <= len(stop) <= 4 or any(
                not isinstance(item, str) or not 1 <= len(item) <= 100
                for item in stop
            ):
                return "stop must contain at most four bounded strings"
        else:
            return "invalid stop value"
    return None
