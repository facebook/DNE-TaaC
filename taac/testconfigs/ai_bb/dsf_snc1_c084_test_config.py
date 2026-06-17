# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""SNC1 C084 DSF FR4 lite-optics TestConfig.

Builds the `TEST_SNC1_C084_DSF_FR4_LITE_OPTICS` TestConfig for the AI BB
SNC1 C084/C085 DSF testbed exercising FR4 lite-optics behavior. Wires up
a fixed set of IXIA ports and assembles a broad disruption playbook
profile (FBOSS SW/HW agent restart/crash, FSDB crash/restart, QSFP
restart/crash, BGPD restart/crash, agent warmboot/coldboot, device
reboot/drain, interface drain/flap, DSF endurance/longevity) using the
centralized playbook definitions from `playbooks.playbook_definitions`.
"""

from ixia.ixia import types as ixia_types
from taac.packet_headers import DEFAULT_IPV6_HEADER
from taac.playbooks.playbook_definitions import (
    _add_tc_checks_to_playbook,
    ATTRIBUTE_FILTERS_FDSW,
    DSF_C084_TEST_DEVICE_DRAIN_PLAYBOOK as TEST_DEVICE_DRAIN_PLAYBOOK,
    DSF_C084_TEST_FBOSS_HW_AGENT_0_CRASH_PLAYBOOK as TEST_FBOSS_HW_AGENT_0_CRASH_PLAYBOOK,
    DSF_C084_TEST_FSDB_CRASH_PLAYBOOK as TEST_FSDB_CRASH_PLAYBOOK,
    DSF_C084_TEST_INTERFACE_DRAIN_PLAYBOOK as TEST_INTERFACE_DRAIN_PLAYBOOK,
    DSF_TEST_AGENT_COLDBOOT_PLAYBOOK,
    DSF_TEST_AGENT_CRASH_PLAYBOOK,
    DSF_TEST_BGPD_CRASH_PLAYBOOK,
    DSF_TEST_BGPD_RESTART_PLAYBOOK,
    DSF_TEST_CONTINUOUS_AGENT_COLDBOOT_PLAYBOOK,
    DSF_TEST_CONTINUOUS_QSPF_RESTART_PLAYBOOK,
    DSF_TEST_DEVICE_REBOOT_PLAYBOOK,
    DSF_TEST_FBOSS_SW_AGENT_AND_HW_AGENT_0_RESTART_PLAYBOOK,
    DSF_TEST_FBOSS_SW_AGENT_CRASH_PLAYBOOK,
    DSF_TEST_FBOSS_SW_AGENT_WARMBOOT_PLAYBOOK,
    gen_dsf_endurance_playbook,
    gen_dsf_longevity_playbook,
    TEST_AGENT_WARMBOOT_AND_FSDB_RESTART_PLAYBOOK,
    TEST_AGENT_WARMBOOT_PLAYBOOK,
    TEST_CONTINUOUS_AGENT_WARMBOOT_AND_FSDB_RESTART_PLAYBOOK,
    TEST_CONTINUOUS_AGENT_WARMBOOT_PLAYBOOK,
    TEST_CONTINUOUS_FSDB_RESTART_PLAYBOOK,
    TEST_DEVICE_REBOOT_WITHOUT_DRAIN_CHECK_PLAYBOOK,
    TEST_FBOSS_HW_AGENT_0_RESTART_PLAYBOOK,
    TEST_FBOSS_HW_AGENT_1_CRASH_PLAYBOOK,
    TEST_FBOSS_HW_AGENT_1_RESTART_PLAYBOOK,
    TEST_FBOSS_SW_AGENT_AND_HW_AGENT_1_RESTART_PLAYBOOK,
    TEST_FSDB_RESTART_PLAYBOOK,
    TEST_INTERFACE_FLAP_PLAYBOOK,
    TEST_QSFP_CRASH_PLAYBOOK,
    TEST_QSPF_RESTART_PLAYBOOK,
)
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import TestConfig

SNC1_C084_C085_IXIA_PORTS = [
    "eth1/11/1",
    "eth1/12/1",
    "eth1/13/1",
    "eth1/15/1",
    "eth1/16/1",
    "eth1/17/1",
    "eth1/21/1",
    "eth1/22/1",
    "eth1/23/1",
    "eth1/25/1",
    "eth1/26/1",
    # "eth1/27/1",
]

SNC1_C084_C085_EXCLUDED_IXIA_PORTS = ["eth1/27/1"]

SNC1_C084_ENDPOINTS = [
    taac_types.Endpoint(
        name="fdsw001.n000.c084.snc1",
        dut=True,
    ),
    taac_types.Endpoint(
        name="rdsw001.u001.c084.snc1",
        dut=True,
        ixia_needed=True,
        ixia_ports=SNC1_C084_C085_IXIA_PORTS,
        exclude_ixia_ports=SNC1_C084_C085_EXCLUDED_IXIA_PORTS,
    ),
    taac_types.Endpoint(
        name="rdsw003.u001.c084.snc1",
        dut=True,
        ixia_needed=True,
        ixia_ports=SNC1_C084_C085_IXIA_PORTS,
        exclude_ixia_ports=SNC1_C084_C085_EXCLUDED_IXIA_PORTS,
    ),
    taac_types.Endpoint(
        name="rdsw004.u001.c084.snc1",
        dut=True,
        ixia_needed=True,
        ixia_ports=SNC1_C084_C085_IXIA_PORTS,
        exclude_ixia_ports=SNC1_C084_C085_EXCLUDED_IXIA_PORTS,
    ),
    taac_types.Endpoint(
        name="rdsw005.u001.c084.snc1",
        dut=True,
        ixia_needed=True,
        ixia_ports=SNC1_C084_C085_IXIA_PORTS,
        exclude_ixia_ports=SNC1_C084_C085_EXCLUDED_IXIA_PORTS,
    ),
    taac_types.Endpoint(
        name="rdsw006.u001.c084.snc1",
        dut=True,
        ixia_needed=True,
        ixia_ports=SNC1_C084_C085_IXIA_PORTS,
        exclude_ixia_ports=SNC1_C084_C085_EXCLUDED_IXIA_PORTS,
    ),
]


SNC1_C084_TRAFFIC_ENDPOINTS = [
    taac_types.TrafficEndpoint(name="rdsw001.u001.c084.snc1:eth1/11/1"),
    taac_types.TrafficEndpoint(name="rdsw001.u001.c084.snc1:eth1/12/1"),
    taac_types.TrafficEndpoint(name="rdsw001.u001.c084.snc1:eth1/13/1"),
    taac_types.TrafficEndpoint(name="rdsw001.u001.c084.snc1:eth1/15/1"),
    taac_types.TrafficEndpoint(name="rdsw001.u001.c084.snc1:eth1/16/1"),
    taac_types.TrafficEndpoint(name="rdsw001.u001.c084.snc1:eth1/17/1"),
    taac_types.TrafficEndpoint(name="rdsw001.u001.c084.snc1:eth1/21/1"),
    taac_types.TrafficEndpoint(name="rdsw001.u001.c084.snc1:eth1/22/1"),
    taac_types.TrafficEndpoint(name="rdsw001.u001.c084.snc1:eth1/23/1"),
    taac_types.TrafficEndpoint(name="rdsw001.u001.c084.snc1:eth1/25/1"),
    taac_types.TrafficEndpoint(name="rdsw001.u001.c084.snc1:eth1/26/1"),
    # taac_types.TrafficEndpoint(name="rdsw001.u001.c084.snc1:eth1/27/1"),
    taac_types.TrafficEndpoint(name="rdsw003.u001.c084.snc1:eth1/11/1"),
    taac_types.TrafficEndpoint(name="rdsw003.u001.c084.snc1:eth1/12/1"),
    taac_types.TrafficEndpoint(name="rdsw003.u001.c084.snc1:eth1/13/1"),
    taac_types.TrafficEndpoint(name="rdsw003.u001.c084.snc1:eth1/15/1"),
    taac_types.TrafficEndpoint(name="rdsw003.u001.c084.snc1:eth1/16/1"),
    taac_types.TrafficEndpoint(name="rdsw003.u001.c084.snc1:eth1/17/1"),
    taac_types.TrafficEndpoint(name="rdsw003.u001.c084.snc1:eth1/21/1"),
    taac_types.TrafficEndpoint(name="rdsw003.u001.c084.snc1:eth1/22/1"),
    taac_types.TrafficEndpoint(name="rdsw003.u001.c084.snc1:eth1/23/1"),
    taac_types.TrafficEndpoint(name="rdsw003.u001.c084.snc1:eth1/25/1"),
    taac_types.TrafficEndpoint(name="rdsw003.u001.c084.snc1:eth1/26/1"),
    # taac_types.TrafficEndpoint(name="rdsw003.u001.c084.snc1:eth1/27/1"),
    taac_types.TrafficEndpoint(name="rdsw004.u001.c084.snc1:eth1/11/1"),
    taac_types.TrafficEndpoint(name="rdsw004.u001.c084.snc1:eth1/12/1"),
    taac_types.TrafficEndpoint(name="rdsw004.u001.c084.snc1:eth1/13/1"),
    taac_types.TrafficEndpoint(name="rdsw004.u001.c084.snc1:eth1/15/1"),
    taac_types.TrafficEndpoint(name="rdsw004.u001.c084.snc1:eth1/16/1"),
    taac_types.TrafficEndpoint(name="rdsw004.u001.c084.snc1:eth1/17/1"),
    taac_types.TrafficEndpoint(name="rdsw004.u001.c084.snc1:eth1/21/1"),
    taac_types.TrafficEndpoint(name="rdsw004.u001.c084.snc1:eth1/22/1"),
    taac_types.TrafficEndpoint(name="rdsw004.u001.c084.snc1:eth1/23/1"),
    taac_types.TrafficEndpoint(name="rdsw004.u001.c084.snc1:eth1/25/1"),
    taac_types.TrafficEndpoint(name="rdsw004.u001.c084.snc1:eth1/26/1"),
    # taac_types.TrafficEndpoint(name="rdsw004.u001.c084.snc1:eth1/27/1"),
    taac_types.TrafficEndpoint(name="rdsw005.u001.c084.snc1:eth1/11/1"),
    taac_types.TrafficEndpoint(name="rdsw005.u001.c084.snc1:eth1/12/1"),
    taac_types.TrafficEndpoint(name="rdsw005.u001.c084.snc1:eth1/13/1"),
    taac_types.TrafficEndpoint(name="rdsw005.u001.c084.snc1:eth1/15/1"),
    taac_types.TrafficEndpoint(name="rdsw005.u001.c084.snc1:eth1/16/1"),
    taac_types.TrafficEndpoint(name="rdsw005.u001.c084.snc1:eth1/17/1"),
    taac_types.TrafficEndpoint(name="rdsw005.u001.c084.snc1:eth1/21/1"),
    taac_types.TrafficEndpoint(name="rdsw005.u001.c084.snc1:eth1/22/1"),
    taac_types.TrafficEndpoint(name="rdsw005.u001.c084.snc1:eth1/23/1"),
    taac_types.TrafficEndpoint(name="rdsw005.u001.c084.snc1:eth1/25/1"),
    taac_types.TrafficEndpoint(name="rdsw005.u001.c084.snc1:eth1/26/1"),
    # taac_types.TrafficEndpoint(name="rdsw005.u001.c084.snc1:eth1/27/1"),
    taac_types.TrafficEndpoint(name="rdsw006.u001.c084.snc1:eth1/11/1"),
    taac_types.TrafficEndpoint(name="rdsw006.u001.c084.snc1:eth1/12/1"),
    taac_types.TrafficEndpoint(name="rdsw006.u001.c084.snc1:eth1/13/1"),
    taac_types.TrafficEndpoint(name="rdsw006.u001.c084.snc1:eth1/15/1"),
    taac_types.TrafficEndpoint(name="rdsw006.u001.c084.snc1:eth1/16/1"),
    taac_types.TrafficEndpoint(name="rdsw006.u001.c084.snc1:eth1/17/1"),
    taac_types.TrafficEndpoint(name="rdsw006.u001.c084.snc1:eth1/21/1"),
    taac_types.TrafficEndpoint(name="rdsw006.u001.c084.snc1:eth1/22/1"),
    taac_types.TrafficEndpoint(name="rdsw006.u001.c084.snc1:eth1/23/1"),
    taac_types.TrafficEndpoint(name="rdsw006.u001.c084.snc1:eth1/25/1"),
    taac_types.TrafficEndpoint(name="rdsw006.u001.c084.snc1:eth1/26/1"),
    # taac_types.TrafficEndpoint(name="rdsw006.u001.c084.snc1:eth1/27/1"),
]

PLAYBOOKS_SNC1_C084_DSF_FR4_LITE_OPTICS = [
    gen_dsf_longevity_playbook("test_one_min_longevity", 60, ATTRIBUTE_FILTERS_FDSW),
    gen_dsf_longevity_playbook("test_ten_min_longevity", 600, ATTRIBUTE_FILTERS_FDSW),
    gen_dsf_longevity_playbook("test_one_hour_longevity", 3600, ATTRIBUTE_FILTERS_FDSW),
    gen_dsf_longevity_playbook(
        "test_one_day_longevity", 3600 * 24, ATTRIBUTE_FILTERS_FDSW
    ),
    TEST_AGENT_WARMBOOT_PLAYBOOK,
    TEST_CONTINUOUS_AGENT_WARMBOOT_PLAYBOOK,
    DSF_TEST_AGENT_COLDBOOT_PLAYBOOK,
    DSF_TEST_CONTINUOUS_AGENT_COLDBOOT_PLAYBOOK,
    TEST_AGENT_WARMBOOT_AND_FSDB_RESTART_PLAYBOOK,
    TEST_CONTINUOUS_AGENT_WARMBOOT_AND_FSDB_RESTART_PLAYBOOK,
    TEST_QSPF_RESTART_PLAYBOOK,
    DSF_TEST_CONTINUOUS_QSPF_RESTART_PLAYBOOK,
    TEST_FSDB_RESTART_PLAYBOOK,
    TEST_CONTINUOUS_FSDB_RESTART_PLAYBOOK,
    DSF_TEST_BGPD_RESTART_PLAYBOOK,
    TEST_FBOSS_HW_AGENT_0_RESTART_PLAYBOOK,
    TEST_FBOSS_HW_AGENT_1_RESTART_PLAYBOOK,
    DSF_TEST_FBOSS_SW_AGENT_WARMBOOT_PLAYBOOK,
    DSF_TEST_FBOSS_SW_AGENT_AND_HW_AGENT_0_RESTART_PLAYBOOK,
    TEST_FBOSS_SW_AGENT_AND_HW_AGENT_1_RESTART_PLAYBOOK,
    DSF_TEST_DEVICE_REBOOT_PLAYBOOK,
    DSF_TEST_AGENT_CRASH_PLAYBOOK,
    TEST_QSFP_CRASH_PLAYBOOK,
    DSF_TEST_BGPD_CRASH_PLAYBOOK,
    TEST_FSDB_CRASH_PLAYBOOK,
    DSF_TEST_FBOSS_SW_AGENT_CRASH_PLAYBOOK,
    TEST_FBOSS_HW_AGENT_0_CRASH_PLAYBOOK,
    TEST_FBOSS_HW_AGENT_1_CRASH_PLAYBOOK,
    TEST_INTERFACE_FLAP_PLAYBOOK,
    TEST_DEVICE_DRAIN_PLAYBOOK,
    TEST_INTERFACE_DRAIN_PLAYBOOK,
    TEST_DEVICE_REBOOT_WITHOUT_DRAIN_CHECK_PLAYBOOK,
]

TEST_SNC1_C084_DSF_FR4_LITE_OPTICS = TestConfig(
    name="TEST_SNC1_C084_DSF_FR4_LITE_OPTICS",
    basset_pool="fboss",
    endpoints=SNC1_C084_ENDPOINTS,
    basic_traffic_item_configs=[
        taac_types.BasicTrafficItemConfig(
            src_endpoints=SNC1_C084_TRAFFIC_ENDPOINTS,
            dest_endpoints=SNC1_C084_TRAFFIC_ENDPOINTS,
            src_dest_mesh=ixia_types.SrcDestMeshType.FULL_MESH,
            full_mesh=False,
            merge_destinations=True,
            name="DSF_FR4_LITE_IMIX",
            line_rate_type=ixia_types.RateType.PERCENT_LINE_RATE,
            line_rate=98,
            traffic_type=ixia_types.TrafficType.IPV6,
            bidirectional=True,
            packet_headers=DEFAULT_IPV6_HEADER,
            frame_size_settings=ixia_types.FrameSize(
                type=ixia_types.FrameSizeType.CUSTOM_IMIX,
                imix_weight={94: 1, 96: 18, 192: 3, 512: 1, 1200: 1, 4600: 76},
            ),
        ),
    ],
    playbooks=[
        # Specify the number of iterations required for the endurance testing (e.g., 100) rather than the default below
        _add_tc_checks_to_playbook(
            p if "longevity" in p.name else gen_dsf_endurance_playbook(p, 1)
        )
        for p in PLAYBOOKS_SNC1_C084_DSF_FR4_LITE_OPTICS
    ],
)
