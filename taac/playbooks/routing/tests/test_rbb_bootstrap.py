# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""Tests for the OSS-safe RBB fresh-image bootstrap."""

import copy
import ipaddress
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from taac.driver.driver_constants import FbossSystemctlServiceName
from taac.tasks.rbb_dut_bootstrap_task import (
    BOOTSTRAP_BACKUP_SUFFIX,
    RbbDutBootstrapTask,
)
from taac.tasks.rbb_edge_config_utils import async_remove_file
from taac.testconfigs.routing.util import bgp_rbb_constants as C
from taac.testconfigs.routing.util.bgp_rbb_bootstrap_config import (
    build_bootstrap_documents,
    validate_bootstrap_device_paths,
    validate_bootstrap_topology,
)
from taac.testconfigs.routing.util.bgp_rbb_topology import (
    CorePortChannel,
    NodeTopology,
    RbbTopology,
)

_BOOTSTRAP_MOD = "taac.tasks.rbb_dut_bootstrap_task"


def _base_agent() -> dict:
    ports = [
        {
            "logicalID": 1,
            "name": "eth1/1/1",
            "state": 0,
            "ingressVlan": 2001,
            "portType": 0,
            "routable": True,
            "speed": 400000,
            "profileID": 38,
            "vendorPreserved": "core-a",
        },
        {
            "logicalID": 2,
            "name": "eth1/1/5",
            "state": 0,
            "ingressVlan": 2002,
            "portType": 0,
            "routable": True,
            "speed": 400000,
            "profileID": 38,
            "vendorPreserved": "core-b",
        },
        {
            "logicalID": 3,
            "name": "eth1/2/1",
            "state": 0,
            "ingressVlan": 2003,
            "portType": 0,
            "routable": True,
            "speed": 100000,
            "profileID": 7,
            "vendorPreserved": "unused",
        },
    ]
    return {
        "defaultCommandLineArgs": {"multi_switch": "true"},
        "platform": {"chip": {"asic": "image-owned"}},
        "sw": {
            "ports": ports,
            "vlans": [
                {
                    "id": port["ingressVlan"],
                    "name": f"Vlan{port['ingressVlan']}",
                    "recordStats": True,
                    "routable": True,
                    "ipAddresses": [],
                }
                for port in ports
            ],
            "interfaces": [
                {
                    "intfID": port["ingressVlan"],
                    "vlanID": port["ingressVlan"],
                    "ipAddresses": [],
                    "mtu": 9000,
                    "isVirtual": False,
                    "isStateSyncDisabled": True,
                    "type": 1,
                    "scope": 0,
                    "routerID": 0,
                }
                for port in ports
            ],
            "vlanPorts": [
                {
                    "vlanID": port["ingressVlan"],
                    "logicalPort": port["logicalID"],
                    "spanningTreeState": 2,
                    "emitTags": False,
                }
                for port in ports
            ],
            "aggregatePorts": [],
            "staticRoutesWithNhops": [
                {"prefix": "2001:db8:ffff::/64", "nexthops": ["2001:db8::1"]}
            ],
            "clientIdToAdminDistance": {
                "0": 20,
                "1": 1,
                "2": 0,
                "3": 0,
                "700": 255,
                "786": 10,
            },
            "switchSettings": {"imageOwned": True},
        },
    }


def _base_bgp() -> dict:
    return {
        "router_id": "REPLACE_ROUTER_ID",
        "local_as_4_byte": 65001,
        "hold_time": 30,
        "listen_addr": "::",
        "listen_port": 179,
        "net_service_config": {
            "net_service_identity": "BgpdService",
            "net_static_file_acl": "/usr/facebook/thrift_acls/dummy_acl.json",
            "preserved": True,
        },
        "peer_groups": [],
        "peers": [],
        "networks4": [],
        "networks6": [],
    }


def _base_openr() -> dict:
    return {
        "node_name": "REPLACE_NODE_NAME",
        "domain": "fboss",
        "areas": [
            {
                "area_id": "0",
                "neighbor_regexes": [".*"],
                "include_interface_regexes": ["eth[0-9].*"],
                "exclude_interface_regexes": [],
                "redistribute_interface_regexes": ["lo"],
                "preserved": True,
            }
        ],
        "fib_port": 5909,
        "spark_config": {"hello_time_s": 20},
    }


def _core_pcs() -> tuple[CorePortChannel, ...]:
    return (
        CorePortChannel("port-channel161", ("eth1/1/1",)),
        CorePortChannel("port-channel162", ("eth1/1/5",)),
    )


def _topology(*, multi_member: bool = False) -> RbbTopology:
    members = ("eth1/1/1", "eth1/1/5") if multi_member else ("eth1/1/1",)
    return RbbTopology(
        r1=NodeTopology(
            role="r1",
            hostname="rbb-r1.lab.local",
            core_pcs=(CorePortChannel("port-channel161", members),),
        ),
        r2=NodeTopology(
            role="r2",
            hostname="rbb-r2.lab.local",
            core_pcs=(CorePortChannel("port-channel161", members),),
        ),
    )


class RbbBootstrapBuilderTest(unittest.TestCase):
    def test_stock_config_is_patched_narrowly(self) -> None:
        base = _base_agent()
        base_bgp = _base_bgp()
        base_bgp["bgp_setting_config"] = {"imageOwned": True}
        docs = build_bootstrap_documents(
            base_agent=base,
            base_bgp=base_bgp,
            base_openr=_base_openr(),
            role="r1",
            core_pcs=_core_pcs(),
        )
        self.assertEqual(base["sw"]["ports"][0]["state"], 0)
        self.assertEqual(docs.agent["platform"], base["platform"])
        self.assertEqual(
            docs.agent["defaultCommandLineArgs"], base["defaultCommandLineArgs"]
        )
        self.assertEqual(
            {
                key
                for key in set(base) | set(docs.agent)
                if base.get(key) != docs.agent.get(key)
            },
            {"sw"},
        )
        self.assertEqual(
            {
                key
                for key in set(base["sw"]) | set(docs.agent["sw"])
                if base["sw"].get(key) != docs.agent["sw"].get(key)
            },
            {
                "aggregatePorts",
                "interfaces",
                "mySidConfig",
                "ports",
                "srv6Tunnels",
                "staticRoutesWithNhops",
                "vlans",
            },
        )
        self.assertEqual(
            docs.agent["sw"]["clientIdToAdminDistance"],
            base["sw"]["clientIdToAdminDistance"],
        )
        ports = {port["name"]: port for port in docs.agent["sw"]["ports"]}
        self.assertEqual(ports["eth1/1/1"]["state"], 2)
        self.assertEqual(ports["eth1/1/5"]["state"], 2)
        self.assertEqual(ports["eth1/2/1"], base["sw"]["ports"][2])
        self.assertEqual(ports["eth1/1/1"]["profileID"], 38)
        self.assertEqual(ports["eth1/1/1"]["vendorPreserved"], "core-a")

        aggregates = docs.agent["sw"]["aggregatePorts"]
        self.assertEqual([aggregate["key"] for aggregate in aggregates], [161, 162])
        self.assertEqual(aggregates[0]["memberPorts"][0]["memberPortID"], 1)
        self.assertEqual(
            aggregates[0]["minimumCapacityToUp"], {"linkPercentage": 0.75}
        )
        self.assertEqual(
            docs.openr["areas"][0]["include_interface_regexes"],
            ["^fboss2001$", "^fboss2002$"],
        )
        self.assertEqual(
            docs.openr["areas"][0]["redistribute_interface_regexes"],
            ["lo", "^fboss4000$"],
        )
        self.assertTrue(docs.openr["areas"][0]["preserved"])
        self.assertEqual(docs.bgp["router_id"], C.R1_ROUTER_ID)
        self.assertEqual(docs.bgp["peers"][0]["peer_addr"], C.R2_ROUTER_ID)
        self.assertTrue(docs.bgp["net_service_config"]["preserved"])
        self.assertEqual(docs.bgp["bgp_setting_config"], {"imageOwned": True})
        self.assertIn(
            "fe80::2001:1/64",
            next(
                interface["ipAddresses"]
                for interface in docs.agent["sw"]["interfaces"]
                if interface["intfID"] == 2001
            ),
        )

    def test_srv6_schema_uses_current_fields_and_derived_mysid_keys(self) -> None:
        r1 = build_bootstrap_documents(
            base_agent=_base_agent(),
            base_bgp=_base_bgp(),
            base_openr=_base_openr(),
            role="r1",
            core_pcs=_core_pcs(),
        )
        r2 = build_bootstrap_documents(
            base_agent=_base_agent(),
            base_bgp=_base_bgp(),
            base_openr=_base_openr(),
            role="r2",
            core_pcs=_core_pcs(),
        )
        tunnel = r1.agent["sw"]["srv6Tunnels"][0]
        self.assertTrue({"ttlMode", "dscpMode", "ecnMode"}.issubset(tunnel))
        self.assertFalse({"ttl", "dscp", "ecn"} & set(tunnel))
        self.assertEqual(tunnel["underlayIntfID"], C.SRV6_SID_VLAN_B)
        self.assertEqual(
            set(r1.agent["sw"]["mySidConfig"]["entries"]),
            {str(0x27CC)},
        )
        self.assertEqual(
            set(r2.agent["sw"]["mySidConfig"]["entries"]),
            {str(0x27D6), str(0x7FFF)},
        )
        self.assertEqual(
            r2.agent["sw"]["mySidConfig"]["entries"][str(0x27D6)][
                "adjacency"
            ]["portName"],
            "Port-Channel162",
        )

    def test_device_only_tail_route_is_bgpd_originated_with_decap_next_hop(self) -> None:
        docs = build_bootstrap_documents(
            base_agent=_base_agent(),
            base_bgp=_base_bgp(),
            base_openr=_base_openr(),
            role="r2",
            core_pcs=_core_pcs(),
        )
        self.assertIn(
            C.TAIL_DEST_PREFIX,
            [network["prefix"] for network in docs.bgp["networks6"]],
        )
        tail_network = next(
            network
            for network in docs.bgp["networks6"]
            if network["prefix"] == C.TAIL_DEST_PREFIX
        )
        self.assertEqual(tail_network["nexthop"], C.SRV6_DECAP_SID)
        self.assertFalse(tail_network["install_to_fib"])
        self.assertFalse(docs.bgp["peer_groups"][0]["next_hop_self"])
        self.assertEqual(docs.bgp["peers"][0]["next_hop6"], C.R2_LOOPBACK_V6)
        self.assertEqual(
            docs.agent["sw"]["staticRoutesWithNhops"],
            _base_agent()["sw"]["staticRoutesWithNhops"],
        )

    def test_traffic_mode_adds_only_the_r2_ixia_return_route(self) -> None:
        docs = build_bootstrap_documents(
            base_agent=_base_agent(),
            base_bgp=_base_bgp(),
            base_openr=_base_openr(),
            role="r2",
            core_pcs=_core_pcs(),
            include_traffic=True,
        )
        self.assertNotIn(
            C.TAIL_DEST_PREFIX,
            [network["prefix"] for network in docs.bgp["networks6"]],
        )
        added_routes = docs.agent["sw"]["staticRoutesWithNhops"][1:]
        self.assertEqual(len(added_routes), 1)
        self.assertEqual(
            added_routes[0]["prefix"],
            str(
                ipaddress.ip_network(
                    f"{C.IXIA_R1_EDGE_V6}/{C.IXIA_EDGE_PREFIX_MASK}", strict=False
                )
            ),
        )

    def test_fresh_image_builder_refuses_preconfigured_state(self) -> None:
        agent = _base_agent()
        agent["sw"]["interfaces"][0]["ipAddresses"] = ["10.0.0.1/31"]
        with self.assertRaisesRegex(ValueError, "already has RIF addresses"):
            build_bootstrap_documents(
                base_agent=agent,
                base_bgp=_base_bgp(),
                base_openr=_base_openr(),
                role="r1",
                core_pcs=_core_pcs(),
            )

        bgp = _base_bgp()
        bgp["peers"] = [{"peer_addr": "192.0.2.100"}]
        with self.assertRaisesRegex(ValueError, "already contains routing state"):
            build_bootstrap_documents(
                base_agent=_base_agent(),
                base_bgp=bgp,
                base_openr=_base_openr(),
                role="r1",
                core_pcs=_core_pcs(),
            )

        bgp = _base_bgp()
        bgp["router_id"] = "192.0.2.99"
        with self.assertRaisesRegex(ValueError, "not the fresh-image placeholder"):
            build_bootstrap_documents(
                base_agent=_base_agent(),
                base_bgp=bgp,
                base_openr=_base_openr(),
                role="r1",
                core_pcs=_core_pcs(),
            )

        openr = _base_openr()
        openr["node_name"] = "operator-owned-node"
        with self.assertRaisesRegex(ValueError, "not the fresh-image placeholder"):
            build_bootstrap_documents(
                base_agent=_base_agent(),
                base_bgp=_base_bgp(),
                base_openr=openr,
                role="r1",
                core_pcs=_core_pcs(),
            )

    def test_stock_enabled_port_without_logical_state_is_supported(self) -> None:
        agent = _base_agent()
        agent["sw"]["ports"][0]["state"] = 2
        docs = build_bootstrap_documents(
            base_agent=agent,
            base_bgp=_base_bgp(),
            base_openr=_base_openr(),
            role="r1",
            core_pcs=_core_pcs(),
        )
        selected = next(
            port
            for port in docs.agent["sw"]["ports"]
            if port["name"] == "eth1/1/1"
        )
        self.assertEqual(selected["state"], 2)

    def test_bootstrap_refuses_a_shared_selected_ingress_vlan(self) -> None:
        agent = _base_agent()
        agent["sw"]["ports"][2]["ingressVlan"] = 2001
        agent["sw"]["vlanPorts"][2]["vlanID"] = 2001
        with self.assertRaisesRegex(ValueError, "shared ingress VLAN"):
            build_bootstrap_documents(
                base_agent=agent,
                base_bgp=_base_bgp(),
                base_openr=_base_openr(),
                role="r1",
                core_pcs=_core_pcs(),
            )

    def test_bootstrap_topology_fails_closed_for_multi_member_lag(self) -> None:
        with self.assertRaisesRegex(ValueError, "exactly one member"):
            validate_bootstrap_topology(_topology(multi_member=True))

    def test_bootstrap_topology_requires_numeric_port_channel_name(self) -> None:
        topology = _topology()
        invalid = RbbTopology(
            r1=NodeTopology(
                role="r1",
                hostname=topology.r1.hostname,
                core_pcs=(CorePortChannel("core-lag", ("eth1/1/1",)),),
            ),
            r2=topology.r2,
        )
        with self.assertRaisesRegex(ValueError, "port-channel<N>"):
            validate_bootstrap_topology(invalid)

    def test_bootstrap_device_paths_reject_shell_active_override(self) -> None:
        with self.assertRaisesRegex(ValueError, "canonical absolute paths"):
            validate_bootstrap_device_paths(("/etc/coop/agent.conf;reboot",))
        with self.assertRaisesRegex(ValueError, "recovery/staging artifact"):
            validate_bootstrap_device_paths(
                ("/etc/coop/agent.conf.taac-rbb-bootstrap-orig",)
            )


class RbbDutBootstrapTaskTest(unittest.IsolatedAsyncioTestCase):
    def _driver(self) -> MagicMock:
        driver = MagicMock()
        driver.async_check_if_file_exists = AsyncMock(return_value=False)
        driver.async_run_cmd_on_shell = AsyncMock(
            side_effect=lambda command: (
                "0\n"
                if command == "id -u"
                else "absent\n"
                if command.startswith("if [ -e ")
                else "ActiveState=active\n"
            )
        )
        driver.async_write_file_on_device = AsyncMock()
        driver.async_read_file = AsyncMock()
        driver.async_agent_config_reload = AsyncMock()
        driver.async_wait_for_agent_state_configured = AsyncMock()
        driver.async_restart_service = AsyncMock()
        driver.async_start_service = AsyncMock()
        driver.async_stop_service = AsyncMock()
        driver.async_get_interfaces_operational_state = AsyncMock(
            return_value={pc.members[0]: True for pc in _core_pcs()}
        )
        peer = MagicMock(peer_addr=C.R1_ROUTER_ID)
        peer.peer.peer_state.name = "ESTABLISHED"
        driver.async_get_bgp_sessions = AsyncMock(return_value=[peer])
        return driver

    async def test_apply_validates_then_uses_service_runtime_state(self) -> None:
        task = RbbDutBootstrapTask(hostname="rbb-r2", logger=MagicMock())
        driver = self._driver()
        documents = build_bootstrap_documents(
            base_agent=_base_agent(),
            base_bgp=_base_bgp(),
            base_openr=_base_openr(),
            role="r2",
            core_pcs=_core_pcs(),
        )
        policy = {
            "policies": {},
            "prefix_sets": {},
            "as_path_sets": {},
            "community_sets": {},
        }
        read_values = {
            C.AGENT_CONFIG_PATH: _base_agent(),
            C.OPENR_CONFIG_PATH: _base_openr(),
            C.BGP_CONFIG_PATH: _base_bgp(),
            C.BGP_POLICY_PATH: policy,
        }
        with patch(
            f"{_BOOTSTRAP_MOD}.async_get_device_driver",
            new_callable=AsyncMock,
            return_value=driver,
        ), patch.object(
            task,
            "_read_json",
            new_callable=AsyncMock,
            side_effect=lambda _driver, _host, path: copy.deepcopy(
                read_values[path.removesuffix(BOOTSTRAP_BACKUP_SUFFIX)]
            ),
        ), patch.object(
            task,
            "_active_state",
            new_callable=AsyncMock,
            side_effect=(
                "active",
                "active",
                "inactive",
                "active",
                "active",
                "inactive",
            ),
        ), patch.object(
            task,
            "_file_mode",
            new_callable=AsyncMock,
            side_effect=("644", "600", "600", "644", "600", "600"),
        ), patch.object(
            task,
            "_file_owner",
            new_callable=AsyncMock,
            side_effect=("0:0", "0:0", "0:0", "0:0", "0:0", "0:0"),
        ), patch.object(
            task,
            "_set_file_mode",
            new_callable=AsyncMock,
        ), patch.object(
            task,
            "_set_file_owner",
            new_callable=AsyncMock,
        ), patch(
            f"{_BOOTSTRAP_MOD}.async_guard_snapshot_set",
            new_callable=AsyncMock,
        ), patch(
            f"{_BOOTSTRAP_MOD}.async_backup_before_overwrite",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            f"{_BOOTSTRAP_MOD}.async_write_json_file",
            new_callable=AsyncMock,
        ) as write_json, patch(
            "taac.utils.json_thrift_utils.json_to_thrift"
        ) as validate_thrift:
            await task.run(
                {
                    "hostname": "rbb-r2",
                    "role": "r2",
                    "core_port_channels": [
                        {"name": pc.name, "members": list(pc.members)}
                        for pc in _core_pcs()
                    ],
                }
            )
        self.assertEqual(validate_thrift.call_count, 2)
        # Recovery state (snapshotting + ready) and three configs are written.
        self.assertEqual(write_json.await_count, 5)
        written_documents = [call.args[2] for call in write_json.await_args_list]
        self.assertIn(documents.agent, written_documents)
        driver.async_agent_config_reload.assert_awaited_once()
        driver.async_restart_service.assert_awaited_once_with(
            FbossSystemctlServiceName.OPENR
        )
        driver.async_start_service.assert_awaited_once_with(
            FbossSystemctlServiceName.BGP
        )
        driver.async_get_interfaces_operational_state.assert_awaited_once()
        driver.async_get_bgp_sessions.assert_awaited_once()

    async def test_restore_preserves_artifacts_until_services_are_restored(self) -> None:
        task = RbbDutBootstrapTask(hostname="rbb-r1", logger=MagicMock())
        driver = self._driver()
        state = {
            "version": 1,
            "hostname": "rbb-r1",
            "phase": "ready",
            "changed_paths": list(
                (C.AGENT_CONFIG_PATH, C.OPENR_CONFIG_PATH, C.BGP_CONFIG_PATH)
            ),
            "service_active_state": {
                "agent": "active",
                "openr": "active",
                "bgp": "inactive",
            },
            "file_modes": {
                C.AGENT_CONFIG_PATH: "644",
                C.OPENR_CONFIG_PATH: "600",
                C.BGP_CONFIG_PATH: "600",
            },
            "file_owners": {
                C.AGENT_CONFIG_PATH: "0:0",
                C.OPENR_CONFIG_PATH: "0:0",
                C.BGP_CONFIG_PATH: "0:0",
            },
        }
        with patch(
            f"{_BOOTSTRAP_MOD}.async_get_device_driver",
            new_callable=AsyncMock,
            return_value=driver,
        ), patch(
            f"{_BOOTSTRAP_MOD}.async_read_file_or_none",
            new_callable=AsyncMock,
            return_value=json.dumps(state),
        ), patch(
            f"{_BOOTSTRAP_MOD}.async_restore_backup",
            new_callable=AsyncMock,
            return_value=True,
        ) as restore, patch(
            f"{_BOOTSTRAP_MOD}.async_discard_backup",
            new_callable=AsyncMock,
        ) as discard, patch(
            f"{_BOOTSTRAP_MOD}.async_write_json_file",
            new_callable=AsyncMock,
        ) as write_json, patch(
            f"{_BOOTSTRAP_MOD}.async_remove_file",
            new_callable=AsyncMock,
        ) as remove, patch.object(
            task,
            "_set_file_mode",
            new_callable=AsyncMock,
        ) as set_mode, patch.object(
            task,
            "_set_file_owner",
            new_callable=AsyncMock,
        ) as set_owner:
            await task.run({"hostname": "rbb-r1", "action": "restore"})
        self.assertEqual(restore.await_count, 3)
        driver.async_stop_service.assert_awaited_once_with(
            FbossSystemctlServiceName.BGP
        )
        driver.async_restart_service.assert_awaited_once_with(
            FbossSystemctlServiceName.OPENR
        )
        driver.async_agent_config_reload.assert_awaited_once()
        self.assertEqual(write_json.await_args.args[2]["phase"], "restored")
        self.assertEqual(discard.await_count, 3)
        self.assertEqual(set_mode.await_count, 3)
        self.assertEqual(set_owner.await_count, 3)
        remove.assert_awaited_once_with(driver, C.BOOTSTRAP_STATE_PATH)

    async def test_restore_allows_service_only_transaction(self) -> None:
        task = RbbDutBootstrapTask(hostname="rbb-r1", logger=MagicMock())
        driver = self._driver()
        state = {
            "version": 1,
            "hostname": "rbb-r1",
            "phase": "ready",
            "changed_paths": [],
            "service_active_state": {
                "agent": "inactive",
                "openr": "inactive",
                "bgp": "inactive",
            },
            "file_modes": {
                C.AGENT_CONFIG_PATH: "644",
                C.OPENR_CONFIG_PATH: "600",
                C.BGP_CONFIG_PATH: "600",
            },
            "file_owners": {
                C.AGENT_CONFIG_PATH: "0:0",
                C.OPENR_CONFIG_PATH: "0:0",
                C.BGP_CONFIG_PATH: "0:0",
            },
        }
        with patch(
            f"{_BOOTSTRAP_MOD}.async_get_device_driver",
            new_callable=AsyncMock,
            return_value=driver,
        ), patch(
            f"{_BOOTSTRAP_MOD}.async_read_file_or_none",
            new_callable=AsyncMock,
            return_value=json.dumps(state),
        ), patch(
            f"{_BOOTSTRAP_MOD}.async_restore_backup",
            new_callable=AsyncMock,
        ) as restore, patch(
            f"{_BOOTSTRAP_MOD}.async_discard_backup",
            new_callable=AsyncMock,
        ) as discard, patch(
            f"{_BOOTSTRAP_MOD}.async_write_json_file",
            new_callable=AsyncMock,
        ), patch(
            f"{_BOOTSTRAP_MOD}.async_remove_file",
            new_callable=AsyncMock,
        ) as remove:
            await task.run({"hostname": "rbb-r1", "action": "restore"})

        restore.assert_not_awaited()
        discard.assert_not_awaited()
        self.assertEqual(driver.async_stop_service.await_count, 3)
        driver.async_restart_service.assert_not_awaited()
        remove.assert_awaited_once_with(driver, C.BOOTSTRAP_STATE_PATH)

    async def test_stale_recovery_state_blocks_before_read_or_write(self) -> None:
        task = RbbDutBootstrapTask(hostname="rbb-r1", logger=MagicMock())
        driver = self._driver()
        driver.async_check_if_file_exists = AsyncMock(return_value=True)
        with patch(
            f"{_BOOTSTRAP_MOD}.async_get_device_driver",
            new_callable=AsyncMock,
            return_value=driver,
        ):
            with self.assertRaisesRegex(Exception, "recovery state already exists"):
                await task.run(
                    {
                        "hostname": "rbb-r1",
                        "role": "r1",
                        "core_port_channels": [
                            {"name": "port-channel161", "members": ["eth1/1/1"]}
                        ],
                    }
                )
        driver.async_write_file_on_device.assert_not_awaited()

    async def test_non_root_session_is_rejected_before_device_file_access(self) -> None:
        task = RbbDutBootstrapTask(hostname="rbb-r1", logger=MagicMock())
        driver = self._driver()
        driver.async_run_cmd_on_shell = AsyncMock(return_value="1000\n")
        with patch(
            f"{_BOOTSTRAP_MOD}.async_get_device_driver",
            new_callable=AsyncMock,
            return_value=driver,
        ):
            with self.assertRaisesRegex(Exception, "requires a root SSH account"):
                await task.run(
                    {
                        "hostname": "rbb-r1",
                        "role": "r1",
                        "core_port_channels": [
                            {"name": "port-channel161", "members": ["eth1/1/1"]}
                        ],
                    }
                )
        driver.async_check_if_file_exists.assert_not_awaited()
        driver.async_write_file_on_device.assert_not_awaited()

    async def test_incomplete_prewrite_snapshot_is_safely_discarded(self) -> None:
        task = RbbDutBootstrapTask(hostname="rbb-r1", logger=MagicMock())
        driver = self._driver()
        state = {
            "version": 1,
            "hostname": "rbb-r1",
            "phase": "snapshotting",
            "changed_paths": [C.AGENT_CONFIG_PATH, C.OPENR_CONFIG_PATH],
            "service_active_state": {
                "agent": "active",
                "openr": "active",
                "bgp": "inactive",
            },
            "file_modes": {
                C.AGENT_CONFIG_PATH: "644",
                C.OPENR_CONFIG_PATH: "600",
                C.BGP_CONFIG_PATH: "600",
            },
            "file_owners": {
                C.AGENT_CONFIG_PATH: "0:0",
                C.OPENR_CONFIG_PATH: "0:0",
                C.BGP_CONFIG_PATH: "0:0",
            },
        }
        with patch(
            f"{_BOOTSTRAP_MOD}.async_get_device_driver",
            new_callable=AsyncMock,
            return_value=driver,
        ), patch(
            f"{_BOOTSTRAP_MOD}.async_read_file_or_none",
            new_callable=AsyncMock,
            return_value=json.dumps(state),
        ), patch(
            f"{_BOOTSTRAP_MOD}.async_discard_backup",
            new_callable=AsyncMock,
        ) as discard, patch(
            f"{_BOOTSTRAP_MOD}.async_remove_file",
            new_callable=AsyncMock,
        ) as remove, patch(
            f"{_BOOTSTRAP_MOD}.async_restore_backup",
            new_callable=AsyncMock,
        ) as restore:
            await task.run({"hostname": "rbb-r1", "action": "restore"})
        self.assertEqual(discard.await_count, 2)
        remove.assert_awaited_once_with(driver, C.BOOTSTRAP_STATE_PATH)
        restore.assert_not_awaited()
        driver.async_restart_service.assert_not_awaited()
        driver.async_stop_service.assert_not_awaited()

    def test_recovery_suffix_is_independent_from_edge_overlay(self) -> None:
        self.assertEqual(BOOTSTRAP_BACKUP_SUFFIX, ".taac-rbb-bootstrap-orig")

    async def test_recovery_artifact_removal_is_verified(self) -> None:
        driver = self._driver()
        driver.async_run_cmd_on_shell = AsyncMock(return_value="present\n")
        with self.assertRaisesRegex(Exception, "failed to remove on-device file"):
            await async_remove_file(driver, "/var/tmp/taac-recovery-state.json")


if __name__ == "__main__":
    unittest.main()
