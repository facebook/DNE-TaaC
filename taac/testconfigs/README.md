# TAAC testconfigs

**Scope**: `fbcode/neteng/test_infra/dne/taac/testconfigs/`.

**Applies to**: TestConfig catalogs, factories, and testbed bindings under this
directory.

**Purpose**: explain where TestConfig authoring rules live and how optional
TAAC Abstractions fit with existing flat authoring.

---

## 1. Directory Ownership

Each domain owns its own authoring guide when it needs domain-specific rules.

Current guides:

- `routing/README.md`: routing testbeds, factories, catalogs, and naming.
- `../playbooks/routing/README.md`: routing playbook factory authoring.
- `../abstractions/README.md`: optional TAAC Abstractions authoring.

Existing flat TAAC authoring remains supported. A factory may continue to build
`TestConfig` fields directly when that is the clearest and safest shape.

---

## 2. Optional Abstractions

TAAC Abstractions are a factory-side helper layer. They compile typed intent
into the same flat `TestConfig` fields used today.

Use an abstraction when it gives a single source of truth for repeated topology
intent, validation, or byte-identical migration work. Do not use an abstraction
as a new runtime or as a reason to change the serialized `TestConfig` shape.

Factories that use topology abstractions should select a topology object, bind
it to a `PhysicalInventory` with `bind_to_inventory()`, and call
`bound.compile()`. Factories should not
instantiate concrete compiler classes.

---

## 3. Golden Rule

Generated `TestConfig` output is part of the API. For behavior-preserving work,
the golden manifest must remain unchanged.

Use the existing golden test:

```text
buck test fbcode//neteng/test_infra/dne/taac/tests:test_config_golden
```

Use the update command as a no-diff check unless a rebaseline is explicitly
approved:

```text
buck run fbcode//neteng/test_infra/dne/taac/tests:config_golden -- --update
```

If the update command changes tracked golden files, the change is not
byte-identical.
