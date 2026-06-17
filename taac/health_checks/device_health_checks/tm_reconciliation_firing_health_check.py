# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""TM_RECONCILIATION_FIRING_CHECK — composite L2-firing postcheck for TAAC.

Cross-checks two independent signals over a time window to determine whether the
TunManager `cleanup_probed_kernel_data` (L2) reconciliation path executed:

1. **Log grep** — delegates to LogParsingHealthCheck for include-regex match on
   wedge_agent.log filtered to lines in [start_time, end_time].
2. **ODS counter** — queries the per-process `probed_state_cleanup_status`
   ODS counter for any value=1 sample in the same window (plus a publish
   lookahead to catch samples generated during the window but published shortly
   after).

The verdict combines both signals per the matrix locked in the Phase 4-1 design
memo (project_p41_taac_hc_design.md §1). When the two signals disagree, the
default is to return PASS with a WARN-style message (tolerant of ODS ingest lag
and sticky-sample carryover); pass `require_both_signals=True` to escalate
disagreements to FAIL.
"""

import asyncio
import time
import typing as t

from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.health_checks.device_health_checks.log_parsing_health_check import (
    LogParsingHealthCheck,
)
from taac.internal.ods_utils import async_query_ods
from taac.health_check.health_check import types as hc_types


# ODS publish cadence is ~60s. Extending the query end past the test-case end
# captures samples generated during the window but published shortly after.
_ODS_LOOKAHEAD_S = 90


class TmReconciliationFiringHealthCheck(
    AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]
):
    """Composite L2-firing postcheck: log-grep + ODS counter + verdict matrix."""

    CHECK_NAME: hc_types.CheckName = hc_types.CheckName.TM_RECONCILIATION_FIRING_CHECK
    OPERATING_SYSTEMS: t.List[str] = ["FBOSS"]

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        expected_to_fire = bool(check_params["expected_to_fire"])
        require_both_signals = bool(check_params.get("require_both_signals", False))
        log_file_path = check_params["log_file_path"]
        firing_pattern = check_params["firing_pattern"]
        ods_key = check_params["ods_key"]
        start_time = int(check_params["start_time"])
        end_time = int(check_params.get("end_time") or time.time())

        log_fired, ods_fired = await asyncio.gather(
            self._log_fired(obj, log_file_path, firing_pattern, start_time, end_time),
            self._ods_fired(obj, ods_key, start_time, end_time),
        )
        return self._verdict(
            expected_to_fire, log_fired, ods_fired, require_both_signals
        )

    async def _log_fired(
        self,
        obj: TestDevice,
        log_file_path: str,
        firing_pattern: str,
        start_time: int,
        end_time: int,
    ) -> bool:
        """Delegate log-grep to LogParsingHealthCheck (include_regex semantics)."""
        log_check = LogParsingHealthCheck(logger=self.logger)
        log_check.driver = self.driver
        result = await log_check._run(
            obj,
            hc_types.BaseHealthCheckIn(),
            {
                "log_file_path": log_file_path,
                "include_regex": firing_pattern,
                "start_time": start_time,
                "end_time": end_time,
            },
        )
        return result.status == hc_types.HealthCheckStatus.PASS

    async def _ods_fired(
        self, obj: TestDevice, ods_key: str, start_time: int, end_time: int
    ) -> bool:
        """True if any value=1 sample for `ods_key` lands in the window."""
        entity = obj.name.removesuffix(".tfbnw.net")
        ods_data = await async_query_ods(
            entity_desc=entity,
            key_desc=ods_key,
            start_time=start_time,
            end_time=end_time + _ODS_LOOKAHEAD_S,
        )
        if not ods_data:
            return False
        # Shape: {entity: {key: {timestamp: value}}}
        for key_to_series in ods_data.values():
            for ts_to_value in key_to_series.values():
                for value in ts_to_value.values():
                    if value == 1:
                        return True
        return False

    def _verdict(
        self,
        expected_to_fire: bool,
        log_fired: bool,
        ods_fired: bool,
        require_both_signals: bool,
    ) -> hc_types.HealthCheckResult:
        """Apply the verdict matrix from project_p41_taac_hc_design.md §1."""
        base = (
            f"[reconciliation] expected={expected_to_fire} "
            f"log_fired={log_fired} ods_fired={ods_fired}"
        )
        if expected_to_fire:
            if log_fired and ods_fired:
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.PASS,
                    message=f"{base} verdict=PASS (both signals agree)",
                )
            if not log_fired and not ods_fired:
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.FAIL,
                    message=f"{base} verdict=FAIL (expected firing, none seen)",
                )
            return self._disagreement(base, require_both_signals)
        # not expected to fire
        if not log_fired and not ods_fired:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.PASS,
                message=f"{base} verdict=PASS (no firing as expected)",
            )
        if log_fired and ods_fired:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=f"{base} verdict=FAIL (unexpected firing)",
            )
        return self._disagreement(base, require_both_signals)

    @staticmethod
    def _disagreement(
        base: str, require_both_signals: bool
    ) -> hc_types.HealthCheckResult:
        """Cross-signal disagreement — FAIL if require_both_signals else PASS (WARN)."""
        if require_both_signals:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=(
                    f"{base} verdict=FAIL "
                    f"(signal disagreement, require_both_signals=True)"
                ),
            )
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
            message=(
                f"{base} verdict=WARN "
                f"(signal disagreement, tolerated; require_both_signals=False)"
            ),
        )
