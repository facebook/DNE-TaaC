# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""CI/CD Thrift-hardening and reboot coverage for a NetOS Wedge400C RSW."""

from ixia.ixia import types as ixia_types
from taac.testconfigs.npi.bgp_reboot_test_config import (
    create_npi_bgp_reboot_test_config,
)
from taac.testconfigs.npi.npi_cicd_constants import (
    is_npi_cicd_dut,
    NPI_CICD_REBOOT_ITERATIONS,
    NPI_CICD_THRIFT_DURATION_S,
    NPI_CICD_THRIFT_REQUESTS_PER_BURST,
    NPI_CICD_THRIFT_RESTART_DURATION_S,
    NPI_CICD_THRIFT_RESTART_PERIOD_S,
)
from taac.testconfigs.npi.thrift_hardening_test_config import (
    create_npi_device_only_thrift_hardening_test_config,
)


RSW001_P001_F01_QZD1 = "rsw001.p001.f01.qzd1"

assert is_npi_cicd_dut(RSW001_P001_F01_QZD1)


RSW001_P001_F01_QZD1_THRIFT_HARDENING_TEST_CONFIG = (
    create_npi_device_only_thrift_hardening_test_config(
        test_config_name="RSW001_P001_F01_QZD1_THRIFT_HARDENING_TEST_CONFIG",
        device_name=RSW001_P001_F01_QZD1,
        test_duration_s=NPI_CICD_THRIFT_DURATION_S,
        restart_test_duration_s=NPI_CICD_THRIFT_RESTART_DURATION_S,
        restart_period_s=NPI_CICD_THRIFT_RESTART_PERIOD_S,
        requests_per_burst=NPI_CICD_THRIFT_REQUESTS_PER_BURST,
        include_kitchen_sink=True,
        basset_pool="dne.regression",
        expected_established_bgp_sessions=6,
        service_restart_services=[
            "bgpd",
            "fboss_hw_agent@0",
            "fboss_sw_agent",
            "fsdb",
            "qsfp_service",
            "wedge_agent",
        ],
    )
)


RSW001_P001_F01_QZD1_SYSTEM_REBOOT_TEST_CONFIG = create_npi_bgp_reboot_test_config(
    test_config_name="RSW001_P001_F01_QZD1_SYSTEM_REBOOT_TEST_CONFIG",
    device_name=RSW001_P001_F01_QZD1,
    device_role="RSW",
    basset_pool="dne.regression",
    ixia_source_interface="eth1/17/1",
    ixia_destination_interface="eth1/18/1",
    source_dut_ip_v6="2401:db00:501c::10",
    destination_dut_ip_v6="2401:db00:e50d:11:18::10",
    source_ixia_ip_v6="2401:db00:501c::11",
    destination_ixia_ip_v6="2401:db00:e50d:11:18::11",
    peer_prefix_length=127,
    source_advertised_prefix_v6="5000:17::",
    destination_advertised_prefix_v6="5000:18::",
    source_remote_as=65000,
    destination_remote_as=6016,
    source_vlan_id=2000,
    destination_vlan_id=4016,
    device_group_multiplier=20,
    line_rate=10,
    frame_size_settings=ixia_types.FrameSize(
        type=ixia_types.FrameSizeType.CUSTOM_IMIX,
        imix_weight={100: 1, 1500: 4, 4500: 5, 7000: 1, 9000: 1},
    ),
    iteration=NPI_CICD_REBOOT_ITERATIONS,
)


RSW001_P001_F01_QZD1_TEST_CONFIGS = [
    RSW001_P001_F01_QZD1_THRIFT_HARDENING_TEST_CONFIG,
    RSW001_P001_F01_QZD1_SYSTEM_REBOOT_TEST_CONFIG,
]


__all__ = [
    "RSW001_P001_F01_QZD1_SYSTEM_REBOOT_TEST_CONFIG",
    "RSW001_P001_F01_QZD1_TEST_CONFIGS",
    "RSW001_P001_F01_QZD1_THRIFT_HARDENING_TEST_CONFIG",
]
