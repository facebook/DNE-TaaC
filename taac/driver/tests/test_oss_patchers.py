# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

import json
import typing as t
import unittest

from configerator.structs.neteng.fboss.bgp.bgp_config.thrift_types import (
    BgpConfig,
    BgpPeer,
    OverloadProtectionMode,
    PeerGroup,
    RouteLimit,
)
from configerator.structs.neteng.robotron.bgp_policy.thrift_types import (
    BgpPolicies,
    BgpPolicyStatement,
    BgpPolicyTerm,
)
from later.unittest import TestCase
from neteng.fboss.agent_config.thrift_types import AgentConfig
from neteng.fboss.phy.phy.thrift_types import (
    FecMode,
    IpModulation,
    PortProfileConfig,
    ProfileSideConfig,
)
from neteng.fboss.platform_config.platform_config.thrift_types import (
    PlatformMapping,
    PlatformPortConfig,
    PlatformPortConfigFactor,
    PlatformPortEntry,
    PlatformPortMapping,
    PlatformPortProfileConfigEntry,
)
from neteng.fboss.switch_config.thrift_types import (
    Interface,
    Port,
    PortProfileID,
    PortSpeed,
    PortState,
    SpanningTreeState,
    SwitchConfig,
    Vlan,
    VlanPort,
)
from taac.driver.config_modifiers import (
    POLICY_PROPAGATE_IN,
    POLICY_PROPAGATE_OUT,
    POLICY_PROPAGATE_OUT_DRAIN,
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


_P800 = PortProfileID.PROFILE_800G_8_PAM4_RS544X2N_OPTICAL
_P400 = PortProfileID.PROFILE_400G_4_PAM4_RS544X2N_OPTICAL
_P200 = PortProfileID.PROFILE_200G_4_PAM4_RS544X2N_OPTICAL
_P100 = PortProfileID.PROFILE_100G_4_NRZ_RS528_OPTICAL


def _platform_mapping(adjacent_800g: bool = False) -> PlatformMapping:
    """One 51T cage: /1 (id 1) offers 800G, which subsumes /5 (id 2)."""
    shared = {p: PlatformPortConfig() for p in (_P400, _P200, _P100)}
    adjacent = {**shared, _P800: PlatformPortConfig()} if adjacent_800g else shared
    return PlatformMapping(
        ports={
            1: PlatformPortEntry(
                mapping=PlatformPortMapping(id=1, name="eth1/1/1"),
                supportedProfiles={
                    **shared,
                    _P800: PlatformPortConfig(subsumedPorts=[2]),
                },
            ),
            2: PlatformPortEntry(
                mapping=PlatformPortMapping(id=2, name="eth1/1/5"),
                supportedProfiles=adjacent,
            ),
        }
    )


class _Inputs:
    def __init__(
        self,
        hardware: t.Optional[str] = "MONTBLANC",
        adjacent_800g: bool = False,
        mapping: t.Optional[PlatformMapping] = None,
    ) -> None:
        self._hardware = hardware
        self._mapping = mapping or _platform_mapping(adjacent_800g)

    async def platform_mapping(self) -> PlatformMapping:
        return self._mapping

    def hardware(self) -> t.Optional[str]:
        return self._hardware


def _cage_config(adjacent_speed: PortSpeed = PortSpeed.FOURHUNDREDG) -> AgentConfig:
    """/1 and /5 at 400G, each in its own VLAN with an L3 interface."""
    adjacent_profile = {PortSpeed.FOURHUNDREDG: _P400, PortSpeed.HUNDREDG: _P100}[
        adjacent_speed
    ]
    return AgentConfig(
        sw=SwitchConfig(
            defaultVlan=4094,
            ports=[
                Port(
                    logicalID=1,
                    name="eth1/1/1",
                    ingressVlan=11,
                    speed=PortSpeed.FOURHUNDREDG,
                    profileID=_P400,
                    state=PortState.ENABLED,
                    maxFrameSize=9412,
                    description="to rsw001",
                ),
                Port(
                    logicalID=2,
                    name="eth1/1/5",
                    ingressVlan=12,
                    speed=adjacent_speed,
                    profileID=adjacent_profile,
                    state=PortState.ENABLED,
                ),
            ],
            vlans=[
                Vlan(name="default", id=4094),
                Vlan(name="vlan11", id=11),
                Vlan(name="vlan12", id=12),
            ],
            vlanPorts=[
                VlanPort(vlanID=11, logicalPort=1),
                VlanPort(vlanID=12, logicalPort=2),
            ],
            interfaces=[
                Interface(intfID=11, vlanID=11, ipAddresses=["fd00:1::/127"]),
                Interface(intfID=12, vlanID=12, ipAddresses=["fd00:2::/127"]),
            ],
        )
    )


def _speed_args(intfs: str, speed: str, profile: PortProfileID) -> dict:
    return {"intfs": intfs, "speed": speed, "profile_id": profile.name}


class ChangeSpeedTest(TestCase):
    async def _change(
        self, config: AgentConfig, args: dict, hardware: t.Optional[str] = "MONTBLANC"
    ) -> AgentConfig:
        return await OssPatchApplier(inputs=_Inputs(hardware)).async_apply(
            config, "agent", "change_speed", args
        )

    async def test_800g_removes_the_subsumed_adjacent_port_and_its_vlan(self) -> None:
        out = await self._change(
            _cage_config(), _speed_args("eth1/1/1", "EIGHTHUNDREDG", _P800)
        )
        sw = out.sw
        (port,) = sw.ports
        self.assertEqual(
            ("eth1/1/1", PortSpeed.EIGHTHUNDREDG, _P800, PortState.ENABLED),
            (port.name, port.speed, port.profileID, port.state),
        )
        self.assertEqual([1], [vp.logicalPort for vp in sw.vlanPorts])
        self.assertEqual([4094, 11], [v.id for v in sw.vlans])
        self.assertEqual([11], [i.vlanID for i in sw.interfaces])

    async def test_800g_is_only_allowed_on_slash_1(self) -> None:
        # Even where the platform mapping offers it on /5.
        with self.assertRaisesRegex(PatcherError, "only on X/Y/1"):
            await OssPatchApplier(inputs=_Inputs(adjacent_800g=True)).async_apply(
                _cage_config(),
                "agent",
                "change_speed",
                _speed_args("eth1/1/5", "EIGHTHUNDREDG", _P800),
            )

    async def test_adjacent_port_speeds_must_be_a_supported_pair(self) -> None:
        # /5 stays at 100G: 200G next to it is not (100,100) nor a 200/400 mix.
        with self.assertRaisesRegex(PatcherError, "incompatible with adjacent"):
            await self._change(
                _cage_config(PortSpeed.HUNDREDG),
                _speed_args("eth1/1/1", "TWOHUNDREDG", _P200),
            )

    async def test_supported_pairs_and_both_adjacent_ports_named_pass(self) -> None:
        out = await self._change(
            _cage_config(), _speed_args("eth1/1/1", "TWOHUNDREDG", _P200)
        )
        self.assertEqual(
            [PortSpeed.TWOHUNDREDG, PortSpeed.FOURHUNDREDG],
            [p.speed for p in out.sw.ports],
        )
        out = await self._change(
            _cage_config(), _speed_args("eth1/1/1,eth1/1/5", "HUNDREDG", _P100)
        )
        self.assertEqual(
            [PortSpeed.HUNDREDG, PortSpeed.HUNDREDG], [p.speed for p in out.sw.ports]
        )

    async def test_adjacent_port_rule_only_applies_to_51t_hardware(self) -> None:
        out = await self._change(
            _cage_config(PortSpeed.HUNDREDG),
            _speed_args("eth1/1/1", "TWOHUNDREDG", _P200),
            hardware="WEDGE400",
        )
        self.assertEqual(PortSpeed.TWOHUNDREDG, out.sw.ports[0].speed)

    async def test_downshift_creates_a_missing_adjacent_port(self) -> None:
        subsumed = await self._change(
            _cage_config(), _speed_args("eth1/1/1", "EIGHTHUNDREDG", _P800)
        )
        out = await self._change(
            subsumed, _speed_args("eth1/1/1,eth1/1/5", "FOURHUNDREDG", _P400)
        )
        sw = out.sw
        adjacent = next(p for p in sw.ports if p.name == "eth1/1/5")
        # Each port has its own VLAN numbered 10 + logicalID, so /5 gets VLAN 12
        # back, with an address-less interface, as COOP gives an unused port.
        self.assertEqual(
            (2, 12, PortSpeed.FOURHUNDREDG, _P400, PortState.ENABLED),
            (
                adjacent.logicalID,
                adjacent.ingressVlan,
                adjacent.speed,
                adjacent.profileID,
                adjacent.state,
            ),
        )
        # Settings from the adjacent port; its link description is not.
        self.assertEqual(9412, adjacent.maxFrameSize)
        self.assertIsNone(adjacent.description)
        self.assertIn(
            (12, 2, SpanningTreeState.FORWARDING),
            [(vp.vlanID, vp.logicalPort, vp.spanningTreeState) for vp in sw.vlanPorts],
        )
        self.assertIn(("vlan12", 12), [(v.name, v.id) for v in sw.vlans])
        intf = next(i for i in sw.interfaces if i.vlanID == 12)
        self.assertEqual((12, []), (intf.intfID, list(intf.ipAddresses)))

    async def test_created_port_joins_its_adjacent_ports_shared_vlan(self) -> None:
        # Like an RSW's server downlinks: /1 shares VLAN 11 with another port, so
        # the created /5 joins VLAN 11 and its existing interface serves it.
        subsumed = await self._change(
            _cage_config(), _speed_args("eth1/1/1", "EIGHTHUNDREDG", _P800)
        )
        sw = subsumed.sw
        other = Port(
            logicalID=3,
            name="eth1/2/1",
            ingressVlan=11,
            speed=PortSpeed.FOURHUNDREDG,
            profileID=_P400,
        )
        mapping = _platform_mapping()
        mapping = mapping(
            ports={
                **mapping.ports,
                3: PlatformPortEntry(
                    mapping=PlatformPortMapping(id=3, name="eth1/2/1"),
                    supportedProfiles={_P400: PlatformPortConfig()},
                ),
            }
        )
        shared = subsumed(sw=sw(ports=[*sw.ports, other]))
        out = await OssPatchApplier(inputs=_Inputs(mapping=mapping)).async_apply(
            shared,
            "agent",
            "change_speed",
            _speed_args("eth1/1/1,eth1/1/5", "FOURHUNDREDG", _P400),
        )
        adjacent = next(p for p in out.sw.ports if p.name == "eth1/1/5")
        self.assertEqual(11, adjacent.ingressVlan)
        self.assertIn((11, 2), [(vp.vlanID, vp.logicalPort) for vp in out.sw.vlanPorts])
        self.assertEqual([11], [i.vlanID for i in out.sw.interfaces])

    async def test_created_port_joins_the_default_vlan_without_dedicated_vlans(
        self,
    ) -> None:
        # The adjacent port's VLAN has no interface, so it is no point-to-point layout:
        # the created /5 goes in the default VLAN with no interface.
        subsumed = await self._change(
            _cage_config(), _speed_args("eth1/1/1", "EIGHTHUNDREDG", _P800)
        )
        no_layout = subsumed(sw=subsumed.sw(interfaces=[]))
        out = await self._change(
            no_layout, _speed_args("eth1/1/1,eth1/1/5", "FOURHUNDREDG", _P400)
        )
        adjacent = next(p for p in out.sw.ports if p.name == "eth1/1/5")
        self.assertEqual(4094, adjacent.ingressVlan)
        self.assertNotIn(4094, [i.vlanID for i in out.sw.interfaces])

    async def test_unsupported_profile_and_unknown_port_raise(self) -> None:
        with self.assertRaisesRegex(PatcherError, "not supported on ports: eth1/1/5"):
            await self._change(
                _cage_config(), _speed_args("eth1/1/1,eth1/1/5", "EIGHTHUNDREDG", _P800)
            )
        with self.assertRaisesRegex(PatcherError, "not in the platform mapping"):
            await self._change(
                _cage_config(), _speed_args("eth9/9/1", "FOURHUNDREDG", _P400)
            )

    async def test_unknown_speed_or_profile_name_raises_patcher_error(self) -> None:
        with self.assertRaisesRegex(PatcherError, "unknown PortSpeed or PortProfileID"):
            await self._change(
                _cage_config(),
                {"intfs": "eth1/1/1", "speed": "NOT_A_SPEED", "profile_id": _P400.name},
            )

    async def test_requested_port_left_subsumed_is_rejected(self) -> None:
        # No hardware rule (as on WEDGE800BNHP): /1 at 800G still subsumes /5,
        # so creating /5 alone would leave it absent again.
        at_800g = await self._change(
            _cage_config(), _speed_args("eth1/1/1", "EIGHTHUNDREDG", _P800), None
        )
        with self.assertRaisesRegex(PatcherError, "would be subsumed"):
            await self._change(
                at_800g, _speed_args("eth1/1/5", "FOURHUNDREDG", _P400), None
            )

    async def test_subsumption_keeps_vlans_with_surviving_tagged_members(self) -> None:
        mapping = _platform_mapping()
        mapping = mapping(
            ports={
                **mapping.ports,
                3: PlatformPortEntry(
                    mapping=PlatformPortMapping(id=3, name="eth1/2/1"),
                    supportedProfiles={_P400: PlatformPortConfig()},
                ),
            }
        )
        config = _cage_config()
        config = config(
            sw=config.sw(
                ports=[
                    *config.sw.ports,
                    Port(
                        logicalID=3,
                        name="eth1/2/1",
                        ingressVlan=11,
                        speed=PortSpeed.FOURHUNDREDG,
                        profileID=_P400,
                    ),
                ],
                vlanPorts=[
                    *config.sw.vlanPorts,
                    VlanPort(vlanID=11, logicalPort=3),
                    VlanPort(vlanID=12, logicalPort=3, emitTags=True),
                ],
            )
        )
        out = await OssPatchApplier(inputs=_Inputs(mapping=mapping)).async_apply(
            config,
            "agent",
            "change_speed",
            _speed_args("eth1/1/1", "EIGHTHUNDREDG", _P800),
        )
        self.assertEqual(["eth1/1/1", "eth1/2/1"], [p.name for p in out.sw.ports])
        self.assertIn(12, [v.id for v in out.sw.vlans])
        self.assertIn(12, [i.vlanID for i in out.sw.interfaces])

    async def test_fuji_adjacent_slots_change_speed_together(self) -> None:
        mapping = PlatformMapping(
            ports={
                n: PlatformPortEntry(
                    mapping=PlatformPortMapping(id=n, name=f"eth3/{10 + n}/1"),
                    supportedProfiles={
                        _P100: PlatformPortConfig(),
                        _P200: PlatformPortConfig(),
                        _P400: PlatformPortConfig(),
                    },
                )
                for n in (1, 2)
            }
        )
        config = AgentConfig(
            sw=SwitchConfig(
                ports=[
                    Port(
                        logicalID=n,
                        name=f"eth3/{10 + n}/1",
                        ingressVlan=4094,
                        speed=PortSpeed.TWOHUNDREDG,
                        profileID=_P200,
                    )
                    for n in (1, 2)
                ],
                vlans=[Vlan(name="default", id=4094)],
            )
        )

        async def change(intfs: str, speed: str, profile: PortProfileID) -> AgentConfig:
            return await OssPatchApplier(
                inputs=_Inputs("FUJI", mapping=mapping)
            ).async_apply(
                config, "agent", "change_speed", _speed_args(intfs, speed, profile)
            )

        with self.assertRaisesRegex(PatcherError, "adjacent port eth3/11/1"):
            await change("eth3/12/1", "HUNDREDG", _P100)
        with self.assertRaisesRegex(PatcherError, "only on odd-numbered ports"):
            await change("eth3/12/1", "FOURHUNDREDG", _P400)
        out = await change("eth3/11/1,eth3/12/1", "HUNDREDG", _P100)
        self.assertEqual(
            [PortSpeed.HUNDREDG, PortSpeed.HUNDREDG], [p.speed for p in out.sw.ports]
        )

    async def test_yamp_allows_200g_only_on_even_ports(self) -> None:
        with self.assertRaisesRegex(PatcherError, "only on even ports"):
            await self._change(
                _cage_config(PortSpeed.HUNDREDG),
                _speed_args("eth1/1/1", "TWOHUNDREDG", _P200),
                hardware="YAMP",
            )

    async def test_needs_the_platform_mapping(self) -> None:
        with self.assertRaisesRegex(PatcherError, "platform mapping"):
            await OssPatchApplier().async_apply(
                _cage_config(),
                "agent",
                "change_speed",
                _speed_args("eth1/1/1", "FOURHUNDREDG", _P400),
            )


class ChangePortAdminStateTest(unittest.TestCase):
    def test_sets_each_named_port(self) -> None:
        out = OssPatchApplier().change_port_admin_state(
            _agent_config(), "agent", {"eth1/1/1": "disable", "eth1/2/1": "enable"}
        )
        self.assertEqual(
            [PortState.DISABLED, PortState.ENABLED], [p.state for p in out.sw.ports]
        )

    def test_bad_state_or_port_raises(self) -> None:
        with self.assertRaises(PatcherError):
            OssPatchApplier().change_port_admin_state(
                _agent_config(), "agent", {"eth1/1/1": "off"}
            )
        with self.assertRaises(PatcherError):
            OssPatchApplier().change_port_admin_state(
                _agent_config(), "agent", {"eth9/9/9": "enable"}
            )


class ChangeMtuTest(unittest.TestCase):
    def test_by_port_name_interface_name_or_vlan_id(self) -> None:
        for intfs in ("eth1/1/1", "10"):
            with self.subTest(intfs=intfs):
                out = OssPatchApplier().change_mtu(
                    _agent_config(), "agent", {"intfs": intfs, "mtu": "1500"}
                )
                self.assertEqual(1500, out.sw.interfaces[0].mtu)

    def test_no_matching_interface_raises(self) -> None:
        with self.assertRaises(PatcherError):
            OssPatchApplier().change_mtu(
                _agent_config(), "agent", {"intfs": "eth9/9/9", "mtu": "1500"}
            )


def _policy_config() -> BgpConfig:
    return BgpConfig(
        policies=BgpPolicies(
            bgp_policy_statements=[
                BgpPolicyStatement(
                    name="IN", policy_entries=[BgpPolicyTerm(name="old")]
                ),
                BgpPolicyStatement(name="OUT"),
            ]
        )
    )


class BgpPolicyPatchersTest(unittest.TestCase):
    def test_add_statement_creates_policies_and_skips_an_existing_name(self) -> None:
        applier = OssPatchApplier()
        args = {"name": "NEW", "description": "d", "policy_entries": "[]"}
        out = applier.add_bgp_policy_statement(BgpConfig(), "bgpcpp", args)
        self.assertEqual(
            ["NEW"], [s.name for s in none_throws(out.policies).bgp_policy_statements]
        )
        again = applier.add_bgp_policy_statement(
            out, "bgpcpp", {**args, "description": "changed"}
        )
        self.assertEqual(
            "d", none_throws(again.policies).bgp_policy_statements[0].description
        )

    def test_match_prefix_goes_first_in_both_statements(self) -> None:
        out = OssPatchApplier().add_bgp_policy_match_prefix_to_propagate_routes(
            _policy_config(),
            "bgpcpp",
            {
                "matching_prefix": "5000::/16",
                "in_stmt_name": "IN",
                "out_stmt_name": "OUT",
            },
        )
        stmt_in, stmt_out = none_throws(out.policies).bgp_policy_statements
        self.assertEqual(2, len(stmt_in.policy_entries))
        self.assertEqual("old", stmt_in.policy_entries[1].name)
        self.assertEqual(1, len(stmt_in.policy_entries[0].policy_action_entries))
        self.assertEqual([], list(stmt_out.policy_entries[0].policy_action_entries))

    def test_missing_statement_is_skipped(self) -> None:
        out = OssPatchApplier().add_bgp_policy_match_prefix_to_propagate_routes(
            _policy_config(),
            "bgpcpp",
            {
                "matching_prefix": "5000::/16",
                "in_stmt_name": "IN",
                "out_stmt_name": "OUT_DRAIN",
            },
        )
        stmt_in, stmt_out = none_throws(out.policies).bgp_policy_statements
        self.assertEqual(2, len(stmt_in.policy_entries))
        self.assertEqual(0, len(stmt_out.policy_entries))


_OPTICAL_100G = PortProfileID.PROFILE_100G_4_NRZ_RS528_OPTICAL  # 23
_COPPER_100G = PortProfileID.PROFILE_100G_4_NRZ_RS528_COPPER  # 22
_COPPER_100G_NOFEC = PortProfileID.PROFILE_100G_4_NRZ_NOFEC_COPPER  # 32
_COPPER_100G_CL91 = PortProfileID.PROFILE_100G_4_NRZ_CL91_COPPER  # 27


def _wire_entry(profile: PortProfileID, fec: FecMode) -> PlatformPortProfileConfigEntry:
    return PlatformPortProfileConfigEntry(
        factor=PlatformPortConfigFactor(profileID=profile),
        profile=PortProfileConfig(
            speed=PortSpeed.HUNDREDG,
            iphy=ProfileSideConfig(numLanes=4, modulation=IpModulation.NRZ, fec=fec),
        ),
    )


def _mixed_media_mapping(copper_offers: t.Sequence[PortProfileID]) -> PlatformMapping:
    """An optical cage (eth1/1/1) and a copper cage (eth1/2/1): the same 100G
    signal is profile 23 on one and 22 on the other."""
    return PlatformMapping(
        ports={
            1: PlatformPortEntry(
                mapping=PlatformPortMapping(id=1, name="eth1/1/1"),
                supportedProfiles={_OPTICAL_100G: PlatformPortConfig()},
            ),
            3: PlatformPortEntry(
                mapping=PlatformPortMapping(id=3, name="eth1/2/1"),
                supportedProfiles={p: PlatformPortConfig() for p in copper_offers},
            ),
        },
        platformSupportedProfiles=[
            _wire_entry(_OPTICAL_100G, FecMode.RS528),
            _wire_entry(_COPPER_100G, FecMode.RS528),
            _wire_entry(_COPPER_100G_NOFEC, FecMode.NONE),
            # Same wire as 22, to make a stand-in ambiguous.
            _wire_entry(_COPPER_100G_CL91, FecMode.RS528),
        ],
    )


def _link_config() -> AgentConfig:
    return AgentConfig(
        sw=SwitchConfig(
            defaultVlan=4094,
            ports=[
                Port(logicalID=1, name="eth1/1/1", ingressVlan=11, profileID=_P400),
                Port(logicalID=3, name="eth1/2/1", ingressVlan=12, profileID=_P400),
            ],
        )
    )


class ProfileFittingTest(TestCase):
    async def _change(self, copper_offers: t.Sequence[PortProfileID]) -> AgentConfig:
        inputs = _Inputs(hardware=None, mapping=_mixed_media_mapping(copper_offers))
        return await OssPatchApplier(inputs=inputs).async_apply(
            _link_config(),
            "agent",
            "change_speed",
            _speed_args("eth1/1/1,eth1/2/1", "HUNDREDG", _OPTICAL_100G),
        )

    async def test_a_port_without_the_profile_takes_its_wire_identical_one(
        self,
    ) -> None:
        # 22 matches 23's speed, lanes, modulation and FEC; 32 differs in FEC.
        out = await self._change([_COPPER_100G, _COPPER_100G_NOFEC])
        self.assertEqual(
            [_OPTICAL_100G, _COPPER_100G], [p.profileID for p in out.sw.ports]
        )

    async def test_no_unique_wire_identical_profile_raises(self) -> None:
        for offers in ([_COPPER_100G_NOFEC], [_COPPER_100G, _COPPER_100G_CL91]):
            with self.subTest(offers=[p.name for p in offers]):
                with self.assertRaisesRegex(PatcherError, "no unique wire-identical"):
                    await self._change(offers)


def _drain_config() -> BgpConfig:
    """Live base config: every group on the propagate policies, and one
    group (``OTHER``) a scoped setup left on its own."""
    return BgpConfig(
        policies=BgpPolicies(
            bgp_policy_statements=[
                BgpPolicyStatement(name=name)
                for name in (
                    POLICY_PROPAGATE_IN,
                    POLICY_PROPAGATE_OUT,
                    POLICY_PROPAGATE_OUT_DRAIN,
                    "OTHER_OUT",
                )
            ]
        ),
        peer_groups=[
            PeerGroup(
                name="FABRIC",
                ingress_policy_name=POLICY_PROPAGATE_IN,
                egress_policy_name=POLICY_PROPAGATE_OUT,
            ),
            PeerGroup(
                name="OTHER",
                ingress_policy_name=POLICY_PROPAGATE_IN,
                egress_policy_name="OTHER_OUT",
            ),
        ],
        peers=[
            BgpPeer(peer_addr="2001:db8:1::1", peer_group_name="FABRIC"),
            BgpPeer(peer_addr="10.0.0.1", peer_group_name="FABRIC"),
            BgpPeer(peer_addr="2001:db8:2::1", peer_group_name="FABRIC"),
            BgpPeer(peer_addr="2001:db8:1::/64", peer_group_name="FABRIC"),
            BgpPeer(peer_addr="2001:db8:3::1", peer_group_name="OTHER"),
        ],
    )


def _drain_args(*networks: str) -> t.Dict[str, str]:
    return {
        "interface_name": "eth1/1/1",
        "networks": json.dumps(list(networks or ("2001:db8:1::/127", "10.0.0.0/31"))),
    }


class DrainInterfaceTest(unittest.TestCase):
    def test_sessions_on_the_interface_take_the_drain_policy(self) -> None:
        out = OssPatchApplier().drain_interface(
            _drain_config(), "bgpcpp", _drain_args()
        )

        drained = (POLICY_PROPAGATE_IN, POLICY_PROPAGATE_OUT_DRAIN)
        self.assertEqual(
            [
                ("2001:db8:1::1", *drained),
                ("10.0.0.1", *drained),
                ("2001:db8:2::1", None, None),
                ("2001:db8:1::/64", None, None),
                ("2001:db8:3::1", None, None),
            ],
            [
                (p.peer_addr, p.ingress_policy_name, p.egress_policy_name)
                for p in out.peers
            ],
        )
        self.assertEqual(["eth1/1/1"], list(out.drained_interfaces))
        self.assertEqual(_drain_config().peer_groups, out.peer_groups)
        self.assertEqual(_drain_config().policies, out.policies)

    def test_interface_without_a_session_is_refused(self) -> None:
        with self.assertRaisesRegex(PatcherError, "no BGP peer"):
            OssPatchApplier().drain_interface(
                _drain_config(), "bgpcpp", _drain_args("2001:db8:9::/127")
            )

    def test_config_without_the_drain_policy_is_refused(self) -> None:
        config = _drain_config()
        config = config(
            policies=BgpPolicies(
                bgp_policy_statements=[
                    s
                    for s in none_throws(config.policies).bgp_policy_statements
                    if s.name != POLICY_PROPAGATE_OUT_DRAIN
                ]
            )
        )
        with self.assertRaisesRegex(PatcherError, POLICY_PROPAGATE_OUT_DRAIN):
            OssPatchApplier().drain_interface(config, "bgpcpp", _drain_args())

    def test_session_outside_the_base_configs_is_refused(self) -> None:
        with self.assertRaisesRegex(PatcherError, "advertises through OTHER_OUT"):
            OssPatchApplier().drain_interface(
                _drain_config(), "bgpcpp", _drain_args("2001:db8:3::/127")
            )

    def test_drained_session_is_refused(self) -> None:
        applier = OssPatchApplier()
        drained = applier.drain_interface(_drain_config(), "bgpcpp", _drain_args())
        with self.assertRaisesRegex(
            PatcherError, f"advertises through {POLICY_PROPAGATE_OUT_DRAIN}"
        ):
            applier.drain_interface(drained, "bgpcpp", _drain_args())
