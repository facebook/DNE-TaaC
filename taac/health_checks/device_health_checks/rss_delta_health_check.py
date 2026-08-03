# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""Reporter health check for the BGP++ (``bgpcpp``) RSS delta bracket.

The measurement is a START/STOP bracket (``bgp_rss_start`` / ``bgp_rss_stop``)
that samples the settled baseline RSS at a caller-chosen pre-phase point, then
the settled current RSS and the peak VmRSS after the phase, and stashes
{baseline, current, peak, growth%} into a jq var. This point-in-time postcheck
reads that summary and reports it into the POST-HEALTH CHECK RESULTS table.

Observe-only by default: with no ``max_growth_pct`` it always PASSes and puts the
baseline/current/peak/growth in the message. Supply ``max_growth_pct`` to gate on
steady-state growth over the in-run baseline. A restart mid-window (flagged by the
STOP step) or a missing summary FAILs loudly -- never a silent pass.
"""

import typing as t

from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.utils.health_check_utils import (
    evaluate_rss_delta_from_baseline,
)
from taac.health_check.health_check import types as hc_types

_BYTES_PER_MIB = 1024 * 1024


class RssDeltaHealthCheck(AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]):
    CHECK_NAME = hc_types.CheckName.RSS_DELTA_CHECK
    OPERATING_SYSTEMS = ["EOS"]
    LOG_TO_SCUBA = True

    def _mib(self, summary: t.Dict[str, t.Any], key: str) -> float:
        return float(summary.get(key, 0)) / _BYTES_PER_MIB

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        summary = check_params.get("summary")
        if not isinstance(summary, dict) or "current_bytes" not in summary:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=(
                    f"RSS delta summary missing on {obj.name}: the START/STOP "
                    f"bracket did not stash results."
                ),
            )
        self.add_data_to_log(summary)

        if summary.get("restarted"):
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=(
                    f"RSS delta on {obj.name}: bgpcpp restarted mid-window; the "
                    f"steady-state comparison is invalid."
                ),
            )

        max_growth_pct = check_params.get("max_growth_pct")
        if max_growth_pct is None:
            # Observe-only: report the growth_pct computed at STOP time (full
            # precision, stashed in the summary) directly -- no threshold
            # evaluation, and no re-derivation from int-truncated byte counts.
            growth_pct = float(summary.get("growth_pct", 0.0))
            detail = (
                f"baseline={self._mib(summary, 'baseline_bytes'):.0f}MiB "
                f"current={self._mib(summary, 'current_bytes'):.0f}MiB "
                f"peak={self._mib(summary, 'peak_bytes'):.0f}MiB "
                f"growth={growth_pct:.1f}%"
            )
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.PASS,
                message=f"{detail} (observe-only)",
            )
        # Gating: evaluate the stashed baseline/current against the threshold.
        result = evaluate_rss_delta_from_baseline(
            baseline_rss_bytes=int(summary["baseline_bytes"]),
            current_rss_bytes=int(summary["current_bytes"]),
            max_growth_pct=float(max_growth_pct),
        )
        detail = (
            f"baseline={self._mib(summary, 'baseline_bytes'):.0f}MiB "
            f"current={self._mib(summary, 'current_bytes'):.0f}MiB "
            f"peak={self._mib(summary, 'peak_bytes'):.0f}MiB "
            f"growth={result.growth_pct:.1f}%"
        )
        return hc_types.HealthCheckResult(
            status=(
                hc_types.HealthCheckStatus.PASS
                if result.passed
                else hc_types.HealthCheckStatus.FAIL
            ),
            message=(
                f"{detail} {'within' if result.passed else 'exceeds'} threshold "
                f"{float(max_growth_pct):.1f}%"
            ),
        )
