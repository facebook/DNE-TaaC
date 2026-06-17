# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
import asyncio
import typing as t

from taac.custom_test_handlers.base_custom_test_handler import (
    BaseCustomTestHandler,
)
from taac.driver.driver_constants import FbossSystemctlServiceName
from taac.utils.driver_factory import async_get_device_driver
from taac.utils.oss_taac_lib_utils import ConsoleFileLogger

COOP_CONFIG_NAMES: t.Set[str] = {"agent", "bgpcpp", "bgpcpp_drain", "bgpcpp_softdrain"}


class PatcherCleanupHelper:
    def __init__(
        self, hostnames: t.List[str], logger: ConsoleFileLogger, *args, **kwargs
    ) -> None:
        super().__init__(*args, **kwargs)
        self.hostnames = hostnames
        self.initial_patchers = {}
        self.current_patchers = {}
        self.logger = logger

    async def get_registered_patchers(self, hostname: str) -> dict:
        driver = await async_get_device_driver(hostname)
        patchers = await asyncio.gather(
            # pyre-fixme[16]: `AbstractSwitch` has no attribute
            #  `async_coop_list_patchers`.
            *[driver.async_coop_list_patchers(config) for config in COOP_CONFIG_NAMES]
        )
        return dict(zip(COOP_CONFIG_NAMES, patchers))

    async def initiate_cleanup(self) -> None:
        await asyncio.gather(
            *[self._cleanup_patchers(hostname) for hostname in self.hostnames]
        )

    async def _cleanup_patchers(self, hostname: str) -> None:
        initial = self.initial_patchers.get(hostname, {})
        current = self.current_patchers.get(hostname, {})
        driver = await async_get_device_driver(hostname)
        remove_tasks = []
        for config, current_list in current.items():
            initial_list = initial.get(config, [])
            new_patchers = set(current_list) - set(initial_list)
            remove_tasks.extend(
                driver.async_coop_unregister_patchers(patcher.name, config)
                for patcher in new_patchers
            )
        if remove_tasks:
            self.logger.debug(f"Removing {len(remove_tasks)} patchers for {hostname}")
            await asyncio.gather(*remove_tasks)
            await driver.async_restart_service(FbossSystemctlServiceName.AGENT)
            await driver.async_wait_for_agent_configured()
        else:
            self.logger.debug(f"No patchers to remove for {hostname}")

    async def set_initial_registered_patchers(self) -> None:
        patchers = await asyncio.gather(
            *(self.get_registered_patchers(hostname) for hostname in self.hostnames)
        )
        self.logger.debug(f"Initial patchers: {patchers}")
        self.initial_patchers = dict(zip(self.hostnames, patchers))

    async def set_current_registered_patchers(self) -> None:
        patchers = await asyncio.gather(
            *(self.get_registered_patchers(hostname) for hostname in self.hostnames)
        )
        self.logger.debug(f"Current patchers: {patchers}")
        self.current_patchers = dict(zip(self.hostnames, patchers))


class PatcherCleanupHandler(BaseCustomTestHandler):
    """Cleanup patchers on FBOSS devices after test cases"""

    SUPPORTED_TAGS = ["patcher-cleanup"]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fboss_devices = [
            device.name
            for device in self.test_topology.devices
            if device.attributes.operating_system == "FBOSS"
        ]
        self.test_case_patcher_cleanup_helper = ...

    async def async_test_case_setUp(self) -> None:
        # pyrefly: ignore [bad-assignment]
        self.test_case_patcher_cleanup_helper = PatcherCleanupHelper(
            self.fboss_devices, self.logger
        )
        # pyrefly: ignore [missing-attribute]
        await self.test_case_patcher_cleanup_helper.set_initial_registered_patchers()

    async def async_test_case_tearDown(self) -> None:
        # pyrefly: ignore [missing-attribute]
        await self.test_case_patcher_cleanup_helper.set_current_registered_patchers()
        # pyrefly: ignore [missing-attribute]
        await self.test_case_patcher_cleanup_helper.initiate_cleanup()
