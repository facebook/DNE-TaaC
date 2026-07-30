# Routing TestConfigs

The central routing TAAC guide is [docs/routing/README.md](../../docs/routing/README.md).
The planning-to-submission sequence is in
[WORKFLOW.md](../../docs/routing/WORKFLOW.md), and topology/inventory planning
is in [TESTBEDS.md](../../docs/routing/TESTBEDS.md).
Normative TestConfig policy is in [TESTCONFIGS.md](../../docs/routing/TESTCONFIGS.md),
and catalog maintenance is in [CATALOGS.md](../../docs/routing/CATALOGS.md).

`factories/` composes topology/capability envelopes. Files named `cicd_*.py`,
`qual_*.py`, and `adhoc_*.py` are lifecycle binding modules that export
TestConfig constants; they are not catalogs. Routing catalogs live in
`../../catalogs/routing/`.

Routing factory, selector, setup, and lifecycle-binding tests live in `tests/`
with their own BUCK package.

`testconfigs/routing/__init__.py` is intentionally side-effect free. Import a
constant from its specific lifecycle module rather than the package root.

Use one TestConfig factory per distinct topology/capability envelope. Update
Group edge cases may use separate factories when Open/R mode, next-hop
resolution, IXIA layout, route pools, AFI, setup/teardown, or feature state
differs. Current `playbooks_selected` behavior is not uniform; see the central
guide before changing selectors.

Before changing a cataloged factory or lifecycle binding, locate every affected
catalog through `../../catalogs/registry.py`, re-evaluate Requirement Coverage
and all remaining gaps, update the YAML in the same diff, regenerate Markdown,
and validate it.
