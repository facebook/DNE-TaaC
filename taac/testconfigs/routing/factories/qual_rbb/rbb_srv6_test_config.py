# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""RBB SRv6 qualification — TestConfig factories.

Assembles the two-node (R1 head/mid ↔ R2 tail) FBOSS TestConfig for the RBB
SRv6 qualification. Structure mirrors the shipped
``openr_portchannel_subif_test_config.py`` (explicit endpoints + os map +
setup/teardown tasks + factory-built playbooks) rather than the heavyweight
topology-compiler path, keeping the OSS slice self-contained.

Physical wiring (DUT hostnames, core port-channels, IXIA edges/ports) is derived
from the run's ``circuit_info.csv`` via ``bgp_rbb_topology.load_rbb_topology``
(generic documentation-range fallback when no CSV is supplied), so a user
cloning the repo reuses the slice by declaring their own topology as INPUT.

Control-plane + data-plane bring-up (core underlay, SRv6 program, IXIA edge)
and verification run as registered tasks (§5.4); the IXIA generator side is
provisioned by the lab's IXIA session and asserted via the shipped
``IXIA_PACKET_LOSS_CHECK`` on the ``RBB_*_SRV6`` traffic items.
"""

import os
import typing as t

from ixia.ixia import types as ixia_types
from taac.abstractions.physical_inventory.physical_inventory import (
    PhysicalInventory,
)
from taac.playbooks.routing.factories.qual_rbb.rbb_srv6_playbook import (
    create_rbb_srv6_3_usids_playbook,
    create_rbb_srv6_te_baseline_playbook,
)
from taac.task_definitions import create_run_task
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import (
    BasicPortConfig,
    BasicTrafficItemConfig,
    BgpConfig,
    DeviceGroupConfig,
    Endpoint,
    IpAddressesConfig,
    RouteScale,
    RouteScaleSpec,
    TestConfig,
    TrafficEndpoint,
)
from taac.testconfigs.routing.util import bgp_rbb_constants as C
from taac.testconfigs.routing.util.bgp_rbb_lab_wiring import (
    build_rbb_inventories,
    rbb_oss_mock_device_data,
)
from taac.testconfigs.routing.util.bgp_rbb_scenario_profiles import (
    core_interface_cmds,
    Srv6Profile,
    SRV6_3_USIDS_PROFILE,
    SRV6_TE_BASELINE_PROFILE,
)
from taac.testconfigs.routing.util.bgp_rbb_topology import (
    load_rbb_topology,
    RbbTopology,
)


def _include_traffic() -> bool:
    """Whether to attach the IXIA generator config (mirrors the playbook flag)."""
    return os.environ.get("TAAC_RBB_INCLUDE_TRAFFIC", "1").lower() not in (
        "0",
        "false",
        "no",
    )


def _provision_setup_tasks(
    r1: PhysicalInventory, r2: PhysicalInventory
) -> t.List[taac_types.Task]:
    """OPT-IN from-scratch provisioning (only when ``TAAC_RBB_PROVISION=1``).

    Prepends, per DUT in order agent → openr → bgpd, the tasks that GENERATE and
    PUSH ``/etc/coop/agent.conf`` (ports/RIFs/PC/SRv6), ``/opt/openr/openr.conf``
    (loopback reachability) and ``/opt/bgpd/bgp.json`` (iBGP over loopbacks) to a
    freshly imaged MORGAN800CC DUT. DISRUPTIVE: each restarts a daemon. Default
    off — the suite otherwise assumes a pre-provisioned underlay.
    """
    if not C.PROVISION_ENABLED:
        return []
    tasks: t.List[taac_types.Task] = []
    for inv, role in ((r1, "r1"), (r2, "r2")):
        for task_name in (
            "provision_fboss_agent_config",
            "provision_fboss_openr_config",
            "provision_fboss_bgp_config",
        ):
            tasks.append(
                create_run_task(
                    task_name=task_name,
                    params_dict={"hostname": inv.device_name, "role": role},
                )
            )
    return tasks


def _edge_bgp_config(
    local_as: int,
    pool_name: str,
    starting_prefix: str,
    prefix_len: int,
    prefix_count: int,
) -> BgpConfig:
    """Emulated eBGP peer on one IXIA edge advertising a v6 prefix pool."""
    return BgpConfig(
        local_as_4_bytes=local_as,
        enable_4_byte_local_as=True,
        bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
        bgp_peer_type=ixia_types.BgpPeerType.EBGP,
        enable_graceful_restart=True,
        graceful_restart_timer=120,
        advertise_end_of_rib=True,
        route_scales=[
            RouteScaleSpec(
                network_group_index=0,
                multiplier=1,
                v6_route_scale=RouteScale(
                    prefix_name=pool_name,
                    starting_prefixes=starting_prefix,
                    prefix_length=prefix_len,
                    multiplier=1,
                    prefix_count=prefix_count,
                    ip_address_family=ixia_types.IpAddressFamily.IPV6,
                ),
            ),
        ],
    )


def _edge_port_config(
    endpoint: str,
    edge_ip: str,
    gw_ip: str,
    mask: int,
    bgp_config: BgpConfig,
) -> BasicPortConfig:
    return BasicPortConfig(
        endpoint=endpoint,
        device_group_configs=[
            DeviceGroupConfig(
                device_group_index=0,
                multiplier=1,
                v6_addresses_config=IpAddressesConfig(
                    starting_ip=edge_ip,
                    gateway_starting_ip=gw_ip,
                    mask=mask,
                ),
                v6_bgp_config=bgp_config,
            ),
        ],
    )


def _ixia_port_configs(
    r1: PhysicalInventory, r2: PhysicalInventory, topology: RbbTopology
) -> t.List[BasicPortConfig]:
    """eBGP-emulation port configs for both IXIA edges (S12-S15).

    R1 (head) edge = IXIA port 3, advertising the head/return pool. R2 (tail)
    edge = IXIA port 10, advertising the REMOTE pool that the port-3 traffic
    targets (the routable inner destination R2 decaps + forwards to port 10).
    """
    r1_iface = topology.r1.primary_ixia_interface
    r2_iface = topology.r2.primary_ixia_interface
    configs: t.List[BasicPortConfig] = []
    if r1_iface:
        configs.append(
            _edge_port_config(
                endpoint=f"{r1.device_name}:{r1_iface}",
                edge_ip=C.IXIA_R1_EDGE_V6,
                gw_ip=C.IXIA_R1_EDGE_GW_V6,
                mask=C.IXIA_EDGE_PREFIX_MASK,
                bgp_config=_edge_bgp_config(
                    local_as=C.IXIA_R1_EDGE_AS,
                    pool_name=C.IXIA_HEAD_PREFIX_POOL_NAME,
                    starting_prefix=C.IXIA_HEAD_ADVERTISED_PREFIX,
                    prefix_len=C.IXIA_HEAD_ADVERTISED_PREFIX_LEN,
                    prefix_count=C.IXIA_HEAD_ADVERTISED_PREFIX_COUNT,
                ),
            )
        )
    if r2_iface:
        configs.append(
            _edge_port_config(
                endpoint=f"{r2.device_name}:{r2_iface}",
                edge_ip=C.IXIA_R2_EDGE_V6,
                gw_ip=C.IXIA_R2_EDGE_GW_V6,
                mask=C.IXIA_EDGE_PREFIX_MASK,
                bgp_config=_edge_bgp_config(
                    local_as=C.IXIA_R2_EDGE_AS,
                    pool_name=C.IXIA_TAIL_PREFIX_POOL_NAME,
                    starting_prefix=C.IXIA_TAIL_ADVERTISED_PREFIX,
                    prefix_len=C.IXIA_TAIL_ADVERTISED_PREFIX_LEN,
                    prefix_count=C.IXIA_TAIL_ADVERTISED_PREFIX_COUNT,
                ),
            )
        )
    return configs


def _ixia_traffic_items(
    r1: PhysicalInventory, r2: PhysicalInventory, topology: RbbTopology
) -> t.List[BasicTrafficItemConfig]:
    """The proposal's real data path: port 3 → R1 SRv6 encap → core → R2 decap
    → port 10 (dest = the tail-advertised REMOTE pool), plus the return item."""
    r1_iface = topology.r1.primary_ixia_interface
    r2_iface = topology.r2.primary_ixia_interface
    if not (r1_iface and r2_iface):
        return []
    frame = ixia_types.FrameSize(
        type=ixia_types.FrameSizeType.FIXED, fixed_size=C.TRAFFIC_FRAME_SIZE
    )
    items = [
        BasicTrafficItemConfig(
            name=C.TRAFFIC_ITEM_R1_TO_R2,
            src_endpoints=[
                TrafficEndpoint(
                    name=f"{r1.device_name}:{r1_iface}", device_group_index=0
                )
            ],
            dest_endpoints=[
                TrafficEndpoint(
                    name=f"{r2.device_name}:{r2_iface}",
                    device_group_index=0,
                    network_group_index=0,
                )
            ],
            traffic_type=ixia_types.TrafficType.IPV6,
            line_rate=C.TRAFFIC_LINE_RATE_PCT,
            line_rate_type=ixia_types.RateType.PERCENT_LINE_RATE,
            frame_size_settings=frame,
            bidirectional=False,
            merge_destinations=True,
            src_dest_mesh=ixia_types.SrcDestMeshType.MANY_TO_MANY,
            tracking_types=[ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM],
        ),
        BasicTrafficItemConfig(
            name=C.TRAFFIC_ITEM_R2_TO_R1,
            src_endpoints=[
                TrafficEndpoint(
                    name=f"{r2.device_name}:{r2_iface}", device_group_index=0
                )
            ],
            dest_endpoints=[
                TrafficEndpoint(
                    name=f"{r1.device_name}:{r1_iface}",
                    device_group_index=0,
                    network_group_index=0,
                )
            ],
            traffic_type=ixia_types.TrafficType.IPV6,
            line_rate=C.TRAFFIC_LINE_RATE_PCT,
            line_rate_type=ixia_types.RateType.PERCENT_LINE_RATE,
            frame_size_settings=frame,
            bidirectional=False,
            merge_destinations=True,
            src_dest_mesh=ixia_types.SrcDestMeshType.MANY_TO_MANY,
            tracking_types=[ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM],
        ),
    ]
    return items


def _edge_ebgp_setup_tasks(
    r1: PhysicalInventory, r2: PhysicalInventory, topology: RbbTopology
) -> t.List[taac_types.Task]:
    """OPT-IN DUT-side edge eBGP bring-up toward the IXIA edges (S14).

    The default lab underlay is iBGP-only over loopbacks; establishing a DUT-side
    eBGP peer toward an IXIA edge is a config change, so it is gated behind
    ``TAAC_RBB_EDGE_EBGP=1`` (``C.EDGE_EBGP_ENABLED``) and off by default to keep
    runs non-destructive.

    Uses the OSS ``rbb_edge_ebgp`` task, which edits the box's ``/opt/bgpd/bgp.json``
    in place (the shipped ``configure_ixia_interfaces`` targets bgpcpp/COOP and is
    incompatible here). The head (R1) simply gains an eBGP peer toward IXIA port 3.
    The tail (R2) gains an eBGP peer toward IXIA port 10, has its iBGP v6 AFI
    switched on, and re-advertises the learned pool into iBGP with the tail SRv6
    decap SID as the v6 next-hop — so R1 SRv6-encapsulates toward R2 (real
    head→core→tail-decap→port-10 SRv6 data path). R2 also gets its edge L3 RIF
    added to agent.conf (the port-10 SVI ships with no address). Every edit is
    backed up to ``*.taac-orig`` and reverted by the teardown restore task.
    """
    if not (C.EDGE_EBGP_ENABLED and _include_traffic()):
        return []
    edge_mask = C.IXIA_EDGE_PREFIX_MASK
    return [
        create_run_task(
            task_name="rbb_edge_ebgp",
            params_dict={
                "hostname": r1.device_name,
                "action": "apply",
                "edge_peer_addr": C.IXIA_R1_EDGE_V6,
                "edge_remote_as": C.IXIA_R1_EDGE_AS,
                "edge_local_addr": C.IXIA_R1_EDGE_GW_V6,
                "edge_rif_cidr": f"{C.IXIA_R1_EDGE_GW_V6}/{edge_mask}",
                "edge_intf_id": C.IXIA_EDGE_INTF_ID,
                "edge_port_name": topology.r1.primary_ixia_interface,
            },
        ),
        create_run_task(
            task_name="rbb_edge_ebgp",
            params_dict={
                "hostname": r2.device_name,
                "action": "apply",
                "edge_peer_addr": C.IXIA_R2_EDGE_V6,
                "edge_remote_as": C.IXIA_R2_EDGE_AS,
                "edge_local_addr": C.IXIA_R2_EDGE_GW_V6,
                # Tail: enable the iBGP v6 AFI and steer the re-advertised pool
                # via the SRv6 decap SID so the head SRv6-encapsulates.
                "enable_ipv6_afi": True,
                "ibgp_srv6_nexthop": C.SRV6_DECAP_SID,
                "edge_rif_cidr": f"{C.IXIA_R2_EDGE_GW_V6}/{edge_mask}",
                "edge_intf_id": C.IXIA_EDGE_INTF_ID,
                "edge_port_name": topology.r2.primary_ixia_interface,
            },
        ),
    ]


def _edge_ebgp_teardown_tasks(
    r1: PhysicalInventory, r2: PhysicalInventory
) -> t.List[taac_types.Task]:
    """Revert the DUT-side edge eBGP edits (restore ``*.taac-orig`` originals)."""
    if not (C.EDGE_EBGP_ENABLED and _include_traffic()):
        return []
    return [
        create_run_task(
            task_name="rbb_edge_ebgp",
            params_dict={"hostname": host, "action": "restore"},
        )
        for host in (r1.device_name, r2.device_name)
    ]


def _core_setup_tasks(
    r1: PhysicalInventory, r2: PhysicalInventory
) -> t.List[taac_types.Task]:
    """Core port-channel underlay confirm on both DUTs (setup phase)."""
    return [
        create_run_task(
            task_name="rbb_core_interface_setup",
            params_dict={
                "hostname": r1.device_name,
                "cmds": core_interface_cmds("r1"),
            },
        ),
        create_run_task(
            task_name="rbb_core_interface_setup",
            params_dict={
                "hostname": r2.device_name,
                "cmds": core_interface_cmds("r2"),
            },
        ),
    ]


def _direct_ixia_connections(
    inv: PhysicalInventory,
    node: t.Any,
    chassis: str,
) -> t.List[taac_types.DirectIxiaConnection]:
    """Explicit DUT-iface ↔ IXIA slot/port map (required in OSS mode).

    OSS ``traffic_generator`` does no LLDP/optical discovery, so each endpoint
    must declare its IXIA connections directly. Built from the topology's IXIA
    edges (``dut_interface`` ↔ ``ixia_port`` "slot/port") and the run's chassis,
    all of which come from the uncommitted ``circuit_info.csv`` — nothing here
    is committed lab data.
    """
    return [
        taac_types.DirectIxiaConnection(
            interface=edge.dut_interface,
            ixia_chassis_ip=chassis,
            ixia_port=edge.ixia_port,
        )
        for edge in node.ixia_edges
    ]


def _build_rbb_test_config(
    name: str,
    profile: Srv6Profile,
    playbooks: t.List[taac_types.Playbook],
    r1: PhysicalInventory,
    r2: PhysicalInventory,
    topology: RbbTopology,
) -> TestConfig:
    include_traffic = _include_traffic()
    r1_ixia_ports = [dut_iface for dut_iface, _ in r1.ixia_ports]
    r2_ixia_ports = [dut_iface for dut_iface, _ in r2.ixia_ports]
    chassis = topology.ixia_chassis or C.IXIA_CHASSIS
    r1_direct = _direct_ixia_connections(r1, topology.r1, chassis)
    r2_direct = _direct_ixia_connections(r2, topology.r2, chassis)
    basic_port_configs = (
        _ixia_port_configs(r1, r2, topology) if include_traffic else None
    )
    basic_traffic_item_configs = (
        _ixia_traffic_items(r1, r2, topology) if include_traffic else None
    )
    return TestConfig(
        name=name,
        basset_pool="",
        skip_ixia_protocol_verification=True,
        # This box runs bgpd from /opt/bgpd/bgp.json, not the COOP-owned
        # /etc/coop/bgpcpp.conf the default OSS ``setup_base_configs`` task
        # expects, so opt out of the default soft-drain config-gen stage (the
        # RBB underlay is pre-provisioned and read-only here).
        skip_default_oss_setup_tasks=True,
        endpoints=[
            Endpoint(
                name=r1.device_name,
                dut=True,
                ixia_needed=include_traffic,
                ixia_ports=r1_ixia_ports if include_traffic else None,
                direct_ixia_connections=r1_direct if include_traffic else None,
            ),
            Endpoint(
                name=r2.device_name,
                dut=True,
                ixia_needed=include_traffic,
                ixia_ports=r2_ixia_ports if include_traffic else None,
                direct_ixia_connections=r2_direct if include_traffic else None,
            ),
        ],
        host_os_type_map={
            r1.device_name: taac_types.DeviceOsType.FBOSS,
            r2.device_name: taac_types.DeviceOsType.FBOSS,
        },
        oss_mock_device_data=rbb_oss_mock_device_data((r1, r2)),
        startup_checks=[],
        setup_tasks=(
            _provision_setup_tasks(r1, r2)
            + _core_setup_tasks(r1, r2)
            + _edge_ebgp_setup_tasks(r1, r2, topology)
        ),
        teardown_tasks=_edge_ebgp_teardown_tasks(r1, r2),
        basic_port_configs=basic_port_configs,
        basic_traffic_item_configs=basic_traffic_item_configs,
        playbooks=playbooks,
    )


def create_rbb_srv6_3_usids_test_config(
    topology: t.Optional[RbbTopology] = None,
    name: str = "RBB_SRV6_3_USIDS_TEST",
) -> TestConfig:
    """TC1: full head→mid→tail 3-uSID chain + TE_AGENT direct-route lifecycle."""
    topology = topology if topology is not None else load_rbb_topology()
    r1, r2 = build_rbb_inventories(topology)
    return _build_rbb_test_config(
        name=name,
        profile=SRV6_3_USIDS_PROFILE,
        playbooks=[
            create_rbb_srv6_3_usids_playbook(
                SRV6_3_USIDS_PROFILE,
                r1_hostname=r1.device_name,
                r2_hostname=r2.device_name,
                topology=topology,
            )
        ],
        r1=r1,
        r2=r2,
        topology=topology,
    )


def create_rbb_srv6_te_baseline_test_config(
    topology: t.Optional[RbbTopology] = None,
    name: str = "RBB_SRV6_TE_BASELINE_TEST",
) -> TestConfig:
    """TC2: TE baseline — tail reachable via BGPD throughout (no direct route)."""
    topology = topology if topology is not None else load_rbb_topology()
    r1, r2 = build_rbb_inventories(topology)
    return _build_rbb_test_config(
        name=name,
        profile=SRV6_TE_BASELINE_PROFILE,
        playbooks=[
            create_rbb_srv6_te_baseline_playbook(
                SRV6_TE_BASELINE_PROFILE,
                r1_hostname=r1.device_name,
                r2_hostname=r2.device_name,
                topology=topology,
            )
        ],
        r1=r1,
        r2=r2,
        topology=topology,
    )
