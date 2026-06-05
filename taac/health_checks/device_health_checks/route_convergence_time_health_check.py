# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe
import asyncio
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
        network_group_regex = check_params.get("network_group_regex")
        log_file = check_params.get("log_file", "/var/facebook/logs/wedge_agent.log")
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
                    start_time_file=start_time_file,
                    iteration=iteration,
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
                    failed_operations.append(
                        f"Iter{iteration}-{operation_type}: {result.get('message', 'Failed')}"
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
        start_time_str = await self._capture_start_time(start_time_file)

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

        # Step 4: Analyze logs
        self.logger.info(
            f"[Iter {iteration}] Analyzing logs for {operation_type} operation"
        )

        try:
            metrics = await self._get_route_convergence_metrics(
                log_file=log_file,
                operation_type=operation_type,
                start_time_str=start_time_str,
                time_threshold=time_threshold,
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

    async def _capture_start_time(self, start_time_file: str) -> t.Optional[str]:
        """
        Capture current time and save to file on the device.

        Args:
            start_time_file: Path to save the timestamp

        Returns:
            HH:MM:SS formatted time string, or None if failed
        """
        try:
            # Run date command on device and save to file
            cmd = f"date '+%H:%M:%S.%6N' | tee {start_time_file}"
            result = await self.driver.async_run_cmd_on_shell(cmd)

            if result and result.strip():
                # Parse to HH:MM:SS format
                return self._parse_start_time_to_hhmmss(result.strip())
        except Exception as e:
            self.logger.error(f"Failed to capture start time: {e}")

        return None

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
                # Handle HH:MM:SS.microseconds format
                hour = parts[0]
                minute = parts[1]
                second = parts[2].split(".")[0]
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
        log_file: str,
        operation_type: str,
        start_time_str: t.Optional[str],
        time_threshold: int,
    ) -> t.Optional[RouteConvergenceMetrics]:
        """
        Parse the log file and calculate route convergence metrics.

        This method uses AWK to parse wedge_agent.log for:
        - RouteUpdateWrapper.cpp lines to count routes added/deleted
        - SwSwitch.cpp lines to sum up state update times

        Args:
            log_file: Path to the wedge_agent.log file
            operation_type: "ADD" or "DELETE"
            start_time_str: Optional HH:MM:SS string to filter logs from
            time_threshold: Time threshold for display in output

        Returns:
            RouteConvergenceMetrics object or None if no operations found
        """
        # Build the AWK command based on operation type
        if operation_type == "ADD":
            cmd = self._build_add_awk_command(log_file, start_time_str, time_threshold)
        else:
            cmd = self._build_delete_awk_command(
                log_file, start_time_str, time_threshold
            )

        result = await self.driver.async_run_cmd_on_shell(cmd)

        if not result or not result.strip():
            return None

        # Parse the AWK output
        return self._parse_awk_output(result, operation_type)

    def _build_add_awk_command(
        self,
        log_file: str,
        start_time_str: t.Optional[str],
        time_threshold: int,
    ) -> str:
        """
        Build AWK command for ADD operation analysis.

        Parses RouteUpdateWrapper.cpp for route counts and SwSwitch.cpp for timing.
        Only counts batches where routes_added > 0.
        """
        start_time = start_time_str or "00:00:00"

        return f"""awk -v start="{start_time}" -v threshold="{time_threshold}" '
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
}}' {log_file}"""

    def _build_delete_awk_command(
        self,
        log_file: str,
        start_time_str: t.Optional[str],
        time_threshold: int,
    ) -> str:
        """
        Build AWK command for DELETE operation analysis.

        Parses RouteUpdateWrapper.cpp for route counts and SwSwitch.cpp for timing.
        Only counts batches where routes_deleted > 0.
        """
        start_time = start_time_str or "00:00:00"

        return f"""awk -v start="{start_time}" -v threshold="{time_threshold}" '
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
}}' {log_file}"""

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
