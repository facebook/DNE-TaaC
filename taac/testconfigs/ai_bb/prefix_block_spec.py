# Copyright (c) Meta Platforms, Inc. and affiliates.

"""Declarative prefix-set specs -> universal IXIA injection CSV.

A prefix set is described by the same columns used to review it:

    root prefix | root mask | contiguous blocks | parent mask per block |
    prefixes per block | individual prefix length | prefix type

One ``PrefixBlockSpec`` is one row of that table. A role (ETSW, GTSW, STSW, ...)
is just a list of them, and any list renders to a single CSV that the TAAC
injector loads into one network group -- mixed mask lengths included, because
``Ipv6PrefixPools.PrefixLength`` is a Multivalue and accepts a per-row
ValueList.

Geometry, all derived (never hand-written):

    slot   = 2^(128 - prefix_length)     one advertised prefix
    parent = 2^(128 - parent_mask)       one contiguous block's container
    block b starts at   root + b * parent
    prefix p sits at    block_start + p * slot

So ``prefixes_per_block`` slots are filled from the start of each parent and the
remainder is a gap. That single rule reproduces every shape we need:

- dense run with a gap   -> prefixes_per_block < slots_per_parent
- fully dense            -> prefixes_per_block == slots_per_parent
- scattered singletons   -> prefixes_per_block == 1, parent_mask << prefix_length

Because the CSV carries explicit addresses, placement is exact. Generating the
same shapes with IxNetwork's INCREMENT pattern does not work: it overrides the
configured step with the natural prefix-size increment, which silently collapses
"19 singleton /46s in separate /44s" into "19 consecutive /46s".

CSV contract (consumed by ``TaacIxia._mutate_pool_config_only``):

    Address,PrefixLength,Ipv6 Next Hop,PrefixType

``Address`` is full 8-hextet with no ``::`` compression and no leading zeros.
``PrefixType`` is ignored by the injector and kept for review. Columns are
resolved by header name, and omitting ``PrefixLength`` preserves the historical
/64-only behaviour.
"""

import csv
import ipaddress
import os
import tempfile
import typing as t
from dataclasses import dataclass


def _atomic_write_rows(
    path: str, header: t.Sequence[str], rows: t.Iterable[t.Sequence[t.Any]]
) -> str:
    """Write a CSV to ``path`` atomically.

    Rendering straight into the destination lets two processes that picked the
    same path truncate each other's file mid-write, and leaves a half-written
    CSV behind if the writer dies. Render to a unique temp file in the same
    directory and ``os.replace`` it into place instead, so a reader either sees
    the previous complete file or the new complete file and never a partial one.

    LF line endings are mandatory: the injector re-chunks server-side treating
    ``\n`` as the row separator, so csv's default CRLF corrupts the upload.
    """
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=directory, prefix=f".{os.path.basename(path)}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", newline="") as f:
            writer = csv.writer(f, lineterminator="\n")
            writer.writerow(header)
            for row in rows:
                writer.writerow(row)
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    return path


@dataclass(frozen=True)
class PrefixBlockSpec:
    """One row of the prefix inventory table."""

    root: str
    root_mask: int
    blocks: int
    parent_mask: int
    prefixes_per_block: int
    prefix_length: int
    prefix_type: str

    def __post_init__(self) -> None:
        if not 0 < self.root_mask <= self.parent_mask <= self.prefix_length <= 128:
            raise ValueError(
                f"{self.prefix_type}: need root_mask <= parent_mask <= "
                f"prefix_length, got /{self.root_mask} /{self.parent_mask} "
                f"/{self.prefix_length}"
            )
        if self.prefixes_per_block > self.slots_per_block:
            raise ValueError(
                f"{self.prefix_type}: {self.prefixes_per_block} prefixes do not "
                f"fit in a /{self.parent_mask} "
                f"({self.slots_per_block} x /{self.prefix_length} slots)"
            )
        if self.blocks > self.max_blocks:
            raise ValueError(
                f"{self.prefix_type}: {self.blocks} blocks of /{self.parent_mask} "
                f"do not fit in /{self.root_mask} (max {self.max_blocks})"
            )

    @property
    def slot_size(self) -> int:
        return 1 << (128 - self.prefix_length)

    @property
    def parent_size(self) -> int:
        return 1 << (128 - self.parent_mask)

    @property
    def slots_per_block(self) -> int:
        """How many prefixes fit in one block's parent container."""
        return 1 << (self.prefix_length - self.parent_mask)

    @property
    def max_blocks(self) -> int:
        """How many parent containers fit under the root."""
        return 1 << (self.parent_mask - self.root_mask)

    @property
    def gap_per_block(self) -> int:
        """Unused slots at the tail of each block."""
        return self.slots_per_block - self.prefixes_per_block

    @property
    def total(self) -> int:
        return self.blocks * self.prefixes_per_block

    def prefixes(self) -> t.Iterator[str]:
        base = int(ipaddress.IPv6Address(self.root))
        for b in range(self.blocks):
            block_start = base + b * self.parent_size
            for p in range(self.prefixes_per_block):
                yield format_ipv6_full(
                    ipaddress.IPv6Address(block_start + p * self.slot_size)
                )


def format_ipv6_full(addr: ipaddress.IPv6Address) -> str:
    """Full 8-hextet form, no ``::`` compression, no leading zeros."""
    return ":".join(f"{int(group, 16):x}" for group in addr.exploded.split(":"))


def nexthop_pool(base: str, count: int, step: int = 1) -> t.List[str]:
    """``count`` consecutive next-hop addresses starting at ``base``."""
    start = int(ipaddress.IPv6Address(base))
    return [
        format_ipv6_full(ipaddress.IPv6Address(start + i * step)) for i in range(count)
    ]


def write_injection_csv(
    path: str,
    specs: t.Sequence[PrefixBlockSpec],
    next_hop: t.Union[str, t.Sequence[str]],
    pair_nexthops: bool = False,
) -> str:
    """Render specs to the universal injection CSV.

    ``next_hop`` may be a single address (one row per prefix) or a list of N
    addresses, in which case each prefix is emitted N times -- once per
    next-hop. Rows sharing an Address form one add-path group, and the injector
    derives ``MvNextHopCount = total_rows / distinct_prefixes`` from that, so a
    list of 45 gives every prefix 45 advertised paths.

    Every next-hop must be NDP-resolvable on the DUT or the paths are dropped;
    pair this with an NDP-supporting device group covering the same pool.

    LF line endings are mandatory: the injector re-chunks server-side treating
    ``\\n`` as the row separator, so csv's default CRLF corrupts the upload.
    """
    next_hops: t.Sequence[str] = (
        [next_hop] if isinstance(next_hop, str) else list(next_hop)
    )
    if not next_hops:
        raise ValueError("next_hop must not be empty")

    def _rows() -> t.Iterator[t.List[t.Any]]:
        idx = 0
        for spec in specs:
            for prefix in spec.prefixes():
                if pair_nexthops:
                    # One row per prefix, cycling through the next-hop pool.
                    # Used to isolate whether IxNetwork's next-hop ValueList is
                    # broken by REPEATED addresses or merely by a large
                    # multiplier: this keeps every address unique.
                    yield [
                        prefix,
                        spec.prefix_length,
                        next_hops[idx % len(next_hops)],
                        spec.prefix_type,
                    ]
                    idx += 1
                else:
                    for nh in next_hops:
                        yield [prefix, spec.prefix_length, nh, spec.prefix_type]

    return _atomic_write_rows(
        path, ["Address", "PrefixLength", "Ipv6 Next Hop", "PrefixType"], _rows()
    )


def write_block_injection_csv(
    path: str,
    specs: t.Sequence[PrefixBlockSpec],
    next_hop: t.Union[str, t.Sequence[str]],
) -> str:
    """Render specs as ONE ROW PER BLOCK instead of one row per prefix.

    A block of N contiguous prefixes is fully described by its first address,
    a count, and a step -- so the whole block collapses to a single row and
    IxNetwork expands it via ``Ipv6PrefixPools.NumberOfAddresses`` +
    ``PrefixAddrStep``. For the ETSW set that is 288 rows instead of 69,120,
    a 240x reduction:

        69,120 prefixes x 45 next-hops = 3,111,255 rows  (~195 MB)
           288 blocks   x 45 next-hops =    12,960 rows  (~0.9 MB)

    That matters because the IXIA port CPU refuses oversized route configs
    ("Port <x> is not CPU ready"), and row count is what drives it.

    CONSTRAINT: ``NumberOfAddresses`` is a scalar on the pool, not a
    Multivalue, so every row in one pool must carry the SAME count. Specs with
    differing ``prefixes_per_block`` therefore cannot share a pool and are
    rejected here rather than silently mis-expanding. (``PrefixAddrStep`` IS a
    Multivalue, so per-row steps are fine.)

    CSV contract:

        Address,PrefixLength,AddressCount,AddressStep,Ipv6 Next Hop,PrefixType

    ``Address`` is the first prefix of the block, ``AddressCount`` how many
    prefixes it expands to, and ``AddressStep`` the gap between them expressed
    as a NUMBER in units of the prefix size -- NOT an IPv6 address.
    ``Ipv6PrefixPools.PrefixAddrStep`` rejects an address literal with
    "Value <x> is not number". A contiguous run of /64s is step 1.
    """
    next_hops: t.Sequence[str] = (
        [next_hop] if isinstance(next_hop, str) else list(next_hop)
    )
    if not next_hops:
        raise ValueError("next_hop must not be empty")

    counts = {sp.prefixes_per_block for sp in specs}
    if len(counts) > 1:
        raise ValueError(
            "Ipv6PrefixPools.NumberOfAddresses is pool-wide, so all specs "
            f"written to one CSV must share prefixes_per_block; got {sorted(counts)}. "
            "Split them into separate pools."
        )

    def _rows() -> t.Iterator[t.List[t.Any]]:
        for spec in specs:
            # Blocks are contiguous runs of `prefix_length`-sized prefixes, so
            # the step is 1 prefix. Kept as a column for generality.
            step = 1
            base = int(ipaddress.IPv6Address(spec.root))
            for b in range(spec.blocks):
                start = format_ipv6_full(
                    ipaddress.IPv6Address(base + b * spec.parent_size)
                )
                for nh in next_hops:
                    yield [
                        start,
                        spec.prefix_length,
                        spec.prefixes_per_block,
                        step,
                        nh,
                        spec.prefix_type,
                    ]

    return _atomic_write_rows(
        path,
        [
            "Address",
            "PrefixLength",
            "AddressCount",
            "AddressStep",
            "Ipv6 Next Hop",
            "PrefixType",
        ],
        _rows(),
    )


def describe(specs: t.Sequence[PrefixBlockSpec]) -> str:
    """Render the specs back as the review table."""
    header = (
        f"{'root':<10} {'rootmask':>8} {'blocks':>7} {'parent':>7} "
        f"{'per blk':>8} {'prefixlen':>9} {'total':>8}  type"
    )
    lines = [header, "-" * len(header)]
    for s in specs:
        lines.append(
            f"{s.root:<10} {'/' + str(s.root_mask):>8} {s.blocks:>7} "
            f"{'/' + str(s.parent_mask):>7} {s.prefixes_per_block:>8} "
            f"{'/' + str(s.prefix_length):>9} {s.total:>8}  {s.prefix_type}"
        )
    lines.append(
        f"{'':<10} {'':>8} {sum(s.blocks for s in specs):>7} {'':>7} {'':>8} "
        f"{'':>9} {sum(s.total for s in specs):>8}  TOTAL"
    )
    return "\n".join(lines)


# =============================================================================
# UFv2 ETSW -- the prefixes an ETSW receives via BGP
# =============================================================================
# Source: "[DCXOR] Backend LLD for UFv2 in DC-TypeG" -- IP Addressing
# ("Proposed UFv2 load-bearing hierarchy"), Scale Numbers ("ETSW Scale (TH6)").
#
# Only RECEIVED prefixes belong on the IXIA. The /56 VF-group summaries and the
# own-L2 /46 are ORIGINATED by the ETSW, and the /127 + /128 infra are connected
# routes -- none of those are injectable over BGP.
ETSW_RECEIVED_SPECS: t.List[PrefixBlockSpec] = [
    # 144 GSLs x 2 VF groups = 288 blocks, 240 of each /56's 256 slots used.
    PrefixBlockSpec(
        root="6000::",
        root_mask=46,
        blocks=288,
        parent_mask=56,
        prefixes_per_block=240,
        prefix_length=64,
        prefix_type="vf_gpu",
    ),
    # 19 remote L2 aggregates, each its own /46 in a separate /44 building
    # block -- 19 singleton blocks, not one contiguous run.
    #
    # Root is /39, not the /40 metro: a /40 holds only 16 /44 buildings and we
    # need 19, so the remote L2s necessarily span more than one metro block.
    PrefixBlockSpec(
        root="6100::",
        root_mask=39,
        blocks=19,
        parent_mask=44,
        prefixes_per_block=1,
        prefix_length=46,
        prefix_type="remote_l2_agg",
    ),
]


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Render prefix specs to CSV")
    parser.add_argument("--out", default="/tmp/etsw_csvs/etsw_injection.csv")
    parser.add_argument("--next-hop", default="2401:db00:206a:c000:0:0:0:b")
    args = parser.parse_args()

    print(describe(ETSW_RECEIVED_SPECS))
    out = write_injection_csv(args.out, ETSW_RECEIVED_SPECS, args.next_hop)
    with open(out) as fh:
        rows = sum(1 for _ in fh) - 1
    print(f"\nwrote {out}: {rows} rows")
