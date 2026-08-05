# DICE Physical Inventory

`PhysicalInventory` is a framework component, parallel to `LogicalTopology`.
It describes physical resources and metadata that DICE binds to logical
intent. The schema is not owned by routing testconfigs.

## Layout

- `physical_inventory.py`: domain-neutral framework definition.
- `routing_ebb_testbed.py`: BAG and EB-family routing inventories.
- `routing_dcn_testbed.py`: FBOSS and DCN routing inventories.
- `routing_cte_testbed.py`: CTE routing inventories.
- `__init__.py`: public inventory import surface.

Each testbed family owns its concrete instances and any small family-local
construction helpers. Do not add a shared routing-default module. A new DICE
consumer should add its own `<domain>_<testbed>_testbed.py` module without
moving its domain policy into the `PhysicalInventory` schema.

Use the framework type through:

```python
from taac.abstractions import PhysicalInventory
```

Use concrete inventories through the package or their owning family module:

```python
from taac.abstractions.physical_inventory import BAG010_ASH6
from taac.abstractions.physical_inventory.routing_dcn_testbed import (
    FSW_FUJI_QZD1,
)
```

`testconfigs/routing/physical_inventory.py` is a compatibility facade only.
New code must not define framework types or concrete inventories there.

---

## File shape for `<domain>_<testbed>_testbed.py`

Every testbed-family module has two parts. `routing_ebb_testbed.py` is
the canonical reference — mirror it when you author or extend another
family module.

```
1. Module docstring
     §1 Purpose (1-2 lines)
     §2 IXIA (or other resource) inventory table
     §3 Figure A — full physical topology (ASCII)
     §4 Figure B — feature-pair / ownership zoom  [OPTIONAL]
                    Include only if the testbed uses a pair-of-DUTs
                    ownership pattern (e.g. two BAGs cabled back-to-back
                    with an OpenR-standalone Port-Channel per side). A
                    single-DUT testbed, or a fabric that uses OpenR
                    standalone without paired ownership, does not need
                    this figure.
     §5 Naming conventions  [OPTIONAL — only for testbeds that adopt one]
                    E.g. the EBB BAG family's `port_channel_id → owner`
                    mapping. Skip if no family-local convention exists.
     §6 See-also cross-refs (including any framework-mode contract this
        family participates in)

2. Artifacts, grouped by role
     - Feature-participating artifacts first, with pair/group header
       comments referring back to the module-docstring figures.
     - Non-participating artifacts of the same device family next,
       calling out why they don't participate (e.g.
       `# openr_standalone_link=None`).
     - Ancillary lab / dev / non-conveyor boxes at the bottom.
```

**Rationale.**
- The **module docstring** loads the reader with the physical picture
  before any code.
- The **artifact block** places DUT declarations where the reader
  arrives already knowing what the fields mean; no back-scrolling.
- **Framework contracts do not live here.** If a testbed's artifacts
  set a framework field whose runtime consumption is non-trivial
  (e.g. `openr_standalone_link`), the contract is documented once in
  `abstractions/README.md`, next to the model definition — not repeated
  per testbed family. Cross-reference from the docstring's §6 See-also.

---

## New OpenR-standalone BAG onboarding — recipe

Follow these steps to add a new BAG pair (or extend an existing one) that
uses the Approach 3 OpenR-standalone mechanism. For the framework
contract (approach, runtime behavior, component call-chain, invariants,
enforcement), see `abstractions/README.md §4 OpenR standalone mode` —
this recipe only covers the ASH6-specific onboarding steps.

1. **Pick the ownership pair.** Two DUTs cabled back-to-back with two
   physical members between them. Each DUT will own one Port-Channel; the
   other DUT terminates the far side as a helper only.

2. **Choose `port_channel_id`.** Use `1003NN` where `NN` is a two-digit
   token equal to the last two digits of the owner's `bag0NN` hostname:
   `po100310 → bag010`, `po100311 → bag011`, `po100312 → bag012`,
   `po100313 → bag013`. This preserves the grep-back-to-owner
   traceability invariant. Do NOT reuse an ID across pairs.

3. **Allocate subnets.** For each direction of the pair:
   - IPv4 `/31` (owner + helper share the network),
   - global IPv6 `/127` (same),
   - IPv6 link-local host prefix `/64` within the `fe80::/10` link-local
     range defined by RFC 4291 (owner + helper share the network).

   `OpenRStandaloneLink.__post_init__` in
   `abstractions/topology/model.py` will reject any pair whose endpoints
   are on different networks on any family, so mis-allocation fails at
   import time.

4. **Define the link.** In `routing_ebb_testbed.py`, immediately before
   the owner's `PhysicalInventory`:

   ```python
   _BAG0NN_OPENR_LINK = OpenRStandaloneLink(
       port_channel_id=1003NN,
       owner=OpenRStandaloneEndpoint(
           hostname="bag0NN.ash6",
           member_interface="Ethernet3/…/1",
           ipv4_cidr="…/31",
           ipv6_cidr="…/127",
           link_local_cidr="fe80::…/64",
       ),
       helper=OpenRStandaloneEndpoint(
           hostname="bag0MM.ash6",   # the peer DUT
           member_interface="Ethernet3/…/1",
           ipv4_cidr="…/31",
           ipv6_cidr="…/127",
           link_local_cidr="fe80::…/64",
       ),
   )
   ```

5. **Define the DUT inventory.** Set
   `openr_standalone_link=_BAG0NN_OPENR_LINK` and
   `openr_configerator_path="taac/ebb_ci_cd_configs/bag0NN_ash6_openr_config"`
   on the owner's `PhysicalInventory`.

6. **Repeat for the peer DUT.** Each side of the pair owns a distinct
   Port-Channel (`1003NN` and `1003MM`). Even though both port-channels
   run over the same two physical cables, each DUT declares only its own
   in its inventory.

7. **Update Figure A** in the module docstring so the topology diagram
   includes the new pair.

8. **Re-export the new constants.** Add them to
   `abstractions/physical_inventory/__init__.py` and, if consumed by
   legacy paths, to
   `testconfigs/routing/physical_inventory.py` (the compatibility
   facade).

9. **Deploy the OpenR config to Configerator** at the declared
   `openr_configerator_path`. Setup will `symlink /mnt/flash/openr_config →
   /etc/openr_config` from this path at test time.

10. **Verify.** `arc lint` + `buck2 build
    fbcode//neteng/test_infra/dne/taac/abstractions/physical_inventory:routing_ebb_testbed-type-checking`.

---

## What NOT to do

- **Do not put two DUTs' OpenR next-hops on a single shared Port-Channel.**
  Breaks the single-ownership invariant and future teardown scope. Each
  DUT must own its own PC.

- **Do not reuse a `port_channel_id` across pairs.** Breaks the
  `po1003NN → bag0NN` traceability convention (see the "Choose
  `port_channel_id`" step above). Grepping a PC id must identify
  exactly one owner.

- **Do not run OpenR on the helper DUT.** The helper's role is strictly
  to bring up the far-side member so the Port-Channel is operational.
  Running OpenR on both sides would form real adjacencies and defeat
  Approach 3's control over the fake KvStore snapshot.

- **Do not add helper-owned `adj:` entries** to the KvStore injection
  path (`internal/utils/openr_route_utils.py`). Only the owner injects.

- **Do not clone this file's shape ad-hoc** for other testbed families.
  Follow the "File shape" template above. Testbed-family docs cover only
  testbed-local topology, IXIA inventory, naming conventions, and
  see-also cross-refs — never framework contracts. Runtime-contract
  documentation for any framework field (e.g. `openr_standalone_link`,
  future `openr_mode` values, new `RoutingDeviceConfig` fields) belongs
  in `abstractions/README.md` next to the model definition, not in a
  per-testbed banner.
