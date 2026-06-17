#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

import asyncio
import functools
import ipaddress
import os
import re
from datetime import datetime
from typing import Any, Callable, List, Optional

from taac.driver.driver_constants import (
    DATE_TIME_FORMAT,
    DEFAULT_MEMORIZE_TIME,
    DNE_INFRA_SMC_TIER,
    DNE_LAB_SMC_TIER,
    DNE_REGRESSION_BASSET_POOL_NAME,
    DNE_STANDALONE_SMC_TIER,
    FBOSS_LAB_SMC_TIER,
    IpAddress,
    NET_AI_DSF,
    NET_AI_LAB_REGRESSION_SMC_TIER,
    NET_AI_LAB_SMC_TIER,
)
from taac.utils.oss_taac_lib_utils import (
    ConsoleFileLogger,
    get_root_logger,
    memoize_timed,
    retryable,
    to_fb_fqdn,
    to_fb_fqdn_facebook,
    wraps,
)
from tabulate import tabulate

TAAC_OSS = os.environ.get("TAAC_OSS", "").lower() in ("1", "true", "yes")

if not TAAC_OSS:
    from libfb.py.thrift_clients.smc2_thrift_client import Smc2ThriftClient


class SerfException(Exception):
    pass


class OutputFormatterError(Exception):
    pass


class CommandExecutionError(Exception):
    pass


class EmptyOutputReturnError(Exception):
    pass


class InterfaceNotFoundError(Exception):
    pass


class InvalidInputError(Exception):
    pass


class InvalidIpAddressError(Exception):
    pass


class FcrError(Exception):
    pass


class InvalidVrfError(Exception):
    pass


class TestingException(Exception):
    pass


class BgpPeerNotFoundError(Exception):
    pass


class UnauthorizedDisruptiveEventError(Exception):
    pass


class ConcurrentActionError(Exception):
    pass


class NonCriticalCoreDumpsError(Exception):
    pass


class FbpkgFetchError(Exception):
    pass


class QsfpThriftException(Exception):
    pass


class DomValidationError(Exception):
    pass


class InterfaceStatusError(Exception):
    pass


class BcmNotFoundError(Exception):
    pass


class OnboxDrainerOperationFailed(Exception):
    pass


class MemoryStressFailed(Exception):
    pass


class DrainJobWaitException(Exception):
    pass


class DrainJobFinalFail(Exception):
    pass


class UnexpectedCommandOutput(Exception):
    pass


logger: ConsoleFileLogger = get_root_logger()


def async_custom_retry(
    max_attempts=5, delay_seconds=120, logger: ConsoleFileLogger = logger
):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            for attempt in range(1, max_attempts + 1):
                try:
                    result = await func(*args, **kwargs)
                    logger.debug(
                        f"Function <{func.__name__}> responded in attemp #{attempt}"
                    )
                    return result
                except Exception as e:
                    logger.info(f"Attempt {attempt} failed with error: {e}")
                    if attempt < max_attempts:
                        logger.info(f"Retrying in {delay_seconds} seconds...")
                        await asyncio.sleep(delay_seconds)
                    else:
                        logger.info("Max attempts reached. Giving up.")
                        raise

        return wrapper

    return decorator


def get_ip_address_version(ip_address: str) -> IpAddress:
    """
    Returns whether a given IP address is an IPv4 adddress or IPv6 address
    """
    version: int = ipaddress.ip_address(ip_address).version
    return IpAddress.IPV4 if version == 4 else IpAddress.IPV6


def get_time_diff_unix_epoch_to_current(epoch_time: float):
    """
    Used to return the time difference between the current time and the
    unix epoch time provided in the DATE_TIME_FORMAT
    """
    epoch_time = float(epoch_time)
    event_time = datetime.fromtimestamp(epoch_time).strftime(DATE_TIME_FORMAT)
    current_time = datetime.now().strftime(DATE_TIME_FORMAT)
    diff = datetime.strptime(current_time, DATE_TIME_FORMAT) - datetime.strptime(
        event_time, DATE_TIME_FORMAT
    )
    return diff


def get_tabulated_output(
    raw_output: List[List[Any]], header_fields: List[str], title: str = ""
) -> Optional[str]:
    """
    Used to convert the raw output in a tabular format. The raw output
    needs to be in the form of nested lists.
    """

    column_mismatch = False
    if not raw_output:
        logger.error(
            "Empty output string given for printing the result in tabular format"
        )
        return None

    for row in raw_output:
        if not len(row) == len(header_fields):
            column_mismatch = True
            break

    if column_mismatch:
        raise OutputFormatterError(
            f"Looks like there is a mismatch between the expected and actual "
            f'number of columns in the table data for Title: "{title}" and '
            f"Header: {header_fields}"
        )

    tabulated_output = tabulate(raw_output, headers=header_fields)
    tabulated_data = f"{title}\n{tabulated_output}"
    return tabulated_data


# =============================================================================
# SMC Host Resolution (used by is_dne_test_device)
# =============================================================================


def is_dne_test_ssw_mgmt(basset_hostname: str, smc_hosts: List[str]) -> bool:
    """
    If the hostname is an Arista SSW, validate its "-mgmt" variant
    against the SMC tier hosts list.
    """
    ssw_match = re.search(r"(ssw\d{3}).(s\d{3}.*)", basset_hostname)
    if ssw_match:
        ssw_hostname_mgmt = f"{ssw_match.group(1)}-mgmt.{ssw_match.group(2)}"
        if ssw_hostname_mgmt in smc_hosts:
            return True
    return False


@memoize_timed(DEFAULT_MEMORIZE_TIME)
@retryable(num_tries=3, sleep_time=1, debug=True)
def get_smc_hosts(smc_tier_name: str) -> List[str]:
    """
    Given the SMC tier name, the list of all the hosts in that tier
    will be returned.
    """
    if TAAC_OSS:
        return []

    try:
        with Smc2ThriftClient() as smc_client:
            smc_services = smc_client.getAllChildServices(smc_tier_name, recursive=True)
            smc_hosts = [service.hostname for service in smc_services]
            return smc_hosts
    except Exception as ex:
        raise EmptyOutputReturnError(
            f"Following error occurred while attempting to get the list of hosts "
            f"in the SMC tier '{smc_tier_name}': {ex}"
        )


def is_dne_test_device(func: Callable) -> Callable:
    """
    Gate Keeper that checks if the given host is a DNE test device.

    In OSS mode (TAAC_OSS=1), this decorator is a free pass — all devices
    are assumed to be test devices since there is no SMC tier to validate against.

    In internal mode, validates against SMC tiers to prevent disruptive
    operations on production devices.
    """

    if TAAC_OSS:

        @functools.wraps(func)
        def sync_passthrough(self, *args, **kwargs):
            return func(self, *args, **kwargs)

        @functools.wraps(func)
        async def async_passthrough(self, *args, **kwargs):
            return await func(self, *args, **kwargs)

        return (
            async_passthrough if asyncio.iscoroutinefunction(func) else sync_passthrough
        )

    def validate_dne_smc(self) -> None:
        if TAAC_OSS:
            logger.info(
                "is_dne_test_device: OSS mode — skipping SMC tier validation. "
                "All devices treated as test devices."
            )
            return

        if not hasattr(self, "hostname"):
            raise InvalidInputError(
                f"Invalid object of type {type(self)} used while invoking "
                f"this decorator to check if it is a DNE test device. Expecting "
                f"an object of type Class AbstractSwitch or its derivatives"
            )

        # Pre-production / nano-FPF cluster allowlist. Devices in these
        # clusters are non-customer-facing test gear that the DNE team uses
        # for disruptive integration tests (port flaps, service restarts,
        # NDP flush, etc.). They may not be enrolled in the legacy
        # dne.test/dne.standalone/dne.regression SMC tiers, so we allow
        # them by hostname substring match instead.
        #
        # Examples:
        #   - gtsw00[1-8].l1002.c087.mwg2   (MWG2 nano-FPF DUT pod)
        #   - gtsw00[1-8].l1001.c087.mwg2   (MWG2 nano-FPF remote pod)
        #   - stsw001.s00[1-8].l202.mwg2    (MWG2 nano-FPF spine layer)
        PREPROD_HOSTNAME_SUBSTRINGS = (
            "c087.mwg2",  # MWG2 nano-FPF lab cluster (preprod)
            "c085.ash6",  # ASH6 IcePack NPI lab cluster (preprod) — gtsw001/stsw001 in c085
            ".qzk1",  # BBE-IP RBB lab devices in QZK1 (SNC)
            ".qzd1",  # BBE-IP RBB lab devices in QZD1 (SNC)
        )
        for substr in PREPROD_HOSTNAME_SUBSTRINGS:
            if substr in self.hostname:
                logger.info(
                    f"validate_dne_smc: '{self.hostname}' matches preprod "
                    f"allowlist substring '{substr}' — skipping SMC tier "
                    f"validation. Disruptive operations are permitted on this "
                    f"non-production device."
                )
                return

        smc_tiers = [
            DNE_LAB_SMC_TIER,
            DNE_INFRA_SMC_TIER,
            DNE_STANDALONE_SMC_TIER,
            DNE_REGRESSION_BASSET_POOL_NAME,
            NET_AI_DSF,
            NET_AI_LAB_SMC_TIER,
            NET_AI_LAB_REGRESSION_SMC_TIER,
            FBOSS_LAB_SMC_TIER,
        ]
        dne_test_devices: List[str] = []
        for smc_tier in smc_tiers:
            dne_test_devices.extend(get_smc_hosts(smc_tier))

        dut_hostname_fqdn: str = to_fb_fqdn(self.hostname)
        dut_hostname_fqdn_facebook: str = to_fb_fqdn_facebook(self.hostname)
        if (
            dut_hostname_fqdn not in dne_test_devices
            and dut_hostname_fqdn_facebook not in dne_test_devices
            and self.hostname not in dne_test_devices
            and not is_dne_test_ssw_mgmt(dut_hostname_fqdn, dne_test_devices)
        ):
            raise UnauthorizedDisruptiveEventError(
                f"{dut_hostname_fqdn} is not part of the DNE Test devices "
                f"listed under the '{DNE_LAB_SMC_TIER}',  {DNE_STANDALONE_SMC_TIER},  {DNE_REGRESSION_BASSET_POOL_NAME} or {DNE_LAB_SMC_TIER} SMC tier, "
                f"and does not match any preprod hostname allowlist "
                f"({', '.join(PREPROD_HOSTNAME_SUBSTRINGS)}). This might "
                f"be a production device and hence not allowing {func.__name__}"
            )

    @functools.wraps(func)
    def sync_wrapper(self, *args, **kwargs):
        validate_dne_smc(self)
        return func(self, *args, **kwargs)

    @functools.wraps(func)
    async def async_wrapper(self, *args, **kwargs):
        validate_dne_smc(self)
        return await func(self, *args, **kwargs)

    return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
