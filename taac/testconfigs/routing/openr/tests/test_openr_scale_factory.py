# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
"""Unit tests for the Open/R scale KvStore injection TestConfig factory."""

import json
import unittest

from taac.testconfigs.routing.openr.openr_scale_test_config import (
    create_openr_scale_test_config,
    DEFAULT_LEAVES,
    DEFAULT_SPINES,
    EB02_MGMT_ADDRESS,
    EB04_INBAND_ADDRESS,
    EB04_MGMT_ADDRESS,
    OPENR_SCALE_KVSTORE_INJECTION_TEST_CONFIG,
    SCALE_TESTER_REMOTE_PATH,
)
from taac.health_check.health_check import types as hc_types


def _injection_step_params(config) -> dict:
    """Pull the injection step's params out of the single stage."""
    stage = config.playbooks[0].stages[0]
    return json.loads(stage.steps[0].step_params.json_params)


def _wired_check_names(config) -> set:
    playbook = config.playbooks[0]
    return {
        check.name
        for check in list(playbook.prechecks or ()) + list(playbook.postchecks or ())
    }


class OpenRScaleTestConfigTest(unittest.TestCase):
    def test_topology_defaults_to_the_bbf_representative_fabric(self) -> None:
        """64 spines / 256 leaves, the first BBF site's shape. Spine count is
        what gives a leaf DUT a representative adjacency count; leaf count
        scales the injected key volume."""
        self.assertEqual(64, DEFAULT_SPINES)
        self.assertEqual(256, DEFAULT_LEAVES)
        params = _injection_step_params(OPENR_SCALE_KVSTORE_INJECTION_TEST_CONFIG)
        self.assertEqual(64, params["num_spines"])
        self.assertEqual(256, params["num_leaves"])
        self.assertEqual("leaf", params["dut_role"])

    def test_injection_targets_inband_and_denies_mgmt_addresses(self) -> None:
        """The whole point of the test: the mgmt path is CoPP-policed and drops
        the large adj: keys, so it must be refused rather than silently used."""
        params = _injection_step_params(OPENR_SCALE_KVSTORE_INJECTION_TEST_CONFIG)
        self.assertEqual(EB04_INBAND_ADDRESS, params["dut_host"])
        self.assertEqual(
            [EB04_MGMT_ADDRESS, EB02_MGMT_ADDRESS], params["forbidden_dut_hosts"]
        )
        self.assertNotIn(params["dut_host"], params["forbidden_dut_hosts"])

    def test_binary_presence_is_verified_and_never_staged(self) -> None:
        params = _injection_step_params(OPENR_SCALE_KVSTORE_INJECTION_TEST_CONFIG)
        self.assertEqual(SCALE_TESTER_REMOTE_PATH, params["remote_path"])
        self.assertTrue(params["require_binary_present"])

    def test_dut_and_helper_endpoints(self) -> None:
        config = OPENR_SCALE_KVSTORE_INJECTION_TEST_CONFIG
        self.assertEqual("dne.test", config.basset_pool)
        self.assertEqual(
            {"eb04.lab.ash6": True, "eb02.lab.ash6": False},
            {endpoint.name: endpoint.dut for endpoint in config.endpoints},
        )

    def test_teardown_stops_the_injector_without_removing_the_binary(self) -> None:
        """The binary is shared testbed foundation, so teardown must not delete
        it -- only stop a process left behind by a failed run."""
        teardown_tasks = list(
            OPENR_SCALE_KVSTORE_INJECTION_TEST_CONFIG.teardown_tasks or []
        )
        self.assertEqual(1, len(teardown_tasks))
        cmds = json.loads(str(teardown_tasks[0].params.json_params))["cmds"]
        # The `bash` prefix is load-bearing: the driver hands commands to the EOS
        # CLI, which rejects a bare `pkill`. Combined with `|| true` that failure
        # is invisible, so run bbc76352491543cdb9b88d0b655d851c reported a passing
        # teardown that killed nothing.
        self.assertEqual([f"bash pkill -f {SCALE_TESTER_REMOTE_PATH} || true"], cmds)
        self.assertNotIn("rm", " ".join(cmds))

    def test_skip_teardown_leaves_no_tasks(self) -> None:
        config = create_openr_scale_test_config(skip_teardown=True)
        self.assertEqual([], list(config.teardown_tasks or []))

    def test_the_gate_is_measured_on_the_dut(self) -> None:
        """The helper runs Open/R too, so the counters must be read from the
        device whose KvStore is under test."""
        params = _injection_step_params(OPENR_SCALE_KVSTORE_INJECTION_TEST_CONFIG)
        self.assertEqual("eb04.lab.ash6", params["dut_name"])
        self.assertEqual("eb02.lab.ash6", params["helper_name"])

    def test_open_r_is_not_restarted(self) -> None:
        """A restart does not give the KvStore a clean start on a two-node rig --
        the peer holds the same infinite-TTL keys and full-syncs them back -- and
        that flood lands in the receive counter the gate measures."""
        params = _injection_step_params(OPENR_SCALE_KVSTORE_INJECTION_TEST_CONFIG)
        self.assertFalse(params["restart_openr"])

    def test_route_computation_is_not_exercised(self) -> None:
        """The contract is KvStore key presence. Waiting on route computation
        would fail the run for a reason the test does not qualify."""
        params = _injection_step_params(OPENR_SCALE_KVSTORE_INJECTION_TEST_CONFIG)
        self.assertFalse(params["verify_routes"])

    def test_no_gating_check_is_inert_on_eos(self) -> None:
        """Both boxes run EOS. SYSTEMCTL_ACTIVE_STATE_CHECK is
        OPERATING_SYSTEMS = ["FBOSS"], so wiring it here would record a pass for a
        check that cannot fire -- the same vacuous-gate failure this test was
        rewritten to remove. Open/R liveness is carried by the counter read in
        the injection step, which goes over Open/R Thrift."""
        wired = _wired_check_names(OPENR_SCALE_KVSTORE_INJECTION_TEST_CONFIG)
        self.assertNotIn(hc_types.CheckName.SYSTEMCTL_ACTIVE_STATE_CHECK, wired)

    def test_resource_ceilings_do_not_gate_the_run(self) -> None:
        """A 4,068 key-value injection legitimately spikes Open/R CPU while flooding
        converges; failing on an arbitrary ceiling would pre-empt the result this
        test exists to produce."""
        wired = _wired_check_names(OPENR_SCALE_KVSTORE_INJECTION_TEST_CONFIG)
        self.assertNotIn(hc_types.CheckName.CPU_UTILIZATION_CHECK, wired)
        self.assertNotIn(hc_types.CheckName.MEMORY_UTILIZATION_CHECK, wired)

    def test_the_injection_step_carries_the_whole_assertion(self) -> None:
        """The gate lives in the step, which brackets the injector with counter
        reads, so the stage needs no separate validation step and the playbook
        needs no postcheck."""
        playbook = OPENR_SCALE_KVSTORE_INJECTION_TEST_CONFIG.playbooks[0]
        self.assertEqual(1, len(playbook.stages[0].steps))
        self.assertEqual([], list(playbook.postchecks or ()))
