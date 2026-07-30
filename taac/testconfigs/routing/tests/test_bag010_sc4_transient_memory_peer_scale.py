# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
import json
import unittest

from taac.testconfigs.routing.adhoc_bgp_ebb_characteristic import (
    BAG010_ASH6_SC4_TRANSIENT_MEMORY_PEER_SCALE_TEST_UPDATE_GROUP_CONFIG,
)
from taac.testconfigs.routing.factories.bgp_ebb_characteristic import (
    _SC4_FIXED_IBGP_PEER_COUNT,
    _SC4_INGRESS_EBGP_PEER_COUNTS,
    _SC4_PREFIX_COUNT,
    create_bgp_ebb_characteristic_transient_memory_peer_scale_test_config,
)
from taac.testconfigs.routing.physical_inventory import (
    BAG010_ASH6,
    BAG012_ASH6,
)

_GFLAG = "bgp_resolve_nexthops_from_interface_state"
_INGRESS_PLAYBOOK_NAME = "Performance_Scaling_Ingress_Peer_Sweep"
_SC4_UG = BAG010_ASH6_SC4_TRANSIENT_MEMORY_PEER_SCALE_TEST_UPDATE_GROUP_CONFIG

# IxNetwork rejects any port whose imported-route total exceeds this hard cap.
_IXIA_MAX_ROUTES_PER_PORT = 5_000_000
# SC2's ingress path scale (8 peers x 100K = 800K, v6-only). SC4 is bounded to
# the same parity so its steady/transient memory tracks SC2's ingress load.
_SC2_INGRESS_PATH_PARITY = 800_000


def _task_names(config) -> list:
    return [task.task_name for task in (config.setup_tasks or [])]


def _params_for(config, task_name: str) -> list:
    return [
        json.loads(task.params.json_params or "{}")
        for task in (config.setup_tasks or [])
        if task.task_name == task_name
    ]


def _sweep_playbook(config):
    for pb in config.playbooks or []:
        if getattr(pb, "name", "") == _INGRESS_PLAYBOOK_NAME:
            return pb
    return None


class Sc4TestbedDrivenNameTest(unittest.TestCase):
    """The SC4 factory is testbed-driven (mirrors SC1/SC3): the name derives from
    ``testbed.device_name`` and update-group appends the suffix."""

    def test_name_derives_from_device(self) -> None:
        # A non-bag010 device (bag012) exercises the derivation independently.
        config = create_bgp_ebb_characteristic_transient_memory_peer_scale_test_config(
            BAG012_ASH6
        )
        self.assertEqual(
            config.name, "BAG012_ASH6_SC4_TRANSIENT_MEMORY_PEER_SCALE_TEST"
        )

    def test_bag010_update_group_appends_suffix(self) -> None:
        self.assertEqual(
            _SC4_UG.name,
            "BAG010_ASH6_SC4_TRANSIENT_MEMORY_PEER_SCALE_TEST_UPDATE_GROUP",
        )


class Sc4IngressResolutionTest(unittest.TestCase):
    """SC4 advertises RESOLVABLE routes to the fixed iBGP egress fan-out (unlike
    ingress-only SC2), so it needs the interface-state nexthop gflag plus the
    Centralized Route Filter cleared -- same device layer as SC1/SC3."""

    def test_nexthop_gflag_enabled_via_managed_shell(self) -> None:
        matching = [
            p
            for p in _params_for(_SC4_UG, "configure_bgpcpp_startup")
            if p.get("flags", {}).get(_GFLAG) == "true"
        ]
        self.assertEqual(len(matching), 1)
        self.assertTrue(matching[0].get("use_managed_shell"))

    def test_route_filter_cleared(self) -> None:
        self.assertEqual(len(_params_for(_SC4_UG, "bgp_clear_route_filter")), 1)


class Sc4IngressSweepTest(unittest.TestCase):
    """SC4 sweeps the eBGP INGRESS sender count at a fixed iBGP egress fan-out via
    the ingress-sweep playbook: one Stage per sweep entry + a trailing aggregator
    Stage (the INGRESS complement of SC1's egress sweep)."""

    def test_uses_ingress_sweep_playbook(self) -> None:
        self.assertIsNotNone(_sweep_playbook(_SC4_UG))

    def test_one_stage_per_sweep_entry_plus_aggregator(self) -> None:
        pb = _sweep_playbook(_SC4_UG)
        stages = getattr(pb, "stages", None) or []
        self.assertEqual(len(stages), len(_SC4_INGRESS_EBGP_PEER_COUNTS) + 1)


class Sc4InterfaceIpCoverageTest(unittest.TestCase):
    """The swept axis is eBGP, so the eBGP interface must carry secondary IPs for
    the sweep MAX (per AF = max(sweep)) -- re-laid once at the full max so every
    Stage's eBGP senders have a local source address."""

    def _iface_peer_counts(self, config, interface: str) -> list:
        return [
            p["peer_count"]
            for p in _params_for(config, "interface_ip_configuration")
            if p["interface"] == interface
        ]

    def test_ebgp_interface_covers_sweep_max(self) -> None:
        counts = self._iface_peer_counts(_SC4_UG, BAG010_ASH6.ixia_ports[0][0])
        self.assertIn(max(_SC4_INGRESS_EBGP_PEER_COUNTS), counts)

    def test_ibgp_interface_is_v6_only(self) -> None:
        # Regression guard (P2441146392): the iBGP egress interface must be laid
        # v6-only. Dual-stack lays 500 v6 + 500 v4 = 1000 secondaries on one
        # interface, overflowing Arista's ~500-secondary-per-interface ceiling,
        # so v6 iBGP peers past ~250 get no local source IP and stay IDLE.
        ibgp_iface = BAG010_ASH6.ixia_ports[1][0]
        tasks = [
            p
            for p in _params_for(_SC4_UG, "interface_ip_configuration")
            if p["interface"] == ibgp_iface
        ]
        self.assertTrue(tasks, "iBGP interface must be provisioned")
        for p in tasks:
            self.assertEqual(p.get("address_families"), ["ipv6"])
            self.assertEqual(p.get("peer_count"), _SC4_FIXED_IBGP_PEER_COUNT)


class Sc4FixedEgressTest(unittest.TestCase):
    """The iBGP egress fan-out is a fixed scalar (not swept): the per-iteration
    factory holds it constant while only the eBGP INGRESS sender count varies. It
    is sized at SC3's fan-out so the transient burst has a realistic, non-trivial
    egress baseline (both SC3 and SC4 gate the transient HM-SSM)."""

    def test_fixed_ibgp_egress_is_large_constant(self) -> None:
        # Egress is a fixed, non-trivial fan-out held constant across the whole
        # ingress sweep -- it is the constant axis (>= the max swept ingress
        # count), not the swept one.
        self.assertGreater(_SC4_FIXED_IBGP_PEER_COUNT, 0)
        self.assertGreaterEqual(
            _SC4_FIXED_IBGP_PEER_COUNT, max(_SC4_INGRESS_EBGP_PEER_COUNTS)
        )


class Sc4V6OnlyBudgetTest(unittest.TestCase):
    """SC4 is v6-only, so the single v6 eBGP IXIA port holds
    ``max(sweep) * prefix_count`` paths (no dual-stack x2 factor). That peak must
    stay within IxNetwork's per-port import limit and at SC2's ~800K ingress
    parity -- the whole point of the v6-only + bounded-sweep redesign."""

    def _peak_v6_ingress_paths(self) -> int:
        return max(_SC4_INGRESS_EBGP_PEER_COUNTS) * _SC4_PREFIX_COUNT

    def test_peak_v6_ingress_paths_within_ixia_limit(self) -> None:
        self.assertLessEqual(self._peak_v6_ingress_paths(), _IXIA_MAX_ROUTES_PER_PORT)

    def test_peak_v6_ingress_paths_match_sc2_parity(self) -> None:
        self.assertLessEqual(self._peak_v6_ingress_paths(), _SC2_INGRESS_PATH_PARITY)


class Sc4UpdateGroupTest(unittest.TestCase):
    """All SC tests run with update-group enabled, so only the ``_UPDATE_GROUP``
    variant is kept. The mirrored SC1 device layer must have laid interface IPs."""

    def test_device_setup_is_provisioned(self) -> None:
        self.assertIn("interface_ip_configuration", _task_names(_SC4_UG))
