# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""Generic Wedge800 1-RSW device + topology constants.
Expected to be filled in by vendors.

SINGLE SOURCE OF TRUTH for everything device-specific about the OSS
single-DUT 1-RSW testbed: hostname, MAC, IXIA wiring, and the per-platform
CPU-punt threshold overrides. Follows the statically-defined-topology
pattern of ``taac/testconfigs/npi/w800_constants.py`` (same DUT, different
test family — values below are cross-checked against that file and
``taac/oss_topology_info/circuit_info.csv``; kept self-contained so the RSW
suite carries no npi import).

Consumed by ``taac/testconfigs/oss/single_dut_rsw_config.py``. Retargeting
the RSW suite to a different DUT should only require edits here (plus the
DUT-side agent.conf/bgpd.conf provisioning documented in
``single_dut_rsw_test_config.py``).
"""

# ---------------------------------------------------------------------------
# Device identity
# ---------------------------------------------------------------------------
RSW_DEVICE_NAME = "dut123"
RSW_LOCAL_MAC_ADDRESS = "00:00:00:00:00:00"

# ---------------------------------------------------------------------------
# IXIA wiring
# ---------------------------------------------------------------------------
RSW_IXIA_CHASSIS = "ixia123"
RSW_IXIA_DOWNLINK_INTERFACE = "eth1/1/1"
RSW_IXIA_DOWNLINK_PORT = "1/1"
RSW_IXIA_UPLINK_INTERFACE = "eth1/2/1"
RSW_IXIA_UPLINK_PORT = "1/2"

# ---------------------------------------------------------------------------
# CPU-punt threshold overrides (platform-specific)
# ---------------------------------------------------------------------------
# HIGH-queue min-pps overrides for the CPU-punt playbooks on this wedge800
# DUT. Its CoPP has high-rate policers only for IPv6 network control, not
# IPv4 ARP — ARP is trapped to the high queue but only trickles at ~1pps
# regardless of offered load (no agent.conf lever exists: the CoPP ACL table
# can't qualify on EtherType). The int-typed thrift map can't express a
# fractional floor and 1 would still fail at ~0.86pps, so the two ARP
# playbooks use 0: the check independently fails a HIGH-queue that saw NO
# packets, so 0 still asserts "ARP was punted to the high queue" without a
# strict pps floor. Other platforms keep the reference 10pps default.
RSW_CPU_PUNT_MIN_PPS_OVERRIDES = {
    "test_arp_traffic_punted_to_cpu_high_queue": 0,
    "test_arp_response_traffic_punted_to_cpu_high_queue": 0,
}
