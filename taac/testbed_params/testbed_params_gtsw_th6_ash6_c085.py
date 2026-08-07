# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""Endpoint constants for GTSW (Tomahawk 6 / IcePack) multi-node PFC.

Source ports live on ``gtsw001.l1001.c085.ash6``; the destination port
lives on ``gtsw001.l1002.c085.ash6`` (sibling pod in the same cluster).
Both DUTs peer with the identical 8-STSW spine plane in ``l201.ash6``
(``stsw001.s001..s008.l201.ash6``), so traffic converges
gtsw001.l1001 → 8× STSW → gtsw001.l1002 and PFC backpressure propagates
across the fabric rather than staying inside one box.

The methodology doc originally called out ``gtsw002.l1001`` as the
destination; ash6 c085 has no IXIA cabling to gtsw002 today, but
``gtsw001.l1002`` is IXIA-anchored on ixia20 and shares the identical
STSW plane, so it exercises the same multi-node PFC path.

Companion methodology doc: fburl.com/gsheet/qhif4j0m + the primary
"GTSW (Tomahawk 6) Multi-Node PFC Test Methodology" gdoc.
"""

from taac.test_as_a_config.types import Endpoint, TrafficEndpoint

# 3× IXIA source ports on gtsw001.l1001.c085.ash6 (the DUT under test).
# Picked from the ixia20-cabled ports (`fboss2 show lldp` peers:
# `ixia20.netcastle.ash6`) — same chassis as the l1002 destination
# port, so the IXIA session lives on a single chassis. Section 9 of the
# methodology doc calls these "TBD" — change here if a different picking
# is desired.
GTSW001_L1001_C085_ASH6 = "gtsw001.l1001.c085.ash6"
GTSW001_L1001_C085_IXIA_SRC_PORTS = [
    "eth1/17/1",
    "eth1/17/3",
    "eth1/17/5",
]

# 1× IXIA destination port on gtsw001.l1002.c085.ash6 (sibling pod).
# Verified via ``fboss2 show lldp`` — l1002 has 2 IXIA-facing ports up
# (``eth1/1/1``, ``eth1/1/3``) cabled to ixia20.netcastle.ash6. Only one
# is needed for the multi-node PFC destination.
GTSW001_L1002_C085_ASH6 = "gtsw001.l1002.c085.ash6"
GTSW001_L1002_C085_IXIA_DST_PORTS = [
    "eth1/1/1",
]

ASH6_C085_GTSW_TH6_MULTI_NODE_PFC_END_POINTS = [
    Endpoint(
        name=GTSW001_L1001_C085_ASH6,
        dut=True,
        ixia_ports=GTSW001_L1001_C085_IXIA_SRC_PORTS,
    ),
    Endpoint(
        name=GTSW001_L1002_C085_ASH6,
        dut=True,
        ixia_ports=GTSW001_L1002_C085_IXIA_DST_PORTS,
    ),
]

# Warmboot + neighbour-uplink-flap variant of the endpoint list.
#
# Same physical pair as the multi-node PFC list above, but ``l1002`` is
# ``dut=False``. That test is symmetric (both boxes source/sink PFC traffic);
# this one is not — only ``l1001`` is warmbooted, and ``l1002`` merely flaps
# its own STSW-facing uplinks. ``TaacRunner.run_tests`` loops
# ``for dut in duts``, so leaving both ``dut=True`` would run the whole
# playbook twice and warmboot both boxes. With ``dut=False`` the neighbour is
# still health-checked (device checks fan out over topology endpoints) but is
# never iterated as a DUT.
ASH6_C085_GTSW_TH6_WARMBOOT_NBR_FLAP_END_POINTS = [
    Endpoint(
        name=GTSW001_L1001_C085_ASH6,
        dut=True,
        ixia_ports=GTSW001_L1001_C085_IXIA_SRC_PORTS,
    ),
    Endpoint(
        name=GTSW001_L1002_C085_ASH6,
        dut=False,
        ixia_ports=GTSW001_L1002_C085_IXIA_DST_PORTS,
    ),
]

# 3 unique src ports + a repeat of P1 → 4-entry list (matches the shape
# ``gen_pfc_functionality_test_generic_4port_configs`` expects; helper
# will also auto-append if only 3 are supplied, but we spell it out to
# match the MTIA / SNC1 templates).
ASH6_C085_GTSW_TH6_MULTI_NODE_PFC_TRAFFIC_SRC_ENDPOINTS = [
    TrafficEndpoint(
        name=f"{GTSW001_L1001_C085_ASH6}:{GTSW001_L1001_C085_IXIA_SRC_PORTS[0]}"
    ),
    TrafficEndpoint(
        name=f"{GTSW001_L1001_C085_ASH6}:{GTSW001_L1001_C085_IXIA_SRC_PORTS[1]}"
    ),
    TrafficEndpoint(
        name=f"{GTSW001_L1001_C085_ASH6}:{GTSW001_L1001_C085_IXIA_SRC_PORTS[2]}"
    ),
    TrafficEndpoint(
        name=f"{GTSW001_L1001_C085_ASH6}:{GTSW001_L1001_C085_IXIA_SRC_PORTS[0]}"
    ),
]

ASH6_C085_GTSW_TH6_MULTI_NODE_PFC_TRAFFIC_DST_ENDPOINTS = [
    TrafficEndpoint(
        name=f"{GTSW001_L1002_C085_ASH6}:{GTSW001_L1002_C085_IXIA_DST_PORTS[0]}"
    ),
]
