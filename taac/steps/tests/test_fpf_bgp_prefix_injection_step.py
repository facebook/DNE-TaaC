# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from neteng.test_infra.dne.taac.constants import TestDevice, TestTopology
from taac.libs.fpf.inject_bgp_prefixes import COMMUNITY_PRESETS
from taac.libs.parameter_evaluator import ParameterEvaluator
from taac.steps.fpf_bgp_prefix_injection_step import (
    FpfBgpPrefixInjectionStep,
)
from taac.test_as_a_config import types as taac_types


class TestFpfBgpPrefixInjectionStep(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.device = MagicMock(spec=TestDevice)
        self.device.name = "gtsw001.l1002.c087.mwg2"

        attributes_mock = MagicMock()
        attributes_mock.operating_system = "FBOSS"
        self.device.attributes = attributes_mock

        self.step_instance = FpfBgpPrefixInjectionStep(
            name="test_fpf_bgp_prefix_injection",
            device=self.device,
            topology=MagicMock(spec=TestTopology),
            test_case_results=[],
            test_config=MagicMock(spec=taac_types.TestConfig),
            test_case_name="test_case",
            test_case_start_time=time.time(),
            parameter_evaluator=MagicMock(spec=ParameterEvaluator),
            step=MagicMock(spec=taac_types.Step),
        )
        self.step_instance.driver = AsyncMock()

    def test_step_name(self):
        """STEP_NAME is set to FPF_BGP_PREFIX_INJECTION_STEP."""
        self.assertEqual(
            FpfBgpPrefixInjectionStep.STEP_NAME,
            taac_types.StepName.FPF_BGP_PREFIX_INJECTION_STEP,
        )

    @patch(
        "neteng.test_infra.dne.taac.steps.fpf_bgp_prefix_injection_step.FbossSwitchInternal"
    )
    @patch(
        "neteng.test_infra.dne.taac.steps.fpf_bgp_prefix_injection_step.inject_prefixes",
        new_callable=AsyncMock,
    )
    async def test_inject_single_device(self, mock_inject, mock_driver_cls):
        """Inject prefixes on a single device with a community preset."""
        mock_driver_instance = MagicMock()
        mock_driver_cls.return_value = mock_driver_instance

        params = {
            "devices": ["gtsw001.l1002.c087.mwg2"],
            "prefix_base": "5000:dd::/64",
            "count": 4,
            "increment_step": "0:0:1::",
            "community_list": "gtsw",
        }

        input_data = taac_types.BaseInput()
        await self.step_instance.setUp(input_data, params)
        await self.step_instance.run(input_data, params)

        # inject_prefixes should be called once for the single device
        mock_inject.assert_called_once()
        call_args = mock_inject.call_args
        # First arg is the driver, second is the prefix list, third is communities
        self.assertEqual(call_args[0][0], mock_driver_instance)
        self.assertEqual(len(call_args[0][1]), 4)
        self.assertEqual(len(call_args[0][2]), len(COMMUNITY_PRESETS["gtsw"]))

    @patch(
        "neteng.test_infra.dne.taac.steps.fpf_bgp_prefix_injection_step.FbossSwitchInternal"
    )
    @patch(
        "neteng.test_infra.dne.taac.steps.fpf_bgp_prefix_injection_step.inject_prefixes",
        new_callable=AsyncMock,
    )
    async def test_inject_multiple_devices(self, mock_inject, mock_driver_cls):
        """Inject prefixes on multiple devices in parallel."""
        mock_driver_cls.return_value = MagicMock()

        params = {
            "devices": [
                "gtsw001.l1002.c087.mwg2",
                "gtsw002.l1002.c087.mwg2",
                "gtsw003.l1002.c087.mwg2",
            ],
            "prefix_base": "5000:dd::/64",
            "count": 2,
            "community_list": "gtsw",
        }

        input_data = taac_types.BaseInput()
        await self.step_instance.setUp(input_data, params)
        await self.step_instance.run(input_data, params)

        # inject_prefixes should be called once per device
        self.assertEqual(mock_inject.call_count, 3)

    @patch(
        "neteng.test_infra.dne.taac.steps.fpf_bgp_prefix_injection_step.FbossSwitchInternal"
    )
    @patch(
        "neteng.test_infra.dne.taac.steps.fpf_bgp_prefix_injection_step.withdraw_prefixes",
        new_callable=AsyncMock,
    )
    async def test_withdraw_only(self, mock_withdraw, mock_driver_cls):
        """withdraw_only=True calls withdraw_prefixes instead of inject."""
        mock_driver_instance = MagicMock()
        mock_driver_cls.return_value = mock_driver_instance

        params = {
            "devices": ["gtsw001.l1002.c087.mwg2"],
            "prefix_base": "5000:dd::/64",
            "count": 16,
            "community_list": "gtsw",
            "withdraw_only": True,
        }

        input_data = taac_types.BaseInput()
        await self.step_instance.setUp(input_data, params)
        await self.step_instance.run(input_data, params)

        mock_withdraw.assert_called_once()
        call_args = mock_withdraw.call_args
        self.assertEqual(call_args[0][0], mock_driver_instance)
        self.assertEqual(len(call_args[0][1]), 16)

    @patch(
        "neteng.test_infra.dne.taac.steps.fpf_bgp_prefix_injection_step.FbossSwitchInternal"
    )
    @patch(
        "neteng.test_infra.dne.taac.steps.fpf_bgp_prefix_injection_step.inject_prefixes",
        new_callable=AsyncMock,
    )
    async def test_stsw_community_preset(self, mock_inject, mock_driver_cls):
        """The stsw community preset is correctly resolved."""
        mock_driver_cls.return_value = MagicMock()

        params = {
            "devices": ["stsw001.s001.l202.mwg2"],
            "prefix_base": "5000:dd::/64",
            "count": 1,
            "community_list": "stsw",
        }

        input_data = taac_types.BaseInput()
        await self.step_instance.setUp(input_data, params)
        await self.step_instance.run(input_data, params)

        mock_inject.assert_called_once()
        communities = mock_inject.call_args[0][2]
        self.assertEqual(len(communities), len(COMMUNITY_PRESETS["stsw"]))

    @patch(
        "neteng.test_infra.dne.taac.steps.fpf_bgp_prefix_injection_step.FbossSwitchInternal"
    )
    @patch(
        "neteng.test_infra.dne.taac.steps.fpf_bgp_prefix_injection_step.inject_prefixes",
        new_callable=AsyncMock,
    )
    async def test_explicit_communities(self, mock_inject, mock_driver_cls):
        """Explicit communities list is used when community_list is absent."""
        mock_driver_cls.return_value = MagicMock()

        params = {
            "devices": ["gtsw001.l1002.c087.mwg2"],
            "prefix_base": "5000:dd::/64",
            "count": 1,
            "communities": ["65441:2241", "65441:2305"],
        }

        input_data = taac_types.BaseInput()
        await self.step_instance.setUp(input_data, params)
        await self.step_instance.run(input_data, params)

        mock_inject.assert_called_once()
        communities = mock_inject.call_args[0][2]
        self.assertEqual(len(communities), 2)

    async def test_missing_communities_raises(self):
        """setUp raises ValueError when neither community_list nor communities given."""
        params = {
            "devices": ["gtsw001.l1002.c087.mwg2"],
            "prefix_base": "5000:dd::/64",
            "count": 1,
        }

        input_data = taac_types.BaseInput()
        with self.assertRaises(ValueError):
            await self.step_instance.setUp(input_data, params)

    async def test_invalid_community_preset_raises(self):
        """setUp raises ValueError for an unknown community_list preset."""
        params = {
            "devices": ["gtsw001.l1002.c087.mwg2"],
            "prefix_base": "5000:dd::/64",
            "count": 1,
            "community_list": "nonexistent_preset",
        }

        input_data = taac_types.BaseInput()
        with self.assertRaises(ValueError):
            await self.step_instance.setUp(input_data, params)

    async def test_cleanup_is_noop(self):
        """cleanUp does nothing (no exception, no side effects)."""
        input_data = taac_types.BaseInput()
        # Should complete without error
        await self.step_instance.cleanUp(input_data, {})

    @patch(
        "neteng.test_infra.dne.taac.steps.fpf_bgp_prefix_injection_step.FbossSwitchInternal"
    )
    @patch(
        "neteng.test_infra.dne.taac.steps.fpf_bgp_prefix_injection_step.inject_prefixes",
        new_callable=AsyncMock,
    )
    async def test_default_count_and_increment(self, mock_inject, mock_driver_cls):
        """Default count=1 generates a single prefix from prefix_base."""
        mock_driver_cls.return_value = MagicMock()

        params = {
            "devices": ["gtsw001.l1002.c087.mwg2"],
            "prefix_base": "5000:dd::/64",
            "community_list": "gtsw",
        }

        input_data = taac_types.BaseInput()
        await self.step_instance.setUp(input_data, params)
        await self.step_instance.run(input_data, params)

        prefixes = mock_inject.call_args[0][1]
        self.assertEqual(len(prefixes), 1)
