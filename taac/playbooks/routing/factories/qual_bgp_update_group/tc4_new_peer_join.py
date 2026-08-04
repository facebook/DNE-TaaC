# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""Spec 2.4 — New Peer Joining a Busy Group. UG qualification playbook factories.

- 2.4.1 New Peer Joins, Receives Full Sync, Then a Peer Goes Down (REAL)
- 2.4.2 New Peer Joins, Then Routes Are Withdrawn (REAL)
- 2.4.3 New Peer Joins, Then Attribute Change on Existing Routes (REAL)
- 2.4.4 New Peer Added Dynamically via addPeer API (REAL)
"""

import typing as t

from taac.health_checks.healthcheck_definitions import (
    create_bgp_peer_route_set_equality_check,
    create_bgp_received_route_community_check,
    create_bgp_route_count_verification_check,
    create_bgp_session_establish_check,
    create_bgp_session_snapshot_check,
    create_bgp_stale_route_check,
    create_bgp_update_group_check,
    create_service_restart_check,
)
from taac.stages.stage_definitions import create_steps_stage
from taac.steps.step_definitions import (
    create_add_bgp_peers_step,
    create_advertise_withdraw_prefixes_step,
    create_custom_step,
    create_del_bgp_peers_step,
    create_ixia_api_step,
    create_longevity_step,
    create_snapshot_bgp_sent_route_counts_step,
    create_start_stop_bgp_peers_step,
    create_tcpdump_step,
    create_validation_step,
    create_verify_bgp_advertised_nlris_step,
    create_verify_bgp_peers_joined_running_step,
    create_verify_bgp_sent_route_count_delta_step,
    create_verify_bgp_sent_route_counts_uniform_step,
)
from taac.testconfigs.routing.util.bgp_ebb_health_checks import (
    BGP_STANDARD_POSTCHECKS,
    BGP_STANDARD_PRECHECKS,
    BGP_STANDARD_SNAPSHOT_CHECKS,
)
from taac.test_as_a_config.types import (
    Playbook,
    PointInTimeHealthCheck,
    SnapshotHealthCheck,
    Step,
)


def create_bgp_ug_new_peer_join_full_sync_resilience_playbook(
    device_name: str,
    control_peer_addrs: t.List[str],
    held_back_peer_addr: str,
    held_back_peer_regex: str,
    disp_peer_addrs: t.List[str],
    disp_peer_regex: str,
    disp_session_start_idx: int,
    disp_session_end_idx: int,
    b_keep_peer_addr: str,
    b_keep_route_count: int,
    b_var1_peer_regex: str,
    b_var1_peer_addr: str,
    b_var1_route_count: int,
    b_var2_peer_regex: str,
    b_var2_peer_addr: str,
    b_var2_route_count: int,
    ug_peer_group_substring: str = "EB-FA-V6",
    setup_convergence_s: int = 30,
    post_test_convergence_s: int = 60,
    post_inject_convergence_s: int = 30,
    setup_steps: t.Optional[t.List[Step]] = None,
    prechecks: t.Optional[t.List[PointInTimeHealthCheck]] = None,
    postchecks: t.Optional[t.List[PointInTimeHealthCheck]] = None,
    snapshot_checks: t.Optional[t.List[SnapshotHealthCheck]] = None,
) -> Playbook:
    """Build the BGP++ Update Group qualification 2.4.1 playbook
    (New Peer Joins, Receives Full Sync, Then a Peer Goes Down).

    See legacy ``playbook_definitions.create_new_peer_join_full_sync_resilience_playbook``
    for the full spec / rationale / flow docstring — this factory is the
    byte-wise-identical move under the routing framework naming.
    """
    phase_1_inject_steps = [
        create_start_stop_bgp_peers_step(
            peer_regex=b_var1_peer_regex,
            start=True,
            start_idx=1,
            end_idx=1,
            description=(
                f"Phase 1 (2.4.1): bring sender DG_B_VAR1 UP -- inject "
                f"{b_var1_route_count} routes while held-back is still down"
            ),
        ),
        create_longevity_step(
            duration=setup_convergence_s,
            description=(
                f"Phase 1 (2.4.1): settle {setup_convergence_s}s for "
                f"DG_B_VAR1 advertise to propagate via UG to side A receivers"
            ),
        ),
        create_validation_step(
            point_in_time_checks=[
                create_bgp_route_count_verification_check(
                    json_params={
                        "descriptions_to_check": list(control_peer_addrs),
                        "direction": "received",
                        "policy_type": "post_policy",
                        "expected_count": b_keep_route_count + b_var1_route_count,
                    },
                )
            ],
            description=(
                "Phase 1 verify (2.4.1): control peers received baseline + "
                "inject routes"
            ),
        ),
    ]

    trigger_steps = [
        create_start_stop_bgp_peers_step(
            peer_regex=held_back_peer_regex,
            start=True,
            start_idx=1,
            end_idx=1,
            description=("Phase 2a (2.4.1): bring held-back peer UP -- begin UG sync"),
        ),
        create_start_stop_bgp_peers_step(
            peer_regex=disp_peer_regex,
            start=False,
            start_idx=disp_session_start_idx,
            end_idx=disp_session_end_idx,
            description=(
                f"Phase 2b (2.4.1): kill DG_A_DISP sessions "
                f"{disp_session_start_idx}-{disp_session_end_idx} mid-sync "
                "(UG member churn during held-back's initial sync)"
            ),
        ),
        create_longevity_step(
            duration=post_test_convergence_s,
            description=(
                f"Phase 2 (2.4.1): settle {post_test_convergence_s}s for "
                "held-back sync + UG re-convergence"
            ),
        ),
        create_validation_step(
            point_in_time_checks=[
                create_bgp_peer_route_set_equality_check(
                    baseline_peer_addr=control_peer_addrs[0],
                    tested_peer_addrs=[held_back_peer_addr]
                    + list(control_peer_addrs[1:]),
                    anchor_route_count=b_keep_route_count + b_var1_route_count,
                )
            ],
            description=(
                "Phase 3 spec gate (2.4.1): held-back + remaining control peers "
                f"received {b_keep_route_count + b_var1_route_count} routes "
                "after sync (full initial dump survived DISP kill mid-sync)"
            ),
        ),
    ]

    expected_after_inject_50 = (
        b_keep_route_count + b_var1_route_count + b_var2_route_count
    )
    phase_3_checks = [
        create_bgp_session_establish_check(
            ignore_all_prefixes_except=[held_back_peer_addr],
        ),
        create_bgp_session_establish_check(
            ignore_all_prefixes_except=disp_peer_addrs,
            expected_established_sessions=0,
        ),
        create_bgp_peer_route_set_equality_check(
            baseline_peer_addr=control_peer_addrs[0],
            tested_peer_addrs=[held_back_peer_addr] + list(control_peer_addrs[1:]),
            anchor_route_count=expected_after_inject_50,
        ),
        create_service_restart_check(
            services=["Bgp"],
            daemons=["FibBgpGrpc"],
        ),
        create_bgp_stale_route_check(),
    ]

    phase_4_steps = [
        create_start_stop_bgp_peers_step(
            peer_regex=b_var2_peer_regex,
            start=True,
            start_idx=1,
            end_idx=1,
            description=(
                f"Phase 4 (2.4.1): bring sender DG_B_VAR2 UP -- inject "
                f"{b_var2_route_count} more routes (runtime update)"
            ),
        ),
        create_longevity_step(
            duration=post_inject_convergence_s,
            description=(
                f"Phase 4 (2.4.1): settle {post_inject_convergence_s}s for "
                "DG_B_VAR2 advertise to propagate"
            ),
        ),
        create_validation_step(
            point_in_time_checks=[
                create_bgp_peer_route_set_equality_check(
                    baseline_peer_addr=control_peer_addrs[0],
                    tested_peer_addrs=[held_back_peer_addr]
                    + list(control_peer_addrs[1:]),
                    anchor_route_count=expected_after_inject_50,
                )
            ],
            description=(
                "Phase 4 verify (2.4.1): held-back + remaining control peers "
                f"received {expected_after_inject_50} routes after runtime "
                "inject (no missing prefixes)"
            ),
        ),
    ]

    cleanup_steps = [
        create_start_stop_bgp_peers_step(
            peer_regex=disp_peer_regex,
            start=True,
            start_idx=disp_session_start_idx,
            end_idx=disp_session_end_idx,
            description="Phase 5 cleanup (2.4.1): restore DG_A_DISP sessions UP",
        ),
        create_start_stop_bgp_peers_step(
            peer_regex=b_var1_peer_regex,
            start=False,
            start_idx=1,
            end_idx=1,
            description="Phase 5 cleanup (2.4.1): bring DG_B_VAR1 back DOWN",
        ),
        create_start_stop_bgp_peers_step(
            peer_regex=b_var2_peer_regex,
            start=False,
            start_idx=1,
            end_idx=1,
            description="Phase 5 cleanup (2.4.1): bring DG_B_VAR2 back DOWN",
        ),
        create_start_stop_bgp_peers_step(
            peer_regex=held_back_peer_regex,
            start=False,
            start_idx=1,
            end_idx=1,
            description="Phase 5 cleanup (2.4.1): restore HELD to admin-DOWN",
        ),
        create_longevity_step(
            duration=setup_convergence_s,
            description=(
                f"Phase 5 cleanup (2.4.1): settle {setup_convergence_s}s for "
                "baseline state to converge"
            ),
        ),
    ]

    if prechecks is None:
        prechecks = [
            create_bgp_update_group_check(
                expect_enabled=True,
                peer_group_substrings=[ug_peer_group_substring],
            ),
            create_bgp_session_establish_check(
                ignore_all_prefixes_except=list(control_peer_addrs)
                + [b_keep_peer_addr],
            ),
            create_bgp_session_establish_check(
                ignore_all_prefixes_except=[
                    held_back_peer_addr,
                    b_var1_peer_addr,
                    b_var2_peer_addr,
                ],
                expected_established_sessions=0,
            ),
            create_bgp_route_count_verification_check(
                json_params={
                    "descriptions_to_check": list(control_peer_addrs),
                    "direction": "received",
                    "policy_type": "post_policy",
                    "expected_count": b_keep_route_count,
                },
            ),
        ]
    if postchecks is None:
        postchecks = list(phase_3_checks)
    if snapshot_checks is None:
        snapshot_checks = list(BGP_STANDARD_SNAPSHOT_CHECKS)

    kwargs = {
        "name": "new_peer_join_full_sync_resilience",
        "stages": [
            create_steps_stage(
                steps=phase_1_inject_steps,
                description="Phase 1 (2.4.1): inject 200 while held-back DOWN",
            ),
            create_steps_stage(
                steps=trigger_steps,
                description=(
                    "Phase 2 (2.4.1): held-back UP + DISP kill (mid-sync churn)"
                ),
            ),
            create_steps_stage(
                steps=phase_4_steps,
                description="Phase 4 (2.4.1): runtime inject 50 more",
            ),
        ],
        "cleanup_steps": cleanup_steps,
        "prechecks": prechecks,
        "postchecks": postchecks,
        "snapshot_checks": snapshot_checks,
    }
    if setup_steps is not None:
        kwargs["setup_steps"] = setup_steps
    return Playbook(**kwargs)


def create_bgp_ug_new_peer_join_routes_withdrawn_playbook(
    device_name: str,
    control_peer_addrs: t.List[str],
    held_back_peer_addr: str,
    held_back_peer_regex: str,
    b_keep_peer_addr: str,
    b_keep_route_count: int,
    b_var1_peer_regex: str,
    b_var1_peer_addr: str,
    b_var1_route_count: int,
    b_var1_device_group_regex: str,
    ug_peer_group_substring: str = "EB-FA-V6",
    setup_convergence_s: int = 30,
    post_test_convergence_s: int = 180,
    capture_tcpdump_device: t.Optional[str] = None,
    capture_tcpdump_path: str = "/tmp/bgp_capture_2_4_2.txt",
    setup_steps: t.Optional[t.List[Step]] = None,
    prechecks: t.Optional[t.List[PointInTimeHealthCheck]] = None,
    postchecks: t.Optional[t.List[PointInTimeHealthCheck]] = None,
    snapshot_checks: t.Optional[t.List[SnapshotHealthCheck]] = None,
) -> Playbook:
    """Build the BGP++ Update Group qualification 2.4.2 playbook
    (New Peer Joins, Then Routes Are Withdrawn).

    See legacy ``playbook_definitions.create_new_peer_join_routes_withdrawn_playbook``
    for the full spec / rationale / flow docstring — this factory is the
    byte-wise-identical move under the routing framework naming.
    """
    trigger_steps: t.List[Step] = []

    if capture_tcpdump_device is not None:
        trigger_steps.append(
            create_tcpdump_step(
                device_name=capture_tcpdump_device,
                mode="start_capture",
                capture_file_path=capture_tcpdump_path,
                description=(
                    "Phase 2 (2.4.2): start tcpdump capture (diagnostic -- "
                    "proves the withdrawal trigger fires on the wire)"
                ),
            )
        )

    trigger_steps.extend(
        [
            create_start_stop_bgp_peers_step(
                peer_regex=held_back_peer_regex,
                start=True,
                start_idx=1,
                end_idx=1,
                description=(
                    "Phase 2a (2.4.2): bring held-back peer UP -- begin UG sync"
                ),
            ),
            create_ixia_api_step(
                api_name="toggle_device_groups",
                args_dict={
                    "enable": False,
                    "device_group_name_regex": b_var1_device_group_regex,
                    "sleep_time_before_applying_change": 5,
                },
                description=(
                    "Phase 2b (2.4.2): admin-disable DG_B_VAR1 mid-sync -- "
                    "DUT withdraws B_VAR1's routes via UG to all members"
                ),
            ),
        ]
    )

    if capture_tcpdump_device is not None:
        trigger_steps.append(
            create_tcpdump_step(
                device_name=capture_tcpdump_device,
                mode="stop_capture",
                capture_file_path=capture_tcpdump_path,
                description="Phase 2 (2.4.2): stop tcpdump capture",
            )
        )

    trigger_steps.append(
        create_longevity_step(
            duration=post_test_convergence_s,
            description=(
                f"Phase 2 (2.4.2): settle {post_test_convergence_s}s for "
                "UG to converge on withdrawn state"
            ),
        )
    )

    phase_3_checks = [
        create_bgp_session_establish_check(
            ignore_all_prefixes_except=[held_back_peer_addr],
        ),
        create_bgp_session_establish_check(
            ignore_all_prefixes_except=[b_var1_peer_addr],
            expected_established_sessions=0,
        ),
        create_bgp_peer_route_set_equality_check(
            baseline_peer_addr=control_peer_addrs[0],
            tested_peer_addrs=[held_back_peer_addr] + list(control_peer_addrs[1:]),
            anchor_route_count=b_keep_route_count,
        ),
        create_service_restart_check(
            services=["Bgp"],
            daemons=["FibBgpGrpc"],
        ),
        create_bgp_stale_route_check(),
    ]

    cleanup_steps = [
        create_ixia_api_step(
            api_name="toggle_device_groups",
            args_dict={
                "enable": True,
                "device_group_name_regex": b_var1_device_group_regex,
                "sleep_time_before_applying_change": 0,
            },
            description="Phase 5 cleanup (2.4.2): re-enable DG_B_VAR1",
        ),
        create_start_stop_bgp_peers_step(
            peer_regex=held_back_peer_regex,
            start=False,
            start_idx=1,
            end_idx=1,
            description="Phase 5 cleanup (2.4.2): restore HELD to admin-DOWN",
        ),
        create_longevity_step(
            duration=setup_convergence_s,
            description=(
                f"Phase 5 cleanup (2.4.2): settle {setup_convergence_s}s for "
                "baseline state to converge"
            ),
        ),
    ]

    if prechecks is None:
        prechecks = [
            create_bgp_update_group_check(
                expect_enabled=True,
                peer_group_substrings=[ug_peer_group_substring],
            ),
            create_bgp_session_establish_check(
                ignore_all_prefixes_except=list(control_peer_addrs)
                + [b_keep_peer_addr, b_var1_peer_addr],
            ),
            create_bgp_session_establish_check(
                ignore_all_prefixes_except=[held_back_peer_addr],
                expected_established_sessions=0,
            ),
            create_bgp_route_count_verification_check(
                json_params={
                    "descriptions_to_check": list(control_peer_addrs),
                    "direction": "received",
                    "policy_type": "post_policy",
                    "expected_count": b_keep_route_count + b_var1_route_count,
                },
            ),
        ]
    if postchecks is None:
        postchecks = list(phase_3_checks)
    if snapshot_checks is None:
        snapshot_checks = list(BGP_STANDARD_SNAPSHOT_CHECKS)

    kwargs = {
        "name": "new_peer_join_routes_withdrawn",
        "stages": [
            create_steps_stage(
                steps=trigger_steps,
                description=(
                    "Phase 2 (2.4.2): held-back UP + sender session-DOWN "
                    "(mid-sync withdrawal trigger)"
                ),
            ),
        ],
        "cleanup_steps": cleanup_steps,
        "prechecks": prechecks,
        "postchecks": postchecks,
        "snapshot_checks": snapshot_checks,
    }
    if setup_steps is not None:
        kwargs["setup_steps"] = setup_steps
    return Playbook(**kwargs)


def create_bgp_ug_new_peer_join_attribute_change_playbook(
    device_name: str,
    control_peer_addrs: t.List[str],
    held_back_peer_addr: str,
    held_back_peer_regex: str,
    b_keep_peer_addr: str,
    b_keep_route_count: int,
    b_keep_peer_regex: str,
    b_keep_device_group_regex: str,
    b_keep_mutated_peer_addr: str,
    b_keep_mutated_device_group_regex: str,
    initial_community: str,
    mutated_community: str,
    ug_peer_group_substring: str = "EB-FA-V6",
    setup_convergence_s: int = 30,
    initial_withdraw_settle_s: int = 90,
    post_test_convergence_s: int = 60,
    setup_steps: t.Optional[t.List[Step]] = None,
    prechecks: t.Optional[t.List[PointInTimeHealthCheck]] = None,
    postchecks: t.Optional[t.List[PointInTimeHealthCheck]] = None,
    snapshot_checks: t.Optional[t.List[SnapshotHealthCheck]] = None,
) -> Playbook:
    """Build the BGP++ Update Group qualification 2.4.3 playbook
    (New Peer Joins, Then Attribute Change on Existing Routes).

    See legacy ``playbook_definitions.create_new_peer_join_attribute_change_playbook``
    for the full spec / rationale / flow docstring — this factory is the
    byte-wise-identical move under the routing framework naming.
    """
    trigger_steps: t.List[Step] = [
        create_start_stop_bgp_peers_step(
            peer_regex=held_back_peer_regex,
            start=True,
            start_idx=1,
            end_idx=1,
            description=("Phase 2a (2.4.3): bring held-back peer UP -- begin UG sync"),
        ),
        create_ixia_api_step(
            api_name="toggle_device_groups",
            args_dict={
                "enable": False,
                "device_group_name_regex": b_keep_device_group_regex,
                "sleep_time_before_applying_change": 0,
            },
            description=(
                "Phase 2b (2.4.3): DG-disable KEEP_INITIAL -- DUT withdraws "
                "the 300 routes carrying the initial community via hold-timer"
            ),
        ),
        create_longevity_step(
            duration=initial_withdraw_settle_s,
            description=(
                f"Phase 2b-settle (2.4.3): {initial_withdraw_settle_s}s for "
                "DUT hold-timer expiry + adj-RIB-out withdraw"
            ),
        ),
        create_ixia_api_step(
            api_name="toggle_device_groups",
            args_dict={
                "enable": True,
                "device_group_name_regex": b_keep_mutated_device_group_regex,
                "sleep_time_before_applying_change": 0,
            },
            description=(
                "Phase 2c (2.4.3): DG-enable KEEP_MUTATED -- same 300 prefixes "
                "re-advertised with mutated community; DUT must re-distribute "
                "via UG to HELD+CTRL"
            ),
        ),
        create_longevity_step(
            duration=post_test_convergence_s,
            description=(
                f"Phase 2 (2.4.3): settle {post_test_convergence_s}s for "
                "KEEP_MUTATED session establish, full route re-advertise, "
                "and DUT UG re-distribute to HELD+CTRL"
            ),
        ),
    ]

    phase_3_checks = [
        create_bgp_session_establish_check(
            ignore_all_prefixes_except=[held_back_peer_addr],
        ),
        create_bgp_session_establish_check(
            ignore_all_prefixes_except=[b_keep_mutated_peer_addr],
        ),
        create_bgp_received_route_community_check(
            baseline_peer_addr=control_peer_addrs[0],
            tested_peer_addrs=[held_back_peer_addr] + list(control_peer_addrs[1:]),
            anchor_community=mutated_community,
            forbidden_communities=[initial_community],
        ),
        create_bgp_route_count_verification_check(
            json_params={
                "descriptions_to_check": [held_back_peer_addr]
                + list(control_peer_addrs),
                "direction": "received",
                "policy_type": "post_policy",
                "expected_count": b_keep_route_count,
            },
        ),
        create_service_restart_check(
            services=["Bgp"],
            daemons=["FibBgpGrpc"],
        ),
        create_bgp_stale_route_check(),
    ]

    cleanup_steps = [
        create_ixia_api_step(
            api_name="toggle_device_groups",
            args_dict={
                "enable": False,
                "device_group_name_regex": b_keep_mutated_device_group_regex,
                "sleep_time_before_applying_change": 0,
            },
            description=("Phase 5 cleanup (2.4.3): DG-disable KEEP_MUTATED"),
        ),
        create_ixia_api_step(
            api_name="toggle_device_groups",
            args_dict={
                "enable": True,
                "device_group_name_regex": b_keep_device_group_regex,
                "sleep_time_before_applying_change": 0,
            },
            description=(
                "Phase 5 cleanup (2.4.3): DG-enable KEEP_INITIAL -- restores "
                "baseline initial-community advertisement"
            ),
        ),
        create_start_stop_bgp_peers_step(
            peer_regex=held_back_peer_regex,
            start=False,
            start_idx=1,
            end_idx=1,
            description="Phase 5 cleanup (2.4.3): restore HELD to admin-DOWN",
        ),
        create_longevity_step(
            duration=setup_convergence_s,
            description=(
                f"Phase 5 cleanup (2.4.3): settle {setup_convergence_s}s for "
                "baseline state to converge"
            ),
        ),
    ]

    if prechecks is None:
        prechecks = [
            create_bgp_update_group_check(
                expect_enabled=True,
                peer_group_substrings=[ug_peer_group_substring],
            ),
            create_bgp_session_establish_check(
                ignore_all_prefixes_except=list(control_peer_addrs)
                + [b_keep_peer_addr],
            ),
            create_bgp_session_establish_check(
                ignore_all_prefixes_except=[held_back_peer_addr],
                expected_established_sessions=0,
            ),
            create_bgp_received_route_community_check(
                baseline_peer_addr=control_peer_addrs[0],
                tested_peer_addrs=list(control_peer_addrs[1:]),
                anchor_community=initial_community,
            ),
        ]
    if postchecks is None:
        postchecks = list(phase_3_checks)
    if snapshot_checks is None:
        snapshot_checks = list(BGP_STANDARD_SNAPSHOT_CHECKS)

    kwargs = {
        "name": "new_peer_join_attribute_change",
        "stages": [
            create_steps_stage(
                steps=trigger_steps,
                description=(
                    "Phase 2 (2.4.3): held-back UP + community swap on "
                    "sender (mid-sync attribute mutation trigger)"
                ),
            ),
        ],
        "cleanup_steps": cleanup_steps,
        "prechecks": prechecks,
        "postchecks": postchecks,
        "snapshot_checks": snapshot_checks,
    }
    if setup_steps is not None:
        kwargs["setup_steps"] = setup_steps
    return Playbook(**kwargs)


def create_bgp_ug_add_peer_dynamic_playbook(
    device_name: str,
    control_peer_addrs: t.List[str],
    spare_peer_addr: str,
    spare_local_addr: str,
    spare_remote_as: int,
    spare_peer_regex: str,
    b_var2_peer_regex: str,
    b_var2_route_count: int,
    spare_peer_group_name: str = "EB-FA-V6",
    spare_egress_policy_name: t.Optional[str] = None,
    ug_peer_group_substring: str = "EB-FA-V6",
    expected_update_group_count: int = 2,
    held_member_peer_regex: t.Optional[str] = None,
    held_member_peer_addr: t.Optional[str] = None,
    ixia_ebgp_capture_interface: t.Optional[str] = None,
    dump_capture_duration_s: int = 180,
    setup_convergence_s: int = 30,
    spare_absent_settle_s: int = 30,
    post_add_convergence_s: int = 60,
    post_inject_convergence_s: int = 30,
    setup_steps: t.Optional[t.List[Step]] = None,
    prechecks: t.Optional[t.List[PointInTimeHealthCheck]] = None,
    postchecks: t.Optional[t.List[PointInTimeHealthCheck]] = None,
    snapshot_checks: t.Optional[t.List[SnapshotHealthCheck]] = None,
) -> Playbook:
    """Build the BGP++ Update Group qualification 2.4.4 playbook
    (New Peer Added Dynamically via the addPeer control-plane API).

    Design (causal proof that ``addPeers`` created the peer):

    * The spare eBGP peer (``spare_peer_addr``) is ABSENT from the DUT's static
      bgpcpp config at baseline -- its interface /127 and IXIA session are
      provisioned by the topology, but no DUT BGP *neighbor* exists.
    * Stage A: record the group dump count ``M`` on the existing EB-FA-V6
      members, then bring the spare's IXIA session UP and assert it is NOT
      Established (the DUT has no neighbor, so no session forms).
    * Stage B: call ``addPeers`` for the spare, then assert it establishes,
      lands in the SAME EB-FA-V6 update group (JOINED_RUNNING), the group is
      intact, its sent-route count is uniform-and-non-zero with the existing
      members, AND its per-peer advertised-NLRI set is byte-identical to the
      members' (i.e. it received the full ``M``-prefix dump -- identical dump
      ⇒ same update group).
    * Stage C: inject 50 more prefixes from an existing iBGP source (DG_B_VAR2)
      and assert the spare AND all existing members receive them (+N delta).
    * Cleanup: ``delPeers`` the spare, bring its IXIA session + the inject source
      back DOWN, and assert the spare left cleanly.

    Distribution is verified two ways, both scoped to the existing members + the
    spare: (1) the ``postpolicy_sent_prefix_count`` PS gauge (portable
    count-parity baseline) and (2) per-peer advertised-NLRI identity via
    ``getPostfilterAdvertisedNetworks`` -- the adj-RIB-out reads populate under
    Update Group on the fixed bag013 binary (T271301144 / T281417842, proven by
    2.5.x + 2.9.7), so the literal NLRI-set identity check is meaningful here.
    """
    members_and_spare = list(control_peer_addrs) + [spare_peer_addr]

    baseline_record_steps = [
        # Pre-condition 3 / step 1 say CONFIRM, not just record: the DUT must
        # already be distributing the same non-zero dump M to every existing
        # member before the spare is introduced. Snapshotting alone would defer
        # the only uniformity assertion to Stage B, where it also covers the
        # spare -- so a pre-broken baseline would surface there and read as an
        # addPeers failure, which is precisely the thing this test isolates.
        create_verify_bgp_sent_route_counts_uniform_step(
            hostname=device_name,
            peer_addrs=list(control_peer_addrs),
            min_count=1,
            max_spread=0,
            description=(
                "Stage A spec gate (2.4.4): every existing EB-FA-V6 member is "
                "already receiving the SAME non-zero group dump M before the "
                "spare is introduced (pre-condition 3 / step 1)"
            ),
        ),
        create_snapshot_bgp_sent_route_counts_step(
            hostname=device_name,
            snapshot_key="ug_2_4_4_baseline",
            peer_addrs=list(control_peer_addrs),
            description=(
                "Stage A (2.4.4): record baseline group dump M on the existing "
                "EB-FA-V6 members (sent-count snapshot)"
            ),
        ),
        create_start_stop_bgp_peers_step(
            peer_regex=spare_peer_regex,
            start=True,
            start_idx=1,
            end_idx=1,
            description=(
                "Stage A (2.4.4): bring the SPARE IXIA session UP -- the DUT has "
                "NO neighbor for it yet (absent from the static bgpcpp config)"
            ),
        ),
        create_longevity_step(
            duration=spare_absent_settle_s,
            description=(
                f"Stage A (2.4.4): settle {spare_absent_settle_s}s -- the DUT "
                "ignores the spare's TCP SYNs (no neighbor configured)"
            ),
        ),
        create_validation_step(
            point_in_time_checks=[
                create_bgp_session_establish_check(
                    ignore_all_prefixes_except=[spare_peer_addr],
                    expected_established_sessions=0,
                )
            ],
            description=(
                "Stage A spec gate (2.4.4): spare is NOT Established with its IXIA "
                "session UP -- proves the later addPeers call is what creates it"
            ),
        ),
    ]

    add_peer_steps = [
        create_add_bgp_peers_step(
            hostname=device_name,
            peer_addr=spare_peer_addr,
            local_addr=spare_local_addr,
            remote_as=spare_remote_as,
            peer_group_name=spare_peer_group_name,
            # Default None = inherit the peer-group's policy, which is what
            # spec step 3 asks for. Kept as an opt-in escape hatch only.
            egress_policy_name=spare_egress_policy_name,
            description=(
                "Stage B (2.4.4): addPeers -- dynamically create the spare "
                "neighbor via the TBgpService.addPeers control-plane RPC "
                "(peer-group EB-FA-V6, inheriting its egress policy)"
            ),
        ),
        create_longevity_step(
            duration=post_add_convergence_s,
            description=(
                f"Stage B (2.4.4): settle {post_add_convergence_s}s for the spare "
                "to establish and receive the full UG dump"
            ),
        ),
        create_validation_step(
            point_in_time_checks=[
                create_bgp_session_establish_check(
                    ignore_all_prefixes_except=[spare_peer_addr],
                ),
                # expected_group_count is the LOAD-BEARING half of spec
                # criterion 2: the spare must join the EXISTING EB-FA-V6 group,
                # so the total group count must be UNCHANGED from baseline. The
                # membership/NLRI gates below cannot catch a split -- a peer in
                # its own group still reports JOINED_RUNNING and can still hold
                # an identical prefix set -- and the peer-group check tolerates
                # a peer-group spanning multiple update groups by design.
                create_bgp_update_group_check(
                    expect_enabled=True,
                    peer_group_substrings=[ug_peer_group_substring],
                    expected_group_count=expected_update_group_count,
                ),
            ],
            description=(
                "Stage B verify (2.4.4): spare Established + EB-FA-V6 update "
                "group intact + total group count UNCHANGED (no new/orphaned "
                "group -- spec criterion 2)"
            ),
        ),
        create_verify_bgp_peers_joined_running_step(
            hostname=device_name,
            peer_addrs=[spare_peer_addr],
            description=(
                "Stage B spec gate (2.4.4): spare is JOINED_RUNNING in the "
                "EB-FA-V6 update group (same existing group, not a new one)"
            ),
        ),
        create_verify_bgp_sent_route_counts_uniform_step(
            hostname=device_name,
            peer_addrs=members_and_spare,
            min_count=1,
            max_spread=0,
            description=(
                "Stage B spec gate (2.4.4): spare received the full M-prefix dump "
                "-- its sent-count is non-zero and identical to the existing "
                "EB-FA-V6 members (count-parity baseline)"
            ),
        ),
        create_verify_bgp_advertised_nlris_step(
            hostname=device_name,
            # /128 of each tracked member + the spare -- scopes the identity
            # assertion to EXACTLY members_and_spare (same scope as the count
            # check above), so it never sweeps in the held/disp eBGP groups that
            # share the ug_ebgp_v6 parent network.
            peer_parent_prefixes=[f"{addr}/128" for addr in members_and_spare],
            min_count=1,
            require_identical=True,
            description=(
                "Stage B spec gate (2.4.4): the spare's per-peer advertised-NLRI "
                "set (getPostfilterAdvertisedNetworks, populated under UG on the "
                "fixed bag013 binary) is IDENTICAL to the existing EB-FA-V6 "
                "members' -- literal full-dump parity, and identical dump ⇒ same "
                "update group (spec step 7 / criteria 2+3)"
            ),
        ),
    ]

    inject_steps = [
        create_snapshot_bgp_sent_route_counts_step(
            hostname=device_name,
            snapshot_key="ug_2_4_4_pre_inject",
            peer_addrs=members_and_spare,
            description=(
                "Stage C (2.4.4): snapshot sent-count on members + spare before "
                "the runtime inject"
            ),
        ),
        create_start_stop_bgp_peers_step(
            peer_regex=b_var2_peer_regex,
            start=True,
            start_idx=1,
            end_idx=1,
            description=(
                f"Stage C (2.4.4): bring DG_B_VAR2 UP -- inject "
                f"{b_var2_route_count} more prefixes from an existing iBGP source"
            ),
        ),
        create_longevity_step(
            duration=post_inject_convergence_s,
            description=(
                f"Stage C (2.4.4): settle {post_inject_convergence_s}s for the "
                "inject to propagate via the UG"
            ),
        ),
        create_verify_bgp_sent_route_count_delta_step(
            hostname=device_name,
            snapshot_key="ug_2_4_4_pre_inject",
            min_delta=b_var2_route_count,
            max_delta=b_var2_route_count,
            peer_addrs=members_and_spare,
            description=(
                f"Stage C spec gate (2.4.4): spare AND all existing members "
                f"received the +{b_var2_route_count} runtime inject"
            ),
        ),
    ]

    # Stage D (OPT-IN, spec step 7 / criterion 3): prove the spare's dump carries
    # the same PATH ATTRIBUTES as a statically-configured member's, not just the
    # same prefixes. Needs an on-wire capture -- getPostfilterAdvertisedNetworks
    # is prefix-level. Runs LAST so the flap it performs cannot perturb the
    # Stage A/B/C assertions, and it compares against HELD (admin-DOWN at
    # baseline) so no ESTABLISHED member is disturbed.
    dump_compare_stages = []
    if ixia_ebgp_capture_interface and held_member_peer_regex:
        dump_compare_stages.append(
            create_steps_stage(
                steps=[
                    create_custom_step(
                        params_dict={
                            "custom_step_name": "test_bgp_add_peer_dump_compare",
                            "hostname": device_name,
                            "ixia_capture_interface": ixia_ebgp_capture_interface,
                            "spare_peer_regex": spare_peer_regex,
                            "member_peer_regex": held_member_peer_regex,
                            "capture_duration_seconds": dump_capture_duration_s,
                        },
                        description=(
                            "Stage D spec gate (2.4.4): the addPeers-created "
                            "spare and a statically-configured member of the "
                            "same update group receive IDENTICAL initial dumps "
                            "-- NLRI AND path attributes (criterion 3)"
                        ),
                    )
                ],
                description=(
                    "Stage D (2.4.4): on-wire initial-dump attribute parity, "
                    "spare vs static member"
                ),
            )
        )

    cleanup_steps = [
        create_del_bgp_peers_step(
            hostname=device_name,
            peer_addrs=[spare_peer_addr],
            description=(
                "Cleanup (2.4.4): delPeers -- remove the dynamically-added spare "
                "neighbor (restore static-config baseline)"
            ),
        ),
        create_start_stop_bgp_peers_step(
            peer_regex=spare_peer_regex,
            start=False,
            start_idx=1,
            end_idx=1,
            description="Cleanup (2.4.4): bring the SPARE IXIA session DOWN",
        ),
        create_start_stop_bgp_peers_step(
            peer_regex=b_var2_peer_regex,
            start=False,
            start_idx=1,
            end_idx=1,
            description="Cleanup (2.4.4): bring DG_B_VAR2 back DOWN",
        ),
        # Stage D flapped HELD UP to get a second initial dump to compare
        # against. Put it back to its admin-DOWN baseline so the testbed is left
        # as it was found -- otherwise a subsequent --skip-setup-tasks rerun
        # starts with an extra established member.
        *(
            [
                create_start_stop_bgp_peers_step(
                    peer_regex=held_member_peer_regex,
                    start=False,
                    start_idx=1,
                    end_idx=1,
                    description=(
                        "Cleanup (2.4.4): return HELD to admin-DOWN (Stage D "
                        "brought it up for the dump comparison)"
                    ),
                )
            ]
            if dump_compare_stages and held_member_peer_regex
            else []
        ),
        create_longevity_step(
            duration=setup_convergence_s,
            description=(
                f"Cleanup (2.4.4): settle {setup_convergence_s}s for baseline "
                "state to converge"
            ),
        ),
        create_validation_step(
            point_in_time_checks=[
                create_bgp_session_establish_check(
                    ignore_all_prefixes_except=[spare_peer_addr],
                    expected_established_sessions=0,
                ),
                # Spec step 9 wants "no stale routes" AFTER delPeers. The
                # postcheck copy of this check cannot cover that: post-test
                # checks run BEFORE cleanup_steps, so only this one observes the
                # post-removal state.
                create_bgp_stale_route_check(),
                # And the group count must return to baseline -- the removed
                # peer must not leave an orphaned group behind.
                create_bgp_update_group_check(
                    expect_enabled=True,
                    peer_group_substrings=[ug_peer_group_substring],
                    expected_group_count=expected_update_group_count,
                ),
            ],
            description=(
                "Cleanup verify (2.4.4): spare left cleanly after delPeers -- "
                "no lingering session, no stale routes, group count back to "
                "baseline (spec step 9)"
            ),
        ),
    ]

    # NB every same-name check below carries an explicit ``check_id``. Without
    # one, ``TaacRunner.get_checks_to_run`` collapses checks into a
    # ``{check.name: check}`` dict (``override_duplicate_checks`` defaults True)
    # and only the LAST BGP_SESSION_ESTABLISH_CHECK survives -- silently dropping
    # the control-peer assertion. Checks that carry a check_id bypass that dict.
    if prechecks is None:
        prechecks = [
            # Pin the BASELINE group count so the Stage B "unchanged" assertion
            # is anchored to a verified starting point rather than an assumption.
            create_bgp_update_group_check(
                expect_enabled=True,
                peer_group_substrings=[ug_peer_group_substring],
                expected_group_count=expected_update_group_count,
            ),
            create_bgp_session_establish_check(
                check_id="ug_2_4_4_pre_controls",
                ignore_all_prefixes_except=list(control_peer_addrs),
            ),
            create_bgp_session_establish_check(
                check_id="ug_2_4_4_pre_spare",
                ignore_all_prefixes_except=[spare_peer_addr],
                expected_established_sessions=0,
            ),
        ]
    if postchecks is None:
        postchecks = [
            create_bgp_session_establish_check(
                check_id="ug_2_4_4_post_controls",
                ignore_all_prefixes_except=list(control_peer_addrs),
            ),
            # The spare is STILL Established here: post-test checks run BEFORE
            # ``cleanup_steps`` (which is where delPeers + spare-session-down
            # live), so the dynamically added peer must still be up. Asserting
            # that is strictly stronger than asserting it is gone -- it proves
            # the added peer survived the Stage C runtime inject.
            create_bgp_session_establish_check(
                check_id="ug_2_4_4_post_spare",
                ignore_all_prefixes_except=[spare_peer_addr],
                expected_established_sessions=1,
            ),
            create_service_restart_check(
                services=["Bgp"],
                daemons=["FibBgpGrpc"],
            ),
            create_bgp_stale_route_check(),
        ]
    if snapshot_checks is None:
        snapshot_checks = list(BGP_STANDARD_SNAPSHOT_CHECKS) + [
            # Spec criterion 5: existing members must be UNDISTURBED -- no
            # session flaps. The standard list (core dumps + peer-route
            # snapshot) catches route churn but not a member that flapped and
            # re-established mid-test: it would still be Established at the end
            # with the same route counts. This snapshot's flap/uptime checks are
            # on by default. The spare is excluded because it legitimately
            # appears (addPeers) and disappears (delPeers) during the test.
            create_bgp_session_snapshot_check(
                # The spare legitimately appears (addPeers) and departs
                # (delPeers). HELD is excluded only when Stage D runs, since
                # that stage brings it up from admin-DOWN -- also not churn.
                parent_prefixes_to_ignore=(
                    [f"{spare_peer_addr}/128"]
                    + (
                        [f"{held_member_peer_addr}/128"]
                        if dump_compare_stages and held_member_peer_addr
                        else []
                    )
                ),
            ),
        ]

    kwargs = {
        "name": "bgp_ug_add_peer_dynamic",
        "stages": [
            create_steps_stage(
                steps=baseline_record_steps,
                description=(
                    "Stage A (2.4.4): record M + bring spare IXIA UP, prove NOT "
                    "Established (no DUT neighbor)"
                ),
            ),
            create_steps_stage(
                steps=add_peer_steps,
                description=(
                    "Stage B (2.4.4): addPeers -> establish + join EB-FA-V6 UG + "
                    "full-dump parity"
                ),
            ),
            create_steps_stage(
                steps=inject_steps,
                description="Stage C (2.4.4): runtime inject 50 -> spare + members",
            ),
            *dump_compare_stages,
        ],
        "cleanup_steps": cleanup_steps,
        "prechecks": prechecks,
        "postchecks": postchecks,
        "snapshot_checks": snapshot_checks,
    }
    if setup_steps is not None:
        kwargs["setup_steps"] = setup_steps
    return Playbook(**kwargs)


# =============================================================================
# BGP++ Update Group qualification 2.3.x -- Backpressure & Blocking Behavior
#
# Spec series 2.3 tests UG behavior under egress backpressure (DUT's adj-RIB-out
# queue blocking when peers can't drain advertised UPDATEs fast enough). All 4
# tests share the same "heavy-attr storm" recipe: advertise N prefixes rapidly
# from an iBGP plane sender, each route carrying 32 communities + 16 extended
# communities + a 255-ASN AS_PATH + random MED/LP/Origin -- enough attribute
# bytes per prefix to fill DUT's per-peer egress queues.
#
# All 4 playbook factories below are device-agnostic; the bag013 (EBB full-scale)
# testconfig wires them up. Specs:
#   2.3.1 fast_peers_not_held_back  -- UG isolates slow peers; fast peers + BGP_MON keep flowing
#   2.3.2 peer_blocks_down_recover   -- 16 eBGP go down mid-storm, come back, get full re-sync
#   2.3.3 withdraw_attr_change       -- withdraw + re-add + LP-modify under backpressure
#   2.3.4 all_peers_block_down_recover -- ALL eBGP simultaneously down + back, shadow-RIB re-sync
# =============================================================================
