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

OBSERVER_GTSWS = [
    "gtsw001.l1002.c087.mwg2",
    "gtsw002.l1002.c087.mwg2",
]

GPU_HOSTS = [
    "rtptest1555.mwg2",
    "rtptest1575.mwg2",
]

# ib_write_bw traffic endpoints (server <-> clients). The server runs the
# ib_write_bw server side; each client connects to it. SPRAY_HOSTS is the set of
# hosts whose per-lane RDMA egress the host-spray check validates (server +
# clients, since traffic flows on both ends).
IB_TRAFFIC_SERVER = GPU_HOSTS[0]
IB_TRAFFIC_CLIENTS = [GPU_HOSTS[1]]
SPRAY_HOSTS = [IB_TRAFFIC_SERVER, *IB_TRAFFIC_CLIENTS]

# RTP hosts whose HRT service system-memory is monitored (ODS-based check).
HRT_MEMORY_HOSTS = ["rtptest1555.mwg2", "rtptest1575.mwg2"]


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


# FSDB ribMap collector read path. "ribmap" -> bgp/ribMap (valid on the current
# GTSWs); "canonical" -> bgp/canonicalRib (newer FSDB schema, returns
# INVALID_PATH on GTSWs that don't expose it yet). Overridable per test config.
FSDB_COLLECTOR_MODE = "ribmap"

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


def create_fpf_endpoints() -> list[Endpoint]:
    return [
        Endpoint(name=OBSERVER_GTSWS[0], dut=True),
        Endpoint(name=OBSERVER_GTSWS[1]),
        *[Endpoint(name=stsw) for stsw in TRIGGER_STSWS],
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
