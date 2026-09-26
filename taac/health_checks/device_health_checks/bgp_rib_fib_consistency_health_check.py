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
``rib_fib_*heal_latency*`` diagnostics are accepted and ignored.
"""

import ipaddress
import socket
import typing as t

from neteng.fboss.ctrl.types import ClientID
from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import AbstractDeviceHealthCheck
from taac.health_check.health_check import types as hc_types

_BGPD = int(ClientID.BGPD)
_MAX_EXAMPLES = 10


def _ntop(addr: bytes, family: int) -> str:
    size = 4 if family == socket.AF_INET else 16
    return socket.inet_ntop(family, bytes(addr).ljust(size, b"\0")[:size])


def rib_prefixes(entries: t.Iterable[t.Any]) -> t.Set[str]:
    """CIDRs of RIB entries that have a selected best path."""
    out = set()
    for e in entries:
        if e.best_path is None:
            continue
        family = socket.AF_INET6 if len(e.prefix.prefix_bin) > 4 else socket.AF_INET
        out.add(f"{_ntop(e.prefix.prefix_bin, family)}/{e.prefix.num_bits}")
    return out


def _cidr(r: t.Any) -> str:
    family = socket.AF_INET6 if len(r.dest.ip.addr) == 16 else socket.AF_INET
    return f"{_ntop(r.dest.ip.addr, family)}/{r.dest.prefixLength}"


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
            ipaddress.ip_network(p, strict=False).version == n.version
            and ipaddress.ip_network(p, strict=False).subnet_of(n)
            for n in nets
        )
    }


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
        rib = drop_ignored(rib_prefixes(await self.driver.async_get_bgp_rib_entries()), ignore)
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
        # A BGP best path is "in the FIB" even when a static or connected route
        # for the same prefix won the FIB slot, so compare against every owner.
        missing_in_fib = sorted(rib - drop_ignored(fib_prefixes(details), ignore))
        missing_in_rib = sorted(fib - rib)
        self.add_data_to_log(
            {
                "rib_prefixes": len(rib),
                "fib_bgp_prefixes": len(fib),
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
