# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

import json
import unittest

from ixia.ixia import types as ixia_types
from taac.testconfigs.routing.adhoc_fibagent_qualification_traffic import (
    BAG013_EBB16_FIBAGENT_QUALIFICATION_TRAFFIC_TEMP,
)


class AdhocFibagentQualificationTrafficTest(unittest.TestCase):
    def test_bag013_config_has_two_routed_traffic_items(self) -> None:
        config = BAG013_EBB16_FIBAGENT_QUALIFICATION_TRAFFIC_TEMP
        items = list(config.basic_traffic_item_configs or [])

        self.assertEqual(
            "BAG013_EBB16_FIBAGENT_QUALIFICATION_TRAFFIC_TEMP",
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
            ["bag013.ash6:Ethernet3/36/2", "bag013.ash6:Ethernet3/36/2"],
            [item.src_endpoints[0].name for item in items],
        )
        self.assertEqual(
            ["bag013.ash6:Ethernet3/36/1", "bag013.ash6:Ethernet3/36/1"],
            [item.dest_endpoints[0].name for item in items],
        )
        self.assertEqual([10, 10], [item.line_rate for item in items])
        self.assertEqual(
            [None, None],
            [item.src_endpoints[0].network_group_index for item in items],
        )
        self.assertEqual(
            [1, 0],
            [item.dest_endpoints[0].device_group_index for item in items],
        )
        self.assertEqual(
            [0, 0],
            [item.dest_endpoints[0].network_group_index for item in items],
        )

    def test_config_keeps_phase1_storm_contract_in_copied_playbook(self) -> None:
        config = BAG013_EBB16_FIBAGENT_QUALIFICATION_TRAFFIC_TEMP
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

        self.assertEqual(48, storm["epoch_count"])
        self.assertEqual(25, storm["epoch_interval_seconds"])
        self.assertEqual(25, storm["target_membership_width"])
        self.assertEqual(1000, storm["fibagent_nhg_watermark_high"])
        self.assertEqual(1000, storm["fibagent_nhg_watermark_low"])
        self.assertTrue(storm["enable_control_plane_validation"])
        self.assertTrue(storm["defer_control_plane_invariant_failures"])
