# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""Framework-owned physical inventory definition for DICE."""

from __future__ import annotations

import typing as t
from dataclasses import dataclass, field, replace

from taac.abstractions.topology import OpenRStandaloneLink
from taac.test_as_a_config.types import MockDeviceInfo


VALID_USAGES: frozenset[str] = frozenset({"cicd", "qual", "adhoc", "retired"})


@dataclass(frozen=True)
class PhysicalInventory:
    """Physical resources and device metadata bound to a logical topology.

    DICE owns this reusable schema. Domain-specific inventory modules own
    concrete instances and may populate role-keyed dictionaries.
    """

    # ─── Physical identity (always required) ──────────────────────────────
    device_name: str
    primary_ixia_chassis_ip: str
    # ``ixia_ports`` items are ``(dut_iface, chassis_port)`` tuples. The
    # chassis-port string is IXIA's ``"<card>/<port>"`` shorthand. Ordering is
    # stable and interpreted by the logical topology consumer.
    ixia_ports: list[tuple[str, str]] = field(default_factory=list)
    secondary_ixia_chassis_ip: str | None = None

    # ─── Which catalog surfaces may bind this physical inventory ──────────
    # Members of ``VALID_USAGES``. A cicd_*.py catalog file may only bind
    # physical inventories whose ``usage`` set includes ``"cicd"``; same for qual_ /
    # adhoc_. ``"retired"`` marks a physical_inventory kept only for historical record.
    # Enforced by tests/test_physical_inventory_usage_matches_catalog.py.
    usage: frozenset[str] = field(default_factory=frozenset)

    # ─── DUT identity properties (optional, flat) ─────────────────────────
    mac_address: str | None = None
    speed: str = "100g-2"
    router_id: str | None = None
    dut_bgp_as: int | None = None  # DUT's own local BGP AS

    # ─── Configerator paths for full-config deployment ────────────────────
    bgpcpp_configerator_path: str | None = None
    openr_configerator_path: str | None = None
    openr_standalone_link: OpenRStandaloneLink | None = None
    fboss_agent_configerator_path: str | None = None

    # ─── Lab auth ─────────────────────────────────────────────────────────
    lab_device_password_env_var: str | None = None
    # SSH user for lab boxes (``svc-netcastle_bot`` is not authorized on
    # ebXX.lab.ash6 / bgp.eb.test.ash6). None for production / conveyor
    # inventories, where Netcastle uses its own default SSH identity.
    ssh_user: str | None = None
    # Precomputed ``TestConfig.host_driver_args`` payload for lab boxes.
    # Populated at PhysicalInventory construction time from the shared lab
    # password env var (``TAAC_EBB_LAB_DEVICE_PASSWORD``, falling back to
    # ``"dnepit"``). None for production / conveyor inventories where
    # ``netwhoami`` returns a valid record.
    host_driver_args: dict[str, str] | None = None
    # Precomputed ``TestConfig.oss_mock_device_data`` payload for lab
    # boxes; ``netwhoami`` returns ``#INVALID#`` for lab devices, so
    # ``get_common_setup_tasks`` needs a synthesized ``MockDeviceInfo``.
    # None for production / conveyor inventories.
    oss_mock_device_data: dict[str, MockDeviceInfo] | None = None

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
                f"PhysicalInventory {self.device_name}: usage contains invalid "
                f"values {sorted(bad)!r}; allowed: {sorted(VALID_USAGES)!r}"
            )

        secondary_ports_defined = bool(self.secondary_ixia_ports)
        secondary_chassis_defined = self.secondary_ixia_chassis_ip is not None
        if secondary_ports_defined and not secondary_chassis_defined:
            raise ValueError(
                f"PhysicalInventory {self.device_name}: secondary_ixia_ports requires "
                "secondary_ixia_chassis_ip to be set"
            )
        if not secondary_ports_defined:
            return

        if not self.secondary_ixia_chassis_ip:
            raise ValueError(
                f"PhysicalInventory {self.device_name}: secondary_ixia_chassis_ip must be nonempty"
            )
        _validate_ixia_port_mapping(self.device_name, "ixia_ports", self.ixia_ports)
        _validate_ixia_port_mapping(
            self.device_name,
            "secondary_ixia_ports",
            self.secondary_ixia_ports,
        )
        if len(self.ixia_ports) != len(self.secondary_ixia_ports):
            raise ValueError(
                f"PhysicalInventory {self.device_name}: primary and secondary IXIA port "
                "mappings must have equivalent connection indices; "
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

    def for_secondary_ixia(self) -> PhysicalInventory:
        if not self.has_secondary_ixia:
            raise ValueError(
                f"PhysicalInventory {self.device_name}: no secondary IXIA mapping is defined"
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
        raise ValueError(
            f"PhysicalInventory {device_name}: {field_name} must be nonempty"
        )

    dut_interfaces: list[str] = []
    chassis_ports: list[str] = []
    for index, entry in enumerate(ports):
        if not isinstance(entry, tuple) or len(entry) != 2:
            raise ValueError(
                f"PhysicalInventory {device_name}: {field_name}[{index}] must be a "
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
                f"PhysicalInventory {device_name}: {field_name}[{index}] must contain "
                "nonempty string interface names"
            )
        dut_interfaces.append(dut_interface)
        chassis_ports.append(chassis_port)

    duplicate_dut_interfaces = _duplicates(dut_interfaces)
    duplicate_chassis_ports = _duplicates(chassis_ports)
    if duplicate_dut_interfaces or duplicate_chassis_ports:
        raise ValueError(
            f"PhysicalInventory {device_name}: {field_name} contains duplicate mappings; "
            f"DUT interfaces={duplicate_dut_interfaces!r}, "
            f"chassis ports={duplicate_chassis_ports!r}"
        )


def _duplicates(values: list[str]) -> list[str]:
    return sorted(value for value in set(values) if values.count(value) > 1)
