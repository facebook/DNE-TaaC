# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import asyncio
import getpass
import inspect
import logging
import os
import socket
import threading
import time
import typing as t
from dataclasses import asdict, is_dataclass
from datetime import datetime
from textwrap import wrap
from typing import Type

import pyjq
from neteng.test_infra.dne.taac.constants import TestDevice, TestResult
from taac.utils.oss_taac_lib_utils import (
    ConsoleFileLogger,
    get_root_logger,
    memoize_forever,
    wraps,
)
from taac.utils.taac_log_formatter import log_section
from taac.health_check.health_check import types as hc_types
from taac.test_as_a_config import types as taac_types
from tabulate import tabulate

LOGGER: ConsoleFileLogger = get_root_logger()
TAAC_OSS = os.environ.get("TAAC_OSS", "").lower() in ("1", "true", "yes")


def get_fburl(url: str) -> str:
    """Get a shortened FB URL. In OSS mode, returns the original URL.

    On any fburl service failure (notably ``fburl`` tier throttling), this
    falls back to returning the original ``url`` instead of raising. A cosmetic
    URL-shortening failure must never fail a test, so we route through libfb's
    ``get_fburl_with_fallback`` which catches ``FBUrlError``/``TooLongException``
    (and unexpected exceptions), logs a warning, and returns the original URL.
    """
    if TAAC_OSS:
        return url

    from libfb.py.fburl import get_fburl_with_fallback as _get_fburl_with_fallback

    return _get_fburl_with_fallback(url)


async def async_get_fburl(url: str) -> str:
    """Async version of get_fburl."""
    return get_fburl(url)


async def async_get_fburl_retry(
    url: str, attempts: int = 4, delay_sec: float = 0.75
) -> str:
    """``async_get_fburl`` that rides out transient fburl-tier throttling.

    ``get_fburl_with_fallback`` returns the ORIGINAL url on throttle/failure
    (it never raises), so a result equal to the input means shortening did not
    happen. When many checks shorten concurrently (e.g. a playbook with a dozen
    postchecks), the fburl tier throttles and callers get the long raw url back.
    Retry a few times with a short backoff before giving up and returning the
    raw url. Best-effort: a cosmetic link must never fail a check.
    """
    import asyncio

    short = url
    for i in range(max(1, attempts)):
        try:
            short = await async_get_fburl(url)
        except Exception:
            short = url
        if short and short != url:
            return short
        if i < attempts - 1:
            await asyncio.sleep(delay_sec)
    return short


async def async_log_to_file_oss(content: str, prefix: str = "taac") -> str:
    """
    OSS alternative for everpaste — writes content to a local file in /tmp.

    Args:
        content: The content to write to file.
        prefix: Prefix for the filename.

    Returns:
        Path to the created file.
    """
    import hashlib
    import tempfile

    content_hash = hashlib.sha256(content.encode()).hexdigest()[:12]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{prefix}_{timestamp}_{content_hash}.log"
    filepath = os.path.join(tempfile.gettempdir(), filename)

    with open(filepath, "w") as f:
        f.write(content)

    LOGGER.info(f"Content logged to: {filepath}")
    return filepath


async def async_everpaste_str(content: str, **kwargs) -> str:
    """Upload string to Everpaste. In OSS mode, writes to /tmp file.
    Accepts and ignores extra kwargs (color, etc.) for API compatibility."""
    if not TAAC_OSS:
        from neteng.netcastle.utils.everpaste_utils import (
            async_everpaste_str as _async_everpaste_str,
        )

        return await _async_everpaste_str(content, **kwargs)
    return await async_log_to_file_oss(content, prefix="taac_everpaste")


async def async_everpaste_if_needed(content: str, thres: int = 5000, **kwargs) -> str:
    """Upload to Everpaste only if content exceeds threshold.
    In OSS mode or if content is short, returns content as-is."""
    if not TAAC_OSS:
        from neteng.netcastle.utils.everpaste_utils import (
            async_everpaste_if_needed as _async_everpaste_if_needed,
        )

        return await _async_everpaste_if_needed(content, thres=thres, **kwargs)
    if len(content) > thres:
        return await async_log_to_file_oss(content, prefix="taac_everpaste")
    return content


def create_everpaste_fburl(data: str) -> t.Optional[str]:
    """
    Upload verbose ``data`` to Everpaste and return the (clickable) Everpaste URL.

    Despite the legacy name, this does NOT create an fburl: an Everpaste URL is
    already a short, clickable internalfb.com link, so routing it through the
    globally throttled ``fburl`` tier is unnecessary. The previous implementation
    passed ``use_fburl=``/``permanent=`` keyword arguments that the netcastle
    ``everpaste_str`` does not accept, which raised ``TypeError`` at runtime
    (the ``pyre-fixme[28]`` masked it). This mirrors the sibling helper in
    ``neteng/test_infra/dne/utils/common.py``.
    """
    if TAAC_OSS:
        return None

    from neteng.netcastle.utils.everpaste_utils import everpaste_str

    return everpaste_str(data)


async def async_everpaste_file(
    filepath: str = "",
    *,
    path: str = "",
    extension: str = "",
    logger: t.Optional[logging.Logger] = None,
) -> str:
    """Upload file to Everpaste (text) or Everstore (binary).

    In OSS mode, returns the local file path. For binary files (e.g. PNG
    images), uploads to Everstore (binary blob store) since Everpaste only
    handles text. Returns a handle in both cases.
    """
    resolved_path = path or filepath
    if not TAAC_OSS:
        # Check if file is binary. The downstream netcastle
        # async_everpaste_file opens in text mode ("r"), which raises
        # UnicodeDecodeError on binary files like PNG images.
        is_binary = False
        try:
            with open(resolved_path, "rb") as f:
                f.read().decode("utf-8")
        except UnicodeDecodeError:
            is_binary = True

        if is_binary:
            from neteng.netcastle.utils.everstore_utils import (
                async_everstore_file as _async_everstore_file,
            )

            return await _async_everstore_file(
                resolved_path,
                extension=extension or "bin",
                logger=logger,
            )

        from neteng.netcastle.utils.everpaste_utils import (
            async_everpaste_file as _async_everpaste_file,
        )

        return await _async_everpaste_file(resolved_path, logger=logger)
    LOGGER.info(f"OSS mode: Log file available at: {resolved_path}")
    return resolved_path


async def async_write_test_result(
    test_case_name: str,
    devices: t.List[TestDevice],
    start_time: float,
    message: t.Optional[str] = None,
    end_time: t.Optional[float] = None,
    check_name: t.Optional[str] = None,
    check_stage: t.Optional[taac_types.ValidationStage] = None,
    test_status: hc_types.HealthCheckStatus = hc_types.HealthCheckStatus.UNKNOWN,
) -> TestResult:
    start_time_str = datetime.fromtimestamp(start_time).strftime("%m/%d/%Y-%H:%M:%S")
    end_time_str = (
        datetime.fromtimestamp(end_time).strftime("%m/%d/%Y-%H:%M:%S")
        if end_time
        else datetime.now().strftime("%m/%d/%Y-%H:%M:%S")
    )
    formatted_message = None
    if message:
        if not TAAC_OSS:
            from taac.utils.common import (
                # pyrefly: ignore [missing-module-attribute]
                async_everpaste_if_needed as _everpaste_if_needed,
            )

            message = await _everpaste_if_needed(message, thres=1000)
        formatted_message = "\n".join(wrap(message))

    return TestResult(
        start_time=start_time_str,
        end_time=end_time_str,
        test_case_name="\n".join(wrap(test_case_name, width=50)),
        hostnames="\n".join(device.name for device in devices),
        platforms="\n".join(
            f"{device.name}: {device.attributes.hardware}" for device in devices
        ),
        check_name=check_name,
        check_stage=check_stage.name if check_stage else None,
        test_status=test_status.name,
        message=formatted_message,
    )


def highlight_text(
    text: str, header_width: int = 80, logger: ConsoleFileLogger = LOGGER
) -> None:
    """
    Used to print the text for better readability.
    Delegates to the centralized log_section formatter for consistent output.
    Args:
        text: string to print
        header_width: header width
    """
    log_section(text, logger=logger, width=header_width)


def get_session_info() -> t.Dict[str, str]:
    """
    Creates a dictionary of runner info (Group ID & Unixname).
    In OSS mode, returns a default group_id since Netcastle RunInfo is unavailable.
    """
    if TAAC_OSS:
        return {"group_id": "oss", "unixname": getpass.getuser()}

    from neteng.netcastle.run_info import RunInfo

    group_id: str = RunInfo().group_id
    unixname: str = getpass.getuser()
    return {"group_id": group_id, "unixname": unixname}


def timeit(callable: t.Callable):
    @wraps(callable)
    async def async_wrapper(*args, **kwargs):
        tstart = time.time()
        output = await callable(*args, **kwargs)
        tend = time.time()
        LOGGER.debug(
            '"{}" took {:.3f} ms to execute\n'.format(
                callable.__name__, (tend - tstart) * 1000
            )
        )
        return output

    def wrapper(*args, **kwargs):
        tstart = time.time()
        output = callable(*args, **kwargs)
        tend = time.time()
        LOGGER.debug(
            '"{}" took {:.3f} ms to execute\n'.format(
                callable.__name__, (tend - tstart) * 1000
            )
        )
        return output

    if inspect.iscoroutine(callable):
        return async_wrapper
    else:
        return wrapper


@memoize_forever
def pyjq_compile(script: str):
    return pyjq.compile(script)


def eval_jq(jq_expr: str, jq_vars: t.Dict[str, t.Any]) -> t.Any:
    jq_vals = pyjq_compile(jq_expr).apply(jq_vars)
    if not jq_vals:
        return None
    elif len(jq_vals) > 1:
        raise ValueError(f"Got unexpected result (need a single JSON value): {jq_vals}")
    return jq_vals[0]


def run_in_thread(func: t.Callable, *args, **kwargs) -> threading.Thread:
    """
    Runs a function in a separate thread.
    Args:
        func: The function to run.
        *args: Any positional arguments to pass to the function.
        **kwargs: Any keyword arguments to pass to the function.
    """
    callable = func
    if asyncio.iscoroutinefunction(func):
        # Create a wrapper to run the async function in an event loop
        def wrapper(*args, **kwargs):
            asyncio.run(func(*args, **kwargs))

        callable = wrapper
    thread = threading.Thread(target=callable, args=args, kwargs=kwargs)
    thread.start()
    return thread


def format_binary_ip(ip) -> str:
    family = socket.AF_INET if len(ip) == 4 else socket.AF_INET6
    return socket.inet_ntop(family, ip)


def async_custom_retry(
    max_attempts=5, delay_seconds=120, logger: ConsoleFileLogger = LOGGER
):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            for attempt in range(1, max_attempts + 1):
                try:
                    result = await func(*args, **kwargs)
                    logger.info(
                        f"Function <{func.__name__}> responded in attemp #{attempt}"
                    )
                    return result
                except Exception as e:
                    logger.info(f"Attempt {attempt} failed with error: {e}")
                    if attempt < max_attempts:
                        logger.info(f"Retrying in {delay_seconds} seconds...")
                        await asyncio.sleep(delay_seconds)
                    else:
                        logger.info("Max attempts reached. Giving up.")
                        raise

        return wrapper

    return decorator


def is_host_drainable(hostname: str) -> bool:
    """
    Checks if a host is drainable or not.
    Args:
        hostname (str): The hostname to check.
    Returns:
        bool: True if the host is drainable, False otherwise.
    """
    non_drainable_roles = {"rsw", "rtsw", "rdsw"}
    return not any(role in hostname for role in non_drainable_roles)


def get_default_configs(hostname: str) -> t.List[str]:
    return ["agent"] + get_default_bgp_configs(hostname)


def get_default_bgp_configs(hostname: str) -> t.List[str]:
    if is_host_drainable(hostname):
        return ["bgpcpp", "bgpcpp_drain", "bgpcpp_softdrain"]
    return ["bgpcpp"]


T = t.TypeVar("T")


def is_overridden(cls: Type[T], parent_cls: Type[T], func_name: str) -> bool:
    """
    Determine if a method or function is overridden in a child class compared to a parent class.
    This function checks whether the method named `func_name` is defined directly in `cls` and
    whether it is different from the implementation in `parent_cls`. This is useful for confirming
    that a child class provides its own implementation of a method that exists in the parent class.
    Args:
        cls (Type[T]): The child class to check for an override.
        parent_cls (Type[T]): The parent class to compare against.
        func_name (str): The name of the method or function to check.
    Returns:
        bool: True if `cls` overrides `func_name` from `parent_cls`, False otherwise.
    Example:
        class Parent:
            def foo(self): pass
        class Child(Parent):
            def foo(self): pass
        is_overridden(Child, Parent, 'foo')  # True
        is_overridden(Parent, Parent, 'foo') # False
    """
    if func_name not in cls.__dict__:
        return False
    if not hasattr(parent_cls, func_name):
        return True  # Parent doesn't have it, so child's is new
    return cls.__dict__[func_name] is not parent_cls.__dict__.get(func_name)


def transpose(matrix: list) -> list:
    return [list(row) for row in zip(*matrix)]


def _get_test_case_header(test_results: t.List) -> t.List[str]:
    if not is_dataclass(test_results) and not len(test_results):
        raise ValueError(
            "Given test results is not of the type of dataclass. Please check!"
        )
    # pyre-fixme[16]: Item `DataclassInstance` of `List[Any] | DataclassInstance`
    #  has no attribute `__getitem__`.
    return [field_name.upper() for field_name in asdict(test_results[0])]


def tabulate_test_results(
    test_results: t.List,
    no_header: bool = False,
) -> str:
    """Tabulate test results from a list of dataclasses."""
    test_result_header: t.List[str] = _get_test_case_header(test_results)
    test_result_data: t.List[t.List] = [
        [value or "" for value in asdict(test_result).values()]
        for test_result in test_results
    ]
    if no_header:
        return tabulate(test_result_data, tablefmt="grid")
    return tabulate(test_result_data, headers=test_result_header, tablefmt="grid")
