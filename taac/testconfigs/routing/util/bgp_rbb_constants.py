# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""RBB SRv6 qualification — shared constants (GENERIC / OSS-safe).

Single source of truth for the two-node RBB SRv6 slice: BGP AS numbers, the
SRv6 locator / uSID / decap-SID plan, the TE_AGENT route-owner lifecycle
tokens, and the IXIA traffic-item names the packet-loss health check asserts on.

Nothing lab-specific is committed here:
  * Hostnames / IXIA chassis are placeholders overridable via ``TAAC_RBB_*``.
  * The SRv6 plan defaults to the IPv6 **documentation** range (RFC 3849,
    ``2001:db8::/32``) and the tail prefix to the IPv4 documentation range
    (RFC 5737); override every value via ``TAAC_RBB_SRV6_*`` / ``TAAC_RBB_TAIL_PREFIX``.
  * Physical wiring (core port-channels + members, IXIA edges + ports) is NOT
    here — it is derived from the run's ``circuit_info.csv`` by
    ``bgp_rbb_topology.load_rbb_topology`` (generic fallback when absent).

The only address-shaped constants kept here are FBOSS-generic *behavior tokens*
(``ADJACENCY_MICRO_SID`` / ``DECAPSULATE_AND_LOOKUP``) and FBOSS ``ClientID``
names (``TE_AGENT`` / ``BGPD``) — these are platform-generic, not lab-specific.
"""

import os
import typing as t


def locator_token(locator: str) -> str:
    """Derive the ``show mysid`` assert token from an SRv6 locator prefix.

    ``2001:db8:6::/48`` → ``2001:db8:6:``.
    The token is the locator address with the mask and any trailing ``::``
    stripped, guaranteed to end in a single ``:`` so it matches the uSID column
    of ``fboss2 show mysid`` regardless of the configured locator.
    """
    addr = locator.split("/", 1)[0]
    tok = addr.rstrip(":")
    return tok if tok.endswith(":") else tok + ":"


# ─── Device identity (env-overridable) ────────────────────────────────────
# R1 = head/mid emulation, R2 = tail emulation. Defaults are non-routable
# example names; set the env vars (and/or supply a device_info CSV) to bind the
# real lab boxes at run time.
R1_HOSTNAME: str = os.environ.get("TAAC_RBB_R1_HOST", "rbb-r1.lab.example")
R2_HOSTNAME: str = os.environ.get("TAAC_RBB_R2_HOST", "rbb-r2.lab.example")

# IXIA chassis handle (IPv6/hostname). Placeholder; override via env.
IXIA_CHASSIS: str = os.environ.get("TAAC_RBB_IXIA_CHASSIS", "rbb-ixia.lab.example")

# ─── BGP AS plan ──────────────────────────────────────────────────────────
R1_BGP_AS: int = int(os.environ.get("TAAC_RBB_R1_AS", "65001"))
R2_BGP_AS: int = int(os.environ.get("TAAC_RBB_R2_AS", "65002"))
# Generic RFC 6996 private-use ASN placeholder; the real edge ASN is supplied
# by the uncommitted lab profile (TAAC_RBB_IXIA_AS / TAAC_RBB_IXIA_R1_AS).
IXIA_EDGE_BGP_AS: int = int(os.environ.get("TAAC_RBB_IXIA_AS", "64512"))

# ─── SRv6 plan (env-overridable; documentation-range defaults) ────────────
# Defaults live entirely in the RFC 3849 IPv6 documentation block so the
# committed repo carries NO operator locator. Set TAAC_RBB_SRV6_LOCATOR and the
# per-node uSIDs to your real plan at run time; the S11 verify asserts on the
# token DERIVED from TAAC_RBB_SRV6_LOCATOR (see ``locator_token``), never a
# hardcoded block.
SRV6_LOCATOR: str = os.environ.get("TAAC_RBB_SRV6_LOCATOR", "2001:db8:6::/48")
SRV6_LOCATOR_TOKEN: str = locator_token(SRV6_LOCATOR)

# SRv6 endpoint-behavior tokens as rendered by ``fboss2 show mysid``. These are
# FBOSS-generic (platform behavior names), not lab-specific — keep as constants.
SRV6_BEHAVIOR_ADJACENCY: str = "ADJACENCY_MICRO_SID"
SRV6_BEHAVIOR_DECAP: str = "DECAPSULATE_AND_LOOKUP"

# Representative per-node uSIDs (documentation-range defaults under the default
# locator). Retained for the Srv6Profile bundle / TC2 baseline; the live verify
# asserts SRV6_LOCATOR_TOKEN + behaviors above rather than these exact values.
SRV6_USID_HEAD: str = os.environ.get("TAAC_RBB_SRV6_USID_HEAD", "2001:db8:6:cc::")
SRV6_USID_MID: str = os.environ.get("TAAC_RBB_SRV6_USID_MID", "2001:db8:6:d6::")
SRV6_USID_TAIL: str = os.environ.get("TAAC_RBB_SRV6_USID_TAIL", "2001:db8:6:ffff::")
SRV6_DECAP_SID: str = os.environ.get("TAAC_RBB_SRV6_DECAP_SID", SRV6_USID_TAIL)

# Tail destination prefix for the TE_AGENT direct-route lifecycle. Default is the
# IPv4 documentation range (RFC 5737); override to your real BGPD-owned prefix.
# The direct-route task adds a more-preferred TE_AGENT copy (reusing the exact
# resolved nexthops, so forwarding is unchanged) and then withdraws it, proving
# the S22/S28 owner transition non-destructively.
TAIL_DEST_PREFIX: str = os.environ.get("TAAC_RBB_TAIL_PREFIX", "203.0.113.0/24")

# Optional substring asserted (in addition to the port-channel name) for the S10
# PC-RIF verify. Parameterized so neither a global-v6 address nor a /30 subnet is
# hardcoded: leave empty (default) to assert only the port-channel's presence, or
# set to e.g. your core /30 subnet or global-v6 token to also assert the RIF.
PC162_RIF_TOKEN: str = os.environ.get("TAAC_RBB_PC162_RIF_TOKEN", "")

# Route-owner tokens matched in ``fboss2 show route details`` (Client: <name>)
# by the verify task. These are real FBOSS ClientID enum names (TE_AGENT=800,
# BGPD=0), not free-form strings — platform-generic, not lab-specific.
ROUTE_OWNER_TE_AGENT: str = "TE_AGENT"
ROUTE_OWNER_BGPD: str = "BGPD"

# ─── IXIA traffic items (asserted by the packet-loss health check) ────────
# One bidirectional item R1-edge ↔ R2-edge across the SRv6 core.
TRAFFIC_ITEM_R1_TO_R2: str = "RBB_R1_TO_R2_SRV6"
TRAFFIC_ITEM_R2_TO_R1: str = "RBB_R2_TO_R1_SRV6"
ALL_TRAFFIC_ITEMS: t.Tuple[str, ...] = (
    TRAFFIC_ITEM_R1_TO_R2,
    TRAFFIC_ITEM_R2_TO_R1,
)

# ─── Timing ───────────────────────────────────────────────────────────────
CONVERGENCE_WAIT_SECONDS: int = 60
TRAFFIC_RUN_SECONDS: int = 120
PACKET_LOSS_THRESHOLD_PCT: str = "0.1"


# ─── Control-plane + underlay gate tokens (S02-S07 / S13) ─────────────────
# The S02-S05 core-link-up gate asserts each core port-channel's members are
# present in ``fboss2 show aggregate-port`` (members drop out of the table when
# a link is down). An additional liveness substring can be asserted via the env
# below (e.g. the FBOSS forwarding token). Default empty → assert PC + members
# present only (topology-derived; nothing lab-specific committed).
CORE_MEMBER_UP_TOKEN: str = os.environ.get("TAAC_RBB_CORE_UP_TOKEN", "")

# The S06 OpenR / S07 iBGP gates prefer shipped OSS health checks
# (OPENR_INITIALIZED/ADJACENCY/SPARK_NEIGHBOR, BGP_SESSION_ESTABLISH,
# BGP_CONVERGENCE, OPENR_FIB_VALIDATE). The S07 "loopbacks learned" sub-gate is
# a verify-task asserting the PEER node's loopback is present in the local RIB;
# the loopback values come from the (env-overridable, doc-range) R{1,2}_ROUTER_ID
# / R{1,2}_LOOPBACK_V6 constants above — nothing lab-specific committed.
# Expected established core iBGP sessions per DUT (one loopback peer each).
CORE_IBGP_EXPECTED_SESSIONS: int = int(
    os.environ.get("TAAC_RBB_CORE_IBGP_SESSIONS", "1")
)
# Expected OpenR spark neighbors per DUT (peer across the two core PCs).
OPENR_EXPECTED_NEIGHBORS: int = int(os.environ.get("TAAC_RBB_OPENR_NEIGHBORS", "0"))


# ─── IXIA eBGP edge emulation (increments B/C; doc-range defaults) ─────────
# Emulated eBGP AS on each IXIA edge. R1 (head) edge = IXIA port 3; R2 (tail)
# edge = IXIA port 10. Real values go in the uncommitted lab profile.
IXIA_R1_EDGE_AS: int = int(os.environ.get("TAAC_RBB_IXIA_R1_AS", str(IXIA_EDGE_BGP_AS)))
# Generic RFC 6996 private-use ASN placeholder; real value in the lab profile.
IXIA_R2_EDGE_AS: int = int(os.environ.get("TAAC_RBB_IXIA_R2_AS", "64513"))

# IXIA edge link addressing (the emulated-router address + its gateway, i.e. the
# DUT edge RIF). Doc-range (RFC 3849) defaults; real values in the lab profile.
IXIA_R1_EDGE_V6: str = os.environ.get("TAAC_RBB_IXIA_R1_EDGE_V6", "2001:db8:a:3::2")
IXIA_R1_EDGE_GW_V6: str = os.environ.get(
    "TAAC_RBB_IXIA_R1_EDGE_GW_V6", "2001:db8:a:3::1"
)
IXIA_R2_EDGE_V6: str = os.environ.get("TAAC_RBB_IXIA_R2_EDGE_V6", "2001:db8:a:10::2")
IXIA_R2_EDGE_GW_V6: str = os.environ.get(
    "TAAC_RBB_IXIA_R2_EDGE_GW_V6", "2001:db8:a:10::1"
)
IXIA_EDGE_PREFIX_MASK: int = int(os.environ.get("TAAC_RBB_IXIA_EDGE_MASK", "64"))
# agent.conf SVI (interface) id for the IXIA edge port (eth1/1/1 -> Vlan/intf
# 2000 + port-id 1 = 2001 on both DUTs). Used by the edge-eBGP task to add the
# tail edge RIF when the SVI has no address yet. Generic FBOSS numbering.
IXIA_EDGE_INTF_ID: int = int(os.environ.get("TAAC_RBB_IXIA_EDGE_INTF_ID", "2001"))

# Remote prefix pool advertised at the R2/port-10 (tail) edge. This is the INNER
# destination the port-3 traffic targets: R1 SRv6-encaps toward R2, R2 decaps +
# inner-looks-up into this pool and forwards to IXIA port 10 (so decap+forward
# succeeds and yields real receipt on port 10). Doc-range default; real pool in
# the uncommitted lab profile.
IXIA_TAIL_ADVERTISED_PREFIX: str = os.environ.get(
    "TAAC_RBB_IXIA_TAIL_PREFIX", "2001:db8:beef::"
)
IXIA_TAIL_ADVERTISED_PREFIX_LEN: int = int(
    os.environ.get("TAAC_RBB_IXIA_TAIL_PREFIX_LEN", "64")
)
IXIA_TAIL_ADVERTISED_PREFIX_COUNT: int = int(
    os.environ.get("TAAC_RBB_IXIA_TAIL_PREFIX_COUNT", "100")
)
IXIA_TAIL_PREFIX_POOL_NAME: str = "RBB_TAIL_REMOTE_V6"

# Return-path prefix pool advertised at the R1/port-3 (head) edge.
IXIA_HEAD_ADVERTISED_PREFIX: str = os.environ.get(
    "TAAC_RBB_IXIA_HEAD_PREFIX", "2001:db8:cafe::"
)
IXIA_HEAD_ADVERTISED_PREFIX_LEN: int = int(
    os.environ.get("TAAC_RBB_IXIA_HEAD_PREFIX_LEN", "64")
)
IXIA_HEAD_ADVERTISED_PREFIX_COUNT: int = int(
    os.environ.get("TAAC_RBB_IXIA_HEAD_PREFIX_COUNT", "100")
)
IXIA_HEAD_PREFIX_POOL_NAME: str = "RBB_HEAD_REMOTE_V6"

# Minimum count of remote IXIA prefixes expected to propagate over the core iBGP
# to R1 (S17-S18 route-count gate). Defaults to 1 (documentation-safe minimum).
IXIA_REMOTE_ROUTE_MIN_COUNT: int = int(
    os.environ.get("TAAC_RBB_IXIA_REMOTE_ROUTE_MIN", "1")
)

# Data-path traffic model (S13-S20 baseline / S24-S25 TE_AGENT path).
TRAFFIC_LINE_RATE_PCT: int = int(os.environ.get("TAAC_RBB_TRAFFIC_LINE_RATE", "10"))
TRAFFIC_FRAME_SIZE: int = int(os.environ.get("TAAC_RBB_TRAFFIC_FRAME_SIZE", "512"))

# S14-S18 edge eBGP emulation + DUT-side edge eBGP is OPT-IN. The default lab
# underlay runs iBGP-only over loopbacks (no eBGP toward IXIA), so bringing up a
# DUT-side edge eBGP peer is a config change (disruptive) and the v6 remote-route
# propagation gate only holds once both edges carry the eBGP session. Set
# TAAC_RBB_EDGE_EBGP=1 to include the DUT-side edge eBGP setup + the eBGP session
# / remote-route / FIB gates. Default off keeps runs non-destructive.
EDGE_EBGP_ENABLED: bool = os.environ.get("TAAC_RBB_EDGE_EBGP", "").lower() in (
    "1",
    "true",
    "yes",
)

# S25 SRv6 encap (R1) / decap (R2) counter tokens rendered by the FBOSS
# per-SID/agent counter reads. Platform-generic tokens, not lab-specific.
SRV6_ENCAP_COUNTER_TOKEN: str = os.environ.get(
    "TAAC_RBB_SRV6_ENCAP_TOKEN", "srv6"
)
SRV6_DECAP_COUNTER_TOKEN: str = os.environ.get(
    "TAAC_RBB_SRV6_DECAP_TOKEN", "decap"
)


# ─── Provisioning (from-scratch config generation) ────────────────────────
# OPT-IN. Only when TAAC_RBB_PROVISION=1 do the RBB factories prepend the
# ``provision_fboss_*`` setup tasks that GENERATE and PUSH agent.conf / bgp.json
# / openr.conf to a freshly imaged MORGAN800CC DUT. This is DISRUPTIVE (restarts
# the agent, bgpd and openr). Default off: the suite assumes a pre-provisioned
# underlay. See ``fboss_config_gen`` + the ``provision_fboss_*`` tasks.
PROVISION_ENABLED: bool = os.environ.get("TAAC_RBB_PROVISION", "").lower() in (
    "1",
    "true",
    "yes",
)

# Guard: provisioning only runs on this hardware family (asicType 15). Comma-list
# of accepted hardware tokens; matched case-insensitively as a substring.
PROVISION_HARDWARE_ALLOWLIST: t.Tuple[str, ...] = tuple(
    h.strip()
    for h in os.environ.get(
        "TAAC_RBB_PROVISION_HW_ALLOWLIST", "MORGAN800CC"
    ).split(",")
    if h.strip()
)
PROVISION_ASIC_TYPE: int = int(os.environ.get("TAAC_RBB_PROVISION_ASIC_TYPE", "15"))

# On-box config paths (reference deployment: Cisco 8501 / MORGAN800CC split
# agent). Override only if your image differs.
AGENT_CONFIG_PATH: str = os.environ.get(
    "TAAC_RBB_AGENT_CONFIG_PATH", "/etc/coop/agent.conf"
)
BGP_CONFIG_PATH: str = os.environ.get("TAAC_RBB_BGP_CONFIG_PATH", "/opt/bgpd/bgp.json")
BGP_POLICY_PATH: str = os.environ.get(
    "TAAC_RBB_BGP_POLICY_PATH", "/opt/bgpd/policy.json"
)
OPENR_CONFIG_PATH: str = os.environ.get(
    "TAAC_RBB_OPENR_CONFIG_PATH", "/opt/openr/openr.conf"
)
# On-box platform mapping (MORGAN800CC). The generator reads the box's
# ``MetaGeneratedPlatformMapping_<date>.json`` to resolve port identity. That
# date-stamped filename is image-build-specific, so NO dated filename is baked in
# here as the effective default: the real path is resolved ON THE DEVICE at run
# time by globbing the mapping directory and picking the newest/lexically-last
# ``MetaGeneratedPlatformMapping*.json`` match (see
# ``rbb_provision_utils.async_resolve_platform_mapping_path``). Precedence:
#   1. ``TAAC_RBB_PLATFORM_MAPPING_PATH`` — exact file, skips the device glob.
#   2. ``TAAC_RBB_PLATFORM_MAPPING_DIR``  — directory to glob (default below).
#   3. ``PLATFORM_MAPPING_FALLBACK_PATH`` — used only if the glob finds nothing.
PLATFORM_MAPPING_PATH: str = os.environ.get("TAAC_RBB_PLATFORM_MAPPING_PATH", "")
PLATFORM_MAPPING_DIR: str = os.environ.get(
    "TAAC_RBB_PLATFORM_MAPPING_DIR", "/opt/fboss/share"
)
PLATFORM_MAPPING_GLOB: str = "MetaGeneratedPlatformMapping*.json"
# Sensible, non-date-stamped fallback if the on-device glob matches nothing.
PLATFORM_MAPPING_FALLBACK_PATH: str = (
    PLATFORM_MAPPING_DIR.rstrip("/") + "/MetaGeneratedPlatformMapping.json"
)

# Single iBGP AS by default (both DUTs); router-id = loopback v4.
CORE_IBGP_AS: int = int(os.environ.get("TAAC_RBB_CORE_AS", str(R1_BGP_AS)))

# Loopbacks (v4 = router-id). Doc-range defaults (RFC 5737 / RFC 3849).
R1_ROUTER_ID: str = os.environ.get("TAAC_RBB_R1_ROUTER_ID", "192.0.2.1")
R2_ROUTER_ID: str = os.environ.get("TAAC_RBB_R2_ROUTER_ID", "192.0.2.2")
R1_LOOPBACK_V6: str = os.environ.get("TAAC_RBB_R1_LOOPBACK_V6", "2001:db8:0:1::1")
R2_LOOPBACK_V6: str = os.environ.get("TAAC_RBB_R2_LOOPBACK_V6", "2001:db8:0:2::1")

# Extra locally originated v4 prefixes (comma-separated CIDR), beyond loopbacks.
R1_NETWORKS4_EXTRA: t.Tuple[str, ...] = tuple(
    p.strip()
    for p in os.environ.get("TAAC_RBB_R1_NETWORKS4", "").split(",")
    if p.strip()
)
R2_NETWORKS4_EXTRA: t.Tuple[str, ...] = tuple(
    p.strip()
    for p in os.environ.get("TAAC_RBB_R2_NETWORKS4", "").split(",")
    if p.strip()
)

# VLAN/interface numbering scheme for the generated SVI RIFs (generic, fixed).
LOOPBACK_VLAN: int = 4000
CORE_RIF_VLAN_BASE: int = 2011  # first core PC RIF => Vlan2011, next => Vlan2012...
EDGE_RIF_VLAN_BASE: int = 2001  # first IXIA edge RIF => Vlan2001, next => Vlan2002...
SRV6_SID_VLAN_A: int = 10  # SRv6 SID interface (mySid decap side)
SRV6_SID_VLAN_B: int = 11  # SRv6 SID interface (tunnel src side)

# mySid decap SID key (tail node). Numeric SID index, not a lab secret.
DECAP_MYSID_KEY: str = os.environ.get("TAAC_RBB_DECAP_MYSID_KEY", "32767")

# SRv6 tunnel id label (FBOSS-generic).
SRV6_TUNNEL_ID: str = os.environ.get("TAAC_RBB_SRV6_TUNNEL_ID", "srv6_tunnel")
