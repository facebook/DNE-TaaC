# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
import json
import unittest

from taac.abstractions.physical_inventory import (
    BAG010_ASH6,
    BAG012_ASH6,
)
from taac.abstractions.topologies.egress_peer_scale import (
    EGRESS_PEER_SCALE_SWEEP_PEER_COUNTS,
)
from taac.testconfigs.routing.factories.bgp_ebb_characteristic import (
    create_bgp_ebb_characteristic_constant_attribute_storage_ingress_test_config,
    create_bgp_ebb_characteristic_performance_scaling_test_config,
)
from taac.testconfigs.routing.factories.bgp_ebb_scaling import (
    create_bgp_ebb_scaling_performance_test_config,
)
from taac.testconfigs.routing.util.bgp_ebb_setup_tasks import (
    build_bgpcpp_peers_patch_shell_cmds,
)

# The router_id splice fragment written into the in-shell bgpcpp_config merge.
_ROUTER_ID_ASSIGN = "c['router_id']="


def _task_json_params(task) -> dict:
    json_params = task.params.json_params
    if json_params is None:
        raise AssertionError("task must have JSON parameters")
    value = json.loads(json_params)
    if not isinstance(value, dict):
        raise AssertionError("task JSON parameters must be an object")
    return value


def _custom_step_params(config) -> list:
    """Params of every CUSTOM_STEP across the config's playbooks."""
    found = []
    for pb in config.playbooks or []:
        for stage in getattr(pb, "stages", None) or []:
            for step in stage.steps or []:
                step_params = getattr(step, "step_params", None)
                raw = getattr(step_params, "json_params", None) if step_params else None
                if raw:
                    params = json.loads(raw)
                    if params.get("custom_step_name"):
                        found.append(params)
    return found


class PerformanceScalingPhysicalInventoryDrivenTest(unittest.TestCase):
    """The perf-scaling factory is physical-inventory-driven: the TestConfig name derives
    from ``physical_inventory.device_name`` and ``router_id`` is optional so physical inventories that
    rely on the device-default router-id (bag010) work without pinning one."""

    def test_name_derives_from_device(self) -> None:
        # The name is device-derived: {DEVICE}_SC1_EGRESS_PEER_SCALE_TEST. A
        # non-bag010 device (bag012) exercises the derivation independently of
        # the bag010 default.
        config = create_bgp_ebb_characteristic_performance_scaling_test_config(
            BAG012_ASH6
        )
        self.assertEqual(config.name, "BAG012_ASH6_SC1_EGRESS_PEER_SCALE_TEST")

    def test_bag010_builds_without_router_id(self) -> None:
        # bag010 has no router_id — the factory must not require one, and the
        # name must derive from the physical_inventory device_name.
        config = create_bgp_ebb_characteristic_performance_scaling_test_config(
            BAG010_ASH6
        )
        self.assertEqual(config.name, "BAG010_ASH6_SC1_EGRESS_PEER_SCALE_TEST")

    def test_update_group_appends_suffix(self) -> None:
        config = create_bgp_ebb_characteristic_performance_scaling_test_config(
            BAG010_ASH6, enable_update_group=True
        )
        self.assertEqual(
            config.name,
            "BAG010_ASH6_SC1_EGRESS_PEER_SCALE_TEST_UPDATE_GROUP",
        )

    def test_explicit_empty_ixia_overrides_are_preserved(self) -> None:
        config = create_bgp_ebb_scaling_performance_test_config(
            BAG010_ASH6,
            name="EMPTY_IXIA_OVERRIDES",
            egress_peer_counts=[1],
            endpoints=[],
            basic_port_configs=[],
        )

        self.assertEqual([], config.endpoints)
        self.assertEqual([], config.basic_port_configs)

    def test_router_id_spliced_when_present(self) -> None:
        # A real router_id is written into /mnt/flash/bgpcpp_config verbatim
        # (unchanged from the legacy behavior).
        merge = build_bgpcpp_peers_patch_shell_cmds(peers=[], router_id="10.163.28.11")[
            -1
        ]
        self.assertIn("c['router_id']='10.163.28.11'; ", merge)

    def test_router_id_preserved_when_none(self) -> None:
        # router_id=None must NOT emit a router_id assignment (preserve the
        # deployed config's router_id) and must never splice the literal
        # string 'None' into the device config.
        merge = build_bgpcpp_peers_patch_shell_cmds(peers=[], router_id=None)[-1]
        self.assertNotIn(_ROUTER_ID_ASSIGN, merge)
        self.assertNotIn("None", merge)


class PerformanceScalingInterfaceIpCoverageTest(unittest.TestCase):
    """The iBGP interface must carry secondary source-IPs for the FULL sweep.

    The per-iteration rescale rewrites only the bgpcpp peer list, never the
    interface IPs. The canonical interface plan must provision the maximum
    resolved peer set once so every sweep stage can establish.
    """

    def _ibgp_interface_ip_peer_counts(self, config) -> list:
        ibgp_iface = BAG010_ASH6.ixia_ports[1][0]
        counts = []
        for task in config.setup_tasks or []:
            if task.task_name != "interface_ip_configuration":
                continue
            params = _task_json_params(task)
            if params["interface"] == ibgp_iface:
                counts.append(params["peer_count"])
        return counts

    def test_ibgp_interface_covers_full_sweep(self) -> None:
        config = create_bgp_ebb_characteristic_performance_scaling_test_config(
            BAG010_ASH6
        )
        counts = self._ibgp_interface_ip_peer_counts(config)
        self.assertEqual(
            [max(EGRESS_PEER_SCALE_SWEEP_PEER_COUNTS)],
            counts,
            "the canonical interface plan must render the iBGP source-address "
            f"set exactly once; got peer_counts={counts}",
        )


class PerformanceScalingNexthopResolutionGflagTest(unittest.TestCase):
    """The perf-scaling test runs WITHOUT_OPEN_R, so directly-connected egress
    nexthops resolve only when bgp_resolve_nexthops_from_interface_state is set
    in run_bgpcpp.sh. The factory must wire a managed-shell configure-startup
    task that enables it; otherwise nexthops stay unresolved (no path selected)
    and convergence completes vacuously.
    """

    def _configure_startup_params(self, config) -> list:
        params = []
        for task in config.setup_tasks or []:
            if task.task_name != "configure_bgpcpp_startup":
                continue
            params.append(_task_json_params(task))
        return params

    def test_nexthop_resolution_gflag_enabled_via_managed_shell(self) -> None:
        config = create_bgp_ebb_characteristic_performance_scaling_test_config(
            BAG010_ASH6
        )
        matching = [
            p
            for p in self._configure_startup_params(config)
            if p.get("flags", {}).get("bgp_resolve_nexthops_from_interface_state")
            == "true"
        ]
        self.assertEqual(
            len(matching),
            1,
            "exactly one configure_bgpcpp_startup task must enable "
            "bgp_resolve_nexthops_from_interface_state",
        )
        self.assertTrue(
            matching[0].get("use_managed_shell"),
            "the nexthop-resolution gflag task must run over the managed shell "
            "(perf-scaling passes no SSH credentials)",
        )

    def test_no_openr_ingress_only_config_uses_same_mode_invariant(self) -> None:
        config = create_bgp_ebb_characteristic_constant_attribute_storage_ingress_test_config(
            BAG010_ASH6,
            enable_update_group=True,
        )
        matching = [
            params
            for params in self._configure_startup_params(config)
            if params.get("flags", {}).get("bgp_resolve_nexthops_from_interface_state")
            == "true"
        ]
        self.assertEqual(1, len(matching))
        self.assertTrue(matching[0].get("use_managed_shell"))

        flag_indices = [
            index
            for index, task in enumerate(config.setup_tasks or [])
            if task.task_name == "configure_bgpcpp_startup"
            and _task_json_params(task)
            .get("flags", {})
            .get("bgp_resolve_nexthops_from_interface_state")
            == "true"
        ]
        bgp_enable_indices = [
            index
            for index, task in enumerate(config.setup_tasks or [])
            if task.task_name == "arista_daemon_control"
            and _task_json_params(task).get("daemon_name") == "Bgp"
            and _task_json_params(task).get("action") == "enable"
        ]
        self.assertEqual(1, len(flag_indices))
        self.assertGreater(len(bgp_enable_indices), 0)
        self.assertLess(flag_indices[0], bgp_enable_indices[0])

    def test_ingress_only_config_also_resolves_nexthops(self) -> None:
        """SC2 must resolve next-hops too, and be ingress-only for a different
        reason.

        char-2 measures attribute storage in a REAL, best-path selected RIB;
        leaving next-hops unresolvable would measure a different (and easier)
        thing to store, and forces the acceptance gate down to counting RECEIVED
        rather than accepted-and-resolved. Selection state does not distort
        sc2_memory_growth either -- the path count is fixed at 800K across the
        sweep, so it is a constant additive term, not a growth term.

        Ingress-only comes from configuring NO egress peer, which the sibling
        test below pins.
        """
        config = create_bgp_ebb_characteristic_constant_attribute_storage_ingress_test_config(
            BAG010_ASH6,
            enable_update_group=True,
        )
        enabling = [
            params
            for params in self._configure_startup_params(config)
            if params.get("flags", {}).get("bgp_resolve_nexthops_from_interface_state")
            == "true"
        ]
        self.assertEqual(
            1,
            len(enabling),
            "SC2 measures a resolved RIB; exactly one setup task must enable "
            "bgp_resolve_nexthops_from_interface_state",
        )

    def test_ingress_only_comes_from_having_no_egress_peer(self) -> None:
        """The property that actually makes SC2 ingress-only.

        With next-hops resolving, nothing stops advertisement except the absence
        of an egress peer -- so pin it. Note BGP++ does NOT suppress eBGP->eBGP
        under update-group (``AdjRibOutGroup::canAnnounceForGroup`` returns true
        for eBGP without consulting ``suppressLoopedAdvertisements``), so the
        iBGP peer count reaching zero is what keeps the DUT silent.
        """
        config = create_bgp_ebb_characteristic_constant_attribute_storage_ingress_test_config(
            BAG010_ASH6,
            enable_update_group=True,
        )
        sweep_steps = [
            params
            for params in _custom_step_params(config)
            if "unique_combination_counts" in params
        ]
        self.assertEqual(
            1, len(sweep_steps), "expected exactly one combination-sweep step"
        )
        self.assertEqual(
            0,
            sweep_steps[0].get("constant_ibgp_peer_count"),
            "SC2 is ingress-only by configuring no iBGP egress peer",
        )


class PerformanceScalingRouteFilterClearTest(unittest.TestCase):
    """This test injects arbitrary scale prefixes that are not in the device's
    baked-in route registry, so the Centralized Route Filter (CRF) must be
    cleared -- otherwise all but the registered handful are denied at ingress
    ("Denied by Route Filter Policy")."""

    def test_route_filter_cleared(self) -> None:
        config = create_bgp_ebb_characteristic_performance_scaling_test_config(
            BAG010_ASH6
        )
        clear_tasks = [
            task
            for task in (config.setup_tasks or [])
            if task.task_name == "bgp_clear_route_filter"
        ]
        self.assertEqual(
            len(clear_tasks),
            1,
            "exactly one bgp_clear_route_filter task must be wired so injected "
            "prefixes are not blocked by the route registry",
        )
