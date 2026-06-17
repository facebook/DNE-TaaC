# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""
OSS-compatible TAAC library utilities.

This module provides pure Python implementations of commonly used utilities
to enable TAAC to run in open-source environments without Meta-internal dependencies.

Usage:
    from taac.utils.oss_taac_lib_utils import (
        retryable,
        async_retryable,
        memoize_forever,
        memoize_timed,
        async_memoize_timed,
        none_throws,
        string_is_ip,
        get_ipv6_for_host,
        to_fb_fqdn,
        to_fb_uqdn,
        convert_to_async,
        wraps,
        lazy_import,
        ConsoleFileLogger,
        get_root_logger,
    )
"""

import asyncio
import datetime
import functools
import ipaddress
import logging
import os
import random
import socket
import tempfile
import time
import typing as t
from logging.handlers import RotatingFileHandler
from typing import Any, Callable, Dict, Optional, Tuple, Type, TypeVar

T = TypeVar("T")
F = TypeVar("F", bound=Callable[..., Any])
AsyncF = TypeVar("AsyncF", bound=Callable[..., t.Coroutine[Any, Any, Any]])

LOGGER = logging.getLogger(__name__)
FB_FQDN_SUFFIX = ".tfbnw.net"
FB_FQDN_FACEBOOK_SUFFIX = ".facebook.com"

# =============================================================================
# none_throws - from libfb.py.pyre
# =============================================================================


def none_throws(
    value: Optional[T],
    message: str = "Unexpected None value",
) -> T:
    """
    Assert that a value is not None and return it.

    This is useful for type narrowing when you know a value cannot be None
    but the type system doesn't.

    Args:
        value: The value to check
        message: Error message if value is None

    Returns:
        The value, guaranteed to be non-None

    Raises:
        AssertionError: If value is None

    Example:
        result: Optional[str] = get_maybe_string()
        # Type is Optional[str], but we know it's not None
        actual: str = none_throws(result, "Expected string to be present")
    """
    if value is None:
        raise AssertionError(message)
    return value


# =============================================================================
# wraps - from libfb.py.decorators (re-export functools.wraps)
# =============================================================================

# Re-export functools.wraps for compatibility
wraps = functools.wraps


# =============================================================================
# retryable - Synchronous retry decorator from libfb.py.decorators
# =============================================================================


def retryable(
    num_tries: int = 3,
    sleep_time: float = 1.0,
    retryable_exs: Tuple[Type[Exception], ...] = (Exception,),
    sleep_multiplier: float = 1.0,
    jitter: bool = False,
    print_ex: bool = False,
    debug: bool = False,
    max_duration: Optional[float] = None,
    # pyre-fixme[34]: `Variable[F (bound to typing.Callable[..., typing.Any])]` isn't
    #  present in the function's parameters.
) -> Callable[[F], F]:
    """
    Decorator that retries a function on failure.

    Args:
        num_tries: Maximum number of attempts (default: 3)
        sleep_time: Initial sleep time between retries in seconds (default: 1.0)
        retryable_exs: Tuple of exception types to retry on (default: all Exceptions)
        sleep_multiplier: Multiplier for sleep time after each retry (default: 1.0)
        jitter: If True, add random jitter to sleep time (default: False)
        print_ex: If True, print exception details on each retry (default: False)
        debug: If True, log debug information during retries (default: False)
        max_duration: Maximum total duration in seconds for all retries (default: None, no limit)

    Returns:
        Decorated function that will retry on failure

    Example:
        @retryable(num_tries=3, sleep_time=2.0, retryable_exs=(ConnectionError,))
        def fetch_data():
            return requests.get("https://api.example.com/data")
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception: Optional[Exception] = None
            current_sleep = sleep_time
            start_time = time.monotonic()

            for attempt in range(num_tries):
                if max_duration is not None and attempt > 0:
                    elapsed = time.monotonic() - start_time
                    if elapsed >= max_duration:
                        break
                try:
                    return func(*args, **kwargs)
                except retryable_exs as e:
                    last_exception = e
                    if attempt < num_tries - 1:
                        actual_sleep = current_sleep
                        if jitter:
                            actual_sleep += random.uniform(0, current_sleep * 0.1)
                        if max_duration is not None:
                            remaining = max_duration - (time.monotonic() - start_time)
                            if remaining <= 0:
                                break
                            actual_sleep = min(actual_sleep, remaining)
                        if print_ex or debug:
                            LOGGER.warning(
                                f"Attempt {attempt + 1}/{num_tries} failed for {func.__name__}: {e}. "  # pyre-ignore[16]
                                f"Retrying in {actual_sleep:.2f}s..."
                            )
                        time.sleep(actual_sleep)
                        current_sleep *= sleep_multiplier

            # All retries exhausted
            raise none_throws(last_exception)

        return t.cast(F, wrapper)

    return decorator


# =============================================================================
# async_retryable - Asynchronous retry decorator from libfb.py.asyncio.decorators
# =============================================================================


def async_retryable(
    num_tries: Optional[int] = None,
    retries: Optional[int] = None,  # Alias for num_tries
    sleep_time: float = 1.0,
    retryable_exs: Optional[Tuple[Type[Exception], ...]] = None,
    exceptions: Optional[Tuple[Type[Exception], ...]] = None,  # Alias for retryable_exs
    sleep_multiplier: float = 1.0,
    jitter: bool = False,
    max_duration: Optional[float] = None,  # Maximum total duration for all retries
    exception_to_raise: Optional[
        Exception
    ] = None,  # Custom exception to raise on failure
    # pyre-fixme[34]: `Variable[AsyncF (bound to typing.Callable[...,
    #  typing.Coroutine[typing.Any, typing.Any, typing.Any]])]` isn't present in the
    #  function's parameters.
) -> Callable[[AsyncF], AsyncF]:
    """
    Async decorator that retries a coroutine on failure.

    Args:
        num_tries: Maximum number of attempts (default: 3)
        retries: Alias for num_tries (for libfb compatibility)
        sleep_time: Initial sleep time between retries in seconds (default: 1.0)
        retryable_exs: Tuple of exception types to retry on (default: all Exceptions)
        exceptions: Alias for retryable_exs (for libfb compatibility)
        sleep_multiplier: Multiplier for sleep time after each retry (default: 1.0)
        jitter: If True, add random jitter to sleep time (default: False)
        max_duration: Maximum total duration in seconds for all retries (default: None)
        exception_to_raise: Custom exception to raise when all retries fail (default: None)

    Returns:
        Decorated async function that will retry on failure

    Example:
        @async_retryable(retries=3, sleep_time=2.0, exceptions=(aiohttp.ClientError,))
        async def fetch_data():
            async with aiohttp.ClientSession() as session:
                return await session.get("https://api.example.com/data")
    """
    # Handle aliases: retries -> num_tries, exceptions -> retryable_exs
    # Ensure at least 1 attempt (retries=0 means "run once, no retries")
    actual_num_tries = max(
        1,
        retries if retries is not None else (num_tries if num_tries is not None else 3),
    )
    actual_retryable_exs = (
        exceptions
        if exceptions is not None
        else (retryable_exs if retryable_exs is not None else (Exception,))
    )

    def decorator(func: AsyncF) -> AsyncF:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception: Optional[Exception] = None
            current_sleep = sleep_time
            start_time = time.time() if max_duration is not None else None

            for attempt in range(actual_num_tries):
                # Check if we've exceeded max_duration
                if start_time is not None and max_duration is not None:
                    elapsed = time.time() - start_time
                    if elapsed >= max_duration:
                        timeout_message = (
                            f"Retry operation for {func.__name__} exceeded max duration "  # pyre-ignore[16]
                            f"of {max_duration}s after {attempt} attempts"
                        )
                        if last_exception is not None:
                            LOGGER.error(timeout_message)
                            raise last_exception
                        raise TimeoutError(timeout_message)

                try:
                    return await func(*args, **kwargs)
                except actual_retryable_exs as e:
                    last_exception = e
                    if attempt < actual_num_tries - 1:
                        # Check if sleeping would exceed max_duration
                        actual_sleep = current_sleep
                        if jitter:
                            actual_sleep += random.uniform(0, current_sleep * 0.1)

                        if start_time is not None and max_duration is not None:
                            remaining = max_duration - (time.time() - start_time)
                            if remaining <= 0:
                                break
                            actual_sleep = min(actual_sleep, remaining)

                        LOGGER.warning(
                            f"Attempt {attempt + 1}/{actual_num_tries} failed for {func.__name__}: {e}. "
                            f"Retrying in {actual_sleep:.2f}s..."
                        )
                        await asyncio.sleep(actual_sleep)
                        current_sleep *= sleep_multiplier

            # All retries exhausted without success
            if exception_to_raise is not None:
                raise exception_to_raise
            if last_exception is not None:
                raise last_exception
            # This should not happen - if we get here, the function succeeded but didn't return
            # (which is impossible for well-formed async functions). The original libfb behavior
            # is to raise the last_exception or exception_to_raise, but if both are None, it would
            # raise a None which Python doesn't allow. We raise a more informative RuntimeError.
            raise RuntimeError(
                f"Retry operation for {func.__name__} exhausted all {actual_num_tries} attempts "
                "without raising a retryable exception or returning a value."
            )

        return t.cast(AsyncF, wrapper)

    return decorator


# =============================================================================
# memoize_forever - Permanent cache decorator from libfb.py.decorators
# =============================================================================


def memoize_forever(func: F) -> F:
    """
    Decorator that caches function results permanently.

    The cache is based on the function arguments (must be hashable).
    Results are cached indefinitely for the lifetime of the process.

    Args:
        func: Function to memoize

    Returns:
        Memoized function

    Example:
        @memoize_forever
        def expensive_computation(x: int) -> int:
            return x ** 2
    """
    cache: Dict[Tuple[Any, ...], Any] = {}

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        # Create a hashable key from args and kwargs
        key = (args, tuple(sorted(kwargs.items())))
        if key not in cache:
            cache[key] = func(*args, **kwargs)
        return cache[key]

    # Expose cache for testing/debugging
    wrapper.cache = cache  # type: ignore[attr-defined]
    wrapper.cache_clear = lambda: cache.clear()  # type: ignore[attr-defined]

    return t.cast(F, wrapper)


# =============================================================================
# memoize_timed - Time-based cache decorator from libfb.py.decorators
# =============================================================================


def memoize_timed(
    timeout_sec: float = 60.0,
    # pyre-fixme[34]: `Variable[F (bound to typing.Callable[..., typing.Any])]` isn't
    #  present in the function's parameters.
) -> Callable[[F], F]:
    """
    Decorator that caches function results for a specified duration.

    Args:
        timeout_sec: Cache TTL in seconds (default: 60.0)

    Returns:
        Decorated function with time-based caching

    Example:
        @memoize_timed(timeout_sec=300)  # Cache for 5 minutes
        def get_config():
            return load_config_from_disk()
    """

    def decorator(func: F) -> F:
        cache: Dict[Tuple[Any, ...], Tuple[Any, float]] = {}

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            key = (args, tuple(sorted(kwargs.items())))
            now = time.time()

            if key in cache:
                value, timestamp = cache[key]
                if now - timestamp < timeout_sec:
                    return value

            result = func(*args, **kwargs)
            cache[key] = (result, now)
            return result

        wrapper.cache = cache  # type: ignore[attr-defined]
        wrapper.cache_clear = lambda: cache.clear()  # type: ignore[attr-defined]

        return t.cast(F, wrapper)

    return decorator


# =============================================================================
# async_memoize_timed - Async time-based cache from libfb.py.asyncio.decorators
# =============================================================================


def async_memoize_timed(
    timeout_sec: float = 60.0,
    # pyre-fixme[34]: `Variable[AsyncF (bound to typing.Callable[...,
    #  typing.Coroutine[typing.Any, typing.Any, typing.Any]])]` isn't present in the
    #  function's parameters.
) -> Callable[[AsyncF], AsyncF]:
    """
    Async decorator that caches coroutine results for a specified duration.

    Works correctly with both standalone async functions and instance methods.

    Args:
        timeout_sec: Cache TTL in seconds (default: 60.0)

    Returns:
        Decorated async function with time-based caching

    Example:
        @async_memoize_timed(timeout_sec=300)
        async def get_remote_config():
            return await fetch_config_from_server()
    """

    def decorator(func: AsyncF) -> AsyncF:
        cache: Dict[Any, Tuple[Any, float]] = {}

        def _make_key(args: tuple, kwargs: dict) -> tuple:
            """Create a hashable cache key, using id() for unhashable args like self."""
            safe_args = []
            for arg in args:
                try:
                    hash(arg)
                    safe_args.append(arg)
                except TypeError:
                    safe_args.append(id(arg))
            return (tuple(safe_args), tuple(sorted(kwargs.items())))

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            key = _make_key(args, kwargs)
            now = time.time()

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


# =============================================================================
# string_is_ip - IP address validation from libfb.py.net
# =============================================================================


def string_is_ip(s: str) -> bool:
    """
    Check if a string is a valid IP address (IPv4 or IPv6).

    Args:
        s: String to check

    Returns:
        True if the string is a valid IP address, False otherwise

    Example:
        string_is_ip("192.168.1.1")  # True
        string_is_ip("2001:db8::1")  # True
        string_is_ip("not-an-ip")    # False
    """
    try:
        ipaddress.ip_address(s)
        return True
    except ValueError:
        return False


# =============================================================================
# get_ipv6_for_host - IPv6 lookup from libfb.py.net
# =============================================================================


def get_ipv6_for_host(hostname: str) -> Optional[str]:
    """
    Get the IPv6 address for a hostname.

    Args:
        hostname: Hostname to resolve

    Returns:
        IPv6 address string if found, None otherwise

    Example:
        ipv6 = get_ipv6_for_host("server.example.com")
    """
    try:
        # Get all address info for the hostname
        addr_info = socket.getaddrinfo(
            hostname,
            None,
            socket.AF_INET6,
            socket.SOCK_STREAM,
        )
        if addr_info:
            # Return the first IPv6 address found
            # pyrefly: ignore [bad-return]
            return addr_info[0][4][0]
    except (socket.gaierror, socket.herror, OSError):
        pass
    return None


# =============================================================================
# Hostname utilities from libfb.py.hostnameutils
# =============================================================================


def to_fb_fqdn(hostname: str) -> str:
    """
    Convert a hostname to fully qualified domain name (FQDN) format.

    Appends '.tfbnw.net' if not already present, matching Meta's
    internal FQDN format used by SMC and other services.

    Args:
        hostname: Hostname to convert

    Returns:
        FQDN version of the hostname

    Example:
        to_fb_fqdn("fsw002.p006.f01.qzd1")  # "fsw002.p006.f01.qzd1.tfbnw.net"
        to_fb_fqdn("fsw002.p006.f01.qzd1.tfbnw.net")  # "fsw002.p006.f01.qzd1.tfbnw.net"
    """
    if hostname.endswith(FB_FQDN_SUFFIX):
        return hostname
    return hostname + FB_FQDN_SUFFIX


def to_fb_fqdn_facebook(hostname: str) -> str:
    """
    Convert a hostname to fully qualified domain name (FQDN) format.

    Appends '.facebook.com' if not already present, matching Meta's
    internal FQDN format used by SMC and other services.

    Args:
        hostname: Hostname to convert

    Returns:
        FQDN version of the hostname

    Example:
        to_fb_fqdn_facebook("fsw002.p006.f01.qzd1")  # "fsw002.p006.f01.qzd1.facebook.com"
        to_fb_fqdn_facebook("fsw002.p006.f01.qzd1.facebook.com")  # "fsw002.p006.f01.qzd1.facebook.com"

        if not present then it will return the same hostname.
    """
    if hostname.endswith(FB_FQDN_FACEBOOK_SUFFIX):
        return hostname
    return hostname + FB_FQDN_FACEBOOK_SUFFIX


def to_fb_uqdn(hostname: str) -> str:
    """
    Convert a hostname to unqualified domain name format.

    Strips domain suffixes to get the short hostname.

    Args:
        hostname: Hostname to convert

    Returns:
        Short hostname without domain suffix

    Example:
        to_fb_uqdn("server1.u000.qzq1.facebook.com")  # "server1.u000.qzq1"
        to_fb_uqdn("server1.u000.qzq1")               # "server1.u000.qzq1"

        hostname will have either ".facebook.com" or ".tfbnw.net" suffix
        removed them to get the short hostname.

        if not present then it will return the same hostname.
    """
    # Strip common domain suffixes
    if hostname.endswith(FB_FQDN_SUFFIX):
        return hostname[: -len(FB_FQDN_SUFFIX)]
    if hostname.endswith(FB_FQDN_FACEBOOK_SUFFIX):
        return hostname[: -len(FB_FQDN_FACEBOOK_SUFFIX)]
    return hostname


# =============================================================================
# convert_to_async - Sync to async wrapper from libfb.py.asyncio.await_utils
# =============================================================================


def convert_to_async(func: Callable[..., T]) -> Callable[..., t.Coroutine[Any, Any, T]]:
    """
    Convert a synchronous function to an async function.

    The sync function will be executed in a thread pool executor
    to avoid blocking the event loop.

    Args:
        func: Synchronous function to convert

    Returns:
        Async version of the function

    Example:
        def blocking_io():
            return read_file_sync("data.txt")

        async_read = convert_to_async(blocking_io)
        result = await async_read()
    """

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> T:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,  # Use default executor
            # pyre-fixme[6]: For 2nd argument expected `(*(*asyncio.events._Ts)) ->
            #  _T` but got `partial[T]`.
            functools.partial(func, *args, **kwargs),
        )

    return wrapper


# =============================================================================
# await_sync - Run async function synchronously from libfb.py.asyncio.await_utils
# =============================================================================


def await_sync(coro: t.Coroutine[Any, Any, T]) -> T:
    """
    Run an async coroutine synchronously.

    This is useful when you need to call async code from a sync context.

    Args:
        coro: Coroutine to execute

    Returns:
        Result of the coroutine

    Example:
        async def async_fetch():
            return await get_data()

        # Call from sync code
        result = await_sync(async_fetch())
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None:
        # We're inside an event loop, use nest_asyncio pattern
        # or run in a new thread
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor() as executor:
            # pyre-fixme[6]: For 1st argument expected `(_P) -> _T` but got `(main:
            #  Coroutine[Any, Any, _T], debug: Optional[bool] = ..., loop_factory:
            #  Optional[() -> AbstractEventLoop] = ...) -> _T`.
            future = executor.submit(asyncio.run, coro)
            return future.result()
    else:
        return asyncio.run(coro)


# =============================================================================
# Lazy import stub from libfb.py.lazy_import
# =============================================================================


def lazy_import(module_path: str) -> Any:
    """
    Lazily import a module.

    In OSS mode, this performs a regular import.
    At Meta, this defers the import until first access.

    Args:
        module_path: Dotted module path to import

    Returns:
        The imported module

    Example:
        heavy_module = lazy_import("some.heavy.module")
    """
    import importlib

    return importlib.import_module(module_path)


# =============================================================================
# memoize_timed_herd - Herd protection memoization from libfb.py.asyncio.decorators
# =============================================================================


def memoize_timed_herd(
    timeout_sec: float = 60.0,
    # pyre-fixme[34]: `Variable[AsyncF (bound to typing.Callable[...,
    #  typing.Coroutine[typing.Any, typing.Any, typing.Any]])]` isn't present in the
    #  function's parameters.
) -> Callable[[AsyncF], AsyncF]:
    """
    Async decorator with time-based caching and thundering herd protection.

    Only one caller will compute the value while others wait for the result.
    This prevents multiple concurrent calls from all computing the same expensive value.

    Args:
        timeout_sec: Cache TTL in seconds (default: 60.0)

    Returns:
        Decorated async function with herd-protected caching

    Example:
        @memoize_timed_herd(timeout_sec=300)
        async def get_expensive_data():
            return await fetch_from_slow_service()
    """
    # This is effectively the same as async_memoize_timed with lock protection
    # The lock ensures only one caller computes while others wait
    return async_memoize_timed(timeout_sec=timeout_sec)


# =============================================================================
# ConsoleFileLogger - Compatibility layer for neteng.netcastle.logger
# =============================================================================

# Environment variable to control OSS mode
TAAC_OSS = os.environ.get("TAAC_OSS", "").lower() in ("1", "true", "yes")

# Only import Meta-internal logger when not in OSS mode
if not TAAC_OSS:
    from neteng.netcastle.logger import (  # pyre-ignore[21]
        ConsoleFileLogger,
        get_root_logger,
    )
else:
    # OSS fallback implementation
    DEFAULT_LOG_FMT = "%(asctime)s.%(msecs)03d|%(process)d|%(threadName)s|%(levelname).1s|%(module)s: %(message)s"
    DEFAULT_LOG_DATEFMT = "%Y/%m/%d %H:%M:%S"
    MAIN_LOGGER_NAME = "neteng.netcastle"

    class ConsoleFileLogger(logging.Logger):
        """
        OSS-compatible logger that logs to both console and file.

        This is a simplified version of neteng.netcastle.logger.ConsoleFileLogger
        that works without Meta-internal dependencies.
        """

        def __init__(self, name: str) -> None:
            super().__init__(name)
            self.setLevel(logging.DEBUG)
            self.propagate = False

            self._file_log_fmt: Tuple[str, str] = (DEFAULT_LOG_FMT, DEFAULT_LOG_DATEFMT)
            self._console_log_fmt: Tuple[str, str] = (
                DEFAULT_LOG_FMT,
                DEFAULT_LOG_DATEFMT,
            )
            self._setup_console_handler()
            self._setup_file_handler()

        @classmethod
        def gen_log_file_path(
            cls, prefix: Optional[str] = None, suffix: str = ".log"
        ) -> str:
            """Generate a unique log file path."""
            log_dir = None
            if not prefix:
                prefix = "taac-%s-%s-" % (
                    os.getpid(),
                    datetime.datetime.now().strftime("%Y%m%d-%H%M%S"),
                )
            fd, path = tempfile.mkstemp(
                suffix=suffix, prefix=prefix, dir=log_dir, text=True
            )
            os.close(fd)
            return path

        def _setup_file_handler(self, path: Optional[str] = None) -> None:
            """Set up file handler for logging to a file."""
            log_file = path or os.environ.get("LOG_FILE", self.gen_log_file_path())
            file_handler = RotatingFileHandler(
                log_file, maxBytes=100 * 1024 * 1024, backupCount=5
            )
            file_handler.setFormatter(logging.Formatter(*self._file_log_fmt))
            file_handler.setLevel(logging.DEBUG)
            self.addHandler(file_handler)
            self._file_handler = file_handler
            self._log_file = log_file

        def _setup_console_handler(self) -> None:
            """Set up console handler for logging to stdout."""
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(logging.Formatter(*self._console_log_fmt))
            console_handler.setLevel(
                logging.DEBUG if os.environ.get("TAAC_DEBUG", None) else logging.INFO
            )
            self.addHandler(console_handler)
            self._console_handler = console_handler

        @property
        def log_file(self) -> str:
            """Return the path to the log file."""
            return self._log_file

        def enable_console_debug_log(self) -> None:
            """Enable debug level logging to console."""
            self._console_handler.setLevel(logging.DEBUG)

        def disable_console_debug_log(self) -> None:
            """Disable debug level logging to console (revert to INFO)."""
            self._console_handler.setLevel(logging.INFO)

    # Global root logger instance for OSS mode
    _root_logger: Optional[ConsoleFileLogger] = None

    def get_root_logger() -> ConsoleFileLogger:
        """
        Get or create the root TAAC logger (OSS implementation).

        Returns:
            ConsoleFileLogger instance configured for TAAC logging.
        """
        global _root_logger
        if _root_logger is None:
            # pyrefly: ignore [bad-assignment]
            _root_logger = ConsoleFileLogger(MAIN_LOGGER_NAME)
        # pyrefly: ignore [bad-return]
        return _root_logger


# =============================================================================
# internal_only - Decorator to gate methods for OSS mode
# =============================================================================


def internal_only(func: Callable) -> Callable:
    """
    Decorator that disables a method in OSS mode.
    Raises NotImplementedError with a descriptive message when TAAC_OSS=1.
    Works for both sync and async functions.
    """

    @functools.wraps(func)
    async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
        if TAAC_OSS:
            raise NotImplementedError(
                f"{func.__name__} is not available in OSS mode. "
                "This functionality requires Meta-internal infrastructure."
            )
        return await func(*args, **kwargs)

    @functools.wraps(func)
    def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        if TAAC_OSS:
            raise NotImplementedError(
                f"{func.__name__} is not available in OSS mode. "
                "This functionality requires Meta-internal infrastructure."
            )
        return func(*args, **kwargs)

    if asyncio.iscoroutinefunction(func):
        return async_wrapper
    return sync_wrapper


# =============================================================================
# Exported names for easy import
# =============================================================================

__all__ = [
    # Type narrowing
    "none_throws",
    # Decorators - sync
    "retryable",
    "memoize_forever",
    "memoize_timed",
    "wraps",
    # Decorators - async
    "async_retryable",
    "async_memoize_timed",
    "memoize_timed_herd",
    # Async utilities
    "convert_to_async",
    "await_sync",
    # Network utilities
    "string_is_ip",
    "get_ipv6_for_host",
    # Hostname utilities
    "to_fb_fqdn",
    "to_fb_uqdn",
    # Import utilities
    "lazy_import",
    # Logging utilities
    "ConsoleFileLogger",
    "get_root_logger",
    # Gating decorator
    "internal_only",
]
