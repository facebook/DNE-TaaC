# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""MWG2 GAR Class D device-drain tests.

These are network-only tests. Each disruption and recovery is a separate
playbook. Device soft-drain restarts BGP, so the 1,000 injected routes are
re-originated after a drain or undrain only on GTSWs that originate them.
Per the GAR drain contract, the postchecks require the production VF route to
remain visible across source, spine, and remote observer. They validate that
rack-topology metadata survives and that the drain community is present on the
paths downstream of each drained device. Scale is present as load but is not
used as a pass/fail health check for soft-drain operations.
"""

from __future__ import annotations

import os

from taac.health_checks.healthcheck_definitions import (
    create_bgp_rib_fib_consistency_check,
    create_bgp_session_establish_check,
    create_device_core_dumps_check,
    create_drain_state_check,
    create_fpf_gar_vf_capacity_check,
    create_port_state_check,
    create_systemctl_active_state_check,
    create_unclean_exit_check,
    create_wedge_agent_configured_check,
)
from taac.libs.fpf.fpf_prod_prefix_map import get_prefix
from taac.libs.fpf.inject_bgp_prefixes import GTSW_COMMUNITIES
from taac.playbooks.playbook_definitions import (
    create_fpf_gar_playbook,
)
from taac.stages.stage_definitions import create_steps_stage
from taac.steps.step_definitions import (
    create_fpf_bgp_prefix_injection_step,
    create_fpf_multi_device_drain_step,
)
from taac.task_definitions import (
    create_fpf_inject_vf_groups_task,
    create_fpf_withdraw_vf_groups_task,
)
from taac.test_as_a_config.types import Endpoint, Playbook, TestConfig


CONTROLLER = "gtsw001.l1002.c087.mwg2"
PRODUCTION_VF_PREFIX = get_prefix("rtptest1555.mwg2", 0)
GAR_PREFIX_BASE = "5000:d0::/64"
GAR_PREFIX_COUNT = int(os.environ.get("FPF_GAR_PREFIX_COUNT", "1000"))
GAR_INCREMENT_STEP = "0:0:1::"
GAR_SETTLE_SEC = int(os.environ.get("FPF_GAR_INJECT_SETTLE_SEC", "30"))
GAR_VALIDATION_TIMEOUT_SEC = int(
    os.environ.get("FPF_GAR_VALIDATION_TIMEOUT_SEC", "120")
)
DRAIN_COMMUNITY = "65446:10"
DRAIN_GTSW_COMMUNITIES = [*GTSW_COMMUNITIES, DRAIN_COMMUNITY]


def _gtsw(plane: int, pod: str) -> str:
    return f"gtsw{plane:03d}.{pod}.c087.mwg2"


def _stsw(plane: int) -> str:
    return f"stsw001.s{plane:03d}.l202.mwg2"


def _plane_devices(plane: int) -> tuple[str, str, str]:
    return _gtsw(plane, "l1002"), _stsw(plane), _gtsw(plane, "l1001")


PLANE1_SOURCE, PLANE1_SPINE, PLANE1_OBSERVER = _plane_devices(1)
PLANE2_SOURCE, PLANE2_SPINE, PLANE2_OBSERVER = _plane_devices(2)
PLANE4_SOURCE, PLANE4_SPINE, PLANE4_OBSERVER = _plane_devices(4)

INJECTION_SOURCES = [PLANE1_SOURCE, PLANE2_SOURCE, PLANE4_SOURCE]
IN_SCOPE_DEVICES = [
    PLANE1_SOURCE,
    PLANE1_SPINE,
    PLANE1_OBSERVER,
    PLANE2_SOURCE,
    PLANE2_SPINE,
    PLANE2_OBSERVER,
    PLANE4_SOURCE,
    PLANE4_SPINE,
    PLANE4_OBSERVER,
]

GAR_INJECTION_GROUPS = [
    {
        "devices": INJECTION_SOURCES,
        "prefix_base": GAR_PREFIX_BASE,
        "count": GAR_PREFIX_COUNT,
        "increment_step": GAR_INCREMENT_STEP,
        "batch_size": 100,
        "community_list": "gtsw",
    }
]


def _pair(
    plane: int,
    *,
    drained_devices: set[str],
) -> dict[str, object]:
    source, spine, observer = _plane_devices(plane)
    source_drained = source in drained_devices
    spine_drained = spine in drained_devices
    pair: dict[str, object] = {
        "name": f"plane-{plane}-l1002-to-l1001",
        "source": source,
        "spine": spine,
        "observer": observer,
        "expected_capacity": 36,
        "expected_spine_capacity": 36,
        "observer_path_count": 36,
        "spine_id": 1,
        "source_route_mode": "vf",
        "observer_required_bgp_topology_fields": [
            "rack_id",
            "spine_id",
            "remote_rack_capacity",
        ],
        "observer_required_agent_topology_fields": [
            "rack_id",
            "spine_id",
            "remote_rack_capacity",
        ],
    }
    if source_drained:
        pair["spine_required_communities"] = [DRAIN_COMMUNITY]
    else:
        pair["spine_forbidden_communities"] = [DRAIN_COMMUNITY]
    if source_drained or spine_drained:
        pair["observer_required_communities"] = [DRAIN_COMMUNITY]
    else:
        pair["observer_forbidden_communities"] = [DRAIN_COMMUNITY]
    return pair


def _vf_check(drained_devices: set[str]):
    return create_fpf_gar_vf_capacity_check(
        pairs=[_pair(plane, drained_devices=drained_devices) for plane in (1, 2, 4)],
        prefixes=[PRODUCTION_VF_PREFIX],
        timeout_sec=GAR_VALIDATION_TIMEOUT_SEC,
        poll_interval_sec=5,
        check_id="fpf_gar_class_d_vf_capacity",
    )


def _health_checks(
    *,
    drained_devices: set[str],
    include_vf: bool = True,
) -> list:
    checks = [
        *[
            create_drain_state_check(
                expected_drained=device in drained_devices,
                device_name=device,
            )
            for device in IN_SCOPE_DEVICES
        ],
        create_bgp_session_establish_check(
            min_established_pct=0.7,
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
            services_json=["bgpd", "wedge_agent", "qsfp_service"],
            retry_count=12,
            retry_delay_seconds=10,
            retry_delay_multiplier=1,
        ),
        create_unclean_exit_check(),
        create_device_core_dumps_check(),
    ]
    if include_vf:
        checks.append(_vf_check(drained_devices))
    return checks


def _reinjection_step(*, drained: bool):
    if drained:
        return create_fpf_bgp_prefix_injection_step(
            devices=[PLANE1_SOURCE],
            prefix_base=GAR_PREFIX_BASE,
            count=GAR_PREFIX_COUNT,
            increment_step=GAR_INCREMENT_STEP,
            batch_size=100,
            communities=DRAIN_GTSW_COMMUNITIES,
            description=(
                f"Re-inject {GAR_PREFIX_COUNT} scale prefixes on the drained "
                f"source with community {DRAIN_COMMUNITY}"
            ),
        )
    return create_fpf_bgp_prefix_injection_step(
        devices=[PLANE1_SOURCE],
        prefix_base=GAR_PREFIX_BASE,
        count=GAR_PREFIX_COUNT,
        increment_step=GAR_INCREMENT_STEP,
        batch_size=100,
        community_list="gtsw",
        description=(
            f"Re-inject {GAR_PREFIX_COUNT} scale prefixes on the recovered source "
            "with normal GTSW communities"
        ),
    )


def _class_d_playbooks(
    *,
    name: str,
    description: str,
    drain_devices: list[str],
    reinject_source: bool,
) -> list[Playbook]:
    drain = create_fpf_multi_device_drain_step(
        devices=drain_devices,
        drain=True,
        description=f"{name}: soft-drain {drain_devices}",
    )
    undrain = create_fpf_multi_device_drain_step(
        devices=drain_devices,
        drain=False,
        description=f"{name}: undrain {drain_devices}",
    )
    disrupt_steps = [drain]
    recovery_steps = [undrain]
    cleanup_steps = [undrain]
    if reinject_source:
        disrupt_steps.append(_reinjection_step(drained=True))
        normal_reinjection = _reinjection_step(drained=False)
        recovery_steps.append(normal_reinjection)
        cleanup_steps.append(normal_reinjection)

    recovery_name = f"{name}_recovery"
    return [
        create_fpf_gar_playbook(
            name=name,
            description=description,
            prechecks=_health_checks(drained_devices=set()),
            postchecks=_health_checks(drained_devices=set(drain_devices)),
            stages=[
                create_steps_stage(stage_id=f"{name}_trigger", steps=disrupt_steps)
            ],
            override_duplicate_checks=False,
        ),
        create_fpf_gar_playbook(
            name=recovery_name,
            description=f"Recovery for {name}: undrain every target.",
            prechecks=_health_checks(
                drained_devices=set(drain_devices),
                include_vf=False,
            ),
            postchecks=_health_checks(drained_devices=set()),
            stages=[
                create_steps_stage(
                    stage_id=f"{recovery_name}_trigger", steps=recovery_steps
                )
            ],
            cleanup_steps=cleanup_steps,
            override_duplicate_checks=False,
        ),
    ]


def create_fpf_gar_class_d_test_config() -> TestConfig:
    playbooks: list[Playbook] = []
    playbooks += _class_d_playbooks(
        name="fpf_gar_d1_gtsw_plane1_drain",
        description=(
            "Class D-tc1: soft-drain the plane-1 l1002 source GTSW and require "
            "its VF, rack topology, and drain community to remain visible on "
            "the plane-1 spine and remote GTSW."
        ),
        drain_devices=[PLANE1_SOURCE],
        reinject_source=True,
    )
    playbooks += _class_d_playbooks(
        name="fpf_gar_d2_stsw_plane1_drain",
        description=(
            "Class D-tc2: soft-drain the plane-1 STSW and require the VF and "
            "rack topology to remain visible, with the drain community on the "
            "remote GTSW path."
        ),
        drain_devices=[PLANE1_SPINE],
        reinject_source=False,
    )
    playbooks += _class_d_playbooks(
        name="fpf_gar_d3_gtsw_stsw_plane1_drain",
        description=(
            "Class D-tc3: simultaneously soft-drain the plane-1 source GTSW "
            "and plane-1 STSW; require the VF and rack topology to remain "
            "visible with the drain community downstream."
        ),
        drain_devices=[PLANE1_SOURCE, PLANE1_SPINE],
        reinject_source=True,
    )
    playbooks += _class_d_playbooks(
        name="fpf_gar_d4_gtsw_plane1_stsw_plane2_drain",
        description=(
            "Class D-tc4: simultaneously soft-drain the plane-1 source GTSW "
            "and plane-2 STSW; require VF visibility, rack topology, and the "
            "drain community on both affected planes while plane 4 remains "
            "undrained."
        ),
        drain_devices=[PLANE1_SOURCE, PLANE2_SPINE],
        reinject_source=True,
    )

    return TestConfig(
        name="fpf_gar_class_d",
        endpoints=[
            Endpoint(name=CONTROLLER, dut=True),
            *[
                Endpoint(name=device, dut=False)
                for device in IN_SCOPE_DEVICES
                if device != CONTROLLER
            ],
        ],
        setup_tasks=[
            create_fpf_withdraw_vf_groups_task(groups=GAR_INJECTION_GROUPS),
            create_fpf_inject_vf_groups_task(
                groups=GAR_INJECTION_GROUPS,
                settle_sec=GAR_SETTLE_SEC,
            ),
        ],
        teardown_tasks=[
            create_fpf_withdraw_vf_groups_task(groups=GAR_INJECTION_GROUPS),
        ],
        playbooks=playbooks,
        tags=["fpf", "gar", "class-d", "network-only"],
    )


TEST_CONFIG = create_fpf_gar_class_d_test_config()
