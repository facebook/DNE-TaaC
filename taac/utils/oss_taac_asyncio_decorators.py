# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""
OSS-compatible async decorators for TAAC framework.

This module provides async memoization decorators that mirror the functionality
of libfb.py.asyncio.decorators for use in OSS environments.
"""

import asyncio
import functools
import time
import typing as t
from typing import Any, Callable, Dict, Tuple

# Type variable for async functions
AsyncF = t.TypeVar("AsyncF", bound=Callable[..., t.Coroutine[t.Any, t.Any, t.Any]])


def memoize_forever(func: AsyncF) -> AsyncF:
    """
    Async decorator that caches coroutine results permanently.

    The cache is based on the function arguments (must be hashable).
    Results are cached indefinitely for the lifetime of the process.

    This is the async equivalent of libfb.py.asyncio.decorators.memoize_forever.

    Args:
        func: Async function to memoize

    Returns:
        Memoized async function

    Example:
        @memoize_forever
        async def get_device_info(hostname: str) -> dict:
            return await fetch_device_info(hostname)
    """
    cache: Dict[Tuple[Any, ...], Any] = {}
    locks: Dict[Tuple[Any, ...], asyncio.Lock] = {}

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        key = (args, tuple(sorted(kwargs.items())))

        # Fast path: check cache without lock
        if key in cache:
            return cache[key]

        # Get or create lock for this key
        if key not in locks:
            locks[key] = asyncio.Lock()

        async with locks[key]:
            # Double-check after acquiring lock
            if key in cache:
                return cache[key]

            result = await func(*args, **kwargs)
            cache[key] = result
            return result

    # Expose cache for testing/debugging
    wrapper.cache = cache  # type: ignore[attr-defined]
    wrapper.cache_clear = lambda: cache.clear()  # type: ignore[attr-defined]

    return t.cast(AsyncF, wrapper)


def memoize_timed(
    timeout_sec: float = 60.0,
    # pyre-fixme[34]: `Variable[AsyncF (bound to typing.Callable[...,
    #  typing.Coroutine[typing.Any, typing.Any, typing.Any]])]` isn't present in the
    #  function's parameters.
) -> Callable[[AsyncF], AsyncF]:
    """
    Async decorator that caches coroutine results for a specified duration.

    This is the async equivalent of libfb.py.asyncio.decorators.memoize_timed.

    Args:
        timeout_sec: Cache TTL in seconds (default: 60.0)

    Returns:
        Decorated async function with time-based caching

    Example:
        @memoize_timed(3600)  # Cache for 1 hour
        async def get_skynet_data(hostname: str) -> dict:
            return await fetch_from_skynet(hostname)
    """

    def decorator(func: AsyncF) -> AsyncF:
        cache: Dict[Tuple[Any, ...], Tuple[Any, float]] = {}
        locks: Dict[Tuple[Any, ...], asyncio.Lock] = {}

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            key = (args, tuple(sorted(kwargs.items())))
            now = time.time()

            # Check cache without lock first (fast path)
            if key in cache:
                value, timestamp = cache[key]
                if now - timestamp < timeout_sec:
                    return value

            # Get or create lock for this key
            if key not in locks:
                locks[key] = asyncio.Lock()

            async with locks[key]:
                # Double-check after acquiring lock
                if key in cache:
                    value, timestamp = cache[key]
                    if now - timestamp < timeout_sec:
                        return value

                result = await func(*args, **kwargs)
                cache[key] = (result, time.time())
                return result

        wrapper.cache = cache  # type: ignore[attr-defined]
        wrapper.cache_clear = lambda: cache.clear()  # type: ignore[attr-defined]

        return t.cast(AsyncF, wrapper)

    return decorator
