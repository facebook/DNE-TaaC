# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

import json
import unittest

from taac.testconfigs.routing.openr.openr_scale_ipv4_ipv6_prefix_injection_test_config import (
    OPENR_SCALE_IPV4_IPV6_PREFIX_INJECTION_TEST_CONFIG,
)
from taac.testconfigs.routing.openr.openr_scale_test_config import (
    EB02_MGMT_ADDRESS,
    EB04_INBAND_ADDRESS,
    EB04_MGMT_ADDRESS,
)


def _step_params(index: int) -> dict:
    step = (
        OPENR_SCALE_IPV4_IPV6_PREFIX_INJECTION_TEST_CONFIG.playbooks[0]
        .stages[0]
        .steps[index]
    )
    if step.step_params is None or step.step_params.json_params is None:
        raise AssertionError("custom step is missing serialized parameters")
    return json.loads(step.step_params.json_params)


class OpenRScaleIpv4Ipv6PrefixInjectionFactoryTest(unittest.TestCase):
    def test_full_scale_dual_family_contract(self) -> None:
        injection = _step_params(1)
        validation = _step_params(3)

        self.assertEqual(64, injection["num_spines"])
        self.assertEqual(256, injection["num_leaves"])
        self.assertEqual(11, injection["num_prefixes_per_node"])
        self.assertTrue(injection["generate_ipv4_prefixes"])
        self.assertEqual(7797, injection["expected_updated_key_vals_delta"])
        self.assertEqual([20250903], validation["seeds"])
        self.assertTrue(validation["generate_ipv4_prefixes"])
        self.assertTrue(validation["exact_scope"])

    def test_injection_is_inband_only(self) -> None:
        injection = _step_params(1)

        self.assertEqual(EB04_INBAND_ADDRESS, injection["dut_host"])
        self.assertEqual(
            [EB04_MGMT_ADDRESS, EB02_MGMT_ADDRESS],
            injection["forbidden_dut_hosts"],
        )

    def test_setup_and_teardown_both_isolate_the_scale_namespace(self) -> None:
        config = OPENR_SCALE_IPV4_IPV6_PREFIX_INJECTION_TEST_CONFIG
        setup = list(config.setup_tasks or ())
        teardown = list(config.teardown_tasks or ())

        self.assertEqual(1, len(setup))
        self.assertEqual(1, len(teardown))
        self.assertEqual("openr_scale_isolation", setup[0].task_name)
        self.assertEqual(setup[0], teardown[0])

    def test_lifecycle_identity_is_specific_to_prefix_injection(self) -> None:
        config = OPENR_SCALE_IPV4_IPV6_PREFIX_INJECTION_TEST_CONFIG

        self.assertEqual("OPENR_SCALE_IPV4_IPV6_PREFIX_INJECTION", config.name)
        self.assertEqual(
            "openr_scale_ipv4_ipv6_prefix_injection_playbook",
            config.playbooks[0].name,
        )
