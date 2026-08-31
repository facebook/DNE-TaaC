# MWG2 FPF GAR Class A tests

`fpf_gar_class_a` automates the four functional GAR cases across all eight
planes and both MWG2 test pods. It is intentionally separate from
`fpf_gar_class_b_c`, so a single-link Class B run retains its smaller six-device
scope.

## Topology and route injection

The config includes 16 GTSWs and eight STSWs. Only
`gtsw001.l1002.c087.mwg2` is marked as the TAAC controller/DUT, so each
topology-scoped playbook executes once.

Four independent 1,000-prefix ranges are injected with the existing `gtsw`
community preset:

| Source pod | VF planes | Prefix range | Source devices |
| --- | --- | --- | --- |
| l1002 | 1-4 | `5000:ca::/64` | `gtsw001`-`gtsw004.l1002.c087.mwg2` |
| l1002 | 5-8 | `5000:cb::/64` | `gtsw005`-`gtsw008.l1002.c087.mwg2` |
| l1001 | 1-4 | `5000:cc::/64` | `gtsw001`-`gtsw004.l1001.c087.mwg2` |
| l1001 | 5-8 | `5000:cd::/64` | `gtsw005`-`gtsw008.l1001.c087.mwg2` |

These are direct BGP++ `addNetworks()` routes. They are local drop routes and
are not NDP-conditional. Setup first removes stale copies, injection uses
100-prefix batches, and teardown withdraws every range.

Every Class A playbook also validates the production VF1 prefix
`2401:db00:292a:a284::/64`, sourced by `rtptest1555.mwg2` GPU 0, across
planes 1-4. This is the independent NDP/HRT-originated signal; it is checked
alongside, not replaced by, the complete 1,000-prefix injected scale ranges.

## Automated cases

- `fpf_gar_a1_topology_info_all_planes` verifies every plane has the expected
  source and STSW paths and that the remote GTSW BGP and Agent next hops carry
  the expected `remote_rack_capacity` and `spine_id=1`.
- `fpf_gar_a2_stsw_capacity_add_path` validates the BGP path chain: one local
  source path, source-capacity paths on the STSW, and the complete remote
  add-path set with the encoded GAR capacity.
- `fpf_gar_a3_remote_rib_fib_capacity` focuses on the receiving GTSWs and checks
  all injected prefixes in both the BGP RIB and Agent FIB.
- `fpf_gar_a4_multi_pod_origination` runs the full source, spine, and remote
  BGP/Agent contract in both directions, independently for both VF groups.

The known plane-3 asymmetry is represented explicitly. The l1002 plane-3
source/observer bundle defaults to 34 links; override it with
`FPF_GAR_PLANE3_CAPACITY` after the two links are repaired.

All Class A playbooks run both `FPF_GAR_VF_CAPACITY_CHECK` and
`FPF_GAR_SCALE_CAPACITY_CHECK`. They retain the SSH-dependent process,
unclean-exit, and core-dump checks. `TAAC_FPF_SKIP_SSH_DEPS` is not consulted
by this config.

## Running

```text
TAAC_SSH_VIA_LAB_SSH=1 FPF_GAR_PREFIX_COUNT=1000 \
buck2 run neteng/netcastle:netcastle_taac -- \
  --team taac \
  --test-config fpf_gar_class_a \
  --dev \
  --skip-basset-reservation \
  --skip-testbed-isolation \
  --debug \
  --skip-fboss-rsyslog
```

Run one case with `--regex`, for example:

```text
--regex fpf_gar_a4_multi_pod_origination
```
