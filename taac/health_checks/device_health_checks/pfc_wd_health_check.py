# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import asyncio
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


def _parse_endpoint(endpoint: str) -> t.Tuple[str, str]:
    parts = endpoint.split(":", 1)
    if len(parts) != 2 or not all(parts):
        raise ValueError(
            f"Invalid PFC watchdog endpoint {endpoint!r}; expected 'device:interface'"
        )
    return parts[0], parts[1]


class PfcWdHealthCheck(AbstractDeviceHealthCheck[hc_types.PfcWdHealthCheckIn]):
    CHECK_NAME: hc_types.CheckName = hc_types.CheckName.PFC_WD_CHCEK

    # Precheck and postcheck use separate health-check instances, so the baseline
    # must be shared. The test-case start time isolates concurrent and subsequent
    # runs. Failed checks retain their baseline for framework retries. Entries
    # older than a full day are abandoned-run state and are pruned without
    # evicting baselines from normal in-flight tests.
    _snapshots: t.Dict[t.Tuple[str, str, str], t.Tuple[int, int]] = {}
    _snapshot_created_at: t.Dict[t.Tuple[str, str, str], float] = {}
    _SNAPSHOT_TTL_SECONDS = 24 * 60 * 60

    @classmethod
    def _discard_snapshot(cls, key: t.Tuple[str, str, str]) -> None:
        cls._snapshots.pop(key, None)
        cls._snapshot_created_at.pop(key, None)

    @classmethod
    def _prune_expired_snapshots(cls) -> None:
        cutoff = time.monotonic() - cls._SNAPSHOT_TTL_SECONDS
        for key, created_at in list(cls._snapshot_created_at.items()):
            if created_at < cutoff:
                cls._discard_snapshot(key)

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.PfcWdHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        try:
            for threshold in input.thresholds:
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
                    f"PfcWdHealthCheck mode={mode!r} requires FBOSS; "
                    f"got {operating_system!r}"
                ),
            )
        match operating_system:
            case "FBOSS":
                return await self._run_fboss_pfc_wd_health_check(
                    obj, input, check_params
                )
            case "EOS":
                return await self._run_eos_pfc_wd_health_check(obj, input, check_params)
            case _:
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.FAIL,
                    message=f"Unsupported operating system: {operating_system}",
                )

    async def _run_fboss_pfc_wd_health_check(
        self,
        obj: TestDevice,
        input: hc_types.PfcWdHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        mode = check_params.get("mode", "windowed_60")
        if mode == "windowed_60":
            return await self._run_fboss_pfc_wd_windowed(input)
        if mode not in ("snapshot", "check"):
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.ERROR,
                message=f"Unsupported PfcWdHealthCheck mode: {mode}",
            )
        max_difference = check_params.get("max_detection_recovery_difference")
        if max_difference is not None and (
            not isinstance(max_difference, int)
            or isinstance(max_difference, bool)
            or max_difference < 0
        ):
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.ERROR,
                message=(
                    "max_detection_recovery_difference must be a non-negative "
                    f"integer; got {max_difference!r}"
                ),
            )
        return await self._run_fboss_pfc_wd_monotonic(
            obj, input, check_params, mode, max_difference
        )

    async def _run_fboss_pfc_wd_monotonic(
        self,
        obj: TestDevice,
        input: hc_types.PfcWdHealthCheckIn,
        check_params: t.Dict[str, t.Any],
        mode: str,
        max_difference: t.Optional[int],
    ) -> hc_types.HealthCheckResult:
        snapshot_id = str(check_params.get("snapshot_id", "legacy"))
        executor_device = check_params.get("executor_device")
        if executor_device is not None and not is_same_device(
            str(executor_device), obj.name
        ):
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.PASS,
                message=(
                    f"Skipping PFC watchdog check on non-executor DUT {obj.name!r}; "
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
        if not endpoints_to_check:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.PASS,
                message=(
                    f"Skipping PFC watchdog check on DUT {obj.name!r}; no "
                    "threshold interface belongs to this DUT."
                ),
            )
        snapshot_retry_on_zero = bool(check_params.get("snapshot_retry_on_zero", False))
        replace_snapshot = bool(check_params.get("replace_snapshot", False))
        consumed_keys = {
            (snapshot_id, device, interface)
            for device, interface, _endpoint, _threshold in endpoints_to_check
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
                max_difference,
                snapshot_retry_on_zero,
            )
            if failure is not None:
                return failure

        if mode == "check":
            for key in consumed_keys:
                self._discard_snapshot(key)
        return hc_types.HealthCheckResult(status=hc_types.HealthCheckStatus.PASS)

    async def _check_fboss_monotonic_endpoint(
        self,
        snapshot_id: str,
        device: str,
        interface: str,
        endpoint: str,
        threshold: hc_types.PfcWdThreshold,
        mode: str,
        max_difference: t.Optional[int],
        snapshot_retry_on_zero: bool,
    ) -> t.Optional[hc_types.HealthCheckResult]:
        key = (snapshot_id, device, interface)
        if mode == "check" and key not in self._snapshots:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=(
                    "PfcWdHealthCheck mode=check requires a prior snapshot "
                    f"for {device} {interface}; wire a mode=snapshot precheck first."
                ),
            )
        baseline = self._snapshots.get(key, (0, 0))
        try:
            (
                deadlock_sum,
                recovery_sum,
            ) = await self._get_fboss_monotonic_pfc_wd_counters(
                device=device,
                interface=interface,
                baseline=baseline,
                retry_on_regression=mode == "check",
                retry_on_zero=mode == "snapshot" and snapshot_retry_on_zero,
            )
        except Exception as e:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=(
                    "Failed to fetch monotonic PFC watchdog counters for "
                    f"{device} {interface}: {str(e)}"
                ),
            )

        if mode == "snapshot":
            self._prune_expired_snapshots()
            if key in self._snapshots:
                prior_deadlock, prior_recovery = self._snapshots[key]
                deadlock_sum = max(deadlock_sum, prior_deadlock)
                recovery_sum = max(recovery_sum, prior_recovery)
            self._snapshots[key] = (deadlock_sum, recovery_sum)
            self._snapshot_created_at[key] = time.monotonic()
            self.logger.info(
                f"Snapshotted {endpoint} - pfc_deadlock_detection.sum: "
                f"{deadlock_sum}, pfc_deadlock_recovery.sum: {recovery_sum}"
            )
            return None

        baseline_deadlock, baseline_recovery = baseline
        deadlock = max(0, deadlock_sum - baseline_deadlock)
        recovery = max(0, recovery_sum - baseline_recovery)
        self.logger.info(
            f"At {endpoint} observed - pfc_deadlock_detection: {deadlock}, "
            f"pfc_deadlock_recovery: {recovery} (delta from snapshot: "
            f"detection_sum {baseline_deadlock}→{deadlock_sum}, "
            f"recovery_sum {baseline_recovery}→{recovery_sum})"
        )

        is_violated, message = await self._check_threshold_condition_violated(
            threshold.comparison,
            deadlock,
            recovery,
            threshold.deadlock_threshold,
            threshold.recovery_threshold,
        )
        if is_violated:
            return await self.create_failure_result(
                device, interface, deadlock, recovery, message
            )

        difference = abs(deadlock - recovery)
        if max_difference is not None and difference > max_difference:
            return await self.create_failure_result(
                device,
                interface,
                deadlock,
                recovery,
                "Detection/recovery difference "
                f"{difference} exceeds configured maximum {max_difference}",
            )
        return None

    async def _get_fboss_monotonic_pfc_wd_counters(
        self,
        device: str,
        interface: str,
        baseline: t.Tuple[int, int],
        retry_on_regression: bool,
        retry_on_zero: bool,
    ) -> t.Tuple[int, int]:
        deadlock_key = f"{interface}.pfc_deadlock_detection.sum"
        recovery_key = f"{interface}.pfc_deadlock_recovery.sum"
        deadlock_sum = 0
        recovery_sum = 0
        expected_counter_keys = {deadlock_key, recovery_key}
        max_attempts = 5
        async with await get_fb303_client(device) as client:
            for attempt in range(max_attempts):
                # A retry is valid only when that attempt's sample window contains
                # both counters; retaining keys from an earlier attempt can mask a
                # disappearing FB303 counter during agent recovery.
                observed_counter_keys: t.Set[str] = set()
                for _ in range(3):
                    counters = await client.getSelectedCounters(
                        [deadlock_key, recovery_key]
                    )
                    if deadlock_key in counters:
                        observed_counter_keys.add(deadlock_key)
                        deadlock_sum = max(deadlock_sum, counters[deadlock_key])
                    if recovery_key in counters:
                        observed_counter_keys.add(recovery_key)
                        recovery_sum = max(recovery_sum, counters[recovery_key])
                missing_counter_keys = expected_counter_keys - observed_counter_keys
                if missing_counter_keys:
                    if attempt < max_attempts - 1:
                        self.logger.warning(
                            f"PFC watchdog counters missing at {device}:{interface} "
                            f"(attempt {attempt + 1}/{max_attempts}): "
                            f"{sorted(missing_counter_keys)}"
                        )
                        await asyncio.sleep(0.2)
                        continue
                    raise RuntimeError(
                        f"PFC watchdog counters missing for {device}:{interface}: "
                        f"{sorted(missing_counter_keys)}"
                    )
                retry_needed = (
                    retry_on_regression
                    and (deadlock_sum < baseline[0] or recovery_sum < baseline[1])
                ) or (retry_on_zero and deadlock_sum == 0 and recovery_sum == 0)
                if not retry_needed:
                    break
                self.logger.warning(
                    f"Racy PFC watchdog counter sample suspected at "
                    f"{device}:{interface} (attempt {attempt + 1}/{max_attempts}): "
                    f"current detection_sum={deadlock_sum}, "
                    f"recovery_sum={recovery_sum}; baseline={baseline}"
                )
                if attempt < max_attempts - 1:
                    await asyncio.sleep(0.2)
        if retry_on_regression and (
            deadlock_sum < baseline[0] or recovery_sum < baseline[1]
        ):
            raise RuntimeError(
                "PFC watchdog counters remained below the snapshot baseline "
                f"after {max_attempts} attempts: current="
                f"({deadlock_sum}, {recovery_sum}), "
                f"baseline={baseline}"
            )
        return deadlock_sum, recovery_sum

    async def _run_fboss_pfc_wd_windowed(
        self,
        input: hc_types.PfcWdHealthCheckIn,
    ) -> hc_types.HealthCheckResult:
        for threshold in input.thresholds:
            for endpoint in threshold.interfaces:
                device, interface = _parse_endpoint(endpoint)
                # Fetch counters for the interface from the selected device
                try:
                    async with await get_fb303_client(device) as client:
                        counter = await client.getSelectedCounters(
                            [
                                f"{interface}.pfc_deadlock_detection.sum.60",
                                f"{interface}.pfc_deadlock_recovery.sum.60",
                            ]
                        )
                    deadlock = counter.get(
                        f"{interface}.pfc_deadlock_detection.sum.60", 0
                    )
                    recovery = counter.get(
                        f"{interface}.pfc_deadlock_recovery.sum.60", 0
                    )
                    self.logger.info(
                        f"At {endpoint} observed - pfc_deadlock_detection: {deadlock}, "
                        f"pfc_deadlock_recovery: {recovery}"
                    )

                    # Check for deadlock but no recovery
                    if deadlock > 0 and recovery == 0:
                        return hc_types.HealthCheckResult(
                            status=hc_types.HealthCheckStatus.FAIL,
                            message=f"Deadlock detected on {device} {interface} but no recovery happened",
                        )

                    (
                        is_violated,
                        message,
                    ) = await self._check_threshold_condition_violated(
                        threshold.comparison,
                        deadlock,
                        recovery,
                        threshold.deadlock_threshold,
                        threshold.recovery_threshold,
                    )
                    if is_violated:
                        return await self.create_failure_result(
                            device, interface, deadlock, recovery, message
                        )
                except Exception as e:
                    return hc_types.HealthCheckResult(
                        status=hc_types.HealthCheckStatus.FAIL,
                        message=f"Failed to fetch counters for {device} {interface}: {str(e)}",
                    )

        # Return PASS if no issues were found
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
        )

    # For Arista EOS devices, the PFC watchdog health check must follow this specific sequence:
    # 1. Clear the watchdog counters
    # 2. Start traffic
    # 3. Stop traffic
    # 4. Fetch the watchdog counters
    #
    # This order is critical because:
    # - The "Stuck" counter updates at the start of traffic.
    # - The "Recovery" counter updates at the end of traffic.
    async def _run_eos_pfc_wd_health_check(
        self,
        obj: TestDevice,
        input: hc_types.PfcWdHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        if self.ixia is None:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message="ixia is None, failed to stop traffics and fetch PFC watchdog counters",
            )
        ixia = self.ixia
        # Check the counters for each interface
        for threshold in input.thresholds:
            for endpoint in threshold.interfaces:
                device, interface = _parse_endpoint(endpoint)
                try:
                    self.logger.info("Stopping traffic to fetch PFC watchdog counters")
                    ixia.stop_traffic()
                    await asyncio.sleep(3)
                    counters = await self._get_eos_pfc_wd_counters(interface)
                    stuck_count = counters.get("stuckCount", 0)
                    recovery_count = counters.get("recoveryCount", 0)
                    self.logger.info(
                        f"At {endpoint} observed - PFC watchdog stuck count: {stuck_count}, "
                        f"recovery count: {recovery_count}"
                    )

                    # Check for watchdog stuck but no recovery
                    if stuck_count > 0 and recovery_count == 0:
                        return hc_types.HealthCheckResult(
                            status=hc_types.HealthCheckStatus.FAIL,
                            message=f"Stuck detected on {device} {interface} but no recovery happened",
                        )

                    (
                        is_violated,
                        message,
                    ) = await self._check_threshold_condition_violated(
                        threshold.comparison,
                        stuck_count,
                        recovery_count,
                        threshold.deadlock_threshold,
                        threshold.recovery_threshold,
                    )
                    if is_violated:
                        return await self.create_failure_result(
                            device, interface, stuck_count, recovery_count, message
                        )
                except Exception as e:
                    return hc_types.HealthCheckResult(
                        status=hc_types.HealthCheckStatus.FAIL,
                        message=f"Failed to fetch counters for {device} {interface}: {str(e)}",
                    )

        # Return PASS if no failures
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
        )

    async def _get_eos_pfc_wd_counters(self, interface: str) -> t.Dict[str, int]:
        cmd = "show priority-flow-control counters watchdog | json"
        # pyrefly: ignore [missing-attribute]
        response = await self.driver.async_execute_show_json_on_shell(cmd)
        # Arista returns {"interfaces": {}} when no WD event has fired on any
        # interface, and omits an interface key entirely until that interface
        # has had its first event. Both states are functionally equivalent to
        # stuckCount=0, recoveryCount=0 — treat missing keys as zero.
        tx_queue_data = (
            response.get("interfaces", {})
            .get(interface, {})
            .get("txQueues", {})
            .get("2", {})
        )
        return {
            "stuckCount": tx_queue_data.get("stuckCount", 0),
            "recoveryCount": tx_queue_data.get("recoveryCount", 0),
        }

    async def _check_threshold_condition_violated(
        self,
        comparison: hc_types.ComparisonType,
        deadlock: int,
        recovery: int,
        deadlock_threshold: int = 0,
        recovery_threshold: int = 0,
    ) -> t.Tuple[bool, str]:
        if comparison == hc_types.ComparisonType.LESS_THAN:
            if deadlock >= deadlock_threshold or recovery >= recovery_threshold:
                return True, "Deadlock or Recovery threshold exceeded"
        elif comparison == hc_types.ComparisonType.GREATER_THAN:
            if deadlock <= deadlock_threshold or recovery <= recovery_threshold:
                return True, "Deadlock or Recovery value less than expected threshold"
        elif comparison == hc_types.ComparisonType.EQUAL_TO:
            if deadlock != deadlock_threshold or recovery != recovery_threshold:
                return (
                    True,
                    "Deadlock or Recovery value does not match the expected threshold",
                )
        return False, ""

    async def create_failure_result(
        self,
        device: str,
        interface: str,
        deadlock: int,
        recovery: int,
        failure_message: str,
    ) -> hc_types.HealthCheckResult:
        # Use the Everpaste URL directly; it is already a clickable internalfb.com
        # link, so the throttled fburl tier (createFBUrl) is unnecessary here.
        everpaste_url = await async_everpaste_str(
            f"Deadlock: {deadlock}, Recovery: {recovery}"
        )
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.FAIL,
            message=f"{failure_message} on {device} {interface}. "
            f"Observed Deadlock: {deadlock}, Recovery: {recovery}. Failure report: {everpaste_url}",
        )

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
