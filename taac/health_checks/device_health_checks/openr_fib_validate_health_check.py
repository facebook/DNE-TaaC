# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe
import typing as t

from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.health_check.health_check import types as hc_types


class OpenrFibValidateHealthCheck(
    AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]
):
    """
    Compares Open/R Decision-computed routes vs FIB-programmed routes
    and fails if there are mismatches (missing or extra routes).
    Also fails if both Decision and FIB are empty (vacuous match).

    check_params:
        allow_empty (bool): set True to allow 0 routes in both Decision
            and FIB (e.g. isolated node with no Open/R routes)
    """

    CHECK_NAME = hc_types.CheckName.OPENR_FIB_VALIDATE_CHECK
    OPERATING_SYSTEMS = ["FBOSS"]

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        allow_empty = check_params.get("allow_empty", False)
        result = await self.driver.async_validate_openr_fib()

        missing = result.get("missing_in_fib", set())
        extra = result.get("extra_in_fib", set())
        match = result.get("match", False)
        decision_db = result.get("decision_route_db")
        fib_db = result.get("fib_route_db")

        decision_count = len(decision_db.unicastRoutes) if decision_db else 0
        fib_count = len(fib_db.unicastRoutes) if fib_db else 0

        if not match:
            details = []
            if missing:
                details.append(
                    f"{len(missing)} route(s) missing in FIB: {sorted(missing)[:10]}"
                )
            if extra:
                details.append(
                    f"{len(extra)} extra route(s) in FIB: {sorted(extra)[:10]}"
                )
            if not details:
                details.append(
                    "FIB validation reported mismatch with no specific "
                    "missing/extra routes"
                )
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=f"{obj.name}: FIB validate FAILED — " + "; ".join(details),
            )

        if decision_count == 0 and fib_count == 0 and not allow_empty:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=f"{obj.name}: FIB validate FAILED — "
                f"both Decision and FIB have 0 routes (vacuous match)",
            )

        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
            message=f"{obj.name}: FIB validate PASSED — "
            f"{decision_count} Decision route(s) match "
            f"{fib_count} FIB route(s)",
        )
