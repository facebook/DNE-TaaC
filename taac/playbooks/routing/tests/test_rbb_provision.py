# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""Unit tests for the RBB from-scratch FBOSS provisioning path.

Covers the pure generators (platform-mapping resolver, provisioning plan,
agent.conf / bgp.json / openr.conf builders) and the three ``provision_fboss_*``
tasks' skip / backup / write / guard behavior with a mock driver.

Lives under ``taac/playbooks/routing/tests`` because that is the OSS-collected
test home (``taac/tasks`` and ``testconfigs`` trees are excluded from
collection); the modules under test keep their real homes.
"""

import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from taac.constants import TestCaseFailure
from taac.testconfigs.routing.util.bgp_rbb_topology import (
    CorePortChannel,
    IxiaEdge,
    NodeTopology,
    RbbTopology,
)
from taac.testconfigs.routing.util.fboss_config_gen.agent_config import (
    build_agent_config,
    build_switch_config,
)
from taac.testconfigs.routing.util.fboss_config_gen.bgp_config import (
    build_bgp_config,
    build_policy_config,
    IBGP_PEER_GROUP,
)
from taac.testconfigs.routing.util.fboss_config_gen.openr_config import (
    build_openr_config,
)
from taac.testconfigs.routing.util.fboss_config_gen.platform_mapping import (
    all_ports,
    parse_platform_mapping,
    resolve_port,
)
from taac.testconfigs.routing.util.fboss_config_gen.provision_plan import (
    build_rbb_provision_plan,
)


# ─── Fixtures ──────────────────────────────────────────────────────────────
def _mapping_fixture() -> dict:
    """A tiny platform mapping: edges eth1/1/1(1) eth1/1/5(2), core eth1/6/1(11)
    eth1/6/5(12), plus one spare, each 400G (profile 38)."""
    def port(pid, name, profiles=("38", "25")):
        return {
            "key": str(pid),
            "value": {
                "mapping": {"id": pid, "name": name},
                "supportedProfiles": {p: {} for p in profiles},
            },
        }

    ports = {
        str(p["value"]["mapping"]["id"]): p["value"]
        for p in [
            port(1, "eth1/1/1"),
            port(2, "eth1/1/5"),
            port(11, "eth1/6/1"),
            port(12, "eth1/6/5"),
            port(20, "eth1/2/1"),
        ]
    }
    return {"ports": ports, "chips": {}, "platformSupportedProfiles": []}


def _topology_fixture() -> RbbTopology:
    r1 = NodeTopology(
        role="r1",
        hostname="rbb-r1",
        core_pcs=(
            CorePortChannel(name="port-channel161", members=("eth1/6/1",)),
            CorePortChannel(name="port-channel162", members=("eth1/6/5",)),
        ),
        ixia_edges=(
            IxiaEdge(dut_interface="eth1/1/1", ixia_port="1/3"),
            IxiaEdge(dut_interface="eth1/1/5", ixia_port="1/4"),
        ),
    )
    r2 = NodeTopology(
        role="r2",
        hostname="rbb-r2",
        core_pcs=(
            CorePortChannel(name="port-channel161", members=("eth1/6/1",)),
            CorePortChannel(name="port-channel162", members=("eth1/6/5",)),
        ),
        ixia_edges=(IxiaEdge(dut_interface="eth1/1/1", ixia_port="1/10"),),
    )
    return RbbTopology(r1=r1, r2=r2, ixia_chassis="rbb-ixia")


def _agent_conf_fixture(asic_type: int = 15) -> dict:
    return {
        "defaultCommandLineArgs": {"enable_stats_update_thread": "true"},
        "platform": {"chip": {"bcm": {}}, "platformSettings": {}},
        "sw": {
            "switchSettings": {
                "switchType": 0,
                "switchIdToSwitchInfo": {
                    "0": {"asicType": asic_type, "switchIndex": 0}
                },
            },
            "ports": [{"logicalID": 11, "name": "eth1/6/1", "pfc": {"tx": False}}],
            "cpuQueues": [{"id": 0}],
        },
    }


# ─── Platform mapping ──────────────────────────────────────────────────────
class PlatformMappingTest(unittest.TestCase):
    def test_parse_and_resolve(self) -> None:
        pm = parse_platform_mapping(_mapping_fixture())
        self.assertEqual(resolve_port(pm, "eth1/6/1"), (11, 38))
        self.assertEqual(resolve_port(pm, "eth1/1/1"), (1, 38))
        self.assertEqual(len(all_ports(pm)), 5)
        # all_ports sorted by logical id
        self.assertEqual([p.logical_id for p in all_ports(pm)], [1, 2, 11, 12, 20])

    def test_resolve_unknown_raises(self) -> None:
        pm = parse_platform_mapping(_mapping_fixture())
        with self.assertRaises(KeyError):
            resolve_port(pm, "eth9/9/9")


# ─── Provisioning plan ─────────────────────────────────────────────────────
class ProvisionPlanTest(unittest.TestCase):
    def setUp(self) -> None:
        self.pm = parse_platform_mapping(_mapping_fixture())
        self.plans = build_rbb_provision_plan(_topology_fixture(), self.pm)

    def test_roles_and_as(self) -> None:
        self.assertEqual(set(self.plans), {"r1", "r2"})
        r1, r2 = self.plans["r1"], self.plans["r2"]
        self.assertEqual(r1.local_as, r2.local_as)  # single iBGP AS
        # router-id is the far peer's loopback for the other node
        self.assertEqual(r1.peer_loopback_v4, r2.router_id)
        self.assertEqual(r2.peer_loopback_v4, r1.router_id)

    def test_rif_vlan_scheme(self) -> None:
        r1 = self.plans["r1"]
        vlans = {r.vlan_id for r in r1.rifs}
        # loopback 4000, SRv6 SID 10/11
        self.assertIn(4000, vlans)
        self.assertIn(10, vlans)
        self.assertIn(11, vlans)
        # core RIF VLAN = 2000 + member port id (eth1/6/1=11, eth1/6/5=12)
        self.assertIn(2011, vlans)
        self.assertIn(2012, vlans)
        # edge RIF VLAN = 2000 + edge port id (eth1/1/1=1, eth1/1/5=2)
        self.assertIn(2001, vlans)
        self.assertIn(2002, vlans)

    def test_agg_ports_from_core_members(self) -> None:
        r1 = self.plans["r1"]
        names = {a.name for a in r1.agg_ports}
        self.assertEqual(names, {"Port-Channel161", "Port-Channel162"})
        pc161 = next(a for a in r1.agg_ports if a.name == "Port-Channel161")
        self.assertEqual(pc161.member_port_ids, (11,))

    def test_tail_has_decap_head_does_not(self) -> None:
        r1 = self.plans["r1"]
        r2 = self.plans["r2"]
        self.assertFalse(any(e.behavior == "decap" for e in r1.mysid_entries))
        self.assertTrue(any(e.behavior == "decap" for e in r2.mysid_entries))
        self.assertTrue(any(e.behavior == "adjacency" for e in r1.mysid_entries))

    def test_static_route_present(self) -> None:
        self.assertTrue(self.plans["r1"].static_routes)
        self.assertTrue(self.plans["r2"].static_routes)


# ─── agent.conf builder ────────────────────────────────────────────────────
class AgentConfigTest(unittest.TestCase):
    def setUp(self) -> None:
        self.pm = parse_platform_mapping(_mapping_fixture())
        self.plans = build_rbb_provision_plan(_topology_fixture(), self.pm)

    def test_switch_config_ports_and_vlans(self) -> None:
        sw = build_switch_config(self.plans["r1"], self.pm)
        # one port per mapping entry
        self.assertEqual(len(sw["ports"]), 5)
        # per-port VLAN + interface, plus 3 virtual RIFs (loopback + 2 SID)
        self.assertEqual(len(sw["vlans"]), 5 + 3)
        self.assertEqual(len(sw["interfaces"]), 5 + 3)
        self.assertEqual(len(sw["vlanPorts"]), 5)
        # port ingress vlan = 2000 + id
        p11 = next(p for p in sw["ports"] if p["logicalID"] == 11)
        self.assertEqual(p11["ingressVlan"], 2011)
        self.assertEqual(p11["profileID"], 38)

    def test_rif_ips_land_on_core_vlan(self) -> None:
        sw = build_switch_config(self.plans["r1"], self.pm)
        intf2011 = next(i for i in sw["interfaces"] if i["intfID"] == 2011)
        self.assertTrue(intf2011["ipAddresses"])  # core RIF has IPs
        intf2020 = next(i for i in sw["interfaces"] if i["intfID"] == 2020)
        self.assertEqual(intf2020["ipAddresses"], [])  # spare port, no RIF

    def test_srv6_and_static_and_agg_sections(self) -> None:
        sw = build_switch_config(self.plans["r2"], self.pm)
        self.assertEqual(len(sw["aggregatePorts"]), 2)
        self.assertIn("entries", sw["mySidConfig"])
        self.assertTrue(sw["srv6Tunnels"])
        self.assertTrue(sw["staticRoutesWithNhops"])
        # decap SID present on tail
        self.assertTrue(
            any("decap" in v for v in sw["mySidConfig"]["entries"].values())
        )
        # clientIdToAdminDistance rendered as list of structs
        self.assertTrue(
            all("clientId" in c for c in sw["clientIdToAdminDistance"])
        )
        self.assertEqual(sw["switchSettings"]["switchIdToSwitchInfo"]["0"]["asicType"], 15)

    def test_base_sw_scaffolding_preserved(self) -> None:
        base = _agent_conf_fixture()["sw"]
        sw = build_switch_config(self.plans["r1"], self.pm, base_sw=base)
        # board-generic sections preserved from base
        self.assertIn("cpuQueues", sw)
        # generated section overwritten
        self.assertEqual(len(sw["ports"]), 5)

    def test_agent_config_wrapper_round_trips(self) -> None:
        base = _agent_conf_fixture()
        cfg = build_agent_config(
            self.plans["r1"],
            self.pm,
            platform=base["platform"],
            default_command_line_args=base["defaultCommandLineArgs"],
            base_sw=base["sw"],
        )
        self.assertIn("platform", cfg)
        self.assertIn("defaultCommandLineArgs", cfg)
        self.assertEqual(json.loads(json.dumps(cfg))["sw"]["ports"][0]["name"], cfg["sw"]["ports"][0]["name"])

    def test_agent_config_omits_platform_when_absent(self) -> None:
        cfg = build_agent_config(self.plans["r1"], self.pm)
        self.assertNotIn("platform", cfg)
        self.assertIn("sw", cfg)


# ─── bgp.json / openr.conf builders ────────────────────────────────────────
class BgpOpenrConfigTest(unittest.TestCase):
    def test_bgp_config_shape(self) -> None:
        cfg = build_bgp_config(
            local_as=65001,
            router_id="192.0.2.1",
            loopback_v4="192.0.2.1/32",
            loopback_v6="2001:db8:0:1::1/128",
            peer_loopback_v4="192.0.2.2",
            networks4=("192.0.2.1/32", "203.0.113.0/24"),
            networks6=("2001:db8:0:1::1/128",),
        )
        self.assertEqual(cfg["local_as_4_byte"], 65001)
        self.assertEqual(cfg["router_id"], "192.0.2.1")
        self.assertEqual(cfg["peer_groups"][0]["name"], IBGP_PEER_GROUP)
        self.assertTrue(cfg["peer_groups"][0]["next_hop_self"])
        peer = cfg["peers"][0]
        self.assertEqual(peer["peer_addr"], "192.0.2.2")
        self.assertEqual(peer["local_addr"], "192.0.2.1")
        self.assertEqual(peer["next_hop6"], "2001:db8:0:1::1")
        self.assertEqual({n["prefix"] for n in cfg["networks4"]}, {"192.0.2.1/32", "203.0.113.0/24"})
        json.dumps(cfg)  # round-trips

    def test_policy_empty(self) -> None:
        self.assertEqual(build_policy_config(), {})

    def test_openr_config_shape(self) -> None:
        cfg = build_openr_config(node_name="r1")
        self.assertEqual(cfg["node_name"], "r1")
        self.assertEqual(cfg["domain"], "fboss")
        area = cfg["areas"][0]
        self.assertEqual(area["area_id"], "0")
        self.assertIn("^fboss[0-9]+$", area["include_interface_regexes"])
        self.assertIn("^lo$", area["redistribute_interface_regexes"])
        self.assertEqual(cfg["fib_port"], 5909)
        json.dumps(cfg)


# ─── Task behavior (mock driver) ───────────────────────────────────────────
class _MockDriver:
    """Records writes; serves configurable exists/read maps."""

    def __init__(self, exists: dict, contents: dict) -> None:
        self._exists = exists
        self._contents = contents
        self.writes: dict = {}
        self.reloaded = False
        self.waited = False
        self.restarted: list = []

    async def async_check_if_file_exists(self, path: str) -> bool:
        return bool(self._exists.get(path, False))

    async def async_read_file(self, path: str) -> str:
        return self._contents[path]

    async def async_write_file_on_device(self, contents, path, create_parent_dir=True):
        self.writes[path] = contents
        # a written file now exists (so a re-check sees the backup)
        self._exists[path] = True
        self._contents[path] = contents

    async def async_agent_config_reload(self) -> None:
        self.reloaded = True

    async def async_wait_for_agent_state_configured(self) -> None:
        self.waited = True

    async def async_restart_service(self, service, agents=None) -> None:
        self.restarted.append(service)

    async def async_run_cmd_on_shell(self, cmd: str) -> str:
        # The agent-config task resolves the platform-mapping file by globbing
        # the on-box mapping dir; return the fixture path so the resolver picks
        # it deterministically in these unit tests.
        return _MAP_PATH


_AGENT_PATH = "/etc/coop/agent.conf"
_BGP_PATH = "/opt/bgpd/bgp.json"
_POLICY_PATH = "/opt/bgpd/policy.json"
_OPENR_PATH = "/opt/openr/openr.conf"
_MAP_PATH = "/opt/fboss/share/MetaGeneratedPlatformMapping_reference.json"

_AGENT_TASK = "taac.tasks.provision_fboss_agent_config_task.async_get_device_driver"
_BGP_TASK = "taac.tasks.provision_fboss_bgp_config_task.async_get_device_driver"
_OPENR_TASK = "taac.tasks.provision_fboss_openr_config_task.async_get_device_driver"


class ProvisionAgentTaskTest(unittest.IsolatedAsyncioTestCase):
    def _driver(self, asic_type: int = 15) -> _MockDriver:
        return _MockDriver(
            exists={_AGENT_PATH: True, _MAP_PATH: True},
            contents={
                _AGENT_PATH: json.dumps(_agent_conf_fixture(asic_type)),
                _MAP_PATH: json.dumps(_mapping_fixture()),
            },
        )

    async def test_first_run_backs_up_writes_and_reloads(self) -> None:
        from taac.tasks.provision_fboss_agent_config_task import (
            ProvisionFbossAgentConfigTask,
        )

        driver = self._driver()
        task = ProvisionFbossAgentConfigTask(hostname="rbb-r1", logger=MagicMock())
        with patch(_AGENT_TASK, new_callable=AsyncMock, return_value=driver):
            await task.run({"hostname": "rbb-r1", "role": "r1"})
        self.assertIn(_AGENT_PATH + ".taac-orig", driver.writes)  # backup
        self.assertIn(_AGENT_PATH, driver.writes)  # new config
        self.assertTrue(driver.reloaded)
        self.assertTrue(driver.waited)

    async def test_idempotent_skip_when_backup_exists(self) -> None:
        from taac.tasks.provision_fboss_agent_config_task import (
            ProvisionFbossAgentConfigTask,
        )

        driver = self._driver()
        driver._exists[_AGENT_PATH + ".taac-orig"] = True  # already provisioned
        task = ProvisionFbossAgentConfigTask(hostname="rbb-r1", logger=MagicMock())
        with patch(_AGENT_TASK, new_callable=AsyncMock, return_value=driver):
            await task.run({"hostname": "rbb-r1", "role": "r1"})
        self.assertNotIn(_AGENT_PATH, driver.writes)  # skipped
        self.assertFalse(driver.reloaded)

    async def test_force_rewrites_even_with_backup(self) -> None:
        from taac.tasks.provision_fboss_agent_config_task import (
            ProvisionFbossAgentConfigTask,
        )

        driver = self._driver()
        driver._exists[_AGENT_PATH + ".taac-orig"] = True
        task = ProvisionFbossAgentConfigTask(hostname="rbb-r1", logger=MagicMock())
        with patch(_AGENT_TASK, new_callable=AsyncMock, return_value=driver):
            await task.run({"hostname": "rbb-r1", "role": "r1", "force": True})
        self.assertIn(_AGENT_PATH, driver.writes)

    async def test_hardware_guard_rejects_wrong_asic(self) -> None:
        from taac.tasks.provision_fboss_agent_config_task import (
            ProvisionFbossAgentConfigTask,
        )

        driver = self._driver(asic_type=2)  # not MORGAN800CC
        task = ProvisionFbossAgentConfigTask(hostname="rbb-r1", logger=MagicMock())
        with patch(_AGENT_TASK, new_callable=AsyncMock, return_value=driver):
            with self.assertRaises(TestCaseFailure):
                await task.run({"hostname": "rbb-r1", "role": "r1"})

    async def test_bad_role_raises(self) -> None:
        from taac.tasks.provision_fboss_agent_config_task import (
            ProvisionFbossAgentConfigTask,
        )

        task = ProvisionFbossAgentConfigTask(hostname="rbb-r1", logger=MagicMock())
        with self.assertRaises(ValueError):
            await task.run({"hostname": "rbb-r1", "role": "bogus"})


class ProvisionBgpTaskTest(unittest.IsolatedAsyncioTestCase):
    async def test_writes_bgp_and_policy_then_restarts(self) -> None:
        from taac.driver.driver_constants import FbossSystemctlServiceName
        from taac.tasks.provision_fboss_bgp_config_task import (
            ProvisionFbossBgpConfigTask,
        )

        driver = _MockDriver(
            exists={_AGENT_PATH: True, _BGP_PATH: True, _POLICY_PATH: True},
            contents={_AGENT_PATH: json.dumps(_agent_conf_fixture())},
        )
        task = ProvisionFbossBgpConfigTask(hostname="rbb-r1", logger=MagicMock())
        with patch(_BGP_TASK, new_callable=AsyncMock, return_value=driver):
            await task.run({"hostname": "rbb-r1", "role": "r1"})
        self.assertIn(_BGP_PATH, driver.writes)
        self.assertIn(_POLICY_PATH, driver.writes)
        self.assertIn(FbossSystemctlServiceName.BGP, driver.restarted)
        # generated bgp.json parses and carries the local AS
        self.assertEqual(json.loads(driver.writes[_BGP_PATH])["router_id"] is not None, True)


class ProvisionOpenrTaskTest(unittest.IsolatedAsyncioTestCase):
    async def test_writes_openr_then_restarts(self) -> None:
        from taac.driver.driver_constants import FbossSystemctlServiceName
        from taac.tasks.provision_fboss_openr_config_task import (
            ProvisionFbossOpenrConfigTask,
        )

        driver = _MockDriver(
            exists={_AGENT_PATH: True, _OPENR_PATH: True},
            contents={_AGENT_PATH: json.dumps(_agent_conf_fixture())},
        )
        task = ProvisionFbossOpenrConfigTask(hostname="rbb-r2", logger=MagicMock())
        with patch(_OPENR_TASK, new_callable=AsyncMock, return_value=driver):
            await task.run({"hostname": "rbb-r2", "role": "r2"})
        self.assertIn(_OPENR_PATH, driver.writes)
        self.assertEqual(json.loads(driver.writes[_OPENR_PATH])["node_name"], "r2")
        self.assertIn(FbossSystemctlServiceName.OPENR, driver.restarted)


if __name__ == "__main__":
    unittest.main()
