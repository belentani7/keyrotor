"""Circuit breaker per provider.

Thresholds follow the 2026 AI API integration best practices:
- OPEN after `threshold` consecutive failures (default 5)
- stay open for `cooldown` seconds (default 60)
- HALF-OPEN: allow exactly one probe request; success closes the
  circuit, failure extends the open period.
"""

from __future__ import annotations

import threading
import time
from enum import Enum
from typing import Optional


class State(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    def __init__(self, threshold: int = 5, cooldown: float = 60.0) -> None:
        self.threshold = threshold
        self.cooldown = cooldown
        self._lock = threading.Lock()
        self._state = State.CLOSED
        self._failures = 0
        self._opened_at: Optional[float] = None
        self._probing = False

    @property
    def state(self) -> State:
        with self._lock:
            self._transition()
            return self._state

    @property
    def failures(self) -> int:
        with self._lock:
            return self._failures

    def _transition(self) -> None:
        if self._state == State.OPEN and self._opened_at is not None:
            if time.time() - self._opened_at >= self.cooldown:
                self._state = State.HALF_OPEN
                self._probing = False

    def allow(self) -> bool:
        """True if a request may pass right now.

        In HALF_OPEN exactly one probe is admitted at a time; concurrent
        callers are refused until the probe resolves.
        """
        with self._lock:
            self._transition()
            if self._state == State.OPEN:
                return False
            if self._state == State.HALF_OPEN:
                if self._probing:
                    return False
                self._probing = True
                return True
            return True

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._state = State.CLOSED
            self._opened_at = None
            self._probing = False

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._state == State.HALF_OPEN:
                self._state = State.OPEN
                self._opened_at = time.time()
                self._probing = False
            elif self._failures >= self.threshold:
                self._state = State.OPEN
                self._opened_at = time.time()
