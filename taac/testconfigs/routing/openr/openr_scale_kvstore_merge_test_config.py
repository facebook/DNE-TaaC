# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
"""Isolated two-injection Open/R KvStore merge lifecycle on eb02/eb04."""

import typing as t

from taac.abstractions.physical_inventory import (
    EB02_LAB_ASH6,
    EB04_LAB_ASH6,
    PhysicalInventory,
)
from taac.playbooks.routing.openr_scale_playbooks import (
    get_openr_scale_kvstore_merge_playbook,
)
from taac.task_definitions import (
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


DEFAULT_SPINES: int = 64
DEFAULT_LEAVES: int = 256
DEFAULT_CONTROL_NODES: int = 0
DEFAULT_SITES: int = 20
DEFAULT_ECMP_WIDTH: int = 8
DEFAULT_PREFIXES_PER_NODE: int = 11
PREFIX_SEED_A: int = 20250903
PREFIX_SEED_B: int = 20250904
DEFAULT_AREA: str = "0"
DEFAULT_STATE_KEY: str = "openr_scale_kvstore_merge_adjacency_fingerprints"
DEFAULT_INJECTION_RUN_DURATION_SEC: int = 5
DEFAULT_INJECTION_TIMEOUT_SEC: int = 120


def create_openr_scale_kvstore_merge_test_config(
    name: str = "OPENR_SCALE_KVSTORE_MERGE",
    num_spines: int = DEFAULT_SPINES,
    num_leaves: int = DEFAULT_LEAVES,
    num_control_nodes: int = DEFAULT_CONTROL_NODES,
    num_sites: int = DEFAULT_SITES,
    ecmp_width: int = DEFAULT_ECMP_WIDTH,
    prefixes_per_node: int = DEFAULT_PREFIXES_PER_NODE,
    seed_a: int = PREFIX_SEED_A,
    seed_b: int = PREFIX_SEED_B,
    area: str = DEFAULT_AREA,
    state_key: str = DEFAULT_STATE_KEY,
    dut_inventory: PhysicalInventory = EB04_LAB_ASH6,
    helper_inventory: PhysicalInventory = EB02_LAB_ASH6,
    dut_inband_address: str = EB04_INBAND_ADDRESS,
    dut_mgmt_addresses: t.Optional[t.List[str]] = None,
    scale_tester_remote_path: str = SCALE_TESTER_REMOTE_PATH,
    injection_run_duration_sec: int = DEFAULT_INJECTION_RUN_DURATION_SEC,
    injection_timeout_sec: int = DEFAULT_INJECTION_TIMEOUT_SEC,
) -> TestConfig:
    """Create the isolated Test 3 lifecycle for exact KvStore merge semantics."""
    dut_device = dut_inventory.device_name
    helper_device = helper_inventory.device_name
    cleanup_hosts = [dut_device, helper_device]
    forbidden_hosts = (
        dut_mgmt_addresses
        if dut_mgmt_addresses is not None
        else [EB04_MGMT_ADDRESS, EB02_MGMT_ADDRESS]
    )
    isolation_task = create_openr_scale_isolation_task(
        hosts=cleanup_hosts,
        helper_hostname=helper_device,
        scale_tester_remote_path=scale_tester_remote_path,
        area=area,
    )

    return TestConfig(
        name=name,
        basset_pool="dne.test",
        endpoints=[
            Endpoint(name=dut_device, dut=True),
            Endpoint(name=helper_device, dut=False),
        ],
        host_os_type_map={
            dut_device: taac_types.DeviceOsType.ARISTA_OS,
            helper_device: taac_types.DeviceOsType.ARISTA_OS,
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
        setup_tasks=[isolation_task],
        teardown_tasks=[isolation_task],
        playbooks=[
            get_openr_scale_kvstore_merge_playbook(
                helper_name=helper_device,
                dut_name=dut_device,
                dut_inband_address=dut_inband_address,
                dut_mgmt_addresses=forbidden_hosts,
                scale_tester_remote_path=scale_tester_remote_path,
                num_spines=num_spines,
                num_leaves=num_leaves,
                num_control_nodes=num_control_nodes,
                num_sites=num_sites,
                ecmp_width=ecmp_width,
                prefixes_per_node=prefixes_per_node,
                seed_a=seed_a,
                seed_b=seed_b,
                area=area,
                state_key=state_key,
                injection_run_duration_sec=injection_run_duration_sec,
                injection_timeout_sec=injection_timeout_sec,
            )
        ],
    )


# Concrete lifecycle binding consumed by ``netcastle_taac --test-config``.
# Requires ``--skip-testbed-isolation`` to preserve Port-Channel1910.
OPENR_SCALE_KVSTORE_MERGE_TEST_CONFIG: TestConfig = (
    create_openr_scale_kvstore_merge_test_config()
)
