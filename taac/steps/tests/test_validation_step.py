# Copyright (c) Meta Platforms, Inc. and affiliates.

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

from later.unittest import TestCase
from taac.constants import (
    TestCaseFailure,
    TestDevice,
    TestTopology,
)
from taac.libs.parameter_evaluator import ParameterEvaluator
from taac.steps import step_definitions
from taac.steps.step_definitions import (
    create_validation_step,
    ValidationStep,
)
from taac.health_check.health_check import types as hc_types
from taac.test_as_a_config import types as taac_types


class ValidationStepTest(TestCase):
    def setUp(self) -> None:
        device = MagicMock(spec=TestDevice)
        device.name = "dut.example.com"
        self.parameter_evaluator = MagicMock(spec=ParameterEvaluator)
        self.parameter_evaluator.evaluate.return_value = {}
        self.step = ValidationStep(
            name="validation",
            device=device,
            topology=MagicMock(spec=TestTopology),
            test_case_results=[],
            test_config=MagicMock(spec=taac_types.TestConfig),
            test_case_name="test_case",
            test_case_start_time=time.time(),
            parameter_evaluator=self.parameter_evaluator,
            step=MagicMock(spec=taac_types.Step),
        )
        self.step.ixia = MagicMock()

    async def test_mid_test_failure_can_stop_workload(self) -> None:
        check = taac_types.PointInTimeHealthCheck(
            name=hc_types.CheckName.IXIA_PACKET_LOSS_CHECK
        )
        input_data = taac_types.ValidationInput(
            point_in_time_checks=[check],
            stage=taac_types.ValidationStage.MID_TEST,
        )
        result = hc_types.HealthCheckResult(
            name=hc_types.CheckName.IXIA_PACKET_LOSS_CHECK,
            status=hc_types.HealthCheckStatus.FAIL,
            message="packet loss",
        )
        check_impl = step_definitions.NAME_TO_POINT_IN_TIME_HEALTH_CHECK[check.name]

        with (
            patch.object(check_impl, "run_wrapper", new=AsyncMock(return_value=result)),
            patch.object(
                step_definitions,
                "async_write_test_result",
                new=AsyncMock(return_value=MagicMock()),
            ),
            patch.object(step_definitions, "log_results_table"),
        ):
            with self.assertRaisesRegex(TestCaseFailure, "failed"):
                await self.step.run(input_data, {"fail_on_failure": True})

    def test_factory_encodes_fatal_failure_without_starting_traffic(self) -> None:
        definition = create_validation_step(
            point_in_time_checks=[
                taac_types.PointInTimeHealthCheck(
                    name=hc_types.CheckName.IXIA_PACKET_LOSS_CHECK
                )
            ],
            start_traffic=False,
            fail_on_failure=True,
        )

        self.assertIsNotNone(definition.step_params)
        params = json.loads(definition.step_params.json_params or "{}")
        self.assertTrue(params["skip_start_traffic"])
        self.assertTrue(params["fail_on_failure"])
