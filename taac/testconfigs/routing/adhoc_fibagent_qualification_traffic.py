# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

"""One-off BAG013 traffic qualification for the EBB16 NHG storm."""

from taac.abstractions.physical_inventory import BAG013_ASH6
from taac.abstractions.topologies.ebb16_ebbfs_with_traffic import (
    ebb16_ebbfs_with_traffic_topology,
    EBB16_PREFIX_CONTINUITY_TRAFFIC_ITEMS,
)
from taac.abstractions.topologies.ebb_full_scale import (
    EBB_FULL_SCALE_PORT_MAP_WITH_BGPMON,
    EBB_NEXT_HOPS,
    EBB_PARENT_NETWORKS,
)
from taac.abstractions.topology import OpenRMode
from taac.constants import BgpPlusPlusProfile
from taac.playbooks.routing.bgp_ebb_traffic_playbooks import (
    get_bgp_ebb_nexthop_group_count_threshold_traffic_playbook,
)
from taac.testconfigs.routing.factories.bgp_ebb_full_scale import (
    create_bgp_ebb_full_scale_test_config,
)
from taac.test_as_a_config.types import TestConfig


def _build_bag013_ebb16_traffic_test_config() -> TestConfig:
    topology = ebb16_ebbfs_with_traffic_topology(
        openr_mode=OpenRMode.STANDALONE,
        include_bgpmon=True,
        next_hops=EBB_NEXT_HOPS,
        traffic_line_rate_percent=10,
    )
    control_plane = create_bgp_ebb_full_scale_test_config(
        BAG013_ASH6,
        name="BAG013_EBB16_FIBAGENT_QUALIFICATION_TRAFFIC_TEMP",
        playbooks_selected=["bgp_ebb_nexthop_group_count_threshold_playbook"],
        profile=BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R,
        enable_update_group=False,
        parent_networks=EBB_PARENT_NETWORKS,
        next_hops=EBB_NEXT_HOPS,
        port_map=EBB_FULL_SCALE_PORT_MAP_WITH_BGPMON,
        nhg_storm_epoch_count=48,
        nhg_storm_epoch_interval_seconds=25,
        nhg_storm_soak_seconds=300,
        nhg_storm_poll_interval_seconds=5,
        nhg_storm_target_membership_width=25,
        nhg_storm_control_plane_sample_interval_seconds=5,
        topology_override=topology,
    )
    if len(control_plane.playbooks) != 1:
        raise ValueError(
            "EBB16 traffic qualification requires one control-plane playbook"
        )
    return control_plane(
        playbooks=[
            get_bgp_ebb_nexthop_group_count_threshold_traffic_playbook(
                control_plane.playbooks[0],
                traffic_item_names=EBB16_PREFIX_CONTINUITY_TRAFFIC_ITEMS,
            )
        ],
    )


BAG013_EBB16_FIBAGENT_QUALIFICATION_TRAFFIC_TEMP = (
    _build_bag013_ebb16_traffic_test_config()
)
