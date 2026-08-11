#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""Continuous systemd-unit-state collector for OSS FBOSS DUTs.

Polls the standard set of systemd unit properties every ``interval_sec``
seconds and stores a per-poll snapshot per service. Multiple health checks
consume this shared timeline instead of each running its own per-service SSH
at postcheck time:

* ``UncleanExitHealthCheck`` — flags any sample whose ``Result`` is in
  ``_UNCLEAN_SYSTEMD_RESULTS`` (core-dump/signal/watchdog/timeout/oom-kill)
  or whose ``ActiveState`` reached ``failed``. Closes the crash-then-recover
  blindspot of one-shot postchecks: systemd's ``Result`` reflects the *last*
  run only, so a service that crashed and was auto-restarted reports
  ``Result=success`` when the postcheck reads it — a periodic sample can
  catch the crash before the restart overwrites it.
* Future consumers (``SystemctlActiveStateHealthCheck``,
  ``ServiceRestartHealthCheck``) use the same samples for
  window-based verdicts without adding more SSH.

Properties polled (matches all three checks' combined needs):

* ``Id`` — required for the base class's block-to-unit matching.
* ``LoadState`` / ``ActiveState`` / ``UnitFileState`` — is-active check.
* ``Result`` — unclean-exit detection.
* ``ActiveEnterTimestamp`` / ``NRestarts`` — service-restart detection.

Usage (started by ``CollectorsTestHandler``, consumed by a postcheck):

    collector = SystemdStateCollector(
        driver=dut_driver,
        services=DEFAULT_SERVICE_NAMES,
        host=dut.name,
        interval_sec=5.0,
    )
    collector.start()
    register_collector("systemd_state", collector)
    ...  # test runs
    unclean = collector.unclean_samples_in_window(window_start, window_end)
    # [("bgpd", "2026-07-31 22:56:18.423-0700", "core-dump"), ...]
"""

import logging
import os
import time
import typing as t
from dataclasses import dataclass, field

from taac.libs.collectors.service_polling_collector import ServicePollingCollector


logger = logging.getLogger(__name__)


# systemd ``Result`` values that mean the unit's last run terminated abnormally.
# Mirrors ``UncleanExitHealthCheck._UNCLEAN_SYSTEMD_RESULTS`` — kept in sync there.
UNCLEAN_SYSTEMD_RESULTS: t.FrozenSet[str] = frozenset(
    {"core-dump", "signal", "watchdog", "timeout", "oom-kill"}
)


@dataclass
class SystemdUnitState:
    """One systemd unit's state at a single poll cycle.

    ``None`` on any field means the property wasn't reported (unit not loaded,
    inactive, ssh-error, or systemd didn't emit the property for that unit
    type). Consumers should treat ``None`` as "no signal from this poll" and
    fall through to the next sample rather than as evidence of a state change.
    """

    load_state: t.Optional[str] = None
    active_state: t.Optional[str] = None
    result: t.Optional[str] = None
    unit_file_state: t.Optional[str] = None
    active_enter_ts: t.Optional[int] = None
    n_restarts: t.Optional[int] = None

    @property
    def is_unclean(self) -> bool:
        """Whether this sample reflects an abnormal termination.

        Two independent signals: ``Result`` in the unclean set (catches
        core-dump/signal/watchdog/timeout/oom-kill even if the unit was
        auto-restarted afterward and the *next* sample looks healthy), and
        ``ActiveState=failed`` (catches a unit that hasn't yet had its
        result classified — a failure-in-flight).
        """
        if self.result in UNCLEAN_SYSTEMD_RESULTS:
            return True
        if self.active_state == "failed":
            return True
        return False


@dataclass
class SystemdStateSample:
    """One collector row — every monitored service's ``SystemdUnitState`` at a
    single point in time. ``per_service`` maps service name to its state; a
    missing service means the poll couldn't classify it (unloaded / ssh-error /
    parse-failure), NOT that it's healthy."""

    timestamp: str
    epoch: float
    per_service: t.Dict[str, SystemdUnitState] = field(default_factory=dict)
    notes: str = ""


class SystemdStateCollector(ServicePollingCollector):
    """Polls systemd unit properties via SSH once per interval, records one
    ``SystemdUnitState`` per service per poll.

    Inherits the batched-SSH poll loop, ``Id``-keyed block matching, and
    window queries from ``ServicePollingCollector``. Overrides only the
    per-property extraction (``_extract_value``) and the sample dataclass
    (``_make_sample``) — no stateful transform, no delta computation.
    """

    # State transitions ARE the signal here — an inactive/failed unit is
    # exactly what UncleanExitHealthCheck and (future)
    # SystemctlActiveStateHealthCheck / ServiceRestartHealthCheck need to
    # see. Disable the base's active-only filter so ``_extract_value`` runs
    # for every polled unit regardless of ActiveState.
    _SKIP_INACTIVE_UNITS: t.ClassVar[bool] = False

    def __init__(
        self,
        driver: t.Any,
        services: t.Sequence[str],
        host: str,
        tmp_path: t.Optional[str] = None,
        interval_sec: float = 5.0,
    ) -> None:
        if tmp_path is None:
            tmp_path = (
                f"/tmp/systemd_state_collector.{os.getpid()}.{int(time.time())}.log"
            )
        super().__init__(
            driver=driver,
            services=services,
            host=host,
            tmp_path=tmp_path,
            interval_sec=interval_sec,
        )
        self.rows: t.List[SystemdStateSample] = []

    def _systemd_properties(self) -> t.List[str]:
        # The monotonic variant of ActiveEnterTimestamp is what we actually
        # read (see _extract_value); request both so we always get a numeric
        # form regardless of what systemd emits by default on this DUT image.
        return [
            "LoadState",
            "ActiveState",
            "Result",
            "UnitFileState",
            "ActiveEnterTimestamp",
            "ActiveEnterTimestampMonotonic",
            "NRestarts",
        ]

    def _extract_value(
        self, unit_data: t.Dict[str, str], service: str
    ) -> t.Optional[SystemdUnitState]:
        """Turn one ``systemctl show`` block into a ``SystemdUnitState``.

        The base class already filters unloaded/inactive units to ``None``
        before this runs; getting here means the unit is loaded + active,
        so ``load_state`` / ``active_state`` will always be set. ``Result`` is
        populated for all units (systemd emits ``Result=success`` for a
        healthy unit); ``NRestarts`` / ``ActiveEnterTimestamp`` may be absent
        on very old systemd but present on everything we run.
        """
        # ActiveEnterTimestamp is emitted as a human-readable string
        # (``Sun 2026-07-13 15:22:34 UTC``) by default, but the monotonic
        # ``-usec`` variant is a plain integer that's cheap to diff for
        # restart detection. Prefer it; fall back to nothing if absent.
        aet_raw = unit_data.get("ActiveEnterTimestampMonotonic", "")
        aet: t.Optional[int] = int(aet_raw) if aet_raw.isdigit() else None
        n_restarts_raw = unit_data.get("NRestarts", "")
        n_restarts: t.Optional[int] = (
            int(n_restarts_raw) if n_restarts_raw.isdigit() else None
        )
        return SystemdUnitState(
            load_state=unit_data.get("LoadState") or None,
            active_state=unit_data.get("ActiveState") or None,
            result=unit_data.get("Result") or None,
            unit_file_state=unit_data.get("UnitFileState") or None,
            active_enter_ts=aet,
            n_restarts=n_restarts,
        )

    def _format_value(self, value: t.Any) -> str:
        if not isinstance(value, SystemdUnitState):
            return str(value)
        # One tight column per service — the .log stays scannable when many
        # services are monitored. Compact form: active_state|result|nrestarts.
        active = value.active_state or "?"
        result = value.result or "?"
        nrestarts = value.n_restarts if value.n_restarts is not None else "?"
        return f"{active}|{result}|{nrestarts}"

    def _make_sample(
        self,
        timestamp: str,
        epoch: float,
        per_service: t.Dict[str, t.Any],
        notes: str,
    ) -> SystemdStateSample:
        return SystemdStateSample(
            timestamp=timestamp, epoch=epoch, per_service=per_service, notes=notes
        )

    # -- Domain query APIs -------------------------------------------------

    def unclean_samples_in_window(
        self,
        window_start: float,
        window_end: float,
        services: t.Optional[t.Sequence[str]] = None,
    ) -> t.List[t.Tuple[str, str, str]]:
        """Return ``[(service, timestamp, reason), ...]`` for every poll in the
        window where a monitored service's sample was ``is_unclean``.

        ``reason`` is either the ``Result`` value (core-dump / signal / ...) or
        the literal ``"active-state:failed"`` when only the failed-state signal
        fired. Restricted to ``services`` if given, else every service the
        collector polls. Order preserves poll order.
        """
        wanted = set(services) if services is not None else set(self.services)
        rows = self.get_rows_in_window(window_start, window_end)
        results: t.List[t.Tuple[str, str, str]] = []
        for row in rows:
            for service, state in row.per_service.items():
                if service not in wanted:
                    continue
                if not isinstance(state, SystemdUnitState):
                    continue
                if not state.is_unclean:
                    continue
                if state.result in UNCLEAN_SYSTEMD_RESULTS:
                    reason = state.result
                else:
                    reason = "active-state:failed"
                results.append((service, row.timestamp, reason))
        return results

    def services_ever_inactive_in_window(
        self,
        window_start: float,
        window_end: float,
        services: t.Optional[t.Sequence[str]] = None,
        skip_disabled: bool = True,
        skip_not_loaded: bool = True,
    ) -> t.Dict[str, str]:
        """Return ``{service: first_non_active_state}`` for services whose
        ``ActiveState`` was not ``active`` at any sample in the window.

        ``skip_disabled=True`` (default): a service whose ``UnitFileState``
        is ``disabled`` on any sample is omitted — an intentionally-disabled
        unit is not an outage. ``skip_not_loaded=True`` (default): a service
        whose ``LoadState`` is ``not-loaded`` / ``not-found`` on any sample
        is omitted — the unit isn't present on this DUT image at all, so
        there's nothing to check. Both match the semantics
        ``SystemctlActiveStateHealthCheck``'s legacy per-service SSH path
        used; a caller wanting stricter checking can flip either flag off.
        """
        # The filters below decide sample-by-sample, not once-per-service:
        # a monitored unit can be disabled/not-loaded at one poll and
        # loaded/active at another (e.g. brought up mid-playbook, or an
        # unrelated ``daemon-reload`` transient), and we must not let a
        # single skip-worthy sample erase an outage recorded from a
        # loaded+enabled one. This is a regression an earlier iteration
        # of this method introduced (skip-set + ``first_bad.pop(...)``)
        # and the review caught: a real ``failed`` sample at t=1 followed
        # by a not-loaded sample at t=3 silently returned an empty dict.
        wanted = set(services) if services is not None else set(self.services)
        rows = self.get_rows_in_window(window_start, window_end)
        first_bad: t.Dict[str, str] = {}
        for row in rows:
            for service, state in row.per_service.items():
                if service not in wanted or service in first_bad:
                    continue
                if not isinstance(state, SystemdUnitState):
                    continue
                if skip_disabled and state.unit_file_state == "disabled":
                    continue
                if (
                    skip_not_loaded
                    and state.load_state
                    and state.load_state != "loaded"
                ):
                    continue
                if state.active_state and state.active_state != "active":
                    first_bad[service] = state.active_state
        return first_bad

    def services_not_active_at_end(
        self,
        window_start: float,
        window_end: float,
        services: t.Optional[t.Sequence[str]] = None,
    ) -> t.Dict[str, str]:
        """Return ``{service: final_active_state}`` for services whose *last*
        in-window sample shows a non-``active`` state.

        Complements ``services_ever_inactive_in_window``: that method surfaces
        any transient outage during the window; this one only surfaces
        services that didn't finish the window active. Used by checks that
        allow-list an intentional restart — the transient
        ``deactivating`` / ``activating`` states of the restarted service are
        expected and must not FAIL, but the check still needs to verify
        recovery. A disabled / not-loaded final sample is skipped (nothing
        to verify recovery to)."""
        wanted = set(services) if services is not None else set(self.services)
        rows = self.get_rows_in_window(window_start, window_end)
        # Walk the samples once, keeping the last SystemdUnitState per
        # service; a later sample overwrites an earlier one.
        last_seen: t.Dict[str, SystemdUnitState] = {}
        for row in rows:
            for service, state in row.per_service.items():
                if service not in wanted:
                    continue
                if not isinstance(state, SystemdUnitState):
                    continue
                last_seen[service] = state
        result: t.Dict[str, str] = {}
        for service, state in last_seen.items():
            if state.unit_file_state == "disabled":
                continue
            if state.load_state and state.load_state != "loaded":
                continue
            if state.active_state and state.active_state != "active":
                result[service] = state.active_state
        return result

    def services_restarted_in_window(
        self,
        window_start: float,
        window_end: float,
        services: t.Optional[t.Sequence[str]] = None,
        skip_disabled: bool = True,
        skip_not_loaded: bool = True,
    ) -> t.Dict[str, t.Tuple[int, int]]:
        """Return ``{service: (n_restarts_delta, active_enter_ts_changes)}``
        for services whose restart-indicating fields changed across the window.

        A restart shows as either an ``NRestarts`` bump (systemd's own
        counter) or an ``ActiveEnterTimestampMonotonic`` change (the unit's
        activation moment moved). Either signal alone is sufficient; both
        are tracked so a consumer can distinguish "clean restart" (NRestarts
        bumped) from "warmboot-style re-init" (ActiveEnterTimestamp changed
        without NRestarts, seen in some FBOSS paths).

        ``skip_disabled=True`` (default): omit services that sampled as
        ``UnitFileState=disabled`` — a disabled unit can't be running to
        restart. ``skip_not_loaded=True`` (default): omit services that
        sampled as ``LoadState`` != ``loaded`` — the unit isn't present on
        this DUT image. Both match the semantics ``ServiceRestartHealthCheck``
        wants; a stricter caller can flip either off.
        """
        # Filters decide per-sample, not per-service — mirrors the fix on
        # ``services_ever_inactive_in_window`` (see the comment there).
        # An early not-loaded or a late disabled sample must not veto
        # loaded+enabled samples on either side of it: a service brought
        # up mid-playbook (early sample = not-found) or torn down late
        # (late sample = disabled) still has its NRestarts / AET delta
        # computed from the loaded+enabled samples.
        wanted = set(services) if services is not None else set(self.services)
        rows = self.get_rows_in_window(window_start, window_end)
        first_seen: t.Dict[str, SystemdUnitState] = {}
        last_seen: t.Dict[str, SystemdUnitState] = {}
        for row in rows:
            for service, state in row.per_service.items():
                if service not in wanted:
                    continue
                if not isinstance(state, SystemdUnitState):
                    continue
                if skip_disabled and state.unit_file_state == "disabled":
                    continue
                if (
                    skip_not_loaded
                    and state.load_state
                    and state.load_state != "loaded"
                ):
                    continue
                if service not in first_seen:
                    first_seen[service] = state
                last_seen[service] = state
        result: t.Dict[str, t.Tuple[int, int]] = {}
        for service, last in last_seen.items():
            first = first_seen[service]
            n_delta = 0
            if first.n_restarts is not None and last.n_restarts is not None:
                n_delta = max(0, last.n_restarts - first.n_restarts)
            aet_changes = 0
            if (
                first.active_enter_ts is not None
                and last.active_enter_ts is not None
                and first.active_enter_ts != last.active_enter_ts
            ):
                aet_changes = 1
            if n_delta > 0 or aet_changes > 0:
                result[service] = (n_delta, aet_changes)
        return result
