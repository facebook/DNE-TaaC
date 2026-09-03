# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""RBB core-underlay interface setup task.

Applies the two-node underlay device configuration for the RBB SRv6
qualification: the PC161 / PC162 core port-channels between R1 and R2 plus any
loopback / core-IP configuration the scenario supplies.

This is a thin, factory-built ``BaseTask`` (§5.1 / §5.4 of the OSS onboarding
guide): the concrete CLI is supplied by the caller as ``cmds`` (built by
``taac/testconfigs/routing/util/bgp_rbb_scenario_profiles.py``) so the exact
device syntax stays with the scenario rather than hard-coded in the task.
"""

import typing as t

from taac.tasks.base_task import BaseTask
from taac.utils.driver_factory import async_get_device_driver
from taac.utils.oss_taac_lib_utils import ConsoleFileLogger


class RbbCoreInterfaceSetupTask(BaseTask):
    """Configure the RBB core underlay (PC161/PC162 + loopbacks) on one DUT."""

    # pyrefly: ignore [bad-override-mutable-attribute]
    NAME: str = "rbb_core_interface_setup"

    def __init__(
        self,
        hostname: t.Optional[str] = None,
        description: t.Optional[str] = None,
        ixia: t.Optional[t.Any] = None,
        logger: t.Optional[ConsoleFileLogger] = None,
        shared_data: t.Optional[t.Dict[t.Any, t.Any]] = None,
    ) -> None:
        super().__init__(hostname, description, ixia, logger, shared_data)

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        """Apply the underlay config.

        params:
            hostname: DUT to configure (required).
            cmds: ordered list of CLI commands to apply (required).
        """
        hostname = params.get("hostname") or self.hostname
        if not hostname:
            raise ValueError("rbb_core_interface_setup requires 'hostname'")
        cmds: t.List[str] = params.get("cmds", [])
        if not cmds:
            self.logger.info(f"{hostname} -- rbb_core_interface_setup: no cmds supplied")
            return

        driver = await async_get_device_driver(hostname)
        self.logger.info(f"{hostname} -- RBB core interface setup ({len(cmds)} cmds)")
        for cmd in cmds:
            self.logger.info(f"{hostname} -- apply: {cmd}")
            await driver.async_run_cmd_on_shell(cmd)
