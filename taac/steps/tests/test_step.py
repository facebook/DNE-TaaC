# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from neteng.test_infra.dne.taac.constants import TestDevice, TestTopology
from taac.libs.parameter_evaluator import ParameterEvaluator
from taac.steps.step import Step
from taac.test_as_a_config import types as taac_types


class ConcreteStep(Step):
    STEP_NAME = taac_types.StepName.LONGEVITY_STEP

    async def run(self, input, params):
        pass


MODULE = "neteng.test_infra.dne.taac.steps.step"


class StepEverpasteFallbackTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.device = MagicMock(spec=TestDevice)
        self.device.name = "test_device.p001.f01.snc1"

        attributes_mock = MagicMock()
        attributes_mock.operating_system = "FBOSS"
        self.device.attributes = attributes_mock

        self.topology = MagicMock(spec=TestTopology)
        self.test_case_results = []
        self.test_config = MagicMock(spec=taac_types.TestConfig)
        self.parameter_evaluator = MagicMock(spec=ParameterEvaluator)
        self.step_mock = MagicMock(spec=taac_types.Step)

        self.logger_mock = MagicMock()

        self.step = ConcreteStep(
            name="test_step",
            device=self.device,
            topology=self.topology,
            test_case_results=self.test_case_results,
            test_config=self.test_config,
            test_case_name="test_case",
            test_case_start_time=time.time(),
            parameter_evaluator=self.parameter_evaluator,
            step=self.step_mock,
            logger=self.logger_mock,
        )

    @patch(f"{MODULE}.log_step_info")
    @patch(f"{MODULE}.async_everpaste_if_needed", new_callable=AsyncMock)
    async def test_run_continues_when_everpaste_fails_during_setup_logging(
        self, mock_everpaste, mock_log_step
    ):
        mock_everpaste.side_effect = Exception("EverPaste handle cannot be null")
        self.step.setUp = AsyncMock()
        self.step.run = AsyncMock()

        await self.step._run(taac_types.BaseInput(), {"key": "value"})

        self.step.setUp.assert_awaited_once()
        self.step.run.assert_awaited_once()

    @patch(f"{MODULE}.log_step_info")
    @patch(f"{MODULE}.async_everpaste_if_needed", new_callable=AsyncMock)
    async def test_run_logs_warning_when_everpaste_fails_during_setup_logging(
        self, mock_everpaste, mock_log_step
    ):
        mock_everpaste.side_effect = Exception("EverPaste handle cannot be null")
        self.step.setUp = AsyncMock()
        self.step.run = AsyncMock()

        await self.step._run(taac_types.BaseInput(), {"key": "value"})

        self.step.logger.warning.assert_called_once()
        warning_msg = self.step.logger.warning.call_args[0][0]
        self.assertIn("Failed to everpaste step input", warning_msg)
        self.assertIn("EverPaste handle cannot be null", warning_msg)

    @patch(f"{MODULE}.log_step_info")
    @patch(f"{MODULE}.async_everpaste_if_needed", new_callable=AsyncMock)
    async def test_run_completes_normally_when_everpaste_succeeds(
        self, mock_everpaste, mock_log_step
    ):
        mock_everpaste.return_value = "everpasted content"
        self.step.setUp = AsyncMock()
        self.step.run = AsyncMock()

        await self.step._run(taac_types.BaseInput(), {"key": "value"})

        self.step.setUp.assert_awaited_once()
        self.step.run.assert_awaited_once()

    @patch(f"{MODULE}.async_write_test_result", new_callable=AsyncMock)
    @patch(f"{MODULE}.async_get_fburl", new_callable=AsyncMock)
    @patch(f"{MODULE}.async_everpaste_str", new_callable=AsyncMock)
    @patch(f"{MODULE}.log_step_info")
    @patch(f"{MODULE}.async_everpaste_if_needed", new_callable=AsyncMock)
    async def test_failure_recorded_when_everpaste_fails_during_failure_reporting(
        self,
        mock_everpaste_if_needed,
        mock_log_step,
        mock_everpaste_str,
        mock_get_fburl,
        mock_write_test_result,
    ):
        mock_everpaste_if_needed.return_value = "input logged"
        long_error = "x" * 200
        step_error = RuntimeError(long_error)
        self.step.setUp = AsyncMock()
        self.step.run = AsyncMock(side_effect=step_error)
        mock_everpaste_str.side_effect = Exception("EverPaste handle cannot be null")
        mock_write_test_result.return_value = MagicMock()

        with self.assertRaises(RuntimeError) as ctx:
            await self.step._run(taac_types.BaseInput(), {})

        self.assertIs(ctx.exception, step_error)
        mock_write_test_result.assert_awaited_once()
        self.assertEqual(len(self.test_case_results), 1)

    @patch(f"{MODULE}.async_write_test_result", new_callable=AsyncMock)
    @patch(f"{MODULE}.async_get_fburl", new_callable=AsyncMock)
    @patch(f"{MODULE}.async_everpaste_str", new_callable=AsyncMock)
    @patch(f"{MODULE}.log_step_info")
    @patch(f"{MODULE}.async_everpaste_if_needed", new_callable=AsyncMock)
    async def test_failure_uses_raw_message_when_everpaste_fails(
        self,
        mock_everpaste_if_needed,
        mock_log_step,
        mock_everpaste_str,
        mock_get_fburl,
        mock_write_test_result,
    ):
        mock_everpaste_if_needed.return_value = "input logged"
        long_error = "x" * 200
        self.step.setUp = AsyncMock()
        self.step.run = AsyncMock(side_effect=RuntimeError(long_error))
        mock_everpaste_str.side_effect = Exception("EverPaste handle cannot be null")
        mock_write_test_result.return_value = MagicMock()

        with self.assertRaises(RuntimeError):
            await self.step._run(taac_types.BaseInput(), {})

        expected_message = (
            f"Step ConcreteStep failed on {self.device.name}: {long_error}"
        )
        actual_message = mock_write_test_result.call_args.kwargs["message"]
        self.assertEqual(actual_message, expected_message)

    @patch(f"{MODULE}.log_step_info")
    @patch(f"{MODULE}.async_everpaste_if_needed", new_callable=AsyncMock)
    async def test_step_input_everpaste_uses_high_threshold(
        self, mock_everpaste, mock_log_step
    ):
        # The step-input debug everpaste must use a high threshold so routine
        # small step inputs (a few hundred chars) are not uploaded to Everpaste
        # on every step — that per-step everpasting was the dominant upload
        # volume in a run.
        mock_everpaste.return_value = "input logged"
        self.step.setUp = AsyncMock()
        self.step.run = AsyncMock()

        await self.step._run(taac_types.BaseInput(), {"key": "value"})

        mock_everpaste.assert_awaited_once()
        # The threshold is the second positional arg to async_everpaste_if_needed.
        self.assertEqual(mock_everpaste.await_args.args[1], 5000)
