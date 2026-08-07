# Generalized EOS compiler roadmap

Status snapshot: 2026-08-06

## Goal

Compile a new supported, single-DUT EOS/BGP++ topology from logical intent and
physical inventory without:

- changing compiler code;
- assigning a `legacy_profile`;
- supplying `legacy_ixia_*` names or indices; or
- hand-authoring baseline setup and teardown tasks in the factory.

The compiler continues to emit the existing flat TAAC `TestConfig` fragments.
This project does not introduce a topology runtime into the TAAC runner.

## Current position

DICE already has most of the intent and binding foundation:

- typed logical endpoints and device groups;
- address, peer-group, prefix, route-attribute, traffic, and OpenR intent;
- physical inventory binding with normalized provenance;
- EOS/BGP++ interface and peer projections;
- backend selection and a typed device-plan boundary; and
- production migrations proving several concrete topology shapes.

The missing generalization is in lowering and lifecycle management. The EOS
compiler still selects most endpoint, setup, teardown, and IXIA renderers from
exact topology names or `legacy_profile`. Its generic fallback can return empty
artifacts. Policy projection is bookkeeping-only, traffic intent is not
rendered, and teardown is assembled independently for a fixed profile
allowlist.

## Narrow first milestone

The first profile-free compiler supports:

- one EOS DUT and one IXIA endpoint;
- the BGP++ routing driver;
- explicit or already-bound IPv4 and IPv6 interface addressing;
- eBGP and iBGP device groups;
- existing/borrowed peer-group and policy references;
- deterministic IXIA device groups and BGP peers;
- OpenR mode `NONE`;
- generated endpoints, basic port configs, setup, verification, and teardown;
  and
- explicit compile errors for intent outside this capability set.

Traffic items, compiler-owned policy authoring, OpenR `STANDALONE`/`PEER`,
address allocation, multi-DUT orchestration, FBOSS/COOP, and AR/BGP follow after
this milestone.

## Migration shape

Keep the checked production paths stable while adding a profile-free lane:

```text
BoundTopology
  |
  +-- legacy profile --> compatibility planner --> existing rendered output
  |
  +-- no profile ------> capability analysis
                              |
                              v
                       normalized EOS input
                              |
                              v
                       typed resource plan
                              |
                              v
                         TAAC renderer
```

The generic planner must not branch on logical-topology name. Prefer a
normalized EOS compile input that omits `name`, `legacy_profile`, and
`legacy_ixia_*` fields from its decision surface. A source name may be carried
separately for diagnostics.

## Target compiler stages

### 1. Analyze capabilities

Walk the bound intent before rendering and classify every requested feature as:

- supported and required;
- supported and intentionally skipped;
- borrowed from the physical testbed; or
- unsupported.

Return a structured compile report. Any unsupported required feature fails
before task rendering. Empty output is valid only when the report records an
intentional no-op such as `setup_mode="skip"`.

### 2. Plan typed resources

Translate supported intent into a dependency graph of desired resources. The
initial resource set should cover:

- TAAC endpoint and IXIA connection;
- IXIA device group and BGP peer;
- EOS interface address block;
- BGP++ peer-set configuration;
- BGP++ component configuration and daemon state; and
- readiness verification.

Each mutating resource declares:

- stable resource identity;
- dependencies;
- whether it is compiler-owned, borrowed, or snapshot-restored;
- the desired state and verification condition; and
- its cleanup or restoration strategy.

Do not store rendered `Task` objects in the resource plan. Keeping desired
resources separate from rendering preserves the information needed to derive
safe teardown and explain compilation.

### 3. Order the lifecycle

Validate resource identity and dependency uniqueness, reject cycles, and derive:

- setup from dependency order;
- verification after the resources it observes; and
- teardown from reverse dependency order.

Only resources changed or owned by the compiler may be removed. A
snapshot-restored resource must reuse its first pre-mutation snapshot throughout
the plan. Cleanup attempts independent resources even after an earlier cleanup
failure and preserves the primary execution error.

The generated flat task lists remain constrained by TAAC's existing failure and
teardown execution contract. Where the runner cannot guarantee rollback after
partial setup, the renderer must use an atomic/bounded task that performs its
own local rollback or reject that lifecycle shape.

### 4. Render TAAC artifacts

The EOS/BGP++ renderer converts the typed plan into existing task definitions
and `CompiledTaacArtifacts`. Renderer responsibilities include:

- bounded external operations;
- task parameters and backend-specific commands;
- acknowledgement and exact readback where supported; and
- deterministic TAAC and IXIA names derived from logical resource identity.

The renderer does not select behavior from topology names.

## Incremental diff sequence

### Diff 1: Capability report and strict completeness

- Add a structured EOS capability/compile report.
- Define the supported first-milestone feature set.
- Replace silent generic empty success with actionable validation errors.
- Record explicit reasons for borrowed and intentionally skipped resources.
- Update the generic compiler test that currently expects empty setup and IXIA
  output.

If an existing consumer relies on empty generic output, land this in a stack
with the profile-free vertical slice so the stack has no broken intermediate
state.

### Diff 2: Resource-plan primitives

- Add typed resource IDs, ownership/restoration modes, and resource variants.
- Add dependency graph validation and deterministic ordering.
- Add unit tests for duplicate identities, missing dependencies, cycles,
  setup order, and reverse teardown order.
- Keep existing production profile rendering unchanged.

Likely code boundaries are `eos_bgpcpp_capabilities.py`,
`eos_bgpcpp_resources.py`, `eos_bgpcpp_planner.py`, and
`eos_bgpcpp_renderer.py`. `compiler.py` should become orchestration plus a
temporary compatibility adapter rather than acquire more topology branches.

### Diff 3: Profile-free vertical slice

- Generate the TAAC endpoint from bound endpoint and inventory data.
- Generate deterministic IXIA connection and device-group configuration.
- Reuse the existing generic EOS interface and BGP peer projections.
- Plan BGP++ peer configuration, component startup, and readiness.
- Generate teardown from the same resources.
- Add one synthetic dual-stack eBGP+iBGP topology with
  `legacy_profile=None` and no legacy IXIA fields.

The fixture should change topology name in a second test and prove that emitted
semantics do not change.

### Diff 4: Lifecycle hardening

- Attach bounded execution and acknowledgement to external mutations.
- Verify interface, BGP++ configuration, daemon readiness, and IXIA state.
- Test partial setup, repeated teardown, borrowed resources, and restoration
  after a later operation fails.
- Ensure ambiguous IXIA sessions cannot be reused as a trusted baseline.

### Diff 5 and later: Production migrations

- Choose the smallest existing single-DUT profile whose features fit the
  generic capability set.
- Compare normalized resource plans and serialized TestConfig semantics.
- Cut that topology over to the generic planner.
- Delete its topology predicate, argument adapter, and legacy IXIA metadata once
  no consumer remains.
- Repeat by increasing feature complexity, using EBB full scale as a later
  parity and scale case.

Short-lived migration assertions are acceptable. Do not leave an old/new
production oracle after a topology has durable semantic tests and golden
coverage.

## First vertical-slice acceptance test

Construct a topology with:

- logical endpoints `dut0` and `ixia`;
- one IPv6 eBGP group and one IPv4/IPv6 iBGP role on bound IXIA ports;
- explicit parent networks, ASNs, and borrowed peer-group references;
- OpenR `NONE`;
- `legacy_profile=None`; and
- no `legacy_ixia_*` fields.

Compilation must prove:

1. endpoint and direct IXIA connections are present;
2. every device group has an interface, BGP peer, and IXIA projection;
3. setup contains BGP++ configuration, interface mutation, startup, and
   readiness in dependency order;
4. teardown restores only compiler-mutated resources in reverse dependency
   order;
5. the compile report accounts for every requested resource;
6. renaming the topology does not change emitted semantics; and
7. adding unsupported traffic or policy intent fails before rendering.

## Generalized-EOS exit criteria

The narrow compiler is generalized when:

- a new supported topology requires only intent and inventory declarations;
- compiler decisions are independent of topology name and legacy profile;
- every required intent element is emitted, borrowed explicitly, skipped with
  a reason, or rejected;
- setup, verification, and teardown come from the same typed resource graph;
- partial setup and repeated cleanup have deterministic tests;
- external mutations are bounded and verified;
- existing migrated topologies retain semantic and golden equivalence; and
- specialized compatibility branches are deleted as their last consumers
  migrate.

## Follow-on capability order

After the baseline vertical slice, add capabilities in this order:

1. prefix advertisements, next-hop distributions, and supported route
   attributes;
2. compiler-owned peer-group and policy rendering;
3. `TrafficFlowSpec` to IXIA traffic-item lowering;
4. OpenR `STANDALONE`, preserving link ownership and exact cleanup;
5. deterministic role/link binding and optional address allocation;
6. additional EOS routing drivers; and
7. multi-DUT planning and transaction boundaries.

Each capability should extend analysis, resource planning, rendering, and
failure-path tests together.
