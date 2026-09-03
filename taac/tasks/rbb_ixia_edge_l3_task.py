# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""RBB IXIA-facing L3 edge enable task.

Enables the DUT-side IXIA-facing L3 interfaces and eBGP toward the traffic
generator (gate S12). Runs after IXIA setup (``ixia_needed=True`` at the
factory call site). Command content is scenario-supplied.
"""

import typing as t

from taac.tasks.base_task import BaseTask
from taac.utils.driver_factory import async_get_device_driver
from taac.utils.oss_taac_lib_utils import ConsoleFileLogger


class RbbIxiaEdgeL3Task(BaseTask):
    """Enable IXIA-facing L3 + eBGP on one DUT."""

    # pyrefly: ignore [bad-override-mutable-attribute]
    NAME: str = "rbb_ixia_edge_l3"

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
        """Enable the IXIA-facing edge.

        params:
            hostname: DUT to configure (required).
            cmds: ordered list of CLI commands (required).
        """
        hostname = params.get("hostname") or self.hostname
        if not hostname:
            raise ValueError("rbb_ixia_edge_l3 requires 'hostname'")
        cmds: t.List[str] = params.get("cmds", [])
        if not cmds:
            self.logger.info(f"{hostname} -- rbb_ixia_edge_l3: no cmds supplied")
            return

        driver = await async_get_device_driver(hostname)
        self.logger.info(f"{hostname} -- IXIA edge L3 enable ({len(cmds)} cmds)")
        for cmd in cmds:
            self.logger.info(f"{hostname} -- edge: {cmd}")
            await driver.async_run_cmd_on_shell(cmd)
