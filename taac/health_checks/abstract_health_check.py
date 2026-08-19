# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
import asyncio
import time
import traceback
import typing as t
from abc import ABC, abstractmethod

from taac.constants import (
    FAILED_HC_STATUSES,
    TestDevice,
    TestTopology,
)
from taac.health_checks.common_utils import (
    async_get_everpaste_fburl_if_needed,
)
from taac.ixia.taac_ixia import (  # oss-rewrite (force ShipIt re-export to taac.* root)
    TaacIxia as Ixia,
)
from taac.utils.common import is_overridden
from taac.utils.driver_factory import async_get_device_driver
from taac.utils.oss_taac_lib_utils import ConsoleFileLogger
from taac.utils.taac_log_formatter import log_health_check_info
from taac.health_check.health_check import types as hc_types


HealthCheckIn = t.TypeVar("HealthCheckIn", bound=t.Any)
Object = t.TypeVar("Object", bound=t.Any)


class AbstractPointInTimeHealthCheck(t.Generic[HealthCheckIn, Object], ABC):
    CHECK_NAME: hc_types.CheckName = hc_types.CheckName.UNDEFINED
    CHECK_SCOPE = hc_types.Scope.DEFAULT
    DEFAULT_PRIORITY = hc_types.DEFAULT_HC_PRIORITY

    """Whether a FAIL verdict is retried (only meaningful when retry_count > 0).

    Defaults to True: most checks evaluate dynamic device state that settles
    after a perturbation, so a FAIL is worth re-evaluating. Static checks (those
    reading fixed config/inventory, e.g. graceful-restart config or file
    existence) set this to False — a real FAIL there will not change on retry.
    A transient data-fetch failure (an exception from ``_run``) is always
    retried regardless of this flag (see ``run``).
    """
    RETRY_ON_FAIL: bool = True

    def __init__(self, logger: ConsoleFileLogger, ixia: t.Optional[Ixia] = None):
        if self.__class__.CHECK_NAME is hc_types.CheckName.UNDEFINED:
            raise ValueError(
                f"{self.__class__.__name__} must have a valid CHECK_NAME defined"
            )
        self.logger = logger
        self.ixia = ixia
        # Per-attempt diff magnitude (e.g. RIB-FIB missing-route count).
        # Subclasses MAY populate this inside `_run()` so the retry-loop
        # framework can capture a per_attempt_diff[] trajectory in the
        # always-on timing annotation. Reset by the framework before
        # each attempt; None means "no trajectory data" (default).
        self._last_attempt_diff: t.Optional[int] = None

    async def run_wrapper(
        self,
        obj: Object,
        input: t.Optional[HealthCheckIn],
        default_input: HealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        # Override this method to add custom logic before running the health check
        return await self.run(obj, input, default_input, check_params)

    def _extract_retry_params(
        self, check_params: t.Dict[str, t.Any]
    ) -> t.Tuple[int, float, float]:
        """Extract per-check retry configuration from check_params.

        Health checks are single-shot by default (retry_count=0).  When
        retry_count > 0, the **full** data-fetch + validation cycle is
        retried on FAIL with exponential backoff:

            delay(n) = retry_delay_seconds * retry_delay_multiplier ** n

        where n = 0, 1, 2, ... is the zero-based retry index (n=0 is
        the first retry, not the initial attempt).

        Example with defaults (retry_delay_seconds=5.0, multiplier=1.5):
            attempt 1 → immediate  (initial)
            attempt 2 → wait  5.0 s   (5.0 * 1.5^0, first retry)
            attempt 3 → wait  7.5 s   (5.0 * 1.5^1)
            attempt 4 → wait 11.25 s  (5.0 * 1.5^2)

        Only FAIL is retried; PASS, SKIP, and ERROR break immediately.
        Exceptions (ERROR) are never retried — they propagate to the
        outer handler unchanged.

        Input validation: retry_count is clamped to >= 0,
        retry_delay_seconds to >= 0.0, retry_delay_multiplier to >= 1.0.

        Returns:
            (retry_count, retry_delay_seconds, retry_delay_multiplier)
        """
        retry_count = max(0, int(check_params.get("retry_count", 0)))
        retry_delay_seconds = max(
            0.0, float(check_params.get("retry_delay_seconds", 5.0))
        )
        retry_delay_multiplier = max(
            1.0, float(check_params.get("retry_delay_multiplier", 1.5))
        )
        return retry_count, retry_delay_seconds, retry_delay_multiplier

    async def run(
        self,
        obj: Object,
        input: t.Optional[HealthCheckIn],
        default_input: HealthCheckIn,
        check_params: t.Dict[str, t.Any],
        custom_run_fn: t.Optional[t.Callable] = None,
    ) -> hc_types.HealthCheckResult:
        try:
            should_skip_check, reason = await self.should_skip_check(obj)
            if should_skip_check:
                self.logger.info(
                    f"Skipping health check {self.__class__.CHECK_NAME} for the reason {reason}"
                )
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.SKIP,
                    message=reason,
                )
            input = input or self._default_input(obj) or default_input
            self.logger.info(f"Running health check: {self.__class__.__name__}")
            self.logger.debug(f"Health check input: {input}")
            run_fn = custom_run_fn or self._run

            retry_count, retry_delay, retry_multiplier = self._extract_retry_params(
                check_params
            )
            current_delay = retry_delay
            check_result = None

            # Heal-latency instrumentation state (T274256815, paste
            # P2390924278). Always-on, additive — never alters verdict.
            # `t0` is the wall-clock anchor used by both the timing
            # annotation and the optional post-verdict heal probe so
            # they report from the same origin. Monotonic clock chosen
            # to be robust against wall-clock adjustments.
            t0_monotonic = time.monotonic()
            per_attempt_diff: t.List[t.Optional[int]] = []
            attempts_to_pass: t.Optional[int] = None
            elapsed_to_pass_sec: t.Optional[float] = None

            for attempt in range(1 + retry_count):
                if attempt > 0:
                    self.logger.info(
                        f"Retry {attempt}/{retry_count} for "
                        f"{self.__class__.__name__} after {current_delay:.1f}s delay"
                    )
                    await asyncio.sleep(current_delay)
                    current_delay *= retry_multiplier

                self._last_attempt_diff = None
                try:
                    check_result = await run_fn(obj, input, check_params)
                except Exception as e:
                    # A transient data-fetch failure (dropped RPC / timeout /
                    # empty read) is not a real verdict, so it is retried for
                    # EVERY check until retries are exhausted, then surfaced as
                    # ERROR. This is distinct from a FAIL verdict (below), which
                    # only stateful checks retry.

                    self.logger.warning(
                        f"Health check {self.__class__.__name__} raised on attempt "
                        f"{attempt + 1}/{1 + retry_count}: {type(e).__name__}: {e}"
                    )
                    check_result = hc_types.HealthCheckResult(
                        status=hc_types.HealthCheckStatus.ERROR,
                        message=(
                            f"Exception occurred while running "
                            f"{self.__class__.__name__}: {e}\n "
                            f"{traceback.format_tb(e.__traceback__)}"
                        ),
                    )
                    per_attempt_diff.append(self._last_attempt_diff)
                    continue
                per_attempt_diff.append(self._last_attempt_diff)

                if check_result.status != hc_types.HealthCheckStatus.FAIL:
                    if check_result.status == hc_types.HealthCheckStatus.PASS:
                        attempts_to_pass = attempt + 1
                        elapsed_to_pass_sec = time.monotonic() - t0_monotonic
                    break

                # A FAIL verdict is retried only for stateful checks. Static
                # checks (RETRY_ON_FAIL = False) read fixed config/inventory, so
                # a real FAIL will not change on retry.
                if not self.__class__.RETRY_ON_FAIL:
                    break

                if attempt < retry_count:
                    self.logger.warning(
                        f"Health check {self.__class__.__name__} FAIL on attempt "
                        f"{attempt + 1}/{1 + retry_count}, will retry. "
                        f"Message: {check_result.message}"
                    )

            assert check_result is not None

            if (
                check_result.status == hc_types.HealthCheckStatus.FAIL
                and retry_count > 0
                and self.__class__.RETRY_ON_FAIL
            ):
                annotated_msg = (
                    f"[Failed after {retry_count} retries] {check_result.message}"
                )
                check_result = check_result(message=annotated_msg)

            check_result = await self._apply_timing_and_probe_annotations(
                check_result=check_result,
                obj=obj,
                input=input,
                check_params=check_params,
                t0_monotonic=t0_monotonic,
                attempts_to_pass=attempts_to_pass,
                elapsed_to_pass_sec=elapsed_to_pass_sec,
                per_attempt_diff=per_attempt_diff,
            )

            check_result = check_result(
                message=await self._safe_shorten(
                    check_result.message,
                    shorten_fburl=check_result.status in FAILED_HC_STATUSES,
                )
            )
            log_health_check_info(
                self.__class__.__name__,
                check_result.status.name,
                logger=self.logger,
            )
            return check_result(
                name=self.__class__.CHECK_NAME,
            )
        except Exception as e:
            err_msg = f"Exception occurred while running {self.__class__.__name__}: {e}\n {traceback.format_tb(e.__traceback__)}"
            self.logger.error(err_msg)
            return hc_types.HealthCheckResult(
                name=self.__class__.CHECK_NAME,
                status=hc_types.HealthCheckStatus.ERROR,
                message=await self._safe_shorten(err_msg, shorten_fburl=True),
            )

    async def _apply_timing_and_probe_annotations(
        self,
        check_result: hc_types.HealthCheckResult,
        obj: Object,
        input: HealthCheckIn,
        check_params: t.Dict[str, t.Any],
        t0_monotonic: float,
        attempts_to_pass: t.Optional[int],
        elapsed_to_pass_sec: t.Optional[float],
        per_attempt_diff: t.List[t.Optional[int]],
    ) -> hc_types.HealthCheckResult:
        """Append the always-on timing annotation and (on FAIL) the
        opt-in post-verdict probe annotation. Verdict-preserving:
        annotations may only enrich `message`, never change `status`.
        """
        timing_annotation = self._format_timing_annotation(
            attempts_to_pass=attempts_to_pass,
            elapsed_to_pass_sec=elapsed_to_pass_sec,
            per_attempt_diff=per_attempt_diff,
            final_status=check_result.status,
        )
        if timing_annotation:
            check_result = check_result(
                message=self._append_annotation(check_result.message, timing_annotation)
            )

        if check_result.status != hc_types.HealthCheckStatus.FAIL:
            return check_result

        try:
            probe_annotation = await self._run_post_verdict_probe(
                obj, input, check_params, t0_monotonic
            )
        except Exception as probe_exc:
            # A probe failure must never escalate to ERROR or otherwise
            # affect the verdict — log and move on.
            self.logger.warning(
                f"[{self.__class__.__name__}] post-verdict probe "
                f"raised {type(probe_exc).__name__}: {probe_exc}; "
                f"continuing with original FAIL verdict"
            )
            return check_result

        if probe_annotation:
            check_result = check_result(
                message=self._append_annotation(check_result.message, probe_annotation)
            )
        return check_result

    async def _safe_shorten(
        self, msg: t.Optional[str], shorten_fburl: bool = False
    ) -> t.Optional[str]:
        """Wrap async_get_everpaste_fburl_if_needed with a fallback.

        If everpaste / fburl shortening fails (network error, service
        degradation, rate-limit), return the raw message and log a WARNING.
        A cosmetic URL-shortening failure must never convert a successful
        health check into an ERROR, and must never cascade into additional
        network calls in the error path.

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

    @staticmethod
    def _append_annotation(existing_message: t.Optional[str], annotation: str) -> str:
        if not existing_message:
            return annotation
        return f"{existing_message} {annotation}"

    def _format_timing_annotation(
        self,
        attempts_to_pass: t.Optional[int],
        elapsed_to_pass_sec: t.Optional[float],
        per_attempt_diff: t.List[t.Optional[int]],
        final_status: hc_types.HealthCheckStatus,
    ) -> t.Optional[str]:
        """Format a single-line timing annotation appended to `message`.

        Verdict-preserving: this annotation only encodes timing data
        captured by the framework retry loop. On PASS it distinguishes
        first-try success from passed-on-retry; on FAIL it records the
        per-attempt diff trajectory so consumers can spot a
        monotonically-shrinking diff (transient/recovering) versus a
        stuck diff (persistent).

        Returns None for first-try PASS (the common path) to keep noise
        down — the absence of the annotation itself encodes
        "passed@attempt=1".
        """
        if final_status == hc_types.HealthCheckStatus.PASS:
            if (
                attempts_to_pass is not None
                and attempts_to_pass > 1
                and elapsed_to_pass_sec is not None
            ):
                return (
                    f"[timing: passed@attempt={attempts_to_pass} "
                    f"elapsed_to_pass_sec={elapsed_to_pass_sec:.1f}]"
                )
            return None
        if final_status == hc_types.HealthCheckStatus.FAIL:
            attempts_used = len(per_attempt_diff)
            diff_traj = ",".join(
                str(d) if d is not None else "?" for d in per_attempt_diff
            )
            final_diff = per_attempt_diff[-1] if per_attempt_diff else None
            final_diff_str = f"{final_diff}" if final_diff is not None else "?"
            return (
                f"[timing: failed attempts={attempts_used} "
                f"final_diff={final_diff_str} "
                f"per_attempt_diff=[{diff_traj}]]"
            )
        return None

    async def _run_post_verdict_probe(
        self,
        obj: Object,
        input: HealthCheckIn,
        check_params: t.Dict[str, t.Any],
        t0_monotonic: float,
    ) -> t.Optional[str]:
        """Optional diagnostic probe invoked only after a FAIL verdict.

        Subclasses opt in by overriding this and gating execution on a
        check_params flag (e.g. RIB-FIB uses
        ``rib_fib_record_heal_latency``). The probe MUST be
        diagnostic-only — it may not flip the verdict. Return either an
        annotation string (appended to the FAIL message) or None (no
        annotation).

        ``t0_monotonic`` is the framework's first-attempt start so the
        probe can report heal-latency from the same origin used by the
        timing annotation.

        Default: no probe.
        """
        return None

    @abstractmethod
    async def _run(
        self,
        obj: Object,
        input: HealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        raise NotImplementedError

    def default_input(self, obj: Object) -> t.Optional[HealthCheckIn]:
        try:
            return self.default_input(obj)
        except Exception as ex:
            self.logger.error(
                f"Failed to get default input for {self.__class__.__name__}: {ex}"
            )
            return None

    def _default_input(self, obj: Object) -> t.Optional[HealthCheckIn]:
        return None

    async def should_skip_check(self, obj: Object) -> t.Tuple[bool, str | None]:
        return False, None


class AbstractIxiaHealthCheck(AbstractPointInTimeHealthCheck[HealthCheckIn, Ixia], ABC):
    pass


OPERATING_SYSTEM_TO_FN_NAME = {
    "FBOSS": "_run_fboss",
    "EOS": "_run_arista",
    "IOSXR": "_run_cisco",
}


class AbstractDeviceHealthCheck(
    AbstractPointInTimeHealthCheck[HealthCheckIn, TestDevice], ABC
):
    OPERATING_SYSTEMS = ["FBOSS", "EOS"]
    LOG_TO_SCUBA: bool = False
    CHECK_SCOPE = hc_types.Scope.TOPOLOGY

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # Sentinel until run_wrapper() resolves the concrete driver. Typed
        # Any because subclasses reach for methods that live on the concrete
        # switch drivers, not on the AbstractSwitch base.
        self.driver: t.Any = ...
        self.data_to_log = {}

    async def run_wrapper(
        self,
        obj: Object,
        input: t.Optional[HealthCheckIn],
        default_input: HealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        # pyrefly: ignore [missing-attribute]
        os = obj.attributes.operating_system
        if os in self.__class__.OPERATING_SYSTEMS:
            # pyrefly: ignore [bad-assignment, missing-attribute]
            self.driver = await async_get_device_driver(obj.name)
            fn_name = OPERATING_SYSTEM_TO_FN_NAME[os]
            is_fn_overridden = is_overridden(
                self.__class__, AbstractDeviceHealthCheck, fn_name
            )
            custom_run_fn = getattr(self, fn_name, None) if is_fn_overridden else None
            return await self.run(
                obj, input, default_input, check_params, custom_run_fn
            )

        return hc_types.HealthCheckResult(
            name=self.__class__.CHECK_NAME,
            status=hc_types.HealthCheckStatus.SKIP,
        )

    def add_data_to_log(self, json_serializable_dict: t.Dict) -> None:
        self.data_to_log.update(json_serializable_dict)

    async def _run_arista(
        self,
        obj: Object,
        input: HealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        raise NotImplementedError

    async def _run_fboss(
        self,
        obj: Object,
        input: HealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        raise NotImplementedError

    async def _run_cisco(
        self,
        obj: Object,
        input: HealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        raise NotImplementedError


class AbstractTopologyHealthCheck(
    AbstractPointInTimeHealthCheck[HealthCheckIn, TestTopology], ABC
):
    pass
