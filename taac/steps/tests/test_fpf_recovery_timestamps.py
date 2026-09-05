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
    set_recovery_completion_time,
    set_recovery_start_time,
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
            # A completed owned restore cleared the marker. A repeated no-op
            # must retain the original recovery boundary for the postcheck.
            await custom_step.fpf_conditional_undrain(params)

        self.assertEqual(get_recovery_start_time(), 100.0)
        self.assertEqual(get_recovery_completion_time(), 110.0)
        self.assertEqual(get_disruption_time(), 50.0)
        self.assertIsNone(get_drain_mutation("tc17"))
        self.assertEqual(driver.async_undrain_interface.await_count, 1)

    async def test_interface_cleanup_does_not_reanchor_recovery(self) -> None:
        custom_step = _make_custom_step()
        driver = t.cast(AsyncMock, custom_step.driver)
        driver.async_get_all_interfaces_admin_status.return_value = {"eth1/41/5": True}
        set_recovery_start_time(100.0)
        set_recovery_completion_time(110.0)

        await custom_step.fpf_set_interface_admin(
            {
                "interfaces": ["eth1/41/5"],
                "is_enable": True,
                "best_effort": True,
                "record_event_time": False,
            }
        )

        self.assertEqual(get_recovery_start_time(), 100.0)
        self.assertEqual(get_recovery_completion_time(), 110.0)
        driver.async_thrift_disable_enable_interfaces.assert_awaited_once()

    async def test_interface_cleanup_failure_is_best_effort(self) -> None:
        custom_step = _make_custom_step()
        driver = t.cast(AsyncMock, custom_step.driver)
        driver.async_thrift_disable_enable_interfaces.side_effect = RuntimeError(
            "enable failed"
        )

        await custom_step.fpf_set_interface_admin(
            {
                "interfaces": ["eth1/41/5"],
                "is_enable": True,
                "best_effort": True,
                "record_event_time": False,
            }
        )

        t.cast(MagicMock, custom_step.logger.error).assert_called_once()
        self.assertIn(
            "continuing cleanup",
            t.cast(MagicMock, custom_step.logger.error).call_args.args[0],
        )

    async def test_best_effort_cleanup_cannot_record_unmatched_recovery(self) -> None:
        custom_step = _make_custom_step()
        driver = t.cast(AsyncMock, custom_step.driver)
        driver.async_thrift_disable_enable_interfaces.side_effect = RuntimeError(
            "enable failed"
        )

        await custom_step.fpf_set_interface_admin(
            {
                "interfaces": ["eth1/41/5"],
                "is_enable": True,
                "best_effort": True,
                "record_event_time": True,
            }
        )

        self.assertEqual(get_recovery_start_time(), 0.0)
        self.assertEqual(get_recovery_completion_time(), 0.0)
        self.assertTrue(
            any(
                "disabling event-time recording" in str(call)
                for call in t.cast(MagicMock, custom_step.logger.warning).call_args_list
            )
        )


if __name__ == "__main__":
    unittest.main()
