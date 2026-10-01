# Copyright (c) Meta Platforms, Inc. and affiliates.

from __future__ import annotations

import typing as t
from dataclasses import replace

from taac.abstractions.topologies.ebb_full_scale import (
    ebb_full_scale_topology,
    EBB_NEXT_HOPS,
    EbbNextHopScheme,
)
from taac.abstractions.topology import (
    LogicalTopology,
    OpenRMode,
    PrefixAdvertisement,
    PrefixSet,
    TaskCompatibilityProfile,
    TrafficFlowSpec,
)

EBB16_IPV4_PREFIX_CONTINUITY_TRAFFIC_ITEM = "EBB16_IPV4_PREFIX_CONTINUITY"
EBB16_IPV6_PREFIX_CONTINUITY_TRAFFIC_ITEM = "EBB16_IPV6_PREFIX_CONTINUITY"
EBB16_PREFIX_CONTINUITY_TRAFFIC_ITEMS = (
    EBB16_IPV4_PREFIX_CONTINUITY_TRAFFIC_ITEM,
    EBB16_IPV6_PREFIX_CONTINUITY_TRAFFIC_ITEM,
)


def ebb16_ebbfs_with_traffic_topology(
    *,
    openr_mode: OpenRMode,
    include_bgpmon: bool = True,
    ebgp_graceful_restart: bool = True,
    next_hop_self: bool = False,
    include_legacy_community_rows: bool = True,
    ebgp_prefix_count: int = 750,
    ebgp_static_prefix_count: int | None = None,
    extra_prefix_sets: tuple[PrefixSet, ...] = (),
    extra_advertisements: t.Mapping[str, tuple[PrefixAdvertisement, ...]] | None = None,
    next_hops: EbbNextHopScheme = EBB_NEXT_HOPS,
    route_storm_shards: bool = False,
    traffic_line_rate_percent: int = 1,
) -> LogicalTopology:
    """Return full-scale EBB with v4/v6 iBGP-to-eBGP continuity traffic."""
    if (
        isinstance(traffic_line_rate_percent, bool)
        or not isinstance(traffic_line_rate_percent, int)
        or not 1 <= traffic_line_rate_percent <= 10
    ):
        raise ValueError("EBB16 traffic line rate must be from 1% through 10%")
    return replace(
        ebb_full_scale_topology(
            openr_mode=openr_mode,
            include_bgpmon=include_bgpmon,
            ebgp_graceful_restart=ebgp_graceful_restart,
            next_hop_self=next_hop_self,
            include_legacy_community_rows=include_legacy_community_rows,
            ebgp_prefix_count=ebgp_prefix_count,
            ebgp_static_prefix_count=ebgp_static_prefix_count,
            extra_prefix_sets=extra_prefix_sets,
            extra_advertisements=extra_advertisements,
            next_hops=next_hops,
            route_storm_shards=route_storm_shards,
        ),
        name="ebb16_ebbfs_with_traffic",
        legacy_profile=None,
        task_compatibility_profile=(
            TaskCompatibilityProfile.EBB_FULL_SCALE_WITH_BGPMON
            if include_bgpmon
            else TaskCompatibilityProfile.EBB_FULL_SCALE_NO_BGPMON
        ),
        traffic_flows=(
            TrafficFlowSpec(
                name=EBB16_IPV4_PREFIX_CONTINUITY_TRAFFIC_ITEM,
                src_dg="dg_ibgp_v4_dc_p1",
                dst_dg="dg_ebgp_v4",
                traffic_profile="fibagent_qualification_traffic",
                rate_percent=traffic_line_rate_percent,
            ),
            TrafficFlowSpec(
                name=EBB16_IPV6_PREFIX_CONTINUITY_TRAFFIC_ITEM,
                src_dg="dg_ibgp_v6_dc_p1",
                dst_dg="dg_ebgp_v6",
                traffic_profile="fibagent_qualification_traffic",
                rate_percent=traffic_line_rate_percent,
            ),
        ),
    )
