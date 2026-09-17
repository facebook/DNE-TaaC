#!/usr/bin/env python3
# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""ECMP CSV generator — IXIA add-path (prefix, next-hop) upload files.

ECMP ONLY. Unlike ``dlb_csvs/gen_dlb_csv.py`` there is no DLB super-group / ARS
/ spillover machinery and no community sidecar (the ECMP-only configs use a
PERMIT-ALL ingress policy, so routes install without gating).

Platform-agnostic: call ``gen_for_profile_pool(profile, pool)`` and the sizing
comes from ``ECMP_RESOURCE_PROFILES[asic]`` with addressing from an
``EcmpNhPool``. The module-level ``MAX_*`` constants are only defaults for the
``__main__`` CLI and happen to carry the KO3/G200 numbers.

The CSV row model (matches the IXIA sample + the DLB CSVs): full 8-hextet IPv6,
no leading zeros, no ``::`` compression. Header ``Address,Ipv6 Next Hop``.
Semantics enforced by ``ixia/taac_ixia.py::apply_pool_mutations``:
  * every data row is one ECMP MEMBER (prefix -> next-hop)  -> members = row count
  * rows sharing an Address are one ECMP GROUP of that width -> width = rows/prefix
  * a GROUP is a prefix with a DISTINCT next-hop set        -> groups = unique
    prefixes with unique NH sets (FBOSS `EcmpResourceManager` dedups prefixes
    that share an identical NH set into ONE group).

Per-platform budgets live in ``ECMP_RESOURCE_PROFILES`` in
``playbooks/dlb_platform_constants.py``; each entry supplies max ECMP groups,
max ECMP members (sum of widths across all groups), max group width, and the
device-wide unique-NH cap. Example (KO3 / G200): 768 / 13,629 / 128 / 500.

The unique-NH cap is the reason we generate CSVs instead of a formulaic
sliding-window ``CustomNetworkGroupConfig``: 768 DISTINCT groups cannot be
built from a step-1 sliding window over 500 NHs (a linear window yields only
``500 - width + 1`` distinct sets, < 768). We instead draw each group as a
DISTINCT SUBSET of a fixed pool, so unique-NH count is bounded by the pool size
regardless of width or group count, and NHs are reused across groups.

Anchor-pair construction (deterministic, provably drop-safe)
------------------------------------------------------------
The pool splits into a small ANCHOR range ``{0..anchor_count-1}`` and a BODY
range ``{anchor_count..pool_size-1}``. Each group gets:
  * a UNIQUE pair of anchors (``C(anchor_count, 2)`` distinct pairs), and
  * a filler body drawn from the body range (body may be reused across groups).
The unique anchor pair is the group's fingerprint, which gives two guarantees
that random subsets only give probabilistically:
  * distinctness: two groups differ in at least one anchor, so their NH sets
    differ even if their bodies coincide.
  * drop-robustness: dropping any single NH cannot make two groups identical.
    A valid group has exactly 2 anchors; dropping a body NH keeps the unique
    pair, and dropping an anchor leaves a 1-anchor set that matches no valid
    2-anchor group. This matters for resource tests that randomly withdraw NHs
    -- a collision would masquerade as a silicon dedup result.

Outputs (default ``./csv``):
  ecmp_max_groups.csv  maximize the GROUP table: 768 groups, widths balanced to
                       the member cap (18/17 -> exactly 13,629 members).
  ecmp_max_width.csv   maximize per-group WIDTH: width 128, groups = member cap
                       // 128 with a smaller final group (106x128 + 1x61 ->
                       exactly 13,629 members, 107 groups).

Usage:
  python3 gen_ecmp_csv.py                       # defaults: 768 groups / 13629 members / 128 width / 500 NHs
  python3 gen_ecmp_csv.py --pool 500 --out /path/to/dir
"""

import argparse
import csv
import ipaddress
import itertools
import os
from typing import Optional

# ---- Default addressing (KO3 Main ECMP pool on the rogue port) ----
# Kept as module constants so the leaf generator has no TAAC deps. Callers with
# an NhPool should use the ``*_for_pool`` wrappers (see ``ecmp_nh_pools.py``).
NH_NETWORK = "2401:db00:206a:1"  # rogue-port NH /64 (the NDP pool lives here)
NH_HOST_START = 0xA001  # first NH host -> ::a001
PREFIX_BASE = "5000:dd::"  # advertised ECMP prefixes -> 5000:dd:0:N::

# KO3 (G200) silicon budget — mirrored here as generator defaults. The source of
# truth is ECMP_RESOURCE_PROFILES[EcmpAsic.G200] in dlb_platform_constants.py.
MAX_GROUPS = 768
MAX_MEMBERS = 13629
MAX_WIDTH = 128
MAX_UNIQUE_NHS = 500

# Body-window stride: any value coprime with the body-range length spreads the
# per-group body across the whole body range (maximizing unique-NH usage toward
# the pool cap). Body choice does NOT affect correctness -- the anchor pair
# carries distinctness and drop-robustness -- so this only tunes how many body
# NHs get touched.
#
# The body range is ``pool_size - anchor_count``, and ``anchor_count`` grows
# with the group count, so coprimality has to be checked per (pool_size, groups)
# pair. Worked examples:
#   G200  768 groups -> anchors 40, body 460  gcd(37,460)=1  -> all 500 NHs used
#   TH4  1536 groups -> anchors 56, body 456  gcd(37,456)=1  -> all 512 NHs used
# A pool_size of 500 at 1536 groups would give body 444 = 2^2*3*37, sharing the
# factor 37 and collapsing the window to 12 distinct offsets (only 368 of 500
# NHs touched). If a new platform's unique-NH count comes out well below its
# pool size, this is why -- adjust pool_size rather than the stride.
_BODY_STRIDE = 37


def fmt(addr: str) -> str:
    """Full 8-hextet, no leading zeros, no ``::`` -- matches the IXIA upload sample."""
    return ":".join(
        f"{int(g, 16):x}" for g in ipaddress.IPv6Address(addr).exploded.split(":")
    )


def nh(i: int, network: str = NH_NETWORK, host_start: int = NH_HOST_START) -> str:
    """i-th next-hop address within ``network``, starting at ``host_start``."""
    return fmt(f"{network}::{host_start + i:x}")


def prefix(n: int, prefix_base: str = PREFIX_BASE) -> str:
    """n-th advertised prefix: ``{prefix_base}:0:n::`` (accepts base with/without ``::``)."""
    base = prefix_base.rstrip(":")
    return fmt(f"{base}:0:{n:x}::")


def write_csv(path: str, rows) -> int:
    # lineterminator="\n": csv.writer defaults to CRLF; the TAAC injector re-chunks
    # server-side treating "\n" as the row separator, so keep the source LF-only.
    with open(path, "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["Address", "Ipv6 Next Hop"])
        w.writerows(rows)
    return len(rows)


def anchor_count_for(num_groups: int) -> int:
    """Smallest ``m`` such that ``C(m, 2) >= num_groups`` (distinct anchor pairs)."""
    m = 2
    while m * (m - 1) // 2 < num_groups:
        m += 1
    return m


def gen_anchored(
    widths,
    pool_size: int = MAX_UNIQUE_NHS,
    nh_network: str = NH_NETWORK,
    nh_host_start: int = NH_HOST_START,
    prefix_base: str = PREFIX_BASE,
    anchor_count: Optional[int] = None,
):
    """Emit one distinct, drop-safe ECMP group per entry in ``widths``.

    ``widths[g]`` is the width (member count) of group ``g``; each width must be
    ``>= 2`` (2 anchors + body). All NH indices are drawn from ``range(pool_size)``,
    so the union of unique NHs is bounded by ``pool_size``.
    """
    n = len(widths)
    if anchor_count is None:
        anchor_count = anchor_count_for(n)
    if anchor_count * (anchor_count - 1) // 2 < n:
        raise ValueError(
            f"anchor_count={anchor_count} yields only "
            f"{anchor_count * (anchor_count - 1) // 2} pairs for {n} groups"
        )
    if anchor_count >= pool_size:
        raise ValueError(f"anchor_count={anchor_count} >= pool_size={pool_size}")

    body_pool = list(range(anchor_count, pool_size))
    body_len_pool = len(body_pool)
    pairs = itertools.combinations(range(anchor_count), 2)
    rows = []
    for g, w in enumerate(widths):
        if w < 2:
            raise ValueError(f"group {g}: anchored width {w} < 2")
        body_len = w - 2
        if body_len > body_len_pool:
            raise ValueError(
                f"group {g}: needs {body_len} body NHs but pool has {body_len_pool}"
            )
        a1, a2 = next(pairs)
        base = (g * _BODY_STRIDE) % body_len_pool
        body = [body_pool[(base + k) % body_len_pool] for k in range(body_len)]
        for i in (a1, a2, *body):  # w distinct NHs (anchors disjoint from body)
            rows.append((prefix(g, prefix_base), nh(i, nh_network, nh_host_start)))
    return rows


def widths_max_groups(
    groups: int = MAX_GROUPS,
    member_cap: int = MAX_MEMBERS,
    max_width: int = MAX_WIDTH,
):
    """Balanced per-group widths for the GROUP-table-maximizing CSV.

    Distributes ``member_cap`` members across exactly ``groups`` groups so widths
    differ by at most 1 and sum to ``member_cap`` (e.g. 13629/768 -> 573x18 +
    195x17). Each width lands in ``[2, max_width]``.
    """
    base, rem = divmod(member_cap, groups)
    if base < 2:
        raise ValueError(f"member_cap/groups = {base} < 2 (anchored width floor)")
    if base + 1 > max_width:
        raise ValueError(f"balanced width {base + 1} exceeds max_width {max_width}")
    return [base + 1] * rem + [base] * (groups - rem)


def widths_max_width(member_cap: int = MAX_MEMBERS, width: int = MAX_WIDTH):
    """Per-group widths for the WIDTH-maximizing CSV.

    Fills full ``width``-wide groups until the member budget is exhausted, with a
    smaller final group for the remainder (e.g. 13629 @ 128 -> 106x128 + 1x61).
    """
    full, rem = divmod(member_cap, width)
    widths = [width] * full
    if rem == 1:
        raise ValueError(
            f"remainder width 1 (< 2) for member_cap={member_cap}, width={width}"
        )
    if rem >= 2:
        widths.append(rem)
    return widths


# ---------------------------------------------------------------------------
# NhPool convenience wrappers. Duck-type the pool (``size``, ``nh_network``,
# ``nh_host_start``, ``prefix_base``) to avoid importing the pool type here and
# keep this module a dependency-free leaf.
# ---------------------------------------------------------------------------
def gen_max_groups_for_pool(
    pool, groups=MAX_GROUPS, member_cap=MAX_MEMBERS, max_width=MAX_WIDTH
):
    """GROUP-maximizing CSV rows parameterized from an NhPool."""
    return gen_anchored(
        widths_max_groups(groups, member_cap, max_width),
        pool_size=pool.size,
        nh_network=pool.nh_network,
        nh_host_start=pool.nh_host_start,
        prefix_base=pool.prefix_base,
    )


def gen_max_width_for_pool(pool, member_cap=MAX_MEMBERS, width=MAX_WIDTH):
    """WIDTH-maximizing CSV rows parameterized from an NhPool."""
    return gen_anchored(
        widths_max_width(member_cap, width),
        pool_size=pool.size,
        nh_network=pool.nh_network,
        nh_host_start=pool.nh_host_start,
        prefix_base=pool.prefix_base,
    )


def gen_for_profile_pool(profile, pool):
    """Profile-driven generation: ``{"max_groups": rows, "max_width": rows}``.

    Sizing (groups / members / width / unique-NH cap) comes from an ECMP profile
    (duck-typed: ``max_ecmp_groups`` / ``max_ecmp_members`` / ``max_group_width``
    / ``max_unique_next_hops`` -- i.e. ``ECMP_RESOURCE_PROFILES[asic]``), and
    addressing from an NhPool (``nh_network`` / ``nh_host_start`` /
    ``prefix_base``). This is the entry the KO3 testconfig uses so caps are never
    hardcoded here. ``pool.size`` (if present) must match the profile's unique-NH
    cap.
    """
    if (
        getattr(pool, "size", profile.max_unique_next_hops)
        != profile.max_unique_next_hops
    ):
        raise ValueError(
            f"pool.size={pool.size} != profile.max_unique_next_hops="
            f"{profile.max_unique_next_hops}"
        )
    kwargs = {
        "pool_size": profile.max_unique_next_hops,
        "nh_network": pool.nh_network,
        "nh_host_start": pool.nh_host_start,
        "prefix_base": pool.prefix_base,
    }
    return {
        "max_groups": gen_anchored(
            widths_max_groups(
                profile.max_ecmp_groups,
                profile.max_ecmp_members,
                profile.max_group_width,
            ),
            **kwargs,
        ),
        "max_width": gen_anchored(
            widths_max_width(profile.max_ecmp_members, profile.max_group_width),
            **kwargs,
        ),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--out",
        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "csv"),
    )
    ap.add_argument("--groups", type=int, default=MAX_GROUPS)
    ap.add_argument("--members", type=int, default=MAX_MEMBERS)
    ap.add_argument("--width", type=int, default=MAX_WIDTH)
    ap.add_argument("--pool", type=int, default=MAX_UNIQUE_NHS)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    jobs = {
        # Maximize the GROUP table: all 768 groups, widths balanced (18/17) so
        # members hit exactly the 13,629 cap. Fills groups AND members at once.
        "ecmp_max_groups.csv": gen_anchored(
            widths_max_groups(a.groups, a.members, a.width), pool_size=a.pool
        ),
        # Maximize per-group WIDTH: 128-wide groups until the member cap is spent
        # (106x128 + 61 = 13,629 -> 107 groups).
        "ecmp_max_width.csv": gen_anchored(
            widths_max_width(a.members, a.width), pool_size=a.pool
        ),
    }
    for name, rows in jobs.items():
        n = write_csv(os.path.join(a.out, name), rows)
        groups = len({r[0] for r in rows})
        nhs = len({r[1] for r in rows})
        print(f"{name:22s} rows={n:>7d}  groups={groups:>4d}  unique_nh={nhs:>4d}")
    print(
        f"\nWrote to {a.out}  (ECMP only; anchor-pair distinct subsets, pool={a.pool})"
    )


if __name__ == "__main__":
    main()
