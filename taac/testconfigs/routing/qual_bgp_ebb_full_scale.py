# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""BGP++ EBB full-scale mimic qualification testconfigs (Arista lab boxes eb01 / eb03 / eb04).

Wave 5E.2 -- migrates the 3 thin wrappers previously living at
``testconfigs/routing/ebb/eb01_arista_mimic_ebb_test_full_scale_without_open_r_test_config.py``,
``testconfigs/routing/ebb/eb03_arista_mimic_ebb_test_full_scale_with_open_r_test_config.py``
and ``testconfigs/routing/ebb/eb04_arista_mimic_ebb_test_full_scale_with_open_r_test_config.py``
into this qualification lifecycle binding module. Each ``TestConfig.name``
string is grandfathered from the legacy wrapper so the golden manifest hash is
byte-wise identical.

The shared/generic ``ARISTA_MIMIC_EBB_TEST_FULL_SCALE`` sibling targets
the ``JSW002_M001_SNC1`` production physical_inventory (usage=adhoc) and lives in
``adhoc_bgp_ebb_full_scale.py``.

External consumers import from this member module directly; see
``fbcode/neteng/test_infra/routing_qualification/docs/taac/TESTCONFIGS.md``.
"""

from taac.abstractions.physical_inventory import (
    EB01_LAB_ASH6,
    EB03_LAB_ASH6,
    EB04_LAB_ASH6,
)
from taac.constants import BgpPlusPlusProfile
from taac.testconfigs.routing.factories.bgp_ebb_full_scale_mimic import (
    create_bgp_ebb_full_scale_mimic_test_config,
)
from taac.test_as_a_config import types as taac_types


# ─── EB01 -- mimic EBB test full scale (with Open/R, no BGP-MON peers) ────
# Legacy wrapper wired ``bgp_mon_peer_count=0`` (no BGP-MON port on eb01)
# and 2 ``DirectIxiaConnection`` entries (eBGP + iBGP). ``TestConfig.name``
# preserved verbatim.
EB01_ARISTA_MIMIC_EBB_TEST_FULL_SCALE_WITHOUT_OPEN_R_TEST_CONFIG = (
    create_bgp_ebb_full_scale_mimic_test_config(
        EB01_LAB_ASH6,
        name="EB01-ARISTA_MIMIC_EBB_TEST_FULL_SCALE_WITHOUT_OPEN_R",
        ixia_interface_mimic_ebgp="Ethernet3/1/3",
        ixia_interface_mimic_ibgp="Ethernet3/1/5",
        ixia_interface_mimic_bgp_mon="Ethernet3/1/7",
        bgp_mon_peer_count=0,
        profile=BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R,
        direct_ixia_connections=[
            taac_types.DirectIxiaConnection(
                interface="Ethernet3/1/3",  # EBGP interface
                ixia_chassis_ip=EB01_LAB_ASH6.ixia_chassis_ip,
                ixia_port="5/7",
            ),
            taac_types.DirectIxiaConnection(
                interface="Ethernet3/1/5",  # IBGP interface
                ixia_chassis_ip=EB01_LAB_ASH6.ixia_chassis_ip,
                ixia_port="5/8",
            ),
        ],
    )
)


# ─── EB03 -- mimic EBB test full scale (with Open/R + BGP-MON peers) ──────
# Legacy wrapper wired ``bgp_mon_peer_count=2`` and 3 ``DirectIxiaConnection``
# entries (BGP Mon + eBGP + iBGP). Note ``ixia_interface_mimic_bgp_mon``
# ``Ethernet3/1/1`` here does NOT match ``EB03_LAB_ASH6.ixia_ports[2][0]``
# (which is ``Ethernet3/36/1``) -- the mimic-scale test uses a different
# card than the queue-memory-monitor sibling. Kept explicit for byte-identity.
EB03_ARISTA_MIMIC_EBB_TEST_FULL_SCALE_WITH_OPEN_R_TEST_CONFIG = (
    create_bgp_ebb_full_scale_mimic_test_config(
        EB03_LAB_ASH6,
        name="EB03-ARISTA_MIMIC_EBB_TEST_FULL_SCALE_WITH_OPEN_R",
        ixia_interface_mimic_ebgp="Ethernet3/1/3",
        ixia_interface_mimic_ibgp="Ethernet3/1/5",
        ixia_interface_mimic_bgp_mon="Ethernet3/1/1",
        bgp_mon_peer_count=2,
        profile=BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R,
        direct_ixia_connections=[
            taac_types.DirectIxiaConnection(
                interface="Ethernet3/1/1",  # BGP Mon interface
                ixia_chassis_ip=EB03_LAB_ASH6.ixia_chassis_ip,
                ixia_port="6/4",
            ),
            taac_types.DirectIxiaConnection(
                interface="Ethernet3/1/3",  # EBGP interface
                ixia_chassis_ip=EB03_LAB_ASH6.ixia_chassis_ip,
                ixia_port="6/5",
            ),
            taac_types.DirectIxiaConnection(
                interface="Ethernet3/1/5",  # IBGP interface
                ixia_chassis_ip=EB03_LAB_ASH6.ixia_chassis_ip,
                ixia_port="6/6",
            ),
        ],
    )
)


# ─── EB04 -- mimic EBB test full scale (with Open/R, no BGP-MON peers) ────
# Legacy wrapper wired ``bgp_mon_peer_count=0`` and 2 ``DirectIxiaConnection``
# entries (eBGP + iBGP). ``ixia_interface_mimic_bgp_mon`` aliases the eBGP
# port and is unused at runtime because ``bgp_mon_peer_count=0``.
EB04_ARISTA_MIMIC_EBB_TEST_FULL_SCALE_WITH_OPEN_R_TEST_CONFIG = (
    create_bgp_ebb_full_scale_mimic_test_config(
        EB04_LAB_ASH6,
        name="EB04-ARISTA_MIMIC_EBB_TEST_FULL_SCALE_WITH_OPEN_R",
        ixia_interface_mimic_ebgp="Ethernet3/1/1",
        ixia_interface_mimic_ibgp="Ethernet3/1/3",
        ixia_interface_mimic_bgp_mon="Ethernet3/1/1",
        bgp_mon_peer_count=0,
        profile=BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R,
        direct_ixia_connections=[
            taac_types.DirectIxiaConnection(
                interface="Ethernet3/1/1",  # EBGP interface
                ixia_chassis_ip=EB04_LAB_ASH6.ixia_chassis_ip,
                ixia_port="6/7",
            ),
            taac_types.DirectIxiaConnection(
                interface="Ethernet3/1/3",  # IBGP interface
                ixia_chassis_ip=EB04_LAB_ASH6.ixia_chassis_ip,
                ixia_port="6/8",
            ),
        ],
    )
)


__all__ = [
    "EB01_ARISTA_MIMIC_EBB_TEST_FULL_SCALE_WITHOUT_OPEN_R_TEST_CONFIG",
    "EB03_ARISTA_MIMIC_EBB_TEST_FULL_SCALE_WITH_OPEN_R_TEST_CONFIG",
    "EB04_ARISTA_MIMIC_EBB_TEST_FULL_SCALE_WITH_OPEN_R_TEST_CONFIG",
]
