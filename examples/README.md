# TAAC Examples

Runnable TAAC test configurations demonstrating the framework's capabilities
from simplest to most complex. Each config is a Python file you pass to
`taac.runner.oss_entry_point` via `--test-configs`.

## Quick Start

All examples run inside the `fboss-taac` Docker image. Build it once:

```bash
./docker/build_taac_docker.sh
```

Then use `./docker/run_taac_docker.sh run <command>` as the prefix for every
invocation below. The repo is bind-mounted at `/workspace` inside the image,
so pass paths as `/workspace/examples/...`.

---

## Device Targeting

All device-specific values — hostname, MAC, monitored-port and TGEN wiring,
IP addressing, AS numbers — live in **`testbed_constants.py`**, the single
source of truth consumed by every example config (modeled on
`taac/testconfigs/npi/w800_constants.py`). To target a real testbed, edit
that one file. The configs build at import time, so they are importable and
dry-runnable before any hardware exists.

To keep site-specific hostnames out of the shared examples, you can instead
leave `testbed_constants.py` generic and export
`TAAC_TESTBED_CONSTANTS=/path/to/site_constants.py`; any names that file
assigns override the placeholders at import time.

The topology CSVs under `topology/` are still consumed by the runner for
testbed setup; keep their interface rows in sync with the constants.

## Examples

### 1. `simple_connectivity_test.py` — Basic Connectivity (Simple)

Runs `hostname` over SSH on the DUT and verifies that the monitored ports
(defaults: the TGEN-facing ports) are operationally UP. No traffic generator
required.

**Topology:** `topology/single_switch/`

**Prerequisites:** DUT reachable via SSH; monitored ports UP.

**Run:**

```bash
./docker/run_taac_docker.sh run \
    python3 -m taac.runner.oss_entry_point \
        --test-configs /workspace/examples/simple_connectivity_test.py \
        --device-info-csv /workspace/examples/topology/single_switch/device_info.csv \
        --circuit-info-csv /workspace/examples/topology/single_switch/circuit_info.csv \
        --dut switch01.example.com \
        --skip-ixia-setup \
        --skip-post-setup-wait
```

| Playbook | What it does |
|---|---|
| `ssh_check` | Runs `hostname` on the DUT |
| `port_state_check` | Asserts monitored ports UP, then holds 30 s watching for flaps; postchecks: collector-backed `SYSTEMCTL_ACTIVE_STATE_CHECK`, `UNCLEAN_EXIT_CHECK`, `CPU_UTILIZATION_CHECK`, `MEMORY_UTILIZATION_CHECK` |

---

### 2. `agent_restart_test.py` — FBOSS Agent Restart (Medium)

Restarts `fboss_sw_agent` on the DUT via `systemctl restart`, waits for the
agent to converge, then re-verifies the monitored port state.

**Topology:** `topology/single_switch/`

**Prerequisites:** `fboss_sw_agent` running and monitored ports UP.

**Run:**

```bash
./docker/run_taac_docker.sh run \
    python3 -m taac.runner.oss_entry_point \
        --test-configs /workspace/examples/agent_restart_test.py \
        --device-info-csv /workspace/examples/topology/single_switch/device_info.csv \
        --circuit-info-csv /workspace/examples/topology/single_switch/circuit_info.csv \
        --dut switch01.example.com \
        --skip-ixia-setup \
        --skip-post-setup-wait
```

| Playbook | What it does |
|---|---|
| `baseline_port_check` | Asserts monitored ports UP before restart |
| `agent_restart` | Restarts the agent, waits for convergence, re-verifies monitored ports; postchecks: `SERVICE_RESTART_CHECK` + `SYSTEMCTL_ACTIVE_STATE_CHECK` (restart cascade allow-listed), `UNCLEAN_EXIT_CHECK`, `MEMORY_UTILIZATION_CHECK` |

---

### 3. `bgp_session_test.py` — BGP Session Establishment (Medium)

Configures a traffic-generator port as an IPv4 eBGP peer toward the DUT and
verifies the BGP session reaches Established state. Peer AS 65001, DUT AS 65000.

Runs on either traffic-generator backend — see
[Traffic-Generator Backends](#traffic-generator-backends).

Only IPv4 Unicast capability is advertised — FBOSS rejects peers that
advertise unsupported address families in the BGP OPEN message.

**Topology:** `topology/single_switch/` (one DUT port connected to Ixia)

**DUT prerequisites:**
- IPv4 `10.0.3.1/24` on the TGEN-facing interface
- BGP ASN 65000, accepting eBGP peer `10.0.3.2` (remote-as 65001)
- IPv4 unicast address-family enabled on that peer

Sample DUT configs satisfying these prerequisites (see
[Sample DUT Configs](#sample-dut-configs)):
`switch01.fboss_sw_agent.example.conf`, `switch01.bgp_pp.example.conf`

**Run:**

```bash
./docker/run_taac_docker.sh run \
    python3 -m taac.runner.oss_entry_point \
        --test-configs /workspace/examples/bgp_session_test.py \
        --device-info-csv /workspace/examples/topology/single_switch/device_info.csv \
        --circuit-info-csv /workspace/examples/topology/single_switch/circuit_info.csv \
        --dut switch01.example.com \
        --ixia-api-server ixia-api.example.com \
        --skip-post-setup-wait
```

| Phase | Description |
|---|---|
| `bgp_session_check` playbook | No disruptive steps |
| Postchecks | `BGP_SESSION_ESTABLISH_CHECK` (retries until Established, up to 60 s) + collector-backed `SYSTEMCTL_ACTIVE_STATE_CHECK`, `UNCLEAN_EXIT_CHECK` |

---

### 4. `traffic_forwarding_test.py` — IPv4 L3 Traffic Forwarding (Complex)

Configures two traffic-generator ports as IPv4 endpoints on opposite sides
of the DUT, sends 10% bidirectional traffic, and verifies zero packet loss.

Runs on either traffic-generator backend — see
[Traffic-Generator Backends](#traffic-generator-backends).

**Topology:** `topology/single_switch/` (two DUT ports connected to Ixia)

**DUT prerequisites:**
- IPv4 `10.0.3.1/24` on Port A (first TGEN-connected interface in circuit_info.csv)
- IPv4 `10.0.4.1/24` on Port B (second TGEN-connected interface)
- Routing between the two subnets (covered by connected routes when both
  addresses live on the DUT)

Sample DUT config satisfying these prerequisites (see
[Sample DUT Configs](#sample-dut-configs)):
`switch01.fboss_sw_agent.example.conf`

**Run:**

```bash
./docker/run_taac_docker.sh run \
    python3 -m taac.runner.oss_entry_point \
        --test-configs /workspace/examples/traffic_forwarding_test.py \
        --device-info-csv /workspace/examples/topology/single_switch/device_info.csv \
        --circuit-info-csv /workspace/examples/topology/single_switch/circuit_info.csv \
        --dut switch01.example.com \
        --ixia-api-server ixia-api.example.com \
        --skip-post-setup-wait
```

| Phase | Description |
|---|---|
| `traffic_forwarding` playbook | Sends 10% line-rate bidirectional IPv4 traffic through the DUT |
| Postchecks | `IXIA_PACKET_LOSS_CHECK` (0% loss on `L3_IPV4_BIDIR`) + collector-backed `SYSTEMCTL_ACTIVE_STATE_CHECK`, `UNCLEAN_EXIT_CHECK`, `CPU_UTILIZATION_CHECK`, `MEMORY_UTILIZATION_CHECK` |

---

## OSS Collector Health Checks

Under `TAAC_OSS`, `CollectorsTestHandler` starts CPU, memory, and systemd-state
collectors on the DUT for every run. The examples' postchecks consume them:
`SYSTEMCTL_ACTIVE_STATE_CHECK`, `SERVICE_RESTART_CHECK`, `UNCLEAN_EXIT_CHECK`,
`CPU_UTILIZATION_CHECK`, `MEMORY_UTILIZATION_CHECK`. Note these must be playbook
`postchecks` — the OSS runner skips TestConfig-level `startup_checks`.

## Sample DUT Configs

Ready-made DUT-side configs for examples 3 and 4 (derived from the
bgpd_restart sample configs):

| File | Deploys to | Provides |
|---|---|---|
| `switch01.fboss_sw_agent.example.conf` | `/etc/coop/agent.conf` | `10.0.3.1/24` on `eth1/1/1`, `10.0.4.1/24` on `eth1/2/1` (routed VLAN interfaces 2017/2018) |
| `switch01.bgp_pp.example.conf` | `/etc/coop/bgpcpp.conf` (bgpd `--config`) | AS 65000, IPv4 eBGP peer `10.0.3.2` (remote-as 65001), IPv4-unicast only (`disable_ipv6_afi`) |

```bash
scp examples/switch01.fboss_sw_agent.example.conf switch01:/etc/coop/agent.conf
scp examples/switch01.bgp_pp.example.conf switch01:/etc/coop/bgpcpp.conf
ssh switch01 'systemctl restart fboss_sw_agent bgpd'
```

The agent config assumes the DUT's TGEN-facing ports are `eth1/1/1` and
`eth1/2/1` — the same ports as the topology CSVs. If your wiring differs,
update the `vlanPorts` entries for VLANs 2017/2018 (and the CSVs) to match.
`traffic_forwarding_test.py` needs no BGP config: with both subnets directly
connected, forwarding is covered by connected routes.

## Traffic-Generator Backends

Examples 3 and 4 build **both** backend variants at import time (e.g.
`BGP_SESSION_RESTPY_TEST_CONFIG` / `BGP_SESSION_OTG_TEST_CONFIG`); the
`TAAC_TGEN_BACKEND` environment variable selects which one runs:

| Backend | Selection | `--ixia-api-server` value | Topology |
|---|---|---|---|
| IxNetwork (RESTPY, default) | unset | IxNetwork API server hostname | `topology/single_switch/` |
| OTG (ixia-c / Keysight Elemental) | `TAAC_TGEN_BACKEND=otg` | OTG controller URL, e.g. `https://localhost:8443` | `topology/single_switch_otg/` |

Example OTG invocation:

```bash
./docker/run_taac_docker.sh run \
    env TAAC_TGEN_BACKEND=otg \
    python3 -m taac.runner.oss_entry_point \
        --test-configs /workspace/examples/traffic_forwarding_test.py \
        --device-info-csv /workspace/examples/topology/single_switch_otg/device_info.csv \
        --circuit-info-csv /workspace/examples/topology/single_switch_otg/circuit_info.csv \
        --dut switch01.example.com \
        --ixia-api-server https://localhost:8443 \
        --skip-post-setup-wait
```

In the OTG topology CSV the `neighbor_interface` column carries the OTG
port-location string (ixia-c: interface names like `eth1`; Keysight OTG:
controller port endpoints) instead of a physical chassis port.

## Topology Templates

```
examples/topology/
├── single_switch/
│   ├── device_info.csv   # One FBOSS DUT + one Ixia chassis
│   └── circuit_info.csv  # DUT on two ports -> Ixia (Port A and Port B)
└── single_switch_otg/
│   ├── device_info.csv   # One FBOSS DUT + one OTG controller host
│   └── circuit_info.csv  # DUT on two ports -> OTG port locations eth1/eth2
```

Copy the relevant directory, replace placeholder hostnames and interface
names with your actual fleet, and pass the updated paths to
`--device-info-csv` / `--circuit-info-csv`.

## Dry-Run / Config Validation

Validate any config without touching real devices:

```bash
./docker/run_taac_docker.sh run \
    python3 -m taac.runner.oss_entry_point \
        --test-configs /workspace/examples/simple_connectivity_test.py \
        --device-info-csv /workspace/examples/topology/single_switch/device_info.csv \
        --circuit-info-csv /workspace/examples/topology/single_switch/circuit_info.csv \
        --dut switch01.example.com \
        --dry-run
```
