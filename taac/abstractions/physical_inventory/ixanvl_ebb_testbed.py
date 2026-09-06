# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""IxANVL BGP conformance rigs, resolved from the EBB physical inventory.

──────────────────────────────────────────────────────────────────────────
 §1  Purpose
──────────────────────────────────────────────────────────────────────────
Bind an ``(IXIA chassis, DUT)`` pair to the physical facts the IxANVL BGP
conformance runner needs, so the runner can be invoked as

    bgpconf run 1.1 --ixia ixia11.netcastle.ash6 --dut eb03.lab.ash6

and take the cabling, the chassis addressing and the lab credentials from
here instead of from hardcoded tables in the conformance CLI.
This module is the source of truth for the PHYSICAL layout.

It deliberately holds NO L3 addressing. The DUT and tester IP addresses are
already stated per test, in the configs the runner consumes:

    fbcode/neteng/test_infra/routing_qualification/bgp_conformance/configs/ixanvl/<suite>/<test>/dut.json    local_addr / peer_addr
    fbcode/neteng/test_infra/routing_qualification/bgp_conformance/configs/ixanvl/<suite>/<test>/anvl.json   interfaces{dut,anvl,mask}

Restating them here would create a second copy of a value that is already
per-test, and per-test is the level at which it actually varies. What is
NOT stated anywhere else, and is therefore what this module adds, is which
DUT interface each chassis port is cabled to, and how to reach the box.

──────────────────────────────────────────────────────────────────────────
 §2  IXIA chassis inventory
──────────────────────────────────────────────────────────────────────────
Each chassis has TWO addresses and they are not interchangeable:

    Handle             Address                      Who uses it
    ─────────────────  ───────────────────────────  ──────────────────────
    IXIA11_ASH6        2401:db00:2066:303b::3001    Netcastle / DICE, as
                                                    the routable management
                                                    address of the chassis
    knc_chassis        192.168.124.1                The KNC application, as
                                                    the chassis handle
                                                    inside a
                                                    "chassis;card;port"
                                                    port string
    knc_host           ixia11.netcastle.ash6        The KNC web app host,
                                                    which is what --ixia
                                                    names

The same physical chassis. A port string built with the management address
is rejected by KNC, so ``knc_chassis`` is the one that goes into the port
key and ``primary_ixia_chassis_ip`` is the one DICE binds.

──────────────────────────────────────────────────────────────────────────
 §3  Figure A — IxANVL conformance rig (ASH6)
──────────────────────────────────────────────────────────────────────────
Three links, and the ORDER below is load-bearing: it is what makes a port
``Network Interface 1`` / ``2`` / ``3`` on the tester side, and therefore
which link a test's ``<DIface-N>`` resolves to.

    IXIA11_ASH6 (knc_chassis 192.168.124.1)          eb03.lab.ash6
    ───────────────────────────────────────          ─────────────
      card 6 port 5  ●────────────────────────────●  Ethernet3/1/3    DIface-0
      card 6 port 6  ●────────────────────────────●  Ethernet3/1/5    DIface-1
      card 2 port 8  ●────────────────────────────●  Ethernet3/36/1   DIface-2

eb01, eb02 and eb04 sit on the same chassis on different ports and are not
part of the conformance rig; see ``routing_ebb_testbed.py``.

──────────────────────────────────────────────────────────────────────────
 §6  See also
──────────────────────────────────────────────────────────────────────────
- ``routing_ebb_testbed.py`` — the ``PhysicalInventory`` artifacts this
  module resolves against. ``EB03_LAB_ASH6`` already declares the cabling
  and the lab credentials; nothing here redefines them.
- ``README.md`` — the ``<domain>_<testbed>_testbed.py`` file shape, and the
  rule that a DICE consumer adds its own module rather than pushing domain
  policy into the ``PhysicalInventory`` schema. This module follows that:
  it adds no fields to the schema.
- ``neteng/test_infra/routing_qualification/bgp_conformance/docs/RULEBOOK.md §2.0b`` — why interface
  ORDER is a whole-mapping replace and never a merge.
"""

from __future__ import annotations

from dataclasses import dataclass

from taac.abstractions.physical_inventory.physical_inventory import (
    PhysicalInventory,
)
from taac.abstractions.physical_inventory.routing_ebb_testbed import (
    EB03_LAB_ASH6,
    IXIA11_ASH6,
)


@dataclass(frozen=True)
class IxanvlChassis:
    """One IXIA chassis, under all three of the names it answers to."""

    # What ``--ixia`` names: the KNC web application host.
    knc_host: str
    # The chassis handle the KNC app expects inside a port string.
    knc_chassis: str
    # The routable management address DICE binds as
    # ``PhysicalInventory.primary_ixia_chassis_ip``.
    management_address: str


IXIA11 = IxanvlChassis(
    knc_host="ixia11.netcastle.ash6",
    knc_chassis="192.168.124.1",
    management_address=IXIA11_ASH6,
)


@dataclass(frozen=True)
class IxanvlRig:
    """An ``(IXIA chassis, DUT)`` pair the conformance runner can be pointed at."""

    chassis: IxanvlChassis
    inventory: PhysicalInventory

    def __post_init__(self) -> None:
        # The two records must agree about which chassis this DUT is on. They
        # are maintained in different places by different teams, so a silent
        # disagreement would point the runner at one chassis while DICE
        # reserved another — and every test would fail looking like a DUT
        # fault. Fail at import instead.
        if self.inventory.primary_ixia_chassis_ip != self.chassis.management_address:
            raise ValueError(
                f"IxanvlRig {self.inventory.device_name}: inventory chassis "
                f"{self.inventory.primary_ixia_chassis_ip!r} does not match "
                f"{self.chassis.knc_host} ({self.chassis.management_address!r})"
            )
        if not self.inventory.ixia_ports:
            raise ValueError(
                f"IxanvlRig {self.inventory.device_name}: inventory declares no "
                "ixia_ports, so there is no cabling to resolve"
            )

    @property
    def device_name(self) -> str:
        """What ``--dut`` names."""
        return self.inventory.device_name

    @property
    def interconnects(self) -> list[tuple[str, str]]:
        """``(dut_interface, "chassis;card;port")`` per link, IN ORDER.

        Order is the tester's ``Network Interface`` numbering, so it is a
        contract and not a presentation choice. It is taken from
        ``PhysicalInventory.ixia_ports``, whose own docstring states the
        ordering is stable and interpreted by the consumer.
        """
        return [
            (dut_interface, self.port_key(chassis_port))
            for dut_interface, chassis_port in self.inventory.ixia_ports
        ]

    def port_key(self, chassis_port: str) -> str:
        """``"6/5"`` -> ``"192.168.124.1;6;5"``, the form KNC expects."""
        card, _, port = chassis_port.partition("/")
        if not card or not port:
            raise ValueError(
                f"IxanvlRig {self.device_name}: chassis port {chassis_port!r} is "
                "not in '<card>/<port>' form"
            )
        return f"{self.chassis.knc_chassis};{card};{port}"

    # ─── Reaching the box ─────────────────────────────────────────────────
    # Taken from the inventory rather than restated, so the conformance
    # runner stops carrying its own copy of the lab credentials.

    @property
    def ssh_user(self) -> str | None:
        return self.inventory.ssh_user

    @property
    def password_env_var(self) -> str | None:
        return self.inventory.lab_device_password_env_var

    @property
    def dut_bgp_as(self) -> int | None:
        return self.inventory.dut_bgp_as


IXANVL_EB03_ASH6 = IxanvlRig(chassis=IXIA11, inventory=EB03_LAB_ASH6)

# Keyed by the two names the CLI is given. A DUT can appear under more than
# one chassis once a secondary is cabled, which is why the key is the pair
# and not the DUT alone.
IXANVL_RIGS: dict[tuple[str, str], IxanvlRig] = {
    (IXANVL_EB03_ASH6.chassis.knc_host, IXANVL_EB03_ASH6.device_name): (
        IXANVL_EB03_ASH6
    ),
}


def resolve_rig(ixia: str, dut: str) -> IxanvlRig:
    """Look up the rig for ``--ixia``/``--dut``.

    Raises rather than falling back to a default. A conformance run against
    the wrong cabling produces verdicts that describe neither the DUT nor the
    rig, and a wrong default is the failure mode that is hardest to notice.
    """
    try:
        return IXANVL_RIGS[(ixia, dut)]
    except KeyError:
        known = ", ".join(f"--ixia {i} --dut {d}" for i, d in sorted(IXANVL_RIGS))
        raise KeyError(
            f"no IxANVL rig for --ixia {ixia!r} --dut {dut!r}. Known rigs: {known}"
        ) from None
