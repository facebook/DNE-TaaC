# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe
"""Neutral shared symbols for BGP DC tests.

Wave 3A hoist. Symbols here are consumed by:
- `testconfigs/routing/util/bgp_dc_stages.py` (BGP DC stage-composition layer)
- `playbooks/playbook_definitions.py` (BGP DC playbook helpers)
- `testconfigs/fboss_solution_tests/fboss_bgp_and_platform_hardening_conveyor.py`
  (re-exports for non-bgp_dc consumers)
- `testconfigs/routing/fboss_bgp_plus_plus_chronos_node_test_config.py`
"""

from taac.health_checks.healthcheck_definitions import (
    create_bgp_session_establish_check,
    create_ixia_packet_loss_check_traffic_split,
)
from taac.steps.step_definitions import (
    create_service_restart_steps,
)
from taac.test_as_a_config import types as taac_types

# Re-export `create_ixia_packet_loss_check_traffic_split` for existing callers.
__all__ = [
    "AGENT_RESTART_STEPS",
    "BGP_RESTART_STEPS",
    "BGP_SESSION_HEALTHCHECK_NO_V6_LOSS_EXPECTED",
    "create_ixia_packet_loss_check_traffic_split",
    "get_ixia_healthcheck_ignore_cpu_and_v4_directional_traffic",
    "get_ixia_healthcheck_stable_state",
]


BGP_SESSION_HEALTHCHECK_NO_V6_LOSS_EXPECTED = create_bgp_session_establish_check(
    ignore_all_prefixes_except=[
        # Generate 50 IPv6 addresses with 8:: subnet (11,13,15,17,19,1b,...)
        f"2401:db00:e50d:11:8::{i:x}"
        for i in range(17, 117, 2)
    ]
    + [
        # Generate 50 IPv6 addresses with 9:: subnet, same hex pattern
        f"2401:db00:e50d:11:9::{i:x}"
        for i in range(17, 117, 2)
    ],
    verbose=True,
)

BGP_RESTART_STEPS = create_service_restart_steps(taac_types.Service.BGP)
AGENT_RESTART_STEPS = create_service_restart_steps(taac_types.Service.AGENT)


def get_ixia_healthcheck_ignore_cpu_and_v4_directional_traffic(device_name: str):
    return create_ixia_packet_loss_check_traffic_split(
        device_name,
        expect_loss_traffic=[
            "GOOD_BUT_LOSSY_NDP_TRAFFIC",
            "LOSSY_ROGUE_NDP_TRAFFIC",
            "V4_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK",
        ],
        no_loss_traffic=[
            "V6_LAYER3_TRAFFIC_DOWNLINK_AND_UPLINK",
            "V6_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK",
        ],
    )


def get_ixia_healthcheck_stable_state(
    device_name: str, clear_traffic_stats: bool = False
):
    return create_ixia_packet_loss_check_traffic_split(
        device_name,
        expect_loss_traffic=["GOOD_BUT_LOSSY_NDP_TRAFFIC", "LOSSY_ROGUE_NDP_TRAFFIC"],
        no_loss_traffic=[
            "V6_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK",
            "V4_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK",
            "V6_LAYER3_TRAFFIC_DOWNLINK_AND_UPLINK",
        ],
        clear_traffic_stats=clear_traffic_stats,
    )
