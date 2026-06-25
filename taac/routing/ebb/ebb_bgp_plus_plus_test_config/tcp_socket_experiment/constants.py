# pyre-unsafe
"""
Constants for TCP Socket Experiment test configurations.

This module contains all configurable parameters for the BGP peering
experiments between bag012.ash6 (BGP++) and bag013.ash6 (ar-bgp / EOS BGP).

Topology:
    bag012.ash6 (EOS BGP++ / DUT)
        - Runs Meta's BGP++ (bgpcpp) — peers configured via /mnt/flash/bgpcpp_config
        IXIA connections (ixia11.netcastle.ash6):
            - 7/7 → <configurable interface>
            - 7/8 → <configurable interface>
            - 8/1 → <configurable interface>

    bag013.ash6 (ar-bgp / standard EOS BGP)
        - Runs native Arista EOS BGP — peers configured via CLI (router bgp / neighbor)
        IXIA connections (ixia11.netcastle.ash6):
            - 8/2 → Et3/36/1
            - 8/3 → Et3/36/3
            - 8/4 → Et3/36/5

    Inter-device links (LLDP verified):
        bag013:Et3/1/1 ↔ bag012:Ethernet3/1/1
        bag013:Et3/2/1 ↔ bag012:Ethernet3/2/1

Test Cases:
    Case 1: 140 eBGP sessions (bag013 ↔ bag012) + 1 IXIA→bag012 with 15K prefixes
            IXIA injects 15K routes into bag012 (BGP++), which redistributes
            to 140 eBGP sessions towards bag013 (ar-bgp).

    Case 2: 1 eBGP session (bag013 ↔ bag012) + 140 IXIA→bag012 sessions
            IXIA injects 15K routes into bag013 (ar-bgp), which advertises
            them to bag012 (BGP++) via 1 eBGP session. bag012 then
            redistributes to 140 IXIA peers.

Peer Configuration Methods:
    bag012 (BGP++):   /mnt/flash/bgpcpp_config (JSON file, deployed via setup tasks)
    bag013 (ar-bgp):  Standard EOS CLI (router bgp <ASN> / neighbor commands)
"""

# =============================================================================
# Device Names
# =============================================================================
BAG012_DEVICE_NAME = "bag012.ash6"  # BGP++ device (DUT)
BAG013_DEVICE_NAME = "bag013.ash6"  # ar-bgp (EOS BGP) device


# =============================================================================
# IXIA Chassis
# =============================================================================
IXIA_CHASSIS = "2401:db00:2066:303b::3001"  # ixia11.netcastle.ash6


# =============================================================================
# IXIA Port Mappings — bag012.ash6 (BGP++)
# Update these interface names to match actual wiring on bag012
# =============================================================================
BAG012_IXIA_INTERFACE_1 = "Ethernet3/36/1"
BAG012_IXIA_INTERFACE_2 = "Ethernet3/36/3"
BAG012_IXIA_INTERFACE_3 = "Ethernet3/36/5"

BAG012_IXIA_PORT_1 = "7/7"
BAG012_IXIA_PORT_2 = "7/8"
BAG012_IXIA_PORT_3 = "8/1"


# =============================================================================
# IXIA Port Mappings — bag013.ash6 (ar-bgp)
# =============================================================================
BAG013_IXIA_INTERFACE_1 = "Ethernet3/36/1"
BAG013_IXIA_INTERFACE_2 = "Ethernet3/36/3"
BAG013_IXIA_INTERFACE_3 = "Ethernet3/36/5"

BAG013_IXIA_PORT_1 = "8/2"
BAG013_IXIA_PORT_2 = "8/3"
BAG013_IXIA_PORT_3 = "8/4"


# =============================================================================
# Inter-device Interconnect Interfaces (bag012 ↔ bag013 direct links)
# Verified via LLDP:
#   bag013:Et3/1/1 ↔ bag012:Ethernet3/1/1
#   bag013:Et3/2/1 ↔ bag012:Ethernet3/2/1
# Two physical links available — 140 eBGP sessions split across both (70 each)
# =============================================================================
BAG012_INTERCONNECT_INTERFACES = ["Ethernet3/1/1", "Ethernet3/2/1"]
BAG013_INTERCONNECT_INTERFACES = ["Ethernet3/1/1", "Ethernet3/2/1"]
EBGP_SESSIONS_PER_LINK = 70  # 140 total / 2 links


# =============================================================================
# BGP AS Numbers
# BAG012_EOS_BGP_AS: native EOS BGP AS on bag012 (for 'router bgp X / shutdown')
# BAG012_BGPCPP_AS: BGP++ AS from bgpcpp_config (local_as_4_byte)
#   This comes from the base config and should NOT be changed.
# =============================================================================
BAG012_EOS_BGP_AS = 65012  # native EOS BGP AS (for shutdown only)
BAG012_BGPCPP_AS = 64981  # BGP++ AS from bgpcpp_config base template
BAG012_LOCAL_AS = BAG012_EOS_BGP_AS  # backward com pat alias (used by cleanup)
BAG013_LOCAL_AS = 65013  # ar-bgp device local AS (existing on device)
IXIA_AS = 65300  # IXIA simulated AS


# =============================================================================
# BGP Router IDs
# =============================================================================
BAG012_ROUTER_ID = "10.46.0.12"  # existing on device
BAG013_ROUTER_ID = "10.46.0.13"  # existing on device


# =============================================================================
# BGP Peer Group Names — BGP++ (bag012, bgpcpp_config)
# These MUST match the standard BGP++ peer group naming convention.
# See taac/ebb_ci_cd_configs/ebb_full_scale_bgpcpp_config for reference.
#
# FA = Fabric-Aggregator peering (eBGP between tiers: bag012 ↔ bag013)
# EB = Edge-Bridge peering (iBGP within tier: IXIA simulating EB peers)
# =============================================================================
# For device-to-device eBGP sessions (bag012 ↔ bag013)
BGPCPP_PEERGROUP_EBGP_V6 = "EB-FA-V6"
BGPCPP_PEERGROUP_EBGP_V4 = "EB-FA-V4"
BGPCPP_EGRESS_POLICY_EBGP = "EB-FA-OUT"

# For IXIA sessions to bag012 (simulating iBGP / EB peers)
BGPCPP_PEERGROUP_IXIA_V6 = "EB-EB-V6"
BGPCPP_PEERGROUP_IXIA_V4 = "EB-EB-V4"
BGPCPP_EGRESS_POLICY_IXIA = "EB-EB-OUT"


# =============================================================================
# BGP Peer Group Names — ar-bgp (bag013, EOS CLI)
# These are local to bag013's EOS BGP config. They don't need to match BGP++.
# =============================================================================
ARBGP_PEERGROUP_EBGP_V6 = "TCP-EXP-EBGP-V6"
ARBGP_PEERGROUP_EBGP_V4 = "TCP-EXP-EBGP-V4"
ARBGP_PEERGROUP_IXIA_V6 = "TCP-EXP-IXIA-V6"
ARBGP_PEERGROUP_IXIA_V4 = "TCP-EXP-IXIA-V4"


# =============================================================================
# Scale Parameters (configurable)
# EBGP_SESSION_COUNT = 140 means 140 IPv4 + 140 IPv6 = 280 total BGP sessions
# =============================================================================
EBGP_SESSION_COUNT = 140  # 140 V4 + 140 V6 = 280 total sessions between bag012 ↔ bag013
IXIA_PREFIX_COUNT = 15000  # Number of prefixes injected by IXIA


# =============================================================================
# IP Addressing — Inter-device eBGP (bag012 ↔ bag013)
# Using /127 subnets, incrementing by 2 for each session
# bag012 gets even addresses (.10, .12, .14, ...), bag013 gets odd (.11, .13, .15, ...)
# Separate IPv4 base per link to avoid overflow past .255
# Link 1 (Et3/1/1): 10.200.28.x (70 peers = .10 to .149)
# Link 2 (Et3/2/1): 10.200.29.x (70 peers = .10 to .149)
# =============================================================================
INTERCONNECT_IPV6_BASE = "2401:db00:e700:11:8"
INTERCONNECT_IPV4_BASES = ["10.200.28", "10.200.29"]  # One per link
INTERCONNECT_IPV6_START_OFFSET = 10  # First address: <base>::10
INTERCONNECT_IPV4_START_OFFSET = 10  # First address: <base>.10


# =============================================================================
# IP Addressing — IXIA ↔ bag012 (BGP++)
# =============================================================================
IXIA_BAG012_IPV6_BASE = "2401:db00:e700:11:9"
IXIA_BAG012_IPV4_BASE = "10.201.28"


# =============================================================================
# IP Addressing — IXIA ↔ bag013 (ar-bgp) — used in Case 2 for route injection
# =============================================================================
IXIA_BAG013_IPV6_BASE = "2401:db00:e700:11:10"
IXIA_BAG013_IPV4_BASE = "10.202.28"


# =============================================================================
# Route Prefix Ranges (15K routes advertised by IXIA)
# =============================================================================
ROUTE_PREFIX_START_V6 = "2620:10d:c0a8::"
ROUTE_PREFIX_START_V4 = "192.168.0.0"
ROUTE_PREFIX_LEN_V6 = 48
ROUTE_PREFIX_LEN_V4 = 24
ROUTE_PREFIX_STEP_V6 = "0:0:1::"
ROUTE_PREFIX_STEP_V4 = "0.1.0.0"


# =============================================================================
# BGP++ Config — Base Template from Configerator
# The bgpcpp_config contains peer_groups, policies, communities, localprefs,
# switch_limit_config, bgp_setting_config, etc. We MUST preserve all of these.
# Only the 'peers', 'router_id', and 'local_as_4_byte' fields are replaced.
# =============================================================================
BGPCPP_BASE_CONFIG_CONFIGERATOR_PATH = (
    "taac/ebb_ci_cd_configs/ebb_full_scale_bgpcpp_config"
)
BGPCPP_CONFIG_PATH = "/mnt/flash/bgpcpp_config"


# =============================================================================
# BGP++ Supporting Agent Config Files (required for FibAgent daemons)
# Without these, FibAgent/FibAgentBgp/FibGrpc won't start.
# =============================================================================
FIBAGENT_JSON_CONFIGERATOR_PATH = "taac/ebb_ci_cd_configs/FibAgent.json"
FIBAGENT_JSON_DEVICE_PATH = "/usr/facebook/thrift_acls/FibAgent.json"

FIBAGENT_BGP_CONF_CONFIGERATOR_PATH = "taac/ebb_ci_cd_configs/fib_agent_bgp.conf"
FIBAGENT_BGP_CONF_DEVICE_PATH = "/mnt/fb/agent_configs/fib_agent_bgp.conf"

FIBAGENT_CONF_DEVICE_PATH = "/mnt/fb/agent_configs/fib_agent.conf"

# fib_agent_bgp.conf is only 884 bytes — embed as base64 to avoid
# arista_create_file_from_config which silently fails on this device.
# Generated from: configerator/raw_configs/taac/ebb_ci_cd_configs/fib_agent_bgp.conf
# To regenerate: cat <file> | base64 -w0
FIBAGENT_BGP_CONF_B64 = "eyIxIjp7InJlYyI6eyIxIjp7ImkzMiI6NjAxMDB9LCIyIjp7ImkzMiI6NDh9LCIzIjp7ImkzMiI6NX0sIjQiOnsiaTMyIjoxNX0sIjUiOnsic3RyIjoiIn0sIjYiOnsic3RyIjoiL3BlcnNpc3Qvc2VjdXJlL2NhcGkucGVtIn0sIjciOnsic3RyIjoiL3BlcnNpc3Qvc2VjdXJlL2NhcGlrZXkucGVtIn0sIjgiOnsic3RyIjoiL21udC9mYi9jZXJ0cy9BcmlzdGFGaWJBZ2VudF9zZXJ2ZXIucGVtIn0sIjkiOnsiaTMyIjo1OTEzfSwiMTAiOnsic3RyIjoiL3Zhci9mYWNlYm9vay9yb290Y2FuYWwvY2EucGVtIn0sIjExIjp7InRmIjoxfSwiMTIiOnsidGYiOjF9LCIxMyI6eyJzdHIiOiJGaWJTZXJ2aWNlIn0sIjE0Ijp7ImkzMiI6MX0sIjE1Ijp7ImkzMiI6MX0sIjE2Ijp7InRmIjoxfSwiMTciOnsidGYiOjF9LCIxOCI6eyJzdHIiOiIvdXNyL2ZhY2Vib29rL3RocmlmdF9hY2xzL0ZpYkFnZW50X2xhYi5qc29uIn0sIjE5Ijp7InN0ciI6Ii91c3IvZmFjZWJvb2svdGhyaWZ0X2FjbHMvYXV0aF9raWxsX3N3aXRjaF9maWxlIn0sIjIwIjp7InRmIjowfSwiMjEiOnsiaTMyIjo3MjAwfSwiMjIiOnsidGYiOjF9LCIyMyI6eyJ0ZiI6MX0sIjI0Ijp7ImkzMiI6LTF9LCIyNSI6eyJzdHIiOiJGaWIgYWdlbnQgaXMgZGVzaWduZWQgdG8gZXhlY3V0ZSByZW1vdGUgcHJvZ3JhbW1pbmcgcmVxdWVzdHMgZnJvbSBPcGVuL1IgdG8gY2hhbmdlIE9wZW4vUiByb3V0ZXMgYWRtaW4gZGlzdGFuY2VzIHRvIGluZmx1ZW5jZSBiZXN0IHBhdGggc2VsZWN0aW9ucy4ifSwiMjYiOnsiaTMyIjo5NTQ1fSwiMjciOnsic3RyIjoiIn19fSwiMiI6eyJ0ZiI6MH0sIjMiOnsidGYiOjF9LCI0Ijp7ImkzMiI6Nzg3fSwiNSI6eyJpMzIiOjIwMH0sIjYiOnsiaTMyIjo0MH0sIjciOnsidGYiOjF9fQo="  # noqa: E501
FIBAGENT_BGP_CONF_DEPLOY_CMD = (
    f"bash echo '{FIBAGENT_BGP_CONF_B64}' | base64 -d > {FIBAGENT_BGP_CONF_DEVICE_PATH}"
)

# fib_agent.conf — also embedded as base64 (same approach as fib_agent_bgp.conf)
# Key differences from fib_agent_bgp.conf: port 5912 (vs 5913), port 9544 (vs 9545),
# client_id 786 (vs 787), max_sync_fib_batches 10 (vs 200), bgp_mode false (vs true)
FIBAGENT_CONF_B64 = "eyIxIjp7InJlYyI6eyIxIjp7ImkzMiI6NjAxMDB9LCIyIjp7ImkzMiI6NDh9LCIzIjp7ImkzMiI6NX0sIjQiOnsiaTMyIjoxNX0sIjUiOnsic3RyIjoiIn0sIjYiOnsic3RyIjoiL3BlcnNpc3Qvc2VjdXJlL2NhcGkucGVtIn0sIjciOnsic3RyIjoiL3BlcnNpc3Qvc2VjdXJlL2NhcGlrZXkucGVtIn0sIjgiOnsic3RyIjoiL21udC9mYi9jZXJ0cy9BcmlzdGFGaWJBZ2VudF9zZXJ2ZXIucGVtIn0sIjkiOnsiaTMyIjo1OTEyfSwiMTAiOnsic3RyIjoiL3Zhci9mYWNlYm9vay9yb290Y2FuYWwvY2EucGVtIn0sIjExIjp7InRmIjoxfSwiMTIiOnsidGYiOjF9LCIxMyI6eyJzdHIiOiJGaWJTZXJ2aWNlIn0sIjE0Ijp7ImkzMiI6MX0sIjE1Ijp7ImkzMiI6MX0sIjE2Ijp7InRmIjoxfSwiMTciOnsidGYiOjF9LCIxOCI6eyJzdHIiOiIvdXNyL2ZhY2Vib29rL3RocmlmdF9hY2xzL0ZpYkFnZW50X2xhYi5qc29uIn0sIjE5Ijp7InN0ciI6Ii91c3IvZmFjZWJvb2svdGhyaWZ0X2FjbHMvYXV0aF9raWxsX3N3aXRjaF9maWxlIn0sIjIwIjp7InRmIjowfSwiMjEiOnsiaTMyIjo3MjAwfSwiMjIiOnsidGYiOjF9LCIyMyI6eyJ0ZiI6MX0sIjI0Ijp7ImkzMiI6LTF9LCIyNSI6eyJzdHIiOiJGaWIgYWdlbnQgaXMgZGVzaWduZWQgdG8gZXhlY3V0ZSByZW1vdGUgcHJvZ3JhbW1pbmcgcmVxdWVzdHMgZnJvbSBPcGVuL1IgdG8gY2hhbmdlIE9wZW4vUiByb3V0ZXMgYWRtaW4gZGlzdGFuY2VzIHRvIGluZmx1ZW5jZSBiZXN0IHBhdGggc2VsZWN0aW9ucy4ifSwiMjYiOnsiaTMyIjo5NTQ0fSwiMjciOnsic3RyIjoiIn19fSwiMiI6eyJ0ZiI6MH0sIjMiOnsidGYiOjF9LCI0Ijp7ImkzMiI6Nzg2fSwiNSI6eyJpMzIiOjEwfSwiNiI6eyJpMzIiOjQwfSwiNyI6eyJ0ZiI6MH19"  # noqa: E501
FIBAGENT_CONF_DEPLOY_CMD = (
    f"bash echo '{FIBAGENT_CONF_B64}' | base64 -d > {FIBAGENT_CONF_DEVICE_PATH}"
)


# =============================================================================
# BGP++ Daemon Names (for arista_daemon_control tasks)
# NOTE: Openr excluded — not used in this experiment
# =============================================================================
BGPCPP_DAEMONS = [
    "Bgp",
    "FibAgent",
    "FibAgentBgp",
    "FibBgpGrpc",
    "FibGrpc",
    "RouteGrpc",
]


# =============================================================================
# TCP Data Collection Parameters
# collect_tcp_data.sh collects ss data and bgpcpp egress summary
# Output written to /tmp/tcp_data on the device
# Script source: tcp_socket_experiment/scripts/collect_tcp_data.sh
# =============================================================================
TCP_DATA_COLLECTION_DURATION_SECONDS = 300  # 5 minutes default
TCP_DATA_COLLECTION_INTERVAL_SECONDS = 1  # Sample every 1 second
TCP_DATA_OUTPUT_DIR = "/tmp/tcp_data"
TCP_DATA_COLLECTION_SCRIPT = "/mnt/flash/collect_tcp_data.sh"
TCP_DATA_CONVERGENCE_TIME_SECONDS = 600  # Estimated BGP convergence time
TCP_DATA_STEADY_STATE_DURATION_SECONDS = 300  # Steady state collection (5 min)
TCP_DATA_SAMPLE_INTERVAL_SECONDS = 5  # Sample every 5 seconds

# Script deployment uses base64 to avoid shell escaping issues.
# The script is encoded at config generation time, then decoded on the device.
import base64 as _b64

_SCRIPT_CONTENT = """#!/bin/bash
duration=$1
interval=$2
is_bgpcpp=$3
if [ -z "$duration" ] || [ -z "$interval" ] || [ -z "$is_bgpcpp" ]; then
    echo "Usage: $0 <duration> <interval> <is_bgpcpp>"
    exit 1
fi
iterations=$((duration / interval))
output_dir="/tmp/tcp_data"
mkdir -p "$output_dir" 2>/dev/null
for ((epoch=0; epoch<=iterations; epoch++)); do
    timestamp=$(date +%s)
    local_date=$(date)
    ss_file="${output_dir}/ss_${timestamp}"
    { echo "Epoch: ${epoch}"; echo "Date: ${local_date}"; echo ""; ss -tbamie 2>/dev/null; } > "$ss_file"
    if [ "$is_bgpcpp" = "true" ] || [ "$is_bgpcpp" = "1" ]; then
        egress_file="${output_dir}/egress_${timestamp}"
        { echo "Epoch: ${epoch}"; echo "Date: ${local_date}"; echo ""; LC_ALL="C" bgpcli --ssl-policy=plaintext show bgp summary egress 2>/dev/null; } > "$egress_file"
    fi
    [ "$epoch" -lt "$iterations" ] && sleep "$interval"
done
echo "All files written to $output_dir"
ls -lrth "$output_dir" | head -10
"""
_SCRIPT_B64 = _b64.b64encode(_SCRIPT_CONTENT.encode()).decode()

TCP_DATA_COLLECTION_SCRIPT_DEPLOY_CMD = (
    f"bash echo '{_SCRIPT_B64}' | base64 -d > /mnt/flash/collect_tcp_data.sh && "
    "chmod +x /mnt/flash/collect_tcp_data.sh"
)
# The IXIA iBGP routes (EB-EB) MUST carry a community that the EB-FA-OUT
# policy permits, otherwise BGP++ won't advertise them to eBGP peers.
#
# EB-FA-OUT policy permits routes matching these communities:
#   65531:50300 = AS32934_AGGREGATE_GLOBAL (FB Global Public Aggregates)
#   65531:50200 = AS32934_PRIVATE_AGGREGATE (FB Global Private Aggregates)
#   65526:35724 = eb_fa_private_ic_agg
#   65526:35720 = eb_plane_private_ic_agg
#   65529:15980 = topology/plane routing
#   65529:15990 = default routes
#
# Using 65531:50300 for this experiment — routes will appear as global aggregates
# and be permitted by EB-FA-OUT policy for advertisement to ar-bgp.
# =============================================================================
IXIA_IBGP_COMMUNITIES = "65526:35724"
IXIA_EBGP_COMMUNITIES = "65100:100"


# =============================================================================
# Control Plane ACLs — deployed on both bag012 and bag013
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
