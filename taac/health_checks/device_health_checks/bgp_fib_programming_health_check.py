# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
import re
import time
import typing as t
from datetime import datetime

from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from neteng.test_infra.dne.taac.utils import arista_utils, log_parsing_utils
from taac.health_check.health_check import types as hc_types


class BgpFibProgrammingCheck(AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]):
    CHECK_NAME = hc_types.CheckName.BGP_FIB_PROGRAMMING_CHECK
    OPERATING_SYSTEMS = [
        "EOS",
    ]
    CONVERGENCE_TIME_THRESHOLD_SECONDS = 550

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ):
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.FAIL,
            message="BGP_FIB_PROGRAMMING_CHECK is not supported for FBOSS devices",
        )

    async def _run_arista(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        start_time = check_params.get("start_time")
        end_time = int(check_params.get("end_time") or time.time())

        if not start_time:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.ERROR,
                message="start_time is required for BGP fib programming health check",
            )

        try:
            agent_name = "Bgp"
            pid = await arista_utils.get_daemon_pid(self.driver, agent_name)

        except Exception as e:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.ERROR,
                message=f"Failed to check Bgp logs: {str(e)}",
            )
        if not pid:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=f"No running {agent_name} daemon found",
            )

        log_file = arista_utils.get_agent_log_file(agent_name, pid)
        self.logger.info(
            f"[BGP_FIB_PROGRAMMING] Getting log file from device: {log_file}"
        )

        # pyrefly: ignore [missing-attribute]
        log_content_active = await self.driver.async_read_file(log_file)
        if not log_content_active:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.ERROR,
                message=f"Could not read log file {log_file}",
            )
        self.logger.info(f"[BGP_FIB_PROGRAMMING] Log file {log_file} read successfully")

        self.logger.info(
            "[BGP_FIB_PROGRAMMING] Getting any archived agent logs if present"
        )
        try:
            log_content_archived = await arista_utils.get_archived_agent_logs(
                self.driver, agent_name, pid
            )
        except Exception as e:
            self.logger.error(
                f"[BGP_FIB_PROGRAMMING] Error getting archived agent logs: {e}"
            )
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.ERROR,
                message=f"Could not read archived log file for {log_file}",
            )

        all_logs = log_content_archived + log_content_active

        filtered_content = log_parsing_utils.filter_agent_logs_by_time(
            all_logs, start_time, end_time
        )

        if not filtered_content:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message="No log entries found between start_time and end_time",
            )

        convergence_time = await self._parse_convergence_time(filtered_content)

        if convergence_time is None:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message="Couldn't determine the convergence time for FIB programming",
            )

        if convergence_time > self.CONVERGENCE_TIME_THRESHOLD_SECONDS:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=f"BGP convergence time {convergence_time:.3f} seconds exceeded threshold of {self.CONVERGENCE_TIME_THRESHOLD_SECONDS} seconds",
            )

        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
            message=f"BGP convergence time: {convergence_time:.3f} seconds",
        )

    async def _get_number_device_bgp_routes(self) -> int:
        total_routes = set()
        try:
            # pyrefly: ignore [missing-attribute]
            routes_dict = await self.driver.async_get_static_routes()
            for route, route_info in routes_dict.items():
                preference = route_info.get("preference")
                if preference == 200:
                    total_routes.add(route)
                    self.logger.debug(
                        f"[BGP_FIB_PROGRAMMING] Added route {route} with preference {preference}"
                    )
        except Exception as e:
            self.logger.error(f"[BGP_FIB_PROGRAMMING] Error getting BGP routes: {e}")

        self.logger.info(
            f"[BGP_FIB_PROGRAMMING] Total static routes with preference 200: {len(total_routes)}"
        )
        return len(total_routes)

    async def _parse_convergence_time(self, log_content: str) -> t.Optional[float]:
        pattern = r"Programmed HW with (\d+) updates"

        first_timestamp = None
        last_timestamp = None
        total_updates = 0

        current_year = time.localtime().tm_year

        for line in log_content.splitlines():
            match = re.search(pattern, line)
            if match:
                updates_count = int(match.group(1))
                total_updates += updates_count

                timestamp = self._extract_timestamp(line, current_year)
                if timestamp is not None:
                    if first_timestamp is None:
                        first_timestamp = timestamp
                        self.logger.info(
                            f"[BGP_FIB_PROGRAMMING] Found first pattern at timestamp: {first_timestamp}"
                        )
                    last_timestamp = timestamp
                    self.logger.info(
                        f"[BGP_FIB_PROGRAMMING] Found pattern at timestamp: {last_timestamp}, updates: {updates_count}"
                    )

        if first_timestamp is None or last_timestamp is None:
            self.logger.warning(
                f"[BGP_FIB_PROGRAMMING] Missing patterns - first: {first_timestamp}, last: {last_timestamp}"
            )
            return None

        device_bgp_routes_count = await self._get_number_device_bgp_routes()
        self.logger.info(
            f"[BGP_FIB_PROGRAMMING] Device BGP routes count: {device_bgp_routes_count}"
        )

        if device_bgp_routes_count != total_updates:
            self.logger.error(
                f"[BGP_FIB_PROGRAMMING] Mismatch between device routes ({device_bgp_routes_count}) and total updates ({total_updates})"
            )
            return None

        convergence_time = last_timestamp - first_timestamp
        self.logger.info(
            f"[BGP_FIB_PROGRAMMING] Total updates: {total_updates}, convergence time: {convergence_time:.3f} seconds"
        )
        return convergence_time

    def _extract_timestamp(self, line: str, current_year: int) -> t.Optional[float]:
        try:
            month_day = line[1:5]
            time_part = line[6:21]

            if len(month_day) != 4 or not month_day.isdigit():
                return None

            if (
                len(time_part) < 15
                or time_part[2] != ":"
                or time_part[5] != ":"
                or time_part[8] != "."
            ):
                return None

            month = int(month_day[:2])
            day = int(month_day[2:4])
            hour = int(time_part[:2])
            minute = int(time_part[3:5])
            second = int(time_part[6:8])
            microsecond = int(time_part[9:15])

            dt = datetime(current_year, month, day, hour, minute, second, microsecond)
            return dt.timestamp()

        except (ValueError, IndexError):
            return None
