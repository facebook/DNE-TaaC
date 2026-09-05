# Copyright (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe

"""Structural safety tests for shared-suite TC17/TC19 drain coverage."""

import importlib
import json
import os
import unittest
from unittest.mock import patch

from taac.testconfigs.fpf import (
    fpf_hardening_common,
    fpf_shared_injection_suite,
    fpf_tc19_device_drain,
)
from taac.testconfigs.fpf.fpf_hardening_common import (
    DEFAULT_GPU_HOSTS,
    DEFAULT_LINK_DRAIN_INTERFACE,
    fpf_device_drain_gtsw,
    fpf_link_drain_interface,
)
from taac.health_check.health_check import types as hc_types


TW_HOSTS = ["twshared1352.03.mwg2", "twshared1388.03.mwg2"]
TW_ENV = {
    "FPF_GPU_HOSTS": ",".join(TW_HOSTS),
    "FPF_HRT_DEVICE_IDS": "0,1,2,3,4,5,6,7",
    "FPF_HRT_LANES": "0,1,2,3",
    "FPF_HRT_VF1_DEVICE_IDS": "0,2,4,6",
    "FPF_HRT_VF2_DEVICE_IDS": "1,3,5,7",
    "TAAC_FPF_LINK_DRAIN_INTERFACE": "eth1/41/5",
    "TAAC_FPF_DEVICE_DRAIN_GTSW": "gtsw002.l1002.c087.mwg2",
    "TAAC_FPF_SKIP_IB_TRAFFIC": "1",
    "TAAC_FPF_SKIP_SSH_DEPS": "0",
}


def _playbook(config, name):
    return next(playbook for playbook in config.playbooks if playbook.name == name)


def _steps(playbook):
    return [step for stage in playbook.stages for step in (stage.steps or [])]


def _custom_steps(playbook, name: str):
    return [
        step
        for step in _steps(playbook)
        if _step_params(step).get("custom_step_name") == name
    ]


def _step_params(step) -> dict:
    return json.loads(step.step_params.json_params)


def _check_params(check) -> dict:
    return json.loads(check.check_params.json_params)


class FpfDrainSafetyTest(unittest.TestCase):
    @classmethod
    def tearDownClass(cls) -> None:
        # Other tests in this target must see the legacy environment again.
        importlib.reload(fpf_hardening_common)
        importlib.reload(fpf_shared_injection_suite)
        importlib.reload(fpf_tc19_device_drain)

    def _twshared_config(self):
        with patch.dict(os.environ, TW_ENV):
            importlib.reload(fpf_hardening_common)
            importlib.reload(fpf_shared_injection_suite)
            importlib.reload(fpf_tc19_device_drain)
            return fpf_shared_injection_suite.create_fpf_shared_injection_suite_test_config()

    def _twshared_standalone_tc19(self):
        with patch.dict(os.environ, TW_ENV):
            importlib.reload(fpf_hardening_common)
            importlib.reload(fpf_tc19_device_drain)
            return fpf_tc19_device_drain.create_fpf_tc19_test_config()

    def test_link_interface_legacy_default_and_override_validation(self) -> None:
        with patch.dict(os.environ):
            os.environ.pop("TAAC_FPF_LINK_DRAIN_INTERFACE", None)
            self.assertEqual(
                fpf_link_drain_interface(DEFAULT_GPU_HOSTS),
                DEFAULT_LINK_DRAIN_INTERFACE,
            )
            with self.assertRaisesRegex(ValueError, "required"):
                fpf_link_drain_interface(TW_HOSTS)

        with patch.dict(
            os.environ,
            {"TAAC_FPF_LINK_DRAIN_INTERFACE": "not-an-interface"},
        ):
            with self.assertRaisesRegex(ValueError, "exact FBOSS interface"):
                fpf_link_drain_interface(TW_HOSTS)

        with patch.dict(
            os.environ,
            {"TAAC_FPF_LINK_DRAIN_INTERFACE": "eth1/45/5"},
        ):
            with self.assertRaisesRegex(ValueError, "does not match"):
                fpf_link_drain_interface(TW_HOSTS)

        with patch.dict(
            os.environ,
            {"TAAC_FPF_LINK_DRAIN_INTERFACE": "eth1/41/5"},
        ):
            self.assertEqual(fpf_link_drain_interface(TW_HOSTS), "eth1/41/5")

    def test_device_drain_target_default_and_validation(self) -> None:
        with patch.dict(os.environ):
            os.environ.pop("TAAC_FPF_DEVICE_DRAIN_GTSW", None)
            self.assertEqual(
                fpf_device_drain_gtsw(),
                "gtsw001.l1002.c087.mwg2",
            )

        with patch.dict(
            os.environ,
            {"TAAC_FPF_DEVICE_DRAIN_GTSW": "gtsw002.l1002.c087.mwg2"},
        ):
            self.assertEqual(
                fpf_device_drain_gtsw(),
                "gtsw002.l1002.c087.mwg2",
            )

        with patch.dict(
            os.environ,
            {"TAAC_FPF_DEVICE_DRAIN_GTSW": "gtsw002.l1001.c087.mwg2"},
        ):
            with self.assertRaisesRegex(ValueError, "local-pod"):
                fpf_device_drain_gtsw()

    def test_twshared_tc17_uses_exact_target_and_strict_readback(self) -> None:
        config = self._twshared_config()
        disrupt = _playbook(config, "fpf_tc17_link_drain_disrupt")
        restore = _playbook(config, "fpf_tc17_link_drain_restore")

        drain_step = next(
            step
            for step in _steps(disrupt)
            if _step_params(step).get("custom_step_name") == "fpf_drain_interface"
            and _step_params(step)["is_drain"]
        )
        drain = _step_params(drain_step)
        self.assertEqual(drain["interfaces"], ["eth1/41/5"])
        self.assertEqual(drain["target_device"], "gtsw001.l1002.c087.mwg2")
        self.assertEqual(drain["mutation_token"], "fpf_tc17_link_drain")
        verifies = [
            _step_params(step)
            for step in _custom_steps(disrupt, "fpf_verify_disruption")
        ]
        self.assertEqual(
            [verify["expect_drained"] for verify in verifies], [False, True]
        )
        self.assertTrue(all(verify["mode"] == "drain" for verify in verifies))
        self.assertTrue(all(verify["fail_if_ineffective"] for verify in verifies))
        self.assertTrue(
            all(
                verify["target_device"] == "gtsw001.l1002.c087.mwg2"
                for verify in verifies
            )
        )
        self.assertIn(fpf_shared_injection_suite.DUT_GTSW, drain_step.description)

        plane_check = next(
            check
            for check in disrupt.postchecks
            if check.check_id == "fpf_hrt_plane_status_drain"
        )
        self.assertEqual(
            _check_params(plane_check)["impacted_tuples_by_host_device"],
            {TW_HOSTS[0]: {"0": [0]}},
        )

        restore_action = next(
            _step_params(step)
            for step in _steps(restore)
            if _step_params(step).get("custom_step_name") == "fpf_conditional_undrain"
        )
        self.assertEqual(restore_action["interfaces"], ["eth1/41/5"])
        self.assertEqual(restore_action["mutation_token"], "fpf_tc17_link_drain")
        self.assertFalse(restore_action["best_effort"])
        restore_verify = next(
            _step_params(step)
            for step in _steps(restore)
            if _step_params(step).get("custom_step_name") == "fpf_verify_disruption"
        )
        self.assertIs(restore_verify["expect_drained"], False)
        self.assertIs(restore_verify["fail_if_ineffective"], True)
        self.assertEqual(list(disrupt.cleanup_steps or []), [])
        cleanup = _step_params(restore.cleanup_steps[0])
        self.assertEqual(cleanup["interfaces"], ["eth1/41/5"])
        self.assertTrue(cleanup["best_effort"])

    def test_tc19_targets_gtsw002_even_devices_on_local_plane_one(self) -> None:
        config = self._twshared_config()
        disrupt = _playbook(config, "fpf_tc19_device_drain_disrupt")
        plane_check = next(
            check
            for check in disrupt.postchecks
            if check.check_id == "fpf_hrt_plane_status_drain"
        )
        self.assertEqual(
            _check_params(plane_check)["impacted_tuples_by_host_device"],
            {TW_HOSTS[0]: {"0": [1], "2": [1], "4": [1], "6": [1]}},
        )

        verifies = [
            _step_params(step)
            for step in _custom_steps(disrupt, "fpf_verify_disruption")
        ]
        self.assertEqual(
            [verify["mode"] for verify in verifies], ["device_clean", "device_drain"]
        )
        self.assertTrue(all(verify["interfaces"] == [] for verify in verifies))
        self.assertTrue(all(verify["fail_if_ineffective"] for verify in verifies))
        self.assertTrue(
            all(
                verify["target_device"] == "gtsw002.l1002.c087.mwg2"
                for verify in verifies
            )
        )
        drain = _step_params(_custom_steps(disrupt, "fpf_drain_interface")[0])
        self.assertEqual(drain["target_device"], "gtsw002.l1002.c087.mwg2")
        self.assertEqual(drain["mutation_token"], "fpf_tc19_device_drain")
        restore = _playbook(config, "fpf_tc19_device_drain_restore")
        self.assertEqual(list(disrupt.cleanup_steps or []), [])
        cleanup = _step_params(restore.cleanup_steps[0])
        self.assertEqual(cleanup["interfaces"], [])
        self.assertEqual(cleanup["target_device"], "gtsw002.l1002.c087.mwg2")
        self.assertTrue(cleanup["best_effort"])

        circuits = fpf_shared_injection_suite._device_drain_circuits(
            "gtsw002.l1002.c087.mwg2"
        )
        self.assertTrue(circuits)
        self.assertTrue(all(circuit.a_end_interface == "" for circuit in circuits))

        collector = next(
            task
            for task in config.setup_tasks
            if task.task_name == "fpf_start_collectors"
        )
        collector_params = json.loads(collector.params.json_params)
        self.assertIn("gtsw002.l1002.c087.mwg2", collector_params["gtsws"])

    def test_standalone_tc19_uses_same_target_and_tuple_scope(self) -> None:
        config = self._twshared_standalone_tc19()
        disrupt = _playbook(config, "fpf_tc19_device_drain_disrupt")
        drain = _step_params(_custom_steps(disrupt, "fpf_drain_interface")[0])
        self.assertEqual(drain["target_device"], "gtsw002.l1002.c087.mwg2")
        plane_check = next(
            check
            for check in disrupt.postchecks
            if check.check_id == "fpf_hrt_plane_status_drain"
        )
        self.assertEqual(
            _check_params(plane_check)["impacted_tuples_by_host_device"],
            {TW_HOSTS[0]: {"0": [1], "2": [1], "4": [1], "6": [1]}},
        )
        restore = _playbook(config, "fpf_tc19_device_drain_restore")
        self.assertEqual(list(disrupt.cleanup_steps or []), [])
        self.assertTrue(restore.cleanup_steps)
        collector = next(
            task
            for task in config.setup_tasks
            if task.task_name == "fpf_start_collectors"
        )
        collector_params = json.loads(collector.params.json_params)
        self.assertIn("gtsw002.l1002.c087.mwg2", collector_params["gtsws"])
        self.assertEqual(collector_params["hrt_device_ids"], list(range(8)))
        self.assertEqual(collector_params["hrt_plane_ids"], list(range(4)))

    def test_non_drain_playbooks_and_global_tasks_have_no_drain_mutation(self) -> None:
        config = self._twshared_config()
        self.assertNotIn(
            "fpf_ensure_undrained",
            [task.task_name for task in [*config.setup_tasks, *config.teardown_tasks]],
        )
        for playbook in config.playbooks:
            if playbook.name.startswith(("fpf_tc17_", "fpf_tc19_")):
                continue
            custom_names = {
                _step_params(step).get("custom_step_name")
                for step in [*_steps(playbook), *(playbook.cleanup_steps or [])]
                if step.step_params is not None
                and step.step_params.json_params is not None
            }
            self.assertFalse(
                {"fpf_drain_interface", "fpf_conditional_undrain"} & custom_names,
                playbook.name,
            )

    def test_disrupt_and_restore_include_generic_ssh_and_snapshots(self) -> None:
        config = self._twshared_config()
        for name in (
            "fpf_tc17_link_drain_disrupt",
            "fpf_tc17_link_drain_restore",
            "fpf_tc19_device_drain_disrupt",
            "fpf_tc19_device_drain_restore",
        ):
            with self.subTest(playbook=name):
                playbook = _playbook(config, name)
                pre_names = {check.name for check in playbook.prechecks or []}
                post_names = {check.name for check in playbook.postchecks or []}
                point_in_time_names = pre_names | post_names
                snapshot_names = {
                    check.name for check in playbook.snapshot_checks or []
                }
                self.assertIn(
                    hc_types.CheckName.SYSTEMCTL_ACTIVE_STATE_CHECK,
                    point_in_time_names,
                )
                self.assertIn(
                    hc_types.CheckName.UNCLEAN_EXIT_CHECK,
                    point_in_time_names,
                )
                self.assertIn(
                    hc_types.CheckName.MEMORY_UTILIZATION_CHECK,
                    point_in_time_names,
                )
                self.assertIn(
                    hc_types.CheckName.DEVICE_CORE_DUMPS_CHECK,
                    point_in_time_names,
                )
                self.assertIn(hc_types.CheckName.CORE_DUMPS_CHECK, snapshot_names)
                self.assertIn(hc_types.CheckName.BGP_SESSION_CHECK, snapshot_names)


if __name__ == "__main__":
    unittest.main()
