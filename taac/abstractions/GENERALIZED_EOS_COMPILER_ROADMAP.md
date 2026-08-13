# Generalized topology compiler design and roadmap

Status: Phase 1.5 design baseline, 2026-08-07

The filename is retained because existing documentation links to it. The design
is no longer an EOS-only compiler design: it defines one platform-neutral
compiler pipeline with shared IXIA lowering and selectable DUT backends. Phase
1.5 implements the EOS/BGP++ backend first and leaves FBOSS emission as a
follow-on.

## Goal

Compile a supported topology from logical intent and physical inventory into
the existing flat TAAC artifacts without:

- changing compiler code for each new topology;
- selecting behavior from topology name or `legacy_profile`;
- depending on routing testconfig helpers or constants;
- supplying `legacy_ixia_*` names or indices;
- duplicating IXIA lowering between EOS and FBOSS; or
- hand-authoring baseline setup and teardown in each factory.

TAAC remains flat at runtime. DICE is an authoring-time compiler and continues
to emit `CompiledTaacArtifacts` for existing consumers.

## Current position

DICE now has enforced import boundaries, a task-free common compilation plan,
explicit physical network roles, typed EB policy selection, and a complete
semantic IXIA plan for the current topology families. The temporary migration
parity harness was retired after cutover; reusable topology cases remain in
`abstractions/tests/compiler_test_cases.py` for focused planner and renderer
tests. The candidate compiler can project bound device groups into DUT and IXIA
resources without invoking a renderer.

It is not generalized yet:

- `compiler.py` dispatches rendering through topology names and
  `legacy_profile`;
- established setup phases and component plans contain rendered TAAC `Task`
  objects;
- the established EOS `IxiaPlan` contains already-rendered TAAC configs, while
  the new semantic `IxiaPlan` does not yet have a native renderer;
- component-role and lifecycle dependency intent are not yet projected;
- the candidate artifact adapter delegates DUT and IXIA rendering as one
  monolithic compatibility operation;
- IXIA endpoint wiring and route-mutation lifecycle are still embedded in the
  EOS compiler;
- profile-specific lowering still reads `BoundTopology` directly; and
- `FbossCoopCompiler` is an empty shell.

The current 48-task BAG sequence is valuable compatibility evidence, but it
must not become the architecture.

## Non-negotiable contracts

1. `BoundTopology.compile()` remains the public entry point.
2. Factories continue consuming the same flat `CompiledTaacArtifacts` fields.
3. Backend selection happens once from bound physical metadata, currently
   `(endpoint_os, routing_driver)`.
4. Logical topology remains platform-neutral. A topology is not cloned merely
   to select EOS versus FBOSS.
5. Structural migration preserves current consumer output until a separately
   reviewed semantic change deliberately updates it.
6. The migration parity oracle is test-only and is removed after each path has
   durable semantic and golden coverage.
7. Plans contain desired state and lifecycle metadata, never rendered
   `Task` objects.
8. Unsupported required intent fails before rendering; generic empty success
   is not a valid compile result.

## Architecture

```text
LogicalTopology + PhysicalInventory
                |
                v
             binding
                |
                v
          BoundTopology
                |
                v
     capability analysis + common planner
                |
                v
        TopologyCompilationPlan
          /                 \
         /                   \
shared IXIA resources      DUT desired state
         |                   |
         v                   v
 shared IXIA renderer     selected DutBackend
                         /                  \
                 EOS/BGP++ backend       FBOSS backend
                         \                  /
                          lifecycle fragments
                                  |
                                  v
                    common dependency scheduler
                                  |
                                  v
                    CompiledTaacArtifacts adapter
```

There are not two complete topology compilers. If compatibility requires
`EosBgpCppCompiler` and `FbossCoopCompiler` classes to remain temporarily,
they are thin compositions of the same planner and IXIA renderer with
different DUT backends.

### Common planner ownership

The common planner owns:

- endpoint and physical-link identity;
- bound addresses, ASNs, peer multiplicity, and route scale;
- interface and adjacency desired state;
- prefix and route-attribute intent;
- network-role policy selection;
- IXIA ports, device groups, peers, advertisements, and traffic items;
- component roles and dependency intent;
- ownership, readiness requirements, and teardown relationships; and
- capability accounting and diagnostics.

It does not own EOS CLI, FBOSS agent operations, daemon names, filesystem
paths, Configerator installation commands, or route-map spellings.

### Shared IXIA ownership

EOS and FBOSS use the same IXIA resources when bound to the same topology:

- port and L1 configuration;
- device-group allocation;
- BGP peer/session configuration;
- prefix and route-attribute emission;
- runtime route mutations;
- IXIA cleanup and session ownership.

IXIA capability is a traffic-generator concern, not a DUT platform branch. A
future non-IXIA traffic generator would be another traffic-generator backend,
orthogonal to `DutBackend`.

`TrafficFlowSpec` and traffic-item lowering are deferred. None of Phases
1.5-1.9 depends on compiler-generated traffic items.

### DUT backend ownership

A DUT backend renders platform realization for:

- pre-IXIA host and port preparation;
- routing-config fetch, installation, and optional experiment variant;
- interface realization;
- role-policy realization;
- component startup, restart, dependency order, and readiness;
- platform-specific OpenR link work;
- ACL, logging, firewall, certificate, and filesystem preparation; and
- restoration and teardown.

EOS/BGP++ therefore owns the BGP disable/enable sequence, BGP++/FibAgent/OpenR
daemon mapping, EOS interface CLI, EOS route-map bindings, and
`/mnt/flash/bgpcpp_config` installation. FBOSS will own the corresponding
agent configuration and lifecycle.

### Lifecycle is a graph, not a pre/post-IXIA split

“Pre-IXIA” and “post-IXIA” describe current ordering, not code ownership.
Resources declare dependencies and the common scheduler orders them. Example
dependency milestones are:

- `dut_links_prepared`;
- `ixia_ports_configured`;
- `routing_config_installed`;
- `dut_interfaces_configured`;
- `routing_components_ready`; and
- `routing_sessions_ready`.

The EOS backend can preserve the current order while the FBOSS backend uses a
different legal order. A fixed sleep remains in the compatibility renderer
until a backend readiness contract replaces it.

## Existing BAG setup classification

The current BAG Stage-1 sequence is classified as follows:

| Current tasks | Meaning | Target owner |
|---|---|---|
| 1-5 | Disable `BgpTcpdump`, prepare IXIA-facing EOS ports, wait | Common link intent; EOS rendering |
| 6 | Formulaic IXIA route mutation | Shared IXIA renderer |
| 7-15 | Host bootstrap, certificates, routing config, FibAgent config, legacy peer materialization | EOS/BGP++ backend |
| 16-17 | OpenR config fetch and installation | Common OpenR intent; EOS rendering |
| 18-34 | Logging, ACLs, component disable/enable, runtime checks | Common component intent; EOS rendering |
| 35-44 | Bound interface-address blocks | Common interface plan; backend rendering |
| 45-47 | Standalone OpenR link and route injection | Common feature plan; platform link rendering; shared API where possible |
| 48 | EOS BGP firewall finalization | EOS/BGP++ backend |

The ranges are a compatibility signature, not permanent phase APIs.

## Role and policy model

“Role” currently has several meanings and they must not be conflated:

| Concept | Example | Owner |
|---|---|---|
| Endpoint function | `dut`, `trafficgen` | Logical topology |
| Device-group purpose | `uplink`, `ibgp_dc_p1` | Logical topology |
| Network-device role | `EB`, later `FA`, `FADU`, `SSW` | Physical inventory |
| Peer relationship | EB-to-FA external, EB-to-EB internal, monitor | Adjacency intent |

`PhysicalInventory` gains an explicit network-role field. Every BAG inventory
declares `EB`; this must not be represented by changing
`EndpointSpec.role="dut"`.

Policy resolution uses a normalized key:

```text
local network role
  + peer relationship or peer role
  + address family
  + import/export direction
  -> semantic RolePolicyPreset
```

The planner resolves each unique preset once, then binds all applicable device
groups to it. For EB this distinguishes at least EB-to-FA external policy,
EB-to-EB internal policy, and monitor behavior. It does not duplicate policy
rules per peer.

The common preset expresses policy semantics. Platform bindings map that preset
to implementation:

- EOS/BGP++ selects the Configerator profile, peer-group, and route-map
  references;
- FBOSS renders the equivalent agent policy; and
- an unsupported mapping is a capability error.

Adding a future device role adds a preset and platform binding. It does not add
a topology-name branch to the compiler.

## Routing-config ownership and experiment overrides

The normal path treats the Configerator routing artifact as the source of
truth. The compiler fetches and installs it, then the backend reconciles the
required components. It does not scatter one-off Python or shell patches
through setup helpers.

The plan models:

```text
RoutingConfigPlan
  source: ConfigArtifactRef
  requirements: RoutingConfigRequirements
  variant: None | RoutingConfigVariant
```

`RoutingConfigVariant` is the single intentional override seam for A/B
comparisons such as feature enabled versus disabled:

- absent by default;
- platform-specific, typed, and allowlisted;
- deterministic and visible in the compile report;
- applied in one backend-owned renderer;
- followed by the backend-declared restart sequence; and
- removed or restored through the same lifecycle plan.

Selecting a separate Configerator artifact or a native overlay is preferred. If
BGP++ requires materialization, the backend creates an ephemeral derived
artifact rather than repeatedly editing the fetched base file in place.

Role policy is normal compilation, not an experiment override. The Configerator
contract must declare which peer and policy requirements an artifact satisfies.
The compiler does not need runtime content validation, but it must reject a
known-incompatible artifact before rendering. Until Configerator or BGP++
provides a complete peer/policy contract, current peer replacement remains
isolated compatibility debt and is not part of the generalized API.

## Task-free intermediate representation

The compilation plan contains typed desired resources such as:

- `EndpointPlan`;
- `DutLinkPlan`;
- `InterfacePlan`;
- `BgpAdjacencyPlan`;
- `PolicyPlan` and `PolicyBinding`;
- `RoutingConfigPlan`;
- `ComponentPlan`;
- `IxiaPlan`;
- `OpenRPlan`; and
- `LifecycleOperation`.

Each mutating operation carries:

- a stable resource ID;
- dependency IDs;
- ownership: compiler-owned, borrowed, or snapshot-restored;
- desired state;
- a readiness requirement;
- inverse or restoration behavior; and
- an explicit no-op or unsupported reason when applicable.

Setup is dependency order. Teardown is reverse dependency order over resources
owned or changed by the compiler. A snapshot-restored resource reuses its first
pre-mutation snapshot. Partial cleanup attempts independent resources and
preserves the primary execution error.

## Dependency rules

The allowed dependency direction is:

```text
factories
  -> topology + physical inventory
  -> compiler facade
  -> common planning model
      -> role-policy presets
      -> IXIA planner/renderer
      -> selected DUT backend
          -> stable TAAC task definitions
```

The following are forbidden:

- `abstractions/**` importing `testconfigs/**`;
- the common planner importing concrete topology modules;
- a DUT backend importing a factory or topology instance;
- plans importing TAAC `Task` types;
- common code branching on EOS/FBOSS after backend selection; and
- normal behavior selected from topology name or `legacy_profile`.

Existing constants move according to meaning:

| Constant kind | Destination |
|---|---|
| Full-scale counts, prefix shapes, exclusions | Concrete topology module |
| Parent networks and physical links | Physical inventory or binding input |
| EB policy semantics | EB role-policy preset |
| EOS route-map/peer-group spellings | EOS/BGP++ policy binding |
| Daemon names, commands, paths, ACLs, logging | EOS/BGP++ backend |
| IXIA naming/allocation defaults | Shared IXIA planner |

The existing `compiler.py` remains a stable facade during migration. New code
lives under a package that does not collide with that module:

```text
abstractions/compilation/
  model.py
  capabilities.py
  planner.py
  lifecycle.py
  report.py
  policy/
    model.py
    presets/eb.py
  ixia/
    planner.py
    renderer.py
  backends/
    base.py
    eos_bgpcpp/
      config.py
      host.py
      interfaces.py
      policy.py
      components.py
      openr.py
      renderer.py
    fboss/
      renderer.py
```

The FBOSS package may initially contain only capability declarations and an
explicit unsupported result. It must not return silent empty artifacts.

## Phase 1.5: dependency inversion with compatibility

Phase 1.5 establishes the generalized structure while preserving current
consumers. It is not the claim that arbitrary topologies are already supported.

### In scope

1. Add the task-free common plan, lifecycle metadata, compile report, and
   `DutBackend` protocol.
2. Keep `BoundTopology.compile()` and `CompiledTaacArtifacts` unchanged.
3. Separate the shared IXIA plan/renderer from DUT rendering.
4. Move EOS host, config, interface, policy-binding, component, OpenR, and
   finalization rendering behind the EOS/BGP++ backend.
5. Add explicit network role to physical inventory and mark BAG devices as
   `EB`.
6. Add the role-policy model, the EB preset, and EOS bindings to existing
   peer-group/route-map references.
7. Add `RoutingConfigPlan` and the single optional experiment-variant seam.
8. Eliminate every production `abstractions/** -> testconfigs/**` import and
   the compiler's import of concrete topology modules.
9. Isolate remaining topology/profile dispatch in a compatibility adapter; new
   planning code cannot observe topology name or `legacy_profile`.
10. Add test-only old/new parity checks for the migrated BAG path, including
    the ordered 48-task signature and normalized IXIA artifacts.

### Explicitly out of Phase 1.5

- production FBOSS task emission;
- removing every legacy topology branch;
- arbitrary policy-language compilation;
- traffic-item lowering where no current compiler output exists;
- multi-DUT orchestration;
- automatic address allocation;
- a new TAAC runtime or serialized topology field; and
- lifecycle reordering or removal of compatibility tasks without a separate
  semantic review.

### Exit criteria

Phase 1.5 is complete when:

- no production Python file under `abstractions/` imports `testconfigs/`;
- the common compiler and backend interfaces import no concrete topology;
- common plans contain no TAAC `Task` values;
- every BAG physical inventory exposes network role `EB`;
- EB policy selection is driven by role and adjacency rather than topology
  identity;
- IXIA planning is shared and contains no EOS/FBOSS branch;
- EOS task rendering is backend-owned and current BAG consumers retain
  normalized artifact parity;
- baseline routing config has no ad-hoc feature patch; an override is explicit
  and compile-report-visible;
- unsupported FBOSS compilation is explicit rather than empty success; and
- lint, focused unit tests, compiler tests, and relevant golden checks pass.

## EOS capability sequence

Phases 1.5-1.7 complete the generalized EOS setup compiler. Phase 1.8 then
uses its stable topology artifacts to compile playbook behavior. Phase 1.9 is
reserved for OpenR/helper semantics and cannot be fully implementation-scoped
until that design is agreed.

FBOSS, multi-DUT transactions, additional routing drivers, and traffic-item
compilation are deferred beyond this EOS sequence. The common abstractions must
remain capable of supporting them without carrying incomplete implementations.

## Phase 1.5 implementation plan: dependency inversion and parity

### Objective

Establish the generalized internal structure and remove reverse helper
dependencies without changing existing factory APIs or BAG behavior. Phase 1.5
does not claim profile-free compilation.

### Diff 1.5.0: compatibility and parity harness (historical)

This migration-only gate was removed after cutover. The following records the
constraints it enforced while both compiler paths coexisted.

Implement the migration harness before extracting planner or renderer code:

1. Keep the established compiler authoritative for production consumers.
2. Add a test-only `CompilerParityHarness` that accepts established and
   candidate compiler callables for the same `BoundTopology`.
3. Canonicalize and compare every `CompiledTaacArtifacts` field:
   - endpoint identity and parameters;
   - host OS mapping;
   - ordered setup task name, hostname, parameters, and IXIA requirement;
   - ordered teardown tasks;
   - IXIA port, device-group, BGP-session, and advertisement configuration; and
   - traffic-item output, which must remain empty where it is empty today.
4. Support exact comparison for stable values and narrowly scoped
   normalization for known nondeterministic serialization. Normalization must
   never hide task insertion, deletion, reordering, parameter changes, scale
   changes, or resource-ownership changes.
5. Report the first mismatch by artifact field, lifecycle phase, resource ID,
   and task index so parity failures are actionable.
6. Seed the harness with BAG010's ordered 48-task contract and representative
   BAG/UG/update-packing/egress-scale/bounded-ECMP fixtures.
7. Keep TestConfig goldens as an independent drift detector; the harness is
   the structural migration gate.

The candidate path is invoked explicitly by tests. Do not dual-render in
production or change what factories receive before parity passes. After a path
cuts over, replace temporary old/new assertions with durable semantic tests and
remove that path from the harness.

### Zero-shift gate for Phases 1.5-1.7

Behavior-preserving compiler migration must not update
`tests/golden_config_manifest.json`. A manifest change is a migration failure,
not something to rebaseline in the same diff.

The existing golden test is necessary but not sufficient:

- it hashes stable JSON for cataloged deterministic TestConfigs and is
  land-blocking through its CI hint;
- its pre-commit hook can regenerate the manifest, so reviewers must verify the
  manifest is absent from migration diffs; and
- `NONDETERMINISTIC_CONFIGS` currently excludes BAG010 Stage 1 and several EBB
  full-scale configs, so those paths receive no hash protection from the
  manifest.

Use three independent gates:

1. **Compiler-artifact parity.** The harness compares established and candidate
   artifacts for every migrated topology/inventory/setup-mode case, including
   configs excluded from the golden manifest.
2. **Factory-level golden gate.** Run
   `buck test fbcode//neteng/test_infra/dne/taac/tests:test_config_golden`
   without changing the checked-in manifest.
3. **No-diff regeneration check.** Run
   `(cd fbcode && buck run //neteng/test_infra/dne/taac/tests:config_golden -- --update)`
   as a diagnostic and require no tracked manifest change. If it changes,
   investigate the candidate output and do not include the regenerated
   manifest.

The harness canonicalizer may sort JSON object keys and normalize only
documented nondeterministic values. It must compare these consumer-significant
properties exactly:

- artifact membership and count;
- endpoint and connection identity;
- setup/teardown task count and order;
- task name, hostname, `ixia_needed`, and complete parameters;
- interface, address, ASN, peer-group, route-map, and component values;
- IXIA device-group/session names, indices, route counts, and attributes; and
- full-scale peer and prefix scale.

Cut over one capability/profile at a time:

1. add its complete case matrix to the harness;
2. make the candidate reach zero artifact differences;
3. run focused semantic tests plus the full golden test;
4. switch only that case to the candidate;
5. rerun artifact parity against the retained established implementation;
6. verify the golden manifest is unchanged; and
7. remove the established path only after durable semantic tests replace the
   temporary comparison.

An intentional TestConfig semantic change must be a separate reviewed diff with
an explained manifest update. Mixing such a change into Phases 1.5-1.7 would
make compiler migration drift impossible to attribute.

### Diff 1.5.1: dependency ownership

1. Create the `abstractions/compilation/` package and its BUCK boundaries.
2. Move every constant currently imported from
   `testconfigs/routing/util/bgp_ebb_constants.py` into its owning layer:
   topology shape, physical inventory, EB policy preset, shared IXIA planner,
   or EOS/BGP++ backend.
3. Remove the compiler import of the concrete egress-scale topology.
4. Add an import-boundary test that rejects:
   - production `abstractions/** -> testconfigs/**` imports;
   - common-planner imports of concrete topology modules; and
   - common-plan imports of TAAC task types.
5. Prove no serialized artifact or golden change.

### Diff 1.5.2: task-free compiler contracts

1. Add stable resource IDs, ownership/restoration modes, lifecycle dependency
   metadata, and `CompileReport`.
2. Add task-free plans for endpoints, links, interfaces, adjacencies, policy,
   routing config, components, IXIA, and OpenR.
3. Add `DutBackend` and traffic-generator renderer protocols.
4. Keep `compiler.py`, `BoundTopology.compile()`, and
   `CompiledTaacArtifacts` as the compatibility facade.
5. Add the candidate composition as an explicit harness target without making
   it authoritative.
6. Unit-test duplicate IDs, missing dependencies, cycles, deterministic order,
   reverse teardown order, unsupported intent, and explicit no-op reasons.

### Diff 1.5.3: physical role and EB policy seam

1. Add an explicit physical network role to `PhysicalInventory`, binding, and
   resolved endpoint metadata.
2. Mark every BAG inventory as `EB`; retain `EndpointSpec.role="dut"`.
3. Add normalized adjacency relationship metadata instead of parsing raw role
   strings throughout renderers.
4. Define the semantic EB policy presets for external, internal, and monitor
   relationships by AFI and direction.
5. Add EOS/BGP++ bindings from those presets to the existing Configerator
   profile, peer-group, and route-map references.
6. Keep resulting peer-group and route-map behavior identical.

### Diff 1.5.4: shared IXIA lane

Split this diff at the semantic-plan/native-renderer boundary so either slice
can be reviewed or deferred independently.

**Diff 1.5.4a: semantic IXIA plan**

1. Build a task-free IXIA plan from bound ports, endpoint identities,
   addresses, ASNs, peers, advertisements, next hops, and route attributes.
2. Use stable logical `ResourceId` values for allocation and references.
   Preserve legacy IXIA names and indices only in an optional compatibility
   identity sidecar; they cannot affect semantic planning.
3. Validate cross-resource references, peer cardinality, route cardinality,
   child windows, and exactly-once compile reporting.
4. Reject nonempty `TrafficFlowSpec` input explicitly until traffic-item
   lowering has its own phase.
5. Freeze semantic counts and route geometry for BAG010, UG new/dynamic peer,
   update packing, egress scale, and bounded ECMP.

Status: locally complete on 2026-08-07 with zero candidate artifact or golden
shift.

**Diff 1.5.4b: shared native IXIA renderer**

1. Define a renderer result that owns port configs, traffic-generator-owned
   setup fragments, and IXIA endpoint wiring.
2. Render current port, device-group, BGP-session, advertisement, and
   route-mutation artifacts from the semantic plan plus optional identity
   sidecar, without an EOS/FBOSS branch.
3. Preserve exact omitted-versus-`None` field behavior and established ordering
   while compatibility identities are requested.
4. Compare normalized IXIA artifacts for the complete parity case matrix.
5. Switch only the traffic-generator lane to native after parity; keep DUT
   rendering delegated until Diff 1.5.5.

### Diff 1.5.5: EOS/BGP++ renderer extraction

1. Move host preparation, config installation, interface realization,
   component lifecycle, policy binding, OpenR realization, and host
   finalization behind the EOS/BGP++ backend.
2. Replace helpers named for `ebb_full_scale` when their inputs are generic.
   Full-scale naming remains only for full-scale topology shape and scale.
3. Derive interface operations from `InterfacePlan`; do not enumerate
   `_EBB_IBGP_ROLES` inside the renderer.
4. Preserve the established BAG task order, including the 48-task Stage-1
   signature, until a separately reviewed semantic change removes a task.
5. Keep platform commands and TAAC task construction out of common plans.

### Diff 1.5.6: routing-config variant and facade cutover

1. Add `RoutingConfigPlan`, `ConfigArtifactRef`,
   `RoutingConfigRequirements`, and the optional typed
   `RoutingConfigVariant`.
2. Fetch the Configerator-owned base artifact and centralize the EOS restart
   requirements.
3. Make A/B feature overrides explicit, allowlisted, and absent by default.
4. Isolate legacy peer materialization as compatibility debt; it cannot become
   a common planning API.
5. Dual-render only in tests. Continue returning the established output until
   normalized parity passes, then make the composed planner/renderers
   authoritative.
6. Remove the temporary oracle after durable semantic and golden assertions
   cover the new path.

### Phase 1.5 validation

- Compatibility-harness self-tests proving that task insertion, deletion,
  reordering, parameter drift, scale drift, and IXIA drift are detected.
- Import-boundary and BUCK-layer tests.
- Pure-plan and lifecycle unit tests.
- Physical role/binding and EB policy-resolution tests.
- Normalized IXIA parity.
- BAG010 ordered 48-task signature and task-parameter parity.
- Representative topology compiler tests.
- Relevant TestConfig golden checks.
- `arc lint` for every changed file.

### Phase 1.5 exit

- No production `abstractions/** -> testconfigs/**` dependency remains.
- The established compiler remains authoritative until the harness proves
  candidate parity and an explicit cutover occurs.
- The common plan is task-free and platform-neutral.
- IXIA planning is shared.
- EOS realization is backend-owned.
- BAG role and baseline policy selection are explicit.
- Existing consumers and outputs remain stable.

## Phase 1.6 implementation plan: profile-free EOS baseline

### Objective

Compile a new, supported EOS/BGP++ topology without a topology-name branch,
`legacy_profile`, or `legacy_ixia_*` identity.

### Diff 1.6.1: EOS capability analysis

1. Define the supported baseline:
   - one EOS DUT and one IXIA endpoint;
   - BGP++ routing driver;
   - already-bound IPv4/IPv6 addresses;
   - eBGP and iBGP adjacencies;
   - EB role presets backed by a compatible Configerator artifact;
   - OpenR `NONE`; and
   - no traffic items.
2. Account for every requested resource as emitted, borrowed, intentionally
   skipped, or unsupported.
3. Fail unsupported required intent before task rendering.
4. Replace generic silent-empty success with an actionable compile error.

### Diff 1.6.2: generic resource planning

1. Generate endpoints and host metadata from bound endpoint/inventory data.
2. Generate DUT link, interface-address, BGP adjacency, routing-config,
   component, and IXIA plans by iterating bound resources.
3. Eliminate required-role and peer-count tables from the generic planner.
4. Allocate stable identities and deterministic ordering from logical resource
   identity, not topology name.
5. Produce setup and teardown lifecycle operations from the same plan.

### Diff 1.6.3: baseline EOS rendering

1. Render EOS pre-IXIA link preparation.
2. Fetch/install the declared BGP++ Configerator artifact.
3. Render interface realization and the BGP++/FibAgent component sequence.
4. Render shared IXIA ports, device groups, BGP sessions, and advertisements.
5. Render readiness requirements needed for safe ordering, without adding
   broad configuration-validation probes.
6. Render teardown only for compiler-owned or snapshot-restored resources.

### Diff 1.6.4: profile-free acceptance fixture

Create a synthetic dual-stack eBGP+iBGP topology with:

- `legacy_profile=None`;
- no `legacy_ixia_*` fields;
- explicit EB network and peer relationships;
- explicit/bound parent networks and ASNs;
- OpenR `NONE`; and
- no traffic flow.

The tests must prove:

1. all required endpoint, interface, peer, policy, config, component, and IXIA
   resources are accounted for;
2. setup and teardown are ordered by dependencies;
3. renaming the topology does not change normalized semantics;
4. changing only bound inventory changes only physical realization;
5. unsupported policy/OpenR intent fails before rendering; and
6. no compiler edit is required to add a second topology using the supported
   capability set.

### Phase 1.6 exit

A profile-free EOS topology compiles completely through the generalized path.
The compatibility adapter is still allowed for production profiles whose
capabilities are not yet covered. Existing catalog TestConfigs and the golden
manifest remain unchanged.

## Phase 1.7 implementation plan: EOS route and policy capabilities

### Objective

Cover the route and role-policy capabilities required by current EOS
topologies, without adding traffic-item compilation or playbook churn logic.

### Diff 1.7.1: route advertisement lowering

1. Lower prefix-set membership and formulaic/explicit prefix sources.
2. Lower next-hop ownership and supported per-peer/per-prefix distribution.
3. Lower current standard/extended communities and supported AS-path shapes.
4. Preserve active-prefix count semantics when exclusions are present.
5. Emit explicit capability errors for unsupported Add-Path or attribute
   combinations.

### Diff 1.7.2: role-policy completion

1. Resolve import/export policy from local network role, peer relationship,
   AFI, and direction.
2. Complete the EB preset coverage used by BAG topologies.
3. Resolve semantic presets to EOS/BGP++ Configerator
   peer-group/route-map bindings.
4. Represent MED, local preference, community actions, AS-path prepend, route
   limits, and timers only where the selected EOS binding supports them.
5. Keep experimental feature toggles in `RoutingConfigVariant`, not in role
   presets.

### Diff 1.7.3: EOS profile capability migrations

1. Migrate non-OpenR setup capabilities in increasing complexity:
   bounded ECMP, egress peer scale, update packing, UG baseline setup, then EBB
   full scale.
2. Compare normalized resource plans and serialized artifacts.
3. Delete a topology predicate, argument adapter, and legacy IXIA identity
   immediately after its last consumer migrates.
4. Keep runtime triggers and churn actions factory/playbook-owned until Phase
   1.8.
5. Preserve full-scale scale and route-count expectations.

### Phase 1.7 validation

- Prefix membership and exclusion-boundary tests.
- Per-peer route attribute and next-hop tests.
- EB policy-resolution matrices by relationship, AFI, and direction.
- Unsupported-capability tests.
- Normalized and golden parity for each migrated topology.
- Full-scale planning tests that avoid materializing route-count-sized Python
  structures unnecessarily.

### Phase 1.7 exit

All currently required non-OpenR EOS setup capabilities compile through common
planning plus the EOS/BGP++ backend. Traffic generation beyond routing
protocol/session and advertisement setup remains deferred. Every migrated
existing TestConfig has zero established/candidate artifact drift and no golden
manifest change.

## Phase 1.8: topology-artifact-driven playbook chains

Phase 1.8 begins only after Phase 1.7 provides stable logical resource IDs and
compiled artifact provenance. Its purpose is to formalize test behavior rather
than add more setup templates.

The compiler exposes a typed `TopologyArtifactIndex` mapping logical resources
to concrete endpoints, interfaces, peer groups, sessions, prefixes, policies,
and components. A separate playbook compiler consumes selectors over that
index and lowers a chain such as:

```text
preconditions
  -> trigger
  -> churn or mutation window
  -> convergence validations
  -> steady-state validations
  -> recovery
  -> restoration validations
```

The initial design must define:

- typed trigger targets and actions;
- churn cardinality, ordering, duration, and repetition;
- validation dependencies, deadlines, and convergence windows;
- whether a validation observes topology intent, emitted setup state, or
  runtime state;
- recovery and cleanup behavior after a failed intermediate step; and
- platform-neutral action intent with EOS-specific trigger/validation
  rendering where necessary.

Playbooks continue emitting existing TAAC steps. This phase does not put
playbook execution into the topology compiler and does not require traffic-item
generation.

## Phase 1.9: OpenR/helper capability and final compatibility removal

Phase 1.9 is design-gated. The existing standalone owner/helper wiring contract
does not yet define a generalized “OpenR helper mode.”

Before implementation, decide:

- whether a helper is a borrowed physical endpoint, a compiler-managed
  endpoint, or a full topology node;
- whether the helper runs OpenR or only brings up the far-side link;
- whether the mode uses real adjacency, synthetic KvStore injection, or both;
- which side owns config deployment, component lifecycle, readiness, and
  teardown;
- how port-channel and route ownership behave across multiple DUTs;
- how partial setup and helper unavailability affect rollback; and
- whether helper behavior belongs in the DUT backend, a multi-endpoint
  orchestrator, or the playbook chain layer.

Until those questions are answered, Phase 1.9 retains the current explicit
`OpenRStandaloneLink` behavior for existing consumers and does not claim a
general helper abstraction. Final OpenR profile migration and remaining
compatibility deletion follow the approved design.

## Weekend implementation plan

Status: implementation started 2026-08-07. Diffs 1.5.0 through the
independently droppable all-16 shared IXIA endpoint extraction and
resource-keyed endpoint composition are committed. EOS/BGP++ capability
preflight now runs ahead of adaptation and shadow rendering, and shared IXIA
port-base rendering owns `BasicPortConfig.endpoint` across all frozen cases.
The four already-native IXIA cases also expose resource-keyed
`device_group_configs` shadows with per-group provenance and compose both
fields through an identity-blind, resource-keyed shadow boundary.

The weekend goal is a reviewable stack that establishes the migration safety
rail and generalized compiler contracts. It does not attempt to complete all
of Phase 1.5:

1. **Completed:** Diff 1.5.0, compatibility/parity harness.
2. **Completed:** Diff 1.5.1, dependency ownership and import guards.
3. **Completed:** Diff 1.5.2, task-free types and backend protocols behind the
   unchanged facade.
4. **Completed:** Diff 1.5.3, physical `EB` role and the
   policy-resolution seam.
5. **Completed:** Diff 1.5.4a, complete the
   shared semantic IXIA plan and its invariants without changing rendering.
6. **Completed shadow capabilities:** Diff 1.5.4b, add shared IXIA rendering
   for UG and IPv6 update-packing without artifact authority.
7. **Completed shadow capability:** Diff 1.5.5a, extract field-scoped EOS
   host-OS and endpoint-base rendering.
8. **Completed shadow capability:** Diff 1.5.5b, separate IXIA endpoint wiring
   from full session, advertisement, and lifecycle lowering.
9. **Completed shadow capability:** Diff 1.5.5c, compose EOS endpoint bases and
   shared IXIA endpoint patches by stable resource ID without changing artifact
   authority.
10. **Completed migration gate:** Diff 1.5.5d, extract EOS/BGP++ capability
    preflight from the established adapter and run it before every rendering
    lane.
11. **Completed shadow capability:** Diff 1.5.5e, render resource-keyed IXIA
    `BasicPortConfig` endpoint bases independently of device-group, session,
    advertisement, and lifecycle lowering.
12. **Completed shadow capability:** Diff 1.5.5f, extract resource-keyed
    `BasicPortConfig.device_group_configs` bodies for the four existing native
    IXIA cases without expanding their semantic capability.
13. **Completed contract hardening:** Diff 1.5.5g, replace parallel IXIA
    device-group identity/config tuples with nested resource-keyed provenance
    before composing `BasicPortConfig` values.
14. **Completed shadow capability:** Diff 1.5.5h, compose IXIA port bases and
    device-group bodies by stable resource ID without changing artifact or
    renderer-report authority.
15. **Completed semantic prerequisite:** Diff 1.5.5i, distinguish an explicitly
    selected advertising-session local next hop from an unset IXIA default.
16. **Completed shadow capability:** Diff 1.5.5j, lower partitioned dual-stack
    IXIA device-group bodies from semantic resources and compose them by
    resource ID for both bounded-ECMP cases.
17. **Completed Phase 1.6 identity prerequisite:** Diff 1.6.2a, derive
    partitioned IXIA group, session, and advertisement presentation from
    stable resource IDs while retaining field-scoped compatibility overrides.

#### Resource-derived partitioned IXIA presentation

Partitioned dual-stack lowering no longer requires group, session, or
advertisement entries in `LegacyIxiaIdentitySidecar`. A task-free presentation
resolver derives versioned, fixed-length names from typed `ResourceId` values
and allocates zero-based device-group indices from per-port plan order.
Explicit sidecar fields remain resource-keyed overrides. They do not reorder
resources or shift other defaults, and resolved name or index collisions fail
closed.

`IxiaDeviceGroupChild` legacy presentation fields are now optional. A
bounded-ECMP topology with `legacy_profile=None` and those fields omitted
produces the same semantic IXIA plan, while the existing overrides preserve
the established artifacts exactly.

This completes only the partitioned IXIA identity-allocation portion of Diff
1.6.2. Port endpoint labels still depend on `LegacyIxiaPortIdentity`; native
EOS setup, teardown, endpoint realization, and artifact assembly remain Phase
1.6 work. Legacy identity requirements for the initial/tagged and compact/named
IXIA capabilities remain deferred to their Phase 1.7 profile migrations.

Remaining IXIA families and lifecycle capabilities, EOS
lifecycle/config/interface rendering, facade cutover, Phase 1.6, Phase 1.7,
traffic-item compilation, generalized OpenR/helper behavior, and FBOSS task
emission remain independently gated.
Do not substitute topology-selected compatibility constants for missing typed
inputs merely to make the weekend stack appear complete.

### Recorded implementation blocker

The Phase 1.5.1 source-boundary test has complete, fail-closed coverage for the
current flat abstraction packages. Buck globs stop at child package boundaries,
so that resource harness cannot automatically discover a future nested package
such as `compilation/backends/eos`.

Diff 1.5.2 therefore remains flat. Before introducing the first nested compiler
package, add query/BXL-backed recursive discovery or a governed library macro
that makes omission impossible. A nested package must not be added using only
the current explicit resource manifest.

### Phase 1.5.2 deferred projections

The task-free contracts expose policy bindings and component resources, but the
current logical topology does not yet provide enough platform-neutral input to
populate them safely:

- `BgpPolicy` does not encode DUT import versus export direction. Diff 1.5.3
  resolves directional DUT bindings from typed network role, relationship,
  AFI, and direction instead of misusing advertisement `BgpPolicy` intent.
- Current topology intent does not declare semantic component roles or their
  dependencies. `ComponentPlan` projection remains in Diff 1.5.5 with EOS
  renderer extraction; the common planner must not infer daemon roles.
- Final EOS and IXIA artifact rendering remains compatibility-delegated in the
  Phase 1.5.2 harness composition. Native renderer reports replace those
  delegations in Diffs 1.5.4-1.5.6.

Legacy IXIA names and indices are accepted only through an optional identity
sidecar keyed by stable `ResourceId`. The sidecar cannot affect allocation,
capability selection, scheduling, ownership, or lifecycle. Peer counts,
partitions, child windows, physical inventory indices, ports, addresses, ASNs,
and route geometry remain semantic plan data.

### Phase 1.5.3 implementation result

The implementation uses strict `NetworkRole` and `PeerRelationship` enums.
All eleven definite EBB inventories in `routing_ebb_testbed.py` declare `EB`;
QZD/FSW inventories remain unclassified rather than inheriting a role from a
hostname or Configerator path. `EndpointSpec.role="dut"` is unchanged, and the
new role is propagated in a separate typed bound mapping so legacy resolution
dictionaries retain their exact shape.

All 37 directly authored current device groups declare external, internal, or
monitor relationship explicitly. Derived UG-backpressure groups retain the
relationship through immutable replacement. Binding keeps one exact legacy
role table for older callers, but policy projection never parses raw role
strings, topology names, or `legacy_profile`.

The common catalog contains the complete twelve-key EB semantic matrix:
three relationships by two AFIs by import/export. The EOS/BGP++ compatibility
binding supports the ten references proven by the current profile: external
and internal v4/v6 plus monitor v6. Monitor v4 fails before established task
rendering because no current topology or Configerator contract proves that
mapping. The normal path still consumes the fetched Configerator artifact; it
does not patch BGP++ policy content.

The full EBB+BGP-MON candidate plan contains ten selected semantic presets,
1,274 present adjacencies, and 2,548 directional bindings. Declared
advertisement policies remain separate. EOS peer-group, route-map, and profile
literals live only in the compatibility binding, and the candidate adapter
delegates unchanged artifact rendering only after the candidate compiler's
EOS/BGP++ capability preflight accepts every selected preset.

The EB inventory-ASN compatibility rule is also typed and provenance-limited:
only an internal adjacency on an `EB` inventory may treat
`physical_inventory.dut_bgp_as` as fixture identity while the fetched routing
artifact owns the protocol-local ASN. An unclassified inventory or an
explicitly authored local-ASN mismatch still fails validation. The rule does
not inspect a topology profile, role string, ASN-map key, or EOS peer-group
name.

Final local validation passed on 2026-08-07: the full abstraction suite passed
471/471 tests (TestInfra `10977524280131120`), and the factory golden gate passed
2/2 tests (TestInfra `28710447648723841`). Golden regeneration found 294
unchanged configurations, with zero additions, changes, or removals. The
manifest SHA-256 remained
`741b81402258cf9feb3047e0e000441d332308823d20a00e909ef3a53cd282bf`.

### Phase 1.5.4a implementation result

The common planner now produces a complete semantic IXIA graph for every
current parity topology. Ports identify both logical endpoints and physical DUT
and chassis realization. Device groups own child peer windows. Sessions carry
peer CIDRs, typed relationship and capabilities, address prefix/step/start-index
realization, four-byte-AS behavior, timers, and effective graceful-restart
intent. Advertisements retain compact prefix-source and membership geometry,
peer distribution, next-hop intent, scalar attributes, standard and extended
communities, AS paths, and policy communities without materializing scale
lists.

`IxiaBgpSessionIntent` makes traffic-side realization distinct from DUT
peer-group defaults. Common IXIA defaults are 30/10-second timers, an address
step derived from the authored address-plan stride, and backend-effective
graceful restart. Update packing explicitly asks for both IPv4 and IPv6 unicast
capabilities even though its adjacency is IPv6; UG explicitly asks for /127
IXIA address realization. Other IPv6 profiles retain the established /64 IXIA
realization, IPv4 masks derive from bound peer CIDRs, and monitor sessions
derive their five-capability set from typed `PeerRelationship.MONITOR`. These
differences no longer require a profile branch in the renderer.

The planner has no topology-profile or DUT-platform branch. Stable resource
paths are derived only from logical port, device-group, child, session, and
advertisement identity. Legacy device-group, BGP-peer, tag, prefix-pool names,
and device-group indices are produced in a separate optional sidecar. Tests
change EOS to FBOSS and rename both top-level and bounded-child compatibility
identities while proving the semantic `IxiaPlan` remains equal. This confirms
that legacy IXIA names and indices can support custom topology components
without becoming generalized compiler semantics.

The frozen representative shapes are:

- BAG EBB+BGP-MON: 3 ports, 19 groups/sessions, 1,274 peers, 10
  advertisements, and 373,700 distinct routes;
- UG new peer: 2 ports, 7 groups/sessions, 25 peers, and 850 routes;
- UG dynamic peer: 2 ports, 8 groups/sessions, 26 IXIA peers, including the
  intentionally absent baseline DUT adjacency, and 850 routes;
- IPv6 update packing: 2 groups/sessions, 11 peers, and 10,000 routes;
- egress peer scale: 4 groups/sessions, 1,002 peers, and 100,000 routes; and
- bounded ECMP: 8 child groups/sessions, 512 peers, and 30,000 routes.

Setup mode does not change the IXIA plan. Every IXIA resource is reported
exactly once, and malformed port, endpoint, link, adjacency, peer-cardinality,
or route-cardinality references fail during planning. Nonempty traffic-flow
intent now fails explicitly instead of being silently ignored.

Final local validation passed on 2026-08-07: the full abstraction suite passed
481/481 tests (TestInfra `20266198360288304`), and changed-target Pyre found no
errors across 34 owning targets. The complete 16-case EOS
artifact-parity/import gate passed 45/45 tests (TestInfra
`31806672392539190`), and the factory golden gate passed 2/2 tests (TestInfra
`25895697894487685`). Golden regeneration found 294 unchanged configurations,
with zero additions, changes, or removals. The manifest SHA-256 remained
`741b81402258cf9feb3047e0e000441d332308823d20a00e909ef3a53cd282bf`.

### Phase 1.5.4b shadow-renderer boundary result

The candidate pipeline now constructs a typed traffic-generator render request
from the semantic `IxiaPlan`, its optional legacy identity sidecar, and an
endpoint activation policy derived from setup mode. Full activates endpoint
patches, basic port configs, and lifecycle. Skip keeps endpoint and port
realization but suppresses lifecycle. Verify-only suppresses all three without
changing the semantic IXIA graph.

`TrafficGeneratorRenderer` returns a typed result containing exact resource-ID
coverage, basic port and traffic-item configs, endpoint patches limited to
`ixia_ports` and `direct_ixia_connections`, and named lifecycle fragments.
Validation fails closed on missing or extra resources, inactive or incomplete
endpoint patches, incorrect port-config cardinality, nonempty Phase 1.5 traffic
items, duplicate lifecycle slots, and missing or extra formulaic-route
configuration lifecycle.

The renderer is an optional shadow lane. `CandidateTopologyCompiler` completes
EOS capability preflight, delegates established artifact generation, invokes
the renderer, validates the result, and exposes it on
`CandidateCompilation`. It does not merge the result into artifacts, and the
traffic-generator renderer report remains `COMPATIBILITY_DELEGATED`. This gives
native lowering a comparison seam without permitting partial ownership or a
consumer-visible shift.

Final local validation passed on 2026-08-07: the full abstraction suite passed
484/484 tests (TestInfra `21955048220539361`), the focused candidate/import/IXIA
and 16-case EOS parity gate passed 31/31 tests (TestInfra
`23362423104092708`), and changed-target Pyre found no errors across 17 owning
targets. The factory golden gate passed 2/2 tests (TestInfra
`16044073863541622`). Golden regeneration found 294 unchanged configurations,
with zero additions, changes, or removals. The manifest SHA-256 remained
`741b81402258cf9feb3047e0e000441d332308823d20a00e909ef3a53cd282bf`.

### Phase 1.5.4c initial shared IXIA shadow lowering result

The shared renderer now performs real TAAC lowering for the initial IPv6
device-group capability used by UG new-peer and dynamic-peer topologies. It
consumes only the semantic `IxiaPlan`, typed endpoint activation, and optional
legacy presentation sidecars. It does not inspect `BoundTopology`, EOS, FBOSS,
topology/profile names, or role strings.

Capability selection is semantic and fail-closed. The initial slice requires
the exact supported IPv6 session, address, prefix-window, next-hop, and
field-presence contract. Legacy tags, BGP peer names, and indices only supply
presentation identity; changing identity alone cannot select the capability.
Every non-UG case in the 16-case parity matrix is asserted unsupported. Invalid
address progressions, identical local/gateway addresses, duplicate per-port
group indices, sparse prefixes, attributes, peer slicing, and unsupported
session shapes fail before rendering.

Endpoint port presentation is now explicit port-scoped topology input through
`IxiaEndpointPortLabelStyle`. UG selects `CHASSIS_PORT`; current other families
retain `DUT_INTERFACE`. Logical validation requires the typed enum, binding
preserves and audits its provenance, and mixed tag/named device-group identity
cannot implicitly change the label. Endpoint labels and direct connections
also retain independent port-resource provenance, allowing a future family to
use different ordering for the two lists without weakening completeness
validation.

The two frozen UG cases match the established basic-port configs and endpoint
wiring exactly, including the dynamic spare peer. This remains a shadow lane:
the established adapter is still the sole artifact authority, no fragments are
merged, and `RendererLane.TRAFFIC_GENERATOR` remains
`COMPATIBILITY_DELEGATED`.

Final local validation passed on 2026-08-07: the full abstraction suite passed
498/498 tests (TestInfra `12666374140105692`), the focused IXIA/topology gate
passed 162/162 tests (TestInfra `12947849116830946`), and changed-target Pyre
found no errors across 18 owning targets. The factory golden gate passed 2/2
tests (TestInfra `13229324093522662`). Golden regeneration found 294 unchanged
configurations, with zero additions, changes, or removals. The manifest
SHA-256 remained
`741b81402258cf9feb3047e0e000441d332308823d20a00e909ef3a53cd282bf`.

#### IPv6 update-packing shadow extension

The shared renderer now also lowers the compact named-IPv6 capability used by
IPv6 update packing. The capability is selected from the semantic session
shape before compatibility identities are read. It requires one ordered iBGP
singleton followed by one ten-peer eBGP sender, the checked effective session
defaults, `/127` peer geometry, and the checked shared 10,000-prefix `/64`
advertisement. Identity-only changes cannot enable this capability.

This extension preserves the established field-presence contract rather than
reusing UG serialization: named groups replace tags, address masks are omitted,
session capabilities/timers/graceful-restart use their TAAC defaults, the iBGP
group keeps `route_scales=None`, and the eBGP group emits its source step
`0:0:1::` with an explicit empty community list. Endpoint label fragments stay
iBGP then eBGP while independently proven direct-connection fragments remain
eBGP then iBGP.

Both frozen full and skip cases match established basic-port configs and
endpoint wiring exactly. Verify-only is rejected until its established
realization behavior is separately frozen. The remaining 12 parity cases stay
fail-closed, and the established adapter remains the only artifact authority.

Final local validation passed on 2026-08-07: the full abstraction suite passed
505/505 tests (TestInfra `7036874786004605`), the focused renderer gate passed
16/16 tests (TestInfra `34058472206227343`), and changed-target Pyre found no
errors across 15 owning targets. The factory golden gate passed 2/2 tests
(TestInfra `24206848034226053`). Golden regeneration found 294 unchanged
configurations, with zero additions, changes, or removals. The manifest
SHA-256 remained
`741b81402258cf9feb3047e0e000441d332308823d20a00e909ef3a53cd282bf`.

### Phase 1.5.4d authoritative renderer boundary

The semantic plan is sufficient for resource behavior, but exact legacy
serialization and artifact composition remain separate migration risks. The
largest gaps are:

1. The established `ArtifactAdapter` remains the sole artifact authority; DUT
   and traffic-generator results are not yet composed independently.
2. Endpoint label style is modeled, but every delegated family still needs its
   label and independent label/direct-connection ordering frozen before
   authoritative cutover. IPv6 update packing intentionally uses different
   orders for those two endpoint fields.
3. The established EOS wrapper is also named `IxiaPlan` even though it stores
   already-rendered TAAC configs.
4. IXIA endpoint connection fragments are mixed into whole EOS endpoints; an
   authoritative merge needs keyed endpoint-patch composition.
5. Formulaic route mutation is emitted from the EOS setup-phase builder rather
   than lowered from advertisement intent into the named IXIA lifecycle slot.
6. Existing lowering helpers branch on topology profiles and read
   `BoundTopology` directly. Their observable omitted-versus-`None` versus
   empty-list behavior, encoding flavor, and exact tuple order must be frozen
   as compatibility policy during extraction.
7. EOS capability preflight now runs before the established adapter and both
   renderers. It no longer blocks shadow extraction; artifact authority remains
   blocked by the other incomplete lanes above.

Partitioned EBB is outside the current 16-case artifact matrix and remains
delegated until it has direct parity coverage. For every family, shadow output
may be compared, but native and delegated traffic-generator fragments must
never be merged. Flip `RendererLane.TRAFFIC_GENERATOR` to `NATIVE` only when
endpoint patches, port configs, traffic items, and lifecycle are all complete.

#### Deferred egress next-hop realization

Egress peer-scale lowering remains delegated because the semantic
`IxiaNextHopMode.SELF` currently covers two observably different serialization
shapes: an omitted `set_next_hop_type` and an explicit
`SAME_AS_LOCAL_IP`. Runtime implementation and comments allow the omitted case
to select `MANUALLY`, while the explicit value actively selects local-address
realization. Treating this as a presentation-only sidecar would therefore risk
changing behavior rather than merely preserving legacy field presence.

Do not select either shape from a topology/profile/name or legacy IXIA
identity. Before extracting egress lowering, collect runtime evidence for the
unset case and then choose one semantic resolution:

- if unset and explicit local-address realization are behaviorally identical,
  preserve the difference as rendering compatibility;
- if both are self next hops but use different self-address realizations, add
  a typed self-realization field to the next-hop plan; or
- if unset is not guaranteed to mean self, model it as a distinct next-hop
  mode.

Any plan-model change must explicitly preserve the existing UG and
update-packing semantics and pass the zero-shift harness. Until then, egress
remains fail-closed in the shared renderer and authoritative only through the
established adapter.

### Phase 1.5.5 initial EOS host-OS shadow extraction result

The common endpoint plan now carries a normalized `is_dut` classification.
`BoundTopologyPlanner` derives it with the established role-aware predicate,
including the rule that traffic roles cannot become DUTs merely by using
`kind="dut"`. This gives backend renderers one platform-neutral classification
instead of duplicating legacy role/kind interpretation. The field remains
required for manually constructed plans so alternate planners cannot silently
omit the classification.

The new `DutHostOsRenderer` seam owns only host-OS metadata. Its result is
resource-keyed and validates exact normalized-DUT coverage, unique physical
identifiers, and identifier agreement with the common plan. The EOS/BGP++
implementation accepts exactly one normalized EOS DUT with a physical
identifier and emits `ARISTA_FBOSS`. It does not inspect `BoundTopology`, a
topology/profile name, a logical endpoint name, or testconfig helpers.

`CandidateTopologyCompiler` invokes the renderer only after EOS capability
preflight and established artifact generation. The shadow result is validated
and exposed separately; it is never merged into `CompiledTaacArtifacts`, and
the DUT renderer report remains `COMPATIBILITY_DELEGATED`. Exact established
host-OS map equality is frozen across all 16 EOS parity cases. Structural
result validation intentionally does not define backend-specific OS values, so
that parity gate remains mandatory until cutover.

Final local validation passed on 2026-08-07: the focused renderer, candidate,
planner, model, and import-boundary gate passed 46/46 tests (TestInfra
`1125900425307579`); the combined full abstraction and factory-golden gate
passed 516/516 tests (TestInfra `21110623290421101`); and changed-target Pyre
found no errors across 13 owning targets. Golden regeneration found 294
unchanged configurations, with zero additions, changes, or removals. The
manifest SHA-256 remained
`741b81402258cf9feb3047e0e000441d332308823d20a00e909ef3a53cd282bf`.

#### Endpoint-base shadow extension

The EOS backend now also lowers the DUT endpoint base from the same normalized
endpoint plan. It owns exactly the ordered normalized-DUT coverage and the
`Endpoint` fields `name`, `dut`, `ixia_needed`, `mac_address`, and
`exclude_ixia_ports`. The current capability requires exactly one EOS DUT with
a physical identifier, emits `name=<physical identifier>` and `dut=True`, and
requires the three optional non-IXIA fields to retain their unset defaults.
The shared traffic-generator lane remains the sole owner of `ixia_ports` and
`direct_ixia_connections`.

A Thrift-metadata guard partitions every current `Endpoint` field between
those two owners and fails if a future field is silently unowned. Exact base
projection matches all 16 EOS parity cases with no ignored extra endpoint.
Test-only keyed composition of the EOS base and the shared IXIA endpoint patch
matches the complete established endpoint, including list order and
unset-versus-list behavior, for UG new peer, UG dynamic peer, and IPv6 update
packing in full and skip modes. The endpoint-only extension below completes
patch parity for the other 12 cases without changing base ownership.

The endpoint result remains a separate validated shadow after the established
adapter; it is never merged into artifacts and `RendererLane.DUT` remains
`COMPATIBILITY_DELEGATED`. Lifecycle extraction is explicitly deferred. Host
preparation still contains an unmodeled physical interface profile, including
fixed descriptions and `speed 100g-2`; common component plans are empty;
routing configuration lacks the Configerator artifact, router ID, variant, and
restart requirements; interface realization lacks aggregation and
clear-versus-secondary semantics; and OpenR lacks helper/config materialization.
No topology/profile/name-selected constant may substitute for those inputs.

Final local validation passed on 2026-08-07: the focused EOS endpoint, shared
IXIA composition, candidate, complete parity, and import-boundary gate passed
51/51 tests (TestInfra `36028797043214708`); the combined full abstraction and
factory-golden gate passed 520/520 tests (TestInfra `844425448459007`); and
changed-target Pyre found no errors across 13 owning targets. Golden
regeneration found 294 unchanged configurations, with zero additions, changes,
or removals. The manifest SHA-256 remained
`741b81402258cf9feb3047e0e000441d332308823d20a00e909ef3a53cd282bf`.

#### All-16 shared IXIA endpoint extension

IXIA-owned endpoint wiring now has a contract independent of whole-session
capability selection. Its request contains normalized port plans, one typed
peer relationship per port, endpoint activation, and the resolved endpoint
label. Its result owns only exact ordered endpoint and port consumption plus
resource-keyed endpoint patches; it does not claim device-group, session,
advertisement, port-config, traffic-item, or lifecycle completion.

For every activated endpoint, `ixia_ports` preserves normalized port order.
`direct_ixia_connections` independently uses external, internal, then monitor
relationship order while preserving port order within a relationship. Result
validation freezes both observable orders separately and rejects missing,
unexpected, duplicate, or reordered resources. Verify-only deliberately emits
no endpoint patch.

This endpoint-only lane matches the complete established endpoint for all 16
EOS parity cases when composed test-only with the EOS endpoint base. The full
shared IXIA renderer intentionally retains its prior capability-specific
endpoint path and accepted-domain/error ordering: it remains native only for
the four UG and IPv6 update-packing cases. The other 12 cases still delegate
port-config, session, advertisement, and formulaic lifecycle lowering, but no
longer block independent endpoint-wiring progress.

The candidate exposes the endpoint result as a separate validated shadow.
Established artifacts and all renderer reports remain adapter-owned and
`COMPATIBILITY_DELEGATED`. The current endpoint request rejects a physical port
whose groups have multiple peer relationships. All current cases have an
unambiguous relationship; a future mixed-role port requires a typed
port-presentation ordering key rather than a topology/profile/name branch.

Final local validation passed on 2026-08-08: the focused endpoint and full
IXIA renderer gate passed 22/22 tests (TestInfra `12947849116845075`); the
combined full abstraction and factory-golden gate passed 526/526 tests
(TestInfra `13510799070260901`); and changed-target Pyre found no errors across
10 owning targets. Golden regeneration found 294 unchanged configurations,
with zero additions, changes, or removals. The manifest SHA-256 remained
`741b81402258cf9feb3047e0e000441d332308823d20a00e909ef3a53cd282bf`.

#### Resource-keyed TAAC endpoint composition

Endpoint composition now has a task-free cross-lane request and result. It
joins EOS-owned endpoint bases with the traffic-generator endpoint-patch
subset by stable `ResourceId`, emits exact `DutPlan` order, and validates
unique and complete DUT coverage. A DUT may intentionally have no IXIA patch;
traffic-generator resources may never reference an endpoint outside the DUT
plan.

The TAAC-specific composer lives outside the task-free package. It explicitly
copies the five EOS-owned fields and fills only the two IXIA-owned fields. It
rejects ownership collisions even when a base supplies an empty list, checks
the concrete TAAC schema values, creates a new immutable endpoint for every
result, and preserves verify-only `None` semantics rather than materializing
empty IXIA lists. The existing schema-metadata guard continues to fail if a
future endpoint field is silently left unowned.

All 16 frozen EOS cases now exercise fully native endpoint source lanes: the
EOS base renderer, shared IXIA endpoint renderer, and production keyed composer.
The established endpoint is used only as the parity oracle. A synthetic
two-DUT test reverses base-fragment order, patches only the second DUT, and
proves that composition follows plan identity and order rather than input
position.

`CandidateTopologyCompiler` exposes the composed result as a separate shadow
only after both source lanes validate. The established adapter object remains
the returned `CompiledTaacArtifacts`, and all renderer reports remain
`COMPATIBILITY_DELEGATED`; no consumer-visible artifact or lifecycle ownership
changed.

With EOS capability preflight ahead of both renderers, authoritative endpoint
cutover remains deferred until keyed artifact assembly owns collision checks
and shared IXIA port-config, session, advertisement, and lifecycle lowering is
complete. The egress self-next-hop ambiguity, remaining EOS
config/interface/component lifecycle inputs, and multi-DUT orchestration also
remain explicit blockers rather than compatibility fallbacks.

Final local validation passed on 2026-08-08: the focused composer, candidate,
IXIA, EOS parity, and import-boundary gate passed 54/54 tests (TestInfra
`6755399808516615`); the combined full abstraction and factory-golden gate
passed 534/534 tests (TestInfra `10696049303403415`); and changed-target Pyre
found no errors across 11 owning targets. Golden regeneration found 294
unchanged configurations, with zero additions, changes, or removals. The
manifest SHA-256 remained
`741b81402258cf9feb3047e0e000441d332308823d20a00e909ef3a53cd282bf`.

#### EOS/BGP++ capability preflight extraction

EOS/BGP++ capability validation is now a required injected compiler stage. It
runs after common-plan report renderability succeeds and before the established
artifact adapter, endpoint renderers, traffic-generator renderers, or endpoint
composer can run. The compatibility adapter is again only an artifact and
renderer-report adapter; it no longer hides backend validation.

The task-free preflight requires exactly one normalized EOS DUT with a physical
identifier and exactly one routing-config plan targeting that DUT through the
`bgpcpp` driver. For every present adjacency it requires one import and one
export binding, rejects missing, duplicate, absent, or unknown adjacency
coverage, and verifies the selected role-policy preset against binding
direction, adjacency AFI and relationship, and the DUT network role. Every
selected preset must also have a supported EOS peer-group and route-map
binding. All 16 frozen EOS cases satisfy this contract; monitor IPv4 and other
unsupported mappings fail before any artifact or shadow renderer call.

The preflight does not yet claim that the selected Configerator artifact
satisfies every `RoutingConfigPlan.required_features` entry. The plan still
lacks the typed artifact reference, router-ID, experiment variant, and restart
requirements needed for that check. Those remain explicit routing-config
extraction work rather than an inferred compatibility rule.

Established `CompiledTaacArtifacts` identity and the three
`COMPATIBILITY_DELEGATED` renderer reports remain unchanged. The new gate
closes preflight ordering as an authoritative-cutover blocker without moving
artifact ownership.

Final local validation passed on 2026-08-08: the focused capability,
candidate, IXIA, EOS parity, and import-boundary gate passed 55/55 tests
(TestInfra `10414574326720042`); the combined full abstraction and
factory-golden gate passed 541/541 tests (TestInfra `22799473150708757`); and
changed-target Pyre found no errors across 11 owning targets. Golden
regeneration found 294 unchanged configurations, with zero additions, changes,
or removals. The manifest SHA-256 remained
`741b81402258cf9feb3047e0e000441d332308823d20a00e909ef3a53cd282bf`.

#### Shared IXIA BasicPortConfig endpoint-base extraction

The shared IXIA lane now has a task-free, field-scoped port-base contract. Its
request contains only normalized `IxiaPortPlan` values and per-endpoint setup
activation. It cannot inspect legacy IXIA identities, topology/profile names,
BGP sessions, advertisements, policies, or TAAC tasks. Its result consumes
every planned IXIA port by `ResourceId` and emits fragments for active ports in
exact plan order; verify-only activation consumes the plan but emits no
configuration fragment.

`SharedIxiaPortBaseRenderer` lowers each active port to a
`BasicPortConfig` containing only the physical DUT endpoint. `l1_config` and
`device_group_configs` remain unset and unowned. A Thrift-metadata guard freezes
the complete three-field schema partition, so adding a schema field requires an
explicit owner instead of being silently dropped. The all-16 parity harness
projects established configurations down to the endpoint-only base and proves
exact sequence equality, including secondary IXIA, skip, and verify-only cases.

`CandidateTopologyCompiler` exposes these keyed fragments as a separate shadow.
It does not merge them into `CompiledTaacArtifacts`, and the established adapter
and renderer reports remain authoritative and unchanged. Authoritative
`BasicPortConfig` assembly still requires a resource-keyed composer plus native
device-group/session/advertisement lowering. Full equality remains blocked on
the recorded omitted-versus-empty route-scale behavior, peer start-index
encoding, route geometry, baseline communities, `SELF` next-hop realization,
and lifecycle ownership; the endpoint-base slice does not infer any of them.
Opaque payload overlap checks belong at the future composer boundary, and
multi-DUT/interleaved-port coverage is required before expanding beyond the
current single-DUT EOS matrix.

Final local validation passed on 2026-08-08: the split focused candidate, IXIA,
EOS parity, and import-boundary gate passed 54/54 tests (TestInfra
`35747322066529518` and `21110623290437692`); the combined full abstraction and
factory-golden gate passed 546/546 tests (TestInfra `11821949210020761`); and
changed-target Pyre found no errors across 9 owning targets. Golden
regeneration found 294 unchanged configurations, with zero additions, changes,
or removals. The manifest SHA-256 remained
`741b81402258cf9feb3047e0e000441d332308823d20a00e909ef3a53cd282bf`. An
independent harness audit found no must-fix issue.

#### Shared IXIA BasicPortConfig device-group extraction

The four cases already supported by `SharedIxiaRenderer` now have a second,
field-scoped shadow for `BasicPortConfig.device_group_configs`. The renderer
reuses the existing capability selection, validation, and device-group lowering
functions; this slice adds no topology family, route shape, session behavior,
or compatibility fallback.

Each active port produces one fragment keyed by `IxiaPortPlan.resource_id`.
Each device-group value is nested with the exact device-group, BGP-session, and
advertisement resource IDs that produced it. Validation requires exact plan
order and coverage at every level, rejects missing, duplicate, or unexpected
provenance, and references the complete semantic IXIA graph. The twelve
delegated cases continue to fail closed, and identity-only changes cannot select
a semantic capability.

`BasicPortConfig.endpoint` remains owned by `SharedIxiaPortBaseRenderer`;
`l1_config` remains explicitly deferred. The Thrift-metadata guard now freezes
all three owners separately. `CandidateTopologyCompiler` exposes the
device-group result only as an optional shadow after established adaptation,
so returned artifacts and all delegated renderer reports remain unchanged.

Resource-keyed `BasicPortConfig` composition is intentionally the next boundary
rather than part of this extraction. It can combine the endpoint base and body
for the four native cases without mapping by tuple position or endpoint string.
The remaining twelve bodies still require their recorded route/session semantic
gaps to close before they can participate.

Validation passed the focused import, candidate, IXIA, and EOS parity gate
(56/56, TestInfra `20266198360321249`) and the complete abstraction suite
(549/549, TestInfra `21110623290439650`). Changed-target Pyre checked seven
targets without errors. Golden regeneration reported all 294 configs unchanged,
with manifest SHA-256
`741b81402258cf9feb3047e0e000441d332308823d20a00e909ef3a53cd282bf`. An
independent harness audit found no must-fix issue.

#### Keyed IXIA device-group provenance

The device-group shadow no longer associates device-group configs with resource
IDs through parallel tuples. Each port contains keyed per-group children with
one device-group ID, one BGP-session ID, that group's ordered advertisement IDs,
and its opaque rendered config. Port and group output order still comes only
from `IxiaPlan`, while maps keyed by `ResourceId` perform association.

The result now calls its complete-graph coverage `referenced_resource_ids`
rather than claiming those resources as artifact ownership. Endpoint ownership
stays with the port-base lane, device-group field ownership stays with this
lane, and `l1_config` remains deferred. This removes positional and flattened
advertisement provenance before the next `BasicPortConfig` composition slice;
it does not remove the upstream compatibility sidecar that currently supplies
legacy presentation names and indices.

Validation passed the focused import, candidate, IXIA, and EOS parity gate
(63/63, TestInfra `5910974891543779`) and the complete abstraction suite
(553/553, TestInfra `28991922625450767`). Changed-target Pyre checked six
targets without errors. Golden regeneration reported all 294 configs unchanged,
with manifest SHA-256
`741b81402258cf9feb3047e0e000441d332308823d20a00e909ef3a53cd282bf`. The
independent audit's mutation-sensitivity findings were closed before commit.

#### Resource-keyed TAAC BasicPortConfig composition

`BasicPortConfig` composition now has a task-free request and result that do
not carry the legacy IXIA identity sidecar. The request combines the semantic
IXIA plan, endpoint activation, validated port-base fragments, and validated
device-group fragments. Port bases and bodies are associated through port
`ResourceId`; nested device-group configs are associated through device-group
`ResourceId` and materialized in semantic plan order. Endpoint strings and
tuple positions are never join keys.

The TAAC-specific composer is an explicit schema adapter outside the task-free
package. It requires a base containing only `endpoint`, rejects any existing
`l1_config` or `device_group_configs` value even when the latter is empty,
requires TAAC device-group bodies, and emits a fresh `BasicPortConfig` with
exact per-group session and advertisement provenance. Result validation
rejects missing, unexpected, duplicate, or reordered port keys and any drift
in DUT endpoint, physical endpoint, device-group order, session ownership, or
advertisement boundaries.

The four native UG and IPv6 update-packing cases match both the full shared
renderer and established artifacts exactly. Candidate compilation exposes the
composed values only as a shadow after both source lanes validate. The adapter's
original `CompiledTaacArtifacts` object remains authoritative, and the DUT,
traffic-generator, and artifact-adapter reports all remain
`COMPATIBILITY_DELEGATED`.

This boundary does not complete IXIA generalization. `l1_config` remains
deferred; the twelve delegated device-group bodies retain their recorded
route/session semantic gaps; and upstream native body lowering still uses the
optional compatibility sidecar for presentation names and indices. Custom IXIA
topology components can eventually provide those presentation attributes, but
they are not composition semantics and cannot select capabilities.

Validation passed the focused import, candidate, composer, IXIA, and EOS parity
gate (73/73, TestInfra `21392098267160622`) and the complete abstraction suite
(564/564, TestInfra `22799473150717648`). Changed-target Pyre checked seven
targets without errors. The factory golden gate passed 2/2 (TestInfra
`31243722439157375`), and golden regeneration reported all 294 configs
unchanged, with manifest SHA-256
`741b81402258cf9feb3047e0e000441d332308823d20a00e909ef3a53cd282bf`. Two
independent audits found no remaining architecture or mutation-sensitivity
issue.

#### Typed self next-hop realization

`SELF` next-hop intent now has an optional behavioral realization rather than
using legacy identity or route shape to select IXIA serialization. The initial
explicit value means that the advertising BGP session's local address must be
used. The task-free IXIA plan carries the normalized value, and it is legal
only with `IxiaNextHopMode.SELF`.

Bounded ECMP declares this requirement for its six eBGP child advertisements,
matching the established `SAME_AS_LOCAL_IP` behavior in both frozen full and
skip cases. Existing UG and IPv6 update-packing advertisements intentionally
retain no explicit realization. Their native renderer paths now reject a
nonempty value rather than silently preserving the old omitted field. Egress
and EBB remain deferred until their desired behavior is represented and proven
independently; the planner does not infer realization from topology/profile
name, OpenR mode, route geometry, or legacy IXIA identity.

Legacy device-group, peer, prefix, and index values remain optional custom
topology presentation attributes projected into the resource-keyed identity
sidecar. They can preserve serialized names and indices, but cannot select
next-hop behavior, capability, allocation, ordering, ownership, or lifecycle.

Validation passed the focused topology, model, planner, and renderer gate
(81/81, TestInfra `12103424186717476`) and the complete abstraction suite
(568/568, TestInfra `3659175079964137`). Changed-target Pyre checked nineteen
targets without errors. The factory golden gate passed 2/2 (TestInfra
`7036874786034830`), and golden regeneration reported all 294 configs
unchanged, with manifest SHA-256
`741b81402258cf9feb3047e0e000441d332308823d20a00e909ef3a53cd282bf`.

#### Partitioned dual-stack IXIA device-group lowering

The field-scoped shared renderer now lowers the partitioned dual-stack
capability used by bounded ECMP. Capability selection and validation consume
only normalized ports, device groups, BGP sessions, advertisements, endpoint
activation, and typed next-hop realization. They do not inspect the topology
name, `legacy_profile`, EOS, OpenR mode, or a compatibility helper.

The capability requires one external and one internal active port, IPv4 and
IPv6 groups per relationship, contiguous per-AFI child windows, one checked
session per group, and ordered advertisements for every external child. It
preserves the established address encoding, BGP field-presence defaults,
graceful-restart distinction, standard communities, shared prefix allocation,
and explicit advertising-session local next hop. Both frozen inventories
therefore lower eight child groups, 512 peers, six advertisements, and 30,000
routes without materializing route-sized collections.

Legacy group, peer, prefix, and index values do not participate in capability
selection and remain resource-keyed presentation data. Presentation validation
requires complete names and unique per-port indices, but semantic plan order
remains authoritative; tests reverse the indices and replace every name while
preserving successful lowering and the requested serialized values. The
sidecar cannot change peer partitions, capability, route geometry, next-hop
behavior, ordering, ownership, or lifecycle. Removing it entirely by deriving
stable default names and per-port indices from resource IDs and plan order is
the next Phase 1.6 input-generalization step; explicit values then remain an
override.

The candidate pipeline composes the new bodies with shared port bases by
`ResourceId`, but the established adapter's original artifacts remain the
consumer result. Both bounded full and skip cases match established
`BasicPortConfig` values and frozen digests exactly. The whole IXIA renderer
continues to reject this capability because endpoint, `l1_config`, traffic
items, and lifecycle authority are intentionally outside this slice. All
renderer reports remain `COMPATIBILITY_DELEGATED`.

Mutation tests fail closed on next-hop realization, prefix-source geometry,
route-attribute rows, session timers, non-leading addresses,
graceful-restart behavior, and child peer windows. Final validation passed the
focused renderer target (42/42) and the complete abstraction suite (573/573,
TestInfra `3940650056643110`). Changed-target Pyre checked eleven targets
without errors. The factory golden gate passed 2/2 (TestInfra
`18014398700788396`), and regeneration left all 294 configurations and the
manifest SHA-256 unchanged at
`741b81402258cf9feb3047e0e000441d332308823d20a00e909ef3a53cd282bf`.
Independent architecture and mutation-sensitivity re-audits found no remaining
blocker.

### Multi-agent operating model

Reuse the original DICE Phase 0/1 execution discipline, not its now-stale
legacy delegation architecture:

- one orchestrator owns the shared checkout, checklist, diff stack, integration,
  rebases, submissions, golden-file policy, and user status;
- at most three workers operate concurrently, and only on disjoint files after
  their upstream API is frozen;
- a persistent gatekeeper independently audits worker output and later monitors
  CI/review signals read-only; it never fixes its own findings;
- workers do not edit shared integration files, mutate the stack, regenerate
  goldens, mark their own work complete, or expand their assigned scope; and
- integration is serialized even when research, tests, or disjoint leaf-file
  implementation run in parallel.

The orchestrator exclusively owns these collision-prone surfaces:

- `abstractions/compiler.py`;
- `abstractions/artifacts.py`;
- the `BoundTopology.compile()` portion of `abstractions/topology/model.py`;
- root and shared `BUCK` files;
- `tests/test_config_golden.py` and its migration-freeze resource;
- `tests/golden_config_manifest.json`, which remains read-only; and
- all source-control and diff metadata.

If a worker discovers a required change in one of those surfaces, it records an
integration request with the exact location and expected behavior. The
orchestrator applies it after checking the other lanes.

### Dependency graph

```text
Wave 0: freeze evidence, case matrix, APIs, ownership, and stop conditions
  |
  v
Diff 1.5.0: parity harness and golden-manifest freeze
  |
  v
Diff 1.5.1: dependency ownership and import/BUCK boundary
  |
  v
Diff 1.5.2: task-free model, lifecycle, report, and renderer protocols
  |
  v
Diff 1.5.3: physical EB role and policy seam                 [stretch]
  |
  v
Diff 1.5.4: shared IXIA lane                                [next phase]
```

Within a diff, workers may prepare disjoint leaves concurrently. Diffs remain
ordered because each one establishes a gate or API required by the next.

### Wave 0: freeze the implementation inputs

Before editing production code, three read-only lanes produce one frozen
execution checklist:

1. **Parity lane:** resolve the exact topology, inventory, setup mode, OpenR
   mode, BGP-MON mode, and IXIA profile behind the documented BAG010 48-task
   contract. Existing notes also describe 53-, 47-, and 35-task variants, so a
   hostname plus task count is not a valid oracle.
2. **Dependency lane:** enumerate every production
   `abstractions/** -> testconfigs/**` Python and BUCK edge, classify each
   imported constant by semantic owner, and check the proposed compatibility
   re-export direction for cycles.
3. **Contract lane:** enumerate every rendered `Task` or IXIA config currently
   stored in a plan, then freeze the resource-ID, ownership, dependency,
   readiness, restoration, report, and renderer-protocol contracts needed by
   Diff 1.5.2.

Wave 0 exits only after the orchestrator records:

- the complete parity case IDs and expected setup modes;
- the documented canonicalization rules and any allowed nondeterminism;
- allowed files and owner for each worker lane;
- the ordered diff parents and per-diff test targets; and
- every unresolved design choice in the blocker ledger below.

### Wave 1: Diff 1.5.0, parity harness

One worker owns the harness implementation, one reviews fixture coverage, and
the gatekeeper adversarially tests the comparator. No production compiler file
changes in this diff.

The retired test-only surface was:

```text
abstractions/tests/compiler_parity_harness.py
abstractions/tests/compiler_parity_cases.py
abstractions/tests/test_compiler_parity_harness.py
abstractions/tests/test_eos_compiler_parity.py
abstractions/tests/fixtures/bag010_<resolved-variant>_setup_contract.json
abstractions/tests/fixtures/excluded_config_artifacts.json
tests/compiler_migration_manifest.sha256
```

`CompilerParityHarness` accepts two explicit
`Callable[[BoundTopology], CompiledTaacArtifacts]` values and invokes them on
the same freshly built bound topology. It must not call
`BoundTopology.compile()` for either side, because a later selector cutover
could alias the established and candidate paths. The retained
`EosBgpCppCompiler` remains the authoritative callable; new work is composed
beside it and never refactors the oracle in place.

The harness must:

- introspect and compare all six current `CompiledTaacArtifacts` fields, and
  fail if a future field is not registered;
- preserve every sequence's length and order;
- compare task name, hostname, description, `ixia_needed`, and every parameter;
- compare endpoint/connection identity and every IXIA port, device group, BGP
  session, advertisement, route count, multiplier, community, and AS path;
- parse schema-known nested JSON strings and sort only object keys for
  representation; JSON list order and all values remain exact;
- retain a Thrift-type marker and fail on an unknown value instead of falling
  back to `repr()`;
- compare empty traffic-item output explicitly; and
- report the first mismatch by case, artifact field, lifecycle, structured
  path, resource/task identity, and task index, with bounded nearby context.

Mutation self-tests must prove detection of insertion, deletion, reorder,
hostname/name/parameter/`ixia_needed` drift, endpoint and host-OS drift, IXIA
session and attribute drift, peer/prefix scale drift, and traffic-item drift.
An object-key-only JSON reorder must pass; a list reorder must fail.

The initial real-case matrix includes:

- the resolved BAG010 48-task full-setup contract;
- full EBB with standalone OpenR and BGP-MON on BAG010, BAG011, BAG012, and
  BAG013, plus BAG010's secondary-IXIA projection;
- EBB no-OpenR `full`, `skip`, and `verify_only` setup modes;
- UG new-peer-join on BAG012 and add-peer-dynamic on BAG013;
- IPv6 update packing on BAG012 in full and skip modes;
- egress peer scale on BAG010 and BAG012;
- bounded ECMP on BAG013 in full mode and its existing skip-mode case; and
- artifact projections for every TestConfig excluded by
  `NONDETERMINISTIC_CONFIGS`.

The five excluded TestConfigs remain outside the existing golden manifest.
Four contain known randomized playbook churn, which is outside compiler
artifacts and must not become a compiler normalizer. BAG010 Stage 1's exclusion
has no current proven source; Wave 0 must reproduce the differing path or mark
the exclusion as stale. It is not permission to ignore a field.

Add a temporary byte-level freeze of `golden_config_manifest.json` to the
land-blocking golden test. The generated-vs-checked comparison still runs; the
freeze separately prevents an automatic `--update` from hiding migration
drift. A non-writing `--check` mode is preferred for migration CI. Any future
intentional TestConfig change updates the manifest and freeze in a separate,
explicitly reviewed semantic diff.

Wave 1 exits when the self-tests, complete real-case matrix, independent audit,
golden test, and no-diff regeneration check pass with the established compiler
still authoritative.

### Wave 2: Diff 1.5.1, dependency ownership

Use three disjoint worker lanes:

1. **Topology-data lane:** move topology shapes, scale, prefix definitions, and
   exclusions out of `bgp_ebb_constants.py`; owns the five topology modules and
   `topologies/BUCK`, never `compiler.py`.
2. **EOS/compatibility-data lane:** classify daemon order, commands, paths,
   logging, ACLs, and platform spellings under the EOS/BGP++ backend; sends any
   required `compiler.py` edit to the orchestrator.
3. **Boundary-test lane:** add an AST/import and BUCK-layer gate for the three
   forbidden edges without editing production modules.

Parent networks and physical-link values move to physical inventory or binding
input. EB semantic policy data and EOS peer-group/route-map spellings are kept
separate. Legacy factories may temporarily import compatibility re-exports,
but the safe direction is:

```text
testconfigs compatibility module -> abstraction-owned value
```

The reverse edge is never retained under a new name. Remove the compiler's
concrete egress-scale topology import; exact legacy-shape validation stays in a
compatibility adapter or is derived from bound resources.

The boundary test must use an explicit packaged source inventory or a build
layering rule. A recursive filesystem scan that can silently omit BUCK-packaged
files is not an acceptable gate.

Wave 2 exits when all production Python and BUCK reverse edges are gone, each
forbidden-edge self-test fails as expected, compiler artifacts have zero drift,
and the golden manifest is unchanged.

### Wave 3: Diff 1.5.2, task-free contracts

Freeze `ResourceId` and the shared enums first, then use three disjoint lanes:

1. **Model/report/capability lane:** endpoint, link, interface, adjacency,
   policy, routing-config, component, IXIA, and OpenR desired-resource plans;
   ownership/restoration metadata; and `CompileReport`.
2. **Lifecycle lane:** dependency validation, stable scheduling, reverse
   teardown, first-snapshot reuse, and deterministic partial-cleanup ordering.
3. **Protocol/composition lane:** `DutBackend`, traffic-generator renderer, and
   an explicit candidate callable behind the unchanged public facade.

The new package owns pure contracts. It cannot import TAAC task definitions,
platform commands, concrete topology modules, or testconfig helpers. Keep the
current taskful `EosBgpCppDevicePlan` as compatibility code rather than
mutating it into the new IR in this diff.

The candidate remains test-only. Until shared IXIA and EOS renderers exist, an
explicit compatibility adapter may delegate final rendering to the retained
implementation, but the report must make that debt visible. Do not claim that
the new task-free resources are authoritative merely because the adapter
returns parity output. Candidate FBOSS analysis may report unsupported; do not
change the production FBOSS behavior as an incidental EOS migration.

Required tests cover duplicate IDs, missing dependencies, cycles, deterministic
tie-break order, exact reverse teardown over changed/owned resources, borrowed
resource handling, first-snapshot reuse, unsupported required intent, explicit
no-op reasons, and complete emitted/borrowed/skipped/unsupported accounting.

Wave 3 exits when common plans contain no rendered tasks/configs, the candidate
is reachable only through the harness, the public facade and all established
artifacts remain unchanged, and lifecycle/capability/parity/golden gates pass.

### Wave 4: Diff 1.5.3, physical EB role and policy seam

This is stretch work and remains the top, independently droppable diff. Do not
start it until the three required diffs are locally green and independently
audited.

Use separate physical-binding and policy-binding lanes:

- add an explicit network role to `PhysicalInventory` and resolved endpoint
  metadata, mark the BAG inventories `EB`, and retain
  `EndpointSpec.role="dut"`;
- normalize peer relationship during binding rather than parsing raw role
  strings in new policy code;
- add platform-neutral EB presets keyed by local role, relationship, AFI, and
  direction; and
- map those presets to the existing EOS/BGP++ Configerator peer-group and
  route-map references.

This diff performs selection and parity only. It does not compile arbitrary
`BgpPolicy`, rewrite the fetched BGP++ config, or require a new Configerator
contract. Gate it with the external/internal/monitor by IPv4/IPv6 by
import/export matrix and exact existing peer-group/route-map values.

### Worker handoff and completion rules

Every worker returns the same evidence packet:

- task and diff ID, parent, allowed files, and explicit non-goals;
- changed files and behavior summary;
- architectural invariants checked;
- exact lint, type, build, and test commands with outcomes;
- established/candidate case matrix and the first mismatch, if any;
- golden test, manifest-freeze, and no-diff regeneration status;
- whether any generated TAAC output changed;
- risks, unresolved decisions, and next dependency; and
- checklist items the worker believes are ready.

Only the orchestrator marks an item complete after the independent audit. A
worker with a finding cannot self-approve its fix.

### Per-diff validation and automation

Every required diff must pass, in order:

1. focused unit and compiler tests for its changed surface;
2. the complete established/candidate artifact matrix;
3. the factory-level golden test;
4. the manifest byte-freeze and non-writing regeneration check;
5. `arc lint -a` for changed Python/BUCK files, clean `arc lint`, and owning
   target type checks for new typed Python;
6. independent architecture and test-sensitivity audit; and
7. stack-wide CI/review monitoring after draft submission.

Once explicitly activated, the orchestrator uses the stack-wide CI patrol
because failures in a lower dependency can surface on every descendant diff.
It attributes and fixes local failures in the owning diff, validates before
resubmission, and keeps unrelated infrastructure or parent failures separate.
No CI process is started while this plan remains in the waiting state.

No lab-device E2E run is required for these structural diffs. A setup-only
canary may be requested separately after an eventual EOS facade cutover; it is
not a substitute for artifact parity.

Stop and request a decision if any diff requires:

- an intentional established-artifact or TestConfig semantic change;
- a golden-manifest update;
- weakening or broadening a canonicalization rule;
- changing the public factory or `CompiledTaacArtifacts` API;
- a new Configerator peer/policy contract;
- pulling Diff 1.5.4 or later capability work into the weekend stack; or
- accepting a repeated design-level correctness finding.

Ordinary scoped lint, type, test, build, and locally attributable CI failures
are fixed within the owning diff without expanding scope.

### Initial blocker ledger

| ID | Status | Affects | Blocker and unblock condition |
|---|---|---|---|
| `W0-01` | Open | 1.5.0 | The BAG010 “48-task” variant is ambiguous. Freeze the full topology/inventory/setup/OpenR/BGP-MON/IXIA tuple and review its complete task fixture. |
| `W0-02` | Open | 1.5.0 | BAG010 Stage 1 is excluded from goldens without a currently proven nondeterministic path. Reproduce across fresh imports/hash seeds or treat the exclusion as stale; add no ignore rule. |
| `W0-03` | Mitigation selected | 1.5.0 | The golden pre-commit updater can hide drift. Add the temporary manifest SHA freeze and non-writing check before migration edits. |
| `W1-01` | Open | 1.5.1 | Compatibility re-exports and new BUCK ownership may form cycles. Confirm the one-way testconfig-to-abstraction direction before moving constants. |
| `W1-02` | Open | 1.5.1 | Parent networks mix topology and inventory concerns. Choose physical-inventory input or a binding-owned compatibility module without changing factory output. |
| `W1-03` | Open | 1.5.1 | The import gate needs a complete packaged-source inventory. Select explicit AST inputs or a build-layering rule; do not rely on a best-effort filesystem walk. |
| `W2-01` | Open | 1.5.2 | Freeze resource-ID namespace/tie-breaks, borrowed teardown, snapshot reuse, readiness representation, and cleanup-error aggregation before parallel coding. |
| `W2-02` | Open | 1.5.2 | `CompileReport` cannot change flat artifacts. Choose an internal `CompilationResult` stripped by the adapter or a separate inspection API. |
| `W3-01` | Resolved | 1.5.3 | Use a strict enum. Mark all eleven definite inventories in `routing_ebb_testbed.py`; do not infer roles for QZD/FSW inventories. |
| `W3-02` | Known limit | 1.5.3 | Configerator lacks a complete peer/policy capability contract. Bind existing references only and leave peer materialization as explicit compatibility debt. |
| `W3-03` | Deferred | 1.5.3 | EOS monitor-v4 has no current topology or profile-contract evidence. Keep semantic intent representable but fail EOS capability resolution until the Configerator owner confirms a mapping. |

Traffic items, generalized OpenR/helper semantics, FBOSS emission, and Phase
1.6/1.7 capabilities are recorded deferrals, not blockers for the weekend
exit.

### Weekend exit and handoff

The required weekend goal is complete when Diffs 1.5.0-1.5.2 are reviewable,
locally green, independently audited, and have zero artifact and golden drift.
Diff 1.5.3 is included only if it independently meets the same standard.

The final handoff records:

- the exact stack and parent order;
- harness invocation and complete case matrix;
- frozen package/API and dependency-boundary map;
- lifecycle/resource invariants and test inventory;
- whether the stretch diff is complete or cleanly absent;
- remaining name/profile and peer-materialization compatibility debt;
- all open blockers with evidence; and
- Diff 1.5.4 shared IXIA planning as the next ready work item, only after the
  required stack is green.

## EOS compiler sequence exit criteria

The single-DUT EOS compiler is generalized when:

- a new supported topology requires only topology and inventory declarations;
- renaming it does not change compiled semantics;
- every requested resource is emitted, explicitly borrowed/skipped, or rejected;
- role-policy behavior comes from device and adjacency roles;
- setup and teardown derive from one task-free lifecycle plan;
- IXIA lowering is independent of the EOS backend and ready for reuse;
- partial failure and repeated cleanup are deterministic; and
- no compatibility branch, reverse helper dependency, or legacy IXIA identity
  remains on the generalized path.

FBOSS capability and parity are a separate follow-on using these common
contracts; they are not exit requirements for Phases 1.5-1.9.
