# pyre-unsafe
"""
TCP Socket Experiment — Topology Overview & Path Computation

Run this file to print the experiment topology diagrams and path calculations:
    buck run //neteng/test_infra/dne/taac/routing/ebb/ebb_bgp_plus_plus_test_config/tcp_socket_experiment:topology

Or directly:
    python -m neteng.test_infra.dne.taac.routing.ebb.ebb_bgp_plus_plus_test_config.tcp_socket_experiment.topology
"""

from taac.routing.ebb.ebb_bgp_plus_plus_test_config.tcp_socket_experiment.constants import (
    EBGP_SESSION_COUNT,
    IXIA_PREFIX_COUNT,
)


def compute_paths(
    prefix_count: int = IXIA_PREFIX_COUNT,
    session_count: int = EBGP_SESSION_COUNT,
) -> str:
    """
    Compute ingress/egress/total BGP paths from bag012 (BGP++) perspective.

    Both cases have the same path counts — only the direction differs.

    Args:
        prefix_count: Prefixes per address family (V4 and V6 each)
        session_count: Sessions per address family (V4 and V6 each)
    """
    # Ingress: 1 source peer (per AF) × prefix_count
    ingress_v6 = prefix_count
    ingress_v4 = prefix_count
    ingress_total = ingress_v6 + ingress_v4

    # Egress: prefix_count × session_count destination peers (per AF)
    egress_v6 = prefix_count * session_count
    egress_v4 = prefix_count * session_count
    egress_total = egress_v6 + egress_v4

    total_paths = ingress_total + egress_total

    return f"""
═══════════════════════════════════════════════════════════════════════════════════
  PATH COMPUTATION (from bag012 / BGP++ perspective)
  Identical for BOTH Case 1 and Case 2 — only the direction changes.
═══════════════════════════════════════════════════════════════════════════════════

  Parameters:
    Prefixes per AF:           {prefix_count:>10,}  (V4 and V6 each)
    Sessions per AF:           {session_count:>10,}  (V4 and V6 each)

  ┌───────────────────────────────────────────────────────────────────────┐
  │                        INGRESS PATHS (Adj-RIB-In)                   │
  │  From 1 source peer per AF (IXIA in Case 1, bag013 in Case 2)      │
  ├─────────────────────────────────────────────────┬───────────────────┤
  │  IPv6:  {prefix_count:>10,} prefixes × 1 peer  │ = {ingress_v6:>13,} │
  │  IPv4:  {prefix_count:>10,} prefixes × 1 peer  │ = {ingress_v4:>13,} │
  ├─────────────────────────────────────────────────┼───────────────────┤
  │  Ingress Total                                  │ = {ingress_total:>13,} │
  └─────────────────────────────────────────────────┴───────────────────┘

  ┌───────────────────────────────────────────────────────────────────────┐
  │                        EGRESS PATHS (Adj-RIB-Out)                   │
  │  To {session_count} destination peers per AF                               │
  │  (bag013 in Case 1, IXIA in Case 2)                                 │
  ├─────────────────────────────────────────────────┬───────────────────┤
  │  IPv6:  {prefix_count:>10,} prefixes × {session_count:>3} peers  │ = {egress_v6:>13,} │
  │  IPv4:  {prefix_count:>10,} prefixes × {session_count:>3} peers  │ = {egress_v4:>13,} │
  ├─────────────────────────────────────────────────┼───────────────────┤
  │  Egress Total                                   │ = {egress_total:>13,} │
  └─────────────────────────────────────────────────┴───────────────────┘

  ┌───────────────────────────────────────────────────────────────────────┐
  │  TOTAL BGP PATHS = Ingress + Egress             │ = {total_paths:>13,} │
  └─────────────────────────────────────────────────┴───────────────────┘

  Session Summary:
    Case 1 bgpcpp_config peers: {session_count} V6 + {session_count} V4 eBGP (EB-FA) + 1 V6 + 1 V4 IXIA (EB-EB) = {session_count * 2 + 2} total
    Case 2 bgpcpp_config peers: 1 V6 + 1 V4 eBGP (EB-FA) + {session_count} V6 + {session_count} V4 IXIA (EB-EB) = {session_count * 2 + 2} total
"""


TOPOLOGY = r"""
╔══════════════════════════════════════════════════════════════════════════════════╗
║                     TCP SOCKET EXPERIMENT — TOPOLOGY OVERVIEW                  ║
╠══════════════════════════════════════════════════════════════════════════════════╣
║                                                                                ║
║  Devices:                                                                      ║
║    bag012.ash6  — EOS BGP++ (DUT)    │  Peers via /mnt/flash/bgpcpp_config     ║
║    bag013.ash6  — ar-bgp (EOS BGP)   │  Peers via EOS CLI (router bgp 65013)   ║
║                                                                                ║
║  NOTE: bgpcpp_config is generated FRESH — not copied from configerator.        ║
║        Only experiment peers are included (no stale bag002 peers).             ║
║                                                                                ║
║  Inter-device Links (LLDP verified):                                           ║
║    bag013:Et3/1/1  ←→  bag012:Ethernet3/1/1                                   ║
║    bag013:Et3/2/1  ←→  bag012:Ethernet3/2/1                                   ║
║                                                                                ║
║  IXIA Chassis: ixia11.netcastle.ash6                                           ║
║    bag012 ports: 7/7, 7/8, 8/1                                                 ║
║    bag013 ports: 8/2, 8/3, 8/4                                                 ║
║                                                                                ║
║  IMPORTANT: "1 IXIA peer" = 1 V4 session + 1 V6 session = 2 BGP sessions      ║
║             "140 peers"   = 140 V4 + 140 V6 = 280 BGP sessions                ║
║                                                                                ║
╠══════════════════════════════════════════════════════════════════════════════════╣
║                                                                                ║
║  BGP++ Peer Groups & Policies (in bgpcpp_config on bag012):                    ║
║    EB-FA-V6/V4 + EB-FA-OUT   →  device-to-device eBGP (bag012 ↔ bag013)       ║
║    EB-EB-V6/V4 + EB-EB-OUT   →  IXIA iBGP sessions (simulated EB peers)       ║
║                                                                                ║
║  ar-bgp Peer Groups (EOS CLI on bag013):                                       ║
║    TCP-EXP-EBGP-V6/V4       →  eBGP towards bag012                            ║
║    TCP-EXP-IXIA-V6/V4       →  IXIA sessions (Case 2 only)                    ║
║                                                                                ║
║  Scale: 140 V4 + 140 V6 = 280 sessions  (70 per link × 2 links per AF)        ║
║                                                                                ║
╚══════════════════════════════════════════════════════════════════════════════════╝


═══════════════════════════════════════════════════════════════════════════════════
  CASE 1:  140+140 eBGP (bag013 ↔ bag012) + 1+1 IXIA → bag012 (15K prefixes)
═══════════════════════════════════════════════════════════════════════════════════

  IXIA injects 15K V4 + 15K V6 prefixes into bag012 (BGP++) via 2 sessions.
  bag012 redistributes to 140 V4 + 140 V6 eBGP sessions towards bag013.
  bag013 (ar-bgp) is a receiver only — does NOT originate routes.

  ┌─────────────────────────┐
  │   ixia11.netcastle.ash6 │
  │                         │
  │  2 BGP sessions:        │
  │    1 V6 (15K prefixes)  │
  │    1 V4 (15K prefixes)  │
  │  EB-EB-V6/V4 policy     │
  └────────┬────────────────┘
           │ port 7/7
           │
           ▼
  ┌────────────────────────────────┐        ┌────────────────────────────┐
  │       bag012.ash6              │        │       bag013.ash6          │
  │       EOS BGP++ (DUT)         │        │       ar-bgp (EOS BGP)    │
  │                                │        │                            │
  │  bgpcpp_config (generated)     │        │  router bgp 65013         │
  │  AS: 65100                     │        │  (existing config)        │
  │                                │        │                            │
  │  IXIA peers (EB-EB):           │        │                            │
  │    1 V6 (EB-EB-V6, EB-EB-OUT) │        │                            │
  │    1 V4 (EB-EB-V4, EB-EB-OUT) │        │                            │
  │         │                      │        │                            │
  │         ▼  receives 30K routes │        │                            │
  │         │  (15K V4 + 15K V6)  │        │                            │
  │         │                      │        │                            │
  │  eBGP peers (EB-FA):           │        │  eBGP peers:               │
  │    140 V6 ──┬──Et3/1/1────────────────▶│    140 V6 (TCP-EXP-EBGP)  │
  │    140 V4 ──┤  (70 per link)  │        │    140 V4 (TCP-EXP-EBGP)  │
  │             └──Et3/2/1────────────────▶│    (receiver only)         │
  │    egress: EB-FA-OUT           │        │                            │
  └────────────────────────────────┘        └────────────────────────────┘

  Route flow:  IXIA ──(30K)──▶ bag012 ──(redistribute)──▶ bag013 (receives)


═══════════════════════════════════════════════════════════════════════════════════
  CASE 2:  1+1 eBGP (bag013 → bag012) + 140+140 IXIA ↔ bag012
═══════════════════════════════════════════════════════════════════════════════════

  IXIA injects 15K V4 + 15K V6 prefixes into bag013 (ar-bgp) via 2 sessions.
  bag013 advertises them to bag012 via 1 V6 + 1 V4 iBGP session (EB-EB).
  bag012 (BGP++) redistributes to 140 V4 + 140 V6 IXIA eBGP peers (EB-FA).

  ┌─────────────────────────┐                      ┌─────────────────────────┐
  │   ixia11.netcastle.ash6 │                      │   ixia11.netcastle.ash6 │
  │   (route injection)     │                      │   (route receivers)     │
  │                         │                      │                         │
  │  2 BGP sessions:        │                      │  280 BGP sessions:      │
  │    1 V6 (15K prefixes)  │                      │    140 V6               │
  │    1 V4 (15K prefixes)  │                      │    140 V4               │
  └────────┬────────────────┘                      └────────▲────────────────┘
           │ port 8/2                                       │ port 7/7
           │                                                │
           ▼                                                │
  ┌────────────────────────────┐        ┌──────────────────────────────────┐
  │       bag013.ash6          │        │       bag012.ash6                │
  │       ar-bgp (EOS BGP)    │        │       EOS BGP++ (DUT)           │
  │                            │        │                                  │
  │  router bgp 65013          │        │  bgpcpp_config (generated)       │
  │                            │        │  AS: 65100                       │
  │  IXIA peers:               │        │                                  │
  │    1 V6 (TCP-EXP-IXIA)    │        │                                  │
  │    1 V4 (TCP-EXP-IXIA)    │        │                                  │
  │         │                  │        │                                  │
  │         ▼ receives 30K     │        │                                  │
  │         │                  │        │                                  │
  │  eBGP peers:               │        │  iBGP peers (EB-EB):            │
  │    1 V6 ─────Et3/1/1──────────────▶│    1 V6 (EB-EB-V6, EB-EB-OUT)  │
  │    1 V4 ─────────────────────────▶│    1 V4 (EB-EB-V4, EB-EB-OUT)  │
  │    (TCP-EXP-EBGP)         │        │         │                        │
  │    advertises 30K routes   │        │         ▼ redistributes 30K     │
  │                            │        │         │                        │
  │                            │        │  IXIA peers (EB-FA):             │
  │                            │        │    140 V6 (EB-FA-V6, EB-FA-OUT) │
  │                            │        │    140 V4 (EB-FA-V4, EB-FA-OUT) │
  └────────────────────────────┘        └──────────────────────────────────┘

  Route flow:  IXIA ──(30K)──▶ bag013 ──(1+1 eBGP)──▶ bag012 ──(redistribute)──▶ 140+140 IXIA


═══════════════════════════════════════════════════════════════════════════════════
  USAGE EXAMPLES
═══════════════════════════════════════════════════════════════════════════════════

  # Case 1 — full setup (first run):
  config = create_case1_test_config()

  # Case 1 — change prefix count only (skip infra rebuild):
  config = create_case1_test_config(ixia_prefix_count=20000, skip_infra_setup=True)

  # Case 1 — keep infra after test (for next run):
  config = create_case1_test_config(skip_teardown=True)

  # Case 2 — full setup:
  config = create_case2_test_config()


═══════════════════════════════════════════════════════════════════════════════════
  FILES
═══════════════════════════════════════════════════════════════════════════════════

  tcp_socket_experiment/
  ├── __init__.py          # Package init
  ├── constants.py         # All configurable params (devices, IXIA, AS, IPs)
  ├── ixia_config.py       # IXIA BasicPortConfig factories
  ├── cleanup.py           # Shared cleanup (daemons, bgpcpp_config, ar-bgp)
  ├── case1_test_config.py # Case 1: 280 eBGP + 2 IXIA
  ├── case2_test_config.py # Case 2: 2 eBGP + 280 IXIA
  ├── topology.py          # This file (topology + path computation)
  └── BUCK                 # Build targets
"""


def print_topology(
    prefix_count: int = IXIA_PREFIX_COUNT,
    session_count: int = EBGP_SESSION_COUNT,
) -> None:
    """Print full topology diagrams and path computation."""
    print(TOPOLOGY)
    print(
        compute_paths(
            prefix_count=prefix_count,
            session_count=session_count,
        )
    )


if __name__ == "__main__":
    print_topology()
