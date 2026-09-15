# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""Wedge800 (w800) NPI device + topology constants.

SINGLE SOURCE OF TRUTH for everything device-specific about the w800 NPI DUT:
hostname, MAC, IXIA wiring, CPU-queue indices, BGP peer groups / route-maps /
AS numbers, IXIA-side networks, route scale, and the monitored service list.

w800 is a NEW device that has not arrived in the lab yet, so every value below
is a **TODO placeholder** modeled on the IcePack GTSW CPU-queue reference
(`NPI_DVT_ICEPACK_GTSW__CPU_QUEUE_TEST_CONFIG` in cpu_queue_test_config.py).
Placeholders are intentionally syntactically valid (RFC5737/RFC3849
documentation IPs, locally-administered MAC) so the test config builds and is
importable before the hardware exists. When the real w800 DUT is racked and
wired to IXIA, replace the values marked `# TODO(w800)` here — this is the ONLY
file that should need device-specific edits.

Consumed by `wedge800_npi_test_config.py`.
"""

# ---------------------------------------------------------------------------
# Device identity
# ---------------------------------------------------------------------------
# TODO(w800): real scale-topology hostnames once the devices are in the lab.
W800_FSW_DEVICE_NAMES: list[str] = [
    "wedge800fsw001.TODO.example",
    "wedge800fsw002.TODO.example",
]
W800_RSW_DUT_DEVICE_NAME: str = "wedge800rsw001.TODO.example"
W800_RSW_PEER_DEVICE_NAME: str = "wedge800rsw002.TODO.example"
# TODO(w800): real standalone DUT hostname once the device is in the lab.
W800_DEVICE_NAME: str = "wedge800001.TODO.example"
# TODO(w800): local MAC for the DUT side of IXIA peering (placeholder = locally
# administered address). Read from the real DUT when it arrives.
W800_LOCAL_MAC_ADDRESS: str = "02:00:00:00:00:0c"
# TODO(w800): local MAC for the peer RSW side of IXIA peering.
W800_RSW_PEER_LOCAL_MAC_ADDRESS: str = "02:00:00:00:00:0d"
# Basset device pool. TODO(w800): confirm the w800 lab pool.
W800_BASSET_POOL = "dne.test"

# ---------------------------------------------------------------------------
# IXIA wiring (DUT-facing IXIA ports)
# ---------------------------------------------------------------------------
# Factory usage (see reference): uplink is the SOURCE of CPU-queue test traffic,
# downlink is the sink + BGP-flap target, rogue is required by the signature but
# unused for CPU-queue items.
# TODO(w800): real IXIA-connected interfaces on the w800 DUT.
W800_IXIA_DOWNLINK_INTERFACE = "eth1/13/1"
W800_IXIA_UPLINK_INTERFACE = "eth1/13/3"
W800_IXIA_ROGUE_INTERFACE = "eth1/13/5"
W800_RSW_DUT_IXIA_PORTS: list[str] = [
    W800_IXIA_DOWNLINK_INTERFACE,
    W800_IXIA_UPLINK_INTERFACE,
    W800_IXIA_ROGUE_INTERFACE,
]
W800_RSW_PEER_IXIA_DOWNLINK_INTERFACE: str = "eth1/13/1"
W800_RSW_PEER_IXIA_UPLINK_INTERFACE: str = "eth1/13/3"
W800_RSW_PEER_IXIA_ROGUE_INTERFACE: str = "eth1/13/5"
W800_RSW_PEER_IXIA_PORTS: list[str] = [
    W800_RSW_PEER_IXIA_DOWNLINK_INTERFACE,
    W800_RSW_PEER_IXIA_UPLINK_INTERFACE,
    W800_RSW_PEER_IXIA_ROGUE_INTERFACE,
]

# ---------------------------------------------------------------------------
# CPU queue indices (low / mid / high)
# ---------------------------------------------------------------------------
# Passed explicitly into create_npi_cpu_queue_test_config() so the factory does
# NOT do a live netwhoami lookup (which would fail for a not-yet-existent w800).
# Placeholder mirrors TH-class silicon (Minipack3 / IcePack TH6 = 0/2/9).
# TODO(w800): verify against real w800 silicon; if confirmed, also add the
# w800 netwhoami hardware enum name to get_cpu_queue_constants() so live runs
# can resolve these without this override.
W800_CPU_LOW_QUEUE = 0
W800_CPU_MID_QUEUE = 2
W800_CPU_HIGH_QUEUE = 9

# ---------------------------------------------------------------------------
# BGP peer groups (must be REAL peer-group names present on the w800 DUT config;
# the factory's coop patchers validate/attach against these at runtime)
# ---------------------------------------------------------------------------
# TODO(w800): replace with the actual peer-group names on the w800 DUT.
W800_PEERGROUP_UPLINK_MIMIC_V6 = "TODO_W800_PEERGROUP_UPLINK_V6"
W800_PEERGROUP_UPLINK_MIMIC_V4 = "TODO_W800_PEERGROUP_UPLINK_V4"
W800_PEERGROUP_DOWNLINK_MIMIC_V6 = "TODO_W800_PEERGROUP_DOWNLINK_V6"
W800_PEERGROUP_DOWNLINK_MIMIC_V4 = "TODO_W800_PEERGROUP_DOWNLINK_V4"
W800_PEERGROUP_ROGUE_MIMIC_V6 = "TODO_W800_PEERGROUP_ROGUE_V6"
W800_PEERGROUP_ROGUE_MIMIC_V4 = "TODO_W800_PEERGROUP_ROGUE_V4"

# ---------------------------------------------------------------------------
# Route-maps (must be REAL route-map/policy names on the w800 DUT; add_peer_group
# patcher validates ingress/egress policies exist before accepting peer config)
# ---------------------------------------------------------------------------
# TODO(w800): replace with the actual route-map names on the w800 DUT.
W800_ROUTE_MAP_UPLINK_INGRESS = "TODO_W800_ROUTE_MAP_UPLINK_IN"
W800_ROUTE_MAP_UPLINK_EGRESS = "TODO_W800_ROUTE_MAP_UPLINK_OUT"
W800_ROUTE_MAP_DOWNLINK_INGRESS = "TODO_W800_ROUTE_MAP_DOWNLINK_IN"
W800_ROUTE_MAP_DOWNLINK_EGRESS = "TODO_W800_ROUTE_MAP_DOWNLINK_OUT"
W800_ROUTE_MAP_ROGUE_INGRESS = "TODO_W800_ROUTE_MAP_ROGUE_IN"
W800_ROUTE_MAP_ROGUE_EGRESS = "TODO_W800_ROUTE_MAP_ROGUE_OUT"

# ---------------------------------------------------------------------------
# IXIA-side parent networks (per interface, v6 /64 stem + v4 /24 stem)
# Placeholders use RFC3849 (2001:db8::/32) and RFC5737 (TEST-NET) documentation
# ranges so nothing collides with a real subnet.
# ---------------------------------------------------------------------------
# TODO(w800): set to IXIA-mimic parent ranges reachable on the real w800 DUT
# interfaces (mirror the DUT's BGP_MONITOR placeholder ranges as IcePack does).
W800_IXIA_DOWNLINK_IC_PARENT_NETWORK_V6 = "2001:db8:0:1108"
W800_IXIA_UPLINK_IC_PARENT_NETWORK_V6 = "2001:db8:0:1109"
W800_IXIA_ROGUE_IC_PARENT_NETWORK_V6 = "2001:db8:0:110a"
W800_IXIA_DOWNLINK_IC_PARENT_NETWORK_V4 = "192.0.2"
W800_IXIA_UPLINK_IC_PARENT_NETWORK_V4 = "198.51.100"
W800_IXIA_ROGUE_IC_PARENT_NETWORK_V4 = "203.0.113"

# ---------------------------------------------------------------------------
# Route scale / peer counts
# ---------------------------------------------------------------------------
# Minimal first-pass scale (mirrors IcePack CPU-queue baseline: BGP peers are
# just anchors for IXIA traffic injection; CPU-queue assertions don't depend on
# prefix count). TODO(w800): tune once real w800 CPU headroom is known.
# TODO(w800): raised from the IcePack baseline (5000) to exercise higher route
# scale on w800; tune once real w800 CPU/FIB headroom is known.
W800_UNIQUE_PREFIX_LIMIT = "75000"
W800_PER_PEER_MAX_ROUTE_LIMIT = "20000"
W800_DOWNLINK_PEER_COUNT = 8
W800_UPLINK_PEER_COUNT = 8
W800_ROGUE_PEER_COUNT = 8
W800_IXIA_DOWNLINK_PREFIX_COUNT_V6 = 500
W800_IXIA_UPLINK_PREFIX_COUNT_V6 = 500
W800_IXIA_ROGUE_PREFIX_COUNT_V6 = 500
W800_IXIA_DOWNLINK_PREFIX_COUNT_V4 = 500
W800_IXIA_UPLINK_PREFIX_COUNT_V4 = 500
W800_IXIA_ROGUE_PREFIX_COUNT_V4 = 500

# ---------------------------------------------------------------------------
# Remote AS numbers (IXIA-mimic peers). Must DIFFER from the DUT's local AS
# (EBGP), since IXIA BGP-mimic uses step=1 and treats peers as EBGP.
# ---------------------------------------------------------------------------
# TODO(w800): confirm w800 DUT local AS and pick base ASNs well outside it.
W800_REMOTE_UPLINK_AS_4BYTE = 65272
W800_REMOTE_DOWNLINK_AS_4BYTE = 7001
W800_REMOTE_ROGUE_AS_4BYTE = 2500
W800_REMOTE_AS_4_BYTE_STEP = 1
W800_IS_UPLINK_PEER_CONFED = "False"
W800_IS_DOWNLINK_PEER_CONFED = "False"
W800_IS_ROGUE_PEER_CONFED = "False"

# ---------------------------------------------------------------------------
# BGP communities required for the DUT's ingress policy to ACCEPT + FIB-install
# IXIA-mimic routes (otherwise BGP_PREFIX_TRAFFIC background sees 100% loss).
# The exact set is policy-specific.
# ---------------------------------------------------------------------------
# TODO(w800): replace with the communities the w800 DUT's ingress route-map
# requires (inspect the real policy, as done for IcePack's PROPAGATE_GTSW_STSW_IN).
W800_IXIA_DOWNLINK_COMMUNITIES = ["65446:30", "65441:323", "65456:323"]
W800_IXIA_UPLINK_COMMUNITIES = ["65446:30", "65441:323", "65456:323"]

# Peer tags (labels for the mimic peer groups).
W800_DOWNLINK_PEER_TAG = "HOST"
W800_UPLINK_PEER_TAG = "UPLINK"

# ---------------------------------------------------------------------------
# Restart iteration counts (used by the factory's restart tasks/playbooks).
# ---------------------------------------------------------------------------
W800_BGPD_RESTART_NO_OF_ITERATIONS = 5
W800_WEDGE_AGENT_RESTART_NO_OF_ITERATIONS = 5

# ---------------------------------------------------------------------------
# Services monitored by the postcheck ServiceRestartHealthCheck.
# ---------------------------------------------------------------------------
# TODO(w800): confirm which services the w800 image actually runs. Placeholder
# mirrors the IcePack backend list (openr dropped). If the combined FE+BE w800
# role DOES run Open/R, add "openr" back.
W800_SERVICE_RESTART_SERVICES = [
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
# Consumed by wedge800_npi_test_config.py's W800_BGP_HARDENING_TEST_CONFIG,
# which calls build_bgp_dc_test_config() and selects the sheet's BGP_DC
# longevity playbooks. MOST device knobs above (device/mac/ixia interfaces,
# peer groups, route-maps, IC parent networks, peer counts, AS numbers, confed
# flags, prefix counts, communities, peer tags, basset pool) are SHARED with
# the CPU-queue config and reused directly. Only the BGP-DC-only extras live
# below.

# Aggregate DUT prefix limit for the BGP-DC build (string). Reuses the same
# 75000 scale as the CPU-queue unique-prefix limit (single source of truth).
W800_BGP_PREFIX_LIMIT = W800_UNIQUE_PREFIX_LIMIT

# Good/rogue NDP + ARP entry parent networks for the DUT-side neighbor tables.
# TODO(w800): set to real reachable stems on the w800 DUT. Placeholders use
# RFC3849 v6 doc ranges; ARP stems are 2-octet (matching the Kodiak-3 RBB
# reference shape).
W800_GOOD_NDP_ENTRY_NETWORK_V6 = "2001:db8:0:1109"
W800_ROGUE_NDP_ENTRY_NETWORK_V6 = "2001:db8:0:1108"
W800_GOOD_ARP_ENTRY_NETWORK_V4 = "192.168"
W800_ROGUE_ARP_ENTRY_NETWORK_V4 = "193.168"
W800_IXIA_UPLINK_GOOD_NDP_NETWORK = "2001:db8:0:1901"
W800_IXIA_DOWNLINK_GOOD_NDP_NETWORK = "2001:db8:0:1801"

# Neighbor-table / ECMP scale (ints). Mirror the Kodiak-3 RBB reference; tune
# once real w800 headroom is known. TODO(w800).
W800_ECMP_GROUP_LIMIT = 200
W800_ECMP_MEMBER_LIMIT = 5000
W800_GOOD_NDP_ENTRIES_UPLINK = 100
W800_GOOD_NDP_ENTRIES_DOWNLINK = 100
W800_ROGUE_NDP_ENTRIES = 50
W800_GOOD_ARP_ENTRIES = 100
W800_ROGUE_ARP_ENTRIES = 100
W800_GOOD_MAC_ENTRY_COUNT = 100
W800_ROGUE_MAC_ENTRY_COUNT = 200
W800_BGP_INDUCED_ECMP_GROUP_COUNT = 50

# ===========================================================================
# Longevity tests (snake / loopback standalone -> test_72hr_longevity)
# ===========================================================================
# Consumed by wedge800_npi_test_config.py's W800_LONGEVITY_TEST_CONFIG, which
# calls gen_snake_test_config() -- the ONLY builder that emits the sheet's
# test_72hr_longevity playbook. Snake = single-DUT loopback: one source port
# jumpered to one destination port on the SAME DUT, with point-to-point IPv6
# addressing. Standalone snake tests use the dne.standalone basset pool by
# convention. TODO(w800): real looped interfaces + jumper IPs once the DUT is
# racked and cabled.
W800_STANDALONE_BASSET_POOL = "dne.standalone"
W800_SNAKE_SOURCE_INTERFACE = "eth1/1/1"
W800_SNAKE_DEST_INTERFACE = "eth1/2/1"
W800_SNAKE_SOURCE_IP = "5000:1::1/64"
W800_SNAKE_DEST_IP = "5000:1::2/64"

# ===========================================================================
# Snake tests (per speed grade)
# ===========================================================================
# Consumed by wedge800_npi_test_config.py's W800_SNAKE_*_TEST_CONFIG, built
# with gen_snake_test_config() -- the same builder as the longevity config
# above, but one TestConfig per speed grade (the shape the reference
# MINIPACK3_STANDALONE_TEST_CONFIG_{400G,800G} configs use) so a failure
# names the speed it happened at.
#
# Each loop entry is (source_interface, destination_interface, source_ip,
# destination_ip); source and destination are two cages on the SAME DUT
# joined by a fiber jumper, with point-to-point /64 addressing. Every loop
# in a config must run at that config's speed grade.
#
# The 800G loop deliberately reuses the longevity jumper above: it is the
# same physical cable, so it must not be described twice.
# TODO(w800): real jumpered cages per speed grade once the DUT is cabled.
W800_SNAKE_800G_LOOPS = [
    (
        W800_SNAKE_SOURCE_INTERFACE,
        W800_SNAKE_DEST_INTERFACE,
        W800_SNAKE_SOURCE_IP,
        W800_SNAKE_DEST_IP,
    ),
]
W800_SNAKE_400G_LOOPS = [
    ("eth1/3/1", "eth1/4/1", "5000:2::1/64", "5000:2::2/64"),
    ("eth1/3/5", "eth1/4/5", "4000:2::1/64", "4000:2::2/64"),
]

# 99% rather than 100%: the reference 800G snake caps line rate to stay under
# the IXIA overspeed rounding that reports false loss (T227297634).
W800_SNAKE_LINE_RATE = 99
W800_SNAKE_ITERATION = 10
# FRONTEND IMIX distribution -- the DEFAULT_FRAME_SIZE weights from
# qos_scheduling_test_config.py. Deliberately NOT the DSF_FRAME_SIZES weights
# the reference Minipack3 800G snake uses: those are the backend/DSF fabric
# profile, and w800 is a frontend platform.
W800_SNAKE_IMIX_WEIGHT = {100: 1, 1500: 4, 4500: 5, 7000: 1, 9000: 1}

# ===========================================================================
# Thrift hardening tests (THFT_001..005)
# ===========================================================================
# Consumed by wedge800_npi_test_config.py's W800_THRIFT_HARDENING_TEST_CONFIG.
# ALL BGP scaffolding knobs are SHARED with the CPU-queue / BGP configs above
# and reused directly; the only THFT-specific value is the flap-port list.
# stsw_flap_ports = DUT-side NBR/STSW-adjacent uplink ports the qsfp-flap
# background will tx_disable/tx_enable. MUST EXCLUDE the IXIA-facing ports
# (W800_IXIA_*_INTERFACE) -- flapping those breaks IXIA peering and would
# invalidate the BGP_SESSION_ESTABLISH precheck.
# TODO(w800): real NBR-adjacent uplink ports once the DUT is racked/cabled.
W800_STSW_FLAP_PORTS = [
    "eth1/5/1",
    "eth1/6/1",
]

# ===========================================================================
# Speed flip tests (subsume-churn / SPD_041)
# ===========================================================================
# Consumed by wedge800_npi_test_config.py's W800_SPEED_FLIP_SUBSUME_CHURN_TEST_CONFIG,
# which calls build_subsume_churn_test_config() from speed_flip_test_configs.py
# (the SPD_041 factory landed in D113718643). The factory requires EXACTLY 6
# circuits = 3 dual cages x 2 subports (/1 and /5); a_end = DUT cage base,
# z_end = peer interface base. NOTE: most other w800 speed-flip rows in the
# test plan are "not feasible in OSS" (GSC-native circuit-DB / config-generate
# / reprovision paths); the reboot/coldboot/800G rows that ARE feasible reuse
# hardcoded dataclass literals in speed_flip_test_configs.py (no device-
# parameterized factory) and are deferred until real w800 port maps exist.
# TODO(w800): real DUT cages + peer device/interfaces once racked and cabled.
W800_SPEED_FLIP_PEER_DEVICE_NAME = "wedge800peer001.TODO.example"
W800_SPEED_FLIP_CHURN_ITERATIONS = 10
# (dut_cage_base, peer_interface_base); each contributes a /1 and /5 subport.
W800_SPEED_FLIP_CHURN_CAGES = [
    ("eth1/17", "eth1/1"),
    ("eth1/21", "eth1/2"),
    ("eth1/22", "eth1/3"),
]
