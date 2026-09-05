# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe
"""Unit tests for the FPF flap + STSW disruption test configs (TC32, TC33, TC35).

These configs build at import time with no device access, so the tests assert
the static TestConfig structure: the two-playbook (disruption-only +
longevity) shape, the rapid-flap window (900s), longevity settle (300s), the
STSW drain/undrain step ordering + reinject community, and the ``["fpf"]`` tag.
"""

import importlib
import json
import os
import unittest
from unittest.mock import patch

from taac.testconfigs.fpf import (
    fpf_hardening_common,
    fpf_tc32_downlink_flaps,
)
from taac.testconfigs.fpf.fpf_hardening_common import GPU_HOSTS
from taac.testconfigs.fpf.fpf_tc32_downlink_flaps import (
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
    "fpf_hrt_postcheck",
}

# Remote-failure stable check IDs. The single-injection configs (tc32/tc33)
# carry one broad "fpf_remote_failure_stable" check; the 8-STSW split-per-VF
# injection configs (tc34/tc35, rf_vf_groups) replace it with one per VF group,
# each scoped to that group's own lanes ("fpf_remote_failure_stable_<suffix>").
_RF_STABLE_SINGLE_IDS = {"fpf_remote_failure_stable"}
_RF_STABLE_VF_GROUP_IDS = {
    "fpf_remote_failure_stable_vf1",
    "fpf_remote_failure_stable_vf2",
}


def _longevity_carries_v2_stable_check_set(tc, test, vf_grouped=False):
    """Per-config HC contract: the longevity playbook (v2) must carry the full
    stable-state check set (see _V2_STABLE_REQUIRED_IDS), the remote-failure
    stable check(s) (per-VF-group when ``vf_grouped``), plus EITHER the
    prod-prefix stability or recovery check."""
    longevity = tc.playbooks[1]
    ids = {c.check_id for c in (longevity.postchecks or []) if c.check_id}
    required = _V2_STABLE_REQUIRED_IDS | (
        _RF_STABLE_VF_GROUP_IDS if vf_grouped else _RF_STABLE_SINGLE_IDS
    )
    missing = required - ids
    test.assertFalse(missing, f"longevity missing stable check IDs: {missing}")
    test.assertTrue(
        ("fpf_prod_hrt_prefix_stability" in ids)
        or ("fpf_prod_hrt_prefix_recovery" in ids),
        "longevity missing a prod-prefix HC (stability or recovery)",
    )


class TestRapidFlapConfigs(unittest.TestCase):
    """TC32 (downlinks) and TC33 (uplinks) share the same flap shape."""

    def _assert_flap_config(
        self,
        tc,
        name,
        flap_sec,
        longevity_sec,
        neighbor_pattern,
        *,
        vf_grouped=False,
    ):
        self.assertEqual(tc.name, name)
        self.assertIn("fpf", tc.tags or [])
        # Two-playbook structure.
        self.assertEqual(len(tc.playbooks), 2)
        _disrupt_playbook_has_no_checks(tc, self)
        _longevity_playbook_has_checks(tc, self)
        _longevity_carries_v2_stable_check_set(tc, self, vf_grouped=vf_grouped)

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
            None,
            vf_grouped=True,
        )
        # TC32 is the single-plane staging gate for the wider TC40 campaign. It
        # must touch exactly the environment-selected server circuit and fail
        # closed if LLDP resolves anything else.
        flap_params = _params(_steps(TC32.playbooks[0])[0])
        self.assertEqual(flap_params["neighbor_hosts"], [GPU_HOSTS[0]])
        self.assertIsNone(flap_params["neighbor_pattern"])
        self.assertTrue(flap_params["fail_closed"])
        self.assertTrue(flap_params["require_exact_neighbor_hosts"])
        self.assertEqual(len(flap_params["expected_interfaces"]), 4)
        self.assertEqual(
            flap_params["nic_recovery_by_interface"],
            {
                interface: {"host": GPU_HOSTS[0], "dev": gpu, "lane": 0}
                for gpu, interface in enumerate(flap_params["expected_interfaces"])
            },
        )

    def test_nic_recovery_map_is_derived_from_breakout_channel(self):
        shuffled = ["eth1/41/8", "eth1/41/5", "eth1/41/7", "eth1/41/6"]
        recovery = fpf_hardening_common.fpf_nic_recovery_by_interface(
            gtsw="gtsw001.l1002.c087.mwg2",
            host="twshared1352.03.mwg2",
            interfaces=shuffled,
        )
        self.assertEqual(
            {interface: target["dev"] for interface, target in recovery.items()},
            {
                "eth1/41/5": 0,
                "eth1/41/6": 1,
                "eth1/41/7": 2,
                "eth1/41/8": 3,
            },
        )
        self.assertTrue(all(target["lane"] == 0 for target in recovery.values()))

    def test_nic_recovery_map_rejects_non_bundle_interfaces(self):
        with self.assertRaisesRegex(ValueError, "exact 1..4 or 5..8 breakout"):
            fpf_hardening_common.fpf_nic_recovery_by_interface(
                gtsw="gtsw001.l1002.c087.mwg2",
                host="twshared1352.03.mwg2",
                interfaces=[
                    "eth1/41/5",
                    "eth1/41/6",
                    "eth1/41/7",
                    "eth1/41/9",
                ],
            )

    def test_tc32_twshared_uses_exact_circuit_and_eight_by_four_model(self):
        hosts = ["twshared1352.03.mwg2", "twshared1375.03.mwg2"]
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
                    "TAAC_FPF_LINK_DRAIN_INTERFACE": "eth1/41/5",
                },
            ):
                os.environ.pop("TAAC_FPF_SKIP_SSH_DEPS", None)
                os.environ.pop("TAAC_FPF_SKIP_IB_TRAFFIC", None)
                importlib.reload(fpf_hardening_common)
                module = importlib.reload(fpf_tc32_downlink_flaps)
                config = module.create_fpf_tc32_test_config()

                flap = _params(_steps(config.playbooks[0])[0])
                self.assertEqual(flap["neighbor_hosts"], [hosts[0]])
                self.assertEqual(
                    flap["expected_interfaces"],
                    ["eth1/41/5", "eth1/41/6", "eth1/41/7", "eth1/41/8"],
                )
                self.assertEqual(
                    flap["nic_recovery_by_interface"],
                    {
                        f"eth1/41/{5 + gpu}": {
                            "host": hosts[0],
                            "dev": gpu,
                            "lane": 0,
                        }
                        for gpu in range(4)
                    },
                )

                collector = next(
                    task
                    for task in config.setup_tasks
                    if task.task_name == "fpf_start_collectors"
                )
                collector_params = json.loads(collector.params.json_params)
                self.assertEqual(collector_params["hrt_device_ids"], list(range(8)))
                self.assertEqual(collector_params["hrt_plane_ids"], [0, 1, 2, 3])

                inject = next(
                    task
                    for task in config.setup_tasks
                    if task.task_name == "fpf_inject_bgp_prefixes"
                    and not json.loads(task.params.json_params)["withdraw"]
                )
                inject_params = json.loads(inject.params.json_params)
                self.assertEqual(inject_params["groups"][0]["count"], 4032)
                self.assertEqual(inject_params["groups"][1]["count"], 4032)
                self.assertIn(
                    "fpf_start_ib_traffic",
                    {task.task_name for task in config.setup_tasks},
                )
        finally:
            importlib.reload(fpf_hardening_common)
            importlib.reload(fpf_tc32_downlink_flaps)

    def test_tc32_derives_interface_scope_when_factory_is_called(self):
        interfaces = [f"eth1/41/{channel}" for channel in range(1, 5)]
        with (
            patch.object(
                fpf_tc32_downlink_flaps,
                "fpf_gpu_downlink_interfaces",
                return_value=interfaces,
            ) as derive_interfaces,
            patch.object(
                fpf_tc32_downlink_flaps,
                "fpf_nic_recovery_by_interface",
                return_value={interface: {} for interface in interfaces},
            ) as derive_recovery,
        ):
            config = fpf_tc32_downlink_flaps.create_fpf_tc32_test_config()

        flap_params = _params(_steps(config.playbooks[0])[0])
        self.assertEqual(flap_params["expected_interfaces"], interfaces)
        derive_interfaces.assert_called_once_with()
        derive_recovery.assert_called_once_with(
            gtsw=fpf_tc32_downlink_flaps.DUT_GTSW,
            host=fpf_tc32_downlink_flaps.FLAP_HOST,
            interfaces=interfaces,
        )

    def test_downlink_bundle_rejects_cross_breakout_start(self):
        with patch.object(
            fpf_hardening_common,
            "fpf_link_drain_interface",
            return_value="eth1/41/6",
        ):
            with self.assertRaisesRegex(ValueError, "breakout channel 1 or 5"):
                fpf_hardening_common.fpf_gpu_downlink_interfaces()

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
        """Downlinks use an exact GPU host; uplinks use the STSW glob."""
        tc32_params = _params(_steps(TC32.playbooks[0])[0])
        tc33_params = _params(_steps(TC33.playbooks[0])[0])
        self.assertEqual(tc32_params["neighbor_hosts"], [GPU_HOSTS[0]])
        self.assertIsNone(tc32_params["neighbor_pattern"])
        self.assertIsNone(tc33_params["neighbor_hosts"])
        self.assertEqual(tc33_params["neighbor_pattern"], UPLINK_NEIGHBOR_PATTERN)


class TestStswDrainReinjectConfigs(unittest.TestCase):
    def test_tc35_undrain_step_ordering_and_base_community(self):
        self.assertEqual(TC35.name, "fpf_tc35_stsw_undrain_reinject")
        self.assertIn("fpf", TC35.tags or [])
        self.assertEqual(len(TC35.playbooks), 2)
        _disrupt_playbook_has_no_checks(TC35, self)
        _longevity_playbook_has_checks(TC35, self)
        _longevity_carries_v2_stable_check_set(TC35, self, vf_grouped=True)
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
