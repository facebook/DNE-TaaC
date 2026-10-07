# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-strict

import calendar
import re
import time
import typing as t
from datetime import datetime, timezone


def check_regex_patterns(
    log_content: str, include_regex: t.Optional[str], exclude_regex: t.Optional[str]
) -> t.Tuple[bool, t.List[str]]:
    """
    Apply include/exclude regex filtering to log content.

    Returns (success, matching_lines) tuple.
    For include_regex: success=True if lines match, matching_lines contains matches
    For exclude_regex: success=True if no lines match, matching_lines contains matches if any
    """
    regex = include_regex or exclude_regex
    if not regex:
        return True, []

    matching_lines = [
        line for line in log_content.splitlines() if re.search(regex, line)
    ]

    if include_regex:
        # Success if we found matches
        return len(matching_lines) > 0, matching_lines
    else:
        # Success if we found no matches (exclude worked)
        return len(matching_lines) == 0, matching_lines


def check_error_patterns(log_content: str) -> t.List[str]:
    """
    Check for default error patterns in log content.

    Returns list of lines containing error patterns.
    """
    error_patterns = [
        r"\bERROR\b",
        r"\bWARN\b",
        r"\bFATAL\b",
        r"\bException\b",
        r"\bError\b",
        r"\bFailed\b",
        r"\bFailure\b",
    ]
    combined_pattern = "|".join(error_patterns)

    return [
        line
        for line in log_content.splitlines()
        if re.search(combined_pattern, line, re.IGNORECASE)
    ]


def format_time_range(start_time: t.Optional[int], end_time: t.Optional[int]) -> str:
    """
    Format time range for success messages.

    Rendered in UTC and labeled, so the range can be compared directly with
    the UTC timestamps on the device log lines it summarizes.
    """
    if start_time and end_time:
        start_str = time.strftime("%H:%M:%S", time.gmtime(start_time))
        end_str = time.strftime("%H:%M:%S", time.gmtime(end_time))
        return f" from {start_str} to {end_str} UTC"
    return ""


def filter_agent_logs_by_time(content: str, start_time: int, end_time: int) -> str:
    """
    Filter agent logs by timestamp range.

    Agent logs use format: E0930 10:07:24.282159 (Level+MMDD HH:MM:SS.microseconds)
    This format is used by BGP, FIB, and other agent logs. Device log timestamps
    are UTC; start_time and end_time are Unix epochs.
    """
    current_year = time.gmtime().tm_year
    filtered_lines = []

    for line in content.splitlines():
        if is_agent_log_line_in_time_range(line, start_time, end_time, current_year):
            filtered_lines.append(line)

    return "\n".join(filtered_lines)


def is_agent_log_line_in_time_range(
    line: str, start_time: int, end_time: int, current_year: int
) -> bool:
    """
    Check if an Arista daemon log line timestamp falls within the given time range.

    Arista daemon log format: E0930 10:07:24.282159 (Level+MMDD HH:MM:SS.microseconds)
    This format is used by BGP, FIB, and other Arista daemons.
    Returns True for non-timestamp lines (safer to include than exclude).

    The line timestamp is interpreted as UTC because devices log in UTC. Using
    the host's local time instead shifts every line by the host's UTC offset,
    which on a non-UTC devserver pushes all lines outside the test window and
    makes callers silently check nothing.
    """
    try:
        # log format: E0930 10:07:24.282159
        if len(line) < 15 or not line[0].isalpha() or line[5] != " ":
            return True  # Include non-timestamp lines

        # Extract timestamp components
        month_day = line[1:5]  # "0930"
        time_part = line[6:14]  # "10:07:24"

        if len(month_day) != 4 or not month_day.isdigit():
            return True

        if len(time_part) != 8 or time_part[2] != ":" or time_part[5] != ":":
            return True

        # Parse components
        month = int(month_day[:2])
        day = int(month_day[2:4])
        hour = int(time_part[:2])
        minute = int(time_part[3:5])
        second = int(time_part[6:8])

        start_year = time.gmtime(start_time).tm_year
        end_year = time.gmtime(end_time).tm_year
        candidate_years = set(range(start_year, end_year + 1))
        candidate_years.add(current_year)
        return any(
            start_time
            <= calendar.timegm((year, month, day, hour, minute, second, 0, 0, 0))
            <= end_time
            for year in candidate_years
        )

    except (ValueError, IndexError):
        # If parsing fails, include the line (safer)
        return True


def is_eos_system_log_line_in_time_range(
    line: str, start_time: int, end_time: int
) -> bool:
    """
    Check if an EOS system log line timestamp falls within the given time range.

    EOS system log formats:
    - Sep 13 13:12:45 (MMM DD HH:MM:SS)
    - 2025 Sep 13 13:15:46 (YYYY MMM DD HH:MM:SS)

    Returns True for non-timestamp lines (safer to include than exclude).

    The line timestamp is interpreted as UTC because devices log in UTC; a
    naive local-time parse shifts every line by the host's UTC offset and
    silently filters out the whole test window. Lines without a year are
    tried against every year the window touches, so a window spanning New
    Year still matches.
    """

    try:
        line_strip = line.strip()
        if not line_strip:
            return True

        # Use regex to extract timestamp patterns
        # Pattern 1: YYYY MMM DD HH:MM:SS
        pattern_with_year = r"^(\d{4})\s+(\w{3})\s+(\d{1,2})\s+(\d{1,2}:\d{2}:\d{2})"
        # Pattern 2: MMM DD HH:MM:SS
        pattern_without_year = r"^(\w{3})\s+(\d{1,2})\s+(\d{1,2}:\d{2}:\d{2})"

        match_with_year = re.match(pattern_with_year, line_strip)
        match_without_year = re.match(pattern_without_year, line_strip)

        if match_with_year:
            year, month, day, time_str = match_with_year.groups()
            candidate_years = {int(year)}
        elif match_without_year:
            month, day, time_str = match_without_year.groups()
            candidate_years = set(
                range(
                    time.gmtime(start_time).tm_year, time.gmtime(end_time).tm_year + 1
                )
            )
            candidate_years.add(time.gmtime().tm_year)
        else:
            return True  # Non-timestamp line, include it

        for candidate_year in candidate_years:
            # strptime handles month names; the result is pinned to UTC.
            dt = datetime.strptime(
                f"{candidate_year} {month} {day} {time_str}", "%Y %b %d %H:%M:%S"
            ).replace(tzinfo=timezone.utc)
            if start_time <= dt.timestamp() <= end_time:
                return True
        return False

    except (ValueError, AttributeError):
        # If parsing fails, include the line (safer)
        return True
