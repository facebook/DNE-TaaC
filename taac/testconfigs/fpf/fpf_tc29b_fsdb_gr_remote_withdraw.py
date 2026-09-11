# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe

"""TC29b: one-way remote-prefix withdrawal while local FSDB is in GR.

The runtime-only B namespace originates on the remote l1001 GTSW. Local l1002
FSDB is stopped, remote BGP is stopped 30 seconds later, and local FSDB is
restored after another 30 seconds. B must withdraw everywhere and remain absent
when remote BGP is started again; recovery never reinjects B. Canonical A routes
provide a phase-aware protected-route control signal. No IB traffic is used.
"""

from taac.health_checks.healthcheck_definitions import (
    create_device_core_dumps_check,
    create_fpf_hrt_plane_status_check,
    create_fpf_hrt_session_stat_check,
    create_fpf_remote_prefix_lifecycle_check,
    create_systemctl_active_state_check,
    create_unclean_exit_check,
)
from taac.playbooks.playbook_definitions import (
    create_fpf_lifecycle_phase_playbook,
)
from taac.steps.step_definitions import (
    create_fpf_remote_prefix_gr_sequence_step,
    create_fpf_remote_prefix_start_origin_bgp_step,
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
    create_fpf_endpoints,
    DEFAULT_COMMUNITY_LIST,
    EXPECTED_FSDB_SESSION_COUNT,
    fpf_vf_injection_groups,
    FSDB_COLLECTOR_MODE,
    GPU_HOSTS,
    OBSERVER_GTSWS,
    VF_COLLECTOR_SUBNET,
)
from taac.health_check.health_check import types as hc_types
from taac.test_as_a_config.types import TestConfig

LOCAL_GTSW = OBSERVER_GTSWS[0]
REMOTE_GTSW = OBSERVER_GTSWS[1]
HRT_DEVICE_IDS = list(range(8))
HRT_PLANES = list(range(4))
A_COUNT = 4032
B_COUNT = 1000

A_INJECTION_GROUPS = fpf_vf_injection_groups(count=A_COUNT)
B_INJECTION_GROUP = {
    "devices": [REMOTE_GTSW],
    "prefix_base": "4000:dd::/64",
    "count": B_COUNT,
    "increment_step": "0:0:1::",
    "community_list": "gtsw",
    "batch_size": 100,
}
INJECTION_GROUPS = [*A_INJECTION_GROUPS, B_INJECTION_GROUP]


def _all(value: int):
    return {
        host: {str(device): [value] * 4 for device in HRT_DEVICE_IDS}
        for host in GPU_HOSTS
    }


def _b_present_positive():
    return {
        host: {
            str(device): ([B_COUNT, 0, 0, 0] if device % 2 == 0 else [0] * 4)
            for device in HRT_DEVICE_IDS
        }
        for host in GPU_HOSTS
    }


def _b_present_remote_failure():
    return {
        host: {
            str(device): (
                [0, B_COUNT, B_COUNT, B_COUNT] if device % 2 == 0 else [0] * 4
            )
            for device in HRT_DEVICE_IDS
        }
        for host in GPU_HOSTS
    }


def _a_withdrawn_positive():
    result = _all(A_COUNT)
    remote_host = GPU_HOSTS[1]
    for device in HRT_DEVICE_IDS:
        if device % 2 == 0:
            result[remote_host][str(device)] = [0, A_COUNT, A_COUNT, A_COUNT]
    return result


def _a_withdrawn_remote_failure():
    result = _all(0)
    remote_host = GPU_HOSTS[1]
    for device in HRT_DEVICE_IDS:
        if device % 2 == 0:
            result[remote_host][str(device)] = [A_COUNT, 0, 0, 0]
    return result


def _lifecycle_check(*, mode: str, deadline_sec: int, check_id: str):
    b_present = mode == "present"
    a_withdrawn = mode == "withdrawn"
    scalars = [
        ["bgp_remote_b", REMOTE_GTSW, B_COUNT if b_present else 0],
        ["bgp_remote_b", LOCAL_GTSW, B_COUNT if b_present else 0],
        ["fib_remote_b", LOCAL_GTSW, B_COUNT if b_present else 0],
        ["fsdb_remote_b", LOCAL_GTSW, B_COUNT if b_present else 0],
        ["fib_local_a", LOCAL_GTSW, A_COUNT],
    ]
    # During withdrawal the origin BGP service is intentionally unavailable;
    # its collector cannot prove B=0 and is therefore omitted. The local
    # endpoint remains authoritative for exact absence.
    if mode == "withdrawn":
        scalars = [item for item in scalars if item[1] != REMOTE_GTSW]
    return create_fpf_remote_prefix_lifecycle_check(
        mode=mode,
        runner_device=LOCAL_GTSW,
        scalar_expectations=scalars,
        a_hrt_positive_expected=(
            _a_withdrawn_positive() if a_withdrawn else _all(A_COUNT)
        ),
        a_hrt_remote_failure_expected=(
            _a_withdrawn_remote_failure() if a_withdrawn else _all(0)
        ),
        b_hrt_positive_expected=(_b_present_positive() if b_present else _all(0)),
        b_hrt_remote_failure_expected=(
            _b_present_remote_failure() if b_present else _all(0)
        ),
        deadline_sec=deadline_sec,
        outage_tolerant_collectors=(
            [
                f"fsdb_remote_b@{LOCAL_GTSW}",
                f"hrt_remote_b@{GPU_HOSTS[0]}",
                f"hrt@{GPU_HOSTS[0]}",
            ]
            if mode == "withdrawn"
            else ([f"bgp_remote_b@{REMOTE_GTSW}"] if mode == "recovery" else [])
        ),
        check_id=check_id,
    )


def create_fpf_tc29b_test_config() -> TestConfig:
    safety_checks = [
        create_unclean_exit_check(check_id="fpf_tc29b_unclean_exit"),
        create_device_core_dumps_check(),
    ]
    disrupt = create_fpf_lifecycle_phase_playbook(
        playbook_name="fpf_tc29b_fsdb_gr_remote_withdraw_disrupt",
        prechecks=[
            _lifecycle_check(
                mode="present",
                deadline_sec=120,
                check_id="fpf_tc29b_remote_prefix_present",
            )
        ],
        postchecks=[
            _lifecycle_check(
                mode="withdrawn",
                deadline_sec=120,
                check_id="fpf_tc29b_remote_prefix_withdrawn",
            ),
            *safety_checks,
        ],
        stage_id="remote_withdraw",
        steps=[
            create_fpf_remote_prefix_gr_sequence_step(
                local_gtsw=LOCAL_GTSW,
                remote_gtsw=REMOTE_GTSW,
                between_stops_sec=30,
                before_local_restart_sec=30,
                max_fsdb_outage_sec=120,
            ),
            create_longevity_step(
                duration=120,
                description="Observe exact B withdrawal for the 120s SLA",
            ),
        ],
    )

    recovery = create_fpf_lifecycle_phase_playbook(
        playbook_name="fpf_tc29b_fsdb_gr_remote_withdraw_recovery",
        prechecks=[],
        postchecks=[
            _lifecycle_check(
                mode="recovery",
                deadline_sec=60,
                check_id="fpf_tc29b_remote_prefix_stays_absent",
            ),
            create_fpf_hrt_session_stat_check(
                mode="stable",
                expected_connected=EXPECTED_FSDB_SESSION_COUNT,
                lookback_sec=90,
                check_id="fpf_tc29b_hrt_sessions_recovered",
            ),
            create_fpf_hrt_plane_status_check(
                mode="all_up",
                device_ids=HRT_DEVICE_IDS,
                expected_planes=HRT_PLANES,
                lookback_sec=90,
                stability_mode="strict",
                check_id="fpf_tc29b_hrt_planes_recovered",
            ),
            create_systemctl_active_state_check(
                services=[hc_types.Service.BGPD, hc_types.Service.FSDB]
            ),
            *safety_checks,
        ],
        stage_id="origin_bgp_recovery",
        steps=[
            create_fpf_remote_prefix_start_origin_bgp_step(remote_gtsw=REMOTE_GTSW),
            create_longevity_step(
                duration=90,
                description=("Observe A recovery within 60s while B remains absent"),
            ),
        ],
    )

    return TestConfig(
        name="fpf_tc29b_fsdb_gr_remote_withdraw",
        endpoints=create_fpf_endpoints(stsws=ALL_STSWS),
        setup_tasks=[
            create_fpf_start_collectors_task(
                gtsws=OBSERVER_GTSWS,
                hosts=GPU_HOSTS,
                subnet_prefix=VF_COLLECTOR_SUBNET,
                poll_interval_sec=2.0,
                baseline_collection_sec=0,
                fsdb_mode=FSDB_COLLECTOR_MODE,
                enable_fsdb_session_collector=True,
                fsdb_session_hosts=GPU_HOSTS,
                fsdb_session_poll_interval_sec=2.0,
                fsdb_session_expected=EXPECTED_FSDB_SESSION_COUNT,
                hrt_device_ids=HRT_DEVICE_IDS,
                hrt_plane_ids=HRT_PLANES,
                additional_namespaces=[
                    {
                        "name": "remote_b",
                        "subnet_prefix": "4000:dd::/32",
                        "bgp_gtsws": [REMOTE_GTSW, LOCAL_GTSW],
                        "fsdb_gtsws": [LOCAL_GTSW],
                        "fib_gtsws": [LOCAL_GTSW],
                        "hosts": GPU_HOSTS,
                        "device_ids": HRT_DEVICE_IDS,
                        "plane_ids": HRT_PLANES,
                        "include_remote_failure": True,
                    },
                    {
                        "name": "local_a",
                        "subnet_prefix": "5000:dd::/32",
                        "fib_gtsws": [LOCAL_GTSW],
                    },
                ],
            ),
            create_fpf_inject_vf_groups_task(
                groups=INJECTION_GROUPS,
                settle_sec=120,
            ),
        ],
        teardown_tasks=[
            create_fpf_restart_service_task(
                devices=OBSERVER_GTSWS,
                service="BGP",
            ),
            create_fpf_restart_service_task(
                devices=[LOCAL_GTSW],
                service="FSDB",
            ),
            create_fpf_withdraw_vf_groups_task(groups=INJECTION_GROUPS),
            create_fpf_restart_service_task(devices=ALL_STSWS, service="BGP"),
            create_fpf_stop_collectors_task(
                trigger_stsws=ALL_STSWS,
                withdraw=False,
                community_list=DEFAULT_COMMUNITY_LIST,
            ),
        ],
        playbooks=[disrupt, recovery],
        tags=["fpf"],
    )


TEST_CONFIG = create_fpf_tc29b_test_config()
