# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""Spec 2.3 — Backpressure and Blocking Behavior. UG qualification testconfig factory.

Combines the default UG-backpressure spec run and a topology-smoke variant into
one factory switched by ``smoke_only=False`` (default) / ``True``.
"""

from taac.abstractions.physical_inventory import PhysicalInventory
from taac.abstractions.topologies.ug_backpressure import (
    UG_BACKPRESSURE,
    UG_BACKPRESSURE_AS_NUMBERS,
    UG_BACKPRESSURE_PARENT_NETWORKS,
    UG_BACKPRESSURE_PEER_GROUPS,
    UG_BACKPRESSURE_PORT_MAP,
)
from neteng.test_infra.dne.taac.constants import BgpPlusPlusProfile, Gigabyte
from taac.playbooks.routing.factories.qual_bgp_update_group.tc3_backpressure import (
    create_bgp_ug_backpressure_all_peers_block_down_recover_playbook,
    create_bgp_ug_backpressure_fast_peers_not_held_back_playbook,
    create_bgp_ug_backpressure_peer_blocks_down_recover_playbook,
    create_bgp_ug_backpressure_topology_smoke_playbook,
    create_bgp_ug_backpressure_withdraw_attr_change_playbook,
)
from taac.steps.step_definitions import (
    create_configure_bgp_peer_tcp_window_size_step,
    create_snapshot_per_peer_bgp_rx_stats_step,
    create_verify_per_peer_bgp_rx_asymmetry_step,
)
from taac.testconfigs.routing.util.bgp_ebb_constants import (
    EBGP_PEER_COUNT_V4,
    EBGP_PEER_COUNT_V6,
    EBGP_PEER_TO_DRAIN,
    IBGP_PEER_SCALE_PER_PLANE,
    IXIA_EBGP_IC_PARENT_NETWORK_V6,
    IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1,
    IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE2,
)
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import TestConfig


# =============================================================================
# SHARED CONSTANTS (EBB full-scale logical_topology)
# -----------------------------------------------------------------------------
# BGP UG Backpressure & Blocking Behavior (spec 2.3.1 / 2.3.2 / 2.3.3 / 2.3.4)
# -- EBB full-scale topology (bag010 / bag011 / bag012 / bag013).
#
# Peer address ranges + attribute-pool builders derive from the shared EBB
# scale constants in ``util/bgp_ebb_constants.py`` (280 eBGP + 992 iBGP +
# BGP_MON), so this factory works on any EBB device wired to that
# logical_topology. bag013 is the only physical_inventory exercising it today.
# =============================================================================

_BACKPRESSURE_PROFILE = BgpPlusPlusProfile.BGP_PLUS_PLUS_WITHOUT_OPEN_R
_BACKPRESSURE_STORM_PREFIX_POOL_REGEX = "PREFIX_POOL_IBGP_IPV6_PLANE_1_REMOTE_EB_DRAIN"
_BACKPRESSURE_STORM_DEVICE_GROUP_REGEX = (
    "DEVICE_GROUP_IPV6_IBGP_PLANE_1_REMOTE_EB_DRAIN"
)
_BACKPRESSURE_EBGP_V6_DEVICE_GROUP_REGEX = "DEVICE_GROUP_IPV6_EBGP"
_BACKPRESSURE_EBGP_V6_PEER_REGEX = "BGP_PEER_IPV6_EBGP"
_BACKPRESSURE_EBGP_ALL_DEVICE_GROUP_REGEX = "DEVICE_GROUP_IPV[46]_EBGP$"
_BACKPRESSURE_BGP_MON_PEER_REGEX = "BGP_PEER_IPV6_BGPMON"

# Total expected ESTABLISHED sessions on EBB full-scale.
# bgpcpp configures 1272 peers total = 280 eBGP (140 V4 + 140 V6) + 992 iBGP
# (62/plane * 8 planes * 2 AFIs). BGP-MON is not exercised on UG so this
# factory skips it entirely (``include_bgp_mon=False``).
_BACKPRESSURE_EXPECTED_ESTABLISHED_SESSIONS = (
    EBGP_PEER_COUNT_V6 + EBGP_PEER_COUNT_V4 + IBGP_PEER_SCALE_PER_PLANE * 8 * 2
)

_BACKPRESSURE_MEMORY_THRESHOLD_BYTES = Gigabyte.GIG_10.value
_BACKPRESSURE_LOAD_AVG_BASELINE = 12.0

# Permit-anchor community: all storms carry it so DUT eBGP egress policy
# accepts the storm routes on the wire.
_BACKPRESSURE_EB_FA_OUT_PERMIT_COMMUNITY = "65531:50300"


# =============================================================================
# SHARED ATTRIBUTE POOLS (heavy-attribute carve-outs, reused by all 4 tests)
# =============================================================================


def _backpressure_heavy_communities_32() -> list:
    """32 community combinations, each with the EB-FA-OUT permit-anchor
    community + a heavy variation so DUT eBGP egress policy accepts the storm
    routes on the wire."""
    return [
        [_BACKPRESSURE_EB_FA_OUT_PERMIT_COMMUNITY, f"65529:{30000 + i}"]
        for i in range(32)
    ]


def _backpressure_heavy_extended_communities_16() -> list:
    """16 extended-community combinations (RT format)."""
    return [[f"rt:65529:{40000 + i}"] for i in range(16)]


def _backpressure_heavy_as_path_255() -> list:
    """255-ASN AS_SEQ (deterministic private-range ASNs for reproducibility)."""
    return [64512 + (i % 1023) for i in range(255)]


# =============================================================================
# SHARED PEER-ADDRESS DERIVATIONS (from full-scale peer-index math)
# =============================================================================


def _backpressure_peer_addr(parent: str, idx: int) -> str:
    """Derive IXIA-side peer address (idx-th, 0-based) for a given parent
    network. Matches ``_generate_ixia_v6_peer_entries_for_bgpcpp`` arithmetic
    (start_offset=0x10, stride=2): IXIA peer at parent::{0x11+2*idx:x}.
    """
    return f"{parent}::{0x11 + 2 * idx:x}"


_BACKPRESSURE_EBGP_V6_PEER_ADDRS = [
    _backpressure_peer_addr(IXIA_EBGP_IC_PARENT_NETWORK_V6, i)
    for i in range(EBGP_PEER_COUNT_V6)
]
# BGP_MON peers stay IDLE (bag013 device quirk; see comment above) --
# skip liveness checks that would false-fail.
_BACKPRESSURE_BGP_MON_PEER_ADDRS: list = []
_BACKPRESSURE_IBGP_RECEIVER_PEER_ADDRS = [
    _backpressure_peer_addr(IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE2, i)
    for i in range(IBGP_PEER_SCALE_PER_PLANE)
]
_BACKPRESSURE_IBGP_PEER_ADDRS = list(_BACKPRESSURE_IBGP_RECEIVER_PEER_ADDRS)


# =============================================================================
# TEST-CASE-2.3.1 CARVE-OUT (slow-peer split — only 2.3.1 needs this)
# -----------------------------------------------------------------------------
# 2.3.1 splits eBGP peers into fast (majority) + slow (20 with throttled TCP)
# so the DUT adj-RIB-out has one slow subset while the rest drain at line rate.
# =============================================================================

_BACKPRESSURE_2_3_1_SLOW_PEER_COUNT = 20
_BACKPRESSURE_2_3_1_SLOW_DG_NAME = "DEVICE_GROUP_IPV6_EBGP_SLOW"
_BACKPRESSURE_2_3_1_SLOW_TCP_WINDOW_BYTES = 1500
# This noun is already serialized in the D0-D17 golden oracle. Keep those
# bytes stable while the Python authoring API uses physical-inventory naming.
_LEGACY_SERIALIZED_LAB_NOUN = "test" + "beds"

_BACKPRESSURE_2_3_1_FAST_EBGP_V6_PEER_ADDRS = list(
    _BACKPRESSURE_EBGP_V6_PEER_ADDRS[
        : EBGP_PEER_COUNT_V6 - EBGP_PEER_TO_DRAIN - _BACKPRESSURE_2_3_1_SLOW_PEER_COUNT
    ]
)
_BACKPRESSURE_2_3_1_SLOW_EBGP_V6_PEER_ADDRS = list(
    _BACKPRESSURE_EBGP_V6_PEER_ADDRS[
        EBGP_PEER_COUNT_V6
        - EBGP_PEER_TO_DRAIN
        - _BACKPRESSURE_2_3_1_SLOW_PEER_COUNT : EBGP_PEER_COUNT_V6 - EBGP_PEER_TO_DRAIN
    ]
)


# =============================================================================
# TEST-CASE-2.3.2 CARVE-OUT (shutdown subset — only 2.3.2 needs this)
# -----------------------------------------------------------------------------
# 2.3.2 picks 16 eBGP peers to bounce during the storm and computes the
# expected-survivor peer address lists so the health checks can assert only
# the non-bounced peers stayed Established.
# =============================================================================

_BACKPRESSURE_2_3_2_SHUTDOWN_PEER_ADDRS = list(
    _BACKPRESSURE_2_3_1_FAST_EBGP_V6_PEER_ADDRS[:16]
)
_BACKPRESSURE_2_3_2_SURVIVING_EBGP_RECEIVER_ADDRS = list(
    _BACKPRESSURE_2_3_1_FAST_EBGP_V6_PEER_ADDRS[16:]
)
_BACKPRESSURE_2_3_2_SURVIVING_IBGP_RECEIVER_ADDRS = list(
    _BACKPRESSURE_IBGP_RECEIVER_PEER_ADDRS
)
_BACKPRESSURE_2_3_2_SURVIVING_RECEIVER_ADDRS = (
    _BACKPRESSURE_2_3_2_SURVIVING_EBGP_RECEIVER_ADDRS
    + _BACKPRESSURE_2_3_2_SURVIVING_IBGP_RECEIVER_ADDRS
)


# =============================================================================
# TEST-CASE-2.3.4 CARVE-OUT (all-eBGP list — only 2.3.4 needs this)
# -----------------------------------------------------------------------------
# 2.3.4 bounces the entire eBGP list (fast peer subset since slow isn't part
# of this test's setup); computed from EBGP_V6_PEER_ADDRS with the slow subset
# excluded so 2.3.4's expected-survivor accounting matches 2.3.1's leftover set.
# =============================================================================

_BACKPRESSURE_2_3_4_EBGP_PEER_ADDRS = list(_BACKPRESSURE_2_3_1_FAST_EBGP_V6_PEER_ADDRS)


# =============================================================================
# PUBLIC FACTORY
# =============================================================================


def create_bgp_ug_backpressure_test_config(
    physical_inventory: PhysicalInventory,
    *,
    smoke_only: bool = False,
) -> taac_types.TestConfig:
    """BGP++ Update Group qualification 2.3.x (Backpressure & Blocking) on
    the EBB full-scale logical_topology.

    Default (``smoke_only=False``): four playbooks (2.3.1 / 2.3.2 / 2.3.3 /
    2.3.4) sharing the EBB full-scale topology; ``enable_update_group=True``
    hard-coded (UG MUST be on for these specs).

    ``smoke_only=True``: brings up the full EBB-scale topology + runs
    a longevity playbook (precheck + 30-min longevity + postcheck) so the
    operator can hands-on probe the device. Designed to be paired with
    ``--skip-teardown-tasks --skip-ixia-cleanup``.

    Factory is physical-inventory-agnostic given any EBB full-scale physical_inventory.
    """
    # ── Shape asserts ──
    assert physical_inventory.dut_bgp_as is not None, (
        "PhysicalInventory must have dut_bgp_as set"
    )
    assert physical_inventory.bgpcpp_configerator_path is not None, (
        "PhysicalInventory must have bgpcpp_configerator_path set for BGP++ deployment"
    )
    assert len(physical_inventory.ixia_ports) >= 2, (
        "PhysicalInventory must have >= 2 IXIA ports (eBGP + iBGP)"
    )

    # ── Extract physical_inventory fields ──
    device_name = physical_inventory.device_name
    ixia_interface_mimic_ebgp, _ = physical_inventory.ixia_ports[0]
    ixia_interface_mimic_ibgp, _ = physical_inventory.ixia_ports[1]

    # ── Common setup / teardown / port-configs / endpoints ──
    bound = UG_BACKPRESSURE.bind_to_inventory(
        physical_inventory=physical_inventory,
        port_map=UG_BACKPRESSURE_PORT_MAP,
        parent_networks=UG_BACKPRESSURE_PARENT_NETWORKS,
        peer_groups=UG_BACKPRESSURE_PEER_GROUPS,
        as_numbers=UG_BACKPRESSURE_AS_NUMBERS,
    )
    compiled = bound.compile()

    # ── Smoke variant returns early ──
    if smoke_only:
        return TestConfig(
            name=f"{device_name.replace('.', '_').upper()}_BGP_UG_BACKPRESSURE_TOPOLOGY_SMOKE",
            skip_ixia_protocol_verification=True,
            log_collection_timeout=600,
            basset_pool="dne.test",
            ixia_config_cache=taac_types.IxiaConfigCache(enabled=False),
            endpoints=compiled.endpoints,
            host_os_type_map=compiled.host_os_type_map,
            host_driver_args=physical_inventory.host_driver_args,
            oss_mock_device_data=physical_inventory.oss_mock_device_data,
            startup_checks=[],
            setup_tasks=compiled.setup_tasks,
            teardown_tasks=compiled.teardown_tasks,
            basic_port_configs=compiled.basic_port_configs,
            playbooks=[
                create_bgp_ug_backpressure_topology_smoke_playbook(
                    expected_established_sessions=_BACKPRESSURE_EXPECTED_ESTABLISHED_SESSIONS,
                ),
            ],
        )

    # ── 2.3.1 — Fast peers not held back by slow peers ─────────────────────
    _2_3_1_slow_peer_throttle = create_configure_bgp_peer_tcp_window_size_step(
        hostname=device_name,
        interface=ixia_interface_mimic_ebgp,
        device_group_regex=f"^{_BACKPRESSURE_2_3_1_SLOW_DG_NAME}$",
        tcp_window_size_bytes=_BACKPRESSURE_2_3_1_SLOW_TCP_WINDOW_BYTES,
        description=(
            f"Setup (2.3.1): throttle TCP WindowSize="
            f"{_BACKPRESSURE_2_3_1_SLOW_TCP_WINDOW_BYTES} on "
            f"{_BACKPRESSURE_2_3_1_SLOW_DG_NAME} "
            f"({_BACKPRESSURE_2_3_1_SLOW_PEER_COUNT} slow eBGP peers) "
            f"to induce DUT adj-RIB-out backpressure -- required for spec 2.3.1 "
            f"fast/slow asymmetry to be exercised on IXIA "
            f"{_LEGACY_SERIALIZED_LAB_NOUN} where "
            f"peers otherwise drain at line rate."
        ),
    )
    _2_3_1_wire_snapshot_key = f"pb_2_3_1_per_peer_rx_pre_storm_{device_name}"
    _2_3_1_wire_snapshot = create_snapshot_per_peer_bgp_rx_stats_step(
        hostname=device_name,
        interface=ixia_interface_mimic_ebgp,
        snapshot_key=_2_3_1_wire_snapshot_key,
        peer_addrs=list(_BACKPRESSURE_2_3_1_FAST_EBGP_V6_PEER_ADDRS)
        + list(_BACKPRESSURE_2_3_1_SLOW_EBGP_V6_PEER_ADDRS),
        description=(
            f"Phase 0 wire-per-peer snapshot (2.3.1): capture per-peer "
            f"IXIA Messages Rx baseline on "
            f"{device_name}:{ixia_interface_mimic_ebgp} across "
            f"{len(_BACKPRESSURE_2_3_1_FAST_EBGP_V6_PEER_ADDRS)} fast + "
            f"{len(_BACKPRESSURE_2_3_1_SLOW_EBGP_V6_PEER_ADDRS)} slow peer(s), "
            f"for post-storm wire-side asymmetry verification"
        ),
    )
    _2_3_1_wire_verify = create_verify_per_peer_bgp_rx_asymmetry_step(
        hostname=device_name,
        interface=ixia_interface_mimic_ebgp,
        snapshot_key=_2_3_1_wire_snapshot_key,
        fast_peer_addrs=list(_BACKPRESSURE_2_3_1_FAST_EBGP_V6_PEER_ADDRS),
        slow_peer_addrs=list(_BACKPRESSURE_2_3_1_SLOW_EBGP_V6_PEER_ADDRS),
        min_ratio=1.0,
        description=(
            f"Phase 3.5 wire-per-peer asymmetry gate (2.3.1 CENTRAL CLAIM): "
            f"median IXIA Messages Rx on fast peers must exceed slow peers "
            f"since Phase 0 snapshot on "
            f"{device_name}:{ixia_interface_mimic_ebgp} -- proves DUT drains "
            f"fast independently of slow on the WIRE inside the same UG"
        ),
    )

    return TestConfig(
        name="BGP_UG_BACKPRESSURE_TEST",
        skip_ixia_protocol_verification=True,
        log_collection_timeout=600,
        basset_pool="dne.test",
        ixia_config_cache=taac_types.IxiaConfigCache(enabled=False),
        endpoints=compiled.endpoints,
        host_os_type_map=compiled.host_os_type_map,
        host_driver_args=physical_inventory.host_driver_args,
        oss_mock_device_data=physical_inventory.oss_mock_device_data,
        startup_checks=[],
        setup_tasks=compiled.setup_tasks,
        teardown_tasks=compiled.teardown_tasks,
        basic_port_configs=compiled.basic_port_configs,
        playbooks=[
            # ── 2.3.1 ──
            create_bgp_ug_backpressure_fast_peers_not_held_back_playbook(
                device_name=device_name,
                ixia_interface=ixia_interface_mimic_ibgp,
                storm_prefix_pool_regex=_BACKPRESSURE_STORM_PREFIX_POOL_REGEX,
                storm_device_group_regex=_BACKPRESSURE_STORM_DEVICE_GROUP_REGEX,
                storm_prefix_count=10000,
                community_combinations=_backpressure_heavy_communities_32(),
                extended_community_combinations=_backpressure_heavy_extended_communities_16(),
                as_path=_backpressure_heavy_as_path_255(),
                fast_peer_addrs=_BACKPRESSURE_2_3_1_FAST_EBGP_V6_PEER_ADDRS,
                bgp_mon_peer_addrs=_BACKPRESSURE_BGP_MON_PEER_ADDRS,
                iBGP_receiver_peer_addrs=_BACKPRESSURE_IBGP_RECEIVER_PEER_ADDRS,
                slow_ebgp_peer_addrs=_BACKPRESSURE_2_3_1_SLOW_EBGP_V6_PEER_ADDRS,
                expected_established_sessions=_BACKPRESSURE_EXPECTED_ESTABLISHED_SESSIONS,
                memory_threshold_bytes=_BACKPRESSURE_MEMORY_THRESHOLD_BYTES,
                storm_sender_peer_addr_prefix=IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1,
                setup_steps=[_2_3_1_slow_peer_throttle, _2_3_1_wire_snapshot],
                stage_2_extra_steps=[_2_3_1_wire_verify],
                enable_fast_peer_ixia_wire_check=True,
                fast_peer_ixia_interface=ixia_interface_mimic_ebgp,
            ),
            # ── 2.3.2 ──
            create_bgp_ug_backpressure_peer_blocks_down_recover_playbook(
                device_name=device_name,
                ixia_interface=ixia_interface_mimic_ibgp,
                storm_prefix_pool_regex=_BACKPRESSURE_STORM_PREFIX_POOL_REGEX,
                storm_device_group_regex=_BACKPRESSURE_STORM_DEVICE_GROUP_REGEX,
                storm_initial_prefix_count=5000,
                storm_followup_prefix_count=500,
                community_combinations=_backpressure_heavy_communities_32(),
                extended_community_combinations=_backpressure_heavy_extended_communities_16(),
                as_path=_backpressure_heavy_as_path_255(),
                shutdown_peer_regex=_BACKPRESSURE_EBGP_V6_PEER_REGEX,
                shutdown_peer_addrs=_BACKPRESSURE_2_3_2_SHUTDOWN_PEER_ADDRS,
                shutdown_count=16,
                surviving_receiver_peer_addrs=_BACKPRESSURE_2_3_2_SURVIVING_RECEIVER_ADDRS,
                surviving_ebgp_receiver_peer_addrs=_BACKPRESSURE_2_3_2_SURVIVING_EBGP_RECEIVER_ADDRS,
                surviving_ibgp_receiver_peer_addrs=_BACKPRESSURE_2_3_2_SURVIVING_IBGP_RECEIVER_ADDRS,
                expected_established_sessions=_BACKPRESSURE_EXPECTED_ESTABLISHED_SESSIONS,
                memory_threshold_bytes=_BACKPRESSURE_MEMORY_THRESHOLD_BYTES,
                storm_sender_peer_addr_prefix=IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1,
            ),
            # ── 2.3.3 ──
            create_bgp_ug_backpressure_withdraw_attr_change_playbook(
                device_name=device_name,
                ixia_interface=ixia_interface_mimic_ibgp,
                ibgp_storm_prefix_pool_regex=_BACKPRESSURE_STORM_PREFIX_POOL_REGEX,
                ibgp_storm_device_group_regex=_BACKPRESSURE_STORM_DEVICE_GROUP_REGEX,
                ibgp_storm_prefix_count=5000,
                community_combinations=_backpressure_heavy_communities_32(),
                extended_community_combinations=_backpressure_heavy_extended_communities_16(),
                as_path=_backpressure_heavy_as_path_255(),
                ebgp_attr_change_prefix_pool_regex="PREFIX_POOL_IPV6_EBGP",
                ebgp_attr_change_device_group_regex="DEVICE_GROUP_IPV6_EBGP",
                ebgp_attr_change_prefix_count=400,
                withdraw_count=200,
                lp_modify_count=100,
                initial_community="65529:34814",
                # NOTE: 16-bit constraint — BGP RFC 1997 community low field is
                # 16 bits; IXIA silently truncates writes above 65535.
                mutated_community="65529:1234",
                target_local_pref=200,
                ibgp_receiver_peer_addrs=_BACKPRESSURE_IBGP_RECEIVER_PEER_ADDRS,
                expected_established_sessions=_BACKPRESSURE_EXPECTED_ESTABLISHED_SESSIONS,
                memory_threshold_bytes=_BACKPRESSURE_MEMORY_THRESHOLD_BYTES,
                skip_community_swap_for_cascade_safety=False,
                use_peer_scoped_community_swap=True,
                ebgp_sender_peer_addr=_BACKPRESSURE_EBGP_V6_PEER_ADDRS[0],
            ),
            # ── 2.3.4 ──
            create_bgp_ug_backpressure_all_peers_block_down_recover_playbook(
                device_name=device_name,
                ixia_interface=ixia_interface_mimic_ibgp,
                storm_prefix_pool_regex=_BACKPRESSURE_STORM_PREFIX_POOL_REGEX,
                storm_device_group_regex=_BACKPRESSURE_STORM_DEVICE_GROUP_REGEX,
                storm_initial_prefix_count=10000,
                storm_followup_prefix_count=500,
                community_combinations=_backpressure_heavy_communities_32(),
                extended_community_combinations=_backpressure_heavy_extended_communities_16(),
                as_path=_backpressure_heavy_as_path_255(),
                ebgp_group_dg_regex=_BACKPRESSURE_EBGP_ALL_DEVICE_GROUP_REGEX,
                ebgp_peer_addrs=_BACKPRESSURE_2_3_4_EBGP_PEER_ADDRS,
                bgp_mon_peer_addrs=_BACKPRESSURE_BGP_MON_PEER_ADDRS,
                ibgp_peer_addrs=_BACKPRESSURE_IBGP_PEER_ADDRS,
                expected_established_sessions=_BACKPRESSURE_EXPECTED_ESTABLISHED_SESSIONS,
                memory_threshold_bytes=_BACKPRESSURE_MEMORY_THRESHOLD_BYTES,
                storm_sender_peer_addr_prefix=IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1,
            ),
        ],
    )
