"""TTLCache unit tests."""

import time

from keyrotor.cache import TTLCache


def make_cache():
    return TTLCache()


def test_set_get_hit():
    cache = make_cache()
    cache.set("k1", {"answer": 42})
    assert cache.get("k1", ttl=60) == {"answer": 42}
    assert cache.hits == 1
    assert cache.misses == 0


def test_get_missing_is_miss():
    cache = make_cache()
    assert cache.get("nope", ttl=60) is None
    assert cache.misses == 1
    assert cache.hits == 0


def test_ttl_expiry():
    cache = make_cache()
    cache.set("k1", "value")
    time.sleep(0.03)
    assert cache.get("k1", ttl=0.01) is None
    assert cache.misses == 1
    assert cache.evictions == 1
    assert cache.size == 0


def test_ttl_not_yet_expired():
    cache = make_cache()
    cache.set("k1", "value")
    assert cache.get("k1", ttl=5.0) == "value"
    assert cache.size == 1


def test_hit_rate_math():
    cache = make_cache()
    cache.set("a", 1)
    cache.set("b", 2)
    cache.get("a", ttl=60)          # hit
    cache.get("b", ttl=60)          # hit
    cache.get("c", ttl=60)          # miss
    cache.get("d", ttl=60)          # miss
    assert cache.hits == 2
    assert cache.misses == 2
    assert cache.hit_rate == 0.5


def test_hit_rate_zero_when_empty():
    cache = make_cache()
    assert cache.hit_rate == 0.0


def test_clear():
    cache = make_cache()
    cache.set("a", 1)
    cache.set("b", 2)
    assert cache.size == 2
    cache.clear()
    assert cache.size == 0
    assert cache.get("a", ttl=60) is None
