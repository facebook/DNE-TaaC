# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""MWG2 FPF GAR Class A baseline and multi-pod functional tests.

The setup injects independent VF1/VF2 prefix ranges from every GTSW in both
test pods. Four read-only playbooks then validate topology_info, STSW capacity
and add-path behavior, remote BGP/Agent state, and reciprocal multi-pod
origination across all eight fabric planes.
"""

from __future__ import annotations

import os
import typing as t

from taac.health_checks.healthcheck_definitions import (
    create_bgp_rib_fib_consistency_check,
    create_bgp_session_establish_check,
    create_device_core_dumps_check,
    create_drain_state_check,
    create_fpf_gar_scale_capacity_check,
    create_fpf_gar_vf_capacity_check,
    create_port_state_check,
    create_systemctl_active_state_check,
    create_unclean_exit_check,
    create_wedge_agent_configured_check,
)
from taac.libs.fpf.fpf_prod_prefix_map import get_prefix
from taac.playbooks.playbook_definitions import (
    create_fpf_gar_playbook,
)
from taac.stages.stage_definitions import create_steps_stage
from taac.steps.step_definitions import create_validation_step
from taac.task_definitions import (
    create_fpf_inject_vf_groups_task,
    create_fpf_withdraw_vf_groups_task,
)
from taac.test_as_a_config.types import (
    Endpoint,
    Playbook,
    PointInTimeHealthCheck,
    TestConfig,
)


CONTROLLER: str = "gtsw001.l1002.c087.mwg2"
PLANE_COUNT: int = 8
NOMINAL_CAPACITY: int = 36
L1002_PLANE3_CAPACITY: int = int(os.environ.get("FPF_GAR_PLANE3_CAPACITY", "34"))

GAR_PREFIX_COUNT: int = int(os.environ.get("FPF_GAR_PREFIX_COUNT", "1000"))
GAR_INCREMENT_STEP: str = "0:0:1::"
GAR_SETTLE_SEC: int = int(os.environ.get("FPF_GAR_INJECT_SETTLE_SEC", "30"))
GAR_VALIDATION_TIMEOUT_SEC: int = int(
    os.environ.get("FPF_GAR_VALIDATION_TIMEOUT_SEC", "120")
)

L1002_VF1_PREFIX_BASE: str = "5000:ca::/64"
L1002_VF2_PREFIX_BASE: str = "5000:cb::/64"
L1001_VF1_PREFIX_BASE: str = "5000:cc::/64"
L1001_VF2_PREFIX_BASE: str = "5000:cd::/64"
PRODUCTION_VF_PREFIX: str = get_prefix("rtptest1555.mwg2", 0)


def _gtsw(plane: int, pod: str) -> str:
    return f"gtsw{plane:03d}.{pod}.c087.mwg2"


def _stsw(plane: int) -> str:
    return f"stsw001.s{plane:03d}.l202.mwg2"


def _source_capacity(plane: int, source_pod: str) -> int:
    if plane == 3 and source_pod == "l1002":
        return L1002_PLANE3_CAPACITY
    return NOMINAL_CAPACITY


def _observer_path_count(plane: int, observer_pod: str) -> int:
    if plane == 3 and observer_pod == "l1002":
        return L1002_PLANE3_CAPACITY
    return NOMINAL_CAPACITY


def _pairs(
    *,
    source_pod: str,
    observer_pod: str,
    planes: t.Iterable[int],
    validation_scope: str,
    source_route_mode: str = "drop",
) -> list[dict[str, object]]:
    pairs: list[dict[str, object]] = []
    for plane in planes:
        capacity = _source_capacity(plane, source_pod)
        observer_paths = _observer_path_count(plane, observer_pod)
        pairs.append(
            {
                "name": f"plane-{plane}-{source_pod}-to-{observer_pod}",
                "source": _gtsw(plane, source_pod),
                "spine": _stsw(plane),
                "observer": _gtsw(plane, observer_pod),
                "expected_capacity": capacity,
                "observer_path_count": observer_paths,
                "observer_forwarding_count": min(capacity, observer_paths),
                "spine_id": 1,
                "source_route_mode": source_route_mode,
                "validation_scope": validation_scope,
            }
        )
    return pairs


INJECTION_GROUPS: list[dict[str, object]] = [
    {
        "devices": [_gtsw(plane, "l1002") for plane in range(1, 5)],
        "prefix_base": L1002_VF1_PREFIX_BASE,
        "count": GAR_PREFIX_COUNT,
        "increment_step": GAR_INCREMENT_STEP,
        "batch_size": 100,
        "community_list": "gtsw",
    },
    {
        "devices": [_gtsw(plane, "l1002") for plane in range(5, 9)],
        "prefix_base": L1002_VF2_PREFIX_BASE,
        "count": GAR_PREFIX_COUNT,
        "increment_step": GAR_INCREMENT_STEP,
        "batch_size": 100,
        "community_list": "gtsw",
    },
    {
        "devices": [_gtsw(plane, "l1001") for plane in range(1, 5)],
        "prefix_base": L1001_VF1_PREFIX_BASE,
        "count": GAR_PREFIX_COUNT,
        "increment_step": GAR_INCREMENT_STEP,
        "batch_size": 100,
        "community_list": "gtsw",
    },
    {
        "devices": [_gtsw(plane, "l1001") for plane in range(5, 9)],
        "prefix_base": L1001_VF2_PREFIX_BASE,
        "count": GAR_PREFIX_COUNT,
        "increment_step": GAR_INCREMENT_STEP,
        "batch_size": 100,
        "community_list": "gtsw",
    },
]


def _generic_health_checks() -> list[PointInTimeHealthCheck]:
    return [
        *[
            create_drain_state_check(expected_drained=False, device_name=device)
            for device in [
                *[_gtsw(plane, "l1002") for plane in range(1, PLANE_COUNT + 1)],
                *[_stsw(plane) for plane in range(1, PLANE_COUNT + 1)],
                *[_gtsw(plane, "l1001") for plane in range(1, PLANE_COUNT + 1)],
            ]
        ],
        create_bgp_session_establish_check(
            # Plane-3's known 34-link baseline leaves 71/103 sessions up on
            # its STSW (68.9%). Keep the floor below that known-good state.
            min_established_pct=0.68,
            retry_count=3,
            retry_delay_seconds=5,
        ),
        create_port_state_check(
            retry_count=30,
            retry_delay_seconds=10,
            retry_delay_multiplier=1,
        ),
        create_wedge_agent_configured_check(),
        create_bgp_rib_fib_consistency_check(
            retry_count=3,
            retry_delay_seconds=5,
        ),
        create_systemctl_active_state_check(
            services_json=["bgpd", "wedge_agent", "qsfp_service"]
        ),
        create_unclean_exit_check(),
        create_device_core_dumps_check(),
    ]


def _scale_check(
    *,
    prefix_base: str,
    source_pod: str,
    observer_pod: str,
    planes: t.Iterable[int],
    validation_scope: str,
    check_id: str,
) -> PointInTimeHealthCheck:
    return create_fpf_gar_scale_capacity_check(
        pairs=_pairs(
            source_pod=source_pod,
            observer_pod=observer_pod,
            planes=planes,
            validation_scope=validation_scope,
        ),
        prefix_base=prefix_base,
        prefix_count=GAR_PREFIX_COUNT,
        increment_step=GAR_INCREMENT_STEP,
        timeout_sec=GAR_VALIDATION_TIMEOUT_SEC,
        poll_interval_sec=5,
        check_id=check_id,
    )


def _vf_check(
    *,
    validation_scope: str,
    check_id: str,
) -> PointInTimeHealthCheck:
    return create_fpf_gar_vf_capacity_check(
        pairs=_pairs(
            source_pod="l1002",
            observer_pod="l1001",
            planes=range(1, 5),
            validation_scope=validation_scope,
            source_route_mode="vf",
        ),
        prefixes=[PRODUCTION_VF_PREFIX],
        timeout_sec=GAR_VALIDATION_TIMEOUT_SEC,
        poll_interval_sec=5,
        check_id=check_id,
    )


def _one_direction_checks(
    validation_scope: str, check_id_prefix: str
) -> list[PointInTimeHealthCheck]:
    return [
        _vf_check(
            validation_scope=validation_scope,
            check_id=f"{check_id_prefix}_production_vf",
        ),
        _scale_check(
            prefix_base=L1002_VF1_PREFIX_BASE,
            source_pod="l1002",
            observer_pod="l1001",
            planes=range(1, 5),
            validation_scope=validation_scope,
            check_id=f"{check_id_prefix}_l1002_vf1",
        ),
        _scale_check(
            prefix_base=L1002_VF2_PREFIX_BASE,
            source_pod="l1002",
            observer_pod="l1001",
            planes=range(5, 9),
            validation_scope=validation_scope,
            check_id=f"{check_id_prefix}_l1002_vf2",
        ),
    ]


def _both_direction_checks(
    validation_scope: str, check_id_prefix: str
) -> list[PointInTimeHealthCheck]:
    return [
        *_one_direction_checks(validation_scope, check_id_prefix),
        _scale_check(
            prefix_base=L1001_VF1_PREFIX_BASE,
            source_pod="l1001",
            observer_pod="l1002",
            planes=range(1, 5),
            validation_scope=validation_scope,
            check_id=f"{check_id_prefix}_l1001_vf1",
        ),
        _scale_check(
            prefix_base=L1001_VF2_PREFIX_BASE,
            source_pod="l1001",
            observer_pod="l1002",
            planes=range(5, 9),
            validation_scope=validation_scope,
            check_id=f"{check_id_prefix}_l1001_vf2",
        ),
    ]


def _class_a_playbook(
    *,
    name: str,
    description: str,
    gar_checks: list[PointInTimeHealthCheck],
) -> Playbook:
    return create_fpf_gar_playbook(
        name=name,
        description=description,
        prechecks=_generic_health_checks(),
        postchecks=_generic_health_checks(),
        stages=[
            create_steps_stage(
                stage_id=f"{name}_validate",
                steps=[
                    create_validation_step(
                        point_in_time_checks=gar_checks,
                        description=f"{name}: validate GAR signals across all planes",
                    )
                ],
            )
        ],
        # The drain gate intentionally contains one same-name check per device.
        # Keep all of them instead of applying TAAC's default name-based dedupe.
        override_duplicate_checks=False,
    )


def create_fpf_gar_class_a_test_config() -> TestConfig:
    playbooks = [
        _class_a_playbook(
            name="fpf_gar_a1_topology_info_all_planes",
            description=(
                "Class A1: validate GAR topology_info capacity and spine ID across "
                "all eight source GTSWs, plane STSWs, and remote GTSWs."
            ),
            gar_checks=_one_direction_checks("topology_info", "fpf_gar_a1"),
        ),
        _class_a_playbook(
            name="fpf_gar_a2_stsw_capacity_add_path",
            description=(
                "Class A2: validate every plane STSW computes its source bundle "
                "capacity and advertises the expected add-path set remotely."
            ),
            gar_checks=_one_direction_checks("bgp", "fpf_gar_a2"),
        ),
        _class_a_playbook(
            name="fpf_gar_a3_remote_rib_fib_capacity",
            description=(
                "Class A3: validate remote GTSW BGP RIB and Agent FIB capacity "
                "for every injected prefix on all eight planes."
            ),
            gar_checks=_one_direction_checks("remote_rib_fib", "fpf_gar_a3"),
        ),
        _class_a_playbook(
            name="fpf_gar_a4_multi_pod_origination",
            description=(
                "Class A4: validate independent reciprocal origination from l1001 "
                "and l1002 across both VF groups and all eight planes."
            ),
            gar_checks=_both_direction_checks("full", "fpf_gar_a4"),
        ),
    ]

    endpoints = [Endpoint(name=CONTROLLER, dut=True)]
    endpoints.extend(
        Endpoint(name=_gtsw(plane, "l1002"), dut=False)
        for plane in range(2, PLANE_COUNT + 1)
    )
    endpoints.extend(
        Endpoint(name=_stsw(plane), dut=False) for plane in range(1, PLANE_COUNT + 1)
    )
    endpoints.extend(
        Endpoint(name=_gtsw(plane, "l1001"), dut=False)
        for plane in range(1, PLANE_COUNT + 1)
    )

    return TestConfig(
        name="fpf_gar_class_a",
        endpoints=endpoints,
        setup_tasks=[
            create_fpf_withdraw_vf_groups_task(groups=INJECTION_GROUPS),
            create_fpf_inject_vf_groups_task(
                groups=INJECTION_GROUPS,
                settle_sec=GAR_SETTLE_SEC,
            ),
        ],
        teardown_tasks=[
            create_fpf_withdraw_vf_groups_task(groups=INJECTION_GROUPS),
        ],
        playbooks=playbooks,
        tags=["fpf", "gar", "class-a", "network-only"],
    )


TEST_CONFIG = create_fpf_gar_class_a_test_config()
