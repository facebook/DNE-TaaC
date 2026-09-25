# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
import asyncio
import re
import shlex
import time
import typing as t
from dataclasses import dataclass
from datetime import datetime

from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.health_check.health_check import types as hc_types


@dataclass
class RouteConvergenceMetrics:
    """Metrics collected from route convergence analysis."""

    total_routes_added: int = 0
    total_routes_deleted: int = 0
    num_batches: int = 0
    total_state_update_time_sec: float = 0.0
    first_batch_time: str = ""
    last_batch_time: str = ""


class RouteConvergenceTimeHealthCheck(
    AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]
):
    """
    Health check to validate route convergence time with automatic DELETE→ADD cycles.

    This health check performs complete DELETE→ADD cycles for the specified iterations:
    For each iteration:
    1. DELETE: Disable network groups → Wait → Analyze convergence
    2. ADD: Enable network groups → Wait → Analyze convergence

    Example: iterations=5 means 5 complete cycles of DELETE→ADD (10 total operations)

    Key features:
    - Integrated toggle functionality (calls IXIA API directly)
    - Automatic DELETE→ADD cycling with configurable iterations
    - Uses actual state update processing time (from "Update state took Xus" logs)
    - Parses RouteUpdateWrapper.cpp for route counts (Routes added/deleted)
    - Parses SwSwitch.cpp for state update timing
    - Provides detailed metrics including batch counts and per-operation times

    Parameters:
        network_group_regex (str): Regex to match network groups for toggle.
            Example: ".*PREFIX_STRESSER_CONTIGUOUS.*"
        iterations (int): Number of DELETE→ADD cycles to run. Default: 5
        time_threshold (int): Maximum allowed time in seconds for route convergence. Default: 35
        wait_time_seconds (int): Time to wait for convergence after each toggle. Default: 60
        log_file (str): Path to the log file. Default: "/var/facebook/logs/wedge_agent.log"

    Usage in test config:
        # Run 5 iterations of DELETE→ADD cycles
        PointInTimeHealthCheck(
            name=hc_types.CheckName.ROUTE_CONVERGENCE_TIME_CHECK,
            check_params=Params(json_params=json.dumps({
                "network_group_regex": ".*PREFIX_STRESSER_CONTIGUOUS.*",
                "iterations": 5,
                "time_threshold": 35,
                "wait_time_seconds": 60,
            })),
        )

        # Single DELETE→ADD cycle
        PointInTimeHealthCheck(
            name=hc_types.CheckName.ROUTE_CONVERGENCE_TIME_CHECK,
            check_params=Params(json_params=json.dumps({
                "network_group_regex": ".*PREFIX_STRESSER_NON_CONTIGUOUS.*",
                "iterations": 1,
                "time_threshold": 35,
            })),
        )
    """

    CHECK_NAME = hc_types.CheckName.ROUTE_CONVERGENCE_TIME_CHECK
    OPERATING_SYSTEMS = ["FBOSS"]

    # Default path where toggle start time is stored
    DEFAULT_START_TIME_FILE = "/tmp/toggle_start_time"

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        """
        Run the route convergence time health check with DELETE→ADD cycles.

        This method performs N iterations of:
        1. DELETE: Disable network groups → Wait → Analyze convergence
        2. ADD: Enable network groups → Wait → Analyze convergence

        Args:
            obj (TestDevice): The device to run the health check on.
            input (hc_types.BaseHealthCheckIn): The input parameters for the health check.
            check_params (t.Dict[str, t.Any]): A dictionary of additional parameters

        Returns:
            hc_types.HealthCheckResult: The result of the health check.
        """
        # Parse parameters
        iterations = int(check_params.get("iterations", 5))
        time_threshold = int(check_params.get("time_threshold", 35))
        wait_time_seconds = int(check_params.get("wait_time_seconds", 60))
        expected_route_count_param = check_params.get("expected_route_count")
        expected_route_count = (
            int(expected_route_count_param)
            if expected_route_count_param is not None
            else None
        )
        observation_timeout_seconds = float(
            check_params.get("observation_timeout_seconds", 15)
        )
        observation_poll_interval_seconds = float(
            check_params.get("observation_poll_interval_seconds", 1)
        )
        network_group_regex = check_params.get("network_group_regex")
        log_file = check_params.get("log_file", "/var/facebook/logs/wedge_agent.log")
        archive_dir = check_params.get(
            "archive_dir", "/var/facebook/logs/fboss/archive"
        )
        start_time_file = check_params.get(
            "start_time_file", self.DEFAULT_START_TIME_FILE
        )

        # Get device name from the TestDevice object
        device_name = obj.name if obj else "unknown"
        context_prefix = f"[{device_name}]"

        # Validate required params
        if not self.ixia:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.ERROR,
                message="IXIA client not available. Cannot perform toggle operation.",
            )

        if not network_group_regex:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.ERROR,
                message="Missing required parameter: network_group_regex",
            )

        self.logger.info(
            f"Starting route convergence check: {iterations} iterations of DELETE→ADD, "
            f"network_group_regex='{network_group_regex}', threshold={time_threshold}s"
        )

        # Track results for all iterations
        all_results: t.List[t.Dict[str, t.Any]] = []
        failed_operations: t.List[str] = []

        for iteration in range(1, iterations + 1):
            self.logger.info(f"=== Iteration {iteration}/{iterations} ===")

            # Run DELETE then ADD for this iteration
            # This ensures routes end in ADD (enabled) state after all iterations
            for operation_type in ["DELETE", "ADD"]:
                result = await self._run_single_operation(
                    operation_type=operation_type,
                    network_group_regex=network_group_regex,
                    time_threshold=time_threshold,
                    wait_time_seconds=wait_time_seconds,
                    log_file=log_file,
                    archive_dir=archive_dir,
                    start_time_file=start_time_file,
                    iteration=iteration,
                    expected_route_count=expected_route_count,
                    observation_timeout_seconds=observation_timeout_seconds,
                    observation_poll_interval_seconds=observation_poll_interval_seconds,
                )

                all_results.append(
                    {
                        "iteration": iteration,
                        "operation": operation_type,
                        "passed": result["passed"],
                        "time": result.get("time", 0),
                        "routes": result.get("routes", 0),
                        "message": result.get("message", ""),
                    }
                )

                if not result["passed"]:
                    failure = (
                        f"Iter{iteration}-{operation_type}: "
                        f"{result.get('message', 'Failed')}"
                    )
                    failed_operations.append(failure)
                    self.logger.error(
                        f"[Iter {iteration}] {operation_type} FAILED: "
                        f"{result.get('message', 'Failed')}"
                    )

        # Build summary
        total_ops = len(all_results)
        passed_ops = sum(1 for r in all_results if r["passed"])
        failed_ops = total_ops - passed_ops

        if failed_ops > 0:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=(
                    f"{context_prefix} Route convergence FAILED: "
                    f"{passed_ops}/{total_ops} operations passed. "
                    f"Failures: {'; '.join(failed_operations[:3])}"
                    + (
                        f" (+{len(failed_operations) - 3} more)"
                        if len(failed_operations) > 3
                        else ""
                    )
                ),
            )

        # Calculate summary stats
        add_times = [r["time"] for r in all_results if r["operation"] == "ADD"]
        delete_times = [r["time"] for r in all_results if r["operation"] == "DELETE"]
        avg_add = sum(add_times) / len(add_times) if add_times else 0
        avg_delete = sum(delete_times) / len(delete_times) if delete_times else 0

        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
            message=(
                f"{context_prefix} Route convergence PASSED: "
                f"{iterations} iterations of DELETE→ADD completed. "
                f"Avg ADD: {avg_add:.3f}s, Avg DELETE: {avg_delete:.3f}s "
                f"(threshold: {time_threshold}s)"
            ),
        )

    async def _run_single_operation(
        self,
        operation_type: str,
        network_group_regex: str,
        time_threshold: int,
        wait_time_seconds: int,
        log_file: str,
        start_time_file: str,
        iteration: int,
        archive_dir: str = "/var/facebook/logs/fboss/archive",
        expected_route_count: int | None = None,
        observation_timeout_seconds: float = 0,
        observation_poll_interval_seconds: float = 1,
    ) -> t.Dict[str, t.Any]:
        """
        Run a single ADD or DELETE operation.

        Returns:
            Dict with keys: passed (bool), time (float), routes (int), message (str)
        """
        # Step 1: Capture start time BEFORE toggle
        self.logger.info(
            f"[Iter {iteration}] Capturing start time before {operation_type}"
        )
        start_time_str, start_stamp = await self._capture_start_time(start_time_file)

        if not start_time_str:
            return {
                "passed": False,
                "message": "Failed to capture start time",
            }

        # Step 2: Toggle BGP prefixes via IXIA
        enable = operation_type == "ADD"
        action_verb = "Enabling" if enable else "Disabling"

        self.logger.info(
            f"[Iter {iteration}] {action_verb} network groups matching '{network_group_regex}'"
        )

        if not self.ixia:
            return {
                "passed": False,
                "message": "IXIA client not available. Cannot perform toggle operation.",
            }
        ixia = self.ixia

        try:
            ixia.activate_deactivate_bgp_prefix(
                active=enable,
                network_group_name_regex=network_group_regex,
            )
            self.logger.info(
                f"[Iter {iteration}] Successfully toggled network groups (active={enable})"
            )
        except Exception as e:
            return {
                "passed": False,
                "message": f"Toggle failed: {e}",
            }

        # Step 3: Wait for routes to converge
        self.logger.info(
            f"[Iter {iteration}] Waiting {wait_time_seconds}s for routes to converge ({operation_type})"
        )
        await asyncio.sleep(wait_time_seconds)

        # Step 4: Analyze logs (live log + any rotated archives covering the window)
        self.logger.info(
            f"[Iter {iteration}] Analyzing logs for {operation_type} operation"
        )

        try:
            metrics = await self._observe_route_convergence_metrics(
                start_stamp=start_stamp,
                log_file=log_file,
                archive_dir=archive_dir,
                operation_type=operation_type,
                start_time_str=start_time_str,
                time_threshold=time_threshold,
                expected_route_count=expected_route_count,
                observation_timeout_seconds=observation_timeout_seconds,
                observation_poll_interval_seconds=observation_poll_interval_seconds,
            )
        except Exception as ex:
            return {
                "passed": False,
                "message": f"Log analysis failed: {ex}",
            }

        if metrics is None:
            return {
                "passed": False,
                "message": f"No {operation_type} operations found in logs",
            }

        # Check threshold
        route_count = (
            metrics.total_routes_added
            if operation_type == "ADD"
            else metrics.total_routes_deleted
        )

        if expected_route_count is not None and route_count < expected_route_count:
            return {
                "passed": False,
                "time": metrics.total_state_update_time_sec,
                "routes": route_count,
                "message": (
                    f"Incomplete {operation_type}: observed "
                    f"{route_count}/{expected_route_count} routes"
                ),
            }

        metrics.total_state_update_time_sec = self._elapsed_seconds(
            start_time_str, metrics.last_batch_time
        )

        if metrics.total_state_update_time_sec > time_threshold:
            return {
                "passed": False,
                "time": metrics.total_state_update_time_sec,
                "routes": route_count,
                "message": f"{operation_type} took {metrics.total_state_update_time_sec:.3f}s > {time_threshold}s",
            }

        self.logger.info(
            f"[Iter {iteration}] {operation_type} PASSED: {metrics.total_state_update_time_sec:.3f}s, "
            f"routes={route_count}, batches={metrics.num_batches}"
        )

        return {
            "passed": True,
            "time": metrics.total_state_update_time_sec,
            "routes": route_count,
            "message": f"{operation_type} completed in {metrics.total_state_update_time_sec:.3f}s",
        }

    async def _observe_route_convergence_metrics(
        self,
        start_stamp: str | None,
        log_file: str,
        archive_dir: str,
        operation_type: str,
        start_time_str: str,
        time_threshold: int,
        expected_route_count: int | None,
        observation_timeout_seconds: float,
        observation_poll_interval_seconds: float,
    ) -> RouteConvergenceMetrics | None:
        deadline = time.monotonic() + observation_timeout_seconds
        latest_metrics = None

        while True:
            log_files = await self._find_log_files(start_stamp, log_file, archive_dir)
            latest_metrics = await self._get_route_convergence_metrics(
                log_files=log_files,
                operation_type=operation_type,
                start_time_str=start_time_str,
                time_threshold=time_threshold,
                start_stamp=start_stamp,
            )
            route_count = self._route_count(latest_metrics, operation_type)
            if latest_metrics is not None and (
                expected_route_count is None or route_count >= expected_route_count
            ):
                return latest_metrics

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return latest_metrics

            await asyncio.sleep(min(observation_poll_interval_seconds, remaining))

    @staticmethod
    def _route_count(
        metrics: RouteConvergenceMetrics | None, operation_type: str
    ) -> int:
        if metrics is None:
            return 0
        return (
            metrics.total_routes_added
            if operation_type == "ADD"
            else metrics.total_routes_deleted
        )

    async def _capture_start_time(
        self, start_time_file: str
    ) -> t.Tuple[t.Optional[str], t.Optional[str]]:
        """
        Capture current time and save to file on the device.

        Args:
            start_time_file: Path to save the timestamp

        Returns:
            Tuple of (HH:MM:SS string used to filter log lines, YYYYMMDDHHMM
            string used to select rotated archive files). Both None on failure.
        """
        try:
            # Capture, from a single `date` call, both a filename-comparable
            # stamp (YYYYMMDDHHMM, minute precision — matches the archive
            # filename resolution) and the HH:MM:SS the glog lines carry.
            cmd = f"date '+%Y%m%d%H%M %H:%M:%S.%6N' | tee {start_time_file}"
            # pyrefly: ignore [missing-attribute]
            result = await self.driver.async_run_cmd_on_shell(cmd)

            if result and result.strip():
                # e.g. "202607170952 09:52:15.879279"
                start_stamp, _, time_part = result.strip().partition(" ")
                hhmmss = self._parse_start_time_to_hhmmss(time_part)
                # Only surface the stamp when the time parsed too; a malformed
                # result (no space) leaves time_part empty and start_stamp a
                # garbage value, so treat that as a total failure.
                if hhmmss:
                    return hhmmss, (start_stamp or None)
        except Exception as e:
            self.logger.error(f"Failed to capture start time: {e}")

        return None, None

    def _parse_start_time_to_hhmmss(self, start_time: t.Any) -> t.Optional[str]:
        """
        Parse start_time from various formats to HH:MM:SS string.

        Args:
            start_time: Start time in various formats (epoch seconds, ISO format, HH:MM:SS)

        Returns:
            HH:MM:SS string or None if parsing fails
        """
        if start_time is None:
            return None

        # If already in HH:MM:SS format
        if isinstance(start_time, str) and ":" in start_time:
            # Already in time format, extract HH:MM:SS part
            parts = start_time.split(":")
            if len(parts) >= 3:
                # Preserve fractional seconds so pre-toggle events in the same
                # wall-clock second cannot enter the measurement window.
                hour = parts[0]
                minute = parts[1]
                second = parts[2]
                return f"{hour}:{minute}:{second}"
            elif len(parts) == 2:
                return f"{parts[0]}:{parts[1]}:00"
            return start_time

        # If it's a number (epoch seconds)
        if isinstance(start_time, (int, float)):
            dt = datetime.fromtimestamp(start_time)
            return dt.strftime("%H:%M:%S")

        # If it's a string that looks like epoch seconds
        if isinstance(start_time, str):
            try:
                dt = datetime.fromtimestamp(float(start_time))
                return dt.strftime("%H:%M:%S")
            except ValueError:
                pass

            # Try ISO format
            try:
                dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                return dt.strftime("%H:%M:%S")
            except ValueError:
                pass

        return None

    async def _get_route_convergence_metrics(
        self,
        log_files: t.List[str],
        operation_type: str,
        start_time_str: t.Optional[str],
        time_threshold: int,
        start_stamp: t.Optional[str] = None,
    ) -> t.Optional[RouteConvergenceMetrics]:
        """
        Parse the given log files and calculate route convergence metrics.

        Each file (a rotated `.gz` archive or the plain live log) is scanned
        with its own AWK invocation via `zcat -f`, parsed independently, and
        merged into a single RouteConvergenceMetrics. Normally only one file
        contains the operation (the rest return None); merging covers the rare
        case where the op straddles a rotation boundary.

        Args:
            log_files: Ordered files to scan (archives first, live log last),
                as produced by `_find_log_files`.
            operation_type: "ADD" or "DELETE"
            start_time_str: Optional HH:MM:SS string to filter logs from
            time_threshold: Time threshold for display in output

        Returns:
            RouteConvergenceMetrics object, or None if no operations found in
            any file.
        """
        aggregated: t.Optional[RouteConvergenceMetrics] = None

        for log_file in log_files:
            # The driver selects a file stream for Classic/NSPAWN and a
            # service journal for native NetOS. FBOSS messages retain their
            # glog timestamps, so the AWK parser remains common.
            # pyrefly: ignore [missing-attribute]
            log_source_command = await self.driver.async_get_log_source_command(
                log_file, start_time=start_stamp
            )
            # Build the AWK command based on operation type
            if operation_type == "ADD":
                cmd = self._build_add_awk_command(
                    log_file,
                    start_time_str,
                    time_threshold,
                    log_source_command=log_source_command,
                )
            else:
                cmd = self._build_delete_awk_command(
                    log_file,
                    start_time_str,
                    time_threshold,
                    log_source_command=log_source_command,
                )

            # pyrefly: ignore [missing-attribute]
            result = await self.driver.async_run_cmd_on_shell(cmd)

            if not result or not result.strip():
                continue

            metrics = self._parse_awk_output(result, operation_type)
            if metrics is None:
                continue

            aggregated = (
                metrics
                if aggregated is None
                else self._merge_metrics(aggregated, metrics)
            )

        return aggregated

    def _build_add_awk_command(
        self,
        log_file: str,
        start_time_str: t.Optional[str],
        time_threshold: int,
        log_source_command: t.Optional[str] = None,
    ) -> str:
        """
        Build AWK command for ADD operation analysis.

        Parses RouteUpdateWrapper.cpp for route counts and SwSwitch.cpp for timing.
        Only counts batches where routes_added > 0.
        """
        start_time = start_time_str or "00:00:00"

        source_command = log_source_command or f"zcat -f {shlex.quote(log_file)}"
        return f"""{source_command} | awk -v start="{start_time}" -v threshold="{time_threshold}" '
function time_to_sec(t) {{
    split(t, a, ":");
    split(a[3], b, ".");
    return a[1]*3600 + a[2]*60 + b[1] + (length(b[2]) > 0 ? b[2]/1000000 : 0)
}}
BEGIN {{
    total_added=0; total_deleted=0; batches=0;
    first_ts=""; last_ts=""; start_sec=time_to_sec(start)
}}
/RouteUpdateWrapper.cpp.*Routes added:/ {{
    if (match($0, /[0-9][0-9]:[0-9][0-9]:[0-9][0-9]\\.[0-9]+/)) {{
        ts = substr($0, RSTART, RLENGTH);
        if (time_to_sec(ts) >= start_sec) {{
            if (match($0, /Routes added: [0-9]+/)) {{
                split(substr($0, RSTART, RLENGTH), arr, " ");
                added = arr[3];
                if (added > 0) {{
                    batches++;
                    if (first_ts == "") first_ts = ts;
                    last_ts = ts;
                    total_added += added
                }}
            }}
            if (match($0, /Routes deleted: [0-9]+/)) {{
                split(substr($0, RSTART, RLENGTH), arr, " ");
                total_deleted += arr[3]
            }}
        }}
    }}
}}
END {{
    if (batches > 0) {{
        wall_clock_time = time_to_sec(last_ts) - time_to_sec(first_ts);
        printf "METRICS %d %d %d %.6f %s %s\\n", total_added, total_deleted, batches, wall_clock_time, first_ts, last_ts
    }} else {{
        print "NONE"
    }}
}}'"""

    def _build_delete_awk_command(
        self,
        log_file: str,
        start_time_str: t.Optional[str],
        time_threshold: int,
        log_source_command: t.Optional[str] = None,
    ) -> str:
        """
        Build AWK command for DELETE operation analysis.

        Parses RouteUpdateWrapper.cpp for route counts and SwSwitch.cpp for timing.
        Only counts batches where routes_deleted > 0.
        """
        start_time = start_time_str or "00:00:00"

        source_command = log_source_command or f"zcat -f {shlex.quote(log_file)}"
        return f"""{source_command} | awk -v start="{start_time}" -v threshold="{time_threshold}" '
function time_to_sec(t) {{
    split(t, a, ":");
    split(a[3], b, ".");
    return a[1]*3600 + a[2]*60 + b[1] + (length(b[2]) > 0 ? b[2]/1000000 : 0)
}}
BEGIN {{
    total_added=0; total_deleted=0; batches=0;
    first_ts=""; last_ts=""; start_sec=time_to_sec(start)
}}
/RouteUpdateWrapper.cpp.*Routes added:/ {{
    if (match($0, /[0-9][0-9]:[0-9][0-9]:[0-9][0-9]\\.[0-9]+/)) {{
        ts = substr($0, RSTART, RLENGTH);
        if (time_to_sec(ts) >= start_sec) {{
            if (match($0, /Routes deleted: [0-9]+/)) {{
                split(substr($0, RSTART, RLENGTH), arr, " ");
                deleted = arr[3];
                if (deleted > 0) {{
                    batches++;
                    if (first_ts == "") first_ts = ts;
                    last_ts = ts;
                    total_deleted += deleted
                }}
            }}
            if (match($0, /Routes added: [0-9]+/)) {{
                split(substr($0, RSTART, RLENGTH), arr, " ");
                total_added += arr[3]
            }}
        }}
    }}
}}
END {{
    if (batches > 0) {{
        wall_clock_time = time_to_sec(last_ts) - time_to_sec(first_ts);
        printf "METRICS %d %d %d %.6f %s %s\\n", total_added, total_deleted, batches, wall_clock_time, first_ts, last_ts
    }} else {{
        print "NONE"
    }}
}}'"""

    def _parse_awk_output(
        self, output: str, _operation_type: str
    ) -> t.Optional[RouteConvergenceMetrics]:
        """
        Parse the AWK command output into RouteConvergenceMetrics.

        Expected format:
            METRICS <added> <deleted> <batches> <time_sec> <first_ts> <last_ts>
            or
            NONE

        Args:
            output: Raw output from AWK command
            _operation_type: "ADD" or "DELETE" (used for logging context, unused here)

        Returns:
            RouteConvergenceMetrics object or None if no operations found
        """
        output = output.strip()

        if output == "NONE" or not output.startswith("METRICS"):
            return None

        try:
            parts = output.split()
            if len(parts) >= 7:
                return RouteConvergenceMetrics(
                    total_routes_added=int(parts[1]),
                    total_routes_deleted=int(parts[2]),
                    num_batches=int(parts[3]),
                    total_state_update_time_sec=float(parts[4]),
                    first_batch_time=parts[5],
                    last_batch_time=parts[6],
                )
        except (ValueError, IndexError) as e:
            self.logger.warning(f"Failed to parse AWK output: {output}, error: {e}")

        return None

    async def _find_log_files(
        self,
        start_stamp: t.Optional[str],
        log_file: str,
        archive_dir: str = "/var/facebook/logs/fboss/archive",
    ) -> t.List[str]:
        """
        Return the log files to scan for one operation.

        A fast DELETE emits only a handful of lines; if the live log rotates
        right after it, those lines move to a compressed archive the live-log
        scan can't see, and the op is reported missing. This returns any
        rotated archives whose window covers `start_stamp`, in chronological
        order, followed by the current (live) log.

        Rotated archives are named `wedge_agent.log-YYYYMMDDHHMM.gz`, where the
        stamp is the time of the LAST line in that archive. An archive is
        relevant when that stamp is >= our start (its tail reaches into the
        operation window). The live log is always included, so the common
        no-rotation case still works and an op that straddles a rotation is
        fully covered (rotation moves lines, so there is no double count).

        Args:
            start_stamp: YYYYMMDDHHMM start stamp, or None.
            log_file: Path to the current (live) log file.
            archive_dir: Directory holding rotated `.gz` archives.

        Returns:
            Ordered list of file paths (archives first, live log last).
        """
        archives: t.List[t.Tuple[str, str]] = []
        if start_stamp:
            try:
                # pyrefly: ignore [missing-attribute]
                out = await self.driver.async_run_cmd_on_shell(
                    f"ls -1 {shlex.quote(archive_dir)}/wedge_agent.log-*.gz 2>/dev/null"
                )
            except Exception as e:
                self.logger.warning(f"Failed to list archive logs: {e}")
                out = ""

            for line in (out or "").splitlines():
                path = line.strip()
                # Match only wedge_agent.log-<12 digits>.gz; this excludes
                # wedge_agent_snapshots.log* by construction.
                match = re.search(r"wedge_agent\.log-(\d{12})\.gz$", path)
                if match and match.group(1) >= start_stamp:
                    archives.append((match.group(1), path))

        # Zero-padded YYYYMMDDHHMM sorts chronologically as a string.
        archives.sort()
        return [path for _, path in archives] + [log_file]

    @staticmethod
    def _hhmmss_to_sec(ts: str) -> float:
        """Convert an 'HH:MM:SS[.ffffff]' timestamp to seconds."""
        hour, minute, rest = ts.split(":")
        return int(hour) * 3600 + int(minute) * 60 + float(rest)

    @classmethod
    def _elapsed_seconds(cls, start: str, end: str) -> float:
        elapsed = cls._hhmmss_to_sec(end) - cls._hhmmss_to_sec(start)
        return elapsed + 86400 if elapsed < 0 else elapsed

    def _merge_metrics(
        self,
        base: RouteConvergenceMetrics,
        extra: RouteConvergenceMetrics,
    ) -> RouteConvergenceMetrics:
        """
        Merge metrics parsed from a second log file into an accumulator.

        Counts and batches are summed; the batch-time window is widened to the
        earliest first / latest last across files, and the wall-clock is
        recomputed from that widened window (NOT summed, which would drop the
        inter-file gap). In practice one op lives in one file, so this only
        matters for an op that straddles a rotation boundary.

        `base` accumulates the chronologically earlier files and `extra` is the
        next (later) file — `_get_route_convergence_metrics` feeds them in
        `_find_log_files` order. So the window runs from `base`'s first batch to
        `extra`'s last batch by file order, NOT by lexicographic min/max on the
        `HH:MM:SS` strings: the latter picks the wrong endpoints when the window
        straddles midnight (e.g. base ends 23:59:50, extra starts 00:00:05).
        """
        first = base.first_batch_time or extra.first_batch_time
        last = extra.last_batch_time or base.last_batch_time
        if first and last:
            wall = self._hhmmss_to_sec(last) - self._hhmmss_to_sec(first)
            if wall < 0:
                # Window straddled midnight (last clock time < first); add a day
                # so the duration stays a small positive value instead of ~ -86400s.
                wall += 86400
        else:
            wall = base.total_state_update_time_sec + extra.total_state_update_time_sec
        return RouteConvergenceMetrics(
            total_routes_added=base.total_routes_added + extra.total_routes_added,
            total_routes_deleted=base.total_routes_deleted + extra.total_routes_deleted,
            num_batches=base.num_batches + extra.num_batches,
            total_state_update_time_sec=wall,
            first_batch_time=first,
            last_batch_time=last,
        )
