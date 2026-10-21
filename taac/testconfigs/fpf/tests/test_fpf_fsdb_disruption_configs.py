# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe

"""Structural unit tests for the FPF FSDB disruption test configs.

Covers the standalone tc29b config (one-way remote-prefix withdrawal while the
local FSDB is in graceful restart). The tc28/tc29/tc30/tc31 standalone configs
were removed: tc28 runs as the ``fpf_tc28_fsdb_kill`` playbooks of
``fpf_shared_injection_suite``, tc29 is covered by the suite's tc07 (FSDB stop
inside the GR window) and tc30/tc31 by the suite's tc08 (FSDB stop beyond the
GR window, restart and settle in one playbook).
"""

import json
import unittest

from taac.testconfigs.fpf import fpf_tc29b_fsdb_gr_remote_withdraw
from taac.test_as_a_config import types as taac_types


def _check_params(check) -> dict:
    return json.loads(check.check_params.json_params)


def _all_steps(playbook):
    steps = []
    for stage in playbook.stages or []:
        steps.extend(stage.steps or [])
    return steps


def _step_params(step) -> dict:
    if step.step_params is None:
        return {}
    return json.loads(step.step_params.json_params)


def _task_params(task) -> dict:
    if task.params is None:
        return {}
    return json.loads(task.params.json_params)


def _checks_by_id(playbook) -> dict:
    return {c.check_id: c for c in (playbook.postchecks or []) if c.check_id}


def _prechecks_by_id(playbook) -> dict:
    return {c.check_id: c for c in (playbook.prechecks or []) if c.check_id}


class TestFpfTc29bRemotePrefixWithdraw(unittest.TestCase):
    def setUp(self):
        self.module = fpf_tc29b_fsdb_gr_remote_withdraw
        self.cfg = self.module.TEST_CONFIG

    def test_two_phase_shape_without_ib_traffic(self):
        self.assertEqual(self.cfg.name, "fpf_tc29b_fsdb_gr_remote_withdraw")
        self.assertEqual(
            [playbook.name for playbook in self.cfg.playbooks],
            [
                "fpf_tc29b_fsdb_gr_remote_withdraw_disrupt",
                "fpf_tc29b_fsdb_gr_remote_withdraw_recovery",
            ],
        )
        task_names = [task.task_name for task in self.cfg.setup_tasks]
        self.assertNotIn("fpf_start_ib_traffic", task_names)
        self.assertNotIn("fpf_stop_ib_traffic", task_names)

    def test_exact_a_and_b_injection_and_named_collectors(self):
        injections = [
            task
            for task in self.cfg.setup_tasks
            if task.task_name == "fpf_inject_bgp_prefixes"
        ]
        groups = [
            group for task in injections for group in _task_params(task)["groups"]
        ]
        remote_b = next(g for g in groups if g["prefix_base"] == "4000:dd::/64")
        self.assertEqual(remote_b["devices"], [self.module.REMOTE_GTSW])
        self.assertEqual(remote_b["count"], 1000)
        self.assertEqual(remote_b["increment_step"], "0:0:1::")
        self.assertEqual(remote_b["community_list"], "gtsw")
        self.assertEqual(remote_b["batch_size"], 100)

        collector_task = next(
            task
            for task in self.cfg.setup_tasks
            if task.task_name == "fpf_start_collectors"
        )
        params = _task_params(collector_task)
        self.assertEqual(params["poll_interval_sec"], 2.0)
        groups = {g["name"]: g for g in params["additional_namespaces"]}
        self.assertEqual(groups["remote_b"]["subnet_prefix"], "4000:dd::/32")
        self.assertEqual(
            groups["remote_b"]["bgp_gtsws"],
            [self.module.REMOTE_GTSW, self.module.LOCAL_GTSW],
        )
        self.assertEqual(groups["remote_b"]["fsdb_gtsws"], [self.module.LOCAL_GTSW])
        self.assertEqual(groups["remote_b"]["fib_gtsws"], [self.module.LOCAL_GTSW])
        self.assertEqual(groups["local_a"]["fib_gtsws"], [self.module.LOCAL_GTSW])

    def test_collectors_pin_the_characterized_twshared_hosts(self):
        expected = ["twshared1352.03.mwg2", "twshared1388.03.mwg2"]
        stale = {"rtptest1555.mwg2", "rtptest1599.mwg2"}
        collector_task = next(
            task
            for task in self.cfg.setup_tasks
            if task.task_name == "fpf_start_collectors"
        )
        params = _task_params(collector_task)
        remote_b = next(
            group
            for group in params["additional_namespaces"]
            if group["name"] == "remote_b"
        )

        self.assertEqual(self.module.GPU_HOSTS, expected)
        self.assertEqual(params["hosts"], expected)
        self.assertEqual(params["fsdb_session_hosts"], expected)
        self.assertEqual(remote_b["hosts"], expected)
        self.assertTrue(stale.isdisjoint(params["hosts"]))

        lifecycle = _check_params(
            _checks_by_id(self.cfg.playbooks[0])["fpf_tc29b_remote_prefix_withdrawn"]
        )
        for key in (
            "a_hrt_positive_expected",
            "a_hrt_remote_failure_expected",
            "b_hrt_positive_expected",
            "b_hrt_remote_failure_expected",
        ):
            self.assertEqual(list(lifecycle[key]), expected)

    def test_scale_injection_is_252_batched_and_serially_bounded(self):
        injection_tasks = [
            task
            for task in self.cfg.setup_tasks
            if task.task_name == "fpf_inject_bgp_prefixes"
        ]
        self.assertEqual(
            len(injection_tasks),
            9,
            "eight A origins plus one B origin must be separate setup tasks",
        )
        all_groups = []
        for task in injection_tasks:
            params = _task_params(task)
            self.assertEqual(len(params["groups"]), 1)
            group = params["groups"][0]
            self.assertEqual(len(group["devices"]), 1)
            all_groups.append(group)

        a_groups = [g for g in all_groups if g["prefix_base"].startswith("5000:")]
        self.assertEqual(len(a_groups), 8)
        for group in a_groups:
            self.assertEqual(group["count"], 4032)
            self.assertEqual(group["batch_size"], 252)
            self.assertEqual(group["count"] // group["batch_size"], 16)

        self.assertEqual(_task_params(injection_tasks[-1])["settle_sec"], 120)
        self.assertTrue(
            all(_task_params(task)["settle_sec"] == 0 for task in injection_tasks[:-1])
        )

        present = _check_params(
            _prechecks_by_id(self.cfg.playbooks[0])["fpf_tc29b_remote_prefix_present"]
        )
        self.assertIn(
            ["fib_local_a", self.module.LOCAL_GTSW, 4032],
            present["scalar_expectations"],
        )
        for host_map in present["a_hrt_positive_expected"].values():
            for counts in host_map.values():
                self.assertEqual(counts, [4032, 4032, 4032, 4032])

        withdrawal_tasks = [
            task
            for task in self.cfg.teardown_tasks
            if task.task_name == "fpf_inject_bgp_prefixes"
        ]
        self.assertEqual(len(withdrawal_tasks), 9)
        for task in withdrawal_tasks:
            params = _task_params(task)
            self.assertTrue(params["withdraw"])
            self.assertEqual(len(params["groups"]), 1)
            self.assertEqual(len(params["groups"][0]["devices"]), 1)

    def test_disruption_sequence_and_absence_contract(self):
        disrupt = self.cfg.playbooks[0]
        custom = [
            _step_params(step)
            for step in _all_steps(disrupt)
            if step.name == taac_types.StepName.CUSTOM_STEP
        ]
        sequence = next(
            params
            for params in custom
            if params.get("custom_step_name") == "fpf_remote_prefix_gr_sequence"
        )
        self.assertEqual(sequence["local_gtsw"], self.module.LOCAL_GTSW)
        self.assertEqual(sequence["remote_gtsw"], self.module.REMOTE_GTSW)
        self.assertEqual(sequence["between_stops_sec"], 30)
        self.assertEqual(sequence["before_local_restart_sec"], 30)
        self.assertEqual(sequence["max_fsdb_outage_sec"], 120)

        lifecycle = _check_params(
            _checks_by_id(disrupt)["fpf_tc29b_remote_prefix_withdrawn"]
        )
        self.assertEqual(lifecycle["mode"], "withdrawn")
        self.assertEqual(lifecycle["deadline_sec"], 120)
        self.assertEqual(
            set(lifecycle["outage_tolerant_collectors"]),
            {
                f"fsdb_remote_b@{self.module.LOCAL_GTSW}",
                f"hrt_remote_b@{self.module.GPU_HOSTS[0]}",
                f"hrt@{self.module.GPU_HOSTS[0]}",
            },
        )
        self.assertEqual(
            lifecycle["scalar_expectations"],
            [
                ["bgp_remote_b", self.module.LOCAL_GTSW, 0],
                ["fib_remote_b", self.module.LOCAL_GTSW, 0],
                ["fsdb_remote_b", self.module.LOCAL_GTSW, 0],
                ["fib_local_a", self.module.LOCAL_GTSW, 4032],
            ],
        )
        remote_host = self.module.GPU_HOSTS[1]
        local_host = self.module.GPU_HOSTS[0]
        a_positive = lifecycle["a_hrt_positive_expected"]
        self.assertEqual(a_positive[local_host]["0"], [4032, 4032, 4032, 4032])
        self.assertEqual(a_positive[remote_host]["0"], [0, 4032, 4032, 4032])
        self.assertEqual(a_positive[remote_host]["1"], [4032, 4032, 4032, 4032])
        a_rf = lifecycle["a_hrt_remote_failure_expected"]
        self.assertEqual(a_rf[remote_host]["0"], [4032, 0, 0, 0])
        self.assertEqual(a_rf[remote_host]["1"], [0, 0, 0, 0])

    def test_recovery_starts_only_remote_bgp_and_b_remains_absent(self):
        recovery = self.cfg.playbooks[1]
        custom = [
            _step_params(step)
            for step in _all_steps(recovery)
            if step.name == taac_types.StepName.CUSTOM_STEP
        ]
        start = next(
            params
            for params in custom
            if params.get("custom_step_name") == "fpf_remote_prefix_start_origin_bgp"
        )
        self.assertEqual(start["remote_gtsw"], self.module.REMOTE_GTSW)
        self.assertFalse(
            any(
                step.name == taac_types.StepName.FPF_BGP_PREFIX_INJECTION_STEP
                for step in _all_steps(recovery)
            ),
            "recovery must not recreate the runtime-only B namespace",
        )
        lifecycle = _check_params(
            _checks_by_id(recovery)["fpf_tc29b_remote_prefix_stays_absent"]
        )
        self.assertEqual(lifecycle["mode"], "recovery")
        self.assertEqual(lifecycle["deadline_sec"], 60)
        self.assertEqual(
            lifecycle["outage_tolerant_collectors"],
            [f"bgp_remote_b@{self.module.REMOTE_GTSW}"],
        )
        b_scalars = [
            expected
            for collector, _device, expected in lifecycle["scalar_expectations"]
            if collector.endswith("remote_b")
        ]
        self.assertTrue(b_scalars)
        self.assertTrue(all(expected == 0 for expected in b_scalars))
        self.assertIn(
            ["fib_local_a", self.module.LOCAL_GTSW, 4032],
            lifecycle["scalar_expectations"],
        )
        for host_map in lifecycle["b_hrt_positive_expected"].values():
            for counts in host_map.values():
                self.assertEqual(counts, [0, 0, 0, 0])
        for host_map in lifecycle["b_hrt_remote_failure_expected"].values():
            for counts in host_map.values():
                self.assertEqual(counts, [0, 0, 0, 0])


if __name__ == "__main__":
    unittest.main()
