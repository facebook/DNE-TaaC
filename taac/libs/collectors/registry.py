#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""Module-level registry for long-lived collectors — OSS-safe primitives.

Extracted from ``taac/libs/fpf/fpf_collector_registry.py``. Holds the two
pieces of state a domain-agnostic collector consumer needs:

* A dict of registered collectors keyed by name — populated by whichever
  ``setup_task`` (or custom test handler) starts collectors for a given
  test config, consulted by health checks at check time, and cleared in
  teardown.
* The test-case start timestamp — set by the TAAC runner at the start of
  each playbook iteration, consulted by health checks to bound the
  default query window.

Meta's ``fpf_collector_registry`` re-exports these primitives + adds its own
FPF-specific state (disruption effectiveness, baseline-impaired lanes, the
3-signal evaluator). ``clear_all()`` on the FPF side calls into ``clear_collectors()``
here to reset the shared state.
"""

import typing as t


_collectors: t.Dict[str, t.Any] = {}
_test_case_start_time: float = 0.0


def register_collector(name: str, collector: t.Any) -> None:
    """Register ``collector`` under ``name``. Overwrites an existing entry
    silently — collector names are singletons within a test-config run."""
    _collectors[name] = collector


def get_collector(name: str) -> t.Optional[t.Any]:
    """Return the collector registered under ``name``, or ``None`` if not present.

    Health checks should treat ``None`` as ``SKIP`` (the collector wasn't
    started for this test config), not as a failure."""
    return _collectors.get(name)


def host_key(name: str, host: str) -> str:
    """Registry key for ``name``'s collector on ``host``.

    One flat slot per collector name only ever holds one host's samples, so
    on a multi-node topology every device but the registrant's got SKIPped.
    Qualifying the key by host gives each node its own slot while leaving the
    unqualified name free for single-host registrants (the FPF collectors)."""
    return f"{name}@{host}"


def get_collector_for_host(name: str, host: str) -> t.Optional[t.Any]:
    """Return ``host``'s collector for ``name``, or ``None``.

    Prefers the host-qualified slot. Falls back to the unqualified one only
    when it is actually bound to ``host`` -- a collector registered flat by
    some other producer is still usable by the device it polls, but must not
    be handed to a check running against a different device."""
    collector = _collectors.get(host_key(name, host))
    if collector is not None:
        return collector
    collector = _collectors.get(name)
    if collector is not None and getattr(collector, "host", None) == host:
        return collector
    return None


def unregister_collector(name: str) -> None:
    """Drop the entry under ``name``, if any. A no-op when absent.

    Preferred over ``clear_collectors()`` for a handler's own teardown: the
    registry is shared across handlers, so clearing it wholesale discards
    slots the caller never owned (and resets the runner's test-case start
    timestamp)."""
    _collectors.pop(name, None)


def get_all_collectors() -> t.Dict[str, t.Any]:
    """Snapshot copy of the registry — safe to iterate while mutating the source."""
    return dict(_collectors)


def clear_collectors() -> None:
    """Clear the registry + reset the test-case start timestamp.

    Called by test-config teardown. Does NOT stop any registered collector
    threads — the caller is responsible for awaiting each collector's
    ``stop()`` before invoking this."""
    global _test_case_start_time
    _collectors.clear()
    _test_case_start_time = 0.0


def set_test_case_start_time(ts: float) -> None:
    """Record the epoch timestamp at which the current playbook iteration started.

    Called by the TAAC runner at the beginning of each playbook iteration
    so health checks can bound their default query window to just this
    iteration's data (skipping the pre-iteration baseline)."""
    global _test_case_start_time
    _test_case_start_time = ts


def get_test_case_start_time() -> float:
    """Return the current playbook iteration's start timestamp, or ``0.0`` if
    unset. Health checks fall back to a ``lookback_sec`` window when this is
    unset."""
    return _test_case_start_time
