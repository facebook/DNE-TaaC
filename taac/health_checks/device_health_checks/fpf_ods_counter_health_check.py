# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""ODS counter health check with custom entity list and time-windowed evaluation.

Queries ODS for a configurable counter (e.g., in_dst_null_discard) across a
list of devices, using the test case start time from the collector registry
as the window start. Evaluates per-entity: if any entity's value exceeds the
threshold, the check fails.

Designed for FPF hardening tests but generic enough for any ODS counter.
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
)
from taac.health_check.health_check import types as hc_types


class FpfOdsCounterHealthCheck(AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]):
    """Check ODS counters across a custom set of devices within a time window.

    Uses ``entity_desc`` from check_params (comma-separated device list)
    instead of the DUT device name. Queries ODS with the provided key, reduce,
    and transform parameters, then validates each entity's result against the
    threshold.

    check_params:
        entity_desc (str): Comma-separated list of device hostnames
        key_desc (str): ODS key regex (e.g., regex(fboss.agent.eth.*discards.sum.60),filter(.*in_dst_null.*))
        validation_expr (str): Comparison expression (e.g., "<= 10000")
        reduce_desc (str): ODS reduce function (default: "")
        transform_desc (str): ODS transform function (default: "max"). NOTE the
            bare form — NOT "max()": empty parens make Rapido parse "" as a time
            and fail with "input time is an empty string".
        counter_name (str): Human-readable counter name for logging (default: "ODS counter")
    """

    CHECK_NAME = hc_types.CheckName.GENERIC_ODS_CHECK
    CHECK_SCOPE = hc_types.Scope.DEFAULT
    OPERATING_SYSTEMS = ["FBOSS"]

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        entity_desc = check_params["entity_desc"]
        key_desc = check_params["key_desc"]
        validation_expr = check_params["validation_expr"]
        reduce_desc = check_params.get("reduce_desc", "")
        transform_desc = check_params.get("transform_desc", "max")
        counter_name = check_params.get("counter_name", "ODS counter")

        tc_start = get_test_case_start_time()
        start_time = int(check_params.get("start_time", tc_start or time.time() - 900))
        end_time = int(time.time())

        self.logger.info(
            f"  [{counter_name}] Querying ODS for {entity_desc} "
            f"window: {start_time} to {end_time} "
            f"({end_time - start_time}s span)"
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
                start_time=start_time,
                end_time=end_time,
            )
            self.logger.info(f"  [{counter_name}] No ODS data returned. URL: {ods_url}")
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.SKIP,
                message=f"No ODS data for {counter_name}. URL: {ods_url}",
            )

        violations = []
        pass_details = []

        for entity, key_data in ods_data.items():
            for _key_name, time_series in key_data.items():
                if not time_series:
                    continue
                max_val = max(time_series.values())
                # max_ts intentionally not computed — only max_val drives the check
                passed = eval(f"{max_val} {validation_expr}")
                if passed:
                    pass_details.append(f"{entity}: {max_val:.0f}")
                    self.logger.info(
                        f"  [{counter_name}] {entity}: [PASS] "
                        f"max={max_val:.0f} ({validation_expr})"
                    )
                else:
                    violations.append(
                        f"{entity}: max={max_val:.0f} (threshold: {validation_expr})"
                    )
                    self.logger.info(
                        f"  [{counter_name}] {entity}: [FAIL] "
                        f"max={max_val:.0f} exceeds {validation_expr}"
                    )

        if violations:
            ods_url = await async_generate_ods_url(
                entity_desc=entity_desc,
                key_desc=key_desc,
                start_time=start_time,
                end_time=end_time,
            )
            fail_msg = "; ".join(violations)
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=f"{counter_name} threshold exceeded: {fail_msg}. "
                f"ODS: {ods_url}",
            )

        pass_msg = "; ".join(pass_details)
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
            message=f"{counter_name} within threshold: {pass_msg}",
        )
