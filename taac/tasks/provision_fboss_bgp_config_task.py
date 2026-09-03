# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""Provision ``/opt/bgpd/bgp.json`` (+ ``policy.json``) from scratch and restart bgpd.

Generates the FBOSS bgpd config for the RBB iBGP loopback session from the
per-DUT plan (local AS, router-id=loopback v4, next-hop-self peer group, the
far-DUT loopback peer, originated networks), pushes it plus an empty policy, and
restarts bgpd.

OPT-IN (``TAAC_RBB_PROVISION=1``) and DISRUPTIVE (bgpd restart drops iBGP).
Backs up the pristine originals once; idempotent unless ``force``; asicType-15
guarded.
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
from taac.testconfigs.routing.util.fboss_config_gen.bgp_config import (
    build_bgp_config,
    build_policy_config,
)
from taac.utils.driver_factory import async_get_device_driver
from taac.utils.oss_taac_lib_utils import ConsoleFileLogger


class ProvisionFbossBgpConfigTask(BaseTask):
    """Generate + push ``/opt/bgpd/bgp.json`` + ``policy.json`` and restart bgpd."""

    # pyrefly: ignore [bad-override-mutable-attribute]
    NAME: str = "provision_fboss_bgp_config"

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
            role: "r1" | "r2" (required).
            force: re-provision even if a backup exists (default False).
        """
        hostname = params.get("hostname") or self.hostname
        role = params.get("role")
        force = bool(params.get("force", False))
        if not hostname:
            raise ValueError("provision_fboss_bgp_config requires 'hostname'")
        if role not in ("r1", "r2"):
            raise ValueError(
                f"provision_fboss_bgp_config 'role' must be 'r1'/'r2', got {role!r}"
            )

        driver = await async_get_device_driver(hostname)
        await guard_hardware(driver, hostname, self.logger)

        plan = build_node_plan_for_role(role)
        bgp_cfg = build_bgp_config(
            local_as=plan.local_as,
            router_id=plan.router_id,
            loopback_v4=plan.loopback_v4,
            loopback_v6=plan.loopback_v6,
            peer_loopback_v4=plan.peer_loopback_v4,
            networks4=plan.networks4,
            networks6=plan.networks6,
            peer_description=(
                f"iBGP loopback peer {plan.peer_loopback_v4} (AS {plan.local_as})"
            ),
        )
        bgp_contents = json.dumps(bgp_cfg, indent=2)
        policy_contents = json.dumps(build_policy_config(), indent=2)
        self.logger.info(
            f"{hostname} -- generated bgp.json for {role}: AS {plan.local_as}, "
            f"router-id {plan.router_id}, peer {plan.peer_loopback_v4}, "
            f"{len(bgp_cfg['networks4'])}x v4 + {len(bgp_cfg['networks6'])}x v6 networks"
        )

        proceed = await async_backup_before_overwrite(
            driver, C.BGP_CONFIG_PATH, self.logger, hostname, force
        )
        if not proceed:
            return

        # Keep policy.json in lockstep with bgp.json (back it up too).
        await async_backup_before_overwrite(
            driver, C.BGP_POLICY_PATH, self.logger, hostname, force
        )
        await driver.async_write_file_on_device(bgp_contents, C.BGP_CONFIG_PATH)
        await driver.async_write_file_on_device(policy_contents, C.BGP_POLICY_PATH)
        self.logger.info(
            f"{hostname} -- wrote {C.BGP_CONFIG_PATH} + {C.BGP_POLICY_PATH}; "
            f"restarting {FbossSystemctlServiceName.BGP.value}"
        )
        await driver.async_restart_service(FbossSystemctlServiceName.BGP)
        self.logger.info(f"{hostname} -- bgpd restarted after provisioning")
