# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
import re
import time
import typing as t

from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.utils import (  # oss-rewrite (force ShipIt re-export to taac.* root)
    arista_utils,
    log_parsing_utils,
)
from taac.health_check.health_check import types as hc_types


_RESOURCE_ACCOUNTANT_REJECTION_RE = re.compile(
    r"(?:"
    r"Total (?:NDP|ARP|l2|unified neighbor) entries in new switchState: "
    r"\d+ exceeds the limit: \d+"
    r"|Invalid route update - exceeding (?:DLB|route or ECMP) resource limits"
    r"|State updated rejected by resource accountant"
    r")",
    re.IGNORECASE,
)
_AGENT_LOG_TIMESTAMP_RE = re.compile(r"\b[A-Z]\d{4} \d{2}:\d{2}:\d{2}")
_RESOURCE_ACCOUNTANT_GREP_PATTERN = (
    "Total (NDP|ARP|l2|unified neighbor) entries in new switchState: "
    "[0-9]+ exceeds the limit: [0-9]+|"
    "Invalid route update - exceeding (DLB|route or ECMP) resource limits|"
    "State updated rejected by resource accountant"
)


def find_resource_accountant_rejections(
    log_content: str,
    start_time: int | None = None,
    end_time: int | None = None,
) -> list[str]:
    """Return canonical ResourceAccountant rejection lines in the time window."""
    current_year = time.localtime().tm_year
    matching_lines = []
    for line in log_content.splitlines():
        if not _RESOURCE_ACCOUNTANT_REJECTION_RE.search(line):
            continue
        if start_time is not None:
            # A windowed assertion must never accept an undated continuation or
            # a historical line merely because it contains the class name.
            # NetOS journald output prepends a syslog date/host/process prefix
            # before the embedded FBOSS timestamp, so parse from that marker.
            timestamp_match = _AGENT_LOG_TIMESTAMP_RE.search(line)
            if timestamp_match is None:
                continue
            if not log_parsing_utils.is_agent_log_line_in_time_range(
                line[timestamp_match.start() :],
                start_time,
                end_time if end_time is not None else int(time.time()),
                current_year,
            ):
                continue
        matching_lines.append(line)
    return matching_lines


class LogParsingHealthCheck(AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]):
    CHECK_NAME = hc_types.CheckName.LOG_PARSING_CHECK
    OPERATING_SYSTEMS = [
        "FBOSS",
        "EOS",
    ]
    _REGEX_META_CHARACTERS = frozenset(r"\.^$*+?{}[]|()")

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        start_time = check_params.get("start_time")
        end_time = int(check_params.get("end_time") or time.time())
        log_file_path = check_params["log_file_path"]
        if check_params.get("resource_accountant_activation"):
            # The driver reads Classic/NSPAWN files and native NetOS journald,
            # while bounding remote output before applying exact timestamps.
            # pyrefly: ignore [missing-attribute]
            log_content = await self.driver.async_read_log_file(
                log_file_path,
                start_time=int(start_time) if start_time is not None else None,
                end_time=end_time,
                grep_pattern=_RESOURCE_ACCOUNTANT_GREP_PATTERN,
                tail_lines=200,
            )
            matching_lines = find_resource_accountant_rejections(
                log_content,
                int(start_time) if start_time is not None else None,
                end_time,
            )
            if not matching_lines:
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.FAIL,
                    message=(
                        "No ResourceAccountant rejection was logged in the "
                        "requested validation window"
                    ),
                )
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.PASS,
                message=(
                    f"Found {len(matching_lines)} ResourceAccountant rejection "
                    f"line(s): {matching_lines[:3]}"
                ),
            )
        include_regex = check_params.get("include_regex")
        exclude_regex = check_params.get("exclude_regex")
        assert bool(include_regex) ^ bool(exclude_regex), (
            "Please provide either include_regex or exclude_regex, but not both"
        )
        read_kwargs = {
            "start_time": int(start_time) if start_time is not None else None,
            "end_time": end_time if start_time is not None else None,
        }
        if check_params.get("tail_lines") is not None:
            read_kwargs["tail_lines"] = int(check_params["tail_lines"])
        # pyrefly: ignore [missing-attribute]
        log_content = await self.driver.async_read_log_file(
            log_file_path,
            **read_kwargs,
        )
        matching_lines = [
            line
            for line in log_content.splitlines()
            # pyrefly: ignore [no-matching-overload]
            if re.search(include_regex or exclude_regex, line)
        ]
        if include_regex:
            if not matching_lines:
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.FAIL,
                    message=f"No lines matched the regex {include_regex}",
                )
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.PASS,
                message=f"Found {len(matching_lines)} line(s) matching include regex {include_regex}",
            )
        if matching_lines:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=f"Found {len(matching_lines)} lines matching criteria: {matching_lines}",
            )
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
            message=f"No lines matched exclude regex {exclude_regex}",
        )

    async def _run_arista(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        """Arista EOS implementation for log parsing health check."""
        try:
            params = self._validate_arista_params(check_params)
            if params["agent_name"]:
                return await self._handle_arista_agent_logs(obj, params)
            else:
                return await self._handle_arista_system_logs(params)
        except Exception as e:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.ERROR,
                message=f"Failed to check EOS logs: {str(e)}",
            )

    def _validate_arista_params(
        self, check_params: t.Dict[str, t.Any]
    ) -> t.Dict[str, t.Any]:
        """Extract and validate parameters for Arista log checking."""
        include_regex = check_params.get("include_regex")
        exclude_regex = check_params.get("exclude_regex")
        raw_start_time = check_params.get("start_time")
        raw_end_time = check_params.get("end_time")
        start_time = int(raw_start_time) if raw_start_time is not None else None
        end_time = int(raw_end_time) if raw_end_time is not None else int(time.time())

        if include_regex or exclude_regex:
            assert bool(include_regex) ^ bool(exclude_regex), (
                "Please provide either include_regex or exclude_regex, but not both"
            )
        if start_time is not None and end_time < start_time:
            raise ValueError(
                f"end_time ({end_time}) must not be earlier than start_time "
                f"({start_time})"
            )

        return {
            "start_time": start_time,
            "end_time": end_time,
            "include_regex": include_regex,
            "exclude_regex": exclude_regex,
            "agent_name": check_params.get("agent_name"),
        }

    async def _handle_arista_agent_logs(
        self, obj: TestDevice, params: t.Dict[str, t.Any]
    ) -> hc_types.HealthCheckResult:
        """Handle agent log checking with time filtering and regex."""
        agent_name = params["agent_name"]

        # Get daemon PID and log file
        pid = await arista_utils.get_daemon_pid(self.driver, agent_name)
        if not pid:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=f"No running {agent_name} daemon found",
            )

        log_file = arista_utils.get_agent_log_file(agent_name, pid)
        self.logger.info(f"[LOG_PARSING] Getting log content from: {log_file}")
        live_log_found = True
        try:
            # pyrefly: ignore [missing-attribute]
            live_content = await self.driver.async_read_file(log_file)
        except FileNotFoundError:
            live_log_found = False
            live_content = ""
            self.logger.info(
                f"[LOG_PARSING] Live agent log is no longer present: {log_file}"
            )

        archived_content = await arista_utils.get_archived_agent_logs(
            self.driver,
            agent_name,
            pid,
            start_time=params["start_time"],
            end_time=params["end_time"],
            matching_literal=(
                self._get_matching_literal(params) if live_log_found else None
            ),
        )
        if not live_log_found and not archived_content:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.ERROR,
                message=(f"No live or archived {agent_name} logs found for PID {pid}"),
            )

        log_content = "\n".join(
            content for content in (live_content, archived_content) if content
        )
        log_content = self._filter_log_content_with_time_filter(log_content, params)

        return self._check_log_content(log_content, params, agent_name)

    def _get_matching_literal(self, params: t.Dict[str, t.Any]) -> t.Optional[str]:
        pattern = params["include_regex"] or params["exclude_regex"]
        if not isinstance(pattern, str) or any(
            character in self._REGEX_META_CHARACTERS for character in pattern
        ):
            return None
        return pattern

    async def _handle_arista_system_logs(
        self, params: t.Dict[str, t.Any]
    ) -> hc_types.HealthCheckResult:
        """Handle system log checking (emergency/critical/error)."""
        if params["include_regex"] or params["exclude_regex"]:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.ERROR,
                message="System logs do not support regex filtering",
            )

        system_logs = await arista_utils.check_eos_system_logs(
            self.driver, params.get("start_time"), params.get("end_time")
        )
        classification = arista_utils.classify_eos_system_log_entries(system_logs)
        recovery_context = list(classification.excluded)
        system_log_issues = list(classification.issues)

        if recovery_context:
            self.logger.warning(
                "Observed excluded EOS recovery logs: %s",
                recovery_context,
            )

        if system_log_issues:
            recovery_suffix = (
                f"; recovery context: {recovery_context}" if recovery_context else ""
            )
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=(
                    f"Found {len(system_log_issues)} system log issues: "
                    f"{system_log_issues}{recovery_suffix}"
                ),
            )

        recovery_suffix = (
            f"; observed recovery context: {recovery_context}"
            if recovery_context
            else ""
        )
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
            message=(
                "No emergency/critical/error issues found in EOS system logs"
                f"{recovery_suffix}"
            ),
        )

    def _filter_log_content_with_time_filter(
        self, content: str, params: t.Dict[str, t.Any]
    ) -> str:
        """Apply an optional time window to combined live and archived logs."""
        start_time = params["start_time"]
        end_time = params["end_time"]

        self.logger.info(
            f"[LOG_PARSING] Time filter - start: {start_time}, end: {end_time}"
        )

        if not content:
            self.logger.info("[LOG_PARSING] Combined log content is empty")
            return ""

        # Apply time filtering if specified
        if start_time is not None:
            self.logger.info("[LOG_PARSING] Applying BGP-specific time filtering")
            filtered_content = log_parsing_utils.filter_agent_logs_by_time(
                content, start_time, end_time
            )
            self.logger.info(
                f"[LOG_PARSING] Filtered from {len(content.splitlines())} to {len(filtered_content.splitlines())} lines"
            )
            return filtered_content
        else:
            self.logger.info("[LOG_PARSING] No time filtering - returning full content")
            return content

    def _check_log_content(
        self, log_content: str, params: t.Dict[str, t.Any], agent_name: str
    ) -> hc_types.HealthCheckResult:
        """Check log content with regex or error patterns using utility functions."""
        include_regex = params["include_regex"]
        exclude_regex = params["exclude_regex"]

        if include_regex or exclude_regex:
            # Use utility function for regex checking
            success, matching_lines = log_parsing_utils.check_regex_patterns(
                log_content, include_regex, exclude_regex
            )

            if not success:
                if include_regex:
                    return hc_types.HealthCheckResult(
                        status=hc_types.HealthCheckStatus.FAIL,
                        message=f"No lines matched include regex '{include_regex}'",
                    )
                else:
                    return hc_types.HealthCheckResult(
                        status=hc_types.HealthCheckStatus.FAIL,
                        message=f"Found {len(matching_lines)} lines matching exclude regex: {matching_lines[:5]}",
                    )

            # Success case for regex
            regex = include_regex or exclude_regex
            action = "matched include" if include_regex else "excluded by"
            time_info = log_parsing_utils.format_time_range(
                params.get("start_time"), params.get("end_time")
            )
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.PASS,
                message=f"All {agent_name} logs{time_info} {action} regex '{regex}'",
            )
        else:
            # Use utility function for error pattern checking
            error_lines = log_parsing_utils.check_error_patterns(log_content)

            if error_lines:
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.FAIL,
                    message=f"Found {len(error_lines)} error patterns: {error_lines[:5]}",  # Limit output
                )

            time_info = log_parsing_utils.format_time_range(
                params.get("start_time"), params.get("end_time")
            )
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.PASS,
                message=f"No error patterns found in {agent_name} logs{time_info}",
            )
