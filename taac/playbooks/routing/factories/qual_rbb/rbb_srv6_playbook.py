# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""RBB SRv6 qualification playbook factory.

One spec-anchored playbook, built as a factory ``Playbook`` (no inline
``Step``/``Stage`` construction — §5.1). Every stage is a sequence of
registered-task steps (``rbb_srv6_direct_route`` / ``rbb_srv6_verify`` /
``rbb_srv6_counter_delta``),
shipped-HC validation steps (OpenR / BGP control-plane, IXIA packet-loss), and
shipped IXIA traffic steps — all built from the OSS factories.

Gate → mechanism (verified OSS-available before wiring):
  S02-S05  core PC members Up        — verify-task (fboss2 show aggregate-port)
  S06/S13  OpenR up + redistribution — verify-task (OPENR-owned peer loopback)
  S07      core iBGP + loopbacks      — shipped BGP_SESSION_ESTABLISH +
                                       verify-task (peer loopback)
  S10-S11  core RIF / SRv6 uSIDs       — verify-tasks
  S14      DUT-side edge eBGP (opt-in)— registered rbb_edge_ebgp setup task
  S16      edge eBGP sessions         — shipped BGP_SESSION_ESTABLISH
  S17-S18  remote route + FIB         — exact-prefix verify-task (the shipped
                                       count check is not prefix-specific and
                                       FBOSS skips BGP_FIB_PROGRAMMING_CHECK)
  S13-S20  baseline traffic           — shipped IXIA_PACKET_LOSS_CHECK
  S19      pre-route baseline         — verify-task (tail BGPD-owned)
  S21-S23  TE_AGENT install + owner    — rbb_srv6_direct_route + verify-task
  S24-S25  traffic + path counter delta— IXIA_PACKET_LOSS_CHECK +
                                       rbb_srv6_counter_delta (real delta gate)
  S26      SRv6 FIB present            — verify-task
  S27-S28  delete + revert to BGPD     — rbb_srv6_direct_route + verify-task
"""

import os
import re
import typing as t

from taac.health_check.health_check import types as hc_types
from taac.health_checks.healthcheck_definitions import (
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
    srv6_decap_counter_spec,
    srv6_encap_counter_spec,
    Srv6Profile,
    verify_core_links_up_spec,
    verify_openr_adjacency_spec,
    verify_pc162_global_ipv6_spec,
    verify_peer_loopback_learned_spec,
    verify_route_owner_bgpd_spec,
    verify_route_owner_te_agent_spec,
    verify_remote_ixia_prefix_spec,
    verify_srv6_counters_spec,
    verify_srv6_tunnels_spec,
)
from taac.testconfigs.routing.util.bgp_rbb_topology import (
    load_rbb_topology,
    RbbTopology,
    validate_rbb_topology,
)


def _include_traffic(override: t.Optional[bool]) -> bool:
    """Whether to include the IXIA packet-loss stages/prechecks.

    Defaults to off so importing a public example never reserves a chassis.
    Set ``TAAC_RBB_INCLUDE_TRAFFIC=1`` to build the full data-plane
    slice around the control-plane gates, SRv6/route verifies, and TE_AGENT
    direct-route lifecycle.
    """
    if override is not None:
        return override
    return C.INCLUDE_TRAFFIC


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
            f"{spec.get('direction', 'srv6')} path counter on {hostname}"
        ),
        ixia_needed=True,
    )


def _bgp_peer_up_step(hostname: str, peer: str, gate: str) -> Step:
    """Verify one exact peer on an explicitly selected DUT."""
    return create_run_task_step(
        task_name="rbb_srv6_verify",
        params_dict={
            "hostname": hostname,
            "gate": gate,
            "bgp_peers_established": [peer],
        },
        description=f"[{gate}] {hostname}: BGP peer {peer} Established",
    )


def _traffic_loss_validation_step(description: str) -> Step:
    """Packet-loss assertion over the configured R1-to-R2 SRv6 path."""
    return create_validation_step(
        point_in_time_checks=[
            create_ixia_packet_loss_check(
                thresholds=[
                    hc_types.PacketLossThreshold(
                        names=list(C.ALL_TRAFFIC_ITEMS),
                        metric=hc_types.PacketLossMetric.PERCENTAGE,
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
    """S06/S13 — OpenR up, adjacency, and loopback redistribution.

    The shipped ``Openr*HealthCheck`` checks raise ``NotImplementedError`` under
    ``TAAC_OSS=1`` (they require Meta-internal OpenR thrift), so — per the OSS
    rule — this gate is an ``rbb_srv6_verify`` read instead: the peer loopback
    must be installed with an ``OPENR`` route client, which confirms the core
    adjacency and peer-loopback redistribution. Edge-prefix propagation is
    checked separately at S17-S18 when edge eBGP is enabled.
    """
    return create_steps_stage(
        steps=[
            _verify_step(r1_hostname, verify_openr_adjacency_spec("r1", topology)),
            _verify_step(r2_hostname, verify_openr_adjacency_spec("r2", topology)),
        ],
        description="S06/S13 OpenR up + adjacency/loopback redistribution",
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
    # The playbook is anchored to R1. Scope the shipped health check to its
    # single declared core peer so unrelated sessions on a shared DUT neither
    # inflate the expected count nor fail this qualification. Exact task checks
    # below cover the peer on both R1 and R2.
    session_check = create_bgp_session_establish_check(
        ignore_all_prefixes_except=[C.R2_ROUTER_ID],
        expected_established_sessions=1,
        # Device health checks default to TOPOLOGY scope. These parameters name
        # R1's peer, so evaluating them unchanged on R2 produces a false failure
        # (R2 does not peer with itself). The explicit task checks below verify
        # the reciprocal session on both DUTs.
        check_scope=hc_types.Scope.DEFAULT,
    )
    return create_steps_stage(
        steps=[
            create_validation_step(
                point_in_time_checks=[session_check],
                description="S07 core iBGP sessions established",
            ),
            _bgp_peer_up_step(
                r1_hostname, C.R2_ROUTER_ID, "S07_r1_core_ibgp_established"
            ),
            _bgp_peer_up_step(
                r2_hostname, C.R1_ROUTER_ID, "S07_r2_core_ibgp_established"
            ),
            _verify_step(r1_hostname, verify_peer_loopback_learned_spec("r1")),
            _verify_step(r2_hostname, verify_peer_loopback_learned_spec("r2")),
        ],
        description="S07 core iBGP up + loopbacks learned",
    )


def _edge_ebgp_session_stage(r1_hostname: str, r2_hostname: str) -> t.Any:
    """S16 — edge eBGP sessions established (IXIA↔R1, IXIA↔R2)."""
    return create_steps_stage(
        steps=[
            create_validation_step(
                point_in_time_checks=[
                    create_bgp_session_establish_check(
                        ignore_all_prefixes_except=[C.IXIA_R1_EDGE_V6],
                        expected_established_sessions=1,
                        # Scope the shipped check to the playbook's R1 anchor;
                        # the targeted task checks below validate R1 and R2 with
                        # their respective, different IXIA peer addresses.
                        check_scope=hc_types.Scope.DEFAULT,
                    )
                ],
                description="S16 edge eBGP sessions established",
            ),
            _bgp_peer_up_step(
                r1_hostname, C.IXIA_R1_EDGE_V6, "S16_r1_edge_ebgp_established"
            ),
            _bgp_peer_up_step(
                r2_hostname, C.IXIA_R2_EDGE_V6, "S16_r2_edge_ebgp_established"
            ),
        ],
        description="S16 edge eBGP sessions (IXIA↔R1, IXIA↔R2)",
    )


def _remote_route_stage(r1_hostname: str) -> t.Any:
    """S17-S18 — remote IXIA prefixes propagate over core iBGP to R1 + FIB."""
    return create_steps_stage(
        # The generic BGP route-count check evaluates every established peer
        # and the FBOSS driver reports zero for its pre/post-filter counter
        # APIs on this stack. BGP_FIB_PROGRAMMING_CHECK explicitly skips FBOSS.
        # Use the exact-prefix route-details assertion instead: it proves the
        # configured tail prefix, BGPD ownership, resolved decap next hop, and
        # FIB presence without depending on unrelated peers.
        steps=[_verify_step(r1_hostname, verify_remote_ixia_prefix_spec())],
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
    return [
        create_ixia_packet_loss_check(
            thresholds=[
                hc_types.PacketLossThreshold(
                    names=list(C.ALL_TRAFFIC_ITEMS),
                    metric=hc_types.PacketLossMetric.PERCENTAGE,
                    str_value=C.PACKET_LOSS_THRESHOLD_PCT,
                    expect_packet_loss=False,
                )
            ],
            clear_traffic_stats=True,
        )
    ]


def _postchecks() -> t.List[PointInTimeHealthCheck]:
    return [
        create_ixia_packet_loss_check(
            thresholds=[
                hc_types.PacketLossThreshold(
                    names=list(C.ALL_TRAFFIC_ITEMS),
                    metric=hc_types.PacketLossMetric.PERCENTAGE,
                    str_value=C.PACKET_LOSS_THRESHOLD_PCT,
                    expect_packet_loss=False,
                )
            ],
        ),
    ]


def _direct_route_step(hostname: str, action: str, profile: Srv6Profile) -> Step:
    """FBOSS thrift direct-route step (add/withdraw TE_AGENT copy of the tail).

    Reversible: the task retains the BGPD route's original recursive next hops,
    attaches the packed remote uSID container as ``srv6SegmentList``, and
    withdraws only the TE_AGENT client's copy. Runs on R1, the SRv6 head. The
    head's own uSID is not put on the wire because encapsulation occurs there.
    """
    return create_run_task_step(
        task_name="rbb_srv6_direct_route",
        params_dict={
            "hostname": hostname,
            "action": action,
            "prefix": profile.tail_prefix,
            "client": C.ROUTE_OWNER_TE_AGENT,
            "srv6_segments": [
                C.pack_usid_container(profile.locator, profile.encap_usids)
            ],
            "srv6_tunnel_id": C.SRV6_TUNNEL_ID,
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
    """Full head→mid→tail 3-uSID lifecycle through the required gates.

    Control-plane + underlay gates (S02-S07/S13) always run (non-destructive
    reads / shipped OSS health checks). The IXIA edge / eBGP-emulation / route /
    traffic / counter-delta gates (S16/S17-S18/S13-S20/S24-S25) are included
    only when ``include_traffic`` is on (opt-in). ``TAAC_RBB_EDGE_EBGP=1``
    controls only the reversible DUT-side S14 setup task in the TestConfig;
    traffic mode always verifies the edge sessions and advertised prefix,
    including when the adopter pre-provisioned those edges.
    """
    include_traffic = _include_traffic(include_traffic)
    if topology is None:
        topology = load_rbb_topology(
            allow_placeholder=not include_traffic,
            require_ixia=include_traffic,
        )
    else:
        validate_rbb_topology(topology, require_ixia=include_traffic)
    stages = [
        # ── Increment A: control-plane + underlay (always run) ──
        _core_links_up_stage(r1_hostname, r2_hostname, topology),
        _openr_stage(r1_hostname, r2_hostname, topology),
        _core_ibgp_stage(r1_hostname, r2_hostname),
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
        stages.append(_edge_ebgp_session_stage(r1_hostname, r2_hostname))
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

    # S19 pre-route baseline snapshot on the head before TE_AGENT takes over.
    stages.append(
        create_steps_stage(
            steps=[
                _verify_step(
                    r1_hostname,
                    verify_route_owner_bgpd_spec(
                        profile, gate="S19_route_owner_bgpd_baseline"
                    ),
                )
            ],
            description="S19 baseline snapshot (tail prefix BGPD-owned pre-route)",
        )
    )

    stages.append(
        create_steps_stage(
            steps=[_direct_route_step(r1_hostname, "install", profile)],
            description="S21 install TE_AGENT direct route",
        )
    )
    stages.append(
        create_steps_stage(
            steps=[
                _verify_step(r1_hostname, verify_route_owner_te_agent_spec(profile))
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
                description="S24-S25 traffic on TE_AGENT path + path counter delta",
            )
        )

    stages.append(
        create_steps_stage(
            steps=[
                _verify_step(r1_hostname, verify_srv6_counters_spec(profile)),
            ],
            description="S26 verify SRv6 FIB present",
        )
    )
    stages.append(
        create_steps_stage(
            steps=[_direct_route_step(r1_hostname, "delete", profile)],
            description="S27 delete TE_AGENT direct route",
        )
    )

    s28_steps = [_verify_step(r1_hostname, verify_route_owner_bgpd_spec(profile))]
    if include_traffic:
        # Exercise the reverted path, rather than re-reading the stopped
        # S24-S25 traffic item's old counters.
        s28_steps.extend(
            [
                create_clear_traffic_stats_step(),
                create_start_traffic_step(),
                _traffic_loss_validation_step("S28 post-delete traffic no-loss"),
                create_stop_traffic_step(),
            ]
        )
    stages.append(
        create_steps_stage(
            steps=s28_steps,
            description="S28 verify tail prefix reverts to BGPD",
        )
    )

    # Cleanup is fail-fast. Restore the mutated DUT route before touching IXIA
    # so a traffic-stop failure cannot strand the TE_AGENT route after a test
    # failure. IXIA also has resource-level teardown as a final safety net.
    cleanup_steps = [_direct_route_step(r1_hostname, "delete", profile)]
    if include_traffic:
        cleanup_steps.append(create_stop_traffic_step())
    return Playbook(
        name=name,
        prechecks=_prechecks() if include_traffic else [],
        postchecks=_postchecks() if include_traffic else [],
        stages=stages,
        cleanup_steps=cleanup_steps,
        device_regexes=[f"^{re.escape(r1_hostname)}$"],
    )


__all__ = [
    "create_rbb_srv6_3_usids_playbook",
]
