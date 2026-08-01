# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
import json
import unittest

from taac.abstractions.physical_inventory import BAG010_ASH6
from taac.testconfigs.routing.adhoc_bgp_ebb_characteristic import (
    BAG010_ASH6_SC6_CHURN_PROCESSING_TEST_UPDATE_GROUP_CONFIG,
)
from taac.testconfigs.routing.factories.bgp_ebb_characteristic import (
    create_bgp_ebb_characteristic_route_churn_processing_test_config,
)

_SC6 = BAG010_ASH6_SC6_CHURN_PROCESSING_TEST_UPDATE_GROUP_CONFIG
_NEXTHOP_IFACE_STATE_FLAG = "bgp_resolve_nexthops_from_interface_state"


def _task_names(config) -> list:
    return [task.task_name for task in (config.setup_tasks or [])]


def _params_for(config, task_name: str) -> list:
    return [
        json.loads(task.params.json_params or "{}")
        for task in (config.setup_tasks or [])
        if task.task_name == task_name
    ]


def _custom_step_params(config) -> dict:
    """Extract the custom-step params_dict (carries the SC6 churn sweep) from the
    config's playbook."""
    for pb in config.playbooks or []:
        for stage in getattr(pb, "stages", None) or []:
            for step in getattr(stage, "steps", None) or []:
                sp = getattr(step, "step_params", None)
                raw = getattr(sp, "json_params", None) if sp else None
                if raw:
                    d = json.loads(raw)
                    if "prefix_configs" in d and "churn_count" in d:
                        return d
    return {}


def _periodic_task_names(config) -> list:
    """Extract periodic task names from the playbook."""
    for pb in config.playbooks or []:
        return [
            getattr(pt, "name", None)
            for pt in getattr(pb, "periodic_tasks", None) or []
        ]
    return []


class Sc6TestbedDrivenNameTest(unittest.TestCase):
    """The SC6 factory is testbed-driven (mirrors SC3/SC4): the name derives from
    ``testbed.device_name`` + ``_UPDATE_GROUP`` when ``enable_update_group=True``."""

    def test_name_derives_from_device_with_ug(self) -> None:
        config = create_bgp_ebb_characteristic_route_churn_processing_test_config(
            BAG010_ASH6, enable_update_group=True
        )
        self.assertEqual(
            config.name, "BAG010_ASH6_SC6_CHURN_PROCESSING_TEST_UPDATE_GROUP"
        )


class Sc6DeviceSetupTest(unittest.TestCase):
    """SC6 needs the interface-state nexthop gflag and Centralized Route Filter
    cleared (same device layer as SC3/SC4) so the iBGP-injected churn prefixes
    are accepted."""

    def test_nexthop_gflag_enabled_via_managed_shell(self) -> None:
        matching = [
            p
            for p in _params_for(_SC6, "configure_bgpcpp_startup")
            if p.get("flags", {}).get(_NEXTHOP_IFACE_STATE_FLAG) == "true"
        ]
        self.assertEqual(len(matching), 1)
        self.assertTrue(matching[0].get("use_managed_shell"))

    def test_route_filter_cleared(self) -> None:
        self.assertEqual(len(_params_for(_SC6, "bgp_clear_route_filter")), 1)


class Sc6ChurnSweepTest(unittest.TestCase):
    """SC6 sweeps the total route scale (5K→50K) at a fixed churn count (100).
    The per-scale convergence budget is generous (700s) so the engine's built-in
    gate is observe-first."""

    def test_prefix_sweep_with_fixed_churn(self) -> None:
        params = _custom_step_params(_SC6)
        self.assertEqual(
            params.get("prefix_configs"),
            [[5000, 700], [10000, 700], [20000, 700], [50000, 700]],
        )
        self.assertEqual(params.get("churn_count"), 100)
        self.assertEqual(params.get("max_convergence_time_seconds"), 700)


class Sc6QueueBackpressureGateTest(unittest.TestCase):
    """SC6 wires the queue-backpressure periodic task to monitor egress-queue
    backlog (permissive default, observe-only until calibrated)."""

    def test_queue_backpressure_periodic_task_wired(self) -> None:
        task_names = _periodic_task_names(_SC6)
        self.assertIn("bgp_queue_backpressure_check", task_names)


class Sc6DriverBindingTest(unittest.TestCase):
    """SC6 must bind the DUT to the BGP++-aware AristaFbossSwitch driver via
    host_os_type_map, so the MID_TEST health checks query BGP++ over thrift
    instead of falling back to native ar-bgp CLI. Mirrors SC2/SC3/SC4."""

    def test_host_os_type_map_binds_arista_fboss(self) -> None:
        os_map = _SC6.host_os_type_map or {}
        self.assertEqual(len(os_map), 1)
        self.assertEqual([v.name for v in os_map.values()], ["ARISTA_FBOSS"])


class Sc6UpdateGroupEnablementTest(unittest.TestCase):
    """SC6 enables update-group via a post-replace config-patch task (global
    bgp_setting_config flag; the persisted peers are re-grouped on the daemon
    restart). The UG health check is present in the playbook postchecks."""

    def test_update_group_config_patch_setup_present(self) -> None:
        run_cmds_tasks = _params_for(_SC6, "run_commands_on_shell")
        ug_patch_tasks = [
            p
            for p in run_cmds_tasks
            if any("enable_update_group" in cmd for cmd in p.get("cmds", []))
        ]
        self.assertEqual(len(ug_patch_tasks), 1, "UG config-patch task not found")

    def test_daemon_restart_after_ug_patch(self) -> None:
        daemon_tasks = _params_for(_SC6, "arista_daemon_control")
        bgp_tasks = [p for p in daemon_tasks if p.get("daemon_name") == "Bgp"]
        self.assertGreaterEqual(
            len(bgp_tasks), 2, "Expected disable + enable Bgp daemon tasks"
        )

    def test_update_group_health_check_in_postchecks(self) -> None:
        for pb in _SC6.playbooks or []:
            postchecks = getattr(pb, "postchecks", None) or []
            ug_checks = [
                c
                for c in postchecks
                if "BGP_UPDATE_GROUP_CHECK" in str(getattr(c, "name", None))
            ]
            self.assertGreaterEqual(
                len(ug_checks), 1, "UG health check not found in postchecks"
            )


if __name__ == "__main__":
    unittest.main()
