# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

"""Open/R recovery after FibAgent is frozen under an update burst (eb02/eb04).

Starts and ends on an empty rig. Setup clears stray scale-tester state and
switches the DUT's Open/R to ``dryrun: false``; the playbook simulates the
fabric from the helper; teardown expires the injected keys, waits for Open/R to
withdraw its routes, and restores the original Open/R config. The helper is not
an endpoint, so endpoint-wide checks do not run on it; it runs no FibAgent.
"""

import typing as t

from taac.abstractions.physical_inventory import (
    EB02_LAB_ASH6,
    EB04_LAB_ASH6,
    PhysicalInventory,
)
from taac.playbooks.routing.openr_scale_playbooks import (
    get_openr_fibagent_pause_playbook,
)
from taac.task_definitions import (
    create_openr_fib_programming_task,
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


def create_openr_fibagent_pause_test_config(
    name: str = "OPENR_FIBAGENT_PAUSE",
    bursts: int = 2,
    updates_per_burst: int = 4,
    dut_inventory: PhysicalInventory = EB04_LAB_ASH6,
    helper_inventory: PhysicalInventory = EB02_LAB_ASH6,
) -> TestConfig:
    dut_name = dut_inventory.device_name
    helper_name = helper_inventory.device_name
    isolation = create_openr_scale_isolation_task(
        hosts=[dut_name, helper_name],
        helper_hostname=helper_name,
        scale_tester_remote_path=SCALE_TESTER_REMOTE_PATH,
    )
    return TestConfig(
        name=name,
        basset_pool="dne.test",
        endpoints=[Endpoint(name=dut_name, dut=True)],
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
        setup_tasks=[
            isolation,
            create_openr_fib_programming_task(dut_name=dut_name, action="enable"),
        ],
        # Expire the injected keys before restoring dryrun: Open/R can only
        # withdraw its routes from FibAgent while it is still programming.
        teardown_tasks=[
            isolation,
            create_openr_fib_programming_task(dut_name=dut_name, action="disable"),
        ],
        playbooks=[
            get_openr_fibagent_pause_playbook(
                dut_name=dut_name,
                helper_name=helper_name,
                dut_inband_address=EB04_INBAND_ADDRESS,
                dut_mgmt_addresses=[EB04_MGMT_ADDRESS, EB02_MGMT_ADDRESS],
                bursts=bursts,
                updates_per_burst=updates_per_burst,
                scale_tester_remote_path=SCALE_TESTER_REMOTE_PATH,
            )
        ],
    )


OPENR_FIBAGENT_PAUSE: TestConfig = create_openr_fibagent_pause_test_config()
