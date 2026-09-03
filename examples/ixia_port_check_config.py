"""Minimal single-node IXIA connectivity check.

Reserves one physical IXIA port and binds it to a single DUT interface, then
runs a trivial playbook. The point is to exercise the IXIA & TOPOLOGY SETUP
path end to end — connect to the IxNetwork API server, create a session, and
reserve the physical port — without any BGP / traffic emulation.

Nothing lab-specific is committed here (rule: no hardcoded credentials/hosts):
  - DUT host              -> TAAC_IXIA_CHECK_DUT       (must match --dut and the
                             device-info CSV hostname; also the SSH target)
  - DUT edge interface    -> TAAC_IXIA_CHECK_DUT_IFACE (default: eth1/1/1)
  - IXIA physical port    -> TAAC_IXIA_CHECK_IXIA_PORT (slot/port, default: 1/3)
  - IxNetwork API server  -> pass --ixia-api-server on the CLI (the REST/OTG
                             controller the client logs in to)
  - PHYSICAL chassis IP   -> TAAC_IXIA_CHECK_CHASSIS_IP (the hardware chassis
                             where the cards/ports physically live). This is
                             DISTINCT from the API server when IxNetwork runs on
                             a separate Linux box. If left unset it falls back to
                             the --ixia-api-server IP, which only works when the
                             API server IS the chassis (integrated appliance);
                             otherwise the port host never reaches "ready" and
                             assign_ports times out.

Example (from the repo root, inside the fboss-taac image):

    export TAAC_OSS=1 TAAC_SSH_USER=<user>
    source ~/.taac-secrets   # exports TAAC_SSH_PASSWORD (keep creds out of argv)
    export TAAC_IXIA_CHECK_DUT=<dut-mgmt-ip>
    python3 -m taac.runner.oss_entry_point \\
        --test-configs examples/ixia_port_check_config.py \\
        --device-info-csv <device_info.csv> \\
        --dut "$TAAC_IXIA_CHECK_DUT" \\
        --ixia-api-server <chassis-ip> \\
        --skip-oss-setup-tasks --skip-post-setup-wait
"""

import os

from taac.test_as_a_config.types import (
    DirectIxiaConnection,
    Endpoint,
    Playbook,
    Stage,
    Step,
    StepName,
    TestConfig,
)

_DUT: str = os.environ.get("TAAC_IXIA_CHECK_DUT", "")

# Physical chassis IP for the ports. Empty => fall back to --ixia-api-server
# (only correct for an integrated chassis/appliance). Set this when the IxNetwork
# API server is a separate box from the hardware that hosts the cards/ports.
_CHASSIS_IP: str = os.environ.get("TAAC_IXIA_CHECK_CHASSIS_IP", "")

# Lab wiring: DUT interface <-> IXIA physical port (slot/port; the traffic
# generator splits on "/", so "1/3" == card 1, port 3). Two 400G links on this
# single DUT: eth1/1/1<->IXIA port3, eth1/1/5<->IXIA port4. Each pair is
# env-overridable; leave the second pair's iface blank to reserve one port.
_LINKS = [
    (
        os.environ.get("TAAC_IXIA_CHECK_DUT_IFACE", "eth1/1/1"),
        os.environ.get("TAAC_IXIA_CHECK_IXIA_PORT", "1/3"),
    ),
    (
        os.environ.get("TAAC_IXIA_CHECK_DUT_IFACE2", "eth1/1/5"),
        os.environ.get("TAAC_IXIA_CHECK_IXIA_PORT2", "1/4"),
    ),
]

_connections = [
    DirectIxiaConnection(
        interface=iface,
        ixia_port=ixia_port,
        # Physical chassis that hosts the port. When blank, traffic_generator
        # falls back to primary_chassis_ip (= --ixia-api-server).
        ixia_chassis_ip=_CHASSIS_IP or None,
        # Physical reservation of the given slot/port (not a pre-provisioned
        # IxNetwork logical port).
        is_logical_port=False,
    )
    for iface, ixia_port in _LINKS
    if iface
]

# The endpoint must carry the IXIA connections, so it can't be left to the
# entry point's plain --dut append. Build it here from the env-supplied host.
_endpoints = (
    [
        Endpoint(
            name=_DUT,
            dut=True,
            ixia_ports=[iface for iface, _ in _LINKS if iface],
            direct_ixia_connections=_connections,
        )
    ]
    if _DUT
    else []
)


test_config = TestConfig(
    name="ixia_port_check",
    basset_pool="",
    # No protocols are emulated, so don't wait on IXIA protocol convergence.
    skip_ixia_protocol_verification=True,
    endpoints=_endpoints,
    host_os_type_map={},  # Resolved from the device-info CSV.
    startup_checks=[],
    playbooks=[
        Playbook(
            name="ixia_port_reserve_check",
            stages=[Stage(steps=[Step(name=StepName.DUMMY_STEP)])],
        ),
    ],
)
