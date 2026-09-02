# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-strict

"""Deterministic churn target and prefix selection independent of hardware."""

from __future__ import annotations

import bisect
import ipaddress
import typing as t

from .observations import Block


def topology_prefix_at(
    *,
    start_prefix: str,
    prefix_step: int,
    count: int,
    excluded_indices: t.Sequence[int],
    row: int,
) -> str:
    if row < 0 or row >= count:
        raise ValueError(f"topology prefix row {row} is invalid")
    excluded = tuple(int(value) for value in excluded_indices)
    candidate = row
    for _ in range(len(excluded) + 2):
        adjusted = row + bisect.bisect_right(excluded, candidate)
        if adjusted == candidate:
            break
        candidate = adjusted
    else:
        raise ValueError(
            f"topology prefix row {row} did not converge around exclusions"
        )
    start = ipaddress.ip_address(start_prefix)
    return str(type(start)(int(start) + candidate * prefix_step))


def select_uniform_rows(row_count: int, count: int) -> tuple[int, ...]:
    if count < 2 or row_count < count:
        raise ValueError("selected block count must be between 2 and row count")
    return tuple((index * (row_count - 1)) // (count - 1) for index in range(count))


def sample_prefix_range(
    start: str,
    prefix_length: int,
    *,
    route_count: int,
    sample_count: int,
    concrete_last: str | None = None,
) -> tuple[str, ...]:
    if route_count != 750 or sample_count != 2:
        raise ValueError("CICD-EBB-10 geometry requires 750 routes and 2 samples")
    address = ipaddress.ip_address(start)
    stride = 1 << (address.max_prefixlen - prefix_length)
    last = (
        ipaddress.ip_address(concrete_last)
        if concrete_last is not None
        else address + ((route_count - 1) * stride)
    )
    if last.version != address.version or int(last) < int(address):
        raise ValueError(f"invalid concrete IXIA range {address} -> {last}")
    return (f"{address}/{prefix_length}", f"{last}/{prefix_length}")


def comparison_peers(
    blocks: t.Sequence[Block],
) -> dict[str, tuple[str, frozenset[str]]]:
    by_prefix: dict[str, dict[int, list[str]]] = {}
    for block in blocks:
        for prefix in block.prefixes:
            by_prefix.setdefault(prefix, {}).setdefault(block.plane, []).append(
                block.rib_peer
            )
    if not by_prefix:
        raise ValueError("no sampled comparison prefixes")
    comparisons: dict[str, tuple[str, frozenset[str]]] = {}
    expected_planes = {1, 2, 3, 4}
    for prefix, peers_by_plane in by_prefix.items():
        if set(peers_by_plane) != expected_planes:
            raise ValueError(
                f"{prefix}: comparison geometry requires planes 1-4; "
                f"got {sorted(peers_by_plane)}"
            )
        ambiguous = {
            plane: peers for plane, peers in peers_by_plane.items() if len(peers) != 1
        }
        if ambiguous:
            raise ValueError(
                f"{prefix}: expected exactly one sampled peer per plane; "
                f"got {ambiguous}"
            )
        peers = {plane: values[0] for plane, values in peers_by_plane.items()}
        if len(set(peers.values())) != 4:
            raise ValueError(
                f"{prefix}: sampled comparison peers must be distinct; got {peers}"
            )
        comparisons[prefix] = (
            peers[1],
            frozenset(peers[plane] for plane in (2, 3, 4)),
        )
    return comparisons


def sample_prefixes_by_family(
    prefixes: t.Iterable[str], *, maximum_per_family: int = 4
) -> list[str]:
    candidates: dict[int, list[tuple[int, int, str]]] = {4: [], 6: []}
    for prefix in prefixes:
        network = ipaddress.ip_network(prefix)
        family = candidates[network.version]
        bisect.insort(
            family,
            (int(network.network_address), network.prefixlen, prefix),
        )
        if len(family) > maximum_per_family:
            family.pop()
    return [item[2] for version in (4, 6) for item in candidates[version]]


def summarize_rows(rows: t.Sequence[int]) -> t.Mapping[str, object]:
    ranges: list[dict[str, int]] = []
    for row in sorted(rows):
        if not ranges or row > ranges[-1]["end"] + 1:
            ranges.append({"start": row, "end": row})
        else:
            ranges[-1]["end"] = row
    return {
        "count": len(rows),
        "total_ranges": len(ranges),
        "reported_ranges": min(len(ranges), 10),
        "ranges": ranges[:10],
        "truncated": len(ranges) > 10,
    }
