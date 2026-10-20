# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe

import logging
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from taac.libs.taac_runner import TaacRunner
from taac.test_as_a_config import types as taac_types


def _config() -> taac_types.TestConfig:
    endpoint = taac_types.Endpoint(
        name="dut1",
        dut=True,
        direct_ixia_connections=[
            taac_types.DirectIxiaConnection(
                interface="eth1/1/1",
                ixia_port="1/1",
                ixia_chassis_ip="192.0.2.10",
            )
        ],
    )
    return taac_types.TestConfig(
        name="PLAYBOOK_SHARED_DATA_UNIT_TEST",
        basset_pool="",
        playbooks=[],
        endpoints=[endpoint],
    )


class TaacRunnerPlaybookSharedDataTest(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _prepare_runner() -> TaacRunner:
        runner = TaacRunner(
            _config(), logger=logging.getLogger("playbook-shared-data-test")
        )
        runner.test_summary = MagicMock()
        runner._capture_topology_baseline = AsyncMock()
        runner.initialize_and_setup_snapshot_checks = AsyncMock(return_value=[])
        runner.inject_validation_stages = MagicMock(return_value=[])
        runner.async_run_snapshot_checks = AsyncMock()
        runner._log_post_test_results = AsyncMock()
        runner.async_test_case_tearDown = AsyncMock()
        runner._publish_npi_result = AsyncMock()
        runner._record_playbook_result = MagicMock()

        async def preserve_run_error(
            _test_case_name,
            _test_case_results,
            _test_device,
            _test_case_start_time,
            run_error,
            _active_exception,
        ):
            return run_error

        runner._run_test_case_fallback_cleanup = AsyncMock(
            side_effect=preserve_run_error
        )
        return runner

    def test_initialized_step_uses_playbook_scope(self) -> None:
        runner = TaacRunner(
            _config(), logger=logging.getLogger("playbook-step-shared-data-test")
        )
        runner.topology = MagicMock()
        test_device = SimpleNamespace(name="dut1")

        step = runner._initialize_step(
            taac_types.Step(name=taac_types.StepName.DUMMY_STEP),
            test_device,
            "shared-data-scope",
            1,
            [],
        )

        self.assertIs(step.shared_data, runner._playbook_shared_task_data)
        self.assertIsNot(step.shared_data, runner.shared_task_data)

    async def test_shared_data_is_retained_within_playbook_iterations(self) -> None:
        runner = self._prepare_runner()
        playbook = taac_types.Playbook(
            name="shared-data-scope",
            stages=[],
            iteration=2,
        )
        test_device = SimpleNamespace(name="dut1")
        scopes = []

        async def capture_scope(*_args, **_kwargs) -> None:
            scopes.append(runner._playbook_shared_task_data)
            if len(scopes) == 1:
                scopes[0]["first-iteration-only"] = True
            else:
                self.assertIn("first-iteration-only", scopes[1])

        runner.async_test_case_setUp = AsyncMock(side_effect=capture_scope)

        await runner.run_test_case(playbook, test_device)

        self.assertEqual(len(scopes), 2)
        self.assertIs(scopes[0], scopes[1])
        runner.async_test_case_setUp.assert_awaited()

    async def test_shared_data_is_reset_between_playbooks(self) -> None:
        runner = self._prepare_runner()
        test_device = SimpleNamespace(name="dut1")
        scopes = []

        async def capture_scope(*_args, **_kwargs) -> None:
            scopes.append(runner._playbook_shared_task_data)
            if len(scopes) == 1:
                scopes[0]["first-playbook-only"] = True
            else:
                self.assertNotIn("first-playbook-only", scopes[1])

        runner.async_test_case_setUp = AsyncMock(side_effect=capture_scope)

        await runner.run_test_case(
            taac_types.Playbook(name="first-playbook", stages=[]), test_device
        )
        await runner.run_test_case(
            taac_types.Playbook(name="second-playbook", stages=[]), test_device
        )

        self.assertEqual(len(scopes), 2)
        self.assertIsNot(scopes[0], scopes[1])


if __name__ == "__main__":
    unittest.main()
