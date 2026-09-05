# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe

"""Structural tests for FPF graceful-restart collection contracts."""

import importlib
import json
import os
import unittest
from unittest.mock import patch

from taac.playbooks.playbook_definitions import (
    _resolve_fpf_hrt_precheck_topology,
)
from taac.testconfigs.fpf import (
    fpf_hardening_common,
    fpf_shared_injection_suite,
    fpf_tc05_bgp_gr_within_window,
    fpf_tc06_bgp_gr_beyond_window,
    fpf_tc07_fsdb_gr_within_window,
    fpf_tc08_fsdb_gr_beyond_window,
    fpf_tc15_interface_disable,
    fpf_tc23_bgp_restart,
    fpf_tc25_wedge_agent_restart,
)
from taac.testconfigs.fpf.fpf_hardening_common import (
    fpf_rf_vf_groups,
)


def _playbook(config, name):
    return next(playbook for playbook in config.playbooks if playbook.name == name)


def _check_params(check) -> dict:
    return json.loads(check.check_params.json_params)


def _optional_check_params(check) -> dict:
    if check.check_params is None or check.check_params.json_params is None:
        return {}
    return _check_params(check)


def _step_params(step) -> dict:
    return json.loads(step.step_params.json_params)


def _all_checks(config):
    for playbook in config.playbooks:
        yield from playbook.prechecks or []
        yield from playbook.postchecks or []
        yield from playbook.snapshot_checks or []


def _all_steps(config):
    for playbook in config.playbooks:
        for stage in playbook.stages:
            yield from stage.steps or []


def _assert_restart_contract(test, playbook) -> None:
    bgp_checks = [
        check
        for check in playbook.postchecks or []
        if (check.check_id or "").startswith("fpf_bgp_convergence_lane")
    ]
    test.assertTrue(bgp_checks)
    for check in bgp_checks:
        params = _check_params(check)
        test.assertEqual(params["mode"], "restart")
        test.assertEqual(params["reconverge_sla_sec"], 60.0)

    descriptions = [
        step.description for stage in playbook.stages for step in stage.steps
    ]
    record_index = descriptions.index(
        "Record BGP restart time for RIB reconvergence SLA"
    )
    test.assertIn("Restart BGP", descriptions[record_index + 1])


def _assert_fsdb_restart_contract(test, playbook, has_drain_window: bool) -> None:
    fsdb_checks = [
        check
        for check in playbook.postchecks or []
        if (check.check_id or "").startswith("fpf_fsdb_convergence_lane")
    ]
    test.assertTrue(fsdb_checks)
    for check in fsdb_checks:
        params = _check_params(check)
        test.assertEqual(params["mode"], "restart")
        test.assertEqual(params["reconverge_sla_sec"], 20.0)
        test.assertTrue(params["use_restart_time"])

    steps = [step for stage in playbook.stages for step in stage.steps]
    descriptions = [step.description for step in steps]
    restart_index = descriptions.index(
        "Record FSDB restart time for ribMap reconvergence SLA"
    )
    test.assertEqual(
        _step_params(steps[restart_index])["custom_step_name"],
        "record_fpf_restart_time",
    )
    test.assertIn("Restart FSDB", descriptions[restart_index + 1])

    disruption_descriptions = [
        description
        for description in descriptions
        if description.startswith("Record FSDB-stop disruption time")
    ]
    if has_drain_window:
        test.assertEqual(len(disruption_descriptions), 1)
        disruption_index = descriptions.index(disruption_descriptions[0])
        test.assertEqual(
            _step_params(steps[disruption_index])["custom_step_name"],
            "record_fpf_disruption_time",
        )
        test.assertIn("Stop FSDB", descriptions[disruption_index + 1])
        test.assertLess(disruption_index, restart_index)
    else:
        test.assertEqual(disruption_descriptions, [])


def _assert_ods_policy(test, playbook, transient_discard_allowed: bool) -> None:
    by_id = {
        check.check_id: check for check in playbook.postchecks or [] if check.check_id
    }
    for check_id in ("ods_in_dst_null_discard", "ods_in_discard"):
        params = _check_params(by_id[check_id])
        test.assertEqual(params["baseline_excess_max"], 10000)
        test.assertIs(
            params["transient_excess_informational"], transient_discard_allowed
        )
    for check_id in ("ods_in_congestion", "ods_out_congestion"):
        params = _check_params(by_id[check_id])
        test.assertNotIn("baseline_excess_max", params)
        test.assertFalse(params.get("informational", False))


class TestFpfGracefulRestartConfigs(unittest.TestCase):
    def test_hrt_precheck_topology_preserves_explicit_device_order(self) -> None:
        self.assertEqual(
            _resolve_fpf_hrt_precheck_topology(
                hrt_device_ids=[3, 1],
                rf_vf_groups=None,
                injected_lanes=list(range(8)),
                expected_session_count=8,
            ),
            ([3, 1], 4),
        )

    def test_hrt_precheck_topology_rejects_ambiguous_models(self) -> None:
        cases: tuple[tuple[list[int], list[int], int], ...] = (
            ([0, 1, 2, 3, 4], [0, 1, 2, 3], 32),
            ([0, 0], [0], 2),
            ([0, 1], list(range(9)), 8),
        )
        for device_ids, injected_lanes, expected_session_count in cases:
            with self.subTest(
                device_ids=device_ids,
                injected_lanes=injected_lanes,
                expected_session_count=expected_session_count,
            ):
                with self.assertRaises(ValueError):
                    _resolve_fpf_hrt_precheck_topology(
                        hrt_device_ids=device_ids,
                        rf_vf_groups=None,
                        injected_lanes=injected_lanes,
                        expected_session_count=expected_session_count,
                    )

    def test_hrt_precheck_topology_accepts_global_lanes(self) -> None:
        resolved, planes_per_device = _resolve_fpf_hrt_precheck_topology(
            hrt_device_ids=list(range(8)),
            rf_vf_groups=None,
            injected_lanes=list(range(8)),
            expected_session_count=32,
        )

        self.assertEqual(resolved, list(range(8)))
        self.assertEqual(planes_per_device, 4)

    def test_empty_device_ids_preserve_deduplicated_group_fallback(self) -> None:
        self.assertEqual(
            _resolve_fpf_hrt_precheck_topology(
                hrt_device_ids=[],
                rf_vf_groups=[
                    {"device_ids": [2, 0, 2]},
                    {},
                ],
                injected_lanes=list(range(8)),
                expected_session_count=8,
            ),
            ([0, 2], 4),
        )

    def test_empty_group_device_ids_contribute_nothing(self) -> None:
        self.assertEqual(
            _resolve_fpf_hrt_precheck_topology(
                hrt_device_ids=[],
                rf_vf_groups=[
                    {"device_ids": []},
                    {"device_ids": [3, 1, 3]},
                ],
                injected_lanes=list(range(8)),
                expected_session_count=8,
            ),
            ([1, 3], 4),
        )

    def test_hrt_precheck_legacy_groups_do_not_duplicate_device_zero(self) -> None:
        self.assertEqual(
            _resolve_fpf_hrt_precheck_topology(
                hrt_device_ids=None,
                rf_vf_groups=[{"suffix": "vf1"}, {"suffix": "vf2"}],
                injected_lanes=list(range(8)),
                expected_session_count=32,
            ),
            ([0], None),
        )

    def test_partial_plane_remote_failure_groups_use_explicit_devices(self):
        groups = fpf_rf_vf_groups(
            active_lanes=[0, 1, 2, 3],
            device_ids_by_vf=([0, 2, 4, 6], [1, 3, 5, 7]),
        )
        by_suffix = {group["suffix"]: group for group in groups}
        self.assertEqual(by_suffix["vf1"]["device_ids"], [0, 2, 4, 6])
        self.assertEqual(by_suffix["vf2"]["device_ids"], [1, 3, 5, 7])
        self.assertNotIn("stable_expected_per_lane", by_suffix["vf2"])

    def test_standalone_configs_use_restart_aware_bgp_rib_policy(self):
        configs = [
            fpf_tc05_bgp_gr_within_window.create_fpf_tc05_test_config(),
            fpf_tc06_bgp_gr_beyond_window.create_fpf_tc06_test_config(),
        ]
        for config in configs:
            with self.subTest(config=config.name):
                _assert_restart_contract(self, config.playbooks[0])

    def test_shared_suite_bgp_gr_playbooks_use_restart_aware_policy(self):
        config = (
            fpf_shared_injection_suite.create_fpf_shared_injection_suite_test_config()
        )
        for name in (
            "fpf_tc05_bgp_gr_within_window",
            "fpf_tc06_bgp_gr_beyond_window",
        ):
            with self.subTest(playbook=name):
                _assert_restart_contract(self, _playbook(config, name))

    def test_tc23_restarts_only_the_targeted_dut_bgp_rib(self):
        playbook = fpf_tc23_bgp_restart.create_fpf_tc23_test_config().playbooks[0]
        bgp_checks = {
            check.check_id: _check_params(check)
            for check in playbook.postchecks or []
            if (check.check_id or "").startswith("fpf_bgp_")
        }

        restarted = bgp_checks["fpf_bgp_restart_reconverge_lane0"]
        observer = bgp_checks["fpf_bgp_stable_lane1"]
        self.assertEqual(restarted["lane_map"], {"0": fpf_tc23_bgp_restart.DUT_GTSW})
        self.assertEqual(restarted["mode"], "restart")
        self.assertEqual(restarted["reconverge_sla_sec"], 60.0)
        self.assertEqual(
            observer["lane_map"],
            {"1": fpf_tc23_bgp_restart.OBSERVER_GTSWS[1]},
        )
        self.assertNotIn("mode", observer)

    def test_standalone_fsdb_gr_configs_use_separate_restart_time(self):
        configs = [
            (fpf_tc07_fsdb_gr_within_window.create_fpf_tc07_test_config(), False),
            (fpf_tc08_fsdb_gr_beyond_window.create_fpf_tc08_test_config(), True),
        ]
        for config, has_drain_window in configs:
            with self.subTest(config=config.name):
                _assert_fsdb_restart_contract(
                    self, config.playbooks[0], has_drain_window
                )

    def test_shared_suite_fsdb_gr_playbooks_use_separate_restart_time(self):
        config = (
            fpf_shared_injection_suite.create_fpf_shared_injection_suite_test_config()
        )
        for name, has_drain_window in (
            ("fpf_tc07_fsdb_gr_within_window", False),
            ("fpf_tc08_fsdb_gr_beyond_window", True),
        ):
            with self.subTest(playbook=name):
                _assert_fsdb_restart_contract(
                    self, _playbook(config, name), has_drain_window
                )

    def test_gr_discard_policy_is_hard_within_and_transient_only_beyond(self):
        standalone = (
            (fpf_tc05_bgp_gr_within_window.create_fpf_tc05_test_config(), False),
            (fpf_tc06_bgp_gr_beyond_window.create_fpf_tc06_test_config(), True),
            (fpf_tc07_fsdb_gr_within_window.create_fpf_tc07_test_config(), False),
            (fpf_tc08_fsdb_gr_beyond_window.create_fpf_tc08_test_config(), True),
        )
        for config, transient_allowed in standalone:
            with self.subTest(config=config.name):
                _assert_ods_policy(self, config.playbooks[0], transient_allowed)

        shared = (
            fpf_shared_injection_suite.create_fpf_shared_injection_suite_test_config()
        )
        for name, transient_allowed in (
            ("fpf_tc05_bgp_gr_within_window", False),
            ("fpf_tc06_bgp_gr_beyond_window", True),
            ("fpf_tc07_fsdb_gr_within_window", False),
            ("fpf_tc08_fsdb_gr_beyond_window", True),
            ("fpf_tc41_longevity_pristine", False),
        ):
            with self.subTest(playbook=name):
                _assert_ods_policy(self, _playbook(shared, name), transient_allowed)

    def test_shared_suite_uses_tc04_as_the_single_wedge_warm_restart(self):
        config = (
            fpf_shared_injection_suite.create_fpf_shared_injection_suite_test_config()
        )
        names = [playbook.name for playbook in config.playbooks]

        self.assertEqual(names.count("fpf_tc04_wedge_agent_warmboot"), 1)
        self.assertNotIn("fpf_tc25_wedge_agent_restart", names)
        self.assertEqual(
            fpf_tc25_wedge_agent_restart.create_fpf_tc25_test_config()
            .playbooks[0]
            .name,
            "fpf_tc25_wedge_agent_restart",
        )

    def test_shared_suite_retains_default_ib_device(self):
        with (
            patch.dict(os.environ),
            patch.object(
                fpf_shared_injection_suite,
                "skip_ssh_dependencies",
                return_value=False,
            ),
            patch.object(
                fpf_shared_injection_suite,
                "skip_ib_traffic",
                return_value=False,
            ),
        ):
            os.environ.pop("TAAC_FPF_IB_DEVICE", None)
            config = fpf_shared_injection_suite.create_fpf_shared_injection_suite_test_config()

        start = next(
            task
            for task in config.setup_tasks
            if task.task_name == "fpf_start_ib_traffic"
        )
        params = json.loads(start.params.json_params)
        self.assertEqual(params["device"], "mlx5_34")
        self.assertEqual(params["gid_iface"], "bveth0")

    def test_shared_suite_honors_twshared_ib_device_override(self):
        hosts = ["twshared1352.03.mwg2", "twshared1388.03.mwg2"]
        try:
            with patch.dict(
                os.environ,
                {
                    "FPF_GPU_HOSTS": ",".join(hosts),
                    "FPF_HRT_DEVICE_IDS": "0,1,2,3,4,5,6,7",
                    "FPF_HRT_LANES": "0,1,2,3",
                    "FPF_HRT_VF1_DEVICE_IDS": "0,2,4,6",
                    "FPF_HRT_VF2_DEVICE_IDS": "1,3,5,7",
                    "TAAC_FPF_IB_DEVICE": "mlx5_bveth0",
                    "TAAC_FPF_LINK_DRAIN_INTERFACE": "eth1/41/5",
                },
            ):
                os.environ.pop("TAAC_FPF_SKIP_SSH_DEPS", None)
                os.environ.pop("TAAC_FPF_SKIP_IB_TRAFFIC", None)
                importlib.reload(fpf_hardening_common)
                importlib.reload(fpf_shared_injection_suite)
                config = fpf_shared_injection_suite.create_fpf_shared_injection_suite_test_config()

                start = next(
                    task
                    for task in config.setup_tasks
                    if task.task_name == "fpf_start_ib_traffic"
                )
                params = json.loads(start.params.json_params)
                self.assertEqual(params["server"], hosts[0])
                self.assertEqual(params["clients"], [hosts[1]])
                self.assertEqual(params["device"], "mlx5_bveth0")
                self.assertEqual(params["gid_iface"], "bveth0")

                ensure_steps = [
                    _step_params(step)
                    for step in _all_steps(config)
                    if step.step_params is not None
                    and _step_params(step).get("custom_step_name")
                    == "fpf_ensure_traffic"
                ]
                self.assertTrue(ensure_steps)
                shared_fields = {
                    "server",
                    "clients",
                    "device",
                    "gid_iface",
                    "gid_prefix",
                    "port",
                    "msg_size",
                    "qp",
                    "tclass",
                    "iters",
                    "min_egress_gbps",
                    "settle_sec",
                    "ods_window_sec",
                }
                expected_traffic = {key: params[key] for key in shared_fields}
                for ensure_params in ensure_steps:
                    self.assertEqual(
                        {key: ensure_params[key] for key in shared_fields},
                        expected_traffic,
                    )

                tc52_disrupt = _playbook(config, "fpf_tc52_hrt_restart_disrupt")
                disrupt_steps = [
                    _step_params(step)
                    for stage in tc52_disrupt.stages
                    for step in stage.steps
                ]
                self.assertEqual(
                    disrupt_steps[0]["custom_step_name"], "fpf_ensure_traffic"
                )
                self.assertEqual(
                    sum(
                        step.get("custom_step_name") == "fpf_ensure_traffic"
                        for step in disrupt_steps
                    ),
                    1,
                )
                self.assertGreater(
                    next(
                        index
                        for index, step in enumerate(disrupt_steps)
                        if step.get("custom_step_name") == "fpf_restart_hrt"
                    ),
                    0,
                )
                tc52_longevity = _playbook(config, "fpf_tc52_hrt_restart_longevity")
                longevity_steps = [
                    _step_params(step)
                    for stage in tc52_longevity.stages
                    for step in stage.steps
                ]
                self.assertEqual(
                    longevity_steps[0]["custom_step_name"], "fpf_ensure_traffic"
                )

                stop = next(
                    task
                    for task in config.teardown_tasks
                    if task.task_name == "fpf_stop_ib_traffic"
                )
                stop_params = json.loads(stop.params.json_params)
                self.assertEqual(stop_params["server"], hosts[0])
                self.assertEqual(stop_params["clients"], [hosts[1]])

                baseline = _playbook(config, "fpf_tc41_longevity_pristine")
                self.assertIn(
                    "fpf_host_spray",
                    {check.check_id for check in baseline.postchecks or []},
                )
        finally:
            importlib.reload(fpf_hardening_common)
            importlib.reload(fpf_shared_injection_suite)

    def test_standalone_tc25_honors_twshared_hosts_topology_and_no_ib_mode(self):
        hosts = ["twshared1352.03.mwg2", "twshared1388.03.mwg2"]
        device_ids = list(range(8))
        local_planes = [0, 1, 2, 3]
        try:
            with patch.dict(
                os.environ,
                {
                    "FPF_GPU_HOSTS": ",".join(hosts),
                    "FPF_HRT_DEVICE_IDS": "0,1,2,3,4,5,6,7",
                    "FPF_HRT_LANES": "0,1,2,3",
                    "FPF_HRT_VF1_DEVICE_IDS": "0,2,4,6",
                    "FPF_HRT_VF2_DEVICE_IDS": "1,3,5,7",
                    "TAAC_FPF_SKIP_IB_TRAFFIC": "1",
                },
            ):
                os.environ.pop("TAAC_FPF_SKIP_SSH_DEPS", None)
                importlib.reload(fpf_hardening_common)
                importlib.reload(fpf_tc25_wedge_agent_restart)
                config = fpf_tc25_wedge_agent_restart.create_fpf_tc25_test_config()

                self.assertEqual(fpf_tc25_wedge_agent_restart.GPU_HOSTS, hosts)
                self.assertEqual(fpf_tc25_wedge_agent_restart.HRT_MEMORY_HOSTS, hosts)

                task_names = {
                    task.task_name
                    for task in [*config.setup_tasks, *config.teardown_tasks]
                }
                self.assertNotIn("fpf_start_ib_traffic", task_names)
                self.assertNotIn("fpf_stop_ib_traffic", task_names)

                collector = next(
                    task
                    for task in config.setup_tasks
                    if task.task_name == "fpf_start_collectors"
                )
                collector_params = json.loads(collector.params.json_params)
                self.assertEqual(collector_params["hosts"], hosts)
                self.assertEqual(collector_params["prod_prefix_host"], hosts[0])
                self.assertEqual(collector_params["hrt_device_ids"], device_ids)
                self.assertEqual(collector_params["hrt_plane_ids"], local_planes)
                self.assertEqual(
                    collector_params["rf_vf_groups"][0]["device_ids"],
                    [0, 2, 4, 6],
                )
                self.assertEqual(
                    collector_params["rf_vf_groups"][1]["device_ids"],
                    [1, 3, 5, 7],
                )
                for group in collector_params["rf_vf_groups"]:
                    self.assertEqual(group["lanes"], local_planes)

                by_id = {
                    check.check_id: _optional_check_params(check)
                    for check in _all_checks(config)
                    if check.check_id
                }
                self.assertEqual(by_id["fpf_hrt_bulk_stable"]["device_ids"], device_ids)
                self.assertEqual(by_id["fpf_hrt_bulk_stable"]["lanes"], local_planes)
                self.assertEqual(
                    by_id["fpf_hrt_remote_failure_stable_vf1"]["device_ids"],
                    [0, 2, 4, 6],
                )
                self.assertEqual(
                    by_id["fpf_hrt_remote_failure_stable_vf2"]["device_ids"],
                    [1, 3, 5, 7],
                )
                self.assertEqual(
                    by_id["fpf_hrt_plane_status_all_up"]["device_ids"], device_ids
                )
                self.assertEqual(
                    by_id["fpf_hrt_plane_status_all_up"]["expected_planes"],
                    local_planes,
                )

                check_params_with_hosts = [
                    _optional_check_params(check)
                    for check in _all_checks(config)
                    if "hosts" in _optional_check_params(check)
                    and (check.check_id or "").startswith("fpf_hrt")
                ]
                self.assertTrue(check_params_with_hosts)
                for params in check_params_with_hosts:
                    self.assertEqual(params["hosts"], hosts)

                check_ids = {
                    check.check_id for check in _all_checks(config) if check.check_id
                }
                self.assertNotIn("fpf_host_spray", check_ids)
                custom_step_names = {
                    _step_params(step).get("custom_step_name")
                    for step in _all_steps(config)
                    if step.step_params is not None
                }
                self.assertNotIn("fpf_ensure_traffic", custom_step_names)
        finally:
            # Restore module-level environment-derived constants for subsequent
            # tests after patch.dict has restored the process environment.
            importlib.reload(fpf_hardening_common)
            importlib.reload(fpf_tc25_wedge_agent_restart)

    def test_shared_suite_no_ib_mode_omits_tasks_checks_and_readiness(self):
        try:
            with patch.dict(os.environ, {"TAAC_FPF_SKIP_IB_TRAFFIC": "1"}):
                os.environ.pop("TAAC_FPF_SKIP_SSH_DEPS", None)
                importlib.reload(fpf_hardening_common)
                importlib.reload(fpf_shared_injection_suite)
                config = fpf_shared_injection_suite.create_fpf_shared_injection_suite_test_config()

                task_names = {
                    task.task_name
                    for task in [*config.setup_tasks, *config.teardown_tasks]
                }
                self.assertNotIn("fpf_start_ib_traffic", task_names)
                self.assertNotIn("fpf_stop_ib_traffic", task_names)
                check_ids = {
                    check.check_id for check in _all_checks(config) if check.check_id
                }
                self.assertNotIn("fpf_host_spray", check_ids)
                ensure_steps = [
                    step
                    for step in _all_steps(config)
                    if step.step_params is not None
                    and _step_params(step).get("custom_step_name")
                    == "fpf_ensure_traffic"
                ]
                self.assertEqual(ensure_steps, [])
        finally:
            importlib.reload(fpf_hardening_common)
            importlib.reload(fpf_shared_injection_suite)

    def test_standalone_tc25_retains_legacy_single_device_defaults(self):
        topology_vars = (
            "FPF_HRT_DEVICE_IDS",
            "FPF_HRT_LANES",
            "FPF_HRT_VF1_DEVICE_IDS",
            "FPF_HRT_VF2_DEVICE_IDS",
        )
        try:
            with patch.dict(os.environ):
                for env_name in topology_vars:
                    os.environ.pop(env_name, None)
                importlib.reload(fpf_hardening_common)
                importlib.reload(fpf_tc25_wedge_agent_restart)
                config = fpf_tc25_wedge_agent_restart.create_fpf_tc25_test_config()

                self.assertEqual(fpf_tc25_wedge_agent_restart.HRT_DEVICE_IDS, [0])
                self.assertEqual(
                    fpf_tc25_wedge_agent_restart.INJECTED_LANES, list(range(8))
                )
                self.assertEqual(
                    fpf_tc25_wedge_agent_restart.HRT_VF_DEVICE_IDS, ([0], [0])
                )

                collector = next(
                    task
                    for task in config.setup_tasks
                    if task.task_name == "fpf_start_collectors"
                )
                collector_params = json.loads(collector.params.json_params)
                # Factory serialization omits legacy defaults; the task resolves
                # absent values to dev0 and planes 0-7.
                self.assertNotIn("hrt_device_ids", collector_params)
                self.assertNotIn("hrt_plane_ids", collector_params)
                self.assertNotIn("device_ids", collector_params["rf_vf_groups"][0])
                self.assertNotIn("device_ids", collector_params["rf_vf_groups"][1])

                by_id = {
                    check.check_id: _optional_check_params(check)
                    for check in _all_checks(config)
                    if check.check_id
                }
                self.assertEqual(
                    by_id["fpf_hrt_bulk_stable"].get("device_ids", [0]), [0]
                )
                self.assertEqual(
                    by_id["fpf_hrt_plane_status_all_up"].get("device_ids", [0]),
                    [0],
                )
                self.assertEqual(
                    by_id["fpf_hrt_plane_status_all_up"].get(
                        "expected_planes", list(range(8))
                    ),
                    list(range(8)),
                )
        finally:
            importlib.reload(fpf_hardening_common)
            importlib.reload(fpf_tc25_wedge_agent_restart)

    def test_standalone_tc25_keeps_legacy_ib_device_by_default(self):
        for configured_device in (None, ""):
            with (
                self.subTest(configured_device=configured_device),
                patch.dict(os.environ),
                patch.object(
                    fpf_tc25_wedge_agent_restart,
                    "skip_ssh_dependencies",
                    return_value=False,
                ),
                patch.object(
                    fpf_tc25_wedge_agent_restart,
                    "skip_ib_traffic",
                    return_value=False,
                ),
            ):
                if configured_device is None:
                    os.environ.pop("TAAC_FPF_IB_DEVICE", None)
                else:
                    os.environ["TAAC_FPF_IB_DEVICE"] = configured_device
                config = fpf_tc25_wedge_agent_restart.create_fpf_tc25_test_config()

            start = next(
                task
                for task in config.setup_tasks
                if task.task_name == "fpf_start_ib_traffic"
            )
            params = json.loads(start.params.json_params)
            self.assertEqual(params["device"], "mlx5_34")
            self.assertEqual(params["gid_iface"], "bveth0")

    def test_standalone_tc25_honors_twshared_ib_device_override(self):
        hosts = ["twshared1352.03.mwg2", "twshared1388.03.mwg2"]
        try:
            with patch.dict(
                os.environ,
                {
                    "FPF_GPU_HOSTS": ",".join(hosts),
                    "FPF_HRT_DEVICE_IDS": "0,1,2,3,4,5,6,7",
                    "FPF_HRT_LANES": "0,1,2,3",
                    "FPF_HRT_VF1_DEVICE_IDS": "0,2,4,6",
                    "FPF_HRT_VF2_DEVICE_IDS": "1,3,5,7",
                    "FPF_VF_GROUP_PODS": "16",
                    "FPF_VF_PREFIXES_PER_POD": "252",
                    "TAAC_FPF_IB_DEVICE": "mlx5_bveth0",
                },
            ):
                os.environ.pop("TAAC_FPF_SKIP_SSH_DEPS", None)
                os.environ.pop("TAAC_FPF_SKIP_IB_TRAFFIC", None)
                importlib.reload(fpf_hardening_common)
                importlib.reload(fpf_tc25_wedge_agent_restart)
                config = fpf_tc25_wedge_agent_restart.create_fpf_tc25_test_config()

                self.assertEqual(fpf_tc25_wedge_agent_restart.PREFIX_COUNT, 4032)
                self.assertEqual(
                    fpf_tc25_wedge_agent_restart.HRT_DEVICE_IDS,
                    list(range(8)),
                )
                self.assertEqual(
                    fpf_tc25_wedge_agent_restart.INJECTED_LANES,
                    [0, 1, 2, 3],
                )

                start = next(
                    task
                    for task in config.setup_tasks
                    if task.task_name == "fpf_start_ib_traffic"
                )
                params = json.loads(start.params.json_params)
                self.assertEqual(params["server"], hosts[0])
                self.assertEqual(params["clients"], [hosts[1]])
                self.assertEqual(params["device"], "mlx5_bveth0")
                self.assertEqual(params["gid_iface"], "bveth0")

                ensure = next(
                    _step_params(step)
                    for step in _all_steps(config)
                    if step.step_params is not None
                    and _step_params(step).get("custom_step_name")
                    == "fpf_ensure_traffic"
                )
                for key in (
                    "server",
                    "clients",
                    "device",
                    "gid_iface",
                    "gid_prefix",
                    "port",
                    "msg_size",
                    "qp",
                    "tclass",
                    "iters",
                    "min_egress_gbps",
                    "settle_sec",
                    "ods_window_sec",
                ):
                    self.assertEqual(ensure[key], params[key])

                stop = next(
                    task
                    for task in config.teardown_tasks
                    if task.task_name == "fpf_stop_ib_traffic"
                )
                stop_params = json.loads(stop.params.json_params)
                self.assertEqual(stop_params["server"], hosts[0])
                self.assertEqual(stop_params["clients"], [hosts[1]])

                check_ids = {
                    check.check_id for check in _all_checks(config) if check.check_id
                }
                self.assertIn("fpf_host_spray", check_ids)
                custom_step_names = {
                    _step_params(step).get("custom_step_name")
                    for step in _all_steps(config)
                    if step.step_params is not None
                }
                self.assertIn("fpf_ensure_traffic", custom_step_names)
        finally:
            importlib.reload(fpf_hardening_common)
            importlib.reload(fpf_tc25_wedge_agent_restart)

    def test_shared_suite_wires_explicit_twshared_device_identity(self):
        device_ids = list(range(8))
        groups = fpf_rf_vf_groups(
            active_lanes=[0, 1, 2, 3],
            device_ids_by_vf=([0, 2, 4, 6], [1, 3, 5, 7]),
        )
        with (
            patch.object(fpf_shared_injection_suite, "INJECTED_LANES", [0, 1, 2, 3]),
            patch.object(fpf_shared_injection_suite, "HRT_DEVICE_IDS", device_ids),
            patch.object(
                fpf_shared_injection_suite,
                "HRT_VF_DEVICE_IDS",
                ([0, 2, 4, 6], [1, 3, 5, 7]),
            ),
            patch.object(
                fpf_shared_injection_suite,
                "FSDB_GLOBAL_LANE0_TUPLES",
                {
                    host: {str(device_id): [0] for device_id in [0, 2, 4, 6]}
                    for host in fpf_shared_injection_suite.GPU_HOSTS
                },
            ),
            patch.object(fpf_shared_injection_suite, "RF_VF_GROUPS", groups),
        ):
            config = fpf_shared_injection_suite.create_fpf_shared_injection_suite_test_config()

        collector_task = next(
            task
            for task in config.setup_tasks
            if task.task_name == "fpf_start_collectors"
        )
        task_params = json.loads(collector_task.params.json_params)
        self.assertEqual(task_params["hrt_device_ids"], device_ids)
        self.assertEqual(task_params["hrt_plane_ids"], [0, 1, 2, 3])
        self.assertEqual(task_params["rf_vf_groups"][0]["device_ids"], [0, 2, 4, 6])
        self.assertEqual(task_params["rf_vf_groups"][1]["device_ids"], [1, 3, 5, 7])

        baseline = _playbook(config, "fpf_tc41_longevity_pristine")
        bulk_checks = [
            check
            for check in baseline.postchecks or []
            if (check.check_id or "").startswith("fpf_hrt_convergence_lane")
        ]
        self.assertTrue(bulk_checks)
        for check in bulk_checks:
            self.assertEqual(_check_params(check)["device_ids"], device_ids)
        fsdb_precheck = next(
            check
            for check in baseline.prechecks or []
            if check.check_id == "fpf_hrt_precheck"
        )
        self.assertEqual(_check_params(fsdb_precheck)["device_ids"], device_ids)
        self.assertEqual(_check_params(fsdb_precheck)["planes_per_device"], 4)

        rf_checks = {
            check.check_id: _check_params(check)
            for check in baseline.postchecks or []
            if (check.check_id or "").startswith("fpf_remote_failure_stable_")
        }
        self.assertEqual(
            rf_checks["fpf_remote_failure_stable_vf1"]["device_ids"], [0, 2, 4, 6]
        )
        self.assertEqual(
            rf_checks["fpf_remote_failure_stable_vf2"]["device_ids"], [1, 3, 5, 7]
        )
        self.assertEqual(
            rf_checks["fpf_remote_failure_stable_vf2"]["expected_per_lane"],
            {},
        )

        link_disrupt = _playbook(config, "fpf_tc15_interface_disable_disrupt")
        by_id = {
            check.check_id: _check_params(check)
            for check in link_disrupt.postchecks or []
            if check.check_id
        }
        expected_impacted = {fpf_shared_injection_suite.GPU_HOSTS[0]: {"0": [0]}}
        self.assertEqual(
            by_id["fpf_hrt_bulk_disrupt"]["impacted_tuple_lanes_by_host_device"],
            expected_impacted,
        )
        self.assertEqual(
            by_id["fpf_remote_failure_impacted_vf1"]["tuple_lanes_by_host_device"],
            expected_impacted,
        )
        self.assertEqual(
            by_id["fpf_remote_failure_unimpacted_stable_vf1"][
                "excluded_tuple_lanes_by_host_device"
            ],
            expected_impacted,
        )
        self.assertEqual(
            by_id["fpf_hrt_fsdb_session_disrupt"]["impacted_tuples_by_host_device"],
            expected_impacted,
        )

        for drain_name in (
            "fpf_tc17_link_drain_disrupt",
            "fpf_tc19_device_drain_disrupt",
        ):
            drain_precheck = next(
                check
                for check in _playbook(config, drain_name).prechecks or []
                if check.check_id == "fpf_hrt_fsdb_session_precheck"
            )
            self.assertEqual(_check_params(drain_precheck)["device_ids"], device_ids)
            self.assertEqual(_check_params(drain_precheck)["planes_per_device"], 4)

        drain = _playbook(config, "fpf_tc17_link_drain_disrupt")
        drain_by_id = {
            check.check_id: _check_params(check)
            for check in drain.postchecks or []
            if check.check_id
        }
        self.assertEqual(
            drain_by_id["fpf_hrt_plane_status_drain"]["device_ids"], device_ids
        )
        self.assertEqual(
            drain_by_id["fpf_hrt_plane_status_drain"]["impacted_tuples_by_host_device"],
            expected_impacted,
        )

        fsdb_kill = _playbook(config, "fpf_tc28_fsdb_kill_disrupt")
        session_stat = next(
            check
            for check in fsdb_kill.postchecks or []
            if (check.check_id or "").endswith("_session_stat")
        )
        expected_fsdb_tuples = {
            host: {str(device_id): [0] for device_id in [0, 2, 4, 6]}
            for host in fpf_shared_injection_suite.GPU_HOSTS
        }
        self.assertEqual(
            _check_params(session_stat)["impacted_tuples_by_host_device"],
            expected_fsdb_tuples,
        )

        for playbook_name in (
            "fpf_tc04_wedge_agent_warmboot",
            "fpf_tc23_bgp_restart",
        ):
            restart_playbook = _playbook(config, playbook_name)
            session_check = next(
                check
                for check in restart_playbook.postchecks or []
                if check.check_id == "fpf_hrt_fsdb_session_stable"
            )
            session_params = _check_params(session_check)
            self.assertEqual(session_params["device_ids"], device_ids)
            self.assertEqual(session_params["planes_per_device"], 4)

    def test_tc15_and_tc16_use_validated_twshared_interface(self):
        hosts = ["twshared1352.03.mwg2", "twshared1375.03.mwg2"]
        with (
            patch.object(fpf_shared_injection_suite, "GPU_HOSTS", hosts),
            patch.dict(
                os.environ,
                {"TAAC_FPF_LINK_DRAIN_INTERFACE": "eth1/41/5"},
            ),
        ):
            circuits = fpf_shared_injection_suite._link_drain_circuits()
            tc15 = fpf_shared_injection_suite._tc15(
                circuits=circuits,
                spray=hosts,
                skip_ssh=False,
            )
            tc16 = fpf_shared_injection_suite._tc16(
                circuits=circuits,
                spray=None,
                skip_ssh=True,
            )
            config = fpf_shared_injection_suite.create_fpf_shared_injection_suite_test_config()

        self.assertEqual(circuits[0].a_end_device, "gtsw001.l1002.c087.mwg2")
        self.assertEqual(circuits[0].a_end_interface, "eth1/41/5")
        self.assertEqual(circuits[0].z_end_device, hosts[0])

        def admin_actions(playbook):
            return [
                _step_params(step)
                for stage in playbook.stages
                for step in stage.steps
                if step.step_params is not None
                and _step_params(step).get("custom_step_name")
                == "fpf_set_interface_admin"
            ]

        disable = admin_actions(tc15[0])
        restore = admin_actions(tc15[1])
        compatibility_enable = admin_actions(tc16[0])
        self.assertEqual(
            [(action["interfaces"], action["is_enable"]) for action in disable],
            [(["eth1/41/5"], False)],
        )
        self.assertEqual(
            [(action["interfaces"], action["is_enable"]) for action in restore],
            [(["eth1/41/5"], True)],
        )
        self.assertEqual(
            [
                (action["interfaces"], action["is_enable"])
                for action in compatibility_enable
            ],
            [(["eth1/41/5"], True)],
        )

        restore_steps = tc15[1].stages[0].steps
        self.assertEqual(len(restore_steps), 3)
        self.assertEqual(
            _step_params(restore_steps[0]),
            {
                "custom_step_name": "fpf_set_interface_admin",
                "interfaces": ["eth1/41/5"],
                "is_enable": True,
            },
        )
        self.assertEqual(_step_params(restore_steps[1])["duration"], 180)
        self.assertEqual(
            _step_params(restore_steps[2])["custom_step_name"],
            "fpf_ensure_traffic",
        )

        # The disrupted state must remain held through the first playbook's
        # postchecks. Recovery is initiated only by the restore playbook; its
        # cleanup and the TestConfig teardown remain idempotent safety guards.
        # The cleanup retry is best-effort and must not re-anchor recovery time.
        self.assertEqual(list(tc15[0].cleanup_steps or []), [])
        restore_cleanup = tc15[1].cleanup_steps or []
        self.assertEqual(len(restore_cleanup), 1)
        self.assertEqual(
            _step_params(restore_cleanup[0]),
            {
                "custom_step_name": "fpf_set_interface_admin",
                "interfaces": ["eth1/41/5"],
                "is_enable": True,
                "best_effort": True,
                "record_event_time": False,
            },
        )
        self.assertIn(
            "post-restore traffic readiness",
            restore_steps[2].description.lower(),
        )

        teardown_guard = config.teardown_tasks[0]
        self.assertEqual(
            teardown_guard.task_name,
            "fpf_ensure_interfaces_enabled",
        )
        self.assertEqual(
            json.loads(teardown_guard.params.json_params),
            {
                "targets": [
                    {
                        "device": "gtsw001.l1002.c087.mwg2",
                        "interfaces": ["eth1/41/5"],
                    }
                ]
            },
        )

        collector_task = next(
            task
            for task in config.setup_tasks
            if task.task_name == "fpf_start_collectors"
        )
        collector_params = json.loads(collector_task.params.json_params)
        expected_observations = {
            host: [fpf_shared_injection_suite.PROD_TARGET_PREFIX] for host in hosts
        }
        self.assertEqual(
            collector_params["prod_prefixes_by_host"], expected_observations
        )
        self.assertNotIn("prod_prefix_host", collector_params)
        self.assertNotIn("prod_prefixes", collector_params)

        # The dual-host collector is shared suite-wide, but only TC15 opts into
        # dual-host assertions. Unrelated playbooks preserve the legacy origin-
        # host scope instead of silently gaining a second verdict surface.
        baseline = _playbook(config, "fpf_tc41_longevity_pristine")
        baseline_prod_checks = [
            check
            for check in [*(baseline.prechecks or []), *(baseline.postchecks or [])]
            if check.check_id
            in {
                "fpf_prod_hrt_prefix_stability_precheck",
                "fpf_prod_hrt_prefix_stability",
            }
        ]
        self.assertEqual(len(baseline_prod_checks), 2)
        for check in baseline_prod_checks:
            self.assertEqual(
                _check_params(check)["prefixes_by_host"],
                {
                    fpf_shared_injection_suite.PROD_PREFIX_HOST: [
                        fpf_shared_injection_suite.PROD_TARGET_PREFIX
                    ]
                },
            )

        expected_conditional_route_impacts = {host: [0] for host in hosts}
        transition = next(
            check
            for check in tc15[0].postchecks or []
            if check.check_id == "fpf_prod_hrt_prefix_transition"
        )
        recovery = next(
            check
            for check in tc15[1].postchecks or []
            if check.check_id == "fpf_prod_hrt_prefix_recovery"
        )
        self.assertEqual(
            _check_params(transition)["impacted_planes_by_host"],
            expected_conditional_route_impacts,
        )
        self.assertEqual(
            _check_params(transition)["prefixes_by_host"], expected_observations
        )
        self.assertEqual(
            _check_params(recovery)["impacted_planes_by_host"],
            expected_conditional_route_impacts,
        )
        self.assertEqual(
            _check_params(recovery)["prefixes_by_host"], expected_observations
        )
        self.assertEqual(
            _check_params(recovery)["affected_prefixes_by_host"],
            expected_observations,
        )
        self.assertEqual(
            fpf_shared_injection_suite._impacted_planes_by_host(circuits),
            {hosts[0]: [0]},
        )

        unrelated = (
            fpf_shared_injection_suite._conditional_route_impacted_planes_by_host(
                [
                    *circuits,
                    fpf_shared_injection_suite.Circuit(
                        a_end_device="gtsw002.l1002.c087.mwg2",
                        a_end_interface="eth1/41/5",
                        z_end_device=hosts[1],
                        z_end_gpu_id=0,
                    ),
                ],
                hosts,
            )
        )
        self.assertEqual(unrelated, expected_conditional_route_impacts)

    def test_standalone_tc15_observes_the_same_route_on_both_hosts(self):
        config = fpf_tc15_interface_disable.create_fpf_tc15_test_config()
        hosts = fpf_tc15_interface_disable.GPU_HOSTS
        target = fpf_tc15_interface_disable.PROD_TARGET_PREFIX

        collector_task = next(
            task
            for task in config.setup_tasks
            if task.task_name == "fpf_start_collectors"
        )
        collector_params = json.loads(collector_task.params.json_params)
        self.assertEqual(
            collector_params["prod_prefixes_by_host"],
            {host: [target] for host in hosts},
        )

        expected_impacts = {host: [0] for host in hosts}
        for playbook_name, check_id in (
            (
                "fpf_tc15_interface_disable_disrupt",
                "fpf_prod_hrt_prefix_transition",
            ),
            (
                "fpf_tc15_interface_disable_restore",
                "fpf_prod_hrt_prefix_recovery",
            ),
        ):
            check = next(
                candidate
                for candidate in _playbook(config, playbook_name).postchecks or []
                if candidate.check_id == check_id
            )
            self.assertEqual(
                _check_params(check)["impacted_planes_by_host"], expected_impacts
            )
            self.assertEqual(
                _check_params(check)["prefixes_by_host"],
                {host: [target] for host in hosts},
            )


if __name__ == "__main__":
    unittest.main()
