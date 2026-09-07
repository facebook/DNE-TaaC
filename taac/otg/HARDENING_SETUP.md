# OTG Hardening Conveyor — Testbed Setup

What the DUT, BGP and OTG side need before running one of the
`taac/otg/otg_hardening_*_test_config.py` profiles. COOP patchers are unavailable
in OSS mode, so the DUT is configured by hand.

Every value here is what the configs actually build. If you change their
constants, regenerate rather than trusting this file — the dry run at the bottom
prints the interface and session counts.

Playbook behaviour and the upstream fidelity analysis are in
`taac/otg/README.md`.

## Which config to run

ixia-c community edition caps **two different things** at 4 each:

| ixia-c term | Actually counts |
|---|---|
| control plane connected interfaces | configured **IP addresses**, per simulated device per address family |
| control plane sessions | **BGP peers**, same granularity |

Interfaces is usually the binding constraint — a device can carry an address
without a peer, never the reverse. Two traps:

- **`enable=False` does not help.** ixia-c counts the pushed config, not what is
  up.
- **Dropping a peer but keeping its address saves a session, not an interface.**
  Freeing an interface means dropping the address, which also removes that
  family's measured flow.

Hence three profiles, each independently runnable and inside the budget. There is
deliberately **no all-eight-in-one-run config**: one existed, could not run on
community edition, and silently rotted because nothing exercised it. A licensed
deployment runs the three back to back, which isolates failures better anyway.

| Config | Interfaces | Sessions | Playbooks | Measured flows |
|---|---|---|---|---|
| `otg_hardening_restarts_test_config.py` | 4/4 | 4/4 | 4 restarts + `cpu_high_priority_queue_overload` | V4 + V6 connected |
| `otg_hardening_ecmp_test_config.py` | 4/4 | 2/4 | both ECMP overload tests | V6 connected + `ECMP_FORWARDING_V6` |
| `otg_hardening_malformed_test_config.py` | 3/4 | 2/4 | `bgp_malformed_packet_test` | V4 connected + `GOOD_PREFIX_V4` |

Only restarts can afford a dual-stack measured path, and it is the profile whose
assertions lean most on BGP convergence. The others run one family so their extra
device groups fit: v6 for ECMP (the aggregate is v6, so traffic exercising it must
match), v4 for malformed (the malformations are legacy NEXT_HOP / AS_PATH /
ORIGIN violations, i.e. IPv4 BGP).

Each profile declares `max_cp_interfaces` and `max_bgp_sessions`, so exceeding
either fails at config-build time naming the dimension and the knobs, rather than
as an opaque HTTP 500 from the controller.

### Prefix-targeted flows

The ECMP and malformed profiles each add a flow addressed **into a BGP-advertised
prefix** rather than at a device group's own interface, via `network_group_index`
on the destination endpoint. That is what makes traffic traverse a BGP route
instead of a connected one, and how upstream's `_DIRECTIONAL_` items work. Without
it both profiles are pure liveness probes, detecting only total forwarding death.

| Flow | Destination | Asserts |
|---|---|---|
| `ECMP_FORWARDING_V6` | `2001:db8:ec00::1`, inside the ECMP aggregate | the DUT resolves through its **multipath** route, exposing wrong next-hop selection or a blackholed path |
| `GOOD_PREFIX_V4` | `100.1.0.1`, inside port 1's normally-advertised prefix | malformed UPDATEs from one peer do **not** disturb a valid route from another |

## Ports and the circuit CSV

Two TGEN links to one DUT; the whole port topology comes from the CSV. Ten
positional columns, no header parsed, `#` lines are comments, short rows padded:

```
hostname, local_interface, local_platform, local_parent_interface,
neighbor_hostname, neighbor_interface, neighbor_platform, neighbor_parent_interface,
status, role_name
```

A row is skipped if `hostname`, `local_interface`, `neighbor_hostname` or
`neighbor_interface` is empty. Working example for ixia-c-one:

```
device,eth1/9/1,FBOSS,,ixia,eth1,ixia,,3,IXIA
device,eth1/10/1,FBOSS,,ixia,eth2,ixia,,3,IXIA
```

### What makes a row a TGEN link

From `_classify_link` in `taac/runner/oss_entry_point.py`:

1. **`neighbor_platform` must contain `"ixia"`** — case-insensitive substring, so
   `ixia`, `IXIA` and `ixia-c` all work. This one check produces `LinkType.TGEN`.
2. **`hostname` must differ from `neighbor_hostname`** — the `SNAKE` test runs
   first, so reusing the DUT's name silently yields a snake link.
3. **`hostname` must match `--dut`** — other rows are dropped.

Both failure modes surface as *"requires at least 2 TGEN links"*; only the logged
topology (`{'unknown': ...}` vs `{'snake': ...}`) distinguishes them.

### `neighbor_interface` is the OTG port location

It becomes snappi's `port.location` verbatim.

- **ixia-c-one** — the interface name *inside the container*, e.g. `eth1`, `eth2`
  (matches the macvlan links in
  `examples/topology/otg_l3_forwarding_sample_containerlab.yml`).
- **ixia-c multi-container** — a traffic-engine host:port form. Confirm against
  your controller.
- **Keysight hardware OTG** — the controller endpoint.

### Two gotchas

**Row order sets the addressing.** First TGEN row is port 1 (`10.0.1.x` /
`2001:db8:1::x`), second is port 2. A third row is silently ignored.

**`local_interface` is not consumed** — it must be non-empty or the row drops, but
only the DUT *hostname* and OTG *interface* are used. Keep it accurate as
documentation.

## DUT configuration, per profile

ASN **65000**; all OTG peers are eBGP **remote-as 65001**, hold 90, keepalive 30,
IPv4 + IPv6 unicast. Configure **every** peer listed below, including any marked
down at start — those are held down at setup rather than absent, and a playbook
brings them up mid-test, so a peer missing from the DUT makes that playbook fail
to converge. Peers *not* marked down must establish at setup or it fails with
"BGP sessions not up within 90s".

**restarts** — interfaces `10.0.1.2/24` + `2001:db8:1::2/64`, and `10.0.2.2/24` +
`2001:db8:2::2/64`. Peers `10.0.1.1`, `2001:db8:1::1`, `10.0.2.1`,
`2001:db8:2::1`.

**ecmp** — interfaces `2001:db8:1::2/64`, `2001:db8:1:ec1::2/64`,
`2001:db8:1:ec2::2/64`, `2001:db8:2::2/64`. Peers `2001:db8:1:ec1::10` and
`2001:db8:1:ec2::10` (**down** at start). The measured groups need addresses only,
no peering.

**malformed** — interfaces `10.0.1.2/24`, `10.0.2.2/24`. Peers `10.0.1.1` and
`10.0.1.10` (**down** at start).

ECMP devices start at `ECMP_DEVICE_HOST_OFFSET` (`::10`) so they clear the gateway
at `::2`; with `multiplier > 1` the DUT must accept a peer per device, `::10`
through `::10 + multiplier - 1`.

## Prefixes advertised

Do not filter `2001:db8::/32` or `100.0.0.0/8`.

| Source | Prefixes |
|---|---|
| measured port 1 | `100.1.0.0/24` ×100 step `0.0.1.0`; `2001:db8:1100::/64` ×100 |
| measured port 2 | `100.2.0.0/24` ×100; `2001:db8:1200::/64` ×100 |
| `ECMP_1` + `ECMP_2` | the **same** aggregate `2001:db8:ec00::/64` ×500 — the overlap is what creates ECMP members |
| malformed peer | nothing declaratively; 6 replayed raw UPDATEs over `198.51.100.0/24`, `/25`, `.128/25`, `.64/26`, `.192/26` |

## Device-info CSV

`hostname,ipv6,ipv4,mac,role,os`. The **MAC is mandatory** —
`HIGH_QUEUE_BGP_CP_TRAFFIC` targets the DUT's own MAC so the frames are punted to
its CPU; a missing MAC raises at config-build time. See
`examples/topology/otg_hardening_device_info.csv`.

## CPU queue provisioning

### What the test requires

Only that **the flood reaches the high-priority CPU queue**. On FBOSS it already
does: BGP arrives via rx-reasons 11 and 12, mapped there in
`rxReasonToQueueOrderedList`. A CoPP ACL matching `l4DstPort: 179` + `dscp: 48` is
needed only if your platform sets `NO_RX_REASON_TRAP`.

The test reads **no** policer, queue-drop or ACL counter. It asserts that BGP
sessions do not flap across the flood, recovered afterwards, and no core dumps —
i.e. *"BGP survived a CP flood and nothing crashed."*

### Do not rate-limit the high-priority queue

A `portQueueRate` limit on the queue carrying BGP is counterproductive: the
policer cannot tell flood packets from keepalives — both are TCP/179 at DSCP 48
from the OTG port's own address. Under a saturating flood a keepalive's survival
odds are roughly `policer_pps / flood_pps`, and with keepalive 30 / hold 90 there
are only ~3 chances per hold interval. Sessions flap and the primary assertion
fails, while nothing in the test rewards the policer.

### Recommended: WRR weights, no rate on the high queue

What upstream's `addCpuQueueConfig()` produces for Broadcom SAI, so it is the
configuration upstream's equivalent test passes against. Set all CPU queues to
`scheduling: 0` (`WEIGHTED_ROUND_ROBIN`) with weights high 4, mid 2, default 1,
low 1 (`kCoppHighPriWeight`, `kCoppMidPriWeight`, and 1/1 from
`CoppTestUtils.h`). Nothing is policer-dropped; the scheduler keeps the lower
queues draining while the high queue is saturated.

Both changes are required — `setWeight()` returns early under `STRICT_PRIORITY`,
so weights without the scheduling flip are inert. And if your queues are currently
`STRICT_PRIORITY`, that already diverges from `getCpuDefaultQueueScheduling()`,
which returns `WEIGHTED_ROUND_ROBIN` for every non-Chenab ASIC — so this is a
correctness fix independent of this test.

### Flood rate

`CP_FLOW_PPS = 10000`, absolute **frames per second**. What is overloaded is the
CPU punt path, not the link: CoPP limits sit in the 10²–10³ pps range, so
thousands of pps suffice.

A percentage would not be backend-portable. Upstream's `line_rate=70` is ~10⁸ pps
of small frames on a 400G port — so far past any CoPP limit that no queue config
keeps BGP alive, making the no-flap assertion unmeetable; on a software engine the
same 70% is unachievable and resolves to whatever the container CPU allows. An
absolute pps gives identical stimulus on ixia-c and hardware. Raise it if your
CoPP limits exceed ~1000 pps.

### Address family

The flood is **IPv4** where upstream's `BGP_CP_TRAFFIC_PACKET_HEADERS` is IPv6 — a
deliberate divergence. The DUT punts TCP/179 by rx-reason regardless of family,
the test asserts session survival rather than anything AF-specific, and v4+TCP is
the lower-risk composition on a software engine. IPv6 flow support is required
regardless, since the measured set includes one; what IPv4 avoids is depending on
TCP-over-IPv6 specifically.

## OTG side

Two ports on a conformant OTG endpoint over HTTPS, plus `pip install snappi`.

**Traffic generation is undemanding** — 10 kpps for the flood, 1000 pps per
measured flow. IPv6 data-plane support is required.

**BGP emulation is the real ixia-c risk.** `test_bgp_malformed_packet_test` needs
`peer.replay_updates.raw_bytes`, which is protocol emulation rather than traffic
generation, and community builds have documented limits. If unsupported, that one
playbook fails at setup while the other seven are unaffected. (Verified working on
ixia-c as of the last run.)

## Validating without a DUT

```bash
./docker/run_taac_docker.sh --regen run env TAAC_OSS=1 \
    python3 -m taac.runner.oss_entry_point \
    --test-configs /workspace/taac/otg/otg_hardening_restarts_test_config.py \
    --dut device \
    --device-info-csv /workspace/examples/topology/otg_hardening_device_info.csv \
    --circuit-info-csv /workspace/examples/topology/otg_hardening_circuit_info.csv \
    --dry-run
```

`--regen` is needed while the `BgpUpdateSequence` thrift addition is local (see
Known gaps).

## Known gaps

None stops a run; each changes how to read a green result.

### A disabled peer establishes briefly before being held down

`DeviceGroupConfig.enable` **is** honoured. A group marked `enable=False` is built
in full — addresses, peer, route ranges — and its peers are then driven DOWN and
exempted from the setup-time all-sessions-up gate, so a playbook's
`toggle_device_groups(enable=True)` drives a genuine transition.

The residue: OTG has no device-level disable and protocol start is all-or-nothing,
so a disabled peer can establish for a moment between `start_protocols` and the
hold-down before going back down. The DUT therefore sees one short up/down flap
per disabled group at setup, before any snapshot window opens. If your DUT logs
session churn, expect one entry per disabled peer.

### The malformed peer resets once per replay cycle, by design

The replayed suite ends with the one malformation the DUT is expected to answer
with a NOTIFICATION (an unlocalisable attribute-length error, RFC 7606 section 3).
OTG re-sends the whole sequence on every re-establishment, so the peer settles
into a cycle: five survivable UPDATEs, then a reset, then re-establish and repeat.

That is deliberate, and the ordering is load-bearing — anything placed after the
resetting entry would never be sent on any cycle, because the session is gone
before it is reached. If you add a malformation, put it before that entry unless
you intend it to end the session.

Expect steady session churn on `10.0.1.10` in DUT logs for the duration of this
playbook. The measured peer on the same interface must stay up throughout; that is
the assertion.

### The ECMP profile cannot overload on community edition

`multiplier` **is** implemented — a group expands into that many simulated
devices, each with its own address, MAC, router ID and peer, each contributing one
next-hop per prefix. But every device is an interface *and* a session, so the cap
of 4 binds:

| `ECMP_1` × `ECMP_2` | interfaces | next-hops | members (500 prefixes) | |
|---|---|---|---|---|
| 1 × 1 | 4 | 2 | 1000 | fits |
| 1 × 2 | 5 | 3 | 1500 | over |
| 8 × 24 | 34 | 32 | 16000 | over — the values that actually overload |

So the profile pins `ecmp_multipliers=(1, 1)`: `ECMP_2` coming up adds **one**
next-hop, 1 → 2 paths. That exercises path selection via `ECMP_FORWARDING_V6` but
approaches no platform limit, so both ECMP playbooks pass without stressing the
tables. `LICENSED_ECMP_MULTIPLIERS = (8, 24)` is there for a licensed deployment.

### `BgpUpdateSequence` is not sync-durable

`test_bgp_malformed_packet_test` needs `ixia.BgpUpdateSequence`, added locally to
`taac/thrift/ixia/ixia.thrift` and `taac/thrift/taac/test_as_a_config.thrift`.
Both are `@generated` mechanical copies of configerator sources, so **a sync
removes the struct** and the test fails with `AttributeError: module
'ixia.ixia.types' has no attribute 'BgpUpdateSequence'`.

Local edits here are established practice — commit `2b107c1` added
`port_location` the same way — but that commit also updated the `@generated
SignedSource<<...>>` hash and this change does not; the hash cannot be recomputed
outside Meta's internal tooling. The durable fix is landing the struct in
configerator and letting `configerator-thrift-updater` bring it down. Only this
playbook is affected.
