# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe

import asyncio
import multiprocessing
import threading
import typing as t

from neteng.test_infra.dne.taac.ixia.taac_ixia import TaacIxia as Ixia
from taac.libs.periodic_task_worker import PeriodicTaskWorker
from taac.utils.oss_taac_lib_utils import (
    ConsoleFileLogger,
    get_root_logger,
)
from taac.test_as_a_config import types as taac_types


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

    def stop_all_periodic_tasks(self) -> None:
        # Terminate all processes
        for process in self.processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
                if process.is_alive():
                    process.kill()
                    process.join()

        # Stop all threads by signaling workers
        for worker in self.periodic_task_workers:
            worker.stop()

        # Wait for threads to finish (with timeout)
        for thread in self.threads:
            if thread.is_alive():
                thread.join(timeout=5)

    def create_periodic_tasks(self) -> None:
        for periodic_task in self.periodic_tasks:
            worker = PeriodicTaskWorker(
                periodic_task,
                self.stop_all_periodic_tasks,
                self.logger,
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
                process = multiprocessing.Process(
                    target=worker.run,
                )
                process.start()
                self.processes.append(process)

    def has_error(self) -> bool:
        return any(worker.has_error.value for worker in self.periodic_task_workers)

    async def teardown(self, skip_log_upload: bool = False) -> None:
        """
        Teardown periodic tasks and optionally upload logs.

        Args:
            skip_log_upload: If True, skip calling teardown on workers (logs already uploaded)
        """
        self.stop_all_periodic_tasks()

        if not skip_log_upload:
            # Call teardown on all workers to upload logs to Everpaste
            teardown_tasks = [
                worker.teardown() for worker in self.periodic_task_workers
            ]
            await asyncio.gather(*teardown_tasks, return_exceptions=True)
