# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
import json
import unittest

from taac.abstractions.physical_inventory import BAG010_ASH6
from taac.testconfigs.routing.factories.bgp_ebb_characteristic import (
    create_bgp_ebb_characteristic_route_churn_processing_test_config,
)

_SC6 = create_bgp_ebb_characteristic_route_churn_processing_test_config(
    BAG010_ASH6,
    enable_update_group=True,
)
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

    The second element of each pair is only the settle wait before churn is
    applied, not a gate. The per-scale ceiling is the separate 30s
    ``max_convergence_time_seconds``: a fixed 100-route churn should reconverge
    in seconds, so the engine's old 700s budget could only catch a total hang,
    never the "P(N) grew with N" regression this characteristic targets."""

    def test_prefix_sweep_with_fixed_churn(self) -> None:
        params = _custom_step_params(_SC6)
        self.assertEqual(
            params.get("prefix_configs"),
            [[5000, 120], [10000, 120], [20000, 180], [50000, 300]],
        )
        self.assertEqual(params.get("churn_count"), 100)
        self.assertEqual(params.get("max_convergence_time_seconds"), 30)

    def test_capture_window_bounded_but_above_fail_ceiling(self) -> None:
        # The soak IS the packet-capture window and is otherwise dead wall
        # clock, paid twice per scale. It must stay above the hard-fail ceiling
        # (else a real burst is clipped and silently under-measured) and well
        # below the engine's 600s default (else unrelated late UPDATEs inflate
        # the measured span, and the IXIA capture buffer can wrap at 50K).
        params = _custom_step_params(_SC6)
        soak = params.get("soak_duration_seconds")
        ceiling = params.get("max_convergence_time_seconds")
        self.assertIsNotNone(soak, "SC6 must pin its own capture window")
        self.assertGreater(soak, ceiling)
        self.assertLessEqual(soak, 120)


class Sc6ManagedProvisioningTest(unittest.TestCase):
    """No SC6 setup task may reach the device over raw SSH.

    The churn engine SC6 reuses was written for the ebXX lab boxes and defaults
    to ``ssh_user="admin"`` / ``ssh_password="dnepit"`` -- a credential that only
    exists there. bag010 is a cicd/qual device with no ``admin`` account, so any
    task carrying SSH credentials fails setup outright with
    ``admin@bag010.ash6: Permission denied (publickey,password)``.

    This asserts over EVERY setup task rather than a named one on purpose: the
    original gflag assertion filtered by flag name, so it never inspected the
    ``agent_thrift_recv_timeout_ms`` startup task that actually failed first."""

    def test_no_setup_task_carries_ssh_credentials(self) -> None:
        offenders = [
            (task.task_name, sorted(k for k in params if k.startswith("ssh_")))
            for task, params in (
                (t, json.loads(t.params.json_params or "{}"))
                for t in (_SC6.setup_tasks or [])
            )
            if any(k.startswith("ssh_") for k in params)
        ]
        self.assertEqual(offenders, [], f"raw-SSH setup tasks found: {offenders}")

    def test_peers_are_written_without_replace_bgp_peers(self) -> None:
        # ``replace_bgp_peers`` has no managed branch -- it always builds an
        # AristaSSHHelper -- so its absence is what proves the managed path.
        self.assertNotIn("replace_bgp_peers", _task_names(_SC6))


class Sc6AgentThriftTimeoutTest(unittest.TestCase):
    """SC6 issues the largest full SyncFib of any config here -- 50K prefixes at
    the top of the sweep -- and was the only one left on bgpd's 45s default
    FIB-agent receive timeout while every sibling set 160s."""

    def test_startup_task_sets_the_recv_timeout(self) -> None:
        params = _params_for(_SC6, "configure_bgpcpp_startup")
        matching = [
            p
            for p in params
            if p.get("flags", {}).get("agent_thrift_recv_timeout_ms") == "160000"
        ]
        self.assertEqual(1, len(matching), f"startup tasks={params}")

    def test_flag_is_actually_applied_not_just_written(self) -> None:
        # The task edits run_bgpcpp.sh, which bgpd only re-reads on start, and
        # extra_setup_tasks land AFTER the managed recipe's final Bgp enable.
        # Since the step no longer cycles the daemon per scale, without the
        # restart the flag would sit on disk unread and the run would silently
        # use the 45s default.
        params = _params_for(_SC6, "configure_bgpcpp_startup")
        matching = [
            p
            for p in params
            if p.get("flags", {}).get("agent_thrift_recv_timeout_ms") == "160000"
        ]
        self.assertTrue(matching[0].get("restart_bgp"), f"task={matching[0]}")

    def test_uses_managed_shell(self) -> None:
        # bag010 is a cicd device with no ``admin`` login, so a raw-SSH startup
        # task fails with Permission denied.
        params = _params_for(_SC6, "configure_bgpcpp_startup")
        self.assertTrue(all(p.get("use_managed_shell") for p in params))


class Sc6DaemonRestartBudgetTest(unittest.TestCase):
    """Pin how many times setup cycles the Bgp daemon.

    Every restart is minutes of wall clock and a chance to land in the
    out-of-order-init state (bgpd restarted independently of FibAgentBgp) that
    shows up later as a RIB-FIB inconsistency. The count should only ever go
    down; this fails loudly if a future setup change quietly adds another.

    Counts SETUP cycles only. The per-scale restarts the custom step performs at
    runtime are not visible here -- see the step's own budget."""

    def test_setup_bgp_daemon_cycle_count(self) -> None:
        # 2 cycles: the consolidated ACL/thrift-user cycle, and the
        # peer-rewrite cycle (the daemon only reads the new peer list on
        # enable). Both are load-bearing. Merging them means writing peers and
        # ACLs before a single cycle -- a change to the shared recipe SC2/SC3/SC4
        # also use, so it is a separate diff, not a drive-by here.
        bgp_actions = [
            p.get("action")
            for p in _params_for(_SC6, "arista_daemon_control")
            if p.get("daemon_name") == "Bgp"
        ]
        self.assertEqual(bgp_actions.count("enable"), 2, f"actions={bgp_actions}")


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
    """SC6 consumes update-group from the shared Configerator baseline and
    verifies the running state after BGP starts. The UG health check is present
    in the playbook postchecks."""

    def test_update_group_config_is_not_overwritten_during_setup(self) -> None:
        run_cmds_tasks = _params_for(_SC6, "run_commands_on_shell")
        ug_patch_tasks = [
            p
            for p in run_cmds_tasks
            if any("bgp_setting_config" in cmd for cmd in p.get("cmds", []))
        ]
        self.assertEqual([], ug_patch_tasks)

    def test_bgp_restarts_after_config_deployment(self) -> None:
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
