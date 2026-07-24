# TAAC routing testconfigs — coding guide

**Scope**: `fbcode/neteng/test_infra/dne/taac/testconfigs/routing/`.

**Applies to**: every new testconfig, physical_inventory, and factory added under this directory going forward. Existing files that predate this guide are legacy — they migrate gradually per the routing migration plan; new work follows this guide from day one.

**Purpose**: establish a durable framework so any engineer (human or AI) writing a new testconfig knows exactly where each piece goes, what naming to use, and what patterns to avoid. Cloning a testconfig to a new physical_inventory should be a one-line change; adding a new workflow should require exactly one factory function and one catalog binding.

---

## 1. The three-layer model

```
┌────────────────────────────────────────────────────────┐
│  physical_inventory.py + role_defaults.py                         │
│  PhysicalInventory identity — DUT hostname, IXIA + role config   │  ← physical + baseline binding
├────────────────────────────────────────────────────────┤
│  factories/*.py                                        │
│  Workflow logic — parameterized by physical_inventory             │  ← "what a test does"
├────────────────────────────────────────────────────────┤
│  cicd_*.py / qual_*.py / adhoc_*.py                    │  ← "which physical_inventory × which workflow"
│  Catalog files — TestConfig bindings                   │
└────────────────────────────────────────────────────────┘
```

**The invariant**: every `TestConfig` constant is defined as `create_<workflow>_test_config(<PHYSICAL_INVENTORY>, ...)`. Nothing else.

- PhysicalInventory knows the DUT + IXIA + baseline config (via role helpers).
- Factory knows the workflow. Factory reads standard role keys from the physical_inventory; it does NOT know or branch on DUT role.
- Catalog composes them into named testconfigs.

---

## 2. PhysicalInventory (`physical_inventory.py`)

### What it is

The **DUT baseline** — everything about the device + IXIA wiring + baseline BGP/FBOSS/OpenR config that is INVARIANT across the testcases you run on this DUT. Per-testcase deltas do NOT belong here; they go in factory kwargs.

### Where it lives

Single file: `testconfigs/routing/physical_inventory.py`. All PhysicalInventory instances live here.

### The shape (generalized — fits EBB, DC/FBOSS, FA verify, feature physical inventories)

```python
from dataclasses import dataclass, field
from typing import Any

@dataclass(frozen=True)
class PhysicalInventory:
    """DUT baseline for a routing test. Fits all usecases (EBB, DC/FBOSS, FA verify, feature)."""

    # ─── Physical identity (always required) ──────────────────────────────
    device_name: str
    primary_ixia_chassis_ip: str
    ixia_ports: list[tuple[str, str]] = field(default_factory=list)   # (dut_iface, chassis_port), role-agnostic
    secondary_ixia_chassis_ip: str | None = None

    # ─── DUT identity properties (optional, flat) ─────────────────────────
    mac_address: str | None = None
    speed: str = "100g-2"
    router_id: str | None = None
    dut_bgp_as: int | None = None                     # DUT's own local BGP AS

    # ─── Configerator paths for full-config deployment ────────────────────
    bgpcpp_configerator_path: str | None = None
    openr_configerator_path: str | None = None
    fboss_agent_configerator_path: str | None = None

    # ─── Lab auth ─────────────────────────────────────────────────────────
    lab_device_password_env_var: str | None = None

    # ─── Named parameter maps — BGP topology (factory looks up by role key)
    peer_groups: dict[str, str] = field(default_factory=dict)          # e.g., "ibgp_v6" → "EB-EB-V6"
    as_numbers: dict[str, int] = field(default_factory=dict)            # e.g., "uplink" → 65000
    route_maps: dict[str, str] = field(default_factory=dict)            # e.g., "uplink_ingress" → "PROPAGATE_FSW_SSW_IN"
    communities: dict[str, list[str]] = field(default_factory=dict)     # e.g., "uplink" → ["65441:196", ...]
    parent_networks: dict[str, str] = field(default_factory=dict)       # e.g., "ibgp_v6_plane1" → "2401:db00:e50d:11:9"

    # ─── Named parameter map — FBOSS baseline attributes ──────────────────
    # These describe DUT-baseline knobs that patchers push at setup time.
    # Per-testcase toggles (e.g., "flip DLB off then on again") stay as factory kwargs.
    fboss_attributes: dict[str, Any] = field(default_factory=dict)     # e.g., "enable_dlb" → True

    # ─── Escape hatch ─────────────────────────────────────────────────────
    extras: dict[str, Any] = field(default_factory=dict)               # freeform, use sparingly
```

### Design principles

- **Physical identity fields stay flat + typed** (`device_name`, `primary_ixia_chassis_ip`, `secondary_ixia_chassis_ip`, `ixia_ports`, `mac_address`, `speed`, `router_id`, `dut_bgp_as`, configerator paths, lab auth). Every physical_inventory sets what applies.
- **Anything that varies by physical-inventory family** (BGP peer-group names, uplink/downlink AS, route maps, communities, IXIA subnet prefixes, FBOSS runtime knobs) goes into named dicts keyed by role. Each physical_inventory instance populates the roles it exposes.
- **PhysicalInventory answers "what is TRUE about this DUT for any testcase"** — NOT "what does testcase X need". Per-testcase deltas are factory kwargs.
- **Factories declare the roles they need** via dict lookups (`physical_inventory.peer_groups["uplink_v6"]`). A missing key → clear `KeyError` at setup — the factory was called with a physical_inventory that doesn't support it.

### Port map — role-agnostic

`ixia_ports` is a `list[tuple[str, str]]` where each entry is `(dut_iface, chassis_port)`. **The physical_inventory does NOT assign roles** (eBGP / iBGP / BGP-MON / uplink / downlink). Role assignment lives in the factory (see §3), via `*_port_idx` kwargs.

Rationale: one DUT can be used across different testcases where the same physical port carries different BGP roles.

### Naming PhysicalInventory instances

`UPPER_SNAKE_CASE` with datacenter suffix. Format: `{DUT_ROLE}{NUM}_{DATACENTER}`.

Examples: `BAG002_SNC1`, `BAG010_ASH6`, `BAG013_ASH6`, `EB03_LAB_ASH6`, `FA001_UU001_QZD`, `JSW002_SNC1`, `FSW001_QZB`, `GTSW001_L1001_ASH6`.

### DUT roles and role-defaults helpers

FBOSS DUTs come in several roles (XSW, SSW, FSW, RSW, FAUU, FADU). Each role has its own peer-group naming convention, route-map naming convention, and community intent. All instances of the same role share these values.

**Convention**: factor per-role config into helper functions in a sibling file **`role_defaults.py`** next to `physical_inventory.py`. PhysicalInventory instances call the helpers to populate their dicts.

```
testconfigs/routing/
├── physical_inventory.py           ← PhysicalInventory instances
└── role_defaults.py     ← per-role helper functions (peer_groups, route_maps, communities)
```

Example `role_defaults.py`:

```python
"""Per-role DUT-config helpers.

PhysicalInventory instances in physical_inventory.py call these to populate their peer_groups,
route_maps, and communities dicts. Factory code does NOT branch on role —
it just reads standard role keys (uplink_v6, downlink_v6, uplink_ingress,
etc.) from the PhysicalInventory dicts.
"""

# ─── EBB (Emerald Bay Bridge) role ───────────────────────────────────────
def ebb_peer_groups() -> dict[str, str]:
    return {
        "ibgp_v6": "EB-EB-V6", "ebgp_v6": "EB-FA-V6",
        "ibgp_v4": "EB-EB-V4", "ebgp_v4": "EB-FA-V4",
    }

# ─── FSW (Fabric Switch) role ────────────────────────────────────────────
def fsw_peer_groups() -> dict[str, str]:
    return {
        "uplink_v6":   "PEERGROUP_FSW_SSW_V6", "uplink_v4":   "PEERGROUP_FSW_SSW_V4",
        "downlink_v6": "PEERGROUP_FSW_RSW_V6", "downlink_v4": "PEERGROUP_FSW_RSW_V4",
    }

def fsw_route_maps() -> dict[str, str]:
    return {
        "uplink_ingress":   "PROPAGATE_FSW_SSW_IN",
        "uplink_egress":    "PROPAGATE_FSW_SSW_OUT",
        "downlink_ingress": "PROPAGATE_FSW_RSW_IN",
        "downlink_egress":  "PROPAGATE_FSW_RSW_OUT",
    }

def fsw_communities() -> dict[str, list[str]]:
    return {
        "uplink":   ["65441:196", "65441:9001", "65441:9002", "65441:9003", "65441:9004", "65441:9005"],
        "downlink": ["65441:194", "65441:9001", "65441:9002", "65441:9003", "65441:9004", "65441:9005"],
    }

# ─── SSW (Spine Switch) role ─────────────────────────────────────────────
def ssw_peer_groups() -> dict[str, str]:
    return {
        "uplink_v6":   "PEERGROUP_SSW_CTSW_V6", "uplink_v4":   "PEERGROUP_SSW_CTSW_V4",
        "downlink_v6": "PEERGROUP_SSW_FSW_V6",  "downlink_v4": "PEERGROUP_SSW_FSW_V4",
    }

def ssw_route_maps() -> dict[str, str]:
    return {
        "uplink_ingress":   "PROPAGATE_SSW_CTSW_IN",
        "uplink_egress":    "PROPAGATE_SSW_CTSW_OUT",
        "downlink_ingress": "PROPAGATE_SSW_FSW_IN",
        "downlink_egress":  "PROPAGATE_SSW_FSW_OUT",
    }

def ssw_communities() -> dict[str, list[str]]:
    return {"uplink": [...], "downlink": [...]}

# ─── RSW (Rack Switch) role ──────────────────────────────────────────────
def rsw_peer_groups() -> dict[str, str]:
    return {
        "uplink_v6":   "PEERGROUP_RSW_FSW_V6", "uplink_v4":   "PEERGROUP_RSW_FSW_V4",
        "downlink_v6": "PEERGROUP_RSW_SERVER_V6", ...,
    }

def rsw_route_maps() -> dict[str, str]:
    return {...}

def rsw_communities() -> dict[str, list[str]]:
    return {...}

# ─── XSW / FAUU / FADU roles — same pattern ──────────────────────────────
def xsw_peer_groups() -> dict[str, str]: return {...}
def faup_peer_groups() -> dict[str, str]: return {...}   # FA uplink unit
def fadu_peer_groups() -> dict[str, str]: return {...}   # FA downlink unit
# ... route_maps + communities siblings per role
```

**Per-role vs per-instance split**:

| Field | Scope | Where it's set |
|---|---|---|
| `peer_groups` | Per-role (all FSWs use same peer-group names) | `<role>_peer_groups()` helper in `role_defaults.py` |
| `route_maps` | Per-role (naming convention is role-driven) | `<role>_route_maps()` helper |
| `communities` | Per-role (community intent is role-scoped) | `<role>_communities()` helper |
| `as_numbers` | **Per-instance** (fsw003 might peer with different AS than fsw004) | Inline on PhysicalInventory instance |
| `parent_networks` | **Per-instance** (IXIA subnets depend on physical wiring per DUT) | Inline on PhysicalInventory instance |
| `ixia_ports` | **Per-instance** (port map per DUT) | Inline on PhysicalInventory instance |
| `mac_address`, `device_name`, `primary_ixia_chassis_ip`, `secondary_ixia_chassis_ip` | **Per-instance** | Inline on PhysicalInventory instance |
| `fboss_attributes` | Mostly per-instance (DUT-specific baseline knobs) | Inline on PhysicalInventory instance |

Rule of thumb: **naming conventions dictated by DUT role → per-role helper**. **Physical wiring / instance identity → inline on PhysicalInventory instance.**

### Role-key naming rule — semantic, not DUT-specific

PhysicalInventory dict keys (`peer_groups`, `route_maps`, `communities`, `parent_networks`, `as_numbers`) MUST use semantic role names that any candidate DUT for a factory can supply. This is what makes a test portable across DUT roles.

**Good role keys** (portable):
- `uplink_v6` / `downlink_v6` / `uplink_v4` / `downlink_v4` — generic hierarchy direction (FSW, SSW, RSW all have "up" and "down")
- `ingress` / `egress` — traffic direction from the test's perspective
- `ibgp_v6` / `ebgp_v6` — BGP session type (EBB / peer-mesh physical inventories)

**Bad role keys** (leak DUT identity):
- ❌ `fsw_ssw_v6` — only makes sense on FSW; breaks when moved to SSW
- ❌ `ctsw_facing_v6` — only makes sense on SSW; FSW doesn't face CTSW
- ❌ `ebb_ibgp_v6` — only makes sense on EBB DUTs; breaks on DC-fabric DUTs

If the factory uses `peer_groups["uplink_v6"]`, both FSW and SSW just supply their respective `uplink_v6` value. The test is portable — swap `FSW003_QZD` for `SSW004_S002_QZD` in the catalog binding and the test runs on SSW.

If the factory uses `peer_groups["fsw_ssw_v6"]`, it's coupled to FSW-family DUTs forever.

### Adding a new physical_inventory

Append an instance to `physical_inventory.py`. Populate flat identity fields; populate the named dicts with role keys your factories will look up. Leave anything that doesn't apply empty/None.

Define one canonical `Testbed` artifact per physical DUT. Chassis-specific
variants belong in the artifact's primary/secondary chassis fields, not in
additional objects such as `BAG012_ASH6_IXIA11`.

```python
# --- Shared constants at top of physical_inventory.py ---
_EBB_BGPCPP_PATH = "taac/ebb_ci_cd_configs/ebb_full_scale_bgpcpp_config"
IXIA03_ASH6 = "2401:db00:2066:3036::3003"
IXIA11_ASH6 = "2401:db00:2066:303b::3001"

# --- EBB physical_inventory ---
BAG013_ASH6 = PhysicalInventory(
    device_name="bag013.ash6",
    primary_ixia_chassis_ip=IXIA11_ASH6,
    secondary_ixia_chassis_ip=IXIA03_ASH6,
    ixia_ports=[
        ("Ethernet3/36/1", "8/5"),
        ("Ethernet3/36/2", "8/6"),
        ("Ethernet3/36/3", "8/7"),
    ],
    dut_bgp_as=65013,
    bgpcpp_configerator_path=_EBB_BGPCPP_PATH,
    openr_configerator_path="taac/ebb_ci_cd_configs/bag013_ash6_openr_config",
    peer_groups=ebb_peer_groups(),
)

BAG012_ASH6 = PhysicalInventory(
    device_name="bag012.ash6",
    primary_ixia_chassis_ip=IXIA11_ASH6,
    secondary_ixia_chassis_ip=IXIA03_ASH6,
    ixia_ports=[
        ("Ethernet3/36/1", "8/1"),
        ("Ethernet3/36/2", "8/2"),
        ("Ethernet3/36/3", "8/3"),
    ],
    dut_bgp_as=65012,
    router_id="10.163.28.11",
    bgpcpp_configerator_path=_EBB_BGPCPP_PATH,
    peer_groups=ebb_peer_groups(),
)

# --- DC/FBOSS physical_inventory (FSW role) ---
FSW003_QZD = PhysicalInventory(
    device_name="fsw003.p003.f01.qzd1",
    primary_ixia_chassis_ip="2401:db00:0116:303b::",
    ixia_ports=[
        ("eth7/16/1", "6/1"),   # position 0 (default uplink for DC factories)
        ("eth8/16/1", "6/2"),   # position 1 (default downlink)
    ],
    mac_address="b6:a9:fc:34:2b:41",
    # ─── Role-scoped config (from role_defaults.py helpers) ───────────
    peer_groups=fsw_peer_groups(),
    route_maps=fsw_route_maps(),
    communities=fsw_communities(),
    # ─── Per-instance config (varies per DUT even within FSW role) ────
    as_numbers={
        "uplink":   65000,
        "downlink": 2000,
    },
    parent_networks={
        "uplink_v6":   "2401:db00:e50d:11:9",
        "uplink_v4":   "10.164.29",
        "downlink_v6": "2401:db00:e50d:11:8",
        "downlink_v4": "10.163.28",
    },
    extras={
        "is_uplink_peer_confed":   False,
        "is_downlink_peer_confed": True,
    },
)

# --- DC/FBOSS physical_inventory (SSW role) — same factory portable to this DUT ---
SSW004_S002_QZD = PhysicalInventory(
    device_name="ssw004.s002.f01.qzd1",
    primary_ixia_chassis_ip="...",
    ixia_ports=[("<uplink_iface>", "<chassis_port>"), ("<downlink_iface>", "<chassis_port>")],
    mac_address="...",
    peer_groups=ssw_peer_groups(),        # ← different values, same role keys
    route_maps=ssw_route_maps(),
    communities=ssw_communities(),
    as_numbers={"uplink": <ctsw_as>, "downlink": <fsw_as>},
    parent_networks={"uplink_v6": "...", "downlink_v6": "...", ...},
)

# --- DC/FBOSS physical_inventory with baseline FBOSS attributes (patcher-applied at setup) ---
GTSW001_L1001_ASH6 = PhysicalInventory(
    device_name="gtsw001.l1001.c085.ash6",
    primary_ixia_chassis_ip="2401:db00:2066:31fb::3019",
    ixia_ports=[
        # ~28 IXIA ports across ixia19 + ixia20
        ...
    ],
    fboss_agent_configerator_path="fboss/agent/th6/icepack_agent_config",
    peer_groups=gtsw_peer_groups(),      # (assuming GTSW is its own role)
    route_maps=gtsw_route_maps(),
    communities=gtsw_communities(),
    fboss_attributes={
        # DUT baseline — patchers push these at setup so every testcase starts from a known state.
        "enable_dlb":                True,
        "ecmp_group_limit":          1024,
        "ecmp_member_limit":         11500,
        "spine_modules":             (3, 4, 7, 8, 11, 12, 15, 16, 19, 20, 23, 24, 27, 28, 31, 32,
                                       35, 36, 39, 40, 43, 44, 47, 48, 51, 52, 55, 56, 59, 60, 63, 64),
        "default_drain_state":       "undrained",
    },
)
```

Shared constants (paths, chassis IPs shared across multiple physical inventories) go at the top of `physical_inventory.py` as private module constants (`_UPPER_SNAKE_CASE`).

### Interface peer policies — same config, different mechanism per platform

Interface peer policy (peer-group names, route maps, communities, subnet prefixes, AS numbers) is a **shared concept across EOS and FBOSS**. Both platforms have peer groups called `PEERGROUP_FSW_SSW_V6`, both apply route maps like `PROPAGATE_FSW_SSW_IN`, both use community lists to tag routes. The PhysicalInventory describes **what the DUT is configured with**, NOT how the config gets there.

**The deployment mechanism differs by platform** (this is a factory concern, not a PhysicalInventory concern):

| Platform | Mechanism | PhysicalInventory field that points at it |
|---|---|---|
| **EOS / Arista** | Configerator (declarative config, deployed at setup) | `bgpcpp_configerator_path`, `openr_configerator_path` |
| **FBOSS** | Patchers (runtime API, invoked by setup tasks) | `fboss_agent_configerator_path` (baseline); factory setup tasks push patcher updates |

Consequence: the same PhysicalInventory fields (`peer_groups`, `route_maps`, `communities`, `parent_networks`, `as_numbers`) are populated **the same way** whether the DUT is EOS or FBOSS. The FBOSS-vs-EOS distinction shows up only in:
- Which configerator-path field is set (EOS uses `bgpcpp_configerator_path`; FBOSS uses `fboss_agent_configerator_path` — some physical inventories may have both if they run both).
- What kind of setup tasks the factory chooses (configerator deploy for EOS; patcher push for FBOSS).

**Anti-pattern**: don't duplicate `eos_peer_groups` and `fboss_peer_groups` in the PhysicalInventory. There's one `peer_groups` dict — it describes the peer-group names on the DUT, regardless of platform.

### What goes in `fboss_attributes` vs `peer_groups`/other dicts vs factory kwargs

- **`peer_groups` / `route_maps` / `communities` / `parent_networks` / `as_numbers`** — DUT's baseline interface + BGP policy config. Device-agnostic (EOS or FBOSS both have these).
- **`fboss_attributes`** — FBOSS-specific runtime knobs that do NOT correspond to interface peer policy: DLB enable/disable, ECMP group/member limits, spine-module lists for TAAC framework use, drain-state defaults, feature flags. Patcher-configured on FBOSS; not applicable on EOS.
- **Factory kwargs** — per-testcase deltas from the baseline. Examples: `override_ecmp_limit=64`, `drain_before_stage=True`, `enable_dlb_at_iteration=[True, False, True]`.

Rule of thumb: if a knob varies **per testcase** → factory kwarg. If it's true **for every testcase on this DUT** → the appropriate PhysicalInventory dict (`peer_groups`, `fboss_attributes`, etc.). If it's part of the DUT's **interface peer policy** → `peer_groups` / `route_maps` / `communities` / `parent_networks` / `as_numbers` (regardless of platform).

### Recommended: `_require()` helper for dict lookups

Bare `physical_inventory.peer_groups["uplink_v6"]` raises `KeyError` at runtime if the key is missing. Wrap in a helper for clearer errors:

```python
def _require(physical_inventory: PhysicalInventory, category: str, key: str):
    """Look up a role key from a PhysicalInventory named-map; raise clear error if missing."""
    d = getattr(physical_inventory, category)
    if key not in d:
        raise ValueError(
            f"PhysicalInventory {physical_inventory.device_name} does not define {category}[{key!r}]. "
            f"This factory requires it. Add it to the PhysicalInventory instance or use a different physical_inventory."
        )
    return d[key]

# In a factory:
peergroup_uplink_v6 = _require(physical_inventory, "peer_groups", "uplink_v6")
```

Put `_require()` in `physical_inventory.py` (private) or a `physical_inventory_helpers.py`.

---

## 3. Factory (`factories/*.py`)

### What it is

A function that builds a `TestConfig` given a PhysicalInventory + kwargs. All the workflow logic (playbooks, prechecks, postchecks, snapshot checks, setup tasks, teardown tasks) lives here.

### Where it lives

`testconfigs/routing/factories/<domain>.py`. One file per workflow domain:

| File | Contents |
|---|---|
| `bgp_ebb_full_scale.py` | BGPCPP full-scale EBB conveyor workflows (instability, runtime_update, drain, restart, oscillations, stability, longevity, stage1, cold-start, arista/fboss ebb-scale) |
| `bgp_ebb_characteristic.py` | BGPCPP characteristic / measurement workflows on EBB (constant-attribute storage, queue-memory-monitor, performance-scaling, bounded-ECMP-sets, verify_computational_load, verify_constant_attribute_storage) |
| `bgp_update_group.py` | BGP Update Group qualification workflows (backpressure, new_peer_join, initial_dump, sustained_link_flap) |
| `bgp_ebb_scaling.py` | BGPCPP perf-scaling workflows (case1..case9 factories) |
| `bgp_features.py` | BGP feature tests (med, weight, fast_reset, enforce_first_as, well_known_communities, update_packing) |
| `bgp_dc.py` | BGP DC / chronos-node workflows |
| `tcp_socket_experiment.py` | TCP socket data-collection experiments |

### Factory function signature

```python
def create_<domain>_<workflow>_test_config(
    physical_inventory: PhysicalInventory,
    # Role assignment (indexes into physical_inventory.ixia_ports; defaults match typical EBB wiring)
    ebgp_port_idx: int = 0,
    ibgp_port_idx: int = 1,
    bgp_mon_port_idx: int = 2,
    # Workflow kwargs (individual, with defaults from the spec)
    enable_update_group: bool = False,
    prefix_count: int = 10000,
    ...
) -> TestConfig:
    assert physical_inventory.ixia_ports, "factory requires IXIA port map"
    assert physical_inventory.bgpcpp_configerator_path, "factory requires bgpcpp configerator path"

    ebgp_dut_iface, ebgp_chassis_port = physical_inventory.ixia_ports[ebgp_port_idx]
    ibgp_dut_iface, ibgp_chassis_port = physical_inventory.ixia_ports[ibgp_port_idx]
    # bgp_mon optional — only unpack if the physical_inventory has a third port
    ...

    return TestConfig(
        name=f"{physical_inventory.device_name}_<workflow>_TEST_CONFIG",
        endpoints=[...],
        playbooks=[...],
        ...
    )
```

### Rules for factory functions

- **First arg**: `physical_inventory: PhysicalInventory`.
- **Role assignment**: `*_port_idx` kwargs with sensible defaults (0/1/2). The factory owns which port carries which role. Callers can override for oddly-wired physical inventories.
- **Workflow kwargs**: individual kwargs. Do NOT bundle into a spec-params dataclass argument.
- **Spec constants** (e.g. `_2_3_1_PREFIX_COUNT = 10000`, `_STORM_PREFIX_POOL_REGEX = "..."`): module-level defaults inside the factory file. Factory reads them. Add kwargs incrementally when a caller needs to tune a specific one.
- **Runtime asserts** on required PhysicalInventory fields. PhysicalInventory fields are Optional; a factory that needs `bgpcpp_configerator_path` must assert it's not None.
- **Return** a fully-wired `TestConfig`: name, endpoints, playbooks, prechecks/postchecks/snapshot checks, setup/teardown tasks.
- **Internal helpers stay private** (e.g., `_pb_2_3_1()`, `_snapshot_helper()`). One public factory function per workflow. Sub-playbook helpers do NOT leak.

### Factory function naming

Format: `create_<domain>_<workflow>_test_config`.

- Always `create_` prefix.
- Always `_test_config` suffix.
- `<domain>` matches the file's name minus prefix. In `bgp_update_group.py`: `create_bgp_ug_backpressure_test_config`, `create_bgp_ug_new_peer_join_test_config`.
- **Never encode DUT identity in the factory name.** Factory is DUT-agnostic. `create_bag010_ash6_instability_test_config` is WRONG. Correct: `create_ebb_instability_test_config(physical_inventory=BAG010_ASH6)`.

### Adding a new workflow

1. Pick the right `factories/<domain>.py` file (or create one if the workflow is genuinely new).
2. Add a `def create_<domain>_<workflow>_test_config(physical_inventory, ...)` function.
3. Update `factories/__init__.py` if a new file was created.
4. Update BUCK.

---

## 4. Catalog (`cicd_*.py` / `qual_*.py` / `adhoc_*.py`)

### What it is

A file that binds factory functions + PhysicalInventory instances into named `TestConfig` constants. Every constant is a one-line factory call.

### Strict three-way prefix taxonomy

Every catalog file MUST have one of these prefixes. No exceptions, no no-prefix files.

| Prefix | Meaning | Lifecycle position |
|---|---|---|
| `cicd_*` | Actively scheduled on a CICD conveyor | Qualification finished + adopted |
| `qual_*` | Active qualification (spec being qualified now) | In-flight |
| `adhoc_*` | Not in CICD, not in active qual (shelved, historical, experimental, one-off) | Qualification finished + not adopted, OR never entered qual |

### Lifecycle transitions

```
New testconfig starts in:
    ├── qual_*   if it's being qualified now
    └── adhoc_*  if it's experimental / one-off / research

When qualification finishes:
    ├── adopted by CICD  →  rename qual_*  →  cicd_*
    └── not adopted      →  rename qual_*  →  adhoc_*

Rare reverse transitions (allowed for requalification):
    cicd_*   →  qual_*
    adhoc_*  →  qual_*
```

### Filename format — group by PROJECT, not by category

`{prefix}_<project>.py` where `<project>` is a specific initiative (qualification effort, CICD program, feature-area cluster), NOT a generic category like "features", "scaling", "characteristic", or "vendor".

Examples of correct project-based naming:

| File | Project it represents |
|---|---|
| `cicd_ebb_int_tc.py` | EBB integration testing on the CICD conveyor |
| `qual_bgp_update_group.py` | BGP Update Group qualification (specs 2.1.1 / 2.3.x / 2.4.x / 2.7.2) |
| `qual_bgp_ebb.py` | BGP++ on EBB qualification (full-scale + perf-scaling + characteristic combined) |
| `adhoc_bgp_features.py` | BGP feature-test wrappers (grouped as small feature-test cluster) |
| `adhoc_bgp_verification.py` | BGP++ verification tests |
| `adhoc_bgp_fboss_single_node.py` | FBOSS single-node EBB-mimic tests |
| `adhoc_tcp_socket_experiment.py` | TCP socket data-collection experiment |
| `adhoc_cte_ucmp.py` | CTE UCMP feature test |

The `_tc.py` suffix on CICD files is a convention holdover — kept for CICD files, not required for qual/adhoc.

### File shape

```python
"""Active qualification testconfigs for BGP++ Update Group specs.

See factories/bgp_update_group.py for factory definitions.
"""
from .physical_inventory import BAG012_ASH6, BAG013_ASH6, EB03_LAB_ASH6
from .factories.bgp_update_group import (
    create_bgp_ug_backpressure_test_config,
    create_bgp_ug_backpressure_topology_smoke_test_config,
    create_bgp_ug_new_peer_join_test_config,
    create_bgp_ug_initial_dump_identical_routes_test_config,
    create_bgp_ug_sustained_link_flap_test_config,
)

__all__ = [
    "BAG013_ASH6_BGP_UG_BACKPRESSURE_TEST_CONFIG",
    "BAG013_ASH6_BGP_UG_BACKPRESSURE_TOPOLOGY_SMOKE_TEST_CONFIG",
    "BAG013_ASH6_BGP_UG_INITIAL_DUMP_IDENTICAL_ROUTES_TEST_CONFIG",
    "BAG013_ASH6_BGP_UG_SUSTAINED_LINK_FLAP_TEST_CONFIG",
    "BAG012_ASH6_BGP_UG_NEW_PEER_JOIN_TEST_CONFIG",
    "EB03_LAB_ASH6_BGP_UG_INITIAL_DUMP_IDENTICAL_ROUTES_TEST_CONFIG",
]

BAG013_ASH6_BGP_UG_BACKPRESSURE_TEST_CONFIG              = create_bgp_ug_backpressure_test_config(BAG013_ASH6)
BAG013_ASH6_BGP_UG_BACKPRESSURE_TOPOLOGY_SMOKE_TEST_CONFIG = create_bgp_ug_backpressure_topology_smoke_test_config(BAG013_ASH6)
BAG013_ASH6_BGP_UG_INITIAL_DUMP_IDENTICAL_ROUTES_TEST_CONFIG = create_bgp_ug_initial_dump_identical_routes_test_config(BAG013_ASH6)
BAG013_ASH6_BGP_UG_SUSTAINED_LINK_FLAP_TEST_CONFIG        = create_bgp_ug_sustained_link_flap_test_config(BAG013_ASH6)
BAG012_ASH6_BGP_UG_NEW_PEER_JOIN_TEST_CONFIG              = create_bgp_ug_new_peer_join_test_config(BAG012_ASH6)
EB03_LAB_ASH6_BGP_UG_INITIAL_DUMP_IDENTICAL_ROUTES_TEST_CONFIG = create_bgp_ug_initial_dump_identical_routes_test_config(EB03_LAB_ASH6)
```

### Rules for catalog files

- Every binding is a **one-line factory call**. Multi-arg overrides go on their own kwargs.
- **No `TestConfig(...)` literal** in a catalog file — always call a factory (enforced by future `test_no_inline_testconfig_construction.py`).
- Explicit `__all__` — hand-maintained. Small file, stable content, drift is acceptable.
- File-header docstring names the file's taxonomy bucket + cross-refs the factories it consumes.

### Cloning a testconfig to a new physical_inventory = one line

```python
# In cicd_ebb_int_tc.py or the appropriate catalog:
BAG011_ASH6_BGP_UG_BACKPRESSURE_TEST_CONFIG = create_bgp_ug_backpressure_test_config(BAG011_ASH6)
```

That's it. No copy-file, no hand-edit of port maps, no touching factory internals.

---

## 5. TestConfig constant naming

**Format**: `{PHYSICAL_INVENTORY}_{FACTORY}_TEST_CONFIG[_VARIANT]`

Variant suffix goes **after** `_TEST_CONFIG`, not before it. The invariant is that every catalog constant ends in `_TEST_CONFIG` unless it has a variant tag, in which case it ends in `_TEST_CONFIG_<VARIANT>`.

| Segment | Source | Required? |
|---|---|---|
| **PHYSICAL_INVENTORY** | Bare physical_inventory identifier, DC suffix dropped (`BAG010` not `BAG010_ASH6`, `EB02_LAB` not `EB02_LAB_ASH6`). The DC lives on the PhysicalInventory instance in `physical_inventory.py`, not in the catalog constant. | Yes |
| **FACTORY** | Factory function's workflow part, stripped of `create_` prefix and `_test_config` suffix. Also strip generic infra prefixes (`bgp_`, `ebb_`, `bgp_ebb_`) so the constant reads as the workflow, not the factory-file taxonomy. Examples: `create_ebb_drain_test_config` → `DRAIN`; `create_bgp_ug_backpressure_test_config` → `BGP_UG_BACKPRESSURE`; `create_ebb_stage1_consolidated_test_config` → `STAGE1_CONSOLIDATED`. | Yes |
| **Fixed suffix** | Always `_TEST_CONFIG` | Yes |
| **VARIANT** | Optional short tag identifying a variant of the same factory-on-physical_inventory pair. Prefer short forms: `_UG` (update group), `_SMOKE` (topology smoke), `_WITHOUT_OPEN_R`, `_200_IBGP_PEERS`. Multiple variants concatenate: `_UG_SMOKE`. | Only when applied |

### Examples

```
BAG010_STAGE1_CONSOLIDATED_TEST_CONFIG
BAG010_DRAIN_TEST_CONFIG_UG
BAG010_LONGEVITY_TEST_CONFIG
BAG011_STAGE1_CONSOLIDATED_TEST_CONFIG
BAG012_UPDATE_PACKING_TEST_CONFIG_UG
BAG012_CONSTANT_ATTRIBUTE_STORAGE_TEST_CONFIG
BAG012_QUEUE_MEMORY_MONITOR_TEST_CONFIG
BAG012_BOUNDED_ECMP_SETS_TEST_CONFIG_UG
BAG013_BGP_UG_BACKPRESSURE_TEST_CONFIG
BAG013_BGP_UG_BACKPRESSURE_TEST_CONFIG_SMOKE
EB02_LAB_BGP_PERF_SCALING_EGRESS_PEER_SWEEP_TEST_CONFIG_200_IBGP_PEERS
```

### Relationship to PhysicalInventory instance names

PhysicalInventory instances in `physical_inventory.py` **keep** their DC suffix (`BAG010_ASH6`, `EB02_LAB_ASH6`) — that identifies the physical DUT. The catalog CONSTANT drops it because the constant identifies a workflow-on-physical_inventory *binding*, and one workflow per physical_inventory is the norm; the DC is implicit in which PhysicalInventory instance the factory is called with. If a workflow ever exists on two DCs simultaneously (e.g., `BAG010_ASH6` and `BAG010_SNC1` both wired to the same factory), disambiguate at that point by adding the DC as a `_VARIANT` tag (`_ASH6`, `_SNC1`).

### Relationship to `TestConfig.name`

The `.name` field inside the emitted Thrift struct is a separate identifier consumed by the conveyor cconf's `--test-config` flag. Ideally `.name` matches the Python CONSTANT string exactly. In practice, `.name` renames require a synchronized configerator (cconf) update, so `.name` may lag the CONSTANT rename until the cconf catches up. Grandfathered `.name` values stay verbatim; the factory literal remains the source of truth.

### Grandfathering

TestConfig constant names that predate this convention (e.g., `BGP_UG_BACKPRESSURE_TEST_CONFIG` — missing PHYSICAL_INVENTORY prefix; `ARISTA_MIMIC_EBB_TEST_FULL_SCALE_TEST_CONFIG` — no clear PHYSICAL_INVENTORY) keep their current names during hierarchical migration to avoid grep-and-fix churn on external refs (Netcastle, configerator, cross-testconfig imports).

Renaming grandfathered names can happen in a follow-up diff after migration stabilizes.

**New testconfigs added going forward MUST follow the full `{PHYSICAL_INVENTORY}_{FACTORY}_TEST_CONFIG[_VARIANT]` convention.**

---

## 6. File-name prefixes for factory files

| Prefix | When to use |
|---|---|
| `bgp_ebb_*` | BGPCPP tests specifically on EBB topology (e.g., `bgp_ebb_full_scale.py`, `bgp_ebb_characteristic.py`, `bgp_ebb_scaling.py`) |
| `bgp_*` | BGP work not tied to EBB — features, verification, DC, UG when generalizable (e.g., `bgp_features.py`, `bgp_update_group.py`, `bgp_dc.py`) |
| plain `ebb_*` | Reserved for future protocol-agnostic EBB work (e.g., an OpenR+BGP composite workflow on EBB) |
| plain `<domain>.py` | Non-BGP, non-EBB domain-specific work (e.g., `tcp_socket_experiment.py`, `cte_ucmp.py` if extracted from INLINE_LITERAL) |

Do not use `bgpcpp_` — `bgp_` is our convention.

---

## 7. Import contract

External code MUST import from the routing package root:

```python
from taac.testconfigs.routing import BGP_UG_BACKPRESSURE_TEST_CONFIG
```

**Never import from a catalog file directly** (e.g., `from ...testconfigs.routing.qual_bgp_update_group import ...` is forbidden for external consumers).

`testconfigs/routing/__init__.py` is the single re-export point:

```python
# testconfigs/routing/__init__.py
from .cicd_ebb_int_tc import *          # noqa: F401,F403
from .qual_bgp_update_group import *
from .qual_bgp_ebb import *
from .adhoc_bgp_features import *
from .adhoc_bgp_verification import *
from .adhoc_bgp_fboss_single_node import *
from .adhoc_tcp_socket_experiment import *
from .adhoc_cte_ucmp import *
```

Each catalog file's explicit `__all__` makes the `import *` deterministic.

---

## 8. Directory layout (final)

```
testconfigs/routing/
├── __init__.py                        ← single re-export point
├── physical_inventory.py                         ← PhysicalInventory dataclass + all instances
├── role_defaults.py                   ← per-role helpers (peer_groups, route_maps, communities per DUT role)
├── factories/
│   ├── __init__.py
│   ├── bgp_ebb_full_scale.py
│   ├── bgp_ebb_characteristic.py
│   ├── bgp_update_group.py
│   ├── bgp_ebb_scaling.py
│   ├── bgp_features.py
│   ├── bgp_dc.py
│   └── tcp_socket_experiment.py
│
├── cicd_ebb_int_tc.py                 ← ~28 testconfigs (project: EBB integration on CICD)
├── qual_bgp_update_group.py           ← ~6 testconfigs (project: BGP UG qualification)
├── qual_bgp_ebb.py                    ← ~21 testconfigs (project: BGP++ on EBB qualification)
├── adhoc_bgp_features.py              ← ~2 testconfigs (EB02 update_packing + EB03 well_known_community)
├── adhoc_bgp_verification.py          ← ~2 testconfigs (FA001_UU001 verify)
├── adhoc_bgp_fboss_single_node.py     ← ~4 testconfigs (FSW/QZD EBB-mimic on FBOSS)
├── adhoc_tcp_socket_experiment.py     ← ~2 testconfigs (CASE1/CASE2 bag012↔bag013)
└── adhoc_cte_ucmp.py                  ← ~2 testconfigs (CTE UCMP general feature test)
```

20 files total (adds `role_defaults.py`). Cardinality per bucket will drift as testconfigs are added / promoted / shelved.

---

## 9. Adding a new testconfig — the recipe

Decision tree:

**Q1**: Does an existing factory produce the workflow you need?
- **Yes** → skip to Q2.
- **No** → add factory function to appropriate `factories/*.py` (see §3), then Q2.

**Q2**: Does the target PhysicalInventory already exist in `physical_inventory.py`?
- **Yes** → skip to Q3.
- **No** → add a `PhysicalInventory(...)` instance to `physical_inventory.py` (see §2), then Q3.

**Q3**: Which lifecycle bucket does the testconfig belong to?
- Active qualification → `qual_<project>.py`
- CICD-scheduled → `cicd_<project>_tc.py`
- Everything else → `adhoc_<descriptor>.py`

**Q4**: Does a catalog file for the right project already exist?
- **Yes** → add one-line binding + update its `__all__`.
- **No** → create a new catalog file (see §4), then add binding.

**Q5**: New catalog file?
- Update `testconfigs/routing/__init__.py` with `from .X import *`.
- Add BUCK library target.

---

## 10. BUCK

- One `python_library` per file: `physical_inventory.py`, each `factories/*.py`, each catalog file, `__init__.py`.
- Fine-grained deps: catalog library depends only on the factory files it consumes + `physical_inventory.py`.
- Follow existing `neteng/test_infra/dne/taac` BUCK conventions.

---

## 11. Backward compatibility during migration

- **Grep-fix references + delete legacy file in the same diff.** No re-export shims.
- External code referencing a symbol via the old fully-qualified path gets rewritten to the new `testconfigs.routing` root import in the same diff.
- The conveyor aggregation list `EBB_BGP_PLUS_PLUS_CONVEYOR_NODE_TEST_CONFIGS` keeps its current name during migration (rename in a follow-up after stabilization).
- **TestConfig constant names never change during migration** — hierarchical move only, behavior-preserving.
- Golden manifest catches any regression.

---

## 12. Anti-patterns (do NOT do)

1. ❌ Hardcoding DUT hostname, IXIA chassis IP, or port map in a catalog OR factory file. That belongs in `physical_inventory.py`.
2. ❌ Per-DUT factory names like `create_bag010_ash6_instability_test_config`. Parameterize instead: `create_ebb_instability_test_config(physical_inventory=BAG010_ASH6)`.
3. ❌ `TestConfig(...)` literal in a catalog file. Always call a factory.
4. ❌ Direct catalog-file import from external code. Always go through `testconfigs.routing`.
5. ❌ Silent renaming of a TestConfig constant during migration. Rename is a separate, isolated diff.
6. ❌ Deep bucketing. If N testconfigs share a physical_inventory + project, they go in ONE catalog file (e.g., all bag010/011/012/013 CICD → `cicd_ebb_int_tc.py`, not one file per bag).
7. ❌ `enable_update_group` as a PhysicalInventory field. It's a workflow variant, belongs as factory kwarg.
8. ❌ Spec-params dataclass argument to a factory. Use individual kwargs.
9. ❌ `qual_<category>.py` where category is generic ("features", "scaling", "characteristic", "vendor"). Group by project, not category.
10. ❌ Catalog file with no prefix. Every catalog file gets `cicd_`, `qual_`, or `adhoc_`.
11. ❌ TestConfig constant without a PHYSICAL_INVENTORY prefix (for new testconfigs). Reader can't tell which DUT.
12. ❌ TestConfig constant without a `_TEST_CONFIG` suffix. Inconsistent with the pattern.
13. ❌ Embedding scale/variant in the middle of a TestConfig name (e.g., `BAG013_ASH6_1000_PEERS_INSTABILITY_TEST_CONFIG`). Put scale at the END, after factory.
14. ❌ Role-branching in factory code (`if physical_inventory.role == "fsw": ... elif "ssw": ...`). Factory reads standard role keys; physical_inventory supplies them via `role_defaults.py` helpers. Adding a new DUT role must NEVER require factory changes.
15. ❌ Hardcoded role-specific peer-group / route-map / community names in factory code (e.g., `"PEERGROUP_FSW_SSW_V6"`). Always `physical_inventory.peer_groups["uplink_v6"]`.
16. ❌ DUT-specific keys in PhysicalInventory role dicts (e.g., `peer_groups["fsw_ssw_v6"]`, `peer_groups["ebb_ibgp_v6"]`). Keys must be semantic and portable across DUT roles — `uplink_v6`, `downlink_v6`, `ibgp_v6`, `ebgp_v6`, etc.
17. ❌ Duplicating per-role config across PhysicalInventory instances instead of using `role_defaults.py` helpers. If two FSW physical inventories both hand-write `peer_groups={"uplink_v6": "PEERGROUP_FSW_SSW_V6", ...}`, factor into `fsw_peer_groups()`.
18. ❌ Splitting `eos_peer_groups` vs `fboss_peer_groups` on PhysicalInventory. Interface peer policy is device-agnostic — one `peer_groups` dict.

---

## 13. Enforcement (planned — follow-up diff)

- `test_no_inline_testconfig_construction.py` will forbid `TestConfig(...)` literals in catalog files.
- Existing `test_no_inline_healthcheck_construction.py` + `test_no_inline_step_construction.py` continue to apply within factory code.

---

## 14. What lives OUTSIDE this scope

This guide governs `testconfigs/routing/` only. Not covered here:

- **Helper library** at `taac/routing/` (`conveyor_constants`, `conveyor_common_tasks`, `common_health_checks`, `ixia_config_for_ebb_scale`, `arista_feature_testing`, `arista_bgp_plus_plus_performance_scaling_tests`, `cte_ucmp_test_configs`, `dc_routing`). Factories import from these; migration deferred to a later effort.
- **Playbook / step / task / healthcheck factory definitions** (`playbooks/playbook_definitions.py`, `steps/step_definitions.py`, `tasks/`, `health_checks/healthcheck_definitions.py`). Factories import from these; their own conventions apply.
- **Non-routing testconfigs** (`testconfigs/npi/`, `testconfigs/hyperport/`, `testconfigs/fpf/`, `testconfigs/fboss_solution_tests/`, `testconfigs/internal/`, `testconfigs/ai_bb/`, `testconfigs/mtia/`, `testconfigs/bag/`). Each area has its own conventions.

---

## 15. Optional TAAC Abstractions

Routing factories may use TAAC Abstractions when a typed topology model makes a
factory easier to validate and migrate without changing bytes. The abstraction
path is optional; flat factory authoring remains valid.

The intended factory shape is:

```python
logical_topology = EBB_FULL_SCALE_WITH_BGPMON
bound = logical_topology.bind_to_inventory(
    physical_inventory=physical_inventory,
    port_map={"uplink": 0, "ibgp": 1, "bgpmon": 2},
    parent_networks=parent_networks,
    peer_groups=peer_groups,
    as_numbers=as_numbers,
)
compiled = bound.compile()
```

Routing `PhysicalInventory` remains physical inventory: DUT name, ordered IXIA ports,
IXIA chassis, `dut_bgp_as`, configerator paths, and lab defaults. LogicalTopology
intent belongs in topology objects and factory-level dictionaries.

Factories should import topology instances from
`neteng.test_infra.dne.taac.abstractions.topologies.*`. They should not
instantiate concrete compiler classes or choose EOS/FBOSS by selecting a
different topology object.

Phase 1 keeps playbooks factory-owned and does not migrate production factories
or replace setup/teardown helpers. Any future factory migration must prove
old/new JSON parity and keep the golden manifest unchanged unless a rebaseline
is explicitly approved.

---

## Appendix: quick reference

### Adding a testconfig — checklist

- [ ] PhysicalInventory exists in `physical_inventory.py`? If not, add it.
- [ ] Factory exists in `factories/*.py`? If not, add it.
- [ ] Correct lifecycle bucket picked (`cicd_` / `qual_` / `adhoc_`)?
- [ ] Correct project-based filename?
- [ ] One-line factory call in the catalog file?
- [ ] Constant name follows `{PHYSICAL_INVENTORY}_{FACTORY}_{SCALE|VARIANT}_TEST_CONFIG`?
- [ ] Added to catalog's `__all__`?
- [ ] Added to `testconfigs/routing/__init__.py` if new catalog file?
- [ ] BUCK targets updated?
- [ ] No hardcoded DUT/port/chassis values outside `physical_inventory.py`?

### The invariant

Every `TestConfig` = `create_<workflow>_test_config(<PHYSICAL_INVENTORY>, ...)`.
