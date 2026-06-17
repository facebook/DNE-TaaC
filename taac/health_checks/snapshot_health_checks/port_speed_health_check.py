# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
import typing as t

from taac.constants import TestDevice
from taac.health_checks.abstract_snapshot_health_check import (
    AbstractDeviceSnapshotHealthCheck,
    Snapshot,
)
from taac.health_check.health_check import types as hc_types


class PortSpeedHealtchCheck(
    AbstractDeviceSnapshotHealthCheck[hc_types.BaseHealthCheckIn]
):
    CHECK_NAME = hc_types.CheckName.PORT_SPEED_SNAPSHOT_CHECK
    OPERATING_SYSTEMS = ["FBOSS"]

    async def capture_pre_snapshot(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
        timestamp: int,
    ) -> Snapshot:
        endpoints = check_params.get("endpoints", [])
        if not endpoints:
            raise ValueError("No endpoints provided for port speed health check")

        ports = endpoints.get(obj.name, [])
        if not ports:
            raise ValueError(f"No ports provided for {obj.name}")

        # pyrefly: ignore [missing-attribute]
        port_speeds = await self.driver.async_get_interfaces_speed_in_Gbps(ports)
        return Snapshot(data=port_speeds, timestamp=timestamp)

    async def capture_post_snapshot(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
        timestamp: int,
    ) -> Snapshot:
        endpoints = check_params.get("endpoints", [])
        if not endpoints:
            raise ValueError("No endpoints provided for port speed health check")

        ports = endpoints.get(obj.name, [])
        if not ports:
            raise ValueError(f"No ports provided for {obj.name}")

        # pyrefly: ignore [missing-attribute]
        port_speeds = await self.driver.async_get_interfaces_speed_in_Gbps(ports)
        return Snapshot(data=port_speeds, timestamp=timestamp)

    async def compare_snapshots(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
        pre_snapshot: Snapshot,
        post_snapshot: Snapshot,
    ) -> hc_types.HealthCheckResult:
        pre_snapshot_data = pre_snapshot.data
        post_snapshot_data = post_snapshot.data

        if not pre_snapshot_data or not post_snapshot_data:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message="No snapshot data found",
            )

        issues = []

        for port, pre_speed in pre_snapshot_data.items():
            post_speed = post_snapshot_data.get(port, None)
            if not post_speed:
                issues.append(f"Port {port} not found in post snapshot")
            elif pre_speed != post_speed:
                issues.append(
                    f"Port {port} speed has changed. Speed Before Test: {pre_speed // 1000}G and Speed After Test: {post_speed // 1000}G"
                )

        if issues:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=f"Port speed issues detected on device {obj.name}: \n {'\n'.join(issues)}",
            )

        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
            message=f"All {len(pre_snapshot_data)} ports on {obj.name} have expected speed",
        )
