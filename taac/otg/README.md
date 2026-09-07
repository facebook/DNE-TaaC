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
| `taac/otg/otg_bgp_session_test_config.py` | Example: BGP session + forwarding TestConfig |
| `taac/otg/otg_hardening_builders.py` | Hardening conveyor: shared builders (a library, no `test_config()`) |
| `taac/otg/otg_hardening_{restarts,ecmp,malformed}_test_config.py` | Per-profile configs that fit ixia-c community edition's 4-session cap |
| `taac/otg/otg_hardening_playbooks.py` | Hardening playbook factories (ported from the FBOSS conveyor) |
| `taac/otg/tests/test_otg_traffic_gen.py` | Unit tests for OtgTrafficGen |
| `taac/otg/tests/test_otg_hardening_playbooks.py` | Unit tests for the hardening playbook factories |
| `examples/topology/otg_l3_forwarding_*.csv` | Sample topology files |
| `examples/topology/otg_hardening_*.csv` | Sample topology for the hardening conveyor |
| `taac/otg/HARDENING_SETUP.md` | Testbed setup the hardening conveyor requires, plus known gaps |

### Hardening conveyor

The hardening profiles port a subset of
`taac/testconfigs/fboss_solution_tests/fboss_bgp_and_platform_hardening_conveyor.py`
to the OTG backend. All eight playbooks ship across three runnable configs that
each fit ixia-c community edition's caps, sharing the builders in
`otg_hardening_builders.py`:

- **Six port directly** — the four service restarts,
  `test_ecmp_group_overload_limit` and `test_cpu_high_priority_queue_overload`.
- **`test_bgp_malformed_packet_test` uses a different mechanism.** Upstream
  toggles a NEXT_HOP attribute flag, which a route range cannot express, so this
  authors the exact UPDATE bytes instead (`otg_bgp_malformed_updates.py`, and
  limitation class 2 below). More precise than upstream, not less.
- **`test_ecmp_member_overload_limit` is redesigned** and renamed
  `test_otg_ecmp_member_overload_limit` to say so — its upstream member pressure
  came from a COOP patcher unavailable in OSS mode.


Step-facing APIs added to `OtgTrafficGen`, all reachable via
`create_ixia_api_step` (a bare `getattr(ixia, api_name)`):

| API | OTG mechanism |
|-----|---------------|
| `toggle_device_groups` | Drives the group's BGP peers UP/DOWN via `control_state` — no `set_config`, so unrelated sessions do not flap |
| `enable_traffic` | Mutates the disabled-flow set and transmit state only, never `self.config` |
| `apply_packet_headers` | Narrow restpy-`PacketHeader` → snappi translation; raises `NotImplementedError` on anything outside its whitelist |

Device-group names and the regexes matching them both live in
`otg_hardening_playbooks.py`, with the configs importing them — deliberately, as
a mismatch fails *silently*: `toggle_device_groups` logs a warning, returns, and
the playbook reports green having done nothing.

Failure behaviour is deliberately loud where a silent one would fake a pass:

| Condition | Behaviour |
|---|---|
| Device-group regex matches nothing | warning + no-op, as `restart_bgp_peers` does |
| Unsupported packet-header stack/field | `NotImplementedError` naming it — never a silent drop |
| Missing DUT MAC for the CP flow | `RuntimeError` at config-build time, not mid-run |
| Fewer than 2 TGEN links | `RuntimeError` |
| Over the declared interface/session budget | `RuntimeError` naming the dimension and the knobs |

Playbook factories are unit-tested in `tests/test_otg_hardening_playbooks.py` and
the new `OtgTrafficGen` APIs in `tests/test_otg_traffic_gen.py`. The **configs**
are not: a config exists to be *run*, which needs a real DUT and OTG endpoint —
`pyproject.toml` excludes `taac/testconfigs` from collection for the same reason.
Use `--dry-run` for a DUT-free build check.

Two things to know when reading or asserting on a built config: step and check
arguments are **double-encoded** — `step_params.json_params` carries an
`args_json` string that is itself JSON — and snapshot checkpoint IDs are
top-level fields on the check, not part of any payload.

### Hardening conveyor: testbed setup

Ports, interface addressing, the seven BGP peers, advertised prefixes, the
required DUT MAC, and CPU-queue provisioning are in
**[`HARDENING_SETUP.md`](HARDENING_SETUP.md)**, along with two known gaps that
affect what the tests actually exercise.

## BGP and OTG: classes of limitation

Porting BGP tests from restpy hits several *different* kinds of wall with
different workarounds, and conflating them leads to declaring things impossible
that aren't. Everything below was verified against the installed snappi schema —
before concluding "OTG can't do X", check the schema.

### 1. Mutation granularity — what can change at runtime

`set_config` replaces the whole config, restarting protocols and reconverging
**every** session — roughly 30–60s per call, and a blast radius far wider than the
thing under test. That is decisive for `test_cpu_high_priority_queue_overload`,
whose snapshot check asserts sessions did **not** flap: routing `enable_traffic`
through a re-push would fail it on self-inflicted churn. The narrower primitives:

| Mechanism | Scope | Restarts protocols |
|---|---|---|
| `set_config` | everything | **yes — all sessions** |
| `update_config` (PATCH `/config`) | flow `rate` / `size`; ISIS only | no |
| `append_config` / `delete_config` | **flows only** — not devices or peers | no |
| `control_state.protocol.bgp.peers` | named peers UP / DOWN | no |
| `control_state.protocol.route` | named route ranges ADVERTISE / WITHDRAW | no |
| `control_state.traffic.flow_transmit` | named flows START / STOP | no |
| `control_action.protocol.bgp` | NOTIFICATION; initiate graceful restart | no |

So the data plane has fine-grained runtime mutation, while devices and peers
cannot be added or removed without `set_config`. What you *can* change live is
their **state**: peers up/down, route ranges advertised/withdrawn.

This is a hard property of the declarative model, with no escape hatch — the
workaround is always to find the `control_state` primitive rather than re-push.

`toggle_device_groups` uses peer UP/DOWN. For the ECMP playbooks
`control_state.protocol.route` would be finer: withdrawing a named route range
removes next-hops without taking the session down at all, so there is no session
churn for a flap check to explain away. Peer UP/DOWN stays **required** for
`test_bgp_malformed_packet_test`, where session establishment is what triggers the
UPDATE replay. Switching the ECMP path to route withdraw is an open improvement.

### 2. Declarative-model expressiveness — what the model can describe

The route-range model describes only *conformant* BGP — `next_hop_mode` is
`local_ip` or `manual`, and nothing omits a mandatory attribute — so
malformed-input testing looks impossible from that API alone.

**This class has an escape hatch**, which is what distinguishes it from class 1:
`peer.replay_updates.raw_bytes` takes arbitrary UPDATE bytes (hex, 1–8154) through
the emulated speaker's established session. See `otg_bgp_malformed_updates.py`.

The two classes compose usefully. A replay sequence carries advertises *and*
withdraws with per-entry timing, and OTG replays it on every establishment — so it
is **pre-declared in the pushed config but triggered live** by a `control_state`
peer UP, making mutations that would need `set_config` runtime-triggerable. What
remains out of reach is changing the sequence itself mid-test.

### 3. Description-mechanism mismatch — a porting limit, not an OTG limit

restpy's `PacketHeader` regex-queries IxNetwork's *remote* object tree and sets
vendor attribute names on what it finds; snappi is a local typed schema. The
*packet* is expressible, the *way restpy describes it* is not. Handled by a narrow
whitelist translator that raises `NotImplementedError` rather than dropping
fields — deliberately narrow, since a general translator would build capability
nothing here uses.

The translation is simpler than it looks: `TrafficGenerator.create_packet_headers`
already flattens `attrs_json` **and** resolves every `Reference` (from config
alone — endpoint MACs and device-group IPs) into the ixia-side `Field.attrs` list.
So `OtgTrafficGen` receives a plain `{name: value}` dict with no reference
indirection, and consumes the **ixia-side** struct rather than the taac-side one.

### 4. Field-level constraints — expressible, with rules to translate for

Expressible, but needing conversion — each caused a real bug:

- `bgp.router_id` must be a dotted-quad IPv4, so v6-only peers need a derived
  synthetic ID — and it must be **distinct per speaker** or sessions fail.
- IPv6 route-range `step` is in units of *prefixes*, not an address delta, and
  is uint32-bounded.
- Route-range names must be unique across device groups; the default
  `route_v4`/`route_v6` collide.
- Thrift optional lists arrive as `thrift.python.types.List`, which is **not** a
  `list` or `tuple` — an `isinstance(x, (list, tuple))` guard silently drops
  real config. Use `_nonempty_sequence`.

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
