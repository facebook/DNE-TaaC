# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""Spec 2.7 — Disruption and Recovery. UG qualification playbook factories.

- 2.7.1 Link Flap: Update Group Recovery After Physical Link Bounces (REAL)
- 2.7.2 Sustained Link Flapping Across Multiple Ports (REAL)
- 2.7.4 BGP Daemon Restart: Update Group Reconstruction (SKELETON)
- 2.7.5 Cold Start: Update Group Formation From Zero State (SKELETON)
- 2.7.6 FibAgent Restart: Update Group Stability During Data-Plane Agent Recovery (SKELETON)
"""

import typing as t

from taac.health_checks.healthcheck_definitions import (
    create_bgp_update_group_check,
    create_system_cpu_load_average_check,
)
from taac.playbooks.routing.factories.qual_bgp_update_group.tc7_cases.link_flap_recovery import (
    create_bgp_ug_link_flap_recovery_playbook as create_bgp_ug_link_flap_recovery_playbook,
)
from taac.stages.stage_definitions import create_steps_stage
from taac.steps.step_definitions import create_custom_step
from taac.testconfigs.routing.util.bgp_ebb_health_checks import (
    BGP_STANDARD_POSTCHECKS,
    BGP_STANDARD_SNAPSHOT_CHECKS,
)
from taac.test_as_a_config.types import (
    Playbook,
    PointInTimeHealthCheck,
    SnapshotHealthCheck,
)


def create_bgp_ug_sustained_link_flap_playbook(
    device_name: str,
    port_schedule: t.List[t.Dict[str, t.Any]],
    total_duration_s: int,
    prechecks: t.List[PointInTimeHealthCheck],
    postchecks: t.Optional[t.List[PointInTimeHealthCheck]] = None,
    snapshot_checks: t.Optional[t.List[SnapshotHealthCheck]] = None,
    stabilization_s: int = 30,
    checkpoint_interval_s: int = 900,
) -> Playbook:
    """Build the BGP++ Update Group qualification 2.7.2 playbook
    (Sustained Link Flapping Across Multiple Ports).

    Byte-wise-identical move of the legacy
    ``playbook_definitions.create_update_group_sustained_link_flap_playbook``
    under the routing framework naming. See the legacy docstring for the full
    spec / rationale / flow.
    """
    flap_step = create_custom_step(
        params_dict={
            "custom_step_name": "staggered_flap_with_isolation_check",
            "hostname": device_name,
            "port_schedule": port_schedule,
            "total_duration_s": total_duration_s,
            "stabilization_s": stabilization_s,
            "checkpoint_interval_s": checkpoint_interval_s,
        },
        description=(
            f"BGP++ Update Group qualification 2.7.2 -- rotate flap on "
            f"{len(port_schedule)} ports for {total_duration_s}s on "
            f"{device_name}; per-session isolation check after each cycle."
        ),
    )
    # 2.7.2 pass criteria #3 and #6:
    #   #3 "all update groups correctly formed, no stale entries"
    #      -> ``create_bgp_update_group_check`` (Thrift API per D108632994).
    #   #6 "1m, 5m and 15m load-averages never cross 12"
    #      -> ``create_system_cpu_load_average_check(baseline=12.0)``.
    # ``BGP_STANDARD_POSTCHECKS`` covers per-process CPU (400% threshold) and
    # memory but neither of the above, so extend the default postcheck list
    # here so every consumer of this factory asserts both spec bounds.
    if postchecks is None:
        postchecks = list(BGP_STANDARD_POSTCHECKS) + [
            create_system_cpu_load_average_check(baseline=12.0),
            create_bgp_update_group_check(expect_enabled=True),
        ]
    if snapshot_checks is None:
        snapshot_checks = list(BGP_STANDARD_SNAPSHOT_CHECKS)
    return Playbook(
        # Generic name -- reusable across EBB devices. Device-specific scope
        # lives in the surrounding TestConfig (e.g.
        # ``BAG013_ASH6_BGP_CONVEYOR_TEST_UPDATE_GROUP``), not in the
        # playbook name itself.
        name="update_group_sustained_link_flap",
        stages=[create_steps_stage(steps=[flap_step])],
        prechecks=prechecks,
        postchecks=postchecks,
        snapshot_checks=snapshot_checks,
    )


def create_bgp_ug_bgp_daemon_restart_playbook() -> Playbook:
    """Spec 2.7.4 — BGP Daemon Restart: Update Group Reconstruction. SKELETON."""
    raise NotImplementedError(
        "Spec 2.7.4 (bgp_daemon_restart) playbook not yet implemented"
    )


def create_bgp_ug_cold_start_playbook() -> Playbook:
    """Spec 2.7.5 — Cold Start: Update Group Formation From Zero State. SKELETON."""
    raise NotImplementedError("Spec 2.7.5 (cold_start) playbook not yet implemented")


def create_bgp_ug_fibagent_restart_playbook() -> Playbook:
    """Spec 2.7.6 — FibAgent Restart: Update Group Stability During Data-Plane Agent Recovery. SKELETON."""
    raise NotImplementedError(
        "Spec 2.7.6 (fibagent_restart) playbook not yet implemented"
    )


__all__ = [
    "create_bgp_ug_bgp_daemon_restart_playbook",
    "create_bgp_ug_cold_start_playbook",
    "create_bgp_ug_fibagent_restart_playbook",
    "create_bgp_ug_link_flap_recovery_playbook",
    "create_bgp_ug_sustained_link_flap_playbook",
]
