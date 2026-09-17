# Copyright (c) Meta Platforms, Inc. and affiliates.
"""BGP session establishment test — runnable on IxNetwork (RESTPY) or OTG.

Configures a single traffic-generator port as an IPv4 eBGP peer toward the
DUT and verifies the session reaches Established state.

Topology:
    TGEN Port 1 (10.0.3.2/24, AS 65001) -- eBGP -- DUT Port A (10.0.3.1, AS 65000)

DUT prerequisites (satisfied by examples/switch01.bgp_pp.example.conf and
examples/switch01.fboss_sw_agent.example.conf):
  - IPv4 address 10.0.3.1/24 on the TGEN-facing interface
  - BGP configured: local-as 65000, accept eBGP peer 10.0.3.2 (remote-as 65001)
  - IPv4 unicast address-family enabled on that peer

Device targeting: all device-specific values (hostname, MAC, TGEN wiring,
addressing, AS numbers) live in examples/testbed_constants.py — edit that
file to target a real testbed. The topology CSVs passed to the runner must
describe the same wiring.

Backend selection: both variants are built at import time
(BGP_SESSION_RESTPY_TEST_CONFIG / BGP_SESSION_OTG_TEST_CONFIG); set
TAAC_TGEN_BACKEND=otg to run the OTG one. The --ixia-api-server flag
supplies the IxNetwork server or the OTG controller URL
(e.g. https://localhost:8443) respectively.

Postchecks: BGP_SESSION_ESTABLISH_CHECK (retries until Established, up to
60 s) plus the OSS collector-backed checks (systemd active-state, unclean
exit).

Run (inside fboss-taac image):

    python -m taac.runner.oss_entry_point \
        --test-configs examples/bgp_session_test.py \
        --device-info-csv examples/topology/single_switch/device_info.csv \
        --circuit-info-csv examples/topology/single_switch/circuit_info.csv \
        --dut switch01.example.com \
        --ixia-api-server ixia-api.example.com \
        --skip-post-setup-wait

OTG variant:

    TAAC_TGEN_BACKEND=otg python -m taac.runner.oss_entry_point \
        --test-configs examples/bgp_session_test.py \
        --device-info-csv examples/topology/single_switch_otg/device_info.csv \
        --circuit-info-csv examples/topology/single_switch_otg/circuit_info.csv \
        --dut switch01.example.com \
        --ixia-api-server https://localhost:8443 \
        --skip-post-setup-wait
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import testbed_constants as tb

from ixia.ixia import types as ixia_types

from taac.health_checks.constants import DEFAULT_SERVICE_NAMES
from taac.health_checks.healthcheck_definitions import (
    create_bgp_session_establish_check,
    create_systemctl_active_state_check,
    create_unclean_exit_check,
)
from taac.stages.stage_definitions import create_steps_stage
from taac.test_as_a_config.thrift_types import (
    BasicPortConfig,
    BgpConfig,
    DeviceGroupConfig,
    DeviceOsType,
    DirectIxiaConnection,
    Endpoint,
    IpAddressesConfig,
    Playbook,
    TestConfig,
    TrafficGeneratorBackend,
)


def _build(otg: bool) -> TestConfig:
    if otg:
        # OTG: the port-location string doubles as the logical interface
        # name (matching taac/otg/otg_basic_l3_test_config.py).
        conn = DirectIxiaConnection(
            interface=tb.OTG_PORT_A_LOCATION,
            ixia_port="1/1",
            is_logical_port=True,
            port_location=tb.OTG_PORT_A_LOCATION,
        )
    else:
        conn = DirectIxiaConnection(
            interface=tb.TGEN_PORT_A_DUT_INTERFACE,
            ixia_port=tb.IXIA_PORT_A,
            ixia_chassis_ip=tb.IXIA_CHASSIS,
        )
    iface = conn.interface
    dut = tb.SWITCH01_DEVICE_NAME

    return TestConfig(
        name="bgp_session",
        basset_pool="",
        traffic_generator_backend=(
            TrafficGeneratorBackend.OTG if otg else TrafficGeneratorBackend.RESTPY
        ),
        endpoints=[
            Endpoint(
                name=dut,
                dut=True,
                ixia_ports=[iface],
                mac_address=tb.SWITCH01_LOCAL_MAC_ADDRESS,
                direct_ixia_connections=[conn],
            )
        ],
        basic_port_configs=[
            BasicPortConfig(
                endpoint=f"{dut}:{iface}",
                device_group_configs=[
                    DeviceGroupConfig(
                        device_group_index=0,
                        multiplier=1,
                        v4_addresses_config=IpAddressesConfig(
                            starting_ip=tb.PORT_A_TGEN_IP,
                            mask=tb.PREFIX_LEN,
                            gateway_starting_ip=tb.PORT_A_DUT_GW,
                        ),
                        # IpV4Unicast only — FBOSS rejects peers that advertise
                        # unsupported address families in the BGP OPEN message.
                        v4_bgp_config=BgpConfig(
                            local_as_4_bytes=tb.TGEN_AS,
                            enable_4_byte_local_as=True,
                            bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                            bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                        ),
                    )
                ],
            )
        ],
        playbooks=[
            # No disruptive steps — the test just verifies session establishment.
            # The establish check runs as a playbook postcheck, NOT a
            # startup_check: the OSS runner skips startup_checks entirely
            # ("Startup checks skipped in OSS mode"), which would make this
            # test pass without verifying anything.
            Playbook(
                name="bgp_session_check",
                stages=[create_steps_stage(steps=[], description="No steps — the postchecks are the test")],
                postchecks=[
                    # Retry up to 6 times (10 s base) to account for
                    # hold-timer expiry.
                    create_bgp_session_establish_check(
                        expected_established_sessions=1,
                        retry_count=6,
                        retry_delay_seconds=10.0,
                    ),
                    # OSS collector-backed: services stayed healthy while
                    # the session established. (CPU-percentile / RSS-delta
                    # observe checks are deliberately absent — they read
                    # summaries produced by FPF START/STOP characterization
                    # steps, not the live collectors, and would always SKIP.)
                    create_systemctl_active_state_check(
                        services_json=DEFAULT_SERVICE_NAMES
                    ),
                    create_unclean_exit_check(),
                ],
            )
        ],
        host_os_type_map={dut: DeviceOsType.FBOSS},
        startup_checks=[],
    )


BGP_SESSION_RESTPY_TEST_CONFIG = _build(otg=False)
BGP_SESSION_OTG_TEST_CONFIG = _build(otg=True)

TEST_CONFIG = (
    BGP_SESSION_OTG_TEST_CONFIG
    if os.environ.get("TAAC_TGEN_BACKEND", "").lower() == "otg"
    else BGP_SESSION_RESTPY_TEST_CONFIG
)
