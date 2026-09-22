# Copyright (c) Meta Platforms, Inc. and affiliates.

import json
import unittest

from taac.playbooks.playbook_definitions import (
    add_common_checks_to_thft_playbooks,
    create_thft_playbooks,
)
from taac.health_check.health_check import types as hc_types


class ThftPlaybooksTest(unittest.TestCase):
    def test_default_suite_preserves_existing_numbering(self) -> None:
        playbooks = create_thft_playbooks("dut")

        self.assertEqual(
            [playbook.name for playbook in playbooks],
            [
                "npi_thft_001_baseline_thrift_stress",
                "npi_thft_002_thrift_stress_with_restart_wedge_agent",
                "npi_thft_003_thrift_stress_with_restart_bgpd",
                "npi_thft_004_thrift_stress_with_restart_qsfp_service",
                "npi_thft_005_thrift_stress_with_restart_fsdb",
            ],
        )

    def test_kitchen_sink_suite_uses_requested_six_case_numbering(self) -> None:
        playbooks = create_thft_playbooks(
            "dut",
            include_kitchen_sink=True,
        )

        self.assertEqual(
            [playbook.name for playbook in playbooks],
            [
                "npi_thft_001_kitchen_sink",
                "npi_thft_002_baseline_thrift_stress",
                "npi_thft_003_thrift_stress_with_restart_wedge_agent",
                "npi_thft_004_thrift_stress_with_restart_bgpd",
                "npi_thft_005_thrift_stress_with_restart_qsfp_service",
                "npi_thft_006_thrift_stress_with_restart_fsdb",
            ],
        )
        self.assertEqual(len(playbooks[0].periodic_tasks or []), 1)
        self.assertEqual(len(playbooks[1].periodic_tasks or []), 2)

    def test_device_only_bgp_checks_use_exact_session_count(self) -> None:
        playbooks = add_common_checks_to_thft_playbooks(
            create_thft_playbooks("dut"),
            require_all_bgp_sessions_established=False,
            expected_established_bgp_sessions=6,
            compare_bgp_peer_routes=False,
        )

        for playbook in playbooks:
            self.assertIn(
                hc_types.CheckName.BGP_SESSION_ESTABLISH_CHECK,
                [check.name for check in (playbook.prechecks or [])],
            )
            self.assertIn(
                hc_types.CheckName.BGP_SESSION_ESTABLISH_CHECK,
                [check.name for check in (playbook.postchecks or [])],
            )
            self.assertNotIn(
                hc_types.CheckName.BGP_PEER_ROUTE_CHECK,
                [check.name for check in (playbook.snapshot_checks or [])],
            )

    def test_flap_task_is_dynamic_six_second_and_bounded_to_stress_stage(self) -> None:
        playbook = create_thft_playbooks(
            "dut",
            test_duration_s=600,
        )[0]
        flap_task = next(
            task
            for task in (playbook.periodic_tasks or [])
            if task.name == "qsfp_flap_check"
        )
        params_list = flap_task.params_list or []
        json_params = params_list[0].json_params
        assert json_params is not None
        params = json.loads(json_params)

        self.assertTrue(params["resolve_flap_interfaces_from_lldp"])
        self.assertEqual(params["calls"][0]["args"], [[], 6, 1])
        self.assertEqual(flap_task.interval, 0)
        self.assertEqual(flap_task.max_runtime, 600)

    def test_each_stress_playbook_has_five_minute_clean_longevity_stage(self) -> None:
        playbooks = create_thft_playbooks(
            "dut",
            test_duration_s=600,
            restart_test_duration_s=480,
        )

        for playbook in playbooks:
            stages = playbook.stages or []
            steps = stages[-1].steps or []
            step_params = steps[0].step_params
            assert step_params is not None
            self.assertEqual(
                step_params.json_params,
                '{"duration": 300}',
            )
            stress_duration = 600 if "baseline" in playbook.name else 480
            for task in playbook.periodic_tasks or []:
                self.assertEqual(task.max_runtime, stress_duration)

    def test_common_postchecks_require_all_ports_and_bgp_up(self) -> None:
        playbooks = add_common_checks_to_thft_playbooks(
            create_thft_playbooks("dut"),
            require_all_bgp_sessions_established=True,
        )

        for playbook in playbooks:
            postcheck_names = [check.name for check in (playbook.postchecks or [])]
            self.assertIn(hc_types.CheckName.PORT_STATE_CHECK, postcheck_names)
            self.assertIn(
                hc_types.CheckName.BGP_SESSION_ESTABLISH_CHECK,
                postcheck_names,
            )
            self.assertIn(hc_types.CheckName.UNCLEAN_EXIT_CHECK, postcheck_names)
            self.assertIn(
                hc_types.CheckName.CORE_DUMPS_CHECK,
                [check.name for check in (playbook.snapshot_checks or [])],
            )


if __name__ == "__main__":
    unittest.main()
