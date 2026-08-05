# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""BGP DC TestConfig-level check builders (Wave 3A hoist).

Hoisted OUT of ``testconfigs/fboss_solution_tests/fboss_bgp_and_platform_hardening_conveyor.py``
so the hardening conveyor, the routing BGP DC chronos-node testconfig, and any
future cross-domain consumer can share these building blocks without depending
on the higher-layer hardening-conveyor module.

Contents:
- ``_apply_tc_checks_to_playbooks`` — merge TC-level checks into each playbook.
- ``_PERMIT_ALL_POLICY_TERM`` — policy term that unconditionally accepts routes.
- ``build_bgp_dc_tc_prechecks`` — standard BGP DC TestConfig prechecks list.
- ``build_bgp_dc_tc_postchecks`` — standard BGP DC TestConfig postchecks list.
"""

from taac.constants import WEDGE_AGENT_BINDS_TO_CASCADE
from taac.health_checks.healthcheck_definitions import (
    create_cpu_utilization_check,
    create_device_core_dumps_check,
    create_memory_utilization_check,
    create_prefix_limit_check,
    create_service_restart_check,
    create_systemctl_active_state_check,
    create_unclean_exit_check,
)
from taac.testconfigs.routing.util.bgp_dc_healthchecks import (
    BGP_SESSION_HEALTHCHECK_NO_V6_LOSS_EXPECTED,
    get_ixia_healthcheck_stable_state,
)
from taac.health_check.health_check import types as hc_types

# Playbooks that intentionally restart one or more services: those restarts
# (and their systemd BindsTo cascade) must NOT be flagged by the TC-level
# SERVICE_RESTART_CHECK. Map playbook name -> services expected to restart.
# `test_agent_restart` restarts wedge_agent, which cascades (BindsTo) to
# bgpd / fboss_sw_agent / fboss_hw_agent@0 and brings openr down with it.
_PLAYBOOK_EXPECTED_RESTARTED_SERVICES = {
    "test_agent_restart": WEDGE_AGENT_BINDS_TO_CASCADE + ["openr"],
    # The L2 overload agent-churn playbooks (UTP L2M_002 / L2M_005 / L2M_009)
    # restart wedge_agent every 5 minutes and then coldboot it, so they take
    # the same allowlist as `test_agent_restart`.
    "test_hardening_of_ndp_overload_with_agent_churn": WEDGE_AGENT_BINDS_TO_CASCADE
    + ["openr"],
    "test_hardening_of_arp_overload_with_agent_churn": WEDGE_AGENT_BINDS_TO_CASCADE
    + ["openr"],
    "test_hardening_of_mac_overload_with_agent_churn": WEDGE_AGENT_BINDS_TO_CASCADE
    + ["openr"],
}


def _apply_tc_checks_to_playbooks(
    playbooks, tc_prechecks, tc_postchecks, tc_snapshot_checks
):
    """Merge TestConfig-level checks into each playbook.

    For each playbook, append tc_prechecks/tc_postchecks/tc_snapshot_checks
    to the playbook's existing checks (if any).

    For playbooks that intentionally restart services (see
    ``_PLAYBOOK_EXPECTED_RESTARTED_SERVICES``), the TC-level
    SERVICE_RESTART_CHECK is rebuilt with the matching
    ``expected_restarted_services`` so the by-design restart + its BindsTo
    cascade are not flagged as failures.
    """
    applied = []
    for pb in playbooks:
        postchecks = list(pb.postchecks or []) + tc_postchecks
        expected = _PLAYBOOK_EXPECTED_RESTARTED_SERVICES.get(pb.name)
        if expected:
            postchecks = [
                (
                    create_service_restart_check(expected_restarted_services=expected)
                    if getattr(c, "name", None)
                    == hc_types.CheckName.SERVICE_RESTART_CHECK
                    else c
                )
                for c in postchecks
            ]
        applied.append(
            pb(
                prechecks=list(pb.prechecks or []) + tc_prechecks,
                postchecks=postchecks,
                snapshot_checks=list(pb.snapshot_checks or []) + tc_snapshot_checks,
            )
        )
    return applied


# Policy term that unconditionally accepts all routes (ALWAYS match, no actions
# → bgpd defaults to PERMIT).
_PERMIT_ALL_POLICY_TERM = {
    "name": "RULE_ACCEPT_ALL",
    "description": "Unconditionally accept all prefixes",
    "policy_match_entries": {
        "name": "",
        "description": "",
        "match_logic_type": 1,
        "match_entries": [
            {
                "type": 20,  # ALWAYS
                "match_logic_type": 0,
            }
        ],
    },
}


def build_bgp_dc_tc_prechecks(prefix_limit, *, include_traffic_check, device_name=None):
    """Build the standard BGP DC TestConfig prechecks list. When
    ``include_traffic_check`` is True, the IXIA stable-state check is included
    (requires ``device_name``).

    Mirrors the inline `tc_prechecks` block in
    ``test_config_for_bgp_and_fboss_platform_hardening_in_conveyor`` exactly
    when ``include_traffic_check=True``.
    """
    return [
        create_systemctl_active_state_check(),
        *(
            [get_ixia_healthcheck_stable_state(device_name)]
            if include_traffic_check
            else []
        ),
        create_prefix_limit_check(prefix_limit=prefix_limit),
        create_unclean_exit_check(),
        create_memory_utilization_check(
            threshold=5 * (1024**3),
            threshold_by_service={
                "bgpd": 4.5 * (1024**3),
                "fsdb": 7 * (1024**3),
                "qsfp_service": 2 * (1024**3),
                "fboss_sw_agent": 12 * (1024**3),
                "fboss_hw_agent@0": 8 * (1024**3),
            },
            start_time_jq_var="test_case_start_time",
        ),
        BGP_SESSION_HEALTHCHECK_NO_V6_LOSS_EXPECTED,
    ]


def build_bgp_dc_tc_postchecks(
    prefix_limit, *, include_traffic_check, device_name=None
):
    """Build the standard BGP DC TestConfig postchecks list. When
    ``include_traffic_check`` is True, the IXIA stable-state check is included
    (requires ``device_name``).

    Mirrors the inline `tc_postchecks` block in
    ``test_config_for_bgp_and_fboss_platform_hardening_in_conveyor`` exactly
    when ``include_traffic_check=True``.
    """
    return [
        create_systemctl_active_state_check(),
        create_device_core_dumps_check(),
        *(
            [get_ixia_healthcheck_stable_state(device_name)]
            if include_traffic_check
            else []
        ),
        create_prefix_limit_check(prefix_limit=prefix_limit),
        BGP_SESSION_HEALTHCHECK_NO_V6_LOSS_EXPECTED,
        create_unclean_exit_check(),
        create_memory_utilization_check(
            threshold=5 * (1024**3),
            threshold_by_service={
                "bgpd": 4.5 * (1024**3),
                "fsdb": 5 * (1024**3),
                "qsfp_service": 2 * (1024**3),
                "fboss_sw_agent": 12 * (1024**3),
                "fboss_hw_agent@0": 8 * (1024**3),
            },
            start_time_jq_var="test_case_start_time",
        ),
        create_cpu_utilization_check(
            threshold=400.0, start_time_jq_var="test_case_start_time"
        ),
        create_service_restart_check(),
    ]
