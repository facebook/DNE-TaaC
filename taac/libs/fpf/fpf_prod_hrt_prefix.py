# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""Core reachability model for production HRT prefix monitoring.

Shared by the standalone collector binary
(``scripts/pavanpatil/fpf_prod_hrt_prefix_collector.py``) and the TAAC
``ProdHrtPrefixCollector``. Turns the three HRT thrift APIs
(``getPrefixTable`` / ``getRemoteFailures`` / ``getPlaneStatus``) into a
per-prefix reachability data class:

  - reachable_planes   : planes the prefix is programmed on and NOT drained/failed
  - drained_planes     : planes marked drained for the prefix
  - unreachable_planes : planes in remote-failure (negative route) for the prefix
  - plane_up           : planes whose getPlaneStatus PlaneState is UP
  - plane_down         : planes whose state is anything else (DRAINED / UNKNOWN)
  - device_ids         : GPU device_id(s) on the host carrying the prefix

Plane lists are unioned across the host's matching device entries.
"""

from dataclasses import dataclass, field


def normalize_prefix(prefix: str) -> str:
    return prefix.strip().lower()


def plane_state_name(state) -> str:
    """Return a stable string name for a PlaneState enum value."""
    name = getattr(state, "name", None)
    if name:
        return str(name)
    return str(state).split(".")[-1]


@dataclass
class PrefixReachability:
    """Per-prefix reachability snapshot aggregated across the host's devices."""

    reachable_planes: list[int] = field(default_factory=list)
    drained_planes: list[int] = field(default_factory=list)
    unreachable_planes: list[int] = field(default_factory=list)
    # Derived from plane state: plane_up = planes whose PlaneState is UP;
    # plane_down = planes whose state is anything else (DRAINED / UNKNOWN).
    plane_up: list[int] = field(default_factory=list)
    plane_down: list[int] = field(default_factory=list)
    # Which GPU device_ids on this host carry the prefix (for transparency).
    device_ids: list[int] = field(default_factory=list)


def build_plane_status_map(
    plane_status_entries,
    device_filter: set[int] | None,
) -> dict[int, dict[int, str]]:
    """device_id -> {plane_id -> PlaneState name} from getPlaneStatus()."""
    out: dict[int, dict[int, str]] = {}
    for e in plane_status_entries:
        dev = int(e.device_id)
        if device_filter is not None and dev not in device_filter:
            continue
        out.setdefault(dev, {})[int(e.plane_id)] = plane_state_name(e.state)
    return out


def build_prefix_map(
    prefixes,
    neg_routes,
    plane_status_entries,
    target_prefixes: set[str] | None,
    device_filter: set[int] | None,
) -> dict[str, PrefixReachability]:
    """Aggregate the three HRT API results into prefix -> PrefixReachability.

    When ``target_prefixes`` is None, every prefix returned by HRT is included.
    Plane lists are unioned across the host's matching device entries.
    """
    # Pre-index remote failures: (prefix, device_id) -> failed planes.
    failed_by_pfx_dev: dict[tuple[str, int], list[int]] = {}
    for nr in neg_routes:
        key = (normalize_prefix(nr.prefix), int(nr.device_id))
        failed_by_pfx_dev[key] = sorted(int(p) for p in nr.failed_planes)

    plane_status_by_dev = build_plane_status_map(plane_status_entries, device_filter)

    result: dict[str, PrefixReachability] = {}
    # Internal accumulator: prefix-key -> {plane_id -> PlaneState name}.
    # Used only to derive plane_up / plane_down; not emitted.
    ps_acc: dict[str, dict[int, str]] = {}
    for p in prefixes:
        norm = normalize_prefix(p.prefix)
        if target_prefixes is not None and norm not in target_prefixes:
            continue
        dev = int(p.device_id)
        if device_filter is not None and dev not in device_filter:
            continue

        entry = result.setdefault(p.prefix, PrefixReachability())
        if dev not in entry.device_ids:
            entry.device_ids.append(dev)

        failed = set(failed_by_pfx_dev.get((norm, dev), []))
        for pl in p.planes:
            pid = int(pl.plane_id)
            if pl.is_drained:
                if pid not in entry.drained_planes:
                    entry.drained_planes.append(pid)
            elif pid in failed:
                if pid not in entry.unreachable_planes:
                    entry.unreachable_planes.append(pid)
            else:
                if pid not in entry.reachable_planes:
                    entry.reachable_planes.append(pid)

        # Any failed plane not present in the prefix's plane list still counts
        # as unreachable for this prefix/device.
        for pid in failed:
            if (
                pid not in entry.unreachable_planes
                and pid not in entry.reachable_planes
            ):
                entry.unreachable_planes.append(pid)

        # Fold per-device plane status into the internal accumulator.
        acc = ps_acc.setdefault(p.prefix, {})
        for pid, state in plane_status_by_dev.get(dev, {}).items():
            existing = acc.get(pid)
            if existing is None:
                acc[pid] = state
            elif state not in existing.split("/"):
                acc[pid] = f"{existing}/{state}"

    # Ensure deterministic ordering and derive plane_up / plane_down from the
    # accumulated plane state (UP -> up; anything else, DRAINED/UNKNOWN -> down).
    for pfx, entry in result.items():
        entry.reachable_planes.sort()
        entry.drained_planes.sort()
        entry.unreachable_planes.sort()
        entry.device_ids.sort()
        acc = ps_acc.get(pfx, {})
        entry.plane_up = sorted(pid for pid, st in acc.items() if st == "UP")
        entry.plane_down = sorted(pid for pid, st in acc.items() if st != "UP")

    # Include explicitly-requested prefixes that HRT did not return at all, so
    # the entry is present (empty) rather than silently missing.
    if target_prefixes is not None:
        present = {normalize_prefix(k) for k in result}
        for tp in target_prefixes:
            if tp not in present:
                result[tp] = PrefixReachability()

    return result
