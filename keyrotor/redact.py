"""Secret detection and redaction.

Rule #1 of the project: NO SECRETS in logs, metrics, UI, or git.

The patterns below cover the key formats of the providers this router
supports (Google AI Studio, NVIDIA, OpenRouter, OpenCode/Zen) plus
common GitHub/HuggingFace tokens and JWT-shaped strings, so that an
accidentally leaked secret can never be re-printed by the router.
"""

from __future__ import annotations

import re
from typing import List, Tuple

_SECRET_PATTERNS: List[Tuple[str, re.Pattern]] = [
    ("jwt", re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")),
    ("github-pat", re.compile(r"github_pat_[A-Za-z0-9_]{10,}")),
    ("github-oauth", re.compile(r"\bgh[opsu]_[A-Za-z0-9]{20,}")),
    ("huggingface", re.compile(r"\bhf_[A-Za-z0-9]{20,}")),
    ("openrouter", re.compile(r"\bsk-or-v[0-9]+-[a-fA-F0-9]{20,}")),
    ("openai-proj", re.compile(r"\bsk-proj-[A-Za-z0-9_\-]{20,}")),
    ("openai-like", re.compile(r"\bsk-[A-Za-z0-9]{12,}")),
    ("nvidia", re.compile(r"\bnvapi-[A-Za-z0-9]{20,}")),
    ("google-aistudio", re.compile(r"\bAIza[A-Za-z0-9_\-]{20,}")),
    ("gemini-oauth", re.compile(r"\bAQ\.[A-Za-z0-9_\-]{16,}")),
    ("aws-access", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private-key", re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----[A-Za-z0-9+/=\r\n]+"
        r"-----END [A-Z ]*PRIVATE KEY-----")),
]


def _redact_repl(match: re.Match) -> str:
    token = match.group(0)
    if len(token) > 8:
        return token[:4] + "****" + token[-4:]
    return "****"


def redact(text: str) -> str:
    """Replace every secret-looking substring with a masked form."""
    for _name, pattern in _SECRET_PATTERNS:
        text = pattern.sub(_redact_repl, text)
    return text


def find_secrets(text: str) -> List[Tuple[str, str]]:
    """Return (kind, masked) for each secret found in text."""
    found: List[Tuple[str, str]] = []
    for kind, pattern in _SECRET_PATTERNS:
        for match in pattern.finditer(text):
            found.append((kind, _redact_repl(match)))
    return found


def mask_key(key: str) -> str:
    """Human-safe representation of a key: first 4 + last 4."""
    if not key:
        return ""
    if len(key) <= 8:
        return "****"
    return f"{key[:4]}...{key[-4:]}"


class Redactor:
    """Thin wrapper so router internals share one redaction policy."""

    def clean(self, text: str) -> str:
        return redact(text)

    def mask(self, key: str) -> str:
        return mask_key(key)
