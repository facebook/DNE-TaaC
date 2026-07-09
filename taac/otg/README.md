# OTG (Open Traffic Generator) Backend for TAAC

TAAC's OTG backend uses the [snappi](https://github.com/open-traffic-generator/snappi)
client library to drive any traffic generator that exposes a conformant
[Open Traffic Generator](https://github.com/open-traffic-generator/models) API —
ixia-c containers, Keysight hardware chassis with OTG enabled, or third-party
implementations.

The long-term direction is to move from the mutable, RPC-heavy restpy
(ixnetwork-restpy) API to OTG's declarative model: build a config object,
push it once with `set_config()`, then control via `control_state()` and
read via `get_metrics()`.

## Architecture

```
TestConfig                        (thrift: traffic_generator_backend = OTG)
  │
  ▼
TrafficGenerator pipeline         (taac/libs/traffic_generator.py)
  │
  ├─ OtgTrafficGenerator          (taac/libs/otg_traffic_generator.py)
  │    Subclass of TrafficGenerator. Overrides port-config creation to
  │    skip chassis discovery, SSH checks, and logical-port lookup.
  │    Builds PortConfigs from DirectIxiaConnection.port_location strings.
  │
  ▼
OtgTrafficGen                     (taac/ixia/otg_traffic_gen.py)
  │  Implements AbstractTrafficGenerator ABC.
  │  Translates IxiaConfig thrift → snappi declarative config.
  │  Provides: setup, traffic control, stats capture, BGP, teardown.
  │
  ▼
AbstractTrafficGenerator          (taac/ixia/abstract_traffic_generator.py)
     12 abstract methods defining the contract between the test framework
     (TaacRunner, health checks, steps) and the traffic backend.
     Implementations: OtgTrafficGen (OTG/snappi), TaacIxia (restpy).
```

### Key files

| File | Role |
|------|------|
| `taac/ixia/abstract_traffic_generator.py` | ABC — methods that TaacRunner + health checks call |
| `taac/ixia/otg_traffic_gen.py` | OTG implementation: config builders, two-phase setup, background stats |
| `taac/libs/otg_traffic_generator.py` | `TrafficGenerator` subclass — OTG port-config pipeline |
| `taac/libs/test_setup_orchestrator.py` | Backend dispatch (`traffic_generator_backend` → `"otg"` / `"restpy"`) |
| `taac/otg/otg_basic_l3_test_config.py` | Example: L3 forwarding TestConfig |
| `taac/otg/tests/test_otg_traffic_gen.py` | Unit tests for OtgTrafficGen |
| `examples/topology/otg_l3_forwarding_*.csv` | Sample topology files |

## Design Decisions

### Thin ABC at the orchestration boundary

The `AbstractTrafficGenerator` defines only what TaacRunner and health checks
call directly — the orchestration contract, not every Ixia operation a test
might perform. Three files type `self.ixia` as `AbstractTrafficGenerator`:

- `libs/taac_runner.py`
- `libs/test_setup_orchestrator.py`
- `libs/traffic_generator.py`

Everything downstream — steps, tasks, `InvokeIxiaApiStep` — keeps concrete
backend typing. Backend-specific calls (restpy's mutate-then-commit vs OTG's
declarative config) don't share a useful common shape, so they stay out of the
ABC.

#### ABC methods

| Category | Methods |
|----------|---------|
| Lifecycle | `begin_test_case`, `end_test_case`, `tear_down` |
| Traffic control | `start_traffic`, `stop_traffic`, `get_traffic_start_time` |
| Stats | `get_latest_stats`, `clear_traffic_stats`, `has_traffic_items`, `get_traffic_items` |
| BGP | `restart_bgp_peers`, `find_bgp_peers` |

`begin_test_case` and `end_test_case` absorb backend-specific orchestration
into a single per-test-case call. Restpy: regenerate traffic items, apply
traffic, wait for stat view assistants. OTG: `set_config()` + background
capture thread.

The ABC is minimal because ixnetwork and OTG have fundamentally different
paradigms: ixnetwork/restpy is imperative (mutate live session objects, then
commit), while OTG/snappi is declarative (build a config, push it whole). A
larger shared interface would force one backend to emulate the other's
semantics, defeating the purpose of supporting OTG idiomatically.

### Backend field on TestConfig

`TestConfig.traffic_generator_backend` controls which backend
is used. This is a backward-compatible addition: default `RESTPY`, existing
configs that don't set it behave exactly as today. Because a TestConfig's
playbooks are backend-specific, backend choice belongs with the config, not
as a separate CLI knob.

```
TestConfig.traffic_generator_backend = OTG
  → TaacRunner(traffic_generator_backend="otg")
    → TestSetupOrchestrator(traffic_generator_backend="otg")
      → TrafficGenerator(traffic_generator_backend="otg")
        → OtgTrafficGen
```

## Playbook Compatibility

The ABC makes the runner backend-agnostic, but it does **not** make existing
playbooks portable for free.

### Playbooks that work unchanged

Common service-restart playbooks from `common_playbooks.py` that only use ABC
methods + DUT-side steps:

- `test_agent_warmboot` / `test_agent_coldboot` / `test_agent_restart`
- `test_bgp_restart`
- `test_qsfp_restart` / `test_fsdb_restart`
- `test_agent_warmboot_and_fsdb_restart`

These run against either backend by registering the owning TestConfig twice —
once with `traffic_generator_backend=RESTPY` and once with `OTG`.

### Playbooks using InvokeIxiaApiStep (require rewrite)

`InvokeIxiaApiStep` does `getattr(self.ixia, api_name)(**args)` from playbook
params. Over 20 unique restpy APIs are called this way across 200+ call sites,
most following restpy's mutate-then-commit pattern (`toggle_device_groups`,
`bounce_bgp_next_hop_attribute`, `set_bgp_local_preference`, etc.).

Migration pattern: split playbook construction into restpy and OTG helpers,
register both as separate TestConfig entries:

```python
FBOSS_HARDENING_TEST_CONFIGS = [
    get_test_config(
        test_config_name="WEDGE400C_FBOSS_HARDENING",
        playbooks=_build_restpy_hardening_playbooks(...),
        traffic_generator_backend=TrafficGeneratorBackend.RESTPY,
    ),
    get_test_config(
        test_config_name="WEDGE400C_FBOSS_HARDENING_OTG",
        playbooks=_build_otg_hardening_playbooks(...),
        traffic_generator_backend=TrafficGeneratorBackend.OTG,
    ),
]
```

## Running the Example

```bash
export TAAC_OSS=1 TAAC_SSH_USER=root TAAC_SSH_PASSWORD=root

./docker/run_taac_docker.sh run python3 -m taac.runner.oss_entry_point \
    --test-configs /workspace/taac/otg/otg_basic_l3_test_config.py \
    --dut <dut-hostname> \
    --ixia-api-server https://<otg-controller>:8443 \
    --device-info-csv /workspace/examples/topology/otg_l3_forwarding_device_info.csv \
    --circuit-info-csv /workspace/examples/topology/otg_l3_forwarding_circuit_info.csv \
    --skip-post-setup-wait
```

### Prerequisites

- OTG-compatible traffic generator reachable via HTTPS (port 8443)
- At least two OTG ports with L2 connectivity to distinct DUT interfaces
- DUT interfaces configured with matching IP addresses (default: 10.0.1.2/24, 10.0.2.2/24)
- L3 forwarding enabled between the two subnets on the DUT
- `pip install snappi` in the test environment

### Deployment options

The test is backend-agnostic. Any OTG-conformant endpoint works:

- **ixia-c-one** — single container, software traffic engine (good for CI/dev)
- **ixia-c multi-container** — controller + separate traffic engines
- **Keysight hardware chassis** with OTG API enabled

See `examples/topology/otg_l3_forwarding_sample_containerlab.yml` for a
sample ixia-c deployment using containerlab.

### OTG versions and compatibility

TAAC's OTG backend uses [snappi](https://github.com/open-traffic-generator/snappi),
the reference Python client for the [Open Traffic Generator](https://otg.dev/)
API. snappi talks to any conformant OTG endpoint — the backend is not
tied to a specific vendor or implementation.

Pin your `snappi` version to match the OTG API version your traffic
generator exposes. For ixia-c deployments (Keysight's open-source OTG
implementation), snappi and ixia-c release versions track together; see
the [ixia-c compatibility matrix](https://ixia-c.dev/releases/).

See also: [OTG implementations](https://otg.dev/implementations/),
[snappi on PyPI](https://pypi.org/project/snappi/)

### Migrating from IxNetwork to OTG on hardware chassis

For teams running existing Keysight hardware under IxNetwork, see
[MIGRATION.md](MIGRATION.md). The short answer: no chassis reconfiguration
is required. There is no "OTG mode" to flip — the switch happens entirely
at the port reservation level in software.

## Running Tests

```bash
# Inside Docker (preferred — has thrift bindings):
./docker/run_taac_docker.sh run python3 -m pytest taac/otg/tests/ -v

# Locally (if thrift bindings are available):
python3 -m pytest taac/otg/tests/ -v
```

## Known Limitations

- **`InvokeIxiaApiStep` methods:** 20+ restpy-specific APIs (e.g.
  `toggle_device_groups`, `configure_traffic_items_on_the_fly`) are not on the
  ABC. Playbooks using these steps require OTG-native rewrites.
- **Loss-duration precision:** OTG reports `packet_loss_duration` as a
  wall-clock approximation (1s polling granularity), not chassis-reported
  hardware timestamps. Sufficient for longevity tests, not for sub-second
  convergence SLAs.
