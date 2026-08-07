# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
import asyncio
import os
import time
import typing as t

from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.health_checks.constants import (
    DAILY_TABLE_TRANSFORM_DESC,
    DEFAULT_SERVICE_NAMES,
)
from taac.libs.collectors.cpu_utilization_collector import (
    CpuUtilizationCollector,
)
from taac.libs.collectors.registry import get_collector
from taac.utils.health_check_utils import (
    collector_window_start,
    format_timestamp,
)
from taac.health_check.health_check import types as hc_types
from tabulate import tabulate

TAAC_OSS = os.environ.get("TAAC_OSS", "").lower() in ("1", "true", "yes")

if t.TYPE_CHECKING or not TAAC_OSS:
    from taac.internal.ods_utils import (
        async_generate_ods_url,
        async_query_ods,
    )
    from taac.utils.common import async_get_fburl


CPU_UTILIZATION_KEY_DESC_FBOSS = "regex(cgroup.slice.workload.*({service}).*.cpu.stat.util_pct),!filter(.*(metalos).*)"
CPU_UTILIZATION_KEY_DESC_EOS = "bgpd.process.cpu.percent"


class CpuUtilizationHealthCheck(AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]):
    CHECK_NAME = hc_types.CheckName.CPU_UTILIZATION_CHECK
    OPERATING_SYSTEMS = [
        "FBOSS",
        "EOS",
    ]
    LOG_TO_SCUBA = True

    def _format_cpu_utilization_table(
        self, service_data: t.List[t.Dict[str, t.Any]]
    ) -> str:
        """
        Format CPU utilization data as a table using tabulate library.

        Args:
            service_data: List of dictionaries containing service CPU data

        Returns:
            Formatted table string
        """
        if not service_data:
            return "No CPU utilization data available"

        # Prepare data for tabulate
        table_data = []
        for data in service_data:
            table_data.append(
                [
                    data["service"],
                    f"{data['max_usage']:.2f}",
                    data["max_timestamp"],
                    f"{data['avg_usage']:.2f}",
                ]
            )

        headers = ["Service", "Max CPU (%)", "Max CPU Time", "Avg CPU (%)"]
        table_output = tabulate(table_data, headers=headers, tablefmt="simple_grid")

        return f"CPU Utilization Summary\n{table_output}"

    async def _prepare_time_window(
        self, start_time: int, sleep_timer: int
    ) -> t.Tuple[int, int]:
        """
        Prepare the time window for ODS query by handling sleep timer and minimum window size.

        Args:
            start_time: Initial start time
            sleep_timer: Time to sleep before querying ODS data

        Returns:
            Tuple of (adjusted_start_time, end_time)
        """
        if sleep_timer > 0:
            self.logger.debug(
                f"Sleeping for {sleep_timer} seconds before querying ODS data"
            )
            await asyncio.sleep(sleep_timer)

        end_time = int(time.time())
        if end_time - start_time < 60:
            self.logger.debug(
                f"Time window too small ({end_time - start_time}s), adjusting start_time"
            )
            start_time = start_time - 60

        return start_time, end_time

    async def _query_cpu_utilization_data(
        self, device_name: str, services: t.List[str], start_time: int, end_time: int
    ) -> t.Dict[str, t.Dict[int, float]]:
        """
        Query CPU utilization data from ODS.

        Args:
            device_name: Name of the device
            services: List of services to query
            start_time: Query start time
            end_time: Query end time

        Returns:
            CPU utilization data dictionary

        Raises:
            Exception: If ODS query returns no data
        """
        key_desc = ",".join(
            [
                CPU_UTILIZATION_KEY_DESC_FBOSS.format(service=service)
                for service in services
            ]
        )

        ods_data = await async_query_ods(
            entity_desc=device_name,
            key_desc=key_desc,
            transform_desc=DAILY_TABLE_TRANSFORM_DESC,
            start_time=int(start_time),
            end_time=int(end_time),
        )

        if not ods_data:
            ods_query_url = await async_generate_ods_url(
                entity_desc=device_name,
                key_desc=key_desc,
                start_time=int(start_time),
                end_time=int(end_time),
            )
            # No fburl here: this URL only ever reaches a debug log before we
            # return {}, so shortening it through the throttled fburl tier is
            # pure waste.
            self.logger.debug(f"ODS query returned no data: {ods_query_url}")
            return {}

        # Convert nested mappings to dicts to satisfy type checker
        result = {}
        for key, value_mapping in ods_data[device_name].items():
            result[key] = dict(value_mapping)
        return result

    def _process_service_data(
        self,
        cpu_util_data: t.Dict[str, t.Dict[int, float]],
        threshold: float,
        threshold_by_service: t.Dict[str, float],
    ) -> t.Tuple[t.List[str], t.Set[str], t.List[t.Dict[str, t.Any]]]:
        """
        Process CPU utilization data to identify threshold violations and collect service statistics.

        Args:
            cpu_util_data: Raw CPU utilization data from ODS
            threshold: Default threshold value
            threshold_by_service: Service-specific threshold overrides

        Returns:
            Tuple of (threshold_violations, failing_services, service_data_list)
        """
        cpu_util_exceeds_threshold = []
        failing_services = set()
        service_data_list = []

        for key_desc, data in cpu_util_data.items():
            service = key_desc.split(".")[3]

            # Check for threshold violations
            for timestamp, value in data.items():
                service_cpu_util_threshold = threshold_by_service.get(
                    service, threshold
                )
                if value > service_cpu_util_threshold:
                    msg = (
                        f"CPU utilization for {service} at {format_timestamp(timestamp)} "
                        f"exceeds threshold {service_cpu_util_threshold} with value {value}"
                    )
                    self.logger.debug(msg)
                    cpu_util_exceeds_threshold.append(msg)
                    failing_services.add(service)

            # Calculate service statistics
            max_usage = max(data.values())
            max_timestamp = max(data.keys(), key=lambda k: data[k])
            max_timestamp_readable = format_timestamp(max_timestamp)
            avg_usage = sum(data.values()) / len(data.values())

            # Collect service data for table display
            service_data_list.append(
                {
                    "service": service,
                    "max_usage": max_usage,
                    "max_timestamp": max_timestamp_readable,
                    "avg_usage": avg_usage,
                }
            )

            # Log service data
            self.add_data_to_log(
                {
                    f"max_{service}_cpu_usage_usec": max_usage,
                    f"max_{service}_cpu_usage_timestamp": max_timestamp_readable,
                    f"avg_{service}_cpu_usage_usec": avg_usage,
                }
            )

        return cpu_util_exceeds_threshold, failing_services, service_data_list

    async def _generate_failure_result(
        self,
        device_name: str,
        threshold_violations: t.List[str],
        failing_services: t.Set[str],
        start_time: int,
        end_time: int,
    ) -> hc_types.HealthCheckResult:
        """
        Generate failure result with ODS URL for failing services.

        Args:
            device_name: Name of the device
            threshold_violations: List of threshold violation messages
            failing_services: Set of services that failed
            start_time: Query start time
            end_time: Query end time

        Returns:
            HealthCheckResult with failure status and ODS URL
        """
        self.logger.info(
            f"CPU utilization health check FAILED for device {device_name}. "
            f"Found {len(threshold_violations)} threshold violations"
        )

        threshold_violations_text = "\n".join(threshold_violations)

        # Generate ODS URL with only failing services
        failing_services_key_desc = ",".join(
            [
                CPU_UTILIZATION_KEY_DESC_FBOSS.format(service=service)
                for service in failing_services
            ]
        )
        ods_query_url = await async_generate_ods_url(
            entity_desc=device_name,
            key_desc=failing_services_key_desc,
            start_time=int(start_time),
            end_time=int(end_time),
        )
        ods_url = await async_get_fburl(ods_query_url)

        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.FAIL,
            message=f"CPU utilization exceeded defined threshold:\n{threshold_violations_text}\n\nODS Query URL: {ods_url}",
        )

    async def _run_arista(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        """
        Args:
            check_params:
                - delta: Max allowed delta between cpu utilization checks. When
                    not provided the check is skipped, since the Arista path is
                    sampling-based and has no meaningful default.
                - sleep_timer: Time to sleep before gettig counter again (defaults to 60 seconds)
                - total_time: Total time to measure counters (defaults to 2 min)
        """
        # TODO(loo): Once we get ODS support use ODS instead
        delta = check_params.get("delta")
        if delta is None:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.SKIP,
                message=(
                    "CPU utilization check skipped on Arista device "
                    f"{obj.name}: no 'delta' threshold configured."
                ),
            )
        sleep_timer = check_params.get("sleep_timer", 60)
        total_time = check_params.get("total_time", 120)

        # pyrefly: ignore [missing-attribute]
        last_count = await self.driver.async_get_counter(CPU_UTILIZATION_KEY_DESC_EOS)
        self.logger.debug(f"Initial CPU utilization count: {last_count}")
        iterations = total_time // sleep_timer

        for i in range(iterations):
            self.logger.debug(
                f"Sleeping for {sleep_timer} seconds (iteration {i + 1}/{iterations})"
            )
            await asyncio.sleep(sleep_timer)
            # pyrefly: ignore [missing-attribute]
            current_count = await self.driver.async_get_counter(
                CPU_UTILIZATION_KEY_DESC_EOS
            )
            count_delta = abs(current_count - last_count)
            self.logger.debug(
                f"last_count={last_count}, current_count={current_count}, delta={count_delta}"
            )
            if count_delta > delta:
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.FAIL,
                    message=f"CPU utilization delta exceeded threshold on {obj.name}: "
                    f"delta={count_delta}, threshold={delta}, "
                    f"last={last_count}, current={current_count}",
                )
            last_count = current_count

        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
            message=f"CPU utilization delta is within the defined threshold on {obj.name}.",
        )

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        if TAAC_OSS:
            return await self._run_oss(obj, check_params)

        self.logger.info(
            f"Starting CPU utilization health check for device: {obj.name}"
        )

        # Extract parameters
        start_time: int = check_params.get("start_time", int(time.time()))
        services: t.List[str] = check_params.get("services", DEFAULT_SERVICE_NAMES)
        threshold_by_service: t.Dict[str, float] = check_params.get(
            "threshold_by_service", {}
        )
        threshold: float = check_params.get("threshold", 70.0)
        sleep_timer = check_params.get("sleep_timer", 120)

        self.logger.debug(
            f"Check parameters - start_time: {format_timestamp(start_time)}, services: {services}, "
            f"threshold: {threshold}, threshold_by_service: {threshold_by_service}, "
            f"sleep_timer: {sleep_timer}"
        )

        # Prepare time window
        start_time, end_time = await self._prepare_time_window(start_time, sleep_timer)

        # Query CPU utilization data
        try:
            cpu_util_data = await self._query_cpu_utilization_data(
                obj.name, services, start_time, end_time
            )
        except Exception as e:
            # ODS counter-side throttling is a transient infra issue, not a
            # DUT-side problem. Treat as SKIP so the playbook doesn't
            # false-fail (the next playbook retries naturally after backoff).
            # See sibling fix in MemoryUtilizationHealthCheck.
            err_msg = str(e)
            if "throttling your requests" in err_msg.lower():
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.SKIP,
                    message=(
                        f"ODS counter throttled — skipping this iteration of "
                        f"CpuUtilizationHealthCheck (will retry on next "
                        f"playbook). Underlying error: {err_msg}"
                    ),
                )
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=err_msg,
            )
        if not cpu_util_data:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.SKIP,
                message="ODS query returned no data",
            )

        self.logger.debug(
            f"Processing CPU utilization data for {len(cpu_util_data)} services"
        )

        # Process service data and check thresholds
        threshold_violations, failing_services, service_data_list = (
            self._process_service_data(cpu_util_data, threshold, threshold_by_service)
        )

        # Display service data table
        if service_data_list:
            table_output = self._format_cpu_utilization_table(service_data_list)
            self.logger.info(f"\n{table_output}")

        # Return result based on threshold violations
        if threshold_violations:
            return await self._generate_failure_result(
                obj.name, threshold_violations, failing_services, start_time, end_time
            )

        self.logger.info(f"CPU utilization health check PASSED for device {obj.name}")
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
            message="CPU utilization is within the defined threshold.",
        )

    async def _run_oss(
        self,
        obj: TestDevice,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        """OSS path — no ODS.

        Requires a ``CpuUtilizationCollector`` started as a setup task and
        registered under ``"cpu_utilization"``. Queries the collector's
        ``max_per_service_in_window`` for the check window, which gives
        MAX-over-window semantics closer to the ODS ``cpu.stat.util_pct``
        counter. The window defaults to ``[test_case_start_time, now]`` —
        the current playbook iteration — and can be overridden per-check
        via ``check_params["window_start"]`` / ``["window_end"]``.
        """
        services = check_params.get("services", DEFAULT_SERVICE_NAMES)
        threshold_by_service = check_params.get("threshold_by_service", {})
        threshold = check_params.get("threshold", 70.0)

        return await self._run_oss_via_collector(
            obj, services, threshold, threshold_by_service, check_params
        )

    async def _run_oss_via_collector(
        self,
        obj: TestDevice,
        services: t.Sequence[str],
        threshold: float,
        threshold_by_service: t.Dict[str, float],
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        """MAX-over-window CPU check backed by a live collector.

        Query window defaults to the current playbook iteration (``[test_case
        _start_time, now]``). Fallbacks: if ``test_case_start_time`` is unset,
        use ``[now - lookback_sec, now]`` (default ``lookback_sec=900``).
        Callers can override either endpoint via ``check_params``.
        """
        collector = get_collector("cpu_utilization")
        if not isinstance(collector, CpuUtilizationCollector):
            # CollectorsTestHandler starts collectors for every OSS test
            # config, so a missing one here is unexpected. SKIP (not FAIL) per
            # registry.get_collector's contract, but warn loudly -- silently
            # losing this check's coverage is exactly the failure mode SKIP is
            # meant to make visible.
            self.logger.warning(
                "No CpuUtilizationCollector registered under 'cpu_utilization' -- "
                "CollectorsTestHandler runs by default under TAAC_OSS, so this "
                "means either no FBOSS device in the topology, the "
                "'no_oss_collectors' opt-out tag, or a failed handler setUp. "
                "Skipping."
            )
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.SKIP,
                message=(
                    "No CpuUtilizationCollector registered under 'cpu_utilization'. "
                    "The test config didn't start one — this check has nothing to "
                    "evaluate."
                ),
            )
        if collector.host != obj.name:
            # Only one DUT gets a collector today (see CollectorsTestHandler);
            # a mismatch means we'd be evaluating the wrong device's samples.
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.SKIP,
                message=(
                    f"Registered CpuUtilizationCollector is bound to host "
                    f"'{collector.host}', not '{obj.name}' — multi-DUT collector "
                    "support isn't implemented; skipping this device."
                ),
            )
        now = time.time()
        window_end = check_params.get("window_end", now)
        lookback_sec = check_params.get("lookback_sec", 900)
        window_start = check_params.get(
            "window_start",
            collector_window_start(check_params, window_end, lookback_sec),
        )

        max_per_service = collector.max_per_service_in_window(window_start, window_end)

        missing_from_collector = [s for s in services if s not in collector.services]
        if missing_from_collector:
            self.logger.warning(
                f"Requested services not monitored by the running "
                f"CpuUtilizationCollector (started with services="
                f"{collector.services}): {missing_from_collector}. These will "
                f"not be checked."
            )

        violations: t.List[str] = []
        service_data_list: t.List[t.Dict[str, t.Any]] = []
        for service in services:
            max_pct = max_per_service.get(service)
            if max_pct is None:
                # Collector had no measurable sample for this service in the
                # window — most likely masked/inactive. Skip, same as the
                # fallback-path treatment.
                continue

            svc_threshold = threshold_by_service.get(service, threshold)
            service_data_list.append(
                {
                    "service": service,
                    "cpu_pct": max_pct,
                    "threshold": svc_threshold,
                }
            )
            self.add_data_to_log({f"current_{service}_cpu_pct": max_pct})

            if max_pct > svc_threshold:
                violations.append(
                    f"{service}: {max_pct:.1f}% > {svc_threshold}% threshold "
                    f"(MAX-over-window from continuous collector)"
                )

        if not service_data_list:
            # No requested service had a measurable sample in the window --
            # don't report PASS on an empty check.
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.SKIP,
                message=(
                    "CpuUtilizationCollector had no measurable samples for any "
                    f"requested service in window [{window_start:.0f}, "
                    f"{window_end:.0f}] (services may be masked/inactive, or "
                    "the collector hasn't polled yet)."
                ),
            )

        window_sec = max(0.0, window_end - window_start)
        table_rows = [
            [d["service"], f"{d['cpu_pct']:.2f}", f"{d['threshold']}"]
            for d in service_data_list
        ]
        self.logger.info(
            "\nCPU Utilization Summary (OSS collector, "
            f"MAX over {window_sec:.0f}s window)\n"
            + tabulate(
                table_rows,
                headers=["Service", "CPU (%) [MAX]", "Threshold (%)"],
                tablefmt="simple_grid",
            )
        )

        # Warn — don't fail — if the collector recorded any poll timeouts in
        # the window. For CPU/mem the samples we DO have are still meaningful;
        # a poll timeout here means one SSH command timed out, not that the
        # DUT was unhealthy.
        timeouts = collector.timeout_count_in_window(window_start, window_end)
        if timeouts > 0:
            self.logger.warning(
                f"CpuUtilizationCollector had {timeouts} poll timeout(s) in "
                f"window [{window_start:.0f}, {window_end:.0f}] — some samples "
                f"may be missing but the MAX below is based on what did land."
            )

        if violations:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=(
                    f"CPU utilization exceeded threshold on {obj.name}:\n"
                    + "\n".join(violations)
                ),
            )
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
            message="CPU utilization is within the defined threshold.",
        )
