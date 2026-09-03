# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""RBB SRv6 programming task.

Programs the SRv6 locator, uSIDs, and tunnels on one DUT for the RBB SRv6
qualification (gates S08-S11 / S13). Command content is scenario-supplied via
``cmds`` so the exact device syntax lives in
``taac/testconfigs/routing/util/bgp_rbb_scenario_profiles.py``.
"""

import typing as t

from taac.tasks.base_task import BaseTask
from taac.utils.driver_factory import async_get_device_driver
from taac.utils.oss_taac_lib_utils import ConsoleFileLogger


class RbbSrv6ProgramTask(BaseTask):
    """Program SRv6 locator + uSIDs + tunnels on one DUT."""

    # pyrefly: ignore [bad-override-mutable-attribute]
    NAME: str = "rbb_srv6_program"

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
        """Program SRv6 state.

        params:
            hostname: DUT to program (required).
            cmds: ordered list of SRv6 CLI commands (required).
        """
        hostname = params.get("hostname") or self.hostname
        if not hostname:
            raise ValueError("rbb_srv6_program requires 'hostname'")
        cmds: t.List[str] = params.get("cmds", [])
        if not cmds:
            self.logger.info(f"{hostname} -- rbb_srv6_program: no cmds supplied")
            return

        driver = await async_get_device_driver(hostname)
        self.logger.info(f"{hostname} -- programming SRv6 ({len(cmds)} cmds)")
        for cmd in cmds:
            self.logger.info(f"{hostname} -- srv6: {cmd}")
            await driver.async_run_cmd_on_shell(cmd)
