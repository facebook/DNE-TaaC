# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe
"""Unit tests for the FPF flap + STSW disruption test configs (TC32-TC35).

These configs build at import time with no device access, so the tests assert
the static TestConfig structure: the two-playbook (disruption-only +
longevity) shape, the rapid-flap window (900s), longevity settle (300s), the
STSW drain/undrain step ordering + reinject community, and the ``["fpf"]`` tag.
"""

import json
import unittest

from taac.testconfigs.fpf.fpf_hardening_common import GPU_HOSTS
from taac.testconfigs.fpf.fpf_tc32_downlink_flaps import (
    DOWNLINK_NEIGHBOR_PATTERN,
    FLAP_DURATION_SEC as TC32_FLAP_SEC,
    LONGEVITY_SEC as TC32_LONGEVITY_SEC,
    TEST_CONFIG as TC32,
)
from taac.testconfigs.fpf.fpf_tc33_gtsw_stsw_links_down import (
    FLAP_DURATION_SEC as TC33_FLAP_SEC,
    LONGEVITY_SEC as TC33_LONGEVITY_SEC,
    TEST_CONFIG as TC33,
    UPLINK_NEIGHBOR_PATTERN,
)
from taac.testconfigs.fpf.fpf_tc34_stsw_drain_reinject import (
    DRAIN_COMMUNITY,
    LONGEVITY_SEC as TC34_LONGEVITY_SEC,
    TEST_CONFIG as TC34,
)
from taac.testconfigs.fpf.fpf_tc35_stsw_undrain_reinject import (
    LONGEVITY_SEC as TC35_LONGEVITY_SEC,
    TEST_CONFIG as TC35,
)
from taac.test_as_a_config.types import StepName


def _steps(playbook):
    """Flatten the sequential steps out of a playbook's single stage."""
    out = []
    for stage in playbook.stages:
        out.extend(stage.steps or [])
    return out


def _params(step) -> dict:
    return json.loads(step.step_params.json_params)


def _disrupt_playbook_has_no_checks(tc, test):
    """First playbook is disruption-only: empty pre/post/snapshot checks."""
    disrupt = tc.playbooks[0]
    test.assertEqual(list(disrupt.prechecks or []), [])
    test.assertEqual(list(disrupt.postchecks or []), [])
    test.assertEqual(list(disrupt.snapshot_checks or []), [])


def _longevity_playbook_has_checks(tc, test):
    """Second (longevity) playbook carries the stable-state health checks."""
    longevity = tc.playbooks[1]
    test.assertTrue(longevity.postchecks, "longevity playbook should have postchecks")


# Stable-state hardening v2 check IDs that every tc32-tc35 longevity playbook
# must carry (the runner re-stamps test_case_start_time at the start of this
# playbook so the checks anchor at the post-disruption stable window). Note:
# the prod-prefix check is either ``fpf_prod_hrt_prefix_stability`` (default)
# or ``fpf_prod_hrt_prefix_recovery`` (prod_prefix_recovery=True branch); it
# is asserted separately below.
_V2_STABLE_REQUIRED_IDS = {
    "fpf_fsdb_convergence_lane0",
    "fpf_bgp_convergence_lane0",
    "fpf_hrt_convergence_lane0",
    "fpf_hrt_convergence_lane1",
    "fpf_remote_failure_stable",
    "fpf_hrt_postcheck",
}


def _longevity_carries_v2_stable_check_set(tc, test):
    """Per-config HC contract: the longevity playbook (v2) must carry the full
    stable-state check set (see _V2_STABLE_REQUIRED_IDS) plus EITHER the
    prod-prefix stability or recovery check."""
    longevity = tc.playbooks[1]
    ids = {c.check_id for c in (longevity.postchecks or []) if c.check_id}
    missing = _V2_STABLE_REQUIRED_IDS - ids
    test.assertFalse(missing, f"longevity missing stable check IDs: {missing}")
    test.assertTrue(
        ("fpf_prod_hrt_prefix_stability" in ids)
        or ("fpf_prod_hrt_prefix_recovery" in ids),
        "longevity missing a prod-prefix HC (stability or recovery)",
    )


class TestRapidFlapConfigs(unittest.TestCase):
    """TC32 (downlinks) and TC33 (uplinks) share the same flap shape."""

    def _assert_flap_config(self, tc, name, flap_sec, longevity_sec, neighbor_pattern):
        self.assertEqual(tc.name, name)
        self.assertIn("fpf", tc.tags or [])
        # Two-playbook structure.
        self.assertEqual(len(tc.playbooks), 2)
        _disrupt_playbook_has_no_checks(tc, self)
        _longevity_playbook_has_checks(tc, self)
        _longevity_carries_v2_stable_check_set(tc, self)

        # Scaled window: 15 min flaps, 5 min longevity.
        self.assertEqual(flap_sec, 900)
        self.assertEqual(longevity_sec, 300)

        steps = _steps(tc.playbooks[0])
        self.assertEqual(len(steps), 2)
        # Step 1: rapid flap LLDP variant (CUSTOM_STEP).
        flap_step = steps[0]
        self.assertEqual(flap_step.name, StepName.CUSTOM_STEP)
        flap_params = _params(flap_step)
        self.assertEqual(flap_params["custom_step_name"], "fpf_rapid_flap_lldp")
        self.assertEqual(flap_params["duration_sec"], 900)
        self.assertEqual(flap_params["neighbor_pattern"], neighbor_pattern)
        # Both flap configs now use a 6s per-flap down-time (was 0.1s) and rely
        # on the wall-clock-bounded handler loop.
        self.assertEqual(flap_params["down_time_sec"], 6.0)
        # The static pre-resolved interface map is GONE — resolution happens
        # at run time via async_get_lldp_neighbors.
        self.assertNotIn("interfaces_by_device", flap_params)

        # Step 2: longevity settle 300s.
        longevity_step = steps[1]
        self.assertEqual(longevity_step.name, StepName.LONGEVITY_STEP)
        self.assertEqual(_params(longevity_step)["duration"], 300)

    def test_tc32_downlink_flaps(self):
        self._assert_flap_config(
            TC32,
            "fpf_tc32_downlink_flaps",
            TC32_FLAP_SEC,
            TC32_LONGEVITY_SEC,
            DOWNLINK_NEIGHBOR_PATTERN,
        )
        # tc32 scopes the flap to the exact configured GPU hosts (the glob is a
        # fallback) to avoid flapping ALL downlinks (the 36h-hang root cause).
        flap_params = _params(_steps(TC32.playbooks[0])[0])
        self.assertEqual(flap_params["neighbor_hosts"], list(GPU_HOSTS))

    def test_tc33_uplink_flaps(self):
        self._assert_flap_config(
            TC33,
            "fpf_tc33_gtsw_stsw_links_down",
            TC33_FLAP_SEC,
            TC33_LONGEVITY_SEC,
            UPLINK_NEIGHBOR_PATTERN,
        )
        # tc33 intentionally flaps ALL gtsw001 STSW uplinks via the spine glob —
        # no exact host scoping.
        flap_params = _params(_steps(TC33.playbooks[0])[0])
        self.assertIsNone(flap_params["neighbor_hosts"])

    def test_tc32_and_tc33_target_different_neighbor_classes(self):
        """Downlinks (rtptest* GPUs) and uplinks (stsw* spine) are distinct."""
        self.assertNotEqual(DOWNLINK_NEIGHBOR_PATTERN, UPLINK_NEIGHBOR_PATTERN)


class TestStswDrainReinjectConfigs(unittest.TestCase):
    def test_tc34_drain_step_ordering_and_reinject(self):
        self.assertEqual(TC34.name, "fpf_tc34_stsw_drain_reinject")
        self.assertIn("fpf", TC34.tags or [])
        self.assertEqual(len(TC34.playbooks), 2)
        _disrupt_playbook_has_no_checks(TC34, self)
        _longevity_playbook_has_checks(TC34, self)
        _longevity_carries_v2_stable_check_set(TC34, self)
        self.assertEqual(TC34_LONGEVITY_SEC, 300)

        steps = _steps(TC34.playbooks[0])
        # drain, reinject, longevity.
        self.assertEqual(len(steps), 3)
        self.assertEqual(steps[0].name, StepName.DRAIN_UNDRAIN_STEP)
        self.assertEqual(steps[1].name, StepName.FPF_BGP_PREFIX_INJECTION_STEP)
        self.assertEqual(steps[2].name, StepName.LONGEVITY_STEP)
        self.assertEqual(_params(steps[2])["duration"], 300)

        # Drain appends the drain-marker community to the reinjected prefixes.
        inj = _params(steps[1])
        self.assertIn(DRAIN_COMMUNITY, inj["community_list"])
        self.assertEqual(inj["count"], 1000)

    def test_tc35_undrain_step_ordering_and_base_community(self):
        self.assertEqual(TC35.name, "fpf_tc35_stsw_undrain_reinject")
        self.assertIn("fpf", TC35.tags or [])
        self.assertEqual(len(TC35.playbooks), 2)
        _disrupt_playbook_has_no_checks(TC35, self)
        _longevity_playbook_has_checks(TC35, self)
        _longevity_carries_v2_stable_check_set(TC35, self)
        self.assertEqual(TC35_LONGEVITY_SEC, 300)

        steps = _steps(TC35.playbooks[0])
        # undrain, reinject, longevity.
        self.assertEqual(len(steps), 3)
        self.assertEqual(steps[0].name, StepName.DRAIN_UNDRAIN_STEP)
        self.assertEqual(steps[1].name, StepName.FPF_BGP_PREFIX_INJECTION_STEP)
        self.assertEqual(steps[2].name, StepName.LONGEVITY_STEP)

        # Undrain always re-injects, but with the BASE community only (the
        # drain-marker community "65446:10" must not appear).
        inj = _params(steps[1])
        self.assertNotIn("65446:10", inj["community_list"])
        self.assertEqual(inj["count"], 1000)


if __name__ == "__main__":
    unittest.main()
