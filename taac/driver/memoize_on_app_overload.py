# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import asyncio
import functools
import threading
from typing import Any, Callable, Dict, ParamSpec, Tuple, TypeVar

from cachetools import LRUCache

T = TypeVar("T")
P = ParamSpec("P")

APP_OVERLOAD_ERROR = "APP_OVERLOAD"


def make_cache_key(args: Tuple[Any, ...], kwargs: Dict[str, Any]) -> Tuple:
    # Simple but robust: args + sorted kwargs as tuple
    return args + tuple(sorted(kwargs.items()))


def memoize_on_app_overload(
    max_size: int = 1000,  # 1000 is the default size of the LRU cache
):
    """
    Memoize decorator: on ServiceRouterError(APP_OVERLOAD), return cached value.
    Supports sync and async functions.
    """

    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        cache = LRUCache(max_size)
        lock = threading.Lock()
        async_lock = asyncio.Lock()

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            key = args + tuple(sorted(kwargs.items()))
            try:
                result = func(*args, **kwargs)
                with lock:
                    cache[key] = result
                return result
            except Exception as e:
                if APP_OVERLOAD_ERROR in str(e):
                    with lock:
                        cached = cache.get(key)
                    if cached is not None:
                        return cached
                raise
            return sync_wrapper

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            key = args + tuple(sorted(kwargs.items()))
            try:
                result = await func(*args, **kwargs)
                async with async_lock:
                    cache[key] = result
                return result
            except Exception as e:
                if APP_OVERLOAD_ERROR in str(e):
                    async with async_lock:
                        cached = cache.get(key)
                    if cached is not None:
                        return cached
                raise

        if asyncio.iscoroutinefunction(func):
            return async_wrapper  # type: ignore
        else:
            return sync_wrapper  # type: ignore

    return decorator
