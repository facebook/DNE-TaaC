# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import asyncio
import typing as t

from neteng.fboss.ctrl.thrift_types import DsfSessionState
from taac.constants import TestTopology
from taac.health_checks.abstract_health_check import (
    AbstractTopologyHealthCheck,
)
from taac.utils.driver_factory import async_get_device_driver
from taac.health_check.health_check import types as hc_types


class DsfFsdbSessionHealthCheck(
    AbstractTopologyHealthCheck[hc_types.BaseHealthCheckIn]
):
    CHECK_NAME = hc_types.CheckName.DSF_FSDB_SESSION_CHECK
    OPERATING_SYSTEMS = ["FBOSS"]

    async def _run(
        self,
        obj: TestTopology,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        # Prepare list of devices in topology
        # pyre-fixme[16]: `AbstractSwitch` has no attribute
        #  `async_get_dsf_cluster_switch_id_mapping`.
        switch_id_mapping = await (
            await async_get_device_driver(obj.devices[0].name)
        ).async_get_dsf_cluster_switch_id_mapping()
        dsf_nodes_in_cluster = set(switch_id_mapping.values())

        fsdb_device_names = [
            device_name
            for device_name in dsf_nodes_in_cluster
            # obj.device_names is the list of device names in test config endpoints
            if device_name in obj.device_names and self._has_dsf_session(device_name)
        ]
        if not fsdb_device_names:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.SKIP,
            )

        device_name_to_driver = {
            device_name: await async_get_device_driver(device_name)
            for device_name in fsdb_device_names
        }

        # Get the DSF sessions in all switches
        dsf_sessions = await asyncio.gather(
            *[
                # pyre-fixme[16]: `AbstractSwitch` has no attribute
                #  `async_get_dsf_sessions`.
                device_name_to_driver[device_name].async_get_dsf_sessions()
                for device_name in fsdb_device_names
            ]
        )

        # Verify that all DSF sessions are established towards other switches
        for device_name, dsf_session in zip(fsdb_device_names, dsf_sessions):
            remote_device_names = set()
            expected_remote_device_names = set(fsdb_device_names) - {device_name}
            for session_entry in dsf_session:
                remote_device_name = session_entry.remoteName.split("::")[0]
                remote_device_names.add(remote_device_name)
                if (
                    remote_device_name in fsdb_device_names
                    and session_entry.state != DsfSessionState.ESTABLISHED
                ):
                    return hc_types.HealthCheckResult(
                        status=hc_types.HealthCheckStatus.FAIL,
                        message=f"DSF session is not established from {device_name} towards {remote_device_name}",
                    )

            devices_without_session_info = (
                expected_remote_device_names - remote_device_names
            )
            if len(devices_without_session_info) > 0:
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.FAIL,
                    message=f"DSF session entry not found from {device_name} towards {devices_without_session_info}",
                )

        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
        )

    def _has_dsf_session(self, device_name: str) -> bool:
        return device_name.startswith("rdsw") or device_name.startswith("edsw")
