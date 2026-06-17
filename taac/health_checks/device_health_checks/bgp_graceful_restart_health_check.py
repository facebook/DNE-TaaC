# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

import json
import typing as t

from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.health_check.health_check import types as hc_types


class BgpGracefulRestartHealthCheck(
    AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]
):
    """
    Health check to verify BGP Graceful Restart configuration on a specific peer group.

    Flexible check that validates graceful restart state matches expectation:
    - Can check that graceful restart is enabled for specific peer groups
    - Can check that graceful restart is disabled for specific peer groups
    - Environment agnostic - works for any peer group in any environment
    """

    CHECK_NAME = hc_types.CheckName.BGP_GRACEFUL_RESTART_CHECK
    OPERATING_SYSTEMS = [
        # "FBOSS",
        "EOS",
    ]

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        """
        Check BGP graceful restart configuration.

        Args:
            obj: Test device to check
            input: Base health check input
            check_params: Dictionary containing:
                - peer_group_name: Required string specifying which peer group to check
                - expected_graceful_restart_enabled: Optional boolean (default False)
                  * False: Check that graceful restart is disabled
                  * True: Check that graceful restart is enabled

        Returns:
            PASS if graceful restart state matches expectation, FAIL otherwise
        """
        hostname = obj.name
        peer_group_name = check_params.get("peer_group_name")
        expected_graceful_restart_enabled = check_params.get(
            "expected_graceful_restart_enabled", False
        )

        if not peer_group_name:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.ERROR,
                message="peer_group_name parameter is required",
            )

        try:
            # pyrefly: ignore [missing-attribute]
            bgp_config_json = await self.driver.async_get_bgp_configuration()

            if not bgp_config_json:
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.ERROR,
                    message=f"Unable to get BGP configuration from {hostname}",
                )

            # Parse JSON configuration
            bgp_config = json.loads(bgp_config_json)

            # Check 1: Global graceful restart setting
            global_gr_seconds = bgp_config.get(
                "graceful_restart_convergence_seconds", 0
            )
            global_gr_enabled = global_gr_seconds > 0

            # Check 2: Find the peer group and check graceful restart configuration
            peer_group_found = False
            peer_group_gr_enabled = False
            peer_groups = bgp_config.get("peer_groups", [])

            for peer_group in peer_groups:
                if peer_group.get("name") == peer_group_name:
                    peer_group_found = True
                    bgp_peer_timers = peer_group.get("bgp_peer_timers")

                    if bgp_peer_timers:
                        gr_seconds = bgp_peer_timers.get("graceful_restart_seconds", 0)
                    else:
                        gr_seconds = 0  # No bgp_peer_timers means GR is disabled

                    peer_group_gr_enabled = gr_seconds > 0
                    break

            if not peer_group_found:
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.ERROR,
                    message=f"Peer group '{peer_group_name}' not found in BGP configuration",
                )

            # Graceful restart is enabled if EITHER global OR peer group has it enabled
            actual_gr_enabled = global_gr_enabled or peer_group_gr_enabled

            # Check if the actual state matches the expected state
            if actual_gr_enabled != expected_graceful_restart_enabled:
                expected = (
                    "enabled" if expected_graceful_restart_enabled else "disabled"
                )
                actual = "enabled" if actual_gr_enabled else "disabled"

                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.FAIL,
                    message=f"BGP graceful restart check FAILED: Expected {expected} but found {actual} for peer group '{peer_group_name}'",
                )

            state = "enabled" if actual_gr_enabled else "disabled"
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.PASS,
                message=f"BGP graceful restart is {state} for peer group '{peer_group_name}' as expected.",
            )

        except Exception as e:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.ERROR,
                message=f"Error checking BGP graceful restart on {hostname}: {str(e)}",
            )
