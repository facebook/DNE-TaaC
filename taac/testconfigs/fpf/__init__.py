# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

from taac.testconfigs.fpf.fpf_gar_class_a import (
    TEST_CONFIG as FPF_GAR_CLASS_A,
)
from taac.testconfigs.fpf.fpf_gar_class_b_c import (
    TEST_CONFIG as FPF_GAR_CLASS_B_C,
)
from taac.testconfigs.fpf.fpf_gar_class_d import (
    TEST_CONFIG as FPF_GAR_CLASS_D,
)
from taac.testconfigs.fpf.fpf_shared_injection_suite import (
    TEST_CONFIG as FPF_SHARED_INJECTION_SUITE,
)
from taac.testconfigs.fpf.fpf_stress_test_config import (
    TEST_CONFIG as FPF_STRESS_TEST_CONFIG,
)
from taac.testconfigs.fpf.fpf_tc04_wedge_agent_warmboot import (
    TEST_CONFIG as FPF_TC04_WEDGE_AGENT_WARMBOOT,
)
from taac.testconfigs.fpf.fpf_tc05_bgp_gr_within_window import (
    TEST_CONFIG as FPF_TC05_BGP_GR_WITHIN_WINDOW,
)
from taac.testconfigs.fpf.fpf_tc06_bgp_gr_beyond_window import (
    TEST_CONFIG as FPF_TC06_BGP_GR_BEYOND_WINDOW,
)
from taac.testconfigs.fpf.fpf_tc07_fsdb_gr_within_window import (
    TEST_CONFIG as FPF_TC07_FSDB_GR_WITHIN_WINDOW,
)
from taac.testconfigs.fpf.fpf_tc08_fsdb_gr_beyond_window import (
    TEST_CONFIG as FPF_TC08_FSDB_GR_BEYOND_WINDOW,
)
from taac.testconfigs.fpf.fpf_tc15_interface_disable import (
    TEST_CONFIG as FPF_TC15_INTERFACE_DISABLE,
)
from taac.testconfigs.fpf.fpf_tc16_interface_enable import (
    TEST_CONFIG as FPF_TC16_INTERFACE_ENABLE,
)
from taac.testconfigs.fpf.fpf_tc17_link_drain import (
    TEST_CONFIG as FPF_TC17_LINK_DRAIN,
)
from taac.testconfigs.fpf.fpf_tc19_device_drain import (
    TEST_CONFIG as FPF_TC19_DEVICE_DRAIN,
)
from taac.testconfigs.fpf.fpf_tc21_prod_prefix_drain_link import (
    TEST_CONFIG as FPF_TC21_PROD_PREFIX_DRAIN_LINK,
)
from taac.testconfigs.fpf.fpf_tc22_prod_prefix_drain_device import (
    TEST_CONFIG as FPF_TC22_PROD_PREFIX_DRAIN_DEVICE,
)
from taac.testconfigs.fpf.fpf_tc23_bgp_restart import (
    TEST_CONFIG as FPF_TC23_BGP_RESTART,
)
from taac.testconfigs.fpf.fpf_tc24_fsdb_restart import (
    TEST_CONFIG as FPF_TC24_FSDB_RESTART,
)
from taac.testconfigs.fpf.fpf_tc25_wedge_agent_restart import (
    TEST_CONFIG as FPF_TC25_WEDGE_AGENT_RESTART,
)
from taac.testconfigs.fpf.fpf_tc26_qsfp_service_restart import (
    TEST_CONFIG as FPF_TC26_QSFP_SERVICE_RESTART,
)
from taac.testconfigs.fpf.fpf_tc27_agent_coldboot import (
    TEST_CONFIG as FPF_TC27_AGENT_COLDBOOT,
)
from taac.testconfigs.fpf.fpf_tc28_fsdb_kill import (
    TEST_CONFIG as FPF_TC28_FSDB_KILL,
)
from taac.testconfigs.fpf.fpf_tc29_fsdb_gr_stop30_reenable import (
    TEST_CONFIG as FPF_TC29_FSDB_GR_STOP30_REENABLE,
)
from taac.testconfigs.fpf.fpf_tc30_fsdb_gr_stop180_no_reenable import (
    TEST_CONFIG as FPF_TC30_FSDB_GR_STOP180_NO_REENABLE,
)
from taac.testconfigs.fpf.fpf_tc31_fsdb_enable_recover import (
    TEST_CONFIG as FPF_TC31_FSDB_ENABLE_RECOVER,
)
from taac.testconfigs.fpf.fpf_tc32_downlink_flaps import (
    TEST_CONFIG as FPF_TC32_DOWNLINK_FLAPS,
)
from taac.testconfigs.fpf.fpf_tc33_gtsw_stsw_links_down import (
    TEST_CONFIG as FPF_TC33_GTSW_STSW_LINKS_DOWN,
)
from taac.testconfigs.fpf.fpf_tc35_stsw_undrain_reinject import (
    TEST_CONFIG as FPF_TC35_STSW_UNDRAIN_REINJECT,
)
from taac.testconfigs.fpf.fpf_tc36_stsw_all_connections_down import (
    TEST_CONFIG as FPF_TC36_STSW_ALL_CONNECTIONS_DOWN,
)
from taac.testconfigs.fpf.fpf_tc37_nic_side_link_flap import (
    TEST_CONFIG as FPF_TC37_NIC_SIDE_LINK_FLAP,
)
from taac.testconfigs.fpf.fpf_tc38_persistent_ndp_clear import (
    TEST_CONFIG as FPF_TC38_PERSISTENT_NDP_CLEAR,
)
from taac.testconfigs.fpf.fpf_tc39_fsdb_kill_5min import (
    TEST_CONFIG as FPF_TC39_FSDB_KILL_5MIN,
)
from taac.testconfigs.fpf.fpf_tc40_cont_interface_flaps import (
    TEST_CONFIG as FPF_TC40_CONT_INTERFACE_FLAPS,
)
from taac.testconfigs.fpf.fpf_tc41_longevity_pristine import (
    TEST_CONFIG as FPF_TC41_LONGEVITY_PRISTINE,
)
from taac.testconfigs.fpf.fpf_tc42_cont_flaps_wedge_restart import (
    TEST_CONFIG as FPF_TC42_CONT_FLAPS_WEDGE_RESTART,
)
from taac.testconfigs.fpf.fpf_tc43_cont_flaps_bgp_restart import (
    TEST_CONFIG as FPF_TC43_CONT_FLAPS_BGP_RESTART,
)
from taac.testconfigs.fpf.fpf_tc44_cont_flaps_fsdb_restart import (
    TEST_CONFIG as FPF_TC44_CONT_FLAPS_FSDB_RESTART,
)
from taac.testconfigs.fpf.fpf_tc45_scale_up_4k_8k import (
    TEST_CONFIG as FPF_TC45_SCALE_UP_4K_8K,
)
from taac.testconfigs.fpf.fpf_tc46_scale_down_8k_4k import (
    TEST_CONFIG as FPF_TC46_SCALE_DOWN_8K_4K,
)
from taac.testconfigs.fpf.fpf_tc47_dual_device_drain import (
    TEST_CONFIG as FPF_TC47_DUAL_DEVICE_DRAIN,
)
from taac.testconfigs.fpf.fpf_tc48_dual_device_undrain import (
    TEST_CONFIG as FPF_TC48_DUAL_DEVICE_UNDRAIN,
)
from taac.testconfigs.fpf.fpf_tc49_bgp_kill_5s_10min import (
    TEST_CONFIG as FPF_TC49_BGP_KILL_5S_10MIN,
)
from taac.testconfigs.fpf.fpf_tc50_wedge_agent_kill_5s_10min import (
    TEST_CONFIG as FPF_TC50_WEDGE_AGENT_KILL_5S_10MIN,
)
from taac.testconfigs.fpf.fpf_tc51_fsdb_kill_5s_10min import (
    TEST_CONFIG as FPF_TC51_FSDB_KILL_5S_10MIN,
)
from taac.testconfigs.fpf.fpf_tc52_hrt_restart import (
    TEST_CONFIG as FPF_TC52_HRT_RESTART,
)
from taac.testconfigs.fpf.fpf_tc54_stsw_device_drain import (
    TEST_CONFIG as FPF_TC54_STSW_DEVICE_DRAIN,
)
from taac.testconfigs.fpf.fpf_tc55_gtsw_device_reboot import (
    TEST_CONFIG as FPF_TC55_GTSW_DEVICE_REBOOT,
)

__all__ = [
    "FPF_GAR_CLASS_A",
    "FPF_GAR_CLASS_B_C",
    "FPF_GAR_CLASS_D",
    "FPF_SHARED_INJECTION_SUITE",
    "FPF_STRESS_TEST_CONFIG",
    "FPF_TC04_WEDGE_AGENT_WARMBOOT",
    "FPF_TC05_BGP_GR_WITHIN_WINDOW",
    "FPF_TC06_BGP_GR_BEYOND_WINDOW",
    "FPF_TC07_FSDB_GR_WITHIN_WINDOW",
    "FPF_TC08_FSDB_GR_BEYOND_WINDOW",
    "FPF_TC15_INTERFACE_DISABLE",
    "FPF_TC16_INTERFACE_ENABLE",
    "FPF_TC17_LINK_DRAIN",
    "FPF_TC19_DEVICE_DRAIN",
    "FPF_TC21_PROD_PREFIX_DRAIN_LINK",
    "FPF_TC22_PROD_PREFIX_DRAIN_DEVICE",
    "FPF_TC23_BGP_RESTART",
    "FPF_TC24_FSDB_RESTART",
    "FPF_TC25_WEDGE_AGENT_RESTART",
    "FPF_TC26_QSFP_SERVICE_RESTART",
    "FPF_TC27_AGENT_COLDBOOT",
    "FPF_TC28_FSDB_KILL",
    "FPF_TC29_FSDB_GR_STOP30_REENABLE",
    "FPF_TC30_FSDB_GR_STOP180_NO_REENABLE",
    "FPF_TC31_FSDB_ENABLE_RECOVER",
    "FPF_TC32_DOWNLINK_FLAPS",
    "FPF_TC33_GTSW_STSW_LINKS_DOWN",
    "FPF_TC35_STSW_UNDRAIN_REINJECT",
    "FPF_TC36_STSW_ALL_CONNECTIONS_DOWN",
    "FPF_TC37_NIC_SIDE_LINK_FLAP",
    "FPF_TC38_PERSISTENT_NDP_CLEAR",
    "FPF_TC39_FSDB_KILL_5MIN",
    "FPF_TC40_CONT_INTERFACE_FLAPS",
    "FPF_TC41_LONGEVITY_PRISTINE",
    "FPF_TC42_CONT_FLAPS_WEDGE_RESTART",
    "FPF_TC43_CONT_FLAPS_BGP_RESTART",
    "FPF_TC44_CONT_FLAPS_FSDB_RESTART",
    "FPF_TC45_SCALE_UP_4K_8K",
    "FPF_TC46_SCALE_DOWN_8K_4K",
    "FPF_TC47_DUAL_DEVICE_DRAIN",
    "FPF_TC48_DUAL_DEVICE_UNDRAIN",
    "FPF_TC49_BGP_KILL_5S_10MIN",
    "FPF_TC50_WEDGE_AGENT_KILL_5S_10MIN",
    "FPF_TC51_FSDB_KILL_5S_10MIN",
    "FPF_TC52_HRT_RESTART",
    "FPF_TC54_STSW_DEVICE_DRAIN",
    "FPF_TC55_GTSW_DEVICE_REBOOT",
]
