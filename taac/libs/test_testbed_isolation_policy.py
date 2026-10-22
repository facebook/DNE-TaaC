# Copyright (c) Meta Platforms, Inc. and affiliates.

import unittest
from unittest.mock import MagicMock

from taac.constants import TESTBED_ISOLATION_BYPASS_TAG
from taac.libs.test_setup_orchestrator import (
    TestSetupOrchestrator,
)
from taac.test_as_a_config import types as taac_types


def _config(tags: list[str] | None = None) -> taac_types.TestConfig:
    return taac_types.TestConfig(
        name="ISOLATION_POLICY_TEST",
        basset_pool="dne.test",
        playbooks=[],
        endpoints=[],
        tags=tags,
    )


class TestTestbedIsolationPolicy(unittest.TestCase):
    def test_policy_tag_skips_isolation_without_runner_flag(self) -> None:
        orchestrator = TestSetupOrchestrator(
            _config([TESTBED_ISOLATION_BYPASS_TAG]),
            MagicMock(),
            skip_testbed_isolation=False,
        )

        self.assertTrue(orchestrator._skip_testbed_isolation)
        self.assertTrue(orchestrator._test_config_skips_testbed_isolation)

    def test_runner_flag_remains_supported(self) -> None:
        orchestrator = TestSetupOrchestrator(
            _config(),
            MagicMock(),
            skip_testbed_isolation=True,
        )

        self.assertTrue(orchestrator._skip_testbed_isolation)
        self.assertFalse(orchestrator._test_config_skips_testbed_isolation)

    def test_normal_config_keeps_isolation_enabled(self) -> None:
        orchestrator = TestSetupOrchestrator(
            _config(),
            MagicMock(),
            skip_testbed_isolation=False,
        )

        self.assertFalse(orchestrator._skip_testbed_isolation)
        self.assertFalse(orchestrator._test_config_skips_testbed_isolation)
