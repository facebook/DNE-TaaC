# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe

"""FPF HRT driver-disconnect ODS health check.

Surfaces any HostReachTracker (HRT) driver disconnect on the RTP test hosts
during the test window. HRT exposes ``hrt.driver.created`` as a gauge that is
``1`` while the driver is connected and drops below ``1`` (to ``0``) whenever
the driver disconnects. This check asserts that, for every provided host, the
gauge stays at ``1`` for the ENTIRE window [test-case start, now]. If the value
is ever less than ``1`` on any host, the driver disconnected at least once and
the check FAILs, naming the host(s) and the timestamp(s) of each disconnect.

Metric (ODS):
    hrt.driver.created
    transform: none (raw per-timestamp series). The check asserts EVERY sample
    is 1: PASS only if all in-window samples on a host are 1; FAIL if ANY sample
    is < 1, naming the host and each offending timestamp.

Window: test-case start time -> now (overridable). The check queries ODS for
all provided host entities at once and judges each host independently: one host
that ever dropped below 1 fails the check while the others are still reported OK.
"""

import time
import typing as t
from datetime import datetime

from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.internal.ods_utils import (
    async_generate_ods_url,
    async_query_ods,
)
from taac.libs.fpf.fpf_collector_registry import (
    get_test_case_start_time,
    register_artifact,
)
from taac.utils.common import async_get_fburl
from taac.health_check.health_check import types as hc_types

# Default HRT driver-connected ODS key, transform, expected value, and window.
DEFAULT_HRT_DRIVER_KEY = "hrt.driver.created"
# No ODS transform: fetch the RAW per-timestamp series and assert EVERY sample
# is 1 in Python. A bare aggregate transform would collapse the series and lose
# the per-disconnect timestamps we surface (and the empty-parens form "min()" is
# rejected by Rapido with "input time is an empty string"), so keep it empty.
DEFAULT_TRANSFORM_DESC = ""
# The gauge must stay at this value for the whole window; anything lower means
# the driver disconnected at least once.
EXPECTED_CONNECTED_VALUE = 1.0
DEFAULT_LOOKBACK_SEC = 900
# How many disconnect timestamps to name per host before summarizing the rest.
_MAX_TS_TO_LIST = 10


def _fmt_ts(ts: int) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


class FpfHrtDriverDisconnectHealthCheck(
    AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]
):
    """Postcheck: HRT driver stays connected (``hrt.driver.created`` == 1).

    check_params:
        hosts (List[str]) | entity_desc (str): RTP test hosts to query. Either
            a list (``hosts``) or a comma-separated string (``entity_desc``).
        key_desc (str): ODS key. Default DEFAULT_HRT_DRIVER_KEY.
        transform_desc (str): ODS transform. Default "" (raw per-timestamp
            series; the check asserts every sample is 1).
        expected_value (float): Connected value the gauge must hold. Default 1.0.
        lookback_sec (int): Fallback window length if no test-case start time.
        window_start / window_end (float): Explicit window overrides.
    """

    CHECK_NAME = hc_types.CheckName.FPF_HRT_DRIVER_DISCONNECT_CHECK
    CHECK_SCOPE = hc_types.Scope.DEFAULT
    OPERATING_SYSTEMS = ["FBOSS"]

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        hosts = check_params.get("hosts")
        entity_desc = check_params.get("entity_desc")
        if entity_desc is None:
            if hosts:
                entity_desc = ",".join(hosts)
            elif obj is not None:
                entity_desc = obj.name
            else:
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.SKIP,
                    message="No hosts/entity_desc provided for HRT driver-disconnect check",
                )

        key_desc = check_params.get("key_desc", DEFAULT_HRT_DRIVER_KEY)
        transform_desc = check_params.get("transform_desc", DEFAULT_TRANSFORM_DESC)
        reduce_desc = check_params.get("reduce_desc", "")
        expected_value = float(
            check_params.get("expected_value", EXPECTED_CONNECTED_VALUE)
        )

        window_end = float(check_params.get("window_end", time.time()))
        tc_start = get_test_case_start_time()
        lookback_sec = check_params.get("lookback_sec", DEFAULT_LOOKBACK_SEC)
        window_start = float(
            check_params.get(
                "window_start",
                tc_start if tc_start else window_end - lookback_sec,
            )
        )
        start_time = int(window_start)
        end_time = int(window_end)
        # Guard against a degenerate/zero-length window. This happens when the
        # check runs as a PRECHECK: the test-case start time is ~now, so
        # window_start == window_end and ODS would get an empty time range. Fall
        # back to a lookback window so there is always a valid, non-empty range.
        if end_time - start_time < 1:
            start_time = end_time - int(lookback_sec)

        self.logger.info(
            f"  [HRT driver disconnect] Querying ODS for {entity_desc} "
            f"key={key_desc} transform={transform_desc} "
            f"window {start_time} to {end_time} ({end_time - start_time}s); "
            f"expected gauge == {expected_value:.0f} for the whole window"
        )

        ods_data = await async_query_ods(
            entity_desc=entity_desc,
            key_desc=key_desc,
            reduce_desc=reduce_desc,
            transform_desc=transform_desc,
            start_time=start_time,
            end_time=end_time,
        )

        ods_url = await async_generate_ods_url(
            entity_desc=entity_desc,
            key_desc=key_desc,
            reduce_desc=reduce_desc,
            transform_desc=transform_desc,
            start_time=start_time,
            end_time=end_time,
        )
        # Shorten to an fburl for a readable link in the result message /
        # Everpaste. Best-effort: fall back to the raw chart URL on any failure.
        try:
            ods_url = await async_get_fburl(ods_url)
            register_artifact("ods", "HRT driver connectivity", ods_url)
        except Exception as ex:
            self.logger.warning(f"  [HRT driver disconnect] fburl shorten failed: {ex}")

        if not ods_data:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.SKIP,
                message=f"No ODS data for HRT driver-disconnect. URL: {ods_url}",
            )

        # Judge each host independently: the gauge must hold expected_value for
        # the entire window. Any sample below it is a driver disconnect instance.
        violations: t.List[str] = []
        pass_details: t.List[str] = []
        for entity, key_data in sorted(ods_data.items()):
            all_values: t.Dict[int, float] = {}
            for _key_name, ts_data in key_data.items():
                all_values.update(ts_data)
            if not all_values:
                continue

            disconnect_ts = sorted(
                ts for ts, val in all_values.items() if val < expected_value
            )
            if not disconnect_ts:
                min_val = min(all_values.values())
                pass_details.append(f"{entity}: stayed at {min_val:.0f}")
                self.logger.info(
                    f"  [HRT driver disconnect] {entity}: [PASS] "
                    f"gauge stayed >= {expected_value:.0f} for the whole window"
                )
            else:
                shown = ", ".join(_fmt_ts(ts) for ts in disconnect_ts[:_MAX_TS_TO_LIST])
                extra = len(disconnect_ts) - _MAX_TS_TO_LIST
                if extra > 0:
                    shown += f", ... (+{extra} more)"
                violations.append(
                    f"{entity}: {len(disconnect_ts)} disconnect sample(s) at [{shown}]"
                )
                self.logger.info(
                    f"  [HRT driver disconnect] {entity}: [FAIL] "
                    f"{len(disconnect_ts)} sample(s) below {expected_value:.0f}: {shown}"
                )

        if not pass_details and not violations:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.SKIP,
                message=f"No HRT driver samples in window. URL: {ods_url}",
            )

        if violations:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=(
                    "HRT driver disconnected during the test window — "
                    + "; ".join(violations)
                    + (f" | OK: {'; '.join(pass_details)}" if pass_details else "")
                    + f" | ODS: {ods_url}"
                ),
            )
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
            message=(
                "HRT driver stayed connected for the whole window — "
                + "; ".join(pass_details)
                + f" | ODS: {ods_url}"
            ),
        )
