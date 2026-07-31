# Routing TestConfig factories

Read the central
[routing TAAC guide](../../../../../routing_qualification/docs/taac/README.md)
and
[TestConfig policy](../../../../../routing_qualification/docs/taac/TESTCONFIGS.md)
before editing this package.

Factories own TestConfig composition for a topology/capability envelope.
Lifecycle constants belong one level up in `cicd_*.py`, `qual_*.py`, or
`adhoc_*.py`. Catalog governance belongs in
`../../../../../routing_qualification/catalogs/taac/`.

Any relevant change to a cataloged factory requires same-diff catalog review,
Requirement Coverage and gap re-evaluation, Markdown regeneration, and catalog
validation.
