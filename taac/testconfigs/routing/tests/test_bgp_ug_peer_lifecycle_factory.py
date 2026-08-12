# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""Construction test for the Spec 2.2 Peer Lifecycle (TC2) UG TestConfig.

Exercises the full factory build on BAG011_ASH6 (the bound inventory), which
also constructs all three 2.2 playbooks -- catching any bad step/health-check
kwarg at test time rather than at runtime discovery.
"""

import unittest

from taac.abstractions.physical_inventory import BAG011_ASH6
from taac.testconfigs.routing.factories.qual_bgp_update_group.tc2_peer_lifecycle import (
    create_bgp_ug_peer_lifecycle_test_config,
)


class BgpUgPeerLifecycleFactoryTest(unittest.TestCase):
    def test_constructs_on_bag011_with_expected_name_and_playbooks(self) -> None:
        config = create_bgp_ug_peer_lifecycle_test_config(BAG011_ASH6)
        # --test-config resolves against .name; must match the sibling UG
        # convention (e.g. BAG011_ASH6_BGP_UG_EDGE_CASES_TEST), NOT the
        # _derive_test_config_name form.
        self.assertEqual(config.name, "BAG011_ASH6_BGP_UG_PEER_LIFECYCLE_TEST")
        # 2.2.1 + 2.2.2 + 2.2.3 are all wired; select with --regex at runtime.
        self.assertEqual(
            [pb.name for pb in config.playbooks],
            [
                "bgp_ug_peer_down_remaining_unaffected",
                "bgp_ug_peer_reconnect_shadow_rib",
                "bgp_ug_sustained_group_membership_churn",
            ],
        )


if __name__ == "__main__":
    unittest.main()
