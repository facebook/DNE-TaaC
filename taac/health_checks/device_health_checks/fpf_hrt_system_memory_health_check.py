# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""FPF HRT system-memory ODS health check.

Tracks the HostReachTracker (HRT) service's system memory on the RTP test
hosts and asserts that the per-host MAX over the test window stays under a
threshold (default 8 GiB). This is the first of a planned family of "HRT
system metric" checks; for now only memory is asserted.

Metric (ODS):
    cgroup.slice.system.metalos.wds.hostreachtracker.memory.current
    transform: max()   (per-host max over the window)

Window: test-case start time -> now (overridable). The check queries ODS for
all provided host entities at once, takes each host's max in the window, and
FAILs if ANY host exceeds the threshold. Each host is judged independently:
one host over the line fails the check while the others are still reported OK.
"""

import time
import typing as t

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

# Default HRT system-memory ODS key, transform, threshold, and window.
DEFAULT_HRT_MEMORY_KEY = (
    "cgroup.slice.system.metalos.wds.hostreachtracker.memory.current"
)
GIB = 1024**3
DEFAULT_THRESHOLD_GIB = 8.0
# ODS "max" transform: per-host max over the window, computed server-side. NOTE
# the bare form "max" — NOT "max()": empty parens make Rapido try to parse "" as
# a time and fail with "input time is an empty string". (The check also takes
# max() over the returned values in Python, so it is correct either way.)
DEFAULT_TRANSFORM_DESC = "max"
DEFAULT_LOOKBACK_SEC = 900


class FpfHrtSystemMemoryHealthCheck(
    AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]
):
    """Postcheck: HRT system memory stays under threshold on every RTP host.

    check_params:
        hosts (List[str]) | entity_desc (str): RTP test hosts to query. Either
            a list (``hosts``) or a comma-separated string (``entity_desc``).
        key_desc (str): ODS key. Default DEFAULT_HRT_MEMORY_KEY.
        transform_desc (str): ODS transform. Default "max()".
        threshold_gib (float): Per-host max threshold in GiB. Default 8.0.
        threshold_bytes (int): Overrides threshold_gib if provided.
        lookback_sec (int): Fallback window length if no test-case start time.
        window_start / window_end (float): Explicit window overrides.
    """

    CHECK_NAME = hc_types.CheckName.FPF_HRT_SYSTEM_MEMORY_CHECK
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
                    message="No hosts/entity_desc provided for HRT memory check",
                )

        key_desc = check_params.get("key_desc", DEFAULT_HRT_MEMORY_KEY)
        transform_desc = check_params.get("transform_desc", DEFAULT_TRANSFORM_DESC)
        reduce_desc = check_params.get("reduce_desc", "")

        if "threshold_bytes" in check_params:
            threshold_bytes = float(check_params["threshold_bytes"])
            threshold_gib = threshold_bytes / GIB
        else:
            threshold_gib = float(
                check_params.get("threshold_gib", DEFAULT_THRESHOLD_GIB)
            )
            threshold_bytes = threshold_gib * GIB

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
            f"  [HRT system memory] Querying ODS for {entity_desc} "
            f"key={key_desc} transform={transform_desc} "
            f"window {start_time} to {end_time} ({end_time - start_time}s); "
            f"threshold {threshold_gib:.2f} GiB ({threshold_bytes:.0f} bytes)"
        )

        ods_data = await async_query_ods(
            entity_desc=entity_desc,
            key_desc=key_desc,
            reduce_desc=reduce_desc,
            transform_desc=transform_desc,
            start_time=start_time,
            end_time=end_time,
        )

        if not ods_data:
            ods_url = await async_generate_ods_url(
                entity_desc=entity_desc,
                key_desc=key_desc,
                reduce_desc=reduce_desc,
                transform_desc=transform_desc,
                start_time=start_time,
                end_time=end_time,
            )
            try:
                ods_url = await async_get_fburl(ods_url)
            except Exception:
                pass
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.SKIP,
                message=f"No ODS data for HRT system memory. URL: {ods_url}",
            )

        # Per-host max over the window. Judge each host independently.
        violations: t.List[str] = []
        pass_details: t.List[str] = []
        for entity, key_data in sorted(ods_data.items()):
            all_values: t.Dict[int, float] = {}
            for _key_name, ts_data in key_data.items():
                all_values.update(ts_data)
            if not all_values:
                continue
            max_val = max(all_values.values())
            max_gib = max_val / GIB
            if max_val <= threshold_bytes:
                pass_details.append(f"{entity}: max={max_gib:.2f} GiB")
                self.logger.info(
                    f"  [HRT system memory] {entity}: [PASS] "
                    f"max={max_gib:.2f} GiB <= {threshold_gib:.2f} GiB"
                )
            else:
                violations.append(
                    f"{entity}: max={max_gib:.2f} GiB > {threshold_gib:.2f} GiB"
                )
                self.logger.info(
                    f"  [HRT system memory] {entity}: [FAIL] "
                    f"max={max_gib:.2f} GiB exceeds {threshold_gib:.2f} GiB"
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
        # Everpaste. This check runs once per host-set (not per-device-many-
        # times), so shortening on every path is fine. Best-effort: fall back to
        # the raw chart URL on any failure.
        try:
            ods_url = await async_get_fburl(ods_url)
            register_artifact("ods", "HRT system memory", ods_url)
        except Exception as ex:
            self.logger.warning(f"  [HRT system memory] fburl shorten failed: {ex}")

        if not pass_details and not violations:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.SKIP,
                message=f"No HRT system memory samples in window. URL: {ods_url}",
            )

        if violations:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=(
                    f"HRT system memory exceeded {threshold_gib:.2f} GiB — "
                    + "; ".join(violations)
                    + (f" | OK: {'; '.join(pass_details)}" if pass_details else "")
                    + f" | ODS: {ods_url}"
                ),
            )
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
            message=(
                f"HRT system memory within {threshold_gib:.2f} GiB — "
                + "; ".join(pass_details)
                + f" | ODS: {ods_url}"
            ),
        )
