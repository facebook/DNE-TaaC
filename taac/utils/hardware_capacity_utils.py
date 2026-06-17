# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""
Hardware capacity utilities for network device health checks.

This module provides utilities for checking hardware capacity on Arista devices,
specifically focusing on FEC and ECMP resource utilization.
"""

import typing as t
from dataclasses import dataclass

from taac.health_checks.constants import (
    ARISTA_DEFAULT_CHECK_WATERMARKS,
    ARISTA_DEFAULT_ECMP_THRESHOLD,
    ARISTA_DEFAULT_FEC_THRESHOLD,
    ARISTA_DEFAULT_MAX_ECMP_LEVEL1,
    ARISTA_DEFAULT_MAX_ECMP_LEVEL2,
    ARISTA_DEFAULT_MAX_ECMP_LEVEL3,
    ARISTA_DEFAULT_WATERMARK_DELTA_THRESHOLD,
)
from taac.utils.oss_taac_lib_utils import (
    ConsoleFileLogger,
    get_root_logger,
)

LOGGER: ConsoleFileLogger = get_root_logger()


@dataclass
class HardwareCapacityData:
    """Represents hardware capacity data for FEC and ECMP objects"""

    fec_used: int = 0
    fec_max: int = 0
    fec_high_watermark: int = 0
    ecmp_used: int = 0
    ecmp_max: int = 0
    ecmp_high_watermark: int = 0
    ecmp_level1_used: int = 0
    ecmp_level2_used: int = 0
    ecmp_level3_used: int = 0


class HardwareCapacityThresholds:
    """Hardware capacity threshold configuration"""

    def __init__(
        self,
        fec_threshold: int = ARISTA_DEFAULT_FEC_THRESHOLD,
        ecmp_threshold: int = ARISTA_DEFAULT_ECMP_THRESHOLD,
        max_ecmp_level1: int = ARISTA_DEFAULT_MAX_ECMP_LEVEL1,
        max_ecmp_level2: int = ARISTA_DEFAULT_MAX_ECMP_LEVEL2,
        max_ecmp_level3: int = ARISTA_DEFAULT_MAX_ECMP_LEVEL3,
        watermark_delta_threshold: int = ARISTA_DEFAULT_WATERMARK_DELTA_THRESHOLD,
        check_watermarks: bool = ARISTA_DEFAULT_CHECK_WATERMARKS,
    ):
        self.fec_threshold = fec_threshold
        self.ecmp_threshold = ecmp_threshold
        self.max_ecmp_level1 = max_ecmp_level1
        self.max_ecmp_level2 = max_ecmp_level2
        self.max_ecmp_level3 = max_ecmp_level3
        self.watermark_delta_threshold = watermark_delta_threshold
        self.check_watermarks = check_watermarks

    @classmethod
    def from_dict(cls, params: t.Dict[str, t.Any]) -> "HardwareCapacityThresholds":
        """Create HardwareCapacityThresholds from a parameter dictionary"""
        return cls(
            fec_threshold=params.get("fec_threshold", ARISTA_DEFAULT_FEC_THRESHOLD),
            ecmp_threshold=params.get("ecmp_threshold", ARISTA_DEFAULT_ECMP_THRESHOLD),
            max_ecmp_level1=params.get(
                "max_ecmp_level1", ARISTA_DEFAULT_MAX_ECMP_LEVEL1
            ),
            max_ecmp_level2=params.get(
                "max_ecmp_level2", ARISTA_DEFAULT_MAX_ECMP_LEVEL2
            ),
            max_ecmp_level3=params.get(
                "max_ecmp_level3", ARISTA_DEFAULT_MAX_ECMP_LEVEL3
            ),
            watermark_delta_threshold=params.get(
                "watermark_delta_threshold", ARISTA_DEFAULT_WATERMARK_DELTA_THRESHOLD
            ),
            check_watermarks=params.get(
                "check_watermarks", ARISTA_DEFAULT_CHECK_WATERMARKS
            ),
        )


@dataclass
class HardwareCapacityResult:
    """Result of hardware capacity validation"""

    passed: bool
    errors: t.List[str]
    warnings: t.List[str]
    capacity_data: HardwareCapacityData
    summary: str

    def get_message(self) -> str:
        """Get formatted message for health check result"""
        message = self.summary
        if self.errors:
            message += "\n\nErrors:\n" + "\n".join(self.errors)
        if self.warnings:
            message += "\n\nWarnings:\n" + "\n".join(self.warnings)
        return message


async def get_hardware_capacity_data(driver) -> HardwareCapacityData:
    """
    Get hardware capacity data from network device using show hardware capacity command.

    This function currently supports Arista EOS devices. For FBOSS devices, it would need
    a different command/API approach.

    Args:
        driver: Device driver with async_execute_show_or_configure_cmd_on_shell method

    Returns:
        HardwareCapacityData: Parsed hardware capacity information

    Raises:
        Exception: If command fails or parsing fails

    """
    cmd = "show hardware capacity | grep -i 'ECMP\\|Fec'"
    response = await driver.async_execute_show_or_configure_cmd_on_shell(cmd)

    if not response:
        raise Exception("No hardware capacity data returned from command")

    LOGGER.debug("Hardware capacity command output: %s", response)

    # Parse the output to extract FEC and ECMP data
    capacity_data = HardwareCapacityData()

    # Split response into lines and process each line
    lines = response.strip().split("\n")

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Simple parsing based on actual format:
        # [0]Table [1]Feature/Chip [2]Used [3]Used% [4]Free [5]Committed [6]Max [7]High_watermark
        columns = line.split()

        if len(columns) < 8:
            continue

        resource_name = columns[0].lower()

        try:
            used = int(columns[2])  # Used Entries
            max_val = int(columns[6])  # Max Entries
            high_watermark = int(columns[7])  # High Watermark
        except (ValueError, IndexError):
            continue

        # Parse entries based on resource name
        if resource_name == "fec":
            capacity_data.fec_used = used
            capacity_data.fec_max = max_val
            capacity_data.fec_high_watermark = high_watermark
        elif resource_name == "ecmplevel1":
            capacity_data.ecmp_level1_used = max(capacity_data.ecmp_level1_used, used)
        elif resource_name == "ecmplevel2":
            capacity_data.ecmp_level2_used = max(capacity_data.ecmp_level2_used, used)
        elif resource_name == "ecmplevel3":
            capacity_data.ecmp_level3_used = max(capacity_data.ecmp_level3_used, used)
        elif resource_name == "ecmp":
            capacity_data.ecmp_used = used
            capacity_data.ecmp_max = max_val
            capacity_data.ecmp_high_watermark = high_watermark

    LOGGER.debug("Parsed capacity data: %s", capacity_data)
    return capacity_data


def validate_hardware_capacity(
    capacity_data: HardwareCapacityData,
    thresholds: HardwareCapacityThresholds,
) -> HardwareCapacityResult:
    """
    Validate hardware capacity data against specified thresholds.

    Args:
        capacity_data: Hardware capacity data to validate
        thresholds: Threshold configuration for validation

    Returns:
        HardwareCapacityResult: Validation results including errors, warnings, and summary
    """
    errors = []
    warnings = []

    # Check FEC usage
    if capacity_data.fec_used > thresholds.fec_threshold:
        errors.append(
            f"FEC usage ({capacity_data.fec_used}) exceeds threshold ({thresholds.fec_threshold})"
        )

    # Check ECMP usage
    if capacity_data.ecmp_used > thresholds.ecmp_threshold:
        errors.append(
            f"ECMP usage ({capacity_data.ecmp_used}) exceeds threshold ({thresholds.ecmp_threshold})"
        )

    # Check ECMP level constraints
    if capacity_data.ecmp_level3_used > thresholds.max_ecmp_level3:
        errors.append(
            f"EcmpLevel3 objects ({capacity_data.ecmp_level3_used}) exceeds maximum allowed ({thresholds.max_ecmp_level3})"
        )

    if capacity_data.ecmp_level1_used > thresholds.max_ecmp_level1:
        errors.append(
            f"EcmpLevel1 objects ({capacity_data.ecmp_level1_used}) exceeds maximum allowed ({thresholds.max_ecmp_level1})"
        )

    if capacity_data.ecmp_level2_used > thresholds.max_ecmp_level2:
        errors.append(
            f"EcmpLevel2 objects ({capacity_data.ecmp_level2_used}) exceeds maximum allowed ({thresholds.max_ecmp_level2})"
        )

    # Check high watermarks if enabled
    if thresholds.check_watermarks:
        fec_watermark_delta = abs(
            capacity_data.fec_high_watermark - capacity_data.fec_used
        )
        if fec_watermark_delta > thresholds.watermark_delta_threshold:
            errors.append(
                f"FEC high watermark delta ({fec_watermark_delta}) exceeds threshold ({thresholds.watermark_delta_threshold}). "
                f"Current: {capacity_data.fec_used}, High watermark: {capacity_data.fec_high_watermark}. "
                "Device needs to be reloaded to reset watermark counters before testing."
            )

        ecmp_watermark_delta = abs(
            capacity_data.ecmp_high_watermark - capacity_data.ecmp_used
        )
        if ecmp_watermark_delta > thresholds.watermark_delta_threshold:
            errors.append(
                f"ECMP high watermark delta ({ecmp_watermark_delta}) exceeds threshold ({thresholds.watermark_delta_threshold}). "
                f"Current: {capacity_data.ecmp_used}, High watermark: {capacity_data.ecmp_high_watermark}. "
                "Device needs to be reloaded to reset watermark counters before testing."
            )

    # Prepare result summary
    capacity_summary = (
        f"Hardware capacity summary:\n"
        f"FEC: {capacity_data.fec_used}/{capacity_data.fec_max} (high watermark: {capacity_data.fec_high_watermark})\n"
        f"ECMP: {capacity_data.ecmp_used}/{capacity_data.ecmp_max} (high watermark: {capacity_data.ecmp_high_watermark})\n"
        f"EcmpLevel1: {capacity_data.ecmp_level1_used}\n"
        f"EcmpLevel2: {capacity_data.ecmp_level2_used}\n"
        f"EcmpLevel3: {capacity_data.ecmp_level3_used}"
    )

    return HardwareCapacityResult(
        passed=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        capacity_data=capacity_data,
        summary=capacity_summary,
    )


async def check_hardware_capacity(
    driver,
    thresholds: t.Optional[HardwareCapacityThresholds] = None,
) -> HardwareCapacityResult:
    """
    Complete hardware capacity check for network devices.

    This is a convenience function that combines data retrieval and validation.
    Currently supports Arista EOS devices.

    Args:
        driver: Device driver with async_execute_show_or_configure_cmd_on_shell method
        thresholds: Optional threshold configuration. Uses defaults if not provided.

    Returns:
        HardwareCapacityResult: Complete validation results

    Raises:
        Exception: If hardware capacity data cannot be retrieved

    """
    if thresholds is None:
        thresholds = HardwareCapacityThresholds()

    capacity_data = await get_hardware_capacity_data(driver)
    return validate_hardware_capacity(capacity_data, thresholds)


# Convenience functions for common threshold scenarios


def get_startup_thresholds() -> HardwareCapacityThresholds:
    """Get conservative thresholds for startup/baseline checks"""
    return HardwareCapacityThresholds(
        fec_threshold=5000,  # Lower baseline
        ecmp_threshold=500,
        max_ecmp_level1=3,
        max_ecmp_level2=200,
        max_ecmp_level3=0,
        watermark_delta_threshold=50,
        check_watermarks=True,
    )


def get_precheck_thresholds() -> HardwareCapacityThresholds:
    """Get standard thresholds for pre-test checks"""
    return HardwareCapacityThresholds(
        fec_threshold=10000,  # 10K for pre-check
        ecmp_threshold=1000,
        max_ecmp_level1=5,
        max_ecmp_level2=500,
        max_ecmp_level3=0,
        watermark_delta_threshold=100,
        check_watermarks=False,
    )


def get_postcheck_thresholds() -> HardwareCapacityThresholds:
    """Get higher thresholds for post-test checks"""
    return HardwareCapacityThresholds(
        fec_threshold=20000,  # 20K for post-check
        ecmp_threshold=1000,
        max_ecmp_level1=5,
        max_ecmp_level2=500,
        max_ecmp_level3=0,
        watermark_delta_threshold=100,
        check_watermarks=True,
    )
