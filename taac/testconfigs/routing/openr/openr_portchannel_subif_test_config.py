# Copyright (c) Meta Platforms, Inc. and affiliates.
"""Open/R sub-interface adjacency scaling TestConfig (eb02 ↔ eb04).

TAAC Test 1 (T285180608): create N dot1q routed sub-interfaces on the
port-channel between ``eb04.lab.ash6`` (DUT) and ``eb02.lab.ash6`` (peer),
both running real Open/R, and assert the DUT forms N + 1 ESTABLISHED Open/R
adjacencies -- the N sub-interface adjacencies plus the one parent port-channel
adjacency. N defaults to 1024 = 2x the 512 adjacencies a leaf node must
support (the qualification target); VLANs ``start_vlan .. start_vlan+N-1``.

Scope: this TestConfig manages **sub-interfaces only**. The port-channel
(``Port-Channel1910``), the Open/R daemon, and ``/etc/openr_config`` are
pre-existing testbed foundation and are neither created nor destroyed here.

Setup runs the pre-deployed ``setup_portchannel_subinterfaces.sh`` on each box
under FastCli (far faster than streaming ``configure`` blocks over FCR); teardown
runs the companion ``cleanup_portchannel_subinterfaces.sh``. Each script batches
all of its VLANs internally.

Prerequisite: ``setup_portchannel_subinterfaces.sh`` and
``cleanup_portchannel_subinterfaces.sh`` must be pre-deployed to ``/mnt/flash/``
(persistent storage) on both eb02.lab.ash6 and eb04.lab.ash6 (done manually by
the testbed owner; the script source is fbcode/openr/tests/scale/scripts/).

Addressing convention (matches the script and the manual runbook):
    VLAN X → IPv4 ``10.<X//256>.<X%256>.<octet>/24``
             IPv6 ``fd00:0:0:<hex(X)>::<octet>/64``
    octet 2 = DUT (eb04), octet 1 = peer (eb02).

The assertion is the postcheck ``OpenrSparkNeighborHealthCheck`` with
``expected_neighbor_count == N + 1`` -- the N sub-interface adjacencies plus the
one parent port-channel adjacency; a mismatch is a FAIL verdict, not an error.

Run requirement: this test relies on the pre-existing ``Port-Channel1910``
interconnect between the two DUTs staying up, so it must run with
``--skip-testbed-isolation``. Netcastle testbed isolation shuts interfaces not
declared in the topology (including the port-channel members), which downs the
eb02<->eb04 link and yields 0 adjacencies. Validated end-to-end on hardware
2026-08-19 (Run Id 203a504de0b34636a5b94cdd58cf5b4d): 1024 sub-interface pairs
-> 1024 ESTABLISHED Open/R adjacencies on each box, postcheck PASS.
"""

import typing as t

from taac.abstractions.physical_inventory import (
    EB02_LAB_ASH6,
    EB04_LAB_ASH6,
    PhysicalInventory,
)
from taac.playbooks.playbook_definitions import (
    create_openr_subif_adjacency_scale_playbook,
)
from taac.task_definitions import (
    create_run_commands_on_shell_task,
)
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import Endpoint, TestConfig

# Testbed foundation (pre-existing; not managed by this TestConfig).
# DUT = eb04 (octet 2), peer = eb02 (octet 1); both are EOS lab boxes. Their
# admin/password lab auth (``host_driver_args``) and synthesized MockDeviceInfo
# (``oss_mock_device_data``) are sourced from the PhysicalInventory, because
# ``svc-netcastle_bot`` is not authorized on ebXX.lab.ash6 and ``netwhoami``
# returns ``#INVALID#`` for lab devices.
DEFAULT_PORT_CHANNEL: str = "Port-Channel1910"

# Sub-interface plan defaults. N = 1024 is the qualification target: 2x the
# 512 adjacencies a leaf node must support. The factory stays parameterized so
# larger scale (up to the 4094 dot1q max) or a quick smoke are trivial.
DEFAULT_NUM_SUBINTERFACES: int = 1024
DEFAULT_START_VLAN: int = 1

# Host octet per end (see addressing convention above).
DUT_OCTET: int = 2
PEER_OCTET: int = 1

# Small fixed buffer before the postcheck starts; the retry envelope below is
# the real safety net for convergence, so this stays lean.
DEFAULT_CONVERGENCE_WAIT_SECONDS: int = 60

# Postcheck retry envelope so transient convergence lag does not FAIL the run.
# 10 retries x 15s ~= 2.5 min of re-polling for the sub-interface set.
DEFAULT_POSTCHECK_RETRY_COUNT: int = 10
DEFAULT_POSTCHECK_RETRY_DELAY_SECONDS: float = 15.0

# Device-side scripts, pre-deployed to /mnt/flash (persistent) on eb02/eb04 by
# the testbed owner (source: fbcode/openr/tests/scale/scripts/): setup creates
# the sub-interfaces, cleanup removes them. Each batches all VLANs internally.
_SETUP_SCRIPT_PATH: str = "/mnt/flash/setup_portchannel_subinterfaces.sh"
_CLEANUP_SCRIPT_PATH: str = "/mnt/flash/cleanup_portchannel_subinterfaces.sh"


def _script_setup_tasks(
    hostname: str,
    port_channel: str,
    num_vlans: int,
    start_vlan: int,
    octet: int,
) -> t.List[taac_types.Task]:
    """Run the pre-deployed setup script (creates the sub-interfaces).

    FCR runs commands in the EOS CLI, so the ``bash`` prefix drops into a shell
    and ``sudo`` elevates to root; the script batches all VLANs internally.
    """
    return [
        create_run_commands_on_shell_task(
            hostname=hostname,
            cmds=[
                # `timeout` bounds the on-box script from within the command;
                # the shared run_commands_on_shell task takes no timeout param.
                f"bash sudo timeout 600 bash {_SETUP_SCRIPT_PATH} "
                f"{port_channel} {num_vlans} {start_vlan} {octet}"
            ],
            set_outer_hostname=True,
            validate_output=True,
        ),
    ]


def _script_teardown_tasks(
    hostname: str,
    port_channel: str,
    num_vlans: int,
    start_vlan: int,
) -> t.List[taac_types.Task]:
    """Run the pre-deployed cleanup script (removes the sub-interfaces)."""
    return [
        create_run_commands_on_shell_task(
            hostname=hostname,
            cmds=[
                f"bash sudo timeout 600 bash {_CLEANUP_SCRIPT_PATH} "
                f"{port_channel} {num_vlans} {start_vlan}"
            ],
            set_outer_hostname=True,
            validate_output=True,
        ),
    ]


def create_openr_portchannel_subif_test_config(
    num_subinterfaces: int = DEFAULT_NUM_SUBINTERFACES,
    start_vlan: int = DEFAULT_START_VLAN,
    port_channel: str = DEFAULT_PORT_CHANNEL,
    dut_inventory: PhysicalInventory = EB04_LAB_ASH6,
    peer_inventory: PhysicalInventory = EB02_LAB_ASH6,
    convergence_wait_seconds: int = DEFAULT_CONVERGENCE_WAIT_SECONDS,
    postcheck_retry_count: int = DEFAULT_POSTCHECK_RETRY_COUNT,
    postcheck_retry_delay_seconds: float = DEFAULT_POSTCHECK_RETRY_DELAY_SECONDS,
    skip_teardown: bool = False,
) -> TestConfig:
    """Create the Open/R sub-interface adjacency scaling TestConfig.

    Args:
        num_subinterfaces: Number N of dot1q sub-interface pairs to create; also
            the number of Open/R adjacencies the DUT must form.
        start_vlan: First VLAN id; sub-interfaces use ``start_vlan .. start_vlan+N-1``.
        port_channel: Pre-existing bundling port-channel (e.g. ``Port-Channel1910``).
        dut_inventory: PhysicalInventory for the DUT (octet 2), reserved as
            ``dut=True``; supplies lab auth and mock device data.
        peer_inventory: PhysicalInventory for the peer (octet 1).
        convergence_wait_seconds: Delay before the adjacency-count postcheck.
        postcheck_retry_count: Retries for the postcheck to absorb convergence lag.
        postcheck_retry_delay_seconds: Base delay between postcheck retries.
        skip_teardown: When True, leave sub-interfaces in place for a re-run.

    Returns:
        TestConfig that creates N sub-interface pairs, asserts N + 1 ESTABLISHED
        Open/R adjacencies on the DUT (the N sub-interface adjacencies plus the
        parent port-channel adjacency), and tears the sub-interfaces down.
    """
    dut_device = dut_inventory.device_name
    peer_device = peer_inventory.device_name
    # Lab auth + synthesized MockDeviceInfo for both EOS boxes, merged from the
    # inventory (svc-netcastle_bot is denied on ebXX.lab.ash6).
    host_driver_args = {
        **(dut_inventory.host_driver_args or {}),
        **(peer_inventory.host_driver_args or {}),
    }
    oss_mock_device_data = {
        **(dut_inventory.oss_mock_device_data or {}),
        **(peer_inventory.oss_mock_device_data or {}),
    }

    setup_tasks = _script_setup_tasks(
        hostname=dut_device,
        port_channel=port_channel,
        num_vlans=num_subinterfaces,
        start_vlan=start_vlan,
        octet=DUT_OCTET,
    ) + _script_setup_tasks(
        hostname=peer_device,
        port_channel=port_channel,
        num_vlans=num_subinterfaces,
        start_vlan=start_vlan,
        octet=PEER_OCTET,
    )

    if skip_teardown:
        teardown_tasks: t.List[taac_types.Task] = []
    else:
        teardown_tasks = _script_teardown_tasks(
            hostname=dut_device,
            port_channel=port_channel,
            num_vlans=num_subinterfaces,
            start_vlan=start_vlan,
        ) + _script_teardown_tasks(
            hostname=peer_device,
            port_channel=port_channel,
            num_vlans=num_subinterfaces,
            start_vlan=start_vlan,
        )

    return TestConfig(
        name=f"OPENR_PORTCHANNEL_SUBIF_SCALE_{num_subinterfaces}",
        basset_pool="dne.test",
        endpoints=[
            Endpoint(name=dut_device, dut=True),
            Endpoint(name=peer_device, dut=False),
        ],
        host_os_type_map={
            dut_device: taac_types.DeviceOsType.ARISTA_OS,
            peer_device: taac_types.DeviceOsType.ARISTA_OS,
        },
        startup_checks=[],
        host_driver_args=host_driver_args,
        oss_mock_device_data=oss_mock_device_data,
        setup_tasks=setup_tasks,
        teardown_tasks=teardown_tasks,
        playbooks=[
            create_openr_subif_adjacency_scale_playbook(
                # N sub-interface adjacencies + 1 parent port-channel adjacency.
                expected_neighbor_count=num_subinterfaces + 1,
                convergence_wait_seconds=convergence_wait_seconds,
                postcheck_retry_count=postcheck_retry_count,
                postcheck_retry_delay_seconds=postcheck_retry_delay_seconds,
            ),
        ],
    )


# Concrete lifecycle binding consumed by ``netcastle_taac --test-config``.
# Execution node: pool ``dne.test``, eb04 (DUT) ↔ eb02 over Port-Channel1910.
OPENR_PORTCHANNEL_SUBIF_SCALE_TEST_CONFIG: TestConfig = (
    create_openr_portchannel_subif_test_config()
)
