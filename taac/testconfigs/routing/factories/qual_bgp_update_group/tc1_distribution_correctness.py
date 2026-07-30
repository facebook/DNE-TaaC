# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""Spec 2.1 — Distribution Correctness. UG qualification testconfig factory.

Merges the former bag013 initial-dump path (previously grandfathered as an
empty-playbook TestConfig inside the sustained-link-flap TC) and the eb03
initial-dump lab-box variant into a single spec-anchored factory that
dispatches internally on ``physical_inventory.device_name``.

Golden regen for ``BAG013_ASH6_BGP_UG_INITIAL_DUMP_IDENTICAL_ROUTES_TEST_CONFIG``
is EXPECTED and legitimate: the former empty-playbook TestConfig is
replaced by a TestConfig that actually wires the 2.1.1 playbook. The
eb03 lifecycle constant remains byte-wise identical.

The bag conveyor topology builder is re-used by tc7 (sustained link flap)
and tc9 (edge cases), so ``build_bag_conveyor_test_config`` is a public
helper.
"""

import json
import os
import typing as t

from taac.abstractions.physical_inventory import PhysicalInventory
from taac.abstractions.topologies.ebb_full_scale import (
    EBB_AS_NUMBERS,
    EBB_FULL_SCALE_PORT_MAP,
    ebb_full_scale_topology,
    EBB_PARENT_NETWORKS,
    EBB_PEER_GROUPS,
)
from taac.abstractions.topology import (
    OpenRMode,
    PrefixAdvertisement,
    PrefixSet,
    RoutingDeviceConfig,
)
from taac.constants import BgpPlusPlusProfile
from taac.health_checks.healthcheck_definitions import (
    create_bgp_graceful_restart_check,
    create_bgp_update_group_check,
)
from taac.playbooks.playbook_definitions import (
    build_arista_ebb_scale_playbook,
)
from taac.playbooks.routing.factories.qual_bgp_update_group.tc1_distribution_correctness import (
    create_bgp_ug_initial_dump_identical_routes_playbook,
)
from taac.stages.stage_definitions import create_steps_stage
from taac.steps.step_definitions import (
    create_custom_step,
    create_longevity_step,
    create_validation_step,
)
from taac.testconfigs.routing.util.bgp_ebb_constants import (
    DEFAULT_PROFILE,
    EBGP_PEER_COUNT_V4,
    EBGP_PEER_COUNT_V6,
    EBGP_PEER_TO_DRAIN,
    EBGP_REMOTE_AS,
    IBGP_PEER_SCALE_PER_PLANE,
    IBGP_PEER_TO_DRAIN_PER_PLANE,
    IBGP_REMOTE_AS,
    IXIA_EBGP_IC_PARENT_NETWORK_V4,
    IXIA_EBGP_IC_PARENT_NETWORK_V6,
    IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE1,
    IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE2,
    IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE3,
    IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE4,
    IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE1,
    IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE2,
    IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE3,
    IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE4,
    IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1,
    IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE2,
    IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE3,
    IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE4,
    IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE1,
    IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE2,
    IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE3,
    IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE4,
    PEERGROUP_BGP_MON,
    PEERGROUP_EBGP_V6,
    PEERGROUP_IBGP_V4,
    PEERGROUP_IBGP_V6,
)
from taac.testconfigs.routing.util.bgp_ebb_health_checks import (
    BGP_STANDARD_POSTCHECKS,
    BGP_STANDARD_PRECHECKS,
    BGP_STANDARD_SNAPSHOT_CHECKS,
)
from taac.testconfigs.routing.util.bgp_ebb_ixia_config import (
    create_ebb_scale_basic_port_configs,
)
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import TestConfig


# =============================================================================
# BAG conveyor topology — shared builder re-used by tc7 / tc9 as well.
# =============================================================================
#
# Wave 6 factoring: the previous ``_create_bag013_ash6_conveyor_test_config_impl``
# built one TestConfig with EITHER [] playbooks (default) or [2.1.1, 2.7.2]
# (``enable_update_group=True``). Wave 6 splits that mono-TC into per-spec-section
# TestConfigs (tc1 = 2.1.1 only, tc7 = 2.7.2 only); this helper accepts the
# playbook list + TestConfig ``name`` field as parameters so each spec-section
# factory can build its own TestConfig on the same underlying bag conveyor
# logical_topology. Every value is read from the passed ``physical_inventory`` (device_name,
# dut_bgp_as, ixia_ports, bgpcpp path), so the builder is DUT-agnostic across
# the bag010/011/012/013 EBB conveyor nodes; the tc9 edge-cases factory reuses
# it for bag011.


def build_bag_conveyor_test_config(
    physical_inventory: PhysicalInventory,
    *,
    name: str,
    playbooks: t.List[taac_types.Playbook],
    profile: BgpPlusPlusProfile = BgpPlusPlusProfile.BGP_PLUS_PLUS_WITHOUT_OPEN_R,
    enable_update_group: bool = True,
    # Forwarded to create_ebb_scale_basic_port_configs; when False the eBGP peers
    # are built with graceful restart disabled (the 2.9.2 simultaneous-disruptions
    # test flaps eBGP sessions "without graceful restart" per spec). Default True
    # is byte-identical to the previous behavior (non-optional thrift field
    # defaulting True), so existing bag goldens are unchanged.
    ebgp_graceful_restart: bool = True,
    # Forwarded to create_ebb_scale_basic_port_configs: optional inline-generated
    # spare IPv4 eBGP route pool(s) (RouteScale, no CSV). 2.9.4 dual-stack
    # isolation uses this for genuinely-new IPv4 prefixes advertised at runtime.
    # None -> byte-identical for other callers.
    extra_prefix_sets: tuple[PrefixSet, ...] = (),
    extra_prefix_advertisements: t.Mapping[str, tuple[PrefixAdvertisement, ...]]
    | None = None,
    # Next-hop-self resolution knobs (opt-in). When set, IXIA advertises routes
    # with next-hop = the peer's connected IP (SAME_AS_LOCAL_IP) and the DUT
    # resolves them from interface state via the bgpcpp
    # ``bgp_resolve_nexthops_from_interface_state`` gflag -- letting the DUT
    # install + re-advertise routes under WITHOUT_OPEN_R (no Open/R daemon). The
    # 2.9.1 best-path test enables all three so it can drive real eBGP->iBGP
    # distribution without Open/R. All three must move together; setting the IXIA
    # next-hop-self without the gflag (or vice versa) leaves the DUT unable to
    # resolve. Default False on all -> byte-identical goldens for other callers.
    ebgp_next_hop_self: bool = False,
    ibgp_next_hop_self: bool = False,
    resolve_nexthops_from_interface_state: bool = False,
    # Forwarded to create_ebb_scale_basic_port_configs: a genuinely-new inline v4
    # pool on plane-1's iBGP v4 DC peers (2.9.6 strict runtime-distribution inject).
    # None -> byte-identical for other callers.
    # Forwarded to create_ebb_scale_basic_port_configs: BGP++ UG 2.9.1 best-path
    # competition. When > 0, carve two dedicated eBGP v4 "competing set" DGs
    # (Set A long AS-PATH / Set B short) advertising a shared inline test pool.
    # None/0 -> byte-identical for other callers.
    ebgp_v4_bestpath_set_peer_count: int = 0,
    ebgp_v4_bestpath_route_scales_a: list[taac_types.RouteScaleSpec] | None = None,
    ebgp_v4_bestpath_route_scales_b: list[taac_types.RouteScaleSpec] | None = None,
    # Forwarded to create_ebb_scale_basic_port_configs: 2.9.1 best-path competition
    # IPv6 leg -- carve two dedicated eBGP v6 "competing set" DGs (Set A long
    # AS-PATH / Set B short) advertising a shared inline v6 test pool. None/0 ->
    # byte-identical for other callers.
    ebgp_v6_bestpath_set_peer_count: int = 0,
    ebgp_v6_bestpath_route_scales_a: list[taac_types.RouteScaleSpec] | None = None,
    ebgp_v6_bestpath_route_scales_b: list[taac_types.RouteScaleSpec] | None = None,
) -> taac_types.TestConfig:
    """Shared bag conveyor topology TestConfig builder.

    Wave 6 factoring of the legacy
    ``bag013_ash6_test_config.create_bag013_ash6_conveyor_test_config()``
    body. Callers pass the exact TestConfig ``name`` + playbook list they
    need. UG qualification never exercises BGP-MON or OpenR, so this
    builder wires only the eBGP + iBGP topology (``include_bgp_mon=False``)
    and defaults ``profile`` to ``WITHOUT_OPEN_R``.

    DUT-agnostic across the bag010/011/012/013 EBB conveyor nodes: every
    value is read from ``physical_inventory`` (device_name, dut_bgp_as, ixia_ports,
    bgpcpp_configerator_path), so cloning to a new bag node is a one-line
    lifecycle-binding change. Renamed from ``build_bag013_conveyor_test_config``
    (formerly bag013-hardcoded) during the tc9 edge-cases work;
    behavior-preserving, so existing bag013 goldens stay byte-identical.
    """
    assert physical_inventory.device_name.startswith("bag"), (
        f"bag conveyor topology builder targets bag* EBB conveyor nodes; "
        f"got physical_inventory.device_name={physical_inventory.device_name!r}."
    )
    assert physical_inventory.dut_bgp_as is not None, (
        "PhysicalInventory must have dut_bgp_as set"
    )
    assert physical_inventory.bgpcpp_configerator_path is not None, (
        "PhysicalInventory must have bgpcpp_configerator_path set for BGP++ deployment"
    )
    assert len(physical_inventory.ixia_ports) >= 2, (
        "PhysicalInventory must have >= 2 IXIA ports (eBGP + iBGP)"
    )

    if ebgp_next_hop_self != ibgp_next_hop_self:
        raise ValueError("eBGP and iBGP next-hop-self intent must move together")
    next_hop_self = ebgp_next_hop_self
    if next_hop_self != resolve_nexthops_from_interface_state:
        raise ValueError("next-hop-self requires interface-state next-hop resolution")

    openr_mode = (
        OpenRMode.STANDALONE
        if profile == BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R
        else OpenRMode.NONE
    )
    bound = ebb_full_scale_topology(
        openr_mode=openr_mode,
        include_bgpmon=False,
        ebgp_graceful_restart=ebgp_graceful_restart,
        next_hop_self=next_hop_self,
        resolve_nexthops_from_interface_state=(resolve_nexthops_from_interface_state),
        extra_prefix_sets=extra_prefix_sets,
        extra_advertisements=extra_prefix_advertisements,
    ).bind_to_inventory(
        physical_inventory=physical_inventory,
        port_map=EBB_FULL_SCALE_PORT_MAP,
        parent_networks=EBB_PARENT_NETWORKS,
        peer_groups=EBB_PEER_GROUPS,
        as_numbers=EBB_AS_NUMBERS,
        device_config_override=RoutingDeviceConfig(
            openr_mode=openr_mode,
            update_group_enable=enable_update_group,
            resolve_nexthops_from_interface_state=(
                resolve_nexthops_from_interface_state
            ),
        ),
    )
    compiled = bound.compile()
    basic_port_configs = compiled.basic_port_configs
    if ebgp_v4_bestpath_set_peer_count or ebgp_v6_bestpath_set_peer_count:
        # The best-path test was added after the DICE migration. Its four
        # competing peer sets are not yet expressible by the shared topology.
        basic_port_configs = create_ebb_scale_basic_port_configs(
            device_name=physical_inventory.device_name,
            ixia_interface_mimic_ebgp=physical_inventory.ixia_ports[0][0],
            ixia_interface_mimic_ibgp=physical_inventory.ixia_ports[1][0],
            ebgp_peer_count_v6=EBGP_PEER_COUNT_V6,
            ebgp_peer_count_v4=EBGP_PEER_COUNT_V4,
            ebgp_peer_to_drain=EBGP_PEER_TO_DRAIN,
            ibgp_peer_scale_per_plane=IBGP_PEER_SCALE_PER_PLANE,
            ibgp_peer_to_drain_per_plane=IBGP_PEER_TO_DRAIN_PER_PLANE,
            ebgp_remote_as=EBGP_REMOTE_AS,
            ibgp_remote_as=IBGP_REMOTE_AS,
            ixia_ebgp_ic_parent_network_v6=IXIA_EBGP_IC_PARENT_NETWORK_V6,
            ixia_ebgp_ic_parent_network_v4=IXIA_EBGP_IC_PARENT_NETWORK_V4,
            ixia_ibgp_ic_parent_network_v6_dc_plane1=IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1,
            ixia_ibgp_ic_parent_network_v6_dc_plane2=IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE2,
            ixia_ibgp_ic_parent_network_v6_dc_plane3=IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE3,
            ixia_ibgp_ic_parent_network_v6_dc_plane4=IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE4,
            ixia_ibgp_ic_parent_network_v6_mp_plane1=IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE1,
            ixia_ibgp_ic_parent_network_v6_mp_plane2=IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE2,
            ixia_ibgp_ic_parent_network_v6_mp_plane3=IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE3,
            ixia_ibgp_ic_parent_network_v6_mp_plane4=IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE4,
            ixia_ibgp_ic_parent_network_v4_dc_plane1=IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE1,
            ixia_ibgp_ic_parent_network_v4_dc_plane2=IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE2,
            ixia_ibgp_ic_parent_network_v4_dc_plane3=IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE3,
            ixia_ibgp_ic_parent_network_v4_dc_plane4=IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE4,
            ixia_ibgp_ic_parent_network_v4_mp_plane1=IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE1,
            ixia_ibgp_ic_parent_network_v4_mp_plane2=IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE2,
            ixia_ibgp_ic_parent_network_v4_mp_plane3=IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE3,
            ixia_ibgp_ic_parent_network_v4_mp_plane4=IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE4,
            include_bgp_mon=False,
            profile=profile,
            ebgp_graceful_restart=ebgp_graceful_restart,
            ebgp_next_hop_self=ebgp_next_hop_self,
            ibgp_next_hop_self=ibgp_next_hop_self,
            ebgp_v4_bestpath_set_peer_count=ebgp_v4_bestpath_set_peer_count,
            ebgp_v4_bestpath_route_scales_a=ebgp_v4_bestpath_route_scales_a,
            ebgp_v4_bestpath_route_scales_b=ebgp_v4_bestpath_route_scales_b,
            ebgp_v6_bestpath_set_peer_count=ebgp_v6_bestpath_set_peer_count,
            ebgp_v6_bestpath_route_scales_a=ebgp_v6_bestpath_route_scales_a,
            ebgp_v6_bestpath_route_scales_b=ebgp_v6_bestpath_route_scales_b,
        )
    return taac_types.TestConfig(
        name=name,
        skip_ixia_protocol_verification=True,
        log_collection_timeout=600,
        basset_pool="dne.test",
        endpoints=compiled.endpoints,
        host_os_type_map=compiled.host_os_type_map,
        startup_checks=[],
        setup_tasks=compiled.setup_tasks,
        teardown_tasks=compiled.teardown_tasks,
        basic_port_configs=basic_port_configs,
        playbooks=playbooks,
    )


# =============================================================================
# EB03 lab-box variant helpers (BGP++ UG spec 2.1.1 on eb03.lab.ash6)
# =============================================================================


def _create_eb03_2_1_1_initial_dump_identical_routes_playbook(
    physical_inventory: PhysicalInventory,
):
    """eb03-specific BGP++ Update Group qualification 2.1.1 playbook.

    Byte-wise identical to the legacy
    ``eb03_update_group_test_config._create_2_1_1_initial_dump_identical_routes_playbook``.
    Pinned expected_member_counts (EB-EB-V6=496, EB-FA-V6=140, BGP-MON=2) and
    policy_names are eb03-specific golden values from the live device.
    """
    assert len(physical_inventory.ixia_ports) >= 3, (
        "eb03 2.1.1 playbook requires >= 3 IXIA ports; ixia_ports[2] is the "
        "BGP-MON DUT interface used by the pcap-capture step even though "
        "the containing test config skips BGP-MON in setup/teardown."
    )
    ibgp_dut_iface, _ = physical_inventory.ixia_ports[1]
    bgp_mon_dut_iface, _ = physical_inventory.ixia_ports[2]

    prechecks = [
        *BGP_STANDARD_PRECHECKS,
        create_bgp_graceful_restart_check(
            peer_group_name=PEERGROUP_IBGP_V6,
            expected_graceful_restart_enabled=False,
            check_id="eb03_2_1_1_gr_disabled_ibgp_v6",
        ),
        create_bgp_graceful_restart_check(
            peer_group_name=PEERGROUP_IBGP_V4,
            expected_graceful_restart_enabled=False,
            check_id="eb03_2_1_1_gr_disabled_ibgp_v4",
        ),
    ]
    verify_step = create_validation_step(
        point_in_time_checks=[
            create_bgp_update_group_check(
                peer_group_substrings=[
                    PEERGROUP_IBGP_V6,
                    PEERGROUP_EBGP_V6,
                    PEERGROUP_BGP_MON,
                ],
                expected_group_count=5,
                expected_member_counts={
                    PEERGROUP_IBGP_V6: 496,
                    PEERGROUP_EBGP_V6: 140,
                    PEERGROUP_BGP_MON: 2,
                },
                expected_policy_names={
                    PEERGROUP_IBGP_V6: ["EB-EB-OUT"],
                    PEERGROUP_EBGP_V6: ["EB-FA-OUT"],
                    PEERGROUP_BGP_MON: ["PROPAGATE_EVERYTHING_OUT"],
                },
                check_id="eb03_2_1_1_update_group_membership",
            )
        ],
        description=(
            "BGP++ Update Group qualification 2.1.1 -- verify EB-EB-V6 iBGP (496 "
            "members, EB-EB-OUT), EB-FA-V6 eBGP (140, EB-FA-OUT) and BGP-MON "
            "(2, PROPAGATE_EVERYTHING_OUT) form distinct update groups, with 5 "
            "groups total (one per peer-group per AFI + BGP-MON)."
        ),
    )
    pcap_compare_step = create_custom_step(
        params_dict={
            "custom_step_name": "test_bgp_update_group_dump_compare",
            "hostname": physical_inventory.device_name,
            "ixia_capture_interface": ibgp_dut_iface,
            "ibgp_peer_regex": "BGP_PEER_IPV6_IBGP_PLANE_1_REMOTE_EB",
            "ibgp_peer_session_indices": [1, 2],
            "capture_duration_seconds": 300,
            "settle_seconds": 10,
            "bgp_mon_capture_interface": bgp_mon_dut_iface,
            "bgp_mon_peer_regex": "BGP_PEER_IPV6_BGP_MON",
            "bgp_mon_session_index": 1,
        },
        description=(
            "BGP++ Update Group 2.1.1 steps 6-7 -- capture and compare the "
            "initial-dump UPDATEs to two iBGP peers in the same update group "
            "(identical NLRI/AS_PATH/LOCAL_PREF/COMMUNITY/MED; next-hop may differ)."
        ),
    )
    return build_arista_ebb_scale_playbook(
        name="eb03_2_1_1_initial_dump_identical_routes",
        stages=[
            create_steps_stage(steps=[verify_step]),
            create_steps_stage(steps=[pcap_compare_step]),
        ],
        prechecks=prechecks,
        postchecks=BGP_STANDARD_POSTCHECKS,
        snapshot_checks=BGP_STANDARD_SNAPSHOT_CHECKS,
    )


def _create_eb03_longevity_debugging_playbook():
    """eb03-specific longevity soak playbook — byte-wise identical to legacy inline."""
    return build_arista_ebb_scale_playbook(
        name="eb03_longevity_debugging",
        prechecks=[
            create_bgp_update_group_check(
                peer_group_substrings=[
                    PEERGROUP_IBGP_V6,
                    PEERGROUP_EBGP_V6,
                    PEERGROUP_BGP_MON,
                ],
                check_id="eb03_longevity_update_group_probe",
            ),
        ],
        stages=[
            create_steps_stage(
                steps=[create_longevity_step(duration=20)],
            ),
        ],
    )


def _create_eb03_distribution_correctness_test_config(
    physical_inventory: PhysicalInventory,
    profile: BgpPlusPlusProfile,
) -> taac_types.TestConfig:
    """eb03.lab.ash6 branch of tc1.

    UG qualification never exercises BGP-MON or OpenR, so this branch wires
    only eBGP + iBGP (``include_bgp_mon=False``) and hard-codes
    ``WITHOUT_OPEN_R``. ``profile`` is accepted for signature parity with the
    outer factory but no longer affects setup / port-config wiring.

    Differs from the bag013 branch:
      - ``host_driver_args`` for admin/password auth (svc-netcastle_bot not
        authorized on the lab device)
      - ``oss_mock_device_data`` MockDeviceInfo (netwhoami returns #INVALID#)
      - Playbooks pin eb03-specific expected_member_counts / policy_names
    """
    assert len(physical_inventory.ixia_ports) >= 2, (
        "eb03 UG initial-dump requires >= 2 IXIA ports (eBGP + iBGP)."
    )
    assert physical_inventory.dut_bgp_as is not None, (
        "PhysicalInventory must have dut_bgp_as set"
    )
    assert physical_inventory.bgpcpp_configerator_path is not None, (
        "PhysicalInventory must have bgpcpp_configerator_path set"
    )

    lab_password_env = (
        physical_inventory.lab_device_password_env_var or "TAAC_EBB_LAB_DEVICE_PASSWORD"
    )
    lab_admin_username = physical_inventory.extras.get("lab_admin_username", "admin")
    lab_admin_password_default = physical_inventory.extras.get(
        "lab_admin_password_default",
        "dnepit",  # pragma: allowlist secret
    )
    lab_password = os.environ.get(lab_password_env, lab_admin_password_default)
    compiled = (
        ebb_full_scale_topology(
            openr_mode=OpenRMode.NONE,
            include_bgpmon=False,
        )
        .bind_to_inventory(
            physical_inventory=physical_inventory,
            port_map=EBB_FULL_SCALE_PORT_MAP,
            parent_networks=EBB_PARENT_NETWORKS,
            peer_groups=EBB_PEER_GROUPS,
            as_numbers=EBB_AS_NUMBERS,
            device_config_override=RoutingDeviceConfig(
                openr_mode=OpenRMode.NONE,
                update_group_enable=True,
            ),
        )
        .compile()
    )

    return TestConfig(
        name="EB03_LAB_ASH6_BGP_TEST_UPDATE_GROUP_CONFIG",
        skip_ixia_protocol_verification=True,
        log_collection_timeout=600,
        basset_pool="dne.test",
        host_driver_args={
            physical_inventory.device_name: json.dumps(
                {"username": lab_admin_username, "password": lab_password}
            ),
        },
        endpoints=compiled.endpoints,
        host_os_type_map=compiled.host_os_type_map,
        oss_mock_device_data={
            physical_inventory.device_name: taac_types.MockDeviceInfo(
                name=physical_inventory.device_name,
                hardware=physical_inventory.extras.get(
                    "mock_device_hardware", "ARISTA_7516"
                ),
                role=physical_inventory.extras.get("mock_device_role", "EB"),
                operating_system="EOS",
                dc=physical_inventory.extras.get("mock_device_dc", "ash6"),
                region=physical_inventory.extras.get("mock_device_region", "ash"),
                asset_id=physical_inventory.extras.get("mock_device_asset_id", 12345),
                asic=physical_inventory.extras.get("mock_device_asic", "JERICHO"),
                routing_protocol="BGP",
                dc_type="ONE",
                network_area=physical_inventory.extras.get(
                    "mock_device_network_area", "BACKBONE"
                ),
                network_area_type="BACKBONE",
                network_type=physical_inventory.extras.get(
                    "mock_device_network_type", "EBB"
                ),
            ),
        },
        startup_checks=[],
        setup_tasks=compiled.setup_tasks,
        teardown_tasks=compiled.teardown_tasks,
        basic_port_configs=compiled.basic_port_configs,
        playbooks=[
            _create_eb03_2_1_1_initial_dump_identical_routes_playbook(
                physical_inventory
            ),
            _create_eb03_longevity_debugging_playbook(),
        ],
    )


def _create_bag013_distribution_correctness_test_config(
    physical_inventory: PhysicalInventory,
    profile: BgpPlusPlusProfile,
    name_override: str | None = None,
) -> taac_types.TestConfig:
    """bag013 branch of tc1 — wires ONLY the 2.1.1 playbook.

    UG qualification does not exercise BGP-MON, but the underlying
    ``create_bgp_ug_initial_dump_identical_routes_playbook`` still uses the
    BGP-MON DUT interface as a pcap-capture handle in its 2.1.1 pcap
    compare step. The interface is left addressed on the DUT (see the
    physical_inventory's third ixia port); only the BGP-MON IXIA session + IP config
    are removed via ``include_bgp_mon=False`` inside
    ``build_bag_conveyor_test_config``. ``profile`` is accepted for
    signature parity with the outer factory but forced to ``WITHOUT_OPEN_R``.
    """
    assert len(physical_inventory.ixia_ports) >= 3, (
        "bag013 tc1 branch requires >= 3 IXIA ports; ixia_ports[2] is the "
        "BGP-MON DUT interface used by the playbook's pcap-capture step "
        "even though the shared builder skips BGP-MON in setup/teardown."
    )
    device_name = physical_inventory.device_name
    ixia_interface_mimic_ibgp, _ = physical_inventory.ixia_ports[1]
    ixia_interface_mimic_bgp_mon, _ = physical_inventory.ixia_ports[2]

    playbook = create_bgp_ug_initial_dump_identical_routes_playbook(
        device_name=device_name,
        ixia_interface_mimic_ibgp=ixia_interface_mimic_ibgp,
        ixia_interface_mimic_bgp_mon=ixia_interface_mimic_bgp_mon,
        ibgp_v6_peer_group=PEERGROUP_IBGP_V6,
        ebgp_v6_peer_group=PEERGROUP_EBGP_V6,
        ibgp_v4_peer_group=PEERGROUP_IBGP_V4,
        bgp_mon_peer_group=PEERGROUP_BGP_MON,
    )
    return build_bag_conveyor_test_config(
        physical_inventory,
        name=name_override or "BAG013_ASH6_BGP_UG_INITIAL_DUMP_IDENTICAL_ROUTES_TEST",
        playbooks=[playbook],
        profile=BgpPlusPlusProfile.BGP_PLUS_PLUS_WITHOUT_OPEN_R,
        enable_update_group=True,
    )


def create_bgp_ug_distribution_correctness_test_config(
    physical_inventory: PhysicalInventory,
    profile: BgpPlusPlusProfile = DEFAULT_PROFILE,
    name_override: str | None = None,
) -> taac_types.TestConfig:
    """BGP++ Update Group qualification 2.1.1 (Distribution Correctness /
    Initial Dump -- Identical Routes) TestConfig, dispatched on ``physical_inventory``.

    Wave 6 merges the previous eb03 lab-box factory
    (``create_bgp_ug_eb03_initial_dump_identical_routes_test_config``) and
    the bag013 conveyor factory (``create_bgp_ug_initial_dump_identical_routes_test_config``)
    into one spec-anchored factory. Internal dispatch on ``physical_inventory.device_name``
    because the two topologies diverge structurally (eb03 is a lab box with
    admin/password auth + mock device info; bag013 is a production EBB with
    OpenR route injection + Port-Channel).

    Golden regen for the bag013 lifecycle constant is EXPECTED: pre-Wave-6
    the bag013 constant returned an empty-playbook TestConfig; Wave 6
    wires the 2.1.1 playbook so the TestConfig name matches the actual
    behavior. eb03 golden hash is byte-wise identical.
    """
    if physical_inventory.device_name == "eb03.lab.ash6":
        return _create_eb03_distribution_correctness_test_config(
            physical_inventory, profile
        )
    if physical_inventory.device_name == "bag013.ash6":
        return _create_bag013_distribution_correctness_test_config(
            physical_inventory, profile, name_override
        )
    raise NotImplementedError(
        f"create_bgp_ug_distribution_correctness_test_config does not yet "
        f"handle physical_inventory.device_name={physical_inventory.device_name!r}; add a branch "
        f"or generalize the topology builder."
    )
