# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""Spec 2.1 — Distribution Correctness. UG qualification testconfig factory.

Merges the former bag013 initial-dump path (previously grandfathered as an
empty-playbook TestConfig inside the sustained-link-flap TC) and the eb03
initial-dump lab-box variant into a single spec-anchored factory that
dispatches internally on ``testbed.device_name``.

Golden regen for ``BAG013_ASH6_BGP_UG_INITIAL_DUMP_IDENTICAL_ROUTES_TEST_CONFIG``
is EXPECTED and legitimate: the former empty-playbook TestConfig is
replaced by a TestConfig that actually wires the 2.1.1 playbook. The
eb03 catalog constant remains byte-wise identical.

The bag conveyor topology builder is re-used by tc7 (sustained link flap)
and tc9 (edge cases), so ``build_bag_conveyor_test_config`` is a public
helper.
"""

import json
import os
import typing as t

from taac.constants import BgpPlusPlusProfile
from taac.health_checks.healthcheck_definitions import (
    create_bgp_graceful_restart_check,
    create_bgp_update_group_check,
)
from taac.playbooks.playbook_definitions import (
    build_arista_ebb_scale_playbook,
)
from taac.playbooks.routing.factories.qual_bgp_update_group.tc1_distribution_correctness import (
    create_bgp_ug_initial_dump_identical_routes_playbook,
)
from taac.stages.stage_definitions import create_steps_stage
from taac.steps.step_definitions import (
    create_custom_step,
    create_longevity_step,
    create_validation_step,
)
from taac.testconfigs.routing.testbed import Testbed
from taac.testconfigs.routing.util.bgp_ebb_constants import (
    DEFAULT_PROFILE,
    EBGP_PEER_COUNT_V4,
    EBGP_PEER_COUNT_V6,
    EBGP_PEER_TO_DRAIN,
    EBGP_REMOTE_AS,
    IBGP_PEER_SCALE_PER_PLANE,
    IBGP_PEER_TO_DRAIN_PER_PLANE,
    IBGP_REMOTE_AS,
    IXIA_EBGP_IC_PARENT_NETWORK_V4,
    IXIA_EBGP_IC_PARENT_NETWORK_V6,
    IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE1,
    IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE2,
    IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE3,
    IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE4,
    IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE1,
    IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE2,
    IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE3,
    IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE4,
    IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1,
    IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE2,
    IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE3,
    IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE4,
    IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE1,
    IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE2,
    IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE3,
    IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE4,
    PEERGROUP_BGP_MON,
    PEERGROUP_EBGP_V6,
    PEERGROUP_IBGP_V4,
    PEERGROUP_IBGP_V6,
)
from taac.testconfigs.routing.util.bgp_ebb_health_checks import (
    BGP_STANDARD_POSTCHECKS,
    BGP_STANDARD_PRECHECKS,
    BGP_STANDARD_SNAPSHOT_CHECKS,
)
from taac.testconfigs.routing.util.bgp_ebb_ixia_config import (
    create_ebb_scale_basic_port_configs,
)
from taac.testconfigs.routing.util.bgp_ebb_setup_tasks import (
    get_common_setup_tasks,
    get_teardown_tasks,
)
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import DirectIxiaConnection, Endpoint, TestConfig


# =============================================================================
# BAG conveyor topology — shared builder re-used by tc7 / tc9 as well.
# =============================================================================
#
# Wave 6 factoring: the previous ``_create_bag013_ash6_conveyor_test_config_impl``
# built one TestConfig with EITHER [] playbooks (default) or [2.1.1, 2.7.2]
# (``enable_update_group=True``). Wave 6 splits that mono-TC into per-spec-section
# TestConfigs (tc1 = 2.1.1 only, tc7 = 2.7.2 only); this helper accepts the
# playbook list + TestConfig ``name`` field as parameters so each spec-section
# factory can build its own TestConfig on the same underlying bag conveyor
# topology. Every value is read from the passed ``testbed`` (device_name,
# dut_bgp_as, ixia_ports, bgpcpp path), so the builder is DUT-agnostic across
# the bag010/011/012/013 EBB conveyor nodes; the tc9 edge-cases factory reuses
# it for bag011.


def build_bag_conveyor_test_config(
    testbed: Testbed,
    *,
    name: str,
    playbooks: t.List[taac_types.Playbook],
    profile: BgpPlusPlusProfile = BgpPlusPlusProfile.BGP_PLUS_PLUS_WITHOUT_OPEN_R,
    enable_update_group: bool = True,
    # Forwarded to create_ebb_scale_basic_port_configs; when False the eBGP peers
    # are built with graceful restart disabled (the 2.9.2 simultaneous-disruptions
    # test flaps eBGP sessions "without graceful restart" per spec). Default True
    # is byte-identical to the previous behavior (non-optional thrift field
    # defaulting True), so existing bag goldens are unchanged.
    ebgp_graceful_restart: bool = True,
    # Forwarded to create_ebb_scale_basic_port_configs: optional inline-generated
    # spare IPv4 eBGP route pool(s) (RouteScale, no CSV). 2.9.4 dual-stack
    # isolation uses this for genuinely-new IPv4 prefixes advertised at runtime.
    # None -> byte-identical for other callers.
    ebgp_v4_extra_route_scales: list[taac_types.RouteScaleSpec] | None = None,
) -> taac_types.TestConfig:
    """Shared bag conveyor topology TestConfig builder.

    Wave 6 factoring of the legacy
    ``bag013_ash6_test_config.create_bag013_ash6_conveyor_test_config()``
    body. Callers pass the exact TestConfig ``name`` + playbook list they
    need. UG qualification never exercises BGP-MON or OpenR, so this
    builder wires only the eBGP + iBGP topology (``include_bgp_mon=False``)
    and defaults ``profile`` to ``WITHOUT_OPEN_R``.

    DUT-agnostic across the bag010/011/012/013 EBB conveyor nodes: every
    value is read from ``testbed`` (device_name, dut_bgp_as, ixia_ports,
    bgpcpp_configerator_path), so cloning to a new bag node is a one-line
    catalog change. Renamed from ``build_bag013_conveyor_test_config``
    (formerly bag013-hardcoded) during the tc9 edge-cases work;
    behavior-preserving, so existing bag013 goldens stay byte-identical.
    """
    assert testbed.device_name.startswith("bag"), (
        f"bag conveyor topology builder targets bag* EBB conveyor nodes; "
        f"got testbed.device_name={testbed.device_name!r}."
    )
    assert testbed.dut_bgp_as is not None, "Testbed must have dut_bgp_as set"
    assert testbed.bgpcpp_configerator_path is not None, (
        "Testbed must have bgpcpp_configerator_path set for BGP++ deployment"
    )
    assert len(testbed.ixia_ports) >= 2, (
        "Testbed must have >= 2 IXIA ports (eBGP + iBGP)"
    )

    device_name = testbed.device_name
    ixia_chassis_ip = testbed.ixia_chassis_ip
    ixia_interface_mimic_ebgp, ixia_port_ebgp = testbed.ixia_ports[0]
    ixia_interface_mimic_ibgp, ixia_port_ibgp = testbed.ixia_ports[1]

    # Open/R setup is wired ONLY for the WITH_OPEN_R profile. get_common_setup_tasks
    # deploys the openr_config + injects baseline Open/R routes whenever an
    # openr_configerator_path is passed, so forwarding these unconditionally would
    # add Open/R tasks to the WITHOUT_OPEN_R configs and change their goldens. Under
    # WITHOUT_OPEN_R ``openr_kwargs`` stays empty -> byte-identical to before.
    # bag011's testbed carries every openr_* field (testbed.py); this mirrors the
    # full-scale builder's wiring so a WITH_OPEN_R bag config (e.g. the 2.9.2
    # simultaneous-disruptions test, which needs Open/R for its IGP-instability
    # track) gets a functional Open/R daemon + port-channel + injected routes.
    openr_kwargs: t.Dict[str, t.Any] = {}
    if profile == BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R:
        extras = testbed.extras
        openr_kwargs = {
            "openr_configerator_path": testbed.openr_configerator_path,
            "openr_port_channel_member": extras["openr_port_channel_member"],
            "openr_port_channel_ipv4": extras["openr_port_channel_ipv4"],
            "openr_port_channel_link_local": extras["openr_port_channel_link_local"],
            "openr_local_link": extras["openr_local_link"],
            "openr_other_link": extras["openr_other_link"],
        }

    setup_tasks = get_common_setup_tasks(
        device_name=device_name,
        bgp_asn=testbed.dut_bgp_as,
        ixia_interface_mimic_ebgp=ixia_interface_mimic_ebgp,
        ixia_interface_mimic_ibgp=ixia_interface_mimic_ibgp,
        bgpcpp_configerator_path=testbed.bgpcpp_configerator_path,
        profile=profile,
        include_bgp_mon=False,
        enable_update_group=enable_update_group,
        **openr_kwargs,
    )

    # Pass device_name so the interface-cleanup teardown tasks target the DUT.
    # Without it the tasks get hostname=None and teardown fails resolving the
    # device OS type ("Cannot determine device OS type for None") -- the reserved-
    # device context isn't available under --skip-basset-reservation, so teardown
    # relies on the task hostname to look up host_os_type_map (populated at setup).
    # Matches the full-scale builder (bgp_ebb_full_scale.py) which already does this.
    teardown_tasks = get_teardown_tasks(
        ixia_interface_mimic_ebgp=ixia_interface_mimic_ebgp,
        ixia_interface_mimic_ibgp=ixia_interface_mimic_ibgp,
        device_name=device_name,
    )

    return taac_types.TestConfig(
        name=name,
        skip_ixia_protocol_verification=True,
        log_collection_timeout=600,
        basset_pool="dne.test",
        endpoints=[
            taac_types.Endpoint(
                name=device_name,
                dut=True,
                ixia_ports=[
                    ixia_interface_mimic_ebgp,
                    ixia_interface_mimic_ibgp,
                ],
                direct_ixia_connections=[
                    taac_types.DirectIxiaConnection(
                        interface=ixia_interface_mimic_ebgp,
                        ixia_chassis_ip=ixia_chassis_ip,
                        ixia_port=ixia_port_ebgp,
                    ),
                    taac_types.DirectIxiaConnection(
                        interface=ixia_interface_mimic_ibgp,
                        ixia_chassis_ip=ixia_chassis_ip,
                        ixia_port=ixia_port_ibgp,
                    ),
                ],
            ),
        ],
        host_os_type_map={device_name: taac_types.DeviceOsType.ARISTA_FBOSS},
        startup_checks=[],
        setup_tasks=setup_tasks,
        teardown_tasks=teardown_tasks,
        basic_port_configs=create_ebb_scale_basic_port_configs(
            device_name=device_name,
            ixia_interface_mimic_ebgp=ixia_interface_mimic_ebgp,
            ixia_interface_mimic_ibgp=ixia_interface_mimic_ibgp,
            ebgp_peer_count_v6=EBGP_PEER_COUNT_V6,
            ebgp_peer_count_v4=EBGP_PEER_COUNT_V4,
            ebgp_peer_to_drain=EBGP_PEER_TO_DRAIN,
            ibgp_peer_scale_per_plane=IBGP_PEER_SCALE_PER_PLANE,
            ibgp_peer_to_drain_per_plane=IBGP_PEER_TO_DRAIN_PER_PLANE,
            ebgp_remote_as=EBGP_REMOTE_AS,
            ibgp_remote_as=IBGP_REMOTE_AS,
            ixia_ebgp_ic_parent_network_v6=IXIA_EBGP_IC_PARENT_NETWORK_V6,
            ixia_ebgp_ic_parent_network_v4=IXIA_EBGP_IC_PARENT_NETWORK_V4,
            ixia_ibgp_ic_parent_network_v6_dc_plane1=IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1,
            ixia_ibgp_ic_parent_network_v6_dc_plane2=IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE2,
            ixia_ibgp_ic_parent_network_v6_dc_plane3=IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE3,
            ixia_ibgp_ic_parent_network_v6_dc_plane4=IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE4,
            ixia_ibgp_ic_parent_network_v6_mp_plane1=IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE1,
            ixia_ibgp_ic_parent_network_v6_mp_plane2=IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE2,
            ixia_ibgp_ic_parent_network_v6_mp_plane3=IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE3,
            ixia_ibgp_ic_parent_network_v6_mp_plane4=IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE4,
            ixia_ibgp_ic_parent_network_v4_dc_plane1=IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE1,
            ixia_ibgp_ic_parent_network_v4_dc_plane2=IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE2,
            ixia_ibgp_ic_parent_network_v4_dc_plane3=IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE3,
            ixia_ibgp_ic_parent_network_v4_dc_plane4=IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE4,
            ixia_ibgp_ic_parent_network_v4_mp_plane1=IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE1,
            ixia_ibgp_ic_parent_network_v4_mp_plane2=IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE2,
            ixia_ibgp_ic_parent_network_v4_mp_plane3=IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE3,
            ixia_ibgp_ic_parent_network_v4_mp_plane4=IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE4,
            include_bgp_mon=False,
            profile=profile,
            ebgp_graceful_restart=ebgp_graceful_restart,
            ebgp_v4_extra_route_scales=ebgp_v4_extra_route_scales,
        ),
        playbooks=playbooks,
    )


# =============================================================================
# EB03 lab-box variant helpers (BGP++ UG spec 2.1.1 on eb03.lab.ash6)
# =============================================================================


def _create_eb03_2_1_1_initial_dump_identical_routes_playbook(testbed: Testbed):
    """eb03-specific BGP++ Update Group qualification 2.1.1 playbook.

    Byte-wise identical to the legacy
    ``eb03_update_group_test_config._create_2_1_1_initial_dump_identical_routes_playbook``.
    Pinned expected_member_counts (EB-EB-V6=496, EB-FA-V6=140, BGP-MON=2) and
    policy_names are eb03-specific golden values from the live device.
    """
    assert len(testbed.ixia_ports) >= 3, (
        "eb03 2.1.1 playbook requires >= 3 IXIA ports; ixia_ports[2] is the "
        "BGP-MON DUT interface used by the pcap-capture step even though "
        "the containing test config skips BGP-MON in setup/teardown."
    )
    ibgp_dut_iface, _ = testbed.ixia_ports[1]
    bgp_mon_dut_iface, _ = testbed.ixia_ports[2]

    prechecks = [
        *BGP_STANDARD_PRECHECKS,
        create_bgp_graceful_restart_check(
            peer_group_name=PEERGROUP_IBGP_V6,
            expected_graceful_restart_enabled=False,
            check_id="eb03_2_1_1_gr_disabled_ibgp_v6",
        ),
        create_bgp_graceful_restart_check(
            peer_group_name=PEERGROUP_IBGP_V4,
            expected_graceful_restart_enabled=False,
            check_id="eb03_2_1_1_gr_disabled_ibgp_v4",
        ),
    ]
    verify_step = create_validation_step(
        point_in_time_checks=[
            create_bgp_update_group_check(
                peer_group_substrings=[
                    PEERGROUP_IBGP_V6,
                    PEERGROUP_EBGP_V6,
                    PEERGROUP_BGP_MON,
                ],
                expected_group_count=5,
                expected_member_counts={
                    PEERGROUP_IBGP_V6: 496,
                    PEERGROUP_EBGP_V6: 140,
                    PEERGROUP_BGP_MON: 2,
                },
                expected_policy_names={
                    PEERGROUP_IBGP_V6: ["EB-EB-OUT"],
                    PEERGROUP_EBGP_V6: ["EB-FA-OUT"],
                    PEERGROUP_BGP_MON: ["PROPAGATE_EVERYTHING_OUT"],
                },
                check_id="eb03_2_1_1_update_group_membership",
            )
        ],
        description=(
            "BGP++ Update Group qualification 2.1.1 -- verify EB-EB-V6 iBGP (496 "
            "members, EB-EB-OUT), EB-FA-V6 eBGP (140, EB-FA-OUT) and BGP-MON "
            "(2, PROPAGATE_EVERYTHING_OUT) form distinct update groups, with 5 "
            "groups total (one per peer-group per AFI + BGP-MON)."
        ),
    )
    pcap_compare_step = create_custom_step(
        params_dict={
            "custom_step_name": "test_bgp_update_group_dump_compare",
            "hostname": testbed.device_name,
            "ixia_capture_interface": ibgp_dut_iface,
            "ibgp_peer_regex": "BGP_PEER_IPV6_IBGP_PLANE_1_REMOTE_EB",
            "ibgp_peer_session_indices": [1, 2],
            "capture_duration_seconds": 300,
            "settle_seconds": 10,
            "bgp_mon_capture_interface": bgp_mon_dut_iface,
            "bgp_mon_peer_regex": "BGP_PEER_IPV6_BGP_MON",
            "bgp_mon_session_index": 1,
        },
        description=(
            "BGP++ Update Group 2.1.1 steps 6-7 -- capture and compare the "
            "initial-dump UPDATEs to two iBGP peers in the same update group "
            "(identical NLRI/AS_PATH/LOCAL_PREF/COMMUNITY/MED; next-hop may differ)."
        ),
    )
    return build_arista_ebb_scale_playbook(
        name="eb03_2_1_1_initial_dump_identical_routes",
        stages=[
            create_steps_stage(steps=[verify_step]),
            create_steps_stage(steps=[pcap_compare_step]),
        ],
        prechecks=prechecks,
        postchecks=BGP_STANDARD_POSTCHECKS,
        snapshot_checks=BGP_STANDARD_SNAPSHOT_CHECKS,
    )


def _create_eb03_longevity_debugging_playbook():
    """eb03-specific longevity soak playbook — byte-wise identical to legacy inline."""
    return build_arista_ebb_scale_playbook(
        name="eb03_longevity_debugging",
        prechecks=[
            create_bgp_update_group_check(
                peer_group_substrings=[
                    PEERGROUP_IBGP_V6,
                    PEERGROUP_EBGP_V6,
                    PEERGROUP_BGP_MON,
                ],
                check_id="eb03_longevity_update_group_probe",
            ),
        ],
        stages=[
            create_steps_stage(
                steps=[create_longevity_step(duration=20)],
            ),
        ],
    )


def _create_eb03_distribution_correctness_test_config(
    testbed: Testbed,
    profile: BgpPlusPlusProfile,
) -> taac_types.TestConfig:
    """eb03.lab.ash6 branch of tc1.

    UG qualification never exercises BGP-MON or OpenR, so this branch wires
    only eBGP + iBGP (``include_bgp_mon=False``) and hard-codes
    ``WITHOUT_OPEN_R``. ``profile`` is accepted for signature parity with the
    outer factory but no longer affects setup / port-config wiring.

    Differs from the bag013 branch:
      - ``host_driver_args`` for admin/password auth (svc-netcastle_bot not
        authorized on the lab device)
      - ``oss_mock_device_data`` MockDeviceInfo (netwhoami returns #INVALID#)
      - Playbooks pin eb03-specific expected_member_counts / policy_names
    """
    assert len(testbed.ixia_ports) >= 2, (
        "eb03 UG initial-dump requires >= 2 IXIA ports (eBGP + iBGP)."
    )
    assert testbed.dut_bgp_as is not None, "Testbed must have dut_bgp_as set"
    assert testbed.bgpcpp_configerator_path is not None, (
        "Testbed must have bgpcpp_configerator_path set"
    )

    ebgp_dut_iface, ebgp_chassis_port = testbed.ixia_ports[0]
    ibgp_dut_iface, ibgp_chassis_port = testbed.ixia_ports[1]

    lab_password_env = (
        testbed.lab_device_password_env_var or "TAAC_EBB_LAB_DEVICE_PASSWORD"
    )
    lab_admin_username = testbed.extras.get("lab_admin_username", "admin")
    lab_admin_password_default = testbed.extras.get(
        "lab_admin_password_default",
        "dnepit",  # pragma: allowlist secret
    )
    lab_password = os.environ.get(lab_password_env, lab_admin_password_default)

    setup_tasks = get_common_setup_tasks(
        device_name=testbed.device_name,
        bgp_asn=testbed.dut_bgp_as,
        ixia_interface_mimic_ebgp=ebgp_dut_iface,
        ixia_interface_mimic_ibgp=ibgp_dut_iface,
        bgpcpp_configerator_path=testbed.bgpcpp_configerator_path,
        profile=BgpPlusPlusProfile.BGP_PLUS_PLUS_WITHOUT_OPEN_R,
        include_bgp_mon=False,
        enable_update_group=True,
    )

    # Pass device_name so teardown tasks target the DUT (else hostname=None ->
    # "Cannot determine device OS type for None" at teardown). See the shared
    # builder above for the full rationale.
    teardown_tasks = get_teardown_tasks(
        ixia_interface_mimic_ebgp=ebgp_dut_iface,
        ixia_interface_mimic_ibgp=ibgp_dut_iface,
        device_name=testbed.device_name,
    )

    return TestConfig(
        name="EB03_LAB_ASH6_BGP_TEST_UPDATE_GROUP_CONFIG",
        skip_ixia_protocol_verification=True,
        log_collection_timeout=600,
        basset_pool="dne.test",
        host_driver_args={
            testbed.device_name: json.dumps(
                {"username": lab_admin_username, "password": lab_password}
            ),
        },
        endpoints=[
            Endpoint(
                name=testbed.device_name,
                dut=True,
                ixia_ports=[
                    ebgp_dut_iface,
                    ibgp_dut_iface,
                ],
                direct_ixia_connections=[
                    DirectIxiaConnection(
                        interface=ebgp_dut_iface,
                        ixia_chassis_ip=testbed.ixia_chassis_ip,
                        ixia_port=ebgp_chassis_port,
                    ),
                    DirectIxiaConnection(
                        interface=ibgp_dut_iface,
                        ixia_chassis_ip=testbed.ixia_chassis_ip,
                        ixia_port=ibgp_chassis_port,
                    ),
                ],
            ),
        ],
        host_os_type_map={testbed.device_name: taac_types.DeviceOsType.ARISTA_FBOSS},
        oss_mock_device_data={
            testbed.device_name: taac_types.MockDeviceInfo(
                name=testbed.device_name,
                hardware=testbed.extras.get("mock_device_hardware", "ARISTA_7516"),
                role=testbed.extras.get("mock_device_role", "EB"),
                operating_system="EOS",
                dc=testbed.extras.get("mock_device_dc", "ash6"),
                region=testbed.extras.get("mock_device_region", "ash"),
                asset_id=testbed.extras.get("mock_device_asset_id", 12345),
                asic=testbed.extras.get("mock_device_asic", "JERICHO"),
                routing_protocol="BGP",
                dc_type="ONE",
                network_area=testbed.extras.get("mock_device_network_area", "BACKBONE"),
                network_area_type="BACKBONE",
                network_type=testbed.extras.get("mock_device_network_type", "EBB"),
            ),
        },
        startup_checks=[],
        setup_tasks=setup_tasks,
        teardown_tasks=teardown_tasks,
        basic_port_configs=create_ebb_scale_basic_port_configs(
            device_name=testbed.device_name,
            ixia_interface_mimic_ebgp=ebgp_dut_iface,
            ixia_interface_mimic_ibgp=ibgp_dut_iface,
            ebgp_peer_count_v6=EBGP_PEER_COUNT_V6,
            ebgp_peer_count_v4=EBGP_PEER_COUNT_V4,
            ebgp_peer_to_drain=EBGP_PEER_TO_DRAIN,
            ibgp_peer_scale_per_plane=IBGP_PEER_SCALE_PER_PLANE,
            ibgp_peer_to_drain_per_plane=IBGP_PEER_TO_DRAIN_PER_PLANE,
            ebgp_remote_as=EBGP_REMOTE_AS,
            ibgp_remote_as=IBGP_REMOTE_AS,
            ixia_ebgp_ic_parent_network_v6=IXIA_EBGP_IC_PARENT_NETWORK_V6,
            ixia_ebgp_ic_parent_network_v4=IXIA_EBGP_IC_PARENT_NETWORK_V4,
            ixia_ibgp_ic_parent_network_v6_dc_plane1=IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1,
            ixia_ibgp_ic_parent_network_v6_dc_plane2=IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE2,
            ixia_ibgp_ic_parent_network_v6_dc_plane3=IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE3,
            ixia_ibgp_ic_parent_network_v6_dc_plane4=IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE4,
            ixia_ibgp_ic_parent_network_v6_mp_plane1=IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE1,
            ixia_ibgp_ic_parent_network_v6_mp_plane2=IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE2,
            ixia_ibgp_ic_parent_network_v6_mp_plane3=IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE3,
            ixia_ibgp_ic_parent_network_v6_mp_plane4=IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE4,
            ixia_ibgp_ic_parent_network_v4_dc_plane1=IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE1,
            ixia_ibgp_ic_parent_network_v4_dc_plane2=IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE2,
            ixia_ibgp_ic_parent_network_v4_dc_plane3=IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE3,
            ixia_ibgp_ic_parent_network_v4_dc_plane4=IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE4,
            ixia_ibgp_ic_parent_network_v4_mp_plane1=IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE1,
            ixia_ibgp_ic_parent_network_v4_mp_plane2=IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE2,
            ixia_ibgp_ic_parent_network_v4_mp_plane3=IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE3,
            ixia_ibgp_ic_parent_network_v4_mp_plane4=IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE4,
            include_bgp_mon=False,
            profile=BgpPlusPlusProfile.BGP_PLUS_PLUS_WITHOUT_OPEN_R,
        ),
        playbooks=[
            _create_eb03_2_1_1_initial_dump_identical_routes_playbook(testbed),
            _create_eb03_longevity_debugging_playbook(),
        ],
    )


def _create_bag013_distribution_correctness_test_config(
    testbed: Testbed,
    profile: BgpPlusPlusProfile,
) -> taac_types.TestConfig:
    """bag013 branch of tc1 — wires ONLY the 2.1.1 playbook.

    UG qualification does not exercise BGP-MON, but the underlying
    ``create_bgp_ug_initial_dump_identical_routes_playbook`` still uses the
    BGP-MON DUT interface as a pcap-capture handle in its 2.1.1 pcap
    compare step. The interface is left addressed on the DUT (see the
    testbed's third ixia port); only the BGP-MON IXIA session + IP config
    are removed via ``include_bgp_mon=False`` inside
    ``build_bag_conveyor_test_config``. ``profile`` is accepted for
    signature parity with the outer factory but forced to ``WITHOUT_OPEN_R``.
    """
    assert len(testbed.ixia_ports) >= 3, (
        "bag013 tc1 branch requires >= 3 IXIA ports; ixia_ports[2] is the "
        "BGP-MON DUT interface used by the playbook's pcap-capture step "
        "even though the shared builder skips BGP-MON in setup/teardown."
    )
    device_name = testbed.device_name
    ixia_interface_mimic_ibgp, _ = testbed.ixia_ports[1]
    ixia_interface_mimic_bgp_mon, _ = testbed.ixia_ports[2]

    playbook = create_bgp_ug_initial_dump_identical_routes_playbook(
        device_name=device_name,
        ixia_interface_mimic_ibgp=ixia_interface_mimic_ibgp,
        ixia_interface_mimic_bgp_mon=ixia_interface_mimic_bgp_mon,
        ibgp_v6_peer_group=PEERGROUP_IBGP_V6,
        ebgp_v6_peer_group=PEERGROUP_EBGP_V6,
        ibgp_v4_peer_group=PEERGROUP_IBGP_V4,
        bgp_mon_peer_group=PEERGROUP_BGP_MON,
    )
    return build_bag_conveyor_test_config(
        testbed,
        name="BAG013_ASH6_BGP_UG_INITIAL_DUMP_IDENTICAL_ROUTES_TEST",
        playbooks=[playbook],
        profile=BgpPlusPlusProfile.BGP_PLUS_PLUS_WITHOUT_OPEN_R,
        enable_update_group=True,
    )


def create_bgp_ug_distribution_correctness_test_config(
    testbed: Testbed,
    profile: BgpPlusPlusProfile = DEFAULT_PROFILE,
) -> taac_types.TestConfig:
    """BGP++ Update Group qualification 2.1.1 (Distribution Correctness /
    Initial Dump -- Identical Routes) TestConfig, dispatched on ``testbed``.

    Wave 6 merges the previous eb03 lab-box factory
    (``create_bgp_ug_eb03_initial_dump_identical_routes_test_config``) and
    the bag013 conveyor factory (``create_bgp_ug_initial_dump_identical_routes_test_config``)
    into one spec-anchored factory. Internal dispatch on ``testbed.device_name``
    because the two topologies diverge structurally (eb03 is a lab box with
    admin/password auth + mock device info; bag013 is a production EBB with
    OpenR route injection + Port-Channel).

    Golden regen for the bag013 catalog constant is EXPECTED: pre-Wave-6
    the bag013 constant returned an empty-playbook TestConfig; Wave 6
    wires the 2.1.1 playbook so the catalog name matches the actual
    behavior. eb03 golden hash is byte-wise identical.
    """
    if testbed.device_name == "eb03.lab.ash6":
        return _create_eb03_distribution_correctness_test_config(testbed, profile)
    if testbed.device_name == "bag013.ash6":
        return _create_bag013_distribution_correctness_test_config(testbed, profile)
    raise NotImplementedError(
        f"create_bgp_ug_distribution_correctness_test_config does not yet "
        f"handle testbed.device_name={testbed.device_name!r}; add a branch "
        f"or generalize the topology builder."
    )
