# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""Sequencing/structure tests for the Spec 2.2 peer-lifecycle UG playbooks
(2.2.1 peer-down, 2.2.2 reconnect, 2.2.3 sustained churn).
"""

import unittest

from taac.playbooks.routing.factories.qual_bgp_update_group.tc2_peer_lifecycle import (
    create_bgp_ug_peer_down_remaining_unaffected_playbook,
    create_bgp_ug_peer_reconnect_shadow_rib_playbook,
    create_bgp_ug_sustained_group_membership_churn_playbook,
)

_COMMON = {
    "device_name": "bag011.ash6",
    "ebgp_peer_regex": r"BGP_PEER_IPV[46]_EBGP$",
    "ebgp_peer_group_substrings": ["EB-FA-V4", "EB-FA-V6"],
    "ibgp_peer_group_substrings": ["EB-EB-V4", "EB-EB-V6"],
    "non_ibgp_parent_prefixes": ["10.0.0.0/8"],
    "prechecks": [],
    "vmhwm_threshold_bytes": 10 * 1024**3,
}


class BgpUgPeerLifecyclePlaybookTest(unittest.TestCase):
    def test_peer_down_name_and_structure(self) -> None:
        pb = create_bgp_ug_peer_down_remaining_unaffected_playbook(
            ebgp_inject_pool_regex=r"PREFIX_POOL_IPV6_EBGP$",
            **_COMMON,
        )
        self.assertEqual(pb.name, "bgp_ug_peer_down_remaining_unaffected")
        # baseline + trigger/isolation + distribution workload.
        self.assertEqual(len(pb.stages), 3)
        # Cleanup restores the dropped eBGP sessions and MUST live on the
        # Playbook (not a Stage) so it runs regardless of stage outcome.
        self.assertTrue(pb.cleanup_steps)
        self.assertTrue(pb.postchecks)
        self.assertTrue(pb.snapshot_checks)

    def test_peer_reconnect_name_and_structure(self) -> None:
        pb = create_bgp_ug_peer_reconnect_shadow_rib_playbook(
            ebgp_inject_pool_regex=r"PREFIX_POOL_IPV6_EBGP$",
            **_COMMON,
        )
        self.assertEqual(pb.name, "bgp_ug_peer_reconnect_shadow_rib")
        # baseline + trigger + downtime-inject + reconnect/resync.
        self.assertEqual(len(pb.stages), 4)
        self.assertTrue(pb.cleanup_steps)
        self.assertTrue(pb.postchecks)
        self.assertTrue(pb.snapshot_checks)

    def test_sustained_churn_name_and_structure(self) -> None:
        pb = create_bgp_ug_sustained_group_membership_churn_playbook(
            num_checkpoints=4,
            cycles_per_checkpoint=15,
            **_COMMON,
        )
        self.assertEqual(pb.name, "bgp_ug_sustained_group_membership_churn")
        # Two stages (churn block + checkpoint) per checkpoint.
        self.assertEqual(len(pb.stages), 8)
        self.assertTrue(pb.cleanup_steps)
        self.assertTrue(pb.postchecks)
        self.assertTrue(pb.snapshot_checks)

    def test_caller_snapshot_checks_list_is_not_mutated(self) -> None:
        """A caller-supplied snapshot_checks list must not be appended to.

        The factories add their own no-flap gate on top of what the caller
        passes. Appending to the caller's list instead of copying it would
        accumulate a duplicate gate per factory call when the same list is
        reused, which is exactly what sharing one list across the three 2.2.x
        factories would do.
        """
        shared: list = []
        common = {**_COMMON, "snapshot_checks": shared}

        first = create_bgp_ug_peer_down_remaining_unaffected_playbook(
            ebgp_inject_pool_regex=r"PREFIX_POOL_IPV6_EBGP$", **common
        )
        second = create_bgp_ug_sustained_group_membership_churn_playbook(
            num_checkpoints=4, cycles_per_checkpoint=15, **common
        )

        self.assertEqual([], shared, "factory mutated the caller's list")
        # Each playbook gets exactly its own single added gate, not a running
        # tally of every factory that has been called with this list.
        self.assertEqual(1, len(first.snapshot_checks or []))
        self.assertEqual(1, len(second.snapshot_checks or []))


if __name__ == "__main__":
    unittest.main()
