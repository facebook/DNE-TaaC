# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""RBB SRv6 qualification — TestConfig factories.

Assembles the two-node FBOSS TestConfig for the RBB SRv6 qualification. R1 is
the ingress/head and later transit hop; R2 hosts the midpoint adjacency and
tail decapsulation behaviors. Structure mirrors the shipped
``openr_portchannel_subif_test_config.py`` (explicit endpoints + os map +
setup/teardown tasks + factory-built playbooks) rather than the heavyweight
topology-compiler path, keeping the OSS slice self-contained.

Physical wiring (DUT hostnames, core port-channels, IXIA edges/ports) is derived
from the run's ``circuit_info.csv`` via ``bgp_rbb_topology.load_rbb_topology``.
Read-only factory inspection has a documentation-only fallback; live traffic
requires explicit wiring so a user can safely declare any valid port layout.

Control-plane/data-plane confirmation runs as registered tasks (§5.4). The IXIA
generator side is provisioned by the lab's IXIA session and asserted via the
shipped ``IXIA_PACKET_LOSS_CHECK`` on the ``RBB_*_SRV6`` traffic item.
"""

import ipaddress
import typing as t

from ixia.ixia import types as ixia_types
from taac.abstractions.physical_inventory.physical_inventory import (
    PhysicalInventory,
)
from taac.playbooks.routing.factories.qual_rbb.rbb_srv6_playbook import (
    create_rbb_srv6_3_usids_playbook,
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
from taac.testconfigs.routing.util.bgp_rbb_bootstrap_config import (
    validate_bootstrap_topology,
)
from taac.testconfigs.routing.util.bgp_rbb_lab_wiring import (
    build_rbb_inventories,
    rbb_oss_mock_device_data,
)
from taac.testconfigs.routing.util.bgp_rbb_scenario_profiles import (
    Srv6Profile,
    SRV6_3_USIDS_PROFILE,
)
from taac.testconfigs.routing.util.bgp_rbb_topology import (
    load_rbb_topology,
    RbbTopology,
    validate_rbb_topology,
)


def _include_traffic(override: t.Optional[bool] = None) -> bool:
    """Whether to attach the IXIA generator config (mirrors the playbook flag)."""
    return C.INCLUDE_TRAFFIC if override is None else override


def _resolve_topology(
    topology: t.Optional[RbbTopology], include_traffic: bool
) -> RbbTopology:
    """Resolve and validate wiring before building any side-effecting task."""
    if C.SETUP_DUTS_ENABLED and include_traffic and not C.EDGE_EBGP_ENABLED:
        raise ValueError(
            "fresh-image traffic requires TAAC_RBB_EDGE_EBGP=1 "
            "(--setup-dut-edges)"
        )
    if topology is None:
        topology = load_rbb_topology(
            allow_placeholder=not include_traffic,
            require_ixia=include_traffic,
        )
    else:
        validate_rbb_topology(
            topology,
            require_ixia=include_traffic,
        )
    if C.SETUP_DUTS_ENABLED:
        validate_bootstrap_topology(topology)
    return topology


def _validate_traffic_route_contract(
    profile: Srv6Profile, include_traffic: bool
) -> None:
    """Validate IXIA addressing and TC1's exact steered-route contract."""
    if not include_traffic:
        return
    edge_pairs = (
        ("R1", C.IXIA_R1_EDGE_V6, C.IXIA_R1_EDGE_GW_V6),
        ("R2", C.IXIA_R2_EDGE_V6, C.IXIA_R2_EDGE_GW_V6),
    )
    for role, peer, gateway in edge_pairs:
        peer_interface = ipaddress.ip_interface(
            f"{peer}/{C.IXIA_EDGE_PREFIX_MASK}"
        )
        gateway_interface = ipaddress.ip_interface(
            f"{gateway}/{C.IXIA_EDGE_PREFIX_MASK}"
        )
        if peer_interface.version != 6 or gateway_interface.version != 6:
            raise ValueError(f"{role} IXIA edge addresses must be IPv6")
        if peer_interface.network != gateway_interface.network:
            raise ValueError(
                f"{role} IXIA peer {peer} and DUT gateway {gateway} are not in "
                "the same edge subnet"
            )
        if peer_interface.ip == gateway_interface.ip:
            raise ValueError(f"{role} IXIA peer and DUT gateway must differ")
    if not (
        1 <= C.IXIA_R1_EDGE_AS <= 0xFFFFFFFF
        and 1 <= C.IXIA_R2_EDGE_AS <= 0xFFFFFFFF
    ):
        raise ValueError("IXIA edge ASNs must be in 1..4294967295")

    def route_pool(prefix: str, prefix_len: int, label: str) -> ipaddress.IPv6Network:
        network = ipaddress.ip_network(f"{prefix}/{prefix_len}", strict=False)
        if network.version != 6:
            raise ValueError(f"{label} IXIA advertised pool must be IPv6")
        if ipaddress.ip_address(prefix) != network.network_address:
            raise ValueError(
                f"{label} IXIA starting prefix {prefix!r} is not a /{prefix_len} "
                "network address"
            )
        return t.cast(ipaddress.IPv6Network, network)

    advertised = route_pool(
        C.IXIA_TAIL_ADVERTISED_PREFIX,
        C.IXIA_TAIL_ADVERTISED_PREFIX_LEN,
        "R2 tail",
    )
    if C.IXIA_TAIL_ADVERTISED_PREFIX_COUNT < 1:
        raise ValueError("TAAC_RBB_IXIA_TAIL_PREFIX_COUNT must be positive")
    if not 1 <= C.TRAFFIC_LINE_RATE_PCT <= 100:
        raise ValueError("TAAC_RBB_TRAFFIC_LINE_RATE must be in 1..100")
    if C.TRAFFIC_FRAME_SIZE < 64:
        raise ValueError("TAAC_RBB_TRAFFIC_FRAME_SIZE must be at least 64 bytes")
    if C.IXIA_REMOTE_ROUTE_MIN_COUNT < 1:
        raise ValueError("TAAC_RBB_IXIA_REMOTE_ROUTE_MIN must be positive")

    if profile.name != "srv6_3_usids":
        return
    steered = ipaddress.ip_network(profile.tail_prefix, strict=True)
    if steered != advertised:
        raise ValueError(
            "TAAC_RBB_TAIL_PREFIX must equal the first IXIA tail-advertised "
            f"prefix for TC1 traffic: steered={steered}, advertised={advertised}"
        )
    if C.IXIA_TAIL_ADVERTISED_PREFIX_COUNT != 1:
        raise ValueError(
            "TC1 currently steers one direct route, so "
            "TAAC_RBB_IXIA_TAIL_PREFIX_COUNT must be 1"
        )


def _edge_bgp_config(
    local_as: int,
    route_scale: t.Optional[RouteScaleSpec] = None,
) -> BgpConfig:
    """Build an IPv6 eBGP peer, optionally with one advertised route pool."""
    return BgpConfig(
        local_as_4_bytes=local_as,
        enable_4_byte_local_as=True,
        bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
        bgp_peer_type=ixia_types.BgpPeerType.EBGP,
        enable_graceful_restart=True,
        graceful_restart_timer=120,
        advertise_end_of_rib=True,
        route_scales=[route_scale] if route_scale is not None else [],
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

    The selected R1 edge supplies the source interface and eBGP session. The
    selected R2 edge advertises the one remote pool targeted by traffic.
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
                bgp_config=_edge_bgp_config(local_as=C.IXIA_R1_EDGE_AS),
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
                    route_scale=RouteScaleSpec(
                        network_group_index=0,
                        multiplier=1,
                        v6_route_scale=RouteScale(
                            prefix_name=C.IXIA_TAIL_PREFIX_POOL_NAME,
                            starting_prefixes=C.IXIA_TAIL_ADVERTISED_PREFIX,
                            prefix_length=C.IXIA_TAIL_ADVERTISED_PREFIX_LEN,
                            multiplier=1,
                            prefix_count=C.IXIA_TAIL_ADVERTISED_PREFIX_COUNT,
                            ip_address_family=ixia_types.IpAddressFamily.IPV6,
                        ),
                    ),
                ),
            )
        )
    return configs


def _ixia_traffic_items(
    r1: PhysicalInventory, r2: PhysicalInventory, topology: RbbTopology
) -> t.List[BasicTrafficItemConfig]:
    """Selected R1 edge → SRv6 core → selected R2 edge."""
    r1_iface = topology.r1.primary_ixia_interface
    r2_iface = topology.r2.primary_ixia_interface
    if not (r1_iface and r2_iface):
        return []
    frame = ixia_types.FrameSize(
        type=ixia_types.FrameSizeType.FIXED, fixed_size=C.TRAFFIC_FRAME_SIZE
    )
    return [
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
    ]


def _edge_ebgp_setup_tasks(
    r1: PhysicalInventory,
    r2: PhysicalInventory,
    topology: RbbTopology,
    include_traffic: bool,
) -> t.List[taac_types.Task]:
    """OPT-IN DUT-side edge eBGP bring-up toward the IXIA edges (S14).

    The default lab underlay is iBGP-only over loopbacks; establishing a DUT-side
    eBGP peer toward an IXIA edge is a config change, so it is gated behind
    ``TAAC_RBB_EDGE_EBGP=1`` (``C.EDGE_EBGP_ENABLED``) and off by default to keep
    runs non-destructive.

    Uses the OSS ``rbb_edge_ebgp`` task, which edits the box's ``/opt/bgpd/bgp.json``
    in place (the shipped ``configure_ixia_interfaces`` targets bgpcpp/COOP and is
    incompatible here). The head (R1) gains an eBGP peer toward its selected
    IXIA edge. Both DUTs have their core iBGP v6 AFI enabled. R1 preserves its
    usable routed v6 next-hop (or uses the explicit environment override); the
    tail (R2) advertises its learned pool with the decap SID. The latter supplies
    R1's recursive underlay resolution; the S21 TE_AGENT route's explicit
    segment list triggers SRv6 encapsulation. Each DUT also gets its selected
    edge L3 RIF added to agent.conf when necessary. Every edit has an independent
    snapshot and is reverted by teardown.
    """
    if not (C.EDGE_EBGP_ENABLED and include_traffic):
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
                "enable_ipv6_afi": True,
                "ibgp_peer_addr": C.R2_ROUTER_ID,
                **(
                    {"ibgp_srv6_nexthop": C.R1_IBGP_NEXT_HOP_V6}
                    if C.R1_IBGP_NEXT_HOP_V6
                    else {}
                ),
                "edge_rif_cidr": f"{C.IXIA_R1_EDGE_GW_V6}/{edge_mask}",
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
                # Tail: enable the iBGP v6 AFI and advertise the decap SID as
                # the recursive next hop used by the head's TE_AGENT route.
                "enable_ipv6_afi": True,
                "ibgp_peer_addr": C.R1_ROUTER_ID,
                "ibgp_srv6_nexthop": C.SRV6_DECAP_SID,
                "edge_rif_cidr": f"{C.IXIA_R2_EDGE_GW_V6}/{edge_mask}",
                "edge_port_name": topology.r2.primary_ixia_interface,
            },
        ),
    ]


def _edge_ebgp_teardown_tasks(
    r1: PhysicalInventory, r2: PhysicalInventory, include_traffic: bool
) -> t.List[taac_types.Task]:
    """Revert edge eBGP edits and restore ``*.taac-rbb-edge-orig`` files."""
    if not (C.EDGE_EBGP_ENABLED and include_traffic):
        return []
    return [
        create_run_task(
            task_name="rbb_edge_ebgp",
            params_dict={"hostname": host, "action": "restore"},
        )
        for host in (r1.device_name, r2.device_name)
    ]


def _dut_bootstrap_setup_tasks(
    r1: PhysicalInventory,
    r2: PhysicalInventory,
    topology: RbbTopology,
    include_traffic: bool,
) -> t.List[taac_types.Task]:
    """Temporarily bootstrap a fresh image's core/OpenR/iBGP/SRv6 slice."""
    if not C.SETUP_DUTS_ENABLED:
        return []
    return [
        create_run_task(
            task_name="rbb_dut_bootstrap",
            params_dict={
                "hostname": inventory.device_name,
                "action": "apply",
                "role": node.role,
                # Device-only mode gets a minimal R2 BGPD-owned tail route;
                # traffic mode instead adds only the IXIA return-path route.
                "include_traffic": include_traffic,
                "core_port_channels": [
                    {"name": pc.name, "members": list(pc.members)}
                    for pc in node.core_pcs
                ],
            },
        )
        for inventory, node in ((r1, topology.r1), (r2, topology.r2))
    ]


def _dut_bootstrap_teardown_tasks(
    r1: PhysicalInventory, r2: PhysicalInventory
) -> t.List[taac_types.Task]:
    """Restore the exact image-installed configs/service states on both DUTs."""
    if not C.SETUP_DUTS_ENABLED:
        return []
    return [
        create_run_task(
            task_name="rbb_dut_bootstrap",
            params_dict={"hostname": host, "action": "restore"},
        )
        for host in (r1.device_name, r2.device_name)
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
        for edge in ([node.primary_ixia_edge] if node.primary_ixia_edge else [])
    ]


def _build_rbb_test_config(
    name: str,
    profile: Srv6Profile,
    playbooks: t.List[taac_types.Playbook],
    r1: PhysicalInventory,
    r2: PhysicalInventory,
    topology: RbbTopology,
    include_traffic: bool,
) -> TestConfig:
    _validate_traffic_route_contract(profile, include_traffic)
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
        # Traffic mode depends on the IXIA BGP sessions and advertised tail
        # prefix regardless of who provisioned the DUT edge. The edge setup
        # flag controls mutation only; it must never weaken validation.
        skip_ixia_protocol_verification=not include_traffic,
        # Retain TAAC's global IXIA advertisement allowlist unless an adopter
        # explicitly opts out for an isolated lab prefix. The RBB preflight
        # and factory still require one exact IPv6 pool matching the steered
        # route; this flag never broadens the generated traffic config.
        skip_advertised_prefixes_check=C.SKIP_ADVERTISED_PREFIXES_CHECK,
        # This box runs bgpd from /opt/bgpd/bgp.json, not the COOP-owned
        # /etc/coop/bgpcpp.conf the default OSS ``setup_base_configs`` task
        # expects. The optional RBB bootstrap below owns its independent,
        # reversible transaction; otherwise the underlay remains read-only.
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
            _dut_bootstrap_setup_tasks(r1, r2, topology, include_traffic)
            + _edge_ebgp_setup_tasks(r1, r2, topology, include_traffic)
        ),
        # Teardown runs in list order. Remove the edge overlay before restoring
        # the bootstrap's image baseline underneath it.
        teardown_tasks=(
            _edge_ebgp_teardown_tasks(r1, r2, include_traffic)
            + _dut_bootstrap_teardown_tasks(r1, r2)
        ),
        basic_port_configs=basic_port_configs,
        basic_traffic_item_configs=basic_traffic_item_configs,
        playbooks=playbooks,
    )


def create_rbb_srv6_3_usids_test_config(
    topology: t.Optional[RbbTopology] = None,
    name: str = "RBB_SRV6_3_USIDS_TEST",
    include_traffic: t.Optional[bool] = None,
) -> TestConfig:
    """TC1: full head→mid→tail 3-uSID chain + TE_AGENT direct-route lifecycle."""
    resolved_include_traffic = _include_traffic(include_traffic)
    topology = _resolve_topology(topology, resolved_include_traffic)
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
                include_traffic=resolved_include_traffic,
            )
        ],
        r1=r1,
        r2=r2,
        topology=topology,
        include_traffic=resolved_include_traffic,
    )
