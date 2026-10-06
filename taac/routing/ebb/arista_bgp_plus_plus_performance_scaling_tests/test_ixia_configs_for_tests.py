# pyre-unsafe

import unittest

from ixia.ixia import types as ixia_types
from taac.routing.ebb.arista_bgp_plus_plus_performance_scaling_tests.ixia_configs_for_tests import (
    create_ebb_performance_scale_basic_port_configs,
    create_ebb_route_churn_test_basic_port_configs,
)

_COMMON_KWARGS = {
    "device_name": "bag010.ash6",
    "ixia_interface_mimic_ebgp": "eth1",
    "ixia_interface_mimic_ibgp": "eth2",
    "ebgp_peer_count_v6": 1,
    "ebgp_peer_count_v4": 1,
    "ibgp_peer_count_v6": 1,
    "ibgp_peer_count_v4": 1,
    "ebgp_remote_as": 65334,
    "ibgp_remote_as": 64981,
    "ixia_ebgp_ic_parent_network_v6": "2401:db00:eef0:a00",
    "ixia_ebgp_ic_parent_network_v4": "10.163.28",
    "ixia_ibgp_ic_parent_network_v6": "2401:db00:eef0:a01",
    "ixia_ibgp_ic_parent_network_v4": "10.163.29",
}


def _ebgp_bgp_configs(configs):
    """All eBGP BgpConfigs (v4 + v6) across the returned port configs."""
    bgp_cfgs = []
    for port in configs:
        for dg in port.device_group_configs or []:
            if "EBGP" not in dg.device_group_name:
                continue
            for bgp_cfg in (dg.v4_bgp_config, dg.v6_bgp_config):
                if bgp_cfg is not None:
                    bgp_cfgs.append(bgp_cfg)
    return bgp_cfgs


def _ebgp_import_params(configs):
    params = []
    for bgp_cfg in _ebgp_bgp_configs(configs):
        params.extend(bgp_cfg.import_bgp_routes_params_list or [])
    return params


def _ebgp_route_scales(configs):
    """All eBGP v4/v6 RouteScale objects (compact geometry)."""
    scales = []
    for bgp_cfg in _ebgp_bgp_configs(configs):
        for spec in bgp_cfg.route_scales or []:
            for rs in (spec.v4_route_scale, spec.v6_route_scale):
                if rs is not None:
                    scales.append(rs)
    return scales


class EbgpNextHopSelfCompactGeometryTest(unittest.TestCase):
    """next-hop-self callers (perf-scaling SC1/SC4) advertise a uniform route set,
    so they use the COMPACT route_scales geometry -- one prefix-pool object per
    sender (RouteScale multiplier=1, prefix_count=<count>) with next-hop-self --
    NOT the flat import_bgp_routes path (one IxNetwork object per route), which
    explodes the object count and fails the commit at high sender counts."""

    def test_next_hop_self_uses_compact_route_scales(self) -> None:
        configs = create_ebb_performance_scale_basic_port_configs(
            ebgp_next_hop_self=True,
            ebgp_fixed_communities=["65529:39744"],
            **_COMMON_KWARGS,
        )
        # Compact geometry: route_scales present, flat import path absent.
        self.assertEqual(len(_ebgp_import_params(configs)), 0)
        scales = _ebgp_route_scales(configs)
        self.assertEqual(len(scales), 2)  # one v4, one v6 eBGP pool
        for rs in scales:
            # One compact pool object per sender: NumberOfAddresses=count with
            # NetworkGroup Multiplier=1 -- NOT Multiplier=count (the explosion).
            self.assertEqual(rs.multiplier, 1)
            self.assertEqual(rs.prefix_count, 50000)
            # next-hop-self so the DUT resolves via the connected interface.
            self.assertEqual(
                rs.set_next_hop_type,
                ixia_types.SetNextHopType.SAME_AS_LOCAL_IP,
            )
            # The fixed community rides on the compact route directly.
            self.assertEqual(rs.bgp_communities, ["65529:39744"])

    def test_compact_geometry_can_use_disjoint_sender_blocks(self) -> None:
        configs = create_ebb_performance_scale_basic_port_configs(
            ebgp_next_hop_self=True,
            ebgp_fixed_communities=["65529:39744"],
            ebgp_prefixes_per_sender=3125,
            ebgp_v6_prefix_block_step="0:0:0:c35::",
            ebgp_v4_prefix_block_step="0.12.53.0",
            **_COMMON_KWARGS,
        )

        scales = _ebgp_route_scales(configs)
        self.assertEqual(len(scales), 2)
        by_afi = {scale.ip_address_family: scale for scale in scales}
        self.assertEqual(by_afi[ixia_types.IpAddressFamily.IPV6].prefix_count, 3125)
        self.assertEqual(
            by_afi[ixia_types.IpAddressFamily.IPV6].prefix_step,
            "0:0:0:c35::",
        )
        self.assertEqual(
            by_afi[ixia_types.IpAddressFamily.IPV4].prefix_step,
            "0.12.53.0",
        )

    def test_compact_geometry_rejects_overlapping_sender_blocks(self) -> None:
        with self.assertRaisesRegex(ValueError, "overlaps"):
            create_ebb_performance_scale_basic_port_configs(
                ebgp_next_hop_self=True,
                ebgp_prefixes_per_sender=3125,
                ebgp_v6_prefix_block_step="0:0:0:1::",
                **_COMMON_KWARGS,
            )


class EbgpFlatImportPathTest(unittest.TestCase):
    """Callers that need a CSV-baked next-hop (PRESERVE_FROM_FILE, e.g.
    separable-policy) keep the flat import_bgp_routes path unchanged -- at 1
    sender its object count is small, so it is safe."""

    def test_default_uses_flat_import_with_unset_next_hop(self) -> None:
        configs = create_ebb_performance_scale_basic_port_configs(**_COMMON_KWARGS)
        # Flat path: import params present, compact route_scales absent.
        self.assertEqual(len(_ebgp_route_scales(configs)), 0)
        params = _ebgp_import_params(configs)
        self.assertEqual(len(params), 2)  # one v4, one v6 eBGP pool
        for p in params:
            # Unset next-hop type -> runtime defaults to MANUALLY (CSV-baked
            # next-hop); modification type stays PRESERVE_FROM_FILE.
            self.assertIsNone(p.set_next_hop_type)
            self.assertEqual(
                p.bgp_next_hop_modification_type,
                ixia_types.BgpNextHopModificationType.PRESERVE_FROM_FILE,
            )

    def test_flat_path_uses_uniform_community_csv(self) -> None:
        """The flat path attaches the UNIFORM community CSV. The diverse
        per-route distribution was removed: unreachable from every production
        caller, and it produced named-community collisions that obscured
        acceptance failures."""
        configs = create_ebb_performance_scale_basic_port_configs(**_COMMON_KWARGS)
        community_cfgs = [
            attr
            for p in _ebgp_import_params(configs)
            for attr in (p.bgp_attribute_configs or [])
            if attr.attribute == ixia_types.BgpAttribute.COMMUNITIES
        ]
        self.assertEqual(len(community_cfgs), 2)
        for c in community_cfgs:
            self.assertIsNone(c.value_lists)
            self.assertIsNotNone(c.file_path)
            self.assertIn("same_communities", c.file_path)


class RouteChurnGeometryTest(unittest.TestCase):
    def _route_scales(
        self,
        *,
        churn_count: int = 100,
        churn_prefix_start_v6: str = "5001:db8:1000::",
    ):
        configs = create_ebb_route_churn_test_basic_port_configs(
            device_name="bag012.ash6",
            ixia_interface_mimic_ebgp="eth1",
            ixia_interface_mimic_ibgp="eth2",
            ebgp_peer_count_v6=100,
            ibgp_peer_count_v6=100,
            ebgp_remote_as=65334,
            ibgp_remote_as=64981,
            initial_prefix_count=50000,
            churn_count=churn_count,
            ixia_ebgp_ic_parent_network_v6="2401:db00:eef0:a00",
            ixia_ibgp_ic_parent_network_v6="2401:db00:eef0:a01",
            churn_prefix_start_v6=churn_prefix_start_v6,
        )
        return {
            route_scale.prefix_name: route_scale
            for port in configs
            for group in port.device_group_configs or []
            for bgp_config in (group.v6_bgp_config,)
            if bgp_config is not None
            for spec in bgp_config.route_scales or []
            for route_scale in (spec.v6_route_scale,)
            if route_scale is not None
        }

    def test_peer_one_pools_tile_at_parameterized_churn_boundary(self) -> None:
        scales = self._route_scales()
        churned = scales["PREFIX_POOL_IPV6_IBGP_PEER_1_CHURNED"]
        control = scales["PREFIX_POOL_IPV6_IBGP_PEER_1_CONTROL"]
        remaining_peers = scales["PREFIX_POOL_IPV6_IBGP_PEERS_REST"]

        self.assertEqual(churned.prefix_count, 100)
        self.assertEqual(control.starting_prefixes, "5001:db8:1000:64::")
        self.assertEqual(control.prefix_count, 49900)
        self.assertEqual(remaining_peers.starting_prefixes, "5001:db8:1000::")
        self.assertEqual(remaining_peers.prefix_count, 50000)
        self.assertEqual(
            {
                churned.prefix_step,
                control.prefix_step,
                remaining_peers.prefix_step,
            },
            {"0:0:0:1::"},
        )

    def test_churn_must_be_a_nonempty_proper_slice(self) -> None:
        with self.assertRaisesRegex(ValueError, "smaller than"):
            self._route_scales(churn_count=50000)

    def test_churn_prefix_base_must_be_aligned_to_prefix_step(self) -> None:
        with self.assertRaisesRegex(ValueError, "aligned to a /64 boundary"):
            self._route_scales(churn_prefix_start_v6="5001:db8:1000::1")
