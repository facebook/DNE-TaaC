# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import asyncio
import typing as t

from neteng.test_infra.dne.taac.constants import DNE_LOG_DIR, RSYSLOG_AGENT_FILE
from taac.utils.driver_factory import async_get_device_driver
from taac.utils.oss_taac_lib_utils import (
    ConsoleFileLogger,
    get_root_logger,
)
from taac.test_as_a_config import types as taac_types


LOGGER: ConsoleFileLogger = get_root_logger()


async def async_delete_rsyslog_configuration(
    hostname: str, services: t.List[taac_types.Service]
) -> None:
    """
    Deletes binary log files created via rsyslog at /var/facebook/dne dir on the devices
    Deletes the rsyslog config file created at /etc/rsyslog.d
    Last, restarts rsyslog agent for the configs to take effect.
    """
    driver = await async_get_device_driver(hostname)
    LOGGER.info(f"Deleting {RSYSLOG_AGENT_FILE} from {hostname}, if it exists")
    # pyre-fixme[16]: `AbstractSwitch` has no attribute `async_delete_file`.
    await driver.async_delete_file(RSYSLOG_AGENT_FILE)
    LOGGER.info(f"Restarting rsyslongs on {hostname}")
    await driver.async_run_cmd_on_shell("systemctl restart rsyslog")
    LOGGER.info(f"Deleting service log files from {DNE_LOG_DIR} from all devices")
    tasks = []
    for service in services:
        service_name = taac_types.SERVICE_NAME_MAP[service]
        log_file_name: str = f"{DNE_LOG_DIR}/{service_name}.log"
        # pyrefly: ignore [missing-attribute]
        tasks.append(asyncio.create_task(driver.async_delete_file(log_file_name)))
    await asyncio.gather(*(tasks), return_exceptions=True)


def generate_rsyslog_file_content(services: t.List[taac_types.Service]) -> str:
    """
    Creates rsyslog config file content. Defines the services for which log files need to be created.
    """
    LOGGER.info(f"Creating {DNE_LOG_DIR} on all devices, if not already exists.")
    RSYSLOG_AGENT_FILE_CONTENT: str = ""
    for service in services:
        service_name = taac_types.SERVICE_NAME_MAP[service]
        RSYSLOG_AGENT_FILE_CONTENT += f'if $programname == "{service_name}" then {DNE_LOG_DIR}/{service_name}.log\n'
    return RSYSLOG_AGENT_FILE_CONTENT.strip("\n")


async def async_create_rsyslog_configuration(
    hostname, services: t.List[taac_types.Service]
) -> None:
    """
    Creates /var/facebook/dne dir on the devices, if the directory doesn't already exist.
    Deletes existing log files if they were left from previous runs
    Creates the rsyslog config file at /etc/rsyslog.d and last, restarts rsyslog agent for the configs to take effect.
    """
    RSYSLOG_AGENT_FILE_CONTENT = generate_rsyslog_file_content(services)
    driver = await async_get_device_driver(hostname)
    # pyre-fixme[16]: `AbstractSwitch` has no attribute
    #  `async_create_dir_if_not_exists`.
    await driver.async_create_dir_if_not_exists(DNE_LOG_DIR)
    LOGGER.info(f"Deleting agent log files from {DNE_LOG_DIR} from all devices")
    tasks = []
    for service in services:
        service_name = taac_types.SERVICE_NAME_MAP[service]
        log_file_name: str = f"{DNE_LOG_DIR}/{service_name}.log"
        # pyre-fixme[16]: `AbstractSwitch` has no attribute `async_delete_file`.
        tasks.append(asyncio.create_task(driver.async_delete_file(log_file_name)))
    await asyncio.gather(*(tasks), return_exceptions=True)
    LOGGER.info(f"Creating {RSYSLOG_AGENT_FILE} on {hostname}")
    # pyre-fixme[16]: `AbstractSwitch` has no attribute
    #  `async_create_file_with_content`.
    await driver.async_create_file_with_content(
        RSYSLOG_AGENT_FILE, RSYSLOG_AGENT_FILE_CONTENT
    )
    LOGGER.info(f"Restarting rsyslog on {hostname}")
    await driver.async_run_cmd_on_shell("systemctl restart rsyslog")
