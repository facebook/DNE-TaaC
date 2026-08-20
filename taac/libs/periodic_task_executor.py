# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe

import asyncio
import multiprocessing
import threading
import time
import typing as t

from taac.ixia.taac_ixia import (
    TaacIxia as Ixia,
)  # OSS ship-rewrite probe
from taac.libs.periodic_task_worker import (
    _make_sync_manager,
    PeriodicTaskWorker,
    run_periodic_task_process,
)
from taac.utils.driver_factory import (
    capture_driver_bootstrap_data,
)
from taac.utils.oss_taac_lib_utils import (
    ConsoleFileLogger,
    get_root_logger,
)
from taac.test_as_a_config import types as taac_types

_DEFERRED_THREAD_JOIN_TIMEOUT_S = 60.0


class PeriodicTaskExecutor:
    def __init__(
        self,
        periodic_tasks: t.List[taac_types.PeriodicTask],
        logger: ConsoleFileLogger,
        ixia: t.Optional[Ixia] = None,
    ) -> None:
        self.logger = logger or get_root_logger()
        self.periodic_tasks = periodic_tasks
        self.periodic_task_workers = []
        self.processes = []
        self.threads = []
        self.ixia = ixia
        self._driver_bootstrap = capture_driver_bootstrap_data()
        self._mp_context = multiprocessing.get_context("forkserver")
        self._manager = None
        self._manager_lock = threading.Lock()
        self._manager_shutdown_thread_lock = threading.Lock()
        self._manager_shutdown_thread = None
        self._stop_event = self._mp_context.Event()
        self._started = False

    def stop_all_periodic_tasks(self) -> None:
        """Stop producers while retaining Manager-backed data for final checks."""
        self._stop_event.set()

        for process in self.processes:
            process.join(timeout=5)
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
                if process.is_alive():
                    process.kill()
                    process.join()

        for thread in self.threads:
            if thread.is_alive():
                thread.join(timeout=5)

        live_threads = [thread.name for thread in self.threads if thread.is_alive()]
        if live_threads:
            raise RuntimeError(
                "Periodic task threads did not stop within 5 seconds: "
                + ", ".join(live_threads)
            )

    def _shutdown_manager(self) -> None:
        with self._manager_lock:
            manager = self._manager
            if manager is None:
                return
            self._manager = None
        try:
            manager.shutdown()
        except Exception as error:
            self.logger.debug(f"PeriodicTaskExecutor manager shutdown: {error!r}")

    def _defer_manager_shutdown_until_threads_exit(self) -> None:
        with self._manager_shutdown_thread_lock:
            shutdown_thread = self._manager_shutdown_thread
            if shutdown_thread is not None and shutdown_thread.is_alive():
                return

            live_threads = tuple(thread for thread in self.threads if thread.is_alive())
            if not live_threads:
                shutdown_immediately = True
            else:
                shutdown_immediately = False

                def shutdown_after_join() -> None:
                    deadline = time.monotonic() + _DEFERRED_THREAD_JOIN_TIMEOUT_S
                    for thread in live_threads:
                        thread.join(timeout=max(0.0, deadline - time.monotonic()))
                    still_running = [
                        thread.name for thread in live_threads if thread.is_alive()
                    ]
                    if still_running:
                        self.logger.error(
                            "Forcing periodic task Manager shutdown after waiting "
                            f"{_DEFERRED_THREAD_JOIN_TIMEOUT_S:.0f}s for: "
                            + ", ".join(still_running)
                        )
                    self._shutdown_manager()

                self.logger.warning(
                    "Deferring periodic task Manager shutdown until threads exit: "
                    + ", ".join(thread.name for thread in live_threads)
                )
                self._manager_shutdown_thread = threading.Thread(
                    target=shutdown_after_join,
                    name="PeriodicTaskManagerShutdown",
                    daemon=True,
                )
                self._manager_shutdown_thread.start()

        if shutdown_immediately:
            self._shutdown_manager()

    def create_periodic_tasks(self) -> None:
        if not self.periodic_tasks:
            return
        if self._started:
            raise RuntimeError("PeriodicTaskExecutor instances are single-use")
        if self._manager is None:
            self._manager = _make_sync_manager(self._mp_context, self.logger)
        self._started = True

        for periodic_task in self.periodic_tasks:
            has_error = self._mp_context.Value("b", False)
            worker = PeriodicTaskWorker(
                periodic_task,
                self.logger,
                self._manager,
                self._stop_event,
                has_error,
                ixia=self.ixia,
            )
            self.periodic_task_workers.append(worker)
            self.logger.info(f"Starting periodic task: {periodic_task.name}")

            # Use threading for IXIA tasks (SSL connections can't be pickled across processes)
            # Use multiprocessing for non-IXIA tasks (better isolation)
            if periodic_task.task.ixia_needed:
                thread = threading.Thread(
                    target=worker.run,
                    name=f"PeriodicTask-{periodic_task.name}",
                )
                thread.daemon = True
                thread.start()
                self.threads.append(thread)
            else:
                process = self._mp_context.Process(
                    target=run_periodic_task_process,
                    name=f"PeriodicTask-{periodic_task.name}",
                    args=(
                        periodic_task,
                        self._driver_bootstrap,
                        worker.shared_data,
                        worker.shared_params,
                        worker.shared_state,
                        self._stop_event,
                        has_error,
                    ),
                )
                process.start()
                self.processes.append(process)

    def has_error(self) -> bool:
        return any(worker.has_error.value for worker in self.periodic_task_workers)

    async def teardown(
        self,
        skip_log_upload: bool = False,
        stop_tasks: bool = True,
    ) -> None:
        """Stop workers, upload their logs, and release the shared Manager.

        Args:
            skip_log_upload: Skip worker teardown and log upload when already done.
            stop_tasks: Stop workers here. Set false only after the caller has
                already stopped them for stable final checks.
        """
        errors: t.List[Exception] = []
        try:
            if stop_tasks:
                try:
                    self.stop_all_periodic_tasks()
                except Exception as error:
                    errors.append(error)

            if not skip_log_upload:
                teardown_tasks = [
                    worker.teardown() for worker in self.periodic_task_workers
                ]
                results = await asyncio.gather(*teardown_tasks, return_exceptions=True)
                errors.extend(
                    result for result in results if isinstance(result, Exception)
                )

            if errors:
                raise ExceptionGroup("Periodic task executor teardown failed", errors)
        finally:
            if any(thread.is_alive() for thread in self.threads):
                self._defer_manager_shutdown_until_threads_exit()
            else:
                self._shutdown_manager()
