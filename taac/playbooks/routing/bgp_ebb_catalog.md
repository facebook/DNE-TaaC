# BGP++ EBB CI/CD Catalog

<!-- Generated from the adjacent YAML catalog. Do not edit directly. -->

Daily regression catalog for the 20 currently executable BGP++ EBB playbooks. Qualification and CI/CD have different purposes: this suite continuously detects revision regressions while maintaining representative coverage of Gate2 requirements G2-10 through G2-25. The planned 25-case target will add five catalog entries only when their executable playbooks land.

- **Owner:** `routing_qual`
- **Playbook module:** `neteng.test_infra.dne.taac.playbooks.routing.bgp_ebb_playbooks`

## Sources

- [Gate2 qualification requirements](https://docs.google.com/document/d/1lQy3aeTXRlXxtjxB1BotD84pqchghrWTb-T4FKRW-j4/edit?tab=t.bz5szmb672zh)
- [Gate1 qualification plan](https://docs.google.com/document/d/1vKjERKNSTg_kls1u4JAh84Sk1TJYu5kGX9iaxvpUiiM/edit?tab=t.0#heading=h.p9ark5ckrw4s)

## Required Topologies

| ID | Status | Artifact | Description |
| --- | --- | --- | --- |
| `ebb_full_scale` | modeled | `neteng.test_infra.dne.taac.abstractions.topologies.ebb_full_scale.ebb_full_scale_topology` | Canonical 1,274-peer EBB topology with eBGP, four iBGP planes, BGP-MON, dual-stack parent networks, and optional standalone Open/R. |
| `ipv6_update_packing` | modeled | `neteng.test_infra.dne.taac.abstractions.topologies.ipv6_update_packing.IPV6_UPDATE_PACKING` | Two-port IPv6 topology with eBGP ingress and iBGP capture egress used by the UPDATE-packing workflow. |
| `bounded_ecmp` | modeled | `neteng.test_infra.dne.taac.abstractions.topologies.bounded_ecmp.BOUNDED_ECMP` | Two-port update-group topology with bounded-ECMP routing groups and inspectable IXIA children. |
| `legacy_two_port_ebb` | legacy | Not modeled | Current two-port eBGP/iBGP wiring assembled by the BAG012 characteristic factories. Constant-attribute storage and queue/memory monitoring must migrate to a named topology artifact before this status can be modeled. |

## Catalog at a Glance

| ID | Test Case | Playbook | Gate2 Coverage | Topology | Enforcement |
| --- | --- | --- | --- | --- | --- |
| CICD-01 | BGP daemon restart | `bgp_ebb_daemon_restart_playbook` | G2-11 (direct) | `ebb_full_scale` | blocking |
| CICD-02 | BGP cold start | `bgp_ebb_cold_start_playbook` | G2-10 (direct) | `ebb_full_scale` | blocking |
| CICD-03 | eBGP session oscillation | `bgp_ebb_ebgp_session_oscillation_playbook` | G2-18 (direct) | `ebb_full_scale` | blocking |
| CICD-04 | iBGP plane session oscillation | `bgp_ebb_ibgp_plane_session_oscillation_playbook` | G2-19 (direct) | `ebb_full_scale` | blocking |
| CICD-05 | eBGP route oscillation | `bgp_ebb_ebgp_route_oscillation_playbook` | G2-20 (direct) | `ebb_full_scale` | blocking |
| CICD-06 | iBGP route oscillation | `bgp_ebb_ibgp_route_oscillation_playbook` | G2-21 (direct) | `ebb_full_scale` | blocking |
| CICD-07 | IGP PNH metric oscillation | `bgp_ebb_igp_pnh_metric_oscillation_playbook` | G2-13 (direct) | `ebb_full_scale` | blocking |
| CICD-08 | IGP unresolvable PNH | `bgp_ebb_igp_unresolvable_pnh_playbook` | G2-14 (direct) | `ebb_full_scale` | blocking |
| CICD-09 | Multipath-group oscillation | `bgp_ebb_multipath_group_oscillation_playbook` | G2-16 (direct) | `ebb_full_scale` | blocking |
| CICD-10 | BGP attribute churn | `bgp_ebb_attribute_churn_playbook` | G2-15 (direct) | `ebb_full_scale` | calibrating |
| CICD-11 | BGP route storm | `bgp_ebb_route_storm_playbook` | G2-17 (direct) | `ebb_full_scale` | calibrating |
| CICD-12 | Route-registry runtime update | `bgp_ebb_route_registry_runtime_update_playbook` | G2-24 (direct), G2-25 (supplemental) | `ebb_full_scale` | blocking |
| CICD-13 | FAUU drain and undrain | `bgp_ebb_fauu_drain_undrain_playbook` | G2-23 (direct) | `ebb_full_scale` | blocking |
| CICD-14 | Plane drain and undrain | `bgp_ebb_plane_drain_undrain_playbook` | G2-22 (direct) | `ebb_full_scale` | calibrating |
| CICD-15 | Longevity | `bgp_ebb_longevity_playbook` | G2-12 (proxy) | `ebb_full_scale` | calibrating |
| CICD-16 | Queue and memory monitoring | `bgp_ebb_queue_memory_monitoring_playbook` | G2-25 (supplemental) | `legacy_two_port_ebb` | calibrating |
| CICD-17 | Nexthop-group count threshold | `bgp_ebb_nexthop_group_count_threshold_playbook` | G2-25 (supplemental) | `ebb_full_scale` | calibrating |
| CICD-18 | UPDATE packing | `bgp_ebb_update_packing_playbook` | G2-25 (supplemental) | `ipv6_update_packing` | blocking |
| CICD-19 | Constant attribute storage | `bgp_ebb_constant_attribute_storage_playbook` | G2-25 (supplemental) | `legacy_two_port_ebb` | blocking |
| CICD-20 | Bounded ECMP sets | `bgp_ebb_bounded_ecmp_sets_playbook` | G2-25 (supplemental) | `bounded_ecmp` | calibrating |

## Requirement Coverage

| Requirement | Catalog Cases | Current Coverage |
| --- | --- | --- |
| G2-10 | CICD-02 (direct) | Start BGP++ at full scale and verify peer establishment and convergence. |
| G2-11 | CICD-01 (direct) | Restart BGP++ and verify full session and control-plane recovery. |
| G2-12 | CICD-15 (proxy) | Run a shortened community-churn soak as a daily continuous-operation signal. |
| G2-13 | CICD-07 (direct) | Oscillate IGP metrics for protocol nexthops without destabilizing BGP sessions. |
| G2-14 | CICD-08 (direct) | Make selected PNHs unresolvable and verify withdrawal and restoration behavior. |
| G2-15 | CICD-10 (direct) | Sustain multi-attribute route churn while preserving control-plane health. |
| G2-16 | CICD-09 (direct) | Change live multipath width and verify restoration to the measured baseline. |
| G2-17 | CICD-11 (direct) | Sustain large route advertise and withdraw cycles and verify recovery. |
| G2-18 | CICD-03 (direct) | Repeatedly flap eBGP sessions and verify final recovery. |
| G2-19 | CICD-04 (direct) | Flap iBGP sessions across all tornado planes and verify recovery. |
| G2-20 | CICD-05 (direct) | Repeatedly withdraw and readvertise eBGP routes and verify convergence. |
| G2-21 | CICD-06 (direct) | Repeatedly withdraw and readvertise iBGP routes and verify convergence. |
| G2-22 | CICD-14 (direct) | Drain and undrain iBGP planes while verifying convergence and peer views. |
| G2-23 | CICD-13 (direct) | Drain and undrain FAUU routes while verifying convergence and peer views. |
| G2-24 | CICD-12 (direct) | Apply prefix-list changes at runtime and verify expected route-count transitions. |
| G2-25 | CICD-12 (supplemental), CICD-16 (supplemental), CICD-17 (supplemental), CICD-18 (supplemental), CICD-19 (supplemental), CICD-20 (supplemental) | Assert one formal runtime-policy feature within the broader G2-25 umbrella. Monitor implementation queues and process memory during route churn and CPU stress. Bound nexthop-group growth while routes oscillate. Validate efficient IPv6 UPDATE packing under update-group-enabled distribution. Measure attribute-storage behavior as unique attribute combinations increase. Verify ECMP and nexthop-group state remains bounded under update-group-enabled scale. |

## Outcome Validation Coverage

This summary compares catalog-required blocking signals with the playbook-level health-check chains currently implemented. Step-local assertions and periodic monitors are reported separately and never upgrade health-check coverage.

| ID | Test Case | Health-check Coverage | Remaining Gap |
| --- | --- | --- | --- |
| CICD-01 | BGP daemon restart | Complete | None |
| CICD-02 | BGP cold start | Partial | CPU and memory are periodic tasks, not playbook-level health checks. |
| CICD-03 | eBGP session oscillation | Partial | Flap and uptime comparisons are skipped; resource limits are periodic tasks. |
| CICD-04 | iBGP plane session oscillation | Partial | The shared health-check profile is not evaluated independently per plane. Flap and uptime comparisons are skipped; resource limits are periodic tasks. |
| CICD-05 | eBGP route oscillation | Partial | Session uptime is skipped; resource checks are periodic tasks. |
| CICD-06 | iBGP route oscillation | Partial | Resource checks are periodic tasks, not playbook-level health checks. |
| CICD-07 | IGP PNH metric oscillation | Partial | No playbook-level health check validates the packet-message expectation. Cleanup executes route injection but has no post-cleanup health check. |
| CICD-08 | IGP unresolvable PNH | Partial | The health-check chain runs around the workload, not after cleanup restoration. Final session and RIB/FIB health are checked, but explicit convergence is disabled. Cleanup re-injects routes without a post-cleanup route-state health check. |
| CICD-09 | Multipath-group oscillation | Partial | Multipath width is asserted inside the oscillation stage, not by a health check. Baseline restoration is asserted inside the oscillation stage, not by a health check. |
| CICD-10 | BGP attribute churn | Partial | Only core dumps are snapshotted; resource monitors are non-blocking periodic tasks. RIB/FIB consistency is checked, but the explicit convergence health check is disabled. |
| CICD-11 | BGP route storm | Partial | Only core dumps are snapshotted; resource monitors are non-blocking periodic tasks. |
| CICD-12 | Route-registry runtime update | Partial | The health-check chain validates only the baseline count; transitions are stage-local assertions. Cleanup actions run after the health-check chain and have no post-cleanup check. |
| CICD-13 | FAUU drain and undrain | Partial | The profile disables the convergence health check; the limit is enforced inside the drain stage. Sessions are checked, but captured peer views are validated inside the stage. |
| CICD-14 | Plane drain and undrain | Partial | The profile disables the convergence health check; the limit is enforced inside the drain stage. Sessions are checked, but plane policy and captured views are stage-local validations. |
| CICD-15 | Longevity | Partial | Session and RIB/FIB state are checked, but the explicit convergence health check is disabled. Core dumps are checked, but this playbook has no CPU or memory periodic validation. |
| CICD-16 | Queue and memory monitoring | Partial | Session uptime is snapshotted, but BGP process liveness is validated only inside the custom step. Queue and memory thresholds have no playbook-level health check. The session snapshot excludes expected flaps; route-churn completion is custom-step-local. |
| CICD-17 | Nexthop-group count threshold | Partial | The threshold is enforced by a periodic task, not a playbook-level health check. |
| CICD-18 | UPDATE packing | Missing | Packing size is asserted only inside the custom step; no health-check chain exists. Custom-step completion is not a playbook-level health check. These conditions are handled inside the custom step with no independent health checks. |
| CICD-19 | Constant attribute storage | Missing | Route acceptance is asserted only inside the custom step; no health-check chain exists. Attribute collection is custom-step-local and has no independent health check. The memory-growth gate is custom-step-local and has no independent health check. |
| CICD-20 | Bounded ECMP sets | Partial | The threshold is enforced by a periodic task, not a playbook-level health check. |

## Coverage Notes

### G2-12 daily proxy status

CICD-15 is a provisional daily stability proxy, not equivalent to the 48-hour qualification workload.

**Asserted**

- Four hours of repeated community churn followed by quiesced health checks.
- Session recovery, crash freedom, snapshots, and CPU and memory trends.

**Exercised but not feature-complete**

- Full-scale peer and route state remains active throughout the soak.

**Gaps**

- Qualification-length 48-hour duration.
- Combined route churn, broader attribute churn, drains, and peer restarts.
- An approved blocking rule for long-term resource trends.

### G2-25 current feature coverage

The current 20 playbooks provide one explicit runtime-policy assertion and several supplemental scaling and implementation-health signals. They do not yet establish complete G2-25 feature qualification coverage.

**Asserted**

- CICD-12 validates per-AFI prefix-list updates and route-count transitions without restarting BGP++.
- CICD-16 monitors queue, process-memory, and liveness behavior under route churn and CPU stress.
- CICD-17 and CICD-20 bound nexthop-group and ECMP state during route churn.
- CICD-18 validates IPv6 UPDATE packing with update groups enabled.
- CICD-19 validates route acceptance and attribute-storage memory growth across unique-combination scale.

**Exercised but not feature-complete**

- MED, community, origin, and AS-path mutation during churn and drain workflows.
- Open/R metric changes, PNH withdrawal and restoration, and multipath recovery.
- Full-scale MP-BGP, RFC5549-style nexthops, and BGP-MON observation paths.

**Gaps**

- BGP weight support.
- Complete MED behavior, including missing-AS-worst.
- Enforce-first-as behavior.
- Netlink fast-neighbor teardown and latency.
- Dedicated update-group correctness, backpressure, and edge-case coverage.

# Test Cases

## Lifecycle and Session Stability

### CICD-01: BGP daemon restart

- **Playbook:** `bgp_ebb_daemon_restart_playbook`
- **Factory:** `get_bgp_ebb_daemon_restart_playbook`
- **Requirements:** G2-11 (direct)
- **Required topology:** `neteng.test_infra.dne.taac.abstractions.topologies.ebb_full_scale.ebb_full_scale_topology`
- **Cadence:** Daily.
- **Enforcement:** blocking

**Purpose:** Detect restart regressions in service recovery, convergence, and resource health.

**Stimulus:** Restart the BGP++ daemon, restore IXIA peers, and wait 540 seconds for convergence.

**Scale:** Canonical full-scale EBB peer and route population.

**Blocking signals**

- Restart profile prechecks and postchecks pass.
- Expected BGP sessions recover and remain established.
- Snapshot checks show no unexpected state drift or core dump.

**Outcome validation traceability**

- **Health-check chain:** `daemon_restart`
- **Check profile:** `CheckProfile.DAEMON_RESTART`
- **Implementation:** `get_profile_checks(CheckProfile.DAEMON_RESTART)`

The chain below contains only playbook-level health checks. Trigger, step, task, and periodic-monitor assertions are not counted as health-check coverage.

| Phase | Chain ID | Implemented Health Checks | Notes |
| --- | --- | --- | --- |
| precheck | `pre.standard_bgp` | `startup_bgp_session_verification`, `startup_cpu_load_average_baseline`, `startup_bgp_graceful_restart_disabled_check_v6`, `startup_bgp_graceful_restart_disabled_check_v4`, `startup_hardware_capacity_baseline`, `startup_bgp_convergence`, `startup_ibgp_pnh_verification`, `rib_fib_consistency_precheck` | The PNH check is present only for Open/R profiles. The remaining checks establish the session, resource, convergence, and RIB/FIB baseline. |
| postcheck | `post.restart_recovery` | `postcheck_bgp_convergence_time`, `BGP session establishment`, `BGP stale-route check`, `BGP and system log parsing`, `rib_fib_consistency_postcheck`, `restart-aware BGP service check` | Treats the intentional BGP restart as expected and detects later restarts. |
| snapshot | `snapshot.skip_uptime` | `core-dump snapshot check`, `BGP session flap and peer-identity snapshot check` | Session uptime is intentionally excluded. |

**Specification vs. implemented health checks**

| Required Validation | Implemented By | Coverage | Gap |
| --- | --- | --- | --- |
| Restart profile prechecks and postchecks pass. | `pre.standard_bgp`, `post.restart_recovery` | implemented | None |
| Expected BGP sessions recover and remain established. | `post.restart_recovery`, `snapshot.skip_uptime` | implemented | None |
| Snapshot checks show no unexpected state drift or core dump. | `snapshot.skip_uptime` | implemented | None |

**Validations outside the health-check chain**

- None.

**Expected runtime:** Approximately 34 minutes including shared topology setup.

**Primary triage signals**

- BGP service lifecycle and peer-state logs.
- Convergence timeline and failed peer identities.
- CPU and memory periodic-task samples.

**Artifacts**

- TAAC step and health-check results.
- BGP service logs and core-dump snapshot.
- CPU and memory time series.

**Qualification difference:** Daily CI performs one representative restart rather than the full qualification campaign.

### CICD-02: BGP cold start

- **Playbook:** `bgp_ebb_cold_start_playbook`
- **Factory:** `get_bgp_ebb_cold_start_playbook`
- **Requirements:** G2-10 (direct)
- **Required topology:** `neteng.test_infra.dne.taac.abstractions.topologies.ebb_full_scale.ebb_full_scale_topology`
- **Cadence:** Daily.
- **Enforcement:** blocking

**Purpose:** Detect cold-start regressions in session fan-in, EOR handling, and convergence.

**Stimulus:** Start BGP++ without active peers, enable all peer groups together, wait about 500 seconds, and collect thread CPU.

**Scale:** Canonical full-scale EBB peer and route population.

**Blocking signals**

- Cold-start profile checks pass.
- Expected sessions establish and convergence completes.
- Snapshot, CPU, and memory checks remain healthy.

**Outcome validation traceability**

- **Health-check chain:** `cold_start`
- **Check profile:** `CheckProfile.COLD_START`
- **Implementation:** `get_profile_checks(CheckProfile.COLD_START)`

The chain below contains only playbook-level health checks. Trigger, step, task, and periodic-monitor assertions are not counted as health-check coverage.

| Phase | Chain ID | Implemented Health Checks | Notes |
| --- | --- | --- | --- |
| precheck | `pre.standard_bgp` | `startup_bgp_session_verification`, `startup_cpu_load_average_baseline`, `startup_bgp_graceful_restart_disabled_check_v6`, `startup_bgp_graceful_restart_disabled_check_v4`, `startup_hardware_capacity_baseline`, `startup_bgp_convergence`, `startup_ibgp_pnh_verification`, `rib_fib_consistency_precheck` | The PNH check is present only for Open/R profiles. The remaining checks establish the session, resource, convergence, and RIB/FIB baseline. |
| postcheck | `post.cold_start_recovery` | `postcheck_bgp_convergence_time`, `BGP session establishment`, `BGP stale-route check`, `BGP and system log parsing`, `rib_fib_consistency_postcheck`, `restart-aware BGP service check` | EOR timer expiry is tolerated while final convergence remains enforced. |
| snapshot | `snapshot.full` | `core-dump snapshot check`, `BGP session flap, uptime, and peer-identity snapshot check` | Compares the full session and crash state before and after the workload. |

**Specification vs. implemented health checks**

| Required Validation | Implemented By | Coverage | Gap |
| --- | --- | --- | --- |
| Cold-start profile checks pass. | `pre.standard_bgp`, `post.cold_start_recovery` | implemented | None |
| Expected sessions establish and convergence completes. | `post.cold_start_recovery`, `snapshot.full` | implemented | None |
| Snapshot, CPU, and memory checks remain healthy. | `snapshot.full` | partial | CPU and memory are periodic tasks, not playbook-level health checks. |

**Validations outside the health-check chain**

- Standard CPU and memory periodic tasks run during the workload.

**Expected runtime:** About 10 minutes of stimulus plus shared topology setup.

**Primary triage signals**

- EOR and convergence timeline.
- Per-thread CPU and peer-establishment failures.
- BGP startup logs.

**Artifacts**

- TAAC health-check results.
- BGP startup logs and session snapshots.
- Thread CPU collection.

**Qualification difference:** Daily CI uses the conveyor topology and one synchronized cold-start event.

### CICD-03: eBGP session oscillation

- **Playbook:** `bgp_ebb_ebgp_session_oscillation_playbook`
- **Factory:** `get_bgp_ebb_ebgp_session_oscillation_playbook`
- **Requirements:** G2-18 (direct)
- **Required topology:** `neteng.test_infra.dne.taac.abstractions.topologies.ebb_full_scale.ebb_full_scale_topology`
- **Cadence:** Daily.
- **Enforcement:** blocking

**Purpose:** Detect session-manager and convergence regressions under sustained eBGP peer churn.

**Stimulus:** Randomly flap eBGP sessions for 30 minutes using 30-second up and down intervals.

**Scale:** Seventy eBGP sessions per cycle on the canonical full-scale topology.

**Blocking signals**

- Oscillation profile prechecks and postchecks pass.
- All expected sessions recover after churn.
- No crash, snapshot regression, or resource-limit violation occurs.

**Outcome validation traceability**

- **Health-check chain:** `oscillation_skip_flap_and_uptime`
- **Check profile:** `CheckProfile.OSCILLATION`
- **Implementation:** `get_profile_checks(CheckProfile.OSCILLATION)`

The chain below contains only playbook-level health checks. Trigger, step, task, and periodic-monitor assertions are not counted as health-check coverage.

| Phase | Chain ID | Implemented Health Checks | Notes |
| --- | --- | --- | --- |
| precheck | `pre.standard_bgp` | `startup_bgp_session_verification`, `startup_cpu_load_average_baseline`, `startup_bgp_graceful_restart_disabled_check_v6`, `startup_bgp_graceful_restart_disabled_check_v4`, `startup_hardware_capacity_baseline`, `startup_bgp_convergence`, `startup_ibgp_pnh_verification`, `rib_fib_consistency_precheck` | The PNH check is present only for Open/R profiles. The remaining checks establish the session, resource, convergence, and RIB/FIB baseline. |
| postcheck | `post.standard_without_convergence` | `BGP session establishment`, `BGP stale-route check`, `BGP and system log parsing`, `rib_fib_consistency_postcheck`, `service restart detection` | Omits the explicit BGP convergence-time health check. |
| snapshot | `snapshot.skip_flap_and_uptime` | `core-dump snapshot check`, `BGP session peer-identity snapshot check` | Expected flap and uptime changes are intentionally excluded. |

**Specification vs. implemented health checks**

| Required Validation | Implemented By | Coverage | Gap |
| --- | --- | --- | --- |
| Oscillation profile prechecks and postchecks pass. | `pre.standard_bgp`, `post.standard_without_convergence` | implemented | None |
| All expected sessions recover after churn. | `post.standard_without_convergence`, `snapshot.skip_flap_and_uptime` | implemented | None |
| No crash, snapshot regression, or resource-limit violation occurs. | `snapshot.skip_flap_and_uptime` | partial | Flap and uptime comparisons are skipped; resource limits are periodic tasks. |

**Validations outside the health-check chain**

- Standard CPU and memory periodic tasks run during the workload.

**Expected runtime:** Approximately 1.5 hours including shared topology setup.

**Primary triage signals**

- Flapped and failed peer sets.
- Session transition and convergence logs.
- CPU and memory periodic-task samples.

**Artifacts**

- TAAC stage and health-check results.
- BGP and IXIA logs.
- Session and resource snapshots.

**Qualification difference:** CI fixes the churn duration and cycle shape for repeatable daily comparison.

### CICD-04: iBGP plane session oscillation

- **Playbook:** `bgp_ebb_ibgp_plane_session_oscillation_playbook`
- **Factory:** `get_bgp_ebb_ibgp_plane_session_oscillation_playbook`
- **Requirements:** G2-19 (direct)
- **Required topology:** `neteng.test_infra.dne.taac.abstractions.topologies.ebb_full_scale.ebb_full_scale_topology`
- **Cadence:** Daily.
- **Enforcement:** blocking

**Purpose:** Detect plane-specific session and convergence regressions under sustained iBGP churn.

**Stimulus:** Flap iBGP sessions across planes 1 through 4 for 30 minutes using 30-second up and down intervals.

**Scale:** Four dual-stack iBGP planes at canonical full-scale peer counts.

**Blocking signals**

- Oscillation profile checks pass for every plane.
- All expected iBGP sessions recover after churn.
- No crash, snapshot regression, or resource-limit violation occurs.

**Outcome validation traceability**

- **Health-check chain:** `oscillation_skip_flap_and_uptime`
- **Check profile:** `CheckProfile.OSCILLATION`
- **Implementation:** `get_profile_checks(CheckProfile.OSCILLATION)`

The chain below contains only playbook-level health checks. Trigger, step, task, and periodic-monitor assertions are not counted as health-check coverage.

| Phase | Chain ID | Implemented Health Checks | Notes |
| --- | --- | --- | --- |
| precheck | `pre.standard_bgp` | `startup_bgp_session_verification`, `startup_cpu_load_average_baseline`, `startup_bgp_graceful_restart_disabled_check_v6`, `startup_bgp_graceful_restart_disabled_check_v4`, `startup_hardware_capacity_baseline`, `startup_bgp_convergence`, `startup_ibgp_pnh_verification`, `rib_fib_consistency_precheck` | The PNH check is present only for Open/R profiles. The remaining checks establish the session, resource, convergence, and RIB/FIB baseline. |
| postcheck | `post.standard_without_convergence` | `BGP session establishment`, `BGP stale-route check`, `BGP and system log parsing`, `rib_fib_consistency_postcheck`, `service restart detection` | Omits the explicit BGP convergence-time health check. |
| snapshot | `snapshot.skip_flap_and_uptime` | `core-dump snapshot check`, `BGP session peer-identity snapshot check` | Expected flap and uptime changes are intentionally excluded. |

**Specification vs. implemented health checks**

| Required Validation | Implemented By | Coverage | Gap |
| --- | --- | --- | --- |
| Oscillation profile checks pass for every plane. | `pre.standard_bgp`, `post.standard_without_convergence` | partial | The shared health-check profile is not evaluated independently per plane. |
| All expected iBGP sessions recover after churn. | `post.standard_without_convergence`, `snapshot.skip_flap_and_uptime` | implemented | None |
| No crash, snapshot regression, or resource-limit violation occurs. | `snapshot.skip_flap_and_uptime` | partial | Flap and uptime comparisons are skipped; resource limits are periodic tasks. |

**Validations outside the health-check chain**

- The oscillation stage selects and restores sessions by plane.
- Standard CPU and memory periodic tasks run during the workload.

**Expected runtime:** Approximately 1.6 hours including shared topology setup.

**Primary triage signals**

- Plane and peer indexes for each failed transition.
- Session-manager and convergence logs.
- CPU and memory periodic-task samples.

**Artifacts**

- TAAC stage and health-check results.
- BGP and IXIA logs.
- Per-plane session snapshots.

**Qualification difference:** CI uses a fixed 30-minute churn window across the representative four-plane topology.

## Route and IGP Instability

### CICD-05: eBGP route oscillation

- **Playbook:** `bgp_ebb_ebgp_route_oscillation_playbook`
- **Factory:** `get_bgp_ebb_ebgp_route_oscillation_playbook`
- **Requirements:** G2-20 (direct)
- **Required topology:** `neteng.test_infra.dne.taac.abstractions.topologies.ebb_full_scale.ebb_full_scale_topology`
- **Cadence:** Daily.
- **Enforcement:** blocking

**Purpose:** Detect RIB, FIB, and UPDATE-processing regressions under eBGP route churn.

**Stimulus:** Repeatedly withdraw and readvertise eBGP prefix indexes 0 through 500.

**Scale:** Canonical eBGP peer population with 501 selected prefixes per churn operation.

**Blocking signals**

- Route-oscillation profile checks pass.
- RIB and FIB converge after the final readvertisement.
- Sessions, snapshots, and resource checks remain healthy.

**Outcome validation traceability**

- **Health-check chain:** `oscillation_skip_uptime`
- **Check profile:** `CheckProfile.OSCILLATION`
- **Implementation:** `get_profile_checks(CheckProfile.OSCILLATION)`

The chain below contains only playbook-level health checks. Trigger, step, task, and periodic-monitor assertions are not counted as health-check coverage.

| Phase | Chain ID | Implemented Health Checks | Notes |
| --- | --- | --- | --- |
| precheck | `pre.standard_bgp` | `startup_bgp_session_verification`, `startup_cpu_load_average_baseline`, `startup_bgp_graceful_restart_disabled_check_v6`, `startup_bgp_graceful_restart_disabled_check_v4`, `startup_hardware_capacity_baseline`, `startup_bgp_convergence`, `startup_ibgp_pnh_verification`, `rib_fib_consistency_precheck` | The PNH check is present only for Open/R profiles. The remaining checks establish the session, resource, convergence, and RIB/FIB baseline. |
| postcheck | `post.standard_without_convergence` | `BGP session establishment`, `BGP stale-route check`, `BGP and system log parsing`, `rib_fib_consistency_postcheck`, `service restart detection` | Omits the explicit BGP convergence-time health check. |
| snapshot | `snapshot.skip_uptime` | `core-dump snapshot check`, `BGP session flap and peer-identity snapshot check` | Session uptime is intentionally excluded. |

**Specification vs. implemented health checks**

| Required Validation | Implemented By | Coverage | Gap |
| --- | --- | --- | --- |
| Route-oscillation profile checks pass. | `pre.standard_bgp`, `post.standard_without_convergence` | implemented | None |
| RIB and FIB converge after the final readvertisement. | `post.standard_without_convergence` | implemented | None |
| Sessions, snapshots, and resource checks remain healthy. | `post.standard_without_convergence`, `snapshot.skip_uptime` | partial | Session uptime is skipped; resource checks are periodic tasks. |

**Validations outside the health-check chain**

- Standard CPU and memory periodic tasks run during the workload.

**Expected runtime:** Approximately 1.9 hours including shared topology setup.

**Primary triage signals**

- Prefix-pool actions and UPDATE timing.
- RIB, FIB, and convergence failures.
- BGP and IXIA logs.

**Artifacts**

- TAAC stage and health-check results.
- Route-state snapshots.
- BGP and IXIA logs.

**Qualification difference:** CI uses a deterministic prefix slice and conveyor-sized churn window.

### CICD-06: iBGP route oscillation

- **Playbook:** `bgp_ebb_ibgp_route_oscillation_playbook`
- **Factory:** `get_bgp_ebb_ibgp_route_oscillation_playbook`
- **Requirements:** G2-21 (direct)
- **Required topology:** `neteng.test_infra.dne.taac.abstractions.topologies.ebb_full_scale.ebb_full_scale_topology`
- **Cadence:** Daily.
- **Enforcement:** blocking

**Purpose:** Detect RIB, FIB, and UPDATE-processing regressions under iBGP route churn.

**Stimulus:** Repeatedly withdraw and readvertise iBGP prefix indexes 0 through 100.

**Scale:** Canonical iBGP plane population with 101 selected prefixes per churn operation.

**Blocking signals**

- Route-oscillation profile checks pass.
- RIB and FIB converge after the final readvertisement.
- Sessions, snapshots, and resource checks remain healthy.

**Outcome validation traceability**

- **Health-check chain:** `oscillation_full_snapshot`
- **Check profile:** `CheckProfile.OSCILLATION`
- **Implementation:** `get_profile_checks(CheckProfile.OSCILLATION)`

The chain below contains only playbook-level health checks. Trigger, step, task, and periodic-monitor assertions are not counted as health-check coverage.

| Phase | Chain ID | Implemented Health Checks | Notes |
| --- | --- | --- | --- |
| precheck | `pre.standard_bgp` | `startup_bgp_session_verification`, `startup_cpu_load_average_baseline`, `startup_bgp_graceful_restart_disabled_check_v6`, `startup_bgp_graceful_restart_disabled_check_v4`, `startup_hardware_capacity_baseline`, `startup_bgp_convergence`, `startup_ibgp_pnh_verification`, `rib_fib_consistency_precheck` | The PNH check is present only for Open/R profiles. The remaining checks establish the session, resource, convergence, and RIB/FIB baseline. |
| postcheck | `post.standard_without_convergence` | `BGP session establishment`, `BGP stale-route check`, `BGP and system log parsing`, `rib_fib_consistency_postcheck`, `service restart detection` | Omits the explicit BGP convergence-time health check. |
| snapshot | `snapshot.full` | `core-dump snapshot check`, `BGP session flap, uptime, and peer-identity snapshot check` | Compares the full session and crash state before and after the workload. |

**Specification vs. implemented health checks**

| Required Validation | Implemented By | Coverage | Gap |
| --- | --- | --- | --- |
| Route-oscillation profile checks pass. | `pre.standard_bgp`, `post.standard_without_convergence` | implemented | None |
| RIB and FIB converge after the final readvertisement. | `post.standard_without_convergence` | implemented | None |
| Sessions, snapshots, and resource checks remain healthy. | `post.standard_without_convergence`, `snapshot.full` | partial | Resource checks are periodic tasks, not playbook-level health checks. |

**Validations outside the health-check chain**

- Standard CPU and memory periodic tasks run during the workload.

**Expected runtime:** Approximately 2 hours including shared topology setup.

**Primary triage signals**

- Prefix-pool actions and UPDATE timing.
- RIB, FIB, and convergence failures.
- BGP and IXIA logs.

**Artifacts**

- TAAC stage and health-check results.
- Route-state snapshots.
- BGP and IXIA logs.

**Qualification difference:** CI uses a deterministic prefix slice and conveyor-sized churn window.

### CICD-07: IGP PNH metric oscillation

- **Playbook:** `bgp_ebb_igp_pnh_metric_oscillation_playbook`
- **Factory:** `get_bgp_ebb_igp_pnh_metric_oscillation_playbook`
- **Requirements:** G2-13 (direct)
- **Required topology:** `neteng.test_infra.dne.taac.abstractions.topologies.ebb_full_scale.ebb_full_scale_topology`
- **Cadence:** Daily.
- **Enforcement:** blocking

**Purpose:** Detect best-path, nexthop tracking, and session regressions caused by repeated Open/R metric changes.

**Stimulus:** Oscillate metrics for selected IPv4 and IPv6 PNH routes every 30 seconds for 40 minutes while capturing BGP traffic.

**Scale:** Sixty-three IPv4 and IPv6 PNH routes on standalone Open/R links.

**Blocking signals**

- IGP-instability profile checks pass.
- Packet validation sees only expected KEEPALIVE traffic and no OPEN or NOTIFICATION.
- Cleanup restores original metrics and stable route state.

**Outcome validation traceability**

- **Health-check chain:** `igp_instability`
- **Check profile:** `CheckProfile.IGP_INSTABILITY`
- **Implementation:** `get_profile_checks(CheckProfile.IGP_INSTABILITY)`

The chain below contains only playbook-level health checks. Trigger, step, task, and periodic-monitor assertions are not counted as health-check coverage.

| Phase | Chain ID | Implemented Health Checks | Notes |
| --- | --- | --- | --- |
| precheck | `pre.standard_bgp` | `startup_bgp_session_verification`, `startup_cpu_load_average_baseline`, `startup_bgp_graceful_restart_disabled_check_v6`, `startup_bgp_graceful_restart_disabled_check_v4`, `startup_hardware_capacity_baseline`, `startup_bgp_convergence`, `startup_ibgp_pnh_verification`, `rib_fib_consistency_precheck` | The PNH check is present only for Open/R profiles. The remaining checks establish the session, resource, convergence, and RIB/FIB baseline. |
| postcheck | `post.standard_without_convergence` | `BGP session establishment`, `BGP stale-route check`, `BGP and system log parsing`, `rib_fib_consistency_postcheck`, `service restart detection` | Omits the explicit BGP convergence-time health check. |
| snapshot | `snapshot.full` | `core-dump snapshot check`, `BGP session flap, uptime, and peer-identity snapshot check` | Compares the full session and crash state before and after the workload. |

**Specification vs. implemented health checks**

| Required Validation | Implemented By | Coverage | Gap |
| --- | --- | --- | --- |
| IGP-instability profile checks pass. | `pre.standard_bgp`, `post.standard_without_convergence`, `snapshot.full` | implemented | None |
| Packet validation sees only expected KEEPALIVE traffic and no OPEN or NOTIFICATION. | None | missing | No playbook-level health check validates the packet-message expectation. |
| Cleanup restores original metrics and stable route state. | None | missing | Cleanup executes route injection but has no post-cleanup health check. |

**Validations outside the health-check chain**

- A stage-local counter assertion verifies that metric oscillation sends no BGP withdrawals.
- The cleanup step re-injects the Open/R routes.
- Standard CPU and memory periodic tasks run during the workload.

**Expected runtime:** Approximately 50 minutes including shared topology setup.

**Primary triage signals**

- Open/R route and metric actions.
- Packet capture protocol messages.
- PNH state and BGP session health.

**Artifacts**

- BGP packet capture.
- Open/R route-operation logs.
- TAAC health-check and cleanup results.

**Qualification difference:** CI uses fixed metric cadence and route count for a repeatable daily signal.

### CICD-08: IGP unresolvable PNH

- **Playbook:** `bgp_ebb_igp_unresolvable_pnh_playbook`
- **Factory:** `get_bgp_ebb_igp_unresolvable_pnh_playbook`
- **Requirements:** G2-14 (direct)
- **Required topology:** `neteng.test_infra.dne.taac.abstractions.topologies.ebb_full_scale.ebb_full_scale_topology`
- **Cadence:** Daily.
- **Enforcement:** blocking

**Purpose:** Detect nexthop tracking and UPDATE convergence regressions when Open/R reachability disappears and returns.

**Stimulus:** Delete selected Open/R routes, observe BGP updates, then re-inject the routes and verify recovery.

**Scale:** Representative IPv4 and IPv6 PNHs on the full-scale Open/R topology.

**Blocking signals**

- IGP-instability checks pass through withdrawal and restoration.
- UPDATE convergence and final session health meet expectations.
- Cleanup restores every deleted Open/R route.

**Outcome validation traceability**

- **Health-check chain:** `igp_instability`
- **Check profile:** `CheckProfile.IGP_INSTABILITY`
- **Implementation:** `get_profile_checks(CheckProfile.IGP_INSTABILITY)`

The chain below contains only playbook-level health checks. Trigger, step, task, and periodic-monitor assertions are not counted as health-check coverage.

| Phase | Chain ID | Implemented Health Checks | Notes |
| --- | --- | --- | --- |
| precheck | `pre.standard_bgp` | `startup_bgp_session_verification`, `startup_cpu_load_average_baseline`, `startup_bgp_graceful_restart_disabled_check_v6`, `startup_bgp_graceful_restart_disabled_check_v4`, `startup_hardware_capacity_baseline`, `startup_bgp_convergence`, `startup_ibgp_pnh_verification`, `rib_fib_consistency_precheck` | The PNH check is present only for Open/R profiles. The remaining checks establish the session, resource, convergence, and RIB/FIB baseline. |
| postcheck | `post.standard_without_convergence` | `BGP session establishment`, `BGP stale-route check`, `BGP and system log parsing`, `rib_fib_consistency_postcheck`, `service restart detection` | Omits the explicit BGP convergence-time health check. |
| snapshot | `snapshot.full` | `core-dump snapshot check`, `BGP session flap, uptime, and peer-identity snapshot check` | Compares the full session and crash state before and after the workload. |

**Specification vs. implemented health checks**

| Required Validation | Implemented By | Coverage | Gap |
| --- | --- | --- | --- |
| IGP-instability checks pass through withdrawal and restoration. | `pre.standard_bgp`, `post.standard_without_convergence`, `snapshot.full` | partial | The health-check chain runs around the workload, not after cleanup restoration. |
| UPDATE convergence and final session health meet expectations. | `post.standard_without_convergence`, `snapshot.full` | partial | Final session and RIB/FIB health are checked, but explicit convergence is disabled. |
| Cleanup restores every deleted Open/R route. | None | missing | Cleanup re-injects routes without a post-cleanup route-state health check. |

**Validations outside the health-check chain**

- The unresolvable-PNH stage performs direct BGP++ UPDATE counter validation.
- The cleanup step re-injects the deleted Open/R routes.
- Standard CPU and memory periodic tasks run during the workload.

**Expected runtime:** Measured standalone runtime is not yet recorded; the case shares an 8-hour conveyor node budget.

**Primary triage signals**

- Open/R route state before and after deletion.
- Observer packet capture and UPDATE timing.
- RIB, FIB, and BGP session state.

**Artifacts**

- Observer packet capture.
- Open/R operation and cleanup logs.
- TAAC route and session checks.

**Qualification difference:** CI uses a representative PNH subset and requires deterministic restoration.

### CICD-09: Multipath-group oscillation

- **Playbook:** `bgp_ebb_multipath_group_oscillation_playbook`
- **Factory:** `get_bgp_ebb_multipath_group_oscillation_playbook`
- **Requirements:** G2-16 (direct)
- **Required topology:** `neteng.test_infra.dne.taac.abstractions.topologies.ebb_full_scale.ebb_full_scale_topology`
- **Cadence:** Daily.
- **Enforcement:** blocking

**Purpose:** Detect multipath selection and FIB programming regressions during peer loss and recovery.

**Stimulus:** Measure live multipath width, then stop and start 1 through 11 eBGP peers every 280 seconds for 30 minutes.

**Scale:** Canonical full-scale routes with a dynamically measured multipath baseline.

**Blocking signals**

- Multipath width decreases during disruption.
- Width restores to the measured baseline after peers return.
- Final session, RIB, FIB, and health checks pass.

**Outcome validation traceability**

- **Health-check chain:** `oscillation_skip_flap_and_uptime`
- **Check profile:** `CheckProfile.OSCILLATION`
- **Implementation:** `get_profile_checks(CheckProfile.OSCILLATION)`

The chain below contains only playbook-level health checks. Trigger, step, task, and periodic-monitor assertions are not counted as health-check coverage.

| Phase | Chain ID | Implemented Health Checks | Notes |
| --- | --- | --- | --- |
| precheck | `pre.standard_bgp` | `startup_bgp_session_verification`, `startup_cpu_load_average_baseline`, `startup_bgp_graceful_restart_disabled_check_v6`, `startup_bgp_graceful_restart_disabled_check_v4`, `startup_hardware_capacity_baseline`, `startup_bgp_convergence`, `startup_ibgp_pnh_verification`, `rib_fib_consistency_precheck` | The PNH check is present only for Open/R profiles. The remaining checks establish the session, resource, convergence, and RIB/FIB baseline. |
| postcheck | `post.standard_without_convergence` | `BGP session establishment`, `BGP stale-route check`, `BGP and system log parsing`, `rib_fib_consistency_postcheck`, `service restart detection` | Omits the explicit BGP convergence-time health check. |
| snapshot | `snapshot.skip_flap_and_uptime` | `core-dump snapshot check`, `BGP session peer-identity snapshot check` | Expected flap and uptime changes are intentionally excluded. |

**Specification vs. implemented health checks**

| Required Validation | Implemented By | Coverage | Gap |
| --- | --- | --- | --- |
| Multipath width decreases during disruption. | None | missing | Multipath width is asserted inside the oscillation stage, not by a health check. |
| Width restores to the measured baseline after peers return. | None | missing | Baseline restoration is asserted inside the oscillation stage, not by a health check. |
| Final session, RIB, FIB, and health checks pass. | `post.standard_without_convergence`, `snapshot.skip_flap_and_uptime` | implemented | None |

**Validations outside the health-check chain**

- The multipath oscillation stage measures, reduces, and validates restoration of live width.
- Standard CPU and memory periodic tasks run during the workload.

**Expected runtime:** Approximately 49 minutes including shared topology setup.

**Primary triage signals**

- Baseline and observed multipath widths.
- Stopped peer set and recovery timing.
- RIB, FIB, and session failures.

**Artifacts**

- Multipath width measurements.
- TAAC route and session checks.
- BGP and IXIA logs.

**Qualification difference:** CI measures the active baseline instead of assuming a qualification-lab width.

### CICD-10: BGP attribute churn

- **Playbook:** `bgp_ebb_attribute_churn_playbook`
- **Factory:** `get_bgp_ebb_attribute_churn_playbook`
- **Requirements:** G2-15 (direct)
- **Required topology:** `neteng.test_infra.dne.taac.abstractions.topologies.ebb_full_scale.ebb_full_scale_topology`
- **Cadence:** Daily.
- **Enforcement:** calibrating

**Purpose:** Detect UPDATE generation, canonicalization, memory, and convergence regressions under attribute churn.

**Stimulus:** Repeatedly change local preference, MED, origin, and AS path over iBGP plane-1 prefixes.

**Scale:** Prefix indexes 0 through 500 on the canonical full-scale topology.

**Blocking signals**

- Churn profile checks and expected session checks pass.
- No crash, snapshot regression, or blocking resource threshold is hit.
- Final route state converges after churn.

**Outcome validation traceability**

- **Health-check chain:** `churn_storm`
- **Check profile:** `CheckProfile.CHURN_STORM`
- **Implementation:** `get_profile_checks(CheckProfile.CHURN_STORM)`

The chain below contains only playbook-level health checks. Trigger, step, task, and periodic-monitor assertions are not counted as health-check coverage.

| Phase | Chain ID | Implemented Health Checks | Notes |
| --- | --- | --- | --- |
| precheck | `pre.standard_bgp` | `startup_bgp_session_verification`, `startup_cpu_load_average_baseline`, `startup_bgp_graceful_restart_disabled_check_v6`, `startup_bgp_graceful_restart_disabled_check_v4`, `startup_hardware_capacity_baseline`, `startup_bgp_convergence`, `startup_ibgp_pnh_verification`, `rib_fib_consistency_precheck` | The PNH check is present only for Open/R profiles. The remaining checks establish the session, resource, convergence, and RIB/FIB baseline. |
| postcheck | `post.churn_storm` | `expected-count BGP session establishment`, `BGP stale-route check`, `BGP and system log parsing`, `rib_fib_consistency_postcheck`, `service restart detection` | Omits the convergence-time check. CICD-11 supplies AS-path length and pool size invariants to the RIB/FIB consistency check. |
| snapshot | `snapshot.core_only` | `core-dump snapshot check` | Session snapshots are omitted because sessions may churn throughout the workload. |

**Specification vs. implemented health checks**

| Required Validation | Implemented By | Coverage | Gap |
| --- | --- | --- | --- |
| Churn profile checks and expected session checks pass. | `pre.standard_bgp`, `post.churn_storm` | implemented | None |
| No crash, snapshot regression, or blocking resource threshold is hit. | `snapshot.core_only` | partial | Only core dumps are snapshotted; resource monitors are non-blocking periodic tasks. |
| Final route state converges after churn. | `post.churn_storm` | partial | RIB/FIB consistency is checked, but the explicit convergence health check is disabled. |

**Validations outside the health-check chain**

- Standard CPU and memory periodic tasks run in non-terminating mode.

**Expected runtime:** Approximately 2 hours including shared topology setup.

**Primary triage signals**

- Attribute assignments and generated updates.
- Session and convergence failures.
- CPU and memory trends.

**Artifacts**

- Attribute-change and IXIA logs.
- TAAC health-check results.
- CPU and memory time series.

**Qualification difference:** CI covers a deterministic attribute matrix and prefix slice; resource thresholds require ongoing calibration.

### CICD-11: BGP route storm

- **Playbook:** `bgp_ebb_route_storm_playbook`
- **Factory:** `get_bgp_ebb_route_storm_playbook`
- **Requirements:** G2-17 (direct)
- **Required topology:** `neteng.test_infra.dne.taac.abstractions.topologies.ebb_full_scale.ebb_full_scale_topology`
- **Cadence:** Daily.
- **Enforcement:** calibrating

**Purpose:** Detect route-processing, convergence, and memory regressions during sustained storm load.

**Stimulus:** Advertise and withdraw iBGP plane-1 routes every 30 seconds for 60 minutes, then revert and wait 120 seconds.

**Scale:** Canonical full-scale topology with AS-path length 255 and pool-size invariants.

**Blocking signals**

- Storm profile and expected session checks pass.
- Final AS-path and pool invariants hold.
- No crash, snapshot regression, or blocking resource threshold is hit.

**Outcome validation traceability**

- **Health-check chain:** `churn_storm`
- **Check profile:** `CheckProfile.CHURN_STORM`
- **Implementation:** `get_profile_checks(CheckProfile.CHURN_STORM)`

The chain below contains only playbook-level health checks. Trigger, step, task, and periodic-monitor assertions are not counted as health-check coverage.

| Phase | Chain ID | Implemented Health Checks | Notes |
| --- | --- | --- | --- |
| precheck | `pre.standard_bgp` | `startup_bgp_session_verification`, `startup_cpu_load_average_baseline`, `startup_bgp_graceful_restart_disabled_check_v6`, `startup_bgp_graceful_restart_disabled_check_v4`, `startup_hardware_capacity_baseline`, `startup_bgp_convergence`, `startup_ibgp_pnh_verification`, `rib_fib_consistency_precheck` | The PNH check is present only for Open/R profiles. The remaining checks establish the session, resource, convergence, and RIB/FIB baseline. |
| postcheck | `post.churn_storm` | `expected-count BGP session establishment`, `BGP stale-route check`, `BGP and system log parsing`, `rib_fib_consistency_postcheck`, `service restart detection` | Omits the convergence-time check. CICD-11 supplies AS-path length and pool size invariants to the RIB/FIB consistency check. |
| snapshot | `snapshot.core_only` | `core-dump snapshot check` | Session snapshots are omitted because sessions may churn throughout the workload. |

**Specification vs. implemented health checks**

| Required Validation | Implemented By | Coverage | Gap |
| --- | --- | --- | --- |
| Storm profile and expected session checks pass. | `pre.standard_bgp`, `post.churn_storm` | implemented | None |
| Final AS-path and pool invariants hold. | `post.churn_storm` | implemented | None |
| No crash, snapshot regression, or blocking resource threshold is hit. | `snapshot.core_only` | partial | Only core dumps are snapshotted; resource monitors are non-blocking periodic tasks. |

**Validations outside the health-check chain**

- Standard CPU and memory periodic tasks run in non-terminating mode.

**Expected runtime:** Approximately 2.2 hours including shared topology setup.

**Primary triage signals**

- IXIA advertise and withdraw actions.
- AS-path, pool, RIB, and FIB diagnostics.
- CPU and memory trends.

**Artifacts**

- TAAC stage and health-check results.
- BGP and IXIA logs.
- Resource time series and snapshots.

**Qualification difference:** CI fixes the storm cadence and duration; resource thresholds require ongoing calibration.

## Operational Procedures

### CICD-12: Route-registry runtime update

- **Playbook:** `bgp_ebb_route_registry_runtime_update_playbook`
- **Factory:** `get_bgp_ebb_route_registry_runtime_update_playbook`
- **Requirements:** G2-24 (direct), G2-25 (supplemental)
- **Required topology:** `neteng.test_infra.dne.taac.abstractions.topologies.ebb_full_scale.ebb_full_scale_topology`
- **Cadence:** Daily.
- **Enforcement:** blocking

**Purpose:** Detect live policy evaluation and route-registry regressions without restarting BGP++.

**Stimulus:** Change route-filter prefix lists at runtime, validate route counts, soak for 120 seconds, then restore policy and routes.

**Scale:** Dual-stack full-scale topology with controlled prefix-list transitions.

**Blocking signals**

- Every expected route-count transition is observed.
- Convergence and session health remain within the runtime-update profile.
- Cleanup restores permissive policy and withdrawn routes.

**Outcome validation traceability**

- **Health-check chain:** `runtime_update`
- **Check profile:** `CheckProfile.RUNTIME_UPDATE`
- **Implementation:** `get_profile_checks(CheckProfile.RUNTIME_UPDATE)`

The chain below contains only playbook-level health checks. Trigger, step, task, and periodic-monitor assertions are not counted as health-check coverage.

| Phase | Chain ID | Implemented Health Checks | Notes |
| --- | --- | --- | --- |
| precheck | `pre.runtime_update` | `standard BGP prechecks`, `BGP route-count verification` | Adds an eBGP post-policy route-count baseline to the standard prechecks. |
| postcheck | `post.standard_with_convergence` | `postcheck_bgp_convergence_time`, `BGP session establishment`, `BGP stale-route check`, `BGP and system log parsing`, `rib_fib_consistency_postcheck`, `service restart detection` | Enforces final convergence and common BGP control-plane health. |
| snapshot | `snapshot.full` | `core-dump snapshot check`, `BGP session flap, uptime, and peer-identity snapshot check` | Compares the full session and crash state before and after the workload. |

**Specification vs. implemented health checks**

| Required Validation | Implemented By | Coverage | Gap |
| --- | --- | --- | --- |
| Every expected route-count transition is observed. | `pre.runtime_update` | partial | The health-check chain validates only the baseline count; transitions are stage-local assertions. |
| Convergence and session health remain within the runtime-update profile. | `post.standard_with_convergence`, `snapshot.full` | implemented | None |
| Cleanup restores permissive policy and withdrawn routes. | None | missing | Cleanup actions run after the health-check chain and have no post-cleanup check. |

**Validations outside the health-check chain**

- The runtime-update stage validates route counts after each policy transition.
- Cleanup steps re-advertise prefixes and restore the permissive route filter.
- Standard CPU and memory periodic tasks run during the workload.

**Expected runtime:** Approximately 15 minutes including shared topology setup.

**Primary triage signals**

- Route-filter RPC requests and responses.
- Route counts and policy state at each transition.
- Cleanup and convergence failures.

**Artifacts**

- Route-filter operation logs.
- TAAC route-count and session checks.
- Before and after policy state.

**Qualification difference:** CI exercises a representative prefix-list transition sequence and makes cleanup blocking.

### CICD-13: FAUU drain and undrain

- **Playbook:** `bgp_ebb_fauu_drain_undrain_playbook`
- **Factory:** `get_bgp_ebb_fauu_drain_undrain_playbook`
- **Requirements:** G2-23 (direct)
- **Required topology:** `neteng.test_infra.dne.taac.abstractions.topologies.ebb_full_scale.ebb_full_scale_topology`
- **Cadence:** Daily.
- **Enforcement:** blocking

**Purpose:** Detect operational drain-policy and attribute-propagation regressions.

**Stimulus:** Change local preference and origin for FAUU prefixes, drain and undrain, capture three peer views, and soak for five minutes.

**Scale:** Canonical full-scale eBGP, iBGP, and BGP-MON observation paths.

**Blocking signals**

- Drain profile checks pass.
- Convergence completes within the five-minute stage limit.
- Final sessions and all observed peer views are restored.

**Outcome validation traceability**

- **Health-check chain:** `drain_undrain`
- **Check profile:** `CheckProfile.DRAIN_UNDRAIN`
- **Implementation:** `get_profile_checks(CheckProfile.DRAIN_UNDRAIN)`

The chain below contains only playbook-level health checks. Trigger, step, task, and periodic-monitor assertions are not counted as health-check coverage.

| Phase | Chain ID | Implemented Health Checks | Notes |
| --- | --- | --- | --- |
| precheck | `pre.standard_bgp` | `startup_bgp_session_verification`, `startup_cpu_load_average_baseline`, `startup_bgp_graceful_restart_disabled_check_v6`, `startup_bgp_graceful_restart_disabled_check_v4`, `startup_hardware_capacity_baseline`, `startup_bgp_convergence`, `startup_ibgp_pnh_verification`, `rib_fib_consistency_precheck` | The PNH check is present only for Open/R profiles. The remaining checks establish the session, resource, convergence, and RIB/FIB baseline. |
| postcheck | `post.standard_without_convergence` | `BGP session establishment`, `BGP stale-route check`, `BGP and system log parsing`, `rib_fib_consistency_postcheck`, `service restart detection` | Omits the explicit BGP convergence-time health check. |
| snapshot | `snapshot.skip_flap` | `core-dump snapshot check`, `BGP session uptime and peer-identity snapshot check` | Expected session flaps are intentionally excluded. |

**Specification vs. implemented health checks**

| Required Validation | Implemented By | Coverage | Gap |
| --- | --- | --- | --- |
| Drain profile checks pass. | `pre.standard_bgp`, `post.standard_without_convergence`, `snapshot.skip_flap` | implemented | None |
| Convergence completes within the five-minute stage limit. | None | missing | The profile disables the convergence health check; the limit is enforced inside the drain stage. |
| Final sessions and all observed peer views are restored. | `post.standard_without_convergence`, `snapshot.skip_flap` | partial | Sessions are checked, but captured peer views are validated inside the stage. |

**Validations outside the health-check chain**

- The FAUU drain stage enforces its convergence limit and validates eBGP, iBGP, and BGP-MON views.
- Standard CPU and memory periodic tasks run during the workload.

**Expected runtime:** Approximately 33 minutes including shared topology setup.

**Primary triage signals**

- Policy, local-preference, and origin state.
- eBGP, iBGP, and BGP-MON packet views.
- Convergence and session failures.

**Artifacts**

- Three packet captures.
- TAAC drain and convergence checks.
- BGP policy and session logs.

**Qualification difference:** CI performs one controlled drain and undrain sequence on the conveyor topology.

### CICD-14: Plane drain and undrain

- **Playbook:** `bgp_ebb_plane_drain_undrain_playbook`
- **Factory:** `get_bgp_ebb_plane_drain_undrain_playbook`
- **Requirements:** G2-22 (direct)
- **Required topology:** `neteng.test_infra.dne.taac.abstractions.topologies.ebb_full_scale.ebb_full_scale_topology`
- **Cadence:** Daily after signal calibration.
- **Enforcement:** calibrating

**Purpose:** Detect plane-wide policy, attribute-propagation, and recovery regressions.

**Stimulus:** Apply concurrent IXIA attribute and DUT policy changes across iBGP planes, then soak for 20 minutes.

**Scale:** Four iBGP planes with eBGP, iBGP, and BGP-MON observation paths.

**Blocking signals**

- Drain profile checks pass.
- Convergence completes within the ten-minute stage limit.
- Final plane policy, sessions, and peer views are restored.

**Outcome validation traceability**

- **Health-check chain:** `drain_undrain`
- **Check profile:** `CheckProfile.DRAIN_UNDRAIN`
- **Implementation:** `get_profile_checks(CheckProfile.DRAIN_UNDRAIN)`

The chain below contains only playbook-level health checks. Trigger, step, task, and periodic-monitor assertions are not counted as health-check coverage.

| Phase | Chain ID | Implemented Health Checks | Notes |
| --- | --- | --- | --- |
| precheck | `pre.standard_bgp` | `startup_bgp_session_verification`, `startup_cpu_load_average_baseline`, `startup_bgp_graceful_restart_disabled_check_v6`, `startup_bgp_graceful_restart_disabled_check_v4`, `startup_hardware_capacity_baseline`, `startup_bgp_convergence`, `startup_ibgp_pnh_verification`, `rib_fib_consistency_precheck` | The PNH check is present only for Open/R profiles. The remaining checks establish the session, resource, convergence, and RIB/FIB baseline. |
| postcheck | `post.standard_without_convergence` | `BGP session establishment`, `BGP stale-route check`, `BGP and system log parsing`, `rib_fib_consistency_postcheck`, `service restart detection` | Omits the explicit BGP convergence-time health check. |
| snapshot | `snapshot.skip_flap` | `core-dump snapshot check`, `BGP session uptime and peer-identity snapshot check` | Expected session flaps are intentionally excluded. |

**Specification vs. implemented health checks**

| Required Validation | Implemented By | Coverage | Gap |
| --- | --- | --- | --- |
| Drain profile checks pass. | `pre.standard_bgp`, `post.standard_without_convergence`, `snapshot.skip_flap` | implemented | None |
| Convergence completes within the ten-minute stage limit. | None | missing | The profile disables the convergence health check; the limit is enforced inside the drain stage. |
| Final plane policy, sessions, and peer views are restored. | `post.standard_without_convergence`, `snapshot.skip_flap` | partial | Sessions are checked, but plane policy and captured views are stage-local validations. |

**Validations outside the health-check chain**

- The plane-drain stages enforce convergence limits and validate policy and captured peer views.
- Standard CPU and memory periodic tasks run during the workload.

**Expected runtime:** At least 20 minutes of soak plus shared topology setup.

**Primary triage signals**

- Per-plane policy and attribute state.
- eBGP, iBGP, and BGP-MON packet views.
- Convergence and session failures.

**Artifacts**

- Three packet captures.
- TAAC drain and convergence checks.
- BGP policy and session logs.

**Qualification difference:** CI uses one repeatable plane-drain sequence; runtime and signal-to-noise still require calibration.

## Continuous Operation and Resource Regression

### CICD-15: Longevity

- **Playbook:** `bgp_ebb_longevity_playbook`
- **Factory:** `get_bgp_ebb_longevity_playbook`
- **Requirements:** G2-12 (proxy)
- **Required topology:** `neteng.test_infra.dne.taac.abstractions.topologies.ebb_full_scale.ebb_full_scale_topology`
- **Cadence:** Daily on a dedicated node.
- **Enforcement:** calibrating

**Purpose:** Detect crashes, leaks, and stability regressions during sustained day-to-day churn.

**Stimulus:** Add and remove communities once per minute for four hours, then quiesce and run postchecks.

**Scale:** Canonical full-scale topology with repeated community changes.

**Blocking signals**

- Snapshot and soak postchecks pass after quiescence.
- Final convergence and session state are healthy.
- No crash or blocking resource trend is observed.

**Outcome validation traceability**

- **Health-check chain:** `soak_without_convergence`
- **Check profile:** `CheckProfile.SOAK_NO_PRECHECK`
- **Implementation:** `get_profile_checks(CheckProfile.SOAK_NO_PRECHECK)`

The chain below contains only playbook-level health checks. Trigger, step, task, and periodic-monitor assertions are not counted as health-check coverage.

| Phase | Chain ID | Implemented Health Checks | Notes |
| --- | --- | --- | --- |
| postcheck | `post.standard_without_convergence` | `BGP session establishment`, `BGP stale-route check`, `BGP and system log parsing`, `rib_fib_consistency_postcheck`, `service restart detection` | Omits the explicit BGP convergence-time health check. |
| snapshot | `snapshot.skip_flap_and_uptime` | `core-dump snapshot check`, `BGP session peer-identity snapshot check` | Expected flap and uptime changes are intentionally excluded. |

**Specification vs. implemented health checks**

| Required Validation | Implemented By | Coverage | Gap |
| --- | --- | --- | --- |
| Snapshot and soak postchecks pass after quiescence. | `post.standard_without_convergence`, `snapshot.skip_flap_and_uptime` | implemented | None |
| Final convergence and session state are healthy. | `post.standard_without_convergence`, `snapshot.skip_flap_and_uptime` | partial | Session and RIB/FIB state are checked, but the explicit convergence health check is disabled. |
| No crash or blocking resource trend is observed. | `snapshot.skip_flap_and_uptime` | partial | Core dumps are checked, but this playbook has no CPU or memory periodic validation. |

**Validations outside the health-check chain**

- None.

**Expected runtime:** Four hours of churn plus shared topology setup and postchecks.

**Primary triage signals**

- Churn cycle and final quiescence state.
- Longitudinal CPU and memory samples.
- Session, convergence, and core-dump state.

**Artifacts**

- CPU and memory time series.
- TAAC soak and postcheck results.
- BGP logs and state snapshots.

**Qualification difference:** Gate2 qualification runs 48 hours and includes broader route, attribute, drain, and restart stimuli. This four-hour community-churn workload is a provisional daily proxy, not equivalent qualification coverage.

### CICD-16: Queue and memory monitoring

- **Playbook:** `bgp_ebb_queue_memory_monitoring_playbook`
- **Factory:** `get_bgp_ebb_queue_memory_monitoring_playbook`
- **Requirements:** G2-25 (supplemental)
- **Required topology:** `legacy_two_port_ebb` (legacy; no artifact yet)
- **Cadence:** Daily after threshold calibration.
- **Enforcement:** calibrating

**Purpose:** Detect queue growth, process-memory, and liveness regressions under sustained churn.

**Stimulus:** Monitor BGP++ queues and memory for 60 minutes while routes flap every 15 seconds and CPU stress is active.

**Scale:** 140 eBGP peers, 63 iBGP peers, and 10,000 IPv6 prefixes per eBGP peer.

**Blocking signals**

- BGP process remains alive and sessions remain healthy.
- Queue and memory custom-step thresholds pass.
- Route churn completes without a snapshot regression.

**Outcome validation traceability**

- **Health-check chain:** `session_snapshot_only`
- **Check profile:** None
- **Implementation:** `create_bgp_session_snapshot_check(skip_flap_check=True)`

The chain below contains only playbook-level health checks. Trigger, step, task, and periodic-monitor assertions are not counted as health-check coverage.

| Phase | Chain ID | Implemented Health Checks | Notes |
| --- | --- | --- | --- |
| snapshot | `snapshot.session_only_skip_flap` | `BGP session uptime snapshot check` | Used by CICD-16. The general core-dump check is intentionally omitted so unrelated process crashes do not fail this BGP++-specific monitor. |

**Specification vs. implemented health checks**

| Required Validation | Implemented By | Coverage | Gap |
| --- | --- | --- | --- |
| BGP process remains alive and sessions remain healthy. | `snapshot.session_only_skip_flap` | partial | Session uptime is snapshotted, but BGP process liveness is validated only inside the custom step. |
| Queue and memory custom-step thresholds pass. | None | missing | Queue and memory thresholds have no playbook-level health check. |
| Route churn completes without a snapshot regression. | `snapshot.session_only_skip_flap` | partial | The session snapshot excludes expected flaps; route-churn completion is custom-step-local. |

**Validations outside the health-check chain**

- The queue and memory custom step monitors the BGP PID, focused queues, process memory, churn, and CPU stress.

**Expected runtime:** Sixty minutes of monitoring plus two-port topology setup.

**Primary triage signals**

- Fiber queue samples.
- Process memory and CPU-stress timeline.
- BGP PID and session state.

**Artifacts**

- Queue and process-memory time series.
- TAAC custom-step and session results.
- BGP and CPU-stress logs.

**Qualification difference:** Supplemental implementation-health signal; it does not establish complete G2-25 feature coverage.

## Scaling and Feature Regression

### CICD-17: Nexthop-group count threshold

- **Playbook:** `bgp_ebb_nexthop_group_count_threshold_playbook`
- **Factory:** `get_bgp_ebb_nexthop_group_count_threshold_playbook`
- **Requirements:** G2-25 (supplemental)
- **Required topology:** `neteng.test_infra.dne.taac.abstractions.topologies.ebb_full_scale.ebb_full_scale_topology`
- **Cadence:** Daily after threshold calibration.
- **Enforcement:** calibrating

**Purpose:** Detect nexthop-group allocation and cleanup regressions during route churn.

**Stimulus:** Oscillate 5,000 eBGP prefixes for 20 minutes, poll nexthop groups against threshold 100, then soak for five minutes.

**Scale:** Five thousand prefixes on the canonical full-scale topology.

**Blocking signals**

- Nexthop-group count remains below 100.
- Convergence completes within ten minutes.
- Snapshot, RIB, FIB, and session checks pass.

**Outcome validation traceability**

- **Health-check chain:** `soak_with_convergence`
- **Check profile:** `CheckProfile.SOAK_NO_PRECHECK`
- **Implementation:** `get_profile_checks(CheckProfile.SOAK_NO_PRECHECK)`

The chain below contains only playbook-level health checks. Trigger, step, task, and periodic-monitor assertions are not counted as health-check coverage.

| Phase | Chain ID | Implemented Health Checks | Notes |
| --- | --- | --- | --- |
| postcheck | `post.standard_with_convergence` | `postcheck_bgp_convergence_time`, `BGP session establishment`, `BGP stale-route check`, `BGP and system log parsing`, `rib_fib_consistency_postcheck`, `service restart detection` | Enforces final convergence and common BGP control-plane health. |
| snapshot | `snapshot.skip_flap_and_uptime` | `core-dump snapshot check`, `BGP session peer-identity snapshot check` | Expected flap and uptime changes are intentionally excluded. |

**Specification vs. implemented health checks**

| Required Validation | Implemented By | Coverage | Gap |
| --- | --- | --- | --- |
| Nexthop-group count remains below 100. | None | missing | The threshold is enforced by a periodic task, not a playbook-level health check. |
| Convergence completes within ten minutes. | `post.standard_with_convergence` | implemented | None |
| Snapshot, RIB, FIB, and session checks pass. | `post.standard_with_convergence`, `snapshot.skip_flap_and_uptime` | implemented | None |

**Validations outside the health-check chain**

- The nexthop-group polling periodic task enforces the count threshold during route oscillation.
- Standard CPU and memory periodic tasks run during the workload.

**Expected runtime:** Approximately 52 minutes including shared topology setup.

**Primary triage signals**

- Nexthop-group count series.
- Route actions and convergence timing.
- RIB, FIB, and session failures.

**Artifacts**

- Nexthop-group measurements.
- TAAC convergence and route checks.
- BGP and IXIA logs.

**Qualification difference:** Supplemental scale signal; it does not cover every best-path, Add-Path, or multipath permutation in G2-25.

### CICD-18: UPDATE packing

- **Playbook:** `bgp_ebb_update_packing_playbook`
- **Factory:** `get_bgp_ebb_update_packing_playbook`
- **Requirements:** G2-25 (supplemental)
- **Required topology:** `neteng.test_infra.dne.taac.abstractions.topologies.ipv6_update_packing.IPV6_UPDATE_PACKING`
- **Cadence:** Daily.
- **Enforcement:** blocking

**Purpose:** Detect UPDATE batching and packing-efficiency regressions.

**Stimulus:** Inject IPv6 routes from eBGP peers, restart BGP++ for a complete view, and capture UPDATEs at an iBGP peer for five minutes.

**Scale:** Ten eBGP peers with 10,000 IPv6 prefixes each and one iBGP capture peer.

**Blocking signals**

- Captured UPDATEs meet the minimum packed size of 4,000 prefixes.
- Custom packing validation completes successfully.
- BGP restart, IXIA protocols, and route acceptance remain healthy.

**Outcome validation traceability**

- **Health-check chain:** `custom_step_only`
- **Check profile:** None
- **Implementation:** `No playbook-level health checks`

The chain below contains only playbook-level health checks. Trigger, step, task, and periodic-monitor assertions are not counted as health-check coverage.

No playbook-level health-check chain is implemented.

**Specification vs. implemented health checks**

| Required Validation | Implemented By | Coverage | Gap |
| --- | --- | --- | --- |
| Captured UPDATEs meet the minimum packed size of 4,000 prefixes. | None | missing | Packing size is asserted only inside the custom step; no health-check chain exists. |
| Custom packing validation completes successfully. | None | missing | Custom-step completion is not a playbook-level health check. |
| BGP restart, IXIA protocols, and route acceptance remain healthy. | None | missing | These conditions are handled inside the custom step with no independent health checks. |

**Validations outside the health-check chain**

- The UPDATE-packing custom step drives IXIA, restarts BGP++, captures UPDATEs, and asserts packed size.

**Expected runtime:** Five minutes of capture plus topology setup; conveyor budget is three hours.

**Primary triage signals**

- Packed-size distribution.
- BGP restart and complete-view timing.
- IXIA route and session state.

**Artifacts**

- Packet capture and tshark analysis.
- TAAC custom-step result.
- BGP and IXIA logs.

**Qualification difference:** Supplemental packing signal; it does not replace the dedicated update-group correctness and backpressure suite.

### CICD-19: Constant attribute storage

- **Playbook:** `bgp_ebb_constant_attribute_storage_playbook`
- **Factory:** `get_bgp_ebb_constant_attribute_storage_playbook`
- **Requirements:** G2-25 (supplemental)
- **Required topology:** `legacy_two_port_ebb` (legacy; no artifact yet)
- **Cadence:** Daily.
- **Enforcement:** blocking

**Purpose:** Detect memory growth and canonicalization regressions in constant attribute storage.

**Stimulus:** Hold path and peer counts fixed while sweeping unique attribute combinations with two-minute soaks.

**Scale:** 800,000 received paths with 100,000 through 800,000 unique attribute combinations.

**Blocking signals**

- Required routes reach the RIB at every sweep point.
- Attribute assignments are collected successfully.
- The configured memory-growth gate passes.

**Outcome validation traceability**

- **Health-check chain:** `custom_step_only`
- **Check profile:** None
- **Implementation:** `No playbook-level health checks`

The chain below contains only playbook-level health checks. Trigger, step, task, and periodic-monitor assertions are not counted as health-check coverage.

No playbook-level health-check chain is implemented.

**Specification vs. implemented health checks**

| Required Validation | Implemented By | Coverage | Gap |
| --- | --- | --- | --- |
| Required routes reach the RIB at every sweep point. | None | missing | Route acceptance is asserted only inside the custom step; no health-check chain exists. |
| Attribute assignments are collected successfully. | None | missing | Attribute collection is custom-step-local and has no independent health check. |
| The configured memory-growth gate passes. | None | missing | The memory-growth gate is custom-step-local and has no independent health check. |

**Validations outside the health-check chain**

- The constant-attribute custom step validates route acceptance, assignment collection, and memory growth.

**Expected runtime:** At least 16 minutes of soak plus per-stage setup; conveyor budget is three hours.

**Primary triage signals**

- Attribute pools and assignment dumps.
- Accepted route counts at each sweep point.
- Process memory by combination count.

**Artifacts**

- Attribute-assignment dumps.
- Route-acceptance and memory measurements.
- TAAC stage results and BGP logs.

**Qualification difference:** Supplemental storage signal; it does not independently validate the complete community, AS-path, or policy feature matrices.

### CICD-20: Bounded ECMP sets

- **Playbook:** `bgp_ebb_bounded_ecmp_sets_playbook`
- **Factory:** `get_bgp_ebb_bounded_ecmp_sets_playbook`
- **Requirements:** G2-25 (supplemental)
- **Required topology:** `neteng.test_infra.dne.taac.abstractions.topologies.bounded_ecmp.BOUNDED_ECMP`
- **Cadence:** Daily after threshold calibration.
- **Enforcement:** calibrating

**Purpose:** Detect ECMP-set and nexthop-group growth regressions during route oscillation.

**Stimulus:** Oscillate 5,000 eBGP prefixes for 20 minutes, poll nexthop groups against threshold 50, then soak for five minutes.

**Scale:** 128 eBGP and 128 iBGP peers per AFI with 5,000 prefixes per peer.

**Blocking signals**

- Nexthop-group count remains below 50.
- Session, RIB, FIB, and convergence profile checks pass.
- Final state remains healthy after the soak.

**Outcome validation traceability**

- **Health-check chain:** `bounded_ecmp`
- **Check profile:** `CheckProfile.PERF_SCALING_BOUNDED_ECMP`
- **Implementation:** `get_profile_checks(CheckProfile.PERF_SCALING_BOUNDED_ECMP)`

The chain below contains only playbook-level health checks. Trigger, step, task, and periodic-monitor assertions are not counted as health-check coverage.

| Phase | Chain ID | Implemented Health Checks | Notes |
| --- | --- | --- | --- |
| postcheck | `post.bounded_ecmp` | `BGP session establishment`, `BGP RIB/FIB consistency`, `postcheck_bgp_convergence_time` | Minimal bounded-ECMP recovery chain with standardized retry behavior. |
| snapshot | `snapshot.skip_flap_and_uptime` | `core-dump snapshot check`, `BGP session peer-identity snapshot check` | Expected flap and uptime changes are intentionally excluded. |

**Specification vs. implemented health checks**

| Required Validation | Implemented By | Coverage | Gap |
| --- | --- | --- | --- |
| Nexthop-group count remains below 50. | None | missing | The threshold is enforced by a periodic task, not a playbook-level health check. |
| Session, RIB, FIB, and convergence profile checks pass. | `post.bounded_ecmp`, `snapshot.skip_flap_and_uptime` | implemented | None |
| Final state remains healthy after the soak. | `post.bounded_ecmp`, `snapshot.skip_flap_and_uptime` | implemented | None |

**Validations outside the health-check chain**

- The nexthop-group polling periodic task enforces the count threshold during route oscillation.
- Standard CPU and memory periodic tasks run in non-terminating mode.

**Expected runtime:** Twenty-five minutes of stimulus and soak plus topology setup; conveyor budget is three hours.

**Primary triage signals**

- Nexthop-group count series.
- Route actions and convergence timing.
- RIB, FIB, and session failures.

**Artifacts**

- Nexthop-group measurements.
- TAAC profile and convergence results.
- BGP and IXIA logs.

**Qualification difference:** Supplemental bounded-state signal; complete G2-25 feature coverage still requires dedicated weight, MED, enforce-first-as, and fast-reset cases.
