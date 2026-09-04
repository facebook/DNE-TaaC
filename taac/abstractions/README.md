# DICE: Declarative Intent Compilation Engine

**Scope**: `fbcode/neteng/test_infra/dne/taac/abstractions/`.

**Applies to**: optional high-level authoring helpers and device-independent
behavior abstractions that compile or adapt to the same flat TAAC contracts the
runner already consumes.

**Purpose**: give factory authors a typed source of truth for topology and test
behavior intent without making flat TAAC authoring obsolete. Runtime-neutral
contracts may coordinate that intent, while TAAC-specific execution remains in
`taac/internal`.

Design reference: `P2421897026`.

Implementation roadmap:
[Generalized topology compiler design and roadmap](GENERALIZED_EOS_COMPILER_ROADMAP.md).

---

## 1. Contract

TAAC remains flat. A `TestConfig` is still a flat bundle of endpoints, setup
tasks, teardown tasks, IXIA configs, playbooks, checks, and related thrift
fields.

DICE is an abstraction layer with a factory-side authoring path:

```text
LogicalTopology + PhysicalInventory
  -> bind_to_inventory(physical_inventory, ...)
  -> BoundTopology
  -> inspect_resolved_intent() or compile()
  -> flat TestConfig fragments
```

The runner does not learn a new topology runtime. Generated fragments are copied
into the existing `TestConfig` shape.

Existing flat factory authoring remains supported. Use an abstraction when it
removes duplicated topology intent or gives useful validation; do not use it as
a mandatory wrapper around simple flat configs.

DICE may also define device-independent behavior contracts, such as churn
specifications, policies, selectors, outcomes, and generic orchestration. These
contracts must not depend on TAAC runtime handlers, concrete IXIA objects, DUT
RPC clients, result stores, logging, or `TestCaseFailure`. The concrete adapters
that satisfy those contracts remain under `taac/internal`; reusable IXIA
mechanics remain under `taac/ixia`.

The dependency direction is:

```text
taac/internal/steps
    -> taac/internal
        -> taac/abstractions
        -> taac/ixia
```

Code under `taac/abstractions` must never import `taac/internal`.

### Churn ownership

Churn code follows the same abstraction-to-runtime boundary:

- `taac/abstractions/churn` owns typed scenarios, policies, selectors,
  observations, results, action protocols, generic bounded orchestration, and
  lowering to flat step parameters.
- `taac/internal/churn` owns TAAC handler adapters, DUT RPC integration,
  coordination, result publication, recovery decisions, and test-framework
  failure translation.
- `taac/ixia` owns reusable vendor-specific operations such as session access,
  mutations, bounded apply, readback, restoration, and quarantine mechanisms.
- `taac/internal/steps` remains a thin bridge from `CustomStep` execution into
  the churn runtime adapter.

The abstraction package describes what a churn scenario requires. Internal and
vendor adapters decide how those requirements are executed against live test
infrastructure.

All churn families use the same TAAC playbook renderer. Family-specific
builders supply typed DICE specifications and action-stage factories:

```python
create_dice_unified_churn_playbook(spec=attribute_churn_spec(...))
create_dice_unified_churn_playbook(spec=session_churn_spec(...))
create_dice_unified_churn_playbook(spec=route_churn_spec(...))
```

The unified renderer owns only common `Playbook` assembly. Attribute, session,
and route implementations retain their own target selection, stage parameters,
verification, and recovery behavior.

### Baseline lifecycle and failure ownership

DICE distinguishes two nested restoration boundaries:

- The **topology baseline** is the shared state established by TestConfig
  topology setup. The TAAC runner owns this boundary. For an opted-in Playbook,
  it captures the baseline immediately before Playbook setup and restores it
  before finalizing the Playbook result, including when setup or execution
  fails.
- The **Playbook baseline** is the workload-specific state established after
  Playbook setup, such as selected paths, advertised prefixes, and route
  attributes. The churn implementation owns this boundary and restores it
  after its mutations. For attribute churn, this is an exact restoration of
  the captured IXIA backing vectors rather than a second full-config import.

The intended lifecycle is:

```text
topology setup
  -> capture topology baseline
  -> Playbook setup
  -> capture Playbook baseline
  -> apply and measure churn
  -> restore and verify Playbook baseline
  -> Playbook teardown
  -> restore and verify topology baseline
  -> next Playbook
```

Topology restoration uses the explicit `Playbook.restore_topology_baseline`
opt-in, which defaults to `false`. It does not reuse
`backup_and_restore_ixia_config`; that legacy flag retains its existing
behavior for current consumers. CICD-EBB-10 is the first adopter, so landing
the framework does not enable the topology boundary for every TAAC Playbook.

The two boundaries also have different failure ownership:

- A Playbook-baseline restore failure is a Playbook `FAIL` when the outer
  topology restore succeeds. The workload failed its own restoration contract,
  but the shared environment is safe for the next Playbook.
- A topology-baseline restore timeout, import failure, or verification mismatch
  is an `INFRA_ERROR`. The runner poisons the lifecycle and blocks subsequent
  Playbooks because the shared environment can no longer be trusted.
- If both boundaries fail, `INFRA_ERROR` takes precedence while the original
  Playbook failure remains attached as diagnostic evidence.

The topology IXIA participant verifies the restored configuration against a
canonical JSON digest of the captured snapshot. A successful import without an
exact verification match is therefore still an infrastructure failure.

---

## 2. LogicalTopology Model

LogicalTopology objects declare logical intent:

- endpoints such as `dut0` and `ixia`
- device groups such as `dg_ebgp_v6`
- address plans
- BGP peer-group and policy references
- prefix pools and optional traffic-flow intent
- routing-device defaults such as OpenR or update-group settings

Prefix pools use typed formulaic or explicit sources. Allocation, membership,
next-hop ownership, route attributes, and provenance remain immutable through
binding so inspection and compilation consume the same resolved intent. Add-Path
is represented in intent but remains deferred where the backend cannot lower it.

LogicalTopology objects should be backend-agnostic by default. Do not create separate
topology objects only to switch EOS vs FBOSS. Backend selection comes from
binding to the physical `PhysicalInventory`.

Factories should import concrete topology instances from:

```python
from taac.abstractions.topologies.ebb_full_scale import (
    EBB_FULL_SCALE_NO_BGPMON,
    EBB_FULL_SCALE_WITH_BGPMON,
)
```

Do not add an `abstractions/routing/` layer. Routing-specific behavior belongs
in concrete topology or compiler names, such as `ebb_full_scale.py` and
`EosBgpCppCompiler`.

---

## 3. Binding

`PhysicalInventory` is a first-class DICE framework model, parallel to
`LogicalTopology`. Its domain-neutral definition lives in
`abstractions/physical_inventory/physical_inventory.py`; it must not be defined
under a consumer such as `testconfigs/routing`.

Concrete inventories live in testbed-family modules under
`abstractions/physical_inventory/`. Current routing ownership is:

- `routing_ebb_testbed.py`: BAG and EB-family inventories;
- `routing_dcn_testbed.py`: FBOSS and DCN inventories; and
- `routing_cte_testbed.py`: CTE inventories.

Other DICE consumers add their own testbed modules beside these. Family-local
construction helpers stay in the owning module; there is no shared routing
defaults layer.

Physical inventory supplies:

- DUT name
- physical network role, such as `EB`
- ordered IXIA ports
- IXIA chassis
- local DUT BGP AS (`dut_bgp_as`)
- platform/backend metadata
- configerator paths and lab defaults

LogicalTopology intent belongs in topology objects and factory-level dictionaries. Do
not move logical topology data into `PhysicalInventory` as a side effect of using this
package. The DUT's network role is physical metadata; endpoint function and adjacency
purpose remain logical topology data.

`bind_to_inventory()` resolves logical intent against physical inventory:

- role to `PhysicalInventory.ixia_ports` index
- concrete DUT interfaces and IXIA ports
- endpoint backend
- parent networks
- AS numbers
- peer groups
- concrete A/Z peer addresses

Binding should fail with actionable validation errors when required physical
inventory or factory dictionaries are missing.

`RoutingDeviceConfig.openr_mode` records `NONE`, `STANDALONE`, or `PEER`
intent. Common EOS BGP++ lowering keeps `NONE` inert, stages and restarts
OpenR for `PEER`, and adds the typed standalone link bundle for `STANDALONE`
(see §4 for the full standalone-mode contract). IXIA assignments, route
attributes, and address partitions are typed and validated before
compiler-specific rendering.

---

## 4. OpenR standalone mode

`OpenRMode.STANDALONE` selects the Approach-3 mechanism from the Gate2
OpenR design: a real OpenR daemon runs on the owner DUT but is fed a
synthetic KvStore snapshot instead of forming real adjacencies. The
model types live in `abstractions/topology/model.py`
(`OpenRMode`, `OpenRSetupSequence.STANDALONE_SYNTHETIC_INJECTION`,
`OpenRStandaloneEndpoint`, `OpenRStandaloneLink`).

### 4.1. Approach recap

Three approaches were considered:

1. **Real OpenR to helper devices.** OpenR daemons on both ends form
   real adjacencies. Rejected — cannot vary the IGP metric of individual
   loopbacks independently (all loopbacks resolve out the same
   port-channel).
2. **Script drives FibAgent Thrift directly.** Bypasses OpenR entirely.
   Rejected — leaves the OpenR → FibAgent code path unexercised.
3. **OpenR daemon standalone + fake KvStore snapshot.** IMPLEMENTED.
   Exercises the real code path and gives per-loopback metric control.

### 4.2. Runtime behavior

The OpenR daemon is enabled on the owner DUT with a zero-peer config.
Adjacencies are NOT learned — they are injected into KvStore via
`OpenrCtrlCpp.persistSelfOriginatedKey` with `ttl = int(-(1 << 31))`
(OpenR's "never expire" sentinel). OpenR runs real SPF over the fake
graph and programs FibAgent normally. From FibAgent's perspective the
synthetic routes are indistinguishable from real ones.

### 4.3. Component call-chain

How each `PhysicalInventory` field is consumed by the STANDALONE
lowering path:

| Field | Consumer role |
|---|---|
| `openr_configerator_path` | Deployment task that symlinks the OpenR config into `/etc/openr_config` on the DUT. |
| `openr_standalone_link.owner` | Port-Channel configuration on the owner DUT; admin-up on the owner-side member. |
| `openr_standalone_link.helper` | Far-side member bring-up on the peer DUT so the Port-Channel is operational. The helper does NOT run OpenR. |
| `openr_standalone_link.kv_link(endpoint)` | Adjacency payload used by the standalone synthetic-injection sequence to build `adj:<DUT>`, `adj:<node.*>`, and `prefix:<node.*>` KvStore keys. |

**Reference implementation (EBB BGP++).** The current EOS BGP++ lowering is
split between `abstractions/compiler.py`,
`abstractions/eos_bgpcpp_setup_tasks.py`, and
`internal/utils/openr_route_utils.py`
(`OpenRRouteManager._handle_inject_action_openr`), which invokes
`persistSelfOriginatedKey` via helpers in `openr_kvstore_utils.py`. Phase 1.5
moves platform realization behind the EOS/BGP++ backend and prohibits
`abstractions/**` from importing `testconfigs/**`. Other backends implementing
STANDALONE must satisfy the same field-to-role mapping above.

### 4.4. Single-ownership invariant

Framework contract enforced by every consumer of `OpenRStandaloneLink`:

- **One DUT owns exactly one `OpenRStandaloneLink`.** When two DUTs are
  cabled with two members between them, those members belong to TWO
  SEPARATE port-channels — one owned by each DUT.
- **`owner ≠ helper`**, and owner and helper share the same network on
  each address family (`/31` IPv4, `/127` global IPv6, `/64` IPv6
  link-local within `fe80::/10`).
- **Owner is the authoritative "who may destroy this" field.** Future
  teardown tasks scope their deconfigure operations to the owner's
  Port-Channel only; the peer DUT's inventory retains its own link.

Testbed families that use STANDALONE add their own naming conventions
for `port_channel_id` (e.g. the EBB BAG family's `po1003NN → bag0NN`
rule). Those conventions live in the owning testbed module's docstring,
not here.

### 4.5. Enforcement

`OpenRStandaloneLink.__post_init__` in `abstractions/topology/model.py`
rejects, at import time:

- `port_channel_id <= 0`,
- `owner.hostname == helper.hostname`,
- any endpoint pair whose IPv4 / global-IPv6 / link-local networks
  differ, and
- any endpoint pair whose IP addresses collide on the same address
  family.

Mis-allocation therefore fails when the Python module loads, not at
test execution time.

---

## 5. Compilation

Factories call:

```python
bound = logical_topology.bind_to_inventory(
    physical_inventory=physical_inventory,
    port_map={"uplink": 0, "ibgp": 1},
    parent_networks=parent_networks,
    peer_groups=peer_groups,
    as_numbers=as_numbers,
)
compiled = bound.compile()
```

Factories must not instantiate concrete compiler classes.
`BoundTopology.compile()` selects the backend compiler internally from bound
PhysicalInventory/backend metadata and the resolved routing driver.

Compiler classes are backend or driver implementations, not topology-specific
classes. For example, EBB full-scale and UG custom topology data should both
use the same EOS BGP++ compiler when bound to an EOS BGP++ physical_inventory.

Baseline policy selection is compiler-owned. The common planner resolves a
semantic role-policy preset from the DUT network role, peer relationship,
address family, and direction. The selected platform backend maps that preset
to BGP++ peer-group/route-map references or the corresponding FBOSS policy.
Do not expand or bypass the selected DUT policy merely to make a workload route
pass.

An experiment that compares configuration features uses the single explicit,
typed routing-config variant described in the roadmap. Test-case policy
mutations that are themselves the subject of a playbook remain factory-owned;
they must be explicit and fail closed. They are not a reason to specialize a
reusable topology or add a topology-name branch to a backend.

Compiler-emitted teardown is a stack unwind. When setup tasks take full
running-config snapshots, emit their restores in reverse setup order so the
earliest snapshot determines final device state. Repeated setup tasks that
mutate the same interface must retain and reuse the first pre-mutation backup;
a later intermediate snapshot is not an acceptable teardown baseline.

---

## 6. Migration Checks

Migration acceptance is semantic: prefix membership, peer windows, next hops,
attributes, capabilities, setup, teardown, and playbook effects must remain
equivalent. Order or serialized representation may change when reviewed.

The golden manifest is a diagnostic inventory and drift detector:

```text
buck test fbcode//neteng/test_infra/dne/taac/tests:test_config_golden
```

Refresh it only after semantic assertions explain every changed entry:

```text
buck run fbcode//neteng/test_infra/dne/taac/tests:config_golden -- --update
```

The migration harness does not belong in production. Do not retain legacy raw
builders, CSV digests, certificates, or old/new serialization oracles after a
factory has durable authored, bound, compiled, and catalog assertions.

---

## 7. Phase 1.3 Adoption

The checked production topologies are:

- `EBB_FULL_SCALE_NO_BGPMON` and `EBB_FULL_SCALE_WITH_BGPMON`
- `UG_NEW_PEER_JOIN` and `UG_BACKPRESSURE`
- `IPV6_UPDATE_PACKING`, `EGRESS_PEER_SCALE`, and `BOUNDED_ECMP`

Production factories select an existing topology, bind it to inventory, compile
it, and retain workflow-specific playbooks. Durable assertions live with the
topology and factory rather than in a completed migration-phase ledger.

Playbooks remain factory-owned. Scale Tester, AR/BGP, FBOSS/COOP, multi-DUT,
external OpenR peer creation/readiness, and broader raw-policy rendering are
explicit follow-on work.

---

## 8. Anti-patterns

1. Do not change TAAC runner semantics to support an abstraction.
2. Do not add serialized fields to `TestConfig` for topology data.
3. Do not make TAAC Abstractions mandatory for all factories.
4. Do not instantiate `EosBgpCppCompiler` or any concrete compiler from a
   factory.
5. Do not create one compiler class per topology.
6. Do not add `bgp_asn` to routing `PhysicalInventory`; use existing `dut_bgp_as`.
7. Do not rebaseline goldens without direct semantic evidence for each change.
8. Do not import `testconfigs/**` from `abstractions/**`.
9. Do not store rendered TAAC `Task` objects in common resource plans.
10. Do not select normal compilation behavior from topology name or
    `legacy_profile`.
11. Do not duplicate IXIA lowering between DUT platform backends.
