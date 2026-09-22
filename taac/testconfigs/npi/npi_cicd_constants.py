# Copyright (c) Meta Platforms, Inc. and affiliates.

"""Shared CI/CD device and runtime profiles for NPI qualification."""

NPI_CICD_DUT_NAMES: frozenset[str] = frozenset(
    {
        "fsw004.p003.f01.qzd1",
        "fsw004.p004.f01.qzd1",
        "rsw001.p001.f01.qzd1",
    }
)

NPI_CICD_THRIFT_DURATION_S = 600
NPI_CICD_THRIFT_RESTART_DURATION_S = 480
NPI_CICD_THRIFT_RESTART_PERIOD_S = 240
NPI_CICD_THRIFT_REQUESTS_PER_BURST = 100
NPI_CICD_REBOOT_ITERATIONS = 1


def is_npi_cicd_dut(device_name: str) -> bool:
    """Match both short and fully-qualified lab hostnames."""
    return device_name.lower().removesuffix(".tfbnw.net") in NPI_CICD_DUT_NAMES
