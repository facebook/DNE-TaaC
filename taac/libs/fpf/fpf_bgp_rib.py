#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""
FPF BGP RIB Viewer / Prefix Tracker (sibling of fpf_fsdb_ribmap)

Same UX as fpf_fsdb_ribmap but queries the BGP daemon directly via the
existing FbossSwitchInternal driver + BgpClientHelper
(`await driver.bgp().async_get_bgp_rib_entries()`) — the same path
`inject_bgp_prefixes.py` uses to talk to bgpd. The BGP RIB is the
*source* — FSDB ribMap is downstream of it. Useful to compare what BGP
has accepted/programmed vs. what FSDB ends up exposing to subscribers
(e.g., HRT on the GPU hosts).

Modes:
  default (no --subnet-prefix / --exact-prefix)
      Dump a parsed prefix → best-path nexthops view + total count.
      Optional --everpaste uploads the parsed map to Everpaste.
  --subnet-prefix <SUBNET>   Count BGP RIB prefixes contained within SUBNET
                             (e.g., 5000:dd::/32). Strict subset semantics:
                             counts prefixes whose network is fully
                             contained in SUBNET (includes SUBNET itself if
                             present).
  --exact-prefix <PREFIX>    Count exact-match for PREFIX in BGP RIB (0/1).
  --track-forever            Repeat the count poll forever (Ctrl-C to stop).
                             Each poll prints a timestamped row.
  --track-interval-sec N     Polling interval in seconds (default 2.0).
                             Only meaningful with --track-forever.

Usage:
  # Default — full BGP RIB dump + parsed prefix→nexthops view
  buck2 run fbcode//scripts/pavanpatil:fpf_bgp_rib -- \
    --gtsws gtsw001.l1002.c087.mwg2

  # Track count of BGP RIB prefixes inside the 5000:dd::/32 supernet, every 2s
  buck2 run fbcode//scripts/pavanpatil:fpf_bgp_rib -- \
    --gtsws gtsw001.l1002.c087.mwg2 \
    --subnet-prefix 5000:dd::/32 --track-forever

  # Track exact-match for one prefix, every 2s, forever
  buck2 run fbcode//scripts/pavanpatil:fpf_bgp_rib -- \
    --gtsws gtsw001.l1002.c087.mwg2 \
    --exact-prefix 5000:dd::/64 --track-forever
"""

import argparse
import asyncio
import ipaddress
import json as json_module
import socket
import sys
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from neteng.fboss.bgp_route_types.types import TRibEntry
from neteng.netcastle.logger import get_root_logger
from neteng.netcastle.utils.everpaste_utils import async_everpaste_str
from taac.internal.driver.fboss_switch_internal import (
    FbossSwitchInternal,
)


logger = get_root_logger()


def _ip_ntop(addr: bytes) -> str:
    """Render TRibEntry.prefix_bin bytes as an IP string."""
    if len(addr) == 4:
        return socket.inet_ntop(socket.AF_INET, addr)
    if len(addr) == 16:
        return socket.inet_ntop(socket.AF_INET6, addr)
    raise ValueError(f"bad binary address (len={len(addr)})")


async def get_bgp_rib(hostname: str) -> List[TRibEntry]:
    """Fetch the BGP RIB from a GTSW using the same helper everything else
    in this directory uses (inject_bgp_prefixes, etc.) — goes through
    `FbossSwitchInternal.bgp() → BgpClientHelper.async_get_bgp_rib_entries()`
    which returns IPv6 + IPv4 entries combined.

    Exceptions are intentionally NOT caught here — the caller (tracker /
    viewer) gets the real error and can surface it (e.g. in the tracker's
    `notes` column) instead of an opaque "empty" result.
    """
    driver = FbossSwitchInternal(hostname, logger)
    bgp = await driver.bgp()
    return await bgp.async_get_bgp_rib_entries()


def _rib_entry_to_network(entry: TRibEntry) -> Optional[ipaddress.IPv6Network]:
    """Turn a TRibEntry into a parsed IPv6Network. None on parse failure / v4."""
    try:
        pfx = entry.prefix
        addr_str = _ip_ntop(pfx.prefix_bin)
        net = ipaddress.ip_network(f"{addr_str}/{pfx.num_bits}", strict=False)
    except (ValueError, AttributeError):
        return None
    if not isinstance(net, ipaddress.IPv6Network):
        # ribMap on FPF testbed is IPv6-only; drop stray v4.
        return None
    return net


def parse_bgp_rib_nexthops(
    rib_entries: List[TRibEntry],
) -> Dict[str, List[str]]:
    """Build prefix → best-path nexthops view. Mirrors fpf_fsdb_ribmap's
    parse_rib_map() output shape so the two scripts feel symmetric."""
    out: Dict[str, List[str]] = {}
    for entry in rib_entries:
        net = _rib_entry_to_network(entry)
        if net is None:
            continue
        try:
            best_paths = entry.paths.get("best", []) or []
        except AttributeError:
            best_paths = []
        nhs: List[str] = []
        for p in best_paths:
            try:
                nhs.append(_ip_ntop(p.next_hop.prefix_bin))
            except (AttributeError, ValueError):
                continue
        if nhs:
            out[str(net)] = nhs
    return out


def _count_matching(
    rib_entries: List[TRibEntry],
    subnet: Optional[ipaddress.IPv6Network],
    exact: Optional[ipaddress.IPv6Network],
) -> int:
    """Count BGP RIB entries that match the requested filter.

    - exact  → entries whose network == exact (0 or 1)
    - subnet → entries whose network is fully contained in subnet
               (includes subnet itself). Strict subset_of semantics.
    Caller guarantees exactly one of {subnet, exact} is set.
    """
    count = 0
    for entry in rib_entries:
        net = _rib_entry_to_network(entry)
        if net is None:
            continue
        if exact is not None:
            if net == exact:
                count += 1
        elif subnet is not None:
            try:
                if net.subnet_of(subnet):
                    count += 1
            except (TypeError, ValueError):
                continue
    return count


def _now_ts() -> str:
    """Local timestamp w/ ms precision + TZ (matches fpf_fsdb_ribmap tracker)."""
    now = datetime.now().astimezone()
    return (
        now.strftime("%Y-%m-%d %H:%M:%S.")
        + f"{now.microsecond // 1000:03d}"
        + now.strftime("%z")
    )


async def _poll_count_once(
    gtsw: str,
    subnet: Optional[ipaddress.IPv6Network],
    exact: Optional[ipaddress.IPv6Network],
) -> Tuple[Optional[int], int, Optional[str]]:
    """One BGP RIB fetch + count cycle for one GTSW.

    Returns (matched_count, total_entries, error). matched_count is None on
    fetch failure.
    """
    try:
        rib_entries = await get_bgp_rib(gtsw)
    except Exception as e:
        return (None, 0, f"fetch error: {e}")
    if not rib_entries:
        return (None, 0, "empty/unavailable")
    total = len(rib_entries)
    matched = _count_matching(rib_entries, subnet, exact)
    return (matched, total, None)


async def run_viewer(gtsws: List[str], do_everpaste: bool) -> None:
    print("=" * 80)
    print("  FPF BGP RIB Viewer (FbossSwitchInternal.bgp().async_get_bgp_rib_entries)")
    print("=" * 80)

    for gtsw in gtsws:
        print(f"\n{'─' * 80}")
        print(f"  GTSW: {gtsw}")
        print(f"{'─' * 80}")

        try:
            rib_entries = await get_bgp_rib(gtsw)
        except Exception as e:
            print(f"  ❌ BGP RIB fetch failed: {e}")
            continue
        if not rib_entries:
            print("  ❌ BGP RIB empty")
            continue

        print(f"  ✅ BGP RIB fetched ({len(rib_entries)} entries, v4+v6 combined)")

        prefix_nh_map = parse_bgp_rib_nexthops(rib_entries)
        if prefix_nh_map:
            print(f"\n  Prefix → Best Nexthops ({len(prefix_nh_map)} IPv6 prefixes):")
            print(f"  {'-' * 75}")
            for pfx, nhs in sorted(prefix_nh_map.items()):
                print(f"    {pfx:<45} → {nhs}")

            if do_everpaste:
                try:
                    parsed_json = json_module.dumps(prefix_nh_map, indent=2)
                    ep_url = await async_everpaste_str(parsed_json, logger=logger)
                    print(f"\n  Everpaste (parsed): {ep_url}")
                except Exception as ep_err:
                    print(f"  Everpaste upload failed: {ep_err}")
        else:
            print("  ⚠️  Could not parse any prefix→nexthop pairs.")


async def run_tracker(
    gtsws: List[str],
    subnet: Optional[ipaddress.IPv6Network],
    exact: Optional[ipaddress.IPv6Network],
    track_forever: bool,
    interval_sec: float,
) -> None:
    """Lightweight prefix-counter mode against BGP RIB. Prints one
    timestamped row per poll per GTSW."""

    if subnet is not None and exact is not None:
        print(
            "ERROR: pass only one of --subnet-prefix / --exact-prefix",
            file=sys.stderr,
        )
        sys.exit(2)
    if subnet is None and exact is None:
        # main() routes to run_viewer when neither is set.
        print(
            "ERROR: tracker mode requires --subnet-prefix or --exact-prefix",
            file=sys.stderr,
        )
        sys.exit(2)

    mode_label = f"subnet={subnet}" if subnet is not None else f"exact={exact}"
    print("=" * 80)
    print("  FPF BGP RIB Prefix Tracker (via FbossSwitchInternal.bgp())")
    print(f"  Filter: {mode_label}")
    print(f"  GTSWs:  {', '.join(gtsws)}")
    if track_forever:
        print(f"  Interval: {interval_sec:.2f}s — running forever (Ctrl-C to stop)")
    else:
        print("  Single poll (use --track-forever for continuous)")
    print("=" * 80)
    print(f"{'timestamp':<32}  {'gtsw':<30}  {'matched':>8}  {'total':>8}  notes")
    print("-" * 100)

    while True:
        results = await asyncio.gather(
            *[_poll_count_once(g, subnet, exact) for g in gtsws],
            return_exceptions=False,
        )
        ts = _now_ts()
        for gtsw, (matched, total, err) in zip(gtsws, results):
            matched_str = "--" if matched is None else str(matched)
            note = err if err else ""
            print(
                f"{ts:<32}  {gtsw:<30}  {matched_str:>8}  {total:>8}  {note}",
                flush=True,
            )
        if not track_forever:
            return
        await asyncio.sleep(interval_sec)


def _parse_ipv6_network(value: str, flag_name: str) -> ipaddress.IPv6Network:
    """Parse an IPv6 network from a CLI flag, with a clear error."""
    try:
        net = ipaddress.ip_network(value, strict=False)
    except ValueError as e:
        raise argparse.ArgumentTypeError(
            f"{flag_name}: invalid IPv6 network '{value}': {e}"
        ) from e
    if not isinstance(net, ipaddress.IPv6Network):
        raise argparse.ArgumentTypeError(
            f"{flag_name}: '{value}' is not an IPv6 network "
            f"(BGP RIB v6 tracker is IPv6-only)"
        )
    return net


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "FPF BGP RIB Viewer / Prefix Tracker — query bgpd via "
            "FbossSwitchInternal.bgp().async_get_bgp_rib_entries(). "
            "Sibling of fpf_fsdb_ribmap; same tracker UX (--subnet-prefix / "
            "--exact-prefix [+ --track-forever])."
        )
    )
    parser.add_argument(
        "--gtsws",
        nargs="+",
        required=True,
        help="List of GTSW hostnames (e.g., gtsw001.l1002.c087.mwg2)",
    )

    tracker_group = parser.add_mutually_exclusive_group()
    tracker_group.add_argument(
        "--subnet-prefix",
        type=str,
        default=None,
        help=(
            "Count BGP RIB prefixes contained within this IPv6 supernet "
            "(e.g., 5000:dd::/32). Strict subset semantics — includes the "
            "supernet itself if present. Cannot be combined with "
            "--exact-prefix."
        ),
    )
    tracker_group.add_argument(
        "--exact-prefix",
        type=str,
        default=None,
        help=(
            "Count exact-match for this IPv6 prefix in BGP RIB (0 or 1) "
            "(e.g., 5000:dd::/64). Cannot be combined with --subnet-prefix."
        ),
    )

    parser.add_argument(
        "--track-forever",
        action="store_true",
        help=(
            "In tracker mode, repeat the count poll forever (Ctrl-C to stop). "
            "Each poll prints a timestamped row per GTSW."
        ),
    )
    parser.add_argument(
        "--track-interval-sec",
        type=float,
        default=2.0,
        help=(
            "Polling interval in seconds (default: 2.0). Only used with "
            "--track-forever."
        ),
    )
    parser.add_argument(
        "--everpaste",
        action="store_true",
        help=(
            "Viewer mode only: upload the parsed prefix→nexthops map to "
            "Everpaste. Ignored in tracker mode."
        ),
    )

    args = parser.parse_args()

    subnet_net: Optional[ipaddress.IPv6Network] = None
    exact_net: Optional[ipaddress.IPv6Network] = None
    if args.subnet_prefix is not None:
        subnet_net = _parse_ipv6_network(args.subnet_prefix, "--subnet-prefix")
    if args.exact_prefix is not None:
        exact_net = _parse_ipv6_network(args.exact_prefix, "--exact-prefix")

    if subnet_net is not None or exact_net is not None:
        if args.track_interval_sec <= 0:
            print("ERROR: --track-interval-sec must be > 0", file=sys.stderr)
            sys.exit(2)
        asyncio.run(
            run_tracker(
                args.gtsws,
                subnet_net,
                exact_net,
                args.track_forever,
                args.track_interval_sec,
            )
        )
        return

    if args.track_forever:
        print(
            "ERROR: --track-forever requires --subnet-prefix or --exact-prefix",
            file=sys.stderr,
        )
        sys.exit(2)

    asyncio.run(run_viewer(args.gtsws, args.everpaste))


if __name__ == "__main__":
    main()
