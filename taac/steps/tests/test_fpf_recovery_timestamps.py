# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe

import time
import typing as t
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from neteng.test_infra.dne.taac.constants import TestDevice, TestTopology
from taac.internal.steps.custom_step import CustomStep
from taac.libs.fpf.fpf_collector_registry import (
    clear_all,
    get_disruption_time,
    get_drain_mutation,
    get_recovery_completion_time,
    get_recovery_start_time,
    mark_drain_mutation,
    set_disruption_time,
)
from taac.libs.parameter_evaluator import ParameterEvaluator
from taac.test_as_a_config.types import Step, TestConfig


def _make_custom_step() -> CustomStep:
    device = MagicMock(spec=TestDevice)
    device.name = "gtsw001.l1002.c087.mwg2"
    custom_step = CustomStep(
        name="step",
        device=device,
        topology=MagicMock(spec=TestTopology),
        test_case_results=[],
        test_config=MagicMock(spec=TestConfig),
        test_case_name="case",
        test_case_start_time=time.time(),
        parameter_evaluator=MagicMock(spec=ParameterEvaluator),
        step=MagicMock(spec=Step),
    )
    custom_step.hostname = device.name
    custom_step.driver = AsyncMock()
    custom_step.logger = MagicMock()
    return custom_step


class TestFpfRecoveryTimestamps(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        clear_all()

    def tearDown(self) -> None:
        clear_all()

    async def test_cleanup_then_no_marker_restore_preserves_recovery(self) -> None:
        custom_step = _make_custom_step()
        driver = t.cast(AsyncMock, custom_step.driver)
        set_disruption_time(50.0)
        mark_drain_mutation("tc17", custom_step.hostname, ["eth1/41/5"])
        driver.get_specific_interface_info.return_value = SimpleNamespace(
            isDrained=False
        )
        params = {
            "interfaces": ["eth1/41/5"],
            "mutation_token": "tc17",
        }

        with patch(
            "neteng.test_infra.dne.taac.internal.steps.custom_step.time.time",
            side_effect=[100.0, 110.0],
        ):
            await custom_step.fpf_conditional_undrain(params)
            # Normal restore path: disrupt cleanup cleared the marker. This no-op
            # must retain cleanup's recovery boundary for the restore postcheck.
            await custom_step.fpf_conditional_undrain(params)

        self.assertEqual(get_recovery_start_time(), 100.0)
        self.assertEqual(get_recovery_completion_time(), 110.0)
        self.assertEqual(get_disruption_time(), 50.0)
        self.assertIsNone(get_drain_mutation("tc17"))
        self.assertEqual(driver.async_undrain_interface.await_count, 1)


if __name__ == "__main__":
    unittest.main()
