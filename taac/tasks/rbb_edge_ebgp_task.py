# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""RBB IXIA edge eBGP task — ``/opt/bgpd/bgp.json``-compatible (gates S14/S16-S18).

OSS-safe replacement for the shipped ``configure_ixia_interfaces`` task, which
patches the COOP ``bgpcpp`` config and is incompatible with a box that runs bgpd
from ``/opt/bgpd/bgp.json``. This task edits the DUT's *existing* bgp.json in
place (preserving loopbacks / the core iBGP session / originated networks) to:

* add an eBGP peer toward the IXIA emulated router on the edge port, and
* switch on the iBGP v6 AFI so the eBGP-learned v6 pools propagate across the
  core, and optionally set an explicit advertised iBGP v6 next-hop. R1 uses its
  routed v6 loopback for the ordinary return path; R2 uses its SRv6 **decap
  SID**, which supplies recursive underlay resolution for the head. The S21
  TE_AGENT route's explicit ``srv6SegmentList`` is what makes FBOSS encapsulate
  the inner packet.

It can also add the edge L3 RIF to ``/etc/coop/agent.conf`` (live reload) when
the selected edge SVI has no address yet, so the eBGP session and
the decapped-inner forwarding have an L3 next-hop.

Fully reversible: every file is backed up to ``<path>.taac-rbb-edge-orig`` before the
first edit; ``action="restore"`` copies the pristine originals back and bounces
bgpd / reloads the agent. Guarded behind the opt-in ``TAAC_RBB_EDGE_EBGP`` flag
at the factory call site; nothing runs unless the task is scheduled.
"""

import ipaddress
import json
import typing as t

from taac.constants import TestCaseFailure
from taac.driver.driver_constants import FbossSystemctlServiceName
from taac.tasks.base_task import BaseTask
from taac.tasks.rbb_edge_config_utils import (
    async_apply_backup_metadata,
    async_backup_before_overwrite,
    async_discard_backup,
    async_guard_snapshot_set,
    async_read_file_or_none,
    async_restore_backup,
    async_write_json_file,
    EDGE_BACKUP_SUFFIX,
)
from taac.testconfigs.routing.util import bgp_rbb_constants as C
from taac.testconfigs.routing.util.bgp_rbb_bootstrap_config import (
    validate_bootstrap_device_paths,
)
from taac.testconfigs.routing.util.bgp_rbb_edge_config import (
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
            enable_ipv6_afi: turn on the iBGP v6 AFI (default False).
            ibgp_peer_addr: exact core iBGP peer whose group may be changed.
            ibgp_srv6_nexthop: advertised iBGP v6 next-hop (a routed loopback,
                or the tail decap SID for SRv6 recursion); optional.
            edge_rif_cidr: edge SVI address to add to agent.conf if missing.
            edge_intf_id: optional AgentConfig SVI id; by default it is derived
                from ``edge_port_name``'s ``ingressVlan``.
            force: preserve an existing recovery snapshot and intentionally
                reapply; without it a stale snapshot blocks mutation.
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
        validate_bootstrap_device_paths(
            (C.AGENT_CONFIG_PATH, C.BGP_CONFIG_PATH)
        )

        driver = await async_get_device_driver(hostname)
        await self._require_root(driver, hostname)
        if action == _RESTORE:
            await self._restore(driver, hostname)
            return
        await self._require_active_services(driver, hostname)

        peer_addr = params.get("edge_peer_addr")
        remote_as = params.get("edge_remote_as")
        local_addr = params.get("edge_local_addr")
        if not (peer_addr and remote_as and local_addr):
            raise ValueError(
                "rbb_edge_ebgp apply requires 'edge_peer_addr', 'edge_remote_as', "
                "'edge_local_addr'"
            )
        force = params.get("force", False)
        if not isinstance(force, bool):
            raise ValueError("rbb_edge_ebgp force must be a JSON boolean")
        enable_v6 = params.get("enable_ipv6_afi", False)
        if not isinstance(enable_v6, bool):
            raise ValueError(
                "rbb_edge_ebgp enable_ipv6_afi must be a JSON boolean"
            )
        try:
            peer_ip = ipaddress.ip_address(str(peer_addr))
            local_ip = ipaddress.ip_address(str(local_addr))
        except ValueError as exc:
            raise ValueError(
                f"rbb_edge_ebgp requires valid peer/local IPs: {exc}"
            ) from exc
        if peer_ip.version != local_ip.version:
            raise ValueError("rbb_edge_ebgp peer/local addresses must use one family")
        if peer_ip.version != 6:
            raise ValueError("rbb_edge_ebgp peer/local addresses must use IPv6")
        if peer_ip == local_ip:
            raise ValueError("rbb_edge_ebgp peer/local addresses must differ")
        try:
            if isinstance(remote_as, bool):
                raise ValueError
            remote_as_value = int(remote_as)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "rbb_edge_ebgp edge_remote_as must be an integer"
            ) from exc
        if not 1 <= remote_as_value <= 0xFFFFFFFF:
            raise ValueError("rbb_edge_ebgp edge_remote_as must be 1..4294967295")
        srv6_nexthop = params.get("ibgp_srv6_nexthop")
        ibgp_peer_addr = params.get("ibgp_peer_addr")
        if (enable_v6 or srv6_nexthop) and not ibgp_peer_addr:
            raise ValueError(
                "rbb_edge_ebgp requires 'ibgp_peer_addr' when changing the "
                "iBGP IPv6 configuration"
            )
        if ibgp_peer_addr:
            try:
                ipaddress.ip_address(str(ibgp_peer_addr))
            except ValueError as exc:
                raise ValueError(
                    f"rbb_edge_ebgp invalid ibgp_peer_addr: {exc}"
                ) from exc
        if srv6_nexthop:
            try:
                if ipaddress.ip_address(str(srv6_nexthop)).version != 6:
                    raise ValueError("SRv6 next-hop is not IPv6")
            except ValueError as exc:
                raise ValueError(
                    f"rbb_edge_ebgp invalid ibgp_srv6_nexthop: {exc}"
                ) from exc

        edge_rif_cidr = params.get("edge_rif_cidr")
        if edge_rif_cidr:
            try:
                edge_interface = ipaddress.ip_interface(str(edge_rif_cidr))
            except ValueError as exc:
                raise ValueError(
                    f"rbb_edge_ebgp invalid edge_rif_cidr: {exc}"
                ) from exc
            if edge_interface.ip != local_ip:
                raise ValueError(
                    "rbb_edge_ebgp edge_rif_cidr address must equal edge_local_addr"
                )
            if peer_ip not in edge_interface.network:
                raise ValueError(
                    "rbb_edge_ebgp edge peer and local RIF must share a subnet"
                )

        bgp_cfg, bgp_changed = await self._prepare_bgp_json(
            driver,
            hostname,
            peer_addr=str(peer_addr),
            remote_as=remote_as_value,
            local_addr=str(local_addr),
            enable_v6=enable_v6,
            srv6_nexthop=str(srv6_nexthop) if srv6_nexthop else None,
            ibgp_peer_addr=str(ibgp_peer_addr) if ibgp_peer_addr else None,
        )

        agent_cfg: t.Optional[t.Dict[str, t.Any]] = None
        agent_changed = False
        if edge_rif_cidr:
            agent_cfg, agent_changed = await self._prepare_edge_rif(
                driver,
                hostname,
                str(edge_rif_cidr),
                params.get("edge_port_name"),
                (
                    int(params["edge_intf_id"])
                    if params.get("edge_intf_id") is not None
                    else None
                ),
            )

        if bgp_changed or (agent_changed and agent_cfg is not None):
            # Both documents are patched minimally, but still validate each
            # changed result against this runtime's exact schema before a
            # recovery snapshot or live write.
            from configerator.structs.neteng.fboss.bgp.bgp_config.thrift_types import (
                BgpConfig,
            )
            from neteng.fboss.switch_config.thrift_types import SwitchConfig
            from taac.utils.json_thrift_utils import json_to_thrift

            try:
                if bgp_changed:
                    json_to_thrift(json.dumps(bgp_cfg), BgpConfig)
                if agent_changed and agent_cfg is not None:
                    json_to_thrift(json.dumps(agent_cfg["sw"]), SwitchConfig)
            except Exception as exc:  # noqa: BLE001
                raise TestCaseFailure(
                    f"{hostname}: generated edge config does not match the "
                    f"bundled FBOSS/BGP Thrift schema: {exc}"
                ) from exc

        # Check every document in scope before the idempotent return. Existing
        # edge-only snapshots mean a previous apply was not restored yet and
        # must remain visible to the operator.
        scoped_paths = [C.BGP_CONFIG_PATH]
        if edge_rif_cidr:
            scoped_paths.append(C.AGENT_CONFIG_PATH)
        await async_guard_snapshot_set(
            driver,
            scoped_paths,
            hostname,
            force,
            backup_suffix=EDGE_BACKUP_SUFFIX,
        )
        if not bgp_changed and not agent_changed:
            self.logger.info(f"{hostname} -- edge eBGP/RIF config already active")
            return

        # Both documents are parsed and transformed before the first snapshot
        # or write.  Agent/RIF comes first, then BGP, matching TAAC's normal
        # underlay-before-routing setup order.
        snapshot_paths = []
        if agent_changed:
            snapshot_paths.append(C.AGENT_CONFIG_PATH)
        if bgp_changed:
            snapshot_paths.append(C.BGP_CONFIG_PATH)
        created_snapshots: t.List[str] = []
        try:
            for path in snapshot_paths:
                if await async_backup_before_overwrite(
                    driver,
                    path,
                    self.logger,
                    hostname,
                    force,
                    backup_suffix=EDGE_BACKUP_SUFFIX,
                ):
                    created_snapshots.append(path)
        except Exception:
            # Parsing completed and no live file has changed yet. Remove only
            # this attempt's partial snapshot set.
            for path in created_snapshots:
                await async_discard_backup(
                    driver, path, backup_suffix=EDGE_BACKUP_SUFFIX
                )
            raise

        try:
            if agent_changed and agent_cfg is not None:
                await async_write_json_file(
                    driver, C.AGENT_CONFIG_PATH, agent_cfg, hostname=hostname
                )
                await async_apply_backup_metadata(
                    driver,
                    C.AGENT_CONFIG_PATH,
                    hostname,
                    backup_suffix=EDGE_BACKUP_SUFFIX,
                )
                try:
                    await driver.async_agent_config_reload()
                except Exception as reload_exc:  # noqa: BLE001
                    self.logger.info(
                        f"{hostname} -- reloadConfig failed ({reload_exc}); "
                        f"restarting {FbossSystemctlServiceName.FBOSS_SW_AGENT.value}"
                    )
                    await driver.async_restart_service(
                        FbossSystemctlServiceName.FBOSS_SW_AGENT
                    )
                await driver.async_wait_for_agent_state_configured()
            if bgp_changed:
                await async_write_json_file(
                    driver, C.BGP_CONFIG_PATH, bgp_cfg, hostname=hostname
                )
                await async_apply_backup_metadata(
                    driver,
                    C.BGP_CONFIG_PATH,
                    hostname,
                    backup_suffix=EDGE_BACKUP_SUFFIX,
                )
                await driver.async_restart_service(FbossSystemctlServiceName.BGP)
        except Exception as exc:  # noqa: BLE001
            try:
                await self._restore(driver, hostname)
            except Exception as rollback_exc:  # noqa: BLE001
                raise TestCaseFailure(
                    f"{hostname}: edge config apply failed ({exc}); automatic "
                    f"rollback also failed ({rollback_exc})"
                ) from exc
            raise TestCaseFailure(
                f"{hostname}: edge config apply failed and was rolled back: {exc}"
            ) from exc

        self.logger.info(
            f"{hostname} -- edge eBGP applied (peer {peer_addr} AS {remote_as})"
        )

    @staticmethod
    async def _require_root(driver: t.Any, hostname: str) -> None:
        uid = str(await driver.async_run_cmd_on_shell("id -u") or "").strip()
        if uid != "0":
            raise TestCaseFailure(
                f"{hostname}: --setup-dut-edges requires a root SSH account; "
                f"the remote session reported uid {uid or 'unknown'}"
            )

    @staticmethod
    async def _require_active_services(driver: t.Any, hostname: str) -> None:
        """Fail before mutation unless the overlay can preserve active state."""
        for service in (
            FbossSystemctlServiceName.FBOSS_SW_AGENT,
            FbossSystemctlServiceName.BGP,
        ):
            output = await driver.async_run_cmd_on_shell(
                f"systemctl show {service.value} "
                "--property=LoadState --property=ActiveState"
            )
            fields = {}
            for line in str(output or "").splitlines():
                if "=" in line:
                    key, value = line.split("=", 1)
                    fields[key.strip()] = value.strip()
            if fields.get("LoadState") != "loaded" or fields.get("ActiveState") != "active":
                raise TestCaseFailure(
                    f"{hostname}: --setup-dut-edges requires {service.value} to "
                    "already be loaded and active; use --setup-duts for a fresh "
                    "image"
                )

    async def _prepare_bgp_json(
        self,
        driver: t.Any,
        hostname: str,
        *,
        peer_addr: str,
        remote_as: int,
        local_addr: str,
        enable_v6: bool,
        srv6_nexthop: t.Optional[str],
        ibgp_peer_addr: t.Optional[str],
    ) -> t.Tuple[t.Dict[str, t.Any], bool]:
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

        before = json.loads(json.dumps(cfg))
        if enable_v6 or srv6_nexthop:
            enable_ipv6_afi_on_ibgp(
                cfg,
                ibgp_next_hop6=str(srv6_nexthop) if srv6_nexthop else None,
                ibgp_peer_addr=ibgp_peer_addr,
            )
        add_edge_ebgp_peer(
            cfg,
            peer_addr=peer_addr,
            remote_as=remote_as,
            local_addr=local_addr,
            description=f"IXIA edge eBGP peer {peer_addr} (AS {remote_as})",
        )
        return cfg, cfg != before

    async def _prepare_edge_rif(
        self,
        driver: t.Any,
        hostname: str,
        cidr: str,
        port_name: t.Optional[str],
        intf_id: t.Optional[int],
    ) -> t.Tuple[t.Dict[str, t.Any], bool]:
        raw = await async_read_file_or_none(driver, C.AGENT_CONFIG_PATH)
        if not raw:
            raise TestCaseFailure(
                f"{hostname}: {C.AGENT_CONFIG_PATH} not found; cannot add edge RIF."
            )
        try:
            cfg = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise TestCaseFailure(
                f"{hostname}: {C.AGENT_CONFIG_PATH} is not valid JSON: {exc}"
            ) from exc
        try:
            requested_interface = ipaddress.ip_interface(cidr)
        except ValueError as exc:
            raise TestCaseFailure(
                f"{hostname}: invalid edge RIF CIDR {cidr!r}"
            ) from exc
        sw = cfg.get("sw")
        if not isinstance(sw, dict):
            raise TestCaseFailure(
                f"{hostname}: {C.AGENT_CONFIG_PATH} must contain a sw object"
            )
        if not port_name:
            raise TestCaseFailure(
                f"{hostname}: edge_port_name is required to resolve the edge RIF"
            )
        ports = sw.get("ports")
        if not isinstance(ports, list) or any(
            not isinstance(candidate, dict) for candidate in ports
        ):
            raise TestCaseFailure(
                f"{hostname}: {C.AGENT_CONFIG_PATH} sw.ports must be a list of objects"
            )
        matching_ports = [
            candidate
            for candidate in ports
            if candidate.get("name") == str(port_name)
        ]
        if len(matching_ports) != 1:
            raise TestCaseFailure(
                f"{hostname}: edge port {port_name!r} must occur exactly once in "
                f"{C.AGENT_CONFIG_PATH}; CSV interface names must use the "
                "device's exact spelling"
            )
        port = matching_ports[0]
        if (
            not isinstance(port.get("portType"), int)
            or isinstance(port.get("portType"), bool)
            or port.get("portType") != 0  # cfg::PortType.INTERFACE_PORT
            or port.get("routable") is not True
        ):
            raise TestCaseFailure(
                f"{hostname}: edge port {port_name!r} must be a routable FBOSS "
                "INTERFACE_PORT"
            )
        try:
            port_id = int(port["logicalID"])
            port_intf_id = int(port["ingressVlan"])
        except (KeyError, TypeError, ValueError) as exc:
            raise TestCaseFailure(
                f"{hostname}: edge port {port_name!r} has no usable logicalID/"
                "ingressVlan; "
                "cannot derive its RIF"
            ) from exc
        if intf_id is None:
            intf_id = port_intf_id
        elif intf_id != port_intf_id:
            raise TestCaseFailure(
                f"{hostname}: requested edge RIF {intf_id} does not match "
                f"{port_name!r} ingressVlan {port_intf_id}"
            )
        if not 1 <= intf_id <= 4094:
            raise TestCaseFailure(
                f"{hostname}: edge port {port_name!r} has invalid ingress VLAN {intf_id}"
            )
        try:
            vlan_owner_count = sum(
                int(candidate.get("ingressVlan", -1)) == intf_id
                for candidate in ports
            )
        except (TypeError, ValueError) as exc:
            raise TestCaseFailure(
                f"{hostname}: AgentConfig contains an invalid ingressVlan"
            ) from exc
        if vlan_owner_count != 1:
            raise TestCaseFailure(
                f"{hostname}: edge VLAN {intf_id} is shared by multiple ports; "
                "refusing to alter an operator-owned L2 segment"
            )
        interfaces = sw.get("interfaces")
        vlans = sw.get("vlans")
        vlan_ports = sw.get("vlanPorts")
        if not all(isinstance(items, list) for items in (interfaces, vlans, vlan_ports)):
            raise TestCaseFailure(
                f"{hostname}: AgentConfig interfaces/vlans/vlanPorts must be lists"
            )
        if any(
            not isinstance(item, dict)
            for items in (interfaces, vlans, vlan_ports)
            for item in items
        ):
            raise TestCaseFailure(
                f"{hostname}: AgentConfig interfaces/vlans/vlanPorts contain "
                "an invalid entry"
            )
        matching_interfaces = [
            item for item in interfaces if item.get("intfID") == intf_id
        ]
        matching_vlans = [item for item in vlans if item.get("id") == intf_id]
        matching_vlan_ports = [
            item for item in vlan_ports if item.get("vlanID") == intf_id
        ]
        if (
            len(matching_interfaces) != 1
            or matching_interfaces[0].get("vlanID") != intf_id
            or len(matching_vlans) != 1
            or len(matching_vlan_ports) != 1
            or matching_vlan_ports[0].get("logicalPort") != port_id
        ):
            raise TestCaseFailure(
                f"{hostname}: edge port {port_name!r} needs one exclusive matching "
                f"VLAN/interface/vlanPorts entry for VLAN {intf_id}"
            )
        target = matching_interfaces[0]
        vlan = matching_vlans[0]
        interface_addrs = target.get("ipAddresses")
        vlan_addrs = vlan.get("ipAddresses")
        if not isinstance(interface_addrs, list) or not isinstance(vlan_addrs, list):
            raise TestCaseFailure(
                f"{hostname}: edge VLAN/interface {intf_id} ipAddresses must be lists"
            )
        try:
            existing_interface_addrs = {
                ipaddress.ip_interface(str(address)) for address in interface_addrs
            }
            existing_vlan_addrs = {
                ipaddress.ip_interface(str(address)) for address in vlan_addrs
            }
        except ValueError as exc:
            raise TestCaseFailure(
                f"{hostname}: VLAN/interface {intf_id} contains an invalid IP address"
            ) from exc
        changed = False
        requested_present = (
            requested_interface in existing_interface_addrs
            or requested_interface in existing_vlan_addrs
        )
        if requested_present:
            # A valid preconfigured FBOSS RIF can carry additional addresses
            # (for example IPv4 + IPv6) on sw.interfaces while the matching
            # sw.vlans ipAddresses list stays empty. Preserve both operator-
            # owned lists verbatim when the exact requested RIF already exists.
            self.logger.info(
                f"{hostname} -- edge RIF {cidr} already present; preserving "
                "existing interface/VLAN addresses"
            )
        elif existing_interface_addrs or existing_vlan_addrs:
            raise TestCaseFailure(
                f"{hostname}: edge VLAN/interface {intf_id} already has operator-owned "
                "addresses but not the requested IXIA RIF; refusing to merge it"
            )
        else:
            # The stock image keeps routed addresses on sw.interfaces; its
            # corresponding sw.vlans address list remains empty.
            interface_addrs.append(cidr)
            changed = True

        # The edge port may be persisted DISABLED (state 0); the eBGP session and
        # the decapped-inner forwarding need it ENABLED (cfg::PortState.ENABLED=2).
        # Enable it in the same edit so the single reload brings the SVI up.
        port_state = port.get("state")
        if (
            not isinstance(port_state, int)
            or isinstance(port_state, bool)
            or port_state not in (0, 1, _PORT_ENABLED)
        ):
            raise TestCaseFailure(
                f"{hostname}: edge port {port_name!r} has unsupported state {port_state!r}"
            )
        if port_state != _PORT_ENABLED:
            port["state"] = _PORT_ENABLED
            changed = True
            self.logger.info(
                f"{hostname} -- enabling edge port {port_name} (state -> ENABLED)"
            )

        return cfg, changed

    async def _restore(self, driver: t.Any, hostname: str) -> None:
        """Restore and consume edge-only snapshots, then bounce changed services."""
        restored_agent = False
        restored_bgp = False
        for path in (C.BGP_CONFIG_PATH, C.AGENT_CONFIG_PATH):
            restored = await async_restore_backup(
                driver,
                path,
                self.logger,
                hostname,
                backup_suffix=EDGE_BACKUP_SUFFIX,
                consume=False,
            )
            restored_agent = restored_agent or (
                restored and path == C.AGENT_CONFIG_PATH
            )
            restored_bgp = restored_bgp or (restored and path == C.BGP_CONFIG_PATH)

        if restored_agent:
            try:
                await driver.async_agent_config_reload()
            except Exception:  # noqa: BLE001
                await driver.async_restart_service(
                    FbossSystemctlServiceName.FBOSS_SW_AGENT
                )
            await driver.async_wait_for_agent_state_configured()
        if restored_bgp:
            await driver.async_restart_service(FbossSystemctlServiceName.BGP)
        for path, restored in (
            (C.BGP_CONFIG_PATH, restored_bgp),
            (C.AGENT_CONFIG_PATH, restored_agent),
        ):
            if restored:
                await async_discard_backup(
                    driver, path, backup_suffix=EDGE_BACKUP_SUFFIX
                )
        self.logger.info(f"{hostname} -- edge eBGP restore complete")
