# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import time
import typing as t

from taac.constants import PeriodicCheckResult
from neteng.test_infra.dne.taac.ixia.taac_ixia import TaacIxia as Ixia
from taac.utils.driver_factory import async_get_device_driver
from taac.utils.oss_taac_lib_utils import (
    ConsoleFileLogger,
    get_root_logger,
    none_throws,
)


class _SharedDataView(dict):
    """Dict wrapper that stores data in multiprocessing Manager dict with prefixed keys."""

    def __init__(self, shared_data: t.Dict, task_key: str):
        self._shared_data = shared_data
        self._task_key = task_key
        self._prefix = f"{task_key}:"

    def __setitem__(self, key: t.Any, value: t.Any) -> None:
        # Store in shared_data with prefixed key for isolation
        self._shared_data[f"{self._prefix}{key}"] = value

    def __getitem__(self, key: t.Any) -> t.Any:
        return self._shared_data[f"{self._prefix}{key}"]

    def __contains__(self, key: t.Any) -> bool:
        return f"{self._prefix}{key}" in self._shared_data

    def __len__(self) -> int:
        # Count keys that match our prefix
        return sum(1 for k in self._shared_data.keys() if k.startswith(self._prefix))

    # pyre-ignore[14]: Inconsistent override
    def keys(self) -> t.Iterator[t.Any]:
        prefix_len = len(self._prefix)
        for key in self._shared_data.keys():
            if key.startswith(self._prefix):
                yield key[prefix_len:]  # Remove prefix

    # pyre-ignore[14]: Inconsistent override
    def values(self) -> t.Iterator[t.Any]:
        for key in self._shared_data.keys():
            if key.startswith(self._prefix):
                yield self._shared_data[key]

    # pyre-ignore[14]: Inconsistent override
    def items(self) -> t.Iterator[t.Tuple[t.Any, t.Any]]:
        prefix_len = len(self._prefix)
        for key in self._shared_data.keys():
            if key.startswith(self._prefix):
                yield (key[prefix_len:], self._shared_data[key])


class BaseTask:
    NAME: t.Optional[str] = None

    def __init__(
        self,
        hostname: t.Optional[str] = None,
        description: t.Optional[str] = None,
        ixia: t.Optional[Ixia] = None,
        logger: t.Optional[ConsoleFileLogger] = None,
        shared_data: t.Optional[t.Dict[t.Any, t.Any]] = None,
    ) -> None:
        self.logger = logger or get_root_logger()
        self.hostname = hostname

        self._ixia = ixia
        self._description = description
        # Store reference to shared data dictionary (for cross-task communication)
        self._shared_data = shared_data
        # Each task gets its own isolated namespace within shared_data
        # This prevents tasks from accidentally overwriting each other's data
        if shared_data is not None:
            # Create a unique key for this task instance using task name
            self._task_key = f"__{self.__class__.NAME}__"
            # CRITICAL: We store data directly in shared_data with timestamp keys
            # No nested dict needed - use the task_key as prefix for all data keys
        else:
            # No shared data provided - create local dictionary (backward compatibility)
            # pyrefly: ignore [bad-assignment]
            self._task_key = None
            self._local_data: t.Dict[t.Any, t.Any] = {}
        self._driver = None
        if self.__class__.NAME is None:
            raise ValueError(f"{self.__class__.__name__} must have a name defined")

    @property
    def _data(self) -> t.Dict[t.Any, t.Any]:
        """Access data dict - uses shared_data if available, otherwise local dict."""
        if self._shared_data is not None and self._task_key is not None:
            return _SharedDataView(self._shared_data, self._task_key)
        else:
            return self._local_data

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        raise NotImplementedError("run method must be implemented")

    async def _run(self, params: t.Dict[str, t.Any]) -> None:
        await self.run(params)

    async def _setup(self) -> None:
        # pyre-fixme[6]: For 1st argument expected `str` but got `Optional[str]`.
        self._driver = await async_get_device_driver(self.hostname)

    @property
    def ixia(self):
        return none_throws(self._ixia)

    def driver(self):
        return none_throws(self._driver)

    async def run_final_check(self) -> t.Optional[PeriodicCheckResult]:
        return None


class PeriodicTask(BaseTask):
    def __init__(
        self,
        hostname: t.Optional[str] = None,
        description: t.Optional[str] = None,
        ixia: t.Optional[Ixia] = None,
        logger: t.Optional[ConsoleFileLogger] = None,
        shared_data: t.Optional[t.Dict[t.Any, t.Any]] = None,
        shared_params: t.Optional[t.Dict[str, t.Any]] = None,
    ) -> None:
        # Pass shared_data to parent BaseTask
        super().__init__(hostname, description, ixia, logger, shared_data)
        # Note: self._data is already initialized by BaseTask with shared_data
        self._num_runs = 0
        # Use shared params dict if provided (for multiprocessing), otherwise create regular dict
        self._params: t.Dict[str, t.Any] = (
            shared_params if shared_params is not None else {}
        )

    def add_data(self, value: t.Any, timestamp: t.Optional[float] = None) -> None:
        timestamp = int(timestamp or time.time())
        self._data[timestamp] = value
        self.logger.debug(
            f"add_data: stored {value} at {timestamp}, _data now has {len(self._data)} entries"
        )

    async def _run(self, params: t.Dict[str, t.Any]) -> None:
        # Update shared dict contents instead of replacing reference
        self._params.clear()
        self._params.update(params)
        await self.run(params)

    async def run_final_check(self) -> t.Optional[PeriodicCheckResult]:
        return None
