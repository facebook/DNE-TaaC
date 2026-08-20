# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import asyncio
import logging
import multiprocessing
import sys
import time
import typing as t

from taac.constants import PeriodicCheckResult
from taac.ixia.taac_ixia import (  # oss-rewrite (force ShipIt re-export to taac.* root)
    TaacIxia as Ixia,
)
from taac.libs.parameter_evaluator import ParameterEvaluator
from taac.tasks.utils import get_task_obj
from taac.utils.common import async_everpaste_file
from taac.utils.driver_factory import (
    DriverBootstrapPayload,
    install_driver_bootstrap_data,
)
from taac.utils.oss_taac_lib_utils import ConsoleFileLogger
from taac.test_as_a_config import types as taac_types


_MANAGER_INIT_RETRY_COUNT: int = 3
_MANAGER_INIT_RETRY_BACKOFF_S: float = 2.0
_LOG_FILE_KEY: str = "log_file"


def _make_sync_manager(
    mp_context: multiprocessing.context.BaseContext,
    logger: logging.Logger,
) -> t.Any:
    """Construct a context-local Manager with bounded handshake retry."""
    last_exc: BaseException | None = None
    for attempt in range(1, _MANAGER_INIT_RETRY_COUNT + 1):
        try:
            return mp_context.Manager()
        except (EOFError, OSError) as error:
            last_exc = error
            if attempt < _MANAGER_INIT_RETRY_COUNT:
                logger.warning(
                    f"multiprocessing manager init failed "
                    f"(attempt {attempt}/{_MANAGER_INIT_RETRY_COUNT}): "
                    f"{error!r}; sleeping "
                    f"{_MANAGER_INIT_RETRY_BACKOFF_S}s before retry"
                )
                time.sleep(_MANAGER_INIT_RETRY_BACKOFF_S)
    assert last_exc is not None
    raise last_exc


def _create_worker_logger(name: str, shared_state: t.Any) -> ConsoleFileLogger:
    logger = ConsoleFileLogger(name)
    shared_state[_LOG_FILE_KEY] = _get_worker_log_file(logger)
    logger_with_level = t.cast(t.Any, logger)
    if hasattr(logger_with_level, "set_console_log_level"):
        logger_with_level.set_console_log_level(logging.CRITICAL + 1)
    else:
        logger_with_level._console_handler.setLevel(logging.CRITICAL + 1)
    return logger


def _get_worker_log_file(logger: ConsoleFileLogger) -> str:
    logger_with_file = t.cast(t.Any, logger)
    if hasattr(logger_with_file, "get_log_file"):
        return logger_with_file.get_log_file()
    return logger_with_file.log_file


def _run_periodic_task_loop(
    periodic_task: taac_types.PeriodicTask,
    task_obj: t.Any,
    logger: logging.Logger,
    stop_event: t.Any,
    has_error: t.Any,
) -> None:
    max_runtime = periodic_task.max_runtime or sys.maxsize
    start_time = time.time()
    success_count = 0

    while not stop_event.is_set():
        if time.time() - start_time > max_runtime:
            break
        try:
            dict_params = ParameterEvaluator().evaluate(
                periodic_task.params_list[
                    success_count % len(periodic_task.params_list)
                ]
                if periodic_task.params_list
                else periodic_task.task.params
            )
            logger.info(
                f"Running periodic task {periodic_task.name} with params {dict_params}"
            )
            asyncio.run(task_obj._run(dict_params))
            success_count += 1
            stop_event.wait(periodic_task.interval)
        except Exception as error:
            logger.exception(f"Exception occurred in periodic task: {error}")
            if periodic_task.retryable:
                logger.info(
                    f"Sleeping {periodic_task.exception_sleep_time}s before "
                    "retrying periodic task"
                )
                stop_event.wait(periodic_task.exception_sleep_time)
                continue

            has_error.value = True
            if periodic_task.terminate_on_error:
                stop_event.set()
            break


def run_periodic_task_process(
    periodic_task: taac_types.PeriodicTask,
    driver_bootstrap: DriverBootstrapPayload,
    shared_data: t.Any,
    shared_params: t.Any,
    shared_state: t.Any,
    stop_event: t.Any,
    has_error: t.Any,
) -> None:
    """Run a non-IXIA periodic task from a forkserver-safe entrypoint."""
    logger: logging.Logger | None = None
    try:
        logger = _create_worker_logger(
            multiprocessing.current_process().name,
            shared_state,
        )
        install_driver_bootstrap_data(driver_bootstrap, logger)
        task_obj = get_task_obj(
            periodic_task.task,
            logger=logger,
            shared_data=shared_data,
            shared_params=shared_params,
        )
        _run_periodic_task_loop(
            periodic_task,
            task_obj,
            logger,
            stop_event,
            has_error,
        )
    except Exception:
        try:
            has_error.value = True
        except Exception:
            pass
        if periodic_task.terminate_on_error:
            try:
                stop_event.set()
            except Exception:
                pass
        try:
            (logger or logging.getLogger(__name__)).exception(
                f"Periodic task {periodic_task.name} terminated with an unexpected error"
            )
        except Exception:
            pass


class PeriodicTaskWorker:
    def __init__(
        self,
        periodic_task: taac_types.PeriodicTask,
        main_logger: ConsoleFileLogger,
        manager: t.Any,
        stop_event: t.Any,
        has_error: t.Any,
        ixia: Ixia | None = None,
    ) -> None:
        self.periodic_task = periodic_task
        self.main_logger = main_logger
        self.ixia = ixia
        self.stop_event = stop_event
        self.has_error = has_error
        self.shared_data = manager.dict()
        self.shared_params = manager.dict()
        self.shared_state = manager.dict()
        self.task_obj: t.Any = None
        self._log_everpaste_url: str | None = None

    def run(self) -> None:
        """Run an IXIA periodic task in its executor-owned thread."""
        logger: logging.Logger | None = None
        try:
            logger = _create_worker_logger(
                multiprocessing.current_process().name,
                self.shared_state,
            )
            self.task_obj = get_task_obj(
                self.periodic_task.task,
                logger=logger,
                ixia=self.ixia,
                shared_data=self.shared_data,
                shared_params=self.shared_params,
            )
            _run_periodic_task_loop(
                self.periodic_task,
                self.task_obj,
                logger,
                self.stop_event,
                self.has_error,
            )
        except Exception:
            try:
                self.has_error.value = True
            except Exception:
                pass
            if self.periodic_task.terminate_on_error:
                try:
                    self.stop_event.set()
                except Exception:
                    pass
            try:
                (logger or logging.getLogger(__name__)).exception(
                    f"Periodic task {self.periodic_task.name} terminated with an unexpected error"
                )
            except Exception:
                pass

    async def run_final_check(self) -> PeriodicCheckResult:
        if self.task_obj is None:
            self.task_obj = get_task_obj(
                self.periodic_task.task,
                logger=self.main_logger,
                ixia=self.ixia,
                shared_data=self.shared_data,
                shared_params=self.shared_params,
            )
        task_key = f"__{self.task_obj.__class__.NAME}__"
        prefix = f"{task_key}:"
        entry_count = sum(
            1 for key in self.shared_data.keys() if key.startswith(prefix)
        )
        self.main_logger.debug(
            f"Periodic task '{task_key}': shared_data entries={entry_count}, "
            f"task_obj._data entries={len(self.task_obj._data)}"
        )
        return await self.task_obj.run_final_check()

    async def teardown(self) -> str:
        """Upload the child or thread worker log to Everpaste."""
        log_file = self.shared_state.get(_LOG_FILE_KEY)
        if not log_file:
            self.main_logger.warning(
                f"No log file was recorded for periodic task {self.periodic_task.name}"
            )
            return ""

        everpaste_url = await async_everpaste_file(log_file)
        self.main_logger.info(
            f"Log for periodic task {self.periodic_task.name} has been everpasted "
            f"to: {everpaste_url}"
        )
        self._log_everpaste_url = everpaste_url
        return everpaste_url

    def stop(self) -> None:
        """Request executor-wide shutdown through the event shared by all workers."""
        self.stop_event.set()
