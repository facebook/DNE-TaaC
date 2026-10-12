# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

import json
import unittest

from configerator.structs.neteng.fboss.bgp.bgp_config.thrift_types import (
    BgpConfig,
    BgpPeer,
    OverloadProtectionMode,
    PeerGroup,
    RouteLimit,
)
from later.unittest import TestCase
from neteng.fboss.agent_config.thrift_types import AgentConfig
from neteng.fboss.switch_config.thrift_types import (
    Interface,
    Port,
    SwitchConfig,
    Vlan,
    VlanPort,
)
from neteng.test_infra.dne.taac.driver.oss_patchers import OssPatchApplier, PatcherError
from pyre_extensions import none_throws


def _peer(peer_addr: str, peer_type: str | None = None) -> BgpPeer:
    return BgpPeer(local_addr="::1", peer_addr=peer_addr, type=peer_type)


def _agent_config() -> AgentConfig:
    return AgentConfig(
        sw=SwitchConfig(
            ports=[
                Port(logicalID=1, name="eth1/1/1", ingressVlan=10),
                Port(logicalID=2, name="eth1/2/1", ingressVlan=10),
            ],
            vlans=[Vlan(name="vlan10", id=10, ipAddresses=["fd00::1"])],
            vlanPorts=[VlanPort(vlanID=10, logicalPort=1, emitTags=True)],
            interfaces=[
                Interface(intfID=10, vlanID=10, ipAddresses=["fd00::1/64"], mtu=1500)
            ],
        )
    )


class RemoveBgpPeersTest(unittest.TestCase):
    def setUp(self) -> None:
        self.applier = OssPatchApplier()
        self.config = BgpConfig(
            peers=[
                _peer("10.0.0.1"),
                _peer("2001:db8::1"),
                _peer("10.0.0.9", peer_type="BGP_MONITOR"),
            ]
        )

    def test_delete_all_drops_every_peer(self) -> None:
        out = self.applier.remove_bgp_peers(
            self.config, "bgpcpp", {"delete_all": "True"}
        )
        self.assertEqual([], list(out.peers))

    def test_delete_all_false_string_is_false(self) -> None:
        # COOP's bool("False") is True; here it must not delete everything.
        out = self.applier.remove_bgp_peers(
            self.config,
            "bgpcpp",
            {"delete_all": "False", "peer_addrs": json.dumps(["10.0.0.1"])},
        )
        self.assertEqual(["2001:db8::1", "10.0.0.9"], [p.peer_addr for p in out.peers])

    def test_v4_only_keeps_v4_and_bgp_typed_peers(self) -> None:
        out = self.applier.remove_bgp_peers(self.config, "bgpcpp", {"v4_only": "True"})
        self.assertEqual(["10.0.0.1", "10.0.0.9"], [p.peer_addr for p in out.peers])

    def test_returns_a_copy(self) -> None:
        self.applier.remove_bgp_peers(self.config, "bgpcpp", {"delete_all": "True"})
        self.assertEqual(3, len(self.config.peers))


class BgpSwitchLimitTest(unittest.TestCase):
    def test_replaces_limits_with_the_given_fields(self) -> None:
        out = OssPatchApplier().configure_bgp_switch_limit(
            BgpConfig(),
            "bgpcpp",
            {"prefix_limit": "20000", "overload_protection_mode": "1"},
        )
        limits = none_throws(out.switch_limit_config)
        self.assertEqual(20000, limits.prefix_limit)
        self.assertIsNone(limits.ingress_path_limit)
        self.assertEqual(
            OverloadProtectionMode.DROP_EXCESS_PREFIXES, limits.overload_protection_mode
        )


class ConfigureBgpPeerGroupTest(unittest.TestCase):
    def setUp(self) -> None:
        self.applier = OssPatchApplier()
        self.config = BgpConfig(
            peer_groups=[
                PeerGroup(
                    name="PG",
                    description="old",
                    is_passive=False,
                    pre_filter=RouteLimit(max_routes=100),
                )
            ]
        )

    def _update(self, attrs: dict) -> PeerGroup:
        out = self.applier.configure_bgp_peer_group(
            self.config,
            "bgpcpp",
            {"name": "PG", "attributes_to_update_json": json.dumps(attrs)},
        )
        return none_throws(out.peer_groups)[0]

    def test_converts_to_the_field_type(self) -> None:
        group = self._update({"description": "123", "is_passive": "True"})
        self.assertEqual("123", group.description)
        self.assertTrue(group.is_passive)

    def test_route_limit_fields_land_in_pre_filter(self) -> None:
        group = self._update({"max_routes": "20000"})
        self.assertEqual(20000, none_throws(group.pre_filter).max_routes)

    def test_sets_an_unset_optional_field(self) -> None:
        group = self._update({"link_bandwidth_bps": "1000"})
        self.assertEqual("1000", group.link_bandwidth_bps)

    def test_unknown_field_raises(self) -> None:
        with self.assertRaises(PatcherError):
            self._update({"no_such_field": "1"})

    def test_missing_group_is_left_alone(self) -> None:
        out = self.applier.configure_bgp_peer_group(
            self.config,
            "bgpcpp",
            {"name": "OTHER", "attributes_to_update_json": "{}"},
        )
        self.assertEqual(self.config, out)


class AddPeerGroupTest(unittest.TestCase):
    def test_defaults_fill_absent_kwargs(self) -> None:
        out = OssPatchApplier().add_peer_group_patcher(
            BgpConfig(), "bgpcpp", {"name": "PG", "next_hop_self": "False"}
        )
        group = none_throws(out.peer_groups)[0]
        self.assertFalse(group.next_hop_self)
        self.assertEqual(30, none_throws(group.bgp_peer_timers).hold_time_seconds)
        self.assertEqual(45000, none_throws(group.pre_filter).max_routes)

    def test_replaces_a_group_of_the_same_name(self) -> None:
        config = BgpConfig(peer_groups=[PeerGroup(name="A"), PeerGroup(name="PG")])
        out = OssPatchApplier().add_peer_group_patcher(
            config, "bgpcpp", {"name": "PG", "description": "new"}
        )
        self.assertEqual(["A", "PG"], [g.name for g in none_throws(out.peer_groups)])
        self.assertEqual("new", none_throws(out.peer_groups)[1].description)


class AddBgpPeersTest(unittest.TestCase):
    def test_concrete_peer_fields(self) -> None:
        spec = {
            "local_addr": "10.0.0.0",
            "peer_addr": "10.0.0.1",
            "remote_as_4_byte": "65000",
            "peer_group_name": "PG",
            "description": "dl",
        }
        out = OssPatchApplier().add_bgp_peers(
            BgpConfig(peers=[_peer("old")]),
            "bgpcpp",
            {"peer_configs": json.dumps([spec])},
        )
        peer = out.peers[1]
        self.assertEqual("10.0.0.1", peer.peer_id)
        self.assertEqual("10.0.0.0", peer.next_hop4)
        self.assertEqual("::", peer.next_hop6)
        self.assertEqual(65000, peer.remote_as_4_byte)

    def test_session_spec_expands(self) -> None:
        spec = {
            "starting_ip": "10.0.0.0",
            "gateway_starting_ip": "10.0.0.1",
            "increment_ip": "0.0.0.2",
            "num_sessions": 2,
            "remote_as_4_byte": 65100,
            "remote_as_4_byte_step": 1,
            "peer_group_name": "PG",
        }
        out = OssPatchApplier().add_bgp_peers(
            BgpConfig(), "bgpcpp", {"peer_configs": json.dumps({"eth1/1/1": [spec]})}
        )
        self.assertEqual(["10.0.0.1", "10.0.0.3"], [p.peer_addr for p in out.peers])
        self.assertEqual([65100, 65101], [p.remote_as_4_byte for p in out.peers])

    def test_peer_without_any_policy_holder_raises(self) -> None:
        spec = {"local_addr": "::1", "peer_addr": "::2", "remote_as_4_byte": "1"}
        with self.assertRaises(PatcherError):
            OssPatchApplier().add_bgp_peers(
                BgpConfig(), "bgpcpp", {"peer_configs": json.dumps([spec])}
            )


class ConfigureVlansTest(unittest.TestCase):
    def _vlan_arg(self, vlan_id: int, addresses: list, **extra) -> dict:
        return {
            f"vlan{vlan_id}": json.dumps(
                {"vlan_id": vlan_id, "ip_addresses": addresses, **extra}
            )
        }

    def test_merges_addresses_into_an_existing_interface(self) -> None:
        applier = OssPatchApplier()
        config = applier.configure_vlans(
            _agent_config(), "agent", self._vlan_arg(10, ["2001:db8:3::1/127"])
        )
        config = applier.configure_vlans(
            config, "agent", self._vlan_arg(10, ["2001:db8:4::1/127"])
        )
        intf = config.sw.interfaces[0]
        self.assertEqual(
            ["fd00::1/64", "2001:db8:3::1/127", "2001:db8:4::1/127"],
            list(intf.ipAddresses),
        )
        self.assertEqual(1500, intf.mtu)
        self.assertEqual(
            ["fd00::1", "2001:db8:3::1", "2001:db8:4::1"],
            list(config.sw.vlans[0].ipAddresses),
        )

    def test_creates_a_missing_vlan_and_moves_ports(self) -> None:
        config = OssPatchApplier().configure_vlans(
            _agent_config(), "agent", self._vlan_arg(20, ["10.1.0.1/31"], ports=[1, 2])
        )
        sw = config.sw
        self.assertEqual(9000, sw.interfaces[1].mtu)
        self.assertEqual(["10.1.0.1"], list(sw.vlans[1].ipAddresses))
        self.assertEqual([20, 20], [p.ingressVlan for p in sw.ports])
        # The existing entry keeps its other fields; the missing one is added.
        self.assertEqual(
            [(20, 1, True), (20, 2, False)],
            [(v.vlanID, v.logicalPort, v.emitTags) for v in sw.vlanPorts],
        )

    def test_unknown_port_raises(self) -> None:
        with self.assertRaises(PatcherError):
            OssPatchApplier().configure_vlans(
                _agent_config(),
                "agent",
                self._vlan_arg(20, ["10.1.0.1/31"], ports=[99]),
            )

    def test_replaces_addresses_when_the_split_asks_for_it(self) -> None:
        config = OssPatchApplier().configure_vlans(
            _agent_config(),
            "agent",
            self._vlan_arg(
                10, ["2001:db8:3::1/127"], retain_existing_vlan_addresses=False
            ),
        )
        self.assertEqual(
            ["2001:db8:3::1/127"], list(config.sw.interfaces[0].ipAddresses)
        )
        self.assertEqual(["2001:db8:3::1"], list(config.sw.vlans[0].ipAddresses))

    def test_trunk_port_keeps_a_single_membership(self) -> None:
        config = _agent_config()
        config = config(
            sw=config.sw(
                vlanPorts=[
                    VlanPort(vlanID=10, logicalPort=1),
                    VlanPort(vlanID=11, logicalPort=1, emitTags=True),
                    VlanPort(vlanID=10, logicalPort=2),
                ]
            )
        )
        out = OssPatchApplier().configure_vlans(
            config, "agent", self._vlan_arg(20, ["10.1.0.1/31"], ports=[1])
        )
        self.assertEqual(
            [(20, 1), (10, 2)],
            [(v.vlanID, v.logicalPort) for v in out.sw.vlanPorts],
        )


class AddStaticRoutesTest(unittest.TestCase):
    def test_replaces_a_prefix_already_configured(self) -> None:
        applier = OssPatchApplier()
        config = applier.add_static_routes(
            _agent_config(), "agent", {"2001:db8::/64": json.dumps(["fe80::1"])}
        )
        config = applier.add_static_routes(
            config, "agent", {"2001:db8::/64": json.dumps(["fe80::2"])}
        )
        (route,) = config.sw.staticRoutesWithNhops
        self.assertEqual(["fe80::2"], list(route.nexthops))


class AsyncApplyTest(TestCase):
    async def test_dispatches_by_name(self) -> None:
        out = await OssPatchApplier().async_apply(
            BgpConfig(peers=[_peer("10.0.0.1")]),
            "bgpcpp",
            "remove_bgp_peers",
            {"delete_all": "True"},
        )
        self.assertEqual([], list(out.peers))

    async def test_unported_patcher_raises(self) -> None:
        with self.assertRaises(NotImplementedError):
            await OssPatchApplier().async_apply(BgpConfig(), "bgpcpp", "nope", {})
