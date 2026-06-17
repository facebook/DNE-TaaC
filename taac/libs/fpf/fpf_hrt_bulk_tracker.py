#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""
FPF HRT Bulk Prefix Tracker

Continuously polls HRT getPrefixTable() on a GPU/BE-Node host and prints
a per-lane COUNT of prefixes (for a given device_id) that fall inside a
supernet you specify.

Example: if you inject 5000:dd:0::/64 ... 5000:dd:f::/64 (16 prefixes)
on gtsw001 and pass --supernet 5000:dd::/32, you'll see:

  timestamp                  L0  L1  L2  L3  L4  L5  L6  L7
  -------------------------  --  --  --  --  --  --  --  --
  2026-05-17 10:00:00-07:00  16   0   0   0   0   0   0   0
  2026-05-17 10:00:02-07:00  16   0   0   0   0   0   0   0
  ...

Output structure mirrors the single-prefix tracker in
`fpf_hrt_client --prefix-tracker` but aggregates COUNT across all subnet
matches, broken down by lane.

Usage:
  buck2 run fbcode//scripts/pavanpatil:fpf_hrt_bulk_tracker -- \\
    --host rtptest1544.mwg2 \\
    --device-id 0 \\
    --supernet 5000:dd::/32

  # Poll every 2s, exit after 5 minutes, print every poll (not just changes)
  buck2 run fbcode//scripts/pavanpatil:fpf_hrt_bulk_tracker -- \\
    --host rtptest1544.mwg2 \\
    --device-id 0 \\
    --supernet 5000:dd::/32 \\
    --interval-sec 2 --duration-sec 300 --print-every-poll
"""

import argparse
import asyncio
import ipaddress
import signal
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from neteng.netcastle.logger import get_root_logger
from taac.libs.fpf.fpf_hrt_polling import get_hrt_client


logger = get_root_logger()


NUM_LANES = 8


# ---------------------------------------------------------------------------
# Counting
# ---------------------------------------------------------------------------


def is_subnet(prefix_str: str, supernet: ipaddress.IPv6Network) -> bool:
    try:
        net = ipaddress.ip_network(prefix_str, strict=False)
    except ValueError:
        return False
    if not isinstance(net, ipaddress.IPv6Network):
        return False
    return net.subnet_of(supernet)


def count_per_lane(
    prefix_table,
    device_id: int,
    supernet: ipaddress.IPv6Network,
) -> Tuple[List[int], int]:
    """For each lane 0..NUM_LANES-1, count unique subnet-matching prefixes
    visible on that lane for the given device_id.

    Returns (counts_per_lane, total_unique_matches).
    """
    per_lane_seen: Dict[int, set] = {i: set() for i in range(NUM_LANES)}
    all_seen: set = set()
    for entry in prefix_table:
        if entry.device_id != device_id:
            continue
        if not is_subnet(entry.prefix, supernet):
            continue
        try:
            norm = str(ipaddress.ip_network(entry.prefix, strict=False))
        except Exception:
            continue
        all_seen.add(norm)
        for plane_info in entry.planes or []:
            pid = plane_info.plane_id
            if 0 <= pid < NUM_LANES:
                per_lane_seen[pid].add(norm)
    counts = [len(per_lane_seen[i]) for i in range(NUM_LANES)]
    return counts, len(all_seen)


def count_failed_per_lane(
    remote_failures,
    device_id: int,
    supernet: ipaddress.IPv6Network,
) -> Tuple[List[int], int]:
    """For each lane 0..NUM_LANES-1, count unique subnet-matching prefixes that
    are currently in a remote-failure (negative-route) state on that lane for
    the given device_id.

    ``remote_failures`` is the list returned by HRT ``getRemoteFailures()``;
    each entry has ``.prefix``, ``.device_id`` and ``.failed_planes`` (a list of
    plane ids the prefix is unreachable on). In stable state every lane count is
    0 (all planes available); after a drain the drained lane's count rises to
    the injected prefix count.

    Returns (counts_per_lane, total_unique_failed_matches).
    """
    per_lane_seen: Dict[int, set] = {i: set() for i in range(NUM_LANES)}
    all_seen: set = set()
    for entry in remote_failures:
        if entry.device_id != device_id:
            continue
        if not is_subnet(entry.prefix, supernet):
            continue
        try:
            norm = str(ipaddress.ip_network(entry.prefix, strict=False))
        except Exception:
            continue
        all_seen.add(norm)
        for pid in entry.failed_planes or []:
            if 0 <= pid < NUM_LANES:
                per_lane_seen[pid].add(norm)
    counts = [len(per_lane_seen[i]) for i in range(NUM_LANES)]
    return counts, len(all_seen)


# ---------------------------------------------------------------------------
# Polling loop
# ---------------------------------------------------------------------------


def now_str() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S%z")


def format_row(ts: str, counts: List[int], total: int) -> str:
    lane_cells = "  ".join(f"{c:>2d}" for c in counts)
    return f"  {ts}  {lane_cells}    [unique={total}]"


def print_header() -> None:
    print()
    lane_header = "  ".join(f"L{i}" for i in range(NUM_LANES))
    print(f"  {'timestamp':<25}  {lane_header}    [unique]")
    sep_cells = "  ".join("--" for _ in range(NUM_LANES))
    print(f"  {'-' * 25}  {sep_cells}    {'-' * 8}")


async def run_loop(
    host: str,
    device_id: int,
    supernet: ipaddress.IPv6Network,
    interval_sec: float,
    duration_sec: float,
    print_every_poll: bool,
) -> int:
    print_header()
    last_counts: Optional[List[int]] = None
    deadline = (
        asyncio.get_running_loop().time() + duration_sec if duration_sec > 0 else None
    )
    poll_idx = 0
    while True:
        poll_idx += 1
        try:
            client_ctx = await get_hrt_client(host)
            async with client_ctx as client:
                prefix_table = await client.getPrefixTable()
        except Exception as e:
            logger.error(f"[{host}] HRT poll #{poll_idx} failed: {e}")
            await asyncio.sleep(interval_sec)
            if deadline and asyncio.get_running_loop().time() >= deadline:
                return 1
            continue

        counts, total = count_per_lane(prefix_table, device_id, supernet)
        should_print = print_every_poll or counts != last_counts
        if should_print:
            print(format_row(now_str(), counts, total), flush=True)
            last_counts = counts

        if deadline and asyncio.get_running_loop().time() >= deadline:
            print(f"\nReached --duration-sec {duration_sec}; exiting.")
            return 0

        await asyncio.sleep(interval_sec)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--host",
        required=True,
        help="GPU/BE-Node host running HRT (e.g., rtptest1544.mwg2)",
    )
    parser.add_argument(
        "--device-id",
        type=int,
        default=0,
        help="HRT device_id (GPU index) to filter the prefix table by (default: 0)",
    )
    parser.add_argument(
        "--supernet",
        default="5000:dd::/32",
        help="IPv6 supernet to filter prefixes by — only prefixes that are "
        "subnets of this are counted (default: 5000:dd::/32)",
    )
    parser.add_argument(
        "--interval-sec",
        type=float,
        default=2.0,
        help="Poll interval in seconds (default: 2.0)",
    )
    parser.add_argument(
        "--duration-sec",
        type=float,
        default=0.0,
        help="Total duration in seconds; 0 = run until Ctrl-C (default: 0)",
    )
    parser.add_argument(
        "--print-every-poll",
        action="store_true",
        help="Print a row every poll. Default: only print when the per-lane "
        "counts change (state-change mode).",
    )
    return parser.parse_args()


async def amain(args: argparse.Namespace) -> int:
    try:
        supernet = ipaddress.ip_network(args.supernet, strict=False)
    except ValueError as e:
        logger.error(f"Bad --supernet {args.supernet!r}: {e}")
        return 2
    if not isinstance(supernet, ipaddress.IPv6Network):
        logger.error(f"--supernet must be IPv6, got {args.supernet!r}")
        return 2

    logger.info(
        f"Bulk-tracking HRT prefix table on {args.host} for device "
        f"{args.device_id}, supernet {supernet}, every "
        f"{args.interval_sec}s "
        f"({'forever' if args.duration_sec == 0 else f'for {args.duration_sec}s'})"
    )
    return await run_loop(
        host=args.host,
        device_id=args.device_id,
        supernet=supernet,
        interval_sec=args.interval_sec,
        duration_sec=args.duration_sec,
        print_every_poll=args.print_every_poll,
    )


def main() -> None:
    args = parse_args()

    def _sigint_handler(_signum, _frame):
        print("\nInterrupted by user.")
        sys.exit(130)

    signal.signal(signal.SIGINT, _sigint_handler)
    try:
        exit_code = asyncio.run(amain(args))
    except KeyboardInterrupt:
        exit_code = 130
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
