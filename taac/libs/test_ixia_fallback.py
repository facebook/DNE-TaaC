# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-ignore-all-errors
#
# Broad suppression justified: this file installs a `sys.modules` stub for
# `neteng.test_infra.dne.taac.test_configs` at import time (line ~16) so the
# orchestrator can be constructed without pulling in every TestConfig factory
# in the tree. The stub returns `ModuleType` rather than the concrete module
# type, and the extensive mock injections (`SimpleNamespace`, `MagicMock`,
# `AsyncMock`) into orchestrator/runner attributes are structurally
# compatible but nominally not. Targeted `
# ~40 markers without meaningful safety gain.

import asyncio
import logging
import os
import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, MagicMock, patch

from later.unittest import TestCase as AsyncTestCase
from taac.libs.ixia_candidate import (
    normalize_ixia_candidates,
    select_ixia_candidates,
)

TAAC_OSS = os.environ.get("TAAC_OSS", "").lower() in ("1", "true", "yes")

_TEST_CONFIGS_MODULE = "neteng.test_infra.dne.taac.test_configs"
_test_configs = types.ModuleType(_TEST_CONFIGS_MODULE)
_test_configs.get_test_config = lambda config: config
sys.modules[_TEST_CONFIGS_MODULE] = _test_configs

from taac.constants import IxiaEndpointInfo
from taac.libs import (
    taac_runner as _taac_runner,
    test_setup_orchestrator as _test_setup_orchestrator,
    traffic_generator as _traffic_generator,
)
from taac.libs.taac_runner import (
    _CleanupCancellationBudget,
    _start_test_case_time_window,
    TaacRunner,
)
from taac.libs.test_setup_orchestrator import (
    TestSetupOrchestrator,
)
from taac.libs.traffic_generator import TrafficGenerator
from taac.utils.oss_taac_constants import (
    IxiaChassisUnavailableError,
    IxiaFallbackExhaustedError,
    IxiaPortUnavailableError,
)
from taac.utils.taac_test_summary import SectionStatus
from taac.test_as_a_config import types as taac_types


# ShipIt rewrites import statements (neteng.test_infra.dne.taac. -> taac.) but
# not string literals, so a hardcoded dotted path would only be correct in one
# of the two worlds. These two modules are same-layer imports this file already
# holds, so read the name straight off the imported module — that is guaranteed
# to be the module patch() must target.
_MODULE = _test_setup_orchestrator.__name__
_TRAFFIC_GENERATOR_MODULE = _traffic_generator.__name__

# Selected by env rather than imported: internal/ is stripped by ShipIt, so an
# import statement here would both break OSS and add a libs -> internal BUCK
# edge that the OSS layering rules disallow.
_INTERNAL_UTILS_MODULE = (
    "taac.internal.internal_utils"
    if TAAC_OSS
    else "neteng.test_infra.dne.taac.internal.internal_utils"
)

if TAAC_OSS:
    # Register a stub under the name test_setup_orchestrator's lazy import
    # resolves to after export, so the internal teardown path stays patchable.
    _internal_pkg = types.ModuleType("taac.internal")
    _internal_utils_stub = types.ModuleType(_INTERNAL_UTILS_MODULE)
    _internal_utils_stub.async_release_devices_in_basset = None
    sys.modules.setdefault("taac.internal", _internal_pkg)
    sys.modules.setdefault(_INTERNAL_UTILS_MODULE, _internal_utils_stub)


def _endpoint(interface: str, ixia_port: str) -> taac_types.Endpoint:
    return taac_types.Endpoint(
        name="dut1",
        dut=True,
        direct_ixia_connections=[
            taac_types.DirectIxiaConnection(
                interface=interface,
                ixia_port=ixia_port,
                ixia_chassis_ip="192.0.2.10",
            )
        ],
    )


def _config(
    secondary_endpoint: taac_types.Endpoint | None = None,
    primary_setup_tasks=None,
    primary_teardown_tasks=None,
    secondary_setup_tasks=None,
    secondary_teardown_tasks=None,
) -> taac_types.TestConfig:
    secondary_profile = None
    if secondary_endpoint is not None:
        secondary_profile = taac_types.IxiaSetupProfile(
            name="secondary",
            api_server_ip="192.0.2.20",
            endpoints=[secondary_endpoint],
            setup_tasks=secondary_setup_tasks or [],
            teardown_tasks=secondary_teardown_tasks or [],
        )
    return taac_types.TestConfig(
        name="IXIA_FALLBACK_UNIT_TEST",
        basset_pool="",
        playbooks=[],
        endpoints=[_endpoint("eth1/1/1", "1/1")],
        setup_tasks=primary_setup_tasks,
        teardown_tasks=primary_teardown_tasks,
        secondary_ixia_profile=secondary_profile,
    )


class TaacRunnerTimeWindowTest(unittest.TestCase):
    def test_start_clears_previous_playbook_end_time(self) -> None:
        jq_vars = {
            "test_case_start_time": 100,
            "test_case_end_time": 150,
            "unrelated": "preserved",
        }

        _start_test_case_time_window(jq_vars, 200)

        self.assertEqual(200, jq_vars["test_case_start_time"])
        self.assertNotIn("test_case_end_time", jq_vars)
        self.assertEqual("preserved", jq_vars["unrelated"])


class TaacRunnerFailurePrecedenceTest(unittest.IsolatedAsyncioTestCase):
    async def test_teardown_failure_keeps_stage_primary_first(self) -> None:
        logger = logging.getLogger("taac-runner-failure-precedence-test")
        logger.setLevel(logging.INFO)
        runner = TaacRunner(_config(), logger=logger)
        stage = taac_types.Stage(id="failing-stage")
        playbook = taac_types.Playbook(name="failure-precedence", stages=[stage])
        test_device = SimpleNamespace(name="dut1")
        primary = RuntimeError("stage primary")
        teardown = ValueError("strict teardown")

        runner.test_summary = MagicMock()
        runner.async_test_case_setUp = AsyncMock()
        runner.initialize_and_setup_snapshot_checks = AsyncMock(return_value=[])
        runner.inject_validation_stages = MagicMock(return_value=[stage])
        runner.async_run_snapshot_checks = AsyncMock()
        runner.async_run_stage = AsyncMock(side_effect=primary)
        runner._log_post_test_results = AsyncMock()
        runner.async_test_case_tearDown = AsyncMock(side_effect=teardown)
        runner._publish_npi_result = AsyncMock()

        with self.assertRaises(ExceptionGroup) as context:
            await runner.run_test_case(playbook, test_device)

        self.assertEqual((primary, teardown), context.exception.exceptions)
        runner.async_test_case_tearDown.assert_awaited_once()
        runner._publish_npi_result.assert_awaited_once()


class TaacRunnerTeardownTaskExecutionTest(AsyncTestCase):
    def _runner(self) -> TaacRunner:
        logger = logging.getLogger("taac-runner-teardown-task-test")
        logger.setLevel(logging.INFO)
        return TaacRunner(_config(), logger=logger)

    @staticmethod
    def _tasks() -> tuple[taac_types.Task, ...]:
        return tuple(
            taac_types.Task(task_name=name, params=taac_types.Params())
            for name in ("first-cleanup", "fibagent-restore", "last-cleanup")
        )

    async def test_attempts_every_task_and_aggregates_failures_in_order(self) -> None:
        runner = self._runner()
        tasks = self._tasks()
        attempted = []
        first_error = RuntimeError("first cleanup failed")
        restore_error = ValueError("FibAgent restore failed")

        async def run_one(task, *, index, total) -> None:
            attempted.append(task.task_name)
            if task is tasks[0]:
                raise first_error
            if task is tasks[1]:
                raise restore_error

        runner._run_task_once = AsyncMock(side_effect=run_one)
        budget = _CleanupCancellationBudget()
        budget.arm(3600)

        with self.assertRaises(ExceptionGroup) as raised:
            await runner.run_teardown_tasks(tasks, cancellation_budget=budget)

        self.assertEqual(
            ["first-cleanup", "fibagent-restore", "last-cleanup"], attempted
        )
        self.assertEqual((first_error, restore_error), raised.exception.exceptions)
        self.assertIn("task 1/3", first_error.__notes__[0])
        self.assertIn("task 2/3", restore_error.__notes__[0])

    async def test_single_failure_preserves_original_exception(self) -> None:
        runner = self._runner()
        tasks = self._tasks()
        failure = RuntimeError("restore failed")

        async def run_one(task, *, index, total) -> None:
            if task is tasks[1]:
                raise failure

        runner._run_task_once = AsyncMock(side_effect=run_one)
        budget = _CleanupCancellationBudget()
        budget.arm(3600)

        with self.assertRaises(RuntimeError) as raised:
            await runner.run_teardown_tasks(tasks, cancellation_budget=budget)

        self.assertIs(failure, raised.exception)
        self.assertEqual(3, runner._run_task_once.await_count)

    async def test_cancellation_propagates_after_attempting_later_tasks(self) -> None:
        runner = self._runner()
        tasks = self._tasks()
        attempted = []
        cancellation = asyncio.CancelledError()

        async def run_one(task, *, index, total) -> None:
            attempted.append(task.task_name)
            if task is tasks[0]:
                raise cancellation

        runner._run_task_once = AsyncMock(side_effect=run_one)

        with self.assertRaises(asyncio.CancelledError):
            await runner.run_teardown_tasks(tasks)

        self.assertEqual(
            ["first-cleanup", "fibagent-restore", "last-cleanup"], attempted
        )

    async def test_cancellation_retains_later_cleanup_failure_as_note(self) -> None:
        runner = self._runner()
        tasks = self._tasks()
        attempted = []
        cancellation = asyncio.CancelledError()

        async def run_one(task, *, index, total) -> None:
            attempted.append(task.task_name)
            if task is tasks[0]:
                raise cancellation
            if task is tasks[1]:
                raise RuntimeError("FibAgent restore failed")

        runner._run_task_once = AsyncMock(side_effect=run_one)

        with self.assertRaises(asyncio.CancelledError) as raised:
            await runner.run_teardown_tasks(tasks)

        self.assertEqual(
            ["first-cleanup", "fibagent-restore", "last-cleanup"], attempted
        )
        self.assertIn("FibAgent restore failed", raised.exception.__notes__[-1])
        self.assertIsInstance(raised.exception.__cause__, ExceptionGroup)
        self.assertEqual(
            ["FibAgent restore failed"],
            [str(error) for error in raised.exception.__cause__.exceptions],
        )

    async def test_cancellation_grace_timeout_cancels_the_task(self) -> None:
        runner = self._runner()
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def wait_forever() -> None:
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        cleanup = asyncio.create_task(
            runner._await_cleanup_to_completion(
                wait_forever(),
                phase="hung cleanup",
                cancellation_grace_seconds=0.01,
            )
        )
        await started.wait()
        cleanup.cancel()
        cancellation, error = await cleanup
        await asyncio.wait_for(cancelled.wait(), 1)

        self.assertIsInstance(cancellation, asyncio.CancelledError)
        self.assertEqual(0, cleanup.cancelling())
        self.assertIsInstance(error, TimeoutError)
        self.assertIn("hung cleanup", str(error))
        self.assertTrue(cancelled.is_set())

    async def test_child_self_cancellation_does_not_arm_shared_budget(self) -> None:
        runner = self._runner()
        budget = _CleanupCancellationBudget()

        async def cancel_self() -> None:
            current_task = asyncio.current_task()
            if current_task is None:
                self.fail("cleanup must run in an asyncio task")
            current_task.cancel()
            await asyncio.sleep(0)

        observed, error = await runner._await_cleanup_to_completion(
            cancel_self(),
            phase="self-cancelled cleanup",
            cancellation_budget=budget,
        )

        self.assertIsInstance(observed, asyncio.CancelledError)
        self.assertIsNone(error)
        self.assertIsNone(budget.deadline)
        current_task = asyncio.current_task()
        self.assertIsNotNone(current_task)
        self.assertEqual(0, current_task.cancelling())

    async def test_spurious_cancellation_is_retained_while_cleanup_finishes(
        self,
    ) -> None:
        runner = self._runner()
        budget = _CleanupCancellationBudget()
        cancellation = asyncio.CancelledError()
        original_shield = asyncio.shield
        first_call = True

        async def cancel_once(cleanup_task):
            nonlocal first_call
            if first_call:
                first_call = False
                raise cancellation
            return await original_shield(cleanup_task)

        with patch.object(asyncio, "shield", side_effect=cancel_once):
            observed, error = await runner._await_cleanup_to_completion(
                asyncio.sleep(0),
                phase="spurious cancellation cleanup",
                cancellation_budget=budget,
            )

        self.assertIs(cancellation, observed)
        self.assertIsNone(error)
        self.assertIsNone(budget.deadline)

    async def test_prior_cancellation_bounds_later_cleanup(self) -> None:
        runner = self._runner()
        budget = _CleanupCancellationBudget()
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def wait_forever() -> None:
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        task = asyncio.create_task(wait_forever())
        await started.wait()
        budget.arm(0)
        cancellation, error = await runner._await_cleanup_to_completion(
            task,
            phase="later cleanup",
            cancellation_grace_seconds=0.01,
            cancellation_budget=budget,
        )
        await asyncio.wait_for(cancelled.wait(), 1)

        self.assertIsNone(cancellation)
        self.assertIsInstance(error, TimeoutError)
        self.assertTrue(cancelled.is_set())

    async def test_abandoned_cleanup_failure_uses_generic_log_message(self) -> None:
        runner = self._runner()
        runner.logger = MagicMock()

        async def fail() -> None:
            raise RuntimeError("late cleanup failure")

        task = asyncio.create_task(fail())
        with self.assertRaisesRegex(RuntimeError, "late cleanup failure"):
            await task

        runner._log_abandoned_cleanup_result(task, phase="resource cleanup")

        runner.logger.exception.assert_called_once_with(
            "resource cleanup failed after TAAC stopped waiting for it"
        )

    async def test_retry_reexecutes_only_failed_teardown_tasks(self) -> None:
        runner = self._runner()
        tasks = self._tasks()
        attempted = []
        first_attempt = True

        async def run_one(task, *, index, total) -> None:
            nonlocal first_attempt
            attempted.append(task.task_name)
            if task is tasks[0] and first_attempt:
                first_attempt = False
                raise RuntimeError("transient cleanup failure")

        runner._run_task_once = AsyncMock(side_effect=run_one)
        sleep = AsyncMock()

        with patch.object(asyncio, "sleep", sleep):
            await runner.run_teardown_tasks(tasks)

        self.assertEqual(
            [
                "first-cleanup",
                "fibagent-restore",
                "last-cleanup",
                "first-cleanup",
            ],
            attempted,
        )
        sleep.assert_awaited_once_with(_taac_runner._TASK_RETRY_SLEEP_SECONDS)

    async def test_retry_reports_only_persistent_failures(self) -> None:
        runner = self._runner()
        tasks = self._tasks()
        attempted = []
        transient_failure = RuntimeError("transient cleanup failure")
        persistent_failure = ValueError("persistent cleanup failure")
        attempts = {task.task_name: 0 for task in tasks}

        async def run_one(task, *, index, total) -> None:
            attempted.append(task.task_name)
            attempts[task.task_name] += 1
            if task is tasks[0] and attempts[task.task_name] == 1:
                raise transient_failure
            if task is tasks[1]:
                raise persistent_failure

        runner._run_task_once = AsyncMock(side_effect=run_one)

        with patch.object(asyncio, "sleep", AsyncMock()):
            with self.assertRaises(ValueError) as raised:
                await runner.run_teardown_tasks(tasks)

        self.assertIs(persistent_failure, raised.exception)
        self.assertEqual(
            [
                "first-cleanup",
                "fibagent-restore",
                "last-cleanup",
                "first-cleanup",
                "fibagent-restore",
            ],
            attempted,
        )

    async def test_armed_cancellation_budget_skips_teardown_retry(self) -> None:
        runner = self._runner()
        task = self._tasks()[0]
        budget = _CleanupCancellationBudget()
        budget.arm(3600)
        runner._run_task_once = AsyncMock(
            side_effect=RuntimeError("cleanup failed after cancellation")
        )
        sleep = AsyncMock()

        with patch.object(asyncio, "sleep", sleep):
            with self.assertRaisesRegex(
                RuntimeError, "cleanup failed after cancellation"
            ):
                await runner.run_teardown_tasks([task], cancellation_budget=budget)

        runner._run_task_once.assert_awaited_once()
        sleep.assert_not_awaited()

    async def test_cancellation_during_retry_sleep_retains_failure(self) -> None:
        runner = self._runner()
        task = self._tasks()[0]
        failure = RuntimeError("cleanup failed before cancellation")
        cancellation = asyncio.CancelledError()
        runner._run_task_once = AsyncMock(side_effect=failure)

        with patch.object(
            asyncio,
            "sleep",
            AsyncMock(side_effect=cancellation),
        ):
            with self.assertRaises(asyncio.CancelledError) as raised:
                await runner.run_teardown_tasks([task])

        self.assertIs(cancellation, raised.exception)
        self.assertIn(str(failure), cancellation.__notes__[-1])

    async def test_retry_self_cancellation_retains_first_attempt_failure(
        self,
    ) -> None:
        runner = self._runner()
        task = self._tasks()[0]
        first_failure = RuntimeError("first attempt failed")
        budget = _CleanupCancellationBudget()
        attempts = 0

        async def run_one(_task, *, index, total) -> None:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise first_failure
            current_task = asyncio.current_task()
            if current_task is None:
                self.fail("cleanup must run in an asyncio task")
            current_task.cancel()
            await asyncio.sleep(0)

        runner._run_task_once = AsyncMock(side_effect=run_one)

        with patch.object(_taac_runner, "_TASK_RETRY_SLEEP_SECONDS", 0):
            with self.assertRaises(asyncio.CancelledError) as raised:
                await runner.run_teardown_tasks([task], cancellation_budget=budget)

        self.assertEqual(2, attempts)
        self.assertIsNone(budget.deadline)
        self.assertIsInstance(raised.exception.__cause__, ExceptionGroup)
        self.assertEqual(
            (first_failure,),
            raised.exception.__cause__.exceptions,
        )


class IxiaCandidateTest(unittest.TestCase):
    def test_normalizes_fully_materialized_secondary(self) -> None:
        candidates = normalize_ixia_candidates(_config(_endpoint("eth1/1/1", "2/2")))

        self.assertEqual(
            [candidate.name for candidate in candidates], ["primary", "secondary"]
        )
        self.assertEqual(candidates[1].api_server_ip, "192.0.2.20")
        self.assertEqual(
            candidates[1].endpoints[0].direct_ixia_connections[0].interface, "eth1/1/1"
        )
        self.assertEqual(candidates[1].basic_port_configs, ())

    def test_rejects_secondary_without_ixia_endpoints(self) -> None:
        config = _config(taac_types.Endpoint(name="dut1", dut=True))

        with self.assertRaisesRegex(ValueError, "both require IXIA"):
            normalize_ixia_candidates(config)

    def test_explicit_override_disables_automatic_fallback(self) -> None:
        candidates = normalize_ixia_candidates(_config(_endpoint("eth1/1/1", "2/2")))

        selected = select_ixia_candidates(
            candidates, "auto", explicit_ixia_override=True
        )

        self.assertEqual(selected, (candidates[0],))

    def test_forced_primary_and_secondary_select_exact_candidate(self) -> None:
        candidates = normalize_ixia_candidates(_config(_endpoint("eth1/1/1", "2/2")))

        primary = select_ixia_candidates(
            candidates, "primary", explicit_ixia_override=False
        )
        secondary = select_ixia_candidates(
            candidates, "secondary", explicit_ixia_override=False
        )

        self.assertEqual(primary, (candidates[0],))
        self.assertEqual(secondary, (candidates[1],))

    def test_rejects_secondary_endpoint_name_mismatch(self) -> None:
        secondary = taac_types.Endpoint(
            name="dut2",
            dut=True,
            direct_ixia_connections=[
                taac_types.DirectIxiaConnection(
                    interface="eth1/1/1",
                    ixia_port="2/2",
                    ixia_chassis_ip="192.0.2.20",
                )
            ],
        )

        with self.assertRaisesRegex(ValueError, "same endpoint names"):
            normalize_ixia_candidates(_config(secondary))

    def test_rejects_secondary_dut_mismatch(self) -> None:
        secondary = _endpoint("eth1/1/1", "2/2")(dut=False)

        with self.assertRaisesRegex(ValueError, "same DUTs"):
            normalize_ixia_candidates(_config(secondary))

    def test_allows_candidate_specific_pre_ixia_task_payloads(self) -> None:
        shared = taac_types.Task(task_name="shared", params=taac_types.Params())
        primary_only = taac_types.Task(
            task_name="primary-only", params=taac_types.Params()
        )
        secondary_only = taac_types.Task(
            task_name="secondary-only", params=taac_types.Params()
        )
        config = _config(
            _endpoint("eth1/1/1", "2/2"),
            primary_setup_tasks=[shared, primary_only],
            secondary_setup_tasks=[shared, secondary_only],
        )

        primary, secondary = normalize_ixia_candidates(config)
        self.assertEqual(2, len(primary.setup_tasks))
        self.assertEqual(2, len(secondary.setup_tasks))

    def test_rejects_pre_ixia_task_count_mismatch(self) -> None:
        shared = taac_types.Task(task_name="shared", params=taac_types.Params())
        extra = taac_types.Task(task_name="extra", params=taac_types.Params())
        config = _config(
            _endpoint("eth1/1/1", "2/2"),
            primary_setup_tasks=[shared, extra],
            secondary_setup_tasks=[shared],
        )

        with self.assertRaisesRegex(ValueError, "non-IXIA setup tasks"):
            normalize_ixia_candidates(config)

    def test_rejects_secondary_with_otg_backend(self) -> None:
        config = _config(
            _endpoint("eth1/1/1", "2/2"),
        )(traffic_generator_backend=taac_types.TrafficGeneratorBackend.OTG)

        with self.assertRaisesRegex(ValueError, "only by the RESTPY"):
            normalize_ixia_candidates(config)

    def test_forced_profile_collects_only_selected_pre_ixia_tasks(self) -> None:
        primary_task = taac_types.Task(
            task_name="primary-pre", params=taac_types.Params()
        )
        config = _config(
            _endpoint("eth1/1/1", "2/2"),
            primary_setup_tasks=[primary_task],
            secondary_setup_tasks=[primary_task],
        )

        primary = TestSetupOrchestrator(config, MagicMock(), ixia_profile="primary")
        secondary = TestSetupOrchestrator(config, MagicMock(), ixia_profile="secondary")

        self.assertEqual(primary.ixia_candidates_to_try[0].setup_tasks, (primary_task,))
        self.assertEqual(
            secondary.ixia_candidates_to_try[0].setup_tasks, (primary_task,)
        )

    def test_rejects_basic_port_config_count_mismatch(self) -> None:
        # Per-config differences on `endpoint` / `device_group_configs` are
        # legitimate under dual-chassis (each config carries the DUT interface
        # of its own profile). Rejection now fires only on count mismatch.
        port_a = taac_types.BasicPortConfig(
            endpoint="dut1:eth1/1/1",
            device_group_configs=[
                taac_types.DeviceGroupConfig(device_group_index=0, tag_name="EBGP")
            ],
        )
        port_b = taac_types.BasicPortConfig(
            endpoint="dut1:eth1/1/2",
            device_group_configs=[
                taac_types.DeviceGroupConfig(device_group_index=1, tag_name="IBGP")
            ],
        )
        config = _config(_endpoint("eth1/1/1", "2/2"))
        config = config(
            basic_port_configs=[port_a, port_b],
            secondary_ixia_profile=config.secondary_ixia_profile(
                basic_port_configs=[port_a]
            ),
        )

        with self.assertRaisesRegex(ValueError, "basic port configurations"):
            normalize_ixia_candidates(config)

    def test_rejects_traffic_item_name_mismatch(self) -> None:
        primary_item = taac_types.BasicTrafficItemConfig(
            name="traffic",
            src_endpoints=[
                taac_types.TrafficEndpoint(name="dut1", device_group_index=0)
            ],
            dest_endpoints=[],
        )
        secondary_item = taac_types.BasicTrafficItemConfig(
            name="traffic-different-identity",
            src_endpoints=[
                taac_types.TrafficEndpoint(name="dut1", device_group_index=0)
            ],
            dest_endpoints=[],
        )
        config = _config(_endpoint("eth1/1/1", "2/2"))
        config = config(
            basic_traffic_item_configs=[primary_item],
            secondary_ixia_profile=config.secondary_ixia_profile(
                basic_traffic_item_configs=[secondary_item]
            ),
        )

        with self.assertRaisesRegex(ValueError, "traffic item identities"):
            normalize_ixia_candidates(config)

    def test_allows_traffic_configuration_field_differences(self) -> None:
        # Same identity (name), differing per-endpoint device_group_index —
        # allowed under dual-chassis compilation.
        primary_item = taac_types.BasicTrafficItemConfig(
            name="traffic",
            src_endpoints=[
                taac_types.TrafficEndpoint(name="dut1", device_group_index=0)
            ],
            dest_endpoints=[],
        )
        secondary_item = taac_types.BasicTrafficItemConfig(
            name="traffic",
            src_endpoints=[
                taac_types.TrafficEndpoint(name="dut1", device_group_index=1)
            ],
            dest_endpoints=[],
        )
        config = _config(_endpoint("eth1/1/1", "2/2"))
        config = config(
            basic_traffic_item_configs=[primary_item],
            secondary_ixia_profile=config.secondary_ixia_profile(
                basic_traffic_item_configs=[secondary_item]
            ),
        )

        primary, secondary = normalize_ixia_candidates(config)
        self.assertEqual(1, len(primary.basic_traffic_item_configs))
        self.assertEqual(1, len(secondary.basic_traffic_item_configs))

    def test_rejects_snake_configuration_count_mismatch(self) -> None:
        snake = taac_types.SnakeConfig(
            source="dut1",
            destination="dut1",
            source_ip="2001:db8::1",
            destination_ip="2001:db8::2",
        )
        config = _config(_endpoint("eth1/1/1", "2/2"))
        config = config(
            snake_configs=[snake],
            secondary_ixia_profile=config.secondary_ixia_profile(snake_configs=[]),
        )

        with self.assertRaisesRegex(ValueError, "snake configurations"):
            normalize_ixia_candidates(config)

    def test_single_ixia_config_normalizes_to_one_candidate(self) -> None:
        # Regression: existing single-IXIA TestConfigs without
        # `secondary_ixia_profile` must keep the pre-change one-attempt path.
        candidates = normalize_ixia_candidates(_config())

        self.assertEqual([c.name for c in candidates], ["primary"])
        self.assertEqual(
            select_ixia_candidates(candidates, "auto", explicit_ixia_override=False),
            (candidates[0],),
        )

    def test_simultaneous_multi_chassis_endpoints_do_not_enable_fallback(self) -> None:
        # Regression: an existing endpoint that carries multiple
        # DirectIxiaConnection entries (i.e., "one session across several
        # chassis") is not implicitly converted into a fallback candidate list.
        multi_chassis_endpoint = taac_types.Endpoint(
            name="dut1",
            dut=True,
            direct_ixia_connections=[
                taac_types.DirectIxiaConnection(
                    interface="eth1/1/1",
                    ixia_port="1/1",
                    ixia_chassis_ip="192.0.2.10",
                ),
                taac_types.DirectIxiaConnection(
                    interface="eth1/1/2",
                    ixia_port="1/2",
                    ixia_chassis_ip="192.0.2.11",
                ),
            ],
        )
        config = taac_types.TestConfig(
            name="EXISTING_MULTI_CHASSIS",
            basset_pool="",
            playbooks=[],
            endpoints=[multi_chassis_endpoint],
        )
        candidates = normalize_ixia_candidates(config)

        self.assertEqual([c.name for c in candidates], ["primary"])
        self.assertEqual(
            [
                connection.ixia_chassis_ip
                for connection in candidates[0].endpoints[0].direct_ixia_connections
            ],
            ["192.0.2.10", "192.0.2.11"],
        )

    def test_rejects_missing_parent_traffic_item_reference(self) -> None:
        config = _config(_endpoint("eth1/1/1", "2/2"))(
            traffic_items_to_start=["missing-traffic"]
        )

        with self.assertRaisesRegex(ValueError, "missing-traffic"):
            normalize_ixia_candidates(config)


class IxiaChassisResolutionTest(unittest.IsolatedAsyncioTestCase):
    async def test_hostname_resolution_failure_is_fallback_eligible(self) -> None:
        generator = TrafficGenerator(
            endpoints=[], primary_chassis_ip="unreachable-ixia.example"
        )
        resolution_error = OSError("DNS lookup failed")

        with patch(
            f"{_TRAFFIC_GENERATOR_MODULE}.async_get_ip_from_hostname",
            new=AsyncMock(side_effect=resolution_error),
        ):
            with self.assertRaises(IxiaChassisUnavailableError) as context:
                await generator.async_get_primary_ixia_chassis_ip()

        self.assertIs(context.exception.__cause__, resolution_error)


def _discovered_ixia_asset(interface: str, port: str) -> IxiaEndpointInfo:
    return IxiaEndpointInfo(
        ixia_chassis_ip="192.0.2.10",
        ixia_slot_num="1",
        ixia_port_num=port,
        remote_device_name="dut1",
        remote_intf_name=interface,
        is_logical_port=True,
    )


class IxiaLldpDiscoveryTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.endpoint = taac_types.Endpoint(
            name="dut1",
            dut=True,
            ixia_ports=["eth1/1/1", "eth1/1/2"],
        )
        self.complete_assets = [
            _discovered_ixia_asset("eth1/1/1", "17"),
            _discovered_ixia_asset("eth1/1/2", "18"),
        ]

    async def test_requeries_until_complete_then_reuses_snapshot(self) -> None:
        lldp_discovery = AsyncMock(
            side_effect=[[], self.complete_assets[:1], self.complete_assets]
        )
        optical_discovery = AsyncMock()
        generator = TrafficGenerator(
            endpoints=[self.endpoint],
            logger=MagicMock(),
            wait_for_lldp_reconvergence=True,
        )

        with (
            patch(
                f"{_INTERNAL_UTILS_MODULE}.async_create_lldp_ixia_connection_assets",
                new=lldp_discovery,
            ),
            patch(
                f"{_TRAFFIC_GENERATOR_MODULE}.async_create_optical_switch_ixia_connection_assets",
                new=optical_discovery,
            ),
            patch("asyncio.sleep", new=AsyncMock()) as sleep,
        ):
            assets = await generator.async_get_endpoint_desired_ixia_assets(
                self.endpoint
            )
            repeated_assets = await generator.async_get_endpoint_desired_ixia_assets(
                self.endpoint
            )

        self.assertCountEqual(self.complete_assets, assets)
        self.assertCountEqual(self.complete_assets, repeated_assets)
        self.assertEqual(3, lldp_discovery.await_count)
        self.assertEqual(2, sleep.await_count)
        optical_discovery.assert_not_awaited()

    async def test_uses_optical_fallback_after_lldp_deadline(self) -> None:
        lldp_discovery = AsyncMock(return_value=[])
        optical_discovery = AsyncMock(return_value=self.complete_assets)
        generator = TrafficGenerator(
            endpoints=[self.endpoint],
            logger=MagicMock(),
            wait_for_lldp_reconvergence=True,
        )

        with (
            patch(
                f"{_INTERNAL_UTILS_MODULE}.async_create_lldp_ixia_connection_assets",
                new=lldp_discovery,
            ),
            patch(
                f"{_TRAFFIC_GENERATOR_MODULE}.async_create_optical_switch_ixia_connection_assets",
                new=optical_discovery,
            ),
            patch("asyncio.sleep", new=AsyncMock()) as sleep,
        ):
            assets = await generator.async_get_endpoint_desired_ixia_assets(
                self.endpoint
            )

        self.assertCountEqual(self.complete_assets, assets)
        self.assertEqual(6, lldp_discovery.await_count)
        self.assertEqual(5, sleep.await_count)
        optical_discovery.assert_awaited_once_with("dut1")

    async def test_skipped_package_update_does_not_delay_fallback(self) -> None:
        lldp_discovery = AsyncMock(return_value=[])
        optical_discovery = AsyncMock(return_value=self.complete_assets)
        generator = TrafficGenerator(endpoints=[self.endpoint], logger=MagicMock())

        with (
            patch(
                f"{_INTERNAL_UTILS_MODULE}.async_create_lldp_ixia_connection_assets",
                new=lldp_discovery,
            ),
            patch(
                f"{_TRAFFIC_GENERATOR_MODULE}.async_create_optical_switch_ixia_connection_assets",
                new=optical_discovery,
            ),
            patch("asyncio.sleep", new=AsyncMock()) as sleep,
        ):
            assets = await generator.async_get_endpoint_desired_ixia_assets(
                self.endpoint
            )

        self.assertCountEqual(self.complete_assets, assets)
        lldp_discovery.assert_awaited_once_with("dut1")
        sleep.assert_not_awaited()
        optical_discovery.assert_awaited_once_with("dut1")


class IxiaFallbackTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.config = _config(_endpoint("eth1/1/1", "2/2"))
        self.logger = MagicMock()
        self.orchestrator = TestSetupOrchestrator(self.config, self.logger)
        self.chunker = MagicMock()
        self.chunker.async_create_test_bed = AsyncMock(
            return_value=SimpleNamespace(devices=[])
        )

    async def _run_setup(self) -> None:
        with (
            patch(f"{_MODULE}.TAAC_OSS", True),
            patch(f"{_MODULE}.OssTestBedChunker", return_value=self.chunker),
        ):
            await self.orchestrator.async_setUp()

    async def test_healthy_primary_does_not_attempt_secondary(self) -> None:
        primary_ixia = SimpleNamespace(session_id=11)
        self.orchestrator.async_create_ixia_setup = AsyncMock(return_value=primary_ixia)

        await self._run_setup()

        self.assertEqual(self.orchestrator.selected_ixia_candidate.name, "primary")
        self.orchestrator.async_create_ixia_setup.assert_awaited_once()

    async def test_normal_teardown_is_not_disabled_with_failed_setup_cleanup(
        self,
    ) -> None:
        teardown = MagicMock()
        orchestrator = TestSetupOrchestrator(
            self.config,
            self.logger,
            cleanup_failed_setup=False,
        )
        orchestrator.traffic_generator = SimpleNamespace(teardown_ixia_setup=teardown)

        await orchestrator.async_teardown_ixia_setup()

        teardown.assert_called_once()

    async def test_internal_teardown_attempts_every_resource(self) -> None:
        orchestrator = TestSetupOrchestrator(
            self.config,
            self.logger,
            skip_testbed_isolation=False,
        )
        restore = AsyncMock(side_effect=RuntimeError("restore failed"))
        release = AsyncMock(side_effect=RuntimeError("release failed"))
        ixia_cleanup = AsyncMock(side_effect=RuntimeError("IXIA cleanup failed"))
        orchestrator.test_bed_chunker = SimpleNamespace(
            async_restore_test_bed_connectivity=restore
        )
        orchestrator.basset_butler = object()
        orchestrator.async_teardown_ixia_setup = ixia_cleanup

        with (
            patch(f"{_MODULE}.TAAC_OSS", False),
            patch(
                f"{_INTERNAL_UTILS_MODULE}.async_release_devices_in_basset",
                new=release,
            ),
        ):
            with self.assertRaises(ExceptionGroup) as context:
                await orchestrator.async_tearDown(strict_ixia_cleanup=True)

        self.assertEqual(len(context.exception.exceptions), 3)
        restore.assert_awaited_once()
        release.assert_awaited_once_with(orchestrator.basset_butler, self.logger)
        ixia_cleanup.assert_awaited_once_with(strict=True)

    async def test_internal_teardown_before_test_bed_creation(self) -> None:
        orchestrator = TestSetupOrchestrator(
            self.config,
            self.logger,
            skip_testbed_isolation=False,
        )
        ixia_cleanup = AsyncMock()
        orchestrator.async_teardown_ixia_setup = ixia_cleanup

        with patch(f"{_MODULE}.TAAC_OSS", False):
            await orchestrator.async_tearDown(strict_ixia_cleanup=True)

        self.assertIsNone(orchestrator.test_bed_chunker)
        ixia_cleanup.assert_awaited_once_with(strict=True)

    async def test_port_failure_cleans_primary_and_selects_secondary(self) -> None:
        teardown = MagicMock()

        async def create_ixia(candidate, *_args):
            if candidate.name == "primary":
                self.orchestrator.traffic_generator = SimpleNamespace(
                    teardown_ixia_setup=teardown
                )
                raise IxiaPortUnavailableError("primary port unavailable")
            return SimpleNamespace(session_id=22)

        self.orchestrator.async_create_ixia_setup = AsyncMock(side_effect=create_ixia)

        await self._run_setup()

        self.assertEqual(self.orchestrator.selected_ixia_candidate.name, "secondary")
        self.assertEqual(self.orchestrator.async_create_ixia_setup.await_count, 2)
        teardown.assert_called_once_with()

    async def test_noneligible_failure_does_not_fallback(self) -> None:
        self.orchestrator.async_create_ixia_setup = AsyncMock(
            side_effect=ValueError("invalid test config")
        )

        with self.assertRaisesRegex(ValueError, "invalid test config"):
            await self._run_setup()

        self.orchestrator.async_create_ixia_setup.assert_awaited_once()

    async def test_both_candidate_failures_are_aggregated(self) -> None:
        teardown_primary = MagicMock()
        teardown_secondary = MagicMock()

        async def create_ixia(candidate, *_args):
            teardown = (
                teardown_primary if candidate.name == "primary" else teardown_secondary
            )
            self.orchestrator.traffic_generator = SimpleNamespace(
                teardown_ixia_setup=teardown
            )
            raise IxiaPortUnavailableError(f"{candidate.name} failed")

        self.orchestrator.async_create_ixia_setup = AsyncMock(side_effect=create_ixia)

        with self.assertRaises(IxiaFallbackExhaustedError) as context:
            await self._run_setup()

        self.assertEqual(
            [name for name, _error in context.exception.failures],
            ["primary", "secondary"],
        )
        teardown_primary.assert_called_once_with()
        teardown_secondary.assert_called_once_with()

    async def test_cleanup_failure_aborts_before_secondary(self) -> None:
        teardown = MagicMock(side_effect=RuntimeError("cleanup failed"))

        async def create_ixia(_candidate, *_args):
            self.orchestrator.traffic_generator = SimpleNamespace(
                teardown_ixia_setup=teardown
            )
            raise IxiaPortUnavailableError("primary failed")

        self.orchestrator.async_create_ixia_setup = AsyncMock(side_effect=create_ixia)

        with self.assertRaisesRegex(RuntimeError, "cleanup failed"):
            await self._run_setup()

        self.orchestrator.async_create_ixia_setup.assert_awaited_once()
        self.assertIsNotNone(self.orchestrator.traffic_generator)


class SetupOnlyTest(unittest.IsolatedAsyncioTestCase):
    async def test_skips_playbook_execution(self) -> None:
        logger = MagicMock()
        runner = TaacRunner(_config(), setup_only=True, logger=logger)
        runner.run_test_case = AsyncMock()

        await runner.run_tests()

        runner.run_test_case.assert_not_awaited()
        logger.warning.assert_called_once_with(
            "Setup-only mode: setup completed; skipping all playbooks"
        )


class IxiaDiagnosticsDefaultTest(unittest.TestCase):
    def test_collection_is_enabled_by_default(self) -> None:
        runner = TaacRunner(_config())

        self.assertTrue(runner.collect_ixia_diagnostics)

    def test_collection_can_be_disabled(self) -> None:
        runner = TaacRunner(_config(), collect_ixia_diagnostics=False)

        self.assertFalse(runner.collect_ixia_diagnostics)


class StatefulTaskRetryTest(unittest.IsolatedAsyncioTestCase):
    async def test_retry_does_not_replay_completed_tasks(self) -> None:
        first = taac_types.Task(
            task_name="stateful-first", params=taac_types.Params()
        )
        second = taac_types.Task(
            task_name="transient-second", params=taac_types.Params()
        )
        runner = TaacRunner(_config())
        runner.parameter_evaluator.evaluate = MagicMock(
            side_effect=({"attempt": 1}, {"attempt": 1}, {"attempt": 2})
        )

        with patch(
            f"{TaacRunner.__module__}.run_task",
            new_callable=AsyncMock,
            side_effect=(None, RuntimeError("transient"), None),
        ) as run, patch(
            "taac.utils.oss_taac_lib_utils.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            await runner.run_tasks((first, second))

        self.assertEqual(
            [awaited.args[0] for awaited in run.await_args_list],
            [first, second, second],
        )
        self.assertEqual(runner.parameter_evaluator.evaluate.call_count, 3)
        self.assertEqual(
            [awaited.args[1] for awaited in run.await_args_list],
            [{"attempt": 1}, {"attempt": 1}, {"attempt": 2}],
        )


class SelectedCandidateTaskTest(unittest.IsolatedAsyncioTestCase):
    async def test_section_start_failure_still_releases_resources(self) -> None:
        runner = TaacRunner(
            _config(), logger=logging.getLogger("taac-section-start-failure-test")
        )
        start_failure = RuntimeError("section start failed")
        runner.test_setup_orchestrator.async_tearDown = AsyncMock()
        summary = MagicMock()
        summary.start_section.side_effect = start_failure
        runner.test_summary = summary

        with self.assertRaises(RuntimeError) as raised:
            await runner.async_test_tearDown()

        self.assertIs(start_failure, raised.exception)
        runner.test_setup_orchestrator.async_tearDown.assert_awaited_once_with(
            strict_ixia_cleanup=False
        )
        summary.cleanup.assert_called_once()

    async def test_entry_cleanup_cancellation_remains_primary(self) -> None:
        runner = TaacRunner(
            _config(), logger=logging.getLogger("taac-entry-cleanup-cancel-test")
        )
        start_failure = RuntimeError("section start failed")
        cleanup_started = asyncio.Event()
        release_cleanup = asyncio.Event()

        async def cleanup_resources(**_kwargs) -> None:
            cleanup_started.set()
            await release_cleanup.wait()

        runner.test_setup_orchestrator.async_tearDown = AsyncMock(
            side_effect=cleanup_resources
        )
        summary = MagicMock()
        summary.start_section.side_effect = start_failure
        runner.test_summary = summary

        teardown = asyncio.create_task(runner.async_test_tearDown())
        await cleanup_started.wait()
        teardown.cancel()
        await asyncio.sleep(0)
        self.assertFalse(teardown.done())
        release_cleanup.set()

        with self.assertRaises(asyncio.CancelledError) as raised:
            await teardown

        self.assertIsInstance(raised.exception.__cause__, ExceptionGroup)
        self.assertEqual(
            (start_failure,),
            raised.exception.__cause__.exceptions,
        )
        summary.cleanup.assert_called_once()

    async def test_secondary_post_setup_and_teardown_tasks_are_used(self) -> None:
        pre_task = taac_types.Task(task_name="common-pre", params=taac_types.Params())
        primary_post = taac_types.Task(
            task_name="primary-post", params=taac_types.Params(), ixia_needed=True
        )
        secondary_post = taac_types.Task(
            task_name="secondary-post", params=taac_types.Params(), ixia_needed=True
        )
        primary_teardown = taac_types.Task(
            task_name="primary-teardown", params=taac_types.Params()
        )
        secondary_teardown = taac_types.Task(
            task_name="secondary-teardown", params=taac_types.Params()
        )
        config = _config(
            _endpoint("eth1/1/1", "2/2"),
            primary_setup_tasks=[pre_task, primary_post],
            primary_teardown_tasks=[primary_teardown],
            secondary_setup_tasks=[pre_task, secondary_post],
            secondary_teardown_tasks=[secondary_teardown],
        )
        logger = logging.getLogger("taac-fallback-selected-task-test")
        logger.setLevel(logging.INFO)
        runner = TaacRunner(config, logger=logger)
        runner.run_tasks = AsyncMock()
        runner._add_oss_mock_device_data = MagicMock()
        runner._add_host_to_device_os_type_data = MagicMock()
        runner._add_host_driver_args_data = MagicMock()
        runner.filter_custom_test_handlers_by_tags = MagicMock(return_value=[])

        async def select_secondary() -> None:
            runner.test_setup_orchestrator.selected_ixia_candidate = (
                runner.ixia_candidates[1]
            )
            runner.test_setup_orchestrator.ixia = None
            runner.test_setup_orchestrator.test_topology = SimpleNamespace(devices=[])

        runner.test_setup_orchestrator.async_setUp = AsyncMock(
            side_effect=select_secondary
        )

        await runner.async_test_setUp()

        setup_task_calls = [call.args[0] for call in runner.run_tasks.await_args_list]
        self.assertIn([pre_task], setup_task_calls)
        self.assertIn([secondary_post], setup_task_calls)
        self.assertLess(
            setup_task_calls.index([pre_task]),
            setup_task_calls.index([secondary_post]),
        )

        runner.run_tasks.reset_mock()
        teardown_events = []

        async def run_selected_teardown(_task, *, index, total) -> None:
            teardown_events.append("selected-tasks")

        async def release_resources(**_kwargs) -> None:
            teardown_events.append("orchestrator")

        runner._run_task_once = AsyncMock(side_effect=run_selected_teardown)
        runner.test_setup_orchestrator.async_tearDown = AsyncMock(
            side_effect=release_resources
        )
        summary = MagicMock()
        summary.start_section.return_value = MagicMock()
        summary.sections = []
        summary.async_upload_and_log_summary = AsyncMock()
        runner.test_summary = summary

        await runner.async_test_tearDown()

        runner._run_task_once.assert_awaited_once_with(
            secondary_teardown, index=1, total=1
        )
        self.assertEqual(teardown_events, ["selected-tasks", "orchestrator"])

    async def test_teardown_task_failure_still_releases_resources(self) -> None:
        teardown_task = taac_types.Task(
            task_name="teardown", params=taac_types.Params()
        )
        config = _config(primary_teardown_tasks=[teardown_task])
        logger = logging.getLogger("taac-fallback-task-failure-test")
        logger.setLevel(logging.INFO)
        runner = TaacRunner(config, logger=logger)
        runner.selected_ixia_candidate = runner.ixia_candidates[0]
        runner.run_teardown_tasks = AsyncMock(
            side_effect=RuntimeError("task cleanup failed")
        )
        handler = MagicMock()
        handler._async_test_tearDown = AsyncMock()
        runner.custom_test_handlers = [handler]
        runner.test_setup_orchestrator.async_tearDown = AsyncMock()
        summary = MagicMock()
        summary.start_section.return_value = MagicMock()
        summary.sections = []
        summary.async_upload_and_log_summary = AsyncMock()
        runner.test_summary = summary

        with self.assertRaisesRegex(RuntimeError, "task cleanup failed"):
            await runner.async_test_tearDown()

        handler._async_test_tearDown.assert_awaited_once()
        runner.test_setup_orchestrator.async_tearDown.assert_awaited_once()

    async def test_handler_factory_errors_do_not_skip_remaining_cleanup(self) -> None:
        runner = TaacRunner(
            _config(), logger=logging.getLogger("taac-handler-factory-failure-test")
        )
        runner.selected_ixia_candidate = runner.ixia_candidates[0]
        runner.run_teardown_tasks = AsyncMock()
        factory_failure = RuntimeError("handler factory failed")
        failing_handler = MagicMock()
        failing_handler._async_test_tearDown = MagicMock(side_effect=factory_failure)
        nonawaitable_handler = MagicMock()
        nonawaitable_handler._async_test_tearDown = MagicMock(return_value=None)
        final_handler = MagicMock()
        final_handler._async_test_tearDown = AsyncMock()
        runner.custom_test_handlers = [
            failing_handler,
            nonawaitable_handler,
            final_handler,
        ]
        runner.test_setup_orchestrator.async_tearDown = AsyncMock()
        runner._async_run_lifecycle_investigation_if_enabled = AsyncMock()
        summary = MagicMock()
        summary.start_section.return_value = MagicMock()
        summary.sections = []
        summary.async_upload_and_log_summary = AsyncMock()
        runner.test_summary = summary

        with self.assertRaises(ExceptionGroup) as raised:
            await runner.async_test_tearDown()

        self.assertIs(factory_failure, raised.exception.exceptions[0])
        self.assertIsInstance(raised.exception.exceptions[1], TypeError)
        failing_handler._async_test_tearDown.assert_called_once()
        nonawaitable_handler._async_test_tearDown.assert_called_once()
        final_handler._async_test_tearDown.assert_awaited_once()
        runner.test_setup_orchestrator.async_tearDown.assert_awaited_once()
        summary.async_upload_and_log_summary.assert_awaited_once()
        summary.cleanup.assert_called_once()

    async def test_task_base_exception_still_runs_mandatory_cleanup(self) -> None:
        class FatalTeardown(BaseException):
            pass

        runner = TaacRunner(
            _config(), logger=logging.getLogger("taac-task-base-exception-test")
        )
        runner.selected_ixia_candidate = runner.ixia_candidates[0]
        fatal = FatalTeardown("fatal teardown failure")
        runner.run_teardown_tasks = AsyncMock(side_effect=fatal)
        runner.test_setup_orchestrator.async_tearDown = AsyncMock()
        summary = MagicMock()
        summary.start_section.return_value = MagicMock()
        summary.sections = []
        summary.async_upload_and_log_summary = AsyncMock()
        runner.test_summary = summary

        with self.assertRaises(FatalTeardown) as raised:
            await runner.async_test_tearDown()

        self.assertIs(fatal, raised.exception)
        runner.test_setup_orchestrator.async_tearDown.assert_awaited_once()
        summary.async_upload_and_log_summary.assert_not_awaited()
        summary.cleanup.assert_called_once()

    async def test_pre_release_cancellation_survives_later_base_exception(
        self,
    ) -> None:
        class FatalTeardown(BaseException):
            pass

        runner = TaacRunner(
            _config(), logger=logging.getLogger("taac-cancel-then-fatal-test")
        )
        runner.selected_ixia_candidate = runner.ixia_candidates[0]
        cancellation = asyncio.CancelledError()
        fatal = FatalTeardown("fatal handler failure")
        runner.teardown_period_task_executor_if_exists = AsyncMock(
            side_effect=cancellation
        )
        runner.run_teardown_tasks = AsyncMock()
        handler = MagicMock()
        handler._async_test_tearDown = MagicMock(side_effect=fatal)
        runner.custom_test_handlers = [handler]
        runner.test_setup_orchestrator.async_tearDown = AsyncMock()
        summary = MagicMock()
        summary.start_section.return_value = MagicMock()
        summary.sections = []
        summary.async_upload_and_log_summary = AsyncMock()
        runner.test_summary = summary

        with self.assertRaises(FatalTeardown) as raised:
            await runner.async_test_tearDown()

        self.assertIs(fatal, raised.exception)
        self.assertIsInstance(raised.exception.__cause__, BaseExceptionGroup)
        self.assertEqual(
            (cancellation,),
            raised.exception.__cause__.exceptions,
        )
        runner.test_setup_orchestrator.async_tearDown.assert_awaited_once()
        summary.cleanup.assert_called_once()

    async def test_resource_base_exception_does_not_mask_pre_release_failure(
        self,
    ) -> None:
        class FatalTeardown(BaseException):
            pass

        runner = TaacRunner(
            _config(), logger=logging.getLogger("taac-resource-base-exception-test")
        )
        runner.selected_ixia_candidate = runner.ixia_candidates[0]
        cancellation = asyncio.CancelledError()
        earlier_failure = RuntimeError("earlier cleanup failure")
        pre_release_failure = FatalTeardown("pre-release failure")
        resource_failure = FatalTeardown("resource release failure")
        runner.teardown_period_task_executor_if_exists = AsyncMock(
            side_effect=cancellation
        )
        runner.run_teardown_tasks = AsyncMock(side_effect=earlier_failure)
        handler = MagicMock()
        handler._async_test_tearDown = MagicMock(side_effect=pre_release_failure)
        runner.custom_test_handlers = [handler]
        runner.test_setup_orchestrator.async_tearDown = MagicMock(
            side_effect=resource_failure
        )
        summary = MagicMock()
        summary.start_section.return_value = MagicMock()
        summary.sections = []
        summary.async_upload_and_log_summary = AsyncMock()
        runner.test_summary = summary

        with self.assertRaises(FatalTeardown) as raised:
            await runner.async_test_tearDown()

        self.assertIs(pre_release_failure, raised.exception)
        self.assertIsInstance(raised.exception.__cause__, BaseExceptionGroup)
        self.assertEqual(
            (earlier_failure, cancellation, resource_failure),
            raised.exception.__cause__.exceptions,
        )
        summary.cleanup.assert_called_once()

    async def test_resource_base_exception_retains_recorded_pre_release_state(
        self,
    ) -> None:
        class FatalTeardown(BaseException):
            pass

        runner = TaacRunner(
            _config(), logger=logging.getLogger("taac-resource-primary-fatal-test")
        )
        runner.selected_ixia_candidate = runner.ixia_candidates[0]
        cancellation = asyncio.CancelledError()
        earlier_failure = RuntimeError("earlier cleanup failure")
        resource_failure = FatalTeardown("resource release failure")
        runner.teardown_period_task_executor_if_exists = AsyncMock(
            side_effect=cancellation
        )
        runner.run_teardown_tasks = AsyncMock(side_effect=earlier_failure)
        runner.test_setup_orchestrator.async_tearDown = MagicMock(
            side_effect=resource_failure
        )
        summary = MagicMock()
        summary.start_section.return_value = MagicMock()
        summary.sections = []
        summary.async_upload_and_log_summary = AsyncMock()
        runner.test_summary = summary

        with self.assertRaises(FatalTeardown) as raised:
            await runner.async_test_tearDown()

        self.assertIs(resource_failure, raised.exception)
        self.assertIsInstance(raised.exception.__cause__, BaseExceptionGroup)
        self.assertEqual(
            (earlier_failure, cancellation),
            raised.exception.__cause__.exceptions,
        )
        summary.cleanup.assert_called_once()

    async def test_summary_base_exception_does_not_mask_teardown_failure(
        self,
    ) -> None:
        class FatalTeardown(BaseException):
            pass

        runner = TaacRunner(
            _config(), logger=logging.getLogger("taac-summary-base-exception-test")
        )
        runner.selected_ixia_candidate = runner.ixia_candidates[0]
        teardown_failure = FatalTeardown("fatal teardown failure")
        summary_failure = FatalTeardown("fatal summary cleanup failure")
        runner.run_teardown_tasks = AsyncMock(side_effect=teardown_failure)
        runner.test_setup_orchestrator.async_tearDown = AsyncMock()
        summary = MagicMock()
        summary.start_section.return_value = MagicMock()
        summary.sections = []
        summary.async_upload_and_log_summary = AsyncMock()
        summary.cleanup.side_effect = summary_failure
        runner.test_summary = summary

        with self.assertRaises(FatalTeardown) as raised:
            await runner.async_test_tearDown()

        self.assertIs(teardown_failure, raised.exception)
        self.assertIsInstance(raised.exception.__cause__, BaseExceptionGroup)
        self.assertEqual(
            (summary_failure,),
            raised.exception.__cause__.exceptions,
        )
        runner.test_setup_orchestrator.async_tearDown.assert_awaited_once()
        summary.cleanup.assert_called_once()

    async def test_exhausted_pre_release_budget_does_not_starve_resource_release(
        self,
    ) -> None:
        runner = TaacRunner(
            _config(), logger=logging.getLogger("taac-resource-budget-test")
        )
        runner.selected_ixia_candidate = runner.ixia_candidates[0]

        async def exhaust_budget(_tasks, *, cancellation_budget) -> None:
            cancellation_budget.deadline = 0

        resource_released = False

        async def release_resources(**_kwargs) -> None:
            nonlocal resource_released
            await asyncio.sleep(0)
            resource_released = True

        runner.run_teardown_tasks = AsyncMock(side_effect=exhaust_budget)
        runner.test_setup_orchestrator.async_tearDown = AsyncMock(
            side_effect=release_resources
        )
        summary = MagicMock()
        summary.start_section.return_value = MagicMock()
        summary.sections = []
        summary.async_upload_and_log_summary = AsyncMock()
        runner.test_summary = summary

        await runner.async_test_tearDown()

        self.assertTrue(resource_released)
        summary.cleanup.assert_called_once()

    async def test_task_self_cancellation_does_not_bound_resource_release(
        self,
    ) -> None:
        teardown_task = taac_types.Task(
            task_name="self-cancelling-cleanup", params=taac_types.Params()
        )
        runner = TaacRunner(
            _config(primary_teardown_tasks=[teardown_task]),
            logger=logging.getLogger("taac-self-cancel-resource-budget-test"),
        )
        runner.selected_ixia_candidate = runner.ixia_candidates[0]

        async def cancel_self(_task, *, index, total) -> None:
            current_task = asyncio.current_task()
            if current_task is None:
                self.fail("cleanup must run in an asyncio task")
            current_task.cancel()
            await asyncio.sleep(0)

        resource_released = False

        async def release_resources(**_kwargs) -> None:
            nonlocal resource_released
            await asyncio.sleep(0)
            resource_released = True

        runner._run_task_once = AsyncMock(side_effect=cancel_self)
        runner.test_setup_orchestrator.async_tearDown = AsyncMock(
            side_effect=release_resources
        )
        summary = MagicMock()
        summary.start_section.return_value = MagicMock()
        summary.sections = []
        summary.async_upload_and_log_summary = AsyncMock()
        runner.test_summary = summary

        with patch.object(_taac_runner, "_CLEANUP_CANCELLATION_GRACE_SECONDS", 0):
            with self.assertRaises(asyncio.CancelledError):
                await runner.async_test_tearDown()

        self.assertTrue(resource_released)
        summary.cleanup.assert_called_once()

    async def test_reporting_failure_is_not_masked_by_teardown_failure(self) -> None:
        runner = TaacRunner(
            _config(), logger=logging.getLogger("taac-teardown-reporting-failure-test")
        )
        runner.selected_ixia_candidate = runner.ixia_candidates[0]
        runner.run_teardown_tasks = AsyncMock(
            side_effect=RuntimeError("task cleanup failed")
        )
        runner.test_setup_orchestrator.async_tearDown = AsyncMock()
        runner._async_run_lifecycle_investigation_if_enabled = AsyncMock()
        summary = MagicMock()
        section = MagicMock()
        events = []
        summary.start_section.return_value = section
        summary.sections = []
        summary.end_section.side_effect = ValueError("summary reporting failed")

        async def verify_finalized_summary(_artifacts) -> None:
            events.append("upload")
            self.assertEqual(SectionStatus.FAIL, section.status)
            self.assertIn("summary reporting failed", section.error_message)

        summary.async_upload_and_log_summary = AsyncMock(
            side_effect=verify_finalized_summary
        )
        summary.cleanup.side_effect = lambda: events.append("cleanup")
        runner.test_summary = summary

        with self.assertRaises(ExceptionGroup) as raised:
            await runner.async_test_tearDown()

        self.assertEqual(
            ["task cleanup failed", "summary reporting failed"],
            [str(error) for error in raised.exception.exceptions],
        )
        self.assertEqual(summary.end_section.call_args.args[1], section.status)
        self.assertIn("task cleanup failed", section.error_message)
        self.assertIn("summary reporting failed", section.error_message)
        investigation_error = (
            runner._async_run_lifecycle_investigation_if_enabled.call_args.kwargs[
                "error"
            ]
        )
        self.assertIsInstance(investigation_error, ExceptionGroup)
        self.assertEqual(
            ["task cleanup failed", "summary reporting failed"],
            [str(error) for error in investigation_error.exceptions],
        )
        summary.cleanup.assert_called_once()
        self.assertEqual(["upload", "cleanup"], events)

    async def test_upload_failure_still_cleans_up(self) -> None:
        runner = TaacRunner(
            _config(), logger=logging.getLogger("taac-summary-upload-failure-test")
        )
        runner.selected_ixia_candidate = runner.ixia_candidates[0]
        runner.run_teardown_tasks = AsyncMock()
        runner.test_setup_orchestrator.async_tearDown = AsyncMock()
        upload_failure = RuntimeError("summary upload failed")
        summary = MagicMock()
        section = MagicMock()
        summary.start_section.return_value = section
        summary.sections = []
        summary.async_upload_and_log_summary = AsyncMock(side_effect=upload_failure)
        runner.test_summary = summary

        with self.assertRaises(RuntimeError) as raised:
            await runner.async_test_tearDown()

        self.assertIs(upload_failure, raised.exception)
        summary.cleanup.assert_called_once()
        self.assertEqual(SectionStatus.FAIL, section.status)
        self.assertIn("summary upload failed", section.error_message)

    async def test_synchronous_upload_factory_failure_still_cleans_up(self) -> None:
        runner = TaacRunner(
            _config(), logger=logging.getLogger("taac-sync-upload-failure-test")
        )
        runner.selected_ixia_candidate = runner.ixia_candidates[0]
        runner.run_teardown_tasks = AsyncMock()
        runner.test_setup_orchestrator.async_tearDown = AsyncMock()
        upload_failure = RuntimeError("summary upload factory failed")
        summary = MagicMock()
        section = MagicMock()
        summary.start_section.return_value = section
        summary.sections = []
        summary.async_upload_and_log_summary = MagicMock(side_effect=upload_failure)
        runner.test_summary = summary

        with self.assertRaises(RuntimeError) as raised:
            await runner.async_test_tearDown()

        self.assertIs(upload_failure, raised.exception)
        summary.cleanup.assert_called_once()
        self.assertEqual(SectionStatus.FAIL, section.status)
        self.assertIn("summary upload factory failed", section.error_message)

    async def test_summary_cleanup_failure_does_not_mask_teardown_failure(self) -> None:
        runner = TaacRunner(
            _config(), logger=logging.getLogger("taac-summary-cleanup-failure-test")
        )
        runner.selected_ixia_candidate = runner.ixia_candidates[0]
        teardown_failure = RuntimeError("task cleanup failed")
        summary_cleanup_failure = ValueError("summary cleanup failed")
        runner.run_teardown_tasks = AsyncMock(side_effect=teardown_failure)
        runner.test_setup_orchestrator.async_tearDown = AsyncMock()
        runner._async_run_lifecycle_investigation_if_enabled = AsyncMock()
        summary = MagicMock()
        section = MagicMock()
        summary.start_section.return_value = section
        summary.sections = []
        summary.async_upload_and_log_summary = AsyncMock()
        summary.cleanup.side_effect = summary_cleanup_failure
        runner.test_summary = summary

        with self.assertRaises(ExceptionGroup) as raised:
            await runner.async_test_tearDown()

        self.assertEqual(
            (teardown_failure, summary_cleanup_failure),
            raised.exception.exceptions,
        )
        self.assertIn("task cleanup failed", section.error_message)
        self.assertIn("summary cleanup failed", section.error_message)

    async def test_early_cancellation_still_runs_tasks_and_releases_resources(
        self,
    ) -> None:
        teardown_task = taac_types.Task(
            task_name="fibagent-restore", params=taac_types.Params()
        )
        runner = TaacRunner(
            _config(primary_teardown_tasks=[teardown_task]),
            logger=logging.getLogger("taac-cancelled-teardown-test"),
        )
        runner.selected_ixia_candidate = runner.ixia_candidates[0]

        async def cancel_during_initial_phase(_executor) -> None:
            current_task = asyncio.current_task()
            if current_task is None:
                self.fail("teardown must run in an asyncio task")
            current_task.cancel()
            await asyncio.sleep(0)

        runner.teardown_period_task_executor_if_exists = AsyncMock(
            side_effect=cancel_during_initial_phase
        )
        runner.run_teardown_tasks = AsyncMock()
        runner.test_setup_orchestrator.async_tearDown = AsyncMock()
        summary = MagicMock()
        summary.start_section.return_value = MagicMock()
        summary.sections = []
        summary.async_upload_and_log_summary = AsyncMock()
        runner.test_summary = summary

        teardown = asyncio.create_task(runner.async_test_tearDown())
        with self.assertRaises(asyncio.CancelledError):
            await teardown

        self.assertTrue(teardown.cancelled())
        self.assertEqual(0, teardown.cancelling())
        runner.run_teardown_tasks.assert_awaited_once_with(
            (teardown_task,), cancellation_budget=ANY
        )
        runner.test_setup_orchestrator.async_tearDown.assert_awaited_once()
        self.assertEqual(
            "TAAC test-config teardown was cancelled",
            summary.end_section.call_args.args[2],
        )

    async def test_retry_sleep_cancellation_still_releases_resources(self) -> None:
        teardown_task = taac_types.Task(
            task_name="fibagent-restore", params=taac_types.Params()
        )
        runner = TaacRunner(
            _config(primary_teardown_tasks=[teardown_task]),
            logger=logging.getLogger("taac-retry-cancellation-test"),
        )
        runner.selected_ixia_candidate = runner.ixia_candidates[0]
        runner._run_task_once = AsyncMock(
            side_effect=RuntimeError("cleanup failed before retry")
        )
        runner.test_setup_orchestrator.async_tearDown = AsyncMock()
        summary = MagicMock()
        summary.start_section.return_value = MagicMock()
        summary.sections = []
        summary.async_upload_and_log_summary = AsyncMock()
        runner.test_summary = summary
        original_sleep = asyncio.sleep

        async def cancel_during_retry(_delay) -> None:
            current_task = asyncio.current_task()
            if current_task is None:
                self.fail("teardown must run in an asyncio task")
            current_task.cancel()
            await original_sleep(0)

        with patch.object(asyncio, "sleep", side_effect=cancel_during_retry):
            teardown = asyncio.create_task(runner.async_test_tearDown())
            with self.assertRaises(asyncio.CancelledError):
                await teardown

        self.assertTrue(teardown.cancelled())
        self.assertEqual(0, teardown.cancelling())
        runner._run_task_once.assert_awaited_once()
        runner.test_setup_orchestrator.async_tearDown.assert_awaited_once()

    async def test_cancelled_task_failures_reach_summary_and_investigation(
        self,
    ) -> None:
        cancellation = asyncio.CancelledError()
        failure = RuntimeError("FibAgent restore failed")
        first_task = taac_types.Task(
            task_name="first-cleanup", params=taac_types.Params()
        )
        restore_task = taac_types.Task(
            task_name="fibagent-restore", params=taac_types.Params()
        )
        runner = TaacRunner(
            _config(primary_teardown_tasks=[first_task, restore_task]),
            logger=logging.getLogger("taac-cancelled-task-failure-test"),
        )
        runner.selected_ixia_candidate = runner.ixia_candidates[0]

        async def run_one(task, *, index, total) -> None:
            if task.task_name == first_task.task_name:
                raise cancellation
            if task.task_name == restore_task.task_name:
                raise failure

        runner._run_task_once = AsyncMock(side_effect=run_one)
        runner.test_setup_orchestrator.async_tearDown = AsyncMock()
        runner._async_run_lifecycle_investigation_if_enabled = AsyncMock()
        summary = MagicMock()
        section = MagicMock()
        summary.start_section.return_value = section
        summary.sections = []
        summary.async_upload_and_log_summary = AsyncMock()
        runner.test_summary = summary

        with self.assertRaises(asyncio.CancelledError) as raised:
            await runner.async_test_tearDown()

        self.assertIsInstance(raised.exception, asyncio.CancelledError)
        self.assertIn("FibAgent restore failed", section.error_message)
        investigation_error = (
            runner._async_run_lifecycle_investigation_if_enabled.call_args.kwargs[
                "error"
            ]
        )
        self.assertIs(failure, investigation_error)

    async def test_orchestrator_cleanup_finishes_before_cancellation_propagates(
        self,
    ) -> None:
        runner = TaacRunner(
            _config(),
            logger=logging.getLogger("taac-shielded-resource-cleanup-test"),
        )
        runner.selected_ixia_candidate = runner.ixia_candidates[0]
        runner.run_teardown_tasks = AsyncMock()
        cleanup_started = asyncio.Event()
        release_cleanup = asyncio.Event()
        cleanup_finished = False

        async def cleanup_resources(**_kwargs) -> None:
            nonlocal cleanup_finished
            cleanup_started.set()
            await release_cleanup.wait()
            cleanup_finished = True

        runner.test_setup_orchestrator.async_tearDown = AsyncMock(
            side_effect=cleanup_resources
        )
        summary = MagicMock()
        summary.start_section.return_value = MagicMock()
        summary.sections = []
        summary.async_upload_and_log_summary = AsyncMock()
        runner.test_summary = summary

        teardown = asyncio.create_task(runner.async_test_tearDown())
        await cleanup_started.wait()
        teardown.cancel()
        await asyncio.sleep(0)
        self.assertFalse(teardown.done())
        release_cleanup.set()

        with self.assertRaises(asyncio.CancelledError):
            await teardown

        self.assertTrue(cleanup_finished)
        runner.test_setup_orchestrator.async_tearDown.assert_awaited_once()

    async def test_cancellation_retains_resource_cleanup_failure_as_note(self) -> None:
        runner = TaacRunner(
            _config(),
            logger=logging.getLogger("taac-cancelled-cleanup-failure-test"),
        )
        runner.selected_ixia_candidate = runner.ixia_candidates[0]
        cancellation = asyncio.CancelledError()
        runner.teardown_period_task_executor_if_exists = AsyncMock(
            side_effect=cancellation
        )
        runner.run_teardown_tasks = AsyncMock()
        runner.test_setup_orchestrator.async_tearDown = AsyncMock(
            side_effect=RuntimeError("resource cleanup failed")
        )
        summary = MagicMock()
        summary.start_section.return_value = MagicMock()
        summary.sections = []
        summary.async_upload_and_log_summary = AsyncMock()
        runner.test_summary = summary

        with self.assertRaises(asyncio.CancelledError) as raised:
            await runner.async_test_tearDown()

        self.assertIs(cancellation, raised.exception)
        self.assertIn("resource cleanup failed", cancellation.__notes__[-1])
        teardown_detail = summary.end_section.call_args.args[2]
        self.assertIn("TAAC test-config teardown was cancelled", teardown_detail)
        self.assertIn("RuntimeError: resource cleanup failed", teardown_detail)

    async def test_setup_only_strict_teardown_failure_fails_run(self) -> None:
        config = _config()
        logger = logging.getLogger("taac-fallback-setup-only-test")
        logger.setLevel(logging.INFO)
        runner = TaacRunner(config, setup_only=True, logger=logger)
        runner.selected_ixia_candidate = runner.ixia_candidates[0]
        runner.run_tasks = AsyncMock()
        runner.test_setup_orchestrator.async_tearDown = AsyncMock(
            side_effect=RuntimeError("session delete failed")
        )
        summary = MagicMock()
        summary.start_section.return_value = MagicMock()
        summary.sections = []
        summary.async_upload_and_log_summary = AsyncMock()
        runner.test_summary = summary

        with self.assertRaisesRegex(RuntimeError, "session delete failed"):
            await runner.async_test_tearDown()

        runner.test_setup_orchestrator.async_tearDown.assert_awaited_once_with(
            strict_ixia_cleanup=True
        )
