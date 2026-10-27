# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""BGP_RIB_FIB_CONSISTENCY_CHECK for OSS: every BGP best path is in the FIB and
every BGP-owned FIB route is in the RIB.

``create_bgp_rib_fib_consistency_check()`` existed without a class claiming
``CheckName.BGP_RIB_FIB_CONSISTENCY_CHECK``, so the registry lookup raised a
bare ``KeyError`` that surfaced as ``Step ValidationStep failed on <dut>:
<CheckName.BGP_RIB_FIB_CONSISTENCY_CHECK: 21>`` and failed every
service-restart playbook on an otherwise healthy DUT.

Supported check_params: ``parent_prefixes_to_ignore`` (list of CIDRs whose
subnets are excluded from both sides) and the base-class retry knobs. The
``rib_fib_*heal_latency*`` diagnostics are accepted and ignored. Independently
of check_params, a network bgpd itself originates with ``install_to_fib`` false
(``getOriginatedRoutes``) is excluded from the RIB-to-FIB direction only, and
only while its locally originated path is the best path: that is the one case
bgpd never programs. If bgpd cannot list them, nothing is excluded.
"""

import ipaddress
import socket
import typing as t

from neteng.fboss.ctrl.types import ClientID
from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.health_check.health_check import types as hc_types

_BGPD = int(ClientID.BGPD)
_MAX_EXAMPLES = 10


_FAMILY_BY_WIDTH = {4: socket.AF_INET, 16: socket.AF_INET6}


def _ntop(addr: bytes) -> str:
    # ``TIpPrefix.prefix_bin`` and ``BinaryAddress.addr`` each hold a whole
    # address rather than one truncated to the prefix length, so the width
    # alone names the family. Both the RIB and the FIB side route through
    # here: picking the family two ways makes identical routes format
    # differently and never compare equal.
    packed = bytes(addr)
    family = _FAMILY_BY_WIDTH.get(len(packed))
    if family is None:
        raise ValueError(f"not a packed IPv4/IPv6 address: {packed!r}")
    return socket.inet_ntop(family, packed)


def _prefix_cidr(prefix: t.Any) -> str:
    """CIDR of a bgpd TIpPrefix."""
    return f"{_ntop(prefix.prefix_bin)}/{prefix.num_bits}"


def rib_prefixes(entries: t.Iterable[t.Any]) -> t.Set[str]:
    """CIDRs of RIB entries that have a selected best path."""
    return {_prefix_cidr(e.prefix) for e in entries if e.best_path is not None}


def local_best_prefixes(entries: t.Iterable[t.Any]) -> t.Set[str]:
    """CIDRs of RIB entries whose best path is a locally originated route.

    bgpd's own test (RibBase isLocalRouteBest): the best path's next hop is
    the unspecified address, 0.0.0.0 or ::. A learned path that wins is
    programmed even for a network originated with install_to_fib false.
    """
    return {
        _prefix_cidr(e.prefix)
        for e in entries
        if e.best_path is not None
        and e.best_path.next_hop is not None
        and not any(bytes(e.best_path.next_hop.prefix_bin))
    }


def not_installed_prefixes(routes: t.Iterable[t.Any]) -> t.Set[str]:
    """CIDRs of the routes bgpd originates without programming them in the FIB."""
    # Formatted like rib_prefixes, so the two compare as plain strings.
    return {_prefix_cidr(r.prefix) for r in routes if not r.install_to_fib}


def _cidr(r: t.Any) -> str:
    return f"{_ntop(r.dest.ip.addr)}/{r.dest.prefixLength}"


def fib_prefixes(routes: t.Iterable[t.Any]) -> t.Set[str]:
    """CIDRs of every FIB route (getRouteTableDetails rows), whoever owns it."""
    return {_cidr(r) for r in routes}


def fib_bgp_prefixes(routes: t.Iterable[t.Any]) -> t.Set[str]:
    """CIDRs of FIB routes that BGP programmed (getRouteTableDetails rows)."""
    # getRouteTable() leaves adminDistance unset on OSS agents; the
    # per-client next hops in the details view name the owner instead.
    return {
        _cidr(r)
        for r in routes
        if any(cn.clientId == _BGPD for cn in (r.nextHopMulti or []))
    }


def drop_ignored(prefixes: t.Set[str], parents: t.Iterable[str]) -> t.Set[str]:
    nets = [ipaddress.ip_network(p, strict=False) for p in parents]
    return {
        p
        for p in prefixes
        if not any(
            _is_subnet_of(ipaddress.ip_network(p, strict=False), n) for n in nets
        )
    }


def _is_subnet_of(
    net: t.Union[ipaddress.IPv4Network, ipaddress.IPv6Network],
    parent: t.Union[ipaddress.IPv4Network, ipaddress.IPv6Network],
) -> bool:
    """Family-aware ``subnet_of``.

    ``subnet_of`` raises on a mixed-family pair, so the families are matched
    with isinstance rather than by comparing ``.version`` -- only the former
    narrows the union for the type checker.
    """
    if isinstance(net, ipaddress.IPv4Network) and isinstance(
        parent, ipaddress.IPv4Network
    ):
        return net.subnet_of(parent)
    if isinstance(net, ipaddress.IPv6Network) and isinstance(
        parent, ipaddress.IPv6Network
    ):
        return net.subnet_of(parent)
    return False


class BgpRibFibConsistencyHealthCheck(
    AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]
):
    CHECK_NAME = hc_types.CheckName.BGP_RIB_FIB_CONSISTENCY_CHECK
    OPERATING_SYSTEMS = ["FBOSS"]

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        ignore = check_params.get("parent_prefixes_to_ignore") or []
        entries = await self.driver.async_get_bgp_rib_entries()
        rib = drop_ignored(rib_prefixes(entries), ignore)
        details = await self.driver.async_get_route_table_details()
        unowned = sum(1 for r in details if not r.nextHopMulti)
        if unowned:
            # An agent that leaves nextHopMulti empty hides BGP ownership, so
            # missing_in_rib would under-report; say so instead of staying quiet.
            self.logger.warning(
                f"{unowned}/{len(details)} FIB rows carry no nextHopMulti; "
                "BGP ownership is unknown for them"
            )
        fib = drop_ignored(fib_bgp_prefixes(details), ignore)
        not_installed = await self._not_installed_prefixes(obj) & local_best_prefixes(
            entries
        )
        # A BGP best path is "in the FIB" even when a static or connected route
        # for the same prefix won the FIB slot, so compare against every owner.
        missing_in_fib = sorted(
            rib - drop_ignored(fib_prefixes(details), ignore) - not_installed
        )
        missing_in_rib = sorted(fib - rib)
        self.add_data_to_log(
            {
                "rib_prefixes": len(rib),
                "fib_bgp_prefixes": len(fib),
                "originated_not_installed": len(not_installed),
                "missing_in_fib": len(missing_in_fib),
                "missing_in_rib": len(missing_in_rib),
            }
        )
        if not missing_in_fib and not missing_in_rib:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.PASS,
                message=f"{obj.name}: {len(rib)} BGP prefixes consistent between RIB and FIB",
            )
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.FAIL,
            message=(
                f"{obj.name}: RIB/FIB drift -- {len(missing_in_fib)} RIB best paths not in "
                f"FIB (e.g. {missing_in_fib[:_MAX_EXAMPLES]}), {len(missing_in_rib)} BGP FIB "
                f"routes not in RIB (e.g. {missing_in_rib[:_MAX_EXAMPLES]})"
            ),
        )

    async def _not_installed_prefixes(self, obj: TestDevice) -> t.Set[str]:
        try:
            return not_installed_prefixes(
                await self.driver.async_get_bgp_originated_routes() or []
            )
        except Exception as exc:
            # Excluding nothing keeps the check at its strictest; the miss is
            # reported, not hidden.
            self.logger.warning(
                f"{obj.name}: cannot list bgpd's originated routes, so no "
                f"install_to_fib=false network is excluded: {exc}"
            )
            return set()
