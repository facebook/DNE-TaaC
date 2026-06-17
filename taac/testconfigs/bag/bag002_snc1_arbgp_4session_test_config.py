# pyre-unsafe
# Copyright (c) Meta Platforms, Inc. and affiliates.

"""TAAC test config for ``bag002.snc1``: 4 eBGP sessions over ar-bgp.

This module builds the ``BAG002_SNC1_ARBGP_4SESSION`` ``TestConfig``,
which qualifies the EOS-native BGP stack (a.k.a. ``ar-bgp``, **not**
BGP++) on ``bag002.snc1``. Each of the 4 IXIA-connected ports gets one
device group with a /127 IPv6 point-to-point link and a single eBGP
session toward the BAG device, with 1k IPv6 prefixes per session
advertised with a Link Bandwidth extended community.

Setup is intentionally split into two ``run_commands_on_shell`` phases
so that interfaces can be brought up before IXIA does its own port
discovery, then IPv6 addresses + BGP neighbors are pushed once IXIA has
attached:

  * Phase 1 (``ixia_needed=False``): no-shutdown + no-switchport +
    ipv6-enable on all 4 ports.
  * Phase 2 (``ixia_needed=True``): per-port IPv6 addressing + BGP
    neighbor activation.

Teardown removes the BGP neighbors and interface IPs (never the whole
``router bgp`` section). Only consumer is
``testconfigs/bag/__init__.py``, which re-exports
``BAG002_SNC1_ARBGP_4SESSION_TEST_CONFIG`` into
``testconfigs/internal/all.py``.
"""

from ixia.ixia import types as ixia_types
from taac.playbooks.playbook_definitions import (
    create_arbgp_4session_longevity_playbook,
)
from taac.task_definitions import (
    create_run_commands_on_shell_task,
)
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import (
    BasicPortConfig,
    BgpConfig,
    DeviceGroupConfig,
    Endpoint,
    IpAddressesConfig,
    RouteScale,
    RouteScaleSpec,
    TestConfig,
)


# =============================================================================
# DEVICE LOOKUP RESULTS (from device_info_cli)
# DO NOT EDIT — these values come from CLI lookups
# =============================================================================

# Device OS — EOS ar-bgp (native BGP, NOT BGP++)
# ar-bgp → use run_commands_on_shell with EOS CLI
# NEVER use create_coop_*, create_interface_ip_configuration_task, or BGP++ tasks
DEVICE_OS = "EOS"

DEVICE_NAME = "bag002.snc1"
DEVICE_ASN = 65060
IXIA_EBGP_AS = 1

# 4 IXIA-connected ports (from sh lldp neighbors / ixia_port_cli)
IXIA_PORTS = [
    "Ethernet3/25/1",
    "Ethernet3/26/1",
    "Ethernet3/27/1",
    "Ethernet4/25/1",
]

# Route scale per session
V6_PREFIX_COUNT = 1000

# Extended BGP community — Link Bandwidth for ECMP (1Gbps = 125,000,000 bytes/sec)
# Use IXIA_EBGP_AS (not DEVICE_ASN) for community AS — global_as_number is i16 (max 32767)
EXTENDED_BGP_COMMUNITIES = [f"link_bw:4:{IXIA_EBGP_AS}:125000000"]


# =============================================================================
# Per-port IPv6 addressing (/127 point-to-point)
#   BAG side = gateway (::1), IXIA side = starting_ip (::0)
# =============================================================================

PORT_PARAMS = [
    {
        "port": "Ethernet3/25/1",
        "bag_ip": "5000::1/127",
        "ixia_ip": "5000::0",
        "gateway_ip": "5000::1",
        "peer_name": "BGP_PEER_V6_EBGP_PORT1",
        "device_group_name": "IXIA_EBGP_PORT1",
        "prefix_name": "EBGP_PORT1_V6",
        "starting_prefix": "5000:1::",
    },
    {
        "port": "Ethernet3/26/1",
        "bag_ip": "6000::1/127",
        "ixia_ip": "6000::0",
        "gateway_ip": "6000::1",
        "peer_name": "BGP_PEER_V6_EBGP_PORT2",
        "device_group_name": "IXIA_EBGP_PORT2",
        "prefix_name": "EBGP_PORT2_V6",
        "starting_prefix": "5000:1::",
    },
    {
        "port": "Ethernet3/27/1",
        "bag_ip": "7000::1/127",
        "ixia_ip": "7000::0",
        "gateway_ip": "7000::1",
        "peer_name": "BGP_PEER_V6_EBGP_PORT3",
        "device_group_name": "IXIA_EBGP_PORT3",
        "prefix_name": "EBGP_PORT3_V6",
        "starting_prefix": "5000:1::",
    },
    {
        "port": "Ethernet4/25/1",
        "bag_ip": "8000::1/127",
        "ixia_ip": "8000::0",
        "gateway_ip": "8000::1",
        "peer_name": "BGP_PEER_V6_EBGP_PORT4",
        "device_group_name": "IXIA_EBGP_PORT4",
        "prefix_name": "EBGP_PORT4_V6",
        "starting_prefix": "5000:1::",
    },
]


# =============================================================================
# EOS CLI command generators (ar-bgp setup/teardown)
# =============================================================================


def _generate_no_shutdown_commands() -> str:
    """Pre-IXIA: bring up all 4 interfaces (no shut + no switchport + ipv6 enable)."""
    lines = ["configure"]
    for p in PORT_PARAMS:
        lines.append(f"interface {p['port']}")
        lines.append(f"description IXIA_EBGP_{p['port'].replace('/', '_')}")
        lines.append("no shutdown")
        lines.append("no switchport")
        lines.append("ipv6 enable")
        lines.append("!")
    lines.append("end")
    return "\n".join(lines)


def _generate_ip_and_bgp_commands() -> str:
    """Post-IXIA: configure IPv6 addresses + BGP neighbors on BAG side."""
    lines = ["configure"]

    # Interface IPv6 addresses
    for p in PORT_PARAMS:
        lines.append(f"interface {p['port']}")
        lines.append(f"ipv6 address {p['bag_ip']}")
        lines.append("!")

    # BGP neighbor config
    lines.append(f"router bgp {DEVICE_ASN}")
    for p in PORT_PARAMS:
        peer_ip = p["ixia_ip"]
        lines.append(f"neighbor {peer_ip} remote-as {IXIA_EBGP_AS}")
        lines.append(f"neighbor {peer_ip} description IXIA_{p['port']}")
        lines.append("address-family ipv6")
        lines.append(f"neighbor {peer_ip} activate")
        lines.append("!")

    lines.append("end")
    return "\n".join(lines)


def _generate_teardown_commands() -> str:
    """Teardown: remove BGP neighbors and interface IPs.

    CRITICAL: Never use 'no router bgp' — that destroys the entire BGP config.
    """
    lines = ["configure"]

    # Remove BGP neighbors first
    lines.append(f"router bgp {DEVICE_ASN}")
    for p in PORT_PARAMS:
        lines.append(f"no neighbor {p['ixia_ip']}")
    lines.append("!")

    # Remove interface IPs
    for p in PORT_PARAMS:
        lines.append(f"interface {p['port']}")
        lines.append(f"no ipv6 address {p['bag_ip']}")
        lines.append("!")

    lines.append("end")
    return "\n".join(lines)


# =============================================================================
# IXIA port config builder
# =============================================================================


def _build_ebgp_port_config(params: dict) -> BasicPortConfig:
    """Build a single ``BasicPortConfig`` with one IXIA-side eBGP peer.

    Wraps the per-port entry in ``PORT_PARAMS`` into a fully populated
    IXIA device group: /127 IPv6 addressing, 4-byte local AS
    ``IXIA_EBGP_AS``, IPv6-unicast capability, graceful restart enabled
    (120s timer, EoR), 30s hold / 10s keepalive, and one route range of
    ``V6_PREFIX_COUNT`` /48 prefixes tagged with the Link Bandwidth
    extended community.

    Args:
        params: One dict from :data:`PORT_PARAMS`. Must contain
            ``port``, ``ixia_ip``, ``gateway_ip``, ``device_group_name``,
            ``peer_name``, ``prefix_name``, and ``starting_prefix``.

    Returns:
        ``BasicPortConfig`` whose ``endpoint`` is
        ``"{DEVICE_NAME}:{params['port']}"``.
    """
    return BasicPortConfig(
        endpoint=f"{DEVICE_NAME}:{params['port']}",
        device_group_configs=[
            DeviceGroupConfig(
                device_group_index=0,
                multiplier=1,
                enable=True,
                device_group_name=params["device_group_name"],
                v6_addresses_config=IpAddressesConfig(
                    starting_ip=params["ixia_ip"],
                    gateway_starting_ip=params["gateway_ip"],
                    mask=127,
                ),
                v6_bgp_config=BgpConfig(
                    bgp_peer_name=params["peer_name"],
                    local_as_4_bytes=IXIA_EBGP_AS,
                    enable_4_byte_local_as=True,
                    bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                    bgp_capabilities=[
                        ixia_types.BgpCapability.IpV6Unicast,
                    ],
                    enable_graceful_restart=True,
                    graceful_restart_timer=120,
                    advertise_end_of_rib=True,
                    hold_timer=30,
                    keepalive_timer=10,
                    route_scales=[
                        RouteScaleSpec(
                            network_group_index=0,
                            multiplier=1,
                            v6_route_scale=RouteScale(
                                prefix_name=params["prefix_name"],
                                starting_prefixes=params["starting_prefix"],
                                prefix_length=48,
                                prefix_count=V6_PREFIX_COUNT,
                                ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                extended_bgp_communities=EXTENDED_BGP_COMMUNITIES,
                            ),
                        ),
                    ],
                ),
            ),
        ],
    )


# =============================================================================
# Config builder
# =============================================================================


def get_test_config(
    device_name: str = DEVICE_NAME,
) -> TestConfig:
    """Generate the ``BAG002_SNC1_ARBGP_4SESSION`` ``TestConfig``.

    Composes IXIA port configs (one per :data:`PORT_PARAMS` entry), the
    ``ARBGP_4SESSION`` longevity playbook, and the two-phase shell-based
    setup + teardown described in the module docstring. Uses
    ``DeviceOsType.ARISTA_OS`` and skips IXIA protocol verification
    because ar-bgp does not require COOP-side handshakes.

    Args:
        device_name: BAG hostname to drive. Defaults to
            :data:`DEVICE_NAME` (``bag002.snc1``); kept parametric so
            the same config can be repointed at another bag002-class
            device.

    Returns:
        A ``TestConfig`` named ``BAG002_SNC1_ARBGP_4SESSION`` ready to
        register in ``testconfigs/internal/all.py``.
    """

    # IXIA port configs — 1 device group (1 eBGP peer) per port
    basic_port_configs = [_build_ebgp_port_config(p) for p in PORT_PARAMS]

    # Longevity playbook — verify all 4 eBGP sessions stay up
    longevity_playbook = create_arbgp_4session_longevity_playbook(duration=180)

    # ── Setup tasks (ar-bgp pattern: run_commands_on_shell) ──

    # Phase 1 — Pre-IXIA: no shutdown + no switchport + ipv6 enable
    pre_ixia_setup = create_run_commands_on_shell_task(
        hostname=device_name,
        cmds=[_generate_no_shutdown_commands()],
        set_outer_hostname=True,
        ixia_needed=False,
    )

    # Phase 2 — Post-IXIA: IPv6 addresses + BGP neighbors
    post_ixia_setup = create_run_commands_on_shell_task(
        hostname=device_name,
        cmds=[_generate_ip_and_bgp_commands()],
        set_outer_hostname=True,
        ixia_needed=True,
    )

    # # Wait for BGP sessions to come up (must be post-IXIA)
    # bgp_convergence = Task(
    #     task_name="wait_for_bgp_convergence",
    #     hostname=device_name,
    #     ixia_needed=True,
    #     params=Params(
    #         json_params=json.dumps(
    #             {
    #                 "hostnames": [device_name],
    #                 "num_tries": 120,
    #                 "sleep": 10,
    #             }
    #         )
    #     ),
    # )

    # ── Teardown tasks ──

    teardown = create_run_commands_on_shell_task(
        hostname=device_name,
        cmds=[_generate_teardown_commands()],
        set_outer_hostname=True,
        ixia_needed=True,
    )

    return TestConfig(
        name="BAG002_SNC1_ARBGP_4SESSION",
        basset_pool="dne.test",
        basset_reservation_time_hr=4,
        host_os_type_map={
            device_name: taac_types.DeviceOsType.ARISTA_OS,
        },
        endpoints=[
            Endpoint(
                name=device_name,
                dut=True,
                ixia_ports=IXIA_PORTS,
            ),
        ],
        skip_ixia_protocol_verification=True,
        basic_port_configs=basic_port_configs,
        basic_traffic_item_configs=[],
        playbooks=[longevity_playbook],
        setup_tasks=[
            pre_ixia_setup,
            post_ixia_setup,
            # bgp_convergence,
        ],
        teardown_tasks=[teardown],
    )


BAG002_SNC1_ARBGP_4SESSION_TEST_CONFIG = get_test_config()
