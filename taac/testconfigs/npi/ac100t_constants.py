# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""Steller Eagle / 100T air-cooled (ac100t) NPI device + topology constants.

SINGLE SOURCE OF TRUTH for everything device-specific about the ac100t NPI
testbed: per-DUT identity, IXIA fanout wiring, route sets, CPU-queue indices,
BGP peer groups / route-maps / AS numbers, route scale, and the monitored
service list.

Topology follows the M4062NHP TAAC Physical Topology doc (the only physical
topology planned for Steller Eagle; logical variants are expressed by swapping
TestConfigs, not by re-cabling)::

                          IXIA (fanout)
              A |        B |        C |        D,E |
                v          v          v            v
              DUT1       DUT2       DUT3         DUT4
           (SE 100T)  (SE 100T)  (SE 100T)     (w800 CE)

  Route sets advertised from the IXIA fanout:
    A -> DUT1 only        B -> DUT2 only        C -> DUT3 only
    D -> DUT4 only        E -> DUT1 and DUT4

  Traffic items (framed from DUT2's point of view):
    1  B -> D   in 1-way,   out <=254-way (400G) or <=127-way (800G)
    2a A -> C   in 192-way (400G), out 124-way (200G) or 62-way (800G)
    2b C -> A

  Device drain: run B -> D, drain DUT3, all traffic converges on DUT1.
  QoS: B and D routes send traffic to A routes (2x800G bw -> 1x800G bw).

Steller Eagle has NOT arrived in the lab and is NOT in fbsource: there is no
`Hardware` enum value for it in netwhoami.thrift and no entry in
`get_cpu_queue_constants()` (which today only knows MONTBLANC / MINIPACK3BA /
ICECUBE800BC -> 0/2/9 and MORGAN800CC -> 0/2/7). So every device value below is
a **TODO placeholder**, kept syntactically valid (RFC5737/RFC3849 documentation
IPs, locally administered MACs) so the test configs build and import before the
hardware exists. When the DUTs are racked and cabled, replace the values marked
`# TODO(ac100t)` here -- this is the ONLY file that should need device-specific
edits.

The full constant set (CPU queue, BGP hardening, longevity, thrift hardening,
speed flip) is staged here so later test classes can be bound without touching
this file again. Only the CPU-queue block is consumed today; see
`ac100t_npi_test_config.py`.
"""

# ---------------------------------------------------------------------------
# Device identity (4-DUT testbed)
# ---------------------------------------------------------------------------
# DUT1-DUT3 are Steller Eagle 100T air-cooled units. DUT4 is a Wedge800 acting
# as the CE; its real device values are tracked separately in w800_constants.py,
# and the placeholder below exists so the multi-DUT test classes can name it.
# TODO(ac100t): real DUT hostnames once the devices are in the lab / netwhoami.
AC100T_DUT1_DEVICE_NAME = "ac100t001.TODO.example"
AC100T_DUT2_DEVICE_NAME = "ac100t002.TODO.example"
AC100T_DUT3_DEVICE_NAME = "ac100t003.TODO.example"
AC100T_DUT4_CE_DEVICE_NAME = "wedge800001.TODO.example"

# TODO(ac100t): local MACs for the DUT side of IXIA peering (placeholders are
# locally administered addresses). Read from the real DUTs when they arrive.
AC100T_DUT1_LOCAL_MAC_ADDRESS = "02:00:00:00:01:01"
AC100T_DUT2_LOCAL_MAC_ADDRESS = "02:00:00:00:01:02"
AC100T_DUT3_LOCAL_MAC_ADDRESS = "02:00:00:00:01:03"
AC100T_DUT4_CE_LOCAL_MAC_ADDRESS = "02:00:00:00:01:04"

# Basset device pool. NOTE: create_npi_cpu_queue_test_config currently hardcodes
# basset_pool="dne.test" internally, so this is informational until that param
# is honored. TODO(ac100t): confirm the ac100t lab pool.
AC100T_BASSET_POOL = "dne.test"

# ---------------------------------------------------------------------------
# IXIA fanout wiring
# ---------------------------------------------------------------------------
# The "fanout" in the topology doc IS the IXIA chassis -- every route set is
# advertised by an IXIA BGP-mimic device group, and every DUT connects straight
# back to IXIA. There is no intermediate fanout switch, so all DUTs must land on
# the SAME IXIA chassis (a TAAC TestConfig drives exactly one IXIA session).
# TODO(ac100t): real IXIA-connected interfaces per DUT, and the chassis name.
AC100T_IXIA_CHASSIS = "TODO_AC100T_IXIA_CHASSIS"
AC100T_DUT1_IXIA_INTERFACES = ["eth1/13/1", "eth1/13/3", "eth1/13/5"]
AC100T_DUT2_IXIA_INTERFACES = ["eth1/14/1", "eth1/14/3", "eth1/14/5"]
AC100T_DUT3_IXIA_INTERFACES = ["eth1/15/1", "eth1/15/3", "eth1/15/5"]
AC100T_DUT4_CE_IXIA_INTERFACES = ["eth1/16/1", "eth1/16/3", "eth1/16/5"]

# ---------------------------------------------------------------------------
# Route sets (advertised from the IXIA fanout, one set per DUT)
# ---------------------------------------------------------------------------
# Set E is advertised to BOTH DUT1 and DUT4, which is what makes the drain case
# (drain DUT3, converge on DUT1) and the QoS case (B + D -> A) expressible.
# Placeholder parent networks use RFC3849 (2001:db8::/32) and RFC5737 (TEST-NET)
# documentation ranges so nothing collides with a real subnet.
# TODO(ac100t): set to ranges reachable on the real DUT interfaces.
AC100T_ROUTE_SET_A_TARGET_DUTS = [AC100T_DUT1_DEVICE_NAME]
AC100T_ROUTE_SET_B_TARGET_DUTS = [AC100T_DUT2_DEVICE_NAME]
AC100T_ROUTE_SET_C_TARGET_DUTS = [AC100T_DUT3_DEVICE_NAME]
AC100T_ROUTE_SET_D_TARGET_DUTS = [AC100T_DUT4_CE_DEVICE_NAME]
AC100T_ROUTE_SET_E_TARGET_DUTS = [
    AC100T_DUT1_DEVICE_NAME,
    AC100T_DUT4_CE_DEVICE_NAME,
]

AC100T_ROUTE_SET_A_PARENT_NETWORK_V6 = "2001:db8:0:1a00"
AC100T_ROUTE_SET_B_PARENT_NETWORK_V6 = "2001:db8:0:1b00"
AC100T_ROUTE_SET_C_PARENT_NETWORK_V6 = "2001:db8:0:1c00"
AC100T_ROUTE_SET_D_PARENT_NETWORK_V6 = "2001:db8:0:1d00"
AC100T_ROUTE_SET_E_PARENT_NETWORK_V6 = "2001:db8:0:1e00"
AC100T_ROUTE_SET_A_PARENT_NETWORK_V4 = "192.0.2"
AC100T_ROUTE_SET_B_PARENT_NETWORK_V4 = "198.51.100"
AC100T_ROUTE_SET_C_PARENT_NETWORK_V4 = "203.0.113"
AC100T_ROUTE_SET_D_PARENT_NETWORK_V4 = "192.0.2"
AC100T_ROUTE_SET_E_PARENT_NETWORK_V4 = "198.51.100"

# Per-route-set prefix counts. The doc's Scale section (BGP neighbors,
# paths/neighbor, v4/v6 routes per neighbor and total, ECMP, UCMP) is still
# unfilled, so these are the IcePack CPU-queue baseline.
# TODO(ac100t): replace with the signed-off M4062NHP scale numbers.
AC100T_ROUTE_SET_PREFIX_COUNT_V6 = 500
AC100T_ROUTE_SET_PREFIX_COUNT_V4 = 500

# ---------------------------------------------------------------------------
# Traffic items (DUT2 point of view) -- ECMP way counts per the topology doc
# ---------------------------------------------------------------------------
# Used by the multi-DUT traffic/QoS/drain classes once they are bound; the
# single-node CPU-queue config does not consume these.
AC100T_TRAFFIC_B_TO_D_INGRESS_WAYS = 1
AC100T_TRAFFIC_B_TO_D_EGRESS_WAYS_400G = 254
AC100T_TRAFFIC_B_TO_D_EGRESS_WAYS_800G = 127
AC100T_TRAFFIC_A_TO_C_INGRESS_WAYS_400G = 192
AC100T_TRAFFIC_A_TO_C_EGRESS_WAYS_200G = 124
AC100T_TRAFFIC_A_TO_C_EGRESS_WAYS_800G = 62
# Drain case: run B -> D, drain DUT3, expect convergence onto DUT1.
AC100T_DRAIN_TARGET_DEVICE = AC100T_DUT3_DEVICE_NAME
AC100T_DRAIN_CONVERGENCE_DEVICE = AC100T_DUT1_DEVICE_NAME
# QoS case: B and D routes send traffic to A routes, 2x800G bw -> 1x800G bw.
AC100T_QOS_SOURCE_ROUTE_SETS = ["B", "D"]
AC100T_QOS_DESTINATION_ROUTE_SET = "A"

# ===========================================================================
# CPU queue tests: Generic (FE + BE)
# ===========================================================================
# create_npi_cpu_queue_test_config is a SINGLE-DUT factory, so the CPU-queue
# class runs on one Steller Eagle unit rather than the full 4-DUT topology.
# DUT2 is chosen because the topology doc frames its traffic items from DUT2's
# point of view, making it the primary device under test.
AC100T_CPU_QUEUE_DUT = AC100T_DUT2_DEVICE_NAME
AC100T_CPU_QUEUE_LOCAL_MAC_ADDRESS = AC100T_DUT2_LOCAL_MAC_ADDRESS

# The factory's three IXIA-facing roles, mapped onto DUT2's fanout links:
# uplink is the SOURCE of CPU-queue test traffic, downlink is the sink +
# BGP-flap target, rogue is required by the signature but unused for CPU-queue
# items. TODO(ac100t): confirm which of DUT2's fanout ports takes each role.
AC100T_CPU_QUEUE_IXIA_DOWNLINK_INTERFACE = AC100T_DUT2_IXIA_INTERFACES[0]
AC100T_CPU_QUEUE_IXIA_UPLINK_INTERFACE = AC100T_DUT2_IXIA_INTERFACES[1]
AC100T_CPU_QUEUE_IXIA_ROGUE_INTERFACE = AC100T_DUT2_IXIA_INTERFACES[2]

# CPU queue indices (low / mid / high). Passed explicitly into
# create_npi_cpu_queue_test_config() so the factory does NOT do a live netwhoami
# lookup, which would raise for a hardware type it has never seen. Placeholder
# mirrors TH-class silicon (Minipack3 / IcePack TH6 = 0/2/9).
# TODO(ac100t): verify against real Steller Eagle silicon; once the platform has
# a netwhoami Hardware enum value, add it to get_cpu_queue_constants() so live
# runs resolve these without this override.
AC100T_CPU_LOW_QUEUE = 0
AC100T_CPU_MID_QUEUE = 2
AC100T_CPU_HIGH_QUEUE = 9

# ---------------------------------------------------------------------------
# BGP peer groups (must be REAL peer-group names present on the DUT config; the
# factory's coop patchers validate/attach against these at runtime)
# ---------------------------------------------------------------------------
# Scoped to the CPU-queue DUT (DUT2). TODO(ac100t): replace with the actual
# peer-group names, and add per-DUT variants when the multi-DUT classes land.
AC100T_PEERGROUP_UPLINK_MIMIC_V6 = "TODO_AC100T_PEERGROUP_UPLINK_V6"
AC100T_PEERGROUP_UPLINK_MIMIC_V4 = "TODO_AC100T_PEERGROUP_UPLINK_V4"
AC100T_PEERGROUP_DOWNLINK_MIMIC_V6 = "TODO_AC100T_PEERGROUP_DOWNLINK_V6"
AC100T_PEERGROUP_DOWNLINK_MIMIC_V4 = "TODO_AC100T_PEERGROUP_DOWNLINK_V4"
AC100T_PEERGROUP_ROGUE_MIMIC_V6 = "TODO_AC100T_PEERGROUP_ROGUE_V6"
AC100T_PEERGROUP_ROGUE_MIMIC_V4 = "TODO_AC100T_PEERGROUP_ROGUE_V4"

# ---------------------------------------------------------------------------
# Route-maps (must be REAL route-map/policy names on the DUT; the add_peer_group
# patcher validates ingress/egress policies exist before accepting peer config)
# ---------------------------------------------------------------------------
# TODO(ac100t): replace with the actual route-map names on the ac100t DUTs.
AC100T_ROUTE_MAP_UPLINK_INGRESS = "TODO_AC100T_ROUTE_MAP_UPLINK_IN"
AC100T_ROUTE_MAP_UPLINK_EGRESS = "TODO_AC100T_ROUTE_MAP_UPLINK_OUT"
AC100T_ROUTE_MAP_DOWNLINK_INGRESS = "TODO_AC100T_ROUTE_MAP_DOWNLINK_IN"
AC100T_ROUTE_MAP_DOWNLINK_EGRESS = "TODO_AC100T_ROUTE_MAP_DOWNLINK_OUT"
AC100T_ROUTE_MAP_ROGUE_INGRESS = "TODO_AC100T_ROUTE_MAP_ROGUE_IN"
AC100T_ROUTE_MAP_ROGUE_EGRESS = "TODO_AC100T_ROUTE_MAP_ROGUE_OUT"

# ---------------------------------------------------------------------------
# IXIA-side parent networks for the CPU-queue DUT's three mimic peer groups.
# Downlink/uplink reuse the DUT2-facing route set (B); rogue gets its own stem
# so bogus routes are distinguishable from set B.
# ---------------------------------------------------------------------------
# TODO(ac100t): set to IXIA-mimic parent ranges reachable on the real DUT2
# interfaces.
AC100T_IXIA_DOWNLINK_IC_PARENT_NETWORK_V6 = AC100T_ROUTE_SET_B_PARENT_NETWORK_V6
AC100T_IXIA_UPLINK_IC_PARENT_NETWORK_V6 = "2001:db8:0:1b01"
AC100T_IXIA_ROGUE_IC_PARENT_NETWORK_V6 = "2001:db8:0:1bff"
AC100T_IXIA_DOWNLINK_IC_PARENT_NETWORK_V4 = AC100T_ROUTE_SET_B_PARENT_NETWORK_V4
AC100T_IXIA_UPLINK_IC_PARENT_NETWORK_V4 = "192.0.2"
AC100T_IXIA_ROGUE_IC_PARENT_NETWORK_V4 = "203.0.113"

# ---------------------------------------------------------------------------
# Route scale / peer counts
# ---------------------------------------------------------------------------
# Minimal first-pass scale: for CPU-queue purposes BGP peers are just anchors
# for IXIA traffic injection, and the CPU-queue assertions do not depend on
# prefix count. The doc's Scale section is still unfilled.
# TODO(ac100t): tune once the signed-off M4062NHP scale numbers exist and real
# Steller Eagle CPU/FIB headroom is known.
AC100T_UNIQUE_PREFIX_LIMIT = "75000"
AC100T_PER_PEER_MAX_ROUTE_LIMIT = "20000"
AC100T_DOWNLINK_PEER_COUNT = 8
AC100T_UPLINK_PEER_COUNT = 8
AC100T_ROGUE_PEER_COUNT = 8
AC100T_IXIA_DOWNLINK_PREFIX_COUNT_V6 = AC100T_ROUTE_SET_PREFIX_COUNT_V6
AC100T_IXIA_UPLINK_PREFIX_COUNT_V6 = AC100T_ROUTE_SET_PREFIX_COUNT_V6
AC100T_IXIA_ROGUE_PREFIX_COUNT_V6 = AC100T_ROUTE_SET_PREFIX_COUNT_V6
AC100T_IXIA_DOWNLINK_PREFIX_COUNT_V4 = AC100T_ROUTE_SET_PREFIX_COUNT_V4
AC100T_IXIA_UPLINK_PREFIX_COUNT_V4 = AC100T_ROUTE_SET_PREFIX_COUNT_V4
AC100T_IXIA_ROGUE_PREFIX_COUNT_V4 = AC100T_ROUTE_SET_PREFIX_COUNT_V4

# Port speeds present in the topology. Snake runs at 800G and 400G.
# TODO(ac100t): confirm the per-cage speed map once the port map exists.
AC100T_PORT_SPEEDS_GBPS = [800, 400, 200]
AC100T_SNAKE_PORT_SPEEDS_GBPS = [800, 400]

# ---------------------------------------------------------------------------
# Remote AS numbers (IXIA-mimic peers). Must DIFFER from the DUT's local AS
# (EBGP), since IXIA BGP-mimic uses step=1 and treats peers as EBGP.
# ---------------------------------------------------------------------------
# TODO(ac100t): confirm each DUT's local AS and pick base ASNs well outside it.
AC100T_REMOTE_UPLINK_AS_4BYTE = 65272
AC100T_REMOTE_DOWNLINK_AS_4BYTE = 7001
AC100T_REMOTE_ROGUE_AS_4BYTE = 2500
AC100T_REMOTE_AS_4_BYTE_STEP = 1
AC100T_IS_UPLINK_PEER_CONFED = "False"
AC100T_IS_DOWNLINK_PEER_CONFED = "False"
AC100T_IS_ROGUE_PEER_CONFED = "False"

# ---------------------------------------------------------------------------
# BGP communities required for the DUT's ingress policy to ACCEPT + FIB-install
# IXIA-mimic routes (otherwise BGP_PREFIX_TRAFFIC background sees 100% loss).
# The exact set is policy-specific.
# ---------------------------------------------------------------------------
# TODO(ac100t): replace with the communities the ac100t DUT's ingress route-map
# requires (inspect the real policy, as done for IcePack's
# PROPAGATE_GTSW_STSW_IN).
AC100T_IXIA_DOWNLINK_COMMUNITIES = ["65446:30", "65441:323", "65456:323"]
AC100T_IXIA_UPLINK_COMMUNITIES = ["65446:30", "65441:323", "65456:323"]

# Peer tags (labels for the mimic peer groups).
AC100T_DOWNLINK_PEER_TAG = "HOST"
AC100T_UPLINK_PEER_TAG = "UPLINK"

# ---------------------------------------------------------------------------
# Restart iteration counts (used by the factory's restart tasks/playbooks).
# ---------------------------------------------------------------------------
AC100T_BGPD_RESTART_NO_OF_ITERATIONS = 5
AC100T_WEDGE_AGENT_RESTART_NO_OF_ITERATIONS = 5

# ---------------------------------------------------------------------------
# Services monitored by the postcheck ServiceRestartHealthCheck.
# ---------------------------------------------------------------------------
# TODO(ac100t): confirm which services the Steller Eagle image actually runs.
# Placeholder mirrors the IcePack backend list (openr dropped). If the DUT role
# DOES run Open/R, add "openr" back.
AC100T_SERVICE_RESTART_SERVICES = [
    "bgpd",
    "fboss_hw_agent@0",
    "fboss_sw_agent",
    "fsdb",
    "qsfp_service",
    "wedge_agent",
]

# ===========================================================================
# BGP Hardening tests (BGP-DC chronos longevity playbooks)
# ===========================================================================
# For a future AC100T_BGP_HARDENING_TEST_CONFIG built with
# build_bgp_dc_test_config(). MOST knobs above (DUT identity, IXIA interfaces,
# peer groups, route-maps, IC parent networks, peer counts, AS numbers, confed
# flags, prefix counts, communities, peer tags, basset pool) are SHARED with the
# CPU-queue config and are meant to be reused directly. Only the BGP-DC-only
# extras live below.

# Aggregate DUT prefix limit for the BGP-DC build (string). Reuses the same
# 75000 scale as the CPU-queue unique-prefix limit (single source of truth).
AC100T_BGP_PREFIX_LIMIT = AC100T_UNIQUE_PREFIX_LIMIT

# Good/rogue NDP + ARP entry parent networks for the DUT-side neighbor tables.
# TODO(ac100t): set to real reachable stems. Placeholders use RFC3849 v6 doc
# ranges; ARP stems are 2-octet (matching the Kodiak-3 RBB reference shape).
AC100T_GOOD_NDP_ENTRY_NETWORK_V6 = "2001:db8:0:1b01"
AC100T_ROGUE_NDP_ENTRY_NETWORK_V6 = "2001:db8:0:1bff"
AC100T_GOOD_ARP_ENTRY_NETWORK_V4 = "192.168"
AC100T_ROGUE_ARP_ENTRY_NETWORK_V4 = "193.168"
AC100T_IXIA_UPLINK_GOOD_NDP_NETWORK = "2001:db8:0:2901"
AC100T_IXIA_DOWNLINK_GOOD_NDP_NETWORK = "2001:db8:0:2801"

# Neighbor-table / ECMP scale (ints). Mirror the Kodiak-3 RBB reference; tune
# once the doc's ECMP/UCMP scale rows are filled in. TODO(ac100t).
AC100T_ECMP_GROUP_LIMIT = 200
AC100T_ECMP_MEMBER_LIMIT = 5000
AC100T_GOOD_NDP_ENTRIES_UPLINK = 100
AC100T_GOOD_NDP_ENTRIES_DOWNLINK = 100
AC100T_ROGUE_NDP_ENTRIES = 50
AC100T_GOOD_ARP_ENTRIES = 100
AC100T_ROGUE_ARP_ENTRIES = 100
AC100T_GOOD_MAC_ENTRY_COUNT = 100
AC100T_ROGUE_MAC_ENTRY_COUNT = 200
AC100T_BGP_INDUCED_ECMP_GROUP_COUNT = 50

# ===========================================================================
# Longevity tests (snake / loopback standalone -> test_72hr_longevity)
# ===========================================================================
# For a future AC100T_LONGEVITY_TEST_CONFIG built with gen_snake_test_config()
# -- the ONLY builder that emits the test_72hr_longevity playbook. Snake =
# single-DUT loopback: one source port jumpered to one destination port on the
# SAME DUT, with point-to-point IPv6 addressing, so it runs on the CPU-queue DUT
# rather than the full topology. Standalone snake tests use the dne.standalone
# basset pool by convention.
# TODO(ac100t): real looped interfaces + jumper IPs once the DUT is cabled; the
# doc calls for snake at both 800G and 400G (see AC100T_SNAKE_PORT_SPEEDS_GBPS).
AC100T_STANDALONE_BASSET_POOL = "dne.standalone"
AC100T_SNAKE_DEVICE_NAME = AC100T_CPU_QUEUE_DUT
AC100T_SNAKE_SOURCE_INTERFACE = "eth1/1/1"
AC100T_SNAKE_DEST_INTERFACE = "eth1/2/1"
AC100T_SNAKE_SOURCE_IP = "5000:1::1/64"
AC100T_SNAKE_DEST_IP = "5000:1::2/64"

# ===========================================================================
# Thrift hardening tests (THFT_001..005)
# ===========================================================================
# For a future AC100T_THRIFT_HARDENING_TEST_CONFIG. ALL BGP scaffolding knobs
# are SHARED with the CPU-queue / BGP configs above and are meant to be reused
# directly; the only THFT-specific value is the flap-port list.
# flap_ports = DUT-side ports the qsfp-flap background will tx_disable /
# tx_enable. MUST EXCLUDE the IXIA-facing ports (AC100T_DUT2_IXIA_INTERFACES) --
# flapping those breaks IXIA peering and would invalidate the
# BGP_SESSION_ESTABLISH precheck. In this topology the non-IXIA ports on DUT2
# are its inter-DUT links.
# TODO(ac100t): real inter-DUT ports once the DUTs are racked/cabled.
AC100T_STSW_FLAP_PORTS = [
    "eth1/5/1",
    "eth1/6/1",
]

# ===========================================================================
# Speed flip tests (subsume-churn / SPD_041)
# ===========================================================================
# For a future AC100T_SPEED_FLIP_SUBSUME_CHURN_TEST_CONFIG built with
# build_subsume_churn_test_config() from speed_flip_test_configs.py. The factory
# requires EXACTLY 6 circuits = 3 dual cages x 2 subports (/1 and /5);
# a_end = DUT cage base, z_end = peer interface base. The peer here is another
# DUT in the topology rather than an external device. NOTE: most other
# speed-flip rows in the NPI test plan are "not feasible in OSS" (GSC-native
# circuit-DB / config-generate / reprovision paths); the reboot/coldboot/800G
# rows that ARE feasible reuse hardcoded dataclass literals in
# speed_flip_test_configs.py (no device-parameterized factory) and are deferred
# until real Steller Eagle port maps exist.
# TODO(ac100t): real DUT cages + peer interfaces once racked and cabled.
AC100T_SPEED_FLIP_DEVICE_NAME = AC100T_CPU_QUEUE_DUT
AC100T_SPEED_FLIP_PEER_DEVICE_NAME = AC100T_DUT3_DEVICE_NAME
AC100T_SPEED_FLIP_CHURN_ITERATIONS = 10
# (dut_cage_base, peer_interface_base); each contributes a /1 and /5 subport.
AC100T_SPEED_FLIP_CHURN_CAGES = [
    ("eth1/17", "eth1/1"),
    ("eth1/21", "eth1/2"),
    ("eth1/22", "eth1/3"),
]
