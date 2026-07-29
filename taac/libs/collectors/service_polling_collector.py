#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""Intermediate base for collectors that poll systemd service properties via SSH.

Sits between ``BaseCollector`` (generic poll-loop / thread / file-IO) and
domain collectors (CPU, memory, ...).  Owns:

* ``driver`` / ``services`` / ``host`` init
* One batched ``systemctl show`` SSH call per poll cycle for all services
  (see ``_sample_all``) — a per-service SSH round trip does not scale with
  poll interval and service count and was observed to trip sshd's
  ``MaxStartups`` under load. Output blocks are matched back to their unit by
  the ``Id`` property, never by position.
* SSH error + not-measurable notes
* Per-poll file-write (``timestamp  val  val  ...  notes``)
* ``max_per_service_in_window`` / ``samples_per_service_in_window`` queries

Subclasses supply two hooks:

* ``_systemd_properties()`` — which ``-p`` properties to request
* ``_extract_value(unit_data, service)`` — parse the raw value out of the
  ``systemctl show`` key=value dict (return ``None`` if not measurable)

Optional hooks for stateful collectors (e.g. CPU delta computation):

* ``_format_value(value)`` — format for the .log column (default ``str``)
* ``_make_sample(timestamp, epoch, per_service, notes)`` — construct the
  domain-specific sample dataclass
* ``_transform_per_service(raw_per_service, poll_wall)`` — post-process the
  raw per-service values into what gets stored (e.g. CPU's ns-delta -> pct).
  A ``None`` raw value means "no sample this poll", which is where a stateful
  transform resets whatever per-service state it carries.
"""

import logging
import time
import typing as t
from dataclasses import dataclass, field
from datetime import datetime, timezone

from taac.libs.collectors.base_collector import BaseCollector, _now_str


logger = logging.getLogger(__name__)

# systemd reports this sentinel for counters that are unset/unavailable
# (e.g. CPUUsageNSec/MemoryCurrent on a unit with no cgroup accounting yet).
# It parses as a valid, enormous digit string, so it must be filtered
# explicitly or it becomes a guaranteed-FAIL "max" sample.
UNAVAILABLE_COUNTER_VALUE: int = (1 << 64) - 1


@dataclass
class ServicePollingSample:
    """Generic per-poll row. Subclasses may use their own dataclass via
    ``_make_sample``, but this default works for simple cases."""

    timestamp: str
    epoch: float
    per_service: t.Dict[str, t.Any] = field(default_factory=dict)
    notes: str = ""


class ServicePollingCollector(BaseCollector):
    """Polls systemd service properties via SSH, one row per poll cycle.

    Not instantiated directly — subclass and implement ``_systemd_properties``
    and ``_extract_value``.
    """

    def __init__(
        self,
        driver: t.Any,
        services: t.Sequence[str],
        host: str,
        tmp_path: str,
        interval_sec: float = 5.0,
    ) -> None:
        super().__init__(tmp_path, interval_sec)
        self.driver = driver
        self.services: t.List[str] = list(services)
        self.host = host
        self.rows: t.List = []

    # -- Subclass hooks (required) ------------------------------------------

    def _systemd_properties(self) -> t.List[str]:
        raise NotImplementedError

    def _extract_value(
        self, unit_data: t.Dict[str, str], service: str
    ) -> t.Any:
        raise NotImplementedError

    # -- Helpers for subclass hooks ------------------------------------------

    @staticmethod
    def _parse_counter(raw: str) -> t.Optional[int]:
        """Parse a systemd cumulative-counter property, or ``None`` if it holds
        no usable sample.

        Covers both unavailable forms: a non-numeric value (``''``,
        ``'[not set]'``) and ``UNAVAILABLE_COUNTER_VALUE``, which is numeric
        but means "unset" — treating it as a real sample would make it a
        guaranteed-FAIL "max".
        """
        if not raw.isdigit():
            return None
        value = int(raw)
        return None if value == UNAVAILABLE_COUNTER_VALUE else value

    # -- Subclass hooks (optional) ------------------------------------------

    def _format_value(self, value: t.Any) -> str:
        return str(value)

    def _make_sample(
        self,
        timestamp: str,
        epoch: float,
        per_service: t.Dict[str, t.Any],
        notes: str,
    ) -> t.Any:
        return ServicePollingSample(
            timestamp=timestamp, epoch=epoch, per_service=per_service, notes=notes
        )

    def _transform_per_service(
        self, raw_per_service: t.Dict[str, t.Any], poll_wall: float
    ) -> t.Dict[str, t.Any]:
        """Post-process raw per-service values before they're stored.

        Default is identity — override for stateful transforms (e.g. CPU's
        cumulative-ns-to-percent delta, which needs ``poll_wall`` and prior
        state). ``poll_wall`` is the wall-clock time captured just before
        this poll's SSH round trip, for consistent delta timing.
        """
        return raw_per_service

    # -- Shared implementation ----------------------------------------------

    def _write_header(self, f) -> None:
        cols = ["timestamp"] + list(self.services) + ["notes"]
        f.write("  ".join(cols) + "\n")

    @staticmethod
    def _parse_blocks_by_unit(output: str) -> t.Dict[str, t.Dict[str, str]]:
        """Parse ``systemctl show <unit>...`` output into ``{unit Id: props}``.

        Blocks are blank-line separated, but each is keyed by the ``Id`` it
        reports rather than by its position in the output. Position would be a
        silent-corruption risk: one extra or missing leading block (an echoed
        command, a warning line) would shift every unit by one and attribute
        one service's counters to another with no error anywhere.

        CRLF is normalized first. The OSS driver runs asyncssh ``conn.run()``
        with no ``term_type`` so it gets LF, but ``async_run_cmd_on_shell`` is
        overridden internally and a PTY-backed transport yields ``\\r\\n``,
        which would collapse the whole output into a single block and fail
        every ``Id`` lookup -- turning each poll into an all-services
        ssh-error rather than anything that looks like a parsing problem.
        """
        blocks_by_unit: t.Dict[str, t.Dict[str, str]] = {}
        for block in output.replace("\r\n", "\n").split("\n\n"):
            unit_data: t.Dict[str, str] = {}
            for line in block.split("\n"):
                key, sep, value = line.partition("=")
                if sep:
                    unit_data[key] = value
            unit_id = unit_data.get("Id")
            if unit_id:
                blocks_by_unit[unit_id] = unit_data
        return blocks_by_unit

    async def _sample_all(self) -> t.Tuple[t.Dict[str, t.Any], t.List[str]]:
        """One SSH call for all services, batched into a single ``systemctl
        show``. Returns (raw_per_service, notes)."""
        # "Id" is always requested so each block can be matched back to the
        # unit it describes -- see _parse_blocks_by_unit.
        props = ",".join(
            ["Id"] + [p for p in self._systemd_properties() if p != "Id"]
        )
        units = " ".join(self.services)
        raw_per_service: t.Dict[str, t.Any] = {}
        notes: t.List[str] = []

        try:
            # `or ""` because a driver may return None rather than raise (OSS
            # FbossSwitch.async_run_cmd_on_shell is `result.stdout if result
            # else None`). Without it the parse below raises AttributeError,
            # which _run_loop's generic handler swallows -- no row, no note,
            # just an unexplained gap in the .log. Empty output degrades to
            # "every unit missing" instead, i.e. per-service ssh-error notes.
            output = (
                await self.driver.async_run_cmd_on_shell(
                    f"systemctl show {units} -p {props} --no-page"
                )
                or ""
            )
        except Exception:
            for service in self.services:
                raw_per_service[service] = None
                notes.append(f"{service}=ssh-error")
            return raw_per_service, notes

        blocks_by_unit = self._parse_blocks_by_unit(output)
        for service in self.services:
            # systemd reports Id with the unit suffix applied ("bgpd" ->
            # "bgpd.service"), so accept the requested name either way.
            unit_data = blocks_by_unit.get(service) or blocks_by_unit.get(
                f"{service}.service"
            )
            if unit_data is None:
                # No block for this unit at all -- truncated or garbled output,
                # which says nothing about the service. Treat it as an SSH
                # error rather than as "not measurable".
                raw_per_service[service] = None
                notes.append(f"{service}=ssh-error")
                continue
            load_state = unit_data.get("LoadState")
            if load_state != "loaded" or unit_data.get("ActiveState") != "active":
                raw_per_service[service] = None
                if load_state and load_state != "loaded":
                    notes.append(f"{service}={load_state}")
                continue
            raw_per_service[service] = self._extract_value(unit_data, service)

        return raw_per_service, notes

    async def _poll_once(self) -> None:
        poll_wall = time.time()
        raw_per_service, notes = await self._sample_all()
        per_service = self._transform_per_service(raw_per_service, poll_wall)

        sample = self._make_sample(
            timestamp=_now_str(),
            epoch=datetime.now(timezone.utc).timestamp(),
            per_service=per_service,
            notes=",".join(notes),
        )
        self.rows.append(sample)

        if self._file is not None:
            try:
                cols = [sample.timestamp]
                for service in self.services:
                    v = per_service.get(service)
                    cols.append("---" if v is None else self._format_value(v))
                cols.append(sample.notes)
                self._file.write("  ".join(cols) + "\n")
                self._file.flush()
            except Exception:
                pass

    def max_per_service_in_window(
        self, window_start: float, window_end: float
    ) -> t.Dict[str, t.Any]:
        rows = self.get_rows_in_window(window_start, window_end)
        result: t.Dict[str, t.Any] = {}
        for row in rows:
            for service, value in row.per_service.items():
                if value is None:
                    continue
                cur = result.get(service)
                if cur is None or value > cur:
                    result[service] = value
        return result

    def samples_per_service_in_window(
        self, window_start: float, window_end: float
    ) -> t.Dict[str, t.List]:
        rows = self.get_rows_in_window(window_start, window_end)
        result: t.Dict[str, t.List] = {}
        for row in rows:
            for service, value in row.per_service.items():
                if value is None:
                    continue
                result.setdefault(service, []).append(value)
        return result
