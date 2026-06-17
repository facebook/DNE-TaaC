# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
import typing as t

from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.health_check.health_check import types as hc_types


class OpenrSparkNeighborHealthCheck(
    AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]
):
    """
    Validates that all expected Open/R Spark neighbors are ESTABLISHED.

    Expected neighbor count is resolved in this order:
    1. check_params["expected_neighbor_count"] — explicit override
    2. check_params["expected_neighbors"] — len of the explicit list
    3. len(obj.interfaces) — derived from topology (each interface = 1 neighbor)
    4. If none of the above, requires at least 1 neighbor.

    check_params:
        expected_neighbor_count (int): exact number of expected neighbors
        expected_neighbors (list[str]): optional list of expected neighbor node names
        allow_zero (bool): set True to allow 0 neighbors (e.g. isolated node test)
    """

    CHECK_NAME = hc_types.CheckName.OPENR_SPARK_NEIGHBOR_CHECK
    OPERATING_SYSTEMS = ["FBOSS"]

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        explicit_count = check_params.get("expected_neighbor_count")
        expected_neighbors = check_params.get("expected_neighbors", [])
        allow_zero = check_params.get("allow_zero", False)

        # pyrefly: ignore [missing-attribute]
        neighbors = await self.driver.async_get_openr_spark_neighbors()
        established = [n for n in neighbors if str(n.state) == "ESTABLISHED"]
        non_established = [n for n in neighbors if str(n.state) != "ESTABLISHED"]

        # Resolve expected count
        if explicit_count is not None:
            expected_count = explicit_count
        elif expected_neighbors:
            expected_count = len(expected_neighbors)
        elif obj.interfaces:
            expected_count = len(obj.interfaces)
        else:
            expected_count = None

        failure_reasons = []

        # Fail on 0 neighbors unless explicitly allowed
        if len(established) == 0 and not allow_zero:
            if expected_count is None or expected_count > 0:
                failure_reasons.append(
                    "No ESTABLISHED neighbors found"
                    + (f" (expected {expected_count})" if expected_count else "")
                )

        # Count mismatch
        if (
            expected_count is not None
            and len(established) != expected_count
            and not (len(established) == 0 and failure_reasons)
        ):
            failure_reasons.append(
                f"Expected {expected_count} ESTABLISHED neighbor(s), "
                f"found {len(established)}"
            )

        # Named neighbor check
        if expected_neighbors:
            found_names = {str(n.nodeName) for n in established}
            missing = set(expected_neighbors) - found_names
            if missing:
                failure_reasons.append(
                    f"Missing ESTABLISHED neighbor(s): {sorted(missing)}"
                )

        # Non-established neighbors
        for n in non_established:
            failure_reasons.append(
                f"Neighbor {n.nodeName} is in state {n.state} (expected ESTABLISHED)"
            )

        if failure_reasons:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=f"{obj.name}: Spark neighbor check failed — "
                + "; ".join(failure_reasons),
            )

        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
            message=f"{obj.name}: {len(established)} Spark neighbor(s) all ESTABLISHED",
        )
