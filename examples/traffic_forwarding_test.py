# Copyright (c) Meta Platforms, Inc. and affiliates.
"""IPv4 L3 traffic-forwarding test — runnable on IxNetwork (RESTPY) or OTG.

Configures two traffic-generator ports as IPv4 endpoints on opposite sides
of the DUT, sends bidirectional traffic at 10% line rate, and verifies zero
packet loss.

Topology:
    TGEN Port 1 (10.0.3.2/24) -- DUT Port A (10.0.3.1) -- DUT Port B (10.0.4.1) -- TGEN Port 2 (10.0.4.2/24)

DUT prerequisites (satisfied by examples/switch01.fboss_sw_agent.example.conf):
  - IPv4 address 10.0.3.1/24 on Port A, 10.0.4.1/24 on Port B
  - Routing between the two subnets (covered by connected routes when both
    addresses live on the DUT)

Device targeting: all device-specific values (hostname, MAC, TGEN wiring,
addressing) live in examples/testbed_constants.py — edit that file to
target a real testbed. The topology CSVs passed to the runner must describe
the same wiring.

Backend selection: both variants are built at import time
(TRAFFIC_FORWARDING_RESTPY_TEST_CONFIG / TRAFFIC_FORWARDING_OTG_TEST_CONFIG);
set TAAC_TGEN_BACKEND=otg to run the OTG one. The --ixia-api-server flag
supplies the IxNetwork server or the OTG controller URL
(e.g. https://localhost:8443) respectively.

Run (inside fboss-taac image):

    python -m taac.runner.oss_entry_point \
        --test-configs examples/traffic_forwarding_test.py \
        --device-info-csv examples/topology/single_switch/device_info.csv \
        --circuit-info-csv examples/topology/single_switch/circuit_info.csv \
        --dut switch01.example.com \
        --ixia-api-server ixia-api.example.com \
        --skip-post-setup-wait

OTG variant:

    TAAC_TGEN_BACKEND=otg python -m taac.runner.oss_entry_point \
        --test-configs examples/traffic_forwarding_test.py \
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
    create_cpu_utilization_check,
    create_memory_utilization_check,
    create_systemctl_active_state_check,
    create_traffic_item_packet_loss_check,
    create_unclean_exit_check,
)
from taac.stages.stage_definitions import create_steps_stage
from taac.steps.step_definitions import create_longevity_step
from taac.test_as_a_config.thrift_types import (
    BasicPortConfig,
    BasicTrafficItemConfig,
    DeviceGroupConfig,
    DeviceOsType,
    DirectIxiaConnection,
    Endpoint,
    IpAddressesConfig,
    Playbook,
    TestConfig,
    TrafficEndpoint,
    TrafficGeneratorBackend,
)


def _connection(otg: bool, dut_interface: str, ixia_port: str, otg_location: str):
    if otg:
        # OTG: the port-location string doubles as the logical interface
        # name (matching taac/otg/otg_basic_l3_test_config.py).
        return DirectIxiaConnection(
            interface=otg_location,
            ixia_port=ixia_port,
            is_logical_port=True,
            port_location=otg_location,
        )
    return DirectIxiaConnection(
        interface=dut_interface,
        ixia_port=ixia_port,
        ixia_chassis_ip=tb.IXIA_CHASSIS,
    )


def _port_config(dut: str, iface: str, tgen_ip: str, dut_gw: str) -> BasicPortConfig:
    return BasicPortConfig(
        endpoint=f"{dut}:{iface}",
        device_group_configs=[
            DeviceGroupConfig(
                device_group_index=0,
                multiplier=1,
                v4_addresses_config=IpAddressesConfig(
                    starting_ip=tgen_ip,
                    mask=tb.PREFIX_LEN,
                    gateway_starting_ip=dut_gw,
                ),
            )
        ],
    )


def _build(otg: bool) -> TestConfig:
    dut = tb.SWITCH01_DEVICE_NAME
    conn_a = _connection(
        otg, tb.TGEN_PORT_A_DUT_INTERFACE, tb.IXIA_PORT_A, tb.OTG_PORT_A_LOCATION
    )
    conn_b = _connection(
        otg, tb.TGEN_PORT_B_DUT_INTERFACE, tb.IXIA_PORT_B, tb.OTG_PORT_B_LOCATION
    )
    iface_a = conn_a.interface
    iface_b = conn_b.interface

    return TestConfig(
        name="traffic_forwarding",
        basset_pool="",
        traffic_generator_backend=(
            TrafficGeneratorBackend.OTG if otg else TrafficGeneratorBackend.RESTPY
        ),
        # No BGP protocol layer — only IPv4/ARP; skip the protocol-up
        # verification (IxNetwork-only; the OTG backend resolves ARP in its
        # own two-phase config push).
        skip_ixia_protocol_verification=True,
        endpoints=[
            Endpoint(
                name=dut,
                dut=True,
                ixia_ports=[iface_a, iface_b],
                mac_address=tb.SWITCH01_LOCAL_MAC_ADDRESS,
                direct_ixia_connections=[conn_a, conn_b],
            )
        ],
        basic_port_configs=[
            _port_config(dut, iface_a, tb.PORT_A_TGEN_IP, tb.PORT_A_DUT_GW),
            _port_config(dut, iface_b, tb.PORT_B_TGEN_IP, tb.PORT_B_DUT_GW),
        ],
        basic_traffic_item_configs=[
            BasicTrafficItemConfig(
                name=tb.TRAFFIC_ITEM_NAME,
                bidirectional=True,
                line_rate=tb.TRAFFIC_LINE_RATE_PERCENT,
                src_endpoints=[
                    TrafficEndpoint(
                        name=f"{dut}:{iface_a}",
                        device_group_index=0,
                    )
                ],
                dest_endpoints=[
                    TrafficEndpoint(
                        name=f"{dut}:{iface_b}",
                        device_group_index=0,
                    )
                ],
                traffic_type=ixia_types.TrafficType.IPV4,
                tracking_types=[ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM],
            )
        ],
        playbooks=[
            Playbook(
                name="traffic_forwarding",
                stages=[
                    create_steps_stage(
                        steps=[
                            # Dwell while traffic runs so the loss check
                            # evaluates a real tx window (mirrors
                            # taac/otg/otg_basic_l3_test_config.py) and the
                            # collector-backed CPU/memory postchecks get a
                            # non-empty sample window.
                            create_longevity_step(
                                duration=tb.TRAFFIC_HOLD_SEC,
                                description="Traffic dwell window",
                            )
                        ]
                    )
                ],
                postchecks=[
                    create_traffic_item_packet_loss_check(
                        traffic_item_names=[tb.TRAFFIC_ITEM_NAME],
                        max_packet_loss_percent=0.0,
                    ),
                    # OSS collector-backed: forwarding at 10% line rate must
                    # not stress the control plane — CPU/memory within
                    # thresholds, services active, no unclean exits.
                    create_systemctl_active_state_check(
                        services_json=DEFAULT_SERVICE_NAMES
                    ),
                    create_unclean_exit_check(),
                    create_cpu_utilization_check(),
                    create_memory_utilization_check(),
                ],
            )
        ],
        host_os_type_map={dut: DeviceOsType.FBOSS},
        startup_checks=[],
    )


TRAFFIC_FORWARDING_RESTPY_TEST_CONFIG = _build(otg=False)
TRAFFIC_FORWARDING_OTG_TEST_CONFIG = _build(otg=True)

TEST_CONFIG = (
    TRAFFIC_FORWARDING_OTG_TEST_CONFIG
    if os.environ.get("TAAC_TGEN_BACKEND", "").lower() == "otg"
    else TRAFFIC_FORWARDING_RESTPY_TEST_CONFIG
)
