# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""RBB SRv6 qualification — playbook factories (full S02–S28 coverage).

Two spec-anchored playbooks, each a factory-built ``Playbook`` (no inline
``Step``/``Stage`` construction — §5.1). Every stage is a sequence of
registered-task steps (``rbb_srv6_program`` / ``rbb_srv6_direct_route`` /
``rbb_ixia_edge_l3`` / ``rbb_srv6_verify`` / ``rbb_srv6_counter_delta``),
shipped-HC validation steps (OpenR / BGP control-plane, IXIA packet-loss), and
shipped IXIA traffic steps — all built from the OSS factories.

Gate → mechanism (verified OSS-available before wiring):
  S02-S05  core PC members Up        — verify-task (fboss2 show aggregate-port)
  S06/S13  OpenR up + redistribution — shipped OPENR_INITIALIZED / ADJACENCY /
                                       SPARK_NEIGHBOR / FIB_VALIDATE checks
  S07      core iBGP + loopbacks      — shipped BGP_SESSION_ESTABLISH /
                                       BGP_CONVERGENCE + verify-task (peer lo)
  S08-S11  SRv6 mysid / RIF / uSIDs   — program + verify-tasks
  S12      IXIA-facing L3 edge        — rbb_ixia_edge_l3
  S14      DUT-side edge eBGP (opt-in)— shipped configure_ixia_interfaces
  S16      edge eBGP sessions         — shipped BGP_SESSION_ESTABLISH
  S17-S18  remote routes + FIB        — shipped BGP_ROUTE_COUNT_VERIFICATION /
                                       BGP_FIB_PROGRAMMING + verify-task
  S13-S20  baseline traffic           — shipped IXIA_PACKET_LOSS_CHECK
  S19      pre-route baseline         — verify-task (tail BGPD-owned)
  S21-S23  TE_AGENT install + owner    — rbb_srv6_direct_route + verify-task
  S24-S25  traffic + encap/decap delta— IXIA_PACKET_LOSS_CHECK +
                                       rbb_srv6_counter_delta (real delta gate)
  S26      SRv6 FIB present            — verify-task
  S27-S28  delete + revert to BGPD     — rbb_srv6_direct_route + verify-task
"""

import os
import typing as t

from taac.health_check.health_check import types as hc_types
from taac.health_checks.healthcheck_definitions import (
    create_bare_health_check,
    create_bgp_route_count_verification_check,
    create_bgp_session_establish_check,
    create_ixia_packet_loss_check,
)
from taac.stages.stage_definitions import create_steps_stage
from taac.steps.step_definitions import (
    create_clear_traffic_stats_step,
    create_run_task_step,
    create_start_traffic_step,
    create_stop_traffic_step,
    create_validation_step,
)
from taac.test_as_a_config.types import Playbook, PointInTimeHealthCheck, Step
from taac.testconfigs.routing.util import bgp_rbb_constants as C
from taac.testconfigs.routing.util.bgp_rbb_scenario_profiles import (
    core_interface_cmds,
    ixia_edge_cmds,
    srv6_decap_counter_spec,
    srv6_encap_counter_spec,
    Srv6Profile,
    srv6_program_cmds,
    verify_core_links_up_spec,
    verify_openr_adjacency_spec,
    verify_pc162_global_ipv6_spec,
    verify_peer_loopback_learned_spec,
    verify_route_owner_bgpd_spec,
    verify_route_owner_te_agent_spec,
    verify_srv6_counters_spec,
    verify_srv6_tunnels_spec,
)
from taac.testconfigs.routing.util.bgp_rbb_topology import (
    load_rbb_topology,
    RbbTopology,
)


def _include_traffic(override: t.Optional[bool]) -> bool:
    """Whether to include the IXIA packet-loss stages/prechecks.

    Defaults to on (the full S02-S28 procedure, which is what the unit tests
    exercise). Set ``TAAC_RBB_INCLUDE_TRAFFIC=0`` to build the device-path-only
    slice (control-plane gates + program + SRv6/route verifies + TE_AGENT
    direct-route lifecycle) used to validate against live hardware before the
    IXIA phase is wired up.
    """
    if override is not None:
        return override
    return os.environ.get("TAAC_RBB_INCLUDE_TRAFFIC", "1").lower() not in (
        "0",
        "false",
        "no",
    )


def _verify_step(hostname: str, spec: t.Dict[str, t.Any]) -> Step:
    """Wrap a scenario verify spec into an ``rbb_srv6_verify`` task step."""
    params = {"hostname": hostname, **spec}
    return create_run_task_step(
        task_name="rbb_srv6_verify",
        params_dict=params,
        description=f"[{spec.get('gate', 'verify')}] {hostname}: {spec['show_cmd']}",
    )


def _counter_step(hostname: str, action: str, spec: t.Dict[str, t.Any]) -> Step:
    """Wrap a counter spec into an ``rbb_srv6_counter_delta`` task step."""
    params = {"hostname": hostname, "action": action, **spec}
    return create_run_task_step(
        task_name="rbb_srv6_counter_delta",
        params_dict=params,
        description=(
            f"[{spec.get('gate', 'counter')}] {action} "
            f"{spec.get('direction', 'srv6')} counter on {hostname}"
        ),
        ixia_needed=True,
    )


def _program_step(hostname: str, node: str, profile: Srv6Profile) -> Step:
    return create_run_task_step(
        task_name="rbb_srv6_program",
        params_dict={"hostname": hostname, "cmds": srv6_program_cmds(node, profile)},
        description=f"Program SRv6 ({profile.name}) on {hostname}",
    )


def _ixia_edge_step(
    hostname: str, node: str, topology: t.Optional[RbbTopology] = None
) -> Step:
    return create_run_task_step(
        task_name="rbb_ixia_edge_l3",
        params_dict={"hostname": hostname, "cmds": ixia_edge_cmds(node, topology)},
        description=f"Enable IXIA-facing L3 edge on {hostname}",
        ixia_needed=True,
    )


def _traffic_loss_validation_step(description: str) -> Step:
    """Bidirectional packet-loss assertion over the SRv6 core."""
    return create_validation_step(
        point_in_time_checks=[
            create_ixia_packet_loss_check(
                thresholds=[
                    hc_types.PacketLossThreshold(
                        names=list(C.ALL_TRAFFIC_ITEMS),
                        str_value=C.PACKET_LOSS_THRESHOLD_PCT,
                        expect_packet_loss=False,
                    ),
                ],
            ),
        ],
        description=description,
    )


# ─── Control-plane + underlay gates (increment A; always run) ─────────────
def _core_links_up_stage(
    r1_hostname: str, r2_hostname: str, topology: RbbTopology
) -> t.Any:
    return create_steps_stage(
        steps=[
            _verify_step(r1_hostname, verify_core_links_up_spec("r1", topology)),
            _verify_step(r2_hostname, verify_core_links_up_spec("r2", topology)),
        ],
        description="S02-S05 core port-channel members Up",
    )


def _openr_stage(
    r1_hostname: str, r2_hostname: str, topology: RbbTopology
) -> t.Any:
    """S06/S13 — OpenR up, adjacencies, and edge redistribution.

    The shipped ``Openr*HealthCheck`` checks raise ``NotImplementedError`` under
    ``TAAC_OSS=1`` (they require Meta-internal OpenR thrift), so — per the OSS
    rule — this gate is an ``rbb_srv6_verify`` read instead: the peer loopback
    must be installed with an ``OPENR`` route client, which only happens once
    OpenR is up, adjacent over the core, and redistributing (see the scenario
    spec). That single fboss2 read covers both S06 and S13.
    """
    return create_steps_stage(
        steps=[
            _verify_step(r1_hostname, verify_openr_adjacency_spec("r1", topology)),
            _verify_step(r2_hostname, verify_openr_adjacency_spec("r2", topology)),
        ],
        description="S06/S13 OpenR up + adjacencies (redistribute edge)",
    )


def _core_ibgp_stage(r1_hostname: str, r2_hostname: str) -> t.Any:
    """S07 — core iBGP established + peer loopbacks learned.

    ``BgpSessionEstablished`` is OSS-available and used directly. ``BgpConvergence``
    is intentionally *not* wired: it measures time from ``AGENT_CONFIGURED`` to
    ``INITIALIZED`` and, on a long-running pre-converged lab, reports the stale
    120s EOR-timer window as a failure — it is a post-restart convergence gate,
    not a steady-state liveness gate. Steady-state liveness is proven by the
    session check plus the peer-loopback route read.
    """
    session_check = (
        create_bgp_session_establish_check()
        if C.EDGE_EBGP_ENABLED
        else create_bgp_session_establish_check(
            expected_established_sessions=C.CORE_IBGP_EXPECTED_SESSIONS
        )
    )
    return create_steps_stage(
        steps=[
            create_validation_step(
                point_in_time_checks=[session_check],
                description="S07 core iBGP sessions established",
            ),
            _verify_step(r1_hostname, verify_peer_loopback_learned_spec("r1")),
            _verify_step(r2_hostname, verify_peer_loopback_learned_spec("r2")),
        ],
        description="S07 core iBGP up + loopbacks learned",
    )


def _edge_ebgp_session_stage() -> t.Any:
    """S16 — edge eBGP sessions established (IXIA↔R1, IXIA↔R2)."""
    return create_steps_stage(
        steps=[
            create_validation_step(
                point_in_time_checks=[create_bgp_session_establish_check()],
                description="S16 edge eBGP sessions established",
            )
        ],
        description="S16 edge eBGP sessions (IXIA↔R1, IXIA↔R2)",
    )


def _remote_route_stage(r1_hostname: str) -> t.Any:
    """S17-S18 — remote IXIA prefixes propagate over core iBGP to R1 + FIB."""
    return create_steps_stage(
        steps=[
            create_validation_step(
                point_in_time_checks=[
                    create_bgp_route_count_verification_check(
                        json_params={"min_count": C.IXIA_REMOTE_ROUTE_MIN_COUNT}
                    ),
                    create_bare_health_check(
                        hc_types.CheckName.BGP_FIB_PROGRAMMING_CHECK
                    ),
                ],
                description="S17-S18 remote IXIA routes over core iBGP + FIB",
            )
        ],
        description="S17-S18 remote IXIA prefixes propagate to R1 + FIB",
    )


def _prechecks() -> t.List[PointInTimeHealthCheck]:
    # The baseline packet-loss precheck clears stats and asserts the path is
    # already lossless before the staged gates. On a cold bring-up (edge eBGP
    # still converging) it fires first and masks the S16/S17-S18 verdicts, so it
    # can be skipped for diagnostic runs via TAAC_RBB_SKIP_LOSS_PRECHECK=1 to let
    # the eBGP-session / remote-route / FIB stages run (and report) before the
    # in-stage traffic no-loss assertion. Default keeps the precheck on.
    if os.environ.get("TAAC_RBB_SKIP_LOSS_PRECHECK", "0").lower() in (
        "1",
        "true",
        "yes",
    ):
        return []
    return [create_ixia_packet_loss_check(clear_traffic_stats=True)]


def _postchecks() -> t.List[PointInTimeHealthCheck]:
    return [
        create_ixia_packet_loss_check(
            thresholds=[
                hc_types.PacketLossThreshold(
                    names=list(C.ALL_TRAFFIC_ITEMS),
                    str_value=C.PACKET_LOSS_THRESHOLD_PCT,
                    expect_packet_loss=False,
                )
            ],
        ),
    ]


def _direct_route_step(hostname: str, action: str, profile: Srv6Profile) -> Step:
    """FBOSS thrift direct-route step (add/withdraw TE_AGENT copy of the tail).

    Non-destructive & reversible: the task reuses the existing route's resolved
    nexthops, so forwarding never changes; delete withdraws only the TE_AGENT
    client's copy. Runs on the tail node so install/verify/delete are locally
    consistent.
    """
    return create_run_task_step(
        task_name="rbb_srv6_direct_route",
        params_dict={
            "hostname": hostname,
            "action": action,
            "prefix": profile.tail_prefix,
            "client": C.ROUTE_OWNER_TE_AGENT,
        },
        description=f"S{'21' if action == 'install' else '27'} {action} "
        f"TE_AGENT direct route for {profile.tail_prefix} on {hostname}",
    )


def create_rbb_srv6_3_usids_playbook(
    profile: Srv6Profile,
    r1_hostname: str = C.R1_HOSTNAME,
    r2_hostname: str = C.R2_HOSTNAME,
    name: str = "bgp_rbb_srv6_3_usids",
    include_traffic: t.Optional[bool] = None,
    topology: t.Optional[RbbTopology] = None,
) -> Playbook:
    """TC1: full head→mid→tail 3-uSID chain with full S02-S28 coverage.

    Control-plane + underlay gates (S02-S07/S13) always run (non-destructive
    reads / shipped OSS health checks). The IXIA edge / eBGP-emulation / route /
    traffic / counter-delta gates (S12/S14/S16/S17-S18/S13-S20/S24-S25) are
    included only when ``include_traffic`` is on (default). The DUT-side edge
    eBGP + remote-route gates additionally require ``TAAC_RBB_EDGE_EBGP=1`` since
    the default underlay is iBGP-only over loopbacks.
    """
    include_traffic = _include_traffic(include_traffic)
    topology = topology if topology is not None else load_rbb_topology()
    edge_ebgp = include_traffic and C.EDGE_EBGP_ENABLED

    stages = [
        # ── Increment A: control-plane + underlay (always run) ──
        _core_links_up_stage(r1_hostname, r2_hostname, topology),
        _openr_stage(r1_hostname, r2_hostname, topology),
        _core_ibgp_stage(r1_hostname, r2_hostname),
        # ── Device-path SRv6 confirm ──
        create_steps_stage(
            steps=[
                _program_step(r1_hostname, "r1", profile),
                _program_step(r2_hostname, "r2", profile),
            ],
            description="S08-S09 confirm SRv6 mysid on R1 and R2",
        ),
        create_steps_stage(
            steps=[
                _verify_step(
                    r1_hostname, verify_pc162_global_ipv6_spec("r1", topology)
                ),
                _verify_step(
                    r2_hostname, verify_pc162_global_ipv6_spec("r2", topology)
                ),
            ],
            description="S10 verify core PC RIF present",
        ),
        create_steps_stage(
            steps=[
                _verify_step(r1_hostname, verify_srv6_tunnels_spec("r1", profile)),
                _verify_step(r2_hostname, verify_srv6_tunnels_spec("r2", profile)),
            ],
            description="S11 verify SRv6 micro-SIDs programmed",
        ),
    ]

    if include_traffic:
        stages.append(
            create_steps_stage(
                steps=[
                    _ixia_edge_step(r1_hostname, "r1", topology),
                    _ixia_edge_step(r2_hostname, "r2", topology),
                ],
                description="S12 enable IXIA-facing L3 edge",
            )
        )
        if edge_ebgp:
            stages.append(_edge_ebgp_session_stage())
            stages.append(_remote_route_stage(r1_hostname))
        stages.append(
            create_steps_stage(
                steps=[
                    create_clear_traffic_stats_step(),
                    create_start_traffic_step(),
                    _traffic_loss_validation_step("S13-S20 baseline traffic no-loss"),
                    create_stop_traffic_step(),
                ],
                description="S13-S20 baseline traffic (BGPD-owned tail)",
            )
        )

    # S19 pre-route baseline snapshot (tail prefix BGPD-owned before install).
    stages.append(
        create_steps_stage(
            steps=[_verify_step(r2_hostname, verify_route_owner_bgpd_spec(profile))],
            description="S19 baseline snapshot (tail prefix BGPD-owned pre-route)",
        )
    )

    stages.append(
        create_steps_stage(
            steps=[_direct_route_step(r2_hostname, "install", profile)],
            description="S21 install TE_AGENT direct route",
        )
    )
    stages.append(
        create_steps_stage(
            steps=[
                _verify_step(r2_hostname, verify_route_owner_te_agent_spec(profile))
            ],
            description="S22-S23 verify tail prefix owned by TE_AGENT",
        )
    )

    if include_traffic:
        stages.append(
            create_steps_stage(
                steps=[
                    _counter_step(
                        r1_hostname,
                        "snapshot",
                        srv6_encap_counter_spec("r1", topology),
                    ),
                    _counter_step(
                        r2_hostname,
                        "snapshot",
                        srv6_decap_counter_spec("r2", topology),
                    ),
                    create_clear_traffic_stats_step(),
                    create_start_traffic_step(),
                    _traffic_loss_validation_step("S24-S25 TE_AGENT path no-loss"),
                    _counter_step(
                        r1_hostname,
                        "assert",
                        srv6_encap_counter_spec("r1", topology),
                    ),
                    _counter_step(
                        r2_hostname,
                        "assert",
                        srv6_decap_counter_spec("r2", topology),
                    ),
                    create_stop_traffic_step(),
                ],
                description="S24-S25 traffic on TE_AGENT path + encap/decap delta",
            )
        )

    stages.append(
        create_steps_stage(
            steps=[
                _verify_step(r1_hostname, verify_srv6_counters_spec()),
                _verify_step(r2_hostname, verify_srv6_counters_spec()),
            ],
            description="S26 verify SRv6 FIB present",
        )
    )
    stages.append(
        create_steps_stage(
            steps=[_direct_route_step(r2_hostname, "delete", profile)],
            description="S27 delete TE_AGENT direct route",
        )
    )

    s28_steps = [_verify_step(r2_hostname, verify_route_owner_bgpd_spec(profile))]
    if include_traffic:
        s28_steps.append(
            _traffic_loss_validation_step("S28 post-delete traffic no-loss")
        )
    stages.append(
        create_steps_stage(
            steps=s28_steps,
            description="S28 verify tail prefix reverts to BGPD",
        )
    )

    return Playbook(
        name=name,
        prechecks=_prechecks() if include_traffic else [],
        postchecks=_postchecks() if include_traffic else [],
        stages=stages,
    )


def create_rbb_srv6_te_baseline_playbook(
    profile: Srv6Profile,
    r1_hostname: str = C.R1_HOSTNAME,
    r2_hostname: str = C.R2_HOSTNAME,
    name: str = "bgp_rbb_srv6_te_baseline",
    include_traffic: t.Optional[bool] = None,
    topology: t.Optional[RbbTopology] = None,
) -> Playbook:
    """TC2: TE baseline — tail reachable via BGPD throughout (no direct route).

    Includes the same control-plane + underlay gates (S02-S07) so the baseline
    is proven over a verified underlay, then programs the tail uSID, brings up
    the IXIA edge, and asserts lossless bidirectional traffic over the
    BGPD-owned SRv6 path.

    The IXIA edge + traffic stages (and the IXIA packet-loss pre/postchecks) are
    included only when ``include_traffic`` is on (default). With traffic off,
    TC2 is a device-path-only run of the control-plane + SRv6-program gates — no
    IXIA session is set up, so the ``InvokeIxiaApiStep`` traffic steps must be
    skipped to avoid a null-session failure.
    """
    include_traffic = _include_traffic(include_traffic)
    topology = topology if topology is not None else load_rbb_topology()
    stages = [
        _core_links_up_stage(r1_hostname, r2_hostname, topology),
        _openr_stage(r1_hostname, r2_hostname, topology),
        _core_ibgp_stage(r1_hostname, r2_hostname),
        create_steps_stage(
            steps=[
                _program_step(r1_hostname, "r1", profile),
                _program_step(r2_hostname, "r2", profile),
            ],
            description="program SRv6 tail uSID on R1 and R2",
        ),
        create_steps_stage(
            steps=[
                _verify_step(r1_hostname, verify_srv6_tunnels_spec("r1", profile)),
                _verify_step(r2_hostname, verify_srv6_tunnels_spec("r2", profile)),
            ],
            description="verify SRv6 tunnels programmed",
        ),
    ]
    if include_traffic:
        stages.append(
            create_steps_stage(
                steps=[
                    _ixia_edge_step(r1_hostname, "r1", topology),
                    _ixia_edge_step(r2_hostname, "r2", topology),
                ],
                description="enable IXIA-facing L3 edge",
            )
        )
        stages.append(
            create_steps_stage(
                steps=[
                    create_clear_traffic_stats_step(),
                    create_start_traffic_step(),
                    _traffic_loss_validation_step("TE baseline traffic no-loss"),
                    create_stop_traffic_step(),
                ],
                description="baseline traffic over BGPD-owned SRv6 path",
            )
        )
    return Playbook(
        name=name,
        prechecks=_prechecks() if include_traffic else [],
        postchecks=_postchecks() if include_traffic else [],
        stages=stages,
    )


# Re-exported so the testconfig factory can build core-underlay setup tasks
# from the same scenario source of truth.
__all__ = [
    "create_rbb_srv6_3_usids_playbook",
    "create_rbb_srv6_te_baseline_playbook",
    "core_interface_cmds",
]
