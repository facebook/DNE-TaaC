# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""RBB SRv6 qualification — shared constants (GENERIC / OSS-safe).

Single source of truth for the two-node RBB SRv6 slice: BGP AS numbers, the
SRv6 locator / uSID / decap-SID plan, the TE_AGENT route-owner lifecycle
tokens, and the IXIA traffic-item names the packet-loss health check asserts on.

Nothing lab-specific is committed here:
  * Hostnames / IXIA chassis are placeholders overridable via ``TAAC_RBB_*``.
  * The SRv6 plan and traffic prefixes default to the IPv6 **documentation**
    range (RFC 3849, ``2001:db8::/32``); override every value via
    ``TAAC_RBB_SRV6_*`` / ``TAAC_RBB_TAIL_PREFIX``.
  * Physical wiring (core port-channels + members, IXIA edges + ports) is NOT
    here — it is derived from the run's ``circuit_info.csv`` by
    ``bgp_rbb_topology.load_rbb_topology`` (generic fallback when absent).

The only address-shaped constants kept here are FBOSS-generic *behavior tokens*
(``ADJACENCY_MICRO_SID`` / ``DECAPSULATE_AND_LOOKUP``) and FBOSS ``ClientID``
names (``TE_AGENT`` / ``BGPD``) — these are platform-generic, not lab-specific.
"""

import ipaddress
import os
import typing as t


def locator_token(locator: str) -> str:
    """Derive the ``show mysid`` assert token from an SRv6 locator prefix.

    ``2001:db8:6::/48`` → ``2001:db8:6:``.
    The token is the locator address with the mask and any trailing ``::``
    stripped, guaranteed to end in a single ``:`` so it matches the uSID column
    of ``fboss2 show mysid`` regardless of the configured locator.
    """
    network = ipaddress.ip_network(locator, strict=False)
    if network.version != 6:
        raise ValueError("SRv6 locator must be IPv6")
    addr = str(network.network_address)
    tok = addr.rstrip(":")
    return tok if tok.endswith(":") else tok + ":"


def default_usid(locator: str, function: int) -> str:
    """Place a documentation/default function in the locator's next 16 bits."""
    network = ipaddress.ip_network(locator, strict=False)
    if network.version != 6 or network.prefixlen > 112:
        raise ValueError("SRv6 locator must be IPv6 and leave a 16-bit function")
    if network.prefixlen % 16:
        raise ValueError("uSID locator length must be aligned to 16 bits")
    if not 0 <= function <= 0x7FFF:
        raise ValueError("SRv6 function must fit MySidConfig's positive i16 range")
    address = int(network.network_address) | (
        function << (128 - network.prefixlen - 16)
    )
    return str(ipaddress.IPv6Address(address))


def pack_usid_container(locator: str, usids: t.Iterable[str]) -> str:
    """Pack individual 16-bit uSIDs into one IPv6 segment container.

    ``2001:db8::/32`` plus ``2001:db8:27cc::``,
    ``2001:db8:27d6::``, and ``2001:db8:7fff::`` becomes
    ``2001:db8:27cc:27d6:7fff::``. FBOSS programs SRv6 encapsulation from a
    route's ``srv6SegmentList``; a plain next-hop address inside the locator is
    not an SRv6 segment list.
    """
    network = ipaddress.ip_network(locator, strict=False)
    if network.version != 6:
        raise ValueError("SRv6 locator must be IPv6")
    if network.prefixlen % 16:
        raise ValueError("uSID locator length must be aligned to 16 bits")

    sid_values = tuple(usids)
    capacity = (128 - network.prefixlen) // 16
    if not sid_values:
        raise ValueError("at least one uSID is required")
    if len(sid_values) > capacity:
        raise ValueError(
            f"{len(sid_values)} uSIDs do not fit after locator {locator!r} "
            f"(capacity {capacity})"
        )

    function_shift = 128 - network.prefixlen - 16
    packed = int(network.network_address)
    for index, sid in enumerate(sid_values):
        address = ipaddress.ip_address(sid)
        if address.version != 6 or address not in network:
            raise ValueError(f"uSID {sid!r} is outside IPv6 locator {locator!r}")
        function = (int(address) >> function_shift) & 0xFFFF
        trailing_mask = (1 << function_shift) - 1 if function_shift else 0
        if int(address) & trailing_mask:
            raise ValueError(
                f"uSID {sid!r} must contain one 16-bit function after the locator"
            )
        if function == 0:
            raise ValueError(f"uSID {sid!r} has a zero function")
        packed |= function << (128 - network.prefixlen - (index + 1) * 16)
    return str(ipaddress.IPv6Address(packed))


# ─── Device identity (env-overridable) ────────────────────────────────────
# R1 = ingress/head plus transit; R2 = midpoint adjacency plus tail decap.
# Defaults are non-routable example names; set the env vars (and/or supply a
# device_info CSV) to bind the real lab boxes at run time.
R1_HOSTNAME: str = os.environ.get("TAAC_RBB_R1_HOST", "rbb-r1.lab.example")
R2_HOSTNAME: str = os.environ.get("TAAC_RBB_R2_HOST", "rbb-r2.lab.example")
R1_HARDWARE: str = os.environ.get("TAAC_RBB_R1_HARDWARE", "GENERIC_FBOSS")
R2_HARDWARE: str = os.environ.get("TAAC_RBB_R2_HARDWARE", "GENERIC_FBOSS")

# IXIA chassis handle (IPv6/hostname). Placeholder; override via env.
IXIA_CHASSIS: str = os.environ.get("TAAC_RBB_IXIA_CHASSIS", "rbb-ixia.lab.example")

# ─── BGP AS plan ──────────────────────────────────────────────────────────
# The core session is iBGP, so both nodes must use one AS. Keep the original
# per-node variable names as compatibility aliases, but reject conflicting
# values rather than quietly generating a non-establishing "iBGP" session.
_LEGACY_R1_AS: t.Optional[str] = os.environ.get("TAAC_RBB_R1_AS")
_LEGACY_R2_AS: t.Optional[str] = os.environ.get("TAAC_RBB_R2_AS")
CORE_IBGP_AS: int = int(
    os.environ.get("TAAC_RBB_CORE_AS")
    or _LEGACY_R1_AS
    or _LEGACY_R2_AS
    or "65001"
)
R1_BGP_AS: int = int(_LEGACY_R1_AS or CORE_IBGP_AS)
R2_BGP_AS: int = int(_LEGACY_R2_AS or CORE_IBGP_AS)
if R1_BGP_AS != CORE_IBGP_AS or R2_BGP_AS != CORE_IBGP_AS:
    raise ValueError(
        "RBB core is iBGP: TAAC_RBB_R1_AS, TAAC_RBB_R2_AS, and "
        "TAAC_RBB_CORE_AS must resolve to the same AS"
    )
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
# locator). Retained for the Srv6Profile bundle; the live verify
# asserts the corresponding full SID rendered by ``fboss2 show mysid`` plus the
# behavior. The decimal MySID keys below are agent-config map keys and are not
# part of that CLI's output.
SRV6_USID_HEAD: str = os.environ.get("TAAC_RBB_SRV6_USID_HEAD") or default_usid(
    SRV6_LOCATOR, 0x27CC
)
SRV6_USID_MID: str = os.environ.get("TAAC_RBB_SRV6_USID_MID") or default_usid(
    SRV6_LOCATOR, 0x27D6
)
SRV6_USID_TAIL: str = os.environ.get("TAAC_RBB_SRV6_USID_TAIL") or default_usid(
    SRV6_LOCATOR, 0x7FFF
)
SRV6_DECAP_SID: str = os.environ.get("TAAC_RBB_SRV6_DECAP_SID", SRV6_USID_TAIL)

# Tail destination prefix for the TE_AGENT lifecycle.  Its default is derived
# from the first IXIA tail pool prefix below so the route being exercised and
# the packets being sent cannot silently target different address families.
_DEFAULT_IXIA_TAIL_PREFIX: str = os.environ.get(
    "TAAC_RBB_IXIA_TAIL_PREFIX", "2001:db8:beef::"
)
_DEFAULT_IXIA_TAIL_PREFIX_LEN: int = int(
    os.environ.get("TAAC_RBB_IXIA_TAIL_PREFIX_LEN", "64")
)
TAIL_DEST_PREFIX: str = os.environ.get(
    "TAAC_RBB_TAIL_PREFIX",
    f"{_DEFAULT_IXIA_TAIL_PREFIX}/{_DEFAULT_IXIA_TAIL_PREFIX_LEN}",
)

# Optional platform-specific display token for the S10 core-RIF verify. When it
# is empty, TAAC derives the expected IPv6 address from the topology-selected
# CORE<n> setting. Most users should leave this unset.
PC162_RIF_TOKEN: str = os.environ.get("TAAC_RBB_PC162_RIF_TOKEN", "")

# Route-owner tokens matched in ``fboss2 show route details`` (Client: <name>)
# by the verify task. These are real FBOSS ClientID enum names (TE_AGENT=800,
# BGPD=0), not free-form strings — platform-generic, not lab-specific.
ROUTE_OWNER_TE_AGENT: str = "TE_AGENT"
ROUTE_OWNER_BGPD: str = "BGPD"

# ─── IXIA traffic items (asserted by the packet-loss health check) ────────
# The qualification flow is intentionally one-way: ingress R1 to tail R2.
# Reverse ordinary-IPv6 traffic does not add SRv6 coverage.
TRAFFIC_ITEM_R1_TO_R2: str = "RBB_R1_TO_R2_SRV6"
ALL_TRAFFIC_ITEMS: t.Tuple[str, ...] = (
    TRAFFIC_ITEM_R1_TO_R2,
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

# The S06 OpenR gate uses an OSS-safe verify task because the shipped OpenR
# health checks depend on internal Thrift services. S07 uses the shipped BGP
# session check plus a verify task asserting the peer loopback in the local RIB.
# Loopback values come from the env-overridable, documentation-range defaults
# below; nothing lab-specific is committed.
# ─── IXIA eBGP edge emulation (increments B/C; doc-range defaults) ─────────
# Emulated eBGP AS on each selected IXIA edge. Real values go in the run profile.
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
# Remote prefix pool advertised at the selected R2 (tail) edge. This is the
# INNER destination the selected R1-edge traffic targets: R1 encapsulates toward
# R2, which decapsulates and forwards to IXIA. Documentation-range default; the
# real pool is supplied by the run profile.
IXIA_TAIL_ADVERTISED_PREFIX: str = os.environ.get(
    "TAAC_RBB_IXIA_TAIL_PREFIX", _DEFAULT_IXIA_TAIL_PREFIX
)
IXIA_TAIL_ADVERTISED_PREFIX_LEN: int = int(
    os.environ.get(
        "TAAC_RBB_IXIA_TAIL_PREFIX_LEN", str(_DEFAULT_IXIA_TAIL_PREFIX_LEN)
    )
)
IXIA_TAIL_ADVERTISED_PREFIX_COUNT: int = int(
    os.environ.get("TAAC_RBB_IXIA_TAIL_PREFIX_COUNT", "1")
)
IXIA_TAIL_PREFIX_POOL_NAME: str = "RBB_TAIL_REMOTE_V6"

# TAAC's IXIA backend normally restricts advertised routes to its global
# allowlist. Keep that protection by default. An isolated lab that owns a
# different prefix can explicitly opt out for this RBB TestConfig after the
# preflight has constrained the advertisement to one exact IPv6 prefix.
SKIP_ADVERTISED_PREFIXES_CHECK: bool = os.environ.get(
    "TAAC_RBB_SKIP_ADVERTISED_PREFIXES_CHECK", ""
).lower() in ("1", "true", "yes")

# Minimum count of remote IXIA prefixes expected to propagate over the core iBGP
# to R1 (S17-S18 route-count gate). Defaults to 1 (documentation-safe minimum).
IXIA_REMOTE_ROUTE_MIN_COUNT: int = int(
    os.environ.get("TAAC_RBB_IXIA_REMOTE_ROUTE_MIN", "1")
)

# Data-path traffic model (S13-S20 baseline / S24-S25 TE_AGENT path).
TRAFFIC_LINE_RATE_PCT: int = int(os.environ.get("TAAC_RBB_TRAFFIC_LINE_RATE", "10"))
TRAFFIC_FRAME_SIZE: int = int(os.environ.get("TAAC_RBB_TRAFFIC_FRAME_SIZE", "512"))

# Traffic is opt-in.  A plain factory import must never reserve a chassis or
# mutate a DUT merely because the caller did not know about an environment flag.
INCLUDE_TRAFFIC: bool = os.environ.get("TAAC_RBB_INCLUDE_TRAFFIC", "").lower() in (
    "1",
    "true",
    "yes",
)

# DUT-side S14 edge eBGP setup is OPT-IN because it writes system configuration.
# The flag controls only that reversible setup/teardown overlay. Traffic mode
# always validates the IXIA protocols, both DUT edge sessions, and the exact
# remote route whether the edge was pre-provisioned or created by TAAC.
EDGE_EBGP_ENABLED: bool = os.environ.get("TAAC_RBB_EDGE_EBGP", "").lower() in (
    "1",
    "true",
    "yes",
)

# Fresh-image bootstrap is separately opt-in.  It patches the hardware-valid
# AgentConfig already installed by the FBOSS image; it never manufactures a
# platform block, port inventory, speed, or profile.  The runner owns this flag
# so a stale shell/profile value cannot unexpectedly turn a read-mostly run
# into a configuration run.
SETUP_DUTS_ENABLED: bool = os.environ.get("TAAC_RBB_SETUP_DUTS", "").lower() in (
    "1",
    "true",
    "yes",
)

# On-box config paths for the reversible bootstrap and edge setup.  These are
# the locations shipped by fboss-buildimage; alternate OSS images can override
# them without changing the test code.
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
BOOTSTRAP_STATE_PATH: str = os.environ.get(
    "TAAC_RBB_BOOTSTRAP_STATE_PATH", "/var/tmp/taac-rbb-bootstrap-state.json"
)

# Core BGP peer loopbacks/router IDs. The current RBB underlay uses IPv4
# loopback iBGP transport; dataplane traffic, IXIA route pools and SIDs are IPv6.
R1_ROUTER_ID: str = os.environ.get("TAAC_RBB_R1_ROUTER_ID", "192.0.2.1")
R2_ROUTER_ID: str = os.environ.get("TAAC_RBB_R2_ROUTER_ID", "192.0.2.2")
R1_LOOPBACK_V6: str = os.environ.get("TAAC_RBB_R1_LOOPBACK_V6", "2001:db8:0:1::1")
R2_LOOPBACK_V6: str = os.environ.get("TAAC_RBB_R2_LOOPBACK_V6", "2001:db8:0:2::1")

# Logical RIF IDs are deliberately independent of physical port numbering.
# Core RIFs reuse the selected baseline port's existing ingress VLAN/interface;
# only these three virtual interfaces are added by the bootstrap.
LOOPBACK_VLAN: int = 4000
SRV6_SID_VLAN_A: int = 10
SRV6_SID_VLAN_B: int = 11


def core_rif_cidr(role: str, index: int, family: int) -> str:
    """Return one env-overridable documentation-range core RIF address.

    Settings are named ``TAAC_RBB_R1_CORE0_V4``, ``..._V6``, and so on.  The
    generated defaults form matching /30 and /127 point-to-point networks.
    """
    normalized = role.lower()
    if normalized not in ("r1", "r2"):
        raise ValueError(f"unknown RBB role {role!r}; expected 'r1' or 'r2'")
    if index < 0:
        raise ValueError("core RIF index must be non-negative")
    if family not in (4, 6):
        raise ValueError("core RIF family must be 4 or 6")
    env_name = f"TAAC_RBB_{normalized.upper()}_CORE{index}_V{family}"
    role_offset = 1 if normalized == "r1" else 2
    if family == 4:
        default = f"198.51.100.{index * 4 + role_offset}/30"
    else:
        network = ipaddress.ip_network(
            f"2001:db8:{0xC0 + index:x}::/127", strict=True
        )
        default = f"{network.network_address + (0 if normalized == 'r1' else 1)}/127"
    return os.environ.get(env_name, default)


def srv6_source_cidr(role: str, interface: str) -> str:
    """Return an env-overridable /128 source address for SRv6 VLAN A or B."""
    normalized = role.lower()
    selector = interface.upper()
    if normalized not in ("r1", "r2"):
        raise ValueError(f"unknown RBB role {role!r}; expected 'r1' or 'r2'")
    if selector not in ("A", "B"):
        raise ValueError("SRv6 source interface must be 'A' or 'B'")
    node = 1 if normalized == "r1" else 2
    block = "fe00" if selector == "A" else "feff"
    default = f"2001:db8:{block}:200::{node}:0/128"
    return os.environ.get(
        f"TAAC_RBB_{normalized.upper()}_SRV6_SID_{selector}", default
    )


# Optional override used only while minimally patching a pre-provisioned R1
# bgp.json for edge eBGP. Empty preserves its existing usable next_hop6; this
# avoids replacing an operator address with the documentation-range default.
R1_IBGP_NEXT_HOP_V6: t.Optional[str] = os.environ.get(
    "TAAC_RBB_R1_IBGP_NEXT_HOP_V6"
)

# SRv6 tunnel id label (FBOSS-generic).
SRV6_TUNNEL_ID: str = os.environ.get("TAAC_RBB_SRV6_TUNNEL_ID", "srv6_tunnel")
