# Copyright (c) Meta Platforms, Inc. and affiliates.
"""Open/R scale KvStore injection TestConfig (eb02 -> eb04).

TAAC Test 2 (T285180740): run the Open/R ``scale_test_server`` on
``eb02.lab.ash6`` (helper) against ``eb04.lab.ash6`` (DUT), injecting a
synthetic BBF fabric into the DUT's Open/R KvStore, and assert the DUT received
every key-value that fabric should have sent.

Why a receive counter rather than resident keys: the DUT is a real lab box
already holding thousands of its own genuine ``prefix:`` keys, and injected keys
carry an infinite TTL with randomly generated prefixes, so each run leaves a
disjoint residue behind that no later run can tell apart from its own. Resident
state therefore cannot establish that *this* run's keys arrived.
``kvstore.received_key_vals``, sampled on the DUT over Open/R Thrift immediately
before and after the injector runs, can. ``kvstore.updated_key_vals`` -- the
subset that merged -- is logged alongside it and gated by the KvStore-merge
test, which carries the clean-store precondition that makes exact per-node
counts meaningful.

Why the inband path: the ``adj:`` databases are ~51 KB each and arrive as a
multi-segment burst, so they are the key class a control-plane policer drops. An
earlier run over the DUT's **mgmt** address injected 342/372 keys -- every small
``prefix:`` key landed and most large ``adj:`` keys were reset mid-flight (errno
104). Injection therefore targets the DUT's **inband** address, and the mgmt
addresses are passed as an explicit deny-list. Note the limitation this leaves:
a single received total shows the shortfall but cannot localize it to the
``adj:`` class.

Fabric size: 64 spines / 256 leaves, the first BBF site's shape. Spine count is
what matters for DUT realism -- per-leaf adjacency count is spine count x
links-per-spine, so 64 spines makes a leaf DUT BBF-representative, while leaf
count scales overall fabric size and therefore the injected key volume.

Scope: this TestConfig manages **the injection only**. The port-channel
(``Port-Channel1910``) and the ``scale_test_server`` binary are pre-existing
testbed foundation and are neither created nor destroyed here. Open/R is neither
created, destroyed nor restarted: the receive counter is measured across the
injection, so it does not depend on the store's starting contents.

Prerequisite: an **opt-mode** build of ``scale_test_server`` must be pre-deployed
and executable at ``/mnt/flash/scale_test_server`` on eb02.lab.ash6
(``/mnt/flash`` is persistent across reboots; done out of band by the testbed
owner, source is fbcode/openr/tests/scale/). A dev-mode build links ~1000
fine-grained fbcode shared objects that EOS does not carry and will not start.
The test verifies presence and executability before injecting and reports a
loader failure distinctly from an injection failure, but it never builds, copies
or removes the binary. Teardown only stops a lingering injector process.

Run requirement: must run with ``--skip-testbed-isolation``. Netcastle testbed
isolation shuts interfaces not declared in the topology, including
``Port-Channel1910``, which removes the inband path the injection depends on.
"""

import typing as t

from taac.abstractions.physical_inventory import (
    EB02_LAB_ASH6,
    EB04_LAB_ASH6,
    PhysicalInventory,
)
from taac.playbooks.routing.openr_scale_playbooks import (
    get_openr_scale_kvstore_injection_playbook,
)
from taac.task_definitions import (
    create_run_commands_on_shell_task,
)
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import Endpoint, TestConfig


# Inband addresses on the eb02 <-> eb04 Port-Channel1910 /127, read from
# ``breeze -H <host> lm links``. The injector MUST target the inband address:
# the mgmt path (2401:db00:2066:304a::100X) is control-plane policed and resets
# the large adj: requests mid-flight with errno 104, which silently drops
# exactly the keys this test measures. The /127 is point-to-point between the
# two boxes and is deliberately not routable from a devserver -- that is why the
# injector runs on the helper, not on the runner.
EB04_INBAND_ADDRESS: str = "2401:db00:e50d:11:8::10"
EB02_INBAND_ADDRESS: str = "2401:db00:e50d:11:8::11"

# Mgmt addresses, passed to the playbook as a deny-list so that pointing the
# injector at one fails as a precondition instead of as a partial injection.
EB04_MGMT_ADDRESS: str = "2401:db00:2066:304a::1005"
EB02_MGMT_ADDRESS: str = "2401:db00:2066:304a::1003"

# /mnt/flash is persistent across reboots on EOS. Pre-deployed out of band.
SCALE_TESTER_REMOTE_PATH: str = "/mnt/flash/scale_test_server"

# First BBF site's shape. 64 spines is the load-bearing number -- it gives a leaf
# DUT the adjacency count a real data leaf carries; leaf count scales the
# injected key volume.
DEFAULT_SPINES: int = 64
DEFAULT_LEAVES: int = 256


def create_openr_scale_test_config(
    name: str = "OPENR_SCALE_KVSTORE_INJECTION",
    num_spines: int = DEFAULT_SPINES,
    num_leaves: int = DEFAULT_LEAVES,
    dut_inventory: PhysicalInventory = EB04_LAB_ASH6,
    helper_inventory: PhysicalInventory = EB02_LAB_ASH6,
    dut_inband_address: str = EB04_INBAND_ADDRESS,
    dut_mgmt_addresses: t.Optional[t.List[str]] = None,
    dut_role: str = "leaf",
    scale_tester_remote_path: str = SCALE_TESTER_REMOTE_PATH,
    injection_timeout_sec: int = 240,
    num_prefixes_per_node: t.Optional[int] = None,
    skip_teardown: bool = False,
) -> TestConfig:
    """Create the Open/R scale KvStore-injection TestConfig.

    The playbook injects the fabric and asserts the DUT received every key-value
    it should have; teardown stops any lingering injector process. Binary
    staging is out of band -- see the module docstring.

    Args:
        name: TestConfig name, i.e. the ``--test-config`` value.
        num_spines / num_leaves: fabric size to generate and inject.
        dut_inventory / helper_inventory: the two lab boxes. The DUT runs the
            Open/R under test; the helper runs the injector.
        dut_inband_address: address the injector connects to.
        dut_mgmt_addresses: addresses that must never be used for injection.
            Defaults to the DUT and helper mgmt addresses.
        dut_role: ``leaf`` (neighbors are spines) or ``spine``.
        num_prefixes_per_node: prefixes each synthetic node advertises, and so
            part of the expected send count. Left unset it follows the
            injector's own default of 11.
        injection_timeout_sec: cap on the injector command.
        skip_teardown: leave the injector process in place for a follow-up run.

    Returns:
        TestConfig running one Open/R scale injection playbook.
    """
    dut_device = dut_inventory.device_name
    helper_device = helper_inventory.device_name
    # svc-netcastle_bot is denied on ebXX.lab.ash6, so both boxes need the lab
    # admin credentials and synthesized MockDeviceInfo from the inventory.
    host_driver_args = {
        **(dut_inventory.host_driver_args or {}),
        **(helper_inventory.host_driver_args or {}),
    }
    oss_mock_device_data = {
        **(dut_inventory.oss_mock_device_data or {}),
        **(helper_inventory.oss_mock_device_data or {}),
    }

    # Stop a lingering injector, but never remove the binary: it is pre-deployed
    # testbed foundation shared with manual runs. `pkill` returns non-zero when
    # nothing matched, which is the normal case after a clean run, so the exit
    # status is deliberately swallowed.
    #
    # The `bash` prefix is required: the device driver delivers commands to the
    # EOS CLI, which rejects a bare shell command outright. Without it this
    # teardown silently cleaned up nothing while still reporting success, because
    # `|| true` masks the rejection.
    teardown_tasks: t.List[taac_types.Task] = (
        []
        if skip_teardown
        else [
            create_run_commands_on_shell_task(
                hostname=helper_device,
                cmds=[f"bash pkill -f {scale_tester_remote_path} || true"],
            ),
        ]
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
        host_driver_args=host_driver_args,
        oss_mock_device_data=oss_mock_device_data,
        teardown_tasks=teardown_tasks,
        playbooks=[
            get_openr_scale_kvstore_injection_playbook(
                helper_name=helper_device,
                dut_name=dut_device,
                dut_inband_address=dut_inband_address,
                dut_mgmt_addresses=(
                    dut_mgmt_addresses
                    if dut_mgmt_addresses is not None
                    else [EB04_MGMT_ADDRESS, EB02_MGMT_ADDRESS]
                ),
                num_spines=num_spines,
                num_leaves=num_leaves,
                dut_role=dut_role,
                scale_tester_remote_path=scale_tester_remote_path,
                injection_timeout_sec=injection_timeout_sec,
                num_prefixes_per_node=num_prefixes_per_node,
            ),
        ],
    )


# Concrete lifecycle binding consumed by ``netcastle_taac --test-config``.
# Execution node: pool ``dne.test``, eb04 (DUT) <- eb02 (helper) over the
# Port-Channel1910 inband /127. Requires ``--skip-testbed-isolation``.
OPENR_SCALE_KVSTORE_INJECTION_TEST_CONFIG: TestConfig = create_openr_scale_test_config()
