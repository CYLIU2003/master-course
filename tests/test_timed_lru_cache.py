import time
from bff.utils import timed_lru_cache


def test_timed_lru_cache_expires():
    call_tracker = []

    @timed_lru_cache(seconds=2, maxsize=2)
    def expensive_function(arg1):
        call_tracker.append(1)
        return arg1

    # First call
    assert expensive_function("a") == "a"
    assert len(call_tracker) == 1
    assert expensive_function.cache_info().hits == 0
    assert expensive_function.cache_info().misses == 1
    assert expensive_function.cache_info().currsize == 1

    # Second call (cached)
    assert expensive_function("a") == "a"
    assert len(call_tracker) == 1
    assert expensive_function.cache_info().hits == 1
    assert expensive_function.cache_info().misses == 1
    assert expensive_function.cache_info().currsize == 1

    # Wait to expire
    time.sleep(2.1)

    # Third call (re-calculated)
    assert expensive_function("a") == "a"
    assert len(call_tracker) == 2
    # a new time hash is used, so we have a miss, and the cache size is back to 1
    assert expensive_function.cache_info().hits == 0
    assert expensive_function.cache_info().misses == 1
    assert expensive_function.cache_info().currsize == 1


def test_timed_lru_cache_clear():
    call_tracker = []

    @timed_lru_cache(seconds=10)
    def expensive_function(arg1):
        call_tracker.append(1)
        return arg1

    assert expensive_function("a") == "a"
    assert len(call_tracker) == 1
    assert expensive_function.cache_info().currsize == 1

    assert expensive_function("a") == "a"
    assert len(call_tracker) == 1
    assert expensive_function.cache_info().hits == 1

    expensive_function.cache_clear()
    assert expensive_function.cache_info().currsize == 0
    assert expensive_function.cache_info().hits == 0

    assert expensive_function("a") == "a"
    assert len(call_tracker) == 2
    assert expensive_function.cache_info().currsize == 1
    assert expensive_function.cache_info().misses == 1
