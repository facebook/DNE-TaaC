# TAAC routing playbooks — coding guide

**Scope**: `fbcode/neteng/test_infra/dne/taac/playbooks/routing/`.

**Applies to**: every playbook factory function that produces a `Playbook` used by a routing testconfig factory. Existing playbook factories in `playbooks/playbook_definitions.py` are legacy — they migrate gradually. New playbook work follows this guide from day one.

**Companion doc**: this guide pairs with the testconfig guide (`../../testconfigs/routing/README.md`). Testconfig factories consume playbook factories; the two layers live in mirrored `routing/` subdirectories.

**Purpose**: establish a durable pattern so every playbook = one test case, every factory has a predictable name, and adding a new playbook requires one function in one domain file.

---

## 1. The one-layer model

Playbooks have no testbed layer (playbooks are DUT-agnostic — the DUT is bound by the consuming testconfig factory) and no catalog layer (playbooks are consumed as function references, not as module-level constants).

**Just factory files**:

```
┌───────────────────────────────────────────────────────┐
│  playbooks/routing/<domain>_playbooks.py              │
│  Playbook factory functions grouped by domain         │  ← "what a test case does"
└───────────────────────────────────────────────────────┘
```

**The invariant**: one function = one playbook = one test case. Every factory function returns exactly one `Playbook`. No `list[Playbook]`, no `dict[str, Playbook]`, no batch builders.

---

## 2. File organization

Flat structure under `playbooks/routing/`, one file per domain. Filenames MUST include `_playbooks.py` suffix.

```
playbooks/routing/
├── __init__.py                    ← single re-export point
├── bgp_ebb_playbooks.py           ← BGPCPP on EBB topology
├── bgp_ug_playbooks.py            ← BGP Update Group qualification
├── bgp_dc_playbooks.py            ← BGPCPP on DC topology (chronos-node)
├── bgp_feature_playbooks.py       ← Topology-agnostic BGP feature tests
├── tcp_socket_playbooks.py        ← TCP socket data-collection experiments
└── cte_ucmp_playbooks.py          ← CTE UCMP feature
```

**Domain choice rules**:
- One file = factories that share a domain/usage.
- File name = `<domain>_playbooks.py`.
- Add a new domain file only when a genuinely new workflow area lands (not for one-off playbooks — those go into an existing domain).

---

## 3. Naming convention

### Factory function name

**Pattern**: `create_{domain}_{feature_or_usecase}_playbook`

- Always `create_` prefix (no `build_`, no `get_`).
- Always singular `_playbook` suffix.
- `{domain}` = matches the enclosing file's domain (e.g., `bgp_ug` in `bgp_ug_playbooks.py`).
- `{feature_or_usecase}` = specific test-case identifier (snake_case).
- No DUT identity in the name — playbook is DUT-agnostic.
- No project prefix (no `qual_`, `cicd_`, `adhoc_`) — playbook is project-agnostic.

### Playbook `name=` field

**Pattern**: `{domain}_{feature_or_usecase}` — matches the factory name minus `create_` and `_playbook`.

Casing: lowercase snake_case. No PascalCase. No spec-number embeddings.

### Concrete examples

```python
# bgp_ug_playbooks.py
create_bgp_ug_backpressure_fast_peers_not_held_back_playbook   →  name="bgp_ug_backpressure_fast_peers_not_held_back"
create_bgp_ug_backpressure_peer_blocks_down_recover_playbook   →  name="bgp_ug_backpressure_peer_blocks_down_recover"
create_bgp_ug_backpressure_withdraw_attr_change_playbook       →  name="bgp_ug_backpressure_withdraw_attr_change"
create_bgp_ug_backpressure_all_peers_block_down_recover_playbook →  name="bgp_ug_backpressure_all_peers_block_down_recover"
create_bgp_ug_backpressure_topology_smoke_playbook             →  name="bgp_ug_backpressure_topology_smoke"
create_bgp_ug_new_peer_join_full_sync_resilience_playbook      →  name="bgp_ug_new_peer_join_full_sync_resilience"
create_bgp_ug_new_peer_join_routes_withdrawn_playbook          →  name="bgp_ug_new_peer_join_routes_withdrawn"
create_bgp_ug_new_peer_join_attribute_change_playbook          →  name="bgp_ug_new_peer_join_attribute_change"
create_bgp_ug_sustained_link_flap_playbook                     →  name="bgp_ug_sustained_link_flap"
create_bgp_ug_initial_dump_identical_routes_playbook           →  name="bgp_ug_initial_dump_identical_routes"

# bgp_ebb_playbooks.py
create_bgp_ebb_instability_attribute_churn_playbook            →  name="bgp_ebb_instability_attribute_churn"
create_bgp_ebb_route_storm_playbook                            →  name="bgp_ebb_route_storm"
create_bgp_ebb_cold_start_playbook                             →  name="bgp_ebb_cold_start"
create_bgp_ebb_daemon_restart_playbook                         →  name="bgp_ebb_daemon_restart"
create_bgp_ebb_longevity_playbook                              →  name="bgp_ebb_longevity"
create_bgp_ebb_scale_playbook                                  →  name="bgp_ebb_scale"
create_bgp_ebb_queue_memory_monitoring_playbook                →  name="bgp_ebb_queue_memory_monitoring"
create_bgp_ebb_verify_computational_load_playbook              →  name="bgp_ebb_verify_computational_load"
create_bgp_ebb_bounded_ecmp_sets_playbook                      →  name="bgp_ebb_bounded_ecmp_sets"
create_bgp_ebb_transient_memory_route_scale_playbook           →  name="bgp_ebb_transient_memory_route_scale"
create_bgp_ebb_egress_peer_sweep_playbook                      →  name="bgp_ebb_egress_peer_sweep"
create_bgp_ebb_update_packing_validation_playbook              →  name="bgp_ebb_update_packing_validation"

# bgp_feature_playbooks.py
create_bgp_feature_med_playbook                                →  name="bgp_feature_med"
create_bgp_feature_weight_playbook                             →  name="bgp_feature_weight"
create_bgp_feature_fast_reset_playbook                         →  name="bgp_feature_fast_reset"
create_bgp_feature_enforce_first_as_playbook                   →  name="bgp_feature_enforce_first_as"
create_bgp_feature_well_known_communities_playbook             →  name="bgp_feature_well_known_communities"

# bgp_dc_playbooks.py (after splitting the 3 list-returning batch builders)
create_bgp_dc_agent_restart_playbook                           →  name="bgp_dc_agent_restart"
create_bgp_dc_bgp_restart_playbook                             →  name="bgp_dc_bgp_restart"
create_bgp_dc_longevity_prefix_flap_playbook                   →  name="bgp_dc_longevity_prefix_flap"
create_bgp_dc_hardening_ndp_overload_playbook                  →  name="bgp_dc_hardening_ndp_overload"
create_bgp_dc_hardening_ecmp_member_overload_playbook          →  name="bgp_dc_hardening_ecmp_member_overload"
# ... etc.

# tcp_socket_playbooks.py (name= collision fixed)
create_tcp_socket_case1_data_collection_playbook               →  name="tcp_socket_case1_data_collection"
create_tcp_socket_case2_data_collection_playbook               →  name="tcp_socket_case2_data_collection"

# cte_ucmp_playbooks.py (after splitting list-returning batch builders)
create_cte_ucmp_baseline_ecmp_playbook                         →  name="cte_ucmp_baseline_ecmp"
create_cte_ucmp_random_weight_iterations_playbook              →  name="cte_ucmp_random_weight_iterations"
create_cte_ucmp_progressive_bringup_dc1_playbook               →  name="cte_ucmp_progressive_bringup_dc1"
create_cte_ucmp_progressive_bringup_dc2_playbook               →  name="cte_ucmp_progressive_bringup_dc2"
create_cte_ucmp_progressive_bringup_dc3_playbook               →  name="cte_ucmp_progressive_bringup_dc3"
create_cte_ucmp_ecmp_to_ucmp_transition_playbook               →  name="cte_ucmp_ecmp_to_ucmp_transition"
create_cte_ucmp_ucmp_to_ecmp_transition_playbook               →  name="cte_ucmp_ucmp_to_ecmp_transition"
create_cte_ucmp_continuous_warmboot_playbook                   →  name="cte_ucmp_continuous_warmboot"
create_cte_ucmp_continuous_coldboot_playbook                   →  name="cte_ucmp_continuous_coldboot"
# ... etc.
```

---

## 4. One factory = one playbook (hard rule)

Every factory returns a single `Playbook`. Enforced patterns:

```python
# CORRECT
def create_bgp_ug_backpressure_fast_peers_not_held_back_playbook(...) -> Playbook:
    return Playbook(
        name="bgp_ug_backpressure_fast_peers_not_held_back",
        ...
    )

# WRONG — returns list
def get_bgp_dc_longevity_playbooks(...) -> list[Playbook]:
    return [Playbook(...), Playbook(...), ...]
```

If a caller needs N playbooks, it calls N single-playbook factories. This makes:
- Each playbook independently importable + testable.
- Factory names encode exact test-case identity (no hidden fan-out).
- Test filtering / selection at the test-runner level is uniform (one factory = one test-config entry = one test case).

Existing list-returning factories (`get_bgp_dc_*`, `create_test_case_N_playbooks`) split during migration. See §9.

---

## 5. Anatomy of a playbook factory

Every playbook factory returns a `Playbook` object with these fields:

```python
def create_bgp_ug_backpressure_fast_peers_not_held_back_playbook(
    *,
    device_name: str,
    ixia_interface: str,
    storm_prefix_pool_regex: str,
    ...
    # workflow kwargs (individual, with sensible defaults from the spec)
) -> Playbook:
    """Build the BGP++ Update Group qualification 2.3.1 playbook.

    Test case: "Fast Peers Not Held Back by Slow Peers".
    Spec reference: UG spec 2.3.1 (documented in <link>).
    """
    return Playbook(
        name="bgp_ug_backpressure_fast_peers_not_held_back",
        stages=[...],                       # ordered list of Stage objects (the test scenario)
        prechecks=[...],                    # PointInTimeHealthCheck bundle before stages
        postchecks=[...],                   # PointInTimeHealthCheck bundle after stages
        snapshot_checks=[...],              # before/after diff checks
        setup_steps=[...],                  # playbook-scoped setup (optional)
        periodic_tasks=[...],               # background tasks running during stages (optional)
    )
```

### Where to import shared building blocks

- **Prechecks / postchecks / snapshot checks**: import from `health_checks/healthcheck_definitions.py` (e.g., `create_bgp_session_establish_check`, `create_cpu_utilization_check`) OR from routing helper bundles (`routing/ebb/ebb_bgp_plus_plus_test_config/common_health_checks.py` — `BGP_STANDARD_PRECHECKS`, `create_standard_prechecks(...)`, etc.).
- **Steps**: import factories from `steps/step_definitions.py`.
- **Stages**: import factories from `stages/stage_definitions.py`.
- **Periodic tasks**: import from `routing/ebb/ebb_bgp_plus_plus_test_config/common_periodic_tasks.py`.
- **Domain-specific helpers**: if a helper is reused across N factories within one domain (e.g., a `_snapshot_ug_peer_state()` helper used by all `bgp_ug_*` playbooks), define it as a module-level private function (`_leading_underscore`) inside the same `<domain>_playbooks.py`. Do NOT create a `<domain>_helpers.py` sibling — keep the domain file self-contained.

### Kwargs contract

- **Keyword-only** for factories with >3 arguments (`def create_X(*, foo, bar, ...)`). Positional args are error-prone at consumer-side.
- **Individual kwargs**, not a spec-params dataclass. Defaults come from the spec.
- **No DUT identity** as a factory arg. The consuming testconfig factory passes concrete values (device_name, ixia_interface) that it derives from its `PhysicalInventory` argument.
- **Return type annotation**: always `-> Playbook`. Never `list[Playbook]`, `Optional[Playbook]`, etc.

---

## 6. Import contract

External consumers (testconfig factories in `testconfigs/routing/factories/*.py`) import playbook factories from the routing package root:

```python
from taac.playbooks.routing import (
    create_bgp_ug_backpressure_fast_peers_not_held_back_playbook,
    create_bgp_ug_new_peer_join_full_sync_resilience_playbook,
)
```

**Never import from a `<domain>_playbooks.py` file directly** — go through `playbooks/routing/__init__.py`, which re-exports everything:

```python
# playbooks/routing/__init__.py
from .bgp_ebb_playbooks import *           # noqa: F401,F403
from .bgp_ug_playbooks import *
from .bgp_dc_playbooks import *
from .bgp_feature_playbooks import *
from .tcp_socket_playbooks import *
from .cte_ucmp_playbooks import *
```

Each `<domain>_playbooks.py` maintains an explicit `__all__` listing every public factory name.

---

## 7. Adding a new playbook — the recipe

**Q1**: Does the playbook belong to an existing domain?
- **Yes** → open the appropriate `<domain>_playbooks.py`, add a factory function, add its name to `__all__`.
- **No** → add a new `<domain>_playbooks.py` file. Update `playbooks/routing/__init__.py` with `from .<domain>_playbooks import *`. Add BUCK library target.

**Q2**: Name the factory `create_{domain}_{feature_or_usecase}_playbook` and the `name=` field `{domain}_{feature_or_usecase}` (matching, minus `create_` and `_playbook`).

**Q3**: Function returns exactly one `Playbook`. Return-type annotation `-> Playbook`. Body constructs and returns a single `Playbook(...)`.

**Q4**: Kwargs contract — keyword-only, individual kwargs with defaults, no DUT identity, no project prefix. Import shared prechecks / stage helpers as needed.

**Q5**: Docstring — first line one-sentence summary. Follow-up lines cite the test-case name + spec reference (if applicable). Spec numbers go in docstrings, never in `name=`.

**Q6**: Consumer testconfig factory imports the new playbook factory from `playbooks.routing` root (never from the domain file directly).

---

## 8. Grandfathering during migration

- **Factory function names** change during migration (`build_bgp_med_playbook` → `create_bgp_feature_med_playbook`). These are internal Python identifiers — grep-fix all consumers in the same diff, delete the old function.
- **Playbook `name=` field values** — GRANDFATHER during migration. Preserve existing `name=` strings byte-for-byte during the hierarchical move, because external systems (Netcastle test-name refs, configerator schedules, test-report parsers, Devmate signal names) index by `name=`. Rename the `name=` values in a **separate follow-up diff** after migration stabilizes.
- **Batch factories** (`get_bgp_dc_*_playbooks`, `create_test_case_N_playbooks`) split into single-playbook factories. This is a semantic change (breaks callers that iterate the returned list) and belongs in **separate diffs**, not the initial hierarchical migration.

---

## 9. Migration policy for existing violators

Current state (from routing playbook audit):
- 60 factories imported by routing testconfigs today.
- 47 use `create_` prefix (target style).
- 10 use `build_` prefix (trampolines that just forward `Playbook(**kwargs)`).
- 3 use `get_` prefix (list-returning batch builders).
- 15 factories return `list[Playbook]` (violate one-factory-one-playbook).

Migration plan:

**Wave 1 — hierarchical move only** (behavior-preserving):
- Move each factory into its `<domain>_playbooks.py` home.
- Rename factory function name to `create_<domain>_<usecase>_playbook`.
- Grep-fix all testconfig-factory consumers in the same diff.
- Keep existing `name=` strings byte-identical.
- Keep list-returning factories as-is (splitting deferred).

**Wave 2 — kill trampolines** (`build_*`):
- Replace each `build_X_playbook(**kwargs)` call with direct `Playbook(**kwargs)` at the testconfig-factory site OR promote to a proper named factory.
- One diff per trampoline family.

**Wave 3 — split list-returning factories**:
- 7 genuine splits (`get_bgp_dc_*_playbooks`, `create_test_case_1/3/4/14_playbooks`) → ~28 new single-playbook factories.
- 8 trivial splits (list-of-1 → drop the wrapper).
- Semantic-change diffs; go per-consumer, verify no regression.

**Wave 4 — rename grandfathered `name=` values**:
- Only after Waves 1-3 stabilize.
- One diff per domain, updates Netcastle/configerator/report-parser references.

---

## 10. Anti-patterns (do NOT do)

1. ❌ DUT identity in factory name (`create_bag010_ash6_bgp_instability_attribute_churn_playbook`) — playbook is DUT-agnostic.
2. ❌ Project prefix in factory name (`create_qual_bgp_ug_*_playbook`, `create_cicd_*_playbook`) — project is a testconfig-level scope.
3. ❌ Multi-playbook factory (`list[Playbook]` return) — split into N single-playbook factories.
4. ❌ Trampoline factory (`def build_X_playbook(name, stages, ...): return Playbook(**kwargs)`) — kill it; either promote to a real named factory or construct `Playbook(...)` at the caller.
5. ❌ `get_` or `build_` prefix — always `create_`.
6. ❌ Plural `_playbooks` suffix on factory name — always singular (matches the one-playbook return).
7. ❌ PascalCase in `name=` field (`Performance_Scaling_...`, `TC12_Warmboot`) — always lowercase snake_case.
8. ❌ Spec-number in `name=` field (`bgp_ug_2_3_1_playbook`) — spec numbers go in docstrings, not runtime names.
9. ❌ Name collisions across factories (both case1 + case2 tcp_socket previously used `name="tcp_socket_data_collection"`) — enforce uniqueness at review time.
10. ❌ `<domain>_helpers.py` sibling file — domain helpers stay private inside `<domain>_playbooks.py` (private `_leading_underscore` functions).
11. ❌ Direct `<domain>_playbooks.py` import from testconfig-factory code — always import from `playbooks.routing` root.
12. ❌ Missing `__all__` in a domain file — the routing `__init__.py` re-export requires deterministic `import *`.
13. ❌ Positional args on factories with >3 kwargs — always keyword-only (`def create_X(*, foo, bar, ...)`).

---

## 11. What lives OUTSIDE this scope

- **Playbooks under `testconfigs/npi/`, `testconfigs/hyperport/`, `testconfigs/fpf/`, etc.** — this guide governs `playbooks/routing/` only.
- **Playbook / step / task / healthcheck primitive definitions** (`playbooks/playbook_definitions.py` legacy home, `steps/step_definitions.py`, `tasks/`, `health_checks/healthcheck_definitions.py`). Playbook factories in `playbooks/routing/` IMPORT from these; they retain their own conventions.
- **The helper library at `routing/ebb/ebb_bgp_plus_plus_test_config/`** (common_health_checks, common_periodic_tasks, ixia_config_for_ebb_scale, conveyor_common_tasks, conveyor_constants). Playbook factories import from these; helper-tree migration is deferred.
- **TAAC Abstractions topology compile output** (`abstractions/`). Phase 1 keeps
  playbooks factory-owned. A topology helper may later build playbook steps only
  after byte-identical output is proven.

---

## 12. Relationship to TAAC Abstractions

TAAC Abstractions can provide routing topology metadata to factories, but they
do not own playbook selection in Phase 1. The factory still decides which
playbooks and stages belong in a `TestConfig`.

Future topology-backed helper methods may generate low-level step arguments
from device-group and prefix-pool metadata. Those helpers must be validated
against existing playbook output before replacing factory-owned step assembly.
Until then, playbook factories should continue to accept explicit arguments and
return ordinary flat TAAC `Playbook` objects.

---

## Appendix: quick reference

### Adding a playbook — checklist

- [ ] Domain identified (existing `<domain>_playbooks.py` or new file)?
- [ ] Factory name follows `create_{domain}_{feature_or_usecase}_playbook`?
- [ ] Playbook `name=` field follows `{domain}_{feature_or_usecase}`?
- [ ] Factory returns exactly one `Playbook` (return type `-> Playbook`)?
- [ ] Kwargs are keyword-only, individual, with defaults?
- [ ] No DUT identity or project prefix in the name?
- [ ] Docstring cites test case + spec reference?
- [ ] Added to `<domain>_playbooks.py::__all__`?
- [ ] Added `from .<domain>_playbooks import *` in `playbooks/routing/__init__.py` (if new domain file)?
- [ ] BUCK targets updated?
- [ ] Testconfig-factory consumer imports from `playbooks.routing` (not from the domain file)?

### The invariants

- One function = one playbook = one test case.
- Playbook is DUT-agnostic and project-agnostic. Physical-inventory binding + project taxonomy live at the testconfig layer.
- File name = `<domain>_playbooks.py`. Factory name = `create_<domain>_<usecase>_playbook`. Playbook `name=` = `<domain>_<usecase>`.
