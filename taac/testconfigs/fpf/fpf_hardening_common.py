# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""Shared constants and device lists for FPF hardening test configs.

All FPF hardening test configs (TC2-TC33) import from this module to keep
device hostnames, prefix counts, and timing parameters in one place.
"""

import os
import re
import typing as t
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


def skip_ib_traffic() -> bool:
    """Whether to omit only ib_write_bw traffic while retaining SSH checks."""
    return os.environ.get("TAAC_FPF_SKIP_IB_TRAFFIC", "").lower() in (
        "1",
        "true",
        "yes",
    )


DEFAULT_IB_DEVICE: str = "mlx5_34"
DEFAULT_IB_BINARY: str = "/usr/bin/ib_write_bw"
DEFAULT_IB_GID_IFACE: str = "bveth0"
DEFAULT_IB_GID_PREFIX: str = "2401"
DEFAULT_IB_PORT: int = 15000
DEFAULT_IB_MSG_SIZE: int = 4096
DEFAULT_IB_QP: int = 4
DEFAULT_IB_TCLASS: int = 224
DEFAULT_IB_ITERS: int = 1000
DEFAULT_IB_MIN_EGRESS_GBPS: float = 10.0
DEFAULT_IB_SETTLE_SEC: int = 120
DEFAULT_IB_ODS_WINDOW_SEC: int = 120
DEFAULT_LINK_DRAIN_INTERFACE: str = "eth1/45/5"
DEFAULT_GPU_HOSTS: list[str] = ["rtptest1555.mwg2", "rtptest1599.mwg2"]
_KNOWN_LINK_DRAIN_INTERFACES: dict[str, str] = {
    "twshared1352.03.mwg2": "eth1/41/5",
}


class FpfIbTrafficConfig(t.TypedDict):
    server: str
    clients: list[str]
    binary_path: str
    device: str
    gid_iface: str
    gid_prefix: str
    port: int
    msg_size: int
    qp: int
    tclass: int
    iters: int
    min_egress_gbps: float
    settle_sec: int
    ods_window_sec: int


def fpf_ib_device() -> str:
    """Return the shared-suite RDMA device, preserving the legacy default.

    Set TAAC_FPF_IB_DEVICE for hosts whose live RDMA device naming differs,
    such as mlx5_bveth0 on the MWG2 twshared test hosts.
    """
    return (
        os.environ.get("TAAC_FPF_IB_DEVICE", DEFAULT_IB_DEVICE).strip()
        or DEFAULT_IB_DEVICE
    )


def fpf_ib_binary() -> str:
    """Return the absolute ib_write_bw path for setup and recovery.

    The default production path is preserved. Testbeds with host-provisioning
    drift may point at a verified, temporarily staged binary, but relative or
    whitespace-containing paths are rejected before config generation so the
    command cannot be interpreted differently by the remote shell.
    """
    binary_path = (
        os.environ.get("TAAC_FPF_IB_BINARY", DEFAULT_IB_BINARY).strip()
        or DEFAULT_IB_BINARY
    )
    if not os.path.isabs(binary_path):
        raise ValueError(
            f"TAAC_FPF_IB_BINARY must be an absolute path; got {binary_path!r}"
        )
    if re.search(r"\s", binary_path):
        raise ValueError(
            f"TAAC_FPF_IB_BINARY must not contain whitespace; got {binary_path!r}"
        )
    return binary_path


def fpf_link_drain_interface(
    gpu_hosts: list[str] | None = None,
) -> str:
    """Return the GTSW interface used by shared-suite link-drain tests.

    The legacy RTP topology keeps its historical ``eth1/45/5`` default. A
    non-default GPU host pair must explicitly supply
    ``TAAC_FPF_LINK_DRAIN_INTERFACE`` so a copied config cannot silently drain
    the previous host's circuit. MWG2 twshared1352 uses ``eth1/41/5`` on
    ``gtsw001.l1002.c087.mwg2`` for device 0 / local plane 0 / beth0.
    """
    hosts = list(GPU_HOSTS if gpu_hosts is None else gpu_hosts)
    configured = os.environ.get("TAAC_FPF_LINK_DRAIN_INTERFACE", "").strip()
    if not configured:
        if hosts != DEFAULT_GPU_HOSTS:
            raise ValueError(
                "TAAC_FPF_LINK_DRAIN_INTERFACE is required when FPF_GPU_HOSTS "
                f"differs from the legacy RTP hosts {DEFAULT_GPU_HOSTS}; got {hosts}"
            )
        return DEFAULT_LINK_DRAIN_INTERFACE
    if re.fullmatch(r"eth\d+/\d+/\d+", configured) is None:
        raise ValueError(
            "TAAC_FPF_LINK_DRAIN_INTERFACE must be an exact FBOSS interface "
            f"name such as eth1/41/5; got {configured!r}"
        )
    server = hosts[0].removesuffix(".facebook.com") if hosts else ""
    known = _KNOWN_LINK_DRAIN_INTERFACES.get(server)
    if known is not None and configured != known:
        raise ValueError(
            f"TAAC_FPF_LINK_DRAIN_INTERFACE={configured!r} does not match the "
            f"validated {server} device0/local-plane0 circuit {known!r}"
        )
    return configured


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
#
# Optional Pod Mosaic overrides are intentionally runtime-only so the default
# suite remains unchanged. With 16 pods x 252 prefixes/pod, each VF group gets
# 4032 prefixes and every pod bucket carries a distinct origin ASN.
VF_GROUP_PODS = int(os.environ.get("FPF_VF_GROUP_PODS", "0"))
VF_PREFIXES_PER_POD = int(os.environ.get("FPF_VF_PREFIXES_PER_POD", "0"))
VF_BASE_ASN_PATH = int(os.environ.get("FPF_VF_BASE_ASN_PATH", "4203699001"))
VF_INCREMENT_ASN_PER_POD = int(os.environ.get("FPF_VF_INCREMENT_ASN_PER_POD", "1"))
if bool(VF_GROUP_PODS) != bool(VF_PREFIXES_PER_POD):
    raise ValueError(
        "FPF_VF_GROUP_PODS and FPF_VF_PREFIXES_PER_POD must be set together"
    )
if VF_GROUP_PODS < 0 or VF_PREFIXES_PER_POD < 0:
    raise ValueError("FPF Pod Mosaic counts must be non-negative")
VF_GROUP_PREFIX_COUNT = (
    VF_GROUP_PODS * VF_PREFIXES_PER_POD
    if VF_GROUP_PODS
    else int(os.environ.get("FPF_VF_GROUP_PREFIX_COUNT", "1000"))
)

# All 8 lanes/planes carry injected prefixes once both VF groups are advertised
# across all 8 STSW planes (lane N <-> gtsw00{N+1} <-> stsw plane N).
ALL_LANES = [0, 1, 2, 3, 4, 5, 6, 7]


def fpf_hrt_lanes() -> list[int]:
    """Return the HRT plane IDs exposed by the selected GPU hosts.

    Production RTP hosts use the default eight-plane layout. Some twshared
    hosts expose eight GPU devices with four HRT planes per device instead, so
    local validation can scope HRT collectors and checks with FPF_HRT_LANES
    without changing the advertised STSW prefix scale.
    """
    configured = os.environ.get("FPF_HRT_LANES", "").strip()
    if not configured:
        return list(ALL_LANES)

    lanes = [int(value.strip()) for value in configured.split(",")]
    if not lanes or len(lanes) != len(set(lanes)):
        raise ValueError("FPF_HRT_LANES must contain unique comma-separated lanes")
    invalid = sorted(set(lanes) - set(ALL_LANES))
    if invalid:
        raise ValueError(f"FPF_HRT_LANES contains invalid lanes: {invalid}")
    return sorted(lanes)


def _parse_hrt_device_ids(env_name: str, default: list[int]) -> list[int]:
    configured = os.environ.get(env_name, "").strip()
    if not configured:
        return list(default)

    device_ids = [int(value.strip()) for value in configured.split(",")]
    if not device_ids or len(device_ids) != len(set(device_ids)):
        raise ValueError(f"{env_name} must contain unique comma-separated IDs")
    if any(device_id < 0 for device_id in device_ids):
        raise ValueError(f"{env_name} device IDs must be non-negative")
    return sorted(device_ids)


def fpf_hrt_device_ids() -> list[int]:
    """Return HRT device IDs to collect; RTP remains dev0 by default."""
    return _parse_hrt_device_ids("FPF_HRT_DEVICE_IDS", [0])


def fpf_hrt_vf_device_ids(hrt_device_ids: list[int]) -> tuple[list[int], list[int]]:
    """Return explicit VF1/VF2 device sets for the selected HRT topology.

    The legacy RTP layout exposes both VF halves as planes 0-7 on dev0, so its
    compatible default is dev0 for both groups. Multi-device layouts must state
    the mapping explicitly; parity is a verified twshared convention, not a
    universal HRT topology assumption.
    """
    vf1_configured = os.environ.get("FPF_HRT_VF1_DEVICE_IDS", "").strip()
    vf2_configured = os.environ.get("FPF_HRT_VF2_DEVICE_IDS", "").strip()
    if not vf1_configured and not vf2_configured:
        if hrt_device_ids == [0]:
            return [0], [0]
        raise ValueError(
            "Multi-device FPF_HRT_DEVICE_IDS requires explicit "
            "FPF_HRT_VF1_DEVICE_IDS and FPF_HRT_VF2_DEVICE_IDS"
        )
    if not vf1_configured or not vf2_configured:
        raise ValueError(
            "FPF_HRT_VF1_DEVICE_IDS and FPF_HRT_VF2_DEVICE_IDS must be set together"
        )

    vf1 = _parse_hrt_device_ids("FPF_HRT_VF1_DEVICE_IDS", [])
    vf2 = _parse_hrt_device_ids("FPF_HRT_VF2_DEVICE_IDS", [])
    configured = set(hrt_device_ids)
    outside = sorted((set(vf1) | set(vf2)) - configured)
    if outside:
        raise ValueError(f"VF device mapping includes uncollected IDs: {outside}")
    overlap = sorted(set(vf1) & set(vf2))
    if overlap:
        raise ValueError(f"VF1/VF2 device mappings overlap: {overlap}")
    if set(vf1) | set(vf2) != configured:
        missing = sorted(configured - (set(vf1) | set(vf2)))
        raise ValueError(f"HRT device IDs missing from VF mappings: {missing}")
    return vf1, vf2


def hrt_device_plane_to_beth(device_id: int, local_plane: int) -> int:
    """Map the twshared device/local-plane identity to the physical beth index."""
    if device_id < 0:
        raise ValueError("HRT device_id must be non-negative")
    if local_plane not in range(4):
        raise ValueError("twshared local_plane must be in range 0..3")
    gpu = device_id // 2
    vf_half = device_id % 2
    global_lane = 4 * vf_half + local_plane
    return 8 * gpu + global_lane


def fpf_rf_vf_groups(
    active_lanes: list[int] | None = None,
    device_ids_by_vf: tuple[list[int], list[int]] | None = None,
) -> list[dict]:
    """Per-VF-group remote-failure monitoring spec for the 8-STSW injection.

    RTP's compatible default reads both VF halves from dev0 planes 0-7. Alternate
    layouts can map each VF to explicit device IDs while using local planes 0-3.
    Each group is healthy only when its own mapped device/plane tuples have zero
    remote failures; a cross-plane count on another device is never a baseline.
    """
    lanes = list(ALL_LANES if active_lanes is None else active_lanes)
    if device_ids_by_vf is None:
        return [
            {
                "suffix": "vf1",
                "subnet": "5000:dd::/32",
                "lanes": [lane for lane in lanes if lane < 4],
            },
            {
                "suffix": "vf2",
                "subnet": "5000:ee::/32",
                "lanes": [lane for lane in lanes if lane >= 4],
            },
        ]

    vf1_devices, vf2_devices = device_ids_by_vf
    return [
        {
            "suffix": "vf1",
            "subnet": "5000:dd::/32",
            "lanes": lanes,
            "device_ids": vf1_devices,
        },
        {
            "suffix": "vf2",
            "subnet": "5000:ee::/32",
            "lanes": lanes,
            "device_ids": vf2_devices,
        },
    ]


def fpf_vf_injection_groups(count: int = VF_GROUP_PREFIX_COUNT) -> list[dict]:
    """Injection-group spec for the 8-STSW split-per-VF injection setup task.

    Returns one entry per VF group: which STSWs to inject on, the group's prefix
    base, the per-STSW prefix count, and the community preset. Consumed by
    ``create_fpf_inject_vf_groups_task`` / ``create_fpf_withdraw_vf_groups_task``.
    """
    groups = [
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
    if VF_GROUP_PODS:
        expected_count = VF_GROUP_PODS * VF_PREFIXES_PER_POD
        if count != expected_count:
            raise ValueError(
                f"Pod Mosaic count must be pods x prefixes_per_pod "
                f"({VF_GROUP_PODS} x {VF_PREFIXES_PER_POD} = {expected_count}), "
                f"got {count}"
            )
        for group in groups:
            group.update(
                {
                    "pods": VF_GROUP_PODS,
                    "prefixes_per_pod": VF_PREFIXES_PER_POD,
                    "base_asn_path": VF_BASE_ASN_PATH,
                    "increment_asn_per_pod": VF_INCREMENT_ASN_PER_POD,
                    "batch_size": VF_PREFIXES_PER_POD,
                }
            )
    return groups


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


def fpf_device_drain_gtsw() -> str:
    """Return the TC19 whole-device drain target.

    The legacy target remains gtsw001. Alternate testbeds can select another
    local-pod GTSW explicitly, but a typo or remote-pod target is rejected
    before config generation. MWG2 twshared testing uses gtsw002 so an ambient
    drain on gtsw001 is never cleared or otherwise mutated by TC19.
    """
    target = os.environ.get("TAAC_FPF_DEVICE_DRAIN_GTSW", "").strip()
    if not target:
        return ALL_GTSWS[0]
    if target not in ALL_GTSWS:
        raise ValueError(
            "TAAC_FPF_DEVICE_DRAIN_GTSW must be one of the local-pod "
            f"FPF GTSWs {ALL_GTSWS}; got {target!r}"
        )
    return target


GPU_HOSTS = [
    host.strip()
    for host in os.environ.get("FPF_GPU_HOSTS", ",".join(DEFAULT_GPU_HOSTS)).split(",")
    if host.strip()
]
if len(GPU_HOSTS) < 2:
    raise ValueError("FPF_GPU_HOSTS must contain at least two comma-separated hosts")
if len(set(GPU_HOSTS)) != len(GPU_HOSTS):
    raise ValueError("FPF_GPU_HOSTS must contain distinct hosts")

# ib_write_bw traffic endpoints (server <-> clients). The server runs the
# ib_write_bw server side; each client connects to it. SPRAY_HOSTS is the set of
# hosts whose per-lane RDMA egress the host-spray check validates (server +
# clients, since traffic flows on both ends).
IB_TRAFFIC_SERVER = GPU_HOSTS[0]
IB_TRAFFIC_CLIENTS = [GPU_HOSTS[1]]
SPRAY_HOSTS = [IB_TRAFFIC_SERVER, *IB_TRAFFIC_CLIENTS]

# RTP hosts whose HRT service system-memory is monitored (ODS-based check).
HRT_MEMORY_HOSTS = list(GPU_HOSTS)


def fpf_ib_traffic_config(*, ib_device: str | None = None) -> FpfIbTrafficConfig:
    """Build the single setup/recovery traffic contract for an FPF config.

    Callers pass this same mapping to the setup task and every playbook traffic
    readiness step. This prevents recovery from silently falling back to a
    different RDMA device or argument set than the initially validated flow.
    """
    return {
        "server": IB_TRAFFIC_SERVER,
        "clients": list(IB_TRAFFIC_CLIENTS),
        "binary_path": fpf_ib_binary(),
        "device": ib_device if ib_device is not None else fpf_ib_device(),
        "gid_iface": DEFAULT_IB_GID_IFACE,
        "gid_prefix": DEFAULT_IB_GID_PREFIX,
        "port": DEFAULT_IB_PORT,
        "msg_size": DEFAULT_IB_MSG_SIZE,
        "qp": DEFAULT_IB_QP,
        "tclass": DEFAULT_IB_TCLASS,
        "iters": DEFAULT_IB_ITERS,
        "min_egress_gbps": DEFAULT_IB_MIN_EGRESS_GBPS,
        "settle_sec": DEFAULT_IB_SETTLE_SEC,
        "ods_window_sec": DEFAULT_IB_ODS_WINDOW_SEC,
    }


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


def fpf_ib_traffic_tasks(
    skip_ssh: bool,
    skip_ib: bool = False,
    ib_device: str = DEFAULT_IB_DEVICE,
    traffic_config: FpfIbTrafficConfig | None = None,
):
    """Return (setup_tasks, teardown_tasks) for ib_write_bw traffic.

    Empty when SSH dependencies or traffic are explicitly disabled. The
    separate ``skip_ib`` input lets the shared suite retain SSH health checks
    while omitting only ib_write_bw. Imported lazily to avoid an import cycle
    with task_definitions.
    """
    if skip_ssh or skip_ib:
        return [], []
    from taac.task_definitions import (
        create_fpf_start_ib_traffic_task,
        create_fpf_stop_ib_traffic_task,
    )

    if traffic_config is None:
        # Preserve byte-identical legacy serialization for callers that have not
        # opted into the canonical setup/recovery mapping.
        config = fpf_ib_traffic_config(ib_device=ib_device)
        setup = [
            create_fpf_start_ib_traffic_task(
                server=config["server"],
                clients=config["clients"],
                device=config["device"],
            )
        ]
    else:
        config = traffic_config
        setup = [
            create_fpf_start_ib_traffic_task(
                server=config["server"],
                clients=config["clients"],
                binary_path=config["binary_path"],
                device=config["device"],
                gid_iface=config["gid_iface"],
                gid_prefix=config["gid_prefix"],
                port=config["port"],
                msg_size=config["msg_size"],
                qp=config["qp"],
                tclass=config["tclass"],
                iters=config["iters"],
                min_egress_gbps=config["min_egress_gbps"],
                settle_sec=config["settle_sec"],
                ods_window_sec=config["ods_window_sec"],
            )
        ]
    teardown = [
        create_fpf_stop_ib_traffic_task(
            server=config["server"], clients=config["clients"]
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
