# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

"""TC54: STSW device drain (strict stable-state) — drain stsw001.s001.

Soft-drains a single STSW (stsw001.s001, which serves the lane-0 plane) via the
on-box LOCAL_DRAINER and re-injects the FPF prefixes with the drain-marker
community, then validates the steady state.

How this differs from the GTSW device drain (tc19) and the drain-tolerant STSW
drain (tc34):
  - The GTSW's own BGP is NOT restarted/depreferenced here — only the STSW's BGP
    changes. So there is NO GTSW-side transient to absorb: we do NOT apply the
    GTSW-drain allowance (no ``use_bgp_snapshot``, no ``skip_fsdb_session_
    precheck``, no gtsw convergence settle). Every control-plane / HRT collector
    is held to the FULL stable-state contract.
  - The ONLY expected deviation from stable state is on the DATA plane: the
    lane-0 plane that stsw001.s001 serves drains (confirmed on hardware — the
    traffic does NOT reroute), so on BOTH GPU hosts lane 0 (beth0) egress drops
    to ~0. The lane-0 plane must report DRAINED and beth0 is positively capped
    at the drained-traffic ceiling while beth1-3 retain the spray floor.
    Everything else stays strictly stable.

The drain, fail-closed state readback, split-VF drain-community reinjection,
and 300s settle all run inside the checked playbook, so a standalone or
regex-selected run cannot pass without executing the mutation.

NOTE: this config is BUILD-validated only; it has NOT been run end-to-end on
hardware.

Usage:
  buck2 run neteng/netcastle:netcastle_taac -- \\
    --team taac --test-config fpf_tc54_stsw_device_drain \\
    --dev --skip-basset-reservation --skip-testbed-isolation \\
    --debug --continue-on-precheck-failure --skip-fboss-rsyslog
"""

from taac.health_checks.healthcheck_definitions import (
    create_fpf_hrt_plane_status_check,
)
from taac.libs.fpf.fpf_prod_prefix_map import get_prefix
from taac.playbooks.playbook_definitions import (
    create_fpf_hardening_playbook_v2,
)
from taac.steps.step_definitions import (
    create_fpf_stsw_drain_and_reinject_steps,
    create_longevity_step,
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
    create_fpf_endpoints,
    DEFAULT_COMMUNITY_LIST,
    EXPECTED_FSDB_SESSION_COUNT,
    fpf_hrt_device_ids,
    fpf_hrt_lanes,
    fpf_hrt_vf_device_ids,
    fpf_ib_traffic_config,
    fpf_ib_traffic_tasks,
    fpf_rf_vf_groups,
    fpf_vf_injection_groups,
    FSDB_COLLECTOR_MODE,
    GPU_HOSTS,
    HRT_MEMORY_HOSTS,
    OBSERVER_GTSWS,
    skip_ib_traffic,
    skip_ssh_dependencies,
    SPRAY_HOSTS,
    TRIGGER_STSWS,
    VF_COLLECTOR_SUBNET,
    VF_GROUP_PREFIX_COUNT,
)
from taac.test_as_a_config.types import TestConfig

# 8-plane VF-group injection (VF1 5000:dd on s001-s004 = planes 0-3, VF2 5000:ee
# on s005-s008 = planes 4-7); injected once by the setup task, withdrawn in
# teardown, so the longevity playbook passes skip_injection=True.
INJECTION_GROUPS = fpf_vf_injection_groups()
PREFIX_COUNT = VF_GROUP_PREFIX_COUNT
INJECTED_LANES = fpf_hrt_lanes()
HRT_DEVICE_IDS = fpf_hrt_device_ids()
HRT_VF_DEVICE_IDS = fpf_hrt_vf_device_ids(HRT_DEVICE_IDS)
RF_VF_GROUPS = fpf_rf_vf_groups(
    active_lanes=INJECTED_LANES,
    device_ids_by_vf=(HRT_VF_DEVICE_IDS if HRT_DEVICE_IDS != [0] else None),
)
IB_TRAFFIC_CONFIG = fpf_ib_traffic_config()
INJECT_SETTLE_SEC = 300
LONGEVITY_SEC = 300

# STSW plane to drain (the first trigger STSW: stsw001.s001.l202.mwg2), which
# serves lane 0 — the same plane tc19/tc34 monitor on GPU0 of the first GPU host.
DRAIN_TARGET_STSW = TRIGGER_STSWS[0]
# Canonical FPF STSW drain community appended to the re-injected prefixes so the
# drained plane is depreferenced (lane 0 drains) rather than withdrawn.
DRAIN_COMMUNITY = "65446:10"

PROD_PREFIX_HOST = GPU_HOSTS[0]
PROD_PREFIX_DEVICE_ID = 0
PROD_PREFIXES = [get_prefix(PROD_PREFIX_HOST, PROD_PREFIX_DEVICE_ID)]
PROD_PREFIXES_BY_HOST = {host: PROD_PREFIXES for host in GPU_HOSTS}

# stsw001.s001 -> lane 0: the drained data plane on both GPU hosts.
IMPACTED_PLANES_BY_HOST = {host: [0] for host in GPU_HOSTS}


def create_fpf_tc54_test_config() -> TestConfig:
    skip_ssh = skip_ssh_dependencies()
    skip_ib = skip_ib_traffic()
    ib_setup, ib_teardown = fpf_ib_traffic_tasks(
        skip_ssh, skip_ib, traffic_config=IB_TRAFFIC_CONFIG
    )
    spray = None if skip_ssh or skip_ib else SPRAY_HOSTS

    disrupt_steps = [
        # Prefixes are injected once by the setup task (8-plane VF groups). The
        # drain step depreferences the drained STSW's plane and re-advertises with
        # the drain-marker community across all 8 STSWs at the same per-lane count.
        *create_fpf_stsw_drain_and_reinject_steps(
            stsw=DRAIN_TARGET_STSW,
            drained=True,
            trigger_stsws=ALL_STSWS,
            prefix_count=PREFIX_COUNT,
            community_list=DEFAULT_COMMUNITY_LIST,
            drain_community=DRAIN_COMMUNITY,
            injection_groups=INJECTION_GROUPS,
        ),
        create_longevity_step(
            duration=LONGEVITY_SEC,
            description=(
                f"Settle {LONGEVITY_SEC}s after STSW {DRAIN_TARGET_STSW} drain + "
                "reinject"
            ),
        ),
    ]

    # STRICT stable-state longevity: the GTSW BGP is untouched, so unlike tc34 we
    # do NOT pass use_bgp_snapshot / skip_fsdb_session_precheck. Only lane 0's
    # DATA plane is allowed to be drained (host-spray beth0 assertion); every
    # control-plane signal stays strict. In particular, draining an STSW does
    # not drain the host<->GTSW FSDB transport, so HRT plane status must remain
    # UP rather than report DRAINED.
    longevity_playbook = create_fpf_hardening_playbook_v2(
        gtsws=OBSERVER_GTSWS,
        hosts=GPU_HOSTS,
        trigger_stsws=TRIGGER_STSWS,
        disruption_steps=disrupt_steps,
        soak_duration_sec=0,
        stabilization_delay_sec=0,
        prefix_count=PREFIX_COUNT,
        community_list=DEFAULT_COMMUNITY_LIST,
        playbook_name="fpf_tc54_stsw_device_drain_disrupt",
        prod_prefixes=PROD_PREFIXES,
        prod_prefixes_by_host=PROD_PREFIXES_BY_HOST,
        skip_ssh_dependent_checks=skip_ssh,
        fsdb_expected_total=EXPECTED_FSDB_SESSION_COUNT,
        hrt_memory_hosts=HRT_MEMORY_HOSTS,
        hrt_driver_hosts=HRT_MEMORY_HOSTS,
        spray_hosts=spray,
        ib_traffic_config=IB_TRAFFIC_CONFIG if spray else None,
        # Lane 0's data plane drains, but HRT's host<->GTSW FSDB plane remains
        # UP. Keep an explicit strict all-UP check so a real HRT-plane loss is
        # not hidden by the data-plane drain allowance below.
        plane_status_check=False,
        additional_postchecks=[
            create_fpf_hrt_plane_status_check(
                mode="all_up",
                device_ids=HRT_DEVICE_IDS,
                check_id="fpf_hrt_plane_status_stsw_control_up",
            )
        ],
        prod_prefix_recovery=True,
        local_prod_prefixes=PROD_PREFIXES,
        impacted_planes_by_host=IMPACTED_PLANES_BY_HOST,
        # Lane 0 (stsw001.s001 = plane 0 = beth0) STAYS drained for the whole
        # longevity. Host-spray asserts beth0~0, and rib/fsdb/bulk/remote-failure
        # exempt lane 0; every other lane, the all-UP HRT plane-status check, and
        # the HRT FSDB-session census stay STRICT (32/32). The STSW-side drain
        # does not touch the GPU<->GTSW HRT subscription.
        impacted_lanes_drained=[0],
        # 8-plane: prefixes injected once by the setup task; check all 8 lanes.
        skip_injection=True,
        rf_vf_groups=RF_VF_GROUPS,
        lanes=INJECTED_LANES,
        hrt_device_ids=HRT_DEVICE_IDS,
        cleanup_steps=create_fpf_stsw_drain_and_reinject_steps(
            stsw=DRAIN_TARGET_STSW,
            drained=False,
            trigger_stsws=ALL_STSWS,
            prefix_count=PREFIX_COUNT,
            community_list=DEFAULT_COMMUNITY_LIST,
            injection_groups=INJECTION_GROUPS,
        ),
    )

    return TestConfig(
        name="fpf_tc54_stsw_device_drain",
        endpoints=create_fpf_endpoints(stsws=ALL_STSWS),
        setup_tasks=[
            *ib_setup,
            create_fpf_start_collectors_task(
                gtsws=OBSERVER_GTSWS,
                hosts=GPU_HOSTS,
                hrt_device_ids=HRT_DEVICE_IDS,
                hrt_plane_ids=INJECTED_LANES,
                subnet_prefix=VF_COLLECTOR_SUBNET,
                prod_prefixes_by_host=PROD_PREFIXES_BY_HOST,
                prod_prefix_device_id=PROD_PREFIX_DEVICE_ID,
                fsdb_mode=FSDB_COLLECTOR_MODE,
                allow_baseline_failures=ALLOW_BASELINE_FAILURES,
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
        playbooks=[longevity_playbook],
        tags=["fpf"],
    )


TEST_CONFIG = create_fpf_tc54_test_config()
