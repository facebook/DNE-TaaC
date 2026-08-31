# MWG2 FPF GAR hardware results — 2026-08-29 to 2026-08-30

## Outcome

- The FBOSS driver now sends one bulk `softdrain_interfaces` or
  `undrain_interfaces` request per device instead of one request per interface.
- A two-interface hardware regression passed for both soft-drain and undrain.
- Class C: **6/6 playbooks passed** (three disruptions and three recoveries).
- Class D: **8/8 playbooks have a passing final execution** after correcting
  the drain expectation to route preservation plus drain/topology attributes.
- Every Class D drain operation completed and its per-device drain state was
  read back successfully.
- No new core dump or unclean exit was detected in the final Class C, Class D,
  or bulk-interface regression runs.
- Scale prefixes were injected for load. As requested, scale was not used as a
  pass/fail signal for soft-drain or device-drain tests because the BGP restart
  removes runtime-injected prefixes. Source GTSWs were reinjected after drain
  with community `65446:10` and after undrain with normal `gtsw` communities.

## Driver change

For each device, the link-disruption step now groups all target interfaces and
calls the driver once:

```python
await driver.async_softdrain_interfaces(interfaces)
await driver.async_undrain_interfaces(interfaces)
```

The driver delegates to the corresponding local FBOSS bulk APIs:

```python
await client.softdrain_interfaces(interfaces, task_id)
await client.undrain_interfaces(interfaces)
```

Per-interface state is still read back after the bulk mutation, so one failed
or unchanged interface remains independently visible to TAAC.

## Hardware results

| Playbook | Test case | Trigger | Post-check result | Overall |
| --- | --- | --- | --- | --- |
| `fpf_gar_c1_multi_pair_3_6` | Class C1 — pair A:3, pair B:6 | Concurrent admin-down on l1001 and l1002 plane-1 links | VF and all 1,000 scale prefixes passed. l1001-originated route: spine 33, remote BGP/client 30, forwarding 30. l1002-originated route: spine 30, remote BGP/client 33, forwarding 30. | PASS |
| `fpf_gar_c1_multi_pair_3_6_recovery` | C1 recovery | Restore both link sets | VF and all scale prefixes restored to capacity 36. | PASS |
| `fpf_gar_c2_multi_pair_2_6` | Class C2 — pair A:2, pair B:6 | Concurrent admin-down on l1001 and l1002 plane-1 links | VF and all 1,000 scale prefixes passed. Expected reciprocal GAR capacities A=34 and B=30 were observed. | PASS |
| `fpf_gar_c2_multi_pair_2_6_recovery` | C2 recovery | Restore both link sets | VF and all scale prefixes restored to capacity 36. | PASS |
| `fpf_gar_c3_multi_pair_4_6` | Class C3 — pair A:4, pair B:6 | Concurrent admin-down on l1001 and l1002 plane-1 links | VF and all 1,000 scale prefixes passed. l1001 observer client capacity was 32 and forwarding capacity was 30, proving the three overlapping failures plus one additional pruned path were accounted for. | PASS |
| `fpf_gar_c3_multi_pair_4_6_recovery` | C3 recovery | Restore both link sets | VF and all scale prefixes restored to capacity 36. | PASS |
| `fpf_gar_d1_gtsw_plane1_drain` | D-tc1 — GTSW plane 1 drain | Soft-drain `gtsw001.l1002.c087.mwg2`; reinject scale with drain community | VF remained at capacity 36 in source, spine, and receiver BGP/Agent. The spine and receiving GTSW carried `65446:10`; receiving BGP and Agent retained `rack_id`, `spine_id`, and `remote_rack_capacity`. | PASS |
| `fpf_gar_d1_gtsw_plane1_drain_recovery` | D-tc1 recovery | Undrain source GTSW; reinject normal communities | VF remained/restored at 36, receiver rack-topology attributes remained present, and `65446:10` was absent from spine and receiver paths. | PASS |
| `fpf_gar_d2_stsw_plane1_drain` | D-tc2 — STSW plane 1 drain | Soft-drain `stsw001.s001.l202.mwg2` | VF remained at capacity 36. The receiving GTSW retained rack-topology attributes and carried `65446:10`; the source-to-spine path correctly did not carry the drain community. | PASS |
| `fpf_gar_d2_stsw_plane1_drain_recovery` | D-tc2 recovery | Undrain plane-1 STSW | VF remained/restored at 36 with receiver topology present and no stale drain community. | PASS |
| `fpf_gar_d3_gtsw_stsw_plane1_drain` | D-tc3 — GTSW + STSW plane 1 drain | Concurrently soft-drain the plane-1 source GTSW and STSW; reinject scale with drain community | Both drain states passed. VF remained at 36; spine and receiver carried `65446:10`, and receiver BGP/Agent retained all required rack-topology fields. | PASS |
| `fpf_gar_d3_gtsw_stsw_plane1_drain_recovery` | D-tc3 recovery | Concurrently undrain both devices; reinject normal communities | Both devices became undrained; VF remained/restored at 36 and no stale drain community remained. | PASS |
| `fpf_gar_d4_gtsw_plane1_stsw_plane2_drain` | D-tc4 — GTSW plane 1 + STSW plane 2 drain | Concurrently soft-drain the plane-1 source GTSW and plane-2 STSW; reinject scale with drain community | Plane 1 showed the drain community at spine and receiver. Plane 2 showed it at the receiver but not its spine. The independent plane 4 had no drain community. All monitored VFs remained at 36 with receiver topology intact. | PASS |
| `fpf_gar_d4_gtsw_plane1_stsw_plane2_drain_recovery` | D-tc4 recovery | Concurrently undrain both devices; reinject normal communities | Both devices became undrained; all three monitored planes were at 36 and no stale drain community remained. | PASS |
| `fpf_gar_bprime2_softdrain_2` | Bulk API regression — soft-drain two interfaces | One bulk request for `eth1/2/1` and `eth1/2/5` on `gtsw001.l1002.c087.mwg2` | VF capacity changed from 36 to 34; services, sessions, drain state, ports, cores, and unclean exits passed. | PASS |
| `fpf_gar_bprime2_undrain_2` | Bulk API regression — undrain two interfaces | One bulk request for both interfaces | VF capacity returned to 36; no new `bgpd_main` core was created. | PASS |

## Corrected Class D interpretation

The original Class D result was a false negative caused by asserting route
withdrawal. Device soft drain intentionally preserves the VF routes in this
topology. The meaningful assertions are now:

- every requested device reports the expected drain state;
- the production VF stays present in source, spine, and receiving-GTSW BGP and
  Agent state with capacity 36;
- the receiving GTSW retains decoded rack-topology fields (`rack_id`,
  `spine_id`, and `remote_rack_capacity`) in both BGP and Agent next-hop state;
- `65446:10` appears at the appropriate downstream BGP observation points while
  drained and is absent after recovery;
- recovery independently verifies undrain state, normal route capacity, and no
  stale drain community.

An initial D3 rerun was blocked before its trigger because `bgpd` was sampled
while still restarting after the preceding recovery. The system-service check
now retries for up to 120 seconds. Its focused unit test passed, and the D3
drain/recovery rerun subsequently passed 2/2.

## Run artifacts

| Scope | TestInfra | TAAC summary | Console log | Result |
| --- | --- | --- | --- | --- |
| Class C (3/6, 2/6, 4/6 plus recovery) | [15481123912926916](https://internalfb.com/intern/testinfra/testrun/15481123912926916) | [xgdy15pt](https://fburl.com/everpaste/xgdy15pt) | [GE0k9i5GWw7QXTMFAKGyp3hPW-RRbr0LAAAz](https://www.internalfb.com/intern/everpaste/?color=0&handle=GE0k9i5GWw7QXTMFAKGyp3hPW-RRbr0LAAAz) | 6 passed, 0 failed |
| Corrected Class D1 plus recovery | [35747322072363685](https://internalfb.com/intern/testinfra/testrun/35747322072363685) | [GGIOvCkR9ujAavACAE4wkrANLaBGbr0LAAAz](https://www.internalfb.com/intern/everpaste/?color=1&handle=GGIOvCkR9ujAavACAE4wkrANLaBGbr0LAAAz) | [GCBhpCdJ16Uk5f9lAGc7QsczFXsFbr0LAAAz](https://www.internalfb.com/intern/everpaste/?color=0&handle=GCBhpCdJ16Uk5f9lAGc7QsczFXsFbr0LAAAz) | 2 passed, 0 failed |
| Corrected Class D2 and D4 plus recoveries | [15481123913089348](https://internalfb.com/intern/testinfra/testrun/15481123913089348) | [GLVm9i7BxbSuvBgJAOgRz4zk4ucIbr0LAAAz](https://www.internalfb.com/intern/everpaste/?color=1&handle=GLVm9i7BxbSuvBgJAOgRz4zk4ucIbr0LAAAz) | [GF5m9i7_9HCNeuMHAEfXwf5dttoVbr0LAAAz](https://www.internalfb.com/intern/everpaste/?color=0&handle=GF5m9i7_9HCNeuMHAEfXwf5dttoVbr0LAAAz) | D2/D2 recovery/D4/D4 recovery passed; initial D3 attempt was pre-trigger blocked |
| Corrected D3 retry plus recovery | [26458647853789361](https://internalfb.com/intern/testinfra/testrun/26458647853789361) | [GDiZPiqOidaW6L0DAOCEI99Rq7Mibr0LAAAz](https://www.internalfb.com/intern/everpaste/?color=1&handle=GDiZPiqOidaW6L0DAOCEI99Rq7Mibr0LAAAz) | [GDEDDCXpkU6ANRNlAD7m8aSPWXldbr0LAAAz](https://www.internalfb.com/intern/everpaste/?color=0&handle=GDEDDCXpkU6ANRNlAD7m8aSPWXldbr0LAAAz) | 2 passed, 0 failed |
| Two-interface bulk soft-drain/undrain regression | [1970325227714981](https://internalfb.com/intern/testinfra/testrun/1970325227714981) | [g1wr9wfu](https://fburl.com/everpaste/g1wr9wfu) | [GI_iqRaa7JZ5IVEDAPZ6VD4Ij9wZbr0LAAAz](https://www.internalfb.com/intern/everpaste/?color=0&handle=GI_iqRaa7JZ5IVEDAPZ6VD4Ij9wZbr0LAAAz) | 2 passed, 0 failed |

## Code validation

- Focused TAAC suite: 62 passed, 0 failed — TestInfra
  [34621422165348177](https://www.internalfb.com/intern/testinfra/testrun/34621422165348177).
- Bulk driver tests: 2 passed, 0 failed — TestInfra
  [10696049309083031](https://www.internalfb.com/intern/testinfra/testrun/10696049309083031).
- Corrected Class C config tests: 12 passed, 0 failed — TestInfra
  [16888498799332877](https://www.internalfb.com/intern/testinfra/testrun/16888498799332877).
- Drain-state and Class D config tests after the recovery-precheck change: 11
  passed, 0 failed — TestInfra
  [29273397607858374](https://www.internalfb.com/intern/testinfra/testrun/29273397607858374).
- Class D service-retry config test: 9 passed, 0 failed — TestInfra
  [9570149402416106](https://www.internalfb.com/intern/testinfra/testrun/9570149402416106).
- Final GAR checker and Class D config suite: 20 passed, 0 failed — TestInfra
  [13510799076109640](https://www.internalfb.com/intern/testinfra/testrun/13510799076109640).
- Configerator schema validation: `conf build` passed, mutation `6376642109`.
  The FBCode Thrift mirror was then regenerated with
  `configerator-thrift-updater -c /data/users/pavanpatil/configerator --force-sync neteng/taac/health_check.thrift`.
  The source change is still uncommitted in the Configerator checkout, so no
  Configerator Phabricator diff ID exists yet.
- SSH-dependent checks ran through `TAAC_SSH_VIA_LAB_SSH=1`.
  `TAAC_FPF_SKIP_SSH_DEPS=1` was not used.
- Targeted lint has no new blocking issue. The only remaining messages in the
  broader touched-file lint are pre-existing complexity advice and a legacy
  Thrift-import warning.
