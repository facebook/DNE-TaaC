# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""Shared constants and device lists for FPF hardening test configs.

All FPF hardening test configs (TC2-TC33) import from this module to keep
device hostnames, prefix counts, and timing parameters in one place.
"""

import os
import re
from dataclasses import dataclass

from taac.test_as_a_config.types import Endpoint


def skip_ssh_dependencies() -> bool:
    """Whether to drop ALL SSH-dependent pieces (tasks AND checks) from a config.

    SSH-dependent pieces (e.g. the ib_write_bw traffic setup task, which SSHes to
    the RTP hosts, and the generic device-shell health checks) require the
    caller's Kerberos/SSH cert. That cert is present in an engineer's terminal
    but NOT in headless/agent sessions, where SSH to lab devices fails with
    "Permission denied (publickey)". Thrift/ODS paths (collectors, the FPF
    convergence/stability/spray/session checks) use service auth and work in
    both. Set TAAC_FPF_SKIP_SSH_DEPS=1 to omit the SSH-dependent task+check set
    so the rest of the config can run end-to-end without an SSH cert.

    Note: with SSH dependencies skipped there is no ib_write_bw traffic, so the
    host-spray check (which needs that traffic) is also dropped by the configs.
    """
    return os.environ.get("TAAC_FPF_SKIP_SSH_DEPS", "").lower() in ("1", "true", "yes")


TRIGGER_STSWS = [
    "stsw001.s001.l202.mwg2",
    "stsw001.s002.l202.mwg2",
]

# ---------------------------------------------------------------------------
# 8-STSW VF-group injection (split per VF / VIP group)
# ---------------------------------------------------------------------------
#
# The inject-then-disrupt FPF configs now advertise the stress prefixes across
# ALL EIGHT STSW planes instead of just the first two, split into the two VF
# (VIP) groups so each group lands on its own set of planes:
#   - VF1 (planes 0-3, served by GTSW1-4): prefix base 5000:dd::/64 on s001-s004
#   - VF2 (planes 4-7, served by GTSW5-8): prefix base 5000:ee::/64 on s005-s008
# Injection is performed by the FpfInjectBgpPrefixesTask SETUP TASK (so a
# netcastle run is fully self-contained — no external inject script), and
# withdrawn by the same task in teardown. The playbooks for these configs pass
# skip_injection=True so the netcastle run injects exactly once, from setup.
VF1_STSWS = [
    "stsw001.s001.l202.mwg2",
    "stsw001.s002.l202.mwg2",
    "stsw001.s003.l202.mwg2",
    "stsw001.s004.l202.mwg2",
]
VF2_STSWS = [
    "stsw001.s005.l202.mwg2",
    "stsw001.s006.l202.mwg2",
    "stsw001.s007.l202.mwg2",
    "stsw001.s008.l202.mwg2",
]
ALL_STSWS = [*VF1_STSWS, *VF2_STSWS]

VF1_PREFIX_BASE = "5000:dd::/64"
VF2_PREFIX_BASE = "5000:ee::/64"

# Collector subnet filter MUST cover BOTH VF group bases (5000:dd and 5000:ee).
# The FPF collectors (FSDB ribMap, BGP RIB, HRT bulk, HRT remote-failure) filter
# prefixes by a single subnet-containment test, so a /32 on 5000:dd would miss
# the VF2 (5000:ee) group entirely. 5000::/16 covers both.
VF_COLLECTOR_SUBNET = "5000::/16"

# Per-group prefix count injected on EACH STSW in the group. Each STSW in a
# group advertises the SAME prefix set (ECMP across the group's planes).
VF_GROUP_PREFIX_COUNT = 1000

# All 8 lanes/planes carry injected prefixes once both VF groups are advertised
# across all 8 STSW planes (lane N <-> gtsw00{N+1} <-> stsw plane N).
ALL_LANES = [0, 1, 2, 3, 4, 5, 6, 7]


def fpf_rf_vf_groups() -> list[dict]:
    """Per-VF-group remote-failure monitoring spec for the 8-STSW injection.

    Because the fabric is VF-segregated (VF1 reachable only on lanes 0-3, VF2 only
    on lanes 4-7), each group's prefixes appear as (expected) remote-failures on
    the OTHER group's planes. To assert each group has ZERO remote-failure on its
    OWN lanes, a per-group collector with the group's NARROW subnet is started
    (registered "hrt_remote_failure_<suffix>"), and the per-group remote-failure
    check is scoped to the group's lanes. Consumed by both
    ``create_fpf_start_collectors_task(rf_vf_groups=...)`` and the playbook
    factories' ``rf_vf_groups=`` argument.
    """
    return [
        {"suffix": "vf1", "subnet": "5000:dd::/32", "lanes": [0, 1, 2, 3]},
        {"suffix": "vf2", "subnet": "5000:ee::/32", "lanes": [4, 5, 6, 7]},
    ]


def fpf_vf_injection_groups(count: int = VF_GROUP_PREFIX_COUNT) -> list[dict]:
    """Injection-group spec for the 8-STSW split-per-VF injection setup task.

    Returns one entry per VF group: which STSWs to inject on, the group's prefix
    base, the per-STSW prefix count, and the community preset. Consumed by
    ``create_fpf_inject_vf_groups_task`` / ``create_fpf_withdraw_vf_groups_task``.
    """
    return [
        {
            "devices": VF1_STSWS,
            "prefix_base": VF1_PREFIX_BASE,
            "count": count,
            "community_list": "stsw",
        },
        {
            "devices": VF2_STSWS,
            "prefix_base": VF2_PREFIX_BASE,
            "count": count,
            "community_list": "stsw",
        },
    ]


OBSERVER_GTSWS = [
    "gtsw001.l1002.c087.mwg2",  # DUT (l1002) — disruptions target this
    "gtsw001.l1001.c087.mwg2",  # observer — remote-pod (l1001) counterpart of the DUT
]

# All 8 GTSWs in the l1002.c087.mwg2 pod a GPU host connects to (one lane each,
# gtsw001->lane0 ... gtsw008->lane7). Used by the multi-GTSW rapid-flap configs
# (flap every GTSW facing a chosen GPU host in parallel) and the dual-device
# drain configs. The flap/drain custom steps build each GTSW's driver directly
# (async_get_device_driver), so these do NOT all need to be in endpoints.
ALL_GTSWS = [f"gtsw00{i}.l1002.c087.mwg2" for i in range(1, 9)]

GPU_HOSTS = [
    "rtptest1555.mwg2",
    "rtptest1599.mwg2",
]

# ib_write_bw traffic endpoints (server <-> clients). The server runs the
# ib_write_bw server side; each client connects to it. SPRAY_HOSTS is the set of
# hosts whose per-lane RDMA egress the host-spray check validates (server +
# clients, since traffic flows on both ends).
IB_TRAFFIC_SERVER = GPU_HOSTS[0]
IB_TRAFFIC_CLIENTS = [GPU_HOSTS[1]]
SPRAY_HOSTS = [IB_TRAFFIC_SERVER, *IB_TRAFFIC_CLIENTS]

# RTP hosts whose HRT service system-memory is monitored (ODS-based check).
HRT_MEMORY_HOSTS = ["rtptest1555.mwg2", "rtptest1599.mwg2"]


def fpf_clean_slate_setup_task():
    """Return the clean-slate setup task: withdraw leftover 5000:dd test prefixes.

    Place this FIRST in a config's ``setup_tasks`` (before the collectors task
    and before the playbooks' injection steps) so injection always starts from a
    clean ``5000:dd`` baseline — even if the PREVIOUS run was killed mid-flight
    and never ran its teardown withdraw. Idempotent (no-op when nothing is
    present). Imported lazily to avoid an import cycle with task_definitions.
    """
    from taac.task_definitions import (
        create_fpf_withdraw_stale_prefixes_task,
    )

    return create_fpf_withdraw_stale_prefixes_task(trigger_stsws=TRIGGER_STSWS)


def fpf_ib_traffic_tasks(skip_ssh: bool):
    """Return (setup_tasks, teardown_tasks) for ib_write_bw traffic.

    Empty when skip_ssh (ib_write_bw SSHes to the RTP hosts and needs the
    caller's Kerberos/SSH cert). Imported lazily to avoid an import cycle with
    task_definitions.
    """
    if skip_ssh:
        return [], []
    from taac.task_definitions import (
        create_fpf_start_ib_traffic_task,
        create_fpf_stop_ib_traffic_task,
    )

    setup = [
        create_fpf_start_ib_traffic_task(
            server=IB_TRAFFIC_SERVER, clients=IB_TRAFFIC_CLIENTS
        )
    ]
    teardown = [
        create_fpf_stop_ib_traffic_task(
            server=IB_TRAFFIC_SERVER, clients=IB_TRAFFIC_CLIENTS
        )
    ]
    return setup, teardown


# FSDB ribMap collector read path. "canonical" -> bgp/canonicalRib (the path the
# GTSWs publish the RIB under now that canonical RIB is enabled on the fabric);
# "ribmap" -> bgp/ribMap (legacy schema, now empty -> collectors read 0).
# Overridable per test config.
FSDB_COLLECTOR_MODE = "canonical"

# When True, health checks classify failures on lanes already impaired at
# precheck (e.g. a degraded lab GTSW/plane) as PRE-EXISTING (baseline) rather
# than NEW regressions, and let the test pass on baseline state alone. This is
# an explicit per-test-config opt-in so a known-degraded testbed doesn't mask a
# real link-event regression by default. The collector records the baseline
# impaired-lane set at start; the link-event checks fold/exclude those lanes.
ALLOW_BASELINE_FAILURES = True

HARDENING_PREFIX_COUNT = 70000
DEFAULT_STABILIZATION_SEC = 600
DEFAULT_BASELINE_DELAY_SEC = 120
DEFAULT_RECOVERY_WAIT_SEC = 300
DEFAULT_SUBNET_PREFIX = "5000:dd::/32"
DEFAULT_COMMUNITY_LIST = "stsw"
FPF_SERVICES = ["bgpd", "fsdb", "wedge_agent", "qsfp_service"]
DEFAULT_LANES = [0, 1]
DEFAULT_REMOTE_FAILURE_LANES = [0, 1, 2, 3]
REMOTE_FAILURE_SUBNET = "5000:dd::/32"
DRAIN_CONVERGENCE_SLA_SEC = 120


def create_fpf_endpoints(stsws: list[str] | None = None) -> list[Endpoint]:
    """Build the FPF endpoint list — ONLY the two observer GTSWs.

    Endpoints are the DUT (``OBSERVER_GTSWS[0]`` = gtsw001.l1002) and its
    remote-pod observer (``OBSERVER_GTSWS[1]`` = gtsw001.l1001). STSWs are
    deliberately NOT endpoints, and no other GTSW is monitored: per-device
    health checks fan out over endpoints, and we only monitor these two GTSWs.
    The inject / STSW-bgpd-restart tasks drive STSWs directly by hostname
    (``FbossSwitchInternal``), so they don't need STSW endpoints. ``stsws`` is
    accepted for caller back-compat but no longer contributes endpoints.
    """
    _ = stsws  # back-compat: STSWs are driven by hostname in tasks, not endpoints
    return [
        Endpoint(name=OBSERVER_GTSWS[0], dut=True),
        Endpoint(name=OBSERVER_GTSWS[1]),
    ]


# ---------------------------------------------------------------------------
# Circuit model — single source of truth for link/interface selection
# ---------------------------------------------------------------------------
#
# A Circuit fully describes one GTSW<->GPU link end to end. Link-event test
# configs (interface disable/enable, link drain/undrain) supply a
# ``list[Circuit]`` and every selection/expectation value the playbook and
# health checks need is mechanically derived from it (interfaces to
# disable/drain, unique RTP hosts, impacted lanes per (host, gpu), and the
# count of disrupted circuits N for the overall FSDB-session signal).
#
# TODO(pavanpatil): for now circuits are declared inline in each test config.
# Migrate to a topology source-of-truth constants file once the link-event
# suite stabilizes.

GPUS_PER_BE_NODE = 4
GTSWS_PER_GPU = 8
# Total HRT FSDB sessions on one BE node: every GPU subscribes to all 8 GTSWs.
EXPECTED_FSDB_SESSION_COUNT = GPUS_PER_BE_NODE * GTSWS_PER_GPU  # 32

_GTSW_NUM_RE = re.compile(r"gtsw0*(\d+)")


def gtsw_to_lane(gtsw: str) -> int:
    """Derive the GPU lane/plane id (0-7) from a GTSW hostname.

    Topology convention (see fpf_stress_checks.lanes_to_gtsws): lane N maps to
    gtsw00{N+1}. So gtsw001 -> lane 0, gtsw002 -> lane 1, ... gtsw008 -> lane 7.
    """
    m = _GTSW_NUM_RE.search(gtsw)
    if not m:
        raise ValueError(f"Cannot derive lane from GTSW hostname: {gtsw!r}")
    return int(m.group(1)) - 1


@dataclass(frozen=True)
class Circuit:
    """One GTSW<->GPU link, described end to end.

    Attributes:
        a_end_device: GTSW ("gtsr blue") hostname, e.g. gtsw001.l1002.c087.mwg2.
        a_end_interface: GTSW interface to disable/drain, e.g. "eth1/37/5".
        z_end_device: RTP test host (BE node), e.g. "rtptest1544.mwg2".
        z_end_gpu_id: GPU/device id on the BE node (default 0).
        z_end_interface: NIC-side interface; if omitted it is derived as
            beth[gpu*8 + lane]. The lane itself is derived from a_end_device.
    """

    a_end_device: str
    a_end_interface: str
    z_end_device: str
    z_end_gpu_id: int = 0
    z_end_interface: str = ""

    @property
    def lane(self) -> int:
        return gtsw_to_lane(self.a_end_device)

    @property
    def nic_interface(self) -> str:
        return (
            self.z_end_interface
            or f"beth{self.z_end_gpu_id * GTSWS_PER_GPU + self.lane}"
        )


# ---------------------------------------------------------------------------
# Circuit derivations — everything the playbook / health checks key off of
# ---------------------------------------------------------------------------


def disable_interfaces_by_device(circuits: list[Circuit]) -> dict[str, list[str]]:
    """Map each A-end GTSW -> sorted list of interfaces to shut/unshut.

    The COOP change_port_admin_state patcher is per-DUT, so interfaces are
    grouped by their owning GTSW; one interface-flap step is registered per
    device. Order is deterministic for stable golden manifests.
    """
    by_dev: dict[str, list[str]] = {}
    for c in circuits:
        by_dev.setdefault(c.a_end_device, [])
        if c.a_end_interface not in by_dev[c.a_end_device]:
            by_dev[c.a_end_device].append(c.a_end_interface)
    return {dev: sorted(intfs) for dev, intfs in sorted(by_dev.items())}


def unique_z_hosts(circuits: list[Circuit]) -> list[str]:
    """Sorted, de-duplicated list of RTP test hosts referenced by the circuits."""
    return sorted({c.z_end_device for c in circuits})


def impacted_lanes_by_host(circuits: list[Circuit]) -> dict[str, list[int]]:
    """host -> sorted unique impacted lanes (union across that host's GPUs)."""
    out: dict[str, list[int]] = {}
    for c in circuits:
        out.setdefault(c.z_end_device, [])
        if c.lane not in out[c.z_end_device]:
            out[c.z_end_device].append(c.lane)
    return {host: sorted(lanes) for host, lanes in sorted(out.items())}


def impacted_lanes_by_host_gpu(
    circuits: list[Circuit],
) -> dict[str, dict[int, list[int]]]:
    """host -> gpu_id -> sorted impacted lanes. Drives per-device-0 reconciliation."""
    out: dict[str, dict[int, list[int]]] = {}
    for c in circuits:
        out.setdefault(c.z_end_device, {}).setdefault(c.z_end_gpu_id, [])
        if c.lane not in out[c.z_end_device][c.z_end_gpu_id]:
            out[c.z_end_device][c.z_end_gpu_id].append(c.lane)
    return {
        host: {gpu: sorted(lanes) for gpu, lanes in sorted(gpus.items())}
        for host, gpus in sorted(out.items())
    }


def num_disrupted_circuits(circuits: list[Circuit]) -> int:
    """N — the number of distinct disrupted (host, gpu, lane) links.

    Each disabled GTSW<->GPU interface kills exactly one HRT FSDB session, so
    the overall FSDB-session signal expects EXPECTED_FSDB_SESSION_COUNT - N.
    """
    return len({(c.z_end_device, c.z_end_gpu_id, c.lane) for c in circuits})
