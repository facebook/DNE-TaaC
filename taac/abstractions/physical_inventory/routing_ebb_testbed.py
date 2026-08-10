# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""Physical inventories for routing EBB testbeds.

This module holds the ``PhysicalInventory`` artifacts for the ASH6 BAG
conveyor pair-of-pairs (``bag010 / bag011 / bag012 / bag013``), the
historical SNC1 BAG (``bag002``), the EB0x lab boxes, the per-developer
``bgp.eb.test.ash6`` box, and the SNC1 Arista ``jsw002``.

The topology figures and naming conventions below describe the ASH6-
specific wiring. The general OpenR-standalone mode contract (approach,
component wiring, single-ownership invariant) lives in
``abstractions/README.md §4 OpenR standalone mode`` — see §6.

──────────────────────────────────────────────────────────────────────────
 §1  Purpose
──────────────────────────────────────────────────────────────────────────
Framework-owned ``PhysicalInventory`` instances for the routing EBB
testbeds. New OpenR-standalone BAG onboarding follows the recipe in the
sibling ``README.md`` — do not clone this file's shape ad-hoc.

──────────────────────────────────────────────────────────────────────────
 §2  IXIA chassis inventory
──────────────────────────────────────────────────────────────────────────
    Chassis            Address                            Use
    ─────────────────  ─────────────────────────────────  ─────────────────
    IXIA11_ASH6        2401:db00:2066:303b::3001          Primary chassis
                                                          for ALL ASH6 BAGs
                                                          and EB0x lab boxes
    IXIA03_ASH6        2401:db00:2066:3036::3003          Secondary fallback
                                                          for ALL ASH6 BAGs
    ares1-my24520014   (SNC1 chassis, non-IPv6 handle)    Primary for bag002.snc1

──────────────────────────────────────────────────────────────────────────
 §3  Figure A — full ASH6 physical topology
──────────────────────────────────────────────────────────────────────────
BAG002_SNC1 is not shown; it sits in a different datacenter (SNC1) on a
different IXIA chassis and does not participate in the OpenR-standalone
mesh.

    IXIA11_ASH6 (primary)                  IXIA03_ASH6 (secondary)
    ─────────────────────                  ───────────────────────
    7/{1..4} ── Eth3/36/{1..4} bag010       1/{49..52} ── Eth3/35/{1..4} bag010
    7/{5..8} ── Eth3/36/{1..4} bag011       1/{53..56} ── Eth3/35/{1..4} bag011
    8/{1..4} ── Eth3/36/{1..4} bag012       1/{57..60} ── Eth3/35/{1..4} bag012
    8/{5..8} ── Eth3/36/{1..4} bag013       1/{61..64} ── Eth3/35/{1..4} bag013

            BAG cross-cables
            ────────────────
            ┌─────────────┐  ┌─────────────┐
            │   bag010    │  │   bag011    │
            │ owns        │  │ owns        │
            │ po100310    │  │ po100311    │
            │             │  │             │
            │ Eth3/1/1 ●──┼──┼──● Eth3/1/1 │      po100310 members
            │ Eth3/2/1 ●──┼──┼──● Eth3/2/1 │      po100311 members
            └─────────────┘  └─────────────┘

            ┌─────────────┐  ┌─────────────┐
            │   bag012    │  │   bag013    │
            │ owns        │  │ owns        │
            │ po100312    │  │ po100313    │
            │             │  │             │
            │ Eth3/1/1 ●──┼──┼──● Eth3/1/1 │      po100312 members
            │ Eth3/2/1 ●──┼──┼──● Eth3/2/1 │      po100313 members
            └─────────────┘  └─────────────┘

──────────────────────────────────────────────────────────────────────────
 §4  Figure B — ownership-pair zoom (bag010 ↔ bag011)
──────────────────────────────────────────────────────────────────────────
The bag012 ↔ bag013 pair is isomorphic (member interfaces + PC IDs shift
by 2).

   bag010 (OpenR daemon standalone)          bag011 (OpenR daemon standalone)
   ┌──────────────────────┐                  ┌──────────────────────┐
   │  owner of po100310   │                  │  owner of po100311   │
   │  Eth3/1/1 ●──────────┼── phys cable ────┼──────● Eth3/1/1      │  po100310 members
   │  Eth3/2/1 ●──────────┼── phys cable ────┼──────● Eth3/2/1      │  po100311 members
   │  (Eth3/2/1 is only a │                  │  (Eth3/1/1 is only a │
   │   helper member for  │                  │   helper member for  │
   │   bag011's po100311) │                  │   bag010's po100310) │
   └──────────────────────┘                  └──────────────────────┘
       ▲                                          ▲
       │ fake adj:node.bag010.<plane>.<i>         │ fake adj:node.bag011.<plane>.<i>
       │ KvStore keys next-hop → po100310         │ KvStore keys next-hop → po100311

Each DUT runs a real OpenR daemon with a zero-peer config; adjacencies
are injected via Thrift with ``ttl = int(-(1 << 31))``. See
``abstractions/README.md §4 OpenR standalone mode`` for the full
approach and component call-chain.

──────────────────────────────────────────────────────────────────────────
 §5  Naming convention
──────────────────────────────────────────────────────────────────────────
``port_channel_id = 1003NN  ⇔  owner hostname = bag0NN.ash6``

``NN`` is the two-digit token equal to the last two digits of the owner's
``bag0NN`` hostname:

    po100310 → bag010        po100312 → bag012
    po100311 → bag011        po100313 → bag013

──────────────────────────────────────────────────────────────────────────
 §6  See also
──────────────────────────────────────────────────────────────────────────
- ``abstractions/README.md §4 OpenR standalone mode`` for the framework
  contract (approach, runtime behavior, component wiring, invariants,
  and enforcement).
- Sibling ``README.md`` for the file-shape template and the "New
  OpenR-standalone BAG onboarding" recipe.
- ``abstractions/topology/model.py:OpenRStandaloneLink`` for the class
  definition and ``__post_init__`` invariant enforcement.
"""

from __future__ import annotations

import json
import os
import typing as t

from taac.abstractions.physical_inventory.physical_inventory import (
    PhysicalInventory,
)
from taac.abstractions.routing_semantics import NetworkRole
from taac.abstractions.topology import (
    OpenRStandaloneEndpoint,
    OpenRStandaloneLink,
)
from taac.test_as_a_config.types import MockDeviceInfo


def _ebb_peer_groups() -> dict[str, str]:
    return {
        "ibgp_v6": "EB-EB-V6",
        "ebgp_v6": "EB-FA-V6",
        "ibgp_v4": "EB-EB-V4",
        "ebgp_v4": "EB-FA-V4",
    }


# ─── Shared constants ─────────────────────────────────────────────────────

_EBB_BGPCPP_PATH = "taac/ebb_ci_cd_configs/ebb_full_scale_bgpcpp_config"
IXIA03_ASH6 = "2401:db00:2066:3036::3003"
IXIA11_ASH6 = "2401:db00:2066:303b::3001"


# ─── Lab-wiring helpers (used by the ebXX.lab.ash6 + bgp.eb.test.ash6 boxes) ───
# These produce the ``host_driver_args`` / ``oss_mock_device_data`` payloads that
# the retired ``util/bgp_ebb_lab_wiring._lab_device_wiring`` helper used to
# synthesize at factory-call time. Byte-identical outputs preserved: password
# read via ``os.environ.get(env_var, "dnepit")`` (env-var lookup runs at
# PhysicalInventory construction/module-import time; TAAC test processes do
# not mutate the password env var after import).


def _lab_host_driver_args(
    device_name: str,
    *,
    password_env: str = "TAAC_EBB_LAB_DEVICE_PASSWORD",
    password_default: str = "dnepit",  # pragma: allowlist secret
    extra_kwargs: dict[str, t.Any] | None = None,
) -> dict[str, str]:
    driver_kwargs: dict[str, t.Any] = {
        "username": "admin",
        "password": os.environ.get(password_env, password_default),
    }
    if extra_kwargs:
        driver_kwargs.update(extra_kwargs)
    return {device_name: json.dumps(driver_kwargs)}


def _lab_oss_mock_device_data(
    device_name: str,
    *,
    network_type: str | None = None,
) -> dict[str, MockDeviceInfo]:
    mock_kwargs: dict[str, t.Any] = {
        "name": device_name,
        "hardware": "ARISTA_7516",
        "role": "EB",
        "operating_system": "EOS",
        "dc": "ash6",
        "region": "ash",
        "asset_id": 12345,
        "asic": "JERICHO",
        "routing_protocol": "BGP",
        "dc_type": "ONE",
        "network_area": "BACKBONE",
        "network_area_type": "BACKBONE",
    }
    if network_type is not None:
        mock_kwargs["network_type"] = network_type
    return {device_name: MockDeviceInfo(**mock_kwargs)}


# ─── bag010 ↔ bag011 OpenR-standalone pair (see Figure B in module docstring) ───

_BAG010_OPENR_LINK = OpenRStandaloneLink(
    port_channel_id=100310,
    owner=OpenRStandaloneEndpoint(
        hostname="bag010.ash6",
        member_interface="Ethernet3/1/1",
        ipv4_cidr="10.217.10.10/31",
        ipv6_cidr="2620:0:1cff:dead:bef1:100:13:3100/127",
        link_local_cidr="fe80::100:310:0/64",
    ),
    helper=OpenRStandaloneEndpoint(
        hostname="bag011.ash6",
        member_interface="Ethernet3/1/1",
        ipv4_cidr="10.217.10.11/31",
        ipv6_cidr="2620:0:1cff:dead:bef1:100:13:3101/127",
        link_local_cidr="fe80::100:310:1/64",
    ),
)

BAG010_ASH6 = PhysicalInventory(
    device_name="bag010.ash6",
    network_role=NetworkRole.EB,
    usage=frozenset({"cicd", "qual"}),
    primary_ixia_chassis_ip=IXIA11_ASH6,
    secondary_ixia_chassis_ip=IXIA03_ASH6,
    ixia_ports=[
        ("Ethernet3/36/1", "7/1"),
        ("Ethernet3/36/2", "7/2"),
        ("Ethernet3/36/3", "7/3"),
        ("Ethernet3/36/4", "7/4"),
    ],
    secondary_ixia_ports=[
        ("Ethernet3/35/1", "1/49"),
        ("Ethernet3/35/2", "1/50"),
        ("Ethernet3/35/3", "1/51"),
        ("Ethernet3/35/4", "1/52"),
    ],
    dut_bgp_as=65010,
    bgpcpp_configerator_path=_EBB_BGPCPP_PATH,
    openr_configerator_path="taac/ebb_ci_cd_configs/bag010_ash6_openr_config",
    openr_standalone_link=_BAG010_OPENR_LINK,
    peer_groups=_ebb_peer_groups(),
)

_BAG011_OPENR_LINK = OpenRStandaloneLink(
    port_channel_id=100311,
    owner=OpenRStandaloneEndpoint(
        hostname="bag011.ash6",
        member_interface="Ethernet3/2/1",
        ipv4_cidr="10.217.11.11/31",
        ipv6_cidr="2620:0:1cff:dead:bef1:100:13:3111/127",
        link_local_cidr="fe80::100:311:1/64",
    ),
    helper=OpenRStandaloneEndpoint(
        hostname="bag010.ash6",
        member_interface="Ethernet3/2/1",
        ipv4_cidr="10.217.11.10/31",
        ipv6_cidr="2620:0:1cff:dead:bef1:100:13:3110/127",
        link_local_cidr="fe80::100:311:0/64",
    ),
)

BAG011_ASH6 = PhysicalInventory(
    device_name="bag011.ash6",
    network_role=NetworkRole.EB,
    usage=frozenset({"cicd", "qual"}),
    primary_ixia_chassis_ip=IXIA11_ASH6,
    secondary_ixia_chassis_ip=IXIA03_ASH6,
    ixia_ports=[
        ("Ethernet3/36/1", "7/5"),
        ("Ethernet3/36/2", "7/6"),
        ("Ethernet3/36/3", "7/7"),
        ("Ethernet3/36/4", "7/8"),
    ],
    secondary_ixia_ports=[
        ("Ethernet3/35/1", "1/53"),
        ("Ethernet3/35/2", "1/54"),
        ("Ethernet3/35/3", "1/55"),
        ("Ethernet3/35/4", "1/56"),
    ],
    # NOTE: preserved verbatim from the legacy bag011_ash6_test_config.py
    # which stored the DUT's local BGP AS in a variable named
    # ``BAG012_EOS_BGP_AS = 65011``. The literal 65011 is bag011's AS; the
    # legacy variable name was a copy-paste artifact.
    dut_bgp_as=65011,
    bgpcpp_configerator_path=_EBB_BGPCPP_PATH,
    openr_configerator_path="taac/ebb_ci_cd_configs/bag011_ash6_openr_config",
    openr_standalone_link=_BAG011_OPENR_LINK,
    peer_groups=_ebb_peer_groups(),
)


# ─── bag012 ↔ bag013 OpenR-standalone pair (isomorphic to Figure B) ───

_BAG012_OPENR_LINK = OpenRStandaloneLink(
    port_channel_id=100312,
    owner=OpenRStandaloneEndpoint(
        hostname="bag012.ash6",
        member_interface="Ethernet3/1/1",
        ipv4_cidr="10.217.12.12/31",
        ipv6_cidr="2620:0:1cff:dead:bef1:100:13:3120/127",
        link_local_cidr="fe80::100:312:0/64",
    ),
    helper=OpenRStandaloneEndpoint(
        hostname="bag013.ash6",
        member_interface="Ethernet3/1/1",
        ipv4_cidr="10.217.12.13/31",
        ipv6_cidr="2620:0:1cff:dead:bef1:100:13:3121/127",
        link_local_cidr="fe80::100:312:1/64",
    ),
)

BAG012_ASH6 = PhysicalInventory(
    device_name="bag012.ash6",
    network_role=NetworkRole.EB,
    usage=frozenset({"cicd", "qual"}),
    primary_ixia_chassis_ip=IXIA11_ASH6,
    secondary_ixia_chassis_ip=IXIA03_ASH6,
    ixia_ports=[
        ("Ethernet3/36/1", "8/1"),
        ("Ethernet3/36/2", "8/2"),
        ("Ethernet3/36/3", "8/3"),
        ("Ethernet3/36/4", "8/4"),
    ],
    secondary_ixia_ports=[
        ("Ethernet3/35/1", "1/57"),
        ("Ethernet3/35/2", "1/58"),
        ("Ethernet3/35/3", "1/59"),
        ("Ethernet3/35/4", "1/60"),
    ],
    dut_bgp_as=65012,
    # bag012 is the only bag physical_inventory that pins ``router_id`` explicitly
    # (bag010/bag011/bag013 all rely on the device-default BGP router-id).
    # Preserved verbatim from the legacy bag012 config for golden-manifest identity.
    router_id="10.163.28.11",
    bgpcpp_configerator_path=_EBB_BGPCPP_PATH,
    openr_configerator_path="taac/ebb_ci_cd_configs/bag012_ash6_openr_config",
    openr_standalone_link=_BAG012_OPENR_LINK,
    peer_groups=_ebb_peer_groups(),
)

_BAG013_OPENR_LINK = OpenRStandaloneLink(
    port_channel_id=100313,
    owner=OpenRStandaloneEndpoint(
        hostname="bag013.ash6",
        member_interface="Ethernet3/2/1",
        ipv4_cidr="10.217.13.13/31",
        ipv6_cidr="2620:0:1cff:dead:bef1:100:13:3131/127",
        link_local_cidr="fe80::100:313:1/64",
    ),
    helper=OpenRStandaloneEndpoint(
        hostname="bag012.ash6",
        member_interface="Ethernet3/2/1",
        ipv4_cidr="10.217.13.12/31",
        ipv6_cidr="2620:0:1cff:dead:bef1:100:13:3130/127",
        link_local_cidr="fe80::100:313:0/64",
    ),
)

BAG013_ASH6 = PhysicalInventory(
    device_name="bag013.ash6",
    network_role=NetworkRole.EB,
    usage=frozenset({"cicd", "qual"}),
    primary_ixia_chassis_ip=IXIA11_ASH6,
    secondary_ixia_chassis_ip=IXIA03_ASH6,
    ixia_ports=[
        ("Ethernet3/36/1", "8/5"),
        ("Ethernet3/36/2", "8/6"),
        ("Ethernet3/36/3", "8/7"),
        ("Ethernet3/36/4", "8/8"),
    ],
    secondary_ixia_ports=[
        ("Ethernet3/35/1", "1/61"),
        ("Ethernet3/35/2", "1/62"),
        ("Ethernet3/35/3", "1/63"),
        ("Ethernet3/35/4", "1/64"),
    ],
    dut_bgp_as=65013,
    # No ``router_id`` — device-default (same as bag010/bag011; see BAG012_ASH6 note).
    bgpcpp_configerator_path=_EBB_BGPCPP_PATH,
    openr_configerator_path="taac/ebb_ci_cd_configs/bag013_ash6_openr_config",
    openr_standalone_link=_BAG013_OPENR_LINK,
    peer_groups=_ebb_peer_groups(),
)


# ─── BAG002_SNC1 — qual-only, no OpenR (openr_standalone_link=None) ───────

BAG002_SNC1 = PhysicalInventory(
    device_name="bag002.snc1",
    network_role=NetworkRole.EB,
    usage=frozenset({"qual"}),
    primary_ixia_chassis_ip="ares1-my24520014",
    ixia_ports=[
        ("Ethernet3/25/1", "1/17"),
        ("Ethernet3/26/1", "1/18"),
        ("Ethernet3/27/1", "1/19"),
    ],
    bgpcpp_configerator_path=_EBB_BGPCPP_PATH,
    peer_groups=_ebb_peer_groups(),
)


# ─── EB0x lab physical inventories (Arista lab boxes in ASH6) ─────────────────────────
# The ebXX.lab.ash6 devices are lab boxes with admin/password auth
# (svc-netcastle_bot is not authorized). ``extras`` carries the shared lab
# credentials plus MockDeviceInfo fields (netwhoami returns ``#INVALID#`` for
# these devices, so ``get_common_setup_tasks`` needs a synthesized record).
EB01_LAB_ASH6 = PhysicalInventory(
    usage=frozenset({"qual"}),
    device_name="eb01.lab.ash6",
    network_role=NetworkRole.EB,
    primary_ixia_chassis_ip=IXIA11_ASH6,
    ixia_ports=[
        ("Ethernet3/1/3", "5/7"),
        ("Ethernet3/1/5", "5/8"),
        ("Ethernet4/36/1", "5/6"),
    ],
    dut_bgp_as=64981,
    bgpcpp_configerator_path=_EBB_BGPCPP_PATH,
    lab_device_password_env_var="TAAC_EBB_LAB_DEVICE_PASSWORD",
    ssh_user="admin",
    host_driver_args=_lab_host_driver_args("eb01.lab.ash6"),
    oss_mock_device_data=_lab_oss_mock_device_data("eb01.lab.ash6", network_type="EBB"),
    peer_groups=_ebb_peer_groups(),
    extras={
        # Retained for ``factories/bgp_update_group.py`` which still reads
        # these keys inline (Wave 2 candidate: fold into the promoted
        # ``host_driver_args`` / ``oss_mock_device_data`` fields).
        "lab_admin_username": "admin",
        "lab_admin_password_default": "dnepit",  # pragma: allowlist secret
        "mock_device_hardware": "ARISTA_7516",
        "mock_device_role": "EB",
        "mock_device_asic": "JERICHO",
        "mock_device_dc": "ash6",
        "mock_device_region": "ash",
        "mock_device_asset_id": 12345,
        "mock_device_network_area": "BACKBONE",
        "mock_device_network_type": "EBB",
    },
)

EB02_LAB_ASH6 = PhysicalInventory(
    usage=frozenset({"qual"}),
    device_name="eb02.lab.ash6",
    network_role=NetworkRole.EB,
    primary_ixia_chassis_ip=IXIA11_ASH6,
    ixia_ports=[
        ("Ethernet3/1/3", "6/2"),
        ("Ethernet3/1/5", "6/3"),
    ],
    dut_bgp_as=64981,
    bgpcpp_configerator_path=_EBB_BGPCPP_PATH,
    lab_device_password_env_var="TAAC_EBB_LAB_DEVICE_PASSWORD",
    ssh_user="admin",
    host_driver_args=_lab_host_driver_args("eb02.lab.ash6"),
    oss_mock_device_data=_lab_oss_mock_device_data("eb02.lab.ash6", network_type="EBB"),
    peer_groups=_ebb_peer_groups(),
    extras={
        # Retained for ``factories/bgp_update_group.py`` which still reads
        # these keys inline (Wave 2 candidate: fold into the promoted
        # ``host_driver_args`` / ``oss_mock_device_data`` fields).
        "lab_admin_username": "admin",
        "lab_admin_password_default": "dnepit",  # pragma: allowlist secret
        "mock_device_hardware": "ARISTA_7516",
        "mock_device_role": "EB",
        "mock_device_asic": "JERICHO",
        "mock_device_dc": "ash6",
        "mock_device_region": "ash",
        "mock_device_asset_id": 12345,
        "mock_device_network_area": "BACKBONE",
        "mock_device_network_type": "EBB",
    },
)

EB03_LAB_ASH6 = PhysicalInventory(
    usage=frozenset({"qual"}),
    device_name="eb03.lab.ash6",
    network_role=NetworkRole.EB,
    primary_ixia_chassis_ip=IXIA11_ASH6,
    ixia_ports=[
        ("Ethernet3/1/3", "6/5"),
        ("Ethernet3/1/5", "6/6"),
        ("Ethernet3/36/1", "2/8"),
    ],
    dut_bgp_as=64981,
    bgpcpp_configerator_path=_EBB_BGPCPP_PATH,
    lab_device_password_env_var="TAAC_EBB_LAB_DEVICE_PASSWORD",
    ssh_user="admin",
    host_driver_args=_lab_host_driver_args("eb03.lab.ash6"),
    oss_mock_device_data=_lab_oss_mock_device_data("eb03.lab.ash6", network_type="EBB"),
    peer_groups=_ebb_peer_groups(),
    extras={
        # Retained for ``factories/bgp_update_group.py`` which still reads
        # these keys inline (Wave 2 candidate: fold into the promoted
        # ``host_driver_args`` / ``oss_mock_device_data`` fields).
        "lab_admin_username": "admin",
        "lab_admin_password_default": "dnepit",  # pragma: allowlist secret
        "mock_device_hardware": "ARISTA_7516",
        "mock_device_role": "EB",
        "mock_device_asic": "JERICHO",
        "mock_device_dc": "ash6",
        "mock_device_region": "ash",
        "mock_device_asset_id": 12345,
        "mock_device_network_area": "BACKBONE",
        "mock_device_network_type": "EBB",
    },
)

EB04_LAB_ASH6 = PhysicalInventory(
    usage=frozenset({"qual"}),
    device_name="eb04.lab.ash6",
    network_role=NetworkRole.EB,
    primary_ixia_chassis_ip=IXIA11_ASH6,
    ixia_ports=[
        ("Ethernet3/1/1", "6/7"),
        ("Ethernet3/1/3", "6/8"),
    ],
    dut_bgp_as=64981,
    bgpcpp_configerator_path=_EBB_BGPCPP_PATH,
    lab_device_password_env_var="TAAC_EBB_LAB_DEVICE_PASSWORD",
    ssh_user="admin",
    host_driver_args=_lab_host_driver_args("eb04.lab.ash6"),
    # NOTE: legacy eb04 source omits ``network_type`` on MockDeviceInfo,
    # unlike eb01/eb03 which set ``network_type="EBB"``. Preserved verbatim.
    oss_mock_device_data=_lab_oss_mock_device_data("eb04.lab.ash6"),
    peer_groups=_ebb_peer_groups(),
    extras={
        # Retained for ``factories/bgp_update_group.py`` which still reads
        # these keys inline (Wave 2 candidate: fold into the promoted
        # ``host_driver_args`` / ``oss_mock_device_data`` fields).
        "lab_admin_username": "admin",
        "lab_admin_password_default": "dnepit",  # pragma: allowlist secret
        "mock_device_hardware": "ARISTA_7516",
        "mock_device_role": "EB",
        "mock_device_asic": "JERICHO",
        "mock_device_dc": "ash6",
        "mock_device_region": "ash",
        "mock_device_asset_id": 12345,
        "mock_device_network_area": "BACKBONE",
    },
)


# ─── Dev-only EB test device ──────────────────────────────────────────────
# ``bgp.eb.test.ash6`` is a per-developer BGP++ test switch — a lab box like
# the eb0x boxes above, but with an extra ``bgp_ip`` host-driver kwarg
# (thrift-over-IPv6 to a non-loopback address). Only used by the queue-memory
# monitor testconfig.
EB_TEST_DEVICE = PhysicalInventory(
    usage=frozenset({"qual"}),
    device_name="bgp.eb.test.ash6",
    network_role=NetworkRole.EB,
    primary_ixia_chassis_ip=IXIA11_ASH6,
    ixia_ports=[
        ("Ethernet3/1/5", "5/3"),
        ("Ethernet3/1/3", "5/2"),
    ],
    dut_bgp_as=64981,
    bgpcpp_configerator_path=_EBB_BGPCPP_PATH,
    lab_device_password_env_var="TAAC_EBB_LAB_DEVICE_PASSWORD",
    ssh_user="admin",
    # Extra host-driver JSON kwarg beyond the standard username/password
    # pair — routes the BGP++ thrift RPC to a specific IPv6 address on
    # the dev physical_inventory (device's regular loopback is not reachable from
    # devservers).
    host_driver_args=_lab_host_driver_args(
        "bgp.eb.test.ash6",
        extra_kwargs={"bgp_ip": "2401:db00:2066:304a::1001"},
    ),
    oss_mock_device_data=_lab_oss_mock_device_data(
        "bgp.eb.test.ash6", network_type="EBB"
    ),
    peer_groups=_ebb_peer_groups(),
    extras={
        # Retained for ``factories/bgp_update_group.py`` which still reads
        # these keys inline (Wave 2 candidate: fold into the promoted
        # ``host_driver_args`` / ``oss_mock_device_data`` fields).
        "lab_admin_username": "admin",
        "lab_admin_password_default": "dnepit",  # pragma: allowlist secret
        "host_driver_extra_kwargs": {
            "bgp_ip": "2401:db00:2066:304a::1001",
        },
        "mock_device_hardware": "ARISTA_7516",
        "mock_device_role": "EB",
        "mock_device_asic": "JERICHO",
        "mock_device_dc": "ash6",
        "mock_device_region": "ash",
        "mock_device_asset_id": 12345,
        "mock_device_network_area": "BACKBONE",
        "mock_device_network_type": "EBB",
    },
)


# ─── Production Arista EB in SNC1 ─────────────────────────────────────────
# ``jsw002.m001.snc1`` is a production EB Arista used by the non-lab
# ARISTA_MIMIC_EBB_TEST_FULL_SCALE testconfig. The legacy source declares no
# ``direct_ixia_connections`` (topology is discovered at runtime), so the
# chassis + port map is intentionally left empty here — Wave 5B will surface
# the discovered ports if/when the factory needs them.
JSW002_M001_SNC1 = PhysicalInventory(
    usage=frozenset({"adhoc"}),
    device_name="jsw002.m001.snc1",
    network_role=NetworkRole.EB,
    primary_ixia_chassis_ip="",
    dut_bgp_as=64981,
    bgpcpp_configerator_path=_EBB_BGPCPP_PATH,
    peer_groups=_ebb_peer_groups(),
    extras={
        # Reference DUT interfaces from the legacy source, kept here so Wave
        # 5B factories can wire up ixia setup without re-parsing the legacy
        # testconfig files.
        "dut_iface_ebgp": "Ethernet3/8/1",
        "dut_iface_ibgp": "Ethernet3/8/5",
        "dut_iface_bgp_mon": "Ethernet3/9/1",
    },
)
