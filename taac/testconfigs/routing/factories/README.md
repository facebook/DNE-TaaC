# Routing TestConfig factories

Read the central [routing TAAC guide](../../../docs/routing/README.md) and
[TestConfig policy](../../../docs/routing/TESTCONFIGS.md) before editing this
package.

Factories own TestConfig composition for a topology/capability envelope.
Lifecycle constants belong one level up in `cicd_*.py`, `qual_*.py`, or
`adhoc_*.py`. Catalog governance belongs in `../../../catalogs/routing/`.

Any relevant change to a cataloged factory requires same-diff catalog review,
Requirement Coverage and gap re-evaluation, Markdown regeneration, and catalog
validation.
