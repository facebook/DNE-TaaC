# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
import json
import unittest

from taac.abstractions.eos_bgpcpp_setup_tasks import (
    create_bgpcpp_logging_setup_task,
)
from taac.abstractions.physical_inventory import BAG010_ASH6
from taac.testconfigs.routing.factories.bgp_ebb_characteristic import (
    _validate_sc6_startup_order,
    create_bgp_ebb_characteristic_route_churn_processing_test_config,
)
from taac.testconfigs.routing.factories.bgp_ebb_scaling import (
    _sc6_ipv6_address,
    create_bgp_ebb_scaling_route_churn_prefix_test_config,
)
from taac.testconfigs.routing.util.bgp_ebb_constants import (
    EBB_BGPCPP_LOGGING_CONFIG,
    FIBAGENT_BGP_CONF_CONFIGERATOR_PATH,
    FIBAGENT_BGP_CONF_DEVICE_PATH,
)
from taac.test_as_a_config import types as taac_types

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


def _all_custom_step_params(config) -> list[dict]:
    params = []
    for playbook in config.playbooks or []:
        for stage in getattr(playbook, "stages", None) or []:
            for step in getattr(stage, "steps", None) or []:
                step_params = getattr(step, "step_params", None)
                raw = getattr(step_params, "json_params", None) if step_params else None
                if raw:
                    params.append(json.loads(raw))
    return params


def _periodic_task_names(config) -> list:
    """Extract periodic task names from the playbook."""
    for pb in config.playbooks or []:
        return [
            getattr(pt, "name", None)
            for pt in getattr(pb, "periodic_tasks", None) or []
        ]
    return []


def _periodic_params(config, periodic_name: str) -> dict:
    for playbook in config.playbooks or []:
        for periodic_task in getattr(playbook, "periodic_tasks", None) or []:
            if getattr(periodic_task, "name", None) != periodic_name:
                continue
            params_list = periodic_task.params_list or []
            if params_list:
                return json.loads(params_list[0].json_params or "{}")
            task = getattr(periodic_task, "task", None)
            params = getattr(task, "params", None)
            return json.loads(getattr(params, "json_params", None) or "{}")
    return {}


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

    def test_uses_info_logging_instead_of_per_prefix_dbg5(self) -> None:
        commands = [
            command
            for params in _params_for(_SC6, "run_commands_on_shell")
            for command in params.get("cmds", [])
        ]

        def logging_command(logging_config: str) -> str:
            task = create_bgpcpp_logging_setup_task(
                "dut.example.com",
                logging_config,
            )
            return json.loads(task.params.json_params or "{}")["cmds"][0]

        self.assertIn(
            logging_command("INFO;default:async=true"),
            commands,
        )
        self.assertNotIn(
            logging_command(EBB_BGPCPP_LOGGING_CONFIG),
            commands,
        )

    def test_raises_fibagent_bgp_queue_timeout_for_50k_sync(self) -> None:
        matching = [
            params
            for params in _params_for(_SC6, "eos_compiler_lifecycle")
            if params.get("action") == "routing_config_install"
            and params.get("destination") == FIBAGENT_BGP_CONF_DEVICE_PATH
        ]
        self.assertEqual(1, len(matching))
        self.assertEqual(
            FIBAGENT_BGP_CONF_CONFIGERATOR_PATH,
            matching[0].get("source_path"),
        )
        self.assertEqual(
            [
                {
                    "path": ["1", "rec", "36", "i32"],
                    "value": 60_000,
                }
            ],
            matching[0].get("json_i32_overrides"),
        )


class Sc6ChurnSweepTest(unittest.TestCase):
    """SC6 sweeps the total route scale (5K→50K) at fixed measurable churn.

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
        self.assertEqual(params.get("expected_ebgp_peer_count"), 100)
        self.assertEqual(params.get("expected_ibgp_peer_count"), 100)
        self.assertEqual(params.get("churn_prefix_start_v6"), "5001:db8:1000::")
        self.assertEqual(params.get("churn_prefix_length"), 64)

    def test_capture_direction_maps_match_ixia_address_geometry(self) -> None:
        params = _custom_step_params(_SC6)
        self.assertEqual(
            params.get("ibgp_receiver_source_pairs"),
            {"2401:db00:e50d:11:9::10": "2401:db00:e50d:11:9::11"},
        )
        egress_pairs = params.get("ebgp_receiver_source_pairs")
        self.assertIsInstance(egress_pairs, dict)
        assert isinstance(egress_pairs, dict)
        self.assertEqual(len(egress_pairs), 100)
        self.assertEqual(
            egress_pairs.get("2401:db00:e50d:11:8::11"),
            "2401:db00:e50d:11:8::10",
        )
        self.assertEqual(
            egress_pairs.get("2401:db00:e50d:11:8::d7"),
            "2401:db00:e50d:11:8::d6",
        )

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

    def test_every_sweep_scale_must_leave_an_unchurned_control_slice(self) -> None:
        with self.assertRaisesRegex(ValueError, "larger than churn_count"):
            create_bgp_ebb_scaling_route_churn_prefix_test_config(
                BAG010_ASH6,
                name="INVALID_SC6_GEOMETRY",
                ebgp_peer_count=2,
                ibgp_peer_count=2,
                prefix_configs=[(100, 1)],
                churn_count=100,
            )

    def test_ipv6_parent_fragment_accepts_existing_compression_suffix(self) -> None:
        self.assertEqual(
            _sc6_ipv6_address("2401:db00:e50d:11:8", 0x11),
            _sc6_ipv6_address("2401:db00:e50d:11:8::", 0x11),
        )


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


class Sc6DeviceStateGuardTest(unittest.TestCase):
    def test_snapshots_precede_every_sc6_device_mutation(self) -> None:
        setup = _SC6.setup_tasks or []
        actions = []
        for task in setup:
            if task.task_name != "eos_compiler_lifecycle":
                break
            actions.append(json.loads(task.params.json_params or "{}").get("action"))
        self.assertEqual("routing_component_snapshot", actions[0])
        self.assertTrue(
            all(action == "routing_config_snapshot" for action in actions[1:])
        )
        first_mutation = setup[len(actions)]
        self.assertEqual(first_mutation.task_name, "configure_bgpcpp_startup")

    def test_teardown_uses_dependency_aware_restore(self) -> None:
        teardown = _SC6.teardown_tasks or []
        self.assertEqual(len(teardown), 1)
        params = json.loads(teardown[0].params.json_params or "{}")
        self.assertEqual(params.get("action"), "routing_component_restore")


class Sc6ThriftTimeoutTest(unittest.TestCase):
    """SC6 issues the largest full SyncFib of any config here -- 50K prefixes at
    the top of the sweep. BAG012 measured a 391.5s cold sync and postchecks
    load-shedding at the default 100ms server queue deadline. The deployed
    BAG012 package does not support the newer server queue flag, so SC6 keeps
    the supported client budget and bounds the postcheck route population."""

    def test_startup_task_sets_supported_client_timeout(self) -> None:
        params = _params_for(_SC6, "configure_bgpcpp_startup")
        matching = [
            p
            for p in params
            if p.get("flags", {}).get("agent_thrift_recv_timeout_ms") == "600000"
        ]
        self.assertEqual(1, len(matching), f"startup tasks={params}")
        self.assertTrue(
            all("thrift_queue_timeout_ms" not in p.get("flags", {}) for p in params)
        )

    def test_flag_is_applied_before_the_daemon_reads_it(self) -> None:
        tasks = _SC6.setup_tasks or []
        params = [json.loads(task.params.json_params or "{}") for task in tasks]
        flag_indices = [
            index
            for index, (task, task_params) in enumerate(zip(tasks, params))
            if task.task_name == "configure_bgpcpp_startup"
            and task_params.get("flags", {}).get("agent_thrift_recv_timeout_ms")
            == "600000"
        ]
        bgp_enable_indices = [
            index
            for index, (task, task_params) in enumerate(zip(tasks, params))
            if task.task_name == "arista_daemon_control"
            and task_params.get("daemon_name") == "Bgp"
            and task_params.get("action") == "enable"
        ]
        self.assertEqual(len(flag_indices), 1)
        self.assertGreater(len(bgp_enable_indices), 0)
        self.assertLess(flag_indices[0], bgp_enable_indices[0])

    def test_factory_contract_rejects_timeout_after_bgp_enable(self) -> None:
        tasks = _SC6.setup_tasks or []
        timeout_task = next(
            task
            for task in tasks
            if task.task_name == "configure_bgpcpp_startup"
            and json.loads(task.params.json_params or "{}")
            .get("flags", {})
            .get("agent_thrift_recv_timeout_ms")
            == "600000"
        )
        bgp_enable_task = next(
            task
            for task in tasks
            if task.task_name == "arista_daemon_control"
            and json.loads(task.params.json_params or "{}").get("daemon_name") == "Bgp"
            and json.loads(task.params.json_params or "{}").get("action") == "enable"
        )
        with self.assertRaisesRegex(ValueError, "must precede"):
            _validate_sc6_startup_order([bgp_enable_task, timeout_task])

    def test_validator_skips_unrelated_nonobject_params(self) -> None:
        tasks = _SC6.setup_tasks or []
        timeout_task = next(
            task
            for task in tasks
            if task.task_name == "configure_bgpcpp_startup"
            and json.loads(task.params.json_params or "{}")
            .get("flags", {})
            .get("agent_thrift_recv_timeout_ms")
            == "600000"
        )
        bgp_enable_task = next(
            task
            for task in tasks
            if task.task_name == "arista_daemon_control"
            and json.loads(task.params.json_params or "{}").get("daemon_name") == "Bgp"
            and json.loads(task.params.json_params or "{}").get("action") == "enable"
        )
        unrelated_tasks = [
            taac_types.Task(
                task_name="unrelated_array",
                params=taac_types.Params(json_params="[]"),
            ),
            taac_types.Task(
                task_name="unrelated_scalar",
                params=taac_types.Params(json_params="1"),
            ),
            taac_types.Task(
                task_name="configure_bgpcpp_startup",
                params=taac_types.Params(json_params='{"flags": []}'),
            ),
        ]

        _validate_sc6_startup_order([*unrelated_tasks, timeout_task, bgp_enable_task])

    def test_validator_skips_unrelated_malformed_json_params(self) -> None:
        tasks = _SC6.setup_tasks or []
        timeout_task = next(
            task
            for task in tasks
            if task.task_name == "configure_bgpcpp_startup"
            and json.loads(task.params.json_params or "{}")
            .get("flags", {})
            .get("agent_thrift_recv_timeout_ms")
            == "600000"
        )
        bgp_enable_task = next(
            task
            for task in tasks
            if task.task_name == "arista_daemon_control"
            and json.loads(task.params.json_params or "{}").get("daemon_name") == "Bgp"
            and json.loads(task.params.json_params or "{}").get("action") == "enable"
        )
        unrelated_task = taac_types.Task(
            task_name="unrelated_malformed",
            params=taac_types.Params(json_params="not JSON"),
        )

        _validate_sc6_startup_order([unrelated_task, timeout_task, bgp_enable_task])

    def test_validator_rejects_malformed_relevant_json_params(self) -> None:
        malformed_task = taac_types.Task(
            task_name="configure_bgpcpp_startup",
            params=taac_types.Params(json_params="not JSON"),
        )

        with self.assertRaisesRegex(ValueError, "invalid JSON params"):
            _validate_sc6_startup_order([malformed_task])

    def test_managed_startup_task_never_requests_unsupported_restart(self) -> None:
        params = _params_for(_SC6, "configure_bgpcpp_startup")
        self.assertTrue(params)
        for task_params in params:
            if task_params.get("use_managed_shell"):
                self.assertFalse(task_params.get("restart_bgp", False))

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

    def test_queue_monitor_collects_complete_duration_delta(self) -> None:
        params = _periodic_params(_SC6, "bgp_queue_backpressure_check")
        self.assertEqual(params.get("block_duration_threshold_ms"), 0)
        self.assertTrue(params.get("require_complete_delta"))

    def test_custom_step_owns_sc6_queue_verdict(self) -> None:
        params = _custom_step_params(_SC6)
        self.assertEqual(params.get("queue_block_duration_ceiling_ms"), 0)
        self.assertIn("queue_measurement_gate_mode", params)
        self.assertIn("queue_backpressure_gate_mode", params)


class Sc6OperationalGuardTest(unittest.TestCase):
    def test_memory_ceiling_allows_observed_50k_readiness_peak(self) -> None:
        params = _periodic_params(_SC6, "bgpd_mem_util_check")
        self.assertEqual(params.get("threshold"), 7 * (1024**3))


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

    def test_postcheck_drain_preserves_sessions_at_bounded_scale(self) -> None:
        drain_steps = [
            params
            for params in _all_custom_step_params(_SC6)
            if params.get("postcheck_drain_only")
        ]
        self.assertEqual(1, len(drain_steps))
        self.assertEqual(101, drain_steps[0].get("postcheck_prefix_count"))
        self.assertEqual(100, drain_steps[0].get("expected_ebgp_peer_count"))
        self.assertEqual(100, drain_steps[0].get("expected_ibgp_peer_count"))

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
