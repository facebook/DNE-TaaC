# BGP++ Update Group Qualification Catalog

<!-- Generated from the adjacent YAML catalog. Do not edit directly. -->

Qualification catalog for the 28 active cases in the BGP++ on EOS Update Group test plan. It records the source requirement, intended factory and playbook, topology, blocking outcomes, and current automation status. The repository currently contains 16 implemented factories and 12 skeletons; source case 2.9.5 is struck through in the plan and is intentionally absent.

- **Type:** `QUAL`
- **Owner:** `routing_qual`
- **Playbook module:** `neteng.test_infra.dne.taac.playbooks.routing.factories.qual_bgp_update_group`

## Sources

- [Update Group Test Plan — BGP++ on EOS](https://docs.google.com/document/d/1n_Cao8MKBjLUEvZIk58VLMgdWkhWgVcxIaIdOpQipJk/edit?tab=t.0)

## Required Topologies

| ID | Status | Artifact | Description |
| --- | --- | --- | --- |
| `ebb_full_scale_update_group` | modeled | `neteng.test_infra.dne.taac.abstractions.topologies.ebb_full_scale.ebb_full_scale_topology` | Shared EBB-scale topology used by distribution, lifecycle, disruption, and edge-case qualification. Current builders generally omit BGP Monitor. |
| `update_group_backpressure` | modeled | `neteng.test_infra.dne.taac.abstractions.topologies.ug_backpressure.UG_BACKPRESSURE` | Dedicated full-scale route-storm topology with controllable fast and slow peers, heavy attributes, and per-peer egress observability. |
| `update_group_new_peer_join` | modeled | `neteng.test_infra.dne.taac.abstractions.topologies.ug_new_peer_join.UG_NEW_PEER_JOIN` | Dedicated 21-eBGP and 4-iBGP topology with one held-back receiver and independent route pools for join, withdrawal, and attribute-change tests. |

## Catalog at a Glance

| ID | Test Case | Playbook | Status | Requirement Coverage | Topology | Enforcement |
| --- | --- | --- | --- | --- | --- | --- |
| QUAL-UG-01 | Initial Dump — All Peers in Same Group Receive Identical Routes | `bag013_2_1_1_initial_dump_identical_routes` | implemented | UG-2.1.1 (direct) | `ebb_full_scale_update_group` | blocking |
| QUAL-UG-02 | Runtime Route Distribution — Routes Flow to All Group Members | `bgp_ug_runtime_route_distribution` | skeleton | UG-2.1.2 (direct) | `ebb_full_scale_update_group` | informational |
| QUAL-UG-03 | Peer Down — Remaining Group Members Unaffected | `bgp_ug_peer_down_remaining_unaffected` | skeleton | UG-2.2.1 (direct) | `ebb_full_scale_update_group` | informational |
| QUAL-UG-04 | Peer Reconnect — Re-Sync from Shadow RIB | `bgp_ug_peer_reconnect_shadow_rib` | skeleton | UG-2.2.2 (direct) | `ebb_full_scale_update_group` | informational |
| QUAL-UG-05 | Sustained Group Membership Churn — No Memory Leak | `bgp_ug_sustained_group_membership_churn` | skeleton | UG-2.2.3 (direct) | `ebb_full_scale_update_group` | informational |
| QUAL-UG-06 | Fast Peers Not Held Back by Slow Peers | `ug_backpressure_fast_peers_not_held_back` | implemented | UG-2.3.1 (direct) | `update_group_backpressure` | blocking |
| QUAL-UG-07 | Peer Blocks, Goes Down, Comes Back — Full Recovery | `ug_backpressure_peer_blocks_down_recover` | implemented | UG-2.3.2 (direct) | `update_group_backpressure` | blocking |
| QUAL-UG-08 | Withdraw and Attribute Change Under Backpressure | `ug_backpressure_withdraw_attr_change` | implemented | UG-2.3.3 (direct) | `update_group_backpressure` | blocking |
| QUAL-UG-09 | All Peers Block, Then All Go Down, Then All Come Back | `ug_backpressure_all_peers_block_down_recover` | implemented | UG-2.3.4 (direct) | `update_group_backpressure` | blocking |
| QUAL-UG-10 | New Peer Joins, Receives Full Sync, Then a Peer Goes Down | `new_peer_join_full_sync_resilience` | implemented | UG-2.4.1 (direct) | `update_group_new_peer_join` | blocking |
| QUAL-UG-11 | New Peer Joins, Then Routes Are Withdrawn | `new_peer_join_routes_withdrawn` | implemented | UG-2.4.2 (direct) | `update_group_new_peer_join` | blocking |
| QUAL-UG-12 | New Peer Joins, Then Attribute Change on Existing Routes | `new_peer_join_attribute_change` | implemented | UG-2.4.3 (direct) | `update_group_new_peer_join` | blocking |
| QUAL-UG-13 | Multiple Groups Formed for Different Outbound Policies | `bgp_ug_multiple_groups_outbound_policies` | skeleton | UG-2.5.1 (direct) | `ebb_full_scale_update_group` | informational |
| QUAL-UG-14 | Scale Withdraw — 10+ Peers in Same Group, Withdraw Routes | `bgp_ug_scale_withdraw_10plus_peers` | skeleton | UG-2.5.2 (direct) | `ebb_full_scale_update_group` | informational |
| QUAL-UG-15 | Repeated Peer Flaps — Group Remains Stable | `bgp_ug_repeated_peer_flaps_group_stable` | skeleton | UG-2.6.1 (direct) | `ebb_full_scale_update_group` | informational |
| QUAL-UG-16 | Link Flap — Update Group Recovery After Physical Link Bounces | `bgp_ug_link_flap_recovery` | skeleton | UG-2.7.1 (direct) | `ebb_full_scale_update_group` | informational |
| QUAL-UG-17 | Sustained Link Flapping Across Multiple Ports | `update_group_sustained_link_flap` | implemented | UG-2.7.2 (direct) | `ebb_full_scale_update_group` | blocking |
| QUAL-UG-18 | BGP Peer Flapping — Rapid Session Bounces Within Update Group | `bgp_ug_bgp_peer_flapping` | skeleton | UG-2.7.3 (direct) | `ebb_full_scale_update_group` | informational |
| QUAL-UG-19 | BGP Daemon Restart — Update Group Reconstruction | `bgp_ug_bgp_daemon_restart` | skeleton | UG-2.7.4 (direct) | `ebb_full_scale_update_group` | informational |
| QUAL-UG-20 | Cold Start — Update Group Formation From Zero State | `bgp_ug_cold_start` | skeleton | UG-2.7.5 (direct) | `ebb_full_scale_update_group` | informational |
| QUAL-UG-21 | FibAgent Restart — Update Group Stability During Data-Plane Agent Recovery | `bgp_ug_fibagent_restart` | skeleton | UG-2.7.6 (direct) | `ebb_full_scale_update_group` | informational |
| QUAL-UG-22 | Best-Path Change During Active Distribution | `bgp_ug_best_path_change` | implemented | UG-2.9.1 (direct) | `ebb_full_scale_update_group` | calibrating |
| QUAL-UG-23 | Simultaneous Disruptions Across All Groups | `bgp_ug_simultaneous_disruptions` | implemented | UG-2.9.2 (direct) | `ebb_full_scale_update_group` | blocking |
| QUAL-UG-24 | NOTIFICATION Sent to One Peer — Group Isolation | `bgp_ug_notification_isolation` | implemented | UG-2.9.3 (direct) | `ebb_full_scale_update_group` | blocking |
| QUAL-UG-25 | Dual-Stack Isolation — IPv4 Operations Do Not Affect IPv6 Group | `bgp_ug_dual_stack_isolation` | implemented | UG-2.9.4 (direct) | `ebb_full_scale_update_group` | blocking |
| QUAL-UG-26 | Staggered Peer Startup — Peers Coming Up at Different Times | `bgp_ug_staggered_startup` | implemented | UG-2.9.6 (direct) | `ebb_full_scale_update_group` | blocking |
| QUAL-UG-27 | Empty Group — Last Peer Goes Down Without Detached Peers | `bgp_ug_empty_group` | implemented | UG-2.9.7 (direct) | `ebb_full_scale_update_group` | blocking |
| QUAL-UG-28 | Quantifying CPU Reduction from Update Group | `bgp_ug_cpu_quantification` | implemented | UG-2.9.8 (direct) | `ebb_full_scale_update_group` | blocking |

## Requirement Coverage

| Requirement | Catalog Cases | Current Coverage |
| --- | --- | --- |
| UG-2.1.1 | QUAL-UG-01 (direct) | Initial-dump group formation, policy isolation, and identical UPDATE content. |
| UG-2.1.2 | QUAL-UG-02 (direct) | Runtime add, withdraw, re-add, and community-change distribution to every group member. |
| UG-2.2.1 | QUAL-UG-03 (direct) | Partial member loss does not interrupt distribution to surviving groups and peers. |
| UG-2.2.2 | QUAL-UG-04 (direct) | Reconnected peers receive routes added during downtime and rejoin the original group. |
| UG-2.2.3 | QUAL-UG-05 (direct) | One hour of peer join and leave cycles without group-state leakage. |
| UG-2.3.1 | QUAL-UG-06 (direct) | Per-peer backpressure isolation during a heavy-attribute route storm. |
| UG-2.3.2 | QUAL-UG-07 (direct) | Blocked-peer teardown and full shadow-RIB recovery after reconnection. |
| UG-2.3.3 | QUAL-UG-08 (direct) | Withdrawal, re-add, and attribute replacement while egress queues are pressured. |
| UG-2.3.4 | QUAL-UG-09 (direct) | Emptying and rebuilding a fully backpressured eBGP update group. |
| UG-2.4.1 | QUAL-UG-10 (direct) | Full initial sync for a joining peer while other members depart. |
| UG-2.4.2 | QUAL-UG-11 (direct) | A joining peer processes withdrawals issued while its initial sync is in progress. |
| UG-2.4.3 | QUAL-UG-12 (direct) | A joining peer converges to updated route attributes rather than stale initial values. |
| UG-2.5.1 | QUAL-UG-13 (direct) | Separate update groups for each peer-group, AFI, and add-path policy. |
| UG-2.5.2 | QUAL-UG-14 (direct) | Mass withdrawal reaches every member of a large update group without stale routes. |
| UG-2.6.1 | QUAL-UG-15 (direct) | Bit allocation and group membership remain correct after repeated peer flaps. |
| UG-2.7.1 | QUAL-UG-16 (direct) | Group removal, survivor isolation, and full resync across repeated physical link flaps. |
| UG-2.7.2 | QUAL-UG-17 (direct) | One hour of staggered eBGP, iBGP, and BGP-Monitor-facing physical link disruption. |
| UG-2.7.3 | QUAL-UG-18 (direct) | Rapid per-peer churn does not corrupt groups or interrupt stable receivers. |
| UG-2.7.4 | QUAL-UG-19 (direct) | Restart reconstructs identical groups, route state, and runtime distribution. |
| UG-2.7.5 | QUAL-UG-20 (direct) | Cold start forms correct groups and distributes the initial and runtime route views. |
| UG-2.7.6 | QUAL-UG-21 (direct) | FibAgent restart leaves BGP sessions, groups, and route distribution unchanged. |
| UG-2.9.1 | QUAL-UG-22 (direct) | Best-path changes during active distribution converge every member to one final path. |
| UG-2.9.2 | QUAL-UG-23 (direct) | Route, session, IGP, and attribute churn run concurrently without corrupting update groups. |
| UG-2.9.3 | QUAL-UG-24 (direct) | A peer-specific NOTIFICATION affects only the targeted session and recovery is complete. |
| UG-2.9.4 | QUAL-UG-25 (direct) | IPv4 and IPv6 update groups remain structurally and operationally isolated. |
| UG-2.9.6 | QUAL-UG-26 (direct) | Peers started in waves receive complete accumulated state and later runtime updates. |
| UG-2.9.7 | QUAL-UG-27 (direct) | Empty individual and global group states clean up and recover without orphaned state. |
| UG-2.9.8 | QUAL-UG-28 (direct) | Paired one-hour route-churn runs quantify CPU benefit with Update Group off and on. |

## Outcome Validation Coverage

This summary compares catalog-required blocking signals with the playbook-level health-check chains currently implemented. Step-local assertions and periodic monitors are reported separately and never upgrade health-check coverage.

| ID | Test Case | Health-check Coverage | Remaining Gap |
| --- | --- | --- | --- |
| QUAL-UG-01 | Initial Dump — All Peers in Same Group Receive Identical Routes | Partial | BGP Monitor add-path separation from the source plan is not exercised by the current topology. |
| QUAL-UG-02 | Runtime Route Distribution — Routes Flow to All Group Members | Missing | Factory raises NotImplementedError and no TestConfig wires this case. No runnable playbook-level validation chain exists. |
| QUAL-UG-03 | Peer Down — Remaining Group Members Unaffected | Missing | Factory raises NotImplementedError. No runnable health-check chain exists. |
| QUAL-UG-04 | Peer Reconnect — Re-Sync from Shadow RIB | Missing | Factory raises NotImplementedError. No runnable health-check chain exists. |
| QUAL-UG-05 | Sustained Group Membership Churn — No Memory Leak | Missing | Factory raises NotImplementedError. No runnable resource-monitoring chain exists. |
| QUAL-UG-06 | Fast Peers Not Held Back by Slow Peers | Partial | The central queue-asymmetry and progress proofs are step-local rather than playbook health checks. |
| QUAL-UG-07 | Peer Blocks, Goes Down, Comes Back — Full Recovery | Partial | Route-progress and full-resync proofs are enforced by workload steps. |
| QUAL-UG-08 | Withdraw and Attribute Change Under Backpressure | Partial | Community replacement and forbidden-old-value assertions are step-local. |
| QUAL-UG-09 | All Peers Block, Then All Go Down, Then All Come Back | Partial | Group-emptying and full-resync outcomes are asserted by workload steps. |
| QUAL-UG-10 | New Peer Joins, Receives Full Sync, Then a Peer Goes Down | Partial | Join-progress and route-delta proofs are step-local. |
| QUAL-UG-11 | New Peer Joins, Then Routes Are Withdrawn | Partial | Exact held-peer route-count comparison is step-local. |
| QUAL-UG-12 | New Peer Joins, Then Attribute Change on Existing Routes | Partial | New-community presence and old-community absence are step-local assertions. |
| QUAL-UG-13 | Multiple Groups Formed for Different Outbound Policies | Missing | Factory raises NotImplementedError. No runnable distribution or add-path validation exists. |
| QUAL-UG-14 | Scale Withdraw — 10+ Peers in Same Group, Withdraw Routes | Missing | Factory raises NotImplementedError. No runnable health-check chain exists. |
| QUAL-UG-15 | Repeated Peer Flaps — Group Remains Stable | Missing | Factory raises NotImplementedError. No runnable resource or corruption validation exists. |
| QUAL-UG-16 | Link Flap — Update Group Recovery After Physical Link Bounces | Missing | Factory raises NotImplementedError. No runnable recovery or resource validation exists. |
| QUAL-UG-17 | Sustained Link Flapping Across Multiple Ports | Partial | Per-cycle interface isolation is enforced inside the sustained-flap step. |
| QUAL-UG-18 | BGP Peer Flapping — Rapid Session Bounces Within Update Group | Missing | Factory raises NotImplementedError. No runnable resource or recovery validation exists. |
| QUAL-UG-19 | BGP Daemon Restart — Update Group Reconstruction | Missing | Factory raises NotImplementedError. No runnable restart health-check chain exists. |
| QUAL-UG-20 | Cold Start — Update Group Formation From Zero State | Missing | Factory raises NotImplementedError. No runnable cold-start validation chain exists. |
| QUAL-UG-21 | FibAgent Restart — Update Group Stability During Data-Plane Agent Recovery | Missing | Factory raises NotImplementedError. No runnable FibAgent recovery chain exists. |
| QUAL-UG-22 | Best-Path Change During Active Distribution | Partial | The current PS-gauge probe is measure-first and does not hard-gate every peer's final LOCAL_PREF. |
| QUAL-UG-23 | Simultaneous Disruptions Across All Groups | Partial | Track scheduling and per-operation correctness are step-local. |
| QUAL-UG-24 | NOTIFICATION Sent to One Peer — Group Isolation | Partial | Target isolation and runtime route progress are step-local assertions. |
| QUAL-UG-25 | Dual-Stack Isolation — IPv4 Operations Do Not Affect IPv6 Group | Partial | Per-AFI route-count deltas and zero-cross-leakage proofs are step-local. |
| QUAL-UG-26 | Staggered Peer Startup — Peers Coming Up at Different Times | Partial | Per-wave full-dump and route-delta assertions are step-local. |
| QUAL-UG-27 | Empty Group — Last Peer Goes Down Without Detached Peers | Partial | Intermediate empty-state membership and isolation assertions are step-local. |
| QUAL-UG-28 | Quantifying CPU Reduction from Update Group | Partial | Cross-run metric persistence and comparison are step-local rather than playbook health checks. |

## Coverage Notes

### Current automation boundary

Sixteen source cases have executable playbooks; twelve retain explicit skeleton factories so catalog coverage cannot be mistaken for runnable automation.

**Asserted**

- Implemented factories are wired to concrete TestConfig factories and use blocking TAAC assertions where available.
- Skeleton factories raise NotImplementedError and are not wired into runnable playbook lists.

**Exercised but not feature-complete**

- The catalog preserves all 28 active source requirements, including cases that are not automated yet.

**Gaps**

- Implement the twelve skeleton factories and their TestConfig wiring.
- Reconcile source-plan BGP Monitor expectations with current topologies that deliberately omit BGP Monitor sessions.

# Test Cases

## Distribution Correctness

### QUAL-UG-01: Initial Dump — All Peers in Same Group Receive Identical Routes

- **Playbook:** `bag013_2_1_1_initial_dump_identical_routes`
- **Factory:** `create_bgp_ug_initial_dump_identical_routes_playbook`
- **Implementation status:** implemented
- **Requirements:** UG-2.1.1 (direct)
- **Required topology:** `neteng.test_infra.dne.taac.abstractions.topologies.ebb_full_scale.ebb_full_scale_topology`
- **Cadence:** Per qualification candidate.
- **Enforcement:** blocking

**Purpose:** Verify that peers with identical outbound policy share one distribution path and receive equivalent initial UPDATEs.

**Stimulus:** Bring all IXIA sessions up together, inspect update-group membership, and compare captures from two iBGP peers.

**Scale:** EBB-scale iBGP and eBGP peer population on bag013.

**Blocking signals**

- Same-policy peers share an update group and captured initial UPDATE NLRI and attributes match.
- BGP++ remains crash-free and expected sessions and resource checks pass.

**Outcome validation traceability**

- **Health-check chain:** `update_group_standard`
- **Check profile:** None
- **Implementation:** `Factory-specific prechecks, postchecks, and snapshot checks`

The chain below contains only playbook-level health checks. Trigger, step, task, and periodic-monitor assertions are not counted as health-check coverage.

| Phase | Chain ID | Implemented Health Checks | Notes |
| --- | --- | --- | --- |
| precheck | `pre.update_group` | `update group feature enabled or disabled as required by the variant`, `expected BGP sessions established`, `baseline update-group structure and resource health` | Establishes the feature, session, and resource baseline before the workload. |
| postcheck | `post.update_group` | `expected BGP sessions established`, `update-group structure and membership`, `BGP and system logs`, `CPU, load-average, and VmHWM thresholds` | Enforces final control-plane recovery and resource bounds where the factory supplies them. |
| snapshot | `snapshot.standard` | `core-dump snapshot`, `BGP session flap, uptime, and peer-identity snapshot` | Detects crashes and unexpected session drift around the workload. |

**Specification vs. implemented health checks**

| Required Validation | Implemented By | Coverage | Gap |
| --- | --- | --- | --- |
| Same-policy peers share an update group and captured initial UPDATE NLRI and attributes match. | `pre.update_group`, `post.update_group` | partial | BGP Monitor add-path separation from the source plan is not exercised by the current topology. |
| BGP++ remains crash-free and expected sessions and resource checks pass. | `post.update_group`, `snapshot.standard` | implemented | None |

**Validations outside the health-check chain**

- Step-local update-group membership and packet-capture comparison assertions enforce the core distribution outcome.

**Expected runtime:** Up to 10 minutes for convergence plus packet capture and comparison.

**Primary triage signals**

- update-group thrift state
- IXIA BGP captures and route counts
- BGP logs and core dumps

**Artifacts**

- playbooks/routing/factories/qual_bgp_update_group/tc1_distribution_correctness.py
- testconfigs/routing/factories/qual_bgp_update_group/tc1_distribution_correctness.py

**Qualification difference:** Current automation omits BGP Monitor, so the source plan's add-path group assertion remains a gap.

### QUAL-UG-02: Runtime Route Distribution — Routes Flow to All Group Members

- **Playbook:** `bgp_ug_runtime_route_distribution`
- **Factory:** `create_bgp_ug_runtime_route_distribution_playbook`
- **Implementation status:** skeleton
- **Requirements:** UG-2.1.2 (direct)
- **Required topology:** `neteng.test_infra.dne.taac.abstractions.topologies.ebb_full_scale.ebb_full_scale_topology`
- **Cadence:** Not scheduled; skeleton.
- **Enforcement:** informational

**Purpose:** Prove that every member receives runtime route operations and converges without stale attributes.

**Stimulus:** Add 100 routes, withdraw 50, re-add them with a new community, then soak for 10 minutes.

**Scale:** All iBGP group members plus BGP Monitor in the source plan.

**Blocking signals**

- Every group member receives the add, withdraw, and re-add with the new community.
- Sessions remain stable and no stale routes remain after the soak.

**Outcome validation traceability**

- **Health-check chain:** `not_implemented`
- **Check profile:** None
- **Implementation:** `Skeleton factory raising NotImplementedError`

The chain below contains only playbook-level health checks. Trigger, step, task, and periodic-monitor assertions are not counted as health-check coverage.

No playbook-level health-check chain is implemented.

**Specification vs. implemented health checks**

| Required Validation | Implemented By | Coverage | Gap |
| --- | --- | --- | --- |
| Every group member receives the add, withdraw, and re-add with the new community. | None | missing | Factory raises NotImplementedError and no TestConfig wires this case. |
| Sessions remain stable and no stale routes remain after the soak. | None | missing | No runnable playbook-level validation chain exists. |

**Validations outside the health-check chain**

- None.

**Expected runtime:** Approximately 15 minutes including the 10-minute soak.

**Primary triage signals**

- skeleton factory status
- planned IXIA route counts
- planned BGP session and stale-route checks

**Artifacts**

- playbooks/routing/factories/qual_bgp_update_group/tc1_distribution_correctness.py
- testconfigs/routing/factories/qual_bgp_update_group/tc1_distribution_correctness.py

**Qualification difference:** Implement the factory, full-peer route verification, BGP Monitor coverage, and TestConfig wiring.

## Peer Lifecycle Within Update Groups

### QUAL-UG-03: Peer Down — Remaining Group Members Unaffected

- **Playbook:** `bgp_ug_peer_down_remaining_unaffected`
- **Factory:** `create_bgp_ug_peer_down_remaining_unaffected_playbook`
- **Implementation status:** skeleton
- **Requirements:** UG-2.2.1 (direct)
- **Required topology:** `neteng.test_infra.dne.taac.abstractions.topologies.ebb_full_scale.ebb_full_scale_topology`
- **Cadence:** Not scheduled; skeleton.
- **Enforcement:** informational

**Purpose:** Verify that losing 64 eBGP peers does not disrupt iBGP or other update groups.

**Stimulus:** Stop 64 eBGP sessions, inject 50 routes through survivors, and hold the state for five minutes.

**Scale:** 64 departing eBGP peers and all iBGP receivers.

**Blocking signals**

- Surviving groups receive every new route while departed peers are removed cleanly.
- No iBGP flap, crash, CPU breach, or VmHWM breach occurs.

**Outcome validation traceability**

- **Health-check chain:** `not_implemented`
- **Check profile:** None
- **Implementation:** `Skeleton factory raising NotImplementedError`

The chain below contains only playbook-level health checks. Trigger, step, task, and periodic-monitor assertions are not counted as health-check coverage.

No playbook-level health-check chain is implemented.

**Specification vs. implemented health checks**

| Required Validation | Implemented By | Coverage | Gap |
| --- | --- | --- | --- |
| Surviving groups receive every new route while departed peers are removed cleanly. | None | missing | Factory raises NotImplementedError. |
| No iBGP flap, crash, CPU breach, or VmHWM breach occurs. | None | missing | No runnable health-check chain exists. |

**Validations outside the health-check chain**

- None.

**Expected runtime:** Approximately 10 minutes.

**Primary triage signals**

- skeleton factory status
- planned update-group membership
- planned CPU and VmHWM metrics

**Artifacts**

- playbooks/routing/factories/qual_bgp_update_group/tc2_peer_lifecycle.py
- testconfigs/routing/factories/qual_bgp_update_group/tc2_peer_lifecycle.py

**Qualification difference:** Implement the workload and lifecycle assertions, then wire a runnable TestConfig.

### QUAL-UG-04: Peer Reconnect — Re-Sync from Shadow RIB

- **Playbook:** `bgp_ug_peer_reconnect_shadow_rib`
- **Factory:** `create_bgp_ug_peer_reconnect_shadow_rib_playbook`
- **Implementation status:** skeleton
- **Requirements:** UG-2.2.2 (direct)
- **Required topology:** `neteng.test_infra.dne.taac.abstractions.topologies.ebb_full_scale.ebb_full_scale_topology`
- **Cadence:** Not scheduled; skeleton.
- **Enforcement:** informational

**Purpose:** Prove shadow-RIB resynchronization for peers returning after runtime route additions.

**Stimulus:** Stop 32 eBGP peers, inject 100 routes, restart the peers, and compare their final route state.

**Scale:** 32 reconnecting eBGP peers plus all stable receivers.

**Blocking signals**

- Reconnected peers receive the complete current route set and rejoin their original update group.
- Route counts match continuously connected peers with no stale state or crash.

**Outcome validation traceability**

- **Health-check chain:** `not_implemented`
- **Check profile:** None
- **Implementation:** `Skeleton factory raising NotImplementedError`

The chain below contains only playbook-level health checks. Trigger, step, task, and periodic-monitor assertions are not counted as health-check coverage.

No playbook-level health-check chain is implemented.

**Specification vs. implemented health checks**

| Required Validation | Implemented By | Coverage | Gap |
| --- | --- | --- | --- |
| Reconnected peers receive the complete current route set and rejoin their original update group. | None | missing | Factory raises NotImplementedError. |
| Route counts match continuously connected peers with no stale state or crash. | None | missing | No runnable health-check chain exists. |

**Validations outside the health-check chain**

- None.

**Expected runtime:** Approximately 10 minutes.

**Primary triage signals**

- skeleton factory status
- planned shadow-RIB route counts
- planned update-group membership

**Artifacts**

- playbooks/routing/factories/qual_bgp_update_group/tc2_peer_lifecycle.py
- testconfigs/routing/factories/qual_bgp_update_group/tc2_peer_lifecycle.py

**Qualification difference:** Implement the reconnect sequence, full-resync assertions, and TestConfig wiring.

### QUAL-UG-05: Sustained Group Membership Churn — No Memory Leak

- **Playbook:** `bgp_ug_sustained_group_membership_churn`
- **Factory:** `create_bgp_ug_sustained_group_membership_churn_playbook`
- **Implementation status:** skeleton
- **Requirements:** UG-2.2.3 (direct)
- **Required topology:** `neteng.test_infra.dne.taac.abstractions.topologies.ebb_full_scale.ebb_full_scale_topology`
- **Cadence:** Not scheduled; skeleton.
- **Enforcement:** informational

**Purpose:** Detect memory leaks, orphaned members, and stale group entries during sustained membership churn.

**Stimulus:** Flap a random set of 32 eBGP peers every minute for one hour with 15-minute checkpoints.

**Scale:** About 60 churn cycles over 32 eBGP peers.

**Blocking signals**

- Group membership and route counts remain correct at every checkpoint and after recovery.
- VmHWM growth stays below 200 MB with no crash, error logs, or load-average breach.

**Outcome validation traceability**

- **Health-check chain:** `not_implemented`
- **Check profile:** None
- **Implementation:** `Skeleton factory raising NotImplementedError`

The chain below contains only playbook-level health checks. Trigger, step, task, and periodic-monitor assertions are not counted as health-check coverage.

No playbook-level health-check chain is implemented.

**Specification vs. implemented health checks**

| Required Validation | Implemented By | Coverage | Gap |
| --- | --- | --- | --- |
| Group membership and route counts remain correct at every checkpoint and after recovery. | None | missing | Factory raises NotImplementedError. |
| VmHWM growth stays below 200 MB with no crash, error logs, or load-average breach. | None | missing | No runnable resource-monitoring chain exists. |

**Validations outside the health-check chain**

- None.

**Expected runtime:** Slightly over one hour.

**Primary triage signals**

- skeleton factory status
- planned VmHWM trend
- planned membership checkpoints and EOS logs

**Artifacts**

- playbooks/routing/factories/qual_bgp_update_group/tc2_peer_lifecycle.py
- testconfigs/routing/factories/qual_bgp_update_group/tc2_peer_lifecycle.py

**Qualification difference:** Implement the one-hour scheduler, memory delta gate, checkpoint assertions, and TestConfig wiring.

## Backpressure and Blocking Behavior

### QUAL-UG-06: Fast Peers Not Held Back by Slow Peers

- **Playbook:** `ug_backpressure_fast_peers_not_held_back`
- **Factory:** `create_bgp_ug_backpressure_fast_peers_not_held_back_playbook`
- **Implementation status:** implemented
- **Requirements:** UG-2.3.1 (direct)
- **Required topology:** `neteng.test_infra.dne.taac.abstractions.topologies.ug_backpressure.UG_BACKPRESSURE`
- **Cadence:** Per qualification candidate.
- **Enforcement:** blocking

**Purpose:** Verify that slow peers develop deeper queues without preventing fast peers from making progress.

**Stimulus:** Inject 10,000 heavy-attribute routes, observe per-peer backpressure, settle, and withdraw the storm.

**Scale:** EBB-scale sessions with a 10,000-prefix, 32-community, 16-extended-community, 255-ASN workload.

**Blocking signals**

- Slow peers exhibit backpressure while fast peers continue receiving routes and all queues eventually drain.
- All peers converge after withdrawal with no stale routes, crash, or resource breach.

**Outcome validation traceability**

- **Health-check chain:** `update_group_standard`
- **Check profile:** None
- **Implementation:** `Factory-specific prechecks, postchecks, and snapshot checks`

The chain below contains only playbook-level health checks. Trigger, step, task, and periodic-monitor assertions are not counted as health-check coverage.

| Phase | Chain ID | Implemented Health Checks | Notes |
| --- | --- | --- | --- |
| precheck | `pre.update_group` | `update group feature enabled or disabled as required by the variant`, `expected BGP sessions established`, `baseline update-group structure and resource health` | Establishes the feature, session, and resource baseline before the workload. |
| postcheck | `post.update_group` | `expected BGP sessions established`, `update-group structure and membership`, `BGP and system logs`, `CPU, load-average, and VmHWM thresholds` | Enforces final control-plane recovery and resource bounds where the factory supplies them. |
| snapshot | `snapshot.standard` | `core-dump snapshot`, `BGP session flap, uptime, and peer-identity snapshot` | Detects crashes and unexpected session drift around the workload. |

**Specification vs. implemented health checks**

| Required Validation | Implemented By | Coverage | Gap |
| --- | --- | --- | --- |
| Slow peers exhibit backpressure while fast peers continue receiving routes and all queues eventually drain. | `pre.update_group`, `post.update_group` | partial | The central queue-asymmetry and progress proofs are step-local rather than playbook health checks. |
| All peers converge after withdrawal with no stale routes, crash, or resource breach. | `post.update_group`, `snapshot.standard` | implemented | None |

**Validations outside the health-check chain**

- Step-local per-peer queue, blocks, sent-route, and IXIA receive-counter assertions prove fast-peer progress and recovery.

**Expected runtime:** Approximately 20 minutes, workload dependent.

**Primary triage signals**

- per-peer queue and blocks counters
- IXIA receive counters
- BGP routes and process resources

**Artifacts**

- playbooks/routing/factories/qual_bgp_update_group/tc3_backpressure.py
- testconfigs/routing/factories/qual_bgp_update_group/tc3_backpressure.py

**Qualification difference:** Uses dedicated fast and TCP-throttled slow peers; current topology omits BGP Monitor.

### QUAL-UG-07: Peer Blocks, Goes Down, Comes Back — Full Recovery

- **Playbook:** `ug_backpressure_peer_blocks_down_recover`
- **Factory:** `create_bgp_ug_backpressure_peer_blocks_down_recover_playbook`
- **Implementation status:** implemented
- **Requirements:** UG-2.3.2 (direct)
- **Required topology:** `neteng.test_infra.dne.taac.abstractions.topologies.ug_backpressure.UG_BACKPRESSURE`
- **Cadence:** Per qualification candidate.
- **Enforcement:** blocking

**Purpose:** Verify that peer removal under backpressure cannot corrupt group state or lose routes learned during downtime.

**Stimulus:** Inject 5,000 heavy routes, stop selected peers, inject 500 more, then reconnect and verify full recovery.

**Scale:** 5,500 storm routes with a controlled peer subset transitioning through blocked, down, and recovered states.

**Blocking signals**

- Remaining peers continue progressing and reconnected peers receive the complete 5,500-route view.
- No stale routes, crash, core dump, or VmHWM breach remains after recovery.

**Outcome validation traceability**

- **Health-check chain:** `update_group_standard`
- **Check profile:** None
- **Implementation:** `Factory-specific prechecks, postchecks, and snapshot checks`

The chain below contains only playbook-level health checks. Trigger, step, task, and periodic-monitor assertions are not counted as health-check coverage.

| Phase | Chain ID | Implemented Health Checks | Notes |
| --- | --- | --- | --- |
| precheck | `pre.update_group` | `update group feature enabled or disabled as required by the variant`, `expected BGP sessions established`, `baseline update-group structure and resource health` | Establishes the feature, session, and resource baseline before the workload. |
| postcheck | `post.update_group` | `expected BGP sessions established`, `update-group structure and membership`, `BGP and system logs`, `CPU, load-average, and VmHWM thresholds` | Enforces final control-plane recovery and resource bounds where the factory supplies them. |
| snapshot | `snapshot.standard` | `core-dump snapshot`, `BGP session flap, uptime, and peer-identity snapshot` | Detects crashes and unexpected session drift around the workload. |

**Specification vs. implemented health checks**

| Required Validation | Implemented By | Coverage | Gap |
| --- | --- | --- | --- |
| Remaining peers continue progressing and reconnected peers receive the complete 5,500-route view. | `post.update_group` | partial | Route-progress and full-resync proofs are enforced by workload steps. |
| No stale routes, crash, core dump, or VmHWM breach remains after recovery. | `post.update_group`, `snapshot.standard` | implemented | None |

**Validations outside the health-check chain**

- Step-local IXIA toggles, sent-route deltas, and queue-recovery checks enforce the recovery sequence.

**Expected runtime:** Approximately 20 minutes, workload dependent.

**Primary triage signals**

- peer egress queues
- shadow-RIB route counts
- session transitions and core dumps

**Artifacts**

- playbooks/routing/factories/qual_bgp_update_group/tc3_backpressure.py
- testconfigs/routing/factories/qual_bgp_update_group/tc3_backpressure.py

**Qualification difference:** The automation provides deterministic slow-peer controls and explicit post-recovery queue gates.

### QUAL-UG-08: Withdraw and Attribute Change Under Backpressure

- **Playbook:** `ug_backpressure_withdraw_attr_change`
- **Factory:** `create_bgp_ug_backpressure_withdraw_attr_change_playbook`
- **Implementation status:** implemented
- **Requirements:** UG-2.3.3 (direct)
- **Required topology:** `neteng.test_infra.dne.taac.abstractions.topologies.ug_backpressure.UG_BACKPRESSURE`
- **Cadence:** Per qualification candidate.
- **Enforcement:** blocking

**Purpose:** Prove ordering and final-state correctness for route operations performed during backpressure.

**Stimulus:** Build a 5,000-route storm, withdraw and re-add 200 routes with a new community, and modify 100 routes.

**Scale:** Heavy-attribute storm plus targeted route and community mutations.

**Blocking signals**

- All receivers converge to the withdrawal, re-add, and new attribute state without stale values.
- BGP++ remains crash-free and log, session, and snapshot checks pass.

**Outcome validation traceability**

- **Health-check chain:** `update_group_standard`
- **Check profile:** None
- **Implementation:** `Factory-specific prechecks, postchecks, and snapshot checks`

The chain below contains only playbook-level health checks. Trigger, step, task, and periodic-monitor assertions are not counted as health-check coverage.

| Phase | Chain ID | Implemented Health Checks | Notes |
| --- | --- | --- | --- |
| precheck | `pre.update_group` | `update group feature enabled or disabled as required by the variant`, `expected BGP sessions established`, `baseline update-group structure and resource health` | Establishes the feature, session, and resource baseline before the workload. |
| postcheck | `post.update_group` | `expected BGP sessions established`, `update-group structure and membership`, `BGP and system logs`, `CPU, load-average, and VmHWM thresholds` | Enforces final control-plane recovery and resource bounds where the factory supplies them. |
| snapshot | `snapshot.standard` | `core-dump snapshot`, `BGP session flap, uptime, and peer-identity snapshot` | Detects crashes and unexpected session drift around the workload. |

**Specification vs. implemented health checks**

| Required Validation | Implemented By | Coverage | Gap |
| --- | --- | --- | --- |
| All receivers converge to the withdrawal, re-add, and new attribute state without stale values. | `post.update_group` | partial | Community replacement and forbidden-old-value assertions are step-local. |
| BGP++ remains crash-free and log, session, and snapshot checks pass. | `post.update_group`, `snapshot.standard` | implemented | None |

**Validations outside the health-check chain**

- Step-local prefix and community assertions verify the final receiver state before cleanup.

**Expected runtime:** Approximately 15 minutes, workload dependent.

**Primary triage signals**

- route-community state
- peer egress counters
- BGP and system logs

**Artifacts**

- playbooks/routing/factories/qual_bgp_update_group/tc3_backpressure.py
- testconfigs/routing/factories/qual_bgp_update_group/tc3_backpressure.py

**Qualification difference:** Automates both the ordered mutation sequence and stale-community rejection.

### QUAL-UG-09: All Peers Block, Then All Go Down, Then All Come Back

- **Playbook:** `ug_backpressure_all_peers_block_down_recover`
- **Factory:** `create_bgp_ug_backpressure_all_peers_block_down_recover_playbook`
- **Implementation status:** implemented
- **Requirements:** UG-2.3.4 (direct)
- **Required topology:** `neteng.test_infra.dne.taac.abstractions.topologies.ug_backpressure.UG_BACKPRESSURE`
- **Cadence:** Per qualification candidate.
- **Enforcement:** blocking

**Purpose:** Exercise the worst-case transition from all peers blocked to all peers down and fully resynchronized.

**Stimulus:** Inject 10,000 heavy routes, stop every eBGP peer, add 500 routes, and restart the full group.

**Scale:** Full eBGP group with a 10,500-route final shadow-RIB view.

**Blocking signals**

- The group empties and reforms, and every returning peer receives the full route view.
- iBGP remains healthy with no crash, core dump, resource breach, or critical log.

**Outcome validation traceability**

- **Health-check chain:** `update_group_standard`
- **Check profile:** None
- **Implementation:** `Factory-specific prechecks, postchecks, and snapshot checks`

The chain below contains only playbook-level health checks. Trigger, step, task, and periodic-monitor assertions are not counted as health-check coverage.

| Phase | Chain ID | Implemented Health Checks | Notes |
| --- | --- | --- | --- |
| precheck | `pre.update_group` | `update group feature enabled or disabled as required by the variant`, `expected BGP sessions established`, `baseline update-group structure and resource health` | Establishes the feature, session, and resource baseline before the workload. |
| postcheck | `post.update_group` | `expected BGP sessions established`, `update-group structure and membership`, `BGP and system logs`, `CPU, load-average, and VmHWM thresholds` | Enforces final control-plane recovery and resource bounds where the factory supplies them. |
| snapshot | `snapshot.standard` | `core-dump snapshot`, `BGP session flap, uptime, and peer-identity snapshot` | Detects crashes and unexpected session drift around the workload. |

**Specification vs. implemented health checks**

| Required Validation | Implemented By | Coverage | Gap |
| --- | --- | --- | --- |
| The group empties and reforms, and every returning peer receives the full route view. | `post.update_group` | partial | Group-emptying and full-resync outcomes are asserted by workload steps. |
| iBGP remains healthy with no crash, core dump, resource breach, or critical log. | `post.update_group`, `snapshot.standard` | implemented | None |

**Validations outside the health-check chain**

- Step-local peer toggles, update-group checks, and route-count deltas enforce empty-group recovery.

**Expected runtime:** Approximately 20 minutes, workload dependent.

**Primary triage signals**

- update-group membership
- per-peer route counts and queues
- process resources and core dumps

**Artifacts**

- playbooks/routing/factories/qual_bgp_update_group/tc3_backpressure.py
- testconfigs/routing/factories/qual_bgp_update_group/tc3_backpressure.py

**Qualification difference:** Uses the dedicated backpressure topology and excludes its separate topology-smoke helper from catalog scope.

## New Peer Joining a Busy Group

### QUAL-UG-10: New Peer Joins, Receives Full Sync, Then a Peer Goes Down

- **Playbook:** `new_peer_join_full_sync_resilience`
- **Factory:** `create_bgp_ug_new_peer_join_full_sync_resilience_playbook`
- **Implementation status:** implemented
- **Requirements:** UG-2.4.1 (direct)
- **Required topology:** `neteng.test_infra.dne.taac.abstractions.topologies.ug_new_peer_join.UG_NEW_PEER_JOIN`
- **Cadence:** Per qualification candidate.
- **Enforcement:** blocking

**Purpose:** Verify that a held-back peer catches up completely and is not disrupted by concurrent peer loss.

**Stimulus:** Add 200 routes before join, start the held peer, stop 16 distractor peers, then add 50 more routes.

**Scale:** Dedicated 21-eBGP and 4-iBGP topology with one held receiver and 16 distractors.

**Blocking signals**

- The new peer receives pre-join routes, completes sync through peer loss, and receives runtime updates.
- No stale routes, crash, or unexpected session and snapshot failure occurs.

**Outcome validation traceability**

- **Health-check chain:** `update_group_standard`
- **Check profile:** None
- **Implementation:** `Factory-specific prechecks, postchecks, and snapshot checks`

The chain below contains only playbook-level health checks. Trigger, step, task, and periodic-monitor assertions are not counted as health-check coverage.

| Phase | Chain ID | Implemented Health Checks | Notes |
| --- | --- | --- | --- |
| precheck | `pre.update_group` | `update group feature enabled or disabled as required by the variant`, `expected BGP sessions established`, `baseline update-group structure and resource health` | Establishes the feature, session, and resource baseline before the workload. |
| postcheck | `post.update_group` | `expected BGP sessions established`, `update-group structure and membership`, `BGP and system logs`, `CPU, load-average, and VmHWM thresholds` | Enforces final control-plane recovery and resource bounds where the factory supplies them. |
| snapshot | `snapshot.standard` | `core-dump snapshot`, `BGP session flap, uptime, and peer-identity snapshot` | Detects crashes and unexpected session drift around the workload. |

**Specification vs. implemented health checks**

| Required Validation | Implemented By | Coverage | Gap |
| --- | --- | --- | --- |
| The new peer receives pre-join routes, completes sync through peer loss, and receives runtime updates. | `post.update_group` | partial | Join-progress and route-delta proofs are step-local. |
| No stale routes, crash, or unexpected session and snapshot failure occurs. | `post.update_group`, `snapshot.standard` | implemented | None |

**Validations outside the health-check chain**

- Step-local held-peer, distractor-peer, and route-count assertions enforce the source sequence.

**Expected runtime:** Approximately 15 minutes.

**Primary triage signals**

- held-peer IXIA state
- per-peer sent-route counts
- update-group membership and logs

**Artifacts**

- playbooks/routing/factories/qual_bgp_update_group/tc4_new_peer_join.py
- testconfigs/routing/factories/qual_bgp_update_group/tc4_new_peer_join.py

**Qualification difference:** Uses a smaller deterministic topology rather than every EBB peer in the source-plan narrative.

### QUAL-UG-11: New Peer Joins, Then Routes Are Withdrawn

- **Playbook:** `new_peer_join_routes_withdrawn`
- **Factory:** `create_bgp_ug_new_peer_join_routes_withdrawn_playbook`
- **Implementation status:** implemented
- **Requirements:** UG-2.4.2 (direct)
- **Required topology:** `neteng.test_infra.dne.taac.abstractions.topologies.ug_new_peer_join.UG_NEW_PEER_JOIN`
- **Cadence:** Per qualification candidate.
- **Enforcement:** blocking

**Purpose:** Ensure a late peer ends with the current RIB rather than a stale pre-withdrawal snapshot.

**Stimulus:** Inject 500 routes, start the held peer, immediately withdraw 200 routes, and compare final counts.

**Scale:** One held receiver and a 500-to-300 route transition.

**Blocking signals**

- The joining peer and stable peers finish with exactly the same 300-route view.
- No stale routes, crash, or unexpected session and snapshot failure occurs.

**Outcome validation traceability**

- **Health-check chain:** `update_group_standard`
- **Check profile:** None
- **Implementation:** `Factory-specific prechecks, postchecks, and snapshot checks`

The chain below contains only playbook-level health checks. Trigger, step, task, and periodic-monitor assertions are not counted as health-check coverage.

| Phase | Chain ID | Implemented Health Checks | Notes |
| --- | --- | --- | --- |
| precheck | `pre.update_group` | `update group feature enabled or disabled as required by the variant`, `expected BGP sessions established`, `baseline update-group structure and resource health` | Establishes the feature, session, and resource baseline before the workload. |
| postcheck | `post.update_group` | `expected BGP sessions established`, `update-group structure and membership`, `BGP and system logs`, `CPU, load-average, and VmHWM thresholds` | Enforces final control-plane recovery and resource bounds where the factory supplies them. |
| snapshot | `snapshot.standard` | `core-dump snapshot`, `BGP session flap, uptime, and peer-identity snapshot` | Detects crashes and unexpected session drift around the workload. |

**Specification vs. implemented health checks**

| Required Validation | Implemented By | Coverage | Gap |
| --- | --- | --- | --- |
| The joining peer and stable peers finish with exactly the same 300-route view. | `post.update_group` | partial | Exact held-peer route-count comparison is step-local. |
| No stale routes, crash, or unexpected session and snapshot failure occurs. | `post.update_group`, `snapshot.standard` | implemented | None |

**Validations outside the health-check chain**

- Step-local IXIA toggles and exact route-count checks enforce withdrawal-during-sync behavior.

**Expected runtime:** Approximately 10 minutes.

**Primary triage signals**

- held-peer route counts
- withdrawal counters
- session state and core dumps

**Artifacts**

- playbooks/routing/factories/qual_bgp_update_group/tc4_new_peer_join.py
- testconfigs/routing/factories/qual_bgp_update_group/tc4_new_peer_join.py

**Qualification difference:** Uses the dedicated held-peer topology and blocks on the exact post-withdrawal count.

### QUAL-UG-12: New Peer Joins, Then Attribute Change on Existing Routes

- **Playbook:** `new_peer_join_attribute_change`
- **Factory:** `create_bgp_ug_new_peer_join_attribute_change_playbook`
- **Implementation status:** implemented
- **Requirements:** UG-2.4.3 (direct)
- **Required topology:** `neteng.test_infra.dne.taac.abstractions.topologies.ug_new_peer_join.UG_NEW_PEER_JOIN`
- **Cadence:** Per qualification candidate.
- **Enforcement:** blocking

**Purpose:** Verify attribute replacement is ordered correctly relative to a peer's initial sync.

**Stimulus:** Inject 200 routes with one community, start the held peer, and switch the routes to a new community.

**Scale:** One held receiver and 200 routes with a two-community state transition.

**Blocking signals**

- Every peer finishes with the new community and none retain the old community.
- BGP++ remains crash-free and session and snapshot checks pass.

**Outcome validation traceability**

- **Health-check chain:** `update_group_standard`
- **Check profile:** None
- **Implementation:** `Factory-specific prechecks, postchecks, and snapshot checks`

The chain below contains only playbook-level health checks. Trigger, step, task, and periodic-monitor assertions are not counted as health-check coverage.

| Phase | Chain ID | Implemented Health Checks | Notes |
| --- | --- | --- | --- |
| precheck | `pre.update_group` | `update group feature enabled or disabled as required by the variant`, `expected BGP sessions established`, `baseline update-group structure and resource health` | Establishes the feature, session, and resource baseline before the workload. |
| postcheck | `post.update_group` | `expected BGP sessions established`, `update-group structure and membership`, `BGP and system logs`, `CPU, load-average, and VmHWM thresholds` | Enforces final control-plane recovery and resource bounds where the factory supplies them. |
| snapshot | `snapshot.standard` | `core-dump snapshot`, `BGP session flap, uptime, and peer-identity snapshot` | Detects crashes and unexpected session drift around the workload. |

**Specification vs. implemented health checks**

| Required Validation | Implemented By | Coverage | Gap |
| --- | --- | --- | --- |
| Every peer finishes with the new community and none retain the old community. | `post.update_group` | partial | New-community presence and old-community absence are step-local assertions. |
| BGP++ remains crash-free and session and snapshot checks pass. | `post.update_group`, `snapshot.standard` | implemented | None |

**Validations outside the health-check chain**

- Step-local route-community checks enforce updated attributes across the held and control peers.

**Expected runtime:** Approximately 10 minutes.

**Primary triage signals**

- per-peer route communities
- held-peer session state
- BGP logs and core dumps

**Artifacts**

- playbooks/routing/factories/qual_bgp_update_group/tc4_new_peer_join.py
- testconfigs/routing/factories/qual_bgp_update_group/tc4_new_peer_join.py

**Qualification difference:** Uses pre-staged IXIA route variants to make the attribute transition deterministic.

## Multi-Group Formation Correctness

### QUAL-UG-13: Multiple Groups Formed for Different Outbound Policies

- **Playbook:** `bgp_ug_multiple_groups_outbound_policies`
- **Factory:** `create_bgp_ug_multiple_groups_outbound_policies_playbook`
- **Implementation status:** skeleton
- **Requirements:** UG-2.5.1 (direct)
- **Required topology:** `neteng.test_infra.dne.taac.abstractions.topologies.ebb_full_scale.ebb_full_scale_topology`
- **Cadence:** Not scheduled; skeleton.
- **Enforcement:** informational

**Purpose:** Prove correct group partitioning and cross-group route isolation.

**Stimulus:** Inspect group membership, advertise IPv6 routes, and compare IPv6, IPv4, and BGP Monitor behavior.

**Scale:** All source-plan peer groups across both AFIs plus BGP Monitor.

**Blocking signals**

- Each distinct outbound policy forms its own update group with the expected member set.
- Routes stay within the correct AFI and BGP Monitor retains add-path semantics.

**Outcome validation traceability**

- **Health-check chain:** `not_implemented`
- **Check profile:** None
- **Implementation:** `Skeleton factory raising NotImplementedError`

The chain below contains only playbook-level health checks. Trigger, step, task, and periodic-monitor assertions are not counted as health-check coverage.

No playbook-level health-check chain is implemented.

**Specification vs. implemented health checks**

| Required Validation | Implemented By | Coverage | Gap |
| --- | --- | --- | --- |
| Each distinct outbound policy forms its own update group with the expected member set. | None | missing | Factory raises NotImplementedError. |
| Routes stay within the correct AFI and BGP Monitor retains add-path semantics. | None | missing | No runnable distribution or add-path validation exists. |

**Validations outside the health-check chain**

- None.

**Expected runtime:** Approximately 10 minutes.

**Primary triage signals**

- skeleton factory status
- planned group membership
- planned AFI and add-path route counts

**Artifacts**

- playbooks/routing/factories/qual_bgp_update_group/tc5_multigroup_formation.py
- testconfigs/routing/factories/qual_bgp_update_group/tc5_multigroup_formation.py

**Qualification difference:** Implement policy partitioning, AFI isolation, BGP Monitor assertions, and TestConfig wiring.

### QUAL-UG-14: Scale Withdraw — 10+ Peers in Same Group, Withdraw Routes

- **Playbook:** `bgp_ug_scale_withdraw_10plus_peers`
- **Factory:** `create_bgp_ug_scale_withdraw_10plus_peers_playbook`
- **Implementation status:** skeleton
- **Requirements:** UG-2.5.2 (direct)
- **Required topology:** `neteng.test_infra.dne.taac.abstractions.topologies.ebb_full_scale.ebb_full_scale_topology`
- **Cadence:** Not scheduled; skeleton.
- **Enforcement:** informational

**Purpose:** Verify withdrawal fan-out and final route removal across a large peer group.

**Stimulus:** Advertise 1,000 prefixes, withdraw all of them, and verify every peer after 60 seconds.

**Scale:** 252 iBGP peers in the source plan plus BGP Monitor.

**Blocking signals**

- Every group member and BGP Monitor removes all 1,000 prefixes.
- No session flap, stale route, or BGP++ crash occurs.

**Outcome validation traceability**

- **Health-check chain:** `not_implemented`
- **Check profile:** None
- **Implementation:** `Skeleton factory raising NotImplementedError`

The chain below contains only playbook-level health checks. Trigger, step, task, and periodic-monitor assertions are not counted as health-check coverage.

No playbook-level health-check chain is implemented.

**Specification vs. implemented health checks**

| Required Validation | Implemented By | Coverage | Gap |
| --- | --- | --- | --- |
| Every group member and BGP Monitor removes all 1,000 prefixes. | None | missing | Factory raises NotImplementedError. |
| No session flap, stale route, or BGP++ crash occurs. | None | missing | No runnable health-check chain exists. |

**Validations outside the health-check chain**

- None.

**Expected runtime:** Approximately 5 minutes.

**Primary triage signals**

- skeleton factory status
- planned IXIA route counts
- planned session and crash checks

**Artifacts**

- playbooks/routing/factories/qual_bgp_update_group/tc5_multigroup_formation.py
- testconfigs/routing/factories/qual_bgp_update_group/tc5_multigroup_formation.py

**Qualification difference:** Implement full-member withdrawal verification and TestConfig wiring.

## Bit Allocation and Group Stability Under Flaps

### QUAL-UG-15: Repeated Peer Flaps — Group Remains Stable

- **Playbook:** `bgp_ug_repeated_peer_flaps_group_stable`
- **Factory:** `create_bgp_ug_repeated_peer_flaps_group_stable_playbook`
- **Implementation status:** skeleton
- **Requirements:** UG-2.6.1 (direct)
- **Required topology:** `neteng.test_infra.dne.taac.abstractions.topologies.ebb_full_scale.ebb_full_scale_topology`
- **Cadence:** Not scheduled; skeleton.
- **Enforcement:** informational

**Purpose:** Detect membership-bit exhaustion, corruption, or leakage during rapid join and leave cycles.

**Stimulus:** Flap 32 eBGP peers for 50 cycles while continuously injecting and withdrawing routes.

**Scale:** Fifty five-second-down and five-second-up cycles plus runtime route churn.

**Blocking signals**

- All flapped peers rejoin the correct group and receive routes after the final recovery.
- VmHWM growth stays below 200 MB with no bit errors, crash, or load-average breach.

**Outcome validation traceability**

- **Health-check chain:** `not_implemented`
- **Check profile:** None
- **Implementation:** `Skeleton factory raising NotImplementedError`

The chain below contains only playbook-level health checks. Trigger, step, task, and periodic-monitor assertions are not counted as health-check coverage.

No playbook-level health-check chain is implemented.

**Specification vs. implemented health checks**

| Required Validation | Implemented By | Coverage | Gap |
| --- | --- | --- | --- |
| All flapped peers rejoin the correct group and receive routes after the final recovery. | None | missing | Factory raises NotImplementedError. |
| VmHWM growth stays below 200 MB with no bit errors, crash, or load-average breach. | None | missing | No runnable resource or corruption validation exists. |

**Validations outside the health-check chain**

- None.

**Expected runtime:** Approximately 10 minutes.

**Primary triage signals**

- skeleton factory status
- planned bit-allocation diagnostics
- planned memory and load metrics

**Artifacts**

- playbooks/routing/factories/qual_bgp_update_group/tc6_bit_alloc_group_stab_under_flap.py
- testconfigs/routing/factories/qual_bgp_update_group/tc6_bit_alloc_group_stab_under_flap.py

**Qualification difference:** Implement flap scheduling, membership integrity checks, memory delta gating, and TestConfig wiring.

## Disruption and Recovery

### QUAL-UG-16: Link Flap — Update Group Recovery After Physical Link Bounces

- **Playbook:** `bgp_ug_link_flap_recovery`
- **Factory:** `create_bgp_ug_link_flap_recovery_playbook`
- **Implementation status:** skeleton
- **Requirements:** UG-2.7.1 (direct)
- **Required topology:** `neteng.test_infra.dne.taac.abstractions.topologies.ebb_full_scale.ebb_full_scale_topology`
- **Cadence:** Not scheduled; skeleton.
- **Enforcement:** informational

**Purpose:** Verify physical-link recovery cannot leave orphaned members or interrupt unaffected groups.

**Stimulus:** Flap the eBGP IXIA port ten times, inject routes while down, and compare final membership and memory.

**Scale:** Ten 30-second-down and 30-second-up cycles at EBB peer scale.

**Blocking signals**

- Unaffected groups continue distributing and returning peers receive routes learned during link-down.
- Final membership matches baseline with memory growth below 200 MB and no crash or error logs.

**Outcome validation traceability**

- **Health-check chain:** `not_implemented`
- **Check profile:** None
- **Implementation:** `Skeleton factory raising NotImplementedError`

The chain below contains only playbook-level health checks. Trigger, step, task, and periodic-monitor assertions are not counted as health-check coverage.

No playbook-level health-check chain is implemented.

**Specification vs. implemented health checks**

| Required Validation | Implemented By | Coverage | Gap |
| --- | --- | --- | --- |
| Unaffected groups continue distributing and returning peers receive routes learned during link-down. | None | missing | Factory raises NotImplementedError. |
| Final membership matches baseline with memory growth below 200 MB and no crash or error logs. | None | missing | No runnable recovery or resource validation exists. |

**Validations outside the health-check chain**

- None.

**Expected runtime:** Approximately 15 minutes.

**Primary triage signals**

- skeleton factory status
- planned link and membership transitions
- planned memory and log checks

**Artifacts**

- playbooks/routing/factories/qual_bgp_update_group/tc7_disruption_recovery.py
- testconfigs/routing/factories/qual_bgp_update_group/tc7_disruption_recovery.py

**Qualification difference:** Implement the single-link recovery sequence and TestConfig wiring.

### QUAL-UG-17: Sustained Link Flapping Across Multiple Ports

- **Playbook:** `update_group_sustained_link_flap`
- **Factory:** `create_bgp_ug_sustained_link_flap_playbook`
- **Implementation status:** implemented
- **Requirements:** UG-2.7.2 (direct)
- **Required topology:** `neteng.test_infra.dne.taac.abstractions.topologies.ebb_full_scale.ebb_full_scale_topology`
- **Cadence:** Per qualification candidate.
- **Enforcement:** blocking

**Purpose:** Verify cross-group isolation and final recovery during sustained multi-port link flapping.

**Stimulus:** Flap three IXIA-facing ports for 15 seconds on two-, three-, and five-minute periods for one hour.

**Scale:** Production one-hour schedule on the bag013 EBB-scale conveyor topology.

**Blocking signals**

- Peers on non-flapped ports remain healthy and update-group isolation holds during every cycle.
- All groups recover with correct membership, bounded resources, and no crash or stale state.

**Outcome validation traceability**

- **Health-check chain:** `update_group_standard`
- **Check profile:** None
- **Implementation:** `Factory-specific prechecks, postchecks, and snapshot checks`

The chain below contains only playbook-level health checks. Trigger, step, task, and periodic-monitor assertions are not counted as health-check coverage.

| Phase | Chain ID | Implemented Health Checks | Notes |
| --- | --- | --- | --- |
| precheck | `pre.update_group` | `update group feature enabled or disabled as required by the variant`, `expected BGP sessions established`, `baseline update-group structure and resource health` | Establishes the feature, session, and resource baseline before the workload. |
| postcheck | `post.update_group` | `expected BGP sessions established`, `update-group structure and membership`, `BGP and system logs`, `CPU, load-average, and VmHWM thresholds` | Enforces final control-plane recovery and resource bounds where the factory supplies them. |
| snapshot | `snapshot.standard` | `core-dump snapshot`, `BGP session flap, uptime, and peer-identity snapshot` | Detects crashes and unexpected session drift around the workload. |

**Specification vs. implemented health checks**

| Required Validation | Implemented By | Coverage | Gap |
| --- | --- | --- | --- |
| Peers on non-flapped ports remain healthy and update-group isolation holds during every cycle. | `pre.update_group`, `post.update_group` | partial | Per-cycle interface isolation is enforced inside the sustained-flap step. |
| All groups recover with correct membership, bounded resources, and no crash or stale state. | `post.update_group`, `snapshot.standard` | implemented | None |

**Validations outside the health-check chain**

- The sustained-link-flap step validates expected and unexpected peer transitions for each scheduled interface.

**Expected runtime:** Slightly over one hour.

**Primary triage signals**

- interface state and flap schedule
- per-subnet BGP sessions
- update-group membership and resources

**Artifacts**

- playbooks/routing/factories/qual_bgp_update_group/tc7_disruption_recovery.py
- testconfigs/routing/factories/qual_bgp_update_group/tc7_disruption_recovery.py

**Qualification difference:** The production schedule is enabled; current TestConfig omits BGP Monitor sessions despite retaining a monitor-facing port schedule.

### QUAL-UG-18: BGP Peer Flapping — Rapid Session Bounces Within Update Group

- **Playbook:** `bgp_ug_bgp_peer_flapping`
- **Factory:** `create_bgp_ug_bgp_peer_flapping_playbook`
- **Implementation status:** skeleton
- **Requirements:** UG-2.7.3 (direct)
- **Required topology:** `neteng.test_infra.dne.taac.abstractions.topologies.ebb_full_scale.ebb_full_scale_topology`
- **Cadence:** Not scheduled; skeleton.
- **Enforcement:** informational

**Purpose:** Verify thirty minutes of individual peer bounces without leakage, corruption, or missed route churn.

**Stimulus:** Flap 64 eBGP peers every five seconds while stable peers inject and withdraw routes.

**Scale:** Thirty-minute peer churn at EBB scale.

**Blocking signals**

- Stable iBGP peers receive every route operation and flapped peers fully resynchronize.
- Final membership matches baseline with memory growth below 200 MB and no crash or error logs.

**Outcome validation traceability**

- **Health-check chain:** `not_implemented`
- **Check profile:** None
- **Implementation:** `Skeleton factory raising NotImplementedError`

The chain below contains only playbook-level health checks. Trigger, step, task, and periodic-monitor assertions are not counted as health-check coverage.

No playbook-level health-check chain is implemented.

**Specification vs. implemented health checks**

| Required Validation | Implemented By | Coverage | Gap |
| --- | --- | --- | --- |
| Stable iBGP peers receive every route operation and flapped peers fully resynchronize. | None | missing | Factory raises NotImplementedError. |
| Final membership matches baseline with memory growth below 200 MB and no crash or error logs. | None | missing | No runnable resource or recovery validation exists. |

**Validations outside the health-check chain**

- None.

**Expected runtime:** Approximately 35 minutes.

**Primary triage signals**

- skeleton factory status
- planned peer flap counters
- planned route and memory checkpoints

**Artifacts**

- playbooks/routing/factories/qual_bgp_update_group/tc7_disruption_recovery.py
- testconfigs/routing/factories/qual_bgp_update_group/tc7_disruption_recovery.py

**Qualification difference:** Implement per-peer flap scheduling, route-churn verification, and TestConfig wiring.

### QUAL-UG-19: BGP Daemon Restart — Update Group Reconstruction

- **Playbook:** `bgp_ug_bgp_daemon_restart`
- **Factory:** `create_bgp_ug_bgp_daemon_restart_playbook`
- **Implementation status:** skeleton
- **Requirements:** UG-2.7.4 (direct)
- **Required topology:** `neteng.test_infra.dne.taac.abstractions.topologies.ebb_full_scale.ebb_full_scale_topology`
- **Cadence:** Not scheduled; skeleton.
- **Enforcement:** informational

**Purpose:** Verify complete update-group reconstruction after BGP++ service restart.

**Stimulus:** Snapshot group and route state, restart BGP++, measure convergence, inject 100 routes, and soak for 30 minutes.

**Scale:** Full EBB topology with a ten-minute convergence bound and 30-minute soak.

**Blocking signals**

- Post-restart membership and route counts match baseline and runtime distribution resumes within ten minutes.
- Hardware, memory, CPU, logs, withdrawals, and post-convergence quiescence satisfy the source criteria.

**Outcome validation traceability**

- **Health-check chain:** `not_implemented`
- **Check profile:** None
- **Implementation:** `Skeleton factory raising NotImplementedError`

The chain below contains only playbook-level health checks. Trigger, step, task, and periodic-monitor assertions are not counted as health-check coverage.

No playbook-level health-check chain is implemented.

**Specification vs. implemented health checks**

| Required Validation | Implemented By | Coverage | Gap |
| --- | --- | --- | --- |
| Post-restart membership and route counts match baseline and runtime distribution resumes within ten minutes. | None | missing | Factory raises NotImplementedError. |
| Hardware, memory, CPU, logs, withdrawals, and post-convergence quiescence satisfy the source criteria. | None | missing | No runnable restart health-check chain exists. |

**Validations outside the health-check chain**

- None.

**Expected runtime:** Approximately 45 minutes.

**Primary triage signals**

- skeleton factory status
- planned group snapshots and convergence timing
- planned hardware and process metrics

**Artifacts**

- playbooks/routing/factories/qual_bgp_update_group/tc7_disruption_recovery.py
- testconfigs/routing/factories/qual_bgp_update_group/tc7_disruption_recovery.py

**Qualification difference:** Reuse the EBB restart primitives while adding exact pre/post group reconstruction checks.

### QUAL-UG-20: Cold Start — Update Group Formation From Zero State

- **Playbook:** `bgp_ug_cold_start`
- **Factory:** `create_bgp_ug_cold_start_playbook`
- **Implementation status:** skeleton
- **Requirements:** UG-2.7.5 (direct)
- **Required topology:** `neteng.test_infra.dne.taac.abstractions.topologies.ebb_full_scale.ebb_full_scale_topology`
- **Cadence:** Not scheduled; skeleton.
- **Enforcement:** informational

**Purpose:** Verify dynamic group formation and convergence when BGP++ begins with no established sessions.

**Stimulus:** Start all IXIA sessions simultaneously, observe group formation and last UPDATE, inject 100 routes, and soak.

**Scale:** Full EBB topology with a ten-minute convergence bound and 30-minute soak.

**Blocking signals**

- Groups form correctly, peers receive identical routes, and convergence completes within ten minutes.
- Runtime distribution, hardware capacity, resource, log, withdrawal, and quiescence criteria pass.

**Outcome validation traceability**

- **Health-check chain:** `not_implemented`
- **Check profile:** None
- **Implementation:** `Skeleton factory raising NotImplementedError`

The chain below contains only playbook-level health checks. Trigger, step, task, and periodic-monitor assertions are not counted as health-check coverage.

No playbook-level health-check chain is implemented.

**Specification vs. implemented health checks**

| Required Validation | Implemented By | Coverage | Gap |
| --- | --- | --- | --- |
| Groups form correctly, peers receive identical routes, and convergence completes within ten minutes. | None | missing | Factory raises NotImplementedError. |
| Runtime distribution, hardware capacity, resource, log, withdrawal, and quiescence criteria pass. | None | missing | No runnable cold-start validation chain exists. |

**Validations outside the health-check chain**

- None.

**Expected runtime:** Approximately 40 minutes.

**Primary triage signals**

- skeleton factory status
- planned convergence and group formation
- planned hardware and process metrics

**Artifacts**

- playbooks/routing/factories/qual_bgp_update_group/tc7_disruption_recovery.py
- testconfigs/routing/factories/qual_bgp_update_group/tc7_disruption_recovery.py

**Qualification difference:** Implement zero-state setup, group-formation timing, runtime distribution, and TestConfig wiring.

### QUAL-UG-21: FibAgent Restart — Update Group Stability During Data-Plane Agent Recovery

- **Playbook:** `bgp_ug_fibagent_restart`
- **Factory:** `create_bgp_ug_fibagent_restart_playbook`
- **Implementation status:** skeleton
- **Requirements:** UG-2.7.6 (direct)
- **Required topology:** `neteng.test_infra.dne.taac.abstractions.topologies.ebb_full_scale.ebb_full_scale_topology`
- **Cadence:** Not scheduled; skeleton.
- **Enforcement:** informational

**Purpose:** Prove control-plane update-group isolation from data-plane agent recovery.

**Stimulus:** Restart FibAgent, compare membership and route counts, inject and withdraw 100 routes, then soak.

**Scale:** Full EBB topology with hardware-capacity verification and a 30-minute soak.

**Blocking signals**

- No BGP session or group membership changes occur during FibAgent restart.
- Runtime route operations and hardware, resource, and log checks pass after recovery.

**Outcome validation traceability**

- **Health-check chain:** `not_implemented`
- **Check profile:** None
- **Implementation:** `Skeleton factory raising NotImplementedError`

The chain below contains only playbook-level health checks. Trigger, step, task, and periodic-monitor assertions are not counted as health-check coverage.

No playbook-level health-check chain is implemented.

**Specification vs. implemented health checks**

| Required Validation | Implemented By | Coverage | Gap |
| --- | --- | --- | --- |
| No BGP session or group membership changes occur during FibAgent restart. | None | missing | Factory raises NotImplementedError. |
| Runtime route operations and hardware, resource, and log checks pass after recovery. | None | missing | No runnable FibAgent recovery chain exists. |

**Validations outside the health-check chain**

- None.

**Expected runtime:** Approximately 40 minutes.

**Primary triage signals**

- skeleton factory status
- planned BGP and FibAgent lifecycle
- planned hardware and process metrics

**Artifacts**

- playbooks/routing/factories/qual_bgp_update_group/tc7_disruption_recovery.py
- testconfigs/routing/factories/qual_bgp_update_group/tc7_disruption_recovery.py

**Qualification difference:** Implement FibAgent lifecycle control, pre/post group snapshots, and TestConfig wiring.

## Edge Cases and Adversarial Scenarios

### QUAL-UG-22: Best-Path Change During Active Distribution

- **Playbook:** `bgp_ug_best_path_change`
- **Factory:** `create_bgp_ug_best_path_change_playbook`
- **Implementation status:** implemented
- **Requirements:** UG-2.9.1 (direct)
- **Required topology:** `neteng.test_infra.dne.taac.abstractions.topologies.ebb_full_scale.ebb_full_scale_topology`
- **Cadence:** Per qualification candidate while the per-peer attribute gate is calibrated.
- **Enforcement:** calibrating

**Purpose:** Detect split-brain or stale best-path state when a higher-local-preference path arrives during distribution.

**Stimulus:** Advertise 500 prefixes at LOCAL_PREF 100, switch to 200, then alternate the preference every ten seconds.

**Scale:** 500 prefixes over five minutes of best-path oscillation.

**Blocking signals**

- All peers converge to the same final best path without stale LOCAL_PREF state.
- BGP++ remains crash-free and session, group, log, and snapshot checks pass.

**Outcome validation traceability**

- **Health-check chain:** `update_group_standard`
- **Check profile:** None
- **Implementation:** `Factory-specific prechecks, postchecks, and snapshot checks`

The chain below contains only playbook-level health checks. Trigger, step, task, and periodic-monitor assertions are not counted as health-check coverage.

| Phase | Chain ID | Implemented Health Checks | Notes |
| --- | --- | --- | --- |
| precheck | `pre.update_group` | `update group feature enabled or disabled as required by the variant`, `expected BGP sessions established`, `baseline update-group structure and resource health` | Establishes the feature, session, and resource baseline before the workload. |
| postcheck | `post.update_group` | `expected BGP sessions established`, `update-group structure and membership`, `BGP and system logs`, `CPU, load-average, and VmHWM thresholds` | Enforces final control-plane recovery and resource bounds where the factory supplies them. |
| snapshot | `snapshot.standard` | `core-dump snapshot`, `BGP session flap, uptime, and peer-identity snapshot` | Detects crashes and unexpected session drift around the workload. |

**Specification vs. implemented health checks**

| Required Validation | Implemented By | Coverage | Gap |
| --- | --- | --- | --- |
| All peers converge to the same final best path without stale LOCAL_PREF state. | `post.update_group` | partial | The current PS-gauge probe is measure-first and does not hard-gate every peer's final LOCAL_PREF. |
| BGP++ remains crash-free and session, group, log, and snapshot checks pass. | `post.update_group`, `snapshot.standard` | implemented | None |

**Validations outside the health-check chain**

- Step-local route operations and PS-gauge probes exercise the best-path transition sequence.

**Expected runtime:** Approximately 8 minutes.

**Primary triage signals**

- per-peer PS gauge
- route attributes
- update-group structure and logs

**Artifacts**

- playbooks/routing/factories/qual_bgp_update_group/tc9_edge_cases.py
- testconfigs/routing/factories/qual_bgp_update_group/tc9_edge_cases.py

**Qualification difference:** Add a blocking every-peer final-LOCAL_PREF assertion to close the source-plan outcome fully.

### QUAL-UG-23: Simultaneous Disruptions Across All Groups

- **Playbook:** `bgp_ug_simultaneous_disruptions`
- **Factory:** `create_bgp_ug_simultaneous_disruptions_playbook`
- **Implementation status:** implemented
- **Requirements:** UG-2.9.2 (direct)
- **Required topology:** `neteng.test_infra.dne.taac.abstractions.topologies.ebb_full_scale.ebb_full_scale_topology`
- **Cadence:** Per qualification candidate.
- **Enforcement:** blocking

**Purpose:** Stress internal update-group state with four independent disruption tracks running together.

**Stimulus:** Run route churn, peer flaps, IGP metric changes, and LOCAL_PREF churn concurrently for 30 minutes.

**Scale:** Thirty-minute multi-track workload plus a five-minute recovery window.

**Blocking signals**

- iBGP stays established and final routes and attributes converge after all disruption tracks stop.
- Memory growth stays below 500 MB with no crash, core dump, error log, or load-average breach.

**Outcome validation traceability**

- **Health-check chain:** `update_group_standard`
- **Check profile:** None
- **Implementation:** `Factory-specific prechecks, postchecks, and snapshot checks`

The chain below contains only playbook-level health checks. Trigger, step, task, and periodic-monitor assertions are not counted as health-check coverage.

| Phase | Chain ID | Implemented Health Checks | Notes |
| --- | --- | --- | --- |
| precheck | `pre.update_group` | `update group feature enabled or disabled as required by the variant`, `expected BGP sessions established`, `baseline update-group structure and resource health` | Establishes the feature, session, and resource baseline before the workload. |
| postcheck | `post.update_group` | `expected BGP sessions established`, `update-group structure and membership`, `BGP and system logs`, `CPU, load-average, and VmHWM thresholds` | Enforces final control-plane recovery and resource bounds where the factory supplies them. |
| snapshot | `snapshot.standard` | `core-dump snapshot`, `BGP session flap, uptime, and peer-identity snapshot` | Detects crashes and unexpected session drift around the workload. |

**Specification vs. implemented health checks**

| Required Validation | Implemented By | Coverage | Gap |
| --- | --- | --- | --- |
| iBGP stays established and final routes and attributes converge after all disruption tracks stop. | `pre.update_group`, `post.update_group` | partial | Track scheduling and per-operation correctness are step-local. |
| Memory growth stays below 500 MB with no crash, core dump, error log, or load-average breach. | `post.update_group`, `snapshot.standard` | implemented | None |

**Validations outside the health-check chain**

- Four step-local tracks and periodic monitors assert route, session, attribute, and IGP activity during the run.

**Expected runtime:** Approximately 35 minutes.

**Primary triage signals**

- per-track operation logs
- BGP session and route state
- Open/R metrics
- memory and load averages

**Artifacts**

- playbooks/routing/factories/qual_bgp_update_group/tc9_edge_cases.py
- testconfigs/routing/factories/qual_bgp_update_group/tc9_edge_cases.py

**Qualification difference:** The Open/R-enabled TestConfig supplies all four source-plan disruption tracks.

### QUAL-UG-24: NOTIFICATION Sent to One Peer — Group Isolation

- **Playbook:** `bgp_ug_notification_isolation`
- **Factory:** `create_bgp_ug_notification_isolation_playbook`
- **Implementation status:** implemented
- **Requirements:** UG-2.9.3 (direct)
- **Required topology:** `neteng.test_infra.dne.taac.abstractions.topologies.ebb_full_scale.ebb_full_scale_topology`
- **Cadence:** Per qualification candidate.
- **Enforcement:** blocking

**Purpose:** Prove that a single peer teardown cannot disrupt the rest of its update group.

**Stimulus:** Trigger one v4 and one v6 peer timeout, verify survivor distribution, then recover the peers.

**Scale:** One targeted peer per AFI with EBB-scale unaffected sessions.

**Blocking signals**

- Only targeted peers go down while remaining peers and runtime distribution continue normally.
- Recovered peers fully resynchronize with no crash or unexpected error logs.

**Outcome validation traceability**

- **Health-check chain:** `update_group_standard`
- **Check profile:** None
- **Implementation:** `Factory-specific prechecks, postchecks, and snapshot checks`

The chain below contains only playbook-level health checks. Trigger, step, task, and periodic-monitor assertions are not counted as health-check coverage.

| Phase | Chain ID | Implemented Health Checks | Notes |
| --- | --- | --- | --- |
| precheck | `pre.update_group` | `update group feature enabled or disabled as required by the variant`, `expected BGP sessions established`, `baseline update-group structure and resource health` | Establishes the feature, session, and resource baseline before the workload. |
| postcheck | `post.update_group` | `expected BGP sessions established`, `update-group structure and membership`, `BGP and system logs`, `CPU, load-average, and VmHWM thresholds` | Enforces final control-plane recovery and resource bounds where the factory supplies them. |
| snapshot | `snapshot.standard` | `core-dump snapshot`, `BGP session flap, uptime, and peer-identity snapshot` | Detects crashes and unexpected session drift around the workload. |

**Specification vs. implemented health checks**

| Required Validation | Implemented By | Coverage | Gap |
| --- | --- | --- | --- |
| Only targeted peers go down while remaining peers and runtime distribution continue normally. | `pre.update_group`, `post.update_group` | partial | Target isolation and runtime route progress are step-local assertions. |
| Recovered peers fully resynchronize with no crash or unexpected error logs. | `post.update_group`, `snapshot.standard` | implemented | None |

**Validations outside the health-check chain**

- Step-local hold-timer, survivor-session, route-progress, and recovery checks enforce isolation for both AFIs.

**Expected runtime:** Approximately 10 minutes.

**Primary triage signals**

- targeted session notifications
- survivor route counters
- group membership and logs

**Artifacts**

- playbooks/routing/factories/qual_bgp_update_group/tc9_edge_cases.py
- testconfigs/routing/factories/qual_bgp_update_group/tc9_edge_cases.py

**Qualification difference:** Uses deterministic hold-timer expiry rather than malformed packet injection to trigger peer-specific NOTIFICATION behavior.

### QUAL-UG-25: Dual-Stack Isolation — IPv4 Operations Do Not Affect IPv6 Group

- **Playbook:** `bgp_ug_dual_stack_isolation`
- **Factory:** `create_bgp_ug_dual_stack_isolation_playbook`
- **Implementation status:** implemented
- **Requirements:** UG-2.9.4 (direct)
- **Required topology:** `neteng.test_infra.dne.taac.abstractions.topologies.ebb_full_scale.ebb_full_scale_topology`
- **Cadence:** Per qualification candidate.
- **Enforcement:** blocking

**Purpose:** Prevent cross-AFI leakage or unintended route-count changes during sequential and simultaneous operations.

**Stimulus:** Add IPv4 routes, withdraw IPv6 routes, then perform both operations concurrently.

**Scale:** 500-route and 200-route single-AFI operations plus a simultaneous 100-route transition.

**Blocking signals**

- Each AFI changes only its own peers and every post-operation route count is exact.
- AFI-specific groups remain separate with all sessions healthy and no crash.

**Outcome validation traceability**

- **Health-check chain:** `update_group_standard`
- **Check profile:** None
- **Implementation:** `Factory-specific prechecks, postchecks, and snapshot checks`

The chain below contains only playbook-level health checks. Trigger, step, task, and periodic-monitor assertions are not counted as health-check coverage.

| Phase | Chain ID | Implemented Health Checks | Notes |
| --- | --- | --- | --- |
| precheck | `pre.update_group` | `update group feature enabled or disabled as required by the variant`, `expected BGP sessions established`, `baseline update-group structure and resource health` | Establishes the feature, session, and resource baseline before the workload. |
| postcheck | `post.update_group` | `expected BGP sessions established`, `update-group structure and membership`, `BGP and system logs`, `CPU, load-average, and VmHWM thresholds` | Enforces final control-plane recovery and resource bounds where the factory supplies them. |
| snapshot | `snapshot.standard` | `core-dump snapshot`, `BGP session flap, uptime, and peer-identity snapshot` | Detects crashes and unexpected session drift around the workload. |

**Specification vs. implemented health checks**

| Required Validation | Implemented By | Coverage | Gap |
| --- | --- | --- | --- |
| Each AFI changes only its own peers and every post-operation route count is exact. | `post.update_group` | partial | Per-AFI route-count deltas and zero-cross-leakage proofs are step-local. |
| AFI-specific groups remain separate with all sessions healthy and no crash. | `pre.update_group`, `post.update_group`, `snapshot.standard` | implemented | None |

**Validations outside the health-check chain**

- Step-local PS-gauge snapshots and exact per-AFI deltas enforce isolation after every operation.

**Expected runtime:** Approximately 10 minutes.

**Primary triage signals**

- per-AFI PS gauge
- v4 and v6 update-group structure
- session state and core dumps

**Artifacts**

- playbooks/routing/factories/qual_bgp_update_group/tc9_edge_cases.py
- testconfigs/routing/factories/qual_bgp_update_group/tc9_edge_cases.py

**Qualification difference:** Requires the Open/R TestConfig so per-AFI sent-prefix gauges are meaningful.

### QUAL-UG-26: Staggered Peer Startup — Peers Coming Up at Different Times

- **Playbook:** `bgp_ug_staggered_startup`
- **Factory:** `create_bgp_ug_staggered_startup_playbook`
- **Implementation status:** implemented
- **Requirements:** UG-2.9.6 (direct)
- **Required topology:** `neteng.test_infra.dne.taac.abstractions.topologies.ebb_full_scale.ebb_full_scale_topology`
- **Cadence:** Per qualification candidate.
- **Enforcement:** blocking

**Purpose:** Verify late joiners catch up fully when update-group members establish at staggered times.

**Stimulus:** Start eBGP peers in three waves separated by two minutes and add routes between waves.

**Scale:** Source-plan waves of 50, 100, and remaining peers with 100 routes added between waves.

**Blocking signals**

- Each wave receives all routes accumulated before it joined and final counts match across peers.
- Post-start runtime distribution succeeds with no stale routes, crash, or session failure.

**Outcome validation traceability**

- **Health-check chain:** `update_group_standard`
- **Check profile:** None
- **Implementation:** `Factory-specific prechecks, postchecks, and snapshot checks`

The chain below contains only playbook-level health checks. Trigger, step, task, and periodic-monitor assertions are not counted as health-check coverage.

| Phase | Chain ID | Implemented Health Checks | Notes |
| --- | --- | --- | --- |
| precheck | `pre.update_group` | `update group feature enabled or disabled as required by the variant`, `expected BGP sessions established`, `baseline update-group structure and resource health` | Establishes the feature, session, and resource baseline before the workload. |
| postcheck | `post.update_group` | `expected BGP sessions established`, `update-group structure and membership`, `BGP and system logs`, `CPU, load-average, and VmHWM thresholds` | Enforces final control-plane recovery and resource bounds where the factory supplies them. |
| snapshot | `snapshot.standard` | `core-dump snapshot`, `BGP session flap, uptime, and peer-identity snapshot` | Detects crashes and unexpected session drift around the workload. |

**Specification vs. implemented health checks**

| Required Validation | Implemented By | Coverage | Gap |
| --- | --- | --- | --- |
| Each wave receives all routes accumulated before it joined and final counts match across peers. | `post.update_group` | partial | Per-wave full-dump and route-delta assertions are step-local. |
| Post-start runtime distribution succeeds with no stale routes, crash, or session failure. | `post.update_group`, `snapshot.standard` | implemented | None |

**Validations outside the health-check chain**

- Step-local wave toggles, iBGP isolation checks, and per-wave sent-route deltas enforce catch-up behavior.

**Expected runtime:** Approximately 10 minutes.

**Primary triage signals**

- wave-specific session state
- sent-route deltas
- update-group membership and logs

**Artifacts**

- playbooks/routing/factories/qual_bgp_update_group/tc9_edge_cases.py
- testconfigs/routing/factories/qual_bgp_update_group/tc9_edge_cases.py

**Qualification difference:** Runs without Open/R using interface-state next-hop resolution and excludes BGP Monitor.

### QUAL-UG-27: Empty Group — Last Peer Goes Down Without Detached Peers

- **Playbook:** `bgp_ug_empty_group`
- **Factory:** `create_bgp_ug_empty_group_playbook`
- **Implementation status:** implemented
- **Requirements:** UG-2.9.7 (direct)
- **Required topology:** `neteng.test_infra.dne.taac.abstractions.topologies.ebb_full_scale.ebb_full_scale_topology`
- **Cadence:** Per qualification candidate.
- **Enforcement:** blocking

**Purpose:** Verify zero-member groups and the all-groups-empty state are safe and reconstruct cleanly.

**Stimulus:** Stop all eBGP peers, then all iBGP peers, wait in each empty state, and recover both groups.

**Scale:** Full eBGP and iBGP peer populations on the shared EBB topology.

**Blocking signals**

- Empty-group states contain no stale membership and unaffected groups continue operating until also stopped.
- All groups reform with full route resync, bounded memory, and no crash or core dump.

**Outcome validation traceability**

- **Health-check chain:** `update_group_standard`
- **Check profile:** None
- **Implementation:** `Factory-specific prechecks, postchecks, and snapshot checks`

The chain below contains only playbook-level health checks. Trigger, step, task, and periodic-monitor assertions are not counted as health-check coverage.

| Phase | Chain ID | Implemented Health Checks | Notes |
| --- | --- | --- | --- |
| precheck | `pre.update_group` | `update group feature enabled or disabled as required by the variant`, `expected BGP sessions established`, `baseline update-group structure and resource health` | Establishes the feature, session, and resource baseline before the workload. |
| postcheck | `post.update_group` | `expected BGP sessions established`, `update-group structure and membership`, `BGP and system logs`, `CPU, load-average, and VmHWM thresholds` | Enforces final control-plane recovery and resource bounds where the factory supplies them. |
| snapshot | `snapshot.standard` | `core-dump snapshot`, `BGP session flap, uptime, and peer-identity snapshot` | Detects crashes and unexpected session drift around the workload. |

**Specification vs. implemented health checks**

| Required Validation | Implemented By | Coverage | Gap |
| --- | --- | --- | --- |
| Empty-group states contain no stale membership and unaffected groups continue operating until also stopped. | `pre.update_group`, `post.update_group` | partial | Intermediate empty-state membership and isolation assertions are step-local. |
| All groups reform with full route resync, bounded memory, and no crash or core dump. | `post.update_group`, `snapshot.standard` | implemented | None |

**Validations outside the health-check chain**

- Step-local zero-established-session, update-group membership, route distribution, and recovery checks enforce both empty states.

**Expected runtime:** Approximately 10 minutes.

**Primary triage signals**

- zero-member group state
- BGP session transitions
- route recovery
- VmHWM and core dumps

**Artifacts**

- playbooks/routing/factories/qual_bgp_update_group/tc9_edge_cases.py
- testconfigs/routing/factories/qual_bgp_update_group/tc9_edge_cases.py

**Qualification difference:** Current automation covers eBGP and iBGP emptying but omits the source-plan BGP Monitor group.

### QUAL-UG-28: Quantifying CPU Reduction from Update Group

- **Playbook:** `bgp_ug_cpu_quantification`
- **Factory:** `create_bgp_ug_cpu_quantification_playbook`
- **Implementation status:** implemented
- **Requirements:** UG-2.9.8 (direct)
- **Required topology:** `neteng.test_infra.dne.taac.abstractions.topologies.ebb_full_scale.ebb_full_scale_topology`
- **Cadence:** Per qualification candidate; run the off variant before the on variant.
- **Enforcement:** blocking

**Purpose:** Measure and gate the CPU reduction attributable to update-group computation and PDU serialization.

**Stimulus:** Run identical dual-stack 500-route-per-peer churn for one hour with the feature off, then one hour on.

**Scale:** Two one-hour EBB-scale variants with average and peak CPU, load, memory, and session monitoring.

**Blocking signals**

- The update-group-on run records measurably lower average CPU than the saved off-run baseline.
- Both variants stay below peak CPU, VmHWM, load, crash, and session-stability thresholds.

**Outcome validation traceability**

- **Health-check chain:** `update_group_standard`
- **Check profile:** None
- **Implementation:** `Factory-specific prechecks, postchecks, and snapshot checks`

The chain below contains only playbook-level health checks. Trigger, step, task, and periodic-monitor assertions are not counted as health-check coverage.

| Phase | Chain ID | Implemented Health Checks | Notes |
| --- | --- | --- | --- |
| precheck | `pre.update_group` | `update group feature enabled or disabled as required by the variant`, `expected BGP sessions established`, `baseline update-group structure and resource health` | Establishes the feature, session, and resource baseline before the workload. |
| postcheck | `post.update_group` | `expected BGP sessions established`, `update-group structure and membership`, `BGP and system logs`, `CPU, load-average, and VmHWM thresholds` | Enforces final control-plane recovery and resource bounds where the factory supplies them. |
| snapshot | `snapshot.standard` | `core-dump snapshot`, `BGP session flap, uptime, and peer-identity snapshot` | Detects crashes and unexpected session drift around the workload. |

**Specification vs. implemented health checks**

| Required Validation | Implemented By | Coverage | Gap |
| --- | --- | --- | --- |
| The update-group-on run records measurably lower average CPU than the saved off-run baseline. | `post.update_group` | partial | Cross-run metric persistence and comparison are step-local rather than playbook health checks. |
| Both variants stay below peak CPU, VmHWM, load, crash, and session-stability thresholds. | `pre.update_group`, `post.update_group`, `snapshot.standard` | implemented | None |

**Validations outside the health-check chain**

- The off variant writes baseline metrics and the on variant blocks on the paired average-CPU comparison.
- Periodic monitors enforce peak CPU, VmHWM, load-average, session, and crash thresholds during each hour.

**Expected runtime:** Slightly over two hours for the required off-then-on pair.

**Primary triage signals**

- persisted CPU metrics
- periodic process and load samples
- BGP sessions and core dumps

**Artifacts**

- playbooks/routing/factories/qual_bgp_update_group/tc9_edge_cases.py
- testconfigs/routing/factories/qual_bgp_update_group/tc9_edge_cases.py

**Qualification difference:** Automation uses pre-staged community variants and requires ordered UG-off then UG-on executions for a valid comparison.
