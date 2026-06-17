# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
import typing as t

from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.health_check.health_check import types as hc_types


class OpenrAdjacencyHealthCheck(AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]):
    """
    Validates that the expected number of Open/R adjacencies exist.

    Expected count is resolved in this order:
    1. check_params["expected_adjacency_count"] — explicit override
    2. len(obj.interfaces) — derived from topology
    3. If neither, requires at least 1 adjacency.

    check_params:
        expected_adjacency_count (int): exact number of expected adjacencies
        allow_zero (bool): set True to allow 0 adjacencies
    """

    CHECK_NAME = hc_types.CheckName.OPENR_ADJACENCY_CHECK
    OPERATING_SYSTEMS = ["FBOSS"]

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        explicit_count = check_params.get("expected_adjacency_count")
        allow_zero = check_params.get("allow_zero", False)

        # pyrefly: ignore [missing-attribute]
        neighbors = await self.driver.async_get_openr_spark_neighbors()
        established_count = len([n for n in neighbors if str(n.state) == "ESTABLISHED"])

        # Resolve expected count
        if explicit_count is not None:
            expected_count = explicit_count
        elif obj.interfaces:
            expected_count = len(obj.interfaces)
        else:
            expected_count = None

        failure_reasons = []

        # Fail on 0 adjacencies unless explicitly allowed
        if established_count == 0 and not allow_zero:
            if expected_count is None or expected_count > 0:
                failure_reasons.append(
                    "No adjacencies found"
                    + (f" (expected {expected_count})" if expected_count else "")
                )

        # Count mismatch
        if (
            expected_count is not None
            and established_count != expected_count
            and not (established_count == 0 and failure_reasons)
        ):
            failure_reasons.append(
                f"Expected {expected_count} adjacenc(ies), found {established_count}"
            )

        if failure_reasons:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=f"{obj.name}: " + "; ".join(failure_reasons),
            )

        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
            message=f"{obj.name}: {established_count} adjacenc(ies) present"
            + (f" (expected {expected_count})" if expected_count else ""),
        )
