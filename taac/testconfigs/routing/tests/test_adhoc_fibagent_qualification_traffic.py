# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

import json
import unittest

from ixia.ixia import types as ixia_types
from taac.abstractions.eos_bgpcpp_setup_tasks import (
    create_bgpcpp_logging_setup_task,
)
from taac.testconfigs.routing import cicd_ebb_int_tc
from taac.testconfigs.routing.adhoc_fibagent_qualification_traffic import (
    NRQEB009_EBB16_FIBAGENT_QUALIFICATION_TRAFFIC_UG_ADHOC,
)
from taac.testconfigs.routing.util.bgp_ebb_constants import (
    EBB_BGPCPP_LOGGING_CONFIG,
)
from taac.test_as_a_config.types import TestConfig


def _shell_commands(config: TestConfig) -> list[str]:
    return [
        command
        for task in config.setup_tasks or []
        if task.task_name == "run_commands_on_shell"
        for command in json.loads(task.params.json_params or "{}").get("cmds", [])
    ]


def _logging_command(logging_config: str) -> str:
    task = create_bgpcpp_logging_setup_task("nrqeb009.ash6", logging_config)
    return json.loads(task.params.json_params or "{}")["cmds"][0]


class AdhocFibagentQualificationTrafficTest(unittest.TestCase):
    def test_nrqeb009_config_routes_ibgp_to_ebgp_traffic(self) -> None:
        config = NRQEB009_EBB16_FIBAGENT_QUALIFICATION_TRAFFIC_UG_ADHOC
        items = list(config.basic_traffic_item_configs or [])

        self.assertEqual(
            "NRQEB009_EBB16_FIBAGENT_QUALIFICATION_TRAFFIC_UG_ADHOC",
            config.name,
        )
        self.assertEqual(
            [
                "EBB16_IPV4_PREFIX_CONTINUITY",
                "EBB16_IPV6_PREFIX_CONTINUITY",
            ],
            [item.name for item in items],
        )
        self.assertEqual(
            [ixia_types.TrafficType.IPV4, ixia_types.TrafficType.IPV6],
            [item.traffic_type for item in items],
        )
        self.assertEqual(
            ["nrqeb009.ash6:Ethernet3/35/2", "nrqeb009.ash6:Ethernet3/35/2"],
            [item.src_endpoints[0].name for item in items],
        )
        self.assertEqual(
            ["nrqeb009.ash6:Ethernet3/35/1", "nrqeb009.ash6:Ethernet3/35/1"],
            [item.dest_endpoints[0].name for item in items],
        )
        self.assertEqual([10, 10], [item.line_rate for item in items])

    def test_config_keeps_phase1_storm_contract_in_copied_playbook(self) -> None:
        config = NRQEB009_EBB16_FIBAGENT_QUALIFICATION_TRAFFIC_UG_ADHOC
        self.assertEqual(1, len(config.playbooks))
        playbook = config.playbooks[0]
        self.assertEqual(
            "bgp_ebb_nexthop_group_count_threshold_traffic_playbook",
            playbook.name,
        )
        payloads = [
            json.loads(step.step_params.json_params)
            for stage in playbook.stages
            for step in stage.steps or []
            if step.step_params is not None and step.step_params.json_params is not None
        ]
        storm = next(
            payload
            for payload in payloads
            if payload.get("custom_step_name") == "bgp_nhg_random_storm"
        )

        self.assertEqual(20, storm["epoch_count"])
        self.assertEqual(25, storm["epoch_interval_seconds"])
        self.assertEqual(25, storm["target_membership_width"])
        self.assertEqual(1000, storm["fibagent_nhg_watermark_high"])
        self.assertEqual(1000, storm["fibagent_nhg_watermark_low"])
        self.assertTrue(storm["enable_control_plane_validation"])
        self.assertTrue(storm["defer_control_plane_invariant_failures"])
        self.assertEqual(150, storm["restoration_stage_prefix_count"])
        self.assertEqual(10, storm["fibagent_restart_after_epoch"])
        self.assertNotIn(
            "ebb16_fibagent_restart", [stage.id for stage in playbook.stages]
        )

    def test_both_ebb16_configs_run_bgpcpp_at_dbg1(self) -> None:
        for config in (
            cicd_ebb_int_tc.NRQEB009_STAGE1_FULL_SCALE_TEST_CONFIG_UG,
            NRQEB009_EBB16_FIBAGENT_QUALIFICATION_TRAFFIC_UG_ADHOC,
        ):
            with self.subTest(config=config.name):
                commands = _shell_commands(config)
                self.assertIn(_logging_command("DBG1;default:async=true"), commands)
                self.assertNotIn(_logging_command(EBB_BGPCPP_LOGGING_CONFIG), commands)

    def test_config_is_not_scheduled_by_conveyor(self) -> None:
        scheduled_names = {
            value.name
            for value in vars(cicd_ebb_int_tc).values()
            if isinstance(value, TestConfig)
        }
        self.assertTrue(scheduled_names)
        self.assertNotIn(
            NRQEB009_EBB16_FIBAGENT_QUALIFICATION_TRAFFIC_UG_ADHOC.name,
            scheduled_names,
        )
