# RBB SRv6 Test — Adopt & Run Guide

A two-node **SRv6** test for FBOSS switches. It checks that R1 encapsulates
traffic into an SRv6 core, R2 decapsulates it at the tail, and a direct
`TE_AGENT` route can take over and hand back to BGP — optionally sending real
IXIA traffic end to end.

The committed code has **no lab-specific values**. You bring your topology as
two CSV files plus a few environment variables. Unit tests run anywhere; a live
run needs real switches.

---

## Quick start (no hardware)

Just want to see the tests pass? Build the image and run the unit tests:

```bash
./scripts/validate.sh --skip-smoke                                # build the fboss-taac image
./scripts/validate.sh -- --continue-on-collection-errors -k rbb   # 58 RBB unit tests, all pass
```

That's it — no switches, no IXIA. (`--continue-on-collection-errors` is needed
because a few unrelated OSS suites fail to import; without it pytest stops
before the RBB tests run.)

---

## Adopt in 3 inputs

To run against **your** lab, you provide three things:

| # | Input | What it is |
| --- | --- | --- |
| 1 | `device_info.csv` | your two switches (hostname + `FBOSS`) |
| 2 | `circuit_info.csv` | how they're wired (core port-channels + IXIA edges) |
| 3 | a few env vars | SRv6 plan + login secrets |

Copy the bundled templates and edit them:

- [`topology/rbb_device_info.csv`](topology/rbb_device_info.csv)
- [`topology/rbb_circuit_info.csv`](topology/rbb_circuit_info.csv)

**1. `device_info.csv`** — only `hostname` and `operating_system` matter:

```
# hostname,ipv6_address,ipv4_address,mac_address,role,operating_system,hardware
<r1-host>,,,,RBB,FBOSS,CISCO_8501
<r2-host>,,,,RBB,FBOSS,CISCO_8501
```

**2. `circuit_info.csv`** — one row per link. The loader reads it to find the
core port-channels (rows where both ends are DUTs and a `local_parent_interface`
is set) and the IXIA edges (rows with `role=IXIA`, where the DUT interface maps
to an IXIA `slot/port` like `1/3`):

```
hostname,local_interface,local_platform,local_parent_interface,neighbor_hostname,neighbor_interface,neighbor_platform,neighbor_parent_interface,status,role
```

**3. Env vars** — the essentials to get running:

```bash
export TAAC_OSS=1
export TAAC_SSH_USER=<user>
source ~/.taac-secrets          # exports TAAC_SSH_PASSWORD (and TAAC_IXIA_PASSWORD for traffic)
export TAAC_RBB_R1_HOST=<r1-host>   # must match device_info.csv
export TAAC_RBB_R2_HOST=<r2-host>
export TAAC_RBB_SRV6_LOCATOR=2001:db8:6::/48   # your SRv6 locator
```

Keep passwords out of the command line — source them from a `chmod 600` file.
There are more optional knobs (uSIDs, tail prefix, provisioning); they all have
safe defaults and are documented in
`taac/testconfigs/routing/util/bgp_rbb_constants.py`.

---

## Run it

### Default: control-plane only, no IXIA (safe, non-destructive)

```bash
export TAAC_RBB_INCLUDE_TRAFFIC=0

./docker/run_taac_docker.sh run \
  env PYTHONDONTWRITEBYTECODE=1 \
  python3 -m taac.runner.oss_entry_point \
    --test-configs /workspace/examples/rbb_srv6_3_usids_config.py \
    --device-info-csv /workspace/examples/topology/rbb_device_info.csv \
    --circuit-info-csv /workspace/examples/topology/rbb_circuit_info.csv \
    --dut "$TAAC_RBB_R1_HOST" "$TAAC_RBB_R2_HOST" \
    --playbook bgp_rbb_srv6_3_usids
```

Expected: all stages `S08–S28` PASS, exit 0. Nothing on the switch is changed
permanently — the tail route reverts to BGP at the end.

### With live IXIA traffic

Set `TAAC_RBB_INCLUDE_TRAFFIC=1`, also set `TAAC_RBB_IXIA_CHASSIS` (the physical
chassis IP) and `TAAC_IXIA_PASSWORD`, then run the same command. This sends real
SRv6 packets from the IXIA edge and verifies receipt at the tail.

---

## What it tests

```mermaid
flowchart LR
    ixr1["IXIA (edge port)"]
    r1["R1: head/mid (FBOSS)"]
    r2["R2: tail (FBOSS)"]
    ixr2["IXIA (edge port)"]

    ixr1 ---|"edge eth"| r1
    r1 ---|"core PC (2 members)"| r2
    r2 ---|"edge eth"| ixr2
```

- **R1** encapsulates into the SRv6 core; **R2** decapsulates at the tail.
- Verifies the SRv6 my-SID table and core interface addresses.
- Exercises the `TE_AGENT` direct-route lifecycle: install → owner becomes
  `TE_AGENT` → withdraw → reverts to `BGPD`.
- With traffic enabled, confirms packets are received at the tail.

---

## Advanced: provision a bare switch from scratch (opt-in)

By default the test assumes the switch underlay (ports, port-channels, SRv6,
iBGP, OpenR) is already up. For a **freshly imaged MORGAN800CC** with no config,
TaaC can generate and push the whole underlay first:

```bash
export TAAC_RBB_PROVISION=1
```

> **Disruptive:** this restarts the agent, bgpd, and openr. It is guarded to
> MORGAN800CC only, backs up the original config once (`<path>.taac-orig`), and
> skips if already provisioned. Use only on a switch you intend to (re)provision.

It builds `agent.conf`, `bgp.json`, and `openr.conf` from your CSVs + env; the
hardware-specific board descriptor and port identity are read from the switch
itself. All provisioning knobs are documented in
`taac/testconfigs/routing/util/bgp_rbb_constants.py`.

---

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| Unit tests report `0 tests ran` | Add `--continue-on-collection-errors` (see Quick start). |
| `/etc/coop/bgpcpp.conf is missing` on setup | Bare switch — add `--skip-oss-setup-tasks`, or provision with `TAAC_RBB_PROVISION=1`. |
| IXIA `test port hosts ... are not in a ready state` | `TAAC_RBB_IXIA_CHASSIS` must be the **physical chassis** IP, not the IxNetwork API server. |
| `Ixia password ... does not contain a valid password` | Set `TAAC_IXIA_PASSWORD` in the environment. |
| Config builds but nothing runs live | Make sure the CSVs describe your fleet and `--dut` values match the hostnames. |

---

## Reference

- Build / image / driver docs: [`../README.md`](../README.md),
  [`../docker/README.md`](../docker/README.md)
- All `TAAC_RBB_*` env vars (with defaults):
  `taac/testconfigs/routing/util/bgp_rbb_constants.py`
- Suite internals are documented in the module docstrings under
  `taac/tasks/`, `taac/testconfigs/routing/util/`, and the `qual_rbb/` factories.
