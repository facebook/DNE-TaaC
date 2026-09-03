# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""Provision ``/opt/openr/openr.conf`` from scratch and restart OpenR.

Generates the OpenR config (node_name = DUT role, domain ``fboss``, area 0
adjacencies over ``^fboss[0-9]+$`` core interfaces, redistribute the loopback,
fib_port 5909) and restarts openr so loopback reachability is established for the
iBGP session.

OPT-IN (``TAAC_RBB_PROVISION=1``) and DISRUPTIVE (openr restart reconverges the
IGP). Backs up the pristine original once; idempotent unless ``force``;
asicType-15 guarded.
"""

import json
import typing as t

from taac.driver.driver_constants import FbossSystemctlServiceName
from taac.tasks.base_task import BaseTask
from taac.tasks.rbb_provision_utils import (
    async_backup_before_overwrite,
    build_node_plan_for_role,
    guard_hardware,
)
from taac.testconfigs.routing.util import bgp_rbb_constants as C
from taac.testconfigs.routing.util.fboss_config_gen.openr_config import (
    build_openr_config,
)
from taac.utils.driver_factory import async_get_device_driver
from taac.utils.oss_taac_lib_utils import ConsoleFileLogger


class ProvisionFbossOpenrConfigTask(BaseTask):
    """Generate + push ``/opt/openr/openr.conf`` and restart OpenR."""

    # pyrefly: ignore [bad-override-mutable-attribute]
    NAME: str = "provision_fboss_openr_config"

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
        """
        params:
            hostname: DUT to provision (required).
            role: "r1" | "r2" (required) — becomes openr node_name.
            force: re-provision even if a backup exists (default False).
        """
        hostname = params.get("hostname") or self.hostname
        role = params.get("role")
        force = bool(params.get("force", False))
        if not hostname:
            raise ValueError("provision_fboss_openr_config requires 'hostname'")
        if role not in ("r1", "r2"):
            raise ValueError(
                f"provision_fboss_openr_config 'role' must be 'r1'/'r2', got {role!r}"
            )

        driver = await async_get_device_driver(hostname)
        await guard_hardware(driver, hostname, self.logger)

        openr_cfg = build_openr_config(node_name=role)
        contents = json.dumps(openr_cfg, indent=2)
        self.logger.info(
            f"{hostname} -- generated openr.conf for {role}: node_name={role}, "
            f"domain={openr_cfg['domain']}, area={openr_cfg['areas'][0]['area_id']}"
        )

        proceed = await async_backup_before_overwrite(
            driver, C.OPENR_CONFIG_PATH, self.logger, hostname, force
        )
        if not proceed:
            return

        await driver.async_write_file_on_device(contents, C.OPENR_CONFIG_PATH)
        self.logger.info(
            f"{hostname} -- wrote {C.OPENR_CONFIG_PATH}; restarting "
            f"{FbossSystemctlServiceName.OPENR.value}"
        )
        await driver.async_restart_service(FbossSystemctlServiceName.OPENR)
        self.logger.info(f"{hostname} -- openr restarted after provisioning")
