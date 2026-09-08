# Copyright (c) Meta Platforms, Inc. and affiliates.
"""Unit tests for create_systemctl_active_state_check's parameter variants."""

import json
import unittest

from taac.health_check.health_check import types as hc_types
from taac.health_checks.healthcheck_definitions import (
    create_systemctl_active_state_check,
)


class CreateSystemctlActiveStateCheckTest(unittest.TestCase):
    def _params(self, check):
        return json.loads(check.check_params.json_params)

    def test_bare_default_has_no_params(self):
        check = create_systemctl_active_state_check()
        self.assertIsNone(check.check_params)
        self.assertIsNone(check.input_json)

    def test_services_json_only(self):
        check = create_systemctl_active_state_check(services_json=["bgpd", "fsdb"])
        self.assertEqual(self._params(check), {"services": ["bgpd", "fsdb"]})

    def test_expected_restarted_services_with_services_json(self):
        check = create_systemctl_active_state_check(
            services_json=["bgpd", "fsdb", "fboss_sw_agent"],
            expected_restarted_services=["fboss_sw_agent"],
        )
        self.assertEqual(
            self._params(check),
            {
                "services": ["bgpd", "fsdb", "fboss_sw_agent"],
                "expected_restarted_services": ["fboss_sw_agent"],
            },
        )

    def test_expected_restarted_services_alone(self):
        check = create_systemctl_active_state_check(
            expected_restarted_services=["fboss_sw_agent"]
        )
        self.assertEqual(
            self._params(check), {"expected_restarted_services": ["fboss_sw_agent"]}
        )

    def test_expected_restarted_services_rejects_thrift_services_variant(self):
        with self.assertRaises(ValueError):
            create_systemctl_active_state_check(
                services=[hc_types.Service.BGPD],
                expected_restarted_services=["bgpd"],
            )

    def test_services_and_services_json_are_mutually_exclusive(self):
        with self.assertRaises(ValueError):
            create_systemctl_active_state_check(
                services=[hc_types.Service.BGPD], services_json=["bgpd"]
            )
