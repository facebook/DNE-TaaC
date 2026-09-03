# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""RBB IXIA edge eBGP task — ``/opt/bgpd/bgp.json``-compatible (gates S14/S16-S18).

OSS-safe replacement for the shipped ``configure_ixia_interfaces`` task, which
patches the COOP ``bgpcpp`` config and is incompatible with a box that runs bgpd
from ``/opt/bgpd/bgp.json``. This task edits the DUT's *existing* bgp.json in
place (preserving loopbacks / the core iBGP session / originated networks) to:

* add an eBGP peer toward the IXIA emulated router on the edge port, and
* (tail only) switch on the iBGP v6 AFI so the eBGP-learned v6 pool propagates
  over the core iBGP to the head, optionally re-writing the advertised iBGP v6
  next-hop to the tail SRv6 **decap SID** so the head SRv6-encapsulates toward
  the tail (head→core→tail decap→edge = the proposal's real SRv6 data path).

It can also add the edge L3 RIF to ``/etc/coop/agent.conf`` (live reload) when
the edge SVI has no address yet (the tail port-10 edge), so the eBGP session and
the decapped-inner forwarding have an L3 next-hop.

Fully reversible: every file is backed up to ``<path>.taac-orig`` once before the
first edit; ``action="restore"`` copies the pristine originals back and bounces
bgpd / reloads the agent. Guarded behind the opt-in ``TAAC_RBB_EDGE_EBGP`` flag
at the factory call site; nothing runs unless the task is scheduled.
"""

import json
import typing as t

from taac.constants import TestCaseFailure
from taac.driver.driver_constants import FbossSystemctlServiceName
from taac.tasks.base_task import BaseTask
from taac.tasks.rbb_provision_utils import (
    async_backup_before_overwrite,
    async_read_file_or_none,
    BACKUP_SUFFIX,
)
from taac.testconfigs.routing.util import bgp_rbb_constants as C
from taac.testconfigs.routing.util.fboss_config_gen.bgp_config import (
    add_edge_ebgp_peer,
    enable_ipv6_afi_on_ibgp,
)
from taac.utils.driver_factory import async_get_device_driver
from taac.utils.oss_taac_lib_utils import ConsoleFileLogger

_APPLY = "apply"
_RESTORE = "restore"
# cfg::PortState.ENABLED — a persisted-disabled edge port (state 0) must be
# flipped to this for the SVI/link to come up after the agent reload.
_PORT_ENABLED = 2


class RbbEdgeEbgpTask(BaseTask):
    """Bring up (or restore) DUT-side IXIA edge eBGP by editing bgp.json."""

    # pyrefly: ignore [bad-override-mutable-attribute]
    NAME: str = "rbb_edge_ebgp"

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
        """Apply or restore the DUT-side edge eBGP config.

        params:
            hostname: DUT to configure (required).
            action: "apply" (default) or "restore".
            edge_peer_addr: IXIA emulated-router address (eBGP peer).
            edge_remote_as: IXIA emulated eBGP AS.
            edge_local_addr: DUT edge RIF address (eBGP local address).
            enable_ipv6_afi: turn on the iBGP v6 AFI (tail box; default False).
            ibgp_srv6_nexthop: advertised iBGP v6 next-hop (tail decap SID) so the
                head SRv6-encapsulates toward the tail; optional.
            edge_rif_cidr: edge SVI address to add to agent.conf if missing.
            edge_intf_id: agent.conf interface (SVI) id for the edge port.
            force: re-back-up/overwrite even if a backup already exists.
        """
        hostname = params.get("hostname") or self.hostname
        if not hostname:
            raise ValueError("rbb_edge_ebgp requires 'hostname'")
        action = params.get("action", _APPLY)
        if action not in (_APPLY, _RESTORE):
            raise ValueError(
                f"rbb_edge_ebgp 'action' must be {_APPLY!r} or {_RESTORE!r}, "
                f"got {action!r}"
            )

        driver = await async_get_device_driver(hostname)
        if action == _RESTORE:
            await self._restore(driver, hostname)
            return

        peer_addr = params.get("edge_peer_addr")
        remote_as = params.get("edge_remote_as")
        local_addr = params.get("edge_local_addr")
        if not (peer_addr and remote_as and local_addr):
            raise ValueError(
                "rbb_edge_ebgp apply requires 'edge_peer_addr', 'edge_remote_as', "
                "'edge_local_addr'"
            )
        force = bool(params.get("force", False))

        await self._apply_bgp_json(
            driver,
            hostname,
            peer_addr=str(peer_addr),
            remote_as=int(remote_as),
            local_addr=str(local_addr),
            enable_v6=bool(params.get("enable_ipv6_afi", False)),
            srv6_nexthop=params.get("ibgp_srv6_nexthop"),
            force=force,
        )

        edge_rif_cidr = params.get("edge_rif_cidr")
        edge_intf_id = params.get("edge_intf_id")
        if edge_rif_cidr and edge_intf_id is not None:
            await self._ensure_edge_rif(
                driver,
                hostname,
                int(edge_intf_id),
                str(edge_rif_cidr),
                params.get("edge_port_name"),
                force,
            )

        self.logger.info(
            f"{hostname} -- edge eBGP applied (peer {peer_addr} AS {remote_as}); "
            f"restarting {FbossSystemctlServiceName.BGP.value}"
        )
        await driver.async_restart_service(FbossSystemctlServiceName.BGP)

    async def _apply_bgp_json(
        self,
        driver: t.Any,
        hostname: str,
        *,
        peer_addr: str,
        remote_as: int,
        local_addr: str,
        enable_v6: bool,
        srv6_nexthop: t.Optional[str],
        force: bool,
    ) -> None:
        raw = await async_read_file_or_none(driver, C.BGP_CONFIG_PATH)
        if not raw:
            raise TestCaseFailure(
                f"{hostname}: {C.BGP_CONFIG_PATH} not found; this box does not run "
                f"bgpd from a JSON config — cannot apply edge eBGP."
            )
        try:
            cfg = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise TestCaseFailure(
                f"{hostname}: {C.BGP_CONFIG_PATH} is not valid JSON: {exc}"
            ) from exc

        # Back up the pristine original once (before any edit).
        await async_backup_before_overwrite(
            driver, C.BGP_CONFIG_PATH, self.logger, hostname, force
        )

        if enable_v6 or srv6_nexthop:
            enable_ipv6_afi_on_ibgp(
                cfg,
                ibgp_next_hop6=str(srv6_nexthop) if srv6_nexthop else None,
            )
        add_edge_ebgp_peer(
            cfg,
            peer_addr=peer_addr,
            remote_as=remote_as,
            local_addr=local_addr,
            description=f"IXIA edge eBGP peer {peer_addr} (AS {remote_as})",
        )
        await driver.async_write_file_on_device(
            json.dumps(cfg, indent=2), C.BGP_CONFIG_PATH
        )
        self.logger.info(
            f"{hostname} -- wrote {C.BGP_CONFIG_PATH}: +eBGP peer {peer_addr}"
            + (
                f", iBGP v6 next-hop -> {srv6_nexthop} (SRv6 steer)"
                if srv6_nexthop
                else (", iBGP v6 AFI enabled" if enable_v6 else "")
            )
        )

    async def _ensure_edge_rif(
        self,
        driver: t.Any,
        hostname: str,
        intf_id: int,
        cidr: str,
        port_name: t.Optional[str],
        force: bool,
    ) -> None:
        raw = await async_read_file_or_none(driver, C.AGENT_CONFIG_PATH)
        if not raw:
            raise TestCaseFailure(
                f"{hostname}: {C.AGENT_CONFIG_PATH} not found; cannot add edge RIF."
            )
        cfg = json.loads(raw)
        sw = cfg.get("sw") or {}
        interfaces = sw.get("interfaces") or []
        target = next(
            (i for i in interfaces if i.get("intfID") == intf_id), None
        )
        if target is None:
            raise TestCaseFailure(
                f"{hostname}: no interface intfID={intf_id} in {C.AGENT_CONFIG_PATH}; "
                f"cannot add edge RIF {cidr}."
            )
        addrs = target.setdefault("ipAddresses", [])
        changed = False
        if cidr not in addrs:
            addrs.append(cidr)
            changed = True

        # The edge port may be persisted DISABLED (state 0); the eBGP session and
        # the decapped-inner forwarding need it ENABLED (cfg::PortState.ENABLED=2).
        # Enable it in the same edit so the single reload brings the SVI up.
        if port_name:
            port = next(
                (p for p in (sw.get("ports") or []) if p.get("name") == port_name),
                None,
            )
            if port is not None and port.get("state") != _PORT_ENABLED:
                port["state"] = _PORT_ENABLED
                changed = True
                self.logger.info(
                    f"{hostname} -- enabling edge port {port_name} (state -> ENABLED)"
                )

        if not changed:
            self.logger.info(
                f"{hostname} -- edge RIF {cidr}/port already provisioned; skip"
            )
            return

        await async_backup_before_overwrite(
            driver, C.AGENT_CONFIG_PATH, self.logger, hostname, force
        )
        await driver.async_write_file_on_device(
            json.dumps(cfg, indent=2), C.AGENT_CONFIG_PATH
        )
        self.logger.info(
            f"{hostname} -- edge RIF {cidr} on intf {intf_id} (+port enable); "
            f"reloading agent"
        )
        try:
            await driver.async_agent_config_reload()
        except Exception as reload_exc:  # noqa: BLE001
            self.logger.info(
                f"{hostname} -- reloadConfig failed ({reload_exc}); restarting "
                f"{FbossSystemctlServiceName.FBOSS_SW_AGENT.value}"
            )
            await driver.async_restart_service(
                FbossSystemctlServiceName.FBOSS_SW_AGENT
            )
        await driver.async_wait_for_agent_state_configured()
        self.logger.info(f"{hostname} -- agent CONFIGURED after edge RIF add")

    async def _restore(self, driver: t.Any, hostname: str) -> None:
        """Copy the pristine ``.taac-orig`` originals back and bounce services."""
        restored_agent = False
        for path in (C.BGP_CONFIG_PATH, C.AGENT_CONFIG_PATH):
            backup = path + BACKUP_SUFFIX
            try:
                exists = await driver.async_check_if_file_exists(backup)
            except Exception:  # noqa: BLE001
                exists = False
            if not exists:
                continue
            content = await driver.async_read_file(backup)
            await driver.async_write_file_on_device(content, path)
            self.logger.info(f"{hostname} -- restored {path} from {backup}")
            if path == C.AGENT_CONFIG_PATH:
                restored_agent = True

        if restored_agent:
            try:
                await driver.async_agent_config_reload()
                await driver.async_wait_for_agent_state_configured()
            except Exception as exc:  # noqa: BLE001
                self.logger.info(f"{hostname} -- agent reload on restore: {exc}")
        await driver.async_restart_service(FbossSystemctlServiceName.BGP)
        self.logger.info(f"{hostname} -- edge eBGP restore complete (bgpd bounced)")
