# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import asyncio
import operator
import time
import typing as t

from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.utils.common import async_everpaste_str
from taac.utils.health_check_utils import (
    get_fb303_client,
    is_same_device,
)
from taac.health_check.health_check import types as hc_types

# Maps a ComparisonType onto "is the observed PFC count acceptable?".
# _compare_pfc() inverts this to report a violation. BETWEEN is deliberately
# absent: it needs a second bound that DsfPfcThreshold does not carry, so it is
# rejected up front rather than silently reported as healthy.
_PFC_COMPARATORS: t.Mapping[hc_types.ComparisonType, t.Callable[[int, int], bool]] = {
    hc_types.ComparisonType.LESS_THAN: operator.lt,
    hc_types.ComparisonType.GREATER_THAN: operator.gt,
    hc_types.ComparisonType.EQUAL_TO: operator.eq,
    hc_types.ComparisonType.LESS_THAN_EQUAL_TO: operator.le,
    hc_types.ComparisonType.GREATER_THAN_EQUAL_TO: operator.ge,
}


def _supported_comparison_names() -> t.List[str]:
    return sorted(c.name for c in _PFC_COMPARATORS)


def _validate_comparison(comparison: hc_types.ComparisonType) -> None:
    """Raise if DSF_PFC_CHECK cannot evaluate ``comparison``.

    Without this, an unimplemented comparison fell through to "no violation",
    which every caller reads as healthy.
    """
    if comparison not in _PFC_COMPARATORS:
        raise ValueError(
            f"DSF_PFC_CHECK does not support comparison {comparison.name}; "
            f"expected one of {_supported_comparison_names()}"
        )


def _parse_endpoint(endpoint: str) -> t.Tuple[str, str]:
    parts = endpoint.split(":", 1)
    if len(parts) != 2 or not all(parts):
        raise ValueError(
            f"Invalid DSF PFC endpoint {endpoint!r}; expected 'device:interface'"
        )
    return parts[0], parts[1]


class DsfPfcHealthCheck(AbstractDeviceHealthCheck[hc_types.DsfPfcHealthCheckIn]):
    CHECK_NAME: hc_types.CheckName = hc_types.CheckName.DSF_PFC_CHECK

    # Class-level snapshot store keyed by
    # (test-case start time, device, interface, priority) → (out_pfc, in_pfc).
    # Populated when the HC runs with
    # check_params["mode"] == "snapshot" (typically in prechecks) and consumed as
    # the pretest baseline when the HC runs with mode == "check" (postchecks).
    # Bypasses the fb303 hw_agent .sum.60 windowed-counter aggregation race that
    # transiently returns 0 mid-cycle.
    _snapshots: t.Dict[t.Tuple[str, str, str, int], t.Tuple[int, int]] = {}
    _snapshot_created_at: t.Dict[t.Tuple[str, str, str, int], float] = {}
    _SNAPSHOT_TTL_SECONDS = 24 * 60 * 60

    @classmethod
    def _discard_snapshot(cls, key: t.Tuple[str, str, str, int]) -> None:
        cls._snapshots.pop(key, None)
        cls._snapshot_created_at.pop(key, None)

    @classmethod
    def _prune_expired_snapshots(cls) -> None:
        cutoff = time.monotonic() - cls._SNAPSHOT_TTL_SECONDS
        for key, created_at in list(cls._snapshot_created_at.items()):
            if created_at < cutoff:
                cls._discard_snapshot(key)

    def _build_thresholds_from_check_params(
        self,
        obj: TestDevice,
        check_params: t.Dict[str, t.Any],
    ) -> t.List[hc_types.DsfPfcThreshold]:
        """Build thresholds dynamically from check_params + TestDevice interfaces.

        check_params (JSON):
            priorities: list[int] — PFC priority classes (default: [0..7])
            in_pfc_frames: int — max acceptable in PFC frames (default: 0)
            out_pfc_frames: int — max acceptable out PFC frames (default: 0)
            comparison: str — a ComparisonType member name (default:
                "EQUAL_TO"). Unknown or unsupported names are a configuration
                error, not a silent fallback.

        Raises:
            ValueError: if ``comparison`` is not a supported ComparisonType.
        """
        priorities = check_params.get("priorities", list(range(8)))
        in_threshold = check_params.get("in_pfc_frames", 0)
        out_threshold = check_params.get("out_pfc_frames", 0)
        # check_params comes from JSON, so `comparison` need not be a string.
        # str() first: .strip() on an int would raise AttributeError past the
        # KeyError handler and crash the check instead of reporting a config
        # error.
        comparison_str = str(check_params.get("comparison", "EQUAL_TO"))
        try:
            comparison = hc_types.ComparisonType[comparison_str.strip()]
        except KeyError as e:
            raise ValueError(
                f"Unknown comparison {comparison_str!r}; expected one of "
                f"{_supported_comparison_names()}"
            ) from e
        _validate_comparison(comparison)
        endpoints = [f"{obj.name}:{intf.interface_name}" for intf in obj.interfaces]
        return [
            hc_types.DsfPfcThreshold(
                interfaces=endpoints,
                in_pfc=in_threshold,
                out_pfc=out_threshold,
                comparison=comparison,
                priority=hc_types.Priority(priority),
            )
            for priority in priorities
        ]

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.DsfPfcHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        try:
            if not input.thresholds:
                input = hc_types.DsfPfcHealthCheckIn(
                    thresholds=self._build_thresholds_from_check_params(
                        obj, check_params
                    )
                )
            # Reject an unevaluable comparison before reading any counter, so a
            # misconfigured threshold surfaces as a configuration error rather
            # than as a passing check.
            for threshold in input.thresholds:
                _validate_comparison(threshold.comparison)
                for endpoint in threshold.interfaces:
                    _parse_endpoint(endpoint)
        except ValueError as e:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.ERROR,
                message=str(e),
            )
        operating_system = obj.attributes.operating_system
        mode = check_params.get("mode", "windowed_60")
        if operating_system != "FBOSS" and mode != "windowed_60":
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.ERROR,
                message=(
                    f"DsfPfcHealthCheck mode={mode!r} requires FBOSS; "
                    f"got {operating_system!r}"
                ),
            )
        match operating_system:
            case "FBOSS":
                return await self._run_fboss_pfc_health_check(obj, input, check_params)
            case "EOS":
                return await self._run_eos_pfc_health_check(obj, input, check_params)
            case _:
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.FAIL,
                    message=f"Unsupported operating system: {operating_system}",
                )

    async def _run_fboss_pfc_health_check(
        self,
        obj: TestDevice,
        input: hc_types.DsfPfcHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        # mode controls how PFC counters are sampled:
        #   "windowed_60" (default): read `.sum.60` — matches legacy behavior,
        #     but on fboss_hw_agent this counter races with the aggregation
        #     writer and can transiently return 0 mid-cycle.
        #   "snapshot": read monotonic `.sum` and store as pretest baseline
        #     keyed by (device, interface, priority). Always returns PASS.
        #   "check": read monotonic `.sum` and compare (current - snapshot)
        #     against threshold. Bypasses the windowed-counter race entirely.
        mode = check_params.get("mode", "windowed_60")
        if mode == "windowed_60":
            return await self._run_fboss_pfc_windowed(input)
        if mode not in ("snapshot", "check"):
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=f"Unsupported DsfPfcHealthCheck mode: {mode}",
            )
        executor_device = check_params.get("executor_device")
        replace_snapshot = bool(check_params.get("replace_snapshot", False))
        snapshot_retry_out_pfc_on_zero = bool(
            check_params.get("snapshot_retry_out_pfc_on_zero", False)
        )
        snapshot_id = str(check_params.get("snapshot_id", "legacy"))
        if executor_device is not None and not is_same_device(
            str(executor_device), obj.name
        ):
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.PASS,
                message=(
                    f"Skipping DSF PFC check on non-executor DUT {obj.name!r}; "
                    f"selected executor is {executor_device!r}."
                ),
            )
        endpoints_to_check = [
            (device, interface, endpoint, threshold)
            for threshold in input.thresholds
            for endpoint in threshold.interfaces
            for device, interface in [_parse_endpoint(endpoint)]
            if executor_device is not None or is_same_device(device, obj.name)
        ]
        consumed_keys = {
            (snapshot_id, device, interface, int(threshold.priority))
            for device, interface, _endpoint, threshold in endpoints_to_check
        }
        if mode == "snapshot" and replace_snapshot:
            for key in consumed_keys:
                self._discard_snapshot(key)
        for device, interface, endpoint, threshold in endpoints_to_check:
            failure = await self._check_fboss_monotonic_endpoint(
                snapshot_id,
                device,
                interface,
                endpoint,
                threshold,
                mode,
                snapshot_retry_out_pfc_on_zero,
            )
            if failure is not None:
                return failure

        if mode == "check":
            for key in consumed_keys:
                self._discard_snapshot(key)
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
        )

    async def _check_fboss_monotonic_endpoint(
        self,
        snapshot_id: str,
        device: str,
        interface: str,
        endpoint: str,
        threshold: hc_types.DsfPfcThreshold,
        mode: str,
        snapshot_retry_out_pfc_on_zero: bool,
    ) -> t.Optional[hc_types.HealthCheckResult]:
        priority = int(threshold.priority)
        key, baseline, failure = self._prepare_monotonic_baseline(
            snapshot_id, device, interface, priority, mode
        )
        if failure is not None:
            return failure
        max_attempts = 10 if snapshot_retry_out_pfc_on_zero else 5
        counters, failure = await self._fetch_monotonic_counters(
            device,
            interface,
            priority,
            endpoint,
            baseline,
            mode,
            max_attempts,
            snapshot_retry_out_pfc_on_zero,
        )
        if failure is not None:
            return failure
        if counters is None:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.ERROR,
                message=(
                    f"No monotonic PFC counters returned for {endpoint} "
                    f"priority{priority}"
                ),
            )
        out_pfc_sum, in_pfc_sum = counters

        if mode == "snapshot":
            self._store_snapshot(
                key,
                endpoint,
                priority,
                out_pfc_sum,
                in_pfc_sum,
            )
            return None

        return await self._evaluate_monotonic_delta(
            key,
            device,
            interface,
            endpoint,
            threshold,
            priority,
            out_pfc_sum,
            in_pfc_sum,
            max_attempts,
            baseline,
        )

    def _prepare_monotonic_baseline(
        self,
        snapshot_id: str,
        device: str,
        interface: str,
        priority: int,
        mode: str,
    ) -> t.Tuple[
        t.Tuple[str, str, str, int],
        t.Tuple[int, int],
        t.Optional[hc_types.HealthCheckResult],
    ]:
        key = (snapshot_id, device, interface, priority)
        if mode == "check" and key not in self._snapshots:
            return (
                key,
                (0, 0),
                hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.FAIL,
                    message=(
                        "DsfPfcHealthCheck mode=check requires a prior snapshot for "
                        f"{device} {interface} priority{priority}; wire a "
                        "mode=snapshot precheck first."
                    ),
                ),
            )
        return key, self._snapshots.get(key, (0, 0)), None

    async def _fetch_monotonic_counters(
        self,
        device: str,
        interface: str,
        priority: int,
        endpoint: str,
        baseline: t.Tuple[int, int],
        mode: str,
        max_attempts: int,
        snapshot_retry_out_pfc_on_zero: bool,
    ) -> t.Tuple[
        t.Optional[t.Tuple[int, int]],
        t.Optional[hc_types.HealthCheckResult],
    ]:
        try:
            return (
                await self._get_fboss_monotonic_pfc_counters(
                    device,
                    interface,
                    priority,
                    endpoint,
                    baseline,
                    mode,
                    max_attempts,
                    snapshot_retry_out_pfc_on_zero,
                ),
                None,
            )
        except Exception as e:
            return None, hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=(
                    f"Failed to fetch priority{priority} monotonic counters for "
                    f"{device} {interface}: {str(e)}"
                ),
            )

    def _store_snapshot(
        self,
        key: t.Tuple[str, str, str, int],
        endpoint: str,
        priority: int,
        out_pfc_sum: int,
        in_pfc_sum: int,
    ) -> None:
        self._prune_expired_snapshots()
        if key in self._snapshots:
            prior_out, prior_in = self._snapshots[key]
            out_pfc_sum = max(out_pfc_sum, prior_out)
            in_pfc_sum = max(in_pfc_sum, prior_in)
        self._snapshots[key] = (out_pfc_sum, in_pfc_sum)
        self._snapshot_created_at[key] = time.monotonic()
        self.logger.info(
            f"Snapshotted {endpoint} priority{priority} - in_pfc_sum: "
            f"{in_pfc_sum}, out_pfc_sum: {out_pfc_sum}"
        )

    async def _evaluate_monotonic_delta(
        self,
        key: t.Tuple[str, str, str, int],
        device: str,
        interface: str,
        endpoint: str,
        threshold: hc_types.DsfPfcThreshold,
        priority: int,
        out_pfc_sum: int,
        in_pfc_sum: int,
        max_attempts: int,
        baseline: t.Tuple[int, int],
    ) -> t.Optional[hc_types.HealthCheckResult]:
        baseline_out, baseline_in = baseline
        if out_pfc_sum < baseline_out or in_pfc_sum < baseline_in:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=(
                    "PFC counters remained below the snapshot baseline "
                    f"after {max_attempts} attempts for {endpoint} priority{priority}: "
                    f"current=({out_pfc_sum}, {in_pfc_sum}), "
                    f"baseline=({baseline_out}, {baseline_in})"
                ),
            )
        out_pfc = out_pfc_sum - baseline_out
        in_pfc = in_pfc_sum - baseline_in
        self.logger.info(
            f"At {endpoint} priority{priority} observed - in_pfc: {in_pfc}, "
            f"out_pfc: {out_pfc} (delta from snapshot: in_sum "
            f"{baseline_in}→{in_pfc_sum}, out_sum {baseline_out}→{out_pfc_sum})"
        )
        for counter_name, observed, expected in (
            ("out_pfc", out_pfc, threshold.out_pfc),
            ("in_pfc", in_pfc, threshold.in_pfc),
        ):
            if expected is not None and await self._compare_pfc(
                threshold.comparison, observed, expected
            ):
                return await self.create_failure_result(
                    device,
                    interface,
                    counter_name,
                    observed,
                    expected,
                    threshold.comparison,
                    priority,
                )
        return None

    async def _get_fboss_monotonic_pfc_counters(
        self,
        device: str,
        interface: str,
        priority: int,
        endpoint: str,
        baseline: t.Tuple[int, int],
        mode: str,
        max_attempts: int,
        snapshot_retry_out_pfc_on_zero: bool,
    ) -> t.Tuple[int, int]:
        out_key = f"{interface}.out_pfc_frames.priority{priority}.sum"
        in_key = f"{interface}.in_pfc_frames.priority{priority}.sum"
        out_pfc_sum = 0
        in_pfc_sum = 0
        expected_counter_keys = {out_key, in_key}
        async with await get_fb303_client(device) as client:
            for attempt in range(max_attempts):
                # Require a complete counter pair in the current retry attempt.
                # Accumulating presence across attempts can hide counters that
                # disappear while an agent is restarting.
                observed_counter_keys: t.Set[str] = set()
                burst: list[t.Tuple[int, int]] = []
                for _ in range(3):
                    counters = await client.getSelectedCounters([out_key, in_key])
                    if out_key in counters:
                        observed_counter_keys.add(out_key)
                    if in_key in counters:
                        observed_counter_keys.add(in_key)
                    burst.append((counters.get(out_key, 0), counters.get(in_key, 0)))
                out_pfc_sum = max(out_pfc_sum, max(sample[0] for sample in burst))
                in_pfc_sum = max(in_pfc_sum, max(sample[1] for sample in burst))
                missing_counter_keys = expected_counter_keys - observed_counter_keys
                if missing_counter_keys:
                    if attempt < max_attempts - 1:
                        self.logger.warning(
                            f"PFC counters missing at {endpoint} priority{priority} "
                            f"(attempt {attempt + 1}/{max_attempts}): "
                            f"{sorted(missing_counter_keys)}"
                        )
                        await asyncio.sleep(0.2)
                        continue
                    raise RuntimeError(
                        f"PFC counters missing for {endpoint} priority{priority}: "
                        f"{sorted(missing_counter_keys)}"
                    )
                if mode == "check" and (
                    out_pfc_sum >= baseline[0] and in_pfc_sum >= baseline[1]
                ):
                    break
                if mode == "snapshot" and (
                    not snapshot_retry_out_pfc_on_zero or out_pfc_sum > 0
                ):
                    break
                if mode == "check":
                    self.logger.warning(
                        f"Racy zero suspected at {endpoint} priority{priority} "
                        f"(attempt {attempt + 1}/{max_attempts}): current "
                        f"out_sum={out_pfc_sum}, in_sum={in_pfc_sum}; "
                        f"baseline={baseline}"
                    )
                if attempt < max_attempts - 1:
                    await asyncio.sleep(0.2)
        if mode == "snapshot" and snapshot_retry_out_pfc_on_zero and out_pfc_sum == 0:
            self.logger.warning(
                f"PFC out counter remained zero at {endpoint} priority{priority} "
                f"after {max_attempts} attempts; using zero as the snapshot baseline"
            )
        return out_pfc_sum, in_pfc_sum

    async def _run_fboss_pfc_windowed(
        self,
        input: hc_types.DsfPfcHealthCheckIn,
    ) -> hc_types.HealthCheckResult:
        """Legacy windowed `.sum.60` path — preserved for backward compatibility
        with existing callers that do not opt into snapshot mode."""
        for threshold in input.thresholds:
            for endpoint in threshold.interfaces:
                device, interface = _parse_endpoint(endpoint)
                priority = int(threshold.priority)
                try:
                    async with await get_fb303_client(device) as client:
                        counter = await client.getSelectedCounters(
                            [
                                f"{interface}.out_pfc_frames.priority{priority}.sum.60",
                                f"{interface}.in_pfc_frames.priority{priority}.sum.60",
                            ]
                        )
                    out_pfc = counter.get(
                        f"{interface}.out_pfc_frames.priority{priority}.sum.60", 0
                    )
                    in_pfc = counter.get(
                        f"{interface}.in_pfc_frames.priority{priority}.sum.60", 0
                    )
                    self.logger.info(
                        f"At {endpoint} priority{priority} observed - in_pfc: {in_pfc}, out_pfc: {out_pfc}"
                    )
                except Exception as e:
                    return hc_types.HealthCheckResult(
                        status=hc_types.HealthCheckStatus.FAIL,
                        message=f"Failed to fetch priority{priority} counters for {device} {interface}: {str(e)}",
                    )
                if threshold.out_pfc is not None:
                    if await self._compare_pfc(
                        threshold.comparison, out_pfc, threshold.out_pfc
                    ):
                        return await self.create_failure_result(
                            device,
                            interface,
                            "out_pfc",
                            out_pfc,
                            threshold.out_pfc,
                            threshold.comparison,
                            priority,
                        )
                if threshold.in_pfc is not None:
                    if await self._compare_pfc(
                        threshold.comparison, in_pfc, threshold.in_pfc
                    ):
                        return await self.create_failure_result(
                            device,
                            interface,
                            "in_pfc",
                            in_pfc,
                            threshold.in_pfc,
                            threshold.comparison,
                            priority,
                        )
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
        )

    async def _run_eos_pfc_health_check(
        self,
        obj: TestDevice,
        input: hc_types.DsfPfcHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        for threshold in input.thresholds:
            for endpoint in threshold.interfaces:
                device, interface = _parse_endpoint(endpoint)
                priority = int(threshold.priority)
                try:
                    counters = await self._get_eos_pfc_counters(interface, priority)
                    out_pfc = counters["txFrames"]
                    in_pfc = counters["rxFrames"]
                    self.logger.info(
                        f"At {endpoint} priority{priority} observed - in_pfc: {in_pfc}, out_pfc: {out_pfc}"
                    )
                except Exception as e:
                    return hc_types.HealthCheckResult(
                        status=hc_types.HealthCheckStatus.FAIL,
                        message=f"Failed to fetch priority{priority} counters for {device} {interface}: {str(e)}",
                    )

                # Check out_pfc if threshold is provided
                if threshold.out_pfc is not None:
                    if await self._compare_pfc(
                        threshold.comparison, out_pfc, threshold.out_pfc
                    ):
                        return await self.create_failure_result(
                            device,
                            interface,
                            "out_pfc",
                            out_pfc,
                            threshold.out_pfc,
                            threshold.comparison,
                            priority,
                        )

                # Check in_pfc if threshold is provided
                if threshold.in_pfc is not None:
                    if await self._compare_pfc(
                        threshold.comparison, in_pfc, threshold.in_pfc
                    ):
                        return await self.create_failure_result(
                            device,
                            interface,
                            "in_pfc",
                            in_pfc,
                            threshold.in_pfc,
                            threshold.comparison,
                            priority,
                        )

        # Return PASS if no failures
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
        )

    async def _get_eos_pfc_counters(
        self,
        interface: str,
        priority: int,
    ) -> t.Dict[str, int]:
        cmd = f"show interface {interface} priority-flow-control counters detail | json"
        # pyrefly: ignore [missing-attribute]
        response = await self.driver.async_execute_show_json_on_shell(cmd)
        return response["interfaces"][interface]["priorities"][str(priority)]

    async def create_failure_result(
        self,
        device: str,
        interface: str,
        pfc_type,
        observed_pfc,
        threshold_value,
        threshold_comparison,
        priority: int,
    ):
        # Use the Everpaste URL directly; it is already a clickable internalfb.com
        # link, so the throttled fburl tier (createFBUrl) is unnecessary here.
        everpaste_url = await async_everpaste_str(f"{pfc_type}: {observed_pfc}")
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.FAIL,
            message=f"Traffic on {device} {interface} for {pfc_type} (priority {priority}) exceeds the threshold of {threshold_value}. "
            f"Observed {pfc_type}: {observed_pfc}. Failure report: {everpaste_url}",
        )

    async def _compare_pfc(
        self,
        comparison: hc_types.ComparisonType,
        observed_pfc: int,
        threshold_value: int = 0,
    ) -> bool:
        """
        Return True when the observed PFC value VIOLATES the threshold.

        Raises:
            ValueError: if ``comparison`` is not supported. Returning False for
            an unimplemented comparison would report the check as healthy.
        """
        _validate_comparison(comparison)
        return not _PFC_COMPARATORS[comparison](observed_pfc, threshold_value)

    async def skip_check(self, obj: TestDevice) -> t.Tuple[bool, str | None]:
        supported_roles = [
            "RDSW",
            "FDSW",
            "EDSW",
            "DTSW",
            "RTSW",
            "SUSW",
            "BAG",
            "GTSW",
        ]
        if obj.attributes.role not in supported_roles:
            return True, f"{obj.name}'s device role is not in {supported_roles}"
        return False, None
