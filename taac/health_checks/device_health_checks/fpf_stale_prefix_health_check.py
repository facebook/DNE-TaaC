# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

import ipaddress
import typing as t

from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from neteng.test_infra.dne.taac.libs.fpf.fpf_bgp_rib import _count_matching, get_bgp_rib
from taac.health_check.health_check import types as hc_types


class FpfStalePrefixHealthCheck(AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]):
    """Health check to verify no stale test prefixes exist before a stress test.

    Queries the BGP RIB on the device and counts prefixes matching a
    configurable subnet (default ``5000:dd::/32``). If any matching
    prefixes are found, they are considered stale leftovers from a
    previous test run and the check fails.
    """

    CHECK_NAME = hc_types.CheckName.FPF_STALE_PREFIX_CHECK
    OPERATING_SYSTEMS = ["FBOSS"]

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        """Check the BGP RIB for stale test prefixes.

        Args:
            obj: Test device to check.
            input: Base health check input (required by interface).
            check_params: Dictionary containing optional parameters:
                - subnet_prefix: IPv6 subnet to match against
                  (default ``5000:dd::/32``).

        Returns:
            HealthCheckResult: PASS if no matching prefixes found,
            FAIL if stale prefixes exist, SKIP on connection error.
        """
        hostname = obj.name
        if "rtptest" in hostname:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.SKIP,
                message=f"Stale prefix check not applicable to GPU host {hostname}",
            )

        subnet_str = check_params.get("subnet_prefix", "5000:dd::/32")

        self.logger.info(
            f"Running FPF stale prefix health check on {hostname} "
            f"with subnet {subnet_str}"
        )

        try:
            subnet = ipaddress.IPv6Network(subnet_str, strict=False)
        except ValueError as e:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.ERROR,
                message=f"Invalid subnet_prefix '{subnet_str}': {e}",
            )

        try:
            rib_entries = await get_bgp_rib(hostname)
        except ConnectionError as e:
            self.logger.warning(
                f"Connection error fetching BGP RIB from {hostname}: {e}"
            )
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.SKIP,
                message=f"Connection error querying BGP RIB on {hostname}: {e}",
            )

        count = _count_matching(rib_entries, subnet=subnet, exact=None)

        self.logger.info(
            f"FPF stale prefix check on {hostname}: "
            f"found {count} prefixes matching {subnet_str}"
        )

        if count == 0:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.PASS,
                message=(
                    f"No stale test prefixes found in BGP RIB on {hostname} "
                    f"for subnet {subnet_str}"
                ),
            )

        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.FAIL,
            message=(
                f"Found {count} stale test prefix(es) in BGP RIB on "
                f"{hostname} matching {subnet_str}. "
                f"Clean up before starting the stress test."
            ),
        )
