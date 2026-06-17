# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import json
import os
import typing as t

from taac.constants import OS_TO_DEVICE_OS_TYPE_MAP
from taac.driver.abstract_switch import AbstractSwitch
from taac.internal.driver.arista_fboss_switch import (
    AristaFbossSwitch,
)
from taac.internal.driver.arista_switch import AristaSwitch
from taac.internal.driver.cisco_switch import CiscoSwitch
from taac.internal.driver.fboss_switch_internal import (
    FbossSwitchInternal,
)
from taac.utils.oss_taac_lib_utils import (
    async_memoize_timed,
    ConsoleFileLogger,
    get_root_logger,
)
from taac.test_as_a_config import types as taac_types

LOGGER: ConsoleFileLogger = get_root_logger()
TAAC_OSS = os.environ.get("TAAC_OSS", "").lower() in ("1", "true", "yes")

DEVICE_OS_DRIVER_CLASS_MAP = {
    taac_types.DeviceOsType.FBOSS: FbossSwitchInternal,
    taac_types.DeviceOsType.ARISTA_OS: AristaSwitch,
    taac_types.DeviceOsType.CISCO: CiscoSwitch,
    taac_types.DeviceOsType.IOSXR: CiscoSwitch,
    taac_types.DeviceOsType.ARISTA_FBOSS: AristaFbossSwitch,
}

HOST_TO_DEVICE_OS_TYPE_MAP = {}
HOST_TO_DRIVER_ARGS_MAP = {}


def add_host_to_device_os_type_data(
    hostname: str, device_os_type: taac_types.DeviceOsType
) -> None:
    HOST_TO_DEVICE_OS_TYPE_MAP[hostname] = device_os_type


def add_host_to_driver_args_data(
    hostname: str, driver_args: t.Dict[str, t.Any]
) -> None:
    HOST_TO_DRIVER_ARGS_MAP[hostname] = driver_args


@async_memoize_timed(3600)
async def async_get_device_driver(
    hostname: str, logger: t.Optional[ConsoleFileLogger] = None
) -> AbstractSwitch:
    """
    Given a hostname, return the corresponding driver.
    In OSS mode, requires host_os_type_map to be pre-populated.
    In internal mode, falls back to fbnet/netwhoami for OS detection.
    """
    device_os_type = HOST_TO_DEVICE_OS_TYPE_MAP.get(hostname)
    if not device_os_type:
        if TAAC_OSS:
            from taac.oss_topology_info.device_info_loader import (
                get_operating_system_from_hostname_oss,
            )

            os_name = get_operating_system_from_hostname_oss(hostname)
            if os_name and os_name in OS_TO_DEVICE_OS_TYPE_MAP:
                device_os_type = OS_TO_DEVICE_OS_TYPE_MAP[os_name]
            else:
                raise ValueError(
                    f"Cannot determine device OS type for '{hostname}' in OSS mode. "
                    f"Ensure host_os_type_map is set or device_info.csv has the OS. "
                    f"Got os_name='{os_name}'"
                )
        else:
            from taac.internal.netwhoami_utils import fetch_whoami
            from taac.utils.skynet_utils import (
                async_get_device_name,
                async_get_vendor_info_from_fbnet,
            )

            try:
                standard_hostname = await async_get_device_name(hostname)
                if not standard_hostname:
                    raise Exception(f"Unable to fetch standard hostname for {hostname}")
                vendor_name = await async_get_vendor_info_from_fbnet(standard_hostname)
                if not vendor_name:
                    raise Exception(
                        f"Vendor info for {hostname} not available in fbnet"
                    )
                device_os_type = OS_TO_DEVICE_OS_TYPE_MAP[vendor_name]
            except Exception:
                netwhoami = await fetch_whoami(hostname)
                LOGGER.debug(
                    f"Net os type for {hostname} is {netwhoami.operating_system}"
                )
                os_name = (
                    netwhoami.operating_system.name
                    if netwhoami.operating_system
                    else None
                )
                # pyrefly: ignore [bad-argument-type]
                device_os_type = OS_TO_DEVICE_OS_TYPE_MAP.get(os_name)
                if device_os_type is None:
                    raise ValueError(
                        f"Cannot determine device OS type for '{hostname}'. "
                        f"netwhoami returned os_name={os_name!r}. "
                        f"Use add_host_to_device_os_type_data() to pre-register."
                    )

    LOGGER.debug(f"device os type for {hostname} is {device_os_type.name}")
    driver_class = DEVICE_OS_DRIVER_CLASS_MAP[device_os_type]
    # pyrefly: ignore [bad-argument-type]
    driver_args_dict = json.loads(HOST_TO_DRIVER_ARGS_MAP.get(hostname, "{}"))
    device_driver_class = driver_class(
        hostname, logger=logger or LOGGER, **driver_args_dict
    )
    return device_driver_class
