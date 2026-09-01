# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe

"""Consolidated FPF "shared-injection" umbrella suite.

Today every per-disruption FPF config re-injects the 8-plane VF-group prefixes at
setup and withdraws them at teardown, paying the inject + settle cost ONCE PER
DISRUPTION. This umbrella inverts that: it injects the two VF prefix groups on all
8 STSW planes ONCE at setup, runs MANY disruption playbooks back-to-back (each
preserving that single injection via ``skip_injection=True``), then withdraws the
injection ONCE at teardown.

It folds in only the disruptions that PRESERVE the shared STSW injection — i.e.
GTSW-side / host-side disruptions whose recovery leaves the STSW advertisements
intact. It deliberately EXCLUDES the configs that re-advertise, wipe, scale, or
otherwise mutate the shared injection (tc35/36/54 STSW drains; tc45/46 scale) —
those remain standalone.

The setup/teardown and per-playbook builder calls mirror the source configs
faithfully (same disruption_steps, same flags). Each playbook keeps its source
config's playbook_name so results stay attributable. The playbooks are ordered
least-destructive -> most-destructive.

Setup difference vs. the canonical tc41 pattern: ``settle_sec=300`` on the
inject task (matches the per-config value — needed for the first few playbooks to
not trip BGP_SESSION_ESTABLISH on an under-settled fabric), and the collectors
task enables the FSDB-session collector (a superset) because the kill / reboot /
hrt playbooks
(tc28/39/49/50/51/52/55) assert against it.

Usage:
  TAAC_SSH_VIA_LAB_SSH=1 buck2 run neteng/netcastle:netcastle_taac -- \\
    --team taac --test-config fpf_shared_injection_suite \\
    --dev --skip-basset-reservation --skip-testbed-isolation \\
    --debug --continue-on-precheck-failure --skip-fboss-rsyslog
"""

import os

from taac.libs.fpf.fpf_prod_prefix_map import get_prefix
from taac.playbooks.playbook_definitions import (
    create_fpf_disrupt_window_playbook,
    create_fpf_hardening_playbook_v2,
    create_fpf_link_event_disrupt_playbook,
    create_fpf_service_restart_playbook,
)
from taac.steps.step_definitions import (
    create_fpf_drain_interface_step,
    create_fpf_ndp_clear_loop_step,
    create_fpf_record_disruption_time_step,
    create_fpf_record_restart_completion_time_step,
    create_fpf_record_restart_time_step,
    create_fpf_repeated_service_crash_step,
    create_fpf_restart_hrt_step,
    create_fpf_set_interface_admin_step,
    create_fpf_verify_disruption_step,
    create_longevity_step,
    create_service_convergence_step,
    create_service_interruption_step,
    create_system_reboot_step,
)
from taac.task_definitions import (
    create_fpf_inject_vf_groups_task,
    create_fpf_restart_service_task,
    create_fpf_start_collectors_task,
    create_fpf_stop_collectors_task,
    create_fpf_withdraw_vf_groups_task,
)
from taac.testconfigs.fpf.fpf_hardening_common import (
    ALL_STSWS,
    ALLOW_BASELINE_FAILURES,
    Circuit,
    create_fpf_endpoints,
    DEFAULT_COMMUNITY_LIST,
    disable_interfaces_by_device,
    EXPECTED_FSDB_SESSION_COUNT,
    fpf_hrt_device_ids,
    fpf_hrt_lanes,
    fpf_hrt_vf_device_ids,
    fpf_ib_traffic_config,
    fpf_ib_traffic_tasks,
    fpf_rf_vf_groups,
    fpf_vf_injection_groups,
    FpfIbTrafficConfig,
    FSDB_COLLECTOR_MODE,
    GPU_HOSTS,
    HRT_MEMORY_HOSTS,
    impacted_lanes_by_host_gpu,
    num_disrupted_circuits,
    OBSERVER_GTSWS,
    skip_ib_traffic,
    skip_ssh_dependencies,
    SPRAY_HOSTS,
    TRIGGER_STSWS,
    VF_COLLECTOR_SUBNET,
    VF_GROUP_PREFIX_COUNT,
)
from taac.testconfigs.fpf.fpf_kill_contract import (
    build_kill_disrupt_postchecks,
)
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import TestConfig

# ---------------------------------------------------------------------------
# Shared module constants (identical to the per-disruption source configs).
# ---------------------------------------------------------------------------
# 8-plane VF-group injection (VF1 5000:dd on s001-s004 = planes 0-3, VF2 5000:ee
# on s005-s008 = planes 4-7); injected ONCE by the setup task, withdrawn ONCE in
# teardown, so every playbook passes skip_injection=True.
INJECTION_GROUPS = fpf_vf_injection_groups()
PREFIX_COUNT = VF_GROUP_PREFIX_COUNT
INJECTED_LANES = fpf_hrt_lanes()
HRT_DEVICE_IDS = fpf_hrt_device_ids()
HRT_VF_DEVICE_IDS = fpf_hrt_vf_device_ids(HRT_DEVICE_IDS)
IB_TRAFFIC_CONFIG = fpf_ib_traffic_config()
FSDB_GLOBAL_LANE0_TUPLES = (
    {
        host: {str(device_id): [0] for device_id in HRT_VF_DEVICE_IDS[0]}
        for host in GPU_HOSTS
    }
    if HRT_DEVICE_IDS != [0]
    else {}
)
RF_VF_GROUPS = fpf_rf_vf_groups(
    active_lanes=INJECTED_LANES,
    device_ids_by_vf=(HRT_VF_DEVICE_IDS if HRT_DEVICE_IDS != [0] else None),
)


def _ib_readiness_config(
    spray: list[str] | None,
) -> FpfIbTrafficConfig | None:
    """Return the setup-identical traffic contract only when traffic is enabled."""
    return IB_TRAFFIC_CONFIG if spray else None


# Settle after the ONE shared STSW injection, before the first playbook's
# prechecks. Observed convergence is <10s end-to-end (BGP RIB + FSDB ribMap reach
# 1000 in ~7-8s on every GTSW; HRT sessions 32/32), so 30s is ~3x margin and is
# enough. Overridable via FPF_INJECT_SETTLE_SEC for tuning / re-validation.
# (History: was 120s, briefly 300s to paper over first-few-playbook
# BGP_SESSION_ESTABLISH flakiness under heavy back-to-back churn; reduced 300->60
# then 60->30 permanently — 30s validated on single-case --regex runs on a clean
# fabric. Bump via FPF_INJECT_SETTLE_SEC if a precheck flakes on a churned fabric.)
INJECT_SETTLE_SEC = int(os.environ.get("FPF_INJECT_SETTLE_SEC", "30"))

PROD_PREFIX_HOST = GPU_HOSTS[0]
# Production-prefix recovery remains a deliberately narrow dev0 canary. Bulk
# injected-prefix and remote-failure checks cover every configured HRT device.
PROD_PREFIX_DEVICE_ID = 0
PROD_PREFIXES = [get_prefix(PROD_PREFIX_HOST, PROD_PREFIX_DEVICE_ID)]

# The DUT GTSW (gtsw001) owns lane 0; all GTSW-side disruptions target it.
DUT_GTSW = OBSERVER_GTSWS[0]

# Restart / link-event source configs advertise on (and clear from) all 8 STSWs.
ALL_STSW_TRIGGERS = ALL_STSWS

# ---------------------------------------------------------------------------
# Circuit list (the GTSW<->GPU link the link-event playbooks drive) — identical
# to tc15/tc16/tc17/tc19. gtsw001 -> lane 0, rtptest1555 GPU0 beth0.
# (rtptest1555 hangs off eth1/45/x on each GTSW; the retired rtptest1544 used eth1/41/x.)
# ---------------------------------------------------------------------------
CIRCUITS = [
    Circuit(
        a_end_device=OBSERVER_GTSWS[0],
        a_end_interface="eth1/45/5",
        z_end_device=GPU_HOSTS[0],
        z_end_gpu_id=0,
    ),
]


def _impacted_beths_by_host(circuits: list[Circuit]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for c in circuits:
        out.setdefault(c.z_end_device, [])
        if c.nic_interface not in out[c.z_end_device]:
            out[c.z_end_device].append(c.nic_interface)
    return {h: sorted(v) for h, v in sorted(out.items())}


def _impacted_planes_by_host(circuits: list[Circuit]) -> dict[str, list[int]]:
    out: dict[str, list[int]] = {}
    for c in circuits:
        out.setdefault(c.z_end_device, [])
        if c.lane not in out[c.z_end_device]:
            out[c.z_end_device].append(c.lane)
    return {h: sorted(v) for h, v in sorted(out.items())}


# ===========================================================================
# Per-source-config playbook builders. Each returns one (or two) Playbook(s),
# faithfully reproducing the source config's disruption_steps + flags. All pass
# skip_injection=True so the single shared injection is preserved.
# ===========================================================================


def _tc41_baseline(*, spray) -> list:
    """tc41: pristine longevity baseline (no disruption)."""
    skip_ssh = skip_ssh_dependencies()
    return [
        create_fpf_hardening_playbook_v2(
            gtsws=OBSERVER_GTSWS,
            hosts=GPU_HOSTS,
            trigger_stsws=TRIGGER_STSWS,
            soak_duration_sec=300,
            stabilization_delay_sec=300,
            prefix_count=PREFIX_COUNT,
            community_list=DEFAULT_COMMUNITY_LIST,
            playbook_name="fpf_tc41_longevity_pristine",
            prod_prefixes=PROD_PREFIXES,
            skip_ssh_dependent_checks=skip_ssh,
            fsdb_expected_total=EXPECTED_FSDB_SESSION_COUNT,
            hrt_memory_hosts=HRT_MEMORY_HOSTS,
            hrt_driver_hosts=HRT_MEMORY_HOSTS,
            spray_hosts=spray,
            ib_traffic_config=_ib_readiness_config(spray),
            skip_injection=True,
            rf_vf_groups=RF_VF_GROUPS,
            lanes=INJECTED_LANES,
        )
    ]


def _gr_playbook(
    *,
    spray,
    service: taac_types.Service,
    name: str,
    wait_sec: int,
    wait_desc: str,
    convergence_timeout: int,
    reconvergence_service: str,
    convergence_blip_mode: str = "strict",
    additional_postchecks: list | None = None,
    extra_steps_pre: list | None = None,
    gr_beyond: bool = False,
) -> list:
    """tc05/06/07/08: BGP/FSDB graceful-restart within/beyond window.

    The affected BGP/FSDB RIB uses its restart-aware recovery contract.
    ``convergence_blip_mode`` selects the two-mode blip-handling contract for
    the unaffected RIB, HRT bulk/remote-failure, and prod-prefix checks:
    GR-within (tc05/tc07) is graceful -> "skip_null_strict" (MODE B);
    GR-beyond (tc06/tc08) purges routes past the window -> "last_sample"
    (MODE A).
    """
    skip_ssh = skip_ssh_dependencies()
    disruption_steps = list(extra_steps_pre or [])
    disruption_steps += [
        create_service_interruption_step(
            service=service,
            trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_STOP,
            description=f"Stop {service.name} on DUT GTSW",
        ),
        create_longevity_step(duration=wait_sec, description=wait_desc),
    ]
    if service == taac_types.Service.BGP:
        # This GR shape has no separate pre-stop disruption window, so its
        # existing disruption timestamp can anchor BGP RIB recovery.
        disruption_steps.append(
            create_fpf_record_disruption_time_step(
                description="Record BGP restart time for RIB reconvergence SLA"
            )
        )
    elif service == taac_types.Service.FSDB:
        # Keep tc08's pre-stop disruption timestamp intact for its drain-window
        # check while anchoring FSDB ribMap recovery immediately before START.
        disruption_steps.append(
            create_fpf_record_restart_time_step(
                description="Record FSDB restart time for ribMap reconvergence SLA"
            )
        )
    disruption_steps += [
        create_service_interruption_step(
            service=service,
            trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_START,
            description=f"Restart {service.name} on DUT GTSW",
        ),
        create_service_convergence_step(
            services=[service],
            timeout=convergence_timeout,
            description=f"Wait for {service.name} convergence after restart",
        ),
    ]
    if gr_beyond:
        # GR-BEYOND ONLY: holding the service down past the GR window purges
        # routes, so the data-plane recovery ramp (beth egress re-spray, HRT
        # plane-status, prod-prefix reachability) takes real time AFTER restart —
        # measured ~73s for bgp (tc06) and ~113s for fsdb (tc08, beth0 back to
        # line rate at +113s). SERVICE_CONVERGENCE only waits ~5s for the
        # process/BGP to converge, so without a settle the point-in-time
        # postchecks (host-spray floor, prod-prefix compliance) sample the
        # recovery transient and false-fail. 150s covers both bgp and fsdb
        # recovery with comfortable margin. GR-within is graceful (routes
        # retained) and needs no settle.
        disruption_steps.append(
            create_longevity_step(
                duration=150,
                description=(
                    f"Settle 150s after {service.name} restart+convergence before "
                    f"postchecks (GR-beyond data-plane recovery ramp)"
                ),
            )
        )
    return [
        create_fpf_hardening_playbook_v2(
            gtsws=OBSERVER_GTSWS,
            hosts=GPU_HOSTS,
            trigger_stsws=TRIGGER_STSWS,
            disruption_steps=disruption_steps,
            stabilization_delay_sec=300,
            prefix_count=PREFIX_COUNT,
            community_list=DEFAULT_COMMUNITY_LIST,
            additional_postchecks=additional_postchecks,
            playbook_name=name,
            prod_prefixes=PROD_PREFIXES,
            skip_ssh_dependent_checks=skip_ssh,
            fsdb_expected_total=EXPECTED_FSDB_SESSION_COUNT,
            hrt_memory_hosts=HRT_MEMORY_HOSTS,
            hrt_driver_hosts=HRT_MEMORY_HOSTS,
            spray_hosts=spray,
            ib_traffic_config=_ib_readiness_config(spray),
            skip_injection=True,
            rf_vf_groups=RF_VF_GROUPS,
            lanes=INJECTED_LANES,
            assert_bgp_reconvergence=True,
            reconvergence_service=reconvergence_service,
            reconvergence_sla_sec=60.0,
            reconvergence_hosts=[OBSERVER_GTSWS[0]],
            bgp_rib_restart_reconverge=(service == taac_types.Service.BGP),
            fsdb_rib_restart_reconverge=(service == taac_types.Service.FSDB),
            skip_fsdb_session_postcheck=True,
            convergence_blip_mode=convergence_blip_mode,
            # GR-BEYOND ONLY: holding the service down past the GR window purges
            # routes, so non-congestion in_dst_null + in_discard on the fabric are
            # EXPECTED transient loss, not a regression — report them
            # informationally (captured + ODS link kept, no hard FAIL). GR-within
            # is graceful (routes retained) so it keeps these HARD. Congestion
            # discards stay hard in both; recovery is still gated by the
            # plane-status / host-spray / prod-prefix / convergence checks.
            ods_discard_informational=gr_beyond,
        )
    ]


def _tc05(*, spray) -> list:
    return _gr_playbook(
        spray=spray,
        service=taac_types.Service.BGP,
        name="fpf_tc05_bgp_gr_within_window",
        wait_sec=90,
        wait_desc="Wait 90s (within 120s GR window)",
        convergence_timeout=300,
        reconvergence_service="bgpd",
        convergence_blip_mode="skip_null_strict",
    )


def _tc06(*, spray) -> list:
    return _gr_playbook(
        spray=spray,
        service=taac_types.Service.BGP,
        name="fpf_tc06_bgp_gr_beyond_window",
        wait_sec=180,
        wait_desc="Wait 180s (beyond 120s GR window — routes purged)",
        convergence_timeout=600,
        reconvergence_service="bgpd",
        convergence_blip_mode="last_sample",
        gr_beyond=True,
    )


def _tc07(*, spray) -> list:
    return _gr_playbook(
        spray=spray,
        service=taac_types.Service.FSDB,
        name="fpf_tc07_fsdb_gr_within_window",
        wait_sec=90,
        wait_desc="Wait 90s (within 120s GR window)",
        convergence_timeout=300,
        reconvergence_service="fsdb",
        convergence_blip_mode="skip_null_strict",
    )


def _tc08(*, spray) -> list:
    # tc08 records the disruption time first and adds a host-spray postcheck over
    # the post-GR tail asserting lane0 (beth0) drained while lanes1-3 spray.
    from taac.health_checks.healthcheck_definitions import (
        create_fpf_host_spray_check,
    )

    gr_window_sec = 120
    stop_duration_sec = gr_window_sec + 120  # 240s
    postchecks = []
    if spray:
        postchecks.append(
            create_fpf_host_spray_check(
                hosts=SPRAY_HOSTS,
                min_egress_gbps=75.0,
                impacted_lanes_by_host={h: ["beth0"] for h in SPRAY_HOSTS},
                impacted_max_gbps=10.0,
                window_from_disruption_time=True,
                window_offset_sec=gr_window_sec,
                window_duration_sec=stop_duration_sec - gr_window_sec,
                label="[fsdb-stop >GR] lane0(beth0) drained <10G; lanes1-3 spray >75G",
                check_id="fpf_tc08_host_spray_lane0_drained",
            )
        )
    return _gr_playbook(
        spray=spray,
        service=taac_types.Service.FSDB,
        name="fpf_tc08_fsdb_gr_beyond_window",
        wait_sec=stop_duration_sec,
        wait_desc=(
            f"Hold FSDB down {stop_duration_sec}s "
            f"(>{gr_window_sec}s GR window — lane-0 routes purge, beth0 drains)"
        ),
        convergence_timeout=600,
        reconvergence_service="fsdb",
        convergence_blip_mode="last_sample",
        gr_beyond=True,
        additional_postchecks=postchecks,
        extra_steps_pre=[
            create_fpf_record_disruption_time_step(
                description=(
                    "Record FSDB-stop disruption time (anchors the spray window)"
                )
            ),
        ],
    )


def _service_restart_playbook(
    *,
    spray,
    skip_ssh,
    service: taac_types.Service,
    name: str,
    affected_rib: str,
    settle_after_restart_sec: int,
    reconvergence_sla_sec: float,
    create_cold_boot_file: bool = False,
    stable_settle_sec: int = 0,
    bgp_reconverge_sla_sec: float | None = None,
    skip_fsdb_session_postcheck: bool = False,
) -> list:
    """tc04/23/24/25/27: service restart / warmboot / coldboot."""
    return [
        create_fpf_service_restart_playbook(
            gtsws=OBSERVER_GTSWS,
            hosts=GPU_HOSTS,
            trigger_stsws=ALL_STSW_TRIGGERS,
            service=service,
            restart_device_regexes=[DUT_GTSW],
            affected_rib=affected_rib,
            create_cold_boot_file=create_cold_boot_file,
            prefix_count=PREFIX_COUNT,
            community_list=DEFAULT_COMMUNITY_LIST,
            injected_lanes=INJECTED_LANES,
            prod_prefixes=PROD_PREFIXES,
            hrt_memory_hosts=HRT_MEMORY_HOSTS,
            hrt_driver_hosts=HRT_MEMORY_HOSTS,
            fsdb_expected_total=EXPECTED_FSDB_SESSION_COUNT,
            stabilization_delay_sec=120,
            settle_after_restart_sec=settle_after_restart_sec,
            stable_settle_sec=stable_settle_sec,
            bgp_reconverge_sla_sec=bgp_reconverge_sla_sec,
            skip_ssh_dependent_checks=skip_ssh,
            spray_hosts=spray,
            ib_traffic_config=_ib_readiness_config(spray),
            skip_injection=True,
            rf_vf_groups=RF_VF_GROUPS,
            assert_bgp_reconvergence=True,
            reconvergence_sla_sec=reconvergence_sla_sec,
            skip_fsdb_session_postcheck=skip_fsdb_session_postcheck,
            playbook_name=name,
        )
    ]


def _tc23(*, spray, skip_ssh) -> list:
    return _service_restart_playbook(
        spray=spray,
        skip_ssh=skip_ssh,
        service=taac_types.Service.BGP,
        name="fpf_tc23_bgp_restart",
        affected_rib="bgp",
        settle_after_restart_sec=120,
        reconvergence_sla_sec=60.0,
    )


def _tc24(*, spray, skip_ssh) -> list:
    return _service_restart_playbook(
        spray=spray,
        skip_ssh=skip_ssh,
        service=taac_types.Service.FSDB,
        name="fpf_tc24_fsdb_restart",
        affected_rib="fsdb",
        settle_after_restart_sec=60,
        reconvergence_sla_sec=60.0,
        skip_fsdb_session_postcheck=True,
    )


def _tc25(*, spray, skip_ssh) -> list:
    return _service_restart_playbook(
        spray=spray,
        skip_ssh=skip_ssh,
        service=taac_types.Service.AGENT,
        name="fpf_tc25_wedge_agent_restart",
        affected_rib="bgp",
        settle_after_restart_sec=120,
        reconvergence_sla_sec=90.0,
    )


def _tc04(*, spray, skip_ssh) -> list:
    return _service_restart_playbook(
        spray=spray,
        skip_ssh=skip_ssh,
        service=taac_types.Service.AGENT,
        name="fpf_tc04_wedge_agent_warmboot",
        affected_rib="bgp",
        create_cold_boot_file=False,
        settle_after_restart_sec=120,
        reconvergence_sla_sec=90.0,
    )


def _tc27(*, spray, skip_ssh) -> list:
    return _service_restart_playbook(
        spray=spray,
        skip_ssh=skip_ssh,
        service=taac_types.Service.AGENT,
        name="fpf_tc27_agent_coldboot",
        affected_rib="bgp",
        create_cold_boot_file=True,
        settle_after_restart_sec=360,
        stable_settle_sec=300,
        bgp_reconverge_sla_sec=300.0,
        reconvergence_sla_sec=240.0,
    )


def _kill_playbooks(
    *,
    spray,
    skip_ssh,
    killed_service: str,
    kill_service: taac_types.Service,
    disrupt_name: str,
    longevity_name: str,
    kill_every_sec: int,
    kill_duration_sec: int,
    longevity_settle_sec: int,
) -> list:
    """tc49/50/51: graceful loop-kill (disrupt + longevity v2)."""
    stabilization_delay_sec = 120
    stable_after_kill_sec = 120
    longevity_soak_sec = 300
    session_lookback_sec = 1000

    is_agent_kill = killed_service == "wedge_agent"
    is_fsdb_kill = killed_service == "fsdb"

    disrupt_steps = [
        create_longevity_step(
            duration=stabilization_delay_sec,
            description=f"Stabilize {stabilization_delay_sec}s before the kill loop",
        ),
        create_fpf_record_disruption_time_step(
            description=f"Record {killed_service}-kill disruption time"
        ),
        create_fpf_repeated_service_crash_step(
            service=kill_service,
            every_sec=kill_every_sec,
            duration_sec=kill_duration_sec,
            device_regexes=[DUT_GTSW],
            description=(
                f"SIGKILL {kill_service.name} every {kill_every_sec}s for "
                f"{kill_duration_sec}s on {DUT_GTSW}"
            ),
        ),
        create_longevity_step(
            duration=stable_after_kill_sec,
            description=f"Stable {stable_after_kill_sec}s after the kill loop stops",
        ),
    ]
    disrupt_playbook = create_fpf_disrupt_window_playbook(
        playbook_name=disrupt_name,
        disruption_steps=disrupt_steps,
        spray_hosts=spray,
        ib_traffic_config=_ib_readiness_config(spray),
        postchecks=build_kill_disrupt_postchecks(
            killed_service=killed_service,
            observer_gtsws=OBSERVER_GTSWS,
            hrt_memory_hosts=HRT_MEMORY_HOSTS,
            spray_hosts=spray,
            kill_duration_sec=kill_duration_sec,
            prefix_count=PREFIX_COUNT,
            skip_ssh=skip_ssh,
            expected_fsdb_total=EXPECTED_FSDB_SESSION_COUNT,
            session_lookback_sec=session_lookback_sec,
            out_congestion_informational=(is_agent_kill or is_fsdb_kill),
        ),
    )
    longevity_playbook = create_fpf_hardening_playbook_v2(
        gtsws=OBSERVER_GTSWS,
        hosts=GPU_HOSTS,
        trigger_stsws=TRIGGER_STSWS,
        soak_duration_sec=longevity_soak_sec,
        stabilization_delay_sec=0,
        prefix_count=PREFIX_COUNT,
        community_list=DEFAULT_COMMUNITY_LIST,
        playbook_name=longevity_name,
        prod_prefixes=PROD_PREFIXES,
        skip_ssh_dependent_checks=skip_ssh,
        fsdb_expected_total=EXPECTED_FSDB_SESSION_COUNT,
        hrt_memory_hosts=HRT_MEMORY_HOSTS,
        hrt_driver_hosts=HRT_MEMORY_HOSTS,
        spray_hosts=spray,
        ib_traffic_config=_ib_readiness_config(spray),
        convergence_settle_sec=longevity_settle_sec,
        skip_injection=True,
        rf_vf_groups=RF_VF_GROUPS,
        lanes=INJECTED_LANES,
        out_congestion_last_minute_max=is_agent_kill,
        remote_failure_last_n=is_agent_kill,
        host_spray_transform_desc=(
            "formula(/ $1 125000000),latest(3),max" if is_fsdb_kill else None
        ),
        recovery_last_n=(10 if is_fsdb_kill else None),
    )
    return [disrupt_playbook, longevity_playbook]


def _fsdb_kill_window_playbooks(
    *,
    spray,
    skip_ssh,
    disrupt_name: str,
    longevity_name: str,
    kill_duration_sec: int,
    session_lookback_sec: int,
    add_kill_window_spray: bool,
    longevity_host_spray_label: str,
) -> list:
    """tc28/39: unclean SIGKILL of fsdb (disrupt + longevity v2).

    Both use the HRT session-stat disruption postcheck (32 -> 28 on lane 0 ->
    recover). tc39 additionally adds a kill-window host-spray (beth0 drained) and
    labels the longevity host-spray.
    """
    from taac.health_checks.healthcheck_definitions import (
        create_fpf_host_spray_check,
        create_fpf_hrt_session_stat_check,
    )

    stabilization_delay_sec = 120
    stable_after_kill_sec = 120
    longevity_soak_sec = 300
    recovery_min_sec = 60
    connected_during = EXPECTED_FSDB_SESSION_COUNT - 4  # 28
    dut_host = GPU_HOSTS[0]

    disrupt_steps = [
        create_longevity_step(
            duration=stabilization_delay_sec,
            description=f"Stabilize {stabilization_delay_sec}s before the FSDB kill",
        ),
        create_fpf_record_disruption_time_step(
            description="Record FSDB-kill disruption time"
        ),
        create_fpf_repeated_service_crash_step(
            service=taac_types.Service.FSDB,
            every_sec=1,
            duration_sec=kill_duration_sec,
            device_regexes=[DUT_GTSW],
            description=(
                f"SIGKILL fsdb every 1s for {kill_duration_sec}s on {DUT_GTSW} "
                f"(unclean exit)"
            ),
        ),
        create_longevity_step(
            duration=stable_after_kill_sec,
            description=f"Stable {stable_after_kill_sec}s after the FSDB kill stops",
        ),
    ]

    postchecks = [
        create_fpf_hrt_session_stat_check(
            mode="disruption",
            expected_connected=EXPECTED_FSDB_SESSION_COUNT,
            expected_connected_during=connected_during,
            impacted_lanes=([0] if HRT_DEVICE_IDS == [0] else None),
            impacted_tuples_by_host_device=(FSDB_GLOBAL_LANE0_TUPLES or None),
            recovery_min_sec=recovery_min_sec,
            lookback_sec=session_lookback_sec,
            check_id=f"{disrupt_name}_session_stat",
        ),
    ]
    if add_kill_window_spray and spray:
        postchecks.append(
            create_fpf_host_spray_check(
                hosts=GPU_HOSTS,
                impacted_lanes_by_host={dut_host: ["beth0"]},
                impacted_max_gbps=10.0,
                min_egress_gbps=75.0,
                window_from_disruption_time=True,
                window_duration_sec=kill_duration_sec,
                label=(
                    "[fsdb-kill window] DUT-host lane0(beth0) drained <10Gbps + "
                    "its lanes1-3 >75Gbps; other host all 4 lanes >75Gbps "
                    "(containment)"
                ),
                check_id=f"{disrupt_name}_host_spray_kill",
            )
        )

    disrupt_playbook = create_fpf_disrupt_window_playbook(
        playbook_name=disrupt_name,
        disruption_steps=disrupt_steps,
        spray_hosts=(GPU_HOSTS if add_kill_window_spray and spray else spray),
        ib_traffic_config=_ib_readiness_config(spray),
        postchecks=postchecks,
    )
    longevity_playbook = create_fpf_hardening_playbook_v2(
        gtsws=OBSERVER_GTSWS,
        hosts=GPU_HOSTS,
        trigger_stsws=TRIGGER_STSWS,
        soak_duration_sec=longevity_soak_sec,
        stabilization_delay_sec=0,
        prefix_count=PREFIX_COUNT,
        community_list=DEFAULT_COMMUNITY_LIST,
        playbook_name=longevity_name,
        prod_prefixes=PROD_PREFIXES,
        skip_ssh_dependent_checks=skip_ssh,
        hrt_memory_hosts=HRT_MEMORY_HOSTS,
        hrt_driver_hosts=HRT_MEMORY_HOSTS,
        spray_hosts=(GPU_HOSTS if add_kill_window_spray and spray else spray),
        ib_traffic_config=_ib_readiness_config(spray),
        host_spray_label=longevity_host_spray_label,
        fsdb_expected_total=EXPECTED_FSDB_SESSION_COUNT,
        skip_injection=True,
        rf_vf_groups=RF_VF_GROUPS,
        lanes=INJECTED_LANES,
        # The 5-min fsdb-kill (tc39) leaves lane-0 remote-failure flapping into
        # the longevity soak; it ends recovered (last=0) but a whole-window strict
        # check counts the early transient. Validate recovery by the LAST 10
        # samples for the sustained (>=5min) kill only. tc28 (60s kill) keeps the
        # strict whole-window contract (it already passes clean).
        remote_failure_last_n=(kill_duration_sec >= 300),
    )
    return [disrupt_playbook, longevity_playbook]


def _tc28(*, spray, skip_ssh) -> list:
    return _fsdb_kill_window_playbooks(
        spray=spray,
        skip_ssh=skip_ssh,
        disrupt_name="fpf_tc28_fsdb_kill_disrupt",
        longevity_name="fpf_tc28_fsdb_kill_longevity",
        kill_duration_sec=60,
        session_lookback_sec=900,
        add_kill_window_spray=False,
        longevity_host_spray_label="",
    )


def _tc39(*, spray, skip_ssh) -> list:
    return _fsdb_kill_window_playbooks(
        spray=spray,
        skip_ssh=skip_ssh,
        disrupt_name="fpf_tc39_fsdb_kill5m_disrupt",
        longevity_name="fpf_tc39_fsdb_kill5m_longevity",
        kill_duration_sec=300,
        session_lookback_sec=1200,
        add_kill_window_spray=True,
        longevity_host_spray_label="[longevity] all 4 lanes >75Gbps",
    )


def _tc49(*, spray, skip_ssh) -> list:
    return _kill_playbooks(
        spray=spray,
        skip_ssh=skip_ssh,
        killed_service="bgpd",
        kill_service=taac_types.Service.BGP,
        disrupt_name="fpf_tc49_bgp_kill_5s_10min_disrupt",
        longevity_name="fpf_tc49_bgp_kill_5s_10min_longevity",
        kill_every_sec=15,
        kill_duration_sec=300,
        longevity_settle_sec=60,
    )


def _tc50(*, spray, skip_ssh) -> list:
    return _kill_playbooks(
        spray=spray,
        skip_ssh=skip_ssh,
        killed_service="wedge_agent",
        kill_service=taac_types.Service.AGENT,
        disrupt_name="fpf_tc50_wedge_agent_kill_5s_10min_disrupt",
        longevity_name="fpf_tc50_wedge_agent_kill_5s_10min_longevity",
        kill_every_sec=15,
        kill_duration_sec=300,
        longevity_settle_sec=60,
    )


def _tc51(*, spray, skip_ssh) -> list:
    return _kill_playbooks(
        spray=spray,
        skip_ssh=skip_ssh,
        killed_service="fsdb",
        kill_service=taac_types.Service.FSDB,
        disrupt_name="fpf_tc51_fsdb_kill_5s_10min_disrupt",
        longevity_name="fpf_tc51_fsdb_kill_5s_10min_longevity",
        kill_every_sec=15,
        kill_duration_sec=300,
        longevity_settle_sec=60,
    )


def _tc52(*, spray, skip_ssh) -> list:
    """tc52: HRT restart recovery contract followed by stable longevity."""
    stabilization_delay_sec = 120
    post_restart_settle_sec = 120
    longevity_sec = 300
    hrt_restart_hosts = [GPU_HOSTS[0]]

    disrupt_playbook = create_fpf_hardening_playbook_v2(
        gtsws=OBSERVER_GTSWS,
        hosts=GPU_HOSTS,
        trigger_stsws=TRIGGER_STSWS,
        soak_duration_sec=0,
        stabilization_delay_sec=stabilization_delay_sec,
        prefix_count=PREFIX_COUNT,
        community_list=DEFAULT_COMMUNITY_LIST,
        prod_prefixes=PROD_PREFIXES,
        skip_ssh_dependent_checks=skip_ssh,
        fsdb_expected_total=EXPECTED_FSDB_SESSION_COUNT,
        hrt_memory_hosts=HRT_MEMORY_HOSTS,
        hrt_driver_hosts=HRT_MEMORY_HOSTS,
        spray_hosts=spray,
        ib_traffic_config=_ib_readiness_config(spray),
        disruption_steps=[
            create_fpf_record_restart_time_step(
                description=(
                    "Record HRT restart initiation for production-prefix recovery SLA"
                )
            ),
            create_fpf_restart_hrt_step(
                hosts=hrt_restart_hosts,
                description=(
                    f"Restart HostReachTracker on {hrt_restart_hosts} "
                    f"(systemctl restart metalos.wds.hostreachtracker)"
                ),
            ),
            create_fpf_record_restart_completion_time_step(
                description=(
                    "Record HRT restart completion for post-outage recovery eligibility"
                )
            ),
            create_longevity_step(
                duration=post_restart_settle_sec,
                description=(
                    f"Settle {post_restart_settle_sec}s for HRT to re-subscribe "
                    f"and rebuild its 32 FSDB sessions"
                ),
            ),
        ],
        playbook_name="fpf_tc52_hrt_restart_disrupt",
        skip_injection=True,
        rf_vf_groups=RF_VF_GROUPS,
        lanes=INJECTED_LANES,
        prod_prefix_restart_recovery_sla_sec=30.0,
        hrt_restart_tolerant_hosts=hrt_restart_hosts,
    )
    longevity_playbook = create_fpf_hardening_playbook_v2(
        gtsws=OBSERVER_GTSWS,
        hosts=GPU_HOSTS,
        trigger_stsws=TRIGGER_STSWS,
        soak_duration_sec=longevity_sec,
        stabilization_delay_sec=stabilization_delay_sec,
        prefix_count=PREFIX_COUNT,
        community_list=DEFAULT_COMMUNITY_LIST,
        playbook_name="fpf_tc52_hrt_restart_longevity",
        prod_prefixes=PROD_PREFIXES,
        skip_ssh_dependent_checks=skip_ssh,
        fsdb_expected_total=EXPECTED_FSDB_SESSION_COUNT,
        hrt_memory_hosts=HRT_MEMORY_HOSTS,
        hrt_driver_hosts=HRT_MEMORY_HOSTS,
        spray_hosts=spray,
        ib_traffic_config=_ib_readiness_config(spray),
        skip_injection=True,
        rf_vf_groups=RF_VF_GROUPS,
        lanes=INJECTED_LANES,
    )
    return [disrupt_playbook, longevity_playbook]


def _tc38(*, spray, skip_ssh) -> list:
    """tc38: persistent NDP clear (disrupt + stable v2)."""
    from taac.health_checks.healthcheck_definitions import (
        create_fpf_host_spray_check,
        create_fpf_ods_counter_check,
    )

    ndp_clear_every_sec = 1
    ndp_clear_duration_sec = 120
    settle_after_clear_sec = 120
    longevity_sec = 300
    stabilization_delay_sec = 300
    spray_floor_gbps = 75.0
    discard_floor = 10000
    ods_reduce = r"groupby(entity, (\S+?\.\S+?)\..*, %1),sum"
    ods_in_dst_null = r"regex(fboss.agent.eth.*discards.sum.60),filter(.*in_dst_null.*)"
    ods_in_discard = r"regex(fboss.agent.eth.*discards.sum.60),filter(.*in_discard.*)"
    ods_in_congestion = (
        r"regex(fboss.agent.eth.*congestion.*sum.60),"
        r"filter(.*in_congestion_discards.sum.*)"
    )
    ods_out_congestion = (
        r"regex(fboss.agent.eth.*congestion.*sum.60),"
        r"filter(.*out_congestion_discards.sum.*)"
    )
    ods_entity_desc = ",".join(OBSERVER_GTSWS)

    postchecks = [
        create_fpf_ods_counter_check(
            entity_desc=ods_entity_desc,
            key_desc=ods_in_dst_null,
            validation_expr=f">= {discard_floor}",
            reduce_desc=ods_reduce,
            aggregate="max",
            require="any",
            informational=True,
            counter_name="in_dst_null discards (captured)",
            check_id="ndp_clear_ods_in_dst_null",
        ),
        create_fpf_ods_counter_check(
            entity_desc=ods_entity_desc,
            key_desc=ods_in_discard,
            validation_expr=f">= {discard_floor}",
            reduce_desc=ods_reduce,
            aggregate="max",
            require="any",
            informational=True,
            counter_name="in_discard discards (captured)",
            check_id="ndp_clear_ods_in_discard",
        ),
        create_fpf_ods_counter_check(
            entity_desc=ods_entity_desc,
            key_desc=ods_in_congestion,
            validation_expr="<= 0",
            reduce_desc=ods_reduce,
            counter_name="in_congestion discards (must be 0)",
            check_id="ndp_clear_ods_in_congestion",
        ),
        create_fpf_ods_counter_check(
            entity_desc=ods_entity_desc,
            key_desc=ods_out_congestion,
            validation_expr="<= 0",
            reduce_desc=ods_reduce,
            counter_name="out_congestion discards (must be 0)",
            check_id="ndp_clear_ods_out_congestion",
        ),
    ]
    if spray:
        postchecks.append(
            create_fpf_host_spray_check(
                hosts=spray,
                min_egress_gbps=spray_floor_gbps,
                excluded_lanes_by_host={h: ["beth0"] for h in spray},
                window_from_disruption_time=True,
                window_duration_sec=ndp_clear_duration_sec,
                label=(
                    "[ndp-clear] lane0(beth0) ignored (cache wiped); "
                    "lanes1-3 spray >75G"
                ),
                check_id="ndp_clear_host_spray",
            )
        )

    disrupt_playbook = create_fpf_disrupt_window_playbook(
        playbook_name="fpf_tc38_persistent_ndp_clear_disrupt",
        disruption_steps=[
            create_fpf_record_disruption_time_step(
                description="Record NDP-clear disruption time (anchors spray window)"
            ),
            create_fpf_ndp_clear_loop_step(
                every_sec=ndp_clear_every_sec,
                duration_sec=ndp_clear_duration_sec,
                device_regexes=[OBSERVER_GTSWS[0]],
                description=(
                    f"Persistent NDP clear every {ndp_clear_every_sec}s for "
                    f"{ndp_clear_duration_sec}s on {OBSERVER_GTSWS[0]} "
                    f"(ports stay UP)"
                ),
            ),
            create_longevity_step(
                duration=settle_after_clear_sec,
                description=(
                    f"Settle {settle_after_clear_sec}s after the NDP-clear loop "
                    f"before the stable-state window"
                ),
            ),
        ],
        postchecks=postchecks,
    )
    stable_playbook = create_fpf_hardening_playbook_v2(
        gtsws=OBSERVER_GTSWS,
        hosts=GPU_HOSTS,
        trigger_stsws=TRIGGER_STSWS,
        soak_duration_sec=longevity_sec,
        stabilization_delay_sec=stabilization_delay_sec,
        prefix_count=PREFIX_COUNT,
        community_list=DEFAULT_COMMUNITY_LIST,
        playbook_name="fpf_tc38_persistent_ndp_clear_stable",
        prod_prefixes=PROD_PREFIXES,
        skip_ssh_dependent_checks=skip_ssh,
        fsdb_expected_total=EXPECTED_FSDB_SESSION_COUNT,
        hrt_memory_hosts=HRT_MEMORY_HOSTS,
        hrt_driver_hosts=HRT_MEMORY_HOSTS,
        spray_hosts=spray,
        ib_traffic_config=_ib_readiness_config(spray),
        lanes=INJECTED_LANES,
        skip_injection=True,
        rf_vf_groups=RF_VF_GROUPS,
    )
    return [disrupt_playbook, stable_playbook]


def _disable_steps(circuits: list[Circuit], enable: bool) -> list:
    steps = []
    for dev, intfs in disable_interfaces_by_device(circuits).items():
        steps.append(
            create_fpf_set_interface_admin_step(
                interfaces=intfs,
                enable=enable,
                description=(
                    f"{'Enable' if enable else 'Disable'} {intfs} on {dev} "
                    f"(thrift admin state)"
                ),
            )
        )
    return steps


def _tc15(*, spray, skip_ssh) -> list:
    """tc15: GTSW<->GPU interface disable (disrupt + restore)."""
    impacted_lanes = sorted({c.lane for c in CIRCUITS})
    n = num_disrupted_circuits(CIRCUITS)
    stabilization_delay_sec = 300
    longevity_sec = 120

    disrupt_interfaces = sorted(
        {i for intfs in disable_interfaces_by_device(CIRCUITS).values() for i in intfs}
    )
    disrupt_steps = [
        *_disable_steps(CIRCUITS, enable=False),
        create_longevity_step(
            duration=longevity_sec,
            description=(
                f"Settle {longevity_sec}s after disabling {n} circuit(s) "
                f"so connectors/HRT converge before assertion"
            ),
        ),
        create_fpf_verify_disruption_step(
            interfaces=disrupt_interfaces, fail_if_ineffective=True
        ),
    ]
    disrupt_playbook = create_fpf_link_event_disrupt_playbook(
        gtsws=OBSERVER_GTSWS,
        hosts=GPU_HOSTS,
        trigger_stsws=TRIGGER_STSWS,
        disruption_steps=disrupt_steps,
        prefix_count=PREFIX_COUNT,
        community_list=DEFAULT_COMMUNITY_LIST,
        stabilization_delay_sec=stabilization_delay_sec,
        injected_lanes=INJECTED_LANES,
        impacted_lanes=impacted_lanes,
        impacted_lanes_by_host_gpu=impacted_lanes_by_host_gpu(CIRCUITS),
        impacted_beths_by_host=_impacted_beths_by_host(CIRCUITS),
        impacted_planes_by_host=_impacted_planes_by_host(CIRCUITS),
        prod_prefixes=PROD_PREFIXES,
        hrt_memory_hosts=HRT_MEMORY_HOSTS,
        hrt_driver_hosts=HRT_MEMORY_HOSTS,
        spray_hosts=spray,
        ib_traffic_config=_ib_readiness_config(spray),
        flip_fsdb_session=True,
        flip_discards=True,
        fsdb_expected_total=EXPECTED_FSDB_SESSION_COUNT,
        include_ssh_checks=not skip_ssh,
        skip_injection=True,
        rf_vf_groups=RF_VF_GROUPS,
        playbook_name="fpf_tc15_interface_disable_disrupt",
    )
    restore_playbook = create_fpf_hardening_playbook_v2(
        gtsws=OBSERVER_GTSWS,
        hosts=GPU_HOSTS,
        trigger_stsws=TRIGGER_STSWS,
        disruption_steps=[
            *_disable_steps(CIRCUITS, enable=True),
            create_longevity_step(
                duration=180,
                description="Settle after re-enable; expect full recovery",
            ),
        ],
        soak_duration_sec=0,
        stabilization_delay_sec=0,
        prefix_count=PREFIX_COUNT,
        community_list=DEFAULT_COMMUNITY_LIST,
        lanes=INJECTED_LANES,
        skip_injection=True,
        rf_vf_groups=RF_VF_GROUPS,
        playbook_name="fpf_tc15_interface_disable_restore",
        prod_prefixes=PROD_PREFIXES,
        skip_ssh_dependent_checks=skip_ssh,
        use_bgp_snapshot=True,
        prod_prefix_settle_sec=120,
        convergence_settle_sec=120,
        prod_prefix_recovery=True,
        local_prod_prefixes=PROD_PREFIXES,
        impacted_planes_by_host=_impacted_planes_by_host(CIRCUITS),
        fsdb_expected_total=EXPECTED_FSDB_SESSION_COUNT,
        skip_fsdb_session_precheck=True,
        hrt_memory_hosts=HRT_MEMORY_HOSTS,
        hrt_driver_hosts=HRT_MEMORY_HOSTS,
        spray_hosts=spray,
        ib_traffic_config=_ib_readiness_config(spray),
        plane_status_check=True,
    )
    return [disrupt_playbook, restore_playbook]


def _tc16(*, spray, skip_ssh) -> list:
    """tc16: GTSW<->GPU interface enable (single v2 playbook)."""
    stabilization_delay_sec = 300
    steps = []
    for dev, intfs in disable_interfaces_by_device(CIRCUITS).items():
        steps.append(
            create_fpf_set_interface_admin_step(
                interfaces=intfs,
                enable=True,
                description=f"Enable {intfs} on {dev} (thrift admin state)",
            )
        )
    return [
        create_fpf_hardening_playbook_v2(
            gtsws=OBSERVER_GTSWS,
            hosts=GPU_HOSTS,
            trigger_stsws=TRIGGER_STSWS,
            disruption_steps=[
                *steps,
                create_longevity_step(
                    duration=180,
                    description="Settle after enable; expect stable state",
                ),
            ],
            soak_duration_sec=0,
            stabilization_delay_sec=stabilization_delay_sec,
            prefix_count=PREFIX_COUNT,
            community_list=DEFAULT_COMMUNITY_LIST,
            playbook_name="fpf_tc16_interface_enable",
            prod_prefixes=PROD_PREFIXES,
            # tc16 hard-codes skip_ssh_dependent_checks=True regardless of env.
            skip_ssh_dependent_checks=True,
            hrt_memory_hosts=HRT_MEMORY_HOSTS,
            hrt_driver_hosts=HRT_MEMORY_HOSTS,
            spray_hosts=spray,
            ib_traffic_config=_ib_readiness_config(spray),
            plane_status_check=True,
            lanes=INJECTED_LANES,
            skip_injection=True,
            rf_vf_groups=RF_VF_GROUPS,
        )
    ]


def _drain_playbooks(
    *,
    spray,
    skip_ssh,
    device_drain: bool,
    disrupt_name: str,
    restore_name: str,
    drain_desc: str,
    undrain_desc: str,
    verify_mode: str,
    verify_kwargs: dict,
) -> list:
    """tc17 (link drain) / tc19 (device drain): disrupt + restore."""
    impacted_lanes = sorted({c.lane for c in CIRCUITS})
    stabilization_delay_sec = 300
    longevity_sec = 120
    drain_interfaces = (
        [] if device_drain else sorted({c.a_end_interface for c in CIRCUITS})
    )

    disrupt_steps = [
        create_fpf_drain_interface_step(
            interfaces=drain_interfaces,
            drain=True,
            description=drain_desc,
        ),
        create_fpf_verify_disruption_step(
            interfaces=drain_interfaces,
            mode=verify_mode,
            expect_drained=True,
            **verify_kwargs,
        ),
        create_longevity_step(
            duration=longevity_sec,
            description=f"Settle {longevity_sec}s after drain before assertion",
        ),
    ]
    disrupt_playbook = create_fpf_link_event_disrupt_playbook(
        gtsws=OBSERVER_GTSWS,
        hosts=GPU_HOSTS,
        trigger_stsws=ALL_STSW_TRIGGERS,
        disruption_steps=disrupt_steps,
        prefix_count=PREFIX_COUNT,
        community_list=DEFAULT_COMMUNITY_LIST,
        stabilization_delay_sec=stabilization_delay_sec,
        injected_lanes=INJECTED_LANES,
        impacted_lanes=impacted_lanes,
        impacted_lanes_by_host_gpu=impacted_lanes_by_host_gpu(CIRCUITS),
        impacted_beths_by_host=_impacted_beths_by_host(CIRCUITS),
        impacted_planes_by_host=_impacted_planes_by_host(CIRCUITS),
        prod_prefixes=PROD_PREFIXES,
        hrt_memory_hosts=HRT_MEMORY_HOSTS,
        hrt_driver_hosts=HRT_MEMORY_HOSTS,
        spray_hosts=spray,
        ib_traffic_config=_ib_readiness_config(spray),
        flip_fsdb_session=False,
        flip_discards=False,
        injected_prefixes_withdrawn=False,
        fsdb_expected_total=EXPECTED_FSDB_SESSION_COUNT,
        plane_status_mode="drain",
        skip_injection=True,
        rf_vf_groups=RF_VF_GROUPS,
        gtsw_convergence_settle_sec=30,
        playbook_name=disrupt_name,
    )
    restore_playbook = create_fpf_hardening_playbook_v2(
        gtsws=OBSERVER_GTSWS,
        hosts=GPU_HOSTS,
        trigger_stsws=ALL_STSW_TRIGGERS,
        disruption_steps=[
            create_fpf_drain_interface_step(
                interfaces=drain_interfaces,
                drain=False,
                description=undrain_desc,
            ),
            create_longevity_step(
                duration=180,
                description="Settle after undrain; expect full recovery",
            ),
        ],
        soak_duration_sec=0,
        stabilization_delay_sec=0,
        prefix_count=PREFIX_COUNT,
        community_list=DEFAULT_COMMUNITY_LIST,
        lanes=INJECTED_LANES,
        skip_injection=True,
        rf_vf_groups=RF_VF_GROUPS,
        playbook_name=restore_name,
        prod_prefixes=PROD_PREFIXES,
        # tc17/tc19 hard-code skip_ssh_dependent_checks=True on restore.
        skip_ssh_dependent_checks=True,
        use_bgp_snapshot=True,
        prod_prefix_settle_sec=120,
        convergence_settle_sec=120,
        fsdb_expected_total=EXPECTED_FSDB_SESSION_COUNT,
        skip_fsdb_session_precheck=True,
        hrt_memory_hosts=HRT_MEMORY_HOSTS,
        hrt_driver_hosts=HRT_MEMORY_HOSTS,
        spray_hosts=spray,
        ib_traffic_config=_ib_readiness_config(spray),
        plane_status_check=True,
        prod_prefix_recovery=True,
        local_prod_prefixes=PROD_PREFIXES,
        impacted_planes_by_host=_impacted_planes_by_host(CIRCUITS),
    )
    return [disrupt_playbook, restore_playbook]


def _tc17(*, spray, skip_ssh) -> list:
    drain_interfaces = sorted({c.a_end_interface for c in CIRCUITS})
    return _drain_playbooks(
        spray=spray,
        skip_ssh=skip_ssh,
        device_drain=False,
        disrupt_name="fpf_tc17_link_drain_disrupt",
        restore_name="fpf_tc17_link_drain_restore",
        drain_desc=f"Soft-drain link(s) {drain_interfaces} on {OBSERVER_GTSWS[0]}",
        undrain_desc=f"Undrain link(s) {drain_interfaces} on {OBSERVER_GTSWS[0]}",
        verify_mode="drain",
        verify_kwargs={},
    )


def _tc19(*, spray, skip_ssh) -> list:
    return _drain_playbooks(
        spray=spray,
        skip_ssh=skip_ssh,
        device_drain=True,
        disrupt_name="fpf_tc19_device_drain_disrupt",
        restore_name="fpf_tc19_device_drain_restore",
        drain_desc=f"Soft-drain DEVICE {DUT_GTSW} via local drainer",
        undrain_desc=f"Undrain DEVICE {DUT_GTSW} via local drainer",
        verify_mode="device_drain",
        verify_kwargs={
            "fail_if_ineffective": True,
            "description": f"Gate: confirm DEVICE {DUT_GTSW} is_drained()=True",
        },
    )


def _tc55(*, spray, skip_ssh) -> list:
    """tc55: full GTSW device reboot (disrupt + longevity v2)."""
    stabilization_delay_sec = 120
    reboot_comeup_sec = 300
    longevity_soak_sec = 300
    longevity_settle_sec = 120
    session_lookback_sec = 1000

    disrupt_steps = [
        create_longevity_step(
            duration=stabilization_delay_sec,
            description=f"Stabilize {stabilization_delay_sec}s before the reboot",
        ),
        create_fpf_record_disruption_time_step(
            description="Record GTSW reboot disruption time"
        ),
        create_system_reboot_step(
            trigger=taac_types.SystemRebootTrigger.FULL_SYSTEM_REBOOT,
            description="FULL_SYSTEM_REBOOT of the DUT GTSW",
        ),
        create_longevity_step(
            duration=reboot_comeup_sec,
            description=f"Wait {reboot_comeup_sec}s for the GTSW to come back up",
        ),
    ]
    disrupt_playbook = create_fpf_disrupt_window_playbook(
        playbook_name="fpf_tc55_gtsw_device_reboot_disrupt",
        disruption_steps=disrupt_steps,
        spray_hosts=spray,
        ib_traffic_config=_ib_readiness_config(spray),
        postchecks=build_kill_disrupt_postchecks(
            killed_service="wedge_agent",
            observer_gtsws=OBSERVER_GTSWS,
            hrt_memory_hosts=HRT_MEMORY_HOSTS,
            spray_hosts=spray,
            kill_duration_sec=reboot_comeup_sec,
            prefix_count=PREFIX_COUNT,
            skip_ssh=skip_ssh,
            expected_fsdb_total=EXPECTED_FSDB_SESSION_COUNT,
            session_lookback_sec=session_lookback_sec,
        ),
    )
    longevity_playbook = create_fpf_hardening_playbook_v2(
        gtsws=OBSERVER_GTSWS,
        hosts=GPU_HOSTS,
        trigger_stsws=TRIGGER_STSWS,
        soak_duration_sec=longevity_soak_sec,
        stabilization_delay_sec=0,
        prefix_count=PREFIX_COUNT,
        community_list=DEFAULT_COMMUNITY_LIST,
        playbook_name="fpf_tc55_gtsw_device_reboot_longevity",
        prod_prefixes=PROD_PREFIXES,
        skip_ssh_dependent_checks=skip_ssh,
        fsdb_expected_total=EXPECTED_FSDB_SESSION_COUNT,
        hrt_memory_hosts=HRT_MEMORY_HOSTS,
        hrt_driver_hosts=HRT_MEMORY_HOSTS,
        spray_hosts=spray,
        ib_traffic_config=_ib_readiness_config(spray),
        convergence_settle_sec=longevity_settle_sec,
        skip_injection=True,
        rf_vf_groups=RF_VF_GROUPS,
        lanes=INJECTED_LANES,
    )
    return [disrupt_playbook, longevity_playbook]


def create_fpf_shared_injection_suite_test_config() -> TestConfig:
    skip_ssh = skip_ssh_dependencies()
    skip_ib = skip_ib_traffic()
    ib_setup, ib_teardown = fpf_ib_traffic_tasks(
        skip_ssh,
        skip_ib,
        traffic_config=IB_TRAFFIC_CONFIG,
    )
    spray = None if skip_ssh or skip_ib else SPRAY_HOSTS

    # Ordered least-destructive -> most-destructive. Each entry contributes one or
    # more playbooks; all share the single setup-time injection (skip_injection).
    playbooks = []
    playbooks += _tc41_baseline(spray=spray)
    # Graceful restart.
    playbooks += _tc05(spray=spray)
    playbooks += _tc06(spray=spray)
    playbooks += _tc07(spray=spray)
    playbooks += _tc08(spray=spray)
    # Service restarts.
    playbooks += _tc23(spray=spray, skip_ssh=skip_ssh)
    playbooks += _tc24(spray=spray, skip_ssh=skip_ssh)
    playbooks += _tc04(spray=spray, skip_ssh=skip_ssh)
    # Kills (unclean exits).
    playbooks += _tc28(spray=spray, skip_ssh=skip_ssh)
    playbooks += _tc39(spray=spray, skip_ssh=skip_ssh)
    playbooks += _tc49(spray=spray, skip_ssh=skip_ssh)
    playbooks += _tc50(spray=spray, skip_ssh=skip_ssh)
    playbooks += _tc51(spray=spray, skip_ssh=skip_ssh)
    # HRT restart.
    playbooks += _tc52(spray=spray, skip_ssh=skip_ssh)
    # NDP clear.
    playbooks += _tc38(spray=spray, skip_ssh=skip_ssh)
    # Interface admin events.
    playbooks += _tc15(spray=spray, skip_ssh=skip_ssh)
    playbooks += _tc16(spray=spray, skip_ssh=skip_ssh)
    # GTSW drains.
    playbooks += _tc17(spray=spray, skip_ssh=skip_ssh)
    playbooks += _tc19(spray=spray, skip_ssh=skip_ssh)
    # Coldboot.
    playbooks += _tc27(spray=spray, skip_ssh=skip_ssh)
    # Full device reboot (most destructive) — last.
    playbooks += _tc55(spray=spray, skip_ssh=skip_ssh)

    return TestConfig(
        name="fpf_shared_injection_suite",
        endpoints=create_fpf_endpoints(stsws=ALL_STSWS),
        setup_tasks=[
            *ib_setup,
            create_fpf_start_collectors_task(
                gtsws=OBSERVER_GTSWS,
                hosts=GPU_HOSTS,
                hrt_device_ids=HRT_DEVICE_IDS,
                hrt_plane_ids=INJECTED_LANES,
                subnet_prefix=VF_COLLECTOR_SUBNET,
                prod_prefixes=PROD_PREFIXES,
                prod_prefix_host=PROD_PREFIX_HOST,
                prod_prefix_device_id=PROD_PREFIX_DEVICE_ID,
                fsdb_mode=FSDB_COLLECTOR_MODE,
                allow_baseline_failures=ALLOW_BASELINE_FAILURES,
                # Enable the FSDB-session collector: the kill/reboot/hrt playbooks
                # (tc28/39/49/50/51/52/55) assert against it. Superset of tc41's
                # collectors task — harmless for the playbooks that don't use it.
                enable_fsdb_session_collector=True,
                fsdb_session_host=GPU_HOSTS[0],
                fsdb_session_expected=EXPECTED_FSDB_SESSION_COUNT,
                rf_vf_groups=RF_VF_GROUPS,
            ),
            create_fpf_inject_vf_groups_task(
                groups=INJECTION_GROUPS,
                settle_sec=INJECT_SETTLE_SEC,
            ),
        ],
        teardown_tasks=[
            create_fpf_withdraw_vf_groups_task(groups=INJECTION_GROUPS),
            create_fpf_restart_service_task(devices=ALL_STSWS, service="BGP"),
            create_fpf_stop_collectors_task(
                trigger_stsws=TRIGGER_STSWS,
                withdraw=False,
                community_list=DEFAULT_COMMUNITY_LIST,
            ),
            *ib_teardown,
        ],
        playbooks=playbooks,
        tags=["fpf"],
    )


TEST_CONFIG = create_fpf_shared_injection_suite_test_config()
