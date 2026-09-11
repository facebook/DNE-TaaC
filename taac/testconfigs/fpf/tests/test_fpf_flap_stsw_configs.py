# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe
"""Unit tests for the FPF flap + STSW disruption test configs.

These configs build at import time with no device access, so the tests assert
the static TestConfig structure: the two-playbook (disruption-only +
longevity) shape, case-specific rapid-flap windows, longevity settle (300s),
the STSW drain/undrain step ordering + reinject community, and the ``["fpf"]``
tag.
"""

import importlib
import json
import os
import unittest
from unittest.mock import patch

from taac.testconfigs.fpf import (
    fpf_hardening_common,
    fpf_tc32_downlink_flaps,
    fpf_tc40_cont_interface_flaps,
    fpf_tc42_cont_flaps_wedge_restart,
    fpf_tc43_cont_flaps_bgp_restart,
    fpf_tc44_cont_flaps_fsdb_restart,
    fpf_tc55_gtsw_device_reboot,
    fpf_tc56_cont_flaps_qsfp_restart,
    fpf_tc57_cont_flaps_qsfp_crash,
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
from taac.health_check.health_check.types import CheckName
from taac.test_as_a_config.types import Service, StepName


def _steps(playbook):
    """Flatten the sequential steps out of a playbook's single stage."""
    out = []
    for stage in playbook.stages:
        out.extend(stage.steps or [])
    return out


def _params(step) -> dict:
    return json.loads(step.step_params.json_params)


def _check_params(check) -> dict:
    return json.loads(check.check_params.json_params)


def _check_ids(playbook) -> set[str]:
    return {check.check_id for check in playbook.postchecks or [] if check.check_id}


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


def _assert_recovered_baseline_qualification(tc, test):
    prechecks = {
        check.check_id: check
        for check in tc.playbooks[1].prechecks or []
        if check.check_id
    }
    for check_id in (
        "fpf_prod_hrt_prefix_stability_precheck",
        "fpf_hrt_system_memory_precheck",
        "fpf_hrt_driver_disconnect_precheck",
    ):
        test.assertNotIn(check_id, prechecks)
    steps = [step for stage in tc.playbooks[1].stages for step in stage.steps or []]
    gate_index = next(
        index
        for index, step in enumerate(steps)
        if _params(step).get("custom_step_name") == "fpf_verify_recovered_state"
    )
    anchor_index = next(
        index
        for index, step in enumerate(steps)
        if _params(step).get("custom_step_name") == "record_fpf_recovered_baseline_time"
    )
    test.assertLess(gate_index, anchor_index)
    qualification = _params(steps[anchor_index + 1])
    longevity = _params(steps[anchor_index + 2])
    test.assertEqual(qualification["duration"], 120)
    test.assertEqual(longevity["duration"], 300)


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
        _assert_recovered_baseline_qualification(tc, self)

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

                tc40_module = importlib.reload(fpf_tc40_cont_interface_flaps)
                tc40 = tc40_module.create_fpf_tc40_test_config()
                tc40_flap = next(
                    _params(step)
                    for step in _steps(tc40.playbooks[0])
                    if _params(step).get("custom_step_name")
                    == "fpf_multi_gtsw_rapid_flap"
                )
                self.assertTrue(tc40_flap["fail_closed"])
                self.assertEqual(tc40_flap["neighbor_hosts"], [hosts[0]])
                self.assertEqual(
                    tc40_flap["expected_interfaces"],
                    ["eth1/41/5", "eth1/41/6", "eth1/41/7", "eth1/41/8"],
                )
                recovery = tc40_flap["nic_recovery_by_gtsw_interface"]
                self.assertEqual(set(recovery), set(tc40_module.ALL_GTSWS))
                self.assertEqual(
                    recovery[tc40_module.ALL_GTSWS[0]]["eth1/41/8"],
                    {"host": hosts[0], "dev": 3, "lane": 0},
                )
                self.assertEqual(
                    recovery[tc40_module.ALL_GTSWS[-1]]["eth1/41/5"],
                    {"host": hosts[0], "dev": 0, "lane": 7},
                )
        finally:
            importlib.reload(fpf_hardening_common)
            importlib.reload(fpf_tc32_downlink_flaps)
            importlib.reload(fpf_tc40_cont_interface_flaps)

    def test_tc40_opts_into_fail_closed_multi_gtsw_safety(self):
        config = fpf_tc40_cont_interface_flaps.TEST_CONFIG
        _assert_recovered_baseline_qualification(config, self)
        flap = next(
            _params(step)
            for step in _steps(config.playbooks[0])
            if _params(step).get("custom_step_name") == "fpf_multi_gtsw_rapid_flap"
        )
        self.assertTrue(flap["fail_closed"])
        self.assertTrue(flap["require_exact_neighbor_hosts"])
        self.assertEqual(
            flap["expected_interfaces"],
            fpf_tc40_cont_interface_flaps.FLAP_INTERFACES,
        )
        self.assertEqual(
            set(flap["nic_recovery_by_gtsw_interface"]),
            set(fpf_tc40_cont_interface_flaps.ALL_GTSWS),
        )

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

    def test_tc56_tc57_reuse_tc40_contract_with_qsfp_churn(self):
        tc40 = fpf_tc40_cont_interface_flaps.TEST_CONFIG
        cases = (
            (
                fpf_tc56_cont_flaps_qsfp_restart,
                "fpf_tc56_cont_flaps_qsfp_restart",
                "restart",
            ),
            (
                fpf_tc57_cont_flaps_qsfp_crash,
                "fpf_tc57_cont_flaps_qsfp_crash",
                "crash",
            ),
        )
        for module, name, action in cases:
            with self.subTest(name=name):
                config = module.TEST_CONFIG
                self.assertEqual(config.name, name)
                self.assertEqual(config.setup_tasks, tc40.setup_tasks)
                self.assertEqual(config.teardown_tasks, tc40.teardown_tasks)
                self.assertEqual(
                    config.playbooks[0].postchecks,
                    tc40.playbooks[0].postchecks,
                )
                self.assertEqual(
                    config.playbooks[1].postchecks,
                    tc40.playbooks[1].postchecks,
                )
                _longevity_carries_v2_stable_check_set(
                    config,
                    self,
                    vf_grouped=True,
                )
                _assert_recovered_baseline_qualification(config, self)

                steps = _steps(config.playbooks[0])
                self.assertEqual(len(steps), 3)
                self.assertEqual(
                    _params(steps[0])["custom_step_name"],
                    "fpf_up_port_baseline",
                )
                flap = _params(steps[1])
                self.assertEqual(flap["duration_sec"], 1800)
                self.assertEqual(flap["down_time_sec"], 7.0)
                self.assertEqual(flap["up_time_sec"], 7.0)
                self.assertTrue(flap["fail_closed"])
                self.assertEqual(
                    flap["expected_interfaces"],
                    fpf_tc40_cont_interface_flaps.FLAP_INTERFACES,
                )
                self.assertEqual(
                    set(flap["nic_recovery_by_gtsw_interface"]),
                    set(fpf_tc40_cont_interface_flaps.ALL_GTSWS),
                )
                self.assertEqual(
                    flap["churn_service"],
                    int(Service.QSFP_SERVICE.value),
                )
                self.assertEqual(flap["churn_action"], action)
                self.assertEqual(flap["churn_every_sec"], 600)
                self.assertEqual(flap["churn_initial_delay_sec"], 600)
                self.assertEqual(flap["churn_recovery_timeout_sec"], 120)
                self.assertEqual(
                    flap["churn_devices"],
                    fpf_tc40_cont_interface_flaps.ALL_GTSWS,
                )
                self.assertGreaterEqual(
                    (flap["duration_sec"] - flap["churn_initial_delay_sec"])
                    // flap["churn_every_sec"],
                    2,
                )
                self.assertEqual(_params(steps[2])["duration"], 120)

    def test_tc33_uplink_flaps(self):
        self.assertEqual(TC33.name, "fpf_tc33_gtsw_stsw_links_down")
        self.assertEqual(TC33_FLAP_SEC, 900)
        self.assertEqual(TC33_LONGEVITY_SEC, 300)
        self.assertEqual(len(TC33.playbooks), 2)
        _longevity_carries_v2_stable_check_set(TC33, self, vf_grouped=True)
        _assert_recovered_baseline_qualification(TC33, self)
        # tc33 intentionally flaps ALL gtsw001 STSW uplinks via the spine glob —
        # no exact host scoping.
        flap_params = next(
            _params(step)
            for step in _steps(TC33.playbooks[0])
            if _params(step).get("custom_step_name") == "fpf_rapid_flap_lldp"
        )
        self.assertIsNone(flap_params["neighbor_hosts"])
        self.assertEqual(flap_params["neighbor_pattern"], UPLINK_NEIGHBOR_PATTERN)

    def test_tc33_disrupt_is_traffic_agnostic_safety_window(self):
        disrupt = TC33.playbooks[0]
        params = [_params(step) for step in _steps(disrupt)]
        custom_names = [p.get("custom_step_name") for p in params]
        self.assertEqual(custom_names[0], "fpf_up_port_baseline")
        self.assertIn("fpf_rapid_flap_lldp", custom_names)
        self.assertEqual(params[-1]["duration"], 120)

        names = {check.name for check in disrupt.postchecks or []}
        self.assertIn(CheckName.SYSTEMCTL_ACTIVE_STATE_CHECK, names)
        self.assertIn(CheckName.UNCLEAN_EXIT_CHECK, names)
        self.assertIn(CheckName.DEVICE_CORE_DUMPS_CHECK, names)
        self.assertNotIn(CheckName.FPF_HOST_SPRAY_CHECK, names)
        ids = _check_ids(disrupt)
        self.assertFalse(any("convergence" in check_id for check_id in ids))

        longevity_params = [_params(step) for step in _steps(TC33.playbooks[1])]
        longevity_names = [p.get("custom_step_name") for p in longevity_params]
        self.assertEqual(longevity_names[0], "fpf_ensure_traffic")
        self.assertEqual(longevity_names[-1], "fpf_up_port_baseline")
        self.assertEqual(longevity_params[-1]["action"], "verify")

    def test_tc42_to_tc44_flap_all_eight_gtsws_and_split_disrupt_longevity(self):
        cases = (
            fpf_tc42_cont_flaps_wedge_restart.TEST_CONFIG,
            fpf_tc43_cont_flaps_bgp_restart.TEST_CONFIG,
            fpf_tc44_cont_flaps_fsdb_restart.TEST_CONFIG,
        )
        for config in cases:
            with self.subTest(config=config.name):
                self.assertEqual(len(config.playbooks), 2)
                disrupt, longevity = config.playbooks
                params = [_params(step) for step in _steps(disrupt)]
                flap = next(
                    p
                    for p in params
                    if p.get("custom_step_name") == "fpf_multi_gtsw_rapid_flap"
                )
                self.assertEqual(flap["gtsws"], fpf_tc40_cont_interface_flaps.ALL_GTSWS)
                self.assertEqual(
                    flap["expected_interfaces"],
                    fpf_tc40_cont_interface_flaps.FLAP_INTERFACES,
                )
                self.assertEqual(len(flap["gtsws"]), 8)
                self.assertEqual(len(flap["expected_interfaces"]), 4)
                self.assertEqual(flap["duration_sec"], 300)
                self.assertEqual(flap["down_time_sec"], 7.0)
                self.assertEqual(flap["up_time_sec"], 7.0)
                self.assertEqual(flap["churn_every_sec"], 120)
                self.assertEqual(params[-1]["duration"], 120)

                names = {check.name for check in disrupt.postchecks or []}
                self.assertIn(CheckName.SYSTEMCTL_ACTIVE_STATE_CHECK, names)
                self.assertIn(CheckName.UNCLEAN_EXIT_CHECK, names)
                self.assertIn(CheckName.DEVICE_CORE_DUMPS_CHECK, names)
                self.assertNotIn(CheckName.FPF_HOST_SPRAY_CHECK, names)

                disrupt_bgp = [
                    check
                    for check in disrupt.postchecks or []
                    if check.name == CheckName.FPF_BGP_RIB_CONVERGENCE_CHECK
                ]
                self.assertEqual(len(disrupt_bgp), 8)
                self.assertTrue(
                    all(_check_params(check)["informational"] for check in disrupt_bgp)
                )

                longevity_params = [_params(step) for step in _steps(longevity)]
                longevity_names = [p.get("custom_step_name") for p in longevity_params]
                self.assertEqual(longevity_names[0], "fpf_ensure_traffic")
                self.assertEqual(longevity_names[-1], "fpf_up_port_baseline")
                self.assertEqual(
                    longevity_params[-1]["devices"],
                    fpf_tc40_cont_interface_flaps.ALL_GTSWS,
                )
                recovered_anchor = longevity_names.index(
                    "record_fpf_recovered_baseline_time"
                )
                self.assertGreater(recovered_anchor, 0)
                self.assertEqual(
                    longevity_params[recovered_anchor + 1]["duration"], 120
                )
                self.assertEqual(
                    longevity_params[recovered_anchor + 2]["duration"], 300
                )
                longevity_bgp = [
                    check
                    for check in longevity.postchecks or []
                    if check.name == CheckName.FPF_BGP_RIB_CONVERGENCE_CHECK
                ]
                self.assertEqual(len(longevity_bgp), 8)
                for check in longevity_bgp:
                    check_params = _check_params(check)
                    self.assertNotIn("informational", check_params)
                    self.assertEqual(
                        check_params.get("stability_mode", "strict"), "strict"
                    )
                    self.assertTrue(check_params["require_final_exact"])

    def test_tc42_retries_final_cleanup_after_wedge_agent_readiness(self):
        params = next(
            _params(step)
            for step in _steps(
                fpf_tc42_cont_flaps_wedge_restart.TEST_CONFIG.playbooks[0]
            )
            if _params(step).get("custom_step_name") == "fpf_multi_gtsw_rapid_flap"
        )
        self.assertEqual(params["final_up_timeout_sec"], 60)
        self.assertTrue(params["retry_final_cleanup_after_churn"])
        self.assertEqual(params["final_cleanup_service_recovery_timeout_sec"], 120)
        self.assertEqual(params["final_cleanup_retry_timeout_sec"], 120)

    def test_tc55_reboot_drained_then_explicit_undrain_recovery(self):
        config = fpf_tc55_gtsw_device_reboot.TEST_CONFIG
        self.assertEqual(len(config.playbooks), 2)
        disrupt, recovery = config.playbooks
        self.assertEqual(
            recovery.name,
            "fpf_tc55_gtsw_device_reboot_recovery_undrain",
        )
        disrupt_ids = _check_ids(disrupt)
        self.assertIn("gtsw_reboot_drained_state", disrupt_ids)
        self.assertIn("gtsw_reboot_drained_traffic", disrupt_ids)
        self.assertNotIn("fpf_hrt_postcheck", disrupt_ids)

        recovery_steps = _steps(recovery)
        undrain_index = next(
            i
            for i, step in enumerate(recovery_steps)
            if _params(step).get("custom_step_name") == "fpf_drain_interface"
            and not _params(step)["is_drain"]
        )
        ensure_index = next(
            i
            for i, step in enumerate(recovery_steps)
            if _params(step).get("custom_step_name") == "fpf_ensure_traffic"
        )
        verify_index = next(
            i
            for i, step in enumerate(recovery_steps)
            if _params(step).get("custom_step_name") == "fpf_up_port_baseline"
            and _params(step)["action"] == "verify"
        )
        self.assertLess(undrain_index, ensure_index)
        self.assertLess(ensure_index, verify_index)
        self.assertIn(
            300,
            [
                _params(step)["duration"]
                for step in recovery_steps
                if step.name == StepName.LONGEVITY_STEP
            ],
        )

    def test_tc32_and_tc33_target_different_neighbor_classes(self):
        """Downlinks use an exact GPU host; uplinks use the STSW glob."""
        tc32_params = _params(_steps(TC32.playbooks[0])[0])
        tc33_params = next(
            _params(step)
            for step in _steps(TC33.playbooks[0])
            if _params(step).get("custom_step_name") == "fpf_rapid_flap_lldp"
        )
        self.assertEqual(tc32_params["neighbor_hosts"], [GPU_HOSTS[0]])
        self.assertIsNone(tc32_params["neighbor_pattern"])
        self.assertIsNone(tc33_params["neighbor_hosts"])
        self.assertEqual(tc33_params["neighbor_pattern"], UPLINK_NEIGHBOR_PATTERN)


class TestStswDrainReinjectConfigs(unittest.TestCase):
    def test_tc35_undrain_step_ordering_and_base_community(self):
        self.assertEqual(TC35.name, "fpf_tc35_stsw_undrain_reinject")
        self.assertIn("fpf", TC35.tags or [])
        self.assertEqual(len(TC35.playbooks), 1)
        self.assertEqual(
            TC35.playbooks[0].name,
            "fpf_tc35_stsw_undrain_reinject_longevity",
        )
        self.assertTrue(TC35.playbooks[0].postchecks)
        self.assertEqual(TC35_LONGEVITY_SEC, 300)

        steps = _steps(TC35.playbooks[0])
        custom = [_params(step) for step in steps if step.name == StepName.CUSTOM_STEP]
        drain_indices = [
            i
            for i, params in enumerate(custom)
            if params.get("custom_step_name") == "fpf_drain_interface"
        ]
        self.assertEqual([custom[i]["is_drain"] for i in drain_indices], [True, False])
        gates = [
            params
            for params in custom
            if params.get("custom_step_name") == "fpf_verify_disruption"
        ]
        self.assertEqual([params["expect_drained"] for params in gates], [True, False])
        self.assertTrue(all(params["fail_if_ineffective"] for params in gates))

        injections = [
            _params(step)
            for step in steps
            if step.name == StepName.FPF_BGP_PREFIX_INJECTION_STEP
        ]
        self.assertEqual(len(injections), 4)
        drain_injections, live_injections = injections[:2], injections[2:]
        self.assertTrue(
            all(
                params["extra_communities"] == ["65446:10"]
                for params in drain_injections
            )
        )
        self.assertEqual(
            {params["prefix_base"] for params in live_injections},
            {"5000:dd::/64", "5000:ee::/64"},
        )
        for params in live_injections:
            self.assertNotIn("extra_communities", params)
            self.assertEqual(params["community_list"], "stsw")
            self.assertEqual(params["count"], 1000)
        durations = [
            _params(step)["duration"]
            for step in steps
            if step.name == StepName.LONGEVITY_STEP
        ]
        self.assertGreaterEqual(durations.count(300), 3)
        ensure_index = next(
            i
            for i, params in enumerate(custom)
            if params.get("custom_step_name") == "fpf_ensure_traffic"
        )
        self.assertGreater(ensure_index, drain_indices[-1])


if __name__ == "__main__":
    unittest.main()
