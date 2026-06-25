# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe
"""Neutral shared symbols for BGP DC tests.

Phase 5.0d (B2) extraction. Symbols here are consumed by both:
- `routing/dc_routing/bgp_dc/common.py` (the BGP DC building-block layer)
- `playbooks/helpers/routing/bgp_dc/{restart,longevity,platform_hardening}_playbooks.py`
  (the BGP DC playbook helper layer)

Previously these lived in `testconfigs/internal/fboss_bgp_and_platform_hardening_conveyor.py`,
which created a layering-violation: lower layers (helpers + common) imported
from a higher layer (testconfig). They are now defined here and re-exported
from the original testconfig location for backward compatibility with
non-bgp_dc consumers.
"""

from taac.health_checks.healthcheck_definitions import (
    create_bgp_session_establish_check,
    create_ixia_packet_loss_check_traffic_split,
)
from taac.steps.step_definitions import (
    create_service_restart_steps,
)
from taac.test_as_a_config import types as taac_types

# Re-export `create_ixia_packet_loss_check_traffic_split` for the existing
# callers in testconfigs/internal/fboss_bgp_and_platform_hardening_conveyor.py
# and testconfigs/hyperport/* which import it from this module.
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


def get_ixia_healthcheck_stable_state(device_name: str):
    return create_ixia_packet_loss_check_traffic_split(
        device_name,
        expect_loss_traffic=["GOOD_BUT_LOSSY_NDP_TRAFFIC", "LOSSY_ROGUE_NDP_TRAFFIC"],
        no_loss_traffic=[
            "V6_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK",
            "V4_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK",
            "V6_LAYER3_TRAFFIC_DOWNLINK_AND_UPLINK",
        ],
    )
