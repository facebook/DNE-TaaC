# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""Canonical health check factory functions.

Every PointInTimeHealthCheck / SnapshotHealthCheck construction in TAAC
should use a factory from this module.  Gate test
``test_no_inline_healthcheck_construction`` enforces this.

Migration: as inline HC construction in test configs is replaced, the
corresponding factory is added here and the old call site is removed
from the gate-test allowlist.
"""

import json
import typing as t

from taac.utils.json_thrift_utils import thrift_to_json
from taac.health_check.health_check import types as hc_types
from taac.test_as_a_config.types import (
    Params,
    ParamValue,
    PointInTimeHealthCheck,
    SnapshotHealthCheck,
)

_PV = ParamValue


def create_bare_health_check(check_name: hc_types.CheckName) -> PointInTimeHealthCheck:
    """Wrap a CheckName as a bare PointInTimeHealthCheck (no params).

    Adapter for runtime call sites that have a `CheckName` enum value but no
    static knowledge of which dedicated factory applies. Static call sites
    should prefer the per-CheckName factory below (e.g.
    `create_bgp_session_establish_check`).
    """
    return PointInTimeHealthCheck(name=check_name)


def create_device_core_dumps_check(
    core_dumps_to_ignore: t.Optional[t.List[str]] = None,
    use_start_time: bool = True,
) -> PointInTimeHealthCheck:
    """DEVICE_CORE_DUMPS_CHECK — detects new device core dumps.

    Args:
        core_dumps_to_ignore: Process names whose core dumps should NOT cause
            the check to fail (e.g. ``["bgpd_main"]`` for force-kill tests).
        use_start_time: When True (default), scopes the check to dumps after
            ``.test_case_start_time``. Set False for the bare variant (no
            check_params).
    """
    if not use_start_time and core_dumps_to_ignore is None:
        return PointInTimeHealthCheck(name=hc_types.CheckName.DEVICE_CORE_DUMPS_CHECK)
    json_payload: t.Dict[str, t.Any] = {}
    if core_dumps_to_ignore is not None:
        json_payload["core_dumps_to_ignore"] = core_dumps_to_ignore
    return PointInTimeHealthCheck(
        name=hc_types.CheckName.DEVICE_CORE_DUMPS_CHECK,
        check_params=Params(
            json_params=json.dumps(json_payload),
            jq_params=(
                {
                    "start_time": ".test_case_start_time",
                }
                if use_start_time
                else None
            ),
        ),
    )


def create_bgp_session_establish_check(
    ignore_all_prefixes_except: t.Optional[t.List[str]] = None,
    parent_prefixes_to_ignore: t.Optional[t.List[str]] = None,
    expected_established_sessions: t.Optional[int] = None,
    expected_established_sessions_static: t.Optional[int] = None,
    min_established_pct: t.Optional[float] = None,
    max_session_uptime_sec: t.Optional[float] = None,
    verbose: bool = False,
    check_id: t.Optional[str] = None,
    check_scope: t.Optional["hc_types.Scope"] = None,
    retry_count: t.Optional[int] = None,
    retry_delay_seconds: t.Optional[float] = None,
    retry_delay_multiplier: t.Optional[float] = None,
) -> PointInTimeHealthCheck:
    """BGP_SESSION_ESTABLISH_CHECK — verifies BGP sessions reach Established.

    Args:
        ignore_all_prefixes_except: When set, only sessions for these peer
            addresses are checked.
        expected_established_sessions: When set, asserts the exact number of
            sessions that should be in Established state (json_params variant).
        expected_established_sessions_static: Same assertion via the
            `static_params` ParamValue variant (used by EBB). Mutually
            exclusive with `expected_established_sessions`.
        min_established_pct: Minimum fraction of sessions that must be
            Established (0.0–1.0). E.g. 0.5 = at least 50% must be up.
            When set, overrides the default all-or-nothing behavior.
        max_session_uptime_sec: When set, additionally validates that at
            least one established session has ``uptime <= max_session_uptime_sec``,
            confirming sessions came up recently after a process restart.
            Use as a postcheck for BGP/agent restart test cases.
        verbose: Pass ``verbose=True`` through to the check for richer logs.
        retry_count: Number of retries after the initial attempt when the
            check returns FAIL.  0 (default) = single-shot, no retry.
            The retry wraps the **full** data-fetch + validation cycle in
            ``AbstractPointInTimeHealthCheck.run()``, so each attempt
            re-fetches live data from the device.
        retry_delay_seconds: Base delay in seconds before the first retry
            (default 5.0).  Subsequent delays grow by
            ``retry_delay_multiplier`` each attempt:
            ``delay(n) = retry_delay_seconds * retry_delay_multiplier ** n``.
        retry_delay_multiplier: Exponential backoff multiplier applied to
            the delay after each retry (default 1.5).
            1.0 = constant delay, 1.5 = 50 % longer each retry,
            2.0 = double each retry.
    """
    if (
        expected_established_sessions is not None
        and expected_established_sessions_static is not None
    ):
        raise ValueError(
            "expected_established_sessions and expected_established_sessions_static "
            "are mutually exclusive — pass exactly one."
        )
    json_payload: t.Dict[str, t.Any] = {}
    if ignore_all_prefixes_except is not None:
        json_payload["ignore_all_prefixes_except"] = ignore_all_prefixes_except
    if expected_established_sessions is not None:
        # JSON key is `expected_established_session_count` to match the
        # underlying check implementation; the Python kwarg name uses the
        # idiomatic plural for ergonomics. Placed before `parent_prefixes_to_ignore`
        # to preserve byte-equivalence with prior inline constructions.
        json_payload["expected_established_session_count"] = (
            expected_established_sessions
        )
    if parent_prefixes_to_ignore is not None:
        json_payload["parent_prefixes_to_ignore"] = parent_prefixes_to_ignore
    if min_established_pct is not None:
        json_payload["min_established_pct"] = min_established_pct
    if max_session_uptime_sec is not None:
        json_payload["max_session_uptime_sec"] = max_session_uptime_sec
    if verbose:
        json_payload["verbose"] = True
    if retry_count is not None:
        json_payload["retry_count"] = retry_count
    if retry_delay_seconds is not None:
        json_payload["retry_delay_seconds"] = retry_delay_seconds
    if retry_delay_multiplier is not None:
        json_payload["retry_delay_multiplier"] = retry_delay_multiplier
    static_params = None
    if expected_established_sessions_static is not None:
        # `static_params` is the ParamValue-typed variant (used by EBB)
        static_params = {
            "expected_established_session_count": _PV(
                int_value=expected_established_sessions_static,
            ),
        }
    # Emit check_params=None when no payload to match the inline-construction
    # serialized output (PointInTimeHealthCheck(name=...) → check_params=None).
    check_params = None
    if json_payload or static_params:
        check_params = Params(
            json_params=json.dumps(json_payload) if json_payload else None,
            static_params=static_params,
        )
    return PointInTimeHealthCheck(
        name=hc_types.CheckName.BGP_SESSION_ESTABLISH_CHECK,
        check_params=check_params,
        check_id=check_id,
        check_scope=check_scope,
    )


def create_bgp_rib_fib_consistency_check(
    extra_json_params: t.Optional[t.Dict[str, t.Any]] = None,
    check_id: t.Optional[str] = None,
    retry_count: t.Optional[int] = None,
    retry_delay_seconds: t.Optional[float] = None,
    retry_delay_multiplier: t.Optional[float] = None,
) -> PointInTimeHealthCheck:
    """Create a point-in-time check that the BGP RIB matches the device FIB.

    Walks the BGP best-path RIB and asserts every selected prefix has a
    corresponding FIB entry (and vice versa). Used as a postcheck after
    convergence-affecting events (warmboot, BGP restart, churn stages,
    rogue-prefix injection) to catch RIB-vs-FIB drift.

    Args:
        extra_json_params: Opaque pass-through dict merged into the check's
            json_params (e.g. ``{"parent_prefixes_to_ignore": [...]}`` to
            skip rogue-injection parent prefixes that legitimately diverge).
        check_id: Optional unique identifier for the check (used by the
            framework for downstream lookup / scoping).
        retry_count: Number of retries after the initial attempt when the
            check returns FAIL.  0 (default) = single-shot, no retry.
            The retry wraps the **full** data-fetch + validation cycle in
            ``AbstractPointInTimeHealthCheck.run()``, so each attempt
            re-fetches live data from the device.
        retry_delay_seconds: Base delay in seconds before the first retry
            (default 5.0).  Subsequent delays grow by
            ``retry_delay_multiplier`` each attempt:
            ``delay(n) = retry_delay_seconds * retry_delay_multiplier ** n``.
        retry_delay_multiplier: Exponential backoff multiplier applied to
            the delay after each retry (default 1.5).
            1.0 = constant delay, 1.5 = 50 % longer each retry,
            2.0 = double each retry.

    Returns:
        A `PointInTimeHealthCheck` with `name=BGP_RIB_FIB_CONSISTENCY_CHECK`.
    """
    json_payload: t.Dict[str, t.Any] = {}
    if extra_json_params is not None:
        json_payload.update(extra_json_params)
    if retry_count is not None:
        json_payload["retry_count"] = retry_count
    if retry_delay_seconds is not None:
        json_payload["retry_delay_seconds"] = retry_delay_seconds
    if retry_delay_multiplier is not None:
        json_payload["retry_delay_multiplier"] = retry_delay_multiplier

    check_params = None
    if json_payload:
        check_params = Params(json_params=json.dumps(json_payload))
    return PointInTimeHealthCheck(
        name=hc_types.CheckName.BGP_RIB_FIB_CONSISTENCY_CHECK,
        check_params=check_params,
        check_id=check_id,
    )


def create_bgp_convergence_check(
    convergence_threshold: t.Optional[int] = None,
    fail_on_eor_expired: t.Optional[bool] = None,
    extra_json_params: t.Optional[t.Dict[str, t.Any]] = None,
    check_id: t.Optional[str] = None,
) -> PointInTimeHealthCheck:
    """BGP_CONVERGENCE_CHECK — verifies BGP convergence.

    With no kwargs, emits a bare check (no check_params). When kwargs are
    provided, only the explicitly-set keys are included in the JSON payload —
    preserving inline-construction byte equivalence at sites that omit them.
    `extra_json_params` covers custom variants (e.g. ``{"start_event": "3",
    "end_event": "4"}``) and is merged after the named kwargs.
    """
    json_payload: t.Dict[str, t.Any] = {}
    if convergence_threshold is not None:
        json_payload["convergence_threshold"] = convergence_threshold
    if fail_on_eor_expired is not None:
        json_payload["fail_on_eor_expired"] = fail_on_eor_expired
    if extra_json_params is not None:
        json_payload.update(extra_json_params)
    if not json_payload and check_id is None:
        return PointInTimeHealthCheck(name=hc_types.CheckName.BGP_CONVERGENCE_CHECK)
    return PointInTimeHealthCheck(
        name=hc_types.CheckName.BGP_CONVERGENCE_CHECK,
        check_params=(
            Params(json_params=json.dumps(json_payload)) if json_payload else None
        ),
        check_id=check_id,
    )


def create_ixia_packet_loss_check_traffic_split(
    device_name: str,
    expect_loss_traffic: t.List[str],
    no_loss_traffic: t.List[str],
    no_loss_threshold: str = "0.1",
) -> PointInTimeHealthCheck:
    """IXIA_PACKET_LOSS_CHECK — split-threshold variant.

    Builds a thrift-input check that asserts packet loss is **expected** for
    one set of traffic items and **not exceeded** beyond ``no_loss_threshold``
    for another set. Traffic-item names are formed as
    ``f"{device_name.upper()}_{traffic}"``.
    """
    return PointInTimeHealthCheck(
        name=hc_types.CheckName.IXIA_PACKET_LOSS_CHECK,
        input_json=thrift_to_json(
            hc_types.IxiaPacketLossHealthCheckIn(
                thresholds=[
                    hc_types.PacketLossThreshold(
                        names=[
                            f"{device_name.upper()}_{traffic}"
                            for traffic in expect_loss_traffic
                        ],
                        expect_packet_loss=True,
                    ),
                    hc_types.PacketLossThreshold(
                        names=[
                            f"{device_name.upper()}_{traffic}"
                            for traffic in no_loss_traffic
                        ],
                        str_value=no_loss_threshold,
                        expect_packet_loss=False,
                    ),
                ]
            )
        ),
    )


def create_ixia_packet_loss_check(
    thresholds: t.Optional[t.List["hc_types.PacketLossThreshold"]] = None,
    clear_traffic_stats: bool = False,
    priority: t.Optional[int] = None,
    json_params: t.Optional[t.Dict[str, t.Any]] = None,
) -> PointInTimeHealthCheck:
    """IXIA_PACKET_LOSS_CHECK — generic thrift-input variant.

    Caller supplies a fully-built list of `PacketLossThreshold` values, giving
    full control over threshold metric, expect_packet_loss, str_value,
    namespace patterns, etc. For the common split-threshold pattern (one set
    expects loss, another set expects no loss) prefer
    `create_ixia_packet_loss_check_traffic_split`. Pass `clear_traffic_stats=True`
    with `thresholds=None` for the post-reboot stats-clear-only variant.
    `priority` controls the check's run priority (higher = runs first).
    `json_params` selects the legacy untyped check_params.json_params variant
    (e.g. `{"expect_loss": True}`).
    """
    if json_params is not None:
        return PointInTimeHealthCheck(
            name=hc_types.CheckName.IXIA_PACKET_LOSS_CHECK,
            check_params=Params(json_params=json.dumps(json_params)),
            priority=priority,
        )
    return PointInTimeHealthCheck(
        name=hc_types.CheckName.IXIA_PACKET_LOSS_CHECK,
        input_json=thrift_to_json(
            hc_types.IxiaPacketLossHealthCheckIn(
                thresholds=thresholds or [],
                clear_traffic_stats=clear_traffic_stats,
            )
        ),
        priority=priority,
    )


def create_core_dumps_snapshot_check() -> SnapshotHealthCheck:
    """Create a snapshot check that no new core dumps appeared during the playbook.

    Captures the set of core dump files at the pre-snapshot checkpoint and
    fails if any new dumps appear at the post-snapshot checkpoint. Used as a
    blanket guard around disruptive stages (warmboot, BGP restart, service
    churn) to catch unexpected daemon crashes.

    Returns:
        A bare `SnapshotHealthCheck` with `name=CORE_DUMPS_CHECK` (no params).
    """
    return SnapshotHealthCheck(name=hc_types.CheckName.CORE_DUMPS_CHECK)


def _build_threshold_check(
    check_name: hc_types.CheckName,
    threshold: t.Optional[t.Union[int, float]] = None,
    threshold_by_service: t.Optional[t.Dict[str, t.Union[int, float]]] = None,
    start_time_jq_var: t.Optional[str] = None,
    delta: t.Optional[float] = None,
    check_scope: t.Optional["hc_types.Scope"] = None,
) -> PointInTimeHealthCheck:
    """Internal helper: build a CPU/memory-style threshold-based PointInTimeHealthCheck.

    Used by ``create_cpu_utilization_check`` + ``create_memory_utilization_check``
    which differ only in the CheckName enum value.
    """
    json_payload: t.Dict[str, t.Any] = {}
    if threshold is not None:
        json_payload["threshold"] = threshold
    if threshold_by_service is not None:
        json_payload["threshold_by_service"] = threshold_by_service
    if delta is not None:
        json_payload["delta"] = delta
    jq_params = {"start_time": f".{start_time_jq_var}"} if start_time_jq_var else None
    if not json_payload and not jq_params:
        return PointInTimeHealthCheck(name=check_name, check_scope=check_scope)
    return PointInTimeHealthCheck(
        name=check_name,
        check_params=Params(
            json_params=json.dumps(json_payload),
            jq_params=jq_params,
        ),
        check_scope=check_scope,
    )


def create_cpu_utilization_check(
    threshold: t.Optional[float] = None,
    threshold_by_service: t.Optional[t.Dict[str, float]] = None,
    start_time_jq_var: t.Optional[str] = None,
    check_scope: t.Optional["hc_types.Scope"] = None,
) -> PointInTimeHealthCheck:
    """CPU_UTILIZATION_CHECK — verifies CPU utilization stays below thresholds.

    Args:
        threshold: Default CPU% ceiling for any process. When None, no
            threshold key is emitted (bare check).
        threshold_by_service: Per-process overrides (e.g. ``{"bgpd": 100.0}``).
        start_time_jq_var: When set, evaluates the lookback window from this
            jq variable name (typically ``"test_case_start_time"``).
        check_scope: Optional scope override (e.g. ``Scope.DEFAULT`` to run on
            the DUT only).
    """
    return _build_threshold_check(
        hc_types.CheckName.CPU_UTILIZATION_CHECK,
        threshold,
        threshold_by_service,
        start_time_jq_var,
        check_scope=check_scope,
    )


def create_memory_utilization_check(
    threshold: t.Optional[t.Union[int, float]] = None,
    threshold_by_service: t.Optional[t.Dict[str, t.Union[int, float]]] = None,
    start_time_jq_var: t.Optional[str] = None,
    delta: t.Optional[t.Union[int, float]] = None,
    check_scope: t.Optional["hc_types.Scope"] = None,
) -> PointInTimeHealthCheck:
    """MEMORY_UTILIZATION_CHECK — verifies memory usage stays below thresholds.

    Args:
        threshold: Default per-process memory ceiling (bytes) (FBOSS/ODS path).
        threshold_by_service: Per-process overrides (bytes).
        start_time_jq_var: When set, evaluates the lookback window from this
            jq variable name (typically ``"test_case_start_time"``).
        delta: Max allowed memory-counter delta between samples on Arista
            devices. When omitted, the Arista path is skipped.
        check_scope: Optional scope override (e.g. ``Scope.DEFAULT`` to run on
            the DUT only).
    """
    return _build_threshold_check(
        hc_types.CheckName.MEMORY_UTILIZATION_CHECK,
        threshold,
        threshold_by_service,
        start_time_jq_var,
        check_scope=check_scope,
    )


def create_port_speed_check(
    json_params: t.Dict[str, t.Any],
) -> PointInTimeHealthCheck:
    """PORT_SPEED_CHECK — opaque pass-through with caller-supplied json_params.

    The PORT_SPEED_CHECK schema varies considerably across testconfigs; rather
    than re-create every shape as a kwarg, this factory takes the dict the
    caller would have built anyway and performs only the wrapping.
    """
    return PointInTimeHealthCheck(
        name=hc_types.CheckName.PORT_SPEED_CHECK,
        check_params=Params(json_params=json.dumps(json_params)),
    )


def create_ecmp_group_and_member_count_check(
    ecmp_member_count: t.Optional[int] = None,
    ecmp_group_count: t.Optional[int] = None,
) -> PointInTimeHealthCheck:
    """ECMP_GROUP_AND_MEMBER_COUNT_CHECK — verifies ECMP group + member counts.

    Args:
        ecmp_member_count: Maximum allowed ECMP member count.
        ecmp_group_count: Maximum allowed ECMP group count.
    """
    json_payload: t.Dict[str, t.Any] = {}
    if ecmp_member_count is not None:
        json_payload["ecmp_member_count"] = ecmp_member_count
    if ecmp_group_count is not None:
        json_payload["ecmp_group_count"] = ecmp_group_count
    return PointInTimeHealthCheck(
        name=hc_types.CheckName.ECMP_GROUP_AND_MEMBER_COUNT_CHECK,
        check_params=Params(json_params=json.dumps(json_payload)),
    )


def create_log_parsing_check(
    json_params: t.Optional[t.Dict[str, t.Any]] = None,
    start_time_jq_var: t.Optional[str] = None,
    end_time_jq_var: t.Optional[str] = None,
    check_id: t.Optional[str] = None,
) -> PointInTimeHealthCheck:
    """LOG_PARSING_CHECK — read any file on the DUT and PASS/FAIL on a regex.

    Despite the name, this check is a generic per-line regex matcher against any
    on-device file path — not specifically /var/facebook/logs/. Common uses
    include log greps (with optional start/end time filtering for FBOSS log
    timestamps) and config-file flag verification.

    `json_params` accepts (all keys optional except `log_file_path`):
      - `log_file_path` (required): absolute path on the DUT
      - `include_regex` XOR `exclude_regex`: pass exactly one. include → PASS
        when at least one line matches; exclude → PASS when no line matches.
        Pattern is passed to Python `re.search` per-line (not anchored).
      - `start_time` / `end_time`: optional Unix-ts window used to construct an
        FBOSS-log timestamp prefilter (`grep "Mon DD HH:MM"`) before regex
        matching. Omit for non-log files (e.g. config under /etc/).

    Bare by default (no kwargs). When `json_params` and/or jq vars are provided,
    builds the corresponding `Params` object.

    Example — assert TunManager flag is enabled on the FBOSS coop config (JSON):

        create_log_parsing_check(
            json_params={
                "log_file_path": "/etc/coop/agent/current",
                "include_regex": r'"cleanup_probed_kernel_data":\\s*"true"',
            },
        )
    """
    if json_params is None and not start_time_jq_var and not end_time_jq_var:
        return PointInTimeHealthCheck(
            name=hc_types.CheckName.LOG_PARSING_CHECK,
            check_id=check_id,
        )
    jq: t.Dict[str, str] = {}
    if start_time_jq_var:
        jq["start_time"] = f".{start_time_jq_var}"
    if end_time_jq_var:
        jq["end_time"] = f".{end_time_jq_var}"
    return PointInTimeHealthCheck(
        name=hc_types.CheckName.LOG_PARSING_CHECK,
        check_params=Params(
            jq_params=jq if jq else None,
            json_params=json.dumps(json_params) if json_params else None,
        ),
        check_id=check_id,
    )


def create_tm_reconciliation_firing_check(
    expected_to_fire: bool = False,
    require_both_signals: bool = False,
    log_file_path: str = "/var/facebook/logs/fboss/wedge_agent.log",
    firing_pattern: str = "Starting to delete all probed data from kernel",
    ods_key: str = "fboss.agent.probed_state_cleanup_status",
    start_time_jq_var: str = "test_case_start_time",
) -> PointInTimeHealthCheck:
    """TM_RECONCILIATION_FIRING_CHECK — composite L2-firing postcheck.

    Detects whether the `cleanup_probed_kernel_data` (TunManager L2 reconciliation)
    path executed during a test case window by reading TWO independent signals:

    1. **Log grep:** searches wedge_agent.log for ``firing_pattern`` (default is
       the canonical L2-firing log line ``TunManager.cpp:972] Starting to delete
       all probed data from kernel``), filtered to lines in
       ``[test_case_start_time, now]``.
    2. **ODS counter:** queries ``ods_key`` (default
       ``fboss.agent.probed_state_cleanup_status`` — a per-process boolean that
       transitions 0→1 when the cleanup path runs) on the device entity for
       value=1 samples in the same time window.

    The check then applies the Phase 4-1 verdict matrix (see
    `project_p41_taac_hc_design.md` §1):

    +----------------+-----------+-----------+----------------------------------+
    | expected_to_fire | log_fired | ods_fired | verdict                          |
    +================+===========+===========+==================================+
    | True           | True      | True      | PASS                             |
    | True           | True      | False     | WARN (log says fired, ODS no)    |
    | True           | False     | True      | WARN (ODS says fired, log no)    |
    | True           | False     | False     | FAIL (expected firing, none seen)|
    | False          | False     | False     | PASS                             |
    | False          | True      | True      | FAIL (unexpected firing)         |
    | False          | True      | False     | WARN                             |
    | False          | False     | True      | WARN (likely sticky ODS carryover)|
    +----------------+-----------+-----------+----------------------------------+

    When ``require_both_signals=True``, every WARN is escalated to FAIL.

    Args:
        expected_to_fire: True for cp-swap TCs (TC13, TC18, TC21) and Minipack
            pure-restart TCs (placeholder-baseline over-firing). False for RSW
            pure-restart TCs that should stay quiescent.
        require_both_signals: If True, treat any cross-signal disagreement as
            FAIL instead of WARN. Default False (tolerant of ingest lag).
        log_file_path: wedge_agent.log path on the DUT.
        firing_pattern: Regex matched per line of the log.
        ods_key: ODS counter key on the device entity (entity is the device fqdn
            minus ``.tfbnw.net``).
        start_time_jq_var: jq variable name carrying the TC start time. Defaults
            to TAAC's built-in `test_case_start_time`.
    """
    return PointInTimeHealthCheck(
        name=hc_types.CheckName.TM_RECONCILIATION_FIRING_CHECK,
        check_params=Params(
            json_params=json.dumps(
                {
                    "expected_to_fire": expected_to_fire,
                    "require_both_signals": require_both_signals,
                    "log_file_path": log_file_path,
                    "firing_pattern": firing_pattern,
                    "ods_key": ods_key,
                }
            ),
            jq_params={"start_time": f".{start_time_jq_var}"},
        ),
    )


def create_kernel_state_snapshot_check(
    expect_kernel_changes: bool = False,
    bgp_route_tolerance_pct: int = 5,
    proto80_strict: bool = True,
    ignore_ip_rule_priority: bool = True,
    pre_snapshot_checkpoint_id: t.Optional[str] = None,
    post_snapshot_checkpoint_id: t.Optional[str] = None,
) -> SnapshotHealthCheck:
    """KERNEL_STATE_SNAPSHOT_CHECK — composite kernel-state preservation HC.

    Captures kernel-side state on a FBOSS device pre and post a wedge_agent
    restart (or other potentially-disruptive action) and verifies the L2
    reconciliation path did not orphan or lose any TUN interfaces, IP
    rules/addresses, FBOSS-installed routes (proto 80), or trigger interface
    flaps. See `project_p41_taac_hc_design.md` §2 for the full verdict matrix.

    Args:
        expect_kernel_changes: False for pure-restart TCs (TC2/3, TC16/17, etc.) —
            TUN/IP rules/proto-80 must be identical. True for cp-swap / port-delete
            TCs (TC13, TC18, TC21) — TUN and proto-80 drift is reported but does
            not fail the check.
        bgp_route_tolerance_pct: Per-proto-count tolerance for non-proto-80 routes
            (absorbs normal BGP control-plane churn). Default ±5%.
        proto80_strict: When `expect_kernel_changes=False`, FAIL on any proto-80
            drift (FBOSS routes must be preserved). Set False to downgrade to WARN.
        ignore_ip_rule_priority: Strip the leading `<priority>:` prefix when
            comparing IP rules. Default True because wedge_agent re-installs the
            same rule set on restart but the kernel-auto-assigned priorities can
            shift by a small offset (e.g. 32689→32678) without changing the
            functional ordering of the rules. Set False for strict byte-equality.
    """
    return SnapshotHealthCheck(
        name=hc_types.CheckName.KERNEL_STATE_SNAPSHOT_CHECK,
        check_params=Params(
            json_params=json.dumps(
                {
                    "expect_kernel_changes": expect_kernel_changes,
                    "bgp_route_tolerance_pct": bgp_route_tolerance_pct,
                    "proto80_strict": proto80_strict,
                    "ignore_ip_rule_priority": ignore_ip_rule_priority,
                }
            ),
        ),
        pre_snapshot_checkpoint_id=pre_snapshot_checkpoint_id,
        post_snapshot_checkpoint_id=post_snapshot_checkpoint_id,
    )


def create_bgp_graceful_restart_check(
    peer_group_name: str,
    expected_graceful_restart_enabled: bool,
    check_id: t.Optional[str] = None,
) -> PointInTimeHealthCheck:
    """Create a point-in-time check of the BGP graceful-restart (GR) config on a peer group.

    Asserts the running BGP config for `peer_group_name` has GR enabled (or
    disabled) as expected. Used as a startup precheck or post-config-patch
    verification in EBB hardening tests where GR enable/disable is a key
    test variable.

    Args:
        peer_group_name: BGP peer-group name to inspect (e.g.
            ``"peergroup_ibgp_v4"``).
        expected_graceful_restart_enabled: Required GR-enabled state for the
            peer group.
        check_id: Optional unique identifier for the check.

    Returns:
        A `PointInTimeHealthCheck` with `name=BGP_GRACEFUL_RESTART_CHECK`.
    """
    return PointInTimeHealthCheck(
        name=hc_types.CheckName.BGP_GRACEFUL_RESTART_CHECK,
        check_params=Params(
            json_params=json.dumps(
                {
                    "peer_group_name": peer_group_name,
                    "expected_graceful_restart_enabled": expected_graceful_restart_enabled,
                }
            )
        ),
        check_id=check_id,
    )


def create_hardware_capacity_check(
    fec_threshold: t.Optional[t.Any] = None,
    ecmp_threshold: t.Optional[t.Any] = None,
    max_ecmp_level1: t.Optional[t.Any] = None,
    max_ecmp_level2: t.Optional[t.Any] = None,
    max_ecmp_level3: t.Optional[t.Any] = None,
    watermark_delta_threshold: t.Optional[t.Any] = None,
    check_watermarks: t.Optional[bool] = None,
    check_id: t.Optional[str] = None,
) -> PointInTimeHealthCheck:
    """Create a point-in-time check of hardware capacity (FEC + ECMP) utilization.

    Reads ASIC capacity counters from the DUT and asserts each utilization is
    below the supplied threshold. Used as a precheck/postcheck around scale
    tests (large prefix injection, ECMP-width sweeps) to catch HW exhaustion
    before it manifests as packet loss.

    Args:
        fec_threshold: Maximum allowed FEC (next-hop FEC entry) utilization.
        ecmp_threshold: Maximum allowed ECMP-group utilization.
        max_ecmp_level1: Maximum allowed level-1 (primary) ECMP-member count.
        max_ecmp_level2: Maximum allowed level-2 (hierarchical) ECMP-member count.
        max_ecmp_level3: Maximum allowed level-3 (deep hierarchical) ECMP-member count.
        watermark_delta_threshold: Maximum allowed delta between current and
            high-water-mark utilization.
        check_watermarks: If True, also asserts watermark values stayed within
            tolerance.
        check_id: Optional unique identifier for the check.

    Returns:
        A `PointInTimeHealthCheck` with `name=HARDWARE_CAPACITY_CHECK`.
    """
    payload = {
        "fec_threshold": fec_threshold,
        "ecmp_threshold": ecmp_threshold,
        "max_ecmp_level1": max_ecmp_level1,
        "max_ecmp_level2": max_ecmp_level2,
        "max_ecmp_level3": max_ecmp_level3,
        "watermark_delta_threshold": watermark_delta_threshold,
        "check_watermarks": check_watermarks,
    }
    return PointInTimeHealthCheck(
        name=hc_types.CheckName.HARDWARE_CAPACITY_CHECK,
        check_params=Params(json_params=json.dumps(payload)),
        check_id=check_id,
    )


def create_ibgp_pnh_metric_check(
    expected_openr_metric: int,
    expected_openr_ad: int,
    check_id: t.Optional[str] = None,
) -> PointInTimeHealthCheck:
    """Create a point-in-time check of iBGP protocol-next-hop (PNH) metric/AD vs Open/R.

    Asserts that the iBGP PNH route's IGP metric and administrative distance
    match the values learned from Open/R for the same destination. Used in
    EBB hardening tests to catch route-source mis-attribution after BGP/Open/R
    interaction events.

    Args:
        expected_openr_metric: Required Open/R IGP metric for the PNH route.
        expected_openr_ad: Required Open/R administrative-distance value.
        check_id: Optional unique identifier for the check.

    Returns:
        A `PointInTimeHealthCheck` with `name=IBGP_PNH_METRIC_CHECK`.
    """
    return PointInTimeHealthCheck(
        name=hc_types.CheckName.IBGP_PNH_METRIC_CHECK,
        check_params=Params(
            json_params=json.dumps(
                {
                    "expected_openr_metric": expected_openr_metric,
                    "expected_openr_ad": expected_openr_ad,
                }
            )
        ),
        check_id=check_id,
    )


def create_file_exists_check(
    file_path: str,
    check_id: t.Optional[str] = None,
) -> PointInTimeHealthCheck:
    """Create a point-in-time check that a given file path exists on the DUT.

    Used to verify side-effects of stages that produce on-device artifacts
    (e.g., warmboot state files, generated config files, capture files) or
    to assert preconditions before consumer steps run.

    Args:
        file_path: Absolute path on the DUT to check for existence.
        check_id: Optional unique identifier for the check.

    Returns:
        A `PointInTimeHealthCheck` with `name=FILE_EXISTS_HEALTH_CHECK`.
    """
    return PointInTimeHealthCheck(
        name=hc_types.CheckName.FILE_EXISTS_HEALTH_CHECK,
        check_params=Params(json_params=json.dumps({"file_path": file_path})),
        check_id=check_id,
    )


def create_bgp_stale_route_check() -> PointInTimeHealthCheck:
    """Create a point-in-time check that no BGP stale (graceful-restart-marked) routes remain.

    After a BGP graceful restart, peer-installed routes are marked "stale"
    until refreshed; this check asserts the stale flag has cleared on every
    route. Used as a postcheck in BGP restart / graceful-restart playbooks
    to verify EOR (End-Of-RIB) processing completed.

    Returns:
        A bare `PointInTimeHealthCheck` with `name=BGP_STALE_ROUTE_CHECK`.
    """
    return PointInTimeHealthCheck(name=hc_types.CheckName.BGP_STALE_ROUTE_CHECK)


def create_system_cpu_load_average_check(
    baseline: float,
    check_id: t.Optional[str] = None,
) -> PointInTimeHealthCheck:
    """Create a point-in-time check of system CPU load-average against a baseline.

    Reads the kernel's load-average (analogous to ``uptime``) and asserts the
    current value stays below `baseline`. Used as a precheck/postcheck in
    longevity tests to detect runaway CPU consumption that escapes per-process
    `CPU_UTILIZATION_CHECK` thresholds.

    Args:
        baseline: Maximum allowed load-average value (e.g. ``5.0``).
        check_id: Optional unique identifier for the check.

    Returns:
        A `PointInTimeHealthCheck` with `name=SYSTEM_CPU_LOAD_AVERAGE_CHECK`.
    """
    return PointInTimeHealthCheck(
        name=hc_types.CheckName.SYSTEM_CPU_LOAD_AVERAGE_CHECK,
        check_params=Params(json_params=json.dumps({"baseline": baseline})),
        check_id=check_id,
    )


# ---------------------------------------------------------------------------
# Bulk bare/no-arg factories (added in Phase 6-B45 for playbook_definitions.py)
# ---------------------------------------------------------------------------


def create_bgp_peer_route_check() -> PointInTimeHealthCheck:
    """Create a bare point-in-time check of BGP per-peer route counts.

    Inspects the BGP RIB and asserts each established peer is advertising/receiving
    a sane number of prefixes per its peer-group expectation. Bare variant used
    in playbook postchecks where the per-peer expectations are baked into the
    check implementation rather than the factory call.

    Returns:
        A bare `PointInTimeHealthCheck` with `name=BGP_PEER_ROUTE_CHECK`.
    """
    return PointInTimeHealthCheck(name=hc_types.CheckName.BGP_PEER_ROUTE_CHECK)


def create_dlb_resource_stickiness_check(
    json_params: t.Optional[t.Dict[str, t.Any]] = None,
) -> PointInTimeHealthCheck:
    """Create a point-in-time check that DLB (Dynamic Load Balancing) resource assignment is stable.

    Counts unique ECMP groups per prefix-pattern bucket and asserts the totals
    match the expected map in `json_params`. Used in DLB Gold/Rouge tests
    to verify stickiness is maintained (or correctly broken) across traffic
    runs and policy toggles.

    Args:
        json_params: Opaque dict carrying check expectations (e.g.
            ``{"prefix_patterns": ["5000:dd::", "5000:ee::"],
            "expected_counts": {"5000:dd prefixes": {"total": 110}, ...}}``).
            Bare (no params) when omitted.

    Returns:
        A `PointInTimeHealthCheck` with `name=DLB_RESOURCE_STICKINESS_CHECK`.
    """
    if json_params is None:
        return PointInTimeHealthCheck(
            name=hc_types.CheckName.DLB_RESOURCE_STICKINESS_CHECK
        )
    return PointInTimeHealthCheck(
        name=hc_types.CheckName.DLB_RESOURCE_STICKINESS_CHECK,
        check_params=Params(json_params=json.dumps(json_params)),
    )


def create_dsf_fabric_reachability_check() -> PointInTimeHealthCheck:
    """Create a bare point-in-time DSF fabric-endpoint reachability check.

    DSF-specific: queries every fabric endpoint on the DUT and asserts each
    has live reachability through the DSF fabric (no isolated/quarantined
    endpoints). Used in DSF playbooks as a precheck/postcheck around fabric
    drain, agent restart, and link-flap stages.

    Returns:
        A bare `PointInTimeHealthCheck` with `name=DSF_FABRIC_REACHABILITY_CHECK`.
    """
    return PointInTimeHealthCheck(name=hc_types.CheckName.DSF_FABRIC_REACHABILITY_CHECK)


def create_dsf_pfc_check(
    json_params: t.Optional[t.Dict[str, t.Any]] = None,
    thresholds: t.Optional[t.List["hc_types.DsfPfcThreshold"]] = None,
    check_scope: t.Optional["hc_types.Scope"] = None,
) -> PointInTimeHealthCheck:
    """DSF_PFC_CHECK — verifies DSF PFC counters.

    Variants:
    - `json_params`: pass-through Params.json_params dict.
    - `thresholds`: typed thrift `DsfPfcHealthCheckIn(thresholds=...)` via input_json.
    Mutually exclusive.
    """
    if json_params is not None and thresholds is not None:
        raise ValueError("json_params and thresholds are mutually exclusive")
    if thresholds is not None:
        return PointInTimeHealthCheck(
            name=hc_types.CheckName.DSF_PFC_CHECK,
            input_json=thrift_to_json(
                hc_types.DsfPfcHealthCheckIn(thresholds=thresholds)
            ),
            check_scope=check_scope,
        )
    if json_params is None:
        return PointInTimeHealthCheck(
            name=hc_types.CheckName.DSF_PFC_CHECK, check_scope=check_scope
        )
    return PointInTimeHealthCheck(
        name=hc_types.CheckName.DSF_PFC_CHECK,
        check_params=Params(json_params=json.dumps(json_params)),
        check_scope=check_scope,
    )


def create_fsdb_subscriber_timestamp_check(
    json_params: t.Optional[t.Dict[str, t.Any]] = None,
    start_time_jq_var: t.Optional[str] = None,
) -> PointInTimeHealthCheck:
    """Create a point-in-time check that FSDB subscribers are receiving fresh updates.

    Inspects the FSDB last-update timestamps for the named subscribers and
    fails if any timestamp is too stale (per the check's internal threshold).
    Used after `wedge_agent`/FSDB-affecting restart stages to verify the
    streaming-state subscribers re-converged.

    Args:
        json_params: Opaque dict with check scope (e.g.
            ``{"target_device": "...", "subscriber_names": [...],
            "is_validate_fsdb_session_after_agent_restart": True}``).
        start_time_jq_var: When set, anchors the freshness window via
            ``jq_params["start_time"] = f".{start_time_jq_var}"``.

    Returns:
        A `PointInTimeHealthCheck` with `name=FSDB_SUBSCRIBER_TIMESTAMP_CHECK`.
    """
    jq_params = {"start_time": f".{start_time_jq_var}"} if start_time_jq_var else None
    if json_params is None and not jq_params:
        return PointInTimeHealthCheck(
            name=hc_types.CheckName.FSDB_SUBSCRIBER_TIMESTAMP_CHECK
        )
    return PointInTimeHealthCheck(
        name=hc_types.CheckName.FSDB_SUBSCRIBER_TIMESTAMP_CHECK,
        check_params=Params(
            json_params=json.dumps(json_params) if json_params is not None else None,
            jq_params=jq_params,
        ),
    )


def create_ixia_port_stats_check(
    json_params: t.Optional[t.Dict[str, t.Any]] = None,
) -> PointInTimeHealthCheck:
    """Create a point-in-time check of IXIA port-level statistics thresholds.

    Polls IXIA port stats (link state, error counters, signal lock) and
    asserts each value satisfies the supplied thresholds. Used as a precheck
    in IXIA-driven tests to confirm chassis ports are healthy before traffic
    starts.

    Args:
        json_params: Opaque dict carrying threshold expectations
            (port-name → metric → threshold map). Bare check when omitted.

    Returns:
        A `PointInTimeHealthCheck` with `name=IXIA_PORT_STATS_CHECK`.
    """
    if json_params is None:
        return PointInTimeHealthCheck(name=hc_types.CheckName.IXIA_PORT_STATS_CHECK)
    return PointInTimeHealthCheck(
        name=hc_types.CheckName.IXIA_PORT_STATS_CHECK,
        check_params=Params(json_params=json.dumps(json_params)),
    )


def create_ixia_traffic_rate_check(
    json_params: t.Optional[t.Dict[str, t.Any]] = None,
    thresholds: t.Optional[t.List["hc_types.TrafficRateThreshold"]] = None,
) -> PointInTimeHealthCheck:
    """IXIA_TRAFFIC_RATE_CHECK — verifies IXIA traffic-rate thresholds.

    Two variants:
    - `json_params`: pass-through Params.json_params dict.
    - `thresholds`: typed thrift `IxiaTrafficRateHealthCheckIn(thresholds=...)`
      via input_json. Mutually exclusive with json_params.
    """
    if json_params is not None and thresholds is not None:
        raise ValueError("json_params and thresholds are mutually exclusive")
    if thresholds is not None:
        return PointInTimeHealthCheck(
            name=hc_types.CheckName.IXIA_TRAFFIC_RATE_CHECK,
            input_json=thrift_to_json(
                hc_types.IxiaTrafficRateHealthCheckIn(thresholds=thresholds)
            ),
        )
    if json_params is None:
        return PointInTimeHealthCheck(name=hc_types.CheckName.IXIA_TRAFFIC_RATE_CHECK)
    return PointInTimeHealthCheck(
        name=hc_types.CheckName.IXIA_TRAFFIC_RATE_CHECK,
        check_params=Params(json_params=json.dumps(json_params)),
    )


def create_pfc_wd_check(
    json_params: t.Optional[t.Dict[str, t.Any]] = None,
    thresholds: t.Optional[t.List["hc_types.PfcWdThreshold"]] = None,
    check_scope: t.Optional["hc_types.Scope"] = None,
) -> PointInTimeHealthCheck:
    """PFC_WD_CHECK — PFC watchdog verification.

    NOTE: Underlying CheckName is misspelled as PFC_WD_CHCEK (typo) — preserved
    here for byte-equivalence with existing call sites.

    Variants:
    - `json_params`: pass-through Params.json_params dict.
    - `thresholds`: typed thrift `PfcWdHealthCheckIn(thresholds=...)` via input_json.
    Mutually exclusive.
    """
    if json_params is not None and thresholds is not None:
        raise ValueError("json_params and thresholds are mutually exclusive")
    if thresholds is not None:
        return PointInTimeHealthCheck(
            name=hc_types.CheckName.PFC_WD_CHCEK,
            input_json=thrift_to_json(
                hc_types.PfcWdHealthCheckIn(thresholds=thresholds)
            ),
            check_scope=check_scope,
        )
    if json_params is None:
        return PointInTimeHealthCheck(
            name=hc_types.CheckName.PFC_WD_CHCEK, check_scope=check_scope
        )
    return PointInTimeHealthCheck(
        name=hc_types.CheckName.PFC_WD_CHCEK,
        check_params=Params(json_params=json.dumps(json_params)),
        check_scope=check_scope,
    )


def create_port_channel_expected_state_check(
    json_params: t.Optional[t.Dict[str, t.Any]] = None,
) -> PointInTimeHealthCheck:
    """Create a point-in-time check that port-channels (LAGs) are in their expected state.

    Asserts each port-channel's operational state (UP/DOWN) and member-link
    aggregation matches the expected map. Used in port-channel tests around
    member flap, min-link-patcher, and warmboot stages to verify LAG
    re-convergence.

    Args:
        json_params: Opaque dict mapping port-channel name → expected state
            attributes (e.g. ``oper_state``, ``min_links``, ``active_members``).
            Bare check when omitted.

    Returns:
        A `PointInTimeHealthCheck` with `name=PORT_CHANNEL_EXPECTED_STATE_CHECK`.
    """
    if json_params is None:
        return PointInTimeHealthCheck(
            name=hc_types.CheckName.PORT_CHANNEL_EXPECTED_STATE_CHECK
        )
    return PointInTimeHealthCheck(
        name=hc_types.CheckName.PORT_CHANNEL_EXPECTED_STATE_CHECK,
        check_params=Params(json_params=json.dumps(json_params)),
    )


def create_port_counters_check(
    json_params: t.Optional[t.Dict[str, t.Any]] = None,
    thresholds: t.Optional[t.List["hc_types.PortCountersThreshold"]] = None,
) -> PointInTimeHealthCheck:
    """PORT_COUNTERS_CHECK — verifies port counters.

    Args:
        json_params: Opaque dict variant.
        thresholds: Typed PortCountersThreshold list (input_json variant).
    """
    if thresholds is not None:
        return PointInTimeHealthCheck(
            name=hc_types.CheckName.PORT_COUNTERS_CHECK,
            input_json=thrift_to_json(
                hc_types.PortCountersHealthCheckIn(thresholds=thresholds)
            ),
        )
    if json_params is None:
        return PointInTimeHealthCheck(name=hc_types.CheckName.PORT_COUNTERS_CHECK)
    return PointInTimeHealthCheck(
        name=hc_types.CheckName.PORT_COUNTERS_CHECK,
        check_params=Params(json_params=json.dumps(json_params)),
    )


def create_port_queue_rate_check(
    json_params: t.Optional[t.Dict[str, t.Any]] = None,
    thresholds: t.Optional[t.List["hc_types.PortQueueRateThreshold"]] = None,
) -> PointInTimeHealthCheck:
    """PORT_QUEUE_RATE_CHECK — verifies port queue rate thresholds.

    Args:
        json_params: Opaque dict variant.
        thresholds: Typed `PortQueueRateThreshold` list (input_json variant).
    """
    if thresholds is not None:
        return PointInTimeHealthCheck(
            name=hc_types.CheckName.PORT_QUEUE_RATE_CHECK,
            input_json=thrift_to_json(
                hc_types.PortQueueRateHealthCheckIn(thresholds=thresholds)
            ),
        )
    if json_params is None:
        return PointInTimeHealthCheck(name=hc_types.CheckName.PORT_QUEUE_RATE_CHECK)
    return PointInTimeHealthCheck(
        name=hc_types.CheckName.PORT_QUEUE_RATE_CHECK,
        check_params=Params(json_params=json.dumps(json_params)),
    )


def create_port_transceiver_check(
    json_params: t.Optional[t.Dict[str, t.Any]] = None,
) -> PointInTimeHealthCheck:
    """Create a point-in-time check of optical transceiver presence and state.

    Inspects qsfp_service for each port's transceiver and asserts presence /
    detected state matches expectations. Used in transceiver-removal /
    insertion tests and as a precheck around firmware upgrade stages.

    Args:
        json_params: Opaque dict mapping port → expected transceiver
            attributes (presence, type, vendor). Bare check when omitted.

    Returns:
        A `PointInTimeHealthCheck` with `name=PORT_TRANSCEIVER_CHECK`.
    """
    if json_params is None:
        return PointInTimeHealthCheck(name=hc_types.CheckName.PORT_TRANSCEIVER_CHECK)
    return PointInTimeHealthCheck(
        name=hc_types.CheckName.PORT_TRANSCEIVER_CHECK,
        check_params=Params(json_params=json.dumps(json_params)),
    )


def create_port_tx_rx_check(
    json_params: t.Optional[t.Dict[str, t.Any]] = None,
) -> PointInTimeHealthCheck:
    """Create a point-in-time check of port TX/RX byte/packet counters.

    Reads switch-port TX/RX counters and asserts each port's traffic deltas
    satisfy the supplied expectations (non-zero on active ports, zero on
    quiet ports). Used as a postcheck around traffic stages to verify that
    expected paths actually carried traffic.

    Args:
        json_params: Opaque dict carrying per-port TX/RX expectations
            (min/max packet counts, byte counts). Bare check when omitted.

    Returns:
        A `PointInTimeHealthCheck` with `name=PORT_TX_RX_CHECK`.
    """
    if json_params is None:
        return PointInTimeHealthCheck(name=hc_types.CheckName.PORT_TX_RX_CHECK)
    return PointInTimeHealthCheck(
        name=hc_types.CheckName.PORT_TX_RX_CHECK,
        check_params=Params(json_params=json.dumps(json_params)),
    )


def create_lldp_check(
    disabled_interfaces_jq_var: t.Optional[str] = None,
) -> PointInTimeHealthCheck:
    """LLDP_CHECK — LLDP neighbor verification.

    Args:
        disabled_interfaces_jq_var: jq path expression that resolves to a list of
            interface names to skip (e.g. ``"cached.odd_interfaces"``).
    """
    if disabled_interfaces_jq_var is None:
        return PointInTimeHealthCheck(name=hc_types.CheckName.LLDP_CHECK)
    return PointInTimeHealthCheck(
        name=hc_types.CheckName.LLDP_CHECK,
        check_params=Params(
            jq_params={"disabled_interfaces": f".{disabled_interfaces_jq_var}"},
        ),
    )


def create_port_state_check(
    additional_interfaces: t.Optional[t.List[t.Dict[str, str]]] = None,
    disabled_interfaces: t.Optional[t.List[t.Dict[str, str]]] = None,
    disabled_interfaces_jq_var: t.Optional[str] = None,
) -> PointInTimeHealthCheck:
    """PORT_STATE_CHECK — port operational-state verification.

    Args:
        additional_interfaces: Extra `{switch_name, interface_name}` entries to include
            beyond the framework-discovered set (e.g., hyperport sub-interfaces).
        disabled_interfaces: `{switch_name, interface_name}` entries that are expected
            to be down (e.g., transceiver-removal tests).
        disabled_interfaces_jq_var: jq path expression resolving to the list of
            interfaces to treat as expected-down (e.g. ``"cached.odd_interfaces"``).
    """
    if (
        additional_interfaces is None
        and disabled_interfaces is None
        and disabled_interfaces_jq_var is None
    ):
        return PointInTimeHealthCheck(name=hc_types.CheckName.PORT_STATE_CHECK)
    payload: t.Dict[str, t.Any] = {}
    if additional_interfaces is not None:
        payload["additional_interfaces"] = additional_interfaces
    if disabled_interfaces is not None:
        payload["disabled_interfaces"] = disabled_interfaces
    jq_params = (
        {"disabled_interfaces": f".{disabled_interfaces_jq_var}"}
        if disabled_interfaces_jq_var
        else None
    )
    return PointInTimeHealthCheck(
        name=hc_types.CheckName.PORT_STATE_CHECK,
        check_params=Params(
            json_params=json.dumps(payload) if payload else None,
            jq_params=jq_params,
        ),
    )


def create_bgp_session_snapshot_check(
    parent_prefixes_to_ignore: t.Optional[t.List[str]] = None,
    skip_flap_check: t.Optional[bool] = None,
    skip_uptime_check: t.Optional[bool] = None,
    expected_peer_identity: t.Optional[t.Union[str, t.Dict[str, str]]] = None,
    pre_snapshot_checkpoint_id: t.Optional[str] = None,
    post_snapshot_checkpoint_id: t.Optional[str] = None,
) -> SnapshotHealthCheck:
    """BGP_SESSION_CHECK — snapshot variant.

    Bare by default. Pass kwargs to add common JSON params (e.g.
    `parent_prefixes_to_ignore` to skip churn peer addresses) or checkpoint IDs.
    `skip_flap_check`/`skip_uptime_check` are tri-state — `None` omits the key,
    `True`/`False` sets it explicitly (some sites encode `False` to preserve
    historical byte-equivalence).
    """
    json_payload: t.Dict[str, t.Any] = {}
    if parent_prefixes_to_ignore is not None:
        json_payload["parent_prefixes_to_ignore"] = parent_prefixes_to_ignore
    if skip_flap_check is not None:
        json_payload["skip_flap_check"] = skip_flap_check
    if skip_uptime_check is not None:
        json_payload["skip_uptime_check"] = skip_uptime_check
    if expected_peer_identity is not None:
        json_payload["expected_peer_identity"] = expected_peer_identity
    return SnapshotHealthCheck(
        name=hc_types.CheckName.BGP_SESSION_CHECK,
        check_params=(
            Params(json_params=json.dumps(json_payload)) if json_payload else None
        ),
        pre_snapshot_checkpoint_id=pre_snapshot_checkpoint_id,
        post_snapshot_checkpoint_id=post_snapshot_checkpoint_id,
    )


def create_buffer_utilization_snapshot_check(
    thresholds: t.List["hc_types.BufferUtilizationThreshold"],
    pre_snapshot_checkpoint_id: t.Optional[str] = None,
    post_snapshot_checkpoint_id: t.Optional[str] = None,
) -> SnapshotHealthCheck:
    """BUFFER_UTILIZATION_CHECK — snapshot variant.

    Caller supplies fully-built `BufferUtilizationThreshold` values (each
    binds a hostname + interface set + active/other queue byte ceilings).
    """
    return SnapshotHealthCheck(
        name=hc_types.CheckName.BUFFER_UTILIZATION_CHECK,  # pyre-ignore[16]
        input_json=thrift_to_json(
            hc_types.BufferUtilizationHealthCheckIn(
                thresholds=thresholds
            )  # pyre-ignore[16]
        ),
        pre_snapshot_checkpoint_id=pre_snapshot_checkpoint_id,
        post_snapshot_checkpoint_id=post_snapshot_checkpoint_id,
    )


def create_qos_dscp_tx_queue_snapshot_check(
    tx_queue_info_list: t.List["hc_types.TxQueueInfo"],
    pre_snapshot_checkpoint_id: t.Optional[str] = None,
    post_snapshot_checkpoint_id: t.Optional[str] = None,
) -> SnapshotHealthCheck:
    """Create a snapshot check that QoS DSCP-marked traffic landed on the right tx queues.

    Captures per-queue tx counters at pre/post checkpoints and asserts the
    delta on each queue matches the expected (queue, DSCP, traffic-item)
    tuple in `tx_queue_info_list`. Used in QoS / DSCP-classification tests
    to verify class-of-service mapping survives stages.

    Args:
        tx_queue_info_list: Typed `TxQueueInfo` entries binding port +
            queue-id + expected DSCP + traffic-item-name. Required.
        pre_snapshot_checkpoint_id: Optional named checkpoint marker for the
            pre-snapshot capture (defaults to playbook prechecks).
        post_snapshot_checkpoint_id: Optional named checkpoint marker for
            the post-snapshot capture (defaults to playbook postchecks).

    Returns:
        A `SnapshotHealthCheck` with `name=QOS_DSCP_TX_QUEUE_CHECK` carrying
        a `QoSDscpTxQueueHealthCheckIn` input_json payload.
    """
    return SnapshotHealthCheck(
        name=hc_types.CheckName.QOS_DSCP_TX_QUEUE_CHECK,
        input_json=thrift_to_json(
            hc_types.QoSDscpTxQueueHealthCheckIn(tx_queue_info_list=tx_queue_info_list)
        ),
        pre_snapshot_checkpoint_id=pre_snapshot_checkpoint_id,
        post_snapshot_checkpoint_id=post_snapshot_checkpoint_id,
    )


def create_port_channel_state_snapshot_check() -> SnapshotHealthCheck:
    """Create a bare snapshot check that port-channel (LAG) state is unchanged across the playbook.

    Captures port-channel oper state and member-link aggregation at pre/post
    checkpoints and asserts no drift. Used to detect transient LAG flaps
    that recovered before any point-in-time check would catch them.

    Returns:
        A bare `SnapshotHealthCheck` with `name=PORT_CHANNEL_STATE_CHECK`.
    """
    return SnapshotHealthCheck(name=hc_types.CheckName.PORT_CHANNEL_STATE_CHECK)


def create_next_hop_count_snapshot_check() -> SnapshotHealthCheck:
    """Create a bare snapshot check that BGP next-hop counts are unchanged across the playbook.

    Captures the per-prefix next-hop counts at pre/post checkpoints and
    asserts no prefix lost or gained next-hops. Used to detect ECMP-width
    drift after stages that should not affect routing (e.g. pure traffic
    runs, non-disruptive config patches).

    Returns:
        A bare `SnapshotHealthCheck` with `name=NEXT_HOP_COUNT_CHECK`.
    """
    return SnapshotHealthCheck(name=hc_types.CheckName.NEXT_HOP_COUNT_CHECK)


def create_bgp_peer_route_snapshot_check() -> SnapshotHealthCheck:
    """Create a bare snapshot check that BGP per-peer route counts are unchanged across the playbook.

    Captures advertised/received route counts per peer at pre/post checkpoints
    and asserts no churn. Used as a blanket guard around stages that should
    not affect peer-route exchange.

    Returns:
        A bare `SnapshotHealthCheck` with `name=BGP_PEER_ROUTE_CHECK`.
    """
    return SnapshotHealthCheck(name=hc_types.CheckName.BGP_PEER_ROUTE_CHECK)


def create_cpu_queue_snapshot_check(
    active_queues: t.Optional[t.List[int]] = None,
    no_discard_queues: t.Optional[t.List[int]] = None,
    active_min_out_pps_per_queue: t.Optional[t.Dict[int, int]] = None,
    inactive_queues: t.Optional[t.List[int]] = None,
    inactive_max_pps_per_queue: t.Optional[t.Dict[int, int]] = None,
    pre_snapshot_checkpoint_id: t.Optional[str] = None,
    post_snapshot_checkpoint_id: t.Optional[str] = None,
) -> SnapshotHealthCheck:
    """Create a snapshot check that CPU-punted traffic landed on the right CPU queues.

    Captures CPU-queue tx/discard counters at pre/post checkpoints and asserts
    each named queue saw activity (or did not) per the supplied expectations.
    Heavily used in COPP / CPU-prioritization tests (BGP CP, ICMP, DHCP punt
    paths) to verify class-of-service mapping for traffic punted to the CPU.

    Args:
        active_queues: Queue IDs that MUST see non-zero tx packets in the window.
        no_discard_queues: Queue IDs that MUST NOT see any discards (e.g. high-
            priority BGP_CP queue).
        active_min_out_pps_per_queue: Per-queue minimum out-pps requirements
            (e.g. ``{low_queue: 10}``).
        inactive_queues: Queue IDs that MUST stay below a noise threshold (A2
            leakage check — catches misclassification where traffic ends up on
            the wrong queue). Background control traffic (BGP keepalives, LLDP,
            NDP) ticks queues constantly, so each inactive queue is given a
            per-queue noise tolerance via `inactive_max_pps_per_queue` (merged
            into `active_min_out_pps_per_queue` under the hood — the underlying
            HC compares `out_pps > threshold` for inactive queues).
        inactive_max_pps_per_queue: Per-queue noise tolerance for inactive
            queues (e.g. ``{high_queue: 100}``). Queues in `inactive_queues`
            not listed here fall back to the per-queue value from
            `active_min_out_pps_per_queue` if present, else 0.
        pre_snapshot_checkpoint_id: Optional named checkpoint marker for the
            pre-snapshot capture.
        post_snapshot_checkpoint_id: Optional named checkpoint marker for the
            post-snapshot capture.

    Returns:
        A `SnapshotHealthCheck` with `name=CPU_QUEUE_CHECK` carrying a
        `CpuQueueHealthCheckIn` input_json payload.
    """
    if inactive_queues and inactive_max_pps_per_queue:
        merged_pps = dict(active_min_out_pps_per_queue or {})
        for queue, max_pps in inactive_max_pps_per_queue.items():
            merged_pps[queue] = max_pps
        active_min_out_pps_per_queue = merged_pps

    kwargs: t.Dict[str, t.Any] = {}
    if active_queues is not None:
        kwargs["active_queues"] = active_queues
    if inactive_queues is not None:
        kwargs["inactive_queues"] = inactive_queues
    if no_discard_queues is not None:
        kwargs["no_discard_queues"] = no_discard_queues
    if active_min_out_pps_per_queue is not None:
        kwargs["active_min_out_pps_per_queue"] = active_min_out_pps_per_queue
    return SnapshotHealthCheck(
        name=hc_types.CheckName.CPU_QUEUE_CHECK,
        input_json=thrift_to_json(hc_types.CpuQueueHealthCheckIn(**kwargs)),
        pre_snapshot_checkpoint_id=pre_snapshot_checkpoint_id,
        post_snapshot_checkpoint_id=post_snapshot_checkpoint_id,
    )


def create_service_restart_check(
    services: t.Optional[t.List[str]] = None,
    daemons: t.Optional[t.List[str]] = None,
    expected_restarted_services: t.Optional[t.List[str]] = None,
    start_time_jq_var: t.Optional[str] = "test_case_start_time",
    restart_start_time_jq_var: t.Optional[str] = None,
    extra_json_params: t.Optional[t.Dict[str, t.Any]] = None,
    check_scope: t.Optional["hc_types.Scope"] = None,
) -> PointInTimeHealthCheck:
    """SERVICE_RESTART_CHECK — verifies expected services restarted in the lookback window.

    Args:
        services: Services to monitor (e.g. ARISTA_CRITICAL_SAND_AGENTS list).
        daemons: Daemon names variant of services (some checks use this key).
        expected_restarted_services: Services that MUST have restarted.
        start_time_jq_var: jq variable name carrying the lookback start time.
        restart_start_time_jq_var: When set, adds a `restart_start_time` jq_param
            scoped to the post-intentional-restart window.
        extra_json_params: Caller-supplied extra json_params keys merged in.
    """
    json_payload: t.Dict[str, t.Any] = {}
    if services is not None:
        json_payload["services"] = services
    if daemons is not None:
        json_payload["daemons"] = daemons
    if expected_restarted_services is not None:
        json_payload["expected_restarted_services"] = expected_restarted_services
    if extra_json_params:
        json_payload.update(extra_json_params)
    jq_params: t.Dict[str, str] = {}
    if start_time_jq_var:
        jq_params["start_time"] = f".{start_time_jq_var}"
    if restart_start_time_jq_var:
        jq_params["restart_start_time"] = f".{restart_start_time_jq_var}"
    return PointInTimeHealthCheck(
        name=hc_types.CheckName.SERVICE_RESTART_CHECK,
        check_params=Params(
            json_params=json.dumps(json_payload),
            jq_params=jq_params or None,
        ),
        check_scope=check_scope,
    )


def create_systemctl_active_state_check(
    services: t.Optional[t.List["hc_types.Service"]] = None,
    services_json: t.Optional[t.List[str]] = None,
) -> PointInTimeHealthCheck:
    """SYSTEMCTL_ACTIVE_STATE_CHECK — systemctl active-state verification.

    Bare by default. Two variants for scoping to specific services:
    - `services`: thrift `SystemctlActiveStateHealthCheckIn` input_json variant
      (typed Service enum list).
    - `services_json`: check_params.json_params variant (string list).
    Mutually exclusive — pass at most one.
    """
    if services is not None and services_json is not None:
        raise ValueError(
            "services and services_json are mutually exclusive — pass at most one."
        )
    if services is None and services_json is None:
        return PointInTimeHealthCheck(
            name=hc_types.CheckName.SYSTEMCTL_ACTIVE_STATE_CHECK
        )
    if services is not None:
        return PointInTimeHealthCheck(
            name=hc_types.CheckName.SYSTEMCTL_ACTIVE_STATE_CHECK,
            input_json=thrift_to_json(
                hc_types.SystemctlActiveStateHealthCheckIn(services=services)
            ),
        )
    return PointInTimeHealthCheck(
        name=hc_types.CheckName.SYSTEMCTL_ACTIVE_STATE_CHECK,
        check_params=Params(json_params=json.dumps({"services": services_json})),
    )


def create_wedge_agent_configured_check() -> PointInTimeHealthCheck:
    """Create a bare point-in-time check that wedge_agent has applied its configuration.

    FBOSS-only: queries wedge_agent state and asserts it is in the
    "configured" lifecycle phase (config applied, hardware programmed). Used
    as a precheck after agent restart / warmboot to ensure the test does not
    proceed before the data plane is programmed.

    Returns:
        A bare `PointInTimeHealthCheck` with `name=WEDGE_AGENT_CONFIGURED_CHECK`.
    """
    return PointInTimeHealthCheck(name=hc_types.CheckName.WEDGE_AGENT_CONFIGURED_CHECK)


def create_dsf_drain_state_check(
    is_drained: t.Optional[bool] = None,
    check_scope: t.Optional["hc_types.Scope"] = None,
) -> PointInTimeHealthCheck:
    """DSF_DRAIN_STATE_CHECK — DSF drain-state verification.

    Args:
        is_drained: When set, enforces the expected drained state via the
            typed `DsfDrainStateCheckIn` input_json variant.
        check_scope: Optional scope override (e.g. ``Scope.DEFAULT`` to run on
            the DUT only).
    """
    if is_drained is None:
        return PointInTimeHealthCheck(
            name=hc_types.CheckName.DSF_DRAIN_STATE_CHECK,
            check_scope=check_scope,
        )
    return PointInTimeHealthCheck(
        name=hc_types.CheckName.DSF_DRAIN_STATE_CHECK,
        input_json=thrift_to_json(hc_types.DsfDrainStateCheckIn(is_drained=is_drained)),
        check_scope=check_scope,
    )


def create_prefix_limit_check(
    prefix_limit: t.Optional[t.Union[int, str]] = None,
) -> PointInTimeHealthCheck:
    """PREFIX_LIMIT_CHECK — verifies BGP prefix count.

    When `prefix_limit` is set, the check enforces the explicit limit. Bare
    (no kwarg) emits no check_params and lets the check use its default.
    """
    if prefix_limit is None:
        return PointInTimeHealthCheck(name=hc_types.CheckName.PREFIX_LIMIT_CHECK)
    return PointInTimeHealthCheck(
        name=hc_types.CheckName.PREFIX_LIMIT_CHECK,
        check_params=Params(json_params=json.dumps({"prefix_limit": prefix_limit})),
    )


def create_l2_entry_threshold_check(
    ndp_entry_upper_lower_threshold: t.Optional[t.Sequence[int]] = None,
    arp_entry_upper_lower_threshold: t.Optional[t.Sequence[int]] = None,
    mac_entry_upper_lower_threshold: t.Optional[t.Sequence[int]] = None,
) -> PointInTimeHealthCheck:
    """L2_ENTRY_THRESHOLD_CHECK — verifies NDP/ARP/MAC entry counts stay within bounds.

    Each threshold is a `(upper, lower)` tuple. Pass exactly one of the three
    (the underlying check serializes whichever key is provided).
    """
    json_payload: t.Dict[str, t.Any] = {}
    if ndp_entry_upper_lower_threshold is not None:
        json_payload["ndp_entry_upper_lower_threshold"] = (
            ndp_entry_upper_lower_threshold
        )
    if arp_entry_upper_lower_threshold is not None:
        json_payload["arp_entry_upper_lower_threshold"] = (
            arp_entry_upper_lower_threshold
        )
    if mac_entry_upper_lower_threshold is not None:
        json_payload["mac_entry_upper_lower_threshold"] = (
            mac_entry_upper_lower_threshold
        )
    return PointInTimeHealthCheck(
        name=hc_types.CheckName.L2_ENTRY_THRESHOLD_CHECK,
        check_params=Params(json_params=json.dumps(json_payload)),
    )


def create_route_convergence_time_check(
    network_group_regex: str,
    iterations: int = 5,
    time_threshold: int = 35,
    wait_time_seconds: int = 60,
) -> PointInTimeHealthCheck:
    """ROUTE_CONVERGENCE_TIME_CHECK — DELETE/ADD-cycle BGP convergence check.

    Performs `iterations` DELETE→ADD cycles via IXIA toggles and analyzes
    wedge_agent.log to assert each operation completes within `time_threshold` s.
    """
    check_params = {
        "network_group_regex": network_group_regex,
        "iterations": iterations,
        "time_threshold": time_threshold,
        "wait_time_seconds": wait_time_seconds,
    }
    return PointInTimeHealthCheck(
        name=hc_types.CheckName.ROUTE_CONVERGENCE_TIME_CHECK,
        check_params=Params(json_params=json.dumps(check_params)),
    )


def create_oomd_kill_check(
    expected_oom_kills: t.Dict[str, t.List[str]],
    start_time_jq_var: t.Optional[str] = "test_case_start_time",
) -> PointInTimeHealthCheck:
    """OOMD_KILL_CHECK — verifies expected oomd kill events occurred in the lookback.

    Args:
        expected_oom_kills: Mapping from cgroup slice (e.g. ``"system.slice"``) to a
            list of expected kill reasons (e.g. ``["memory-pressure"]``).
        start_time_jq_var: jq variable name for the lookback start time.
    """
    jq_params = {"start_time": f".{start_time_jq_var}"} if start_time_jq_var else None
    return PointInTimeHealthCheck(
        name=hc_types.CheckName.OOMD_KILL_CHECK,
        check_params=Params(
            jq_params=jq_params,
            json_params=json.dumps({"expected_oom_kills": expected_oom_kills}),
        ),
    )


def create_clear_counters_check() -> PointInTimeHealthCheck:
    """Create a bare helper check that clears device counters as a side-effect.

    Despite the "check" naming, this is a side-effect-only entry that resets
    interface / counter state on the DUT so subsequent checks have a clean
    baseline. Used as an early step in playbook prechecks (and around the
    transition from setup to traffic stages) to avoid spurious counter-delta
    failures.

    Returns:
        A bare `PointInTimeHealthCheck` with `name=CLEAR_COUNTERS_CHECK`.
    """
    return PointInTimeHealthCheck(name=hc_types.CheckName.CLEAR_COUNTERS_CHECK)


def create_drain_state_check(
    expected_drained: t.Optional[bool] = None,
    device_name: t.Optional[str] = None,
) -> PointInTimeHealthCheck:
    """DRAIN_STATE_CHECK — verifies the drain state of a device.

    Args:
        expected_drained: When set, asserts drained == expected_drained.
        device_name: When set, scopes the check to a specific device hostname.
    """
    json_payload: t.Dict[str, t.Any] = {}
    if expected_drained is not None:
        json_payload["expected_drained"] = expected_drained
    if device_name is not None:
        json_payload["device_name"] = device_name
    return PointInTimeHealthCheck(
        name=hc_types.CheckName.DRAIN_STATE_CHECK,
        check_params=(
            Params(json_params=json.dumps(json_payload)) if json_payload else None
        ),
    )


def create_unclean_exit_check(
    start_time_jq_var: t.Optional[str] = "test_case_start_time",
    exclude_services: t.Optional[t.List[str]] = None,
) -> PointInTimeHealthCheck:
    """UNCLEAN_EXIT_CHECK — detects unclean process exits since the test started.

    Args:
        start_time_jq_var: jq variable name carrying the lookback start time.
            Defaults to ``"test_case_start_time"``; set to ``None`` to omit.
        exclude_services: Process names to ignore (e.g. ``["bgpd"]`` for crash tests).
    """
    jq_params = {"start_time": f".{start_time_jq_var}"} if start_time_jq_var else None
    json_params = (
        json.dumps({"exclude_services": exclude_services})
        if exclude_services is not None
        else None
    )
    if not jq_params and not json_params:
        return PointInTimeHealthCheck(name=hc_types.CheckName.UNCLEAN_EXIT_CHECK)
    return PointInTimeHealthCheck(
        name=hc_types.CheckName.UNCLEAN_EXIT_CHECK,
        check_params=Params(jq_params=jq_params, json_params=json_params),
    )


def create_bgp_tcpdump_check(
    expected_message_types: t.Optional[t.List[str]] = None,
    unexpected_message_types: t.Optional[t.List[str]] = None,
    cleanup_capture_file: bool = False,
    expected_last_mod_time: t.Optional[int] = None,
) -> PointInTimeHealthCheck:
    """BGP_TCPDUMP_CHECK — verifies recent tcpdump captures contain/exclude given BGP message types.

    Args:
        expected_message_types: Message types that MUST appear (e.g. ``["UPDATE"]``).
        unexpected_message_types: Message types that MUST NOT appear.
        cleanup_capture_file: If True, the capture file is removed after the check.
        expected_last_mod_time: When set, the capture file's last-mod time must
            be within ``expected_last_mod_time`` seconds of the check time.
    """
    json_payload: t.Dict[str, t.Any] = {
        "expected_message_types": expected_message_types or [],
        "unexpected_message_types": unexpected_message_types or [],
        "cleanup_capture_file": cleanup_capture_file,
    }
    if expected_last_mod_time is not None:
        json_payload["expected_last_mod_time"] = expected_last_mod_time
    return PointInTimeHealthCheck(
        name=hc_types.CheckName.BGP_TCPDUMP_CHECK,
        check_params=Params(json_params=json.dumps(json_payload)),
    )


def create_bgp_route_count_verification_check(
    json_params: t.Optional[t.Dict[str, t.Any]] = None,
    check_id: t.Optional[str] = None,
) -> PointInTimeHealthCheck:
    """BGP_ROUTE_COUNT_VERIFICATION_CHECK — opaque pass-through with optional check_id.

    The check schema (descriptions_to_check / descriptions_to_ignore /
    direction / expected_count / policy_type / etc.) varies enough across
    callers that an opaque dict is the simplest factory shape.

    When called with no arguments (``json_params=None``), produces a bare
    PointInTime check (no ``check_params``), matching the previously-separate
    ``create_bgp_route_count_verification_check_bare`` factory.
    """
    if json_params is None:
        return PointInTimeHealthCheck(
            name=hc_types.CheckName.BGP_ROUTE_COUNT_VERIFICATION_CHECK
        )
    return PointInTimeHealthCheck(
        name=hc_types.CheckName.BGP_ROUTE_COUNT_VERIFICATION_CHECK,
        check_params=Params(json_params=json.dumps(json_params)),
        check_id=check_id,
    )


def create_port_speed_snapshot_check(
    json_params: t.Dict[str, t.Any],
    pre_snapshot_checkpoint_id: t.Optional[str] = None,
    post_snapshot_checkpoint_id: t.Optional[str] = None,
) -> SnapshotHealthCheck:
    """PORT_SPEED_SNAPSHOT_CHECK — opaque pass-through with optional checkpoint IDs."""
    return SnapshotHealthCheck(
        name=hc_types.CheckName.PORT_SPEED_SNAPSHOT_CHECK,
        check_params=Params(json_params=json.dumps(json_params)),
        pre_snapshot_checkpoint_id=pre_snapshot_checkpoint_id,
        post_snapshot_checkpoint_id=post_snapshot_checkpoint_id,
    )


def create_next_hop_count_check(
    discover_baseline: bool = False,
    baseline_nexthop_count: t.Optional[int] = None,
    use_discovered_prefixes: bool = False,
    prefix_subnets: t.Optional[t.List[str]] = None,
    expected_nexthop_count: t.Optional[int] = None,
    min_nexthop_count: t.Optional[int] = None,
    max_nexthop_count: t.Optional[int] = None,
    check_id: t.Optional[str] = None,
) -> PointInTimeHealthCheck:
    """NEXT_HOP_COUNT_CHECK — BGP multipath next-hop count.

    Validates the number of next-hops (multipath routes) for BGP prefixes.
    Two modes:
      * Discovery: find prefixes with ``baseline_nexthop_count`` next-hops.
      * Validation: verify discovered prefixes have ``expected_nexthop_count``.

    Args:
        discover_baseline: If True, run in discovery mode.
        baseline_nexthop_count: Number of next-hops to look for during discovery.
        use_discovered_prefixes: Validate against previously-discovered prefixes.
        prefix_subnets: Subnets to constrain the check to.
        expected_nexthop_count: Exact number of next-hops to require.
        min_nexthop_count: Minimum acceptable next-hops.
        max_nexthop_count: Maximum acceptable next-hops.
        check_id: Optional unique identifier for the check.
    """
    check_params: t.Dict[str, t.Any] = {}
    if discover_baseline:
        check_params["discover_baseline"] = True
        if baseline_nexthop_count is not None:
            check_params["baseline_nexthop_count"] = baseline_nexthop_count
    if use_discovered_prefixes:
        check_params["use_discovered_prefixes"] = True
    if prefix_subnets is not None:
        check_params["prefix_subnets"] = prefix_subnets
    if expected_nexthop_count is not None:
        check_params["expected_nexthop_count"] = expected_nexthop_count
    if min_nexthop_count is not None:
        check_params["min_nexthop_count"] = min_nexthop_count
    if max_nexthop_count is not None:
        check_params["max_nexthop_count"] = max_nexthop_count
    return PointInTimeHealthCheck(
        name=hc_types.CheckName.NEXT_HOP_COUNT_CHECK,
        check_params=(
            Params(json_params=json.dumps(check_params)) if check_params else None
        ),
        check_id=check_id,
    )


# ---------------------------------------------------------------------------
# UCMP / CTE family
# ---------------------------------------------------------------------------


def create_bgp_rib_weight_check(
    target_community: str,
    target_prefix: str,
    expected_weights: t.Dict[int, int],
    require_ucmp: bool = True,
    expected_as_weights: t.Optional[t.Dict[int, int]] = None,
) -> PointInTimeHealthCheck:
    """Create a UCMP control-plane check of the BGP RIB weight distribution for a VIP.

    Inspects BGP RIB entries matching `target_community` for `target_prefix`
    and asserts the per-next-hop weight histogram matches `expected_weights`.
    Used in UCMP / CTE tests to verify weighted-load-balancing policy is
    plumbed correctly through BGP attributes (link-bandwidth, etc.).

    Args:
        target_community: BGP community string identifying the VIP under test
            (e.g. ``CTE_UCMP_VIP_COMMUNITY``).
        target_prefix: VIP prefix (typically v6) whose RIB entry is examined.
        expected_weights: Map of weight → next-hop-count expected in the RIB
            (e.g. ``{10: 4, 5: 4, 2: 4}`` for an asymmetric 3-DC VIP).
        require_ucmp: When True (default), requires UCMP-formed weights; set
            False to permit ECMP-fallback (weight-0) entries.
        expected_as_weights: Optional per-AS weight map for cross-AS UCMP
            verification.

    Returns:
        A `PointInTimeHealthCheck` with `name=UCMP_CONTROL_PLANE_CHECK`.
    """
    check_params: t.Dict[str, t.Any] = {
        "target_community": target_community,
        "target_prefix": target_prefix,
        "expected_weights": expected_weights,
        "require_ucmp": require_ucmp,
    }
    if expected_as_weights:
        check_params["expected_as_weights"] = expected_as_weights
    return PointInTimeHealthCheck(
        name=hc_types.CheckName.UCMP_CONTROL_PLANE_CHECK,
        check_scope=hc_types.Scope.DEFAULT,
        check_params=Params(json_params=json.dumps(check_params)),
    )


def create_dynamic_bgp_rib_weight_check(
    target_community: str,
    target_prefix: str,
    jq_var_key: str = "ucmp_random_weights",
    require_ucmp: bool = True,
) -> PointInTimeHealthCheck:
    """Create a UCMP control-plane check whose expected weights are resolved at runtime via jq_vars.

    Sibling of `create_bgp_rib_weight_check` for tests that generate random
    UCMP weights at runtime (see `UcmpRandomWeightCustomStep`) and stash them
    in `parameter_evaluator.jq_vars`. The check resolves
    ``jq_vars[jq_var_key].expected_weights`` (and `.expected_as_weights`) at
    evaluation time instead of having them baked into the static config.

    Args:
        target_community: BGP community string identifying the VIP under test.
        target_prefix: VIP prefix whose RIB entry is examined.
        jq_var_key: Top-level key under `jq_vars` carrying the
            `expected_weights` / `expected_as_weights` sub-dicts (default
            ``"ucmp_random_weights"``, matching `UcmpRandomWeightCustomStep`).
        require_ucmp: When True (default), requires UCMP-formed weights.

    Returns:
        A `PointInTimeHealthCheck` with `name=UCMP_CONTROL_PLANE_CHECK` whose
        `check_params.jq_params` resolves the expected-weight maps at runtime.
    """
    return PointInTimeHealthCheck(
        name=hc_types.CheckName.UCMP_CONTROL_PLANE_CHECK,
        check_scope=hc_types.Scope.DEFAULT,
        check_params=Params(
            json_params=json.dumps(
                {
                    "target_community": target_community,
                    "target_prefix": target_prefix,
                    "require_ucmp": require_ucmp,
                }
            ),
            jq_params={
                "expected_weights": f".{jq_var_key}.expected_weights",
                "expected_as_weights": f".{jq_var_key}.expected_as_weights",
            },
        ),
    )


def create_fib_traffic_distribution_check(
    target_prefix: str,
    expected_fib_weights: t.Dict[int, int],
    tolerance_percent: int = 10,
    expected_traffic_distribution: t.Optional[t.Dict[str, float]] = None,
    min_traffic_bps: t.Optional[int] = None,
    min_ods_query_duration: t.Optional[int] = None,
    sleep_timer: t.Optional[int] = None,
) -> PointInTimeHealthCheck:
    """Create a UCMP data-plane check of FIB-level traffic distribution for a VIP.

    Sibling of `create_bgp_rib_weight_check` (which validates the control
    plane). This factory validates the FIB-programmed weights AND, optionally,
    actual traffic distribution observed via ODS counters. Note FIB weights
    are GCD-normalized (e.g. RIB ``{10: 4, 5: 4, 2: 4}`` → FIB unchanged at
    GCD=1, RIB ``{10: 4, 5: 4}`` → FIB ``{2: 4, 1: 4}`` at GCD=5).

    Args:
        target_prefix: VIP prefix being load-balanced.
        expected_fib_weights: Map of FIB-normalized weight → next-hop-count.
        tolerance_percent: Allowed +/- % variance for traffic distribution
            (default 10%). Only relevant when `expected_traffic_distribution`
            is set.
        expected_traffic_distribution: Optional map of egress port → expected
            fraction of traffic. When set, the check polls ODS counters and
            asserts each port's share is within `tolerance_percent`.
        min_traffic_bps: Optional minimum aggregate traffic rate to accept
            the measurement (filters out low-signal samples).
        min_ods_query_duration: Optional minimum window (seconds) for the
            ODS sampling query.
        sleep_timer: Optional pre-measurement sleep (seconds) to let traffic
            stabilize before sampling.

    Returns:
        A `PointInTimeHealthCheck` with `name=UCMP_TRAFFIC_DISTRIBUTION_CHECK`.
    """
    check_params: t.Dict[str, t.Any] = {
        "target_prefix": target_prefix,
        "expected_fib_weights": expected_fib_weights,
        "tolerance_percent": tolerance_percent,
    }
    if expected_traffic_distribution is not None:
        check_params["expected_traffic_distribution"] = expected_traffic_distribution
    if min_traffic_bps is not None:
        check_params["min_traffic_bps"] = min_traffic_bps
    if min_ods_query_duration is not None:
        check_params["min_ods_query_duration"] = min_ods_query_duration
    if sleep_timer is not None:
        check_params["sleep_timer"] = sleep_timer
    return PointInTimeHealthCheck(
        name=hc_types.CheckName.UCMP_TRAFFIC_DISTRIBUTION_CHECK,
        check_scope=hc_types.Scope.DEFAULT,
        check_params=Params(json_params=json.dumps(check_params)),
    )


def create_traffic_item_packet_loss_check(
    traffic_item_names: t.List[str],
    max_packet_loss_percent: float = 0.0,
) -> PointInTimeHealthCheck:
    """IXIA_PACKET_LOSS_CHECK — single-named-list variant for VIP/non-VIP streams.

    Distinct from `create_ixia_packet_loss_check` (caller-supplied thresholds list)
    and `create_ixia_packet_loss_check_traffic_split` (split expect/no-loss bundle).
    """
    return PointInTimeHealthCheck(
        name=hc_types.CheckName.IXIA_PACKET_LOSS_CHECK,
        input_json=thrift_to_json(
            hc_types.IxiaPacketLossHealthCheckIn(
                thresholds=[
                    hc_types.PacketLossThreshold(
                        names=traffic_item_names,
                        str_value=str(max_packet_loss_percent),
                        metric=hc_types.PacketLossMetric.PERCENTAGE,
                    )
                ],
            )
        ),
    )


def create_packetloss_health_check() -> PointInTimeHealthCheck:
    """Create the bare IXIA_PACKET_LOSS_CHECK variant (no params, no input_json).

    The check evaluates against framework-discovered IXIA traffic items and
    applies its built-in default thresholds. Prefer
    `create_traffic_item_packet_loss_check`,
    `create_ixia_packet_loss_check_traffic_split`, or
    `create_ixia_packet_loss_check` when explicit threshold control is
    required (most modern test configs do).

    Returns:
        A bare `PointInTimeHealthCheck` with `name=IXIA_PACKET_LOSS_CHECK`.
    """
    return PointInTimeHealthCheck(
        name=hc_types.CheckName.IXIA_PACKET_LOSS_CHECK,
    )


def create_system_health_check() -> t.List[PointInTimeHealthCheck]:
    """Bundle of system-wide checks. Currently: UNCLEAN_EXIT_CHECK with `test_case_start_time`."""
    return [
        PointInTimeHealthCheck(
            name=hc_types.CheckName.UNCLEAN_EXIT_CHECK,
            check_params=Params(jq_params={"start_time": ".test_case_start_time"}),
        ),
    ]


def create_fpf_stale_prefix_check(
    subnet_prefix: str = "5000:dd::/32",
    check_id: t.Optional[str] = None,
) -> PointInTimeHealthCheck:
    """FPF_STALE_PREFIX_CHECK — verify no stale test prefixes in BGP RIB."""
    return PointInTimeHealthCheck(
        name=hc_types.CheckName.FPF_STALE_PREFIX_CHECK,
        check_params=Params(json_params=json.dumps({"subnet_prefix": subnet_prefix})),
        check_id=check_id,
    )


def create_fpf_hrt_fsdb_session_check(
    hosts: t.Optional[t.List[str]] = None,
    expected_session_count: t.Optional[int] = None,
    impacted_lanes_by_host_gpu: t.Optional[
        t.Dict[str, t.Dict[int, t.List[int]]]
    ] = None,
    reconcile_device_id: t.Optional[int] = None,
    planes_per_gpu: t.Optional[int] = None,
    check_id: t.Optional[str] = None,
) -> PointInTimeHealthCheck:
    """FPF_HRT_FSDB_SESSION_CHECK — verify HRT FSDB sessions are CONNECTED.

    Two signals (per host): (1) overall CONNECTED count == expected minus the
    impacted (gpu, lane) links; (2) per-device reconciliation on
    ``reconcile_device_id`` — impacted lanes DOWN, the rest CONNECTED.

    ``impacted_lanes_by_host_gpu`` maps host -> {gpu_id -> [lanes]}. Omit it (or
    pass empty) for the stable-state / enable / undrain / link-drain contract
    where every session must be CONNECTED.
    """
    params: t.Dict[str, t.Any] = {"hosts": hosts or []}
    if expected_session_count is not None:
        params["expected_session_count"] = expected_session_count
    if impacted_lanes_by_host_gpu is not None:
        params["impacted_lanes_by_host_gpu"] = impacted_lanes_by_host_gpu
    if reconcile_device_id is not None:
        params["reconcile_device_id"] = reconcile_device_id
    if planes_per_gpu is not None:
        params["planes_per_gpu"] = planes_per_gpu
    return PointInTimeHealthCheck(
        name=hc_types.CheckName.FPF_HRT_FSDB_SESSION_CHECK,
        check_params=Params(json_params=json.dumps(params)),
        check_id=check_id,
    )


def create_fpf_fsdb_ribmap_convergence_check(
    lane_map: t.Optional[t.Dict[str, str]] = None,
    expected_matched: int = 20000,
    trigger_delay_sec: int = 120,
    use_live_collectors: bool = False,
    settle_sec: t.Optional[float] = None,
    window_start: t.Optional[float] = None,
    window_end: t.Optional[float] = None,
    signal1_e2e_max_sec: t.Optional[float] = None,
    signal2_local_max_sec: t.Optional[float] = None,
    signal3_stability_duration_sec: t.Optional[float] = None,
    mode: t.Optional[str] = None,
    reconverge_sla_sec: t.Optional[float] = None,
    check_id: t.Optional[str] = None,
) -> PointInTimeHealthCheck:
    """FPF_FSDB_RIBMAP_CONVERGENCE_CHECK — FSDB ribMap convergence per lane.

    mode="restart": tolerate null/unresponsive polls during an FSDB restart and
    assert each device's ribMap returns to expected_matched within
    ``reconverge_sla_sec`` of the recorded restart moment.
    """
    params: t.Dict[str, t.Any] = {
        "lane_map": lane_map or {},
        "expected_matched": expected_matched,
        "trigger_delay_sec": trigger_delay_sec,
        "use_live_collectors": use_live_collectors,
    }
    if settle_sec is not None:
        params["settle_sec"] = settle_sec
    if window_start is not None:
        params["window_start"] = window_start
    if window_end is not None:
        params["window_end"] = window_end
    if signal1_e2e_max_sec is not None:
        params["signal1_e2e_max_sec"] = signal1_e2e_max_sec
    if signal2_local_max_sec is not None:
        params["signal2_local_max_sec"] = signal2_local_max_sec
    if signal3_stability_duration_sec is not None:
        params["signal3_stability_duration_sec"] = signal3_stability_duration_sec
    if mode is not None:
        params["mode"] = mode
    if reconverge_sla_sec is not None:
        params["reconverge_sla_sec"] = reconverge_sla_sec
    return PointInTimeHealthCheck(
        name=hc_types.CheckName.FPF_FSDB_RIBMAP_CONVERGENCE_CHECK,
        check_params=Params(json_params=json.dumps(params)),
        check_id=check_id,
    )


def create_fpf_bgp_rib_convergence_check(
    lane_map: t.Optional[t.Dict[str, str]] = None,
    expected_matched: int = 20000,
    trigger_delay_sec: int = 120,
    use_live_collectors: bool = False,
    settle_sec: t.Optional[float] = None,
    window_start: t.Optional[float] = None,
    window_end: t.Optional[float] = None,
    signal1_e2e_max_sec: t.Optional[float] = None,
    signal2_local_max_sec: t.Optional[float] = None,
    signal3_stability_duration_sec: t.Optional[float] = None,
    mode: t.Optional[str] = None,
    reconverge_sla_sec: t.Optional[float] = None,
    check_id: t.Optional[str] = None,
) -> PointInTimeHealthCheck:
    """FPF_BGP_RIB_CONVERGENCE_CHECK — BGP RIB convergence per lane.

    mode="restart": tolerate null/unresponsive polls during a bgpd (or
    wedge_agent warmboot) restart and assert each device's BGP RIB returns to
    expected_matched within ``reconverge_sla_sec`` of the recorded restart moment.
    """
    params: t.Dict[str, t.Any] = {
        "lane_map": lane_map or {},
        "expected_matched": expected_matched,
        "trigger_delay_sec": trigger_delay_sec,
        "use_live_collectors": use_live_collectors,
    }
    if settle_sec is not None:
        params["settle_sec"] = settle_sec
    if window_start is not None:
        params["window_start"] = window_start
    if window_end is not None:
        params["window_end"] = window_end
    if signal1_e2e_max_sec is not None:
        params["signal1_e2e_max_sec"] = signal1_e2e_max_sec
    if signal2_local_max_sec is not None:
        params["signal2_local_max_sec"] = signal2_local_max_sec
    if signal3_stability_duration_sec is not None:
        params["signal3_stability_duration_sec"] = signal3_stability_duration_sec
    if mode is not None:
        params["mode"] = mode
    if reconverge_sla_sec is not None:
        params["reconverge_sla_sec"] = reconverge_sla_sec
    return PointInTimeHealthCheck(
        name=hc_types.CheckName.FPF_BGP_RIB_CONVERGENCE_CHECK,
        check_params=Params(json_params=json.dumps(params)),
        check_id=check_id,
    )


def create_fpf_hrt_bulk_convergence_check(
    lanes: t.Optional[t.List[int]] = None,
    expected_per_lane: t.Optional[t.Dict[str, int]] = None,
    trigger_delay_sec: int = 120,
    use_live_collectors: bool = False,
    impacted_lanes: t.Optional[t.List[int]] = None,
    withdrawn_max_count: t.Optional[int] = None,
    lane_labels: t.Optional[t.Dict[str, str]] = None,
    only_hosts: t.Optional[t.List[str]] = None,
    settle_sec: t.Optional[float] = None,
    window_start: t.Optional[float] = None,
    window_end: t.Optional[float] = None,
    signal1_e2e_max_sec: t.Optional[float] = None,
    signal2_local_max_sec: t.Optional[float] = None,
    signal3_stability_duration_sec: t.Optional[float] = None,
    check_id: t.Optional[str] = None,
) -> PointInTimeHealthCheck:
    """FPF_HRT_BULK_CONVERGENCE_CHECK — HRT bulk convergence per lane.

    ``impacted_lanes`` flips those lanes to the withdrawn contract (their last
    in-window sample must be <= ``withdrawn_max_count``, default 0) for
    link-event tests; the remaining ``lanes`` keep the full 3-signal
    convergence evaluation. ``lane_labels`` maps each lane (str key) to a human
    mapping note (e.g. "→ beth0 on rtptest1544") surfaced in check messages.
    ``only_hosts`` restricts evaluation to those GPU host(s) — for a link event
    only the impacted host's lane withdraws, so the unimpacted remote host must
    be excluded or it is a false FAIL.
    """
    params: t.Dict[str, t.Any] = {
        "lanes": lanes or [],
        "expected_per_lane": expected_per_lane or {},
        "trigger_delay_sec": trigger_delay_sec,
        "use_live_collectors": use_live_collectors,
    }
    if impacted_lanes is not None:
        params["impacted_lanes"] = impacted_lanes
    if lane_labels:
        params["lane_labels"] = lane_labels
    if only_hosts:
        params["only_hosts"] = only_hosts
    if settle_sec is not None:
        params["settle_sec"] = settle_sec
    if withdrawn_max_count is not None:
        params["withdrawn_max_count"] = withdrawn_max_count
    if window_start is not None:
        params["window_start"] = window_start
    if window_end is not None:
        params["window_end"] = window_end
    if signal1_e2e_max_sec is not None:
        params["signal1_e2e_max_sec"] = signal1_e2e_max_sec
    if signal2_local_max_sec is not None:
        params["signal2_local_max_sec"] = signal2_local_max_sec
    if signal3_stability_duration_sec is not None:
        params["signal3_stability_duration_sec"] = signal3_stability_duration_sec
    return PointInTimeHealthCheck(
        name=hc_types.CheckName.FPF_HRT_BULK_CONVERGENCE_CHECK,
        check_params=Params(json_params=json.dumps(params)),
        check_id=check_id,
    )


def create_fpf_hrt_remote_failure_convergence_check(
    lanes: t.Optional[t.List[int]] = None,
    expected_per_lane: t.Optional[t.Dict[str, int]] = None,
    direction: str = "drain",
    max_convergence_sec: int = 120,
    trigger_delay_sec: int = 120,
    use_live_collectors: bool = False,
    lane_labels: t.Optional[t.Dict[str, str]] = None,
    only_hosts: t.Optional[t.List[str]] = None,
    window_start: t.Optional[float] = None,
    window_end: t.Optional[float] = None,
    check_id: t.Optional[str] = None,
) -> PointInTimeHealthCheck:
    """FPF_HRT_REMOTE_FAILURE_CONVERGENCE_CHECK — HRT negative-route convergence per lane.

    ``lane_labels`` maps each lane (str key) to a human mapping note (e.g.
    "→ beth0 on rtptest1544") surfaced in check messages for debuggability.
    ``only_hosts`` restricts evaluation to those GPU host(s) — for a link event
    only the impacted host's lane changes, so the unimpacted remote host must be
    excluded or it is a false FAIL.
    """
    params: t.Dict[str, t.Any] = {
        "lanes": lanes or [0, 1, 2, 3],
        "expected_per_lane": expected_per_lane or {},
        "direction": direction,
        "max_convergence_sec": max_convergence_sec,
        "trigger_delay_sec": trigger_delay_sec,
        "use_live_collectors": use_live_collectors,
    }
    if lane_labels:
        params["lane_labels"] = lane_labels
    if only_hosts:
        params["only_hosts"] = only_hosts
    if window_start is not None:
        params["window_start"] = window_start
    if window_end is not None:
        params["window_end"] = window_end
    return PointInTimeHealthCheck(
        name=hc_types.CheckName.FPF_HRT_REMOTE_FAILURE_CONVERGENCE_CHECK,
        check_params=Params(json_params=json.dumps(params)),
        check_id=check_id,
    )


def create_fpf_prod_hrt_prefix_stability_check(
    expected_reachable: t.Optional[t.List[int]] = None,
    expected_drained: t.Optional[t.List[int]] = None,
    expected_unreachable: t.Optional[t.List[int]] = None,
    expected_plane_up: t.Optional[t.List[int]] = None,
    prefixes: t.Optional[t.List[str]] = None,
    mode: t.Optional[str] = None,
    impacted_planes_by_host: t.Optional[t.Dict[str, t.List[int]]] = None,
    max_transition_sec: t.Optional[float] = None,
    local_prefixes: t.Optional[t.List[str]] = None,
    max_drain_sec: t.Optional[float] = None,
    disruption_ts: t.Optional[float] = None,
    lookback_sec: int = 900,
    settle_sec: t.Optional[float] = None,
    window_start: t.Optional[float] = None,
    window_end: t.Optional[float] = None,
    check_id: t.Optional[str] = None,
) -> PointInTimeHealthCheck:
    """FPF_PROD_HRT_PREFIX_STABILITY_CHECK — production HRT prefix reachability.

    Postcheck over the prod_hrt_prefix collector. For every data point between
    the test-case start and end time, asserts each monitored prefix is strictly
    compliant (Signal 1) and that no data point is null/timed-out (Signal 2).

    Expected plane sets default to the validated MWG2 FPF lab steady state
    (reachable [0,1,2,3], drained [], unreachable [4,5,6,7], plane_up [0..7])
    and are overridable for a different topology. Only the params that are
    explicitly provided are emitted; the rest fall back to the health check's
    own defaults.

    ``settle_sec`` skips the first N seconds of the window before evaluating
    stability — use it on the RESTORE/recovery phase so the per-prefix baseline
    is taken after the link recovers (plane comes back), instead of capturing the
    still-degraded state at window start and flagging the recovery as a
    regression. Ignored in transition mode.
    """
    params: t.Dict[str, t.Any] = {"lookback_sec": lookback_sec}
    if mode is not None:
        params["mode"] = mode
    if settle_sec is not None:
        params["settle_sec"] = settle_sec
    if impacted_planes_by_host is not None:
        params["impacted_planes_by_host"] = impacted_planes_by_host
    if max_transition_sec is not None:
        params["max_transition_sec"] = max_transition_sec
    if local_prefixes is not None:
        params["local_prefixes"] = local_prefixes
    if max_drain_sec is not None:
        params["max_drain_sec"] = max_drain_sec
    if disruption_ts is not None:
        params["disruption_ts"] = disruption_ts
    if expected_reachable is not None:
        params["expected_reachable"] = expected_reachable
    if expected_drained is not None:
        params["expected_drained"] = expected_drained
    if expected_unreachable is not None:
        params["expected_unreachable"] = expected_unreachable
    if expected_plane_up is not None:
        params["expected_plane_up"] = expected_plane_up
    if prefixes is not None:
        params["prefixes"] = prefixes
    if window_start is not None:
        params["window_start"] = window_start
    if window_end is not None:
        params["window_end"] = window_end
    return PointInTimeHealthCheck(
        name=hc_types.CheckName.FPF_PROD_HRT_PREFIX_STABILITY_CHECK,
        check_params=Params(json_params=json.dumps(params)),
        check_id=check_id,
    )


def create_fpf_hrt_plane_status_check(
    mode: str = "all_up",
    impacted_planes: t.Optional[t.List[int]] = None,
    expected_planes: t.Optional[t.List[int]] = None,
    lookback_sec: int = 900,
    settle_sec: t.Optional[float] = None,
    window_start: t.Optional[float] = None,
    window_end: t.Optional[float] = None,
    check_id: t.Optional[str] = None,
) -> PointInTimeHealthCheck:
    """FPF_HRT_PLANE_STATUS_CHECK — per-device HRT plane state (hrtctl show plane-status).

    Postcheck over the hrt_plane_status collector.

    mode="all_up" (default): every plane must be UP across the window. Use for
    non-drained scenarios (baseline/precheck, interface enable, link/device
    undrain). ``settle_sec`` advances the window start past a restore-phase
    recovery transient.

    mode="drain": the ``impacted_planes`` must be DRAINED by window end while
    every other plane stays UP. Use for link drain / device drain. The window
    auto-anchors at the recorded disruption time; SKIPs if the disruption was
    verified ineffective.
    """
    params: t.Dict[str, t.Any] = {"mode": mode, "lookback_sec": lookback_sec}
    if impacted_planes is not None:
        params["impacted_planes"] = impacted_planes
    if expected_planes is not None:
        params["expected_planes"] = expected_planes
    if settle_sec is not None:
        params["settle_sec"] = settle_sec
    if window_start is not None:
        params["window_start"] = window_start
    if window_end is not None:
        params["window_end"] = window_end
    return PointInTimeHealthCheck(
        name=hc_types.CheckName.FPF_HRT_PLANE_STATUS_CHECK,
        check_params=Params(json_params=json.dumps(params)),
        check_id=check_id,
    )


def create_fpf_hrt_system_memory_check(
    hosts: t.Optional[t.List[str]] = None,
    entity_desc: t.Optional[str] = None,
    key_desc: t.Optional[str] = None,
    threshold_gib: float = 8.0,
    threshold_bytes: t.Optional[int] = None,
    transform_desc: t.Optional[str] = None,
    lookback_sec: int = 900,
    window_start: t.Optional[float] = None,
    window_end: t.Optional[float] = None,
    check_id: t.Optional[str] = None,
) -> PointInTimeHealthCheck:
    """FPF_HRT_SYSTEM_MEMORY_CHECK — HRT service system memory on RTP hosts.

    Postcheck: queries ODS for
    cgroup.slice.system.metalos.wds.hostreachtracker.memory.current
    (transform max()) across ``hosts`` for the test window and FAILs if any
    host's max exceeds ``threshold_gib`` (default 8 GiB). Each host is judged
    independently. Only explicitly provided params are emitted; the rest fall
    back to the health check's own defaults.
    """
    params: t.Dict[str, t.Any] = {
        "threshold_gib": threshold_gib,
        "lookback_sec": lookback_sec,
    }
    if hosts is not None:
        params["hosts"] = hosts
    if entity_desc is not None:
        params["entity_desc"] = entity_desc
    if key_desc is not None:
        params["key_desc"] = key_desc
    if threshold_bytes is not None:
        params["threshold_bytes"] = threshold_bytes
    if transform_desc is not None:
        params["transform_desc"] = transform_desc
    if window_start is not None:
        params["window_start"] = window_start
    if window_end is not None:
        params["window_end"] = window_end
    return PointInTimeHealthCheck(
        name=hc_types.CheckName.FPF_HRT_SYSTEM_MEMORY_CHECK,
        check_params=Params(json_params=json.dumps(params)),
        check_id=check_id,
    )


def create_fpf_hrt_driver_disconnect_check(
    hosts: t.Optional[t.List[str]] = None,
    entity_desc: t.Optional[str] = None,
    key_desc: t.Optional[str] = None,
    transform_desc: t.Optional[str] = None,
    expected_value: t.Optional[float] = None,
    lookback_sec: int = 900,
    window_start: t.Optional[float] = None,
    window_end: t.Optional[float] = None,
    check_id: t.Optional[str] = None,
) -> PointInTimeHealthCheck:
    """FPF_HRT_DRIVER_DISCONNECT_CHECK — HRT driver stays connected on RTP hosts.

    Postcheck: queries ODS for ``hrt.driver.created`` (transform min()) across
    ``hosts`` for the test window and FAILs if any host's gauge ever drops below
    ``expected_value`` (default 1.0), i.e. the HRT driver disconnected at least
    once. Each host is judged independently and every disconnect timestamp is
    surfaced. Only explicitly provided params are emitted; the rest fall back to
    the health check's own defaults.
    """
    params: t.Dict[str, t.Any] = {
        "lookback_sec": lookback_sec,
    }
    if hosts is not None:
        params["hosts"] = hosts
    if entity_desc is not None:
        params["entity_desc"] = entity_desc
    if key_desc is not None:
        params["key_desc"] = key_desc
    if transform_desc is not None:
        params["transform_desc"] = transform_desc
    if expected_value is not None:
        params["expected_value"] = expected_value
    if window_start is not None:
        params["window_start"] = window_start
    if window_end is not None:
        params["window_end"] = window_end
    return PointInTimeHealthCheck(
        name=hc_types.CheckName.FPF_HRT_DRIVER_DISCONNECT_CHECK,
        check_params=Params(json_params=json.dumps(params)),
        check_id=check_id,
    )


def create_fpf_host_spray_check(
    hosts: t.Optional[t.List[str]] = None,
    entity_desc: t.Optional[str] = None,
    key_desc: t.Optional[str] = None,
    transform_desc: t.Optional[str] = None,
    min_egress_gbps: t.Optional[float] = None,
    max_spread_gbps: t.Optional[float] = None,
    impacted_lanes_by_host: t.Optional[t.Dict[str, t.List[str]]] = None,
    impacted_max_gbps: t.Optional[float] = None,
    lookback_sec: int = 900,
    window_start: t.Optional[float] = None,
    window_end: t.Optional[float] = None,
    check_id: t.Optional[str] = None,
) -> PointInTimeHealthCheck:
    """FPF_HOST_SPRAY_CHECK — per-lane RDMA egress floor + spray fairness.

    Postcheck: queries ODS per-lane NIC tx rate
    (regex(system.beth[0123].tx-bytes-phy.rate), transform formula->Gbps,avg)
    across ``hosts`` for the test window, builds a host -> {lane -> avg Gbps}
    map, and asserts two signals:
      Signal 1: every lane exceeds ``min_egress_gbps`` (default from
        fpf_thresholds.ACTIVE: 75 Gbps temporary / 90 Gbps expected).
      Signal 2: per-host lane spread (max-min) stays within ``max_spread_gbps``
        (default 2 Gbps) — the spraying-fairness bound.
    Only explicitly provided params are emitted; the rest fall back to the
    health check's own defaults (which read fpf_thresholds.ACTIVE).
    """
    params: t.Dict[str, t.Any] = {
        "lookback_sec": lookback_sec,
    }
    if hosts is not None:
        params["hosts"] = hosts
    if entity_desc is not None:
        params["entity_desc"] = entity_desc
    if key_desc is not None:
        params["key_desc"] = key_desc
    if transform_desc is not None:
        params["transform_desc"] = transform_desc
    if min_egress_gbps is not None:
        params["min_egress_gbps"] = min_egress_gbps
    if max_spread_gbps is not None:
        params["max_spread_gbps"] = max_spread_gbps
    if impacted_lanes_by_host is not None:
        params["impacted_lanes_by_host"] = impacted_lanes_by_host
    if impacted_max_gbps is not None:
        params["impacted_max_gbps"] = impacted_max_gbps
    if window_start is not None:
        params["window_start"] = window_start
    if window_end is not None:
        params["window_end"] = window_end
    return PointInTimeHealthCheck(
        name=hc_types.CheckName.FPF_HOST_SPRAY_CHECK,
        check_params=Params(json_params=json.dumps(params)),
        check_id=check_id,
    )


def create_fpf_ods_counter_check(
    entity_desc: str,
    key_desc: str,
    validation_expr: str = "<= 10000",
    reduce_desc: str = "",
    transform_desc: str = "table(daily)",
    counter_name: str = "ODS counter",
    shorten_pass_url: bool = False,
    aggregate: t.Optional[str] = None,
    require: str = "all",
    informational: bool = False,
    check_id: t.Optional[str] = None,
) -> PointInTimeHealthCheck:
    """FPF ODS counter check — validates ODS counters across custom device list.

    Queries ODS for the specified key across all entities in entity_desc,
    applies reduce + transform, then validates each entity's result against
    the threshold. Uses test_case_start_time from the collector registry
    as the query window start.

    ``aggregate="max"`` + ``require`` change the semantics from "every sample on
    every entity must satisfy ``validation_expr``" to "each entity's PEAK over
    the window is judged, and the check passes if any (``require="any"``) or all
    (``require="all"``) entity peaks satisfy it". Use ``aggregate="max",
    require="any"`` for "assert a transient event happened on the impacted path"
    checks — e.g. in_discard loss during a disable/drain, where the counter is 0
    at most samples and only spikes on the impacted device.
    """
    params: t.Dict[str, t.Any] = {
        "entity_desc": entity_desc,
        "key_desc": key_desc,
        "validation_expr": validation_expr,
        "reduce_desc": reduce_desc,
        "transform_desc": transform_desc,
        "counter_name": counter_name,
        "shorten_pass_url": shorten_pass_url,
        "use_test_case_start_time": True,
        "sleep_timer": 0,
        "min_ods_query_duration": 0,
        # When True, a threshold breach is reported as an informational PASS
        # (logged + ODS link kept) instead of a hard FAIL. Used for expected
        # transient discards during a disruptive restart/coldboot.
        "informational": informational,
    }
    if aggregate is not None:
        params["aggregate"] = aggregate
        params["require"] = require
    return PointInTimeHealthCheck(
        name=hc_types.CheckName.GENERIC_ODS_CHECK,
        check_params=Params(json_params=json.dumps(params)),
        check_id=check_id,
    )
