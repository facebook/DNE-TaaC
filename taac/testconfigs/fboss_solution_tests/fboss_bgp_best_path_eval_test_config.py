# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""FBOSS BGP best-path evaluation TestConfig.

Defines the BAG013 BGP++ best-path-eval TestConfig that drives ``LOCAL_PREF`` churn on
downlink iBGP CHURN peers and verifies the DUT re-evaluates best paths correctly. Used
to qualify BGP++ best-path semantics under attribute-churn load.
"""

import json

from ixia.ixia import types as ixia_types
from taac.constants import Gigabyte
from taac.health_checks.healthcheck_definitions import (
    create_bgp_session_establish_check,
    create_bgp_session_snapshot_check,
    create_core_dumps_snapshot_check,
    create_cpu_utilization_check,
    create_ixia_packet_loss_check,
    create_memory_utilization_check,
    create_unclean_exit_check,
)
from taac.playbooks.playbook_definitions import (
    build_best_path_eval_playbook,
)
from taac.stages.stage_definitions import create_steps_stage
from taac.steps.step_definitions import (
    create_ixia_api_step,
    create_longevity_step,
    create_randomize_prefix_local_preference_step,
    create_set_bgp_prefixes_local_preference_step,
    create_validation_step,
)
from taac.task_definitions import (
    create_configure_parallel_bgp_peers_task,
    create_coop_apply_patchers_task,
    create_coop_register_patcher_task,
    create_coop_unregister_patchers_task,
    create_wait_for_agent_convergence_task,
)
from taac.health_check.health_check import types as hc_types
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import TestConfig

# ============================================================================
# Constants
# ============================================================================

CONTROL_TAG = "CONTROL"
CHURN_TAG = "CHURN"
# Dedicated iBGP peer group for CHURN peers (is_confed_peer=False so bgpcpp
# accepts true iBGP sessions where IXIA can send LOCAL_PREF in UPDATEs).
PEERGROUP_IBGP_CHURN_V6 = "PEERGROUP_IBGP_CHURN_V6"
CONTROL_PEER_COUNT = 10
CHURN_PEER_COUNT = 60
CHURN_GROUP_COUNT = 10
PEERS_PER_CHURN_GROUP = 6
# Prefix counts per peer
CONTROL_PREFIX_COUNT_V6 = 5000
CHURN_PREFIX_COUNT_V6 = 15000

# Durations (seconds)
SETUP_WAIT_S = 60
STABLE_STATE_WAIT_S = 120

# Attribute churn parameters
LOCAL_PREF_CHURN_INTERVAL_S = 10
LOCAL_PREF_CHURN_ITERS = 360


# ============================================================================
# Health Check Helpers
# ============================================================================


def _get_control_group_packet_loss_check(device_name):
    """IXIA packet loss check targeting only control group traffic items."""
    return create_ixia_packet_loss_check(
        thresholds=[
            hc_types.PacketLossThreshold(
                names=[f"{device_name.upper()}_CONTROL_V6_TRAFFIC"],
                str_value="0.1",
                expect_packet_loss=False,
            ),
        ],
    )


# ============================================================================
# Cleanup Steps
# ============================================================================


def _get_cleanup_steps():
    """Steps to revert local pref, disable CHURN groups, re-enable CONTROL."""
    return [
        # Revert local preference to default
        create_set_bgp_prefixes_local_preference_step(
            prefix_pool_regex=f".*{CHURN_TAG}.*",
            local_pref_value=100,
            prefix_start_index=0,
            description="Revert CHURN local preference to default (100)",
        ),
        # Re-enable control group
        create_ixia_api_step(
            api_name="toggle_device_groups",
            args_dict={
                "enable": True,
                "device_group_name_regex": CONTROL_TAG,
            },
        ),
        # Disable churn group
        create_ixia_api_step(
            api_name="toggle_device_groups",
            args_dict={
                "enable": False,
                "device_group_name_regex": CHURN_TAG,
            },
        ),
    ]


# ============================================================================
# Best-Path Verification Steps
# ============================================================================

# Substring patterns to identify CHURN prefixes in the BGP++ RIB.
# The task dynamically discovers matching entries instead of requiring
# exact prefix lists, since prefix_limit can cause non-contiguous acceptance.
CHURN_PREFIX_PATTERNS = ["3000:a001:"]


def _create_best_path_baseline_step(device_name):
    """Thin wrapper preserving file-local CHURN_PREFIX_PATTERNS constant."""
    from taac.steps.step_definitions import (
        create_best_path_baseline_step,
    )

    return create_best_path_baseline_step(
        device_name=device_name,
        churn_prefix_patterns=CHURN_PREFIX_PATTERNS,
    )


def _create_best_path_verify_step(device_name):
    """Thin wrapper preserving file-local CHURN_PREFIX_PATTERNS constant."""
    from taac.steps.step_definitions import (
        create_best_path_verify_step,
    )

    return create_best_path_verify_step(
        device_name=device_name,
        churn_prefix_patterns=CHURN_PREFIX_PATTERNS,
    )


# ============================================================================
# Common Helpers
# ============================================================================


def _get_common_checks(device_name, churn_peer_prefixes=None):
    """Return reusable health check objects.

    Args:
        device_name: Device hostname for packet loss check naming.
        churn_peer_prefixes: List of prefixes covering churn peer addresses.
            Used by BGP_SESSION_CHECK to ignore churn sessions so only
            control group sessions are validated for flaps.
    """
    control_packet_loss_check = _get_control_group_packet_loss_check(device_name)
    memory_check = create_memory_utilization_check(
        threshold=Gigabyte.GIG_5.value,
        threshold_by_service={
            "bgpd": Gigabyte.GIG_10.value,
            "fsdb": Gigabyte.GIG_5.value,
            "fboss_sw_agent": Gigabyte.GIG_9.value,
            "fboss_hw_agent@0": Gigabyte.GIG_8.value,
        },
        start_time_jq_var="test_case_start_time",
    )
    cpu_check = create_cpu_utilization_check(
        threshold=400.0,
        start_time_jq_var="test_case_start_time",
    )
    bgp_session_check = create_bgp_session_establish_check()
    bgp_session_snapshot = create_bgp_session_snapshot_check(
        parent_prefixes_to_ignore=churn_peer_prefixes if churn_peer_prefixes else None,
    )
    unclean_exit_check = create_unclean_exit_check()

    return (
        control_packet_loss_check,
        memory_check,
        cpu_check,
        bgp_session_check,
        bgp_session_snapshot,
        unclean_exit_check,
    )


# ============================================================================
# Playbook 1: Setup — enable all DGs, wait for stable state
# ============================================================================


def get_setup_playbook(device_name, churn_peer_prefixes=None):
    """Playbook 1: All DGs enabled, control traffic only.

    Validates baseline with full BGP scale and control traffic flowing.
    Cleanup disables CHURN DGs to prepare for the churn playbook.
    """
    (
        control_packet_loss_check,
        memory_check,
        cpu_check,
        bgp_session_check,
        bgp_session_snapshot,
        unclean_exit_check,
    ) = _get_common_checks(device_name, churn_peer_prefixes)

    return build_best_path_eval_playbook(
        name="test_setup_stable_state",
        postchecks=[
            control_packet_loss_check,
            memory_check,
            cpu_check,
            bgp_session_check,
            unclean_exit_check,
        ],
        snapshot_checks=[
            bgp_session_snapshot,
            create_core_dumps_snapshot_check(),
        ],
        skip_test_config_postchecks=True,
        cleanup_steps=_get_cleanup_steps(),
        stages=[
            create_steps_stage(
                stage_id="setup_stable_state",
                steps=[
                    create_longevity_step(
                        duration=SETUP_WAIT_S,
                        description="Wait for stable state with all DGs and traffic",
                    ),
                    create_validation_step(
                        point_in_time_checks=[
                            control_packet_loss_check,
                        ],
                        description="Validate stable state baseline",
                    ),
                ],
            ),
        ],
    )


# ============================================================================
# Playbook 2: DUT-side best-path verification via local_pref manipulation
# ============================================================================


def get_local_pref_churn_playbook(
    device_name,
    churn_peer_prefixes=None,
):
    """Playbook 2: Verify best-path changes via local_pref churn.

    Downlink CHURN peers are iBGP, so LOCAL_PREF is carried in BGP UPDATEs.
    The churn stage randomises local_pref on all CHURN groups, forcing
    bgpcpp to re-evaluate best paths.
    """
    (
        control_packet_loss_check,
        memory_check,
        cpu_check,
        bgp_session_check,
        bgp_session_snapshot,
        unclean_exit_check,
    ) = _get_common_checks(device_name, churn_peer_prefixes)

    return build_best_path_eval_playbook(
        name="test_continuous_local_pref_churn",
        traffic_items_to_start=[".*CONTROL.*"],
        postchecks=[
            control_packet_loss_check,
            memory_check,
            cpu_check,
            bgp_session_check,
            unclean_exit_check,
        ],
        snapshot_checks=[
            bgp_session_snapshot,
            create_core_dumps_snapshot_check(),
        ],
        skip_test_config_postchecks=True,
        cleanup_steps=_get_cleanup_steps(),
        stages=[
            # Setup: enable CHURN DGs, validate sessions, take baseline
            create_steps_stage(
                stage_id="local_pref_churn_setup",
                steps=[
                    create_ixia_api_step(
                        api_name="toggle_device_groups",
                        args_dict={
                            "enable": True,
                            "device_group_name_regex": CHURN_TAG,
                        },
                        description="Enable CHURN device groups",
                    ),
                    create_longevity_step(
                        duration=SETUP_WAIT_S,
                        description="Wait for CHURN BGP sessions to stabilize",
                    ),
                    create_validation_step(
                        point_in_time_checks=[
                            control_packet_loss_check,
                            bgp_session_check,
                        ],
                        description="Validate all sessions established before churn",
                    ),
                    create_longevity_step(
                        duration=STABLE_STATE_WAIT_S,
                        description="Wait for best-path convergence",
                    ),
                    _create_best_path_baseline_step(device_name),
                ],
            ),
            # Churn: randomise local_pref on all CHURN prefixes (no revert
            # before verify).  iBGP peers carry LOCAL_PREF in BGP UPDATEs,
            # triggering bgpcpp best-path re-evaluation on the DUT.
            create_steps_stage(
                stage_id="local_pref_churn",
                steps=[
                    step
                    for _ in range(LOCAL_PREF_CHURN_ITERS)
                    for step in [
                        create_randomize_prefix_local_preference_step(
                            f".*{CHURN_TAG}.*", 0
                        ),
                        create_longevity_step(
                            duration=LOCAL_PREF_CHURN_INTERVAL_S,
                            description=f"Sleep for {LOCAL_PREF_CHURN_INTERVAL_S}s",
                        ),
                    ]
                ],
            ),
            # Verify best paths changed (while attributes are still modified)
            create_steps_stage(
                stage_id="local_pref_churn_verify",
                steps=[_create_best_path_verify_step(device_name)],
            ),
            # Post-churn health validation (cleanup_steps revert attributes)
            create_steps_stage(
                stage_id="local_pref_churn_validation",
                steps=[
                    create_longevity_step(
                        duration=SETUP_WAIT_S,
                        description="Wait for BGP sessions to stabilize after churn",
                    ),
                    create_validation_step(
                        point_in_time_checks=[
                            control_packet_loss_check,
                            memory_check,
                            cpu_check,
                            bgp_session_check,
                        ],
                        description="Validate health after local_pref churn",
                    ),
                ],
            ),
        ],
    )


# ============================================================================
# Playbook 3: Core dump check
# ============================================================================


def get_core_dump_playbook():
    """Playbook 3: Snapshot check for core dumps and unclean exits."""
    return build_best_path_eval_playbook(
        name="test_core_dump_check",
        postchecks=[],
        snapshot_checks=[
            create_core_dumps_snapshot_check(),
        ],
        skip_test_config_postchecks=True,
        stages=[
            create_steps_stage(
                stage_id="core_dump_check",
                steps=[
                    create_longevity_step(
                        duration=10,
                        description="Brief pause before final core dump check",
                    ),
                ],
            ),
        ],
    )


# ============================================================================
# Main TestConfig Constructor
# ============================================================================


def test_config_best_path_eval(
    test_config_name,
    device_name,
    local_mac_address,
    ixia_uplink_interface,
    ixia_downlink_interface,
    # BGP peering
    peergroup_uplink_mimic_v6,
    peergroup_downlink_mimic_v6,
    route_map_uplink_ingress,
    route_map_uplink_egress,
    route_map_downlink_ingress,
    route_map_downlink_egress,
    uplink_peer_tag,
    downlink_peer_tag,
    # IP addressing
    ixia_uplink_ic_parent_network_v6,
    ixia_downlink_ic_parent_network_v6,
    # AS numbers
    remote_uplink_as_4byte,
    remote_downlink_as_4byte,
    is_uplink_peer_confed,
    is_downlink_peer_confed,
    # Communities, pool
    ixia_uplink_communities,
    ixia_downlink_communities,
    basset_pool,
    # Prefix address space
    v6_uplink_prefix="6000",
    v6_downlink_prefix="3000",
    # Peer route limits
    per_peer_max_route_limit="75000",
    # Control/Churn group sizing
    control_peer_count=CONTROL_PEER_COUNT,
    churn_peer_count=CHURN_PEER_COUNT,
    control_prefix_count_v6=CONTROL_PREFIX_COUNT_V6,
    churn_prefix_count_v6=CHURN_PREFIX_COUNT_V6,
    churn_group_count=CHURN_GROUP_COUNT,
    peers_per_churn_group=PEERS_PER_CHURN_GROUP,
    # DUT's own AS number (for iBGP CHURN peers on downlink)
    dut_as_number=None,
    # Direct IXIA connections (bypass LLDP/Skynet discovery)
    direct_ixia_connections=None,
):
    """Build a BGP best-path evaluation TestConfig for FBOSS BGP++ devices.

    Stresses bgpd's best-path selection by repeatedly randomizing
    `LOCAL_PREF` on prefixes advertised from CHURN iBGP peers on the
    downlink. Each LOCAL_PREF change forces bgpd to re-evaluate which peer
    wins for thousands of prefixes; the test verifies that selection
    remains correct, CONTROL traffic is unaffected, and bgpd does not crash
    or leak memory under sustained best-path churn.

    The CHURN cohort is partitioned into `churn_group_count` device groups
    each with `peers_per_churn_group` peers (default 10 × 6 = 60 peers per
    direction). Downlink CHURN peers are iBGP (same AS as the DUT) so IXIA
    can legally include `LOCAL_PREF` in BGP UPDATEs. CONTROL peers are a
    smaller stable cohort whose sessions and prefixes are excluded from
    flap detection via `parent_prefixes_to_ignore`.

    Args:
        test_config_name: Name to register in `INTERNAL_TEST_CONFIGS`.
        device_name: Hostname of the DUT.
        local_mac_address: DUT-side MAC for the IXIA endpoint.
        ixia_uplink_interface: DUT interface facing the IXIA uplink port.
        ixia_downlink_interface: DUT interface facing the IXIA downlink port.

        BGP peer-group config (V6 only — this test is IPv6-only):
            peergroup_uplink_mimic_v6: bgpcpp peer-group for uplink V6
                CONTROL peers.
            peergroup_downlink_mimic_v6: bgpcpp peer-group for downlink V6
                CONTROL peers (CHURN peers use the dedicated
                `PEERGROUP_IBGP_CHURN_V6` group built inside this function).
            route_map_uplink_ingress: Ingress policy for uplink groups.
            route_map_uplink_egress: Egress policy for uplink groups.
            route_map_downlink_ingress: Ingress policy for downlink groups.
            route_map_downlink_egress: Egress policy for downlink groups.
            uplink_peer_tag: bgpcpp `peer_tag` for uplink groups.
            downlink_peer_tag: bgpcpp `peer_tag` for downlink groups.

        IP addressing (V6 only):
            ixia_uplink_ic_parent_network_v6: IPv6 parent network for uplink
                IXIA peers.
            ixia_downlink_ic_parent_network_v6: IPv6 parent network for
                downlink IXIA peers.

        AS-number config:
            remote_uplink_as_4byte: Base 4-byte AS for uplink IXIA peers;
                CHURN uplink peers begin at base + `control_peer_count`.
            remote_downlink_as_4byte: Base 4-byte AS for downlink CONTROL
                peers (CHURN downlink peers use `dut_as_number` instead so
                they peer iBGP).
            is_uplink_peer_confed: bgpcpp `is_confed_peer` for uplink CONTROL
                peer group.
            is_downlink_peer_confed: Same for downlink CONTROL peer group.

        Communities & infra:
            ixia_uplink_communities: BGP communities for uplink prefixes.
            ixia_downlink_communities: BGP communities for downlink prefixes.
            basset_pool: Basset device-reservation pool name.

        Prefix address space:
            v6_uplink_prefix: IPv6 high-order prefix for uplink routes
                (default "6000").
            v6_downlink_prefix: IPv6 high-order prefix for downlink routes
                (default "3000"); each CHURN group gets a sub-pool under it.

        BGP scale knobs:
            per_peer_max_route_limit: bgpcpp `max_routes` per peer-group
                (string, default "75000").
            control_peer_count: Number of CONTROL peers per direction
                (default `CONTROL_PEER_COUNT`).
            churn_peer_count: Total number of CHURN peers per direction
                across all churn groups (default `CHURN_PEER_COUNT`).
            control_prefix_count_v6: V6 prefixes per CONTROL peer
                (default `CONTROL_PREFIX_COUNT_V6`).
            churn_prefix_count_v6: V6 prefixes per CHURN peer (default
                `CHURN_PREFIX_COUNT_V6`); these are the prefixes whose
                LOCAL_PREF is randomized.
            churn_group_count: Number of CHURN device groups
                (default `CHURN_GROUP_COUNT`).
            peers_per_churn_group: Peers per CHURN device group
                (default `PEERS_PER_CHURN_GROUP`); `churn_group_count *
                peers_per_churn_group` should equal `churn_peer_count`.

        Topology overrides:
            dut_as_number: DUT's BGP AS number; required for iBGP peering on
                CHURN downlink peers. Defaults to None (falls back to
                `remote_downlink_as_4byte + control_peer_count`, which is
                only correct in confed setups).
            direct_ixia_connections: Optional list of direct (device,port)
                tuples bypassing LLDP/Skynet topology discovery
                (`(undocumented; see body)` — passed through to Endpoint).

    Returns:
        A `TestConfig` named `test_config_name` with 3 playbooks: setup,
        local_pref churn, and core-dump.
    """
    total_peer_count = control_peer_count + churn_peer_count

    # Compute IXIA churn group address offsets.
    # Control peers occupy the first control_peer_count * 2 addresses.
    v6_churn_ixia_start = 0x11 + control_peer_count * 2
    v6_churn_gw_start = 0x10 + control_peer_count * 2

    uplink_churn_as = remote_uplink_as_4byte + control_peer_count
    # Downlink CHURN peers are iBGP (same AS as DUT) so IXIA sends
    # LOCAL_PREF in BGP UPDATEs.  Control peers remain confed.
    downlink_churn_as = (
        dut_as_number
        if dut_as_number
        else remote_downlink_as_4byte + control_peer_count
    )

    # Churn peer parent prefixes — used by BGP_SESSION_CHECK
    # (parent_prefixes_to_ignore) to exclude churn sessions from flap detection.
    # These are DUT-side (gateway) addresses.
    churn_peer_prefixes = [
        f"{ixia_uplink_ic_parent_network_v6}::{v6_churn_gw_start:x}",
        f"{ixia_downlink_ic_parent_network_v6}::{v6_churn_gw_start:x}",
    ]

    playbooks = [
        get_setup_playbook(device_name, churn_peer_prefixes),
        get_local_pref_churn_playbook(device_name, churn_peer_prefixes),
        get_core_dump_playbook(),
    ]

    # ================================================================
    # Build CHURN device groups for uplink and downlink (10 groups × 6 peers)
    # ================================================================
    uplink_churn_dgs = []
    downlink_churn_dgs = []
    for i in range(churn_group_count):
        churn_ixia_offset = v6_churn_ixia_start + i * (peers_per_churn_group * 2)
        churn_gw_offset = v6_churn_gw_start + i * (peers_per_churn_group * 2)
        dg_index = i + 1  # DG0 is CONTROL

        # Uplink: EBGP, no routes
        uplink_churn_dgs.append(
            taac_types.DeviceGroupConfig(
                device_group_index=dg_index,
                tag_name=f"{CHURN_TAG}_{i}",
                multiplier=peers_per_churn_group,
                v6_addresses_config=taac_types.IpAddressesConfig(
                    starting_ip=f"{ixia_uplink_ic_parent_network_v6}::{churn_ixia_offset:x}",
                    increment_ip="0:0:0:0::2",
                    gateway_starting_ip=f"{ixia_uplink_ic_parent_network_v6}::{churn_gw_offset:x}",
                    gateway_increment_ip="0:0:0:0::2",
                    mask=127,
                ),
                v6_bgp_config=taac_types.BgpConfig(
                    local_as_4_bytes=uplink_churn_as + i * peers_per_churn_group,
                    local_as_increment=1,
                    enable_4_byte_local_as=True,
                    is_confed=False,
                    bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                ),
            )
        )

        # Downlink: iBGP, with routes (each group gets its own prefix pool)
        downlink_churn_dgs.append(
            taac_types.DeviceGroupConfig(
                device_group_index=dg_index,
                tag_name=f"{CHURN_TAG}_{i}",
                multiplier=peers_per_churn_group,
                v6_addresses_config=taac_types.IpAddressesConfig(
                    starting_ip=f"{ixia_downlink_ic_parent_network_v6}::{churn_ixia_offset:x}",
                    increment_ip="0:0:0:0::2",
                    gateway_starting_ip=f"{ixia_downlink_ic_parent_network_v6}::{churn_gw_offset:x}",
                    gateway_increment_ip="0:0:0:0::2",
                    mask=127,
                ),
                v6_bgp_config=taac_types.BgpConfig(
                    local_as_4_bytes=downlink_churn_as,
                    local_as_increment=0,
                    enable_4_byte_local_as=True,
                    is_confed=False,
                    bgp_peer_type=ixia_types.BgpPeerType.IBGP,
                    bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                    route_scales=[
                        taac_types.RouteScaleSpec(
                            network_group_index=0,
                            v6_route_scale=taac_types.RouteScale(
                                multiplier=1,
                                prefix_count=churn_prefix_count_v6,
                                prefix_length=64,
                                starting_prefixes=f"{v6_downlink_prefix}:a001::",
                                prefix_step="0:0:0:0::",
                                prefix_name=f"PREFIX_POOL_CHURN_{i}_V6_DOWNLINK",
                                bgp_communities=ixia_downlink_communities,
                                ip_address_family=ixia_types.IpAddressFamily.IPV6,
                            ),
                        ),
                    ],
                ),
            )
        )

    return TestConfig(
        name=test_config_name,
        ixia_protocol_verification_timeout=300,
        skip_ixia_protocol_verification=True,
        basset_pool=basset_pool,
        endpoints=[
            taac_types.Endpoint(
                name=device_name,
                ixia_ports=[
                    ixia_uplink_interface,
                    ixia_downlink_interface,
                ],
                dut=True,
                mac_address=local_mac_address,
                direct_ixia_connections=direct_ixia_connections or [],
            ),
        ],
        setup_tasks=[
            # ---- Step 1: Clean slate ----
            create_coop_unregister_patchers_task(device_name),
            create_coop_apply_patchers_task(
                hostnames=[device_name],
            ),
            create_wait_for_agent_convergence_task([device_name]),
            # ---- Step 2: Remove existing BGP peers ----
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name="a_remove_bgp_peers",
                task_name="coop_register_patcher",
                patcher_args={"delete_all": "True"},
                py_func_name="remove_bgp_peers",
            ),
            # ---- Step 2b: Configure BGP switch prefix limit ----
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name="configure_bgp_switch_limit",
                task_name="coop_register_patcher",
                patcher_args={
                    "prefix_limit": "55000",
                },
                py_func_name="configure_bgp_switch_limit",
            ),
            # ---- Step 3: Enable IXIA ports ----
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="agent",
                patcher_name="enable_port_all_ixia_ports",
                task_name="coop_register_patcher",
                patcher_args={
                    f"{ixia_uplink_interface}": "enable",
                    f"{ixia_downlink_interface}": "enable",
                },
                py_func_name="change_port_admin_state",
            ),
            # ---- Step 4: Update existing V6 peer groups ----
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name="update_peer_group_patcher_V6_Downlink",
                task_name="coop_register_patcher",
                patcher_args={
                    "name": peergroup_downlink_mimic_v6,
                    "attributes_to_update_json": json.dumps(
                        {
                            "disable_ipv4_afi": "True",
                            "v4_over_v6_nexthop": "False",
                            "is_passive": "False",
                            "is_confed_peer": is_downlink_peer_confed,
                            "max_routes": per_peer_max_route_limit,
                        }
                    ),
                },
                py_func_name="configure_bgp_peer_group",
            ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name=f"update_peer_group_patcher_{peergroup_uplink_mimic_v6}_Uplink",
                task_name="coop_register_patcher",
                patcher_args={
                    "name": peergroup_uplink_mimic_v6,
                    "attributes_to_update_json": json.dumps(
                        {
                            "disable_ipv4_afi": "True",
                            "v4_over_v6_nexthop": "False",
                            "is_passive": "False",
                            "is_confed_peer": is_uplink_peer_confed,
                            "max_routes": per_peer_max_route_limit,
                        }
                    ),
                },
                py_func_name="configure_bgp_peer_group",
            ),
            # ---- Step 4b: Create iBGP peer group for CHURN peers ----
            # The existing downlink peer group has is_confed_peer=True which
            # rejects true iBGP peers.  We create a separate peer group with
            # is_confed_peer=False so iBGP CHURN peers can establish and IXIA
            # can send LOCAL_PREF in BGP UPDATEs.
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name=f"add_peer_group_patcher_{PEERGROUP_IBGP_CHURN_V6}",
                task_name="coop_register_patcher",
                patcher_args={
                    "name": PEERGROUP_IBGP_CHURN_V6,
                    "description": "iBGP peer group for CHURN peers (LOCAL_PREF test)",
                    "next_hop_self": "True",
                    "disable_ipv4_afi": "True",
                    "disable_ipv6_afi": "False",
                    "is_confed_peer": "False",
                    "ingress_policy_name": route_map_downlink_ingress,
                    "egress_policy_name": route_map_downlink_egress,
                    "bgp_peer_timers_hold_time_seconds": "15",
                    "bgp_peer_timers_keep_alive_seconds": "5",
                    "bgp_peer_timers_out_delay_seconds": "3",
                    "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                    "peer_tag": downlink_peer_tag,
                    "max_routes": per_peer_max_route_limit,
                    "warning_only": "True",
                    "warning_limit": "0",
                    "link_bandwidth_bps": "auto",
                    "v4_over_v6_nexthop": "False",
                    "is_passive": "False",
                },
                py_func_name="add_peer_group_patcher",
            ),
            # ---- Step 5: Configure DUT VLANs and BGP peers ----
            create_configure_parallel_bgp_peers_task(
                hostname=device_name,
                configure_vlans_patcher_name="configure_vlans_patcher_uplink",
                add_bgp_peers_patcher_name="add_bgp_peers_patcher_uplink",
                config_json=json.dumps(
                    {
                        ixia_uplink_interface: [
                            {
                                "starting_ip": f"{ixia_uplink_ic_parent_network_v6}::10",
                                "increment_ip": "0:0:0:0::2",
                                "prefix_length": 127,
                                "description": "Uplink IPv6 Peers (EBGP)",
                                "peer_group_name": peergroup_uplink_mimic_v6,
                                "num_sessions": total_peer_count,
                                "remote_as_4_byte": remote_uplink_as_4byte,
                                "remote_as_4_byte_step": 1,
                                "gateway_starting_ip": f"{ixia_uplink_ic_parent_network_v6}::11",
                                "gateway_increment_ip": "0:0:0:0::2",
                            },
                        ],
                    }
                ),
            ),
            # Downlink: CONTROL peers are confed, CHURN peers are iBGP (AS = DUT)
            create_configure_parallel_bgp_peers_task(
                hostname=device_name,
                configure_vlans_patcher_name="configure_vlans_patcher_downlink",
                add_bgp_peers_patcher_name="add_bgp_peers_patcher_downlink",
                config_json=json.dumps(
                    {
                        ixia_downlink_interface: [
                            {
                                "starting_ip": f"{ixia_downlink_ic_parent_network_v6}::10",
                                "increment_ip": "0:0:0:0::2",
                                "prefix_length": 127,
                                "description": "Downlink IPv6 CONTROL Peers (confed)",
                                "peer_group_name": peergroup_downlink_mimic_v6,
                                "num_sessions": control_peer_count,
                                "remote_as_4_byte": remote_downlink_as_4byte,
                                "remote_as_4_byte_step": 1,
                                "gateway_starting_ip": f"{ixia_downlink_ic_parent_network_v6}::11",
                                "gateway_increment_ip": "0:0:0:0::2",
                            },
                            {
                                "starting_ip": f"{ixia_downlink_ic_parent_network_v6}::{v6_churn_gw_start:x}",
                                "increment_ip": "0:0:0:0::2",
                                "prefix_length": 127,
                                "description": "Downlink IPv6 CHURN Peers (iBGP)",
                                "peer_group_name": PEERGROUP_IBGP_CHURN_V6,
                                "num_sessions": churn_peer_count,
                                "remote_as_4_byte": downlink_churn_as,
                                "remote_as_4_byte_step": 0,
                                "gateway_starting_ip": f"{ixia_downlink_ic_parent_network_v6}::{v6_churn_ixia_start:x}",
                                "gateway_increment_ip": "0:0:0:0::2",
                            },
                        ],
                    }
                ),
            ),
            # ---- Step 6: Apply all registered patchers ----
            create_coop_apply_patchers_task(
                hostnames=[device_name],
            ),
            create_wait_for_agent_convergence_task([device_name]),
        ],
        # ================================================================
        # IXIA Port Configs: Device Groups
        # ================================================================
        basic_port_configs=[
            # ---- UPLINK PORT ----
            taac_types.BasicPortConfig(
                endpoint=f"{device_name}:{ixia_uplink_interface}",
                device_group_configs=[
                    # DG0: CONTROL IPv6 (with routes, prefix_step=0 → same prefixes)
                    taac_types.DeviceGroupConfig(
                        device_group_index=0,
                        tag_name=CONTROL_TAG,
                        multiplier=control_peer_count,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_uplink_ic_parent_network_v6}::11",
                            increment_ip="0:0:0:0::2",
                            gateway_starting_ip=f"{ixia_uplink_ic_parent_network_v6}::10",
                            gateway_increment_ip="0:0:0:0::2",
                            mask=127,
                        ),
                        v6_bgp_config=taac_types.BgpConfig(
                            local_as_4_bytes=remote_uplink_as_4byte,
                            local_as_increment=1,
                            enable_4_byte_local_as=True,
                            is_confed=is_uplink_peer_confed == "True",
                            bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                            route_scales=[
                                taac_types.RouteScaleSpec(
                                    network_group_index=0,
                                    v6_route_scale=taac_types.RouteScale(
                                        multiplier=1,
                                        prefix_count=control_prefix_count_v6,
                                        prefix_length=64,
                                        starting_prefixes=f"{v6_uplink_prefix}:1::",
                                        prefix_step="0:0:0:0::",
                                        prefix_name="PREFIX_POOL_CONTROL_V6_UPLINK",
                                        bgp_communities=ixia_uplink_communities,
                                        ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                    ),
                                ),
                            ],
                        ),
                    ),
                ]
                + uplink_churn_dgs,
            ),
            # ---- DOWNLINK PORT ----
            taac_types.BasicPortConfig(
                endpoint=f"{device_name}:{ixia_downlink_interface}",
                device_group_configs=[
                    # DG0: CONTROL IPv6 (no routes — downlink receives from uplink)
                    taac_types.DeviceGroupConfig(
                        device_group_index=0,
                        tag_name=CONTROL_TAG,
                        multiplier=control_peer_count,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_downlink_ic_parent_network_v6}::11",
                            increment_ip="0:0:0:0::2",
                            gateway_starting_ip=f"{ixia_downlink_ic_parent_network_v6}::10",
                            gateway_increment_ip="0:0:0:0::2",
                            mask=127,
                        ),
                        v6_bgp_config=taac_types.BgpConfig(
                            local_as_4_bytes=remote_downlink_as_4byte,
                            local_as_increment=1,
                            enable_4_byte_local_as=True,
                            is_confed=is_downlink_peer_confed == "True",
                            bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                        ),
                    ),
                ]
                + downlink_churn_dgs,
            ),
        ],
        # ================================================================
        # Traffic Items
        # ================================================================
        basic_traffic_item_configs=[
            # CONTROL V6 traffic (uplink DG0 -> downlink DG0)
            taac_types.BasicTrafficItemConfig(
                name=f"{device_name.upper()}_CONTROL_V6_TRAFFIC",
                bidirectional=False,
                merge_destinations=True,
                line_rate=10,
                src_dest_mesh=ixia_types.SrcDestMeshType.MANY_TO_MANY,
                src_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_uplink_interface}",
                        device_group_index=0,
                    )
                ],
                dest_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{ixia_downlink_interface}",
                        device_group_index=0,
                    )
                ],
                traffic_type=ixia_types.TrafficType.IPV6,
                tracking_types=[ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM],
            ),
        ],
        playbooks=playbooks,
    )


# ============================================================================
# Test Config Instances
# ============================================================================

BEST_PATH_EVAL_TEST_CONFIGS = [
    test_config_best_path_eval(
        test_config_name="BEST_PATH_EVAL_FSW_P003_QZD1",
        device_name="fsw003.p003.f01.qzd1",
        local_mac_address="b6:a9:fc:34:2b:41",
        ixia_uplink_interface="eth7/16/1",
        ixia_downlink_interface="eth8/16/1",
        peergroup_uplink_mimic_v6="PEERGROUP_FSW_SSW_V6",
        peergroup_downlink_mimic_v6="PEERGROUP_FSW_RSW_V6",
        route_map_uplink_ingress="PROPAGATE_FSW_SSW_IN",
        route_map_uplink_egress="PROPAGATE_FSW_SSW_OUT",
        route_map_downlink_ingress="PROPAGATE_FSW_RSW_IN",
        route_map_downlink_egress="PROPAGATE_FSW_RSW_OUT",
        uplink_peer_tag="SSW",
        downlink_peer_tag="RSW",
        ixia_uplink_ic_parent_network_v6="2401:db00:e50d:11:9",
        ixia_downlink_ic_parent_network_v6="2401:db00:e50d:11:8",
        remote_uplink_as_4byte=65000,
        remote_downlink_as_4byte=2000,
        is_uplink_peer_confed="False",
        is_downlink_peer_confed="True",
        dut_as_number=65403,
        ixia_uplink_communities=[
            "65441:196",
            "65441:9001",
            "65441:9002",
            "65441:9003",
            "65441:9004",
            "65441:9005",
        ],
        ixia_downlink_communities=[
            "65441:194",
            "65441:9001",
            "65441:9002",
            "65441:9003",
            "65441:9004",
            "65441:9005",
        ],
        basset_pool="dne.test",
        direct_ixia_connections=[
            taac_types.DirectIxiaConnection(
                interface="eth7/16/1",
                ixia_chassis_ip="2401:db00:0116:303b:0000:0000:0000:0100",
                ixia_port="6/2",
            ),
            taac_types.DirectIxiaConnection(
                interface="eth8/16/1",
                ixia_chassis_ip="2401:db00:0116:303b:0000:0000:0000:0100",
                ixia_port="3/3",
            ),
        ],
    ),
]
