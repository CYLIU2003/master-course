from functools import lru_cache, wraps
from typing import Callable, TypeVar
import time

# Generic type for the decorated function
F = TypeVar("F", bound=Callable)


def timed_lru_cache(seconds: int, maxsize: int = 128) -> Callable[[F], F]:
    """
    LRU cache with a time-to-live (TTL) expiration.
    """

    def wrapper_cache(func: F) -> F:
        current_ttl_hash = None

        @lru_cache(maxsize=maxsize)
        def cached_func_with_ttl(ttl_hash, *args, **kwargs):
            return func(*args, **kwargs)

        @wraps(func)
        def wrapper(*args, **kwargs):
            nonlocal current_ttl_hash
            ttl_hash = round(time.time() / seconds)
            if current_ttl_hash is None:
                current_ttl_hash = ttl_hash
            elif ttl_hash != current_ttl_hash:
                cached_func_with_ttl.cache_clear()
                current_ttl_hash = ttl_hash
            return cached_func_with_ttl(ttl_hash, *args, **kwargs)

        wrapper.cache_info = cached_func_with_ttl.cache_info
        wrapper.cache_clear = cached_func_with_ttl.cache_clear
        return wrapper

    return wrapper_cache
