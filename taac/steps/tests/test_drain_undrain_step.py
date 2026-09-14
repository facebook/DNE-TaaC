# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import asyncio
import json
import time
import typing as t
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from neteng.fboss.ctrl.types import PortInfoThrift
from neteng.test_infra.dne.taac.constants import TestDevice, TestTopology
from taac.libs.parameter_evaluator import ParameterEvaluator
from taac.steps.step_definitions import (
    create_drain_undrain_step,
    DrainUndrainStep,
)
from taac.test_as_a_config import types as taac_types


class DrainUndrainStepTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.device = MagicMock(spec=TestDevice)
        self.device.name = "test_device"
        self.device.get_interface_by_name.side_effect = AssertionError(
            "Local-drainer targets must not require testbed topology membership"
        )
        self.topology = MagicMock(spec=TestTopology)
        self.test_config = MagicMock(spec=taac_types.TestConfig)
        self.step = DrainUndrainStep(
            name="test_drain_undrain",
            device=self.device,
            topology=self.topology,
            test_case_results=[],
            test_config=self.test_config,
            test_case_name="test_case",
            test_case_start_time=time.time(),
            parameter_evaluator=MagicMock(spec=ParameterEvaluator),
            step=MagicMock(spec=taac_types.Step),
        )
        self.driver = AsyncMock()
        self.step.driver = t.cast(t.Any, self.driver)
        self.interfaces = ["eth1/1/1", "eth1/3/1"]

    def _params(self, *, hard_drain: bool = False) -> dict:
        return {
            "interfaces": json.dumps(self.interfaces),
            "hard_drain_interfaces": hard_drain,
        }

    @staticmethod
    def _drain_info(name: str, is_drained: bool) -> PortInfoThrift:
        return PortInfoThrift(name=name, isDrained=is_drained)

    def _port_map(self, *states: bool) -> dict[int, PortInfoThrift]:
        return {
            port_id: self._drain_info(name, is_drained)
            for port_id, (name, is_drained) in enumerate(
                zip(self.interfaces, states), start=1
            )
        }

    async def test_hard_drain_uses_one_bulk_request(self) -> None:
        await self.step.run(
            taac_types.DrainUndrainInput(
                drain=True, drain_handler=taac_types.DrainHandler.LOCAL_DRAINER
            ),
            self._params(hard_drain=True),
        )

        self.driver.async_drain_interfaces.assert_awaited_once_with(self.interfaces)
        self.driver.async_softdrain_interfaces.assert_not_awaited()
        self.driver.async_get_all_port_info.assert_not_awaited()

    async def test_soft_drain_uses_one_bulk_request(self) -> None:
        self.driver.async_get_all_port_info.return_value = self._port_map(True, True)
        await self.step.run(
            taac_types.DrainUndrainInput(
                drain=True, drain_handler=taac_types.DrainHandler.LOCAL_DRAINER
            ),
            self._params(),
        )

        self.driver.async_softdrain_interfaces.assert_awaited_once_with(self.interfaces)
        self.driver.async_softdrain_interface.assert_not_awaited()

    async def test_undrain_uses_one_bulk_request(self) -> None:
        self.driver.async_get_all_port_info.return_value = self._port_map(False, False)
        await self.step.run(
            taac_types.DrainUndrainInput(
                drain=False, drain_handler=taac_types.DrainHandler.LOCAL_DRAINER
            ),
            self._params(),
        )

        self.driver.async_undrain_interfaces.assert_awaited_once_with(self.interfaces)
        self.driver.async_undrain_interface.assert_not_awaited()

    async def test_hard_undrain_skips_non_authoritative_readback(self) -> None:
        await self.step.run(
            taac_types.DrainUndrainInput(
                drain=False, drain_handler=taac_types.DrainHandler.LOCAL_DRAINER
            ),
            self._params(hard_drain=True),
        )

        self.driver.async_undrain_interfaces.assert_awaited_once_with(self.interfaces)
        self.driver.async_get_all_port_info.assert_not_awaited()

    async def test_interface_drain_fails_when_readback_does_not_match(self) -> None:
        self.driver.async_get_all_port_info.return_value = self._port_map(True, False)

        with (
            patch(
                "neteng.test_infra.dne.taac.steps.step_definitions.asyncio.sleep",
                new_callable=AsyncMock,
            ),
            self.assertRaisesRegex(RuntimeError, "eth1/3/1"),
        ):
            await self.step.run(
                taac_types.DrainUndrainInput(
                    drain=True,
                    drain_handler=taac_types.DrainHandler.LOCAL_DRAINER,
                ),
                self._params(),
            )

    async def test_interface_drain_polls_until_readback_matches(self) -> None:
        self.driver.async_get_all_port_info.side_effect = [
            self._port_map(False, True),
            self._port_map(True, True),
        ]

        with patch(
            "neteng.test_infra.dne.taac.steps.step_definitions.asyncio.sleep",
            new_callable=AsyncMock,
        ) as sleep:
            await self.step.run(
                taac_types.DrainUndrainInput(
                    drain=True,
                    drain_handler=taac_types.DrainHandler.LOCAL_DRAINER,
                ),
                self._params(),
            )

        sleep.assert_awaited_once_with(
            self.step.LOCAL_DRAINER_READBACK_INTERVAL_SECONDS
        )

    async def test_interface_readback_timeout_names_every_target(self) -> None:
        async def never_returns() -> dict[int, PortInfoThrift]:
            await asyncio.sleep(60)
            return self._port_map(True, True)

        self.driver.async_get_all_port_info.side_effect = never_returns
        self.step.LOCAL_DRAINER_READBACK_TIMEOUT_SECONDS = 0.01

        with self.assertRaisesRegex(
            RuntimeError, "eth1/1/1.*not read.*eth1/3/1.*not read"
        ):
            await self.step.run(
                taac_types.DrainUndrainInput(
                    drain=True,
                    drain_handler=taac_types.DrainHandler.LOCAL_DRAINER,
                ),
                self._params(),
            )

    async def test_interface_readback_retries_after_bulk_read_timeout(self) -> None:
        self.step.LOCAL_DRAINER_READBACK_INTERVAL_SECONDS = 0
        timed_out = dict.fromkeys(self.interfaces, "not read (timed out)")
        with patch.object(
            self.step,
            "_read_local_drainer_interface_states",
            new_callable=AsyncMock,
            side_effect=[(timed_out, asyncio.TimeoutError()), ({}, None)],
        ) as read_state:
            await self.step.run(
                taac_types.DrainUndrainInput(
                    drain=True,
                    drain_handler=taac_types.DrainHandler.LOCAL_DRAINER,
                ),
                self._params(),
            )

        self.assertEqual(2, read_state.await_count)

    @patch(
        "neteng.test_infra.dne.taac.steps.step_definitions.async_nds_drain",
        new_callable=AsyncMock,
    )
    async def test_nds_resolves_interfaces_through_testbed_topology(
        self, async_nds_drain
    ) -> None:
        resolved = taac_types.TestInterface(interface_name="eth1/1/1")
        self.device.get_interface_by_name.side_effect = None
        self.device.get_interface_by_name.return_value = resolved

        await self.step.run(
            taac_types.DrainUndrainInput(
                drain=True, drain_handler=taac_types.DrainHandler.NDS
            ),
            {"interfaces": json.dumps(["eth1/1/1"])},
        )

        self.device.get_interface_by_name.assert_called_once_with("eth1/1/1")
        async_nds_drain.assert_awaited_once_with(
            self.device.name,
            force_undrain=False,
            interfaces=["eth1/1/1"],
        )

    def test_factory_serializes_hard_drain_and_skip_start_traffic(self) -> None:
        step = create_drain_undrain_step(
            drain=True,
            drain_handler=taac_types.DrainHandler.LOCAL_DRAINER,
            interfaces=self.interfaces,
            hard_drain_interfaces=True,
            start_traffic=False,
        )

        self.assertIsNotNone(step.step_params)
        self.assertEqual(
            json.loads(
                t.cast(str, t.cast(taac_types.Params, step.step_params).json_params)
            ),
            {
                "interfaces": self.interfaces,
                "hard_drain_interfaces": True,
                "skip_start_traffic": True,
            },
        )

    def test_factory_rejects_hard_drain_without_interfaces(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires a LOCAL_DRAINER"):
            create_drain_undrain_step(
                drain=True,
                drain_handler=taac_types.DrainHandler.LOCAL_DRAINER,
                hard_drain_interfaces=True,
            )


if __name__ == "__main__":
    unittest.main()
