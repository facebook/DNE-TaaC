# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-strict


import datetime
import typing as t

from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.utils.bgp_tcpdump_analyzer import BgpTcpdumpAnalyzer
from taac.health_check.health_check import types as hc_types


class BgpTcpdumpHealthCheck(AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]):
    """Health check for analyzing BGP tcpdump packet captures."""

    CHECK_NAME: hc_types.CheckName = hc_types.CheckName.BGP_TCPDUMP_CHECK
    OPERATING_SYSTEMS: t.List[str] = [
        "EOS",
    ]

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        """
        Execute BGP tcpdump analysis health check.

        Args:
            check_params: Dictionary containing:
                - capture_file_path: file path of capture file
                - expected_message_types: list of allowed message types
                - unexpected_message_types: list of unexpected message types
                - cleanup_capture_file: whether to clean up capture file after analysis (default: True)
                - expected_last_mod_time: expected modification time of capture file (default: None)
        Returns:
            Formatted table string
        """
        hostname = obj.name

        capture_file_path = check_params.get("capture_file_path")
        if not capture_file_path:
            capture_file_path = "/tmp/bgp_capture.txt"
            self.logger.info(
                f"No capture_file_path provided, using default: {capture_file_path}"
            )

        # Check if capture file exists
        try:
            check_cmd = f'bash ls -la "{capture_file_path}"'
            # pyrefly: ignore [missing-attribute]
            file_check = await self.driver.async_execute_show_or_configure_cmd_on_shell(
                check_cmd
            )
            if not file_check or "No such file" in file_check:
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.ERROR,
                    message=(
                        f"BGP tcpdump capture file not found on {hostname}: {capture_file_path}. "
                        f"Ensure BGP tcpdump capture task ran successfully before this health check."
                    ),
                )
        except Exception as e:
            self.logger.warning(f"Could not verify capture file existence: {e}")

        expected_message_types = check_params.get("expected_message_types", [])
        unexpected_message_types = check_params.get("unexpected_message_types", [])
        cleanup_capture_file = check_params.get("cleanup_capture_file", True)
        expected_last_mod_time = check_params.get("expected_last_mod_time", None)

        try:
            analyzer = BgpTcpdumpAnalyzer(self.logger)

            analysis_result = await analyzer.analyze_capture_file(
                capture_file_path=capture_file_path,
                driver=self.driver,
                expected_message_types=expected_message_types,
                unexpected_message_types=unexpected_message_types,
                expected_last_mod_time=expected_last_mod_time,
            )

            # Generate health check result based on analysis
            health_check_result = self._generate_health_check_result(
                hostname, capture_file_path, analysis_result
            )

            # Handle capture file based on health check status
            if cleanup_capture_file:
                if health_check_result.status == hc_types.HealthCheckStatus.PASS:
                    # Clean up the capture file only on success
                    await self._cleanup_capture_file(capture_file_path)
                else:
                    # Move the capture file to failure directory for debugging
                    await self._move_capture_file_on_failure(capture_file_path)

            return health_check_result

        except Exception as e:
            self.logger.error(
                f"Failed to analyze capture file {capture_file_path}: {e}"
            )

            # Try to clean up capture file even if analysis failed (if requested)
            if cleanup_capture_file:
                await self._cleanup_capture_file(capture_file_path)

            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.ERROR,
                message=f"BGP tcpdump analysis failed on {hostname}: {str(e)}",
            )

    async def _move_capture_file_on_failure(self, capture_file_path: str) -> None:
        """Move capture file to a failure directory for debugging."""
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        failure_dir = "/tmp/bgp_capture_failures"
        failure_file_path = f"{failure_dir}/bgp_capture_{timestamp}.txt"

        try:
            # Create failure directory if it doesn't exist
            mkdir_cmd = f'bash mkdir -p "{failure_dir}"'
            # pyrefly: ignore [missing-attribute]
            await self.driver.async_execute_show_or_configure_cmd_on_shell(mkdir_cmd)

            # Move the capture file
            move_cmd = f'bash sudo mv "{capture_file_path}" "{failure_file_path}"'
            # pyrefly: ignore [missing-attribute]
            await self.driver.async_execute_show_or_configure_cmd_on_shell(move_cmd)
            self.logger.info(f"Moved capture file to {failure_file_path} for debugging")
        except Exception as e:
            self.logger.warning(f"Failed to move capture file {capture_file_path}: {e}")

    async def _cleanup_capture_file(self, capture_file_path: str) -> None:
        """Clean up the capture file after analysis to save disk space."""
        try:
            cleanup_cmd = f'bash sudo rm -f "{capture_file_path}"'
            # pyrefly: ignore [missing-attribute]
            await self.driver.async_execute_show_or_configure_cmd_on_shell(cleanup_cmd)
            self.logger.info(
                f"Successfully cleaned up capture file: {capture_file_path}"
            )
        except Exception as e:
            self.logger.warning(
                f"Failed to clean up capture file {capture_file_path}: {e}"
            )

    def _generate_health_check_result(
        self, hostname: str, capture_file_path: str, analysis_result: t.Any
    ) -> hc_types.HealthCheckResult:
        """Generate health check result based on analysis."""

        # Handle BgpAnalysisResult object from new regex-based analyzer
        total_packets = analysis_result.total_packets
        message_counts = analysis_result.message_counts
        violations = analysis_result.violations
        analysis_method = analysis_result.analysis_method

        # Check for violations
        if violations:
            violation_details = [
                f"- {v['message_type']}: {v['packet_info']}"
                for v in violations[:5]  # Show first 5 violations
            ]

            if len(violations) > 5:
                violation_details.append(
                    f"... and {len(violations) - 5} more violation types"
                )

            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=(
                    f"BGP tcpdump analysis on {hostname}: Found {len(violations)} violations. "
                    f"Non-allowed message types detected:\n"
                    + "\n".join(violation_details)
                ),
            )

        # No violations found - health check passes
        message_summary = ", ".join(
            [f"{count} {msg_type}" for msg_type, count in message_counts.items()]
        )

        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
            message=(
                f"BGP tcpdump analysis on {hostname}: No violations found. "
                f"Analyzed {total_packets} packets ({analysis_method}) with message distribution: {message_summary}."
            ),
        )
