# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""NPI Multi-Node PFC Test Configuration for IcePack (Tomahawk 6) GTSW.

Instantiates a multi-node PFC TestConfig against the shared
`gen_pfc_functionality_test_generic_4port_configs` factory in
``network_ai_test_configs``. Only the endpoints + port_speed change vs.
the reference `NSF_MULTI_NODE_PFC_TEST_CONFIG` / `MTIA_PFC_TEST_CONFIG` —
the traffic items, playbooks, HCs, and PFC-watchdog thresholds are all
derived by the factory from `port_speed`.

Topology: 3× IXIA sources on ``gtsw001.l1001.c085.ash6`` → 8× STSW spine
plane (``stsw001.s001..s008.l201.ash6``) → 1× IXIA destination on
``gtsw001.l1002.c085.ash6`` (sibling pod in the same cluster, sharing
the identical STSW plane). Backpressure propagates GTSW ← STSW ← GTSW
← Ixia across the fabric (single-node PFC would never leave the box).

Methodology doc:
https://docs.google.com/document/d/1XBnOhM67YkfaAJdvEIMehkY2PsGLsskZ-29ullzPlKA/edit?tab=t.0
"""

import typing as t

from taac.packet_headers import (
    DSF_RDMA_IB_PACKET_HEADERS,
    TC0_PFC_PAUSE_PACKET_HEADERS,
    TC6_PFC_PAUSE_PACKET_HEADERS,
)
from taac.playbooks.playbook_definitions import (
    create_pfc_pause_non_impact_playbook,
    create_pfc_pause_traffic_config,
    create_pfc_repeated_watchdog_playbook,
    create_pfc_wedge_agent_crash_playbook,
)
from taac.testbed_params.testbed_params_gtsw_th6_ash6_c085 import (
    ASH6_C085_GTSW_TH6_MULTI_NODE_PFC_END_POINTS,
    ASH6_C085_GTSW_TH6_MULTI_NODE_PFC_TRAFFIC_DST_ENDPOINTS,
    ASH6_C085_GTSW_TH6_MULTI_NODE_PFC_TRAFFIC_SRC_ENDPOINTS,
    GTSW001_L1001_C085_ASH6,
    GTSW001_L1001_C085_IXIA19_PFC_SRC_PORTS,
    GTSW001_L1002_C085_ASH6,
    GTSW001_L1002_C085_IXIA_DST_PORTS,
)
from taac.testconfigs.fboss_solution_tests.network_ai_test_configs import (
    gen_pfc_functionality_test_generic_4port_configs,
    TRAFFIC_ITEM_HEADERS_MAP,
)
from taac.health_check.health_check import types as hc_types
from taac.test_as_a_config import types as taac_types


# ---------------------------------------------------------------------------
# TestConfig instantiations
#
# All NPI multi-node PFC TestConfigs are constructed below by calling the
# shared `gen_pfc_functionality_test_generic_4port_configs` factory from
# ``network_ai_test_configs``. Adding a new NPI device under multi-node PFC
# coverage = add one factory call here + re-export from this package's
# `__init__.py`.
# ---------------------------------------------------------------------------


def _select_named_config_items(
    *,
    config_name: str,
    items: t.Sequence,
    expected_names: set[str],
    item_type: str,
) -> list:
    selected = [item for item in items if item.name in expected_names]
    selected_names = {item.name for item in selected}
    missing_names = expected_names - selected_names
    if missing_names:
        raise ValueError(
            f"Focused PFC config {config_name} references unknown {item_type}: "
            f"{sorted(missing_names)}"
        )
    return selected


# NPI_DVT_ICEPACK_GTSW__MULTI_NODE_PFC_TEST_CONFIG — IcePack GTSW
# (`gtsw001.l1001.c085.ash6` sources + `gtsw001.l1002.c085.ash6`
# destination; both TH6 ASIC `ICECUBE800BC`; sibling pods in the same
# cluster peering with the identical 8-STSW l201.ash6 spine plane).
# `port_speed=200` matches the IXIA↔GTSW link profile currently in
# use on both DUTs (`PROFILE_200G_1_PAM4_RS544X2N_OPTICAL`,
# confirmed by Pavan 2026-07-06). The factory computes PFC-WD fps
# thresholds proportional to the port speed.
_NPI_DVT_ICEPACK_GTSW_MULTI_NODE_PFC_BASE = (
    gen_pfc_functionality_test_generic_4port_configs(
        test_config_name="NPI_DVT_ICEPACK_GTSW__MULTI_NODE_PFC_TEST_CONFIG",
        endpoints=ASH6_C085_GTSW_TH6_MULTI_NODE_PFC_END_POINTS,
        basset_pool="networkai.test",
        src_endpoints=ASH6_C085_GTSW_TH6_MULTI_NODE_PFC_TRAFFIC_SRC_ENDPOINTS,
        dst_endpoints=ASH6_C085_GTSW_TH6_MULTI_NODE_PFC_TRAFFIC_DST_ENDPOINTS,
        port_speed=200,
        basic_port_configs=None,
        non_congestion_packet_loss_metric=hc_types.PacketLossMetric.DURATION,
        non_congestion_packet_loss_sleep_time=60,
        enable_pfc_counter_baseline_checks=True,
        packet_loss_sleep_time=60,
        packet_loss_duration_only=True,
        enable_platform_hardening_checks=True,
        verify_port_state_transitions=True,
        skip_default_l4_protocol=True,
        # IcePack GTSW RoCE must be RoCEv2/InfiniBand: IP -> UDP(4791) -> IB BTH
        # with Resv7=64 (AR bit = 1). Override the RDMA slot with the shared
        # DSF_RDMA_IB_PACKET_HEADERS (TCP-stripped) so the DUT classifies the
        # flows as RoCE-IB. Applies to all icepack gtsw001.*.ash6 configs.
        traffic_item_headers_map={
            **TRAFFIC_ITEM_HEADERS_MAP,
            "RDMA": DSF_RDMA_IB_PACKET_HEADERS,
        },
    )(
        # Content-blind IXIA config cache keys on <config_name>+<chassis>, so a
        # cached plain-RDMA ixncfg would mask the IB headers; disable it (same as
        # the sibling icepack ECMP / CPU-queue configs).
        ixia_config_cache=taac_types.IxiaConfigCache(enabled=False),
    )
)

NPI_DVT_ICEPACK_GTSW__MULTI_NODE_PFC_TEST_CONFIG = (
    _NPI_DVT_ICEPACK_GTSW_MULTI_NODE_PFC_BASE
)

_PFC_RERUN_TRAFFIC_ITEMS = {
    "TEST_RDMA_TRAFFIC_90PCT_P1_TO_P4",
    "TEST_RDMA_TRAFFIC_90PCT_P2_TO_P4",
    "TEST_RDMA_TRAFFIC_90PCT_P3_TO_P4",
    "TEST_RDMA_TRAFFIC_30PCT_P1_TO_P4",
    "TEST_RDMA_TRAFFIC_30PCT_P2_TO_P4",
    "TEST_RDMA_TRAFFIC_30PCT_P3_TO_P4",
    "TEST_BE_24_TRAFFIC",
    "TRAFFIC_TC2_PFC_PAUSE_7500FPS",
    "TRAFFIC_TC2_PFC_PAUSE_5000FPS",
}
_PFC_RERUN_PLAYBOOKS = {
    "test_pfc_functionality_congestion_non_tc2_traffic",
    "test_pfc_functionality_congestion_and_voq_credit_fairness",
    "test_pfc_functionality_incast_voq_credit_fairness",
    "test_pfc_functionality_port_flap",
    "test_tc2_pfc_wd_functionality",
    "test_tc2_pfc_wd_functionality_transient",
    "test_tc2_pfc_wd_functionality_non_impact_tc1",
}
NPI_DVT_ICEPACK_GTSW__PFC_RERUN_TEST_CONFIG = _NPI_DVT_ICEPACK_GTSW_MULTI_NODE_PFC_BASE(
    name="NPI_DVT_ICEPACK_GTSW__PFC_RERUN_TEST_CONFIG",
    basic_traffic_item_configs=_select_named_config_items(
        config_name="NPI_DVT_ICEPACK_GTSW__PFC_RERUN_TEST_CONFIG",
        items=(
            _NPI_DVT_ICEPACK_GTSW_MULTI_NODE_PFC_BASE.basic_traffic_item_configs or []
        ),
        expected_names=_PFC_RERUN_TRAFFIC_ITEMS,
        item_type="traffic items",
    ),
    playbooks=_select_named_config_items(
        config_name="NPI_DVT_ICEPACK_GTSW__PFC_RERUN_TEST_CONFIG",
        items=_NPI_DVT_ICEPACK_GTSW_MULTI_NODE_PFC_BASE.playbooks or [],
        expected_names=_PFC_RERUN_PLAYBOOKS,
        item_type="playbooks",
    ),
)

_PFC8_SRC_ENDPOINTS = [
    taac_types.TrafficEndpoint(name=f"{GTSW001_L1001_C085_ASH6}:{interface}")
    for interface in GTSW001_L1001_C085_IXIA19_PFC_SRC_PORTS
]
_PFC8_ENDPOINTS = [
    taac_types.Endpoint(
        name=GTSW001_L1001_C085_ASH6,
        dut=True,
        ixia_ports=GTSW001_L1001_C085_IXIA19_PFC_SRC_PORTS,
    ),
    taac_types.Endpoint(
        name=GTSW001_L1002_C085_ASH6,
        dut=False,
        ixia_ports=GTSW001_L1002_C085_IXIA_DST_PORTS,
    ),
]
_PFC_EGRESS_DUT_ENDPOINTS = [
    taac_types.Endpoint(
        name=GTSW001_L1001_C085_ASH6,
        dut=False,
        ixia_ports=GTSW001_L1001_C085_IXIA19_PFC_SRC_PORTS,
    ),
    taac_types.Endpoint(
        name=GTSW001_L1002_C085_ASH6,
        dut=True,
        ixia_ports=GTSW001_L1002_C085_IXIA_DST_PORTS,
    ),
]
_FOCUSED_PFC_BASE = gen_pfc_functionality_test_generic_4port_configs(
    test_config_name="NPI_DVT_ICEPACK_GTSW__PFC8_TEST_CONFIG",
    endpoints=_PFC8_ENDPOINTS,
    basset_pool="networkai.test",
    src_endpoints=_PFC8_SRC_ENDPOINTS,
    dst_endpoints=ASH6_C085_GTSW_TH6_MULTI_NODE_PFC_TRAFFIC_DST_ENDPOINTS,
    port_speed=200,
    basic_port_configs=None,
    non_congestion_packet_loss_metric=hc_types.PacketLossMetric.DURATION,
    non_congestion_packet_loss_sleep_time=60,
    enable_pfc_counter_baseline_checks=True,
    packet_loss_sleep_time=60,
    packet_loss_duration_only=True,
    enable_platform_hardening_checks=True,
    verify_port_state_transitions=True,
    skip_default_l4_protocol=True,
    traffic_item_headers_map={
        **TRAFFIC_ITEM_HEADERS_MAP,
        "RDMA": DSF_RDMA_IB_PACKET_HEADERS,
    },
)(ixia_config_cache=taac_types.IxiaConfigCache(enabled=False))

# Focused execution config for PFC_008. The source ports are on ixia19 and the
# destination is on ixia20, reducing load on the busy ixia20 traffic engine.
# The playbook is compiled only for l1001; l1002 remains in topology and health
# check scope as the remote destination.
NPI_DVT_ICEPACK_GTSW__PFC8_TEST_CONFIG = _FOCUSED_PFC_BASE(
    basic_traffic_item_configs=_select_named_config_items(
        config_name="NPI_DVT_ICEPACK_GTSW__PFC8_TEST_CONFIG",
        items=_FOCUSED_PFC_BASE.basic_traffic_item_configs or [],
        expected_names={"TEST_RDMA_TRAFFIC_90PCT_P1_TO_P4"},
        item_type="traffic items",
    ),
    playbooks=_select_named_config_items(
        config_name="NPI_DVT_ICEPACK_GTSW__PFC8_TEST_CONFIG",
        items=_FOCUSED_PFC_BASE.playbooks or [],
        expected_names={"test_pfc_functionality_non_congestion"},
        item_type="playbooks",
    ),
)


def _create_focused_pfc_test_config(
    *,
    name: str,
    traffic_item_names: set[str],
    playbook_name: str,
) -> taac_types.TestConfig:
    traffic_items = _select_named_config_items(
        config_name=name,
        items=_FOCUSED_PFC_BASE.basic_traffic_item_configs or [],
        expected_names=traffic_item_names,
        item_type="traffic items",
    )
    playbooks = _select_named_config_items(
        config_name=name,
        items=_FOCUSED_PFC_BASE.playbooks or [],
        expected_names={playbook_name},
        item_type="playbooks",
    )
    if len(playbooks) != 1:
        raise ValueError(
            f"Focused PFC config {name} expected exactly one playbook named "
            f"{playbook_name}, found {len(playbooks)}"
        )

    return _FOCUSED_PFC_BASE(
        name=name,
        basic_traffic_item_configs=traffic_items,
        playbooks=playbooks,
    )


# Keep execution configs isolated by playbook. Besides making the run order
# explicit, this prevents unrelated traffic types from participating in IXIA's
# setup-time trial traffic.
NPI_DVT_ICEPACK_GTSW__PFC004_TEST_CONFIG = _create_focused_pfc_test_config(
    name="NPI_DVT_ICEPACK_GTSW__PFC004_TEST_CONFIG",
    traffic_item_names={
        "TEST_RDMA_TRAFFIC_30PCT_P1_TO_P4",
        "TEST_RDMA_TRAFFIC_30PCT_P2_TO_P4",
        "TEST_RDMA_TRAFFIC_30PCT_P3_TO_P4",
        "TEST_BE_24_TRAFFIC",
    },
    playbook_name="test_pfc_functionality_congestion_non_tc2_traffic",
)

NPI_DVT_ICEPACK_GTSW__PFC005_007_TEST_CONFIG = _create_focused_pfc_test_config(
    name="NPI_DVT_ICEPACK_GTSW__PFC005_007_TEST_CONFIG",
    traffic_item_names={
        "TEST_RDMA_TRAFFIC_90PCT_P1_TO_P4",
        "TEST_RDMA_TRAFFIC_90PCT_P2_TO_P4",
        "TEST_RDMA_TRAFFIC_90PCT_P3_TO_P4",
    },
    playbook_name="test_pfc_functionality_congestion_and_voq_credit_fairness",
)

NPI_DVT_ICEPACK_GTSW__PFC009_010_TEST_CONFIG = _create_focused_pfc_test_config(
    name="NPI_DVT_ICEPACK_GTSW__PFC009_010_TEST_CONFIG",
    traffic_item_names={
        "TEST_RDMA_TRAFFIC_90PCT_P1_TO_P4",
        "TEST_RDMA_TRAFFIC_90PCT_P2_TO_P4",
        "TEST_RDMA_TRAFFIC_90PCT_P3_TO_P4",
    },
    playbook_name="test_pfc_functionality_incast_voq_credit_fairness",
)

NPI_DVT_ICEPACK_GTSW__PFC012_TEST_CONFIG = _create_focused_pfc_test_config(
    name="NPI_DVT_ICEPACK_GTSW__PFC012_TEST_CONFIG",
    traffic_item_names={
        "TEST_RDMA_TRAFFIC_90PCT_P1_TO_P4",
        "TEST_RDMA_TRAFFIC_90PCT_P2_TO_P4",
    },
    playbook_name="test_pfc_functionality_port_flap",
)

NPI_DVT_ICEPACK_GTSW__PFC002_TEST_CONFIG = _create_focused_pfc_test_config(
    name="NPI_DVT_ICEPACK_GTSW__PFC002_TEST_CONFIG",
    traffic_item_names={"TRAFFIC_TC2_PFC_PAUSE_7500FPS"},
    playbook_name="test_tc2_pfc_wd_functionality",
)

NPI_DVT_ICEPACK_GTSW__PFC016_TEST_CONFIG = _create_focused_pfc_test_config(
    name="NPI_DVT_ICEPACK_GTSW__PFC016_TEST_CONFIG",
    traffic_item_names={"TRAFFIC_TC2_PFC_PAUSE_5000FPS"},
    playbook_name="test_tc2_pfc_wd_functionality_transient",
)

NPI_DVT_ICEPACK_GTSW__PFC017_TEST_CONFIG = _create_focused_pfc_test_config(
    name="NPI_DVT_ICEPACK_GTSW__PFC017_TEST_CONFIG",
    traffic_item_names={
        "TRAFFIC_TC2_PFC_PAUSE_7500FPS",
        "TEST_BE_24_TRAFFIC",
    },
    playbook_name="test_tc2_pfc_wd_functionality_non_impact_tc1",
)

_PFC013_RDMA_TRAFFIC_ITEMS = [
    "TEST_RDMA_TRAFFIC_90PCT_P1_TO_P4",
    "TEST_RDMA_TRAFFIC_90PCT_P2_TO_P4",
    "TEST_RDMA_TRAFFIC_90PCT_P3_TO_P4",
]
NPI_DVT_ICEPACK_GTSW__PFC013_TEST_CONFIG = _FOCUSED_PFC_BASE(
    name="NPI_DVT_ICEPACK_GTSW__PFC013_TEST_CONFIG",
    endpoints=_PFC_EGRESS_DUT_ENDPOINTS,
    basic_traffic_item_configs=_select_named_config_items(
        config_name="NPI_DVT_ICEPACK_GTSW__PFC013_TEST_CONFIG",
        items=_FOCUSED_PFC_BASE.basic_traffic_item_configs or [],
        expected_names=set(_PFC013_RDMA_TRAFFIC_ITEMS),
        item_type="traffic items",
    ),
    playbooks=[
        create_pfc_wedge_agent_crash_playbook(
            rdma_traffic_item_names=_PFC013_RDMA_TRAFFIC_ITEMS,
            source_interfaces=_PFC8_SRC_ENDPOINTS[:3],
            destination_interfaces=(
                ASH6_C085_GTSW_TH6_MULTI_NODE_PFC_TRAFFIC_DST_ENDPOINTS
            ),
            egress_device_name=GTSW001_L1002_C085_ASH6,
        )
    ],
)

_PFC015_TRAFFIC_ITEMS = _select_named_config_items(
    config_name="NPI_DVT_ICEPACK_GTSW__PFC015_TEST_CONFIG",
    items=_FOCUSED_PFC_BASE.basic_traffic_item_configs or [],
    expected_names={
        "TRAFFIC_TC2_PFC_PAUSE_7500FPS",
        "TEST_BE_24_TRAFFIC",
    },
    item_type="traffic items",
)
_PFC015_PAUSE_FRAME_RATE_FPS = int(
    next(
        item.line_rate
        for item in _PFC015_TRAFFIC_ITEMS
        if item.name == "TRAFFIC_TC2_PFC_PAUSE_7500FPS"
    )
)
NPI_DVT_ICEPACK_GTSW__PFC015_TEST_CONFIG = _FOCUSED_PFC_BASE(
    name="NPI_DVT_ICEPACK_GTSW__PFC015_TEST_CONFIG",
    basic_traffic_item_configs=_PFC015_TRAFFIC_ITEMS,
    playbooks=[
        create_pfc_repeated_watchdog_playbook(
            pause_traffic_item_name="TRAFFIC_TC2_PFC_PAUSE_7500FPS",
            be_traffic_item_name="TEST_BE_24_TRAFFIC",
            receiving_interfaces=_PFC8_SRC_ENDPOINTS[:1],
            device_name=GTSW001_L1001_C085_ASH6,
            pause_frame_rate_fps=_PFC015_PAUSE_FRAME_RATE_FPS,
        )
    ],
)

_PFC018_PAUSE_TRAFFIC_ITEM_NAME = "TRAFFIC_TC6_PFC_PAUSE_7500FPS_REVERSE"
_PFC018_PAUSE_TRAFFIC_ITEM = create_pfc_pause_traffic_config(
    src_endpoints=ASH6_C085_GTSW_TH6_MULTI_NODE_PFC_TRAFFIC_DST_ENDPOINTS,
    dest_endpoints=_PFC8_SRC_ENDPOINTS[:1],
    name=_PFC018_PAUSE_TRAFFIC_ITEM_NAME,
    line_rate=7500,
    packet_headers=TC6_PFC_PAUSE_PACKET_HEADERS,
)
NPI_DVT_ICEPACK_GTSW__PFC018_TEST_CONFIG = _FOCUSED_PFC_BASE(
    name="NPI_DVT_ICEPACK_GTSW__PFC018_TEST_CONFIG",
    endpoints=_PFC_EGRESS_DUT_ENDPOINTS,
    basic_traffic_item_configs=(
        _select_named_config_items(
            config_name="NPI_DVT_ICEPACK_GTSW__PFC018_TEST_CONFIG",
            items=_FOCUSED_PFC_BASE.basic_traffic_item_configs or [],
            expected_names={"TEST_RDMA_TRAFFIC_90PCT_P1_TO_P4"},
            item_type="traffic items",
        )
        + [_PFC018_PAUSE_TRAFFIC_ITEM]
    ),
    playbooks=[
        create_pfc_pause_non_impact_playbook(
            rdma_traffic_item_name="TEST_RDMA_TRAFFIC_90PCT_P1_TO_P4",
            pause_traffic_item_name=_PFC018_PAUSE_TRAFFIC_ITEM_NAME,
            pause_receiving_interfaces=(
                ASH6_C085_GTSW_TH6_MULTI_NODE_PFC_TRAFFIC_DST_ENDPOINTS
            ),
            rdma_source_interfaces=_PFC8_SRC_ENDPOINTS[:1],
            rdma_destination_interfaces=(
                ASH6_C085_GTSW_TH6_MULTI_NODE_PFC_TRAFFIC_DST_ENDPOINTS
            ),
            device_name=GTSW001_L1002_C085_ASH6,
            pause_priority=hc_types.Priority.PRIORITY_6,
            assert_no_watchdog_events=False,
        )
    ],
)

_PFC019_PAUSE_TRAFFIC_ITEM_NAME = "TRAFFIC_TC0_PFC_PAUSE_7500FPS_REVERSE"
_PFC019_PAUSE_TRAFFIC_ITEM = create_pfc_pause_traffic_config(
    src_endpoints=ASH6_C085_GTSW_TH6_MULTI_NODE_PFC_TRAFFIC_DST_ENDPOINTS,
    dest_endpoints=_PFC8_SRC_ENDPOINTS[:1],
    name=_PFC019_PAUSE_TRAFFIC_ITEM_NAME,
    line_rate=7500,
    packet_headers=TC0_PFC_PAUSE_PACKET_HEADERS,
)
NPI_DVT_ICEPACK_GTSW__PFC019_TEST_CONFIG = _FOCUSED_PFC_BASE(
    name="NPI_DVT_ICEPACK_GTSW__PFC019_TEST_CONFIG",
    endpoints=_PFC_EGRESS_DUT_ENDPOINTS,
    basic_traffic_item_configs=(
        _select_named_config_items(
            config_name="NPI_DVT_ICEPACK_GTSW__PFC019_TEST_CONFIG",
            items=_FOCUSED_PFC_BASE.basic_traffic_item_configs or [],
            expected_names={"TEST_RDMA_TRAFFIC_90PCT_P1_TO_P4"},
            item_type="traffic items",
        )
        + [_PFC019_PAUSE_TRAFFIC_ITEM]
    ),
    playbooks=[
        create_pfc_pause_non_impact_playbook(
            rdma_traffic_item_name="TEST_RDMA_TRAFFIC_90PCT_P1_TO_P4",
            pause_traffic_item_name=_PFC019_PAUSE_TRAFFIC_ITEM_NAME,
            pause_receiving_interfaces=(
                ASH6_C085_GTSW_TH6_MULTI_NODE_PFC_TRAFFIC_DST_ENDPOINTS
            ),
            rdma_source_interfaces=_PFC8_SRC_ENDPOINTS[:1],
            rdma_destination_interfaces=(
                ASH6_C085_GTSW_TH6_MULTI_NODE_PFC_TRAFFIC_DST_ENDPOINTS
            ),
            device_name=GTSW001_L1002_C085_ASH6,
            pause_priority=hc_types.Priority.PRIORITY_0,
        )
    ],
)
