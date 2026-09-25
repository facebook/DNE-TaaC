# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

"""Physical Open/R port-channel flap under a live BBF-scale injection.

The lifecycle temporarily moves Ethernet3/10/1 from Port-Channel1910 into a
new routed Port-Channel1911 on eb02 and eb04. Port-Channel1910 remains up and
carries the scale-tester connection while Port-Channel1911 is shut and restored
once. Teardown always returns Ethernet3/10/1 to Port-Channel1910 and deletes
Port-Channel1911; the split is not shared testbed state.

Run with ``--skip-testbed-isolation`` so Netcastle does not shut the undeclared
physical members that provide the inband control path.
"""

import typing as t

from taac.abstractions.physical_inventory import (
    EB02_LAB_ASH6,
    EB04_LAB_ASH6,
    PhysicalInventory,
)
from taac.playbooks.routing.openr_scale_playbooks import (
    get_openr_scale_physical_link_flap_playbook,
)
from taac.task_definitions import (
    create_openr_scale_isolation_task,
    create_openr_scale_link_fixture_task,
)
from taac.testconfigs.routing.openr.openr_scale_test_config import (
    EB02_MGMT_ADDRESS,
    EB04_INBAND_ADDRESS,
    EB04_MGMT_ADDRESS,
    SCALE_TESTER_REMOTE_PATH,
)
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import Endpoint, TestConfig


DEFAULT_SPINES: int = 64
DEFAULT_LEAVES: int = 252
DEFAULT_CONTROL_NODES: int = 0
DEFAULT_SITES: int = 20
DEFAULT_ECMP_WIDTH: int = 8
DEFAULT_PREFIXES_PER_NODE: int = 11
DEFAULT_PREFIX_SEED: int = 20250903
DEFAULT_AREA: str = "0"
DEFAULT_DUT_ROLE: t.Literal["leaf", "spine"] = "leaf"
DEFAULT_MEMBER_INTERFACE: str = "Ethernet3/10/1"
DEFAULT_ORIGINAL_PORT_CHANNEL_ID: int = 1910
DEFAULT_TEST_PORT_CHANNEL_ID: int = 1911
DEFAULT_HELPER_TEST_IPV4_CIDR: str = "10.165.28.12/31"
DEFAULT_DUT_TEST_IPV4_CIDR: str = "10.165.28.13/31"
DEFAULT_SCALE_TESTER_LOG_PATH: str = "/mnt/flash/openr_scale_link_flap.log"
DEFAULT_INJECTION_RUN_DURATION_SEC: int = 900
DEFAULT_INJECTION_READY_TIMEOUT_SEC: int = 90


def create_openr_scale_physical_link_flap_test_config(
    name: str = "OPENR_SCALE_PHYSICAL_LINK_FLAP",
    num_spines: int = DEFAULT_SPINES,
    num_leaves: int = DEFAULT_LEAVES,
    num_control_nodes: int = DEFAULT_CONTROL_NODES,
    num_sites: int = DEFAULT_SITES,
    ecmp_width: int = DEFAULT_ECMP_WIDTH,
    prefixes_per_node: int = DEFAULT_PREFIXES_PER_NODE,
    prefix_seed: int = DEFAULT_PREFIX_SEED,
    area: str = DEFAULT_AREA,
    dut_role: t.Literal["leaf", "spine"] = DEFAULT_DUT_ROLE,
    dut_inventory: PhysicalInventory = EB04_LAB_ASH6,
    helper_inventory: PhysicalInventory = EB02_LAB_ASH6,
    dut_inband_address: str = EB04_INBAND_ADDRESS,
    dut_mgmt_addresses: t.Optional[t.List[str]] = None,
    scale_tester_remote_path: str = SCALE_TESTER_REMOTE_PATH,
    scale_tester_log_path: str = DEFAULT_SCALE_TESTER_LOG_PATH,
    member_interface: str = DEFAULT_MEMBER_INTERFACE,
    original_port_channel_id: int = DEFAULT_ORIGINAL_PORT_CHANNEL_ID,
    test_port_channel_id: int = DEFAULT_TEST_PORT_CHANNEL_ID,
    helper_test_ipv4_cidr: str = DEFAULT_HELPER_TEST_IPV4_CIDR,
    dut_test_ipv4_cidr: str = DEFAULT_DUT_TEST_IPV4_CIDR,
    injection_run_duration_sec: int = DEFAULT_INJECTION_RUN_DURATION_SEC,
    injection_ready_timeout_sec: int = DEFAULT_INJECTION_READY_TIMEOUT_SEC,
) -> TestConfig:
    """Create Test 4 with a test-scoped second routed port-channel."""
    dut_name = dut_inventory.device_name
    helper_name = helper_inventory.device_name
    fixture_addresses = {
        helper_name: helper_test_ipv4_cidr,
        dut_name: dut_test_ipv4_cidr,
    }
    isolation_task = create_openr_scale_isolation_task(
        hosts=[dut_name, helper_name],
        helper_hostname=helper_name,
        scale_tester_remote_path=scale_tester_remote_path,
        area=area,
    )
    fixture_setup = create_openr_scale_link_fixture_task(
        action="setup",
        ipv4_cidrs_by_device=fixture_addresses,
        member_interface=member_interface,
        original_port_channel_id=original_port_channel_id,
        test_port_channel_id=test_port_channel_id,
    )
    fixture_cleanup = create_openr_scale_link_fixture_task(
        action="cleanup",
        ipv4_cidrs_by_device=fixture_addresses,
        member_interface=member_interface,
        original_port_channel_id=original_port_channel_id,
        test_port_channel_id=test_port_channel_id,
    )

    return TestConfig(
        name=name,
        basset_pool="dne.test",
        endpoints=[
            Endpoint(name=dut_name, dut=True),
            Endpoint(name=helper_name, dut=False),
        ],
        host_os_type_map={
            dut_name: taac_types.DeviceOsType.ARISTA_OS,
            helper_name: taac_types.DeviceOsType.ARISTA_OS,
        },
        startup_checks=[],
        host_driver_args={
            **(dut_inventory.host_driver_args or {}),
            **(helper_inventory.host_driver_args or {}),
        },
        oss_mock_device_data={
            **(dut_inventory.oss_mock_device_data or {}),
            **(helper_inventory.oss_mock_device_data or {}),
        },
        setup_tasks=[isolation_task, fixture_setup],
        teardown_tasks=[fixture_cleanup, isolation_task],
        playbooks=[
            get_openr_scale_physical_link_flap_playbook(
                helper_name=helper_name,
                dut_name=dut_name,
                dut_inband_address=dut_inband_address,
                dut_mgmt_addresses=(
                    dut_mgmt_addresses
                    if dut_mgmt_addresses is not None
                    else [EB04_MGMT_ADDRESS, EB02_MGMT_ADDRESS]
                ),
                num_spines=num_spines,
                num_leaves=num_leaves,
                num_control_nodes=num_control_nodes,
                num_sites=num_sites,
                ecmp_width=ecmp_width,
                prefixes_per_node=prefixes_per_node,
                prefix_seed=prefix_seed,
                area=area,
                dut_role=dut_role,
                test_port_channel=f"Port-Channel{test_port_channel_id}",
                scale_tester_remote_path=scale_tester_remote_path,
                scale_tester_log_path=scale_tester_log_path,
                injection_run_duration_sec=injection_run_duration_sec,
                injection_ready_timeout_sec=injection_ready_timeout_sec,
            )
        ],
    )


OPENR_SCALE_PHYSICAL_LINK_FLAP_TEST_CONFIG: TestConfig = (
    create_openr_scale_physical_link_flap_test_config()
)
