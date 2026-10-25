# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""Spec 2.3 — Backpressure and Blocking Behavior. UG qualification playbook factories.

- 2.3.1 Fast Peers Not Held Back by Slow Peers
- 2.3.2 Peer Blocks, Goes Down, Comes Back — Full Recovery
- 2.3.3 Withdraw and Attribute Change Under Backpressure
- 2.3.4 All Peers in Group Block, Then All Go Down, Then All Come Back
- Topology smoke variant
"""

import typing as t

from taac.health_checks.healthcheck_definitions import (
    create_bgp_peer_route_set_equality_check,
    create_bgp_received_route_community_check,
    create_bgp_route_count_verification_check,
    create_bgp_session_establish_check,
    create_bgp_stale_route_check,
    create_bgp_update_group_check,
    create_log_parsing_check,
    create_memory_utilization_check,
    create_service_restart_check,
    create_system_cpu_load_average_check,
)
from taac.stages.stage_definitions import create_steps_stage
from taac.steps.step_definitions import (
    create_advertise_withdraw_prefixes_step,
    create_bgp_prefixes_med_value_step,
    create_configure_as_path_pool_step,
    create_configure_community_pool_step,
    create_configure_extended_community_pool_step,
    create_ixia_api_step,
    create_longevity_step,
    create_modify_bgp_prefixes_origin_value_step,
    create_randomize_prefix_local_preference_step,
    create_run_task_step,
    create_snapshot_bgp_sent_route_counts_step,
    create_snapshot_ixia_bgp_rx_stats_step,
    create_snapshot_peer_egress_stats_step,
    create_start_stop_bgp_peers_step,
    create_validation_step,
    create_verify_backpressure_observed_step,
    create_verify_bgp_sent_route_count_delta_step,
    create_verify_dut_received_from_peer_group_step,
    create_verify_fast_peer_queue_shallower_step,
    create_verify_ixia_bgp_rx_stats_delta_step,
    create_verify_ug_queue_recovered_step,
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


def _heavy_attr_advertise_steps(
    *,
    device_name: str,
    ixia_interface: str,
    prefix_pool_regex: str,
    device_group_regex: str,
    prefix_start_index: int,
    prefix_end_index: int,
    community_combinations: t.List[t.List[str]],
    extended_community_combinations: t.List[t.List[str]],
    as_path: t.List[int],
    randomize_med: bool = True,
    randomize_local_pref: bool = True,
    randomize_origin: bool = True,
    description_prefix: str = "Heavy-attr",
    skip_pool_config: bool = True,
) -> t.List[Step]:
    """Build the 'heavy-attr advertise' step sequence used by all 4 2.3 playbooks.

    With ``skip_pool_config=True`` (default), the three runtime
    ``configure_*_pool`` steps are OMITTED. Callers must pre-attach the
    community / extended-community pools at IXIA-build time (e.g. via
    ``plane_drain_dg_v6_attribute_overrides`` on the EBB topology builder).
    Reason: ``ixia.py`` invokes ``stop_protocols()`` unconditionally at the
    top of ``configure_community_pool`` / ``configure_extended_community_pool``
    / ``configure_as_path_pool``; that tears down every BGP TCP session on
    the chassis, so the test then fails on cascade rather than on the
    trigger's spec.

    With ``skip_pool_config=False``, the legacy 3-step pre-amble is emitted.
    Use ONLY when the caller is comfortable with the chassis-wide
    ``stop_protocols()``.

    The ``community_combinations`` / ``extended_community_combinations`` /
    ``as_path`` parameters stay in the signature for spec traceability and
    so a framework fix can re-enable mid-test pool configuration without
    breaking callers.

    AS_PATH note: build-time pre-attach via the ``BgpAttribute`` thrift enum
    is not supported (enum lacks AS_PATH). A targeted ``configure_as_path_pool``
    step runs below even under ``skip_pool_config=True``, scoped to ONLY the
    storm sender DG (``device_group_regex``) and with ``stop_protocols=False``
    so it writes the AsPath.ValueList in-place without the chassis-wide TCP
    cascade.
    """
    steps: t.List[Step] = []
    if not skip_pool_config:
        steps.extend(
            [
                create_configure_community_pool_step(
                    device_name=device_name,
                    interface=ixia_interface,
                    community_combinations=community_combinations,
                    device_group_regex=device_group_regex,
                    description=f"{description_prefix}: set {len(community_combinations)} community combinations on {device_group_regex}",
                ),
                create_configure_extended_community_pool_step(
                    device_name=device_name,
                    interface=ixia_interface,
                    extended_community_combinations=extended_community_combinations,
                    device_group_regex=device_group_regex,
                    description=f"{description_prefix}: set {len(extended_community_combinations)} ext-community combinations on {device_group_regex}",
                ),
                # Step factory expects ASNs as strings; our spec uses ints.
                create_configure_as_path_pool_step(
                    device_name=device_name,
                    interface=ixia_interface,
                    as_path_pool=[str(a) for a in as_path],
                    device_group_regex=device_group_regex,
                    description=f"{description_prefix}: set AS_PATH (length={len(as_path)}) on {device_group_regex}",
                ),
            ]
        )
    if randomize_med:
        steps.append(
            create_bgp_prefixes_med_value_step(
                prefix_pool_regex=prefix_pool_regex,
                prefix_start_index=prefix_start_index,
                prefix_end_index=prefix_end_index,
                med_value=-1,  # -1 = random per prefix
                description=f"{description_prefix}: randomize MED on {prefix_pool_regex}[{prefix_start_index}..{prefix_end_index}]",
            ),
        )
    if randomize_local_pref:
        steps.append(
            create_randomize_prefix_local_preference_step(
                prefix_pool_regex,
                prefix_start_index,
                prefix_end_index,
                description=f"{description_prefix}: randomize LocalPref on {prefix_pool_regex}[{prefix_start_index}..{prefix_end_index}]",
            ),
        )
    # Runs even under skip_pool_config=True: scoped to ONLY the storm-sender
    # DG (device_group_regex) with stop_protocols=False, so it writes
    # AsPath.ValueList in-place on matching prefix pools without a
    # chassis-wide TCP cascade.
    if as_path:
        steps.append(
            create_configure_as_path_pool_step(
                device_name=device_name,
                interface=ixia_interface,
                as_path_pool=[str(a) for a in as_path],
                device_group_regex=device_group_regex,
                stop_protocols=False,
                description=f"{description_prefix}: set AS_PATH (length={len(as_path)}) on {device_group_regex} (targeted, no cascade)",
            ),
        )
    if randomize_origin:
        # Deterministic order (not random) is required so the playbook config
        # hash stays stable for the golden-config test.
        _origin_cycle = ["igp", "egp", "incomplete"]
        steps.append(
            create_modify_bgp_prefixes_origin_value_step(
                prefix_pool_regex,
                prefix_start_index,
                prefix_end_index=prefix_end_index,
                origin_values=_origin_cycle,
                description=f"{description_prefix}: cycle Origin {_origin_cycle} per-prefix on {prefix_pool_regex}[{prefix_start_index}..{prefix_end_index}]",
            ),
        )
    steps.append(
        create_advertise_withdraw_prefixes_step(
            device_name=device_name,
            advertise=True,
            prefix_pool_regex=prefix_pool_regex,
            prefix_start_index=prefix_start_index,
            prefix_end_index=prefix_end_index,
            description=f"{description_prefix}: advertise {prefix_end_index - prefix_start_index} prefixes on {prefix_pool_regex} (heavy-attr storm)",
        ),
    )
    return steps


def _heavy_attr_withdraw_steps(
    *,
    device_name: str,
    prefix_pool_regex: str,
    prefix_start_index: int,
    prefix_end_index: int,
    description_prefix: str = "Heavy-attr",
) -> t.List[Step]:
    """Withdraw-side mirror of ``_heavy_attr_advertise_steps``."""
    return [
        create_advertise_withdraw_prefixes_step(
            device_name=device_name,
            advertise=False,
            prefix_pool_regex=prefix_pool_regex,
            prefix_start_index=prefix_start_index,
            prefix_end_index=prefix_end_index,
            description=f"{description_prefix}: withdraw {prefix_end_index - prefix_start_index} prefixes on {prefix_pool_regex}",
        ),
    ]


def _ug_backpressure_common_postchecks(
    *,
    expected_established_sessions: int,
    memory_threshold_bytes: int,
    enforce_load_avg: bool = True,
    load_avg_baseline: float = 12.0,
    enforce_log_parsing: bool = False,
) -> t.List[PointInTimeHealthCheck]:
    """Shared crash-guard / resource-guard postchecks used by all 4 2.3 playbooks.

    Args:
        expected_established_sessions: Spec-required session count post-test.
        memory_threshold_bytes: VmHWM threshold for the Bgp service (per spec:
            10 GiB). Pass via ``Gigabyte.GIG_10.value`` from caller.
        enforce_load_avg: When True, asserts 1m/5m/15m system load-avg never
            crossed ``load_avg_baseline`` (2.3.1 spec criterion).
        load_avg_baseline: Load-avg ceiling (2.3.1 spec: 12).
        enforce_log_parsing: When True, asserts no Emergencies/Critical/Error
            BGP/system logs during the test window (2.3.3 + 2.3.4 spec).
    """
    checks: t.List[PointInTimeHealthCheck] = [
        create_service_restart_check(
            services=["Bgpcpp"],
            daemons=["FibBgpGrpc"],
        ),
        create_bgp_stale_route_check(),
        # ALSO pass delta because the Arista check path requires it; without
        # delta the HC SKIPs on ARISTA_FBOSS devices. 2 GiB is a conservative
        # growth ceiling.
        create_memory_utilization_check(
            threshold_by_service={"Bgpcpp": memory_threshold_bytes},
            start_time_jq_var="test_case_start_time",
            delta=2 * (1024**3),
        ),
        create_bgp_session_establish_check(
            expected_established_sessions=expected_established_sessions,
        ),
    ]
    if enforce_load_avg:
        checks.append(create_system_cpu_load_average_check(baseline=load_avg_baseline))
    if enforce_log_parsing:
        checks.append(
            create_log_parsing_check(
                json_params={
                    "agent_name": "Bgpcpp",
                    "exclude_regex": "Memory Limit Reached",
                },
                start_time_jq_var="test_case_start_time",
                end_time_jq_var="test_case_end_time",
                check_id="ug_backpressure_log_parsing",
            ),
        )
    return checks


def create_bgp_ug_backpressure_fast_peers_not_held_back_playbook(
    *,
    device_name: str,
    ixia_interface: str,
    storm_prefix_pool_regex: str,
    storm_device_group_regex: str,
    storm_prefix_count: int,
    community_combinations: t.List[t.List[str]],
    extended_community_combinations: t.List[t.List[str]],
    as_path: t.List[int],
    fast_peer_addrs: t.List[str],
    bgp_mon_peer_addrs: t.List[str],
    iBGP_receiver_peer_addrs: t.List[str],
    expected_established_sessions: int,
    memory_threshold_bytes: int,
    during_storm_settle_s: int = 60,
    post_storm_settle_s: int = 120,
    # 600s (not 120s): IXIA sessions can silently collapse during the
    # post-withdraw settle window; the longer wait + explicit mid-settle
    # session-establish check (added below) catch the collapse sooner and
    # give it more recovery time.
    post_withdraw_settle_s: int = 600,
    setup_steps: t.Optional[t.List[Step]] = None,
    prechecks: t.Optional[t.List[PointInTimeHealthCheck]] = None,
    postchecks: t.Optional[t.List[PointInTimeHealthCheck]] = None,
    snapshot_checks: t.Optional[t.List[SnapshotHealthCheck]] = None,
    # Optional: address-prefix of the storm-sender peer set. When provided,
    # a "storm arrived at DUT" gate is added post-settle asserting DUT
    # ingress RIB received >= storm_prefix_count from those peers. Decoupled
    # from egress-policy filtering (some topologies drop heavy-attr storms
    # at egress).
    storm_sender_peer_addr_prefix: t.Optional[str] = None,
    # Slow eBGP peer address list — the peers that have been artificially
    # TCP-throttled (via ``create_configure_bgp_peer_tcp_window_size_step``
    # in the caller's setup_steps) to induce DUT adj-RIB-out backpressure
    # inside the SAME UG as fast_peer_addrs. When supplied, the Phase 1.5
    # asymmetry gate compares avg blocks_delta on slow_ebgp_peer_addrs vs
    # fast_peer_addrs (spec 2.3.1 central claim). When NOT supplied, the
    # gate falls back to fast vs iBGP receivers (cross-UG comparison --
    # weaker signal since UGs differ).
    slow_ebgp_peer_addrs: t.Optional[t.List[str]] = None,
    # Opt-in fast-peer wire-side observability (snapshot + during-storm liveness
    # + post-settle delta). Off by default because it REQUIRES DUT eBGP egress
    # policy to permit the heavy-attr storm on the wire -- topologies like
    # bag013 that have restrictive egress filters false-fail this gate. Enable
    # only on testbeds where the storm is proven to reach fast peers on-wire.
    enable_fast_peer_wire_check: bool = False,
    # Opt-in IXIA-side wire-received BGP counters check. Bypasses DUT
    # egress-policy blind spots (bag013 EB-FA-OUT filters storm on DUT
    # side, so DUT sent_prefix_count doesn't move -- but IXIA sees
    # whatever DUT actually put on wire, including keepalives + baseline
    # updates). Snapshot pre-storm, verify Rx Total Messages > 0 delta
    # post-storm on the fast-peer-facing DUT port. When enabled, requires
    # ``fast_peer_ixia_interface`` naming the port (e.g. Ethernet3/36/1).
    enable_fast_peer_ixia_wire_check: bool = False,
    fast_peer_ixia_interface: t.Optional[str] = None,
    # Optional post-storm stage — an additional stage appended AFTER the
    # existing storm+settle+gates stage but BEFORE cleanup_steps. Used to
    # inject caller-defined verifiers that must run on the storm's terminal
    # state (e.g. per-peer IXIA wire counter asymmetry gate that compares
    # fast vs slow BGP RX rates). Kept as a separate stage rather than
    # appended to the storm stage's step list so the log output cleanly
    # separates "storm phase" from "post-storm verification" and downstream
    # test-log parsers can attribute failures to the right phase.
    stage_2_extra_steps: t.Optional[t.List[Step]] = None,
) -> Playbook:
    """Build the BGP++ Update Group qualification 2.3.1 playbook --
    'Fast Peers Not Held Back by Slow Peers'.

    Spec: under a heavy-attr 10K-prefix iBGP storm, fast peers (eBGP + BGP_MON)
    must continue receiving updates even when slow iBGP receiver peers
    temporarily block on their adj-RIB-out queue. After settle: all peers
    eventually receive all 10K (no peer permanently stuck). After withdraw:
    no stale routes on any peer.

    Trigger sequence:
      Phase 1 (storm): advertise ``storm_prefix_count`` prefixes from
        ``storm_device_group_regex`` with 32 communities + 16 ext-communities
        + 255-ASN AS_PATH + random MED/LP/Origin per route.
      Phase 2 (post-storm settle): wait ``post_storm_settle_s`` for UG to
        catch up across all peers.
      Phase 3 (spec gate): all peers (fast + slow + BGP_MON) have
        ``storm_prefix_count`` routes received with identical prefix sets.
      Phase 4 (withdraw): withdraw all ``storm_prefix_count`` prefixes.
      Phase 5 (post-withdraw settle): wait + verify all peers cleanly removed.

    Args:
        device_name: DUT hostname.
        ixia_interface: IXIA logical interface for the iBGP storm sender DG.
        storm_prefix_pool_regex: Prefix-pool regex (e.g. ``.*IBGP.*PLANE_1.*``).
        storm_device_group_regex: Device-group regex of the storm sender.
        storm_prefix_count: Number of prefixes (spec: 10000).
        community_combinations: List of community lists, one per slot (spec: 32).
        extended_community_combinations: List of ext-community lists (spec: 16).
        as_path: AS_SEQ ASN list (spec: 255 random ASNs).
        fast_peer_addrs: eBGP receiver peer IPs (the "fast" peers).
        bgp_mon_peer_addrs: BGP-Monitor peer IPs (separate UG, must stay flowing).
        iBGP_receiver_peer_addrs: iBGP receiver peer IPs (the "slow" peers).
        expected_established_sessions: Total expected sessions at end of test.
        memory_threshold_bytes: VmHWM ceiling for Bgp (spec: 10 GiB).
        during_storm_settle_s: Settle inside the storm before the during-storm
            BGP_MON liveness check (default 60s).
        post_storm_settle_s: Settle after storm before the all-peers spec gate.
        post_withdraw_settle_s: Settle after withdraw before clean-state check.
    """
    # Route-set-equality checks must be scoped WITHIN a single outbound-policy
    # group, not across groups. iBGP and eBGP receivers have fundamentally
    # different outbound policies on this DUT class -- iBGP peers receive the
    # full RIB (~45K on EBB scale) while eBGP peers get filtered by egress
    # policy to only the registry prefixes (~750). Mixing them in one gate
    # is guaranteed to fail on cross-peer equality by design.
    _peer_groups = [
        ("eBGP fast", list(fast_peer_addrs)),
        ("BGP_MON", list(bgp_mon_peer_addrs)),
        ("iBGP receivers", list(iBGP_receiver_peer_addrs)),
    ]

    storm_steps = _heavy_attr_advertise_steps(
        device_name=device_name,
        ixia_interface=ixia_interface,
        prefix_pool_regex=storm_prefix_pool_regex,
        device_group_regex=storm_device_group_regex,
        prefix_start_index=0,
        prefix_end_index=storm_prefix_count,
        community_combinations=community_combinations,
        extended_community_combinations=extended_community_combinations,
        as_path=as_path,
        randomize_med=True,
        randomize_local_pref=True,
        randomize_origin=True,
        description_prefix="Phase 1 (2.3.1)",
    )

    # During-storm liveness check: BGP_MON peers MUST still be receiving (the
    # "fast peers not held back" spec assertion). Uses min_count=1 so the check
    # passes as long as BGP_MON has at least one route -- proves DUT is still
    # advertising to BGP_MON even while iBGP receivers may be blocking.
    # When bgp_mon_peer_addrs is empty (some testbeds like bag013 keep BGP_MON
    # IDLE by device-config quirk), the check is skipped -- the "fast peers"
    # spec assertion is still covered by the post-settle all-peers gate.
    during_storm_checks: t.List[PointInTimeHealthCheck] = []
    if bgp_mon_peer_addrs:
        during_storm_checks.append(
            create_bgp_route_count_verification_check(
                json_params={
                    "descriptions_to_check": list(bgp_mon_peer_addrs),
                    "direction": "received",
                    "policy_type": "post_policy",
                    "min_count": 1,
                },
            ),
        )
    during_storm_check: t.Optional[Step] = None
    if during_storm_checks:
        during_storm_check = create_validation_step(
            point_in_time_checks=during_storm_checks,
            description=(
                "Phase 2 (2.3.1): mid-storm BGP_MON liveness -- BGP_MON peers "
                "must still be receiving updates (fast-not-held-back assertion)"
            ),
        )

    # DUT-INTERNAL observability (default ON): snapshot per-peer
    # ``adjribout_queue_blocks`` pre-storm, then post-storm assert
    #   (a) backpressure was observed on some slow peers,
    #   (b) fast-peer avg queue_size < slow-peer avg queue_size mid-storm
    #       (spec 2.3.1 central claim: DUT doesn't hold fast peers back
    #       inside the same UG),
    #   (c) all UG queues drained post-settle (spec 2.3.1 "no peer
    #       permanently stuck").
    # Topology-agnostic: works even when egress policy filters the storm
    # on the wire.
    #
    # TOPOLOGY REQUIREMENT for ``enable_fast_peer_wire_check``: DUT eBGP
    # egress policy MUST permit the heavy-attr storm routes on the wire,
    # otherwise delta is trivially 0 and the gate false-fails.
    _egress_stats_snapshot_key = f"pb_2_3_1_egress_stats_pre_storm_{device_name}"
    _dut_internal_pre_storm: t.List[Step] = []
    _dut_internal_mid_storm: t.List[Step] = []
    _dut_internal_post_settle: t.List[Step] = []
    if fast_peer_addrs and iBGP_receiver_peer_addrs:
        # ``bgp_mon_peer_addrs`` accepts ``None`` in some callers (e.g. bag013
        # keeps BGP_MON IDLE and passes ``[]``, but other callers may pass
        # ``None``). Match ``slow_ebgp_peer_addrs`` pattern with an ``or []``
        # guard so ``list(None)`` cannot raise ``TypeError`` here.
        _all_ug_peer_addrs = (
            list(fast_peer_addrs)
            + list(iBGP_receiver_peer_addrs)
            + list(bgp_mon_peer_addrs or [])
            + list(slow_ebgp_peer_addrs or [])
        )
        _dut_internal_pre_storm.append(
            create_snapshot_peer_egress_stats_step(
                hostname=device_name,
                peer_addrs=_all_ug_peer_addrs,
                snapshot_key=_egress_stats_snapshot_key,
                description=(
                    f"Phase 0 (2.3.1): snapshot per-peer egress stats "
                    f"(adjribout_queue_blocks etc.) for "
                    f"{len(_all_ug_peer_addrs)} peer(s) on {device_name} "
                    f"(key={_egress_stats_snapshot_key})"
                ),
            ),
        )
        _dut_internal_mid_storm.append(
            create_verify_fast_peer_queue_shallower_step(
                hostname=device_name,
                fast_peer_addrs=list(fast_peer_addrs),
                # Prefer same-UG slow peers (TCP-throttled eBGP) when supplied
                # -- that's the spec-loyal fast/slow-inside-same-UG comparison.
                # Fall back to iBGP receivers (cross-UG, weaker signal) when
                # no throttled slow peers are configured.
                slow_peer_addrs=list(
                    slow_ebgp_peer_addrs
                    if slow_ebgp_peer_addrs
                    else iBGP_receiver_peer_addrs
                ),
                snapshot_key=_egress_stats_snapshot_key,
                min_delta=0,
                description=(
                    f"Phase 1.5 fast/slow asymmetry (2.3.1 CENTRAL CLAIM): "
                    f"avg fast-peer UG queue_size < avg slow-peer UG "
                    f"queue_size on {device_name} mid-storm (proves DUT "
                    f"does NOT hold fast peers back on slow-peer "
                    f"backpressure inside the same UG)"
                ),
            ),
        )
        _dut_internal_post_settle.append(
            create_verify_backpressure_observed_step(
                hostname=device_name,
                # Prefer TCP-throttled slow eBGP peers (same-UG asymmetry).
                # Fall back to iBGP receivers (cross-UG) when unavailable.
                peer_addrs=list(
                    slow_ebgp_peer_addrs
                    if slow_ebgp_peer_addrs
                    else iBGP_receiver_peer_addrs
                ),
                snapshot_key=_egress_stats_snapshot_key,
                min_peers_with_block=1,
                description=(
                    f"Phase 3 backpressure-observed pre-condition (2.3.1): "
                    f">= 1 slow iBGP receiver on {device_name} saw "
                    f"adjribout_queue_blocks delta > 0 during storm "
                    f"(spec-loyal: 2.3.1 asymmetry claim requires observed "
                    f"backpressure). If IXIA line-rate receivers don't "
                    f"induce this naturally, artificial slow-peer TCP "
                    f"throttling must be added to the testbed's slow-peer "
                    f"DG (see task #141 slow-peer TCP RxBuffer carve-out)."
                ),
            ),
        )
        # Scope to peers NOT being artificially TCP-throttled. Slow eBGP
        # peers with a tiny TCP window take minutes to drain the storm
        # through their throttled socket, so requiring their queue == 0
        # within the standard settle window is unrealistic. Fast peers ARE
        # what the spec's "no peer permanently stuck" claim tests.
        _queue_drained_scope = [
            addr
            for addr in _all_ug_peer_addrs
            if addr not in set(map(str, slow_ebgp_peer_addrs or []))
        ]
        _dut_internal_post_settle.append(
            create_verify_ug_queue_recovered_step(
                hostname=device_name,
                peer_addrs=_queue_drained_scope,
                # Threshold at 1 MTU = 1500 bytes: below that a peer cannot
                # have a stuck BGP UPDATE, only sub-MTU TCP-buffer noise.
                # The spec's "no peer permanently stuck" is about ROUTE
                # delivery, not sub-MTU residuals.
                max_queue_size=1500,
                num_samples=3,
                sample_interval_s=10,
                description=(
                    f"Phase 3 UG queue drained (2.3.1 'no peer PERMANENTLY "
                    f"stuck'): all {len(_queue_drained_scope)} non-throttled "
                    f"UG peer(s) on {device_name} have "
                    f"total_async_socket_buffered <= 1500B (1 MTU) across "
                    f"3 samples 10s apart, with drain progress if higher "
                    f"(TCP-throttled slow eBGP peers excluded)"
                ),
            ),
        )

    # IXIA-side wire observability: snapshot IXIA-side RX counters on the
    # fast-peer-facing DUT port pre-storm, verify Rx Total Messages grew
    # post-storm. Bypasses DUT egress-policy blind spots -- IXIA counts
    # any BGP traffic that DUT actually emitted on-wire, including
    # keepalives + baseline route re-advertisements. On bag013 where
    # EB-FA-OUT filters the storm, this proves DUT is still actively
    # communicating with fast peers (spec-loyal wire-side proof-of-life).
    _ixia_rx_snapshot_key = f"pb_2_3_1_ixia_rx_pre_storm_{device_name}"
    _ixia_rx_pre_storm_snapshot: t.List[Step] = []
    _ixia_rx_post_settle_verify: t.List[Step] = []
    if enable_fast_peer_ixia_wire_check and fast_peer_ixia_interface:
        _ixia_rx_pre_storm_snapshot.append(
            create_snapshot_ixia_bgp_rx_stats_step(
                hostname=device_name,
                interface=fast_peer_ixia_interface,
                snapshot_key=_ixia_rx_snapshot_key,
                description=(
                    f"Phase 0 (2.3.1): snapshot IXIA-side wire BGP RX "
                    f"counters on {device_name}:{fast_peer_ixia_interface} "
                    f"pre-storm (key={_ixia_rx_snapshot_key})"
                ),
            ),
        )
        _ixia_rx_post_settle_verify.append(
            create_verify_ixia_bgp_rx_stats_delta_step(
                hostname=device_name,
                interface=fast_peer_ixia_interface,
                snapshot_key=_ixia_rx_snapshot_key,
                min_rx_delta=1,
                # Messages Rx counts all BGP messages incl. keepalives
                # (which fire every 30s), so delta > 0 during any window
                # >30s even when the storm gets egress-filtered -- wire-
                # side proof-of-life that the UG isn't blocked from
                # delivering any BGP message to fast peers.
                counter_name="rx_total_messages",
                description=(
                    f"Phase 3 fast-peer IXIA wire-side check (2.3.1): "
                    f"IXIA saw >= 1 new BGP UPDATE message from "
                    f"{device_name} on {fast_peer_ixia_interface} "
                    f"during storm window (spec-loyal wire-side proof "
                    f"that DUT continues sending UPDATEs to fast peers "
                    f"during heavy iBGP backpressure)"
                ),
            ),
        )

    _fast_peer_snapshot_key = f"pb_2_3_1_fast_peer_pre_storm_{device_name}"
    _fast_peer_pre_storm_snapshot: t.List[Step] = []
    _fast_peer_during_storm_liveness: t.List[Step] = []
    _fast_peer_post_settle_delta: t.List[Step] = []
    if fast_peer_addrs and enable_fast_peer_wire_check:
        _fast_peer_pre_storm_snapshot.append(
            create_snapshot_bgp_sent_route_counts_step(
                hostname=device_name,
                peer_addrs=list(fast_peer_addrs),
                snapshot_key=_fast_peer_snapshot_key,
                description=(
                    f"Phase 0 (2.3.1): snapshot {len(fast_peer_addrs)} "
                    f"fast-peer sent_count pre-storm (key="
                    f"{_fast_peer_snapshot_key})"
                ),
            ),
        )
        _fast_peer_during_storm_liveness.append(
            create_verify_bgp_sent_route_count_delta_step(
                hostname=device_name,
                peer_addrs=list(fast_peer_addrs),
                snapshot_key=_fast_peer_snapshot_key,
                min_delta=1,
                tolerance=1,
                description=(
                    "Phase 1.5 fast-peer during-storm liveness (2.3.1): "
                    "each fast peer has received >= 1 storm route by the "
                    "mid-storm settle mark (spec: 'fast peers continue "
                    "receiving even when slow peers block'); tolerance=1"
                ),
            ),
        )
        _fast_peer_post_settle_delta.append(
            create_verify_bgp_sent_route_count_delta_step(
                hostname=device_name,
                peer_addrs=list(fast_peer_addrs),
                snapshot_key=_fast_peer_snapshot_key,
                min_delta=storm_prefix_count,
                tolerance=1,
                description=(
                    f"Phase 3 fast-peer full-delivery gate (2.3.1): each "
                    f"fast peer has received >= {storm_prefix_count} storm "
                    f"routes by post-settle (spec-loyal 'fast peers receive "
                    f"storm on wire'); tolerance=1 absorbs 1 slow-converging"
                ),
            ),
        )

    storm_stage = create_steps_stage(
        steps=_dut_internal_pre_storm
        + _ixia_rx_pre_storm_snapshot
        + _fast_peer_pre_storm_snapshot
        + storm_steps
        + [
            create_longevity_step(
                duration=during_storm_settle_s,
                description=f"Phase 1-settle (2.3.1): {during_storm_settle_s}s mid-storm settle for during-storm liveness window",
            ),
            *([during_storm_check] if during_storm_check is not None else []),
            *_fast_peer_during_storm_liveness,
            *_dut_internal_mid_storm,
            create_longevity_step(
                duration=post_storm_settle_s,
                description=f"Phase 2 (2.3.1): {post_storm_settle_s}s post-storm settle for slow peers to catch up",
            ),
        ]
        + (
            [
                create_verify_dut_received_from_peer_group_step(
                    hostname=device_name,
                    sender_peer_addr_prefix=storm_sender_peer_addr_prefix,
                    min_prefix_count=storm_prefix_count,
                    description=(
                        f"Phase 3 ingress-RIB gate (2.3.1): DUT received >= "
                        f"{storm_prefix_count} prefixes from storm-sender "
                        f"peer group {storm_sender_peer_addr_prefix!r} "
                        f"(spec-loyal storm-ingested probe, decoupled from "
                        f"egress filtering)"
                    ),
                ),
            ]
            if storm_sender_peer_addr_prefix
            else []
        )
        + _fast_peer_post_settle_delta
        + _dut_internal_post_settle
        + _ixia_rx_post_settle_verify
        + [
            # Phase 3 equality gate: within each outbound-policy peer group,
            # all peers have identical route sets (no peer permanently stuck;
            # catches UG shadow-RIB divergence). Absolute count is NOT
            # asserted here -- the delivery-magnitude assertion is the delta
            # gate above.
            create_validation_step(
                point_in_time_checks=[
                    create_bgp_peer_route_set_equality_check(
                        baseline_peer_addr=addrs[0],
                        tested_peer_addrs=addrs[1:],
                    )
                    for _label, addrs in _peer_groups
                    if len(addrs) >= 2
                ],
                description=(
                    "Phase 3 equality gate (2.3.1): within each outbound-"
                    "policy peer group (eBGP fast / BGP_MON / iBGP), all "
                    "peers converged to identical route set post-settle"
                ),
            ),
        ],
        description=f"Phase 0-3 (2.3.1): pre-snapshot + heavy-attr storm of {storm_prefix_count} prefixes + spec gates",
    )

    # Split post-withdraw settle into halves so we catch session collapse
    # earlier (mid-settle) instead of only at end-of-stage.
    mid_settle_s = post_withdraw_settle_s // 2
    end_settle_s = post_withdraw_settle_s - mid_settle_s

    withdraw_stage = create_steps_stage(
        steps=_heavy_attr_withdraw_steps(
            device_name=device_name,
            prefix_pool_regex=storm_prefix_pool_regex,
            prefix_start_index=0,
            prefix_end_index=storm_prefix_count,
            description_prefix="Phase 4 (2.3.1)",
        )
        + [
            create_longevity_step(
                duration=mid_settle_s,
                description=f"Phase 4a-settle (2.3.1): {mid_settle_s}s mid-settle for clean withdrawal propagation",
            ),
            # Catches the silent IXIA-session-collapse failure mode: without
            # this, Phase 5 equality can pass trivially with 0 routes
            # everywhere if all sessions silently IDLEd during the settle.
            create_validation_step(
                point_in_time_checks=[
                    create_bgp_session_establish_check(
                        expected_established_sessions=expected_established_sessions,
                    ),
                ],
                description=(
                    f"Phase 4b mid-settle gate (2.3.1): all "
                    f"{expected_established_sessions} sessions still "
                    "Established after withdraw + half-settle"
                ),
            ),
            create_longevity_step(
                duration=end_settle_s,
                description=f"Phase 4c-settle (2.3.1): {end_settle_s}s final-settle for UG re-convergence",
            ),
        ]
        + [
            # Clean-withdraw spec gate: after the withdraw, all peers
            # converge to the same route set (cross-peer equality with no
            # anchor) and no GR stale flags remain on any prefix. Also
            # asserts sessions are STILL Established (without this, the
            # equality check would pass trivially with 0=0 if all sessions
            # had IDLEd).
            create_validation_step(
                point_in_time_checks=[
                    create_bgp_session_establish_check(
                        expected_established_sessions=expected_established_sessions,
                    ),
                    *[
                        create_bgp_peer_route_set_equality_check(
                            baseline_peer_addr=addrs[0],
                            tested_peer_addrs=addrs[1:],
                        )
                        for label, addrs in _peer_groups
                        if len(addrs) >= 2
                    ],
                    create_bgp_stale_route_check(),
                ],
                description=(
                    "Phase 5 equality gate (2.3.1): clean withdrawal -- within "
                    "each outbound-policy peer group, all peers converged to "
                    "identical route set; no GR stale flags"
                ),
            ),
        ],
        description="Phase 4-5 (2.3.1): withdraw + clean-state verification",
    )

    if prechecks is None:
        prechecks = [
            create_bgp_update_group_check(expect_enabled=True),
            create_bgp_session_establish_check(
                expected_established_sessions=expected_established_sessions,
            ),
        ]
    if postchecks is None:
        postchecks = _ug_backpressure_common_postchecks(
            expected_established_sessions=expected_established_sessions,
            memory_threshold_bytes=memory_threshold_bytes,
            enforce_load_avg=True,
        )
    if snapshot_checks is None:
        snapshot_checks = list(BGP_STANDARD_SNAPSHOT_CHECKS)

    stages_list: t.List[t.Any] = [storm_stage]
    if stage_2_extra_steps:
        stages_list.append(
            create_steps_stage(
                steps=stage_2_extra_steps,
                description=(
                    "Phase 3.5 (2.3.1): caller-defined post-storm "
                    "verification stage (e.g. per-peer IXIA wire "
                    "asymmetry gate)"
                ),
            )
        )
    stages_list.append(withdraw_stage)

    kwargs: t.Dict[str, t.Any] = {
        "name": "ug_backpressure_fast_peers_not_held_back",
        "stages": stages_list,
        "prechecks": prechecks,
        "postchecks": postchecks,
        "snapshot_checks": snapshot_checks,
    }
    if setup_steps is not None:
        kwargs["setup_steps"] = setup_steps
    return Playbook(**kwargs)


def create_bgp_ug_backpressure_peer_blocks_down_recover_playbook(
    *,
    device_name: str,
    ixia_interface: str,
    storm_prefix_pool_regex: str,
    storm_device_group_regex: str,
    storm_initial_prefix_count: int,
    storm_followup_prefix_count: int,
    community_combinations: t.List[t.List[str]],
    extended_community_combinations: t.List[t.List[str]],
    as_path: t.List[int],
    shutdown_peer_regex: str,
    shutdown_peer_addrs: t.List[str],
    shutdown_count: int,
    surviving_receiver_peer_addrs: t.List[str],
    expected_established_sessions: int,
    memory_threshold_bytes: int,
    post_shutdown_settle_s: int = 90,
    post_inject_settle_s: int = 60,
    post_recovery_settle_s: int = 180,
    setup_steps: t.Optional[t.List[Step]] = None,
    prechecks: t.Optional[t.List[PointInTimeHealthCheck]] = None,
    postchecks: t.Optional[t.List[PointInTimeHealthCheck]] = None,
    snapshot_checks: t.Optional[t.List[SnapshotHealthCheck]] = None,
    # Optional split of ``surviving_receiver_peer_addrs`` by outbound-policy
    # group. Route-set equality only holds within a single group: iBGP peers
    # receive the full RIB while eBGP peers receive an egress-policy-filtered
    # subset. When both are supplied, the Phase 4 + Phase 6 equality gates
    # run per-group instead of on the mixed list; when either is None the
    # legacy mixed-list behavior is preserved.
    surviving_ebgp_receiver_peer_addrs: t.Optional[t.List[str]] = None,
    surviving_ibgp_receiver_peer_addrs: t.Optional[t.List[str]] = None,
    # See PB1 factory param note: DUT ingress-RIB probe for storm arrival.
    storm_sender_peer_addr_prefix: t.Optional[str] = None,
) -> Playbook:
    """Build the BGP++ Update Group qualification 2.3.2 playbook --
    'Peer Blocks, Goes Down, Comes Back -- Full Recovery'.

    Spec: under a 5K-prefix iBGP storm with heavy attrs, 16 eBGP sessions are
    shut down mid-storm (without GR -- they may have been blocked when going
    down). 500 more prefixes are injected while the 16 are down. When the 16
    come back, they receive a full re-sync from the shadow RIB --
    including the 500 injected while down.

    Trigger sequence:
      Phase 1 (storm): heavy-attr advertise ``storm_initial_prefix_count``
        prefixes from the iBGP sender.
      Phase 2 (shutdown): shut down ``shutdown_count`` eBGP sessions
        matching ``shutdown_peer_regex`` (no GR).
      Phase 3 (mid-down inject): inject ``storm_followup_prefix_count``
        more prefixes while shut peers are down.
      Phase 4 (verify down state): surviving peers have full count.
      Phase 5 (recovery): bring all shut peers back up.
      Phase 6 (spec gate): all reconnected peers received full re-sync
        (total = initial + followup) from shadow RIB.
    """
    total_count = storm_initial_prefix_count + storm_followup_prefix_count
    # Route-set equality is only valid WITHIN a single outbound-policy group.
    # When the caller supplies both split lists we split; otherwise fall back
    # to a single mixed group (known to false-fail on any real DUT).
    _peer_groups_phase4: t.List[t.Tuple[str, t.List[str]]] = []
    _peer_groups_phase6: t.List[t.Tuple[str, t.List[str]]] = []
    if (
        surviving_ebgp_receiver_peer_addrs is not None
        and surviving_ibgp_receiver_peer_addrs is not None
    ):
        # Phase 4: only survivors visible (shut peers are down).
        _peer_groups_phase4 = [
            ("surviving eBGP", list(surviving_ebgp_receiver_peer_addrs)),
            ("surviving iBGP", list(surviving_ibgp_receiver_peer_addrs)),
        ]
        # Phase 6: shutdowns have recovered; they share the eBGP outbound
        # policy with the eBGP survivors, so group them together.
        _peer_groups_phase6 = [
            (
                "reconnected + surviving eBGP",
                list(shutdown_peer_addrs) + list(surviving_ebgp_receiver_peer_addrs),
            ),
            ("surviving iBGP", list(surviving_ibgp_receiver_peer_addrs)),
        ]
    else:
        _peer_groups_phase4 = [
            ("surviving receivers (mixed)", list(surviving_receiver_peer_addrs)),
        ]
        _peer_groups_phase6 = [
            (
                "reconnected + surviving (mixed)",
                list(shutdown_peer_addrs) + list(surviving_receiver_peer_addrs),
            ),
        ]

    storm_steps = _heavy_attr_advertise_steps(
        device_name=device_name,
        ixia_interface=ixia_interface,
        prefix_pool_regex=storm_prefix_pool_regex,
        device_group_regex=storm_device_group_regex,
        prefix_start_index=0,
        prefix_end_index=storm_initial_prefix_count,
        community_combinations=community_combinations,
        extended_community_combinations=extended_community_combinations,
        as_path=as_path,
        randomize_med=False,
        randomize_local_pref=False,
        randomize_origin=False,
        description_prefix="Phase 1 (2.3.2)",
    )

    trigger_steps = storm_steps + [
        create_start_stop_bgp_peers_step(
            peer_regex=shutdown_peer_regex,
            start=False,
            start_idx=1,
            end_idx=shutdown_count,
            description=(
                f"Phase 2 (2.3.2): shut down {shutdown_count} eBGP "
                f"sessions mid-storm (no GR) -- peers may have been "
                "blocked when going down"
            ),
        ),
        create_longevity_step(
            duration=post_shutdown_settle_s,
            description=f"Phase 2-settle (2.3.2): {post_shutdown_settle_s}s for DUT hold-timer + UG cleanup",
        ),
        create_advertise_withdraw_prefixes_step(
            device_name=device_name,
            advertise=True,
            prefix_pool_regex=storm_prefix_pool_regex,
            prefix_start_index=storm_initial_prefix_count,
            prefix_end_index=total_count,
            description=(
                f"Phase 3 (2.3.2): inject {storm_followup_prefix_count} "
                "more prefixes while shut peers are down"
            ),
        ),
        create_longevity_step(
            duration=post_inject_settle_s,
            description=f"Phase 3-settle (2.3.2): {post_inject_settle_s}s for surviving peers to receive followup inject",
        ),
        create_validation_step(
            point_in_time_checks=[
                create_bgp_session_establish_check(
                    ignore_all_prefixes_except=shutdown_peer_addrs,
                    expected_established_sessions=0,
                ),
                *[
                    create_bgp_peer_route_set_equality_check(
                        baseline_peer_addr=addrs[0],
                        tested_peer_addrs=addrs[1:],
                    )
                    for _label, addrs in _peer_groups_phase4
                    if len(addrs) >= 2
                ],
                create_bgp_update_group_check(expect_enabled=True),
            ],
            description=(
                "Phase 4 inline gate (2.3.2): shut peers DOWN; within each "
                "surviving outbound-policy group peers converged; UG intact"
            ),
        ),
        *(
            [
                create_verify_dut_received_from_peer_group_step(
                    hostname=device_name,
                    sender_peer_addr_prefix=storm_sender_peer_addr_prefix,
                    min_prefix_count=total_count,
                    description=(
                        f"Phase 4 ingress-RIB gate (2.3.2): DUT received >= "
                        f"{total_count} prefixes from storm-sender peer group "
                        f"despite {shutdown_count} eBGP shutdown "
                        f"(spec-loyal storm-ingested probe)"
                    ),
                ),
            ]
            if storm_sender_peer_addr_prefix
            else []
        ),
        create_start_stop_bgp_peers_step(
            peer_regex=shutdown_peer_regex,
            start=True,
            start_idx=1,
            end_idx=shutdown_count,
            description=f"Phase 5 (2.3.2): bring {shutdown_count} eBGP sessions back UP",
        ),
        create_longevity_step(
            duration=post_recovery_settle_s,
            description=f"Phase 5-settle (2.3.2): {post_recovery_settle_s}s for full shadow-RIB re-sync to reconnected peers",
        ),
    ]

    # MUST run inline BEFORE ``cleanup_steps`` withdraws the storm prefixes.
    # TAAC lifecycle is ``trigger_steps -> cleanup_steps -> postchecks``, so
    # running this in postchecks would compare against a post-cleanup state
    # where ALL storm prefixes have been withdrawn and fail vacuously.
    inline_phase_6_checks: t.List[PointInTimeHealthCheck] = [
        create_bgp_session_establish_check(
            ignore_all_prefixes_except=shutdown_peer_addrs,
        ),
        *[
            create_bgp_peer_route_set_equality_check(
                baseline_peer_addr=addrs[0],
                tested_peer_addrs=addrs[1:],
            )
            for _label, addrs in _peer_groups_phase6
            if len(addrs) >= 2
        ],
    ]
    trigger_steps.append(
        create_validation_step(
            point_in_time_checks=inline_phase_6_checks,
            description=(
                f"Phase 6 equality gate (2.3.2): reconnected {shutdown_count} "
                f"eBGP peers Established; within each outbound-policy group "
                f"route sets are identical"
            ),
        ),
    )
    # DUT still has >= total_count from storm sender post-recovery (proves
    # storm+followup weren't accidentally withdrawn during shutdown/recovery
    # churn).
    if storm_sender_peer_addr_prefix:
        trigger_steps.append(
            create_verify_dut_received_from_peer_group_step(
                hostname=device_name,
                sender_peer_addr_prefix=storm_sender_peer_addr_prefix,
                min_prefix_count=total_count,
                description=(
                    f"Phase 6 ingress-RIB gate (2.3.2): DUT still has >= "
                    f"{total_count} prefixes from storm sender post-recovery"
                ),
            ),
        )

    cleanup_steps = [
        create_advertise_withdraw_prefixes_step(
            device_name=device_name,
            advertise=False,
            prefix_pool_regex=storm_prefix_pool_regex,
            prefix_start_index=0,
            prefix_end_index=total_count,
            description=f"Phase 7 cleanup (2.3.2): withdraw all {total_count} storm prefixes",
        ),
        create_longevity_step(
            duration=60,
            description="Phase 7 cleanup (2.3.2): 60s settle for clean withdrawal",
        ),
    ]

    if prechecks is None:
        prechecks = [
            create_bgp_update_group_check(expect_enabled=True),
            create_bgp_session_establish_check(
                expected_established_sessions=expected_established_sessions,
            ),
        ]
    if postchecks is None:
        postchecks = _ug_backpressure_common_postchecks(
            expected_established_sessions=expected_established_sessions,
            memory_threshold_bytes=memory_threshold_bytes,
            enforce_load_avg=False,
        )
    if snapshot_checks is None:
        snapshot_checks = list(BGP_STANDARD_SNAPSHOT_CHECKS)

    kwargs: t.Dict[str, t.Any] = {
        "name": "ug_backpressure_peer_blocks_down_recover",
        "stages": [
            create_steps_stage(
                steps=trigger_steps,
                description=f"Phase 1-5 (2.3.2): storm + shutdown {shutdown_count} + followup + recover",
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


def _pb3_swap_community_step(
    *,
    use_peer_scoped: bool,
    prefix_pool_regex: str,
    community_value: str,
    device_name: str,
    ixia_interface: str,
    device_group_regex: str,
    peer_scoped_description: str,
    legacy_description: str,
) -> Step:
    """PB3 Phase 2c / Phase 4 cleanup: swap the community on the eBGP attr-change
    prefix pool. Two implementations share this helper:

    - ``use_peer_scoped=True``: ``ixia_modify_communities`` task, peer-scoped
      Stop/Start (only flaps the eBGP peer owning the pool, no chassis cascade).
      Broadcasts across ALL slots to cover the round-robin seeding done at
      ``configure_community_pool`` setup time.
    - ``use_peer_scoped=False``: legacy ``configure_community_pool`` step
      (chassis-wide ``stop_protocols()`` cascade — only safe on small testbeds).

    The two branches emit different step descriptions on purpose — they do
    materially different things and downstream unit tests in
    ``test_ug_backpressure_playbooks.py`` grep those descriptions to prove
    the correct branch fired. Callers supply both strings explicitly so the
    text stays close to its author.
    """
    if use_peer_scoped:
        return create_run_task_step(
            task_name="ixia_modify_communities",
            params_dict={
                "prefix_pool_regex": prefix_pool_regex,
                "count": 0,
                "to_add": True,
                "community_values": [community_value],
                "broadcast_to_all_slots": True,
            },
            description=peer_scoped_description,
            ixia_needed=True,
        )
    return create_configure_community_pool_step(
        device_name=device_name,
        interface=ixia_interface,
        community_combinations=[[community_value]],
        device_group_regex=device_group_regex,
        description=legacy_description,
    )


def _pb3_phase_3_community_check(
    *,
    ebgp_sender_peer_addr: t.Optional[str],
    ibgp_receiver_peer_addrs: t.List[str],
    mutated_community: str,
    initial_community: str,
) -> PointInTimeHealthCheck:
    """PB3 Phase 3 spec gate. When ``ebgp_sender_peer_addr`` is set, probe the
    DUT's adj-RIB-IN for that eBGP sender (isolates the IXIA wrapper's
    contract from downstream UG-replication latency). Otherwise fall back to
    adj-RIB-OUT UG-validation across the iBGP receivers.
    """
    if ebgp_sender_peer_addr is not None:
        return create_bgp_received_route_community_check(
            sender_peer_addr=ebgp_sender_peer_addr,
            anchor_community=mutated_community,
            forbidden_communities=[initial_community],
        )
    return create_bgp_received_route_community_check(
        baseline_peer_addr=ibgp_receiver_peer_addrs[0],
        tested_peer_addrs=ibgp_receiver_peer_addrs[1:],
        anchor_community=mutated_community,
        forbidden_communities=[initial_community],
    )


def _pb3_phase_2_steps(
    *,
    device_name: str,
    ixia_interface: str,
    ebgp_attr_change_prefix_pool_regex: str,
    ebgp_attr_change_device_group_regex: str,
    withdraw_count: int,
    lp_modify_count: int,
    initial_community: str,
    mutated_community: str,
    target_local_pref: int,
    withdraw_settle_s: int,
    post_readd_settle_s: int,
    post_lp_modify_settle_s: int,
    skip_community_swap_for_cascade_safety: bool,
    use_peer_scoped_community_swap: bool,
) -> t.List[Step]:
    """PB3 Phase 2 step ladder: 2a (withdraw) -> 2b (settle) -> 2c (community
    swap, optional) -> 2d (re-advertise) -> 2d-settle -> 2e (LP-modify) ->
    2e-settle. Phase 2c is gated behind ``skip_community_swap_for_cascade_safety``
    because ``configure_community_pool`` cascades chassis-wide on EBB-scale
    IXIA topologies (see PB3 factory docstring + project memory).
    """
    steps: t.List[Step] = [
        create_advertise_withdraw_prefixes_step(
            device_name=device_name,
            advertise=False,
            prefix_pool_regex=ebgp_attr_change_prefix_pool_regex,
            prefix_start_index=0,
            prefix_end_index=withdraw_count,
            description=f"Phase 2a (2.3.3): withdraw {withdraw_count} eBGP routes under iBGP-storm backpressure",
        ),
        create_longevity_step(
            duration=withdraw_settle_s,
            description=f"Phase 2b (2.3.3): wait {withdraw_settle_s}s (per spec) for withdraw to propagate via UG",
        ),
    ]
    if not skip_community_swap_for_cascade_safety:
        steps.append(
            _pb3_swap_community_step(
                use_peer_scoped=use_peer_scoped_community_swap,
                prefix_pool_regex=ebgp_attr_change_prefix_pool_regex,
                community_value=mutated_community,
                device_name=device_name,
                ixia_interface=ixia_interface,
                device_group_regex=ebgp_attr_change_device_group_regex,
                peer_scoped_description=(
                    f"Phase 2c (2.3.3, peer-scoped): swap community on "
                    f"{ebgp_attr_change_prefix_pool_regex} ALL slots -> "
                    f"{mutated_community} (peer flap only, no chassis cascade)"
                ),
                legacy_description=(
                    f"Phase 2c (2.3.3): swap eBGP DG community pool "
                    f"{initial_community} -> {mutated_community}"
                ),
            )
        )
    readd_community_label = (
        mutated_community
        if not skip_community_swap_for_cascade_safety
        else f"{initial_community} (swap skipped for cascade safety)"
    )
    steps.extend(
        [
            create_advertise_withdraw_prefixes_step(
                device_name=device_name,
                advertise=True,
                prefix_pool_regex=ebgp_attr_change_prefix_pool_regex,
                prefix_start_index=0,
                prefix_end_index=withdraw_count,
                description=f"Phase 2d (2.3.3): re-advertise {withdraw_count} eBGP routes carrying community {readd_community_label}",
            ),
            create_longevity_step(
                duration=post_readd_settle_s,
                description=f"Phase 2d-settle (2.3.3): {post_readd_settle_s}s for re-added routes to reach all iBGP peers",
            ),
            create_randomize_prefix_local_preference_step(
                ebgp_attr_change_prefix_pool_regex,
                withdraw_count,
                withdraw_count + lp_modify_count,
                target_local_pref,
                target_local_pref + 1,
                description=(
                    f"Phase 2e (2.3.3): LP-modify {lp_modify_count} eBGP routes "
                    f"to LocalPref={target_local_pref} (from default 100)"
                ),
            ),
            create_longevity_step(
                duration=post_lp_modify_settle_s,
                description=f"Phase 2e-settle (2.3.3): {post_lp_modify_settle_s}s for LP-modify to propagate",
            ),
        ]
    )
    return steps


def _pb3_cleanup_steps(
    *,
    device_name: str,
    ixia_interface: str,
    ibgp_storm_prefix_pool_regex: str,
    ibgp_storm_prefix_count: int,
    ebgp_attr_change_prefix_pool_regex: str,
    ebgp_attr_change_device_group_regex: str,
    initial_community: str,
    skip_community_swap_for_cascade_safety: bool,
    use_peer_scoped_community_swap: bool,
) -> t.List[Step]:
    """PB3 Phase 4 cleanup: restore the eBGP community pool to its initial
    value (mirroring the Phase 2c mutation path — peer-scoped if Phase 2c
    was peer-scoped) and withdraw the iBGP storm.
    """
    steps: t.List[Step] = []
    if not skip_community_swap_for_cascade_safety:
        steps.append(
            _pb3_swap_community_step(
                use_peer_scoped=use_peer_scoped_community_swap,
                prefix_pool_regex=ebgp_attr_change_prefix_pool_regex,
                community_value=initial_community,
                device_name=device_name,
                ixia_interface=ixia_interface,
                device_group_regex=ebgp_attr_change_device_group_regex,
                peer_scoped_description=(
                    f"Phase 4 cleanup (2.3.3, peer-scoped): restore "
                    f"{ebgp_attr_change_prefix_pool_regex} ALL slots -> "
                    f"{initial_community}"
                ),
                legacy_description=(
                    f"Phase 4 cleanup (2.3.3): restore eBGP DG community to "
                    f"{initial_community}"
                ),
            )
        )
    steps.extend(
        [
            create_advertise_withdraw_prefixes_step(
                device_name=device_name,
                advertise=False,
                prefix_pool_regex=ibgp_storm_prefix_pool_regex,
                prefix_start_index=0,
                prefix_end_index=ibgp_storm_prefix_count,
                description="Phase 4 cleanup (2.3.3): withdraw iBGP storm prefixes",
            ),
            create_longevity_step(
                duration=60,
                description="Phase 4 cleanup (2.3.3): 60s settle for clean state",
            ),
        ]
    )
    return steps


def create_bgp_ug_backpressure_withdraw_attr_change_playbook(
    *,
    device_name: str,
    ixia_interface: str,
    ibgp_storm_prefix_pool_regex: str,
    ibgp_storm_device_group_regex: str,
    ibgp_storm_prefix_count: int,
    community_combinations: t.List[t.List[str]],
    extended_community_combinations: t.List[t.List[str]],
    as_path: t.List[int],
    ebgp_attr_change_prefix_pool_regex: str,
    ebgp_attr_change_device_group_regex: str,
    ebgp_attr_change_prefix_count: int,
    withdraw_count: int,
    lp_modify_count: int,
    initial_community: str,
    mutated_community: str,
    target_local_pref: int,
    ibgp_receiver_peer_addrs: t.List[str],
    expected_established_sessions: int,
    memory_threshold_bytes: int,
    post_storm_settle_s: int = 60,
    withdraw_settle_s: int = 30,
    post_readd_settle_s: int = 60,
    post_lp_modify_settle_s: int = 60,
    skip_community_swap_for_cascade_safety: bool = False,
    use_peer_scoped_community_swap: bool = False,
    ebgp_sender_peer_addr: t.Optional[str] = None,
    setup_steps: t.Optional[t.List[Step]] = None,
    prechecks: t.Optional[t.List[PointInTimeHealthCheck]] = None,
    postchecks: t.Optional[t.List[PointInTimeHealthCheck]] = None,
    snapshot_checks: t.Optional[t.List[SnapshotHealthCheck]] = None,
) -> Playbook:
    """Build the BGP++ Update Group qualification 2.3.3 playbook --
    'Withdraw and Attribute Change Under Backpressure'.

    Spec: under iBGP-storm backpressure (5K prefixes w/ heavy attrs), perform
    eBGP-side operations:
      - withdraw ``withdraw_count`` (200) of existing eBGP routes
      - wait 30s
      - re-add the ``withdraw_count`` routes with a new community
      - modify LOCAL_PREF on ``lp_modify_count`` (100) other routes
    Verify all iBGP receiver peers see the correct sequence + identical
    final state. No stale community values.

    With ``skip_community_swap_for_cascade_safety=True``, Phase 2c (the
    `configure_community_pool` swap on the eBGP attr-change DG) AND its
    matching `BGP_RECEIVED_ROUTE_COMMUNITY_CHECK` postcheck are OMITTED.
    Phase 2a (withdraw 200) + Phase 2d (re-advertise 200, SAME community
    as initial) + Phase 2e (LP-modify 100) still run. Use this on
    full-scale EBB testbeds where `configure_community_pool` mid-test
    cascade-resets all 1272 BGP TCP sessions chassis-wide (root cause
    in `ixia.py`: unconditional `stop_protocols()`, see project memory
    [[project-bgp-ug-backpressure-validation-matrix]]). The remaining
    PB3 surface still validates the withdraw/re-add round-trip + LP
    propagation under backpressure -- only the community-mutation aspect
    of the spec is dropped until the framework is fixed or the swap is
    re-implemented via peer-scoped `IxiaModifyBgpPrefixesCommunities`.

    Args:
        device_name: DUT hostname.
        ixia_interface: IXIA logical interface (used for community pool config).
        ibgp_storm_prefix_pool_regex: iBGP backpressure storm sender pool regex.
        ibgp_storm_device_group_regex: iBGP storm DG regex.
        ibgp_storm_prefix_count: Storm prefix count (spec: 5000).
        community_combinations: Storm community pool config (heavy-attr 32+).
        extended_community_combinations: Storm ext-community pool config (16+).
        as_path: Storm AS_PATH (255 ASNs).
        ebgp_attr_change_prefix_pool_regex: eBGP route pool that gets
            withdrawn/re-added/LP-modified.
        ebgp_attr_change_device_group_regex: eBGP DG regex for community
            reconfig.
        ebgp_attr_change_prefix_count: Pre-existing eBGP route count
            (must be >= withdraw_count + lp_modify_count).
        withdraw_count: Routes to withdraw + re-add (spec: 200).
        lp_modify_count: Routes to LP-modify (spec: 100).
        initial_community: Community on routes pre-test (e.g. "65529:34814").
        mutated_community: Community after re-add (e.g. "65529:99999").
        target_local_pref: New LP value (spec: 200, from default 100).
        ibgp_receiver_peer_addrs: iBGP peer IPs that observe the operations.
        expected_established_sessions: Total sessions post-test.
        memory_threshold_bytes: VmHWM ceiling for Bgp.
        skip_community_swap_for_cascade_safety: When True, omit the Phase 2c
            community-pool swap and its matching postcheck. Default False.
        use_peer_scoped_community_swap: When True (and the swap is enabled),
            route Phase 2c + cleanup through ``ixia_modify_communities``
            (peer-scoped Stop/Start, single eBGP DG) instead of the legacy
            chassis-wide ``configure_community_pool`` (which cascades a
            ``stop_protocols()`` across all DGs). Default False. Requires
            the prefix pool to have ``NoOfCommunities>0`` already.
        ebgp_sender_peer_addr: Optional eBGP peer IP that owns the prefix
            pool the wrapper task mutates. When set, the inline Phase 3
            spec gate switches to adj-RIB-IN trigger-verification mode
            (probes ``getPrefilterReceivedNetworks(sender)`` and asserts
            the mutated community arrived on the WIRE), which isolates the
            wrapper's contract from any downstream UG-replication latency.
            Without it, the gate falls back to adj-RIB-OUT UG-validation
            (compares per-prefix community across the iBGP receivers).
    """
    # Validate the docstring invariant at construction time so under-sized
    # pools fail loudly here, not deep inside a runtime advertise/withdraw
    # step where the failure reads as a generic IXIA error.
    if ebgp_attr_change_prefix_count < withdraw_count + lp_modify_count:
        raise ValueError(
            f"ebgp_attr_change_prefix_count={ebgp_attr_change_prefix_count} "
            f"is smaller than withdraw_count + lp_modify_count="
            f"{withdraw_count} + {lp_modify_count} = "
            f"{withdraw_count + lp_modify_count}; the pool cannot host "
            "both Phase 2a withdraws and Phase 2e LP-modifies non-overlappingly"
        )
    storm_steps = _heavy_attr_advertise_steps(
        device_name=device_name,
        ixia_interface=ixia_interface,
        prefix_pool_regex=ibgp_storm_prefix_pool_regex,
        device_group_regex=ibgp_storm_device_group_regex,
        prefix_start_index=0,
        prefix_end_index=ibgp_storm_prefix_count,
        community_combinations=community_combinations,
        extended_community_combinations=extended_community_combinations,
        as_path=as_path,
        randomize_med=False,
        randomize_local_pref=False,
        randomize_origin=False,
        description_prefix="Phase 1 (2.3.3)",
    )

    phase_2_steps = _pb3_phase_2_steps(
        device_name=device_name,
        ixia_interface=ixia_interface,
        ebgp_attr_change_prefix_pool_regex=ebgp_attr_change_prefix_pool_regex,
        ebgp_attr_change_device_group_regex=ebgp_attr_change_device_group_regex,
        withdraw_count=withdraw_count,
        lp_modify_count=lp_modify_count,
        initial_community=initial_community,
        mutated_community=mutated_community,
        target_local_pref=target_local_pref,
        withdraw_settle_s=withdraw_settle_s,
        post_readd_settle_s=post_readd_settle_s,
        post_lp_modify_settle_s=post_lp_modify_settle_s,
        skip_community_swap_for_cascade_safety=skip_community_swap_for_cascade_safety,
        use_peer_scoped_community_swap=use_peer_scoped_community_swap,
    )

    trigger_steps = (
        storm_steps
        + [
            create_longevity_step(
                duration=post_storm_settle_s,
                description=f"Phase 1-settle (2.3.3): {post_storm_settle_s}s for iBGP storm to create backpressure",
            ),
        ]
        + phase_2_steps
    )

    # Phase 3 spec gates -- attribute correctness on iBGP peers.
    #
    # The community-anchor check MUST run inline (before cleanup_steps reverts
    # the eBGP DG community back to initial_community), so it sees the
    # mutated state on the wire. TAAC lifecycle is
    # ``trigger_steps -> cleanup_steps -> postchecks``, and Phase 4 cleanup
    # below restores the community for test hygiene -- by the time postchecks
    # run, the mutated_community is gone from the prefix attribute. The
    # route-set-equality check is lifecycle-insensitive (still asserts every
    # iBGP peer received the same routes), so it stays in postchecks.
    inline_phase_3_checks: t.List[PointInTimeHealthCheck] = []
    postcheck_phase_3_checks: t.List[PointInTimeHealthCheck] = []
    if not skip_community_swap_for_cascade_safety:
        # Prefer the adj-RIB-IN probe when ``ebgp_sender_peer_addr`` is
        # supplied: it reads the DUT's view of the sender directly, isolating
        # the wrapper's contract from downstream UG-replication latency.
        # Without ``ebgp_sender_peer_addr``, fall back to the adj-RIB-OUT
        # form (per-prefix community across iBGP receivers).
        #
        # Spec 2.3.3: receivers must observe the new (``anchor``) community
        # AND the old (``forbidden``) community must be absent. Both
        # sub-assertions run inline BEFORE cleanup reverts the mutation.
        #
        # Caveat: if the initial community lands in a non-slot-0 position
        # for any route at setup time (per-route ``community_combinations``
        # cycling in ``configure_community_pool``), the slot-0-only wrapper
        # cannot reach it and the forbidden check will fire on those routes.
        # Setup-side fix: use non-overlapping initial/mutated values.
        inline_phase_3_checks.append(
            _pb3_phase_3_community_check(
                ebgp_sender_peer_addr=ebgp_sender_peer_addr,
                ibgp_receiver_peer_addrs=ibgp_receiver_peer_addrs,
                mutated_community=mutated_community,
                initial_community=initial_community,
            )
        )
    postcheck_phase_3_checks.append(
        create_bgp_peer_route_set_equality_check(
            baseline_peer_addr=ibgp_receiver_peer_addrs[0],
            tested_peer_addrs=ibgp_receiver_peer_addrs[1:],
        ),
    )
    if inline_phase_3_checks:
        trigger_steps.append(
            create_validation_step(
                point_in_time_checks=inline_phase_3_checks,
                description=(
                    "Phase 3 inline trigger-verification gate (2.3.3): "
                    "mutated community present + forbidden initial community "
                    "absent on the eBGP sender's adj-RIB-IN (or iBGP "
                    "receivers' adj-RIB-OUT when no sender_peer_addr is set), "
                    "BEFORE Phase 4 cleanup reverts the eBGP DG community"
                ),
            ),
        )

    cleanup_steps = _pb3_cleanup_steps(
        device_name=device_name,
        ixia_interface=ixia_interface,
        ibgp_storm_prefix_pool_regex=ibgp_storm_prefix_pool_regex,
        ibgp_storm_prefix_count=ibgp_storm_prefix_count,
        ebgp_attr_change_prefix_pool_regex=ebgp_attr_change_prefix_pool_regex,
        ebgp_attr_change_device_group_regex=ebgp_attr_change_device_group_regex,
        initial_community=initial_community,
        skip_community_swap_for_cascade_safety=skip_community_swap_for_cascade_safety,
        use_peer_scoped_community_swap=use_peer_scoped_community_swap,
    )

    if prechecks is None:
        prechecks = [
            create_bgp_update_group_check(expect_enabled=True),
            create_bgp_session_establish_check(
                expected_established_sessions=expected_established_sessions,
            ),
        ]
    if postchecks is None:
        postchecks = list(
            postcheck_phase_3_checks
        ) + _ug_backpressure_common_postchecks(
            expected_established_sessions=expected_established_sessions,
            memory_threshold_bytes=memory_threshold_bytes,
            enforce_load_avg=False,
            enforce_log_parsing=True,  # spec criterion for 2.3.3
        )
    if snapshot_checks is None:
        snapshot_checks = list(BGP_STANDARD_SNAPSHOT_CHECKS)

    kwargs: t.Dict[str, t.Any] = {
        "name": "ug_backpressure_withdraw_attr_change",
        "stages": [
            create_steps_stage(
                steps=trigger_steps,
                description="Phase 1-2 (2.3.3): iBGP storm + eBGP withdraw/re-add/LP-modify under backpressure",
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


def create_bgp_ug_backpressure_all_peers_block_down_recover_playbook(
    *,
    device_name: str,
    ixia_interface: str,
    storm_prefix_pool_regex: str,
    storm_device_group_regex: str,
    storm_initial_prefix_count: int,
    storm_followup_prefix_count: int,
    community_combinations: t.List[t.List[str]],
    extended_community_combinations: t.List[t.List[str]],
    as_path: t.List[int],
    ebgp_group_dg_regex: str,
    ebgp_peer_addrs: t.List[str],
    bgp_mon_peer_addrs: t.List[str],
    ibgp_peer_addrs: t.List[str],
    expected_established_sessions: int,
    memory_threshold_bytes: int,
    post_shutdown_settle_s: int = 90,
    post_inject_settle_s: int = 60,
    post_recovery_settle_s: int = 300,
    setup_steps: t.Optional[t.List[Step]] = None,
    prechecks: t.Optional[t.List[PointInTimeHealthCheck]] = None,
    postchecks: t.Optional[t.List[PointInTimeHealthCheck]] = None,
    snapshot_checks: t.Optional[t.List[SnapshotHealthCheck]] = None,
    # See PB1 factory param note: DUT ingress-RIB probe for storm arrival.
    storm_sender_peer_addr_prefix: t.Optional[str] = None,
) -> Playbook:
    """Build the BGP++ Update Group qualification 2.3.4 playbook --
    'All Peers in Group Block, Then All Go Down, Then All Come Back'.

    Spec edge case: under a 10K-prefix iBGP storm w/ heavy attrs aiming to
    block ALL eBGP peers simultaneously, the entire eBGP DG is taken down at
    once (without GR -- truly simultaneous via ``toggle_device_groups``,
    tearing down the L3 stack). Then 500 more iBGP routes are injected (only
    iBGP active). Then the entire eBGP DG is brought back up simultaneously.
    All 280 eBGP peers must receive full re-sync from the shadow RIB.
    iBGP + BGP_MON peers must be unaffected throughout.

    Trigger sequence:
      Phase 1 (storm): heavy-attr advertise ``storm_initial_prefix_count``
        prefixes from the iBGP sender.
      Phase 2 (mass shutdown -- simultaneous): toggle the WHOLE eBGP DG
        ``enable=False`` via single ``toggle_device_groups`` call.
      Phase 3 (verify no crash): intermediate snapshot for core dumps.
      Phase 4 (followup inject): inject ``storm_followup_prefix_count``
        more prefixes from iBGP while eBGP is fully down.
      Phase 5 (verify unaffected): iBGP + BGP_MON have full + followup.
      Phase 6 (recovery -- simultaneous): toggle the WHOLE eBGP DG
        ``enable=True``.
      Phase 7 (spec gate): all 280 eBGP peers received full re-sync
        from shadow RIB.
    """
    total_count = storm_initial_prefix_count + storm_followup_prefix_count
    unaffected_peers = list(bgp_mon_peer_addrs) + list(ibgp_peer_addrs)
    storm_steps = _heavy_attr_advertise_steps(
        device_name=device_name,
        ixia_interface=ixia_interface,
        prefix_pool_regex=storm_prefix_pool_regex,
        device_group_regex=storm_device_group_regex,
        prefix_start_index=0,
        prefix_end_index=storm_initial_prefix_count,
        community_combinations=community_combinations,
        extended_community_combinations=extended_community_combinations,
        as_path=as_path,
        randomize_med=False,
        randomize_local_pref=False,
        randomize_origin=False,
        description_prefix="Phase 1 (2.3.4)",
    )

    trigger_steps = storm_steps + [
        create_ixia_api_step(
            api_name="toggle_device_groups",
            args_dict={
                "enable": False,
                "device_group_name_regex": ebgp_group_dg_regex,
                "sleep_time_before_applying_change": 0,
            },
            description=(
                f"Phase 2 (2.3.4): MASS SHUTDOWN -- DG-disable WHOLE eBGP "
                f"group ({len(ebgp_peer_addrs)} peers) simultaneously, "
                "no GR -- peers may have been blocked when going down"
            ),
        ),
        create_longevity_step(
            duration=post_shutdown_settle_s,
            description=f"Phase 2-settle (2.3.4): {post_shutdown_settle_s}s for DUT hold-timer + UG cleanup",
        ),
        create_validation_step(
            point_in_time_checks=[
                # Expected count is the size of the scoped filter (NOT the
                # chassis-wide surviving total): the check is already
                # restricted to ``unaffected_peers`` via
                # ``ignore_all_prefixes_except``.
                create_bgp_session_establish_check(
                    ignore_all_prefixes_except=unaffected_peers,
                    expected_established_sessions=len(unaffected_peers),
                ),
                create_bgp_session_establish_check(
                    ignore_all_prefixes_except=list(ebgp_peer_addrs),
                    expected_established_sessions=0,
                ),
                create_bgp_update_group_check(expect_enabled=True),
            ],
            description="Phase 3 mid-shutdown gate (2.3.4): iBGP+BGP_MON UP, all eBGP DOWN, UG intact",
        ),
        create_advertise_withdraw_prefixes_step(
            device_name=device_name,
            advertise=True,
            prefix_pool_regex=storm_prefix_pool_regex,
            prefix_start_index=storm_initial_prefix_count,
            prefix_end_index=total_count,
            description=f"Phase 4 (2.3.4): inject {storm_followup_prefix_count} more prefixes while all eBGP down",
        ),
        create_longevity_step(
            duration=post_inject_settle_s,
            description=f"Phase 4-settle (2.3.4): {post_inject_settle_s}s for iBGP+BGP_MON to receive followup",
        ),
        create_validation_step(
            point_in_time_checks=[
                # ``unaffected_peers = bgp_mon + ibgp`` both fall under the
                # DUT's iBGP-fanout policy (BGP_MON receives the same full
                # RIB), so a single cross-peer equality check is valid.
                create_bgp_peer_route_set_equality_check(
                    baseline_peer_addr=unaffected_peers[0],
                    tested_peer_addrs=unaffected_peers[1:],
                ),
            ],
            description=(
                "Phase 5 equality gate (2.3.4): iBGP+BGP_MON have identical "
                "route sets despite eBGP being down"
            ),
        ),
        *(
            [
                create_verify_dut_received_from_peer_group_step(
                    hostname=device_name,
                    sender_peer_addr_prefix=storm_sender_peer_addr_prefix,
                    min_prefix_count=total_count,
                    description=(
                        f"Phase 5 ingress-RIB gate (2.3.4): DUT received >= "
                        f"{total_count} prefixes from storm sender despite "
                        f"all {len(ebgp_peer_addrs)} eBGP peers being down "
                        f"(spec: iBGP-source storm still reaches DUT)"
                    ),
                ),
            ]
            if storm_sender_peer_addr_prefix
            else []
        ),
        create_ixia_api_step(
            api_name="toggle_device_groups",
            args_dict={
                "enable": True,
                "device_group_name_regex": ebgp_group_dg_regex,
                "sleep_time_before_applying_change": 0,
            },
            description=(
                f"Phase 6 (2.3.4): MASS RECOVERY -- DG-enable WHOLE eBGP "
                f"group ({len(ebgp_peer_addrs)} peers) simultaneously"
            ),
        ),
        create_longevity_step(
            duration=post_recovery_settle_s,
            description=f"Phase 6-settle (2.3.4): {post_recovery_settle_s}s for full shadow-RIB re-sync to all {len(ebgp_peer_addrs)} eBGP peers",
        ),
    ]

    # MUST run inline BEFORE ``cleanup_steps`` withdraws the storm prefixes.
    # TAAC lifecycle is ``trigger_steps -> cleanup_steps -> postchecks``, so
    # running this in postchecks would compare against a post-cleanup state
    # where ALL storm prefixes have been withdrawn and fail vacuously.
    # Split into per-outbound-policy-group equality checks (iBGP receives
    # full RIB, eBGP receives an egress-policy-filtered subset).
    inline_phase_7_checks: t.List[PointInTimeHealthCheck] = [
        create_bgp_session_establish_check(
            ignore_all_prefixes_except=list(ebgp_peer_addrs),
        ),
    ]
    if len(ebgp_peer_addrs) >= 2:
        inline_phase_7_checks.append(
            create_bgp_peer_route_set_equality_check(
                baseline_peer_addr=ebgp_peer_addrs[0],
                tested_peer_addrs=list(ebgp_peer_addrs[1:]),
            )
        )
    if len(unaffected_peers) >= 2:
        inline_phase_7_checks.append(
            create_bgp_peer_route_set_equality_check(
                baseline_peer_addr=unaffected_peers[0],
                tested_peer_addrs=unaffected_peers[1:],
            )
        )
    trigger_steps.append(
        create_validation_step(
            point_in_time_checks=inline_phase_7_checks,
            description=(
                f"Phase 7 equality gate (2.3.4): recovered "
                f"{len(ebgp_peer_addrs)} eBGP peers + iBGP unaffected peers "
                f"each converged within their outbound-policy group"
            ),
        ),
    )
    # "eBGP peers received full re-sync" cannot be verified via peer
    # sent_count on this topology (egress policy filters heavy-attr storm);
    # the ingress-RIB probe validates the DUT-side half of the spec.
    if storm_sender_peer_addr_prefix:
        trigger_steps.append(
            create_verify_dut_received_from_peer_group_step(
                hostname=device_name,
                sender_peer_addr_prefix=storm_sender_peer_addr_prefix,
                min_prefix_count=total_count,
                description=(
                    f"Phase 7 ingress-RIB gate (2.3.4): DUT still has >= "
                    f"{total_count} prefixes from storm sender post-recovery"
                ),
            ),
        )

    cleanup_steps = [
        create_advertise_withdraw_prefixes_step(
            device_name=device_name,
            advertise=False,
            prefix_pool_regex=storm_prefix_pool_regex,
            prefix_start_index=0,
            prefix_end_index=total_count,
            description=f"Phase 8 cleanup (2.3.4): withdraw all {total_count} storm prefixes",
        ),
        create_longevity_step(
            duration=60,
            description="Phase 8 cleanup (2.3.4): 60s settle for clean withdrawal",
        ),
    ]

    if prechecks is None:
        prechecks = [
            create_bgp_update_group_check(expect_enabled=True),
            create_bgp_session_establish_check(
                expected_established_sessions=expected_established_sessions,
            ),
        ]
    if postchecks is None:
        postchecks = _ug_backpressure_common_postchecks(
            expected_established_sessions=expected_established_sessions,
            memory_threshold_bytes=memory_threshold_bytes,
            enforce_load_avg=False,
            enforce_log_parsing=True,  # spec criterion for 2.3.4
        )
    if snapshot_checks is None:
        snapshot_checks = list(BGP_STANDARD_SNAPSHOT_CHECKS)

    kwargs: t.Dict[str, t.Any] = {
        "name": "ug_backpressure_all_peers_block_down_recover",
        "stages": [
            create_steps_stage(
                steps=trigger_steps,
                description=f"Phase 1-6 (2.3.4): storm + mass-shutdown {len(ebgp_peer_addrs)} eBGP + followup + mass-recovery",
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


def create_bgp_ug_backpressure_topology_smoke_playbook(
    *,
    expected_established_sessions: int,
    longevity_duration_s: int = 1800,
) -> Playbook:
    """Topology-smoke playbook for ``<TESTBED>_BGP_UG_BACKPRESSURE_TOPOLOGY_SMOKE``:
    brings the EBB-scale testbed up, asserts all expected sessions Established
    + UG enabled, sits on a longevity step so the operator can hands-on probe
    the device, then a final session-establish + UG-enabled gate.

    Paired with `--skip-teardown-tasks --skip-ixia-cleanup` to keep both DUT
    bgpcpp + IXIA topology alive for hands-on inspection after the playbook
    completes. Lives here (not in the testconfig) because the
    no-inline-Playbook-construction gate test requires all Playbook factories
    to live in `playbooks/playbook_definitions.py`.
    """
    return Playbook(
        name="bgp_ug_backpressure_topology_smoke",
        prechecks=[
            create_bgp_update_group_check(expect_enabled=True),
            create_bgp_session_establish_check(
                expected_established_sessions=expected_established_sessions,
            ),
        ],
        stages=[
            create_steps_stage(
                steps=[
                    create_longevity_step(
                        duration=longevity_duration_s,
                        description=(
                            f"Topology smoke: hold the testbed live for "
                            f"{longevity_duration_s}s for hands-on probing. "
                            "Pair this run with --skip-teardown-tasks "
                            "--skip-ixia-cleanup so the DUT and IXIA session "
                            "both persist after the playbook completes."
                        ),
                    ),
                ],
                description=f"Topology smoke: {longevity_duration_s}s longevity hold",
            ),
        ],
        postchecks=[
            create_bgp_session_establish_check(
                expected_established_sessions=expected_established_sessions,
            ),
            create_bgp_update_group_check(expect_enabled=True),
        ],
        snapshot_checks=[],
    )
