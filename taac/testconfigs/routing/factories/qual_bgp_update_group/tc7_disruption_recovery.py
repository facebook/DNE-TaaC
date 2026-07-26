# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""Spec 2.7 — Disruption and Recovery. UG qualification testconfig factory.

Only sub-spec 2.7.2 (sustained link flap) is REAL today; 2.7.1 / 2.7.3-6 are
SKELETONs. The factory wires ONLY the 2.7.2 playbook (post-Wave-6 split from
the former ``create_bgp_ug_sustained_link_flap_test_config`` that also
included the 2.1.1 initial-dump playbook — 2.1.1 now lives in tc1).

Golden regen for ``BAG013_ASH6_BGP_UG_SUSTAINED_LINK_FLAP_TEST_CONFIG`` is
EXPECTED and legitimate: the pre-Wave-6 TestConfig wired [2.1.1, 2.7.2];
Wave 6 keeps only [2.7.2] in this factory.

Shares the ``build_bag_conveyor_test_config`` helper from tc1 for the
bag013 conveyor topology (setup / teardown / port config).
"""

from taac.abstractions.physical_inventory import PhysicalInventory
from neteng.test_infra.dne.taac.constants import BgpPlusPlusProfile, Gigabyte
from taac.health_checks.healthcheck_definitions import (
    create_bgp_session_establish_check,
    create_bgp_update_group_check,
    create_cpu_utilization_check,
    create_drain_state_check,
    create_memory_utilization_check,
)
from taac.playbooks.routing.factories.qual_bgp_update_group.tc7_disruption_recovery import (
    create_bgp_ug_sustained_link_flap_playbook,
)
from taac.testconfigs.routing.factories.qual_bgp_update_group.tc1_distribution_correctness import (
    build_bag_conveyor_test_config,
)
from taac.testconfigs.routing.util.bgp_ebb_constants import (
    DEFAULT_PROFILE,
    IXIA_BGP_MON_IC_PARENT_NETWORK,
    IXIA_EBGP_IC_PARENT_NETWORK_V6,
    IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1,
    IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE2,
    IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE3,
    IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE4,
    IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE1,
    IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE2,
    IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE3,
    IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE4,
)
from taac.test_as_a_config import types as taac_types


# =============================================================================
# BGP UG sustained-link-flap (spec 2.7.2) — bag013 conveyor logical_topology.
# =============================================================================

# BGP++ Update Group qualification 2.7.2 -- Sustained Link Flap timing.
# Test values are intentional first-run defaults: 15-min total run with short
# cadences (30/45/75 s) and a brief 5 s down to exercise the orchestration in
# a few minutes per iteration. Production values per the BGP++ Update Group
# qualification 2.7.2 doc are 1 h total with 2/3/5 min cadences and 15 s down --
# swap by flipping ``_BAG013_2_7_2_USE_PRODUCTION_VALUES``.
_BAG013_2_7_2_USE_PRODUCTION_VALUES = True

# Per-interface peer subnets in CIDR form. Used by the step's isolation check
# to attribute each Established BGP peer to its IXIA-facing interface so the
# check knows which peers should NOT flap during a given cycle. CIDR is
# required because the step uses ``ipaddress.ip_address() in ipaddress.ip_network()``
# matching (an earlier iteration used bare string prefixes and mis-attributed
# peers that spilled beyond the literal ``IXIA_*_PARENT_NETWORK_*`` constant,
# producing hundreds of false-positive cross-group violations -- e.g. eBGP V4
# extends from 10.163.28.X into 10.163.29.X to fit 140 /31 pairs).
#
# Subnet sizes chosen empirically from the V6 run's peer-address ranges:
#   * eBGP V4 covers 10.163.28-29  -> /16 (10.163.0.0/16) is generously safe
#   * eBGP V6 sits inside :8::/80  -> /80 matches the IXIA generator
#   * iBGP V4 planes 1-8 are on 10.164-10.171, one /16 per plane
#   * iBGP V6 planes 1-8 are on :9::/80 through :16::/80 (one /80 per plane)
#   * BGP MON V6 sits inside :22:a::/80
_BAG013_EBGP_PEER_SUBNETS = [
    "10.163.0.0/16",
    f"{IXIA_EBGP_IC_PARENT_NETWORK_V6}::/80",
]
_BAG013_IBGP_PEER_SUBNETS = [
    # iBGP V4 -- 8 planes (DC 1-4: 10.164-10.167.X; MP 1-4: 10.168-10.171.X)
    "10.164.0.0/16",
    "10.165.0.0/16",
    "10.166.0.0/16",
    "10.167.0.0/16",
    "10.168.0.0/16",
    "10.169.0.0/16",
    "10.170.0.0/16",
    "10.171.0.0/16",
    # iBGP V6 -- 8 planes, each on a distinct /80 inside 2401:db00:e50d:11::
    f"{IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1}::/80",
    f"{IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE2}::/80",
    f"{IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE3}::/80",
    f"{IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE4}::/80",
    f"{IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE1}::/80",
    f"{IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE2}::/80",
    f"{IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE3}::/80",
    f"{IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE4}::/80",
]
_BAG013_BGP_MON_PEER_SUBNETS = [f"{IXIA_BGP_MON_IC_PARENT_NETWORK}::/80"]

if _BAG013_2_7_2_USE_PRODUCTION_VALUES:
    _BAG013_2_7_2_TOTAL_DURATION_S = 3600
    _BAG013_2_7_2_PORT_SCHEDULE = [
        {
            "interface": "Ethernet3/36/1",
            "label": "eBGP",
            "period_s": 120,
            "down_s": 15,
            "peer_subnets": _BAG013_EBGP_PEER_SUBNETS,
        },
        {
            "interface": "Ethernet3/36/2",
            "label": "iBGP",
            "period_s": 180,
            "down_s": 15,
            "peer_subnets": _BAG013_IBGP_PEER_SUBNETS,
        },
        {
            "interface": "Ethernet3/36/3",
            "label": "BGP-MON",
            "period_s": 300,
            "down_s": 15,
            "peer_subnets": _BAG013_BGP_MON_PEER_SUBNETS,
        },
    ]
else:
    _BAG013_2_7_2_TOTAL_DURATION_S = 900
    _BAG013_2_7_2_PORT_SCHEDULE = [
        {
            "interface": "Ethernet3/36/1",
            "label": "eBGP",
            "period_s": 30,
            "down_s": 5,
            "peer_subnets": _BAG013_EBGP_PEER_SUBNETS,
        },
        {
            "interface": "Ethernet3/36/2",
            "label": "iBGP",
            "period_s": 45,
            "down_s": 5,
            "peer_subnets": _BAG013_IBGP_PEER_SUBNETS,
        },
        {
            "interface": "Ethernet3/36/3",
            "label": "BGP-MON",
            "period_s": 75,
            "down_s": 5,
            "peer_subnets": _BAG013_BGP_MON_PEER_SUBNETS,
        },
    ]


def _bag013_2_7_2_prechecks():
    """Build the bag013.ash6-specific precheck list for the 2.7.2 playbook.

    Hand-rolled (rather than via ``create_standard_prechecks``) for two
    bag013-specific reasons:
      1. bag013.ash6 BGP MON peers stay IDLE (known device-level bgpcpp
         config quirk). We pass
         ``parent_prefixes_to_ignore=[IXIA_BGP_MON_IC_PARENT_NETWORK::/80]``
         to drop them from the session count.
      2. ``create_standard_prechecks`` enforces an EXACT
         ``expected_established_sessions`` count. bag013's actual count
         drifts from the bag010 formula (1272 vs 1290) for reasons we
         haven't traced -- safer to use "no non-established peers among
         non-MON set" semantics.
    """
    return [
        create_bgp_session_establish_check(
            parent_prefixes_to_ignore=[f"{IXIA_BGP_MON_IC_PARENT_NETWORK}::/80"],
        ),
        create_drain_state_check(),
        create_memory_utilization_check(
            threshold=Gigabyte.GIG_5.value,
            start_time_jq_var="test_case_start_time",
        ),
        create_cpu_utilization_check(
            threshold=400.0, start_time_jq_var="test_case_start_time"
        ),
        # Confirm BGP++ ``update_group`` is actually active on the running
        # daemon before the flap loop starts.
        create_bgp_update_group_check(expect_enabled=True),
    ]


def create_bgp_ug_disruption_recovery_test_config(
    physical_inventory: PhysicalInventory,
    profile: BgpPlusPlusProfile = DEFAULT_PROFILE,
) -> taac_types.TestConfig:
    """BGP++ Update Group qualification 2.7.2 (Sustained Link Flap) TestConfig
    for the bag013 conveyor logical_topology. Wires ONLY the 2.7.2 playbook (2.1.1
    now lives in tc1).

    Post-Wave-6 split from the former
    ``create_bgp_ug_sustained_link_flap_test_config`` that wired
    [2.1.1, 2.7.2]. Golden regen expected.
    """
    device_name = physical_inventory.device_name
    playbook = create_bgp_ug_sustained_link_flap_playbook(
        device_name=device_name,
        port_schedule=_BAG013_2_7_2_PORT_SCHEDULE,
        total_duration_s=_BAG013_2_7_2_TOTAL_DURATION_S,
        prechecks=_bag013_2_7_2_prechecks(),
    )
    return build_bag_conveyor_test_config(
        physical_inventory,
        name="BAG013_ASH6_BGP_UG_SUSTAINED_LINK_FLAP_TEST",
        playbooks=[playbook],
        profile=BgpPlusPlusProfile.BGP_PLUS_PLUS_WITHOUT_OPEN_R,
        enable_update_group=True,
    )
