# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""Snake test config.

Topology is derived from circuit_info.csv via ConfigTopology at runtime:
  - TGEN links become the snake IXIA endpoints
  - SNAKE links are self-loopback pairs
  - DUT hostname comes from --dut CLI flag

Canonical invocation:

TAAC_SSH_USER=root TAAC_SSH_PASSWORD=root \
./docker/run_taac_docker.sh run python3 -m taac.runner.oss_entry_point \
  --test-configs /workspace/taac/testconfigs/oss/snake_config.py \
  --dut <dut> \
  --ixia-api-server <ixia> \
  --circuit-info-csv /workspace/taac/oss_topology_info/circuit_info.csv \
  --device-info-csv /workspace/taac/oss_topology_info/device_info.csv \
  --playbook test_one_min_longevity
"""

import os

from taac.runner.testbed_topology import (
    ConfigTopology,
    LinkType,
    topology_aware,
)
from taac.testconfigs.snake.test_test_config import (
    gen_snake_test_config,
)
from taac.test_as_a_config import types as taac_types


@topology_aware
def test_config(topology: ConfigTopology):
    dut_name = (
        topology.links[0].local_host
        if topology.links
        else os.environ.get("TAAC_DUT", "switch01.example.com")
    )

    tgen_links = [link for link in topology.links if link.link_type == LinkType.TGEN]

    if len(tgen_links) < 2:
        _base = gen_snake_test_config(
            name="OSS_SNAKE",
            basset_pool="",
            hostname=dut_name,
            snake_configs=[
                taac_types.SnakeConfig(
                    source=f"{dut_name}:eth1/1/1",
                    destination=f"{dut_name}:eth1/2/1",
                    source_ip="5000:1::1/64",
                    destination_ip="5000:1::2/64",
                ),
            ],
            ixia_ports=["eth1/1/1", "eth1/2/1"],
            skip_lldp_check=True,
            use_ipv6_ping=False,
        )
        return _base(ptp_configs=[])

    source_link = tgen_links[0]
    dest_link = tgen_links[1]

    ixia_connections = [
        taac_types.DirectIxiaConnection(
            interface=link.local_port,
            ixia_port=link.remote_port,
            ixia_chassis_ip=link.remote_host,
        )
        for link in tgen_links[:2]
    ]

    _base = gen_snake_test_config(
        name="OSS_SNAKE",
        basset_pool="",
        hostname=dut_name,
        snake_configs=[
            taac_types.SnakeConfig(
                source=f"{dut_name}:{source_link.local_port}",
                destination=f"{dut_name}:{dest_link.local_port}",
                source_ip="5000:1::1/64",
                destination_ip="5000:1::2/64",
            ),
        ],
        direct_ixia_connections=ixia_connections,
        ixia_ports=[source_link.local_port, dest_link.local_port],
        line_rate=int(os.environ.get("TAAC_LINE_RATE", "50")),
        iteration=int(os.environ.get("TAAC_ITERATION", "10")),
        use_ipv6_ping=False,
    )
    # TODO: PTP disabled — IXIA chassis needs PTP license
    return _base(ptp_configs=[])
