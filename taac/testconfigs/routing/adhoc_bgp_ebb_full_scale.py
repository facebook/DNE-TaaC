# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""BGP++ EBB full-scale mimic ad-hoc testconfigs (jsw002.m001.snc1 production EB).

Wave 5E.2 -- migrates the shared/generic mimic-full-scale wrapper
previously living at
``testconfigs/routing/ebb/arista_mimic_ebb_test_full_scale_test_config.py``
into this ad-hoc lifecycle binding module. ``TestConfig.name`` is preserved
verbatim so the golden manifest hash is byte-wise identical.

Wave 5E.4 -- appends 4 FBOSS EBB single-node ``mimic`` full-scale
wrappers previously living at
``testconfigs/routing/ebb/{fsw001_qzb,fsw_qzb,qzd,qzd_fsw002}_single_node_topology_mimic_ebb_test_full_scale*_test_config.py``.
Wrapped via ``factories/bgp_ebb_full_scale_fboss_mimic.py`` since they
call ``test_config_for_bgp_plus_plus_ebb{,_with_bgp_mon}`` (FBOSS COOP
patcher variants) rather than the Arista mimic factory used by 5E.2.

The 3 lab-box siblings (eb01/eb03/eb04) live in
``qual_bgp_ebb_full_scale.py`` since they target ``qual``-usage physical inventories.

External consumers import from this member module directly; see
``docs/routing/TESTCONFIGS.md``.
"""

from taac.abstractions.physical_inventory import (
    FSW001_QZB,
    FSW_QZB,
    JSW002_M001_SNC1,
    QZD_FSW002,
    QZD_LAB,
)
from taac.testconfigs.routing.factories.bgp_ebb_full_scale_fboss_mimic import (
    create_bgp_ebb_full_scale_fboss_test_config,
    create_bgp_ebb_full_scale_fboss_test_config_with_bgp_mon,
)
from taac.testconfigs.routing.factories.bgp_ebb_full_scale_mimic import (
    create_bgp_ebb_full_scale_mimic_test_config,
)
from taac.test_as_a_config import types as taac_types


# ─── ARISTA_MIMIC_EBB_TEST_FULL_SCALE (prod jsw002 EB, no Open/R) ─────────
# Legacy source declared no ``host_driver_args`` / ``oss_mock_device_data``
# / ``direct_ixia_connections`` / ``profile`` override (the underlying
# factory then defaults ``profile`` to ``BGP_PLUS_PLUS_WITHOUT_OPEN_R``).
# ``JSW002_M001_SNC1`` intentionally has an empty ``ixia_chassis_ip`` +
# no ``ixia_ports`` -- topology is discovered at runtime for this prod
# physical_inventory -- so the mimic interface names come from ``physical_inventory.extras``.
ARISTA_MIMIC_EBB_TEST_FULL_SCALE_TEST_CONFIG = (
    create_bgp_ebb_full_scale_mimic_test_config(
        JSW002_M001_SNC1,
        name="ARISTA_MIMIC_EBB_TEST_FULL_SCALE",
        ixia_interface_mimic_ebgp=JSW002_M001_SNC1.extras["dut_iface_ebgp"],
        ixia_interface_mimic_ibgp=JSW002_M001_SNC1.extras["dut_iface_ibgp"],
        ixia_interface_mimic_bgp_mon=JSW002_M001_SNC1.extras["dut_iface_bgp_mon"],
    )
)


# ─── FSW001_QZB_..._MON — FBOSS QZB with BGP MON + direct IXIA links ──────
# Legacy source hardcoded a 3-port direct-ixia connection list against the
# ASH6 chassis, with a typo (``Ethernet/1/1`` missing the port-group ``7``
# on the first entry). Preserved verbatim for byte-identity.
FSW001_QZB_SINGLE_NODE_TOPOLOGY_MIMIC_EBB_TEST_FULL_SCALE_MON_TEST_CONFIG = (
    create_bgp_ebb_full_scale_fboss_test_config_with_bgp_mon(
        FSW001_QZB,
        name="FSW001_QZB_SINGLE_NODE_TOPOLOGY_MIMIC_EBB_TEST_FULL_SCALE_MON",
        ixia_interface_mimic_ebgp="eth7/1/1",
        ixia_interface_mimic_ibgp="eth7/3/1",
        ixia_interface_mimic_bgp_mon="eth7/5/1",
        direct_ixia_connections=[
            taac_types.DirectIxiaConnection(
                interface="Ethernet/1/1",  # EBGP interface
                ixia_chassis_ip="2401:db00:2066:303b::3001",
                ixia_port="1/7",
            ),
            taac_types.DirectIxiaConnection(
                interface="Ethernet7/3/1",  # IBGP interface
                ixia_chassis_ip="2401:db00:2066:303b::3001",
                ixia_port="1/8",
            ),
            taac_types.DirectIxiaConnection(
                interface="Ethernet7/5/1",  # IBGP interface
                ixia_chassis_ip="2401:db00:2066:303b::3001",
                ixia_port="4/3",
            ),
        ],
    )
)


# ─── FSW_QZB — FBOSS QZB, no BGP MON, no direct IXIA links ────────────────
FSW_QZB_SINGLE_NODE_TOPOLOGY_MIMIC_EBB_TEST_FULL_SCALE_TEST_CONFIG = (
    create_bgp_ebb_full_scale_fboss_test_config(
        FSW_QZB,
        name="FSW_QZB_SINGLE_NODE_TOPOLOGY_MIMIC_EBB_TEST_FULL_SCALE",
        ixia_interface_mimic_ebgp=FSW_QZB.extras["dut_iface_ebgp"],
        ixia_interface_mimic_ibgp=FSW_QZB.extras["dut_iface_ibgp"],
    )
)


# ─── QZD_FSW002 — FBOSS FSW002, with BGP MON, no direct IXIA links ───────
QZD_SINGLE_NODE_TOPOLOGY_MIMIC_EBB_TEST_FULL_SCALE_FSW002_TEST_CONFIG = (
    create_bgp_ebb_full_scale_fboss_test_config_with_bgp_mon(
        QZD_FSW002,
        name="QZD_SINGLE_NODE_TOPOLOGY_MIMIC_EBB_TEST_FULL_SCALE_FSW002",
        ixia_interface_mimic_ebgp=QZD_FSW002.extras["dut_iface_ebgp"],
        ixia_interface_mimic_ibgp=QZD_FSW002.extras["dut_iface_ibgp"],
        ixia_interface_mimic_bgp_mon=QZD_FSW002.extras["dut_iface_bgp_mon"],
    )
)


# ─── QZD_LAB — FBOSS FSW003, no BGP MON, PROPAGATE_FSW_{SSW,RSW}_* policy ─
# Legacy source uses a distinct 4-policy naming scheme
# (PROPAGATE_FSW_SSW_IN/OUT for eBGP, PROPAGATE_FSW_RSW_IN/OUT for iBGP)
# instead of the shared ``EB-FA-*``/``EB-EB-*`` names. Overridden here.
QZD_SINGLE_NODE_TOPOLOGY_MIMIC_EBB_TEST_FULL_SCALE_TEST_CONFIG = (
    create_bgp_ebb_full_scale_fboss_test_config(
        QZD_LAB,
        name="QZD_SINGLE_NODE_TOPOLOGY_MIMIC_EBB_TEST_FULL_SCALE",
        ixia_interface_mimic_ebgp=QZD_LAB.extras["dut_iface_ebgp"],
        ixia_interface_mimic_ibgp=QZD_LAB.extras["dut_iface_ibgp"],
        ebgp_ingress_policy_name="PROPAGATE_FSW_SSW_IN",
        ebgp_egress_policy_name="PROPAGATE_FSW_SSW_OUT",
        ibgp_ingress_policy_name="PROPAGATE_FSW_RSW_IN",
        ibgp_egress_policy_name="PROPAGATE_FSW_RSW_OUT",
    )
)


__all__ = [
    "ARISTA_MIMIC_EBB_TEST_FULL_SCALE_TEST_CONFIG",
    "FSW001_QZB_SINGLE_NODE_TOPOLOGY_MIMIC_EBB_TEST_FULL_SCALE_MON_TEST_CONFIG",
    "FSW_QZB_SINGLE_NODE_TOPOLOGY_MIMIC_EBB_TEST_FULL_SCALE_TEST_CONFIG",
    "QZD_SINGLE_NODE_TOPOLOGY_MIMIC_EBB_TEST_FULL_SCALE_FSW002_TEST_CONFIG",
    "QZD_SINGLE_NODE_TOPOLOGY_MIMIC_EBB_TEST_FULL_SCALE_TEST_CONFIG",
]
