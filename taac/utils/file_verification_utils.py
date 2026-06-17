# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""
Utilities for file verification operations.

This module contains shared logic for verifying file modification times
that can be used by both Steps and HealthChecks.
"""

import logging
import typing as t
from dataclasses import dataclass


@dataclass
class FileVerificationResult:
    """Result of a file verification operation."""

    def __init__(self, success: bool, message: str):
        self.success = success
        self.message = message


async def verify_file_modification_time(
    driver: t.Any,
    file_path: str,
    expected_last_mod_time: int,
    logger: logging.Logger,
) -> FileVerificationResult:
    """
    Verify that a file's modification time meets the expected threshold.

    This function checks if a file exists and validates that the elapsed time
    since its last modification is greater than or equal to the expected time.

    Args:
        driver: Driver object that provides async_run_cmd_on_shell method
        file_path: Path to the file to check modification time
        expected_last_mod_time: Expected modification time in seconds. The check will
            pass if elapsed_time_since_modified >= expected_last_mod_time
        logger: Logger instance for logging messages

    Returns:
        FileVerificationResult with success status and descriptive message
    """
    # Check if file exists using ls -la
    try:
        check_cmd = f'bash ls -la "{file_path}"'
        file_check = await driver.async_run_cmd_on_shell(check_cmd)
        if not file_check or "No such file" in file_check:
            return FileVerificationResult(
                success=False, message=f"File {file_path} does not exist"
            )
    except Exception as e:
        logger.warning(f"Could not verify file existence: {e}")
        return FileVerificationResult(
            success=False,
            message=f"Could not verify file {file_path} existence: {e}",
        )

    # Get file modification time in seconds since epoch
    mod_time_cmd = f"bash stat -c %Y {file_path}"
    mod_time_result = await driver.async_run_cmd_on_shell(mod_time_cmd)

    try:
        # Parse the last non-empty line from the output
        lines = [
            line.strip() for line in mod_time_result.strip().split("\n") if line.strip()
        ]
        file_mod_time = int(lines[-1])
    except (ValueError, IndexError) as e:
        return FileVerificationResult(
            success=False,
            message=f"Could not get modification time for file {file_path}: {e}",
        )

    logger.info(f"File {file_path} modification time: {file_mod_time}")

    # Get current epoch time on device
    current_time_cmd = "bash date +%s"
    current_time_result = await driver.async_run_cmd_on_shell(current_time_cmd)

    try:
        # Parse the last non-empty line from the output
        lines = [
            line.strip()
            for line in current_time_result.strip().split("\n")
            if line.strip()
        ]
        current_time = int(lines[-1])
        logger.info(f"Current device time: {current_time}")
    except (ValueError, IndexError) as e:
        return FileVerificationResult(
            success=False, message=f"Could not get current time from device: {e}"
        )

    elapsed_time_since_modified = current_time - file_mod_time

    if elapsed_time_since_modified < expected_last_mod_time:
        return FileVerificationResult(
            success=False,
            message=f"File {file_path} was modified {elapsed_time_since_modified}s ago, less than expected {expected_last_mod_time}s",
        )

    logger.info(
        f"File {file_path} modification time {elapsed_time_since_modified}s is greater than or equal to expected {expected_last_mod_time}s"
    )

    return FileVerificationResult(
        success=True,
        message=f"File {file_path} modification time verification passed. Elasped time since modified {elapsed_time_since_modified}",
    )
