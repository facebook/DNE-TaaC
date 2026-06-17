# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-strict

"""Centralized FPF health-check thresholds.

Single source of truth for the pass/fail thresholds used by the FPF hardening
playbook health checks, so they are NOT hardcoded inside individual test
configs. Two threshold sets are defined:

  * ``EXPECTED``  — the finalized product expectations (what the system should
    ultimately meet).
  * ``TEMPORARY`` — relaxed expectations used while known gaps are being fixed,
    so tests are useful today without being permanently red.

``ACTIVE`` selects which set the playbook actually applies. We currently run on
``TEMPORARY`` (see ``USE_TEMPORARY_THRESHOLDS``); flip the toggle to ``False``
to enforce the finalized ``EXPECTED`` values once the underlying gaps are fixed.

When a threshold is finalized, move its value from ``TEMPORARY`` to match
``EXPECTED`` (or just flip the global toggle once ALL gaps are closed).
"""

from dataclasses import dataclass
from typing import Mapping

_GIB: int = 1024**3


@dataclass(frozen=True)
class FpfThresholds:
    """One coherent set of FPF health-check thresholds."""

    # --- FpfHrtSystemMemoryHealthCheck ---
    # Per-host max HRT service memory ceiling (GiB).
    hrt_system_memory_max_gib: float

    # --- FPF convergence checks (FSDB ribMap / BGP RIB / HRT bulk) ---
    # Signal 1: end-to-end convergence — max seconds from test-case start to
    # reaching the expected prefix count.
    convergence_signal1_e2e_max_sec: float
    # Signal 2: propagation — max seconds from the first non-zero sample to the
    # expected prefix count.
    convergence_signal2_local_max_sec: float
    # Signal 3: post-convergence stability — seconds the count must hold at the
    # expected value with no drops. (Unchanged between temp and expected.)
    convergence_signal3_stability_duration_sec: float

    # --- ODS discard / congestion counters (create_fpf_ods_counter_check) ---
    ods_in_dst_null_discard_max: int
    ods_in_discard_max: int
    ods_in_congestion_max: int
    ods_out_congestion_max: int

    # --- MemoryUtilizationHealthCheck (per-process, device memory) ---
    # Default per-process memory ceiling (bytes) + per-service overrides
    # (bytes). Keys are the process/service names the check matches on.
    mem_util_default_bytes: float
    mem_util_by_service: Mapping[str, float]

    # --- FpfHostSprayHealthCheck (per-lane RDMA egress fairness) ---
    # Signal 1: every host lane's avg egress (beth0-3) must EXCEED this (Gbps).
    host_spray_min_egress_gbps: float
    # Signal 2: per-host spread (max lane - min lane) must stay within this
    # (Gbps) — the spraying-fairness bound across lane0-3.
    host_spray_max_spread_gbps: float

    # --- FpfProdHrtPrefixStabilityHealthCheck (mode="local_drain") ---
    # Max seconds from the recorded disruption time (drain moment) to the LOCAL
    # prefix's impacted plane entering the drained state. Applies to both link
    # drain and device drain.
    prod_prefix_drain_sla_sec: float
    # --- FpfProdHrtPrefixStabilityHealthCheck (mode="local_undrain") ---
    # Max seconds from the recorded recovery time (undrain / interface re-enable
    # command) to the LOCAL prefix's impacted plane returning to the reachable
    # set. Recovery is inherently slower than a drain — a re-enable must reprogram
    # the port, re-advertise BGP, and relearn HRT (observed ~40s for an interface
    # re-enable vs ~10s for a drain) — so this bound is more lenient than the
    # drain SLA.
    prod_prefix_recovery_sla_sec: float

    # --- Service-restart RIB reconverge (mode="restart" on the rib convergence
    # checks) --- Max seconds from the recorded restart moment for the AFFECTED
    # device's RIB to return to the expected prefix count, while tolerating the
    # null/unresponsive thrift polls during the restart. BGP (and wedge_agent
    # warmboot, which restarts bgpd too) reconverge the BGP RIB; an FSDB restart
    # reconverges the FSDB ribMap much faster.
    bgp_restart_reconverge_sla_sec: float
    fsdb_restart_reconverge_sla_sec: float

    @property
    def hrt_system_memory_max_bytes(self) -> int:
        return int(self.hrt_system_memory_max_gib * _GIB)


# Per-process device-memory ceilings. Same values for both the temporary and
# expected sets (per review), mirroring the canonical set used by
# create_test_portchannel_playbook.
_MEM_UTIL_DEFAULT_BYTES: float = 5 * _GIB
_MEM_UTIL_BY_SERVICE: Mapping[str, float] = {
    "bgpd": 4.5 * _GIB,
    "fsdb": 5 * _GIB,
    "qsfp_service": 2 * _GIB,
    "fboss_sw_agent": 9 * _GIB,
    "fboss_hw_agent@0": 8 * _GIB,
}

# Finalized product expectations. These match the historical in-code defaults
# (signal1 180s / signal2 120s / signal3 60s; HRT memory 8 GiB; discard <=10000;
# congestion 0) — captured here so there is a single place to enforce them.
EXPECTED: FpfThresholds = FpfThresholds(
    hrt_system_memory_max_gib=8.0,
    convergence_signal1_e2e_max_sec=180.0,
    convergence_signal2_local_max_sec=120.0,
    convergence_signal3_stability_duration_sec=60.0,
    ods_in_dst_null_discard_max=10000,
    ods_in_discard_max=10000,
    ods_in_congestion_max=0,
    ods_out_congestion_max=0,
    mem_util_default_bytes=_MEM_UTIL_DEFAULT_BYTES,
    mem_util_by_service=_MEM_UTIL_BY_SERVICE,
    host_spray_min_egress_gbps=90.0,
    host_spray_max_spread_gbps=10.0,
    prod_prefix_drain_sla_sec=30.0,
    prod_prefix_recovery_sla_sec=60.0,
    bgp_restart_reconverge_sla_sec=60.0,
    fsdb_restart_reconverge_sla_sec=20.0,
)

# Relaxed thresholds used while known gaps are being worked. Differences vs
# EXPECTED:
#   * HRT system memory: 16 GiB (no fix yet; expected is 8 GiB).
#   * Convergence signal 1 (e2e): 5 min; signal 2 (propagation): 4 min.
#   * Host spray min per-lane egress: 75 Gbps (expected is 90 Gbps).
# Everything else mirrors EXPECTED.
TEMPORARY: FpfThresholds = FpfThresholds(
    hrt_system_memory_max_gib=16.0,
    convergence_signal1_e2e_max_sec=300.0,  # 5 min
    convergence_signal2_local_max_sec=240.0,  # 4 min
    convergence_signal3_stability_duration_sec=60.0,
    ods_in_dst_null_discard_max=10000,
    ods_in_discard_max=10000,
    ods_in_congestion_max=0,
    ods_out_congestion_max=0,
    mem_util_default_bytes=_MEM_UTIL_DEFAULT_BYTES,
    mem_util_by_service=_MEM_UTIL_BY_SERVICE,
    host_spray_min_egress_gbps=75.0,
    host_spray_max_spread_gbps=10.0,
    prod_prefix_drain_sla_sec=30.0,
    prod_prefix_recovery_sla_sec=60.0,
    bgp_restart_reconverge_sla_sec=60.0,
    fsdb_restart_reconverge_sla_sec=20.0,
)

# Toggle: run on the relaxed TEMPORARY set for now. Flip to False to enforce
# the finalized EXPECTED set once the underlying gaps are fixed.
USE_TEMPORARY_THRESHOLDS: bool = True

ACTIVE: FpfThresholds = TEMPORARY if USE_TEMPORARY_THRESHOLDS else EXPECTED
