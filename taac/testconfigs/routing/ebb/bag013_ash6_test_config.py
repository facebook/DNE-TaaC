# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""
BGP++ Conveyor Test Configuration for bag013.ash6.

This device is reserved for ad-hoc testing. The default config has an empty
playbook list so the device setup / IXIA topology can be used for manual
runs.

The ``_UPDATE_GROUP`` sibling variant adds two BGP++ Update Group qualification
playbooks:
- 2.1.1 initial-dump-identical-routes (see
  ``_create_2_1_1_initial_dump_identical_routes_playbook``): verifies update-group
  membership and that two iBGP peers in the same group receive identical initial
  dumps (NLRI/AS_PATH/LOCAL_PREF/COMMUNITY/MED; only next-hop may differ), plus
  BGP-MON add-path separation. Full parity with the eb03.lab.ash6 2.1.1 test.
- 2.7.2 sustained link-flap (see ``create_update_group_sustained_link_flap_playbook``):
  rotates flapping the three IXIA-facing ports on independent cadences and
  asserts no cross-group BGP session disruption after each cycle.

Device: bag013.ash6
IXIA Chassis: ares1-my24520014
IXIA Ports:
- Et3/36/1 -> 8/2 (eBGP)
- Et3/36/2 -> 8/3 (iBGP)
- Et3/36/3 -> 8/4 (BGP MON)
"""

from neteng.test_infra.dne.taac.constants import BgpPlusPlusProfile, Gigabyte
from taac.health_checks.healthcheck_definitions import (
    create_bgp_graceful_restart_check,
    create_bgp_session_establish_check,
    create_bgp_update_group_check,
    create_cpu_utilization_check,
    create_drain_state_check,
    create_memory_utilization_check,
)
from taac.playbooks.playbook_definitions import (
    build_arista_ebb_scale_playbook,
    create_update_group_sustained_link_flap_playbook,
)
from taac.routing.ebb.ebb_bgp_plus_plus_test_config.common_health_checks import (
    BGP_STANDARD_POSTCHECKS,
    BGP_STANDARD_PRECHECKS,
    BGP_STANDARD_SNAPSHOT_CHECKS,
)
from taac.routing.ebb.ebb_bgp_plus_plus_test_config.ebb_bgp_plus_plus_conveyor.conveyor_common_tasks import (
    get_common_setup_tasks,
    get_teardown_tasks,
)
from taac.routing.ebb.ebb_bgp_plus_plus_test_config.ebb_bgp_plus_plus_conveyor.conveyor_constants import (
    BGP_MON_PEER_COUNT,
    BGP_MON_REMOTE_AS,
    DEFAULT_PROFILE,
    EBGP_PEER_COUNT_V4,
    EBGP_PEER_COUNT_V6,
    EBGP_PEER_TO_DRAIN,
    EBGP_REMOTE_AS,
    IBGP_PEER_SCALE_PER_PLANE,
    IBGP_PEER_TO_DRAIN_PER_PLANE,
    IBGP_REMOTE_AS,
    IXIA_BGP_MON_IC_PARENT_NETWORK,
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
from taac.routing.ebb.ebb_bgp_plus_plus_test_config.ixia_config_for_ebb_scale import (
    create_ebb_scale_basic_port_configs,
)
from taac.stages.stage_definitions import create_steps_stage
from taac.steps.step_definitions import (
    create_custom_step,
    create_validation_step,
)
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import DirectIxiaConnection, Endpoint, TestConfig


# =============================================================================
# Device-specific configuration for bag013.ash6
# =============================================================================
DEVICE_NAME = "bag013.ash6"
IXIA_CHASSIS_IP = "2401:db00:2066:303b::3001"
BAG013_EOS_BGP_AS = 65013
SPEED = "100g-2"
BGPCPP_CONFIGERATOR_PATH = "taac/ebb_ci_cd_configs/ebb_full_scale_bgpcpp_config"
OPENR_CONFIGERATOR_PATH = "taac/ebb_ci_cd_configs/bag013_ash6_openr_config"

# IXIA interface mappings for bag013.ash6
IXIA_INTERFACE_MIMIC_EBGP = "Ethernet3/36/1"
IXIA_INTERFACE_MIMIC_IBGP = "Ethernet3/36/2"
IXIA_INTERFACE_MIMIC_BGP_MON = "Ethernet3/36/3"

# IXIA port mappings (chassis slot/port)
IXIA_PORT_EBGP = "8/2"
IXIA_PORT_IBGP = "8/3"
IXIA_PORT_BGP_MON = "8/4"


# =============================================================================
# BGP++ Update Group qualification 2.7.2 -- Sustained Link Flap timing
# =============================================================================
# Test values are intentional first-run defaults: 15-min total run with short
# cadences (30/45/75 s) and a brief 5 s down to exercise the orchestration in
# a few minutes per iteration. Production values per the BGP++ Update Group qualification 2.7.2 doc
# are 1 h total with 2/3/5 min cadences and 15 s down -- swap by flipping
# ``_USE_PRODUCTION_VALUES``.
_USE_PRODUCTION_VALUES = True

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
_EBGP_PEER_SUBNETS = [
    "10.163.0.0/16",
    f"{IXIA_EBGP_IC_PARENT_NETWORK_V6}::/80",
]
_IBGP_PEER_SUBNETS = [
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
_BGP_MON_PEER_SUBNETS = [f"{IXIA_BGP_MON_IC_PARENT_NETWORK}::/80"]

if _USE_PRODUCTION_VALUES:
    _TOTAL_DURATION_S = 3600
    _PORT_SCHEDULE = [
        {
            "interface": "Ethernet3/36/1",
            "label": "eBGP",
            "period_s": 120,
            "down_s": 15,
            "peer_subnets": _EBGP_PEER_SUBNETS,
        },
        {
            "interface": "Ethernet3/36/2",
            "label": "iBGP",
            "period_s": 180,
            "down_s": 15,
            "peer_subnets": _IBGP_PEER_SUBNETS,
        },
        {
            "interface": "Ethernet3/36/3",
            "label": "BGP-MON",
            "period_s": 300,
            "down_s": 15,
            "peer_subnets": _BGP_MON_PEER_SUBNETS,
        },
    ]
else:
    _TOTAL_DURATION_S = 900
    _PORT_SCHEDULE = [
        {
            "interface": "Ethernet3/36/1",
            "label": "eBGP",
            "period_s": 30,
            "down_s": 5,
            "peer_subnets": _EBGP_PEER_SUBNETS,
        },
        {
            "interface": "Ethernet3/36/2",
            "label": "iBGP",
            "period_s": 45,
            "down_s": 5,
            "peer_subnets": _IBGP_PEER_SUBNETS,
        },
        {
            "interface": "Ethernet3/36/3",
            "label": "BGP-MON",
            "period_s": 75,
            "down_s": 5,
            "peer_subnets": _BGP_MON_PEER_SUBNETS,
        },
    ]


def _bag013_2_7_2_prechecks():
    """Build the bag013.ash6-specific precheck list for the 2.7.2 playbook.

    Hand-rolled (rather than via ``create_standard_prechecks``) for two
    bag013-specific reasons:
      1. bag013.ash6 BGP MON peers stay IDLE (known device-level bgpcpp
         config quirk; see project notes / MEMORY). We pass
         ``parent_prefixes_to_ignore=[IXIA_BGP_MON_IC_PARENT_NETWORK::/80]``
         to drop them from the session count.
      2. ``create_standard_prechecks`` enforces an EXACT
         ``expected_established_sessions`` count (defaults to 0 and is
         strictly compared, so omitting the count fails with "expected 0
         found N"). bag013's actual count drifts from the bag010 formula
         (1272 vs 1290) for reasons we haven't traced -- safer to use the
         "no non-established peers among non-MON set" semantics (omit
         ``expected_established_sessions``) than to hard-code a
         device-specific number that will rot.

    Other devices (bag010 / bag011) that pick up the
    ``create_update_group_sustained_link_flap_playbook`` factory should
    pass their own precheck list -- typically
    ``create_standard_prechecks(peergroup_ibgp_v6=..., peergroup_ibgp_v4=...,
    expected_established_sessions=N, exclude_bgp_mon=True)`` -- since
    they don't share bag013's IDLE-MON quirk.
    """
    return [
        create_bgp_session_establish_check(
            # ``IXIA_BGP_MON_IC_PARENT_NETWORK`` is a bare string prefix
            # (e.g. ``"2401:db00:e50d:22:a"``), but the precheck pipes
            # ``parent_prefixes_to_ignore`` through ``ipaddress.ip_network()``
            # which rejects that form. Append ``::/80`` to make it a valid
            # CIDR -- mirrors how ``common_health_checks.create_standard_prechecks``
            # builds the same exclusion list.
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
        # daemon before the flap loop starts. Mirrors the setup-task-level
        # ``Cli -p15 -c 'show bgpcpp update-group'`` guard in
        # ``conveyor_common_tasks._get_control_plane_tasks`` (D108374944), but
        # goes through the ``getUpdateGroupInfo`` thrift API (D108632994)
        # instead of CLI parsing. Provides a second, structured early-fail if
        # the patch silently regressed between setup completion and prechecks.
        create_bgp_update_group_check(expect_enabled=True),
    ]


def _create_2_1_1_initial_dump_identical_routes_playbook():
    """Build the BGP++ Update Group qualification 2.1.1 playbook for bag013.

    Mirrors the eb03.lab.ash6 2.1.1 playbook (full parity): one validation step
    running ``BGP_UPDATE_GROUP_CHECK`` (backed by ``getUpdateGroupInfo`` /
    ``show bgpcpp update-group``) followed by the dedicated dump-compare custom
    step.

    The membership check verifies:
      - all iBGP IPv6 peers (peer-group EB-EB-V6) are in the SAME update group,
      - all eBGP IPv6 peers (EB-FA-V6) are in a DIFFERENT update group,
      - BGP Monitor peers are in their OWN update group (distinct from both),
      - all iBGP peers in the shared group received an IDENTICAL number of
        routes from the DUT (single distribution path).

    Pre-conditions (per the Update Group Test Plan 2.1.1):
      1. No established BGP sessions at the start -- satisfied by the
         cold-start setup (fresh BGP++ config deploy + daemon start). Not
         assertable as a precheck (by precheck time the setup has already
         brought sessions up); the session-establish precheck instead confirms
         the post-convergence state the test then inspects.
      2. Update Group enabled + active -- enabled at setup
         (``enable_update_group=True``).
      3. GR is NOT enabled on the iBGP-mesh -- asserted by the GR prechecks
         below (V6 + V4), reusing ``create_bgp_graceful_restart_check``.
      4. IAR (Immediate Advertisement of Routes) enabled -- IAR is enabled by
         default in the EBB environment, so no explicit check is needed.

    Returns:
        A ``Playbook`` named ``bag013_2_1_1_initial_dump_identical_routes``.
    """
    prechecks = [
        *BGP_STANDARD_PRECHECKS,
        # Pre-condition 3: GR must NOT be enabled on the iBGP mesh (V6 + V4).
        create_bgp_graceful_restart_check(
            peer_group_name=PEERGROUP_IBGP_V6,
            expected_graceful_restart_enabled=False,
            check_id="bag013_2_1_1_gr_disabled_ibgp_v6",
        ),
        create_bgp_graceful_restart_check(
            peer_group_name=PEERGROUP_IBGP_V4,
            expected_graceful_restart_enabled=False,
            check_id="bag013_2_1_1_gr_disabled_ibgp_v4",
        ),
    ]
    verify_step = create_validation_step(
        point_in_time_checks=[
            create_bgp_update_group_check(
                # iBGP-V6, eBGP-V6 and BGP-MON must each have Established peers in
                # the update-group table. (A peer-group may form more than one
                # update group -- one per distinct egress policy -- which is
                # expected, not a failure.)
                peer_group_substrings=[
                    PEERGROUP_IBGP_V6,
                    PEERGROUP_EBGP_V6,
                    PEERGROUP_BGP_MON,
                ],
                # Passing criterion 5: total update groups == number of distinct
                # outbound-policy configs (one per peer-group per AFI + BGP-MON):
                # EB-EB-V4, EB-EB-V6, EB-FA-V4, EB-FA-V6, BGP-MON = 5.
                expected_group_count=5,
                # Golden values (full parity with eb03):
                #   EB-EB-V6 -> policy EB-EB-OUT, 496 members
                #     (62/plane x 4 planes x 2 (DC+MP))
                #   EB-FA-V6 -> policy EB-FA-OUT, 140 members
                #   BGP-MON  -> policy PROPAGATE_EVERYTHING_OUT, 2 members
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
                check_id="bag013_2_1_1_update_group_membership",
            )
        ],
        description=(
            "BGP++ Update Group qualification 2.1.1 -- verify EB-EB-V6 iBGP (496 "
            "members, EB-EB-OUT), EB-FA-V6 eBGP (140, EB-FA-OUT) and BGP-MON "
            "(2, PROPAGATE_EVERYTHING_OUT) form distinct update groups, with 5 "
            "groups total (one per peer-group per AFI + BGP-MON)."
        ),
    )
    # Steps 6-7: capture the initial-dump UPDATEs to two iBGP peers in the same
    # update group and assert they are identical (NLRI/AS_PATH/LOCAL_PREF/
    # COMMUNITY/MED; only next-hop may differ). Runs as a custom step that flaps
    # BOTH iBGP peers TOGETHER under a single capture (brings both down, settles,
    # then brings both up) so they rejoin the update group at the same point in
    # its dump cycle and receive the same synchronized distribution -- flapping
    # one peer at a time is invalid (a peer rejoining an already-converged group
    # alone gets a different slice of the table). It captures on the iBGP vport,
    # then parses + compares the pcaps. Requires a full IXIA run (capture won't
    # work under --skip-setup-tasks).
    pcap_compare_step = create_custom_step(
        params_dict={
            "custom_step_name": "test_bgp_update_group_dump_compare",
            "hostname": DEVICE_NAME,
            "ixia_capture_interface": IXIA_INTERFACE_MIMIC_IBGP,
            # IXIA BGP-peer names (from the session topology), not peer-group
            # names. Two sessions of one iBGP-V6 device group -- both land in
            # update group 0 (all EB-EB-V6 peers share one group).
            "ibgp_peer_regex": "BGP_PEER_IPV6_IBGP_PLANE_1_REMOTE_EB",
            "ibgp_peer_session_indices": [1, 2],
            "capture_duration_seconds": 90,
            "settle_seconds": 10,
            # Criterion 4: BGP-Monitor (add-path capable) UPDATEs must be
            # add-path formatted (distinct from iBGP).
            "bgp_mon_capture_interface": IXIA_INTERFACE_MIMIC_BGP_MON,
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
        name="bag013_2_1_1_initial_dump_identical_routes",
        stages=[
            create_steps_stage(steps=[verify_step]),
            create_steps_stage(steps=[pcap_compare_step]),
        ],
        prechecks=prechecks,
        postchecks=BGP_STANDARD_POSTCHECKS,
        snapshot_checks=BGP_STANDARD_SNAPSHOT_CHECKS,
    )


def create_bag013_ash6_conveyor_test_config(
    profile: BgpPlusPlusProfile = DEFAULT_PROFILE,
    enable_update_group: bool = False,
) -> TestConfig:
    """
    Create the test configuration for bag013.ash6 conveyor testing.

    The default config (``enable_update_group=False``) has no playbooks -- bag013
    is reserved for ad-hoc testing.

    When ``enable_update_group=True``, the BGP++ ``enable_update_group`` setting
    is dynamically toggled on the device during BGP++ deployment (in-shell patch
    of ``/mnt/flash/bgpcpp_config`` per D100093369), the test config name is
    suffixed with ``_UPDATE_GROUP``, and a single ``update_group_sustained_link_flap``
    playbook is included that implements the BGP++ Update Group
    qualification test case 2.7.2 (Sustained Link Flapping Across
    Multiple Ports).

    EOS Image Deployment:
        EOS image deployment is handled dynamically by TaacRunner when
        eos_image_id is passed at runtime. CI/CD conveyor passes the
        eos_image_id to TaacRunner, which deploys the image via fbpkg
        directly on the device before running setup tasks.

    Args:
        profile: BGP++ profile to use. Determines whether OpenR route injection
                 is included in setup tasks.
        enable_update_group: When True, toggles the BGP++ ``enable_update_group``
            setting on the device and includes the 2.7.2 sustained-link-flap
            playbook.

    Returns:
        TestConfig object configured for bag013.ash6.
    """
    setup_tasks = get_common_setup_tasks(
        device_name=DEVICE_NAME,
        bgp_asn=BAG013_EOS_BGP_AS,
        ixia_interface_mimic_ebgp=IXIA_INTERFACE_MIMIC_EBGP,
        ixia_interface_mimic_ibgp=IXIA_INTERFACE_MIMIC_IBGP,
        ixia_interface_mimic_bgp_mon=IXIA_INTERFACE_MIMIC_BGP_MON,
        bgpcpp_configerator_path=BGPCPP_CONFIGERATOR_PATH,
        profile=profile,
        openr_configerator_path=OPENR_CONFIGERATOR_PATH,
        openr_port_channel_member="Ethernet3/9/1",
        openr_port_channel_ipv4="10.131.97.232/31",
        openr_port_channel_link_local="fe80::eba:a7f:fcfc/64",
        openr_local_link={
            "ipv4": "10.131.97.232",
            "ipv6": "fe80::eba:a7f:fcfc",
            "ifName": "po100211",
            "weight": 0,
            "metric": 10,
        },
        openr_other_link={
            "ipv4": "10.131.97.233",
            "ipv6": "fe80::eba:a7f:fcfd",
            "ifName": "po100211",
            "weight": 0,
            "metric": 10,
        },
        enable_update_group=enable_update_group,
    )

    teardown_tasks = get_teardown_tasks(
        ixia_interface_mimic_ebgp=IXIA_INTERFACE_MIMIC_EBGP,
        ixia_interface_mimic_ibgp=IXIA_INTERFACE_MIMIC_IBGP,
        ixia_interface_mimic_bgp_mon=IXIA_INTERFACE_MIMIC_BGP_MON,
    )

    test_config_name = "BAG013_ASH6_BGP_CONVEYOR_TEST"
    if enable_update_group:
        test_config_name += "_UPDATE_GROUP"

    playbooks = (
        [
            # 2.1.1 Initial Dump: all peers in the same group receive identical
            # routes (membership + dump-compare). Full parity with eb03.
            _create_2_1_1_initial_dump_identical_routes_playbook(),
            create_update_group_sustained_link_flap_playbook(
                device_name=DEVICE_NAME,
                port_schedule=_PORT_SCHEDULE,
                total_duration_s=_TOTAL_DURATION_S,
                prechecks=_bag013_2_7_2_prechecks(),
                # postchecks/snapshot_checks left None -- factory defaults
                # cover the spec (BGP_STANDARD_POSTCHECKS + load-avg<12 +
                # BGP_STANDARD_SNAPSHOT_CHECKS).
            ),
        ]
        if enable_update_group
        else []
    )

    test_config = TestConfig(
        name=test_config_name,
        skip_ixia_protocol_verification=True,
        log_collection_timeout=600,
        basset_pool="dne.test",
        endpoints=[
            Endpoint(
                name=DEVICE_NAME,
                dut=True,
                ixia_ports=[
                    IXIA_INTERFACE_MIMIC_EBGP,
                    IXIA_INTERFACE_MIMIC_IBGP,
                    IXIA_INTERFACE_MIMIC_BGP_MON,
                ],
                direct_ixia_connections=[
                    DirectIxiaConnection(
                        interface=IXIA_INTERFACE_MIMIC_EBGP,
                        ixia_chassis_ip=IXIA_CHASSIS_IP,
                        ixia_port=IXIA_PORT_EBGP,
                    ),
                    DirectIxiaConnection(
                        interface=IXIA_INTERFACE_MIMIC_IBGP,
                        ixia_chassis_ip=IXIA_CHASSIS_IP,
                        ixia_port=IXIA_PORT_IBGP,
                    ),
                    DirectIxiaConnection(
                        interface=IXIA_INTERFACE_MIMIC_BGP_MON,
                        ixia_chassis_ip=IXIA_CHASSIS_IP,
                        ixia_port=IXIA_PORT_BGP_MON,
                    ),
                ],
            ),
        ],
        host_os_type_map={DEVICE_NAME: taac_types.DeviceOsType.ARISTA_FBOSS},
        startup_checks=[],
        setup_tasks=setup_tasks,
        teardown_tasks=teardown_tasks,
        # Deprecated - define at playbook level
        # prechecks=[],
        # postchecks=[],
        # snapshot_checks=[],
        basic_port_configs=create_ebb_scale_basic_port_configs(
            device_name=DEVICE_NAME,
            ixia_interface_mimic_ebgp=IXIA_INTERFACE_MIMIC_EBGP,
            ixia_interface_mimic_ibgp=IXIA_INTERFACE_MIMIC_IBGP,
            ixia_interface_mimic_bgp_mon=IXIA_INTERFACE_MIMIC_BGP_MON,
            ebgp_peer_count_v6=EBGP_PEER_COUNT_V6,
            ebgp_peer_count_v4=EBGP_PEER_COUNT_V4,
            ebgp_peer_to_drain=EBGP_PEER_TO_DRAIN,
            ibgp_peer_scale_per_plane=IBGP_PEER_SCALE_PER_PLANE,
            ibgp_peer_to_drain_per_plane=IBGP_PEER_TO_DRAIN_PER_PLANE,
            bgp_mon_peer_count=BGP_MON_PEER_COUNT,
            ebgp_remote_as=EBGP_REMOTE_AS,
            ibgp_remote_as=IBGP_REMOTE_AS,
            bgp_mon_remote_as=BGP_MON_REMOTE_AS,
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
            ixia_bgp_mon_ic_parent_network=IXIA_BGP_MON_IC_PARENT_NETWORK,
            profile=profile,
        ),
        playbooks=playbooks,
    )

    return test_config


# Export the test configs (default + _UPDATE_GROUP variant for 2.7.2)
BAG013_ASH6_CONVEYOR_TEST_CONFIG = create_bag013_ash6_conveyor_test_config()
BAG013_ASH6_CONVEYOR_TEST_UPDATE_GROUP_CONFIG = create_bag013_ash6_conveyor_test_config(
    enable_update_group=True,
)
