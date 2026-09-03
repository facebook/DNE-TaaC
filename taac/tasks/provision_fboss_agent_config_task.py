# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""Provision ``/etc/coop/agent.conf`` from scratch on a MORGAN800CC DUT.

Generates the cfg::AgentConfig (ports/RIFs/port-channels/SRv6) from the run's
topology + ``TAAC_RBB_*`` plan, sourcing only the immutable board ``platform`` /
``defaultCommandLineArgs`` descriptor from the box, then pushes it and reloads
the agent (falling back to a service restart), waiting for CONFIGURED.

OPT-IN and DISRUPTIVE: only scheduled when ``TAAC_RBB_PROVISION=1``. Backs up the
pristine original to ``/etc/coop/agent.conf.taac-orig`` once, is idempotent
(skips if already provisioned unless ``force``), and hard-fails on non-asicType-15
hardware. An agent reload/restart is traffic-affecting.
"""

import json
import typing as t

from taac.constants import TestCaseFailure
from taac.driver.driver_constants import FbossSystemctlServiceName
from taac.tasks.base_task import BaseTask
from taac.tasks.rbb_provision_utils import (
    async_backup_before_overwrite,
    async_read_file_or_none,
    async_resolve_platform_mapping_path,
    build_node_plan_for_role,
    guard_hardware,
    load_port_map,
)
from taac.testconfigs.routing.util import bgp_rbb_constants as C
from taac.testconfigs.routing.util.fboss_config_gen.agent_config import (
    build_agent_config,
)
from taac.utils.driver_factory import async_get_device_driver
from taac.utils.oss_taac_lib_utils import ConsoleFileLogger


class ProvisionFbossAgentConfigTask(BaseTask):
    """Generate + push ``/etc/coop/agent.conf`` and reload the agent."""

    # pyrefly: ignore [bad-override-mutable-attribute]
    NAME: str = "provision_fboss_agent_config"

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
            role: "r1" | "r2" (required) — selects the per-DUT plan.
            force: re-provision even if a backup already exists (default False).
        """
        hostname = params.get("hostname") or self.hostname
        role = params.get("role")
        force = bool(params.get("force", False))
        if not hostname:
            raise ValueError("provision_fboss_agent_config requires 'hostname'")
        if role not in ("r1", "r2"):
            raise ValueError(
                f"provision_fboss_agent_config 'role' must be 'r1'/'r2', got {role!r}"
            )

        driver = await async_get_device_driver(hostname)

        raw = await async_read_file_or_none(driver, C.AGENT_CONFIG_PATH)
        base_cfg: t.Optional[t.Dict[str, t.Any]] = None
        if raw:
            try:
                base_cfg = json.loads(raw)
            except json.JSONDecodeError:
                base_cfg = None

        # Hardware guard (also confirms we can source the board descriptor).
        await guard_hardware(driver, hostname, self.logger, base_cfg)

        base_sw = (base_cfg or {}).get("sw")
        platform = (base_cfg or {}).get("platform")
        default_cli = (base_cfg or {}).get("defaultCommandLineArgs")
        if platform is None:
            raise TestCaseFailure(
                f"{hostname}: no 'platform' block in {C.AGENT_CONFIG_PATH}; the ASIC "
                f"board descriptor is hardware config that cannot be synthesized."
            )

        mapping_path = await async_resolve_platform_mapping_path(driver)
        port_map = await load_port_map(driver, mapping_path)
        if not port_map:
            raise TestCaseFailure(
                f"{hostname}: platform mapping {mapping_path} is "
                f"unavailable; cannot resolve port identity to build ports."
            )

        plan = build_node_plan_for_role(role, port_map)
        agent_cfg = build_agent_config(
            plan,
            port_map,
            platform=platform,
            default_command_line_args=default_cli,
            base_sw=base_sw,
            asic_type=C.PROVISION_ASIC_TYPE,
        )
        contents = json.dumps(agent_cfg, indent=2)
        self.logger.info(
            f"{hostname} -- generated agent.conf for {role}: "
            f"{len(agent_cfg['sw'].get('ports', []))} ports, "
            f"{len(agent_cfg['sw'].get('interfaces', []))} interfaces, "
            f"{len(agent_cfg['sw'].get('aggregatePorts', []))} port-channels, "
            f"{len(agent_cfg['sw'].get('mySidConfig', {}).get('entries', {}))} SRv6 SIDs"
        )

        proceed = await async_backup_before_overwrite(
            driver, C.AGENT_CONFIG_PATH, self.logger, hostname, force
        )
        if not proceed:
            return

        await driver.async_write_file_on_device(contents, C.AGENT_CONFIG_PATH)
        self.logger.info(f"{hostname} -- wrote {C.AGENT_CONFIG_PATH}; reloading agent")

        try:
            await driver.async_agent_config_reload()
        except Exception as reload_exc:  # noqa: BLE001
            self.logger.info(
                f"{hostname} -- reloadConfig failed ({reload_exc}); restarting "
                f"{FbossSystemctlServiceName.FBOSS_SW_AGENT.value}"
            )
            await driver.async_restart_service(FbossSystemctlServiceName.FBOSS_SW_AGENT)

        try:
            await driver.async_wait_for_agent_state_configured()
        except Exception as exc:  # noqa: BLE001
            raise TestCaseFailure(
                f"{hostname}: agent did not reach CONFIGURED after provisioning "
                f"agent.conf: {exc}"
            ) from exc
        self.logger.info(f"{hostname} -- agent CONFIGURED after provisioning")
