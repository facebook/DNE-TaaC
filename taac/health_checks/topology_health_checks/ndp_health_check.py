# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import asyncio
import ipaddress
import typing as t

from taac.constants import TestTopology
from taac.health_checks.abstract_health_check import (
    AbstractTopologyHealthCheck,
)
from taac.utils.driver_factory import async_get_device_driver
from taac.health_check.health_check import types as hc_types


class NdpHealthCheck(AbstractTopologyHealthCheck[hc_types.BaseHealthCheckIn]):
    CHECK_NAME = hc_types.CheckName.NDP_CHECK

    async def _run(
        self,
        obj: TestTopology,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        # Get the list of NDP-running switches in the cluster
        # pyre-fixme[16]: `AbstractSwitch` has no attribute
        #  `async_get_dsf_cluster_switch_id_mapping`.
        switch_id_mapping = await (
            await async_get_device_driver(obj.devices[0].name)
        ).async_get_dsf_cluster_switch_id_mapping()
        dsf_nodes_in_cluster = switch_id_mapping.values()
        hostnames = [
            hostname
            for hostname in dsf_nodes_in_cluster
            if hostname in obj.device_names
            and (hostname.startswith("rdsw") or hostname.startswith("edsw"))
        ]
        if not hostnames:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.SKIP,
            )

        hostname_to_driver = {
            hostname: await async_get_device_driver(hostname) for hostname in hostnames
        }

        # Get the NDP tables for all RDSWs and EDSW in the topology
        ndp_tables = await asyncio.gather(
            *[
                # pyre-fixme[16]: `AbstractSwitch` has no attribute
                #  `async_get_ndp_table`.
                hostname_to_driver[hostname].async_get_ndp_table()
                for hostname in hostnames
            ]
        )
        device_ndp_tables = dict(zip(hostnames, ndp_tables))

        # Verify that a STATIC NDP entry exists for each host in the topology
        for hostname, ndp_table in device_ndp_tables.items():
            static_ndp_neighbors = set()
            for ndp_entry in ndp_table:
                if (
                    ndp_entry.state == "STATIC"
                    and switch_id_mapping.get(ndp_entry.switchId)
                    and switch_id_mapping[ndp_entry.switchId] in hostnames
                ):
                    static_ndp_neighbors.add(switch_id_mapping[ndp_entry.switchId])
            static_ndp_discrepancy = set(hostnames) - set(static_ndp_neighbors)
            if static_ndp_discrepancy:
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.FAIL,
                    message=f"Static NDP discrepancy found on {hostname}: {static_ndp_discrepancy} not found in static NDP table",
                )

        # Verify that the number of DYNAMIC NDP entries in a switch matches the number of total REACHABLE NDP entries in other switches
        for hostname, ndp_table in device_ndp_tables.items():
            dynamic_ndp_entries = set()
            reachable_global_ndp_entries = set()
            for ndp_entry in ndp_table:
                if (
                    ndp_entry.state == "DYNAMIC"
                    and switch_id_mapping.get(ndp_entry.switchId)
                    and switch_id_mapping[ndp_entry.switchId] in hostnames
                ):
                    dynamic_ndp_entries.add(ndp_entry)

            for other_hostname, other_ndp_table in device_ndp_tables.items():
                if hostname != other_hostname:
                    for ndp_entry in other_ndp_table:
                        ip = ipaddress.IPv6Address(ndp_entry.ip.addr)
                        # Link local addresses in a switch are not synced with other switches
                        if ndp_entry.state == "REACHABLE" and not ip.is_link_local:
                            reachable_global_ndp_entries.add(ndp_entry)
            if len(dynamic_ndp_entries) != len(reachable_global_ndp_entries):
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.FAIL,
                    message=f"Dynamic NDP mismatch on {hostname}: expected {len(reachable_global_ndp_entries)}, got {len(dynamic_ndp_entries)}",
                )
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
        )
