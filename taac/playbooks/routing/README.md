# TAAC routing playbooks

Scope: `fbcode/neteng/test_infra/dne/taac/playbooks/routing/`.

Routing playbooks own executable test suites and test cases. TestConfigs consume
and arrange playbooks at runtime; they do not own test-case identity or
documentation.

## Ownership model

```text
playbooks/routing/<suite>_playbooks.py
    Owns the suite's executable Playbook factories.

playbooks/routing/<suite>_catalog.yaml
    Owns the suite's test-case documentation and requirement mappings.

testconfigs/routing/
    Owns runtime arrangement: inventory, topology binding, grouping,
    selection, and execution parameters.
```

The catalog maps a test case to `Playbook.name`. It does not map test cases to
TestConfigs. A playbook remains the same test case regardless of which
TestConfig arranges it.

## File organization

Use one playbook module per test suite. The filename is
`<suite>_playbooks.py`, where `<suite>` is also the runtime-name prefix.

```text
playbooks/routing/
├── __init__.py
├── bgp_ebb_playbooks.py
├── bgp_ug_playbooks.py
├── bgp_dc_playbooks.py
├── bgp_feature_playbooks.py
├── tcp_socket_playbooks.py
└── cte_ucmp_playbooks.py
```

Create another module only for a distinct test suite. Do not split one suite
across category files. Use section headings inside a large suite module when
grouping improves navigation.

## Naming contract

Every runtime name is globally meaningful when removed from its source module.
It therefore includes both the suite prefix and the `_playbook` suffix.

```text
Playbook.name = <suite>_<succinct_case>_playbook
factory       = get_<Playbook.name>
```

For BGP EBB:

```python
def get_bgp_ebb_daemon_restart_playbook(...) -> Playbook:
    return Playbook(
        name="bgp_ebb_daemon_restart_playbook",
        ...
    )
```

Required properties:

- Lowercase snake case only.
- The suite prefix matches the owning module.
- The case segment is succinct but identifies the behavior under test.
- The runtime name ends in `_playbook`.
- The factory name is exactly `get_{playbook_name}`.
- Runtime names and factories are unique within the routing package.
- Do not include a DUT, lab hostname, project phase, cadence, or spec number.

Use a human-readable catalog `title` for presentation. Do not weaken runtime
identity to make dashboard text shorter.

## One factory, one test case

Each public factory returns exactly one `Playbook`:

```python
def get_bgp_ebb_route_storm_playbook(
    *,
    device_name: str,
    ixia_interface_mimic_ibgp: str,
    ...
) -> Playbook:
    return Playbook(
        name="bgp_ebb_route_storm_playbook",
        stages=[...],
        prechecks=[...],
        postchecks=[...],
        snapshot_checks=[...],
        periodic_tasks=[...],
    )
```

Do not return `list[Playbook]`, hide multiple cases behind a batch builder, or
use a generic `Playbook(**kwargs)` trampoline. Callers that need multiple cases
call multiple factories.

## Factory interface

- Return type is always `-> Playbook`.
- Use keyword-only parameters when a factory has more than three arguments.
- Accept explicit workflow inputs; do not accept an entire TestConfig or
  PhysicalInventory object.
- Keep the playbook DUT-agnostic. A caller may pass values such as
  `device_name`, interfaces, and expected scale after deriving them from its
  runtime inventory.
- Use centralized step, stage, task, and health-check factories.
- Keep helpers used only by one suite private in the suite module.

## Catalog and docstrings

The suite catalog is the editable source of truth for:

- Stable catalog ID and human title
- Purpose and requirement coverage
- Preconditions, stimulus, and scale
- Blocking criteria
- Expected runtime, cadence, and enforcement
- Triage signals, artifacts, and likely failure domains
- Cleanup behavior and qualification differences

Factory docstrings stay implementation-focused:

```python
def get_bgp_ebb_daemon_restart_playbook(...) -> Playbook:
    """Build CICD-01: BGP daemon restart.

    See `bgp_ebb_catalog.yaml` for the test contract and triage guidance.

    Args:
        ...
    """
```

Do not duplicate the full catalog entry in a docstring. Document parameter
semantics and non-obvious implementation invariants next to the code.

## Validation traceability

Every blocking signal in a catalog entry must map to the playbook-level
health-check chain that currently enforces it. Define reusable precheck,
postcheck, and snapshot phases in `validation_phases`, compose them in
`validation_chains`, and select one chain from each entry's `validation` block.

Coverage has four states:

- `implemented`: the selected health-check chain directly enforces the signal.
- `partial`: health checks enforce only part of the signal; document the gap.
- `missing`: no playbook-level health check enforces the signal.
- `not_applicable`: the signal intentionally does not require a health check;
  document the rationale.

The `spec_vs_implemented` specifications must exactly match the entry's ordered
`blocking_signals`. References in `implemented_by` must be phases in the selected
chain. A trigger completing, a custom step returning success, a stage-local
assertion, or a periodic task is not part of the health-check chain. Record such
behavior under `non_chain_validations`; it remains visible in rendered docs but
cannot upgrade health-check coverage.

Schema version 2 introduces this required traceability contract. The BGP EBB
catalog was the only TAAC playbook catalog using version 1, so it and its
renderer consumer migrate atomically. Version 1 input fails with migration
instructions rather than being interpreted without validation coverage.

## Rendering catalogs

The YAML catalog is the editable source of truth. Keep the generated Markdown
beside it for human review and downstream publishing:

```text
<suite>_catalog.yaml  # edit this
<suite>_catalog.md    # generated; do not edit directly
```

Render any suite catalog with the generic target:

```bash
buck run fbcode//neteng/test_infra/dne/taac/playbooks/routing:render_playbook_catalog -- \
  fbcode/neteng/test_infra/dne/taac/playbooks/routing/<suite>_catalog.yaml \
  fbcode/neteng/test_infra/dne/taac/playbooks/routing/<suite>_catalog.md
```

Use `--check` in tests and automation. It exits nonzero when the Markdown is
missing or stale. Google Docs synchronization consumes the generated Markdown,
not the YAML and not a TestConfig.

## Synchronizing catalogs to Google Docs

`catalog_gdoc_sync.yaml` is the registry for every catalog published to Google
Docs. Add one enabled target with its catalog resource, generated Markdown,
document ID, stable tab ID, and document mode. Use `pageless` for catalog tabs
so wide tables have room to remain readable. The generic command processes all
enabled targets; `--target` narrows a manual run to one suite:

```bash
# Verify that every registered remote tab has the current Markdown fingerprint.
buck run fbcode//neteng/test_infra/dne/taac/playbooks/routing:sync_playbook_catalogs_to_gdocs -- \
  --check

# Preview Google's merge-aware GHTML update without writing.
buck run fbcode//neteng/test_infra/dne/taac/playbooks/routing:sync_playbook_catalogs_to_gdocs -- \
  --target bgp_ebb --dry-run

# Synchronize all enabled catalogs.
buck run fbcode//neteng/test_infra/dne/taac/playbooks/routing:sync_playbook_catalogs_to_gdocs
```

The publisher refuses stale generated Markdown. It fetches only the configured
tab as GHTML, preserves the tab and document metadata, replaces that tab's body,
and atomically replaces that tab through `meta google.docs.advanced replace`.
A configured tab is generated output: the local catalog owns that tab, so do
not edit its published body directly. Every write is read back and fingerprint
verified. Markdown tables become native Google Docs tables. Content in other
tabs is never part of the update.

## Imports and exports

Each suite module maintains an explicit `__all__` containing its public
factories. External consumers import from the routing package root when the
symbol is re-exported there:

```python
from taac.playbooks.routing import (
    get_bgp_ebb_daemon_restart_playbook,
)
```

Direct suite-module imports are acceptable only where the package currently
exposes the suite as a module rather than re-exporting individual symbols. Use
one style consistently within a consumer module.

## Adding a playbook

1. Identify the owning test suite.
2. Add one `get_<suite>_<case>_playbook` factory to its suite module.
3. Set `Playbook.name` to exactly `<suite>_<case>_playbook`.
4. Add the factory to `__all__`.
5. Add one catalog entry keyed by that runtime name.
6. Update consumers that arrange the playbook at runtime.
7. Run naming, catalog, renderer, lint, type, and owning-target tests.

## Migration policy

Runtime names are external identities used by filtering, logs, dashboards,
reporting, and scheduling. Rename them deliberately:

1. Inventory all repository and external consumers.
2. Update the factory and runtime name together.
3. Update controlled consumers in the same change.
4. Coordinate external selectors, temporarily accepting both names if an
   atomic cross-repository rollout is unavailable.
5. Do not retain Python aliases after controlled callers migrate; aliases
   weaken the `factory == get_{playbook_name}` invariant.
6. Update snapshots and verify serialized behavior is otherwise unchanged.

## Anti-patterns

- `create_*` or `build_*` factory names for routing suite playbooks.
- A factory name that cannot be derived from `Playbook.name`.
- Runtime names without the suite prefix or `_playbook` suffix.
- Runtime names containing DUT identities, project phases, or spec numbers.
- Multiple playbooks returned by one public factory.
- Generic trampoline factories.
- Duplicate test-case documentation in TestConfigs or long docstrings.
- TestConfig names or topology bindings used as catalog identity.
- Missing `__all__` entries.
- Direct construction of shared step, stage, task, or health-check primitives
  when a centralized factory exists.

## Review checklist

- [ ] One suite module owns the test case.
- [ ] Factory returns exactly one `Playbook`.
- [ ] Runtime name matches `<suite>_<case>_playbook`.
- [ ] Factory is exactly `get_{playbook_name}`.
- [ ] Case segment is concise and unambiguous.
- [ ] Factory appears in `__all__`.
- [ ] Catalog entry references `playbook_name`, not a TestConfig.
- [ ] Runtime consumers and selectors are updated.
- [ ] Docstring contains only implementation-local guidance.
- [ ] Naming, catalog, rendering, lint, and owning-target tests pass.
