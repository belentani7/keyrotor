"""CircuitBreaker unit tests."""

import time

from keyrotor.breaker import CircuitBreaker


def test_starts_closed():
    breaker = CircuitBreaker()
    assert breaker.state.value == "closed"
    assert breaker.failures == 0
    assert breaker.allow() is True


def test_threshold_failures_opens():
    breaker = CircuitBreaker(threshold=3)
    for _ in range(3):
        breaker.record_failure()
    assert breaker.state.value == "open"
    assert breaker.failures == 3


def test_allow_false_when_open():
    breaker = CircuitBreaker(threshold=2)
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.state.value == "open"
    assert breaker.allow() is False


def test_cooldown_passes_to_half_open():
    breaker = CircuitBreaker(threshold=2, cooldown=0.02)
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.state.value == "open"
    time.sleep(0.04)
    assert breaker.state.value == "half_open"
    assert breaker.allow() is True


def test_success_closes_after_half_open():
    breaker = CircuitBreaker(threshold=1, cooldown=0.02)
    breaker.record_failure()
    assert breaker.state.value == "open"
    time.sleep(0.04)
    assert breaker.state.value == "half_open"
    breaker.record_success()
    assert breaker.state.value == "closed"
    assert breaker.failures == 0


def test_half_open_failure_reopens():
    breaker = CircuitBreaker(threshold=1, cooldown=0.02)
    breaker.record_failure()
    assert breaker.state.value == "open"
    time.sleep(0.04)
    assert breaker.state.value == "half_open"
    breaker.record_failure()
    assert breaker.state.value == "open"


def test_success_resets_failure_counter():
    breaker = CircuitBreaker(threshold=3)
    breaker.record_failure()
    breaker.record_failure()
    breaker.record_success()
    assert breaker.failures == 0
    breaker.record_failure()
    assert breaker.state.value == "closed"
