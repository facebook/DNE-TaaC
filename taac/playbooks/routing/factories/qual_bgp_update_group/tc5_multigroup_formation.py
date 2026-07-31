# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""Spec 2.5 — Multi-Group Formation Correctness. UG qualification playbook factories.

Implemented:
- 2.5.1 Multiple Groups Formed for Different Outbound Policies

Pending (SKELETON, raises NotImplementedError at call time; not wired into a
TestConfig, so raising is safe):
- 2.5.2 Scale Withdraw: 10+ Peers in Same Group, Withdraw Routes
"""

import typing as t

from taac.health_checks.healthcheck_definitions import (
    create_bgp_update_group_check,
    create_memory_utilization_check,
    create_system_cpu_load_average_check,
)
from taac.playbooks.routing.factories.qual_bgp_update_group.tc9_edge_cases import (
    _no_crash_checks,
)
from taac.stages.stage_definitions import create_steps_stage
from taac.steps.step_definitions import (
    create_advertise_withdraw_prefixes_step,
    create_longevity_step,
    create_snapshot_bgp_sent_route_counts_step,
    create_validation_step,
    create_verify_bgp_sent_route_count_delta_step,
    create_verify_bgp_sent_route_counts_uniform_step,
)
from taac.testconfigs.routing.util.bgp_ebb_health_checks import (
    BGP_STANDARD_POSTCHECKS,
    BGP_STANDARD_SNAPSHOT_CHECKS,
)
from taac.test_as_a_config.types import (
    Playbook,
    PointInTimeHealthCheck,
    SnapshotHealthCheck,
    Step,
)


def create_bgp_ug_multiple_groups_outbound_policies_playbook(
    *,
    device_name: str,
    # --- Group-formation structure check (crit 1/3) -- STRICT ---
    # Peer-group substrings, one update group per (peer-group x AFI): EB-EB-V4/V6
    # iBGP, EB-FA-V4/V6 eBGP = 4 groups. BGP-MON is NOT tested (DNE-confirmed: the
    # monitor peers do not establish on the bag013 conveyor node -- production
    # "monitor peers never establish").
    ibgp_v6_peer_group: str,
    ibgp_v4_peer_group: str,
    ebgp_v6_peer_group: str,
    ebgp_v4_peer_group: str,
    expected_member_counts: t.Dict[str, int],
    expected_policy_names: t.Dict[str, t.List[str]],
    expected_group_count: int,
    # --- Distribution PS-gauge scopes (crit 2 + crit 3) ---
    # iBGP peers selected by peer-address subnet per AFI.
    ibgp_v6_peer_parent_prefixes: t.List[str],
    ibgp_v4_peer_parent_prefixes: t.List[str],
    # Genuinely-new v6 eBGP inject pool (measured at the iBGP-v6 egress).
    ebgp_v6_inject_pool_regex: str,
    # --- Checks ---
    prechecks: t.List[PointInTimeHealthCheck],
    postchecks: t.Optional[t.List[PointInTimeHealthCheck]] = None,
    snapshot_checks: t.Optional[t.List[SnapshotHealthCheck]] = None,
    # --- Tunables ---
    inject_route_count: int = 100,
    # Distribution (eBGP->iBGP re-advertise) is STRICT + UNCONDITIONAL: HW-validated
    # 2026-07-29 / 2026-07-31 -- all 496 iBGP-v6 peers received +100 uniformly
    # (convergence-polled; no flap storm, unlike 2.6.1). No measure-first escape hatch.
    distribution_count_window: int = 10,
    distribution_tolerance: int = 3,
    inject_settle_s: int = 30,
    load_avg_baseline: float = 12.0,
    vmhwm_absolute_threshold_bytes: t.Optional[int] = None,
) -> Playbook:
    """Build the BGP++ Update Group qualification 2.5.1 playbook (Multiple Groups
    Formed for Different Outbound Policies).

    Intent (spec 2.5.1): peers with different outbound policies form SEPARATE
    update groups; each distributes independently with no cross-group / cross-AFI
    leakage. BGP-MON is NOT tested (DNE-confirmed: the monitor peers do not
    establish on the bag013 conveyor node -- "monitor peers never establish").

    Flow:
      1. Group formation (crit 1/3) -- STRICT: one UG structure check asserts each
         peer-group x AFI is its own update group (EB-EB-V4/V6 keyed on EB-EB-OUT;
         EB-FA-V4/V6 on EB-FA-OUT), member counts match the HW baseline (iBGP 496 /
         eBGP 140 / AFI), and there are exactly 4 groups total -- plus no crash.
      2. Distribution (crit 2 + crit 3) -- STRICT: withdraw the v6 eBGP inject pool
         (so its later advertise is a genuine +N), snapshot the iBGP-v6 + iBGP-v4 PS
         gauges, advertise the 100 new v6 routes, settle, then assert -- via the PS
         gauge (UG-safe, T271301144) -- the iBGP-v6 group grew by ~100 uniformly
         (routes reach all members identically, crit 2) and the iBGP-v4 group did NOT
         grow (crit 3, cross-AFI no-leak). Distribution is STRICT + UNCONDITIONAL:
         HW-validated 2026-07-29 / 2026-07-31 -- all 496 iBGP-v6 peers received +100
         uniformly (convergence-polled; no flap storm, unlike 2.6.1).
    """
    inject_min_delta = max(1, inject_route_count - distribution_count_window)

    # --- Stage 1: group formation (crit 1/3) -- STRICT -------------------------
    group_formation_stage = create_steps_stage(
        steps=[
            create_validation_step(
                point_in_time_checks=[
                    create_bgp_update_group_check(
                        peer_group_substrings=[
                            ibgp_v6_peer_group,
                            ibgp_v4_peer_group,
                            ebgp_v6_peer_group,
                            ebgp_v4_peer_group,
                        ],
                        expected_member_counts=expected_member_counts,
                        expected_policy_names=expected_policy_names,
                        expected_group_count=expected_group_count,
                        check_id="multigroup_formation_structure",
                    ),
                    *_no_crash_checks(),
                ],
                description=(
                    "2.5.1 crit 1/3 -- each peer-group x AFI forms its own update "
                    "group (EB-EB-V4/V6 iBGP on EB-EB-OUT, EB-FA-V4/V6 eBGP on "
                    "EB-FA-OUT), 4 groups total; no crash"
                ),
            ),
        ],
        description="2.5.1 -- multi-group formation for different outbound policies",
    )

    # --- Stage 2: distribution (crit 2 + crit 4-receives + crit 3) -------------
    distribution_steps: t.List[Step] = [
        # Baseline: withdraw the v6 inject pool (it comes up Active at build) so its
        # later advertise is a genuinely-new +N at the iBGP-v6 egress.
        create_advertise_withdraw_prefixes_step(
            device_name=device_name,
            advertise=False,
            prefix_pool_regex=ebgp_v6_inject_pool_regex,
            prefix_start_index=0,
            prefix_end_index=inject_route_count,
            description=(
                "2.5.1 baseline -- withdraw the v6 eBGP inject pool so its later "
                "advertise is a genuinely-new +N"
            ),
        ),
        create_longevity_step(
            duration=inject_settle_s,
            description="2.5.1 baseline -- settle after withdrawing the inject pool",
        ),
        create_snapshot_bgp_sent_route_counts_step(
            hostname=device_name,
            snapshot_key="multigroup_ibgp_v6",
            peer_parent_prefixes=ibgp_v6_peer_parent_prefixes,
            description="2.5.1 -- snapshot iBGP v6 PS (delta ref for the v6 inject)",
        ),
        create_snapshot_bgp_sent_route_counts_step(
            hostname=device_name,
            snapshot_key="multigroup_ibgp_v4",
            peer_parent_prefixes=ibgp_v4_peer_parent_prefixes,
            description=(
                "2.5.1 -- snapshot iBGP v4 PS (cross-AFI no-leak ref; the v6 inject "
                "must NOT grow the iBGP v4 group)"
            ),
        ),
        create_advertise_withdraw_prefixes_step(
            device_name=device_name,
            advertise=True,
            prefix_pool_regex=ebgp_v6_inject_pool_regex,
            prefix_start_index=0,
            prefix_end_index=inject_route_count,
            description=(
                f"2.5.1 -- advertise {inject_route_count} genuinely-new v6 eBGP "
                "routes (the DUT should re-advertise them to the iBGP v6 group)"
            ),
        ),
        # crit 2: every iBGP v6 peer's PS grew by >= ~inject_route_count.
        # PROTOTYPE: convergence-POLLED instead of a fixed post-inject settle --
        # no `create_longevity_step` before it; the step polls the per-peer delta
        # until every peer has received the inject AND the counts hold stable for
        # the stability window, up to the hard timeout. Adapts to the emergent
        # eBGP->iBGP re-advertise time (no fixed-settle guessing / idle tail).
        create_verify_bgp_sent_route_count_delta_step(
            hostname=device_name,
            snapshot_key="multigroup_ibgp_v6",
            peer_parent_prefixes=ibgp_v6_peer_parent_prefixes,
            min_delta=inject_min_delta,
            tolerance=distribution_tolerance,
            convergence_hard_timeout_seconds=120.0,
            convergence_poll_interval_seconds=10.0,
            convergence_stability_window_seconds=20.0,
            description=(
                f"2.5.1 crit 2 -- every iBGP v6 peer's PS grew by >= "
                f"~{inject_route_count} (routes distributed within the group reach "
                "all members)"
            ),
        ),
        # crit 2: identical counts across the iBGP v6 group.
        create_verify_bgp_sent_route_counts_uniform_step(
            hostname=device_name,
            peer_parent_prefixes=ibgp_v6_peer_parent_prefixes,
            description=(
                "2.5.1 crit 2 -- iBGP v6 sent-counts identical across the group "
                "(all members received the same route set)"
            ),
        ),
        # crit 3: no cross-AFI leak -- the iBGP v4 group did NOT grow from the v6
        # inject. STRICT (v6 routes structurally cannot enter the iBGP-v4 group):
        # the signed delta is bounded to [0, tolerance].
        create_verify_bgp_sent_route_count_delta_step(
            hostname=device_name,
            snapshot_key="multigroup_ibgp_v4",
            peer_parent_prefixes=ibgp_v4_peer_parent_prefixes,
            min_delta=0,
            max_delta=distribution_tolerance,
            tolerance=distribution_tolerance,
            description=(
                "2.5.1 crit 3 -- no cross-AFI leak: the iBGP v4 group did NOT grow "
                "from the v6 inject (v6 routes never appear in the iBGP-v4 group)"
            ),
        ),
    ]
    distribution_stage = create_steps_stage(
        steps=distribution_steps,
        description=(
            "2.5.1 -- distribution: inject 100 new v6 eBGP routes and verify they "
            "reach every iBGP v6 peer uniformly, with no cross-AFI leak"
        ),
    )

    stages = [group_formation_stage, distribution_stage]

    # Always-appended UG bounds (like tc6 / the other UG playbooks): system
    # load-average + UG still enabled -- whether the caller takes the default
    # BGP_STANDARD_POSTCHECKS bundle or supplies its own list, so they can never be
    # silently dropped.
    base_postchecks = (
        list(postchecks) if postchecks is not None else list(BGP_STANDARD_POSTCHECKS)
    )
    postchecks = base_postchecks + [
        create_system_cpu_load_average_check(baseline=load_avg_baseline),
        create_bgp_update_group_check(expect_enabled=True),
    ]
    if vmhwm_absolute_threshold_bytes is not None:
        postchecks.append(
            create_memory_utilization_check(
                vmhwm_threshold=vmhwm_absolute_threshold_bytes
            )
        )
    if snapshot_checks is None:
        snapshot_checks = list(BGP_STANDARD_SNAPSHOT_CHECKS)

    return Playbook(
        name="bgp_ug_multiple_groups_outbound_policies",
        stages=stages,
        prechecks=prechecks,
        postchecks=postchecks,
        snapshot_checks=snapshot_checks,
    )


def create_bgp_ug_scale_withdraw_10plus_peers_playbook() -> Playbook:
    """Spec 2.5.2 — Scale Withdraw: 10+ Peers in Same Group, Withdraw Routes. SKELETON."""
    raise NotImplementedError(
        "Spec 2.5.2 (scale_withdraw_10plus_peers) playbook not yet implemented"
    )
