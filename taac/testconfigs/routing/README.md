# Routing TestConfigs

The central routing TAAC guide is
[README.md](../../../../routing_qualification/docs/taac/README.md).
The planning-to-submission sequence is in
[WORKFLOW.md](../../../../routing_qualification/docs/taac/WORKFLOW.md), and
topology/inventory planning is in
[TESTBEDS.md](../../../../routing_qualification/docs/taac/TESTBEDS.md).
Normative TestConfig policy is in
[TESTCONFIGS.md](../../../../routing_qualification/docs/taac/TESTCONFIGS.md),
and catalog maintenance is in
[CATALOGS.md](../../../../routing_qualification/docs/taac/CATALOGS.md).

`factories/` composes topology/capability envelopes. Files named `cicd_*.py`,
`qual_*.py`, and `adhoc_*.py` are lifecycle binding modules that export
TestConfig constants; they are not catalogs. Routing catalogs live in
`../../../../routing_qualification/catalogs/taac/`.

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
catalog through `../../../../routing_qualification/catalogs/registry.py`,
re-evaluate Requirement Coverage and all remaining gaps, update the YAML in the
same diff, regenerate Markdown, and validate it.
