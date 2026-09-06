# MWG2 FPF GAR hardware results — 2026-08-28

## Outcome

- Automated playbooks: **38**.
- Passed: **29**.
- Failed with a device-health defect: **5**.
- Blocked by a mandatory precheck: **4**.
- Class B: **16/16 passed**.
- Class B-prime: **7/12 passed**; B-prime2 through B-prime6 undrain each
  created a new critical `bgpd_main` core on `gtsw001.l1002.c087.mwg2`.
- Class C: **6/6 passed**.
- Class A: **0/4 triggered** because
  `gtsw002.l1001.c087.mwg2` was already `DRAINED`. TAAC rejected every case
  before its trigger. The shared device was not undrained by this test run.

The B-prime route-reinjection RPC was corrected during execution. The first
single-RPC implementation timed out when sending 1,000 routes. Reinjection now
uses batches of 100 and succeeded on hardware. Drain-community and
normal-community reinjection is limited to the affected GTSW source that
originates the routes. STSWs and remote GTSWs are validation targets only.

## Result table

`VF` means the production NDP/HRT-originated prefix. `Scale` means every one of
the 1,000 directly injected BGP++ prefixes. Scale is intentionally not an
assertion in B-prime soft-drain/undrain playbooks because the BGP restart drops
runtime-injected routes; those playbooks reinject after drain and undrain.

| Playbook | Document test case | Trigger event | Post-check result | Overall |
| --- | --- | --- | --- | --- |
| `fpf_gar_a1_topology_info_all_planes` | Class A1 — topology information on all planes | Read-only GAR topology validation | Precheck: `gtsw002.l1001` was `DRAINED`.<br>Trigger: not run.<br>VF/Scale post-check: not run. | BLOCKED |
| `fpf_gar_a2_stsw_capacity_add_path` | Class A2 — STSW capacity/add-path | Read-only source → STSW → remote add-path validation | Precheck: `gtsw002.l1001` was `DRAINED`.<br>Trigger: not run.<br>VF/Scale post-check: not run. | BLOCKED |
| `fpf_gar_a3_remote_rib_fib_capacity` | Class A3 — remote RIB/FIB capacity | Read-only remote BGP/Agent validation | Precheck: `gtsw002.l1001` was `DRAINED`.<br>Trigger: not run.<br>VF/Scale post-check: not run. | BLOCKED |
| `fpf_gar_a4_multi_pod_origination` | Class A4 — multi-pod origination | Read-only bidirectional multi-pod validation | Precheck: `gtsw002.l1001` was `DRAINED`.<br>Trigger: not run.<br>VF/Scale post-check: not run. | BLOCKED |
| `fpf_gar_b1_admin_down_1` | B1 — disable 1 link | Admin-down 1 pair-A source link; capacity 36→35 | VF: pass.<br>Scale 1,000/1,000: pass.<br>Remote BGP candidates 36; GAR/Agent forwarding capacity 35.<br>Device health: pass. | PASS |
| `fpf_gar_b1_admin_up_1` | B1 recovery | Restore 1 link; capacity 35→36 | VF: pass.<br>Scale 1,000/1,000: pass.<br>Capacity restored to 36.<br>Device health: pass. | PASS |
| `fpf_gar_b2_admin_down_2` | B2 — disable 2 links | Admin-down 2 pair-A source links; capacity 36→34 | VF: pass.<br>Scale 1,000/1,000: pass.<br>Remote GAR/Agent forwarding capacity 34.<br>Device health: pass. | PASS |
| `fpf_gar_b2_admin_up_2` | B2 recovery | Restore 2 links; capacity 34→36 | VF: pass.<br>Scale 1,000/1,000: pass.<br>Capacity restored to 36.<br>Device health: pass. | PASS |
| `fpf_gar_b3_admin_down_3` | B3 — disable 3 links | Admin-down 3 pair-A source links; capacity 36→33 | VF: pass.<br>Scale 1,000/1,000: pass.<br>Remote GAR/Agent forwarding capacity 33.<br>Device health: pass. | PASS |
| `fpf_gar_b3_admin_up_3` | B3 recovery | Restore 3 links; capacity 33→36 | VF: pass.<br>Scale 1,000/1,000: pass.<br>Capacity restored to 36.<br>Device health: pass. | PASS |
| `fpf_gar_b4_admin_down_4` | B4 — disable 4 links | Admin-down 4 pair-A source links; capacity 36→32 | VF: pass.<br>Scale 1,000/1,000: pass.<br>Remote GAR/Agent forwarding capacity 32.<br>Device health: pass. | PASS |
| `fpf_gar_b4_admin_up_4` | B4 recovery | Restore 4 links; capacity 32→36 | VF: pass.<br>Scale 1,000/1,000: pass.<br>Capacity restored to 36.<br>Device health: pass. | PASS |
| `fpf_gar_b5_admin_down_6` | B5 — disable 6 links | Admin-down 6 pair-A source links; capacity 36→30 | VF: pass.<br>Scale 1,000/1,000: pass.<br>Remote GAR/Agent forwarding capacity 30.<br>Device health: pass. | PASS |
| `fpf_gar_b5_admin_up_6` | B5 recovery | Restore 6 links; capacity 30→36 | VF: pass.<br>Scale 1,000/1,000: pass.<br>Capacity restored to 36.<br>Device health: pass. | PASS |
| `fpf_gar_b6_admin_down_18` | B6 — disable 18 links | Admin-down 18 pair-A source links; capacity 36→18 | VF: pass.<br>Scale 1,000/1,000: pass.<br>Remote GAR/Agent forwarding capacity 18.<br>Device health: pass. | PASS |
| `fpf_gar_b6_admin_up_18` | B6 recovery | Restore 18 links; capacity 18→36 | VF: pass.<br>Scale 1,000/1,000: pass.<br>Capacity restored to 36.<br>Device health: pass. | PASS |
| `fpf_gar_b7a_admin_down_35` | B7a — disable 35 links | Admin-down 35 pair-A source links; capacity 36→1 | VF: pass.<br>Scale 1,000/1,000: pass.<br>Remote GAR/Agent forwarding capacity 1.<br>Device health: pass. | PASS |
| `fpf_gar_b7a_admin_up_35` | B7a recovery | Restore 35 links; capacity 1→36 | VF: pass.<br>Scale 1,000/1,000: pass.<br>Capacity restored to 36.<br>Device health: pass. | PASS |
| `fpf_gar_b7b_admin_down_36` | B7b — disable all 36 links | Admin-down all pair-A source links; capacity 36→0 | VF: pass.<br>Scale 1,000/1,000: pass.<br>Routes pruned from pair-A spine and remote BGP/Agent.<br>Device health: pass. | PASS |
| `fpf_gar_b7b_admin_up_36` | B7b recovery | Restore all 36 links; capacity 0→36 | VF: pass.<br>Scale 1,000/1,000: pass.<br>Routes and capacity restored to 36.<br>Device health: pass. | PASS |
| `fpf_gar_bprime1_softdrain_1` | B-prime1 — soft-drain 1 link | Soft-drain 1 source link; reinject 1,000 routes with `65446:10` | VF: pass at capacity 35.<br>Scale assertion: intentionally N/A.<br>Drain-community reinjection: pass.<br>No new core. | PASS |
| `fpf_gar_bprime1_undrain_1` | B-prime1 recovery | Undrain 1 link; reinject normal communities | VF: pass at restored capacity 36.<br>Scale assertion: intentionally N/A.<br>Normal-community reinjection: pass.<br>No new core. | PASS |
| `fpf_gar_bprime2_softdrain_2` | B-prime2 — soft-drain 2 links | Soft-drain 2 source links; reinject with `65446:10` | VF: pass at capacity 34.<br>Scale assertion: intentionally N/A.<br>Drain-community reinjection: pass.<br>No new core. | PASS |
| `fpf_gar_bprime2_undrain_2` | B-prime2 recovery | Undrain 2 links; reinject normal communities | VF: pass at capacity 36.<br>Normal-community reinjection: pass.<br>Drain/ports/BGP sessions: pass.<br>New critical `bgpd_main` core: fail. | FAIL |
| `fpf_gar_bprime3_softdrain_3` | B-prime3 — soft-drain 3 links | Soft-drain 3 source links; reinject with `65446:10` | VF: pass at capacity 33.<br>Scale assertion: intentionally N/A.<br>Drain-community reinjection: pass.<br>No new core. | PASS |
| `fpf_gar_bprime3_undrain_3` | B-prime3 recovery | Undrain 3 links; reinject normal communities | VF: pass at capacity 36.<br>Normal-community reinjection: pass.<br>Drain/ports/BGP sessions: pass.<br>New critical `bgpd_main` core: fail. | FAIL |
| `fpf_gar_bprime4_softdrain_4` | B-prime4 — soft-drain 4 links | Soft-drain 4 source links; reinject with `65446:10` | VF: pass at capacity 32.<br>Scale assertion: intentionally N/A.<br>Drain-community reinjection: pass.<br>No new core. | PASS |
| `fpf_gar_bprime4_undrain_4` | B-prime4 recovery | Undrain 4 links; reinject normal communities | VF: pass at capacity 36.<br>Normal-community reinjection: pass.<br>Drain/ports/BGP sessions: pass.<br>New critical `bgpd_main` core: fail. | FAIL |
| `fpf_gar_bprime5_softdrain_6` | B-prime5 — soft-drain 6 links | Soft-drain 6 source links; reinject with `65446:10` | VF: pass at capacity 30.<br>Scale assertion: intentionally N/A.<br>Drain-community reinjection: pass.<br>No new core. | PASS |
| `fpf_gar_bprime5_undrain_6` | B-prime5 recovery | Undrain 6 links; reinject normal communities | VF: pass at capacity 36.<br>Normal-community reinjection: pass.<br>Drain/ports/BGP sessions: pass.<br>New critical `bgpd_main` core: fail. | FAIL |
| `fpf_gar_bprime6_softdrain_18` | B-prime6 — soft-drain 18 links | Soft-drain 18 source links; reinject with `65446:10` | VF: pass at capacity 18.<br>Scale assertion: intentionally N/A.<br>Drain-community reinjection: pass.<br>No new core. | PASS |
| `fpf_gar_bprime6_undrain_18` | B-prime6 recovery | Undrain 18 links; reinject normal communities | VF: pass at capacity 36.<br>Normal-community reinjection: pass.<br>Drain/ports/BGP sessions: pass.<br>New critical `bgpd_main` core: fail. | FAIL |
| `fpf_gar_c1_multi_pair_3_6` | C1 — pair A:3, pair B:6 | Concurrent admin-down; A 36→33, B 36→30 | VF: pass on both pairs.<br>Scale 1,000/1,000: pass on both pairs.<br>BGP/Agent capacity: A=33, B=30.<br>Device health: pass. | PASS |
| `fpf_gar_c1_multi_pair_3_6_recovery` | C1 recovery | Concurrent restore; A/B→36 | VF: pass.<br>Scale 1,000/1,000: pass.<br>Both capacities restored to 36.<br>Device health: pass. | PASS |
| `fpf_gar_c2_multi_pair_2_6` | C2 — pair A:2, pair B:6 | Concurrent admin-down; A 36→34, B 36→30 | VF: pass on both pairs.<br>Scale 1,000/1,000: pass on both pairs.<br>BGP/Agent capacity: A=34, B=30.<br>Device health: pass. | PASS |
| `fpf_gar_c2_multi_pair_2_6_recovery` | C2 recovery | Concurrent restore; A/B→36 | VF: pass.<br>Scale 1,000/1,000: pass.<br>Both capacities restored to 36.<br>Device health: pass. | PASS |
| `fpf_gar_c3_multi_pair_4_6` | C3 — pair A:4, pair B:6 | Concurrent admin-down; A 36→32, B 36→30 | VF: pass on both pairs.<br>Scale 1,000/1,000: pass on both pairs.<br>BGP/Agent capacity: A=32, B=30.<br>Device health: pass. | PASS |
| `fpf_gar_c3_multi_pair_4_6_recovery` | C3 recovery | Concurrent restore; A/B→36 | VF: pass.<br>Scale 1,000/1,000: pass.<br>Both capacities restored to 36.<br>Device health: pass. | PASS |

## Run artifacts

| Scope | TestInfra | TAAC summary | Result |
| --- | --- | --- | --- |
| Class B and initial B-prime1 attempt | [18014398706031846](https://internalfb.com/intern/testinfra/testrun/18014398706031846) | [ym3setje](https://fburl.com/everpaste/ym3setje) | Class B 16/16 passed; initial B-prime1 failed on the now-fixed single-RPC timeout. |
| Corrected B-prime1 rerun | [17451448752387372](https://internalfb.com/intern/testinfra/testrun/17451448752387372) | [b6ozt9xm](https://fburl.com/everpaste/b6ozt9xm) | 2/2 passed. |
| B-prime2 execution | [33495522258114202](https://internalfb.com/intern/testinfra/testrun/33495522258114202) | [2mil7hog](https://fburl.com/everpaste/2mil7hog) | Soft-drain passed; undrain failed on a new `bgpd_main` core. |
| B-prime3 execution | [22799473155978717](https://internalfb.com/intern/testinfra/testrun/22799473155978717) | [orac5xl3](https://fburl.com/everpaste/orac5xl3) | Soft-drain passed; undrain failed on a new `bgpd_main` core. |
| B-prime4–6 and Class C | [14918173959076623](https://internalfb.com/intern/testinfra/testrun/14918173959076623) | [clbeil5f](https://fburl.com/everpaste/clbeil5f) | 9 passed, 3 undrain/core failures. |
| Class A gate run | [32369622351279715](https://internalfb.com/intern/testinfra/testrun/32369622351279715) | [akuwk67y](https://fburl.com/everpaste/akuwk67y) | 4/4 blocked before trigger by `gtsw002.l1001` drain state. |

## Validation and implementation notes

- TAAC used `TAAC_SSH_VIA_LAB_SSH=1`; SSH-dependent checks were not skipped.
- `TAAC_FPF_SKIP_SSH_DEPS=1` was not set or used.
- The route-injection TAAC step and standalone injection CLI accept
  `batch_size`; GAR reinjection uses 100-prefix RPC batches.
- The drain utility accepts an explicit `--interface` for safe recovery without
  shell SSH.
- Final focused Buck validation passed: 61 tests, 0 failures.
- Lint completed with only a pre-existing complexity advisory in
  `LongevityStep._run_with_port_state_collection`.
