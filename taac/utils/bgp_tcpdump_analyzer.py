# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-strict

"""
BGP Tcpdump Analyzer Utility

This module provides BGP packet analysis functionality using tcpdump + grep
for efficient processing of large capture files. Instead of parsing hex data in Python,
it uses regex patterns to directly extract BGP message types from tcpdump output.

For BGP UPDATE message packing analysis, use the BgpPcapAnalyzer module which
provides IXIA PCAP-based analysis with tshark parsing.
"""

import typing as t
from dataclasses import dataclass

from taac.utils.file_verification_utils import (
    verify_file_modification_time,
)


@dataclass
class BgpAnalysisResult:
    """Results from BGP packet analysis."""

    total_packets: int
    message_counts: t.Dict[str, int]
    violations: t.List[t.Dict[str, str]]
    unexpected_message_type_count: int
    analysis_method: str = "regex_based"

    @property
    def has_violations(self) -> bool:
        """Check if analysis found any violations."""
        return len(self.violations) > 0


class BgpTcpdumpAnalyzer:
    """
    BGP packet analysis utility.

    This analyzer uses regex patterns to directly extract BGP message types
    from capture output.

    Note: We are not actually reading a full tcpdump file, but a subset of it to save on space.
    The output format can be found by the command stored in ARISTA_DAEMON_EXEC_SCRIPTS["tcpdump"]

    TODO: Add support for extracting timestamp, dst, and src ip
    """

    # BGP message type patterns
    BGP_MESSAGE_PATTERNS = {
        "OPEN": r"Open",
        "UPDATE": r"Update",
        "NOTIFICATION": r"Notification",
        "KEEPALIVE": r"Keepalive",
        "ROUTE-REFRESH": r"Route-Refresh",
    }

    def __init__(self, logger: t.Any) -> None:
        self.logger = logger

    async def count_bgp_message_type(
        self, capture_file_path: str, driver: t.Any, message_type: str
    ) -> int:
        """Count occurrences of a specific BGP message type in capture file."""
        if message_type not in self.BGP_MESSAGE_PATTERNS:
            self.logger.warning(f"Unknown BGP message type: {message_type}")
            return 0

        pattern = self.BGP_MESSAGE_PATTERNS[message_type]

        # Grep the file directly - supports both text tcpdump output and raw pcap files
        # For text files, this will match the pattern directly
        # For pcap files, first check if we need to use tcpdump to convert to text
        cmd = f'bash grep -cE "{pattern}" "{capture_file_path}" || echo "0"'

        try:
            self.logger.debug(f"Executing command: {cmd}")
            result = await driver.async_execute_show_or_configure_cmd_on_shell(
                cmd, timeout=300
            )
            self.logger.debug(f"Command result: '{result}'")

            # Parse the result - extract the number from output
            count = 0
            if result:
                # Split by lines and look for the last line that's a pure number
                lines = result.strip().split("\n")
                for line in reversed(lines):  # Check from last line first
                    line = line.strip()
                    if line.isdigit():
                        count = int(line)
                        break
            self.logger.info(
                f"Found {count} {message_type} messages using pattern: {pattern}"
            )
            return count
        except Exception as e:
            self.logger.warning(
                f"Error counting {message_type} messages with pattern '{pattern}': {e}"
            )
            return 0

    async def count_all_bgp_messages(
        self, capture_file_path: str, driver: t.Any
    ) -> t.Dict[str, int]:
        """Count all BGP message types in capture file."""
        message_counts = {}

        for message_type in self.BGP_MESSAGE_PATTERNS.keys():
            count = await self.count_bgp_message_type(
                capture_file_path, driver, message_type
            )
            # Always include the count, even if it's 0
            message_counts[message_type] = count

        self.logger.info(f"BGP message counts: {message_counts}")
        return message_counts

    def create_analysis_result(
        self, timestamp: str, message_type: str, src: str, dst: str, packet_info: str
    ) -> t.Dict[str, str]:
        """
        Helper to create a violation
        """
        violation = {
            "timestamp": timestamp,
            "message_type": message_type,
            "src": src,
            "dst": dst,
            "packet_info": packet_info,
        }
        return violation

    async def analyze_capture_file(
        self,
        capture_file_path: str,
        driver: t.Any,
        expected_message_types: t.List[str],
        unexpected_message_types: t.List[str],
        expected_last_mod_time: t.Optional[int] = None,
    ) -> BgpAnalysisResult:
        """
        Analyze capture file for expected and not expected BGP message types.
        """
        self.logger.info(
            f"Starting comprehensive regex-based analysis of {capture_file_path}"
        )

        # Count all message types
        message_counts = await self.count_all_bgp_messages(capture_file_path, driver)

        violations = []

        for msg_type in expected_message_types:
            if msg_type not in message_counts:
                self.logger.warning(f"expected msg_type {msg_type} not found")
                violations.append(
                    self.create_analysis_result(
                        "unknown",
                        msg_type,
                        "unknown",
                        "unknown",
                        f"Expected: {msg_type}, Not Found.",
                    )
                )
            elif message_counts[msg_type] < 1:
                self.logger.warning(f"expected msg_type {msg_type} count is 0")
                violations.append(
                    self.create_analysis_result(
                        "unknown",
                        msg_type,
                        "unknown",
                        "unknown",
                        f"Expected: {msg_type}, count > 0.",
                    )
                )

        unexpected_message_type_count = 0
        for msg_type in unexpected_message_types:
            if msg_type in message_counts and message_counts[msg_type] > 0:
                unexpected_message_type_count += message_counts[msg_type]
                self.logger.warning(f"unexpected msg_type {msg_type} found")
                violations.append(
                    self.create_analysis_result(
                        "unknown",
                        msg_type,
                        "unknown",
                        "unknown",
                        f"Unexpected: {msg_type}, Found {message_counts[msg_type]} times",
                    )
                )
        total_packets = sum(message_counts.values())

        if expected_last_mod_time is not None:
            mod_result = await verify_file_modification_time(
                driver=driver,
                file_path=capture_file_path,
                expected_last_mod_time=expected_last_mod_time,
                logger=self.logger,
            )
            if not mod_result.success:
                violations.append(
                    self.create_analysis_result(
                        "unknown", "unknown", "unknown", "unknown", mod_result.message
                    )
                )

        self.logger.info(
            f"Analysis complete: {total_packets} total packets, {len(violations)} violations"
        )

        return BgpAnalysisResult(
            total_packets=total_packets,
            message_counts=message_counts,
            violations=violations,
            unexpected_message_type_count=unexpected_message_type_count,
            analysis_method="regex_based_comprehensive",
        )
