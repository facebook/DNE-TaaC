# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""GTSW warmboot + neighbour uplink-flap hardening TestConfig (IcePack / TH6).

Stresses a GTSW's ability to re-converge while its fabric neighbour's uplinks
churn underneath it. The existing FBOSS hardening conveyors disrupt a single DUT
in isolation; nothing there exercises "DUT recovers while the adjacent switch is
flapping".

Topology (reuses the ash6 c085 multi-node PFC cabling):

    gtsw001.l1001.c085.ash6  (DUT, warmbooted)
        3x IXIA src  eth1/17/1, eth1/17/3, eth1/17/5
              |
              v  8x STSW spine plane (stsw001.s001..s008.l201.ash6)
              |
    gtsw001.l1002.c085.ash6  (NBR, dut=False, uplinks flapped)
        1x IXIA dst  eth1/1/1

The neighbour is ``dut=False`` on purpose. ``TaacRunner.run_tests`` loops
``for dut in duts``, so a second ``dut=True`` would run the whole playbook twice
and warmboot both boxes. As a non-DUT endpoint the neighbour is still covered by
device health checks (they fan out over topology endpoints) but is never
iterated.

Traffic uses a 72..9000 byte random frame-size range. 9000 sits exactly at the
provisioned IcePack fabric-port jumbo MTU; 9100 would be punted to CPU queue 0.

Usage:
  buck2 run neteng/netcastle:netcastle_taac -- \\
    --team taac --test-config GTSW_WARMBOOT_NBR_UPLINK_FLAP_TEST_CONFIG \\
    --dev --skip-basset-reservation --debug
"""

from ixia.ixia import types as ixia_types
from taac.health_checks.healthcheck_definitions import (
    create_bgp_session_establish_check,
    create_port_state_check,
)
from taac.playbooks.playbook_definitions import (
    BGP_RESTART_SERVICE_CHECK,
    create_gtsw_service_restart_nbr_uplink_flap_playbook,
    create_gtsw_warmboot_nbr_uplink_flap_playbook,
    FSDB_RESTART_SERVICE_CHECK,
    QSFP_SERVICE_RESTART_SERVICE_CHECK,
)
from taac.testbed_params.testbed_params_gtsw_th6_ash6_c085 import (
    ASH6_C085_GTSW_TH6_WARMBOOT_NBR_FLAP_END_POINTS,
    GTSW001_L1001_C085_ASH6,
    GTSW001_L1001_C085_IXIA_SRC_PORTS,
    GTSW001_L1002_C085_ASH6,
    GTSW001_L1002_C085_IXIA_DST_PORTS,
)
from taac.test_as_a_config.types import (
    BasicTrafficItemConfig,
    Service,
    TestConfig,
    TrafficEndpoint,
    TrafficItemSettings,
)

# GTSW->STSW uplink selector on the NEIGHBOUR. The flap step resolves the actual
# breakout list at run time from the neighbour's LLDP table, so no eth1/* lanes
# are hardcoded here and the test survives re-cabling.
NBR_UPLINK_NEIGHBOR_PATTERN = "stsw*"

# The whole playbook -- warmboot, neighbour flap, convergence, longevity and the
# full health-check set -- runs PLAYBOOK_ITERATIONS times. The 600s flap budget
# is split evenly across those passes, so changing the iteration count re-slices
# that budget rather than extending the run.
PLAYBOOK_ITERATIONS = 3
TOTAL_FLAP_SEC = 600
PER_ITERATION_FLAP_SEC = TOTAL_FLAP_SEC // PLAYBOOK_ITERATIONS

LONGEVITY_SEC = 300

# Packet sizes span 72 bytes (above the 64B Ethernet minimum) to 9000 bytes
# (the provisioned jumbo MTU on IcePack fabric ports). RANDOM is the only
# frame-size mode that expresses a true min/max range.
FRAME_SIZE_72_TO_9000 = ixia_types.FrameSize(
    type=ixia_types.FrameSizeType.RANDOM,
    random_min=72,
    random_max=9000,
)

# The two extremes of that range, pinned. 9000 sits exactly at the provisioned
# IcePack fabric-port jumbo MTU; 9100 would be punted to CPU queue 0.
FRAME_SIZE_72 = ixia_types.FrameSize(
    type=ixia_types.FrameSizeType.FIXED,
    fixed_size=72,
)
FRAME_SIZE_9000 = ixia_types.FrameSize(
    type=ixia_types.FrameSizeType.FIXED,
    fixed_size=9000,
)

# 3 source ports converge on a single destination port, so each flow is held to
# 30% line rate (~90% aggregate on the destination) to stay lossless in steady
# state — otherwise the packet-loss postcheck would fail on oversubscription
# rather than on a real regression.
PER_FLOW_LINE_RATE = 30

_DST_ENDPOINT = TrafficEndpoint(
    name=f"{GTSW001_L1002_C085_ASH6}:{GTSW001_L1002_C085_IXIA_DST_PORTS[0]}",
    network_group_index=0,
    device_group_index=0,
)

GTSW_WARMBOOT_NBR_FLAP_TRAFFIC_ITEM_CONFIGS = [
    BasicTrafficItemConfig(
        name=f"L1001_TO_L1002_{src_port.replace('/', '_')}",
        bidirectional=False,
        line_rate=PER_FLOW_LINE_RATE,
        frame_size_settings=FRAME_SIZE_72_TO_9000,
        src_dest_mesh=ixia_types.SrcDestMeshType.ONE_TO_ONE,
        src_endpoints=[
            TrafficEndpoint(
                name=f"{GTSW001_L1001_C085_ASH6}:{src_port}",
                network_group_index=0,
                device_group_index=0,
            )
        ],
        dest_endpoints=[_DST_ENDPOINT],
        traffic_type=ixia_types.TrafficType.IPV6,
        tracking_types=[
            ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM,
            ixia_types.TrafficStatsTrackingType.FLOW_GROUP,
        ],
    )
    for src_port in GTSW001_L1001_C085_IXIA_SRC_PORTS
]


def _frame_size_override(
    frame_size: ixia_types.FrameSize,
) -> dict[str, TrafficItemSettings]:
    """Pin every traffic item to one frame size for the duration of a playbook.

    The runner applies these in `async_test_case_setUp` before traffic starts.
    Keys are derived from the same port list that names the traffic items, so
    they cannot drift apart.

    Every playbook below sets this, including the one whose frame size already
    matches the TestConfig default: the override mutates the live IXIA traffic
    item and all playbooks share one session, so a playbook that omitted it
    would inherit whatever the previous playbook left configured.
    """
    return {
        f"L1001_TO_L1002_{src_port.replace('/', '_')}": TrafficItemSettings(
            line_rate=PER_FLOW_LINE_RATE,
            frame_size_settings=frame_size,
        )
        for src_port in GTSW001_L1001_C085_IXIA_SRC_PORTS
    }


def _warmboot_nbr_flap_playbook(
    playbook_name: str,
    frame_size: ixia_types.FrameSize,
):
    """One warmboot + NBR-flap playbook at a given frame size.

    The three playbooks differ only in name and frame size; disruption shape,
    iteration count, flap budget and health checks are identical.
    """
    return create_gtsw_warmboot_nbr_uplink_flap_playbook(
        nbr_device_name=GTSW001_L1002_C085_ASH6,
        iteration=PLAYBOOK_ITERATIONS,
        nbr_uplink_neighbor_pattern=NBR_UPLINK_NEIGHBOR_PATTERN,
        per_iteration_flap_sec=PER_ITERATION_FLAP_SEC,
        longevity_sec=LONGEVITY_SEC,
        playbook_name=playbook_name,
        traffic_items_to_configure=_frame_size_override(frame_size),
    )


# fsdb exposes no convergence signal this test can gate on, so it gets a fixed
# settle instead. 10s matches `create_fsdb_restart_playbook`.
FSDB_SETTLE_SEC = 10


def _service_restart_nbr_flap_playbook(
    playbook_name: str,
    service,
    restart_service_check,
    convergence_services,
    service_label: str,
    post_restart_settle_sec: int = 0,
    extra_post_flap_checks=None,
):
    """One targeted service-restart + NBR-flap playbook.

    Same disruption shape as the warmboot playbooks; only the restarted service
    and its service-specific checks differ. Traffic stays on the 72..9000 random
    range for all three.
    """
    return create_gtsw_service_restart_nbr_uplink_flap_playbook(
        nbr_device_name=GTSW001_L1002_C085_ASH6,
        playbook_name=playbook_name,
        service=service,
        restart_service_check=restart_service_check,
        convergence_services=convergence_services,
        service_label=service_label,
        iteration=PLAYBOOK_ITERATIONS,
        nbr_uplink_neighbor_pattern=NBR_UPLINK_NEIGHBOR_PATTERN,
        per_iteration_flap_sec=PER_ITERATION_FLAP_SEC,
        longevity_sec=LONGEVITY_SEC,
        post_restart_settle_sec=post_restart_settle_sec,
        extra_post_flap_checks=extra_post_flap_checks,
        traffic_items_to_configure=_frame_size_override(FRAME_SIZE_72_TO_9000),
    )


GTSW_WARMBOOT_NBR_UPLINK_FLAP_TEST_CONFIG = TestConfig(
    name="GTSW_WARMBOOT_NBR_UPLINK_FLAP_TEST_CONFIG",
    basset_pool="networkai.test",
    endpoints=ASH6_C085_GTSW_TH6_WARMBOOT_NBR_FLAP_END_POINTS,
    basic_traffic_item_configs=GTSW_WARMBOOT_NBR_FLAP_TRAFFIC_ITEM_CONFIGS,
    playbooks=[
        _warmboot_nbr_flap_playbook(
            "test_warmboot_nbr_uplink_flap",
            FRAME_SIZE_72_TO_9000,
        ),
        _warmboot_nbr_flap_playbook(
            "test_warmboot_nbr_uplink_flap_72b",
            FRAME_SIZE_72,
        ),
        _warmboot_nbr_flap_playbook(
            "test_warmboot_nbr_uplink_flap_9000b",
            FRAME_SIZE_9000,
        ),
        # qsfp_service: port state is asserted after the flap recovers, so it
        # catches a port the restart or the flap left permanently down.
        _service_restart_nbr_flap_playbook(
            playbook_name="test_qsfp_restart_nbr_uplink_flap",
            service=Service.QSFP_SERVICE,
            restart_service_check=QSFP_SERVICE_RESTART_SERVICE_CHECK,
            convergence_services=[Service.QSFP_SERVICE, Service.AGENT, Service.BGP],
            service_label="qsfp_service",
            extra_post_flap_checks=[create_port_state_check()],
        ),
        # bgpd: session establishment is asserted per pass, after the flap
        # recovers, on top of the BGP convergence gate.
        _service_restart_nbr_flap_playbook(
            playbook_name="test_bgp_restart_nbr_uplink_flap",
            service=Service.BGP,
            restart_service_check=BGP_RESTART_SERVICE_CHECK,
            convergence_services=[Service.BGP, Service.AGENT],
            service_label="bgpd",
            extra_post_flap_checks=[create_bgp_session_establish_check()],
        ),
        # fsdb: fixed settle rather than a convergence gate; AGENT + BGP are
        # still gated so the restart is not allowed to disturb forwarding.
        _service_restart_nbr_flap_playbook(
            playbook_name="test_fsdb_restart_nbr_uplink_flap",
            service=Service.FSDB,
            restart_service_check=FSDB_RESTART_SERVICE_CHECK,
            convergence_services=[Service.AGENT, Service.BGP],
            service_label="fsdb",
            post_restart_settle_sec=FSDB_SETTLE_SEC,
        ),
    ],
)
