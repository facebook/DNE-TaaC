# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""RBB SRv6 direct TE_AGENT route task.

Installs or deletes the direct TE_AGENT route for the tail destination
(gates S21 / S27), proving the S22/S28 route-owner transition.

There is no ``fboss2`` write path for routes, so this talks agent thrift
(``addUnicastRoutes`` / ``deleteUnicastRoutes`` with ClientID ``TE_AGENT``).
Install retains the BGPD client's original recursive next hops (including the
tail decap SID) and adds an explicit SRv6 segment list and tunnel ID. Owner
preference comes from the switch's ``clientIdToAdminDistance`` policy. Delete
withdraws only the TE_AGENT copy so the prefix reverts to its BGPD owner.
"""

import ipaddress
import typing as t

from taac.constants import TestCaseFailure
from taac.tasks.base_task import BaseTask
from taac.utils.driver_factory import async_get_device_driver
from taac.utils.oss_taac_lib_utils import ConsoleFileLogger

_INSTALL = "install"
_DELETE = "delete"
_DEFAULT_CLIENT = "TE_AGENT"


def _build_srv6_next_hop(
    next_hop_type: t.Any,
    tunnel_type: t.Any,
    source: t.Any,
    segment_addrs: t.Sequence[t.Any],
    tunnel_id: str,
) -> t.Any:
    """Clone one route-table next hop and attach SRv6 attributes.

    FBOSS route-table RPCs can return a compatibility view generated from an
    older ``NextHopThrift`` schema than the writable client type.  Copy only
    fields exposed by both views so newly added optional fields (for example
    ``role``) do not make route programming version-dependent.
    """
    if not hasattr(source, "address"):
        raise TestCaseFailure("BGPD next hop has no address")

    required_write_fields = ("srv6SegmentList", "tunnelType", "tunnelId")
    unsupported = [
        field for field in required_write_fields if not hasattr(next_hop_type, field)
    ]
    if unsupported:
        raise TestCaseFailure(
            "FBOSS client NextHopThrift does not support required SRv6 fields: "
            + ", ".join(unsupported)
        )

    kwargs: t.Dict[str, t.Any] = {
        "address": source.address,
        "srv6SegmentList": list(segment_addrs),
        "tunnelType": tunnel_type,
        "tunnelId": tunnel_id,
    }
    for field in (
        "weight",
        "mplsAction",
        "disableTTLDecrement",
        "adjustedWeight",
        "topologyInfo",
        "cost",
        "role",
        "backupNexthops",
    ):
        if hasattr(source, field) and hasattr(next_hop_type, field):
            kwargs[field] = getattr(source, field)

    try:
        return next_hop_type(**kwargs)
    except (TypeError, ValueError) as exc:
        raise TestCaseFailure(
            "FBOSS client rejected the SRv6 next-hop fields"
        ) from exc


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
            prefix: IPv6 tail prefix to steer (required).
            client: ClientID enum name for the direct route (default TE_AGENT).
            srv6_segments: ordered IPv6 SRv6 segment list (required on install).
            srv6_tunnel_id: configured FBOSS SRv6 tunnel ID (required on install).
            force_delete: permit an explicit recovery delete without this
                runner's install marker (default False).
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

        prefix = params.get("prefix")
        if not prefix:
            raise ValueError("rbb_srv6_direct_route requires 'prefix'")
        force_delete = params.get("force_delete", False)
        if not isinstance(force_delete, bool):
            raise ValueError(
                "rbb_srv6_direct_route 'force_delete' must be a JSON boolean"
            )

        driver = await async_get_device_driver(hostname)
        await self._run_fboss_thrift(
            driver,
            hostname,
            action,
            prefix,
            params.get("client", _DEFAULT_CLIENT),
            srv6_segments=params.get("srv6_segments"),
            srv6_tunnel_id=params.get("srv6_tunnel_id"),
            force_delete=force_delete,
        )

    async def _run_fboss_thrift(
        self,
        driver: t.Any,
        hostname: str,
        action: str,
        prefix: str,
        client: str,
        *,
        srv6_segments: t.Optional[t.Sequence[str]] = None,
        srv6_tunnel_id: t.Optional[str] = None,
        force_delete: bool = False,
    ) -> None:
        """Add/withdraw the direct route via FBOSS agent thrift.

        Install re-adds the BGPD client's exact route under the given ClientID,
        retaining its original recursive next hops and attaching the requested
        SRv6 segment list. Delete withdraws only that client's copy.
        """
        import socket

        from facebook.network.Address.types import BinaryAddress
        from neteng.fboss.common.types import NextHopThrift, TunnelType
        from neteng.fboss.ctrl.types import AdminDistance, ClientID, UnicastRoute

        try:
            client_id = int(getattr(ClientID, client))
        except AttributeError as exc:
            raise ValueError(
                f"rbb_srv6_direct_route: unknown ClientID {client!r}"
            ) from exc
        admin_distance = getattr(AdminDistance, client, None)
        try:
            bgpd_client_id = int(ClientID.BGPD)
        except AttributeError as exc:
            raise TestCaseFailure(
                "rbb_srv6_direct_route requires the FBOSS BGPD ClientID"
            ) from exc

        try:
            network = ipaddress.ip_network(prefix, strict=True)
        except ValueError as exc:
            raise ValueError(
                f"rbb_srv6_direct_route: invalid prefix {prefix!r}"
            ) from exc
        if network.version != 6:
            raise ValueError("rbb_srv6_direct_route prefix must be IPv6")
        net = str(network.network_address)
        plen = network.prefixlen
        segment_addrs: t.List[t.Any] = []
        if action == _INSTALL:
            if not srv6_segments:
                raise ValueError(
                    "rbb_srv6_direct_route install requires 'srv6_segments'"
                )
            if not srv6_tunnel_id or not str(srv6_tunnel_id).strip():
                raise ValueError(
                    "rbb_srv6_direct_route install requires 'srv6_tunnel_id'"
                )
            for segment in srv6_segments:
                try:
                    parsed = ipaddress.ip_address(segment)
                except ValueError as exc:
                    raise ValueError(
                        f"rbb_srv6_direct_route: invalid segment {segment!r}"
                    ) from exc
                if parsed.version != 6:
                    raise ValueError(
                        f"rbb_srv6_direct_route: segment {segment!r} must be IPv6"
                    )
                segment_addrs.append(BinaryAddress(addr=parsed.packed))
        ownership_key = f"{hostname}:{network.with_prefixlen}:{client}"
        installed_by_this_run = (
            ownership_key in self._data and self._data[ownership_key] is True
        )
        if action == _DELETE and not (installed_by_this_run or force_delete):
            self.logger.info(
                f"{hostname} -- direct route delete skipped for {prefix}: this "
                "runner did not install it (set force_delete=true only for "
                "explicit recovery)"
            )
            return

        def _addr_str(binary_addr: bytes) -> str:
            fam = socket.AF_INET if len(binary_addr) == 4 else socket.AF_INET6
            return socket.inet_ntop(fam, binary_addr)

        def _matches(route: t.Any) -> bool:
            return (
                _addr_str(route.dest.ip.addr) == net
                and route.dest.prefixLength == plen
            )

        async with driver.async_agent_client as agent:
            if action == _INSTALL:
                bgpd_routes = await agent.getRouteTableByClient(bgpd_client_id)
                target = next(
                    (route for route in bgpd_routes if _matches(route)), None
                )
                if target is None:
                    raise TestCaseFailure(
                        f"{hostname}: cannot install {client} copy of {prefix}; "
                        "the exact BGPD-owned route is not present in the RIB"
                    )
                if not installed_by_this_run:
                    existing_client_routes = await agent.getRouteTableByClient(
                        client_id
                    )
                    if any(_matches(route) for route in existing_client_routes):
                        raise TestCaseFailure(
                            f"{hostname}: {client} already owns {prefix}; refusing "
                            "to adopt and later delete an operator-owned route"
                        )
                if not target.nextHops:
                    raise TestCaseFailure(
                        f"{hostname}: BGPD route {prefix} has no structured "
                        "next hops to use for SRv6 resolution"
                    )
                if any(
                    getattr(nh, "mplsAction", None) is not None
                    for nh in target.nextHops
                ):
                    raise TestCaseFailure(
                        f"{hostname}: BGPD route {prefix} carries MPLS actions; "
                        "refusing to replace them with an SRv6 segment list"
                    )
                srv6_next_hops = [
                    _build_srv6_next_hop(
                        NextHopThrift,
                        TunnelType.SRV6_ENCAP,
                        nh,
                        segment_addrs,
                        str(srv6_tunnel_id),
                    )
                    for nh in target.nextHops
                ]
                route_kwargs: t.Dict[str, t.Any] = {
                    "dest": target.dest,
                    "nextHopAddrs": target.nextHopAddrs,
                    "nextHops": srv6_next_hops,
                    "action": target.action,
                    "namedRouteDestination": target.namedRouteDestination,
                    "counterID": target.counterID,
                    "classID": target.classID,
                }
                # The route-table read API may expose internal override fields,
                # but ThriftHandler deliberately rejects either field on client
                # addUnicastRoutes calls.  They are therefore not copied into
                # the TE_AGENT write object.
                if admin_distance is not None:
                    route_kwargs["adminDistance"] = admin_distance
                else:
                    route_kwargs["adminDistance"] = target.adminDistance
                new_route = UnicastRoute(**route_kwargs)
                # Cleanup runs through a separate registered-task instance. The
                # precondition above established that this client/prefix slot
                # was empty. Mark it before the mutating RPC so cleanup also
                # covers an ambiguous transport failure where the agent applies
                # the route but the client never receives the response.
                self._data[ownership_key] = True
                await agent.addUnicastRoutes(client_id, [new_route])
                installed_routes = await agent.getRouteTableByClient(client_id)
                installed = next(
                    (route for route in installed_routes if _matches(route)), None
                )
                if installed is None or not installed.nextHops:
                    raise TestCaseFailure(
                        f"{hostname}: {client} route {prefix} was not readable "
                        "after install"
                    )
                expected_segments = [entry.addr for entry in segment_addrs]
                if any(
                    [
                        entry.addr
                        for entry in (getattr(nh, "srv6SegmentList", None) or [])
                    ]
                    != expected_segments
                    or getattr(nh, "tunnelType", None) != TunnelType.SRV6_ENCAP
                    or getattr(nh, "tunnelId", None) != str(srv6_tunnel_id)
                    for nh in installed.nextHops
                ):
                    raise TestCaseFailure(
                        f"{hostname}: {client} route {prefix} did not retain "
                        "the requested SRv6 segment list and tunnel"
                    )
                self.logger.info(
                    f"{hostname} -- installed {client} direct route for {prefix} "
                    f"with SRv6 segments {list(srv6_segments)!r}"
                )
            else:
                client_routes = await agent.getRouteTableByClient(client_id)
                target = next(
                    (route for route in client_routes if _matches(route)), None
                )
                if target is None:
                    self.logger.info(
                        f"{hostname} -- direct route delete: {client} copy of "
                        f"{prefix} is already absent"
                    )
                    self._data[ownership_key] = False
                    return
                await agent.deleteUnicastRoutes(client_id, [target.dest])
                remaining = await agent.getRouteTableByClient(client_id)
                if any(_matches(route) for route in remaining):
                    raise TestCaseFailure(
                        f"{hostname}: {client} route {prefix} remained after delete"
                    )
                self._data[ownership_key] = False
                self.logger.info(
                    f"{hostname} -- deleted {client} direct route for {prefix}"
                )
