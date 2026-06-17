# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
import asyncio
import time
import unittest
from unittest.mock import AsyncMock, MagicMock

from neteng.test_infra.dne.taac.constants import TestDevice, TestTopology
from taac.libs.parameter_evaluator import ParameterEvaluator
from taac.steps.step_definitions import LongevityStep
from taac.test_as_a_config import types as taac_types


class TestLongevityStep(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.name = "test_longevity"
        self.device = MagicMock(spec=TestDevice)
        self.device.name = "test_device.p001.f01.snc1"

        attributes_mock = MagicMock()
        attributes_mock.operating_system = "FBOSS"
        attributes_mock.role = ""
        attributes_mock.device_name = "test_device"
        attributes_mock.hardware = ""
        attributes_mock.ai_zone = ""
        self.device.attributes = attributes_mock

        self.topology = MagicMock(spec=TestTopology)
        self.test_case_results = []
        self.test_config = MagicMock(spec=taac_types.TestConfig)
        self.test_case_name = "test_case"
        self.test_case_start_time = time.time()
        self.parameter_evaluator = MagicMock(spec=ParameterEvaluator)
        self.step_mock = MagicMock(spec=taac_types.Step)

        self.longevity_step = LongevityStep(
            name=self.name,
            device=self.device,
            topology=self.topology,
            test_case_results=self.test_case_results,
            test_config=self.test_config,
            test_case_name=self.test_case_name,
            test_case_start_time=self.test_case_start_time,
            parameter_evaluator=self.parameter_evaluator,
            step=self.step_mock,
        )

        self.driver_mock = AsyncMock()
        self.longevity_step.driver = self.driver_mock

    def test_step_name(self):
        """Test that STEP_NAME is correctly set."""
        self.assertEqual(LongevityStep.STEP_NAME, taac_types.StepName.LONGEVITY_STEP)

    async def test_run_with_zero_duration(self):
        """Test that run() handles duration=0 correctly (no sleep)."""
        input_data = taac_types.BaseInput()
        params = {"duration": 0}

        # Monkeypatch asyncio.sleep and time.time on the imported module
        import neteng.test_infra.dne.taac.steps.step_definitions as longevity_mod

        original_sleep = asyncio.sleep
        original_time = time.time
        sleep_calls = []

        async def fake_sleep(duration):
            sleep_calls.append(duration)

        time_counter = [0.0]

        def fake_time():
            return time_counter[0]

        longevity_mod.asyncio.sleep = fake_sleep
        longevity_mod.time.time = fake_time
        try:
            await self.longevity_step.run(input_data, params)
        finally:
            longevity_mod.asyncio.sleep = original_sleep
            longevity_mod.time.time = original_time

        # Should not sleep at all since duration=0
        self.assertEqual(len(sleep_calls), 0)

    async def test_run_sleeps_for_configured_duration(self):
        """Test that run() sleeps in a loop until duration elapsed."""
        input_data = taac_types.BaseInput()
        params = {"duration": 120}

        import neteng.test_infra.dne.taac.steps.step_definitions as longevity_mod

        original_sleep = asyncio.sleep
        original_time = time.time
        sleep_calls = []
        time_counter = [0.0]

        async def fake_sleep(duration):
            sleep_calls.append(duration)
            time_counter[0] += duration

        def fake_time():
            return time_counter[0]

        longevity_mod.asyncio.sleep = fake_sleep
        longevity_mod.time.time = fake_time
        try:
            await self.longevity_step.run(input_data, params)
        finally:
            longevity_mod.asyncio.sleep = original_sleep
            longevity_mod.time.time = original_time

        # With duration=120, should sleep twice (60 + 60)
        self.assertEqual(len(sleep_calls), 2)
        self.assertEqual(sleep_calls[0], 60)
        self.assertEqual(sleep_calls[1], 60)

    async def test_run_sleeps_short_duration(self):
        """Test that run() uses min(60, remaining) for sleep time."""
        input_data = taac_types.BaseInput()
        params = {"duration": 30}

        import neteng.test_infra.dne.taac.steps.step_definitions as longevity_mod

        original_sleep = asyncio.sleep
        original_time = time.time
        sleep_calls = []
        time_counter = [0.0]

        async def fake_sleep(duration):
            sleep_calls.append(duration)
            time_counter[0] += duration

        def fake_time():
            return time_counter[0]

        longevity_mod.asyncio.sleep = fake_sleep
        longevity_mod.time.time = fake_time
        try:
            await self.longevity_step.run(input_data, params)
        finally:
            longevity_mod.asyncio.sleep = original_sleep
            longevity_mod.time.time = original_time

        # With duration=30, should sleep once with min(60, 30) = 30
        self.assertEqual(len(sleep_calls), 1)
        self.assertEqual(sleep_calls[0], 30)
