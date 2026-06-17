# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
import typing as t

from taac.constants import TestDevice
from taac.health_checks.abstract_snapshot_health_check import (
    AbstractDeviceSnapshotHealthCheck,
)
from taac.health_checks.constants import Snapshot
from taac.health_check.health_check import types as hc_types


class PortChannelStateHealthCheck(
    AbstractDeviceSnapshotHealthCheck[hc_types.BaseHealthCheckIn],
):
    CHECK_NAME = hc_types.CheckName.PORT_CHANNEL_STATE_CHECK
    OPERATING_SYSTEMS = ["FBOSS", "EOS"]

    async def _async_get_fboss_port_channel_states(
        self,
    ) -> t.Dict[str, t.Dict[str, t.Any]]:
        """Return port-channel states from FBOSS via Thrift."""
        # pyrefly: ignore [missing-attribute]
        agg_ports = await self.driver.async_get_all_aggregated_port_info()
        return {port.name: {"is_up": port.isUp} for port in agg_ports}

    async def _async_get_eos_port_channel_states(
        self,
    ) -> t.Dict[str, t.Dict[str, t.Any]]:
        """Return port-channel states from EOS via the Arista driver."""
        # pyrefly: ignore [missing-attribute]
        output = await self.driver.async_get_port_channel_detailed_info()
        port_channels = output.get("portChannels", {})
        result = {}
        for pc_name, pc_data in port_channels.items():
            active_ports = pc_data.get("activePorts", {})
            inactive_ports = pc_data.get("inactivePorts", {})
            inactive_lag = pc_data.get("inactiveLag", False)
            is_up = bool(active_ports) and not inactive_lag

            lacp_issues = []
            for port_name, port_info in active_ports.items():
                issues = []
                if port_info.get("protocol") != "lacp":
                    issues.append(f"protocol={port_info.get('protocol', 'unknown')}")
                if port_info.get("lacpMode") != "active":
                    issues.append(f"lacpMode={port_info.get('lacpMode', 'unknown')}")
                if not port_info.get("collecting", False):
                    issues.append("collecting=false")
                if not port_info.get("distributing", False):
                    issues.append("distributing=false")
                if issues:
                    lacp_issues.append(f"{port_name}: {', '.join(issues)}")

            result[pc_name] = {
                "is_up": is_up,
                "active_port_count": len(active_ports),
                "inactive_port_count": len(inactive_ports),
                "max_weight": pc_data.get("maxWeight", 0),
                "lacp_issues": lacp_issues,
                "lag_feature": pc_data.get("lagFeature", ""),
            }
        return result

    async def _async_get_port_channel_snapshot_data(
        self,
        obj: TestDevice,
    ) -> t.Dict[str, t.Dict[str, t.Any]]:
        """Dispatch port-channel state collection by OS."""
        if obj.attributes.operating_system == "EOS":
            return await self._async_get_eos_port_channel_states()
        return await self._async_get_fboss_port_channel_states()

    async def capture_pre_snapshot(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
        timestamp: int,
    ) -> Snapshot:
        states = await self._async_get_port_channel_snapshot_data(obj)
        self.logger.info(
            f"Pre-snapshot: Found {len(states)} port-channels on {obj.name}"
        )
        return Snapshot(data=states, timestamp=timestamp)

    async def capture_post_snapshot(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
        timestamp: int,
    ) -> Snapshot:
        states = await self._async_get_port_channel_snapshot_data(obj)
        self.logger.info(
            f"Post-snapshot: Found {len(states)} port-channels on {obj.name}"
        )
        return Snapshot(data=states, timestamp=timestamp)

    async def compare_snapshots(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
        pre_snapshot: Snapshot,
        post_snapshot: Snapshot,
    ) -> hc_types.HealthCheckResult:
        pre_up = {name for name, data in pre_snapshot.data.items() if data["is_up"]}
        post_up = {name for name, data in post_snapshot.data.items() if data["is_up"]}
        went_down = sorted(pre_up - post_up)

        issues = []
        if went_down:
            issues.append(f"Port-channels went down: {', '.join(went_down)}")

        # EOS-specific: check LACP state and LAG feature changes
        if obj.attributes.operating_system == "EOS":
            for pc_name in sorted(post_snapshot.data.keys()):
                post_data = post_snapshot.data[pc_name]
                pre_data = pre_snapshot.data.get(pc_name)

                # New LACP issues that weren't present before the test
                new_lacp_issues = post_data.get("lacp_issues", [])
                if pre_data:
                    pre_lacp = set(pre_data.get("lacp_issues", []))
                    new_lacp_issues = [i for i in new_lacp_issues if i not in pre_lacp]
                if new_lacp_issues:
                    issues.append(
                        f"{pc_name} LACP issues: {'; '.join(new_lacp_issues)}"
                    )

                # LAG feature changed
                if pre_data:
                    pre_lag = pre_data.get("lag_feature", "")
                    post_lag = post_data.get("lag_feature", "")
                    if pre_lag and post_lag and pre_lag != post_lag:
                        issues.append(
                            f"{pc_name} LAG feature changed: {pre_lag} -> {post_lag}"
                        )

        if issues:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=f"Port-channel issues on {obj.name}:\n" + "\n".join(issues),
            )
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
        )
