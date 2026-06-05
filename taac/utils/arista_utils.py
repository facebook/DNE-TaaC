# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-strict
import logging
import re
import time
import typing as t
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional

from taac.constants import ARISTA_BGP_PLUS_PLUS_DAEMON_MAPPINGS
from taac.utils import log_parsing_utils


logger: logging.Logger = logging.getLogger(__name__)

AGENT_LOGS_PATH = "/var/log/agents"
ARCHIVED_AGENT_LOGS_PATH = "/mnt/flash/archive/current/var/log/agents"


def find_pid_in_output(output: str) -> t.Optional[str]:
    """Extract the first PID from command output that may contain EOS prompt lines."""
    if not output:
        return None
    for line in output.splitlines():
        line = line.strip()
        if line and line.split()[0].isdigit():
            return line.split()[0]
    return None


async def get_daemon_pid(driver: t.Any, daemon_name: str) -> t.Optional[str]:
    """Get PID for daemon by checking all mapped process names."""
    mapping = ARISTA_BGP_PLUS_PLUS_DAEMON_MAPPINGS.get(
        daemon_name, {"processes": [daemon_name]}
    )

    for process_name in mapping["processes"]:
        pid = await find_process_pid(driver, process_name)
        if pid:
            return pid
    return None


async def find_process_pid(driver: t.Any, process_name: str) -> t.Optional[str]:
    """Find PID using EOS 'show processes' command."""
    logger.info(f"[ARISTA_UTILS] Finding PID for process: {process_name}")

    try:
        show_cmd = f"show processes | grep {process_name}"
        logger.info(f"[ARISTA_UTILS] Running EOS command: {show_cmd}")

        output = await driver.async_run_cmd_on_shell(show_cmd)
        logger.info(f"[ARISTA_UTILS] EOS command output: {repr(output)}")

        if output and output.strip():
            for i, line in enumerate(output.splitlines()):
                line_stripped = line.strip()
                logger.info(f"[ARISTA_UTILS] EOS Line {i}: {repr(line_stripped)}")

                if (
                    line_stripped
                    and process_name in line_stripped
                    and not line_stripped.startswith("#")
                    and "grep" not in line_stripped
                ):
                    parts = line_stripped.split()
                    logger.info(
                        f"[ARISTA_UTILS] EOS Split into {len(parts)} parts: {parts}"
                    )

                    if len(parts) >= 1 and parts[0].isdigit():
                        pid = parts[0]  # PID is first column in show processes
                        logger.info(
                            f"[ARISTA_UTILS] Found PID from EOS show processes: {pid}"
                        )
                        return pid

    except Exception as e:
        logger.error(
            f"[ARISTA_UTILS] EOS show processes failed for {process_name}: {e}"
        )

    logger.warning(f"[ARISTA_UTILS] No PID found for process: {process_name}")
    return None


def get_agent_log_file(daemon_name: str, pid: str) -> str:
    """Get log file path using daemon mapping."""
    mapping = ARISTA_BGP_PLUS_PLUS_DAEMON_MAPPINGS.get(daemon_name)
    if mapping and isinstance(mapping, dict):
        log_pattern = mapping.get("log_pattern", f"{daemon_name}-{{pid}}")
        log_name = log_pattern.format(pid=pid)
    else:
        log_name = f"{daemon_name}-{pid}"

    return f"/var/log/agents/{log_name}"


async def get_archived_agent_logs(
    driver: t.Any, daemon_name: str, pid: str, time_to_mointor: Optional[str] = None
) -> str:
    """
    Find and extract archived agent logs for a given daemon and PID.

    Searches in both AGENT_LOGS_PATH and ARCHIVED_AGENT_LOGS_PATH directories
    for archived log files (*.gz) matching the daemon's log file pattern.
    Unzips files while preserving originals, reads contents, and returns combined output.

    Args:
        driver: Device driver for running commands
        daemon_name: Name of the daemon
        pid: Process ID of the daemon

    Returns:
        Combined contents of all archived log files as a string
    """
    log_file_path = get_agent_log_file(daemon_name, pid)
    log_name = log_file_path.split("/")[-1]
    combined_contents = []

    logger.info(
        f"[ARISTA_UTILS] Searching for archived logs in {ARCHIVED_AGENT_LOGS_PATH} matching {log_name}*.gz"
    )

    find_cmd = f"bash find {ARCHIVED_AGENT_LOGS_PATH} -name '{log_name}*.gz' 2>/dev/null || true"
    output = await driver.async_execute_show_or_configure_cmd_on_shell(find_cmd)

    if not output or not output.strip():
        logger.info(
            f"[ARISTA_UTILS] No archived logs found in {ARCHIVED_AGENT_LOGS_PATH}"
        )
        return ""

    archived_files = [f.strip() for f in output.strip().split("\n") if f.strip()]
    archived_files = set(archived_files)
    logger.info(
        f"[ARISTA_UTILS] Found {len(archived_files)} archived log files in {ARCHIVED_AGENT_LOGS_PATH}"
    )

    for archived_file in archived_files:
        try:
            logger.info(f"[ARISTA_UTILS] Processing archived file: {archived_file}")

            unzip_cmd = f"bash sudo su\ngunzip -k {archived_file} 2>/dev/null\nexit"
            await driver.async_run_cmd_on_shell(unzip_cmd)

            unzipped_file = archived_file.rstrip(".gz")

            read_cmd = f"bash cat {unzipped_file}"
            content = await driver.async_execute_show_or_configure_cmd_on_shell(
                read_cmd
            )

            if content:
                combined_contents.append(content)
                logger.info(
                    f"[ARISTA_UTILS] Read {len(content)} bytes from {unzipped_file}"
                )

            cleanup_cmd = f"rm -f {unzipped_file}"
            await driver.async_run_cmd_on_shell(cleanup_cmd)

        except Exception as e:
            error_msg = (
                f"[ARISTA_UTILS] Failed to process archived file {archived_file}: {e}"
            )
            logger.error(error_msg)
            raise ArchivedLogError(error_msg) from e

    result = "\n".join(combined_contents)
    logger.info(
        f"[ARISTA_UTILS] Combined archived logs total size: {len(result)} bytes"
    )
    return result


async def check_eos_system_logs(
    driver: t.Any,
    start_time: t.Optional[int] = None,
    end_time: t.Optional[int] = None,
) -> t.List[str]:
    """
    Check EOS system logs for emergency/critical/error entries.

    Args:
        driver: Device driver
        start_time: Optional start time filter (Unix timestamp)
        end_time: Optional end time filter (Unix timestamp)

    Returns:
        List of formatted log entries that match the time filter (if provided)
    """
    log_commands = [
        ("show logging emergencies", "emergency"),
        ("show logging critical", "critical"),
        ("show logging errors", "error"),
    ]

    all_entries = []
    for cmd, log_type in log_commands:
        logger.info(f"[ARISTA_UTILS] Running system log command: {cmd}")

        output = await driver.async_run_cmd_on_shell(cmd)
        entries = parse_eos_log_output(output, log_type, start_time, end_time)
        all_entries.extend(entries)

        logger.info(f"[ARISTA_UTILS] Found {len(entries)} {log_type} entries")

    logger.info(f"[ARISTA_UTILS] Total system log entries: {len(all_entries)}")
    return all_entries


def parse_eos_log_output(
    output: str,
    log_type: str,
    start_time: t.Optional[int] = None,
    end_time: t.Optional[int] = None,
) -> t.List[str]:
    """
    Parse EOS logging command output with optional time filtering.

    Args:
        output: Raw output from EOS logging command
        log_type: Type of log (emergency, critical, error)
        start_time: Optional start time filter (Unix timestamp)
        end_time: Optional end time filter (Unix timestamp)

    Returns:
        List of formatted log entries that match the time filter (if provided)
    """
    # Parse all log entries first
    raw_entries = [
        line
        for line in output.strip().split("\n")
        if line.strip() and "#" not in line.strip()
    ]

    # Apply time filtering if specified
    if start_time and end_time:
        # Use EOS-specific time filtering logic for system logs
        filtered_entries = []
        for line in raw_entries:
            if log_parsing_utils.is_eos_system_log_line_in_time_range(
                line, start_time, end_time
            ):
                filtered_entries.append(line)
        raw_entries = filtered_entries

    # Format the entries
    return [f"[{log_type.upper()}] {line}" for line in raw_entries]


# Daemon status monitoring utilities


@dataclass(frozen=True)
class DaemonStatus:
    """Immutable daemon status information."""

    is_running: bool
    pid: t.Optional[str] = None
    uptime: t.Optional[str] = None


class DaemonParsingError(Exception):
    """Raised when daemon output parsing fails."""

    pass


class ArchivedLogError(Exception):
    """Raised when archived log processing fails."""

    pass


def parse_daemon_output(daemon_name: str, output: str) -> DaemonStatus:
    """
    Parse daemon command output to extract status information.

    Expected format from 'show daemon <name>':
    Process: Bgp (running with PID 12765)
    Uptime: 0:33:54 (Start time: Fri Sep 26 04:40:12 2025)

    Args:
        daemon_name: Name of the daemon to parse status for
        output: Raw command output from daemon status query

    Returns:
        DaemonStatus object containing parsed information

    Raises:
        DaemonParsingError: If output format is unexpected or parsing fails
    """
    if not output or not output.strip():
        logger.warning(f"Empty daemon output for {daemon_name}")
        return DaemonStatus(is_running=False)

    try:
        lines = output.strip().split("\n")
        is_running = False
        pid = None
        uptime = None

        # Regex patterns for robust parsing - handle both "Process:" and "Agent:" prefixes
        process_pattern = re.compile(
            rf"(?:Process|Agent):\s+{re.escape(daemon_name)}\s+\(running with PID\s+(\d+)\)",
            re.IGNORECASE,
        )
        uptime_pattern = re.compile(r"Uptime:\s+([^\(]+)", re.IGNORECASE)

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Check for running process with PID
            process_match = process_pattern.search(line)
            if process_match:
                is_running = True
                pid = process_match.group(1)
                logger.debug(f"Found running daemon {daemon_name} with PID {pid}")
                continue

            # Check for uptime information
            uptime_match = uptime_pattern.search(line)
            if uptime_match:
                uptime = uptime_match.group(1).strip()
                logger.debug(f"Found uptime for {daemon_name}: {uptime}")
                continue

        return DaemonStatus(is_running=is_running, pid=pid, uptime=uptime)

    except (AttributeError, IndexError) as e:
        error_msg = f"Failed to parse daemon output for {daemon_name}: {e}"
        logger.error(error_msg)
        raise DaemonParsingError(error_msg) from e


async def get_daemon_status_comprehensive(
    driver: t.Any, daemon_name: str
) -> DaemonStatus:
    """
    Get comprehensive daemon status using multiple methods for reliability.

    This function combines 'show daemon' output parsing with direct process lookup
    using the existing find_process_pid function for enhanced accuracy.

    Args:
        driver: Device driver for running commands
        daemon_name: Name of the daemon to check

    Returns:
        DaemonStatus with the most accurate information available
    """

    daemon_cmd = f"show daemon {daemon_name}"
    logger.debug(f"Getting daemon status via: {daemon_cmd}")
    daemon_output = await driver.async_run_cmd_on_shell(daemon_cmd)

    status = parse_daemon_output(daemon_name, daemon_output)

    return status


def parse_uptime_to_seconds(uptime_str: str) -> t.Optional[int]:
    """
    Convert uptime string to seconds with robust parsing.

    Supports formats:
    - H:M:S (e.g., '1:23:45')
    - M:S (e.g., '23:45')
    - Days included (e.g., '2 days, 1:23:45')

    Args:
        uptime_str: Uptime string from daemon output

    Returns:
        Total seconds as integer, or None if parsing fails
    """
    if not uptime_str or not uptime_str.strip():
        return None

    try:
        # Clean the input string
        clean_str = uptime_str.strip()

        # Handle days format: "2 days, 1:23:45"
        days = 0
        if "day" in clean_str.lower():
            parts = clean_str.split(",")
            if len(parts) >= 2:
                # Extract days
                day_part = parts[0].strip()
                day_match = re.search(r"(\d+)\s+days?", day_part, re.IGNORECASE)
                if day_match:
                    days = int(day_match.group(1))
                clean_str = parts[1].strip()
            else:
                # Only days, no time component
                day_match = re.search(r"(\d+)\s+days?", clean_str, re.IGNORECASE)
                if day_match:
                    return int(day_match.group(1)) * 24 * 3600
                return None

        # Parse time components: H:M:S or M:S
        time_parts = clean_str.split(":")
        time_parts = [
            int(part.strip()) for part in time_parts if part.strip().isdigit()
        ]

        total_seconds = days * 24 * 3600

        if len(time_parts) == 3:  # H:M:S format
            hours, minutes, seconds = time_parts
            total_seconds += hours * 3600 + minutes * 60 + seconds
        elif len(time_parts) == 2:  # M:S format
            minutes, seconds = time_parts
            total_seconds += minutes * 60 + seconds
        elif len(time_parts) == 1:  # Just seconds
            total_seconds += time_parts[0]
        else:
            logger.warning(f"Unexpected uptime format: {uptime_str}")
            return None

        return total_seconds

    except (ValueError, AttributeError, IndexError) as e:
        logger.warning(f"Failed to parse uptime '{uptime_str}': {e}")
        return None


def parse_daemon_start_time(daemon_output: str) -> t.Optional[datetime]:
    """
    Parse daemon start time from 'show daemon' output.

    Expected format:
        Uptime: 1:22:11 (Start time: Sun Nov 23 16:27:04 2025)

    Args:
        daemon_output: Raw output from 'show daemon <name>' command

    Returns:
        datetime object of when daemon started, or None if parsing fails
    """
    if not daemon_output or not daemon_output.strip():
        logger.warning("Empty daemon output, cannot parse start time")
        return None

    try:
        for line in daemon_output.split("\n"):
            if "Start time:" in line:
                # Extract the datetime string after "Start time: "
                # Format: "Uptime: 1:22:11 (Start time: Sun Nov 23 16:27:04 2025)"
                start_time_str = line.split("Start time:")[-1].strip().rstrip(")")
                # Parse format: "Sun Nov 23 16:27:04 2025"
                return datetime.strptime(start_time_str, "%a %b %d %H:%M:%S %Y")
        logger.warning(f"No 'Start time:' found in daemon output:\n{daemon_output}")
        return None
    except (ValueError, IndexError) as e:
        logger.warning(f"Failed to parse daemon start time: {e}")
        return None


async def get_latest_files(file_set: t.Set[str], n: int = 3) -> t.List[str]:
    """
    Extract the n files with the latest timestamps from a set of filenames.

    Args:
        file_set: Set of file paths with format containing timestamp after last underscore
        n: Number of latest files to return (default: 2)

    Returns:
        List of n file paths with the latest timestamps
    """

    def extract_timestamp(filepath: str) -> int:
        # Extract timestamp from filename (after last underscore, before .gz if present)
        filename = filepath.split("/")[-1]

        # Only process files ending with .gz or no extension
        if not (filename.endswith(".gz")):
            return int(time.time())
        # Remove .gz extension if present
        timestamp_str = filename.replace(".gz", "").split("_")[-1]

        try:
            return int(timestamp_str)
        except ValueError:
            return int(time.time())

    # Sort files by timestamp in descending order and return top n
    sorted_files = sorted(file_set, key=extract_timestamp, reverse=True)
    return sorted_files[:n]


async def get_archived_logs_data(
    driver: t.Any,
    daemon_name: str,
    pid: str,
    time_stamp_str: t.Optional[str] = None,
    file_count_to_parse: int = 3,
    time_to_mointor: int = 30,
) -> t.Tuple[str, int]:
    """
    Retrieve and process archived agent logs for a specific daemon and process ID.
    This function searches for archived log files (*.gz) in the ARCHIVED_AGENT_LOGS_PATH
    directory that match the daemon's log file pattern. It processes the latest log files
    using a filtering script, reads the filtered output, analyzes the log updates, and
    returns the combined results as a string.
    Args:
        driver (Any): Device driver object used to execute shell commands asynchronously.
        daemon_name (str): Name of the daemon whose logs are to be retrieved.
        pid (str): Process ID of the daemon.
        time_stamp_str (str): Timestamp string used for analyzing log updates.
        file_count_to_parse (int, optional): Number of latest archived log files to process. Defaults to 3.
    Returns:
        Tuple[datetime.timedelta, int]:
            - The time difference between the highest and lowest timestamps in the logs.
            - The total count of log updates found.
    """
    if time_stamp_str is None:
        time_stamp_str = datetime.now().strftime("%H:%M:%S")

    # Clean up any previous filtered logs
    await driver.async_run_cmd_on_shell("rm -f /tmp/filtered_logs")
    log_file_path = get_agent_log_file(daemon_name, pid)
    log_name = log_file_path.split("/")[-1]
    logger.info(
        f"[ARISTA_UTILS] Searching for archived logs in {ARCHIVED_AGENT_LOGS_PATH} matching {log_name}*.gz"
    )
    # Find matching archived log files
    find_cmd = (
        f"bash find {ARCHIVED_AGENT_LOGS_PATH} -name '{log_name}*' 2>/dev/null || true"
    )
    output = await driver.async_execute_show_or_configure_cmd_on_shell(find_cmd)
    if not output or not output.strip():
        logger.info(
            f"[ARISTA_UTILS] No archived logs found in {ARCHIVED_AGENT_LOGS_PATH}"
        )
        return ("0:00:00", 0)
    archived_files = {f.strip() for f in output.strip().split("\n") if f.strip()}
    required_files = await get_latest_files(archived_files, file_count_to_parse)
    # Run the filtering script on the required files
    bash_command = (
        f"bash sudo su\ncd /mnt/flash\n./filtering_script.sh {' '.join(required_files)}"
    )
    await driver.async_execute_show_or_configure_cmd_on_shell(bash_command)
    # Read the filtered logs
    read_cmd = "bash cat /tmp/filtered_logs"
    content = await driver.async_execute_show_or_configure_cmd_on_shell(read_cmd)
    # Analyze the log updates
    complete_found_data = await analyze_log_updates(
        content, end_timestamp_str=time_stamp_str, time_window_minutes=time_to_mointor
    )
    lowest = complete_found_data["lowest_timestamp"]
    highest = complete_found_data["highest_timestamp"]
    # Define the format
    fmt = "%H:%M:%S.%f"
    # Convert to datetime objects
    if lowest is None or highest is None:
        return ("0:00:00", 0)
    lowest_dt = datetime.strptime(lowest, fmt)
    highest_dt = datetime.strptime(highest, fmt)
    # Calculate the difference
    time_diff = highest_dt - lowest_dt
    # Extract total count
    total_count = complete_found_data["total_count"]
    # Clean up filtered logs
    await driver.async_run_cmd_on_shell("rm -f /tmp/filtered_logs")
    return (str(time_diff), total_count)


async def analyze_log_updates(
    log_string: str,
    end_timestamp_str: str,
    time_window_minutes: int = 10,
) -> t.Dict[str, t.Any]:
    """
    Analyze log entries within a time window and calculate update statistics.

    Args:
        log_string: Multi-line log string
        start_timestamp_str: Starting timestamp in format "HH:MM:SS" (e.g., "15:15:12")
        time_window_minutes: Time window in minutes (default: 10)

    Returns:
        dict with keys:
            - lowest_timestamp: Earliest timestamp in range
            - highest_timestamp: Latest timestamp in range
            - total_count: Sum of all update counts
            - entries: List of matching entries with timestamps and counts
    """
    end_time = datetime.strptime(end_timestamp_str, "%H:%M:%S")
    start_time = end_time - timedelta(minutes=time_window_minutes)
    pattern = r"I\d{4} (\d{2}:\d{2}:\d{2}\.\d+).*Programmed HW with (\d+) updates\."

    matching_entries = []

    for line in log_string.strip().split("\n"):
        match = re.search(pattern, line)
        if match:
            timestamp_str = match.group(1)
            count = int(match.group(2))

            log_time = datetime.strptime(timestamp_str.split(".")[0], "%H:%M:%S")
            if start_time <= log_time <= end_time:
                matching_entries.append(
                    {"timestamp": timestamp_str, "count": count, "line": line.strip()}
                )

    if not matching_entries:
        return {
            "lowest_timestamp": None,
            "highest_timestamp": None,
            "total_count": 0,
            "entries": [],
        }

    unique_entries = []
    seen = set()

    for entry in matching_entries:
        entry_tuple = (entry["timestamp"], entry["count"], entry["line"])
        if entry_tuple not in seen:
            seen.add(entry_tuple)
            unique_entries.append(entry)
    timestamps = [e["timestamp"] for e in unique_entries]
    total_count = sum(e["count"] for e in unique_entries)
    return {
        "lowest_timestamp": min(timestamps),
        "highest_timestamp": max(timestamps),
        "total_count": total_count,
        "entries": unique_entries,
    }


async def parse_ipv6_prefix(prefix_bin: bytes, num_bits: int) -> str:
    """Convert binary IPv6 prefix to readable format"""
    if len(prefix_bin) == 16:
        ipv6_int = int.from_bytes(prefix_bin, byteorder="big")
        parts = []
        for i in range(8):
            parts.append(format((ipv6_int >> (112 - i * 16)) & 0xFFFF, "x"))
        return f"{':'.join(parts)}/{num_bits}"
    return f"<binary:{prefix_bin.hex()}>/{num_bits}"


async def parse_ipv4_prefix(prefix_bin: bytes, num_bits: int) -> str:
    """Convert binary IPv4 prefix to readable format"""
    if len(prefix_bin) == 4:
        ipv4_int = int.from_bytes(prefix_bin, byteorder="big")
        parts = []
        for i in range(4):
            parts.append(str((ipv4_int >> (24 - i * 8)) & 0xFF))
        return f"{'.'.join(parts)}/{num_bits}"
    return f"<binary:{prefix_bin.hex()}>/{num_bits}"


async def parse_bgp_paths(paths_list: List[t.Any], afi: str) -> set[str]:
    """
    Parse BGP paths and group prefixes by their next hops.
    Only processes paths where peer_description contains 'EBGP'.

    Returns:
        set: Set of next hop strings for EBGP paths
    """
    best_paths = paths_list
    # Filter for EBGP paths
    ebgp_paths = [path for path in best_paths if "EBGP" in path.peer_description]

    if not ebgp_paths:
        logger.info("No EBGP paths found in the data")
        return set()

    next_hops = set()

    for path in ebgp_paths:
        next_hop = path.next_hop
        if afi == "v6":
            next_hop_str = await parse_ipv6_prefix(
                next_hop.prefix_bin, next_hop.num_bits
            )
        else:
            next_hop_str = await parse_ipv4_prefix(
                next_hop.prefix_bin, next_hop.num_bits
            )

        next_hops.add(next_hop_str)

    return set(sorted(next_hops))


def detect_daemon_restart(
    daemon_name: str,
    pre_status: DaemonStatus,
    post_status: DaemonStatus,
    test_duration_seconds: int,
    tolerance_factor: float = 0.1,
) -> t.Optional[str]:
    """
    Detect daemon restart by comparing status snapshots.

    Args:
        daemon_name: Name of the daemon being monitored
        pre_status: Daemon status before test
        post_status: Daemon status after test
        test_duration_seconds: Expected test duration
        tolerance_factor: Acceptable variance in uptime calculation (0.1 = 10%)

    Returns:
        Restart reason string if restart detected, None otherwise
    """
    # Check if daemon stopped running
    if pre_status.is_running and not post_status.is_running:
        return f"daemon stopped running (was PID {pre_status.pid})"

    # Check if daemon wasn't running before
    if not pre_status.is_running:
        if post_status.is_running:
            return f"daemon started during test (now PID {post_status.pid})"
        return None  # Still not running, no restart

    # Both statuses show daemon running - check for restart indicators
    if not post_status.is_running:
        return "daemon not running after test"

    # Compare PIDs (most reliable indicator)
    if pre_status.pid and post_status.pid and pre_status.pid != post_status.pid:
        return f"PID changed from {pre_status.pid} to {post_status.pid}"

    # Compare uptimes for restart detection
    if pre_status.uptime and post_status.uptime:
        pre_seconds = parse_uptime_to_seconds(pre_status.uptime)
        post_seconds = parse_uptime_to_seconds(post_status.uptime)

        if pre_seconds is not None and post_seconds is not None:
            expected_min_uptime = pre_seconds + int(
                test_duration_seconds * (1 - tolerance_factor)
            )

            if post_seconds < expected_min_uptime:
                return (
                    f"uptime decreased unexpectedly "
                    f"(pre: {pre_status.uptime} -> post: {post_status.uptime}, "
                    f"expected min: {expected_min_uptime}s)"
                )

    return None


def interface_name_to_short_format(interface_name: str) -> str:
    """
    Converts interface name from full format to short format.

    Example:
        'Ethernet3/1/3' -> 'et3_1_3'

    Args:
        interface_name: Full interface name (e.g., 'Ethernet3/1/3')

    Returns:
        Shortened format (e.g., 'et3_1_3')
    """
    if interface_name.startswith("Ethernet"):
        # Remove 'Ethernet' prefix and add 'et' prefix
        short_name = "et" + interface_name[len("Ethernet") :]
        # Replace '/' with '_'
        short_name = short_name.replace("/", "_")
        return short_name

    # For other interface types, just replace '/' with '_'
    return interface_name.replace("/", "_")


@dataclass(frozen=True)
class NexthopGroupSummary:
    """Nexthop group summary information from Arista device."""

    num_groups_configured: int
    num_unprogrammed_groups: int
    nexthop_group_sizes: t.Dict[int, int]
    nexthop_group_types: t.Dict[str, int]


async def get_bgpcpp_version(driver: t.Any) -> str:
    """
    Get BGP++ version from Arista EOS device using driver interface.

    This is a convenience wrapper around the driver's async_get_bgpcpp_version() method.

    Args:
        driver: Device driver for running commands

    Returns:
        Version string (e.g., "fb-bgpcpp:20251106 (platform010, cfebe8b)")
        or "BGP++ (version unknown)" if command fails
    """
    return await driver.async_get_bgpcpp_version()


async def get_nexthop_group_summary(driver: t.Any) -> NexthopGroupSummary:
    """
    Get and parse nexthop group summary from Arista device.

    Example output:
        eb03.lab.ash6# show nexthop-group summary
        Number of Nexthop Groups configured: 2
        Number of unprogrammed Nexthop Groups: 0

          Nexthop Group Type   Configured
        -------------------- ------------
                          IP            2

          Nexthop Group Size   Configured
        -------------------- ------------
                         140            2

    Args:
        driver: Device driver for running commands

    Returns:
        NexthopGroupSummary with parsed information

    Raises:
        ValueError: If output format is unexpected or parsing fails
    """
    logger.info("[ARISTA_UTILS] Getting nexthop group summary")

    try:
        output = await driver.async_get_nexthop_group_summary()
        logger.debug(f"[ARISTA_UTILS] Nexthop group summary output: {repr(output)}")

        if not output or not output.strip():
            raise ValueError("Empty output from show nexthop-group summary")

        num_groups_configured = 0
        num_unprogrammed_groups = 0
        nexthop_group_sizes: t.Dict[int, int] = {}
        nexthop_group_types: t.Dict[str, int] = {}

        lines = output.strip().split("\n")
        current_section = None

        for line in lines:
            line = line.strip()
            if not line or line.startswith("-") or line.startswith("#"):
                continue

            # Parse "Number of Nexthop Groups configured: X"
            if "Number of Nexthop Groups configured:" in line:
                match = re.search(r"configured:\s*(\d+)", line)
                if match:
                    num_groups_configured = int(match.group(1))
                    logger.debug(
                        f"[ARISTA_UTILS] Found num_groups_configured: {num_groups_configured}"
                    )
                continue

            # Parse "Number of unprogrammed Nexthop Groups: X"
            if "Number of unprogrammed Nexthop Groups:" in line:
                match = re.search(r"unprogrammed Nexthop Groups:\s*(\d+)", line)
                if match:
                    num_unprogrammed_groups = int(match.group(1))
                    logger.debug(
                        f"[ARISTA_UTILS] Found num_unprogrammed_groups: {num_unprogrammed_groups}"
                    )
                continue

            # Detect section headers
            if "Nexthop Group Type" in line and "Configured" in line:
                current_section = "types"
                logger.debug("[ARISTA_UTILS] Entering types section")
                continue

            if "Nexthop Group Size" in line and "Configured" in line:
                current_section = "sizes"
                logger.debug("[ARISTA_UTILS] Entering sizes section")
                continue

            # Parse data rows based on current section
            if current_section == "types":
                parts = line.split()
                if len(parts) == 2 and parts[1].isdigit():
                    group_type = parts[0]
                    count = int(parts[1])
                    nexthop_group_types[group_type] = count
                    logger.debug(
                        f"[ARISTA_UTILS] Found group type: {group_type} = {count}"
                    )
            elif current_section == "sizes":
                parts = line.split()
                if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                    size = int(parts[0])
                    count = int(parts[1])
                    nexthop_group_sizes[size] = count
                    logger.debug(f"[ARISTA_UTILS] Found group size: {size} = {count}")

        logger.info(
            f"[ARISTA_UTILS] Parsed nexthop group summary: "
            f"configured={num_groups_configured}, "
            f"unprogrammed={num_unprogrammed_groups}, "
            f"types={nexthop_group_types}, "
            f"sizes={nexthop_group_sizes}"
        )

        return NexthopGroupSummary(
            num_groups_configured=num_groups_configured,
            num_unprogrammed_groups=num_unprogrammed_groups,
            nexthop_group_sizes=nexthop_group_sizes,
            nexthop_group_types=nexthop_group_types,
        )

    except Exception as e:
        error_msg = f"[ARISTA_UTILS] Failed to get nexthop group summary: {e}"
        logger.error(error_msg)
        raise ValueError(error_msg) from e


def generate_self_signed_tls_certs_commands(
    cert_dir: str = "/mnt/fb/certs",
    cert_names: t.Optional[t.List[str]] = None,
) -> t.List[str]:
    """
    Generate shell commands to deploy TLS certificates for BGP++ daemons.

    FibAgent, BGP++, and OpenR daemons require TLS certs at specific paths
    under /mnt/fb/certs/. This function generates commands that:
    1. Skip if valid certs already exist (e.g. from Delegator or manual copy)
    2. Generate a self-signed cert as fallback (TLS only, no authorization)

    Each output PEM file contains both cert + key so ThriftServer can use it
    for mTLS.

    Note: For proper infrasec authorization (required for BGP_SESSION_CHECK
    and Thrift API access), the device needs Meta-issued certs provisioned
    via the EBB Delegator service. Self-signed certs only provide TLS
    encryption, not authorization.
    TODO: Add a TAAC task that calls the EBB Delegator service
    (nettools.ebb.Delegator) to auto-provision proper Meta-issued certs.

    Args:
        cert_dir: Directory to store certs (default: "/mnt/fb/certs")
        cert_names: List of cert filenames to create (default:
            ["AristaFibAgent_server.pem", "Bgpcpp_server.pem",
             "fb-openr_server.pem"])

    Returns:
        List of shell commands to run on the device via
        run_commands_on_shell task.
    """
    if cert_names is None:
        cert_names = [
            "AristaFibAgent_server.pem",
            "Bgpcpp_server.pem",
            "fb-openr_server.pem",
        ]

    cmds = [f"bash mkdir -p {cert_dir}"]

    # Skip cert generation if valid certs already exist
    # (e.g. manually copied or provisioned by Delegator).
    # Check if the cert file exists and contains a private key.
    # If not, generate a self-signed cert with both key + cert.
    first_cert = f"{cert_dir}/{cert_names[0]}"
    cmds.append(
        f"bash test -f {first_cert} && grep -q 'PRIVATE KEY' {first_cert}"
        f" || openssl req -x509 -newkey rsa:2048"
        f" -keyout {first_cert} -nodes"
        f" -out {first_cert}"
        f" -days 365 -subj '/CN=localhost' 2>/dev/null"
    )

    # Copy to remaining cert names (only if they don't already exist)
    for name in cert_names[1:]:
        target = f"{cert_dir}/{name}"
        cmds.append(
            f"bash test -f {target} && grep -q 'PRIVATE KEY' {target}"
            f" || cp {first_cert} {target}"
        )

    return cmds


def generate_ipv4_secondary_addresses(
    base_network: str, peer_count: int, start_offset: int = 10
) -> List[str]:
    """
    Generate IPv4 secondary addresses for BGP peers.

    Uses proper IPv4 arithmetic via ipaddress module to handle overflow
    past .255 when peer_count exceeds ~122 (e.g., 140 eBGP peers).

    Args:
        base_network: Base network (e.g., "10.163.28")
        peer_count: Number of peers (BGP sessions)
        start_offset: Starting offset for IP addresses (default: 10)

    Returns:
        List of IPv4 addresses with /31 prefix (e.g., ["10.163.28.10/31", "10.163.28.12/31", ...])

    Example:
        >>> generate_ipv4_secondary_addresses("10.163.28", 3)
        ["10.163.28.10/31", "10.163.28.12/31", "10.163.28.14/31"]
        >>> generate_ipv4_secondary_addresses("10.163.28", 140)
        ["10.163.28.10/31", ..., "10.163.28.254/31", "10.163.29.0/31", ..., "10.163.29.32/31"]
    """
    from ipaddress import IPv4Address

    base_ip = IPv4Address(f"{base_network}.{start_offset}")
    addresses = []
    for i in range(peer_count):
        addresses.append(f"{base_ip + (i * 2)}/31")
    return addresses


def generate_ipv6_secondary_addresses(
    base_network: str, peer_count: int, start_offset: int = 0x10
) -> List[str]:
    """
    Generate IPv6 secondary addresses for BGP peers.

    Args:
        base_network: Base network (e.g., "2001:db8:1:1:8")
        peer_count: Number of peers (BGP sessions)
        start_offset: Starting offset for IPv6 addresses (default: 0x10 = 16)

    Returns:
        List of IPv6 addresses with /127 prefix

    Example:
        >>> generate_ipv6_secondary_addresses("2001:db8:1:1:8", 3)
        ["2001:db8:1:1:8::10/127", "2001:db8:1:1:8::12/127", "2001:db8:1:1:8::14/127"]
    """
    addresses = []
    for i in range(peer_count):
        # /127 networks: each peer needs 2 IPs, increment by 2
        ip_offset = start_offset + (i * 2)
        addresses.append(f"{base_network}::{ip_offset:x}/127")
    return addresses


async def configure_interface_secondary_ips(
    driver: t.Any,
    interface: str,
    ipv4_addresses: List[str] | None = None,
    ipv6_addresses: List[str] | None = None,
    clear_existing: bool = True,
    all_secondary: bool = False,
    logger_instance: t.Optional[logging.Logger] = None,
) -> None:
    """
    Configure secondary IP addresses on an Arista interface.

    Args:
        driver: Device driver instance
        interface: Interface name (e.g., "Ethernet3/1/1")
        ipv4_addresses: List of IPv4 addresses to configure (e.g., ["10.163.28.10/31", ...])
        ipv6_addresses: List of IPv6 addresses to configure (e.g., ["2001:db8:1:1:8::10/127", ...])
        clear_existing: If True, clear existing IP addresses before configuring new ones (default: True)
        all_secondary: If True, add ALL IPv4 addresses as secondary (no primary).
            Use this when appending IPs to an interface that already has a primary
            address from a previous call. (default: False)
        logger_instance: Optional logger instance

    Raises:
        ValueError: If configuration fails

    Example:
        >>> await configure_interface_secondary_ips(
        ...     driver,
        ...     "Ethernet3/1/1",
        ...     ipv4_addresses=["10.163.28.10/31", "10.163.28.12/31"],
        ...     ipv6_addresses=["2001:db8:1:1:8::10/127"],
        ... )
    """
    log = logger_instance or logger

    try:
        # Build configuration commands
        commands = [
            f"interface {interface}",
            "no switchport",  # Ensure L3 mode
        ]

        # Clear existing IP addresses if requested
        if clear_existing:
            log.info(f"[ARISTA_UTILS] Clearing existing IP addresses on {interface}")
            commands.extend(
                [
                    "no ip address",  # Remove all IPv4 addresses
                    "no ipv6 address",  # Remove all IPv6 addresses
                ]
            )

        # Add IPv4 addresses
        if ipv4_addresses:
            log.info(
                f"[ARISTA_UTILS] Configuring {len(ipv4_addresses)} IPv4 addresses on {interface}"
            )
            for idx, ipv4 in enumerate(ipv4_addresses):
                if idx == 0 and not all_secondary:
                    commands.append(f"ip address {ipv4}")
                else:
                    commands.append(f"ip address {ipv4} secondary")

        # Add IPv6 addresses
        if ipv6_addresses:
            log.info(
                f"[ARISTA_UTILS] Configuring {len(ipv6_addresses)} IPv6 addresses on {interface}"
            )
            commands.append("ipv6 enable")
            for ipv6 in ipv6_addresses:
                commands.append(f"ipv6 address {ipv6}")

        # Apply configuration
        config_block = "\n".join(commands)
        log.info(f"[ARISTA_UTILS] Applying interface configuration:\n{config_block}")

        await driver.async_run_cmd_on_shell(f"configure\n{config_block}\nend")

        log.info(
            f"[ARISTA_UTILS] Successfully configured IPs on {interface}: "
            f"{len(ipv4_addresses or [])} IPv4, {len(ipv6_addresses or [])} IPv6"
        )

    except Exception as e:
        error_msg = (
            f"[ARISTA_UTILS] Failed to configure secondary IPs on {interface}: {e}"
        )
        log.error(error_msg)
        raise ValueError(error_msg) from e


async def clear_interface_secondary_ips(
    driver: t.Any,
    interface: str,
    ipv4_addresses: t.Optional[List[str]] = None,
    ipv6_addresses: t.Optional[List[str]] = None,
    clear_existing: bool = False,
    all_secondary: bool = False,
    logger_instance: t.Optional[logging.Logger] = None,
) -> None:
    """
    Clear secondary IP addresses on an Arista interface.

    Args:
        driver: Device driver instance
        interface: Interface name (e.g., "Ethernet3/1/1")
        ipv4_addresses: List of IPv4 addresses to clear (e.g., ["10.163.28.10/31", ...])
        ipv6_addresses: List of IPv6 addresses to clear (e.g., ["2001:db8:1:1:8::10/127", ...])
        clear_existing: If True, clear all existing IP addresses (default: False)
            Primary IP address can only be cleared if no secondary IPs remain.
            Hence, clear_existing_ip4 is False by default.
            No `all_secondary` option as all IPv4 to be removed will be secondary.
            If primary is also to be removed, clear_existing_ip4 must be True.
        all_secondary: If True, all IPv4 removed
        logger_instance: Optional logger instance

    Raises:
        ValueError: If configuration fails

    Example:
        >>> await clear_interface_secondary_ips
        ...     driver,
        ...     "Ethernet3/1/1",
        ...     ipv4_addresses=["10.163.28.10/31", "10.163.28.11/31"],
        ...     ipv6_addresses=["2001:db8:1:1:8::10/127"],
        ... )
    """
    log = logger_instance or logger

    ipv4_addresses = ipv4_addresses or []
    ipv6_addresses = ipv6_addresses or []

    if not clear_existing and len(ipv4_addresses) == 0 and len(ipv6_addresses) == 0:
        log.info(f"[ARISTA_UTILS] No IPs to clear on {interface}, exiting")
        return

    try:
        # Build configuration commands
        commands = [
            f"interface {interface}",
            "no switchport",  # Ensure L3 mode
        ]

        if clear_existing:
            log.info(f"[ARISTA_UTILS] Clearing existing IP addresses on {interface}")
            commands.extend(
                [
                    "no ip address",  # Remove all IPv4 addresses
                    "no ipv6 address",  # Remove all IPv6 addresses
                ]
            )
        else:
            if len(ipv6_addresses) > 0:
                log.info(
                    f"[ARISTA_UTILS] Clearing {len(ipv6_addresses)} IPv6 addresses on {interface}"
                )
                for ipv6 in ipv6_addresses:
                    commands.append(f"no ipv6 address {ipv6}")
            if len(ipv4_addresses) > 0:
                if all_secondary:
                    # Clear specific seconday IPv4 addresses
                    log.info(
                        f"[ARISTA_UTILS] Clearing {len(ipv4_addresses)} seconday IPv4 addresses on {interface}"
                    )
                    for ipv4 in ipv4_addresses:
                        commands.append(f"no ip address {ipv4} secondary")
                else:
                    # all ips are secondary, expect the first
                    log.info(
                        f"[ARISTA_UTILS] Clearing {len(ipv4_addresses)} IPv4 addresses on {interface}"
                    )
                    for ipv4 in ipv4_addresses[1:]:
                        commands.append(f"no ip address {ipv4} secondary")
                    commands.append(f"no ip address {ipv4_addresses[0]}")

        # Apply configuration
        config_block = "\n".join(commands)
        log.info(f"[ARISTA_UTILS] Applying interface configuration:\n{config_block}")

        await driver.async_run_cmd_on_shell(f"configure\n{config_block}\nend")

        log.info(
            f"[ARISTA_UTILS] Successfully cleared IPs on {interface}: "
            f"{len(ipv4_addresses or [])} IPv4, {len(ipv6_addresses or [])} IPv6"
        )

    except Exception as e:
        error_msg = f"[ARISTA_UTILS] Failed to clear IPs on {interface}: {e}"
        log.error(error_msg)
        raise ValueError(error_msg) from e


async def save_running_config(
    driver: t.Any,
    backup_name: str | None = None,
    logger_instance: t.Optional[logging.Logger] = None,
) -> str:
    """
    Save the current running configuration to a backup file on the device.

    This is useful for test workflows where you want to restore the device
    to its original state after testing.

    Args:
        driver: Device driver instance
        backup_name: Optional backup filename (without extension)
                     If not provided, generates one with timestamp
        logger_instance: Optional logger instance

    Returns:
        The backup filename used (e.g., "flash:test_backup_20251114_162530")

    Raises:
        ValueError: If backup operation fails

    Example:
        >>> backup_file = await save_running_config(driver)
        >>> # ... perform tests ...
        >>> await restore_running_config(driver, backup_file)
        >>> await delete_backup_config(driver, backup_file)
    """
    log = logger_instance or logger

    if not backup_name:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"taac_backup_{timestamp}"

    backup_file = f"flash:{backup_name}"

    log.info(f"[ARISTA_UTILS] Saving running config to {backup_file}...")

    try:
        # Copy running-config to backup file
        copy_cmd = f"copy running-config {backup_file}"
        await driver.async_run_cmd_on_shell(copy_cmd)

        log.info(f"[ARISTA_UTILS] Successfully saved running config to {backup_file}")
        return backup_file

    except Exception as e:
        error_msg = f"[ARISTA_UTILS] Failed to save running config: {e}"
        log.error(error_msg)
        raise ValueError(error_msg) from e


async def restore_running_config(
    driver: t.Any,
    backup_file: str,
    logger_instance: t.Optional[logging.Logger] = None,
) -> None:
    """
    Restore running configuration from a backup file.

    This uses 'configure replace' which atomically replaces the running
    configuration with the backup.

    Args:
        driver: Device driver instance
        backup_file: Backup filename to restore from (e.g., "flash:backup_config")
        logger_instance: Optional logger instance

    Raises:
        ValueError: If restore operation fails

    Example:
        >>> await restore_running_config(driver, "flash:my_backup")
    """
    log = logger_instance or logger

    log.info(f"[ARISTA_UTILS] Restoring running config from {backup_file}...")

    try:
        # Use configure replace for atomic restore
        restore_cmd = f"configure replace {backup_file}"
        await driver.async_run_cmd_on_shell(restore_cmd)

        log.info(
            f"[ARISTA_UTILS] Successfully restored running config from {backup_file}"
        )

    except Exception as e:
        error_msg = f"[ARISTA_UTILS] Failed to restore running config: {e}"
        log.error(error_msg)
        raise ValueError(error_msg) from e


async def delete_backup_config(
    driver: t.Any,
    backup_file: str,
    logger_instance: t.Optional[logging.Logger] = None,
) -> None:
    """
    Delete a backup configuration file from the device.

    Args:
        driver: Device driver instance
        backup_file: Backup filename to delete (e.g., "flash:backup_config")
        logger_instance: Optional logger instance

    Note:
        This logs a warning if deletion fails but does not raise an exception,
        as cleanup failures are typically not critical.

    Example:
        >>> await delete_backup_config(driver, "flash:old_backup")
    """
    log = logger_instance or logger

    log.info(f"[ARISTA_UTILS] Deleting backup file {backup_file}...")

    try:
        # Delete backup file
        delete_cmd = f"delete {backup_file}"
        await driver.async_run_cmd_on_shell(delete_cmd)

        log.info(f"[ARISTA_UTILS] Successfully deleted backup file {backup_file}")

    except Exception as e:
        # Don't raise - cleanup failures are not critical
        log.warning(f"[ARISTA_UTILS] Failed to delete backup file: {e}")
