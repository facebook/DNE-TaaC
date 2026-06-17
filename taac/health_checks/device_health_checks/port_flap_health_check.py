# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
import json
import typing as t

from taac.constants import TestDevice
from taac.health_checks.abstract_snapshot_health_check import (
    AbstractDeviceSnapshotHealthCheck,
)
from taac.health_checks.constants import Snapshot
from taac.health_check.health_check import types as hc_types


class PortFlapHealthCheck(
    AbstractDeviceSnapshotHealthCheck[hc_types.BaseHealthCheckIn],
):
    """
    SnapshotHealthCheck that compares port flaps before and after a test.

    This health check captures the total link flap counts for all ports on an FBOSS device
    before and after a test, then compares them to detect any port flaps that occurred
    during the test execution.

    Counter pattern: <interface_name>.link_state.flap.sum
    Example: eth1/1/1.link_state.flap.sum
    """

    CHECK_NAME = hc_types.CheckName.PORT_FLAP_CHECK
    OPERATING_SYSTEMS = [
        "FBOSS",
    ]

    async def _get_port_flap_counters(
        self,
        obj: TestDevice,
    ) -> t.Dict[str, int]:
        """
        Get port flap counters for all ports on the device.

        Returns:
            Dict mapping port names to their total flap counts
        """
        # Get all port information to know which ports exist
        # pyrefly: ignore [missing-attribute]
        all_port_info = await self.driver.async_get_all_port_info()

        # Build counter keys for all ports
        # Counter format: <port_name>.link_state.flap.sum
        counter_keys = []
        port_names = []

        for port_info in all_port_info.values():
            port_name = port_info.name
            port_names.append(port_name)
            counter_key = f"{port_name}.link_state.flap.sum"
            counter_keys.append(counter_key)

        self.logger.info(
            f"Querying flap counters for {len(port_names)} ports on {obj.name}"
        )

        # Get the flap counters for all ports
        # Note: Some counters may not exist if the port has never flapped
        try:
            # pyrefly: ignore [missing-attribute]
            flap_counters = await self.driver.async_get_selected_counters(counter_keys)
        except Exception as e:
            # If some counters don't exist, that's okay - just log and return empty dict
            self.logger.warning(
                f"Could not retrieve all flap counters on {obj.name}: {e}. "
                f"This may be normal if some ports have never flapped."
            )
            flap_counters = {}

        # Convert counter keys back to port names for easier comparison
        port_flap_counts = {}
        for counter_key, count in flap_counters.items():
            # Extract port name from counter key (e.g., eth1/1/1.link_state.flap.sum -> eth1/1/1)
            port_name = counter_key.split(".link_state.flap.sum")[0]
            port_flap_counts[port_name] = int(count)

        self.logger.info(
            f"Retrieved flap counters for {len(port_flap_counts)} ports on {obj.name}"
        )

        return port_flap_counts

    async def capture_pre_snapshot(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
        timestamp: int,
    ) -> Snapshot:
        """
        Capture port flap counters before the test.
        """
        port_flap_counts = await self._get_port_flap_counters(obj)

        self.logger.info(
            f"Pre-snapshot: Captured flap counts for {len(port_flap_counts)} ports on {obj.name}"
        )

        return Snapshot(data=port_flap_counts, timestamp=timestamp)

    async def capture_post_snapshot(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
        timestamp: int,
    ) -> Snapshot:
        """
        Capture port flap counters after the test.
        """
        port_flap_counts = await self._get_port_flap_counters(obj)

        self.logger.info(
            f"Post-snapshot: Captured flap counts for {len(port_flap_counts)} ports on {obj.name}"
        )

        return Snapshot(data=port_flap_counts, timestamp=timestamp)

    async def compare_snapshots(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
        pre_snapshot: Snapshot,
        post_snapshot: Snapshot,
    ) -> hc_types.HealthCheckResult:
        """
        Compare pre and post snapshots to detect any port flaps during the test.

        Args:
            ports_to_ignore: Optional list of port names to exclude from flap detection
        """
        # Get optional list of ports to ignore from check params
        ports_to_ignore = json.loads(check_params.get("ports_to_ignore", "[]"))

        # Find ports that had flaps during the test
        flapped_ports = []

        # Check all ports that exist in both snapshots
        all_ports = set(pre_snapshot.data.keys()) | set(post_snapshot.data.keys())

        for port_name in all_ports:
            if port_name in ports_to_ignore:
                continue

            pre_count = pre_snapshot.data.get(port_name, 0)
            post_count = post_snapshot.data.get(port_name, 0)

            if post_count > pre_count:
                flap_increase = post_count - pre_count
                flapped_ports.append(
                    {
                        "port": port_name,
                        "flaps_before": pre_count,
                        "flaps_after": post_count,
                        "new_flaps": flap_increase,
                    }
                )

        if flapped_ports:
            # Build detailed failure message
            flap_details = "\n".join(
                [
                    f"  - {p['port']}: {p['new_flaps']} new flap(s) "
                    f"(before: {p['flaps_before']}, after: {p['flaps_after']})"
                    for p in flapped_ports
                ]
            )

            message = (
                f"Port flaps detected on {obj.name} during test:\n"
                f"{flap_details}\n"
                f"Total ports with flaps: {len(flapped_ports)}"
            )

            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=message,
            )

        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
            message=f"No port flaps detected on {obj.name} during test",
        )
