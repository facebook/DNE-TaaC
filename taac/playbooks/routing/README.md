# Routing Playbooks

The central routing TAAC guide is
[README.md](../../../../routing_qualification/docs/taac/README.md).
The end-to-end authoring sequence is in
[WORKFLOW.md](../../../../routing_qualification/docs/taac/WORKFLOW.md), and
reusable component policy is in
[COMPONENTS.md](../../../../routing_qualification/docs/taac/COMPONENTS.md).
Normative Playbook policy is in
[PLAYBOOKS.md](../../../../routing_qualification/docs/taac/PLAYBOOKS.md), and
catalog maintenance is in
[CATALOGS.md](../../../../routing_qualification/docs/taac/CATALOGS.md).

This package contains executable routing Playbooks and Playbook factories only.
Catalog governance lives in
`../../../../routing_qualification/catalogs/taac/`; lifecycle binding modules
live in `../../testconfigs/routing/`.

Routing Playbook unit and composition tests live in `tests/` with their own
BUCK package.

For new suites, prefer one suite-owned module, `get_*` factories, and runtime
names ending in `_playbook`. Update Group qualification's spec-section modules,
`create_*` factories, and established unsuffixed runtime names are legacy
exceptions preserved until a coordinated identity migration.

Consumers import the owning module or subpackage directly. This package's
`__init__.py` force-imports modules for discovery and construction gates; it is
not a package-root symbol export contract.

Before changing a cataloged Playbook, locate every affected catalog through
`../../../../routing_qualification/catalogs/registry.py`, re-evaluate
Requirement Coverage and all remaining gaps, update the YAML in the same diff,
regenerate Markdown, and validate it.
