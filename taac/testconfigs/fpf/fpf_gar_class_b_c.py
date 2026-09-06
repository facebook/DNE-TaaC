# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""MWG2 FPF GAR Class B, B-prime, and C network-only test configuration.

The setup task injects a common IPv6 prefix scale on the plane-1 and plane-4
source GTSWs. Every playbook validates those prefixes at the source BGP/Agent,
the plane STSW BGP/Agent, and the remote-pod observer BGP/Agent. Link failure
reduces the advertised GAR capacity and prunes Agent forwarding nexthops; a
complete 36-link failure must prune the injected prefixes from the spine and
observer entirely.
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
from taac.libs.fpf.inject_bgp_prefixes import GTSW_COMMUNITIES
from taac.playbooks.playbook_definitions import (
    create_fpf_gar_playbook,
)
from taac.stages.stage_definitions import create_steps_stage
from taac.steps.step_definitions import (
    create_fpf_bgp_prefix_injection_step,
    create_fpf_gar_set_links_step,
)
from taac.task_definitions import (
    create_fpf_inject_vf_groups_task,
    create_fpf_withdraw_vf_groups_task,
)
from taac.test_as_a_config.types import Endpoint, Playbook, TestConfig


PAIR_A_SOURCE = "gtsw001.l1002.c087.mwg2"
PAIR_A_SPINE = "stsw001.s001.l202.mwg2"
PAIR_A_OBSERVER = "gtsw001.l1001.c087.mwg2"
C_PAIR_A_SOURCE = "gtsw001.l1001.c087.mwg2"
C_PAIR_A_SPINE = PAIR_A_SPINE
C_PAIR_A_OBSERVER = "gtsw001.l1002.c087.mwg2"
C_PAIR_B_SOURCE = "gtsw001.l1002.c087.mwg2"
C_PAIR_B_SPINE = PAIR_A_SPINE
C_PAIR_B_OBSERVER = "gtsw001.l1001.c087.mwg2"
CONTROLLER = PAIR_A_SOURCE
IN_SCOPE_DEVICES = [
    PAIR_A_SOURCE,
    PAIR_A_SPINE,
    PAIR_A_OBSERVER,
]

UPLINK_PORTS = [
    "eth1/2/1",
    "eth1/2/5",
    "eth1/6/1",
    "eth1/6/5",
    "eth1/10/1",
    "eth1/10/5",
    "eth1/14/1",
    "eth1/14/5",
    "eth1/18/1",
    "eth1/18/5",
    "eth1/22/1",
    "eth1/22/5",
    "eth1/23/1",
    "eth1/23/5",
    "eth1/26/1",
    "eth1/26/5",
    "eth1/30/1",
    "eth1/30/5",
    "eth1/34/1",
    "eth1/34/5",
    "eth1/38/1",
    "eth1/38/5",
    "eth1/42/1",
    "eth1/42/5",
    "eth1/46/1",
    "eth1/46/5",
    "eth1/50/1",
    "eth1/50/5",
    "eth1/54/1",
    "eth1/54/5",
    "eth1/58/1",
    "eth1/58/5",
    "eth1/62/1",
    "eth1/62/5",
    "eth1/63/1",
    "eth1/63/5",
]

GAR_PREFIX_BASE = "5000:ca::/64"
C_PAIR_A_PREFIX_BASE = "5000:cc::/64"
GAR_PREFIX_COUNT = int(os.environ.get("FPF_GAR_PREFIX_COUNT", "1000"))
GAR_INCREMENT_STEP = "0:0:1::"
GAR_SETTLE_SEC = int(os.environ.get("FPF_GAR_INJECT_SETTLE_SEC", "30"))
GAR_VALIDATION_TIMEOUT_SEC = int(
    os.environ.get("FPF_GAR_VALIDATION_TIMEOUT_SEC", "120")
)
VF_PREFIX = get_prefix("rtptest1555.mwg2", 0)
C_PAIR_A_VF_PREFIX = get_prefix("rtptest1575.mwg2", 0)
DRAIN_COMMUNITY = "65446:10"
DRAIN_GTSW_COMMUNITIES = [*GTSW_COMMUNITIES, DRAIN_COMMUNITY]
SCALE_INJECTION_DEVICES = frozenset({PAIR_A_SOURCE, C_PAIR_A_SOURCE})
SCALE_PREFIX_BASE_BY_DEVICE = {
    PAIR_A_SOURCE: GAR_PREFIX_BASE,
    C_PAIR_A_SOURCE: C_PAIR_A_PREFIX_BASE,
}

GAR_INJECTION_GROUPS = [
    {
        "devices": [PAIR_A_SOURCE],
        "prefix_base": GAR_PREFIX_BASE,
        "count": GAR_PREFIX_COUNT,
        "increment_step": GAR_INCREMENT_STEP,
        "batch_size": 100,
        "community_list": "gtsw",
    },
    {
        "devices": [C_PAIR_A_SOURCE],
        "prefix_base": C_PAIR_A_PREFIX_BASE,
        "count": GAR_PREFIX_COUNT,
        "increment_step": GAR_INCREMENT_STEP,
        "batch_size": 100,
        "community_list": "gtsw",
    },
]


def _pairs(
    capacity_a: int,
    *,
    source_route_mode: str = "drop",
) -> list[dict[str, object]]:
    return [
        {
            "name": "pair-A-plane-1",
            "source": PAIR_A_SOURCE,
            "spine": PAIR_A_SPINE,
            "observer": PAIR_A_OBSERVER,
            "expected_capacity": capacity_a,
            "observer_path_count": 36,
            "spine_id": 1,
            "source_route_mode": source_route_mode,
        },
    ]


def _targets(count_a: int) -> list[dict[str, object]]:
    return [{"device": PAIR_A_SOURCE, "interfaces": UPLINK_PORTS[:count_a]}]


def _cross_pod_pairs(
    count_a: int,
    count_b: int,
    *,
    source_route_mode: str,
) -> list[dict[str, object]]:
    """Build reciprocal plane-1 GAR expectations for Class C.

    Pair A is l1001 -> l1002 and Pair B is l1002 -> l1001. Because both
    sides disable the same ordered link set, the smaller failed set is a
    subset of the larger one. The observer Agent should therefore retain
    ``36 - max(count_a, count_b)`` forwarding nexthops in both directions,
    rather than double-pruning the overlapping failures.
    """
    expected_forwarding = 36 - max(count_a, count_b)
    pair_a_observer_paths = 36 - count_b
    pair_b_observer_paths = 36 - count_a
    return [
        {
            "name": "pair-A-l1001-to-l1002-plane-1",
            "source": C_PAIR_A_SOURCE,
            "spine": C_PAIR_A_SPINE,
            "observer": C_PAIR_A_OBSERVER,
            "expected_capacity": 36 - count_a,
            # The observer's local failed links are removed from its BGP and
            # Agent client-nexthop sets before the remote GAR capacity is
            # applied to the forwarding set.
            "observer_path_count": pair_a_observer_paths,
            "observer_forwarding_count": expected_forwarding,
            "spine_id": 1,
            "source_route_mode": source_route_mode,
        },
        {
            "name": "pair-B-l1002-to-l1001-plane-1",
            "source": C_PAIR_B_SOURCE,
            "spine": C_PAIR_B_SPINE,
            "observer": C_PAIR_B_OBSERVER,
            "expected_capacity": 36 - count_b,
            "observer_path_count": pair_b_observer_paths,
            "observer_forwarding_count": expected_forwarding,
            "spine_id": 1,
            "source_route_mode": source_route_mode,
        },
    ]


def _gar_health_checks(
    *,
    capacity_a: int,
    include_scale: bool,
) -> list:
    checks = [
        create_fpf_gar_vf_capacity_check(
            pairs=_pairs(
                capacity_a,
                source_route_mode="vf",
            ),
            prefixes=[VF_PREFIX],
            timeout_sec=GAR_VALIDATION_TIMEOUT_SEC,
            poll_interval_sec=5,
            check_id="fpf_gar_vf_capacity",
        ),
    ]
    if include_scale:
        checks.append(
            create_fpf_gar_scale_capacity_check(
                pairs=_pairs(capacity_a),
                prefix_base=GAR_PREFIX_BASE,
                prefix_count=GAR_PREFIX_COUNT,
                increment_step=GAR_INCREMENT_STEP,
                timeout_sec=GAR_VALIDATION_TIMEOUT_SEC,
                poll_interval_sec=5,
                check_id="fpf_gar_scale_capacity",
            )
        )
    return checks


def _device_health_checks(
    *,
    target_interfaces: list[dict[str, str]],
    expected_down: list[dict[str, str]],
    include_fabric_baseline: bool,
) -> list:
    checks = [create_wedge_agent_configured_check()]
    # An admin-down on the GTSW also drops the peer STSW port. Without the
    # LLDP-derived peer interface in disabled_interfaces, the generic topology
    # PORT_STATE_CHECK correctly flags that expected peer-side DOWN. The trigger
    # itself reads back the GTSW admin state, and the GAR checks prove the remote
    # effect, so omit this generic check only during an admin-down state.
    if not expected_down:
        checks.insert(
            0,
            create_port_state_check(
                additional_interfaces=target_interfaces,
                disabled_interfaces=[],
                retry_count=30,
                retry_delay_seconds=10,
                retry_delay_multiplier=1,
            ),
        )
    if include_fabric_baseline:
        checks[:0] = [
            *[
                create_drain_state_check(
                    expected_drained=False,
                    device_name=device,
                )
                for device in IN_SCOPE_DEVICES
            ],
            create_bgp_session_establish_check(
                min_established_pct=0.7,
                retry_count=3,
                retry_delay_seconds=5,
            ),
        ]
        checks.append(
            create_bgp_rib_fib_consistency_check(
                retry_count=3,
                retry_delay_seconds=5,
            )
        )
    checks.extend(
        [
            create_systemctl_active_state_check(
                services_json=["bgpd", "wedge_agent", "qsfp_service"]
            ),
            create_unclean_exit_check(),
            create_device_core_dumps_check(),
        ]
    )
    return checks


def _health_checks(
    *,
    capacity_a: int,
    target_interfaces: list[dict[str, str]],
    expected_down: list[dict[str, str]],
    include_fabric_baseline: bool,
    include_scale: bool,
) -> list:
    return _device_health_checks(
        target_interfaces=target_interfaces,
        expected_down=expected_down,
        include_fabric_baseline=include_fabric_baseline,
    ) + _gar_health_checks(
        capacity_a=capacity_a,
        include_scale=include_scale,
    )


def _cross_pod_gar_checks(*, count_a: int, count_b: int) -> list:
    vf_pairs = _cross_pod_pairs(count_a, count_b, source_route_mode="vf")
    scale_pairs = _cross_pod_pairs(count_a, count_b, source_route_mode="drop")
    checks = []
    for suffix, pair, vf_prefix, scale_prefix_base in (
        (
            "pair_a",
            vf_pairs[0],
            C_PAIR_A_VF_PREFIX,
            C_PAIR_A_PREFIX_BASE,
        ),
        ("pair_b", vf_pairs[1], VF_PREFIX, GAR_PREFIX_BASE),
    ):
        checks.append(
            create_fpf_gar_vf_capacity_check(
                pairs=[pair],
                prefixes=[vf_prefix],
                timeout_sec=GAR_VALIDATION_TIMEOUT_SEC,
                poll_interval_sec=5,
                check_id=f"fpf_gar_cross_pod_vf_{suffix}",
            )
        )
        checks.append(
            create_fpf_gar_scale_capacity_check(
                pairs=[scale_pairs[0 if suffix == "pair_a" else 1]],
                prefix_base=scale_prefix_base,
                prefix_count=GAR_PREFIX_COUNT,
                increment_step=GAR_INCREMENT_STEP,
                timeout_sec=GAR_VALIDATION_TIMEOUT_SEC,
                poll_interval_sec=5,
                check_id=f"fpf_gar_cross_pod_scale_{suffix}",
            )
        )
    return checks


def _scale_reinjection_step(*, devices: list[str], drained: bool):
    prefix_bases = {SCALE_PREFIX_BASE_BY_DEVICE[device] for device in devices}
    if len(prefix_bases) != 1:
        raise ValueError(
            "Scale reinjection requires devices from exactly one prefix group; "
            f"got {devices}"
        )
    prefix_base = next(iter(prefix_bases))
    if drained:
        return create_fpf_bgp_prefix_injection_step(
            devices=devices,
            prefix_base=prefix_base,
            count=GAR_PREFIX_COUNT,
            increment_step=GAR_INCREMENT_STEP,
            batch_size=100,
            communities=DRAIN_GTSW_COMMUNITIES,
            description=(
                f"Re-inject {GAR_PREFIX_COUNT} scale prefixes with drain community "
                f"{DRAIN_COMMUNITY} after soft-drain"
            ),
        )
    return create_fpf_bgp_prefix_injection_step(
        devices=devices,
        prefix_base=prefix_base,
        count=GAR_PREFIX_COUNT,
        increment_step=GAR_INCREMENT_STEP,
        batch_size=100,
        community_list="gtsw",
        description=(
            f"Re-inject {GAR_PREFIX_COUNT} scale prefixes with normal GTSW "
            "communities after undrain"
        ),
    )


def _target_interfaces(targets: list[dict[str, object]]) -> list[dict[str, str]]:
    return [
        {"switch_name": str(target["device"]), "interface_name": interface}
        for target in targets
        for interface in t.cast(list[str], target["interfaces"])
    ]


def _gar_playbooks(
    *,
    name: str,
    description: str,
    mode: str,
    count_a: int,
) -> list[Playbook]:
    targets = _targets(count_a)
    capacity_a = 36 - count_a
    expected_down = _target_interfaces(targets) if mode == "admin" else []
    disrupt = create_fpf_gar_set_links_step(
        targets=targets,
        mode=mode,
        disrupt=True,
        device_regexes=[CONTROLLER],
        description=f"{name}: apply {mode} disruption",
    )
    restore = create_fpf_gar_set_links_step(
        targets=targets,
        mode=mode,
        disrupt=False,
        device_regexes=[CONTROLLER],
        description=f"{name}: restore all affected links",
    )
    include_scale = mode != "softdrain"
    disrupt_steps = [disrupt]
    restore_steps = [restore]
    cleanup_steps = [restore]
    if mode == "softdrain":
        injection_devices = [
            str(target["device"])
            for target in targets
            if str(target["device"]) in SCALE_INJECTION_DEVICES
        ]
        disrupt_steps.append(
            _scale_reinjection_step(devices=injection_devices, drained=True)
        )
        normal_reinjection = _scale_reinjection_step(
            devices=injection_devices,
            drained=False,
        )
        restore_steps.append(normal_reinjection)
        cleanup_steps.append(normal_reinjection)
    disrupt_playbook = create_fpf_gar_playbook(
        name=name,
        description=description,
        prechecks=_health_checks(
            capacity_a=36,
            target_interfaces=_target_interfaces(targets),
            expected_down=[],
            include_fabric_baseline=True,
            include_scale=include_scale,
        ),
        postchecks=_health_checks(
            capacity_a=capacity_a,
            target_interfaces=_target_interfaces(targets),
            expected_down=expected_down,
            include_fabric_baseline=False,
            include_scale=include_scale,
        ),
        stages=[
            create_steps_stage(
                stage_id=f"{name}_trigger",
                steps=disrupt_steps,
            ),
        ],
        # Preserve the independently scoped drain-state check for every switch.
        override_duplicate_checks=False,
    )
    if "_down_" in name:
        restore_name = name.replace("_down_", "_up_")
    elif "_softdrain_" in name:
        restore_name = name.replace("_softdrain_", "_undrain_")
    else:
        restore_name = f"{name}_recovery"
    restore_playbook = create_fpf_gar_playbook(
        name=restore_name,
        description=f"Recovery for {name}: restore the affected links and verify 36.",
        prechecks=_health_checks(
            capacity_a=capacity_a,
            target_interfaces=_target_interfaces(targets),
            expected_down=expected_down,
            include_fabric_baseline=False,
            include_scale=include_scale,
        ),
        postchecks=_health_checks(
            capacity_a=36,
            target_interfaces=_target_interfaces(targets),
            expected_down=[],
            include_fabric_baseline=True,
            include_scale=include_scale,
        ),
        stages=[
            create_steps_stage(
                stage_id=f"{restore_name}_trigger",
                steps=restore_steps,
            )
        ],
        cleanup_steps=cleanup_steps,
        # Preserve the independently scoped drain-state check for every switch.
        override_duplicate_checks=False,
    )
    return [disrupt_playbook, restore_playbook]


def _cross_pod_health_checks(
    *,
    count_a: int,
    count_b: int,
    target_interfaces: list[dict[str, str]],
    expected_down: list[dict[str, str]],
    include_fabric_baseline: bool,
) -> list:
    return _device_health_checks(
        target_interfaces=target_interfaces,
        expected_down=expected_down,
        include_fabric_baseline=include_fabric_baseline,
    ) + _cross_pod_gar_checks(count_a=count_a, count_b=count_b)


def _cross_pod_playbooks(
    *,
    name: str,
    description: str,
    count_a: int,
    count_b: int,
) -> list[Playbook]:
    targets: list[dict[str, object]] = [
        {"device": C_PAIR_A_SOURCE, "interfaces": UPLINK_PORTS[:count_a]},
        {"device": C_PAIR_B_SOURCE, "interfaces": UPLINK_PORTS[:count_b]},
    ]
    target_interfaces = _target_interfaces(targets)
    disrupt = create_fpf_gar_set_links_step(
        targets=targets,
        mode="admin",
        disrupt=True,
        device_regexes=[CONTROLLER],
        description=f"{name}: disable both cross-pod member-link sets",
    )
    restore = create_fpf_gar_set_links_step(
        targets=targets,
        mode="admin",
        disrupt=False,
        device_regexes=[CONTROLLER],
        description=f"{name}: restore both cross-pod member-link sets",
    )
    recovery_name = f"{name}_recovery"
    return [
        create_fpf_gar_playbook(
            name=name,
            description=description,
            prechecks=_cross_pod_health_checks(
                count_a=0,
                count_b=0,
                target_interfaces=target_interfaces,
                expected_down=[],
                include_fabric_baseline=True,
            ),
            postchecks=_cross_pod_health_checks(
                count_a=count_a,
                count_b=count_b,
                target_interfaces=target_interfaces,
                expected_down=target_interfaces,
                include_fabric_baseline=False,
            ),
            stages=[create_steps_stage(stage_id=f"{name}_trigger", steps=[disrupt])],
            override_duplicate_checks=False,
        ),
        create_fpf_gar_playbook(
            name=recovery_name,
            description=f"Recovery for {name}: restore both bundles to 36.",
            prechecks=_cross_pod_health_checks(
                count_a=count_a,
                count_b=count_b,
                target_interfaces=target_interfaces,
                expected_down=target_interfaces,
                include_fabric_baseline=False,
            ),
            postchecks=_cross_pod_health_checks(
                count_a=0,
                count_b=0,
                target_interfaces=target_interfaces,
                expected_down=[],
                include_fabric_baseline=True,
            ),
            stages=[
                create_steps_stage(stage_id=f"{recovery_name}_trigger", steps=[restore])
            ],
            cleanup_steps=[restore],
            override_duplicate_checks=False,
        ),
    ]


def create_fpf_gar_class_b_c_test_config() -> TestConfig:
    playbooks: list[Playbook] = []
    for index, count in enumerate((1, 2, 3, 4, 6, 18), start=1):
        playbooks += _gar_playbooks(
            name=f"fpf_gar_b{index}_admin_down_{count}",
            description=(
                f"Class B{index}: administratively disable {count} member link(s) "
                f"on pair A and require GAR capacity {36 - count}."
            ),
            mode="admin",
            count_a=count,
        )
    playbooks += _gar_playbooks(
        name="fpf_gar_b7a_admin_down_35",
        description="Class B7a: leave one live member; require capacity 1.",
        mode="admin",
        count_a=35,
    )
    playbooks += _gar_playbooks(
        name="fpf_gar_b7b_admin_down_36",
        description=(
            "Class B7b: disable the complete pair-A bundle and require all "
            "scale prefixes to be pruned from the spine and observer."
        ),
        mode="admin",
        count_a=36,
    )
    for index, count in enumerate((1, 2, 3, 4, 6, 18), start=1):
        playbooks += _gar_playbooks(
            name=f"fpf_gar_bprime{index}_softdrain_{count}",
            description=(
                f"Class B-prime{index}: soft-drain {count} member link(s) on "
                f"pair A while links stay physically up; require capacity {36 - count}."
            ),
            mode="softdrain",
            count_a=count,
        )
    playbooks += _cross_pod_playbooks(
        name="fpf_gar_c1_multi_pair_3_6",
        description=(
            "Class C1: l1001 loses 3 links and l1002 loses 6 on plane 1; "
            "validate reciprocal GAR capacity and overlapping-path pruning."
        ),
        count_a=3,
        count_b=6,
    )
    playbooks += _cross_pod_playbooks(
        name="fpf_gar_c2_multi_pair_2_6",
        description=(
            "Class C2: l1001 loses 2 links and l1002 loses 6 on plane 1; "
            "validate reciprocal GAR capacity and overlapping-path pruning."
        ),
        count_a=2,
        count_b=6,
    )
    playbooks += _cross_pod_playbooks(
        name="fpf_gar_c3_multi_pair_4_6",
        description=(
            "Class C3: l1001 loses 4 links and l1002 loses 6 on plane 1; "
            "validate reciprocal GAR capacity and overlapping-path pruning."
        ),
        count_a=4,
        count_b=6,
    )

    return TestConfig(
        name="fpf_gar_class_b_c",
        endpoints=[
            Endpoint(name=PAIR_A_SOURCE, dut=True),
            # The remaining switches participate in validation and health checks,
            # but must not cause TaacRunner to repeat the controller-scoped
            # playbook once per endpoint.
            Endpoint(name=PAIR_A_SPINE, dut=False),
            Endpoint(name=PAIR_A_OBSERVER, dut=False),
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
        tags=["fpf", "gar", "network-only"],
    )


TEST_CONFIG = create_fpf_gar_class_b_c_test_config()
