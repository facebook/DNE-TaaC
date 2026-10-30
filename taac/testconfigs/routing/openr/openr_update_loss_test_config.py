# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

"""Open/R Decision->Fib update-loss TestConfig (eb02 -> eb04).

Regression coverage for S696505. The lifecycle owns everything it needs: it
isolates the rig, splits the second physical member into a test-scoped routed
Port-Channel1911 (so the burst has a disjoint second link), switches the DUT's
Open/R to FIB programming, and clears any stale link-metric overrides. The
playbook simulates a small fabric from the helper, freezes FibAgent through
three asymmetric metric rebuilds, and fails when Decision moved on but Fib or
EOS kept stale values. Teardown clears the overrides, expires the injected
keys, restores the DUT's Open/R config, and returns the member to
Port-Channel1910.

Run with ``--skip-testbed-isolation`` so Netcastle does not shut the undeclared
physical members that provide the inband control path.
"""

from taac.abstractions.physical_inventory import (
    EB02_LAB_ASH6,
    EB04_LAB_ASH6,
    PhysicalInventory,
)
from taac.playbooks.routing.openr_update_loss_playbooks import (
    get_openr_update_loss_playbook,
)
from taac.task_definitions import (
    create_openr_fib_programming_task,
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


DEFAULT_MEMBER_INTERFACE: str = "Ethernet3/10/1"
DEFAULT_ORIGINAL_PORT_CHANNEL_ID: int = 1910
DEFAULT_TEST_PORT_CHANNEL_ID: int = 1911
DEFAULT_HELPER_TEST_IPV4_CIDR: str = "10.165.28.12/31"
DEFAULT_DUT_TEST_IPV4_CIDR: str = "10.165.28.13/31"


def create_openr_update_loss_test_config(
    name: str = "OPENR_UPDATE_LOSS",
    dut_inventory: PhysicalInventory = EB04_LAB_ASH6,
    helper_inventory: PhysicalInventory = EB02_LAB_ASH6,
    member_interface: str = DEFAULT_MEMBER_INTERFACE,
    original_port_channel_id: int = DEFAULT_ORIGINAL_PORT_CHANNEL_ID,
    test_port_channel_id: int = DEFAULT_TEST_PORT_CHANNEL_ID,
    helper_test_ipv4_cidr: str = DEFAULT_HELPER_TEST_IPV4_CIDR,
    dut_test_ipv4_cidr: str = DEFAULT_DUT_TEST_IPV4_CIDR,
) -> TestConfig:
    """Create the Open/R update-loss TestConfig with a test-scoped Po1911."""
    dut_name = dut_inventory.device_name
    helper_name = helper_inventory.device_name
    fixture_addresses = {
        helper_name: helper_test_ipv4_cidr,
        dut_name: dut_test_ipv4_cidr,
    }
    isolation = create_openr_scale_isolation_task(
        hosts=[dut_name, helper_name],
        helper_hostname=helper_name,
        scale_tester_remote_path=SCALE_TESTER_REMOTE_PATH,
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
            fixture_setup,
            create_openr_fib_programming_task(dut_name=dut_name, action="enable"),
        ],
        # Expire the injected keys before restoring dryrun: Open/R can only
        # withdraw its routes from FibAgent while it is still programming.
        # The link fixture is restored last, after Open/R no longer needs it.
        teardown_tasks=[
            isolation,
            create_openr_fib_programming_task(dut_name=dut_name, action="disable"),
            fixture_cleanup,
        ],
        playbooks=[
            get_openr_update_loss_playbook(
                dut_name=dut_name,
                helper_name=helper_name,
                dut_inband_address=EB04_INBAND_ADDRESS,
                dut_mgmt_addresses=[EB04_MGMT_ADDRESS, EB02_MGMT_ADDRESS],
                scale_tester_remote_path=SCALE_TESTER_REMOTE_PATH,
            )
        ],
    )


OPENR_UPDATE_LOSS: TestConfig = create_openr_update_loss_test_config()
