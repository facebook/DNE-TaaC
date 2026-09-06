# MWG2 FPF GAR Class B, B-prime, and C tests

This TAAC configuration exercises GAR capacity advertisement and route pruning
using only the GTSW-to-STSW network links. It does not disrupt GTSW downlinks or
require an IXIA traffic topology.

## Topology

| Pair | Role | Device | SSH `hostname` responsive |
| --- | --- | --- | --- |
| A, plane 1 | Source GTSW | `gtsw001.l1002.c087.mwg2` | Yes |
| A, plane 1 | Plane STSW | `stsw001.s001.l202.mwg2` | Yes |
| A, plane 1 | Remote observer GTSW | `gtsw001.l1001.c087.mwg2` | Yes |
| B, plane 4 | Source GTSW | `gtsw004.l1002.c087.mwg2` | Yes |
| B, plane 4 | Plane STSW | `stsw001.s004.l202.mwg2` | Yes |
| B, plane 4 | Remote observer GTSW | `gtsw004.l1001.c087.mwg2` | Yes |

Each GTSW-to-STSW bundle has 36 members. Class B and B-prime validate only pair
A. The selected plane-4 pair is used only by the multi-pair Class C cases; it is
not treated as a control or baseline for Class B.
Only pair A's source is marked as the TAAC DUT, so each controller-scoped
playbook runs once; the other five endpoints remain available to health checks
and GAR signal validation.

SSH responsiveness was verified on 2026-08-27 by running `hostname` through
the lab-ssh MCP. `fboss2 show port` also completed successfully on all six
switches. TAAC's internal AsyncSSH authentication failures are not treated as a
lab-ssh connectivity result.

## First B1 run and pre-health evidence

The original combined B1 run passed:

- TestInfra: `https://internalfb.com/intern/testinfra/testrun/5629499921632752`
- Run ID: `26310934087b426d8d9fab9637da12cf`
- Detailed log: `https://fburl.com/everpaste/76hkic0q`

Its pre-test phase ran seven TAAC check types. BGP session health passed at
37/39 (95%) on each GTSW and 73/103 (71%) on each STSW. Port state,
wedge-agent configuration, systemctl state, unclean exits, and device core
dumps passed on all six devices. BGP RIB/FIB consistency returned SKIP on all
six devices. Consequently, the concise TAAC summary reported seven check types
passed, while the expanded device table contained 36 PASS and six SKIP results.

The earlier GAR result wording was incomplete. After disabling
`gtsw001.l1002.c087.mwg2:eth1/2/1`, the remote
`gtsw001.l1001.c087.mwg2` retained 36 BGP/client paths, but every path carried
`remote_rack_capacity=35`, and the Agent forwarding set was pruned to 35. The
new health-check report exposes all three numbers separately.

The final split-playbook validation passed both phases on 2026-08-27:

- TestInfra: `https://internalfb.com/intern/testinfra/testrun/2251800203989845`
- Run ID: `1db81125ebf946d0a19d5b05dc08a6a7`
- Summary: `https://fburl.com/everpaste/c3ggovv8`
- Detailed log: `https://fburl.com/everpaste/ckk5i6qf`

The recovery port check initially observed both ends down, retried, and passed
on attempt 2 after approximately 14.5 seconds. Both GAR checks independently
passed at restored capacity 36.

## Scaled route setup

The setup task first withdraws any stale test routes and then injects the same
IPv6 route set from both source GTSWs. By default it injects 1,000 prefixes,
starting at `5000:ca::/64` with increment `0:0:1::`. The routes carry the GTSW
community set used by GAR. Injection and withdrawal use 100-prefix batches to
stay below the BGP++ ServiceRouter RPC timeout. The teardown task withdraws the
complete set.

The scale can be changed with `FPF_GAR_PREFIX_COUNT`. Convergence timeout and
post-injection settling can be adjusted with `FPF_GAR_VALIDATION_TIMEOUT_SEC`
and `FPF_GAR_INJECT_SETTLE_SEC`.

Every baseline, disrupted, and restored state evaluates every injected prefix,
not a sample. The production VF check separately evaluates
`2401:db00:292a:a284::/64`, sourced from `rtptest1555.mwg2` GPU 0.

## Test cases

| Class | Failure action | Expected capacity |
| --- | --- | --- |
| B1-B6 | Administratively disable 1, 2, 3, 4, 6, or 18 links on pair A | 35, 34, 33, 32, 30, or 18 |
| B7a | Administratively disable 35 links on pair A | 1 |
| B7b | Administratively disable all 36 links on pair A | 0; routes must be pruned from its spine and observer |
| B-prime1-B-prime6 | Soft-drain 1, 2, 3, 4, 6, or 18 links on pair A while physical links remain up | 35, 34, 33, 32, 30, or 18 |
| C1 | Disable 3 links on pair A and 6 links on pair B concurrently | A=33, B=30 |
| C2 | Disable 2 links on pair A and 6 links on pair B concurrently | A=34, B=30 |
| C3 | Disable 4 links on pair A and 6 links on pair B concurrently | A=32, B=30 |

Each case is represented by two playbooks:

- The disruption playbook validates the healthy 36-link baseline, disables or
  drains only the requested interface set, and ends by validating the degraded
  GAR state. It intentionally leaves the requested state in place.
- The recovery playbook first validates that degraded state, enables or
  undrains the same interfaces, and ends by validating full recovery to 36.
  Its cleanup repeats the restore operation for safety.

For example, `fpf_gar_b1_admin_down_1` and `fpf_gar_b1_admin_up_1` are separate
playbooks. Run the recovery playbook after the disruption playbook.

## Two GAR health checks

Both checks are first-class TAAC point-in-time health checks and run in the
precheck/postcheck phases for admin-down and recovery cases:

- `FPF_GAR_VF_CAPACITY_CHECK` validates a real production VF prefix.
- `FPF_GAR_SCALE_CAPACITY_CHECK` validates every prefix injected by the setup
  task.

Soft link-drain and link-undrain cases use the production VF check as the
authoritative GAR assertion and intentionally omit the scale check because the
drain operation restarts BGP and removes runtime-injected routes. Immediately
after drain, TAAC re-injects all 1,000 prefixes only on each affected source
GTSW that originates those prefixes, using the normal GTSW community set plus
drain marker `65446:10`. Immediately after undrain (and in recovery cleanup),
it re-injects the same prefixes with the normal GTSW community set, again only
on the affected injecting source. No injection or reinjection step runs on the
STSW or remote observer; those devices are validation targets only.

They share the same evaluator and produce the same detailed BGP and Agent
histograms. The checks cover the source in l1002, the plane STSW, and—most
importantly—the remote observer in l1001.

## Signals checked for every prefix

On the source GTSW:

- BGP++ contains one locally originated path.
- For the production VF signal, FBOSS Agent contains one local client and
  forwarding next hop.
- For the injected scale signal, FBOSS Agent contains the corresponding local
  `Drop` route created by prefix injection.

On the plane STSW when capacity is nonzero:

- BGP++ best-path count equals the number of surviving bundle members.
- FBOSS Agent client and forwarding next-hop counts equal the same capacity.

On the remote observer GTSW when capacity is nonzero:

- BGP++ retains 36 candidate/best paths. This path count is not the GAR
  capacity.
- Every BGP path carries the expected `remote_rack_capacity` and `spine_id`.
- FBOSS Agent retains 36 client next hops but prunes the forwarding next-hop
  set to the expected capacity.
- Every Agent client next hop carries the expected GAR capacity and spine ID.

At zero capacity, the source route must remain present while every injected
prefix must disappear from both BGP and Agent on the plane STSW and remote
observer. This is the scaled route-pruning assertion.

## Health and safety gates

The healthy baseline and recovered state run BGP session health (at least 70%
established), explicit target-port state, wedge-agent configuration, and BGP
RIB/FIB consistency. Port-state validation retries every 10 seconds for up to
five minutes so a 400G link has time to retrain after the recovery trigger.
The intentionally degraded state omits the generic BGP
session and RIB/FIB checks, because a complete 36-link failure is expected to
invalidate them; it still checks process health, crashes, cores, and both
GAR-specific checks. For admin-down states, target admin state is read back by
the trigger step and the generic topology port check is omitted:
the peer STSW port is also expected to go operationally down, and the generic
check cannot infer that peer interface from the explicit GTSW-only target.

`TAAC_SSH_VIA_LAB_SSH=1` only selects lab-ssh as TAAC's SSH transport; it does
not skip checks. This GAR configuration always includes its SSH-dependent
systemctl, unclean-exit, and core-dump checks, even if
`TAAC_FPF_SKIP_SSH_DEPS=1` is present in the environment.

## Standalone health-check binary

The binary invokes the same health-check classes used by TAAC:

```text
# Exercise PASS and FAIL contracts using synthetic switch snapshots.
buck2 run fbcode//scripts/pavanpatil:fpf_gar_health_check_test -- \
  --expected-capacity 35 --scale-prefix-count 4

# Read-only live validation of the production VF prefix at baseline.
TAAC_SSH_VIA_LAB_SSH=1 \
buck2 run fbcode//scripts/pavanpatil:fpf_gar_health_check_test -- \
  --live --check vf --expected-capacity 36 \
  --vf-prefix 2401:db00:292a:a284::/64
```

## Running

```text
TAAC_SSH_VIA_LAB_SSH=1 FPF_GAR_PREFIX_COUNT=1000 \
buck2 run neteng/netcastle:netcastle_taac -- \
  --team taac \
  --test-config fpf_gar_class_b_c \
  --dev \
  --skip-basset-reservation \
  --skip-testbed-isolation \
  --debug \
  --skip-fboss-rsyslog
```

To run B1 as the requested two-phase flow, run the disruption and then the
recovery playbook together in sequence:

```text
--regex 'fpf_gar_b1_admin_(down|up)_1'
```
