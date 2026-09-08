"""Exact-match TTL response cache.

Same idea as LiteLLM's gateway caching and the 2026 best-practice
"exact match caching": hash the request (provider + endpoint + body),
serve repeats from memory, expire entries with a per-provider TTL.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict
from typing import Any, Dict, Optional, Tuple


class TTLCache:
    def __init__(self, maxsize: int = 1000) -> None:
        self._store: "OrderedDict[str, Tuple[float, Any]]" = OrderedDict()
        self._lock = threading.Lock()
        self._maxsize = maxsize
        self.hits = 0
        self.misses = 0
        self.evictions = 0

    @staticmethod
    def digest(provider: str, url: str, payload: dict) -> str:
        raw = json.dumps(
            {"provider": provider, "url": url, "payload": payload},
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, key: str, ttl: float) -> Optional[Any]:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self.misses += 1
                return None
            timestamp, value = entry
            if time.time() - timestamp >= ttl:
                del self._store[key]
                self.evictions += 1
                self.misses += 1
                return None
            self._store.move_to_end(key)
            self.hits += 1
            return value

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._store[key] = (time.time(), value)
            self._store.move_to_end(key)
            while len(self._store) > self._maxsize:
                self._store.popitem(last=False)
                self.evictions += 1

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._store)

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return (self.hits / total) if total else 0.0
