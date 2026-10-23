# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

"""Ad-hoc NRQEB009 traffic qualification for the EBB16 NHG storm.

Run on demand with ``--test-config``. It is deliberately kept out of
``cicd_ebb_int_tc.py``, the scheduled-only module that the ``dne_routing``
Conveyor nodes draw from.
"""

from taac.abstractions.physical_inventory import NRQEB009_ASH6
from taac.abstractions.topologies.ebb16_ebbfs_with_traffic import (
    ebb16_ebbfs_with_traffic_topology,
    EBB16_PREFIX_CONTINUITY_TRAFFIC_ITEMS,
)
from taac.abstractions.topologies.ebb_full_scale import (
    EBB_FULL_SCALE_PORT_MAP_WITH_BGPMON,
    EBB_NEXT_HOPS_IXIA03,
    EBB_PARENT_NETWORKS_IXIA03,
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


def _build_nrqeb009_ebb16_traffic_test_config() -> TestConfig:
    topology = ebb16_ebbfs_with_traffic_topology(
        openr_mode=OpenRMode.STANDALONE,
        include_bgpmon=True,
        next_hops=EBB_NEXT_HOPS_IXIA03,
        traffic_line_rate_percent=10,
    )
    control_plane = create_bgp_ebb_full_scale_test_config(
        NRQEB009_ASH6,
        name="NRQEB009_EBB16_FIBAGENT_QUALIFICATION_TRAFFIC_UG_ADHOC",
        playbooks_selected=["bgp_ebb_nexthop_group_count_threshold_playbook"],
        profile=BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R,
        enable_update_group=True,
        # The launcher keeps whatever level the previous run wrote. DBG1 keeps
        # the per-route updates the FibAgentBgp analysis uses; DBG5 keepalive
        # tracing filled the 6.3 GB /var/log tmpfs within one storm epoch.
        bgpcpp_logging_config_override="DBG1;default:async=true",
        parent_networks=EBB_PARENT_NETWORKS_IXIA03,
        next_hops=EBB_NEXT_HOPS_IXIA03,
        port_map=EBB_FULL_SCALE_PORT_MAP_WITH_BGPMON,
        # 20 epochs keeps a lab run near 1.5 h; the canonical contract is 48.
        nhg_storm_epoch_count=20,
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
                # Five 30-prefix blocks per AFI per stage keep the restoration
                # transient under the 104,856-entry FecLevel2 table.
                restoration_stage_prefix_count=150,
            )
        ],
    )


NRQEB009_EBB16_FIBAGENT_QUALIFICATION_TRAFFIC_UG_ADHOC = (
    _build_nrqeb009_ebb16_traffic_test_config()
)
