#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""
FPF FSDB RibMap Viewer

Fetch FSDB bgp/ribMap state from GTSWs and display:
1. Raw ribMap JSON → uploaded to Everpaste
2. Parsed prefix → nexthop map

Also supports lightweight "prefix counter" modes for scale/convergence
tracking:
  --subnet-prefix <SUBNET>   Count ribMap prefixes that fall within SUBNET
                             (e.g., 5000:dd::/32 — counts everything inside
                             that supernet). Strict subset semantics:
                             counts prefixes whose network range is fully
                             contained in SUBNET.
  --exact-prefix <PREFIX>    Count exact-match for PREFIX in ribMap (0 or 1).
  --track-forever            Repeat the count poll forever (Ctrl-C to stop).
                             Each poll prints a timestamped row.
  --track-interval-sec N     Polling interval in seconds (default 2.0).
                             Only meaningful with --track-forever.

Usage:
  # Default — full ribMap dump + parse + everpaste
  buck2 run fbcode//scripts/pavanpatil:fpf_fsdb_ribmap -- \
    --gtsws gtsw001.l1002.c087.mwg2

  # Track count of prefixes inside the 5000:dd::/32 supernet, every 2s, forever
  buck2 run fbcode//scripts/pavanpatil:fpf_fsdb_ribmap -- \
    --gtsws gtsw001.l1002.c087.mwg2 \
    --subnet-prefix 5000:dd::/32 --track-forever

  # Track exact-match for one prefix, every 2s, forever
  buck2 run fbcode//scripts/pavanpatil:fpf_fsdb_ribmap -- \
    --gtsws gtsw001.l1002.c087.mwg2 \
    --exact-prefix 5000:dd::/64 --track-forever
"""

import argparse
import asyncio
import base64
import ipaddress
import json as json_module
import sys
from datetime import datetime
from typing import Dict, List, Optional

from neteng.netcastle.logger import get_root_logger
from neteng.netcastle.utils.everpaste_utils import async_everpaste_str
from taac.internal.driver.fboss_switch_internal import (
    FbossSwitchInternal,
)


logger = get_root_logger()


FSDB_PATHS = {
    "ribmap": ["bgp", "ribMap"],
    "canonical": ["bgp", "canonicalRib"],
}


async def get_fsdb_rib_map(driver: FbossSwitchInternal, mode: str = "ribmap") -> dict:
    """Fetch FSDB BGP rib state via getOperState thrift API.

    Args:
        driver: FBOSS switch driver for the target GTSW.
        mode: ``"ribmap"`` for ``bgp/ribMap`` (legacy),
              ``"canonical"`` for ``bgp/canonicalRib`` (new).

    Uses a 10s timeout since the payload can be large.
    Exceptions are intentionally NOT caught here — the caller (tracker /
    viewer) gets the real error and can surface it (e.g. in the tracker's
    `notes` column) instead of an opaque "empty" result.
    """
    from neteng.fboss.fsdb import types as fsdb_types
    from neteng.fboss.fsdb.clients import FsdbService
    from neteng.fboss.fsdb_oper import types as fsdb_oper_types
    from neteng.fboss.lib.asyncio import hostnames
    from servicerouter.py3 import ClientParams, get_sr_client

    ip_addr = await hostnames.host_to_ip(driver.hostname)
    if not ip_addr:
        logger.error(f"Cannot resolve {driver.hostname} for FSDB rib")
        return {}
    client_params = (
        ClientParams()
        .setSingleHost(ipAddr=ip_addr, port=5908)
        .setOverallTimeoutMs(10000)
    )
    client_params.setProcessingTimeoutMs(10000)

    raw_path = FSDB_PATHS.get(mode, FSDB_PATHS["ribmap"])
    path = fsdb_oper_types.OperPath(raw=raw_path)
    req = fsdb_types.OperGetRequest(
        path=path, protocol=fsdb_oper_types.OperProtocol.SIMPLE_JSON
    )
    async with get_sr_client(FsdbService, "", params=client_params) as fsdb_client:
        result = await fsdb_client.getOperState(req)
    if result and hasattr(result, "contents") and result.contents:
        data = json_module.loads(result.contents)
        if mode == "canonical" and isinstance(data, dict):
            return data.get("rib_entries", data)
        return data
    return {}


def parse_rib_map(rib_map: dict) -> Dict[str, List[str]]:
    """Parse ribMap JSON into prefix → list of best nexthops.

    Structure: ribMap[prefix_str] = {prefix, paths, best_group, best_next_hop, rib_version}
    - best_next_hop.prefix_bin is base64-encoded 16-byte IPv6
    - paths[group_name] is a list of path entries, each with next_hop.prefix_bin
    """
    prefix_to_nexthops: Dict[str, List[str]] = {}
    if not isinstance(rib_map, dict):
        return prefix_to_nexthops

    for prefix_str, entry in rib_map.items():
        if not isinstance(entry, dict):
            continue
        nexthops = []
        best_group = entry.get("best_group", "best")
        paths = entry.get("paths", {})
        if isinstance(paths, dict):
            best_paths = paths.get(best_group, [])
            if isinstance(best_paths, list):
                for path_entry in best_paths:
                    if not isinstance(path_entry, dict):
                        continue
                    nh = path_entry.get("next_hop", {})
                    if isinstance(nh, dict):
                        b64 = nh.get("prefix_bin", "")
                        if b64:
                            try:
                                padded = (
                                    b64 + "=" * (4 - len(b64) % 4)
                                    if len(b64) % 4
                                    else b64
                                )
                                raw = base64.b64decode(padded)
                                addr = ipaddress.ip_address(raw).compressed
                                nexthops.append(addr)
                            except Exception:
                                nexthops.append(b64)
        if not nexthops:
            bnh = entry.get("best_next_hop", {})
            if isinstance(bnh, dict):
                b64 = bnh.get("prefix_bin", "")
                if b64:
                    try:
                        padded = b64 + "=" * (4 - len(b64) % 4) if len(b64) % 4 else b64
                        raw = base64.b64decode(padded)
                        addr = ipaddress.ip_address(raw).compressed
                        nexthops.append(addr)
                    except Exception:
                        nexthops.append(b64)
        if nexthops:
            prefix_to_nexthops[prefix_str] = nexthops

    return prefix_to_nexthops


def _extract_path_communities(path_entry: dict, sink: set) -> None:
    """Add 'ASN:VALUE' community strings from a single path entry to `sink`."""
    if not isinstance(path_entry, dict):
        return
    comms = path_entry.get("communities") or []
    if not isinstance(comms, list):
        return
    for c in comms:
        if not isinstance(c, dict):
            continue
        asn = c.get("asn")
        val = c.get("value")
        if asn is None or val is None:
            continue
        sink.add(f"{asn}:{val}")


def _extract_entry_communities(entry: dict) -> List[str]:
    """Flatten communities across all path groups of one ribMap entry."""
    seen: set = set()
    if not isinstance(entry, dict):
        return []
    paths = entry.get("paths", {})
    if not isinstance(paths, dict):
        return []
    for path_list in paths.values():
        if not isinstance(path_list, list):
            continue
        for path_entry in path_list:
            _extract_path_communities(path_entry, seen)
    return sorted(seen)


def parse_rib_map_communities(rib_map: dict) -> Dict[str, List[str]]:
    """Parse ribMap JSON into a prefix -> sorted unique list of 'ASN:VALUE'
    community strings across all paths for the prefix.

    Path entries carry communities as a list of {asn, value, community};
    we flatten across all path groups so the caller sees every community
    visible for the prefix at FSDB layer.
    """
    if not isinstance(rib_map, dict):
        return {}
    return {
        prefix_str: _extract_entry_communities(entry)
        for prefix_str, entry in rib_map.items()
    }


async def run(gtsws: List[str], mode: str = "ribmap") -> None:
    path_label = "/".join(FSDB_PATHS[mode])
    print("=" * 80)
    print(f"  FPF FSDB Rib Viewer (mode={mode}, path={path_label})")
    print("=" * 80)

    for gtsw in gtsws:
        print(f"\n{'─' * 80}")
        print(f"  GTSW: {gtsw}")
        print(f"{'─' * 80}")

        driver = FbossSwitchInternal(gtsw, logger)
        try:
            rib_map = await get_fsdb_rib_map(driver, mode=mode)
        except Exception as e:
            print(f"  ❌ rib fetch failed: {e}")
            continue

        if not rib_map:
            print("  ❌ ribMap empty")
            continue

        entry_count = len(rib_map) if isinstance(rib_map, dict) else 0
        print(f"  ✅ rib fetched ({entry_count} entries)")

        # Upload raw JSON to everpaste
        rib_json = json_module.dumps(rib_map, indent=2)
        try:
            ep_url = await async_everpaste_str(rib_json, logger=logger)
            print(f"  Everpaste (raw): {ep_url}")
        except Exception as ep_err:
            print(f"  Everpaste upload failed: {ep_err}")

        # Parse prefix → nexthops
        print("\n  Parsing prefix → nexthop map...")
        prefix_nh_map = parse_rib_map(rib_map)

        if prefix_nh_map:
            print(f"\n  Prefix → Best Nexthops ({len(prefix_nh_map)} prefixes):")
            print(f"  {'-' * 75}")
            for pfx, nhs in sorted(prefix_nh_map.items()):
                print(f"    {pfx:<45} → {nhs}")

            # Also upload parsed map to everpaste
            parsed_json = json_module.dumps(prefix_nh_map, indent=2)
            try:
                parsed_ep = await async_everpaste_str(parsed_json, logger=logger)
                print(f"\n  Everpaste (parsed): {parsed_ep}")
            except Exception:
                pass
        else:
            print("  ⚠️  Could not parse prefix→nexthop map.")
            print("  Check the everpaste link above for raw ribMap structure.")


def _count_matching_prefixes(
    rib_map: dict,
    subnet: Optional[ipaddress.IPv6Network],
    exact: Optional[ipaddress.IPv6Network],
) -> int:
    """Count ribMap top-level prefix keys that match the requested filter.

    - `subnet` set → count prefixes whose network is fully contained in subnet
      (i.e. `pfx.subnet_of(subnet)`). Includes `subnet` itself if present.
    - `exact`  set → count prefixes equal to `exact` (0 or 1).
    Only one of {subnet, exact} should be set; caller enforces this.
    """
    if not isinstance(rib_map, dict):
        return 0
    count = 0
    for prefix_str in rib_map.keys():
        try:
            pfx = ipaddress.ip_network(prefix_str, strict=False)
        except ValueError:
            continue
        if not isinstance(pfx, ipaddress.IPv6Network):
            # ribMap is IPv6-only for our FPF use case; ignore stray v4.
            continue
        if exact is not None:
            if pfx == exact:
                count += 1
        elif subnet is not None:
            try:
                if pfx.subnet_of(subnet):
                    count += 1
            except (TypeError, ValueError):
                # Different address families etc. — skip.
                continue
    return count


def _now_ts() -> str:
    """Local timestamp with millisecond precision + timezone, matching the
    style used by sibling FPF scripts (e.g. fpf_hrt_client tracker)."""
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
    mode: str = "ribmap",
) -> tuple[Optional[int], int, Optional[str]]:
    """Run one rib fetch + count cycle for a single GTSW.

    Returns (matched_count, total_entries, error). matched_count is None on
    fetch failure.
    """
    driver = FbossSwitchInternal(gtsw, logger)
    try:
        rib_map = await get_fsdb_rib_map(driver, mode=mode)
    except Exception as e:
        return (None, 0, f"fetch error: {e}")
    if not rib_map:
        return (None, 0, "empty/unavailable")
    total = len(rib_map) if isinstance(rib_map, dict) else 0
    matched = _count_matching_prefixes(rib_map, subnet, exact)
    return (matched, total, None)


async def run_tracker(
    gtsws: List[str],
    subnet: Optional[ipaddress.IPv6Network],
    exact: Optional[ipaddress.IPv6Network],
    track_forever: bool,
    interval_sec: float,
    mode: str = "ribmap",
) -> None:
    """Lightweight prefix-counter mode. Prints one timestamped row per poll
    per GTSW. Use --track-forever to loop; otherwise run once and exit."""

    if subnet is not None and exact is not None:
        print(
            "ERROR: pass only one of --subnet-prefix / --exact-prefix", file=sys.stderr
        )
        sys.exit(2)
    if subnet is None and exact is None:
        print(
            "ERROR: tracker mode requires --subnet-prefix or --exact-prefix",
            file=sys.stderr,
        )
        sys.exit(2)

    filter_label = f"subnet={subnet}" if subnet is not None else f"exact={exact}"
    path_label = "/".join(FSDB_PATHS[mode])
    print("=" * 80)
    print(f"  FPF FSDB Rib Prefix Tracker (mode={mode}, path={path_label})")
    print(f"  Filter: {filter_label}")
    print(f"  GTSWs:  {', '.join(gtsws)}")
    if track_forever:
        print(f"  Interval: {interval_sec:.2f}s — running forever (Ctrl-C to stop)")
    else:
        print("  Single poll (use --track-forever for continuous)")
    print("=" * 80)

    print(f"{'timestamp':<32}  {'gtsw':<30}  {'matched':>8}  {'total':>8}  notes")
    print("-" * 100)

    poll_idx = 0
    while True:
        poll_idx += 1
        results = await asyncio.gather(
            *[_poll_count_once(g, subnet, exact, mode=mode) for g in gtsws],
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
    """Parse an IPv6 network string from a CLI flag, with a clear error."""
    try:
        net = ipaddress.ip_network(value, strict=False)
    except ValueError as e:
        raise argparse.ArgumentTypeError(
            f"{flag_name}: invalid IPv6 network '{value}': {e}"
        ) from e
    if not isinstance(net, ipaddress.IPv6Network):
        raise argparse.ArgumentTypeError(
            f"{flag_name}: '{value}' is not an IPv6 network (ribMap is IPv6-only)"
        )
    return net


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "FPF FSDB RibMap Viewer — fetch and parse bgp/ribMap from GTSWs. "
            "Also supports lightweight prefix-count tracker mode "
            "(--subnet-prefix / --exact-prefix [+ --track-forever])."
        )
    )
    parser.add_argument(
        "--gtsws",
        nargs="+",
        required=True,
        help="List of GTSW hostnames (e.g., gtsw001.l1002.c087.mwg2)",
    )
    parser.add_argument(
        "--mode",
        choices=list(FSDB_PATHS.keys()),
        default="ribmap",
        help=(
            "FSDB path to query: 'ribmap' for bgp/ribMap (legacy), "
            "'canonical' for bgp/canonicalRib (new). Default: ribmap."
        ),
    )

    # Tracker mode (mutually exclusive: subnet vs exact)
    tracker_group = parser.add_mutually_exclusive_group()
    tracker_group.add_argument(
        "--subnet-prefix",
        type=str,
        default=None,
        help=(
            "Count ribMap prefixes contained within this IPv6 supernet "
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
            "Count exact-match for this IPv6 prefix in ribMap (0 or 1) "
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
        help="Polling interval in seconds (default: 2.0). Only used with --track-forever.",
    )

    args = parser.parse_args()

    # Decide mode:
    #   - tracker mode  → --subnet-prefix or --exact-prefix set
    #   - viewer mode   → neither set (full dump + everpaste)
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
                mode=args.mode,
            )
        )
        return

    if args.track_forever:
        print(
            "ERROR: --track-forever requires --subnet-prefix or --exact-prefix",
            file=sys.stderr,
        )
        sys.exit(2)

    asyncio.run(run(args.gtsws, mode=args.mode))


if __name__ == "__main__":
    main()
