# pyre-unsafe
"""Playbook factories for the OTG FBOSS BGP + platform hardening conveyor.

OTG-backend ports of a subset of
``taac/testconfigs/fboss_solution_tests/fboss_bgp_and_platform_hardening_conveyor.py``.

Seven port faithfully: the four service restarts,
test_bgp_malformed_packet_test, test_ecmp_group_overload_limit and
test_cpu_high_priority_queue_overload — though the malformed one uses a different
mechanism (byte-exact UPDATE injection via ``ixia.BgpUpdateSequence`` rather than
upstream's NEXT_HOP flag; see its factory and ``otg_bgp_malformed_updates.py``).

One is redesigned: ``test_otg_ecmp_member_overload_limit``.  Upstream's member
pressure came from a COOP patcher unavailable in OSS mode, so this generates it
from the OTG side — a real member-overload test, but not a reproduction, hence the
distinct name.
"""

import typing as t

from taac.health_check.health_check import types as hc_types
from taac.health_checks.healthcheck_definitions import (
    create_bgp_convergence_check,
    create_bgp_session_snapshot_check,
    create_device_core_dumps_check,
    create_ixia_packet_loss_check,
    create_service_restart_check,
)
from taac.stages.stage_definitions import create_steps_stage
from taac.steps.step_definitions import (
    create_ixia_api_step,
    create_longevity_step,
    create_service_convergence_step,
    create_service_interruption_step,
    create_service_restart_steps,
)
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import (
    Playbook,
    PointInTimeHealthCheck,
    Service,
)

# Device group naming.  The regexes the playbooks address and the names the
# test config assigns are defined together, HERE, and the config imports the
# builders below.  Keeping both halves in one place removes the possibility of
# drift: a mismatch would fail silently, because toggle_device_groups logs a
# warning, returns, and the playbook reports green having done nothing.
MEASURED_DEVICE_GROUP_PREFIX = "NO_PACKET_LOSS_EXPECTED"
ECMP_1_DEVICE_GROUP_PREFIX = "ECMP_1"
ECMP_2_DEVICE_GROUP_PREFIX = "ECMP_2"
MALFORMED_BGP_DEVICE_GROUP_PREFIX = "MALFORMED_BGP"

ECMP_2_DEVICE_GROUP_REGEX = ECMP_2_DEVICE_GROUP_PREFIX
MALFORMED_BGP_DEVICE_GROUP_REGEX = MALFORMED_BGP_DEVICE_GROUP_PREFIX


def device_group_name(prefix: str, port_index: int) -> str:
    """Name for a device group on `port_index` (0-based)."""
    return f"{prefix}_PORT{port_index + 1}"

# Flow name regex for the CPU control-plane flood.
HIGH_QUEUE_BGP_CP_TRAFFIC = "HIGH_QUEUE_BGP_CP_TRAFFIC"

# The upstream stage/step IDs are referenced verbatim by the CPU-queue
# snapshot checkpoints, so they are constants rather than inline literals.
CPU_QUEUE_STAGE_ID = "test_cpu_high_priority_queue_overload"
CPU_QUEUE_SETTLE_STEP_ID = "sleep_120_secs_after_disabling_bgp_cp_traffic"

# Services SERVICE_RESTART_CHECK asserts stayed ACTIVE during a restart.
#
# Deliberately NOT taac.health_checks.constants.SERVICES_TO_MONITOR_DURING_* —
# those are Meta-internal sets including `coop`, `openr`, `wedge_agent` and
# `fboss_hw_agent@0`, which need not exist on an OSS box; using them verbatim
# failed a live run on `coop`.  Override per DUT via `monitored_services`.
DEFAULT_MONITORED_SERVICES = (
    "fboss_sw_agent",
    "bgpd",
    "fsdb",
    "qsfp_service",
)


def _monitored_services(
    override: t.Optional[t.Sequence[str]],
    excluding: str,
) -> t.List[str]:
    """Services to assert stayed up, minus the one being restarted."""
    services = override if override is not None else DEFAULT_MONITORED_SERVICES
    return [svc for svc in services if svc != excluding]


# Default packet-loss tolerance on the measured path.  0.1% matches the
# existing OTG configs; the restart playbooks legitimately drop a few frames
# while the control plane reconverges.
DEFAULT_MAX_LOSS_PCT = "0.1"


def _packet_loss_check(
    max_loss_pct: str = DEFAULT_MAX_LOSS_PCT,
    clear_traffic_stats: bool = False,
) -> PointInTimeHealthCheck:
    """Assert measured-path loss stays at or below `max_loss_pct`."""
    return create_ixia_packet_loss_check(
        thresholds=[
            hc_types.PacketLossThreshold(
                str_value=max_loss_pct,
                metric=hc_types.PacketLossMetric.PERCENTAGE,
                expect_packet_loss=False,
            ),
        ],
        clear_traffic_stats=clear_traffic_stats,
    )


def _toggle_ecmp_2_step(enable: bool, sleep_before: int = 30):
    return create_ixia_api_step(
        api_name="toggle_device_groups",
        args_dict={
            "enable": enable,
            "device_group_name_regex": ECMP_2_DEVICE_GROUP_REGEX,
            "sleep_time_before_applying_change": sleep_before,
        },
    )


def _toggle_malformed_bgp_step(enable: bool, sleep_before: int = 0):
    return create_ixia_api_step(
        api_name="toggle_device_groups",
        args_dict={
            "enable": enable,
            "device_group_name_regex": MALFORMED_BGP_DEVICE_GROUP_REGEX,
            "sleep_time_before_applying_change": sleep_before,
        },
    )


def _enable_cp_traffic_step(enable: bool):
    return create_ixia_api_step(
        api_name="enable_traffic",
        args_dict={
            "regexes": [HIGH_QUEUE_BGP_CP_TRAFFIC],
            "enable": enable,
        },
    )


def _restore_measured_traffic_step():
    """Put the measured path back without restarting the flood.

    `enable_traffic` transmit-starts every flow it matches, so `regexes=None`
    would clear the disabled set *and* restart the CP flood.  The settle step
    both snapshot checks pivot on runs after this, so the "sessions recovered"
    reading would then be taken while the DUT is still being flooded -- the one
    condition under which it measures nothing.

    Naming the measured prefix uses the disable-non-matching semantics instead:
    the measured flows start and the flood is explicitly disabled and stopped.
    Without this the measured flows stay in `_disabled_flows` after the flood
    step and the profile depends on begin_test_case resetting state for whatever
    runs next, which is a reorder away from a silently dead measured path.
    """
    return create_ixia_api_step(
        api_name="enable_traffic",
        args_dict={
            "regexes": [MEASURED_DEVICE_GROUP_PREFIX],
            "enable": True,
        },
    )


def create_otg_agent_warmboot_playbook(
    iteration: int = 5,
    monitored_services: t.Optional[t.Sequence[str]] = None,
) -> Playbook:
    """test_agent_warmboot — repeated FBOSS agent warmboot.

    Warmboot semantics: no cold_boot_once file is created, so the agent
    restores state rather than reprogramming from scratch.
    """
    return Playbook(
        name="test_agent_warmboot",
        stages=[
            create_steps_stage(
                iteration=iteration,
                steps=create_service_restart_steps(
                    Service.FBOSS_SW_AGENT,
                    convergence_services=[Service.FBOSS_SW_AGENT, Service.BGP],
                ),
            ),
        ],
        postchecks=[
            create_bgp_convergence_check(fail_on_eor_expired=False),
            create_service_restart_check(
                _monitored_services(monitored_services, "fboss_sw_agent")
            ),
            _packet_loss_check(),
            create_device_core_dumps_check(),
        ],
    )


def create_otg_bgpd_restart_playbook(
    iteration: int = 5,
    monitored_services: t.Optional[t.Sequence[str]] = None,
) -> Playbook:
    """test_bgpd_restart — repeated BGP daemon restart."""
    return Playbook(
        name="test_bgpd_restart",
        stages=[
            create_steps_stage(
                iteration=iteration,
                steps=create_service_restart_steps(
                    Service.BGP,
                    convergence_services=[Service.FBOSS_SW_AGENT, Service.BGP],
                ),
            ),
        ],
        postchecks=[
            create_bgp_convergence_check(fail_on_eor_expired=False),
            create_service_restart_check(
                _monitored_services(monitored_services, "bgpd")
            ),
            _packet_loss_check(),
            create_device_core_dumps_check(),
        ],
    )


def create_otg_qsfp_service_restart_playbook(
    iteration: int = 5,
    monitored_services: t.Optional[t.Sequence[str]] = None,
) -> Playbook:
    """test_qsfp_service_restart — repeated optics daemon restart."""
    return Playbook(
        name="test_qsfp_service_restart",
        stages=[
            create_steps_stage(
                iteration=iteration,
                steps=[
                    create_service_interruption_step(
                        service=Service.QSFP_SERVICE,
                        trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                    ),
                    create_service_convergence_step(),
                ],
            ),
        ],
        postchecks=[
            create_service_restart_check(
                _monitored_services(monitored_services, "qsfp_service")
            ),
            _packet_loss_check(),
            create_device_core_dumps_check(),
        ],
    )


def create_otg_fsdb_restart_playbook(
    iteration: int = 5,
    monitored_services: t.Optional[t.Sequence[str]] = None,
) -> Playbook:
    """test_fsdb_restart — repeated fsdb restart.

    fsdb has no convergence step upstream; a short settle is enough.
    """
    return Playbook(
        name="test_fsdb_restart",
        stages=[
            create_steps_stage(
                iteration=iteration,
                steps=[
                    create_service_interruption_step(
                        service=Service.FSDB,
                        trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                    ),
                    create_longevity_step(duration=10),
                ],
            ),
        ],
        postchecks=[
            create_service_restart_check(
                _monitored_services(monitored_services, "fsdb")
            ),
            _packet_loss_check(),
            create_device_core_dumps_check(),
        ],
    )


# ---------------------------------------------------------------------------
# ECMP overload playbooks
# ---------------------------------------------------------------------------


def create_otg_ecmp_group_overload_limit_playbook(
    longevity_duration: int = 100,
) -> Playbook:
    """test_ecmp_group_overload_limit — faithful port.

    Bringing ECMP_2 up advertises a second set of next-hops for the shared
    aggregate, pushing the DUT's ECMP group table past its limit.  Upstream
    enables the device groups; OTG drives the same advertisement via BGP peer UP,
    which produces identical table pressure.
    """
    return Playbook(
        name="test_ecmp_group_overload_limit",
        iteration=1,
        stages=[
            create_steps_stage(
                steps=[
                    _toggle_ecmp_2_step(enable=True),
                    create_longevity_step(duration=longevity_duration),
                ],
            ),
        ],
        cleanup_steps=[
            _toggle_ecmp_2_step(enable=False),
        ],
        postchecks=[
            _packet_loss_check(),
            create_device_core_dumps_check(),
        ],
    )


def create_otg_ecmp_member_overload_limit_playbook(
    longevity_duration: int = 600,
    monitored_services: t.Optional[t.Sequence[str]] = None,
) -> Playbook:
    """test_otg_ecmp_member_overload_limit — REDESIGNED, not an upstream port.

    Upstream drives member count past the limit with mass static routes from a
    COOP patcher, unavailable in OSS mode; stripping those steps would leave this
    indistinguishable from the group test.  Instead the pressure comes from the
    OTG side: ECMP_2 is scaled so each aggregate prefix accrues many next-hops,
    keeping members high while group count stays flat.

    Relies on the platform's default member limit, so the crossing point depends
    on the DUT.
    """
    return Playbook(
        name="test_otg_ecmp_member_overload_limit",
        iteration=1,
        stages=[
            create_steps_stage(
                steps=[
                    _toggle_ecmp_2_step(enable=True),
                    create_longevity_step(duration=longevity_duration),
                    create_service_interruption_step(
                        service=Service.FBOSS_SW_AGENT,
                        trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                    ),
                    create_service_convergence_step(
                        services=[Service.FBOSS_SW_AGENT, Service.BGP],
                    ),
                ],
            ),
        ],
        cleanup_steps=[
            _toggle_ecmp_2_step(enable=False),
        ],
        postchecks=[
            create_service_restart_check(
                _monitored_services(monitored_services, "fboss_sw_agent")
            ),
            # The agent restarts with the aggregate's next-hop count elevated, so
            # forwarding through it is the thing worth measuring.  Without this the
            # test would pass on services being up and no core dumps even if the
            # restart black-holed every ECMP-routed prefix.
            _packet_loss_check(),
            create_device_core_dumps_check(),
        ],
    )


# ---------------------------------------------------------------------------
# BGP malformed packet handling
# ---------------------------------------------------------------------------


def create_otg_bgp_malformed_packet_test_playbook(
    rogue_parent_prefixes_to_ignore: t.Optional[t.List[str]] = None,
    soak_duration: int = 300,
    iteration: int = 2,
) -> Playbook:
    """test_bgp_malformed_packet_test — ported via raw BGP UPDATE injection.

    Upstream's ``bounce_bgp_next_hop_attribute(enable=False)`` has no counterpart:
    route ranges describe only *conformant* BGP (``next_hop_mode`` is
    ``local_ip``/``manual``, nothing omits a mandatory attribute), so the state it
    produces cannot be expressed at all.  Unlike the mutation-granularity limits
    the ECMP and CPU-queue playbooks work around, this class has an escape hatch:
    ``peer.replay_updates.raw_bytes`` sends arbitrary UPDATE bytes through the
    emulated speaker's session.  The config attaches such a sequence
    (``ixia.BgpUpdateSequence``) to a dedicated MALFORMED_BGP group — more precise
    than upstream's flag, since the exact RFC violation is authored deliberately.
    See README.md, "BGP and OTG: classes of limitation".

    OTG replays the sequence on every session establishment, so toggling that
    group up IS the trigger: no ``set_config``, and the measured path is
    untouched.  The malformed peer is separate from the measured path for that
    reason — flapping the measured peer would invalidate its own packet-loss
    postcheck.

    Asserts (RFC mapping in otg_bgp_malformed_updates): bgpd does not crash; the
    DUT does not tear down UNRELATED sessions over one peer's bad input — the real
    hardening claim; the measured path keeps forwarding.

    Does NOT assert that the malformed routes were rejected rather than installed
    — that needs DUT-side RIB inspection.
    """
    ignore = rogue_parent_prefixes_to_ignore or []
    return Playbook(
        name="test_bgp_malformed_packet_test",
        iteration=iteration,
        stages=[
            create_steps_stage(
                steps=[
                    # Establishing the session replays the UPDATE suite.
                    _toggle_malformed_bgp_step(enable=True),
                    create_longevity_step(duration=soak_duration),
                    _toggle_malformed_bgp_step(enable=False),
                    create_longevity_step(duration=60),
                ],
            ),
        ],
        cleanup_steps=[
            _toggle_malformed_bgp_step(enable=False),
        ],
        snapshot_checks=[
            # The malformed peer is expected to come and go; the measured peers
            # are not, so its own churn is excluded from the flap assertion.
            create_bgp_session_snapshot_check(
                parent_prefixes_to_ignore=ignore,
            ),
        ],
        postchecks=[
            create_bgp_convergence_check(fail_on_eor_expired=False),
            _packet_loss_check(),
            create_device_core_dumps_check(),
        ],
    )


# ---------------------------------------------------------------------------
# CPU high-priority queue overload
# ---------------------------------------------------------------------------


def create_otg_cpu_high_priority_queue_overload_playbook(
    rogue_parent_prefixes_to_ignore: t.Optional[t.List[str]] = None,
    flood_duration: int = 150,
    settle_duration: int = 120,
) -> Playbook:
    """test_cpu_high_priority_queue_overload — faithful port.

    Floods the CPU high-priority queue with frames shaped like BGP control-plane
    traffic (dst MAC = DUT MAC, TCP/179, DSCP 48), then checks the queue protected
    the real sessions: the pre-settle snapshot asserts they did NOT flap, the
    post-settle one (flap check skipped) that they recovered.

    `enable_traffic` with a regex also stops every non-matching flow, matching
    restpy — so the measured path is down for the duration and this asserts on
    session state, not packet loss.  Hence no packet-loss postcheck.

    Stage and settle-step IDs come from module constants because the snapshot
    checkpoints reference them verbatim.
    """
    ignore = rogue_parent_prefixes_to_ignore or []
    return Playbook(
        name="test_cpu_high_priority_queue_overload",
        snapshot_checks=[
            create_bgp_session_snapshot_check(
                parent_prefixes_to_ignore=ignore,
                pre_snapshot_checkpoint_id=(
                    f"stage.{CPU_QUEUE_STAGE_ID}.step."
                    f"{CPU_QUEUE_SETTLE_STEP_ID}.end"
                ),
            ),
            create_bgp_session_snapshot_check(
                skip_flap_check=True,
                parent_prefixes_to_ignore=ignore,
                post_snapshot_checkpoint_id=(
                    f"stage.{CPU_QUEUE_STAGE_ID}.step."
                    f"{CPU_QUEUE_SETTLE_STEP_ID}.end"
                ),
            ),
        ],
        stages=[
            create_steps_stage(
                stage_id=CPU_QUEUE_STAGE_ID,
                steps=[
                    _enable_cp_traffic_step(enable=True),
                    create_longevity_step(duration=flood_duration),
                    _enable_cp_traffic_step(enable=False),
                    _restore_measured_traffic_step(),
                    create_longevity_step(
                        duration=settle_duration,
                        step_id=CPU_QUEUE_SETTLE_STEP_ID,
                    ),
                    create_ixia_api_step(
                        api_name="clear_traffic_stats",
                        args_dict={},
                    ),
                ],
            ),
        ],
        postchecks=[
            create_device_core_dumps_check(),
        ],
    )


def create_otg_hardening_playbooks(
    process_restart_iterations: int = 5,
    rogue_parent_prefixes_to_ignore: t.Optional[t.List[str]] = None,
    monitored_services: t.Optional[t.Sequence[str]] = None,
) -> t.List[Playbook]:
    """Build the full OTG hardening playbook list, in execution order.

    Restarts run first so the disruptive ECMP and CPU-queue tests operate on
    a DUT already known to survive process churn.


    NOTE: these eight together exceed ixia-c community edition's cap of 4
    control-plane interfaces and 4 sessions -- the profiles exist precisely
    because no single config can host them all.  Use this only for a licensed
    deployment, or to iterate over the factories (as the tests do); pairing the
    full list with one test config is rejected with an opaque HTTP 500 at
    set_config.
    """
    return [
        create_otg_agent_warmboot_playbook(
            iteration=process_restart_iterations,
            monitored_services=monitored_services,
        ),
        create_otg_bgpd_restart_playbook(
            iteration=process_restart_iterations,
            monitored_services=monitored_services,
        ),
        create_otg_qsfp_service_restart_playbook(
            iteration=process_restart_iterations,
            monitored_services=monitored_services,
        ),
        create_otg_fsdb_restart_playbook(
            iteration=process_restart_iterations,
            monitored_services=monitored_services,
        ),
        create_otg_bgp_malformed_packet_test_playbook(
            rogue_parent_prefixes_to_ignore=rogue_parent_prefixes_to_ignore,
        ),
        create_otg_ecmp_group_overload_limit_playbook(),
        create_otg_ecmp_member_overload_limit_playbook(),
        create_otg_cpu_high_priority_queue_overload_playbook(
            rogue_parent_prefixes_to_ignore=rogue_parent_prefixes_to_ignore,
        ),
    ]
