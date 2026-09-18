# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from __future__ import annotations

import asyncio
import json
import typing as t
from collections.abc import Awaitable
from unittest.mock import AsyncMock, MagicMock, patch

from later.unittest import TestCase
from taac.internal.tasks.openr_scale_isolation_task import (
    OpenRScaleIsolationTask,
)
from taac.task_definitions import (
    create_openr_scale_isolation_task,
)
from taac.tasks.registry import TASK_NAME_TO_CLASS
from openr.tests.scale.scripts.kvstore_cleanup import CleanupError, CleanupSummary


_MODULE = "neteng.test_infra.dne.taac.internal.tasks.openr_scale_isolation_task"
_PARAMS: dict[str, object] = {
    "hosts": ["first.example", "second.example"],
    "helper_hostname": "helper.example",
    "scale_tester_remote_path": "/mnt/flash/scale_test_server",
    "area": "0",
    "ttl_ms": 30_000,
    "wait_sec": 90,
    "batch_size": 500,
}


def _task() -> OpenRScaleIsolationTask:
    return OpenRScaleIsolationTask(logger=MagicMock())


class OpenRScaleIsolationTaskTest(TestCase):
    def test_factory_serializes_exact_parameters(self) -> None:
        task = create_openr_scale_isolation_task(
            hosts=["first.example", "second.example"],
            helper_hostname="helper.example",
            scale_tester_remote_path="/mnt/flash/scale_test_server",
            area="0",
            ttl_ms=31_000,
            wait_sec=91,
            batch_size=499,
        )

        self.assertEqual("openr_scale_isolation", task.task_name)
        self.assertEqual(
            {
                "hosts": ["first.example", "second.example"],
                "helper_hostname": "helper.example",
                "scale_tester_remote_path": "/mnt/flash/scale_test_server",
                "area": "0",
                "ttl_ms": 31_000,
                "wait_sec": 91,
                "batch_size": 499,
            },
            json.loads(str(task.params.json_params)),
        )

    def test_factory_rejects_invalid_parameters(self) -> None:
        cases = (
            {"hosts": []},
            {"hosts": [""]},
            {"hosts": [" "]},
            {"hosts": "first.example"},
            {"helper_hostname": ""},
            {"scale_tester_remote_path": "relative/path"},
            {"ttl_ms": 0},
            {"wait_sec": 0},
            {"batch_size": 0},
            {"ttl_ms": 30_000, "wait_sec": 30},
        )
        for override in cases:
            kwargs: dict[str, t.Any] = {
                "hosts": ["first.example"],
                "helper_hostname": "helper.example",
                "scale_tester_remote_path": "/mnt/flash/scale_test_server",
                **override,
            }
            with self.subTest(override=override), self.assertRaises(ValueError):
                create_openr_scale_isolation_task(**kwargs)

    async def test_runtime_rejects_whitespace_host_before_device_access(self) -> None:
        params = dict(_PARAMS)
        params["hosts"] = [" "]
        get_driver = AsyncMock()
        with patch(f"{_MODULE}.async_get_device_driver", get_driver):
            with self.assertRaisesRegex(ValueError, "hosts"):
                await _task().run(params)
        get_driver.assert_not_awaited()

    def test_registered_only_under_internal_registry(self) -> None:
        self.assertIs(
            OpenRScaleIsolationTask, TASK_NAME_TO_CLASS["openr_scale_isolation"]
        )

    async def test_stops_helper_before_exact_cleanup_delegation(self) -> None:
        events: list[str] = []
        driver = MagicMock()

        async def stop(command: str) -> str:
            events.append(f"stop:{command}")
            return ""

        async def cleanup(*args: object, **kwargs: object) -> CleanupSummary:
            events.append("cleanup")
            self.assertEqual(("first.example", "second.example"), args[0])
            self.assertEqual(
                {"area": "0", "ttl_ms": 30_000, "wait_sec": 90, "batch_size": 500},
                kwargs,
            )
            return CleanupSummary(
                marked_by_host={"first.example": 0, "second.example": 0},
                final_survivors_by_host={},
                host_failures={},
            )

        driver.async_run_cmd_on_shell = AsyncMock(side_effect=stop)
        with (
            patch(f"{_MODULE}.async_get_device_driver", AsyncMock(return_value=driver)),
            patch(f"{_MODULE}.expire_scale_keys_and_verify", side_effect=cleanup),
        ):
            await _task().run(dict(_PARAMS))

        self.assertEqual("cleanup", events[-1])
        self.assertIn("pkill -f --", events[0])
        self.assertIn("[/]mnt/flash/scale_test_server", events[0])

    async def test_waits_until_helper_process_is_gone_before_cleanup(self) -> None:
        commands: list[str] = []
        cleanup_started = asyncio.Event()
        driver = MagicMock()

        async def shell(command: str) -> str:
            commands.append(command)
            if "pkill -f --" in command:
                return ""
            return f"{command}\n4321\n" if len(commands) == 2 else f"{command}\n"

        async def cleanup(*_args: object, **_kwargs: object) -> CleanupSummary:
            self.assertEqual(3, len(commands))
            cleanup_started.set()
            return CleanupSummary({}, {}, {})

        driver.async_run_cmd_on_shell = AsyncMock(side_effect=shell)
        with (
            patch(f"{_MODULE}.async_get_device_driver", AsyncMock(return_value=driver)),
            patch(f"{_MODULE}.expire_scale_keys_and_verify", side_effect=cleanup),
            patch(f"{_MODULE}.asyncio.sleep", AsyncMock()),
        ):
            await _task().run(dict(_PARAMS))

        self.assertTrue(cleanup_started.is_set())
        self.assertTrue(commands[1].startswith("bash pgrep -f -- "))
        self.assertEqual(commands[1], commands[2])

    async def test_echo_only_pgrep_output_allows_cleanup(self) -> None:
        driver = MagicMock()

        async def shell(command: str) -> str:
            return f"{command}\n"

        driver.async_run_cmd_on_shell = AsyncMock(side_effect=shell)
        cleanup = AsyncMock(return_value=CleanupSummary({}, {}, {}))
        with (
            patch(f"{_MODULE}.async_get_device_driver", AsyncMock(return_value=driver)),
            patch(f"{_MODULE}.expire_scale_keys_and_verify", cleanup),
        ):
            await _task().run(dict(_PARAMS))

        cleanup.assert_awaited_once()

    async def test_eos_prompt_echo_without_newline_allows_cleanup(self) -> None:
        driver = MagicMock()

        async def shell(command: str) -> str:
            if "pkill -f --" in command:
                return ""
            return f"eb02.lab.ash6# \x1b[15C{command}"

        driver.async_run_cmd_on_shell = AsyncMock(side_effect=shell)
        cleanup = AsyncMock(return_value=CleanupSummary({}, {}, {}))
        with (
            patch(f"{_MODULE}.async_get_device_driver", AsyncMock(return_value=driver)),
            patch(f"{_MODULE}.expire_scale_keys_and_verify", cleanup),
            patch(f"{_MODULE}._STOP_TIMEOUT_SECONDS", 0.0),
        ):
            await _task().run(dict(_PARAMS))

        cleanup.assert_awaited_once()

    async def _assert_hung_stop_phase_times_out_and_runs_cleanup(  # noqa: C901
        self, phase: str
    ) -> None:
        phase_started = asyncio.Event()
        release_phase = asyncio.Event()
        phase_finished = asyncio.Event()
        cleanup_started = asyncio.Event()
        driver = MagicMock()

        async def hang() -> str:
            phase_started.set()
            try:
                await release_phase.wait()
            finally:
                phase_finished.set()
            return ""

        async def get_driver(_hostname: str) -> object:
            if phase == "driver":
                await hang()
            return driver

        async def shell(command: str) -> str:
            if phase == "pkill" and "pkill -f --" in command:
                return await hang()
            if phase == "pgrep" and "pgrep -f --" in command:
                return await hang()
            return ""

        async def cleanup(*_args: object, **_kwargs: object) -> CleanupSummary:
            cleanup_started.set()
            return CleanupSummary({}, {}, {})

        driver.async_run_cmd_on_shell = AsyncMock(side_effect=shell)
        error: RuntimeError | None = None
        with (
            patch(f"{_MODULE}._STOP_TIMEOUT_SECONDS", 0.01, create=True),
            patch(f"{_MODULE}.async_get_device_driver", side_effect=get_driver),
            patch(f"{_MODULE}.expire_scale_keys_and_verify", side_effect=cleanup),
        ):
            running = asyncio.create_task(_task().run(dict(_PARAMS)))
            await phase_started.wait()
            try:
                cleanup_before_release = await asyncio.wait_for(
                    cleanup_started.wait(), timeout=0.2
                )
            except asyncio.TimeoutError:
                cleanup_before_release = False
            finally:
                release_phase.set()
            try:
                await running
            except RuntimeError as caught:
                error = caught

        self.assertTrue(cleanup_before_release)
        self.assertTrue(phase_finished.is_set())
        self.assertIsNotNone(error)
        self.assertIn("process stop failed", str(error))

    async def _assert_cancellation_during_hung_stop_phase_joins_cleanup(
        self, phase: str
    ) -> None:
        phase_started = asyncio.Event()
        release_phase = asyncio.Event()
        phase_finished = asyncio.Event()
        cleanup_started = asyncio.Event()
        driver = MagicMock()

        async def hang() -> str:
            phase_started.set()
            try:
                await release_phase.wait()
            finally:
                phase_finished.set()
            return ""

        async def get_driver(_hostname: str) -> object:
            if phase == "driver":
                await hang()
            return driver

        async def shell(command: str) -> str:
            if phase == "pkill" and "pkill -f --" in command:
                return await hang()
            if phase == "pgrep" and "pgrep -f --" in command:
                return await hang()
            return ""

        async def cleanup(*_args: object, **_kwargs: object) -> CleanupSummary:
            cleanup_started.set()
            return CleanupSummary({}, {}, {})

        driver.async_run_cmd_on_shell = AsyncMock(side_effect=shell)
        with (
            patch(f"{_MODULE}._STOP_TIMEOUT_SECONDS", 0.01, create=True),
            patch(f"{_MODULE}.async_get_device_driver", side_effect=get_driver),
            patch(f"{_MODULE}.expire_scale_keys_and_verify", side_effect=cleanup),
        ):
            running = asyncio.create_task(_task().run(dict(_PARAMS)))
            await phase_started.wait()
            running.cancel()
            try:
                cleanup_before_release = await asyncio.wait_for(
                    cleanup_started.wait(), timeout=0.2
                )
            except asyncio.TimeoutError:
                cleanup_before_release = False
            finally:
                release_phase.set()
            with self.assertRaises(asyncio.CancelledError):
                await running

        self.assertTrue(cleanup_before_release)
        self.assertTrue(phase_finished.is_set())

    async def test_hung_driver_acquisition_times_out_and_runs_cleanup(self) -> None:
        await self._assert_hung_stop_phase_times_out_and_runs_cleanup("driver")

    async def test_hung_pkill_times_out_and_runs_cleanup(self) -> None:
        await self._assert_hung_stop_phase_times_out_and_runs_cleanup("pkill")

    async def test_hung_pgrep_times_out_and_runs_cleanup(self) -> None:
        await self._assert_hung_stop_phase_times_out_and_runs_cleanup("pgrep")

    async def test_cancellation_during_hung_driver_acquisition_joins_cleanup(
        self,
    ) -> None:
        await self._assert_cancellation_during_hung_stop_phase_joins_cleanup("driver")

    async def test_cancellation_during_hung_pkill_joins_cleanup(self) -> None:
        await self._assert_cancellation_during_hung_stop_phase_joins_cleanup("pkill")

    async def test_cancellation_during_hung_pgrep_joins_cleanup(self) -> None:
        await self._assert_cancellation_during_hung_stop_phase_joins_cleanup("pgrep")

    async def test_process_stop_failure_still_attempts_cleanup_and_is_aggregated(
        self,
    ) -> None:
        driver = MagicMock()
        driver.async_run_cmd_on_shell = AsyncMock(
            side_effect=RuntimeError("helper transport failed")
        )
        cleanup = AsyncMock(
            return_value=CleanupSummary(
                marked_by_host={"first.example": 0, "second.example": 0},
                final_survivors_by_host={},
                host_failures={},
            )
        )

        with (
            patch(f"{_MODULE}.async_get_device_driver", AsyncMock(return_value=driver)),
            patch(f"{_MODULE}.expire_scale_keys_and_verify", cleanup),
        ):
            with self.assertRaisesRegex(RuntimeError, "helper transport failed"):
                await _task().run(dict(_PARAMS))

        cleanup.assert_awaited_once()

    async def test_cleanup_failure_includes_host_and_survivor_context(self) -> None:
        driver = MagicMock()
        driver.async_run_cmd_on_shell = AsyncMock(return_value="")
        cleanup = AsyncMock(
            side_effect=CleanupError(
                "cleanup failed; host_failures={'first.example': 'unreachable'}; "
                "survivors={'second.example': ('adj:leaf-9',)}"
            )
        )

        with (
            patch(f"{_MODULE}.async_get_device_driver", AsyncMock(return_value=driver)),
            patch(f"{_MODULE}.expire_scale_keys_and_verify", cleanup),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "first.example.*unreachable.*second.example.*adj:leaf-9",
            ):
                await _task().run(dict(_PARAMS))

    async def test_cancellation_during_helper_stop_joins_ordered_cleanup(self) -> None:
        stop_started = asyncio.Event()
        release_stop = asyncio.Event()
        cleanup_finished = asyncio.Event()
        driver = MagicMock()

        async def stop(_command: str) -> str:
            stop_started.set()
            await release_stop.wait()
            return ""

        async def cleanup(*_args: object, **_kwargs: object) -> CleanupSummary:
            cleanup_finished.set()
            return CleanupSummary({}, {}, {})

        driver.async_run_cmd_on_shell = AsyncMock(side_effect=stop)
        with (
            patch(f"{_MODULE}.async_get_device_driver", AsyncMock(return_value=driver)),
            patch(f"{_MODULE}.expire_scale_keys_and_verify", side_effect=cleanup),
        ):
            running = asyncio.create_task(_task().run(dict(_PARAMS)))
            await stop_started.wait()
            running.cancel()
            release_stop.set()
            with self.assertRaises(asyncio.CancelledError):
                await running

        self.assertTrue(cleanup_finished.is_set())

    async def test_repeated_cancellation_during_stop_still_joins_cleanup(self) -> None:
        stop_started = asyncio.Event()
        stop_finished = asyncio.Event()
        join_started = asyncio.Event()
        cleanup_finished = asyncio.Event()
        driver = MagicMock()

        async def stop(_command: str) -> str:
            stop_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                stop_finished.set()
            return ""

        async def cleanup(*_args: object, **_kwargs: object) -> CleanupSummary:
            cleanup_finished.set()
            return CleanupSummary({}, {}, {})

        shield_calls = 0
        original_shield = asyncio.shield

        def shield(
            awaitable: Awaitable[CleanupSummary] | asyncio.Future[CleanupSummary],
        ) -> asyncio.Future[CleanupSummary]:
            nonlocal shield_calls
            shield_calls += 1
            if shield_calls == 2:
                join_started.set()
            return original_shield(awaitable)

        driver.async_run_cmd_on_shell = AsyncMock(side_effect=stop)
        with (
            patch(f"{_MODULE}._STOP_TIMEOUT_SECONDS", 0.01),
            patch(f"{_MODULE}.async_get_device_driver", AsyncMock(return_value=driver)),
            patch(f"{_MODULE}.expire_scale_keys_and_verify", side_effect=cleanup),
            patch(f"{_MODULE}.asyncio.shield", side_effect=shield),
        ):
            running = asyncio.create_task(_task().run(dict(_PARAMS)))
            await stop_started.wait()
            running.cancel()
            await join_started.wait()
            running.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await running

        self.assertTrue(stop_finished.is_set())
        self.assertTrue(cleanup_finished.is_set())

    async def test_cancellation_after_partial_mark_joins_cleanup(self) -> None:
        cleanup_started = asyncio.Event()
        release_cleanup = asyncio.Event()
        cleanup_finished = asyncio.Event()
        driver = MagicMock()
        driver.async_run_cmd_on_shell = AsyncMock(return_value="")

        async def cleanup(*_args: object, **_kwargs: object) -> CleanupSummary:
            cleanup_started.set()
            await release_cleanup.wait()
            cleanup_finished.set()
            return CleanupSummary({}, {}, {})

        with (
            patch(f"{_MODULE}.async_get_device_driver", AsyncMock(return_value=driver)),
            patch(f"{_MODULE}.expire_scale_keys_and_verify", side_effect=cleanup),
        ):
            running = asyncio.create_task(_task().run(dict(_PARAMS)))
            await cleanup_started.wait()
            running.cancel()
            release_cleanup.set()
            with self.assertRaises(asyncio.CancelledError):
                await running

        self.assertTrue(cleanup_finished.is_set())

    async def test_cancellation_join_timeout_cancels_and_reaps_child(self) -> None:
        child_started = asyncio.Event()
        child_cancelled = asyncio.Event()

        async def isolation(**_kwargs: object) -> CleanupSummary:
            child_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                child_cancelled.set()
            return CleanupSummary({}, {}, {})

        async def time_out(_awaitable: object, *, timeout: float) -> None:
            self.assertAlmostEqual(108, timeout, delta=0.1)
            raise asyncio.TimeoutError

        with (
            patch(f"{_MODULE}._STOP_TIMEOUT_SECONDS", 11),
            patch(f"{_MODULE}._JOIN_GRACE_SECONDS", 7),
            patch(f"{_MODULE}._ordered_isolation", side_effect=isolation),
            patch(f"{_MODULE}.asyncio.wait_for", side_effect=time_out),
        ):
            running = asyncio.create_task(_task().run(dict(_PARAMS)))
            await child_started.wait()
            running.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await running

        self.assertTrue(child_cancelled.is_set())

    async def test_empty_cleanup_is_idempotent(self) -> None:
        driver = MagicMock()
        driver.async_run_cmd_on_shell = AsyncMock(return_value="")
        cleanup = AsyncMock(return_value=CleanupSummary({}, {}, {}))

        with (
            patch(f"{_MODULE}.async_get_device_driver", AsyncMock(return_value=driver)),
            patch(f"{_MODULE}.expire_scale_keys_and_verify", cleanup),
        ):
            task = _task()
            await task.run(dict(_PARAMS))
            await task.run(dict(_PARAMS))

        self.assertEqual(2, cleanup.await_count)
