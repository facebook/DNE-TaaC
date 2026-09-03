# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""RBB SRv6 direct TE_AGENT route task.

Installs or deletes the direct TE_AGENT route for the tail destination
(gates S21 / S27), proving the S22/S28 route-owner transition.

Two modes, selected by the params:

* **FBOSS thrift mode** (``prefix`` param present): the real, non-destructive
  path used on the lab boxes. There is no ``fboss2`` write path for routes, so
  this talks agent thrift (``addUnicastRoutes`` / ``deleteUnicastRoutes`` with
  ClientID ``TE_AGENT``). Install clones the *existing* route object for the
  prefix and re-adds it under the TE_AGENT client — reusing the exact resolved
  nexthops so forwarding is byte-for-byte unchanged — which makes TE_AGENT the
  more-preferred owner (AdminDistance 2 < BGP 20). Delete withdraws the
  TE_AGENT copy so the prefix reverts to its BGPD owner. Fully reversible.
* **Generic-NOS shell mode** (``install_cmds`` / ``delete_cmds``): runs the
  scenario-supplied CLI bundle for non-FBOSS targets.
"""

import typing as t

from taac.tasks.base_task import BaseTask
from taac.utils.driver_factory import async_get_device_driver
from taac.utils.oss_taac_lib_utils import ConsoleFileLogger

_INSTALL = "install"
_DELETE = "delete"
_DEFAULT_CLIENT = "TE_AGENT"


class RbbSrv6DirectRouteTask(BaseTask):
    """Install/delete the direct TE_AGENT SRv6 route on one DUT."""

    # pyrefly: ignore [bad-override-mutable-attribute]
    NAME: str = "rbb_srv6_direct_route"

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
        """Apply the install or delete action.

        params:
            hostname: DUT to program (required).
            action: "install" or "delete" (required).
            prefix: tail prefix to steer (FBOSS thrift mode; e.g. 203.0.113.0/24).
            client: ClientID enum name for the direct route (default TE_AGENT).
            install_cmds / delete_cmds: ordered CLI bundles (shell mode).
        """
        hostname = params.get("hostname") or self.hostname
        if not hostname:
            raise ValueError("rbb_srv6_direct_route requires 'hostname'")
        action = params.get("action")
        if action not in (_INSTALL, _DELETE):
            raise ValueError(
                f"rbb_srv6_direct_route 'action' must be {_INSTALL!r} or {_DELETE!r}, "
                f"got {action!r}"
            )

        driver = await async_get_device_driver(hostname)

        prefix = params.get("prefix")
        if prefix:
            await self._run_fboss_thrift(
                driver, hostname, action, prefix, params.get("client", _DEFAULT_CLIENT)
            )
            return

        cmds: t.List[str] = params.get(f"{action}_cmds", [])
        if not cmds:
            self.logger.info(
                f"{hostname} -- rbb_srv6_direct_route[{action}]: no cmds supplied"
            )
            return
        self.logger.info(
            f"{hostname} -- SRv6 direct route {action} ({len(cmds)} cmds)"
        )
        for cmd in cmds:
            self.logger.info(f"{hostname} -- {action}: {cmd}")
            await driver.async_run_cmd_on_shell(cmd)

    async def _run_fboss_thrift(
        self,
        driver: t.Any,
        hostname: str,
        action: str,
        prefix: str,
        client: str,
    ) -> None:
        """Add/withdraw the direct route via FBOSS agent thrift.

        Non-destructive: install re-adds the *existing* route object under the
        given ClientID (reusing the resolved nexthops so forwarding is
        unchanged); delete withdraws only that client's copy.
        """
        import socket

        from neteng.fboss.ctrl.types import AdminDistance, ClientID, UnicastRoute

        try:
            client_id = int(getattr(ClientID, client))
        except AttributeError as exc:
            raise ValueError(
                f"rbb_srv6_direct_route: unknown ClientID {client!r}"
            ) from exc
        admin_distance = getattr(AdminDistance, client, None)

        net, _, plen_str = prefix.partition("/")
        plen = int(plen_str) if plen_str else (32 if ":" not in net else 128)

        def _addr_str(binary_addr: bytes) -> str:
            fam = socket.AF_INET if len(binary_addr) == 4 else socket.AF_INET6
            return socket.inet_ntop(fam, binary_addr)

        async with driver.async_agent_client as agent:
            routes = await agent.getRouteTable()
            target = None
            for route in routes:
                if (
                    _addr_str(route.dest.ip.addr) == net
                    and route.dest.prefixLength == plen
                ):
                    target = route
                    break
            if target is None:
                # Delete of an absent route is a no-op; install needs it present.
                self.logger.info(
                    f"{hostname} -- direct route {action}: prefix {prefix} not "
                    f"present in RIB; nothing to do"
                )
                return

            if action == _INSTALL:
                new_route = UnicastRoute(
                    dest=target.dest,
                    nextHops=target.nextHops,
                    adminDistance=admin_distance,
                )
                await agent.addUnicastRoutes(client_id, [new_route])
                self.logger.info(
                    f"{hostname} -- installed {client} direct route for {prefix} "
                    f"(reused resolved nexthops; forwarding unchanged)"
                )
            else:
                await agent.deleteUnicastRoutes(client_id, [target.dest])
                self.logger.info(
                    f"{hostname} -- deleted {client} direct route for {prefix}"
                )
