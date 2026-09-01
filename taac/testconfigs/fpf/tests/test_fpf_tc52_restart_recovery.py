# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe

"""Structural tests for TC52 production-prefix restart recovery."""

import json
import unittest

from taac.testconfigs.fpf import (
    fpf_shared_injection_suite,
    fpf_tc52_hrt_restart,
)


def _playbook(config, name):
    return next(playbook for playbook in config.playbooks if playbook.name == name)


def _params(value) -> dict:
    return json.loads(value.json_params)


def _assert_tc52_contract(test, disrupt_playbook, longevity_playbook) -> None:
    checks = [
        check
        for check in disrupt_playbook.postchecks or []
        if check.check_id == "fpf_prod_hrt_prefix_restart_recovery"
    ]
    test.assertEqual(len(checks), 1)
    check_params = _params(checks[0].check_params)
    test.assertEqual(check_params["mode"], "restart_recovery")
    test.assertEqual(check_params["max_recovery_sec"], 30.0)

    bulk_checks = [
        check
        for check in disrupt_playbook.postchecks or []
        if (check.check_id or "").startswith("fpf_hrt_convergence_lane")
    ]
    rf_checks = [
        check
        for check in disrupt_playbook.postchecks or []
        if (check.check_id or "").startswith("fpf_remote_failure_stable_")
    ]
    test.assertTrue(bulk_checks)
    test.assertTrue(rf_checks)
    for check in bulk_checks + rf_checks:
        test.assertEqual(
            _params(check.check_params)["restart_tolerant_hosts"],
            [fpf_tc52_hrt_restart.GPU_HOSTS[0]],
        )

    steps = [step for stage in disrupt_playbook.stages for step in stage.steps]
    descriptions = [step.description for step in steps]
    record_index = descriptions.index(
        "Record HRT restart initiation for production-prefix recovery SLA"
    )
    test.assertEqual(
        _params(steps[record_index].step_params)["custom_step_name"],
        "record_fpf_restart_time",
    )
    test.assertIn("Restart HostReachTracker", descriptions[record_index + 1])
    test.assertEqual(
        _params(steps[record_index + 2].step_params)["custom_step_name"],
        "record_fpf_restart_completion_time",
    )

    for check in longevity_playbook.postchecks or []:
        if (
            check.check_params is not None
            and check.check_params.json_params is not None
        ):
            test.assertNotIn("restart_tolerant_hosts", _params(check.check_params))

    longevity_ids = {check.check_id for check in longevity_playbook.postchecks or []}
    test.assertIn("fpf_prod_hrt_prefix_stability", longevity_ids)
    test.assertNotIn("fpf_prod_hrt_prefix_restart_recovery", longevity_ids)


class TestFpfTc52RestartRecovery(unittest.TestCase):
    def test_standalone_tc52_uses_restart_recovery_only_on_disrupt(self):
        config = fpf_tc52_hrt_restart.create_fpf_tc52_test_config()
        _assert_tc52_contract(self, config.playbooks[0], config.playbooks[1])

    def test_shared_suite_tc52_uses_restart_recovery_only_on_disrupt(self):
        config = (
            fpf_shared_injection_suite.create_fpf_shared_injection_suite_test_config()
        )
        _assert_tc52_contract(
            self,
            _playbook(config, "fpf_tc52_hrt_restart_disrupt"),
            _playbook(config, "fpf_tc52_hrt_restart_longevity"),
        )


if __name__ == "__main__":
    unittest.main()
