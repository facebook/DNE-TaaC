# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import asyncio
import logging
import multiprocessing
import sys
import time
import typing as t

from taac.constants import PeriodicCheckResult
from neteng.test_infra.dne.taac.ixia.taac_ixia import TaacIxia as Ixia
from taac.libs.parameter_evaluator import ParameterEvaluator
from taac.tasks.utils import get_task_obj
from taac.utils.common import async_everpaste_file
from taac.utils.oss_taac_lib_utils import ConsoleFileLogger
from taac.test_as_a_config import types as taac_types


class PeriodicTaskWorker:
    def __init__(
        self,
        periodic_task: taac_types.PeriodicTask,
        terminate_callback: t.Callable,
        main_logger: logging.Logger,
        ixia: t.Optional[Ixia] = None,
    ):
        self.logger = ConsoleFileLogger(multiprocessing.current_process().name)
        # pyre-fixme[16]: `ConsoleFileLogger` has no attribute `set_console_log_level`.
        self.logger.set_console_log_level(logging.CRITICAL + 1)
        self.periodic_task = periodic_task
        self.main_logger = main_logger
        self.terminate_callback = terminate_callback
        self.has_error = multiprocessing.Value("b", False)
        self._stop_requested = False
        self._log_everpaste_url: t.Optional[str] = None
        # Create shared dictionaries for data collection and params across processes
        manager = multiprocessing.Manager()
        self.shared_data = manager.dict()
        self.shared_params = manager.dict()
        self.task_obj = get_task_obj(
            self.periodic_task.task,
            logger=self.logger,
            ixia=ixia,
            # pyrefly: ignore [bad-argument-type]
            shared_data=self.shared_data,
            # pyrefly: ignore [bad-argument-type]
            shared_params=self.shared_params,
        )

    def run(self) -> None:
        max_runtime = self.periodic_task.max_runtime or sys.maxsize
        start_time = time.time()
        success_count = 0

        while not self._stop_requested:
            if time.time() - start_time > max_runtime:
                break
            try:
                dict_params = ParameterEvaluator().evaluate(
                    self.periodic_task.params_list[
                        success_count % len(self.periodic_task.params_list)
                    ]
                    if self.periodic_task.params_list
                    else self.periodic_task.task.params
                )
                self.logger.info(
                    f"Running periodic task {self.periodic_task.name} with params {dict_params}"
                )
                asyncio.run(self.task_obj._run(dict_params))
                time.sleep(self.periodic_task.interval)
                success_count += 1
            except Exception as ex:
                self.logger.exception(f"Exception occurred in periodic task: {ex}")
                if self.periodic_task.retryable:
                    self.logger.info("Sleeping 60s before retrying periodic task")
                    time.sleep(self.periodic_task.exception_sleep_time)
                    continue
                elif self.periodic_task.terminate_on_error:
                    self.terminate_callback()
                self.has_error.value = True
                break

    async def run_final_check(self) -> PeriodicCheckResult:
        task_key = f"__{self.task_obj.__class__.NAME}__"
        prefix = f"{task_key}:"
        entry_count = sum(1 for k in self.shared_data.keys() if k.startswith(prefix))
        self.main_logger.debug(
            f"Periodic task '{task_key}': shared_data entries={entry_count}, "
            f"task_obj._data entries={len(self.task_obj._data)}"
        )
        return await self.task_obj.run_final_check()

    async def teardown(self) -> str:
        """
        Uploads the periodic task log to everpaste.

        Returns:
            The everpaste URL for the log file
        """
        # pyre-fixme[16]: `ConsoleFileLogger` has no attribute `get_log_file`.
        log_file = self.logger.get_log_file()
        everpaste_url = await async_everpaste_file(log_file)
        self.main_logger.info(
            f"Log for periodic task {self.periodic_task.name} has been everpasted to: {everpaste_url}"
        )
        # Store for access in run_final_check
        self._log_everpaste_url = everpaste_url
        return everpaste_url

    def stop(self) -> None:
        """Signal the worker to stop."""
        self._stop_requested = True
