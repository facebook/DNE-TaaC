# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
import typing as t
from abc import ABC

from taac.constants import (
    FAILED_HC_STATUSES,
    TestDevice,
    TestTopology,
)
from taac.health_checks.common_utils import (
    async_get_everpaste_fburl_if_needed,
)
from taac.health_checks.constants import Snapshot
from taac.utils.driver_factory import async_get_device_driver
from taac.utils.oss_taac_lib_utils import (
    async_retryable,
    ConsoleFileLogger,
)
from taac.health_check.health_check import types as hc_types


HealthCheckIn = t.TypeVar("HealthCheckIn", bound=t.Any)
Object = t.TypeVar("Object", bound=t.Any)


class AbstractSnapshotHealthCheck(t.Generic[HealthCheckIn, Object], ABC):
    CHECK_NAME: hc_types.CheckName = hc_types.CheckName.UNDEFINED
    CHECK_SCOPE = hc_types.Scope.DEFAULT
    DEFAULT_PRIORITY = hc_types.DEFAULT_HC_PRIORITY

    def __init__(
        self,
        obj: Object,
        input: HealthCheckIn,
        pre_snapshot_checkpoint_id: str,
        post_snapshot_checkpoint_id: str,
        check_params: t.Dict[str, t.Any],
        logger: ConsoleFileLogger,
    ):
        if self.__class__.CHECK_NAME is hc_types.CheckName.UNDEFINED:
            raise ValueError(
                f"{self.__class__.__name__} must have a valid CHECK_NAME defined"
            )
        self._input = input
        self._check_params = check_params
        self._obj = obj
        self._pre_snapshot_checkpoint_id = pre_snapshot_checkpoint_id
        self._post_snapshot_checkpoint_id = post_snapshot_checkpoint_id
        self.logger = logger

        # pyrefly: ignore [bad-assignment]
        self._pre_snapshot: Snapshot = ...
        # pyrefly: ignore [bad-assignment]
        self._post_snapshot: Snapshot = ...
        self._should_skip = False

    async def setup(self, obj: Object) -> None:
        pass

    @async_retryable(retries=3, exceptions=(Exception,))  # pyre-ignore[56]
    async def _capture_pre_snapshot(
        self,
        obj: Object,
        input: HealthCheckIn,
        check_params: t.Dict[str, t.Any],
        timestamp: int,
    ) -> Snapshot:
        try:
            if self._should_skip:
                return Snapshot(timestamp=0)
            return await self.capture_pre_snapshot(obj, input, check_params, timestamp)
        except Exception as e:
            self.logger.info(
                f"Error occured while capturing pre snapshot for {self.__class__.CHECK_NAME}: {e}"
            )
            raise e

    async def capture_pre_snapshot(
        self,
        obj: Object,
        input: HealthCheckIn,
        check_params: t.Dict[str, t.Any],
        timestamp: int,
    ) -> Snapshot:
        return Snapshot(timestamp=timestamp)

    @async_retryable(retries=3, exceptions=(Exception,))  # pyre-ignore[56]
    async def _capture_post_snapshot(
        self,
        obj: Object,
        input: HealthCheckIn,
        check_params: t.Dict[str, t.Any],
        timestamp: int,
    ) -> Snapshot:
        try:
            if self._should_skip:
                return Snapshot(timestamp=0)
            return await self.capture_post_snapshot(obj, input, check_params, timestamp)
        except Exception as e:
            self.logger.info(
                f"Error occured while capturing post snapshot for {self.__class__.CHECK_NAME}: {e}"
            )
            raise e

    async def capture_post_snapshot(
        self,
        obj: Object,
        input: HealthCheckIn,
        check_params: t.Dict[str, t.Any],
        timestamp: int,
    ) -> Snapshot:
        return Snapshot(timestamp=timestamp)

    @async_retryable(retries=3, exceptions=(Exception,))  # pyre-ignore[56]
    async def _compare_snapshots(
        self,
        obj: Object,
        input: HealthCheckIn,
        check_params: t.Dict[str, t.Any],
        pre_snapshot: Snapshot,
        post_snapshot: Snapshot,
    ) -> hc_types.HealthCheckResult:
        try:
            if self._should_skip:
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.SKIP,
                )
            check_result = await self.compare_snapshots(
                obj, input, check_params, pre_snapshot, post_snapshot
            )
            check_result = check_result(
                message=await self._safe_shorten(
                    check_result.message,
                    shorten_fburl=check_result.status in FAILED_HC_STATUSES,
                ),
                name=self.__class__.CHECK_NAME,
            )
            return check_result
        except Exception as e:
            self.logger.info(
                f"Error occured while comparing pre and post snapshots for {self.__class__.CHECK_NAME}: {e}"
            )
            raise e

    async def _safe_shorten(
        self, msg: t.Optional[str], shorten_fburl: bool = False
    ) -> t.Optional[str]:
        """Shorten ``msg`` via everpaste/fburl, falling back to the raw message.

        If everpaste/fburl shortening fails (network error, service
        degradation, ``fburl`` tier throttling), return the raw message and log
        a WARNING. A cosmetic URL-shortening failure must never convert a
        passing snapshot check into an ERROR. Critically, this also prevents a
        shortening failure from propagating out of ``_compare_snapshots`` where
        the ``@async_retryable(retries=3)`` decorator would amplify a single
        ``fburl`` throttle into multiple hits against the already-throttled tier.

        ``shorten_fburl`` is forwarded to async_get_everpaste_fburl_if_needed:
        ``False`` (default, used for PASS/SKIP) only uploads to Everpaste (a
        clickable link) without touching the throttled ``fburl`` tier; ``True``
        (used for FAIL/ERROR) additionally fburl-shortens for triage.
        """
        if not msg:
            return msg
        try:
            return await async_get_everpaste_fburl_if_needed(
                msg, shorten_fburl=shorten_fburl
            )
        except Exception as e:
            self.logger.warning(
                f"[{self.__class__.__name__}] everpaste shortening failed; "
                f"using raw message ({len(msg)} chars). Underlying: "
                f"{type(e).__name__}: {e}"
            )
            return msg

    async def compare_snapshots(
        self,
        obj: Object,
        input: HealthCheckIn,
        check_params: t.Dict[str, t.Any],
        pre_snapshot: Snapshot,
        post_snapshot: Snapshot,
    ) -> hc_types.HealthCheckResult:
        raise NotImplementedError


class AbstractDeviceSnapshotHealthCheck(
    AbstractSnapshotHealthCheck[HealthCheckIn, TestDevice], ABC
):
    OPERATING_SYSTEMS = ["FBOSS", "EOS"]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.driver = ...

    async def setup(self, obj: Object) -> None:
        # pyrefly: ignore [missing-attribute]
        if obj.attributes.operating_system in self.__class__.OPERATING_SYSTEMS:
            # pyrefly: ignore [bad-assignment, missing-attribute]
            self.driver = await async_get_device_driver(obj.name)
        else:
            self._should_skip = True
        await super().setup(obj)


class AbstractTopologySnapshotHealthCheck(
    AbstractSnapshotHealthCheck[HealthCheckIn, TestTopology], ABC
):
    pass
