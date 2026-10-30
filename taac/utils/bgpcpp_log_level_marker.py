# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict
"""One greppable run-log line per BGP++ log-level change.

BGP++ verbosity is set in two places: the ``LOGGING=`` startup flag that TAAC
writes into ``run_bgpcpp.sh`` during setup, and live ``setLogLevel`` category
overrides. Neither leaves a readable trace in the run log, so a failure cannot
be matched to the verbosity the DUT was logging at. Each change records the
host's current pair and returns::

    BGPCPP_LOG_LEVEL host=<host> configured='<startup level>' runtime_override='<categories>'
"""

from __future__ import annotations

MARKER: str = "BGPCPP_LOG_LEVEL"

_configured: dict[str, str] = {}
_runtime_override: dict[str, str] = {}


def record_configured(hostname: str, logging_config: str) -> str:
    """Record a new startup level and return its marker line.

    The startup level only takes effect on the BGP++ restart that follows, and
    that restart drops any live category overrides, so they are cleared here.
    """
    _configured[hostname] = logging_config
    _runtime_override.pop(hostname, None)
    return marker_line(hostname)


def record_runtime_override(hostname: str, level_string: str) -> str:
    """Record a live ``setLogLevel`` override and return its marker line."""
    _runtime_override[hostname] = level_string
    return marker_line(hostname)


def marker_line(hostname: str) -> str:
    configured = _configured.get(hostname, "unknown")
    runtime_override = _runtime_override.get(hostname, "none")
    return (
        f"{MARKER} host={hostname} configured='{configured}' "
        f"runtime_override='{runtime_override}'"
    )
