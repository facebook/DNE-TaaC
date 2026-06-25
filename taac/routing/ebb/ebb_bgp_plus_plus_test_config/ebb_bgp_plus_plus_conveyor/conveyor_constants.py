# pyre-unsafe
"""
Common constants for EBB BGP++ Conveyor Test Configurations.

This module contains reusable constants that are shared across all EBB BGP++
conveyor test configurations. Device-specific values (like IXIA interface
mappings and chassis IPs) should remain in individual test config files.

Constants included:
- BGP peer group names (standard EBB naming)
- BGP AS numbers
- BGP peer scale values
- Drain counts for testing
- Default BGP profile
- IXIA network configurations (IP prefixes for BGP peers)
"""

import typing as t

from taac.constants import BgpPlusPlusProfile


# =============================================================================
# BGP Peer Group Names (Standard EBB naming convention)
# =============================================================================
PEERGROUP_IBGP_V6 = "EB-EB-V6"
PEERGROUP_IBGP_V4 = "EB-EB-V4"
PEERGROUP_EBGP_V6 = "EB-FA-V6"
PEERGROUP_EBGP_V4 = "EB-FA-V4"
PEERGROUP_BGP_MON = "BGP-MON"


# =============================================================================
# BGP AS Numbers (Standard EBB AS numbers)
# =============================================================================
IBGP_REMOTE_AS = 64981
EBGP_REMOTE_AS = 65334
BGP_MON_REMOTE_AS = 64001


# =============================================================================
# BGP Peer Scale (Standard EBB full-scale values)
# =============================================================================
EBGP_PEER_COUNT_V4 = 140
EBGP_PEER_COUNT_V6 = 140
BGP_MON_PEER_COUNT = 2
"""
Arista EOS limits each routed interface to 500 secondary IPv4 addresses:

    switch(config-if-EtX/Y/Z)# ip address A.B.C.D/31 secondary
    % This interface already has 500 secondary addresses assigned

Within a plane, an EBB router peers with devices across DC sites and
Mid-Point (MP) sites. Each site has up to 4 devices. IXIA simulates
these peers with one IPv4 secondary address per peer on the iBGP
interface.

Total IPv4 secondaries = IBGP_PEER_SCALE_PER_PLANE * 4 devices * 2 (DC + MP).
At 62 sites: 62 * 4 * 2 = 496 (fits). At 63 sites: 63 * 4 * 2 = 504
(exceeds the 500 limit, causing ARP resolution failures for the last
4 peers).
"""
IBGP_PEER_SCALE_PER_PLANE = 62


# =============================================================================
# Drain Counts for Testing
# =============================================================================
EBGP_PEER_TO_DRAIN = 4
IBGP_PEER_TO_DRAIN_PER_PLANE = 2

# Number of iBGP DC ("Remote EB") planes with a carved DRAIN device group when
# `drain=True` is set in `create_ebb_scale_basic_port_configs`. MP planes do
# NOT have a DRAIN variant — see `ixia_config_for_ebb_scale.py` lines 115-160
# (V6) and 245-290 (V4) where the DRAIN DG is only created in the DC branch
# for each plane (1..4).
IBGP_DC_PLANE_COUNT = 4

# Total carved-out drain pool peer count under `drain=True`.
# = eBGP DRAIN (V4 + V6) + iBGP DC DRAIN per plane × planes × (V4 + V6)
# = 4 × 2 + 2 × 4 × 2 = 8 + 16 = 24
#
# These peers START in TBgpPeerState.IDLE by design — the FAUU / Plane drain
# stages activate them mid-test. The pre-test BGP_SESSION_ESTABLISH_CHECK
# must therefore subtract this count from the expected established session
# count to avoid asserting that the drain pool is up at startup (T-TBD).
DRAIN_POOL_PEER_COUNT = (
    EBGP_PEER_TO_DRAIN * 2 + IBGP_PEER_TO_DRAIN_PER_PLANE * IBGP_DC_PLANE_COUNT * 2
)


# =============================================================================
# Default BGP Profile
# =============================================================================
DEFAULT_PROFILE = BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R


# =============================================================================
# IXIA Network Configurations (Standard EBB IP prefixes for BGP peers)
# =============================================================================

# eBGP IXIA network prefixes
IXIA_EBGP_IC_PARENT_NETWORK_V6 = "2401:db00:e50d:11:8"
IXIA_EBGP_IC_PARENT_NETWORK_V4 = "10.163.28"

# iBGP IXIA network prefixes - DC planes (1-4)
IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1 = "2401:db00:e50d:11:9"
IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE2 = "2401:db00:e50d:11:10"
IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE3 = "2401:db00:e50d:11:11"
IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE4 = "2401:db00:e50d:11:12"
IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE1 = "10.164.28"
IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE2 = "10.165.28"
IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE3 = "10.166.28"
IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE4 = "10.167.28"

# iBGP IXIA network prefixes - MP planes (1-4)
IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE1 = "2401:db00:e50d:11:13"
IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE2 = "2401:db00:e50d:11:14"
IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE3 = "2401:db00:e50d:11:15"
IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE4 = "2401:db00:e50d:11:16"
IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE1 = "10.168.28"
IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE2 = "10.169.28"
IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE3 = "10.170.28"
IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE4 = "10.171.28"

# BGP MON IXIA network prefix
IXIA_BGP_MON_IC_PARENT_NETWORK = "2401:db00:e50d:22:a"

# Interface IP configuration start offsets
IXIA_IPV4_START_OFFSET = 10
IXIA_IPV6_START_OFFSET = 16


# =============================================================================
# Port-Channel Configuration (for OpenR nexthop)
# =============================================================================
OPENR_PORT_CHANNEL = "Port-Channel100211"
OPENR_PORT_CHANNEL_ID = 100211
OPENR_PORT_CHANNEL_MEMBER = "Ethernet3/9/1"
OPENR_PORT_CHANNEL_IPV4 = "10.131.97.236/31"
OPENR_PORT_CHANNEL_IPV6 = "2620:0:1cff:dead:bef1:100:13:3a0/127"
OPENR_PORT_CHANNEL_LINK_LOCAL = "fe80::eba:a7f:fd00/64"

# OpenR nexthop configuration derived from Port-Channel 100211
OPENR_LOCAL_LINK = {
    "ipv4": "10.131.97.236",
    "ipv6": "fe80::eba:a7f:fd00",
    "ifName": "po100211",
    "weight": 0,
    "metric": 10,
}

OPENR_OTHER_LINK = {
    "ipv4": "10.131.97.237",
    "ipv6": "fe80::eba:a7f:fd01",
    "ifName": "po100211",
    "weight": 0,
    "metric": 10,
}


# =============================================================================
# BGP++ Daemon Names (for arista_daemon_control tasks)
# Includes Openr for conveyor profiles that require it.
# =============================================================================
BGPCPP_DAEMONS = [
    "Bgp",
    "FibAgent",
    "FibAgentBgp",
    "FibBgpGrpc",
    "FibGrpc",
    "Openr",
    "RouteGrpc",
]


# =============================================================================
# BGP++ Update Group Config (UpdateGroupConfig thrift struct, D100093369)
# Field names are camelCase to match the on-device JSON serialization of the
# thrift struct (UpdateGroupConfig in bgp_config.thrift).
# Used by the *_UPDATE_GROUP variants of the conveyor test configs.
# =============================================================================
UPDATE_GROUP_ALLOW_SLOW_PEER_DETACH = False
UPDATE_GROUP_SLOW_PEER_TIME_THRESHOLD_MS = 50000
UPDATE_GROUP_SLOW_PEER_BLOCK_COUNT_THRESHOLD = 10
UPDATE_GROUP_SLOW_PEER_BLOCK_COUNT_WINDOW_MS = 1000
UPDATE_GROUP_ENABLE_SERIALIZE_GROUP_PDU = True

UPDATE_GROUP_CONFIG: t.Dict[str, t.Any] = {
    "allowSlowPeerDetach": UPDATE_GROUP_ALLOW_SLOW_PEER_DETACH,
    "slowPeerTimeThresholdMs": UPDATE_GROUP_SLOW_PEER_TIME_THRESHOLD_MS,
    "slowPeerBlockCountThreshold": UPDATE_GROUP_SLOW_PEER_BLOCK_COUNT_THRESHOLD,
    "slowPeerBlockCountWindowMs": UPDATE_GROUP_SLOW_PEER_BLOCK_COUNT_WINDOW_MS,
    "enableSerializeGroupPdu": UPDATE_GROUP_ENABLE_SERIALIZE_GROUP_PDU,
}


# =============================================================================
# BGP++ Supporting Agent Config Files (required for FibAgent daemons)
# Deployed via embedded base64 to avoid arista_create_file_from_config
# which silently fails on some devices.
# Generated from: configerator/raw_configs/taac/ebb_ci_cd_configs/
# To regenerate: cat <file> | base64 -w0
# =============================================================================
FIBAGENT_BGP_CONF_DEVICE_PATH = "/mnt/fb/agent_configs/fib_agent_bgp.conf"
FIBAGENT_BGP_CONF_B64 = "eyIxIjp7InJlYyI6eyIxIjp7ImkzMiI6NjAxMDB9LCIyIjp7ImkzMiI6NDh9LCIzIjp7ImkzMiI6NX0sIjQiOnsiaTMyIjoxNX0sIjUiOnsic3RyIjoiIn0sIjYiOnsic3RyIjoiL3BlcnNpc3Qvc2VjdXJlL2NhcGkucGVtIn0sIjciOnsic3RyIjoiL3BlcnNpc3Qvc2VjdXJlL2NhcGlrZXkucGVtIn0sIjgiOnsic3RyIjoiL21udC9mYi9jZXJ0cy9BcmlzdGFGaWJBZ2VudF9zZXJ2ZXIucGVtIn0sIjkiOnsiaTMyIjo1OTEzfSwiMTAiOnsic3RyIjoiL3Zhci9mYWNlYm9vay9yb290Y2FuYWwvY2EucGVtIn0sIjExIjp7InRmIjoxfSwiMTIiOnsidGYiOjF9LCIxMyI6eyJzdHIiOiJGaWJTZXJ2aWNlIn0sIjE0Ijp7ImkzMiI6MX0sIjE1Ijp7ImkzMiI6MX0sIjE2Ijp7InRmIjoxfSwiMTciOnsidGYiOjF9LCIxOCI6eyJzdHIiOiIvdXNyL2ZhY2Vib29rL3RocmlmdF9hY2xzL0ZpYkFnZW50X2xhYi5qc29uIn0sIjE5Ijp7InN0ciI6Ii91c3IvZmFjZWJvb2svdGhyaWZ0X2FjbHMvYXV0aF9raWxsX3N3aXRjaF9maWxlIn0sIjIwIjp7InRmIjowfSwiMjEiOnsiaTMyIjo3MjAwfSwiMjIiOnsidGYiOjF9LCIyMyI6eyJ0ZiI6MX0sIjI0Ijp7ImkzMiI6LTF9LCIyNSI6eyJzdHIiOiJGaWIgYWdlbnQgaXMgZGVzaWduZWQgdG8gZXhlY3V0ZSByZW1vdGUgcHJvZ3JhbW1pbmcgcmVxdWVzdHMgZnJvbSBPcGVuL1IgdG8gY2hhbmdlIE9wZW4vUiByb3V0ZXMgYWRtaW4gZGlzdGFuY2VzIHRvIGluZmx1ZW5jZSBiZXN0IHBhdGggc2VsZWN0aW9ucy4ifSwiMjYiOnsiaTMyIjo5NTQ1fSwiMjciOnsic3RyIjoiIn19fSwiMiI6eyJ0ZiI6MH0sIjMiOnsidGYiOjF9LCI0Ijp7ImkzMiI6Nzg3fSwiNSI6eyJpMzIiOjIwMH0sIjYiOnsiaTMyIjo0MH0sIjciOnsidGYiOjF9fQo="  # noqa: E501
FIBAGENT_BGP_CONF_DEPLOY_CMD = (
    f"bash echo '{FIBAGENT_BGP_CONF_B64}' | base64 -d > {FIBAGENT_BGP_CONF_DEVICE_PATH}"
)

FIBAGENT_CONF_DEVICE_PATH = "/mnt/fb/agent_configs/fib_agent.conf"
FIBAGENT_CONF_B64 = "eyIxIjp7InJlYyI6eyIxIjp7ImkzMiI6NjAxMDB9LCIyIjp7ImkzMiI6NDh9LCIzIjp7ImkzMiI6NX0sIjQiOnsiaTMyIjoxNX0sIjUiOnsic3RyIjoiIn0sIjYiOnsic3RyIjoiL3BlcnNpc3Qvc2VjdXJlL2NhcGkucGVtIn0sIjciOnsic3RyIjoiL3BlcnNpc3Qvc2VjdXJlL2NhcGlrZXkucGVtIn0sIjgiOnsic3RyIjoiL21udC9mYi9jZXJ0cy9BcmlzdGFGaWJBZ2VudF9zZXJ2ZXIucGVtIn0sIjkiOnsiaTMyIjo1OTEyfSwiMTAiOnsic3RyIjoiL3Zhci9mYWNlYm9vay9yb290Y2FuYWwvY2EucGVtIn0sIjExIjp7InRmIjoxfSwiMTIiOnsidGYiOjF9LCIxMyI6eyJzdHIiOiJGaWJTZXJ2aWNlIn0sIjE0Ijp7ImkzMiI6MX0sIjE1Ijp7ImkzMiI6MX0sIjE2Ijp7InRmIjoxfSwiMTciOnsidGYiOjF9LCIxOCI6eyJzdHIiOiIvdXNyL2ZhY2Vib29rL3RocmlmdF9hY2xzL0ZpYkFnZW50X2xhYi5qc29uIn0sIjE5Ijp7InN0ciI6Ii91c3IvZmFjZWJvb2svdGhyaWZ0X2FjbHMvYXV0aF9raWxsX3N3aXRjaF9maWxlIn0sIjIwIjp7InRmIjowfSwiMjEiOnsiaTMyIjo3MjAwfSwiMjIiOnsidGYiOjF9LCIyMyI6eyJ0ZiI6MX0sIjI0Ijp7ImkzMiI6LTF9LCIyNSI6eyJzdHIiOiJGaWIgYWdlbnQgaXMgZGVzaWduZWQgdG8gZXhlY3V0ZSByZW1vdGUgcHJvZ3JhbW1pbmcgcmVxdWVzdHMgZnJvbSBPcGVuL1IgdG8gY2hhbmdlIE9wZW4vUiByb3V0ZXMgYWRtaW4gZGlzdGFuY2VzIHRvIGluZmx1ZW5jZSBiZXN0IHBhdGggc2VsZWN0aW9ucy4ifSwiMjYiOnsiaTMyIjo5NTQ0fSwiMjciOnsic3RyIjoiIn19fSwiMiI6eyJ0ZiI6MH0sIjMiOnsidGYiOjF9LCI0Ijp7ImkzMiI6Nzg2fSwiNSI6eyJpMzIiOjEwfSwiNiI6eyJpMzIiOjQwfSwiNyI6eyJ0ZiI6MH19"  # noqa: E501
FIBAGENT_CONF_DEPLOY_CMD = (
    f"bash echo '{FIBAGENT_CONF_B64}' | base64 -d > {FIBAGENT_CONF_DEVICE_PATH}"
)


# =============================================================================
# Control Plane ACLs
# These ACLs permit BGP++, FibAgent, and other control plane traffic.
# =============================================================================
ACL_COMMANDS = (
    "configure\n"
    "ipv6 access-list aiv6-control-plane-acl\n"
    "counters per-entry\n"
    "10 permit icmpv6 any any\n"
    "20 permit ipv6 any any tracked\n"
    "30 permit udp any any eq bfd hop-limit eq 255\n"
    "40 permit udp any any eq bfd-echo hop-limit eq 254\n"
    "50 permit udp any any eq multihop-bfd\n"
    "60 permit udp any any eq micro-bfd\n"
    "70 permit udp any any eq sbfd\n"
    "80 permit udp any eq sbfd any eq sbfd-initiator\n"
    "90 permit 51 any any\n"
    "100 permit 50 any any\n"
    "110 permit tcp any any eq ssh www snmp bgp https gnmi\n"
    "120 permit udp any any eq bootps bootpc ntp snmp\n"
    "130 permit tcp any any range 5900 5910\n"
    "140 permit tcp any any range 50000 50100\n"
    "150 permit udp any any range 51000 51100\n"
    "160 permit udp any any eq dhcpv6-client dhcpv6-server\n"
    "170 permit tcp any eq bgp any\n"
    "180 permit tcp any any eq 6040\n"
    "200 permit tcp any any eq 9200\n"
    "245 permit tcp any any eq 6909\n"
    "300 permit tcp any any eq 2018\n"
    "310 permit udp any any eq 6666\n"
    "320 permit tcp any any eq 5921\n"
    "340 permit tcp any any eq 10701\n"
    "350 permit tcp any any eq 1610\n"
    "360 permit tcp any any eq 12112\n"
    "370 permit tcp any any range 5911 5919\n"
    "!\n"
    "ipv6 access-list ebbv6-control-plane-acl\n"
    "counters per-entry\n"
    "10 permit icmpv6 any any\n"
    "20 permit ipv6 any any tracked\n"
    "30 permit udp any any eq bfd hop-limit eq 255\n"
    "40 permit udp any any eq bfd-echo hop-limit eq 254\n"
    "50 permit udp any any eq multihop-bfd\n"
    "60 permit udp any any eq micro-bfd\n"
    "70 permit ospf any any\n"
    "80 permit 51 any any\n"
    "90 permit 50 any any\n"
    "100 permit tcp any any eq ssh snmp bgp https 1610\n"
    "110 permit udp any any eq bootps bootpc ntp snmp\n"
    "120 permit tcp any any eq mlag hop-limit eq 255\n"
    "130 permit udp any any eq mlag hop-limit eq 255\n"
    "140 permit tcp any any range 5900 5910\n"
    "145 permit tcp any any range 5911 5919\n"
    "150 permit tcp any any range 50000 50100\n"
    "160 permit udp any any range 51000 51100\n"
    "170 permit udp any any eq dhcpv6-client dhcpv6-server\n"
    "180 permit tcp any eq bgp any\n"
    "190 permit tcp any any eq nat hop-limit eq 255\n"
    "200 permit udp any any eq nat hop-limit eq 255\n"
    "210 permit rsvp any any\n"
    "220 permit pim any any\n"
    "230 permit udp any any eq 6666\n"
    "240 permit tcp any any eq 2018\n"
    "245 permit tcp any any eq 6909\n"
    "250 permit tcp any any eq 6666\n"
    "260 permit tcp any any eq 60001\n"
    "270 permit tcp any any eq 60002\n"
    "280 permit tcp any any eq 60006\n"
    "290 permit tcp any any eq 60009\n"
    "300 permit tcp any any eq 60100\n"
    "310 permit tcp any any eq 60101\n"
    "330 permit udp any eq lsp-ping any\n"
    "340 permit tcp any any eq 9543\n"
    "!\n"
    "ip access-list ebb-control-plane-acl\n"
    "counters per-entry\n"
    "10 permit icmp any any\n"
    "20 permit ip any any tracked\n"
    "30 permit udp any any eq bfd ttl eq 255\n"
    "40 permit udp any any eq bfd-echo ttl eq 254\n"
    "50 permit udp any any eq multihop-bfd\n"
    "60 permit udp any any eq micro-bfd\n"
    "70 permit ospf any any\n"
    "80 permit tcp any any eq ssh snmp bgp https msdp ldp netconf-ssh gnmi\n"
    "90 permit udp any any eq bootps bootpc ntp snmp rip ldp\n"
    "100 permit tcp any any eq mlag ttl eq 255\n"
    "110 permit udp any any eq mlag ttl eq 255\n"
    "120 permit vrrp any any\n"
    "130 permit ahp any any\n"
    "140 permit pim any any\n"
    "150 permit igmp any any\n"
    "160 permit tcp any any range 5900 5910\n"
    "165 permit tcp any any range 5911 5919\n"
    "170 permit tcp any any range 50000 50100\n"
    "180 permit udp any any range 51000 51100\n"
    "190 permit tcp any any eq 3333\n"
    "200 permit tcp any any eq nat ttl eq 255\n"
    "210 permit tcp any eq bgp any\n"
    "220 permit rsvp any any\n"
    "230 permit tcp any any eq 6666\n"
    "240 permit tcp any any eq 60101\n"
    "245 permit tcp any any eq 6909\n"
    "260 permit udp any eq lsp-ping any\n"
    "!\n"
    "end"
)
