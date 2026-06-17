# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import asyncio
import typing as t

from neteng.test_infra.dne.taac.ixia.taac_ixia import TaacIxia as Ixia
from taac.tasks.registry import TASK_NAME_TO_CLASS
from taac.utils.oss_taac_lib_utils import ConsoleFileLogger
from taac.test_as_a_config import types as taac_types


async def run_task(
    task: taac_types.Task,
    params: t.Dict[str, t.Any],
    ixia: t.Optional[Ixia] = None,
    logger: t.Optional[ConsoleFileLogger] = None,
    shared_data: t.Optional[t.Dict[t.Any, t.Any]] = None,
) -> None:
    task_cls = TASK_NAME_TO_CLASS[task.task_name]
    # Try to create task with shared_data first (for tasks that support it)
    # Fall back to creating without shared_data for legacy tasks
    try:
        task_obj = task_cls(
            logger=logger,
            ixia=ixia,
            hostname=task.hostname,
            description=task.description,
            # pyrefly: ignore [unexpected-keyword]
            shared_data=shared_data,
        )
    except TypeError:
        # Legacy task that doesn't accept shared_data parameter
        task_obj = task_cls(
            logger=logger,
            ixia=ixia,
            hostname=task.hostname,
            description=task.description,
        )
    return await task_obj._run(params)


def get_task_obj(
    task: taac_types.Task,
    ixia: t.Optional[Ixia] = None,
    logger: t.Optional[ConsoleFileLogger] = None,
    shared_data: t.Optional[t.Dict[t.Any, t.Any]] = None,
    shared_params: t.Optional[t.Dict[str, t.Any]] = None,
) -> t.Any:
    task_cls = TASK_NAME_TO_CLASS[task.task_name]
    # Pass shared_data and shared_params if task class accepts them (PeriodicTask), otherwise don't
    try:
        return task_cls(
            logger=logger,
            ixia=ixia,
            hostname=task.hostname,
            description=task.description,
            # pyrefly: ignore [unexpected-keyword]
            shared_data=shared_data,
            # pyrefly: ignore [unexpected-keyword]
            shared_params=shared_params,
        )
    except TypeError:
        # For non-periodic tasks that don't accept shared_data/shared_params parameters
        return task_cls(
            logger=logger,
            ixia=ixia,
            hostname=task.hostname,
            description=task.description,
        )


def run_task_sync(
    task: taac_types.Task,
    params: t.Dict[str, t.Any],
    ixia: t.Optional[Ixia] = None,
    logger: t.Optional[ConsoleFileLogger] = None,
) -> None:
    return asyncio.run(run_task(task, params, ixia, logger))
