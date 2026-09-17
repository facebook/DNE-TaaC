# Copyright (c) Meta Platforms, Inc. and affiliates.
"""Example testbed device + topology constants.

SINGLE SOURCE OF TRUTH for everything device-specific about the example
testbed: hostname, MAC, DUT port wiring, TGEN interfaces and OTG port
locations, IP addressing, and BGP AS numbers. Modeled on
taac/testconfigs/npi/w800_constants.py.

All values are placeholders (example.com hostnames, RFC1918 addressing,
locally-administered MAC) so the example configs build and are importable
without any hardware.

Targeting a real testbed — two options:
  1. Edit the values here (this is the ONLY file that should need
     device-specific edits), or
  2. Leave this file generic and point TAAC_TESTBED_CONSTANTS at a
     site-specific Python file; any names it defines override the values
     below at import time (see the bottom of this module). This keeps
     site-specific hostnames out of the shared examples.

NOTE: the runner still consumes the topology CSVs under examples/topology/
for testbed setup. The interface names below MUST stay in sync with the
corresponding circuit_info.csv rows (single_switch/, single_switch_otg/)
— the CSVs no longer drive the test configs, but they do drive
port classification and health-check scoping.

Consumed by: simple_connectivity_test.py, agent_restart_test.py,
bgp_session_test.py, traffic_forwarding_test.py (each adds its own
directory to sys.path to import this module, since examples/ is not a
package).
"""

import os

# ---------------------------------------------------------------------------
# Device identity
# ---------------------------------------------------------------------------
SWITCH01_DEVICE_NAME = "switch01.example.com"
# Endpoint.mac_address for the DUT. Placeholder (locally-administered). Not
# consumed by these four examples — TGEN-side ARP resolves the real gateway
# MAC — but required by tests that build RAW / CPU-punt traffic items.
SWITCH01_LOCAL_MAC_ADDRESS = "02:00:00:00:00:01"

# ---------------------------------------------------------------------------
# Monitored ports (simple_connectivity_test.py, agent_restart_test.py)
# Per-DUT ports asserted operationally UP. All four examples are single-DUT;
# the defaults reuse the TGEN-facing ports since those are admin-UP on a
# standalone DUT even when no traffic test is running. Must match the
# circuit_info.csv rows for the same ports.
# ---------------------------------------------------------------------------
# Port names only — the {device: ports} dict (MONITORED_PORTS) and the
# restart target (AGENT_RESTART_DUT) are derived at the BOTTOM of this
# module, after the site-override hook, so an override that changes only
# SWITCH01_DEVICE_NAME keeps them consistent.
MONITORED_PORT_NAMES = ["eth1/1/1", "eth1/2/1"]
# simple_connectivity_test.py: steady-state hold after the port check so the
# OSS collectors (5 s poll interval) gather enough CPU/memory samples for
# real utilization verdicts instead of an empty-window SKIP.
CONNECTIVITY_HOLD_SEC = 30
# Services allowed to restart during the agent_restart playbook. On a
# split-agent FBOSS platform (e.g. Wedge800), restarting fboss_sw_agent
# cascades fboss_hw_agent@0 (same systemd transaction) and bgpd (restarts
# ~10 s later once its agent connection drops) — verified live on a Wedge800
# 1-RSW testbed. Adjust for platforms with a different cascade set (e.g.
# mono wedge_agent).
AGENT_RESTART_EXPECTED_RESTARTS = ["fboss_sw_agent", "fboss_hw_agent@0", "bgpd"]

# ---------------------------------------------------------------------------
# Single-switch TGEN testbed (bgp_session_test.py, traffic_forwarding_test.py)
# DUT-facing wiring. Must match topology/single_switch/circuit_info.csv
# (IxNetwork) and topology/single_switch_otg/circuit_info.csv (OTG).
# ---------------------------------------------------------------------------
# IxNetwork (RESTPY) backend: physical DUT interfaces + chassis ports.
TGEN_PORT_A_DUT_INTERFACE = "eth1/1/1"  # 10.0.3.0/24 side
TGEN_PORT_B_DUT_INTERFACE = "eth1/2/1"  # 10.0.4.0/24 side
IXIA_CHASSIS = "ixia01.example.com"
IXIA_PORT_A = "1/1"
IXIA_PORT_B = "1/2"

# OTG backend (ixia-c / Keysight Elemental): port-location strings. For
# ixia-c-one these are the container interface names (see
# topology/otg_l3_forwarding_sample_containerlab.yml).
OTG_PORT_A_LOCATION = "eth1"
OTG_PORT_B_LOCATION = "eth2"

# ---------------------------------------------------------------------------
# IP addressing (matches switch01.fboss_sw_agent.example.conf: DUT holds .1
# on each subnet, TGEN holds .2)
# ---------------------------------------------------------------------------
PORT_A_TGEN_IP = "10.0.3.2"
PORT_A_DUT_GW = "10.0.3.1"
PORT_B_TGEN_IP = "10.0.4.2"
PORT_B_DUT_GW = "10.0.4.1"
PREFIX_LEN = 24

# ---------------------------------------------------------------------------
# BGP. The TGEN peers as eBGP from TGEN_AS; the DUT must accept peer
# PORT_A_TGEN_IP with remote-as TGEN_AS (switch01.bgp_pp.example.conf does,
# with the DUT itself in AS 65000). The DUT's own AS is NOT configured or
# asserted by the tests — the TGEN learns it from the BGP OPEN — it just has
# to differ from TGEN_AS so the session is eBGP.
# ---------------------------------------------------------------------------
TGEN_AS = 65001

# ---------------------------------------------------------------------------
# Traffic (traffic_forwarding_test.py)
# ---------------------------------------------------------------------------
TRAFFIC_ITEM_NAME = "L3_IPV4_BIDIR"
TRAFFIC_LINE_RATE_PERCENT = 10
# traffic_forwarding_test.py: dwell while traffic runs so the loss check
# evaluates a real tx window and the collector checks have samples.
TRAFFIC_HOLD_SEC = 30

# ---------------------------------------------------------------------------
# Site override hook. TAAC_TESTBED_CONSTANTS=<path> names a Python file whose
# top-level assignments replace the placeholders above, so site-specific
# hostnames/wiring live outside the shared examples. Executed last so it can
# reference any of the defaults.
# ---------------------------------------------------------------------------
_override_path = os.environ.get("TAAC_TESTBED_CONSTANTS")
if _override_path:
    with open(_override_path) as _f:
        exec(compile(_f.read(), _override_path, "exec"), globals())

# ---------------------------------------------------------------------------
# Derived values — AFTER the override hook so overriding only
# SWITCH01_DEVICE_NAME (and/or MONITORED_PORT_NAMES) keeps them consistent.
# An override may still set these directly; it wins.
# ---------------------------------------------------------------------------
if "MONITORED_PORTS" not in globals():
    # Per-DUT ports asserted operationally UP by simple_connectivity /
    # agent_restart. Single-DUT by default; add entries for multi-DUT beds.
    MONITORED_PORTS = {SWITCH01_DEVICE_NAME: list(MONITORED_PORT_NAMES)}
if "AGENT_RESTART_DUT" not in globals():
    # The DUT whose fboss_sw_agent gets restarted by agent_restart_test.py.
    AGENT_RESTART_DUT = SWITCH01_DEVICE_NAME
