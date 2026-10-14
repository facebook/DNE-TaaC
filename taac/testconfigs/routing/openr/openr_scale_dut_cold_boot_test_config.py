# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

"""Full-fabric DUT cold-boot qualification on the eb02/eb04 Open/R pair."""

import typing as t

from taac.abstractions.physical_inventory import (
    EB02_LAB_ASH6,
    EB04_LAB_ASH6,
    PhysicalInventory,
)
from taac.playbooks.routing.openr_scale_playbooks import (
    get_openr_scale_dut_cold_boot_playbook,
)
from taac.task_definitions import (
    create_openr_scale_cold_boot_fixture_task,
    create_openr_scale_isolation_task,
)
from taac.testconfigs.routing.openr.openr_scale_test_config import (
    EB02_MGMT_ADDRESS,
    EB04_INBAND_ADDRESS,
    EB04_MGMT_ADDRESS,
    SCALE_TESTER_REMOTE_PATH,
)
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import Endpoint, TestConfig


DEFAULT_SPINES = 64
DEFAULT_LEAVES = 256
DEFAULT_CONTROL_NODES = 0
DEFAULT_SITES = 20
DEFAULT_ECMP_WIDTH = 8
DEFAULT_PREFIXES_PER_NODE = 11
DEFAULT_PREFIX_SEED = 20250903
DEFAULT_AREA = "0"
DEFAULT_INTERFACE = "po1910"
DEFAULT_PORT_CHANNEL = "Port-Channel1910"
DEFAULT_START_VLAN = 100
DEFAULT_DUT_HOST_OCTET = 2
DEFAULT_HELPER_HOST_OCTET = 1
DEFAULT_SCALE_TESTER_LOG_PATH = "/mnt/flash/openr_scale_dut_cold_boot.log"
DEFAULT_INJECTOR_WATCHDOG_SECONDS = 1800


def create_openr_scale_dut_cold_boot_test_config(
    name: str = "OPENR_SCALE_DUT_COLD_BOOT",
    num_spines: int = DEFAULT_SPINES,
    num_leaves: int = DEFAULT_LEAVES,
    num_control_nodes: int = DEFAULT_CONTROL_NODES,
    num_sites: int = DEFAULT_SITES,
    ecmp_width: int = DEFAULT_ECMP_WIDTH,
    prefixes_per_node: int = DEFAULT_PREFIXES_PER_NODE,
    prefix_seed: int = DEFAULT_PREFIX_SEED,
    area: str = DEFAULT_AREA,
    dut_role: t.Literal["leaf", "spine"] = "leaf",
    interface: str = DEFAULT_INTERFACE,
    port_channel: str = DEFAULT_PORT_CHANNEL,
    start_vlan: int = DEFAULT_START_VLAN,
    dut_host_octet: int = DEFAULT_DUT_HOST_OCTET,
    helper_host_octet: int = DEFAULT_HELPER_HOST_OCTET,
    dut_inventory: PhysicalInventory = EB04_LAB_ASH6,
    helper_inventory: PhysicalInventory = EB02_LAB_ASH6,
    dut_inband_address: str = EB04_INBAND_ADDRESS,
    dut_mgmt_addresses: t.Optional[t.List[str]] = None,
    scale_tester_remote_path: str = SCALE_TESTER_REMOTE_PATH,
    scale_tester_log_path: str = DEFAULT_SCALE_TESTER_LOG_PATH,
    injector_watchdog_seconds: int = DEFAULT_INJECTOR_WATCHDOG_SECONDS,
) -> TestConfig:
    """Create the blocking 64/256 leaf-DUT cold-boot qualification."""
    dut_name = dut_inventory.device_name
    helper_name = helper_inventory.device_name
    isolation = create_openr_scale_isolation_task(
        hosts=[dut_name, helper_name],
        helper_hostname=helper_name,
        scale_tester_remote_path=scale_tester_remote_path,
        area=area,
    )
    num_simulated_neighbors = (
        num_spines + int(num_sites > 0)
        if dut_role == "leaf"
        else num_leaves + num_control_nodes
    )
    num_subinterfaces = num_simulated_neighbors - 1
    if num_subinterfaces <= 0:
        raise ValueError("cold-boot scale requires at least two simulated neighbors")
    fixture_setup = create_openr_scale_cold_boot_fixture_task(
        action="setup",
        dut_name=dut_name,
        helper_name=helper_name,
        port_channel=port_channel,
        num_subinterfaces=num_subinterfaces,
        start_vlan=start_vlan,
        dut_host_octet=dut_host_octet,
        helper_host_octet=helper_host_octet,
    )
    fixture_cleanup = create_openr_scale_cold_boot_fixture_task(
        action="cleanup",
        dut_name=dut_name,
        helper_name=helper_name,
        port_channel=port_channel,
        num_subinterfaces=num_subinterfaces,
        start_vlan=start_vlan,
        dut_host_octet=dut_host_octet,
        helper_host_octet=helper_host_octet,
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
        setup_tasks=[isolation, fixture_setup],
        teardown_tasks=[fixture_cleanup, isolation],
        playbooks=[
            get_openr_scale_dut_cold_boot_playbook(
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
                interface=interface,
                start_vlan=start_vlan,
                scale_tester_remote_path=scale_tester_remote_path,
                scale_tester_log_path=scale_tester_log_path,
                injector_watchdog_seconds=injector_watchdog_seconds,
            )
        ],
    )


OPENR_SCALE_DUT_COLD_BOOT: TestConfig = create_openr_scale_dut_cold_boot_test_config()
