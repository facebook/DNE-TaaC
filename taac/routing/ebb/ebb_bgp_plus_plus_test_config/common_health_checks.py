# pyre-unsafe
from taac.constants import Gigabyte
from taac.health_checks.healthcheck_definitions import (
    create_bgp_convergence_check,
    create_bgp_graceful_restart_check,
    create_bgp_peer_route_snapshot_check,
    create_bgp_rib_fib_consistency_check,
    create_bgp_session_establish_check,
    create_bgp_session_snapshot_check,
    create_bgp_stale_route_check,
    create_bgp_tcpdump_check,
    create_core_dumps_snapshot_check,
    create_cpu_utilization_check,
    create_drain_state_check,
    create_file_exists_check,
    create_hardware_capacity_check,
    create_ibgp_pnh_metric_check,
    create_log_parsing_check,
    create_memory_utilization_check,
    create_service_restart_check,
    create_system_cpu_load_average_check,
    create_unclean_exit_check,
)
from taac.routing.ebb.ebb_bgp_plus_plus_test_config.ebb_bgp_plus_plus_conveyor.conveyor_constants import (
    IXIA_BGP_MON_IC_PARENT_NETWORK,
)
from taac.utils.hardware_capacity_utils import (
    get_postcheck_thresholds,
    get_precheck_thresholds,
)
from taac.test_as_a_config.types import PointInTimeHealthCheck, SnapshotHealthCheck

_MEMORY_THRESHOLD_BY_SERVICE_PRECHECK = {
    "bgpd": Gigabyte.GIG_4_POINT_5.value,
    "fsdb": Gigabyte.GIG_5.value,
    "qsfp_service": Gigabyte.GIG_2.value,
    "fboss_sw_agent": Gigabyte.GIG_9.value,
    "fboss_hw_agent@0": Gigabyte.GIG_8.value,
}

_MEMORY_THRESHOLD_BY_SERVICE_POSTCHECK = {
    "bgpd": Gigabyte.GIG_10.value,
    "fsdb": Gigabyte.GIG_5.value,
    "qsfp_service": Gigabyte.GIG_2.value,
    "fboss_sw_agent": Gigabyte.GIG_9.value,
    "fboss_hw_agent@0": Gigabyte.GIG_8.value,
}

# Standard BGP Prechecks
BGP_STANDARD_PRECHECKS = [
    create_bgp_session_establish_check(),
    create_drain_state_check(),
    create_memory_utilization_check(
        threshold=Gigabyte.GIG_5.value,
        # pyrefly: ignore [bad-argument-type]
        threshold_by_service=_MEMORY_THRESHOLD_BY_SERVICE_PRECHECK,
        start_time_jq_var="test_case_start_time",
    ),
    create_cpu_utilization_check(
        threshold=400.0, start_time_jq_var="test_case_start_time"
    ),
]

# Standard BGP Snapshot Checks
BGP_STANDARD_SNAPSHOT_CHECKS = [
    create_core_dumps_snapshot_check(),
    create_bgp_peer_route_snapshot_check(),
]

# Standard BGP Postchecks
BGP_STANDARD_POSTCHECKS = [
    create_bgp_convergence_check(convergence_threshold=600, fail_on_eor_expired=False),
    create_unclean_exit_check(),
    create_bgp_stale_route_check(),
    create_memory_utilization_check(
        threshold=Gigabyte.GIG_5.value,
        # pyrefly: ignore [bad-argument-type]
        threshold_by_service=_MEMORY_THRESHOLD_BY_SERVICE_POSTCHECK,
        start_time_jq_var="test_case_start_time",
    ),
    create_cpu_utilization_check(
        threshold=400.0, start_time_jq_var="test_case_start_time"
    ),
    create_drain_state_check(),
]


# Single source of truth for the standard EBB RIB-FIB consistency check budget
# and heal-latency probe knobs, shared by both the precheck and the postcheck so
# the two cannot drift apart. The 5x30s exponential-backoff budget (re-checks at
# ~30/75/142/244/396s) rides out post-restart RIB->FIB re-convergence
# (~117.8s observed on bag011); the 480s probe cap still self-classifies any
# residual FAIL as transient vs persistent.
_RIB_FIB_RETRY_COUNT = 5
_RIB_FIB_RETRY_DELAY_SECONDS = 30
_RIB_FIB_HEAL_LATENCY_MAX_SEC = 480
_RIB_FIB_HEAL_LATENCY_POLL_SEC = 10

# Standard BGP session-establish check retry budget, shared by the precheck and
# postcheck so the two cannot drift apart (exponential backoff, multiplier 1.5x:
# 10s, 15s, 22.5s).
_BGP_SESSION_RETRY_COUNT = 3
_BGP_SESSION_RETRY_DELAY_SECONDS = 10.0

# BGP convergence-time threshold (seconds), shared by the precheck and postcheck
# convergence checks. Doubles as the precheck's self-wait budget for the device
# to reach INITIALIZED; sized for post-restart / cold-boot convergence.
_BGP_CONVERGENCE_THRESHOLD_SECONDS = 600


def create_standard_prechecks(
    peergroup_ibgp_v6: str,
    peergroup_ibgp_v4: str,
    precheck_thresholds=None,
    expected_established_sessions: int = 0,
    cpu_baseline: float = 4.0,
    check_ibgp_pnh: bool = False,
    check_bgp_convergence: bool = True,
    rp_file_path: str | None = None,
    bgp_session_retry_count: int = _BGP_SESSION_RETRY_COUNT,
    bgp_session_retry_delay_seconds: float = _BGP_SESSION_RETRY_DELAY_SECONDS,
    exclude_bgp_mon: bool = True,
    rib_fib_precheck_json_params: dict | None = None,
    rib_fib_precheck_retry_count: int = _RIB_FIB_RETRY_COUNT,
    rib_fib_precheck_retry_delay_seconds: int = _RIB_FIB_RETRY_DELAY_SECONDS,
    skip_rib_fib_precheck: bool = False,
    rib_fib_record_heal_latency: bool = True,
    rib_fib_heal_latency_max_sec: int = _RIB_FIB_HEAL_LATENCY_MAX_SEC,
    rib_fib_heal_latency_poll_sec: int = _RIB_FIB_HEAL_LATENCY_POLL_SEC,
) -> list[PointInTimeHealthCheck]:
    """
    Create standard prechecks for BGP tests.

    Args:
        peergroup_ibgp_v6: IPv6 iBGP peer group name
        peergroup_ibgp_v4: IPv4 iBGP peer group name
        precheck_thresholds: Hardware capacity thresholds (optional)
        expected_established_sessions: Expected number of established BGP sessions
        cpu_baseline: CPU load average baseline threshold
        check_ibgp_pnh: Enable iBGP PNH metric check (only for Open/R profiles)
        check_bgp_convergence: Add the BGP++ initialization-events convergence
            precheck (default True). Asserts the device reached INITIALIZED
            within the convergence threshold (self-waits up to it). The strict
            canonical-sequence and EOR-timer-expiry assertions are temporarily
            disabled pending the BGP++ cold-start EOR-timer fix.
        rp_file_path: Path to routing policy file (optional)
        bgp_session_retry_count: Number of retries for the BGP session
            establish check on FAIL (default 3). Retries the full
            data-fetch + validation cycle with exponential backoff
            (multiplier 1.5x). Set to 0 for single-shot behavior.
        bgp_session_retry_delay_seconds: Base delay in seconds before the
            first retry (default 10.0). Subsequent delays grow by 1.5x:
            10s, 15s, 22.5s.
        exclude_bgp_mon: When True, exclude BGP_MON peers from session
            establish checks via ``parent_prefixes_to_ignore``. BGP_MON IXIA peers
            flap frequently and cause false health check failures.
        rib_fib_precheck_json_params: Optional extra params forwarded to the
            RIB-FIB consistency precheck (e.g. parent prefixes to ignore).
            Mirrors ``rib_fib_json_params`` on ``create_standard_postchecks``.
        rib_fib_precheck_retry_count: Retry count for the RIB-FIB consistency
            precheck on FAIL (default 5). The precheck runs right after setup —
            including a BGP daemon restart / cold start — where RIB->FIB is
            still converging (~117.8s observed on a daemon-restart re-converge),
            so it retries the full data-fetch + validation cycle with
            exponential backoff (multiplier 1.5x) to let convergence settle
            before failing a transient. Set to 0 for single-shot behavior.
        rib_fib_precheck_retry_delay_seconds: Base delay in seconds before the
            first retry (default 30). Subsequent delays grow by 1.5x:
            30s, 45s, 67.5s, 101s, 152s (re-checks at ~30/75/142/244/396s).
        skip_rib_fib_precheck: Opt-out hatch for the RIB-FIB consistency
            precheck. Default False (precheck always runs). Set True only for
            chained-playbook scenarios that legitimately accept drift carried
            over from a prior playbook.
        rib_fib_record_heal_latency: Opt in to the post-verdict heal-latency
            probe on RIB-FIB precheck FAIL (paste P2390924278). Default
            **True** for all EBB conveyor configs so a precheck FAIL is
            self-classifying — healed-within-Xs (transient, recovery
            race carried over from a prior playbook / setup) vs
            did-not-heal-within (persistent — the real bug). Probe is
            diagnostic-only; never alters PASS/FAIL.
        rib_fib_heal_latency_max_sec: Probe cap for the precheck
            (default 480s, covers observed ~430s cold-boot heal).
        rib_fib_heal_latency_poll_sec: Probe poll interval (default 10s).

    Returns:
        List of standard precheck health checks
    """
    if precheck_thresholds is None:
        precheck_thresholds = get_precheck_thresholds()

    bgp_mon_ignore = (
        [f"{IXIA_BGP_MON_IC_PARENT_NETWORK}::/80"] if exclude_bgp_mon else None
    )

    prechecks = [
        # Pre-condition 1: Verify no established BGP sessions between DUT and traffic generators
        create_bgp_session_establish_check(
            expected_established_sessions_static=expected_established_sessions,
            parent_prefixes_to_ignore=bgp_mon_ignore,
            check_id="startup_bgp_session_verification",
            retry_count=bgp_session_retry_count,
            retry_delay_seconds=bgp_session_retry_delay_seconds,
        ),
        # Pre-condition 2: Confirm CPU load-average is stable and within baseline levels
        create_system_cpu_load_average_check(
            baseline=cpu_baseline,
            check_id="startup_cpu_load_average_baseline",
        ),
        # Pre-condition 3: Make sure that GR is not enabled on iBGP-mesh (IPv6)
        create_bgp_graceful_restart_check(
            peer_group_name=peergroup_ibgp_v6,
            expected_graceful_restart_enabled=False,
            check_id="startup_bgp_graceful_restart_disabled_check_v6",
        ),
        # Pre-condition 3: Make sure that GR is not enabled on iBGP-mesh (IPv4)
        create_bgp_graceful_restart_check(
            peer_group_name=peergroup_ibgp_v4,
            expected_graceful_restart_enabled=False,
            check_id="startup_bgp_graceful_restart_disabled_check_v4",
        ),
        # Pre-condition 4: Collect H/W utilisation and verify thresholds
        create_hardware_capacity_check(
            fec_threshold=precheck_thresholds.fec_threshold,
            ecmp_threshold=precheck_thresholds.ecmp_threshold,
            max_ecmp_level1=precheck_thresholds.max_ecmp_level1,
            max_ecmp_level2=precheck_thresholds.max_ecmp_level2,
            max_ecmp_level3=precheck_thresholds.max_ecmp_level3,
            watermark_delta_threshold=precheck_thresholds.watermark_delta_threshold,
            check_watermarks=precheck_thresholds.check_watermarks,
            check_id="startup_hardware_capacity_baseline",
        ),
    ]

    # Pre-condition 5: BGP++ initialization-events convergence — assert the
    # device reached INITIALIZED within the threshold. Self-waits up to the
    # threshold for post-restart convergence.
    #
    # The strict canonical-sequence and EOR-timer-expiry assertions are
    # TEMPORARILY relaxed (fail_on_eor_expired/validate_sequence=False): on a
    # cold start the EOR timer is started prematurely at PeerManager startup
    # (rather than on first session up), so it always expires before all peers'
    # EoRs arrive — emitting EOR_TIMER_EXPIRED plus an out-of-order late
    # ALL_EOR_RECEIVED. Re-enable both once the BGP++ EOR-timer fix lands.
    if check_bgp_convergence:
        prechecks.append(
            create_bgp_convergence_check(
                convergence_threshold=_BGP_CONVERGENCE_THRESHOLD_SECONDS,
                fail_on_eor_expired=False,
                validate_sequence=False,
                check_id="startup_bgp_convergence",
            )
        )

    # Conditionally add iBGP PNH check only for Open/R profiles
    if check_ibgp_pnh:
        prechecks.append(
            create_ibgp_pnh_metric_check(
                expected_openr_metric=10,
                expected_openr_ad=10,
                check_id="startup_ibgp_pnh_verification",
            )
        )

    if rp_file_path is not None:
        prechecks.append(
            create_file_exists_check(
                file_path=rp_file_path,
                check_id="startup_rp_file_exists",
            )
        )

    # Pre-condition 5: RIB-FIB consistency baseline.
    # Detects drift carried over from prior playbook OR from test-setup
    # (the T274256815 setup-time NH-race per RFC P2381158727). The precheck
    # runs right after setup (incl. BGP daemon restart / cold start) where
    # RIB->FIB is still converging (~117.8s observed on a daemon restart),
    # so it retries with exponential backoff to let convergence settle
    # rather than failing a transient recovery race.
    # A FAIL after that budget pins the drift to setup OR a prior playbook;
    # a PASS here followed by a POSTCHECK FAIL pins drift to this
    # playbook's workload. That attribution is the diagnostic value.
    if not skip_rib_fib_precheck:
        prechecks.append(
            create_bgp_rib_fib_consistency_check(
                check_id="rib_fib_consistency_precheck",
                extra_json_params=rib_fib_precheck_json_params,
                retry_count=rib_fib_precheck_retry_count,
                retry_delay_seconds=rib_fib_precheck_retry_delay_seconds,
                record_heal_latency=rib_fib_record_heal_latency,
                heal_latency_max_sec=rib_fib_heal_latency_max_sec,
                heal_latency_poll_sec=rib_fib_heal_latency_poll_sec,
            )
        )

    return prechecks


def create_standard_postchecks(
    postcheck_thresholds=None,
    convergence_threshold: int = _BGP_CONVERGENCE_THRESHOLD_SECONDS,
    services_to_check: list[str] | None = None,
    daemons_to_check: list[str] | None = None,
    expected_message_types: list[str] | None = None,
    unexpected_message_types: list[str] | None = None,
    check_bgp_convergence: bool = True,
    fail_on_eor_expired: bool = True,
    expected_restarted_services: list[str] | None = None,
    restart_start_time_jq_var: str | None = None,
    expected_established_session_count: int | None = None,
    rib_fib_json_params: dict | None = None,
    bgp_session_retry_count: int = _BGP_SESSION_RETRY_COUNT,
    bgp_session_retry_delay_seconds: float = _BGP_SESSION_RETRY_DELAY_SECONDS,
    rib_fib_retry_count: int = _RIB_FIB_RETRY_COUNT,
    rib_fib_retry_delay_seconds: float = _RIB_FIB_RETRY_DELAY_SECONDS,
    exclude_bgp_mon: bool = True,
    rib_fib_record_heal_latency: bool = True,
    rib_fib_heal_latency_max_sec: int = _RIB_FIB_HEAL_LATENCY_MAX_SEC,
    rib_fib_heal_latency_poll_sec: int = _RIB_FIB_HEAL_LATENCY_POLL_SEC,
) -> list[PointInTimeHealthCheck]:
    """
    Create standard postchecks for BGP tests.

    Args:
        postcheck_thresholds: Hardware capacity thresholds (optional)
        convergence_threshold: BGP convergence time threshold in seconds
        services_to_check: List of EOS Sand agents to check via 'show agent uptime'
            (optional, defaults to ["Bgp", "FibAgent", "FibAgentBgp"])
        daemons_to_check: List of EOS daemons to check via 'show daemon'. Daemons
            are distinct from Sand agents and must be checked with a different EOS
            command. (optional, defaults to ["FibBgpGrpc"])
        expected_message_types: Expected BGP message types for tcpdump check (optional)
        unexpected_message_types: Unexpected BGP message types for tcpdump check (optional)
        check_bgp_convergence: Enable BGP convergence check (default: True)
        expected_restarted_services: List of services that were intentionally restarted
            during the test. For these services, the restart check compares uptime
            against restart_start_time (when the restart completed) instead of the full
            test duration to detect silent crashes after the intentional restart.
            Requires restart_start_time_jq_var to be set. (optional)
        restart_start_time_jq_var: jq variable name (e.g., "daemon_restart_time") that
            holds the unix timestamp of when the intentional restart completed. This
            should be recorded via a record_jq_timestamp custom step right after the
            daemon enable step. Required when expected_restarted_services is set.
        expected_established_session_count: Expected number of established BGP sessions.
            When set, the BGP_SESSION_ESTABLISH_CHECK uses this count instead of
            requiring all sessions to be established. Useful for devices where some
            sessions (e.g. BGP MON) remain IDLE. (optional)
        rib_fib_json_params: Optional dict of extra json_params for the RIB-FIB
            consistency check (e.g., {"debug_route_attributes": True}).
        bgp_session_retry_count: Number of retries for the BGP session
            establish check on FAIL (default 3). Retries the full
            data-fetch + validation cycle with exponential backoff
            (multiplier 1.5x). Set to 0 for single-shot behavior.
        bgp_session_retry_delay_seconds: Base delay in seconds before the
            first retry (default 10.0). Subsequent delays grow by 1.5x:
            10s, 15s, 22.5s.
        rib_fib_retry_count: Number of retries for the RIB-FIB consistency
            check on FAIL (default 5). Handles transient mismatches during
            FIB convergence after route churn (~117.8s observed), retrying
            the full cycle with exponential backoff (multiplier 1.5x).
        rib_fib_retry_delay_seconds: Base delay in seconds before the
            first retry (default 30.0). Subsequent delays grow by 1.5x:
            30s, 45s, 67.5s, 101s, 152s (re-checks at ~30/75/142/244/396s).
        exclude_bgp_mon: When True, exclude BGP_MON peers from session
            establish checks via ``parent_prefixes_to_ignore``, and skip the
            BGP_TCPDUMP_CHECK (tcpdump captures on ``interface: any``
            which includes BGP_MON traffic that cannot be filtered by
            peer address in the grep-based analyzer).
        rib_fib_record_heal_latency: Opt in to the post-verdict heal-latency
            probe on RIB-FIB postcheck FAIL (paste P2390924278). Default
            **True** for all EBB conveyor configs so a postcheck FAIL is
            self-classifying — healed-within-Xs (transient, recovery
            race after this playbook's workload) vs did-not-heal-within
            (persistent — the real bug). Probe is diagnostic-only;
            never alters PASS/FAIL.
        rib_fib_heal_latency_max_sec: Probe cap for the postcheck
            (default 480s, covers observed ~430s cold-boot heal).
        rib_fib_heal_latency_poll_sec: Probe poll interval (default 10s).

    Returns:
        List of standard postcheck health checks
    """
    if postcheck_thresholds is None:
        postcheck_thresholds = get_postcheck_thresholds()

    if services_to_check is None:
        services_to_check = ["Bgp", "FibAgent", "FibAgentBgp"]

    if daemons_to_check is None:
        daemons_to_check = ["FibBgpGrpc"]

    bgp_mon_ignore = (
        [f"{IXIA_BGP_MON_IC_PARENT_NETWORK}::/80"] if exclude_bgp_mon else None
    )

    postchecks: list[PointInTimeHealthCheck] = []

    # Conditionally add BGP convergence check. validate_sequence is temporarily
    # disabled: cold start / restart can emit an out-of-order late
    # ALL_EOR_RECEIVED once the prematurely-started EOR timer expires. Re-enable
    # once the BGP++ EOR-timer fix lands.
    if check_bgp_convergence:
        postchecks.append(
            create_bgp_convergence_check(
                convergence_threshold=convergence_threshold,
                fail_on_eor_expired=fail_on_eor_expired,
                validate_sequence=False,
                check_id="postcheck_bgp_convergence_time",
            )
        )

    # Run BGP session health check to verify all sessions are established
    if expected_established_session_count is not None:
        bgp_session_check = create_bgp_session_establish_check(
            expected_established_sessions=expected_established_session_count,
            parent_prefixes_to_ignore=bgp_mon_ignore,
            retry_count=bgp_session_retry_count,
            retry_delay_seconds=bgp_session_retry_delay_seconds,
        )
    else:
        bgp_session_check = create_bgp_session_establish_check(
            parent_prefixes_to_ignore=bgp_mon_ignore,
            retry_count=bgp_session_retry_count,
            retry_delay_seconds=bgp_session_retry_delay_seconds,
        )

    postchecks.extend(
        [
            bgp_session_check,
            # Run BGP Stale Route Check
            create_bgp_stale_route_check(),
            # System-level log parsing check
            create_log_parsing_check(
                json_params={
                    "agent_name": "Bgp",
                    "exclude_regex": "Memory Limit Reached",
                },
                start_time_jq_var="test_case_start_time",
                end_time_jq_var="test_case_end_time",
                check_id="system_level_log_check",
            ),
            # BGP time-bound log check
            create_log_parsing_check(
                json_params={"check_system_logs": True},
                start_time_jq_var="test_case_start_time",
                end_time_jq_var="test_case_end_time",
                check_id="bgp_time_bound_check",
            ),
            # RIB-FIB consistency check
            create_bgp_rib_fib_consistency_check(
                check_id="rib_fib_consistency_postcheck",
                extra_json_params=rib_fib_json_params,
                retry_count=rib_fib_retry_count,
                retry_delay_seconds=rib_fib_retry_delay_seconds,
                record_heal_latency=rib_fib_record_heal_latency,
                heal_latency_max_sec=rib_fib_heal_latency_max_sec,
                heal_latency_poll_sec=rib_fib_heal_latency_poll_sec,
            ),
            # Service restart check
            create_service_restart_check(
                services=services_to_check,
                daemons=daemons_to_check,
                expected_restarted_services=expected_restarted_services,
                restart_start_time_jq_var=restart_start_time_jq_var,
            ),
        ]
    )

    if expected_message_types is not None and unexpected_message_types is not None:
        # TCP Dump check
        postchecks.append(
            create_bgp_tcpdump_check(
                expected_message_types=expected_message_types,
                unexpected_message_types=unexpected_message_types,
            )
        )

    return postchecks


def create_standard_snapshot_checks(
    skip_flap_check: bool = False,
    skip_uptime_check: bool = False,
    pre_snapshot_checkpoint_id: str | None = None,
    post_snapshot_checkpoint_id: str | None = None,
    expected_peer_identity: dict[str, str] | None = None,
    parent_prefixes_to_ignore: list[str] | None = None,
    exclude_bgp_mon: bool = True,
) -> list[SnapshotHealthCheck]:
    """
    Create standard snapshot checks for BGP tests.

    Args:
        skip_flap_check: Skip BGP session flap detection (default: False)
        skip_uptime_check: Skip BGP session uptime validation (default: False)
        pre_snapshot_checkpoint_id: Custom checkpoint ID for pre-snapshot (default: "test_case_start")
        post_snapshot_checkpoint_id: Custom checkpoint ID for post-snapshot (default: "test_case_end")
        expected_peer_identity: Optional {peer_addr: local_addr} mapping for
            peer identity validation, as returned by get_common_setup_tasks
            or get_update_packing_setup_tasks.
        parent_prefixes_to_ignore: Optional list of CIDR prefixes to ignore in
            BGP session snapshot checks (e.g. ["10.171.28.0/24"] to skip iBGP MP Plane 4 IPv4 peers)
        exclude_bgp_mon: When True, exclude BGP_MON peers from snapshot
            checks via ``parent_prefixes_to_ignore``. BGP_MON IXIA peers
            flap frequently and cause false snapshot check failures.

    Returns:
        List of standard snapshot health checks
    """
    all_prefixes_to_ignore = list(parent_prefixes_to_ignore or [])
    if exclude_bgp_mon:
        all_prefixes_to_ignore.append(f"{IXIA_BGP_MON_IC_PARENT_NETWORK}::/80")

    return [
        create_core_dumps_snapshot_check(),
        create_bgp_session_snapshot_check(
            parent_prefixes_to_ignore=all_prefixes_to_ignore or None,
            skip_flap_check=skip_flap_check,
            skip_uptime_check=skip_uptime_check,
            expected_peer_identity=expected_peer_identity,
            pre_snapshot_checkpoint_id=pre_snapshot_checkpoint_id,
            post_snapshot_checkpoint_id=post_snapshot_checkpoint_id,
        ),
    ]
