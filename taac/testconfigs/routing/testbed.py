# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""Routing test DUT baseline definitions.

Home of the ``Testbed`` dataclass + all Testbed instances used by
routing testconfig factories under ``testconfigs/routing/``. Per-role
config bundles (peer group names, route maps, communities) live in
the sibling ``role_defaults.py``.

See ``README.md`` §2 for the framework rules.
"""

from __future__ import annotations

import json
import os
import typing as t
from dataclasses import dataclass, field, replace

from taac.testconfigs.routing.role_defaults import ebb_peer_groups
from taac.test_as_a_config import types as taac_types


VALID_USAGES: frozenset[str] = frozenset({"cicd", "qual", "adhoc", "retired"})


@dataclass(frozen=True)
class Testbed:
    """DUT baseline for a routing test. Fits all usecases (EBB / DC / FA verify / feature).

    Physical identity fields stay flat; anything varying by testbed-family
    (BGP peer-group names, communities, route maps, etc.) goes into
    role-keyed dicts. Factories look up what they need by role key.
    """

    # ─── Physical identity (always required) ──────────────────────────────
    device_name: str
    primary_ixia_chassis_ip: str
    # ``ixia_ports`` items are ``(dut_iface, chassis_port)`` tuples. The
    # chassis-port string is IXIA's ``"<card>/<port>"`` shorthand (e.g. ``"8/2"``
    # = card 8, port 2 on ``primary_ixia_chassis_ip``). Order is
    # load-bearing for factories that hard-index the list: ``[0]`` = eBGP,
    # ``[1]`` = iBGP, ``[2]`` = BGP-MON (when present).
    ixia_ports: list[tuple[str, str]] = field(default_factory=list)
    secondary_ixia_chassis_ip: str | None = None

    # ─── Which catalog surfaces may bind this testbed ─────────────────────
    # Members of ``VALID_USAGES``. A cicd_*.py catalog file may only bind
    # testbeds whose ``usage`` set includes ``"cicd"``; same for qual_ /
    # adhoc_. ``"retired"`` marks a testbed kept only for historical record.
    # Enforced by tests/test_testbed_usage_matches_catalog.py.
    usage: frozenset[str] = field(default_factory=frozenset)

    # ─── DUT identity properties (optional, flat) ─────────────────────────
    mac_address: str | None = None
    speed: str = "100g-2"
    router_id: str | None = None
    dut_bgp_as: int | None = None  # DUT's own local BGP AS

    # ─── Configerator paths for full-config deployment ────────────────────
    bgpcpp_configerator_path: str | None = None
    openr_configerator_path: str | None = None
    fboss_agent_configerator_path: str | None = None

    # ─── Lab auth ─────────────────────────────────────────────────────────
    lab_device_password_env_var: str | None = None
    # SSH user for lab boxes (``svc-netcastle_bot`` is not authorized on
    # ebXX.lab.ash6 / bgp.eb.test.ash6). None for production / conveyor
    # testbeds, where Netcastle uses its own default SSH identity.
    ssh_user: str | None = None
    # Precomputed ``TestConfig.host_driver_args`` payload for lab boxes.
    # Populated at Testbed construction time from the shared lab-password
    # env var (``TAAC_EBB_LAB_DEVICE_PASSWORD``, falling back to
    # ``"dnepit"``). None for production / conveyor testbeds where
    # ``netwhoami`` returns a valid record.
    host_driver_args: dict[str, str] | None = None
    # Precomputed ``TestConfig.oss_mock_device_data`` payload for lab
    # boxes; ``netwhoami`` returns ``#INVALID#`` for lab devices, so
    # ``get_common_setup_tasks`` needs a synthesized ``MockDeviceInfo``.
    # None for production / conveyor testbeds.
    oss_mock_device_data: dict[str, taac_types.MockDeviceInfo] | None = None

    # ─── Named parameter maps — BGP topology ──────────────────────────────
    peer_groups: dict = field(default_factory=dict)
    as_numbers: dict = field(default_factory=dict)
    route_maps: dict = field(default_factory=dict)
    communities: dict = field(default_factory=dict)
    parent_networks: dict = field(default_factory=dict)

    # ─── FBOSS baseline attributes (patcher-applied at setup) ─────────────
    fboss_attributes: dict = field(default_factory=dict)

    # ─── Escape hatch ─────────────────────────────────────────────────────
    extras: dict = field(default_factory=dict)

    # ─── Optional fallback IXIA inventory ─────────────────────────────────
    # DUT-side pair for ``secondary_ixia_chassis_ip``. Empty = fallback not
    # unlocked (chassis alone is treated as a placeholder).
    secondary_ixia_ports: list[tuple[str, str]] = field(default_factory=list)

    @property
    def ixia_chassis_ip(self) -> str:
        """Compatibility alias for factories that consume the primary chassis."""
        return self.primary_ixia_chassis_ip

    def __post_init__(self) -> None:
        bad = self.usage - VALID_USAGES
        if bad:
            raise ValueError(
                f"Testbed {self.device_name}: usage contains invalid "
                f"values {sorted(bad)!r}; allowed: {sorted(VALID_USAGES)!r}"
            )

        secondary_ports_defined = bool(self.secondary_ixia_ports)
        secondary_chassis_defined = self.secondary_ixia_chassis_ip is not None
        if secondary_ports_defined and not secondary_chassis_defined:
            raise ValueError(
                f"Testbed {self.device_name}: secondary_ixia_ports requires "
                "secondary_ixia_chassis_ip to be set"
            )
        if not secondary_ports_defined:
            return

        if not self.secondary_ixia_chassis_ip:
            raise ValueError(
                f"Testbed {self.device_name}: secondary_ixia_chassis_ip must be nonempty"
            )
        _validate_ixia_port_mapping(self.device_name, "ixia_ports", self.ixia_ports)
        _validate_ixia_port_mapping(
            self.device_name,
            "secondary_ixia_ports",
            self.secondary_ixia_ports,
        )
        if len(self.ixia_ports) != len(self.secondary_ixia_ports):
            raise ValueError(
                f"Testbed {self.device_name}: primary and secondary IXIA port "
                "mappings must have equivalent role indices; "
                f"got {len(self.ixia_ports)} primary and "
                f"{len(self.secondary_ixia_ports)} secondary ports"
            )
        # Primary and secondary may use disjoint DUT interfaces; the runner
        # protects the union at isolation time.

    @property
    def has_secondary_ixia(self) -> bool:
        # Use truthiness (not `is not None`) so this matches the "defined
        # secondary chassis" notion enforced in __post_init__ and stays
        # self-consistent even under a `replace()` that sets an empty string.
        return bool(self.secondary_ixia_chassis_ip) and bool(self.secondary_ixia_ports)

    def for_secondary_ixia(self) -> Testbed:
        if not self.has_secondary_ixia:
            raise ValueError(
                f"Testbed {self.device_name}: no secondary IXIA mapping is defined"
            )
        return replace(
            self,
            primary_ixia_chassis_ip=t.cast(str, self.secondary_ixia_chassis_ip),
            ixia_ports=list(self.secondary_ixia_ports),
            secondary_ixia_chassis_ip=None,
            secondary_ixia_ports=[],
        )


def _validate_ixia_port_mapping(
    device_name: str,
    field_name: str,
    ports: list[tuple[str, str]],
) -> None:
    if not ports:
        raise ValueError(f"Testbed {device_name}: {field_name} must be nonempty")

    dut_interfaces: list[str] = []
    chassis_ports: list[str] = []
    for index, entry in enumerate(ports):
        if not isinstance(entry, tuple) or len(entry) != 2:
            raise ValueError(
                f"Testbed {device_name}: {field_name}[{index}] must be a "
                "(dut_interface, chassis_port) tuple"
            )
        dut_interface, chassis_port = entry
        if (
            not isinstance(dut_interface, str)
            or not dut_interface
            or not isinstance(chassis_port, str)
            or not chassis_port
        ):
            raise ValueError(
                f"Testbed {device_name}: {field_name}[{index}] must contain "
                "nonempty string interface names"
            )
        dut_interfaces.append(dut_interface)
        chassis_ports.append(chassis_port)

    duplicate_dut_interfaces = _duplicates(dut_interfaces)
    duplicate_chassis_ports = _duplicates(chassis_ports)
    if duplicate_dut_interfaces or duplicate_chassis_ports:
        raise ValueError(
            f"Testbed {device_name}: {field_name} contains duplicate mappings; "
            f"DUT interfaces={duplicate_dut_interfaces!r}, "
            f"chassis ports={duplicate_chassis_ports!r}"
        )


def _duplicates(values: list[str]) -> list[str]:
    return sorted(value for value in set(values) if values.count(value) > 1)


# ─── Shared constants ─────────────────────────────────────────────────────

_EBB_BGPCPP_PATH = "taac/ebb_ci_cd_configs/ebb_full_scale_bgpcpp_config"
IXIA03_ASH6 = "2401:db00:2066:3036::3003"
IXIA11_ASH6 = "2401:db00:2066:303b::3001"


# ─── Lab-wiring helpers (used by the ebXX.lab.ash6 + bgp.eb.test.ash6 boxes) ───
# These produce the ``host_driver_args`` / ``oss_mock_device_data`` payloads that
# the retired ``util/bgp_ebb_lab_wiring._lab_device_wiring`` helper used to
# synthesize at factory-call time. Byte-identical outputs preserved: password
# read via ``os.environ.get(env_var, "dnepit")`` (env-var lookup runs at Testbed
# construction / module-import time; TAAC test processes do not mutate the
# password env var after import).


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
) -> dict[str, taac_types.MockDeviceInfo]:
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
    return {device_name: taac_types.MockDeviceInfo(**mock_kwargs)}


# ─── BAG conveyor testbeds ────────────────────────────────────────────────
# Each ASH6 BAG device has one canonical Testbed artifact. ``ixia_ports``
# always describes the chassis selected by ``primary_ixia_chassis_ip``.

BAG002_SNC1 = Testbed(
    device_name="bag002.snc1",
    usage=frozenset({"qual"}),
    primary_ixia_chassis_ip="ares1-my24520014",
    ixia_ports=[
        ("Ethernet3/25/1", "1/17"),  # eBGP
        ("Ethernet3/26/1", "1/18"),  # iBGP
        ("Ethernet3/27/1", "1/19"),  # BGP-MON
    ],
    bgpcpp_configerator_path=_EBB_BGPCPP_PATH,
    peer_groups=ebb_peer_groups(),
)

BAG010_ASH6 = Testbed(
    device_name="bag010.ash6",
    usage=frozenset({"cicd", "qual"}),
    primary_ixia_chassis_ip=IXIA11_ASH6,
    secondary_ixia_chassis_ip=IXIA03_ASH6,
    ixia_ports=[
        ("Ethernet3/36/1", "7/1"),  # eBGP
        ("Ethernet3/36/2", "7/2"),  # iBGP
        ("Ethernet3/36/3", "7/3"),  # BGP-MON
    ],
    dut_bgp_as=65010,
    bgpcpp_configerator_path=_EBB_BGPCPP_PATH,
    openr_configerator_path="taac/ebb_ci_cd_configs/bag010_ash6_openr_config",
    peer_groups=ebb_peer_groups(),
    extras={
        # OpenR link-config knobs consumed by
        # ``conveyor_common_tasks.get_common_setup_tasks`` for the bag010.ash6
        # DUT. Kept in ``extras`` because they are OpenR-specific baseline
        # attributes and do not fit the generic Testbed fields.
        "openr_port_channel_member": "Ethernet3/6/1",
        "openr_port_channel_ipv4": "10.131.97.238/31",
        "openr_port_channel_link_local": "fe80::eba:a7f:fd02/64",
        "openr_local_link": {
            "ipv4": "10.131.97.238",
            "ipv6": "fe80::eba:a7f:fd02",
            "ifName": "po100211",
            "weight": 0,
            "metric": 10,
        },
        "openr_other_link": {
            "ipv4": "10.131.97.239",
            "ipv6": "fe80::eba:a7f:fd03",
            "ifName": "po100211",
            "weight": 0,
            "metric": 10,
        },
    },
)

BAG011_ASH6 = Testbed(
    device_name="bag011.ash6",
    usage=frozenset({"cicd", "qual"}),
    primary_ixia_chassis_ip=IXIA03_ASH6,
    secondary_ixia_chassis_ip=IXIA11_ASH6,
    ixia_ports=[
        ("Ethernet3/35/1", "1/53"),  # eBGP
        ("Ethernet3/35/2", "1/54"),  # iBGP
        ("Ethernet3/35/3", "1/55"),  # BGP-MON
    ],
    # NOTE: preserved verbatim from the legacy bag011_ash6_test_config.py
    # which stored the DUT's local BGP AS in a variable named
    # ``BAG012_EOS_BGP_AS = 65011``. The literal 65011 is bag011's AS; the
    # legacy variable name was a copy-paste artifact.
    dut_bgp_as=65011,
    bgpcpp_configerator_path=_EBB_BGPCPP_PATH,
    openr_configerator_path="taac/ebb_ci_cd_configs/bag011_ash6_openr_config",
    peer_groups=ebb_peer_groups(),
    extras={
        # OpenR link-config knobs consumed by
        # ``conveyor_common_tasks.get_common_setup_tasks`` for the bag011.ash6
        # DUT. Kept in ``extras`` because they are OpenR-specific baseline
        # attributes and do not fit the generic Testbed fields.
        "openr_port_channel_member": "Ethernet3/9/1",
        "openr_port_channel_ipv4": "10.131.97.236/31",
        "openr_port_channel_link_local": "fe80::eba:a7f:fd00/64",
        # bag011 uses the shared ``OPENR_LOCAL_LINK`` / ``OPENR_OTHER_LINK``
        # constants from ``conveyor_constants.py`` verbatim (unlike bag010
        # which has DUT-specific overrides).
        "openr_local_link": {
            "ipv4": "10.131.97.236",
            "ipv6": "fe80::eba:a7f:fd00",
            "ifName": "po100211",
            "weight": 0,
            "metric": 10,
        },
        "openr_other_link": {
            "ipv4": "10.131.97.237",
            "ipv6": "fe80::eba:a7f:fd01",
            "ifName": "po100211",
            "weight": 0,
            "metric": 10,
        },
    },
)

BAG012_ASH6 = Testbed(
    device_name="bag012.ash6",
    usage=frozenset({"cicd", "qual"}),
    primary_ixia_chassis_ip=IXIA11_ASH6,
    secondary_ixia_chassis_ip=IXIA03_ASH6,
    ixia_ports=[
        ("Ethernet3/36/1", "8/1"),  # eBGP
        ("Ethernet3/36/2", "8/2"),  # iBGP
        ("Ethernet3/36/3", "8/3"),  # BGP-MON
    ],
    dut_bgp_as=65012,
    # bag012 is the only bag testbed that pins ``router_id`` explicitly
    # (bag010/bag011/bag013 all rely on the device-default BGP router-id).
    # Preserved verbatim from the legacy bag012 config for golden-manifest identity.
    router_id="10.163.28.11",
    bgpcpp_configerator_path=_EBB_BGPCPP_PATH,
    openr_configerator_path="taac/ebb_ci_cd_configs/bag012_ash6_openr_config",
    peer_groups=ebb_peer_groups(),
    extras={
        # OpenR link-config knobs consumed by
        # ``conveyor_common_tasks.get_common_setup_tasks`` for the bag012.ash6
        # DUT — same shape as bag010/bag011/bag013. Not yet exercised by any
        # BAG012 catalog binding (all 6 current bindings run
        # ``factories/bgp_ebb_characteristic.py`` factories that skip OpenR
        # setup); dormant capability unlocked when a full-scale factory is
        # added for BAG012 (Wave 7A/7B/7C).
        "openr_port_channel_member": "Ethernet3/9/1",
        "openr_port_channel_ipv4": "10.131.97.234/31",
        "openr_port_channel_link_local": "fe80::eba:a7f:fcfe/64",
        "openr_local_link": {
            "ipv4": "10.131.97.234",
            "ipv6": "fe80::eba:a7f:fcfe",
            "ifName": "po100211",
            "weight": 0,
            "metric": 10,
        },
        "openr_other_link": {
            "ipv4": "10.131.97.235",
            "ipv6": "fe80::eba:a7f:fcff",
            "ifName": "po100211",
            "weight": 0,
            "metric": 10,
        },
    },
)

BAG013_ASH6 = Testbed(
    device_name="bag013.ash6",
    usage=frozenset({"cicd", "qual"}),
    primary_ixia_chassis_ip=IXIA11_ASH6,
    secondary_ixia_chassis_ip=IXIA03_ASH6,
    ixia_ports=[
        ("Ethernet3/36/1", "8/5"),  # eBGP
        ("Ethernet3/36/2", "8/6"),  # iBGP
        ("Ethernet3/36/3", "8/7"),  # BGP-MON
    ],
    dut_bgp_as=65013,
    # No ``router_id`` — device-default (same as bag010/bag011; see BAG012_ASH6 note).
    bgpcpp_configerator_path=_EBB_BGPCPP_PATH,
    openr_configerator_path="taac/ebb_ci_cd_configs/bag013_ash6_openr_config",
    peer_groups=ebb_peer_groups(),
    extras={
        # OpenR link-config knobs consumed by
        # ``conveyor_common_tasks.get_common_setup_tasks`` for the bag013.ash6
        # DUT. Kept in ``extras`` because they are OpenR-specific baseline
        # attributes and do not fit the generic Testbed fields.
        "openr_port_channel_member": "Ethernet3/9/1",
        "openr_port_channel_ipv4": "10.131.97.232/31",
        "openr_port_channel_link_local": "fe80::eba:a7f:fcfc/64",
        "openr_local_link": {
            "ipv4": "10.131.97.232",
            "ipv6": "fe80::eba:a7f:fcfc",
            "ifName": "po100211",
            "weight": 0,
            "metric": 10,
        },
        "openr_other_link": {
            "ipv4": "10.131.97.233",
            "ipv6": "fe80::eba:a7f:fcfd",
            "ifName": "po100211",
            "weight": 0,
            "metric": 10,
        },
    },
)

# ─── CTE UCMP testbeds ────────────────────────────────────────────────────
# Wave 2C — CTE UCMP feature testconfigs (moved from testconfigs/routing/
# test_config_cte_ucmp{,_stand_alone}.py). The multi-node QZD topology
# (4 endpoints, no shared chassis IP) does not fit the flat Testbed dataclass;
# only the DUT identity is captured here and the spine + IXIA-port layout
# stays as private module-level constants inside factories/cte_ucmp.py.

CTE_UCMP_QZD_TESTBED = Testbed(
    usage=frozenset({"adhoc"}),
    device_name="fa001-du004.qzd1",
    # No shared IXIA chassis IP: the QZD test config uses per-endpoint
    # ``ixia_ports`` strings and does not declare a chassis IP anywhere.
    # ``ixia_ports`` stays empty for the same reason (per-endpoint port lists
    # live on Endpoint objects built inside the factory).
    primary_ixia_chassis_ip="",
)

CTE_UCMP_STAND_ALONE_TESTBED = Testbed(
    device_name="fsw003.p003.f01.qzd1",
    usage=frozenset({"adhoc"}),
    primary_ixia_chassis_ip="2401:db00:0116:303b:0000:0000:0000:0100",
    ixia_ports=[
        ("eth7/16/1", "6/2"),  # uplink (eBGP)
        ("eth8/16/1", "3/3"),  # downlink (12 confed peers across 3 DCs)
    ],
    mac_address="b6:a9:fc:34:2b:41",
)


# ─── EB0x lab testbeds (Arista lab boxes in ASH6) ─────────────────────────
# The ebXX.lab.ash6 devices are lab boxes with admin/password auth
# (svc-netcastle_bot is not authorized). ``extras`` carries the shared lab
# credentials plus MockDeviceInfo fields (netwhoami returns ``#INVALID#`` for
# these devices, so ``get_common_setup_tasks`` needs a synthesized record).
EB01_LAB_ASH6 = Testbed(
    usage=frozenset({"qual"}),
    device_name="eb01.lab.ash6",
    primary_ixia_chassis_ip=IXIA11_ASH6,
    ixia_ports=[
        ("Ethernet3/1/3", "5/7"),  # eBGP
        ("Ethernet3/1/5", "5/8"),  # iBGP
        # No BGP-MON port on eb01 (bgp_mon_peer_count=0 in the legacy source).
    ],
    dut_bgp_as=64981,
    bgpcpp_configerator_path=_EBB_BGPCPP_PATH,
    lab_device_password_env_var="TAAC_EBB_LAB_DEVICE_PASSWORD",
    ssh_user="admin",
    host_driver_args=_lab_host_driver_args("eb01.lab.ash6"),
    oss_mock_device_data=_lab_oss_mock_device_data("eb01.lab.ash6", network_type="EBB"),
    peer_groups=ebb_peer_groups(),
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

EB02_LAB_ASH6 = Testbed(
    usage=frozenset({"qual"}),
    device_name="eb02.lab.ash6",
    primary_ixia_chassis_ip=IXIA11_ASH6,
    ixia_ports=[
        ("Ethernet3/1/3", "6/2"),  # eBGP
        ("Ethernet3/1/5", "6/3"),  # iBGP
        # No BGP-MON port on eb02 (bgp_mon_peer_count=0 in the legacy source).
    ],
    dut_bgp_as=64981,
    bgpcpp_configerator_path=_EBB_BGPCPP_PATH,
    lab_device_password_env_var="TAAC_EBB_LAB_DEVICE_PASSWORD",
    ssh_user="admin",
    host_driver_args=_lab_host_driver_args("eb02.lab.ash6"),
    oss_mock_device_data=_lab_oss_mock_device_data("eb02.lab.ash6", network_type="EBB"),
    peer_groups=ebb_peer_groups(),
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

EB03_LAB_ASH6 = Testbed(
    usage=frozenset({"qual"}),
    device_name="eb03.lab.ash6",
    primary_ixia_chassis_ip=IXIA11_ASH6,
    ixia_ports=[
        ("Ethernet3/1/3", "6/5"),  # eBGP
        ("Ethernet3/1/5", "6/6"),  # iBGP
        ("Ethernet3/36/1", "2/8"),  # BGP-MON
    ],
    dut_bgp_as=64981,
    bgpcpp_configerator_path=_EBB_BGPCPP_PATH,
    lab_device_password_env_var="TAAC_EBB_LAB_DEVICE_PASSWORD",
    ssh_user="admin",
    host_driver_args=_lab_host_driver_args("eb03.lab.ash6"),
    oss_mock_device_data=_lab_oss_mock_device_data("eb03.lab.ash6", network_type="EBB"),
    peer_groups=ebb_peer_groups(),
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

EB04_LAB_ASH6 = Testbed(
    usage=frozenset({"qual"}),
    device_name="eb04.lab.ash6",
    primary_ixia_chassis_ip=IXIA11_ASH6,
    ixia_ports=[
        ("Ethernet3/1/1", "6/7"),  # eBGP
        ("Ethernet3/1/3", "6/8"),  # iBGP
        # No BGP-MON port on eb04 (bgp_mon_peer_count=0 in the legacy source;
        # ixia_interface_mimic_bgp_mon aliases the eBGP port and is unused).
    ],
    dut_bgp_as=64981,
    bgpcpp_configerator_path=_EBB_BGPCPP_PATH,
    lab_device_password_env_var="TAAC_EBB_LAB_DEVICE_PASSWORD",
    ssh_user="admin",
    host_driver_args=_lab_host_driver_args("eb04.lab.ash6"),
    # NOTE: legacy eb04 source omits ``network_type`` on MockDeviceInfo,
    # unlike eb01/eb03 which set ``network_type="EBB"``. Preserved verbatim.
    oss_mock_device_data=_lab_oss_mock_device_data("eb04.lab.ash6"),
    peer_groups=ebb_peer_groups(),
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
EB_TEST_DEVICE = Testbed(
    usage=frozenset({"qual"}),
    device_name="bgp.eb.test.ash6",
    primary_ixia_chassis_ip=IXIA11_ASH6,
    ixia_ports=[
        ("Ethernet3/1/5", "5/3"),  # eBGP
        ("Ethernet3/1/3", "5/2"),  # iBGP
    ],
    dut_bgp_as=64981,
    bgpcpp_configerator_path=_EBB_BGPCPP_PATH,
    lab_device_password_env_var="TAAC_EBB_LAB_DEVICE_PASSWORD",
    ssh_user="admin",
    # Extra host-driver JSON kwarg beyond the standard username/password
    # pair — routes the BGP++ thrift RPC to a specific IPv6 address on
    # the dev testbed (device's regular loopback is not reachable from
    # devservers).
    host_driver_args=_lab_host_driver_args(
        "bgp.eb.test.ash6",
        extra_kwargs={"bgp_ip": "2401:db00:2066:304a::1001"},
    ),
    oss_mock_device_data=_lab_oss_mock_device_data(
        "bgp.eb.test.ash6", network_type="EBB"
    ),
    peer_groups=ebb_peer_groups(),
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
JSW002_M001_SNC1 = Testbed(
    usage=frozenset({"adhoc"}),
    device_name="jsw002.m001.snc1",
    primary_ixia_chassis_ip="",
    dut_bgp_as=64981,
    bgpcpp_configerator_path=_EBB_BGPCPP_PATH,
    peer_groups=ebb_peer_groups(),
    extras={
        # Reference DUT interfaces from the legacy source, kept here so Wave
        # 5B factories can wire up ixia setup without re-parsing the legacy
        # testconfig files.
        "dut_iface_ebgp": "Ethernet3/8/1",
        "dut_iface_ibgp": "Ethernet3/8/5",
        "dut_iface_bgp_mon": "Ethernet3/9/1",
    },
)


# ─── FA verify testbed (FA001-UU001 in QZD1) ──────────────────────────────
# ``fa001-uu001.qzd1`` is a Fabric-Aggregator uplink used by the BGP++
# computational-load and constant-attribute-storage feature verify configs.
# It uses FAUU-style peer-group names (PEERGROUP_FAUU_*) rather than the
# EBB EB-EB/EB-FA scheme, so ``peer_groups`` is left empty here — a
# future ``fa_uu_peer_groups()`` helper will populate it when Wave 5B
# migrates the FA verify factory.
FA001_UU001_QZD1 = Testbed(
    usage=frozenset({"adhoc"}),
    device_name="fa001-uu001.qzd1",
    primary_ixia_chassis_ip="",
    # dut_bgp_as = ibgp_remote_as (iBGP is same-AS): AS 65271 (FAUU-FADU pool).
    dut_bgp_as=65271,
    extras={
        "dut_iface_ebgp": "eth6/13/1",
        "dut_iface_ibgp": "eth6/15/1",
    },
)


# ─── FBOSS EBB single-node testbeds (FSW / QZD family) ────────────────────
# Four sibling testbeds built from the same ``test_config_for_bgp_plus_plus_ebb``
# / ``..._with_bgp_mon`` factories, each pinning a different DUT. The QZD
# testconfigs uniformly route to the ASH6 IXIA chassis (verbatim from legacy
# ``direct_ixia_connections``); the non-MON siblings do not declare direct
# connections at all, so their ports are captured via ``extras`` for Wave 5B
# to consume.
FSW001_QZB = Testbed(
    usage=frozenset({"adhoc"}),
    device_name="fsw001.p003.f01.qzb1",
    primary_ixia_chassis_ip=IXIA11_ASH6,
    ixia_ports=[
        ("eth7/1/1", "1/7"),  # eBGP
        ("eth7/3/1", "1/8"),  # iBGP
        ("eth7/5/1", "4/3"),  # BGP-MON
    ],
    dut_bgp_as=64981,
    bgpcpp_configerator_path=_EBB_BGPCPP_PATH,
    peer_groups=ebb_peer_groups(),
)

FSW_QZB = Testbed(
    usage=frozenset({"adhoc"}),
    device_name="fsw001.p003.f01.qzb1",
    # Legacy ``fsw_qzb_...`` testconfig declares no ``direct_ixia_connections``.
    # Same physical DUT as ``FSW001_QZB`` above; a separate Testbed instance
    # because it drives a different testconfig (no BGP-MON, different playbook
    # scope) and Wave 5B may layer distinct factory args on top.
    primary_ixia_chassis_ip="",
    dut_bgp_as=64981,
    bgpcpp_configerator_path=_EBB_BGPCPP_PATH,
    peer_groups=ebb_peer_groups(),
    extras={
        "dut_iface_ebgp": "eth7/1/1",
        "dut_iface_ibgp": "eth7/3/1",
    },
)

QZD_FSW002 = Testbed(
    usage=frozenset({"adhoc"}),
    device_name="fsw002.p003.f01.qzb1",
    primary_ixia_chassis_ip="",
    dut_bgp_as=64981,
    bgpcpp_configerator_path=_EBB_BGPCPP_PATH,
    peer_groups=ebb_peer_groups(),
    extras={
        "dut_iface_ebgp": "eth7/1/1",
        "dut_iface_ibgp": "eth7/3/1",
        "dut_iface_bgp_mon": "eth7/5/1",
    },
)

QZD_LAB = Testbed(
    usage=frozenset({"adhoc"}),
    # Same DUT name as ``CTE_UCMP_STAND_ALONE_TESTBED`` — the CTE UCMP config
    # reserves this device for confed-peer stand-alone testing, while
    # ``QZD_LAB`` uses it as an EBB single-node full-scale DUT. Separate
    # logical testbed because peer-groups / route-maps differ (uses
    # PROPAGATE_FSW_SSW_* / PROPAGATE_FSW_RSW_* policy names in the legacy
    # source, distinct from EBB EB-FA-IN/OUT).
    device_name="fsw003.p003.f01.qzd1",
    primary_ixia_chassis_ip="",
    dut_bgp_as=64981,
    bgpcpp_configerator_path=_EBB_BGPCPP_PATH,
    peer_groups=ebb_peer_groups(),
    extras={
        "dut_iface_ebgp": "eth8/16/1",
        "dut_iface_ibgp": "eth9/16/1",
    },
)


# ─── BGP-DC chronos_node testbeds (Wave 3B) ───────────────────────────────
# Consumed by ``factories/bgp_dc_chronos_node.py`` — single-DUT BGP++ DC
# configs assembled through ``create_bgp_dc_chronos_node_test_config``. The
# BGP-DC factory ignores ``ixia_ports`` (physical chassis-port mapping is
# discovered at runtime rather than pinned in the testconfig), so the DUT
# interface names for downlink / uplink / rogue live in ``extras`` where the
# factory reads them. ``extras`` also carries the SSW-vs-FSW peer-group
# names, route-map identifiers, IXIA parent-network prefixes, ASNs, confed
# flags, and per-testbed IXIA BGP communities — every knob that varies by
# testbed but not by binding.

# Shared IXIA parent networks / hardening baselines. Every BGP-DC chronos
# binding pins the same downlink/uplink/rogue IPv6+IPv4 parent prefixes and
# NDP-stressor networks (verified across all 4 pre-migration bindings). Kept
# as a module-level dict so each Testbed inherits the same values without
# repeating them.
_BGP_DC_CHRONOS_SHARED_EXTRAS = {
    "ixia_downlink_ic_parent_network_v6": "2401:db00:e50d:11:8",
    "ixia_uplink_ic_parent_network_v6": "2401:db00:e50d:11:9",
    "ixia_rogue_ic_parent_network_v6": "2401:db00:e50d:11:10",
    "ixia_downlink_ic_parent_network_v4": "10.163.28",
    "ixia_uplink_ic_parent_network_v4": "10.164.28",
    "ixia_rogue_ic_parent_network_v4": "10.165.28",
    "good_ndp_entry_network_v6": "2401:db00:e50d:11:9",
    "rogue_ndp_entry_network_v6": "2401:db00:e50d:11:8",
    "good_arp_entry_network_v4": "192.168",
    "rogue_arp_entry_network_v4": "193.168",
    "ixia_uplink_good_ndp_network": "2401:db00:e50d:1101:9",
    "ixia_downlink_good_ndp_network": "2401:db00:e50d:1101:8",
}

SSW_ELBERT_QZD1 = Testbed(
    usage=frozenset({"adhoc"}),
    device_name="ssw001.s002.f01.qzd1",
    primary_ixia_chassis_ip="",
    mac_address="c2:18:50:9c:1f:1d",
    extras={
        **_BGP_DC_CHRONOS_SHARED_EXTRAS,
        "ixia_downlink_interface": "eth7/16/1",
        "ixia_uplink_interface": "eth8/16/1",
        "ixia_rogue_interface": "eth9/16/1",
        "peergroup_uplink_mimic_v6": "PEERGROUP_SSW_FADU_V6",
        "peergroup_uplink_mimic_v4": "PEERGROUP_SSW_FADU_V4",
        "peergroup_downlink_mimic_v6": "PEERGROUP_SSW_FSW_V6",
        "peergroup_downlink_mimic_v4": "PEERGROUP_SSW_FSW_V4",
        # Rogue peer-group re-uses the uplink identifiers (per pre-migration source).
        "peergroup_rogue_mimic_v6": "PEERGROUP_SSW_FADU_V6",
        "peergroup_rogue_mimic_v4": "PEERGROUP_SSW_FADU_V4",
        "route_map_uplink_ingress": "PROPAGATE_SSW_FADU_IN",
        "route_map_uplink_egress": "PROPAGATE_SSW_FADU_OUT",
        "route_map_downlink_ingress": "PROPAGATE_SSW_FSW_IN",
        "route_map_downlink_egress": "PROPAGATE_SSW_FSW_OUT",
        # Rogue route-map re-uses the uplink ingress + downlink egress (per source).
        "route_map_rogue_ingress": "PROPAGATE_SSW_FADU_IN",
        "route_map_rogue_egress": "PROPAGATE_SSW_FSW_OUT",
        "remote_downlink_as_4byte": 65409,
        "remote_uplink_as_4byte": 65271,
        "remote_rogue_as_4byte": 2500,
        "is_uplink_peer_confed": "False",
        "is_downlink_peer_confed": "False",
        "is_rogue_peer_confed": "False",
        "ixia_downlink_communities": [
            "65529:34814",
            "65441:131",
        ],
        "ixia_uplink_communities": [
            "65441:261",
        ],
    },
)

FSW_FUJI_QZD1 = Testbed(
    usage=frozenset({"adhoc"}),
    device_name="fsw002.p006.f01.qzd1",
    primary_ixia_chassis_ip="",
    mac_address="c2:18:50:9c:13:f8",
    extras={
        **_BGP_DC_CHRONOS_SHARED_EXTRAS,
        "ixia_downlink_interface": "eth8/16/1",
        # Fuji uplink is on eth9/14/1 — the odd port-index (out of the /16/1
        # sibling pattern) is verbatim from the pre-migration source.
        "ixia_uplink_interface": "eth9/14/1",
        "ixia_rogue_interface": "eth9/16/1",
        "peergroup_uplink_mimic_v6": "PEERGROUP_FSW_SSW_V6",
        "peergroup_uplink_mimic_v4": "PEERGROUP_FSW_SSW_V4",
        "peergroup_downlink_mimic_v6": "PEERGROUP_FSW_RSW_V6",
        "peergroup_downlink_mimic_v4": "PEERGROUP_FSW_RSW_V4",
        "peergroup_rogue_mimic_v6": "PEERGROUP_FSW_SSW_V6",
        "peergroup_rogue_mimic_v4": "PEERGROUP_FSW_SSW_V4",
        "route_map_uplink_ingress": "PROPAGATE_FSW_SSW_IN",
        "route_map_uplink_egress": "PROPAGATE_FSW_SSW_OUT",
        "route_map_downlink_ingress": "PROPAGATE_FSW_RSW_IN",
        "route_map_downlink_egress": "PROPAGATE_FSW_RSW_OUT",
        "route_map_rogue_ingress": "PROPAGATE_FSW_SSW_IN",
        "route_map_rogue_egress": "PROPAGATE_FSW_RSW_OUT",
        # FSW uplink terminates on the ASH6 SSW plane (AS 65000); downlink is
        # a private RSW pool (AS 2000); rogue re-uses the rogue AS reservation.
        "remote_downlink_as_4byte": 2000,
        "remote_uplink_as_4byte": 65000,
        "remote_rogue_as_4byte": 2500,
        "is_uplink_peer_confed": "False",
        "is_downlink_peer_confed": "True",
        "is_rogue_peer_confed": "False",
        "ixia_downlink_communities": [
            "65441:194",
            "65441:9001",
            "65441:9002",
            "65441:9003",
            "65441:9004",
            "65441:9005",
        ],
        "ixia_uplink_communities": [
            "65441:196",
            "65441:9001",
            "65441:9002",
            "65441:9003",
            "65441:9004",
            "65441:9005",
        ],
    },
)

# ``FSW_P001_QZD1`` and ``FSW_P006_QZD1`` are declared for
# ``testconfigs/fboss_solution_tests/chronos_node_{fsw_p001_qzd1,
# full_scale_p006_qzd1}_test_config.py`` — configs built by
# ``test_config_for_bgp_and_fboss_platform_hardening_in_conveyor`` (a
# traffic-carrying sibling factory that lives outside this Wave's scope).
# No rogue-interface port and no rogue peer-group / route-map / community
# entries because that factory does not exercise the rogue path.
FSW_P001_QZD1 = Testbed(
    usage=frozenset({"adhoc"}),
    device_name="fsw001.p001.f01.qzd1",
    primary_ixia_chassis_ip="",
    mac_address="fe:59:c0:46:07:94",
    extras={
        "ixia_downlink_interface": "eth8/16/1",
        "ixia_uplink_interface": "eth9/16/1",
    },
)

FSW_P006_QZD1 = Testbed(
    usage=frozenset({"adhoc"}),
    device_name="fsw001.p006.f01.qzd1",
    primary_ixia_chassis_ip="",
    mac_address="c2:18:50:b7:0a:46",
    extras={
        "ixia_downlink_interface": "eth8/16/1",
        "ixia_uplink_interface": "eth9/16/1",
    },
)
