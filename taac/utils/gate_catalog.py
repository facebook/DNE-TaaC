# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-strict
"""Central catalog of TAAC inline test gates and their default enforcement modes.

The single place to SEE and CONTROL which inline (step-computed) test gates BLOCK
vs merely OBSERVE. Each gate has a canonical name constant (import it -- never
stringly-type a gate name) and a default mode in :data:`GATE_DEFAULT_MODES`, and
:func:`register_all_gates` registers them into the process-wide
:mod:`gate_control` registry. New gates should be added here so every registered
gate is visible + controllable in one file.

Precedence at a call site: an explicit per-run mode (e.g. a ``<gate>_gate_mode``
test-config param passed to ``apply_registered_gate``) overrides this catalog;
otherwise the catalog default applies. New gates default PERMISSIVE (observe)
until calibrated on a real run, then are flipped to BLOCKING here.

This is the inline-gate analog of the declarative health-check policy in
``bgp_ebb_check_profiles.py``. Folding inline gates into the health-check
framework (a first-class blocking/permissive severity) is a future consolidation;
for now the two live side by side (see [[project_taac_gate_control_infra]]).
"""

from taac.utils.gate_control import (
    GATE_MODE_BLOCKING,
    GATE_MODE_PERMISSIVE,
    register_gate,
)

# ─── Gate name constants (import these; never hardcode a gate name string) ───
# SC1 -- performance-scaling (egress iBGP peer-scale) sweep test:
GATE_SC1_CPU_STABLE = "sc1_cpu_stable"
GATE_SC1_CPU_TRANSIENT = "sc1_cpu_transient"
GATE_SC1_MEMORY_LEAK = "sc1_memory_leak"
GATE_SC1_MEMORY_STABLE = "sc1_memory_stable"
GATE_SC1_MEMORY_TRANSIENT = "sc1_memory_transient"
GATE_SC1_ROUTES_ADVERTISED = "sc1_routes_advertised"
# SC2 -- constant-attribute-storage (ingress-only) varying-combinations test:
GATE_SC2_ROUTES_ACCEPTANCE = "sc2_routes_acceptance"
GATE_SC2_NEXTHOPS_RESOLVED = "sc2_nexthops_resolved"
GATE_SC2_ATTRIBUTE_POOLS_FLAT = "sc2_attribute_pools_flat"
GATE_SC2_PATHS_DEDUPLICATED = "sc2_paths_deduplicated"
GATE_SC2_MEMORY_GROWTH = "sc2_memory_growth"
# SC5 -- maximally-packed UPDATE messages. Both gate the same custom step that
# BAG012's update-packing test already drives; they were previously bare
# `raise TestCaseFailure` calls, so the enforcement was real but invisible to
# the registry. Registering them keeps the behaviour identical while making the
# mode explicit and centrally controllable.
GATE_SC5_UPDATE_PACKING = "sc5_update_packing"
GATE_SC5_CAPTURE_INTEGRITY = "sc5_capture_integrity"
GATE_SC5_ADVERTISED_NLRI = "sc5_advertised_nlri"
# SC6 -- churn-processing P(N): a fixed 100-route churn is applied at each point
# of a route-scale sweep, and processing must not degrade as the background
# scale grows.
GATE_SC6_ROUTE_SCALE = "sc6_route_scale"
GATE_SC6_CHURN_MEASURED = "sc6_churn_measured"
GATE_SC6_CHURN_LATENCY = "sc6_churn_latency"
GATE_SC6_CHURN_PROCESSING = "sc6_churn_processing"
GATE_SC6_QUEUE_BACKPRESSURE = "sc6_queue_backpressure"
# SC4 -- transient-memory eBGP-INGRESS-sender-scale sweep test. SC4 must NOT
# reuse the SC1 gate names: mode is keyed by gate name, so flipping an SC1 gate
# after SC1 calibration would silently flip it for SC4 too, against a completely
# different sweep (SC1 varies EGRESS peers at a fixed route set; SC4 varies
# INGRESS senders, which scales the path count).
GATE_SC4_CPU_STABLE = "sc4_cpu_stable"
GATE_SC4_CPU_TRANSIENT = "sc4_cpu_transient"
GATE_SC4_MEMORY_GROWTH = "sc4_memory_growth"
GATE_SC4_MEMORY_TRANSIENT = "sc4_memory_transient"
# SC3 -- transient-memory route-scale sweep test:
GATE_SC3_MEMORY_DEDUP = "sc3_memory_dedup"
GATE_SC3_MEMORY_TRANSIENT = "sc3_memory_transient"

# The central control point: gate name -> default enforcement mode. Flip a gate
# globally by editing its mode here; override for a single run via the call site.
# SC1 is fully BLOCKING as of the 2026-08-05 bag010 sweep -- the first run whose
# measurement window contained only the advertisement (D114833653). Worst value
# observed across 202/402/602/802/1002 peers, against the shipped ceiling:
#
#   cpu_stable         2.17%   vs 10%     (4.6x margin)
#   cpu_transient      2 samples vs 5     (2.5x)
#   memory_leak        1.001   vs 1.05
#   memory_stable      14.5%   vs 50%     (3.4x)
#   memory_transient   1.8%    vs 10%     (5.5x)
#
# Every threshold is overridable per test-config, so a flip that turns out wrong
# is a param change rather than a code change.
GATE_DEFAULT_MODES: dict[str, str] = {
    # Transient (peak - stable) memory flatness across the egress-peer sweep --
    # observe until calibrated.
    GATE_SC1_MEMORY_TRANSIENT: GATE_MODE_BLOCKING,
    # Intra-soak memory leak: the soak TAIL (last 20% of samples) must not sit
    # above the soak MEAN. A converged process is flat; a tail riding above the
    # average is the moving average still climbing. Measured 1.000-1.001 across
    # the sweep on bag010. Observe until flipped.
    GATE_SC1_MEMORY_LEAK: GATE_MODE_BLOCKING,
    # Steady memory must grow SUB-PROPORTIONALLY with the related-peer count.
    # Distinct from the leak gate above: that one looks within a single soak,
    # this one looks ACROSS the sweep. Peers grow 5x (202 -> 1002); memory grew
    # 545.1 -> 624.4MB = 14.5%, i.e. ~99KB/peer of route-independent per-peer
    # overhead (socket buffers, per-peer AdjRibOut bookkeeping, session state).
    # Proportional growth would be 400%. Gated at 50% (~340KB/peer) rather than
    # near the observation: one run gives no read on variance, and jemalloc
    # retention can move RSS without a logical change. Observe until calibrated.
    GATE_SC1_MEMORY_STABLE: GATE_MODE_BLOCKING,
    # Stable (soak-mean) CPU flatness across the egress-peer sweep -- the core
    # "constant computation" characteristic (compute once per update-group, not
    # per peer). Observe until calibrated.
    GATE_SC1_CPU_STABLE: GATE_MODE_BLOCKING,
    # Convergence-burst CPU may remain above 50% for up to 24 samples, which is
    # approximately two minutes at the configured five-second cadence.
    GATE_SC1_CPU_TRANSIENT: GATE_MODE_BLOCKING,
    # Anti-vacuousness: the DUT must advertise the ingress route set OUT to its
    # iBGP egress peers (per-peer postpolicy_sent_prefix_count) -- observe until
    # the advertised floor is calibrated, then flip to blocking.
    GATE_SC1_ROUTES_ADVERTISED: GATE_MODE_BLOCKING,
    # Anti-vacuousness: routes must reach the RIB -- hard from the start.
    GATE_SC2_ROUTES_ACCEPTANCE: GATE_MODE_BLOCKING,
    # Every accepted route must have a RESOLVABLE next-hop, i.e.
    # TRibSummary.routes_with_unresolved_nexthops == 0. char-2 measures a real,
    # best-path-selected RIB; a RIB full of unresolved routes is a different
    # (and easier) thing to store. Blocking from the start and deliberately not
    # a tolerance -- the expected value is exactly zero, so there is nothing to
    # calibrate. Ingress-only comes from having no egress peer configured, NOT
    # from breaking next-hop resolution.
    GATE_SC2_NEXTHOPS_RESOLVED: GATE_MODE_BLOCKING,
    # The three sub-attribute pools (AS paths / community sets / ext-community
    # sets) must stay at their configured pool size however far the combination
    # count is swept -- combinations only INDEX the pools. This is characteristic
    # 2 stated directly, and it is the one SC threshold that needs no
    # calibration: the expected value is exactly the pool size, so the tolerance
    # is measurement headroom for the 180s eviction lag rather than a guess.
    GATE_SC2_ATTRIBUTE_POOLS_FLAT: GATE_MODE_BLOCKING,
    # BgpPath's compare key includes the next-hop, so a prefix contributes one
    # entry per peer and the deduplicator should hold exactly the path count at
    # every sweep point. Growth here means paths are NOT collapsing, and storage
    # scales with combinations x peers instead of with attributes.
    GATE_SC2_PATHS_DEDUPLICATED: GATE_MODE_BLOCKING,
    # Stable memory must grow sub-linearly (<= k^p, k = path scale) across the
    # combination sweep. The earlier bag010 calibration (fit p~=0.36) is VOID --
    # it was measured against the old ingredient-pool attribute model -- so the
    # exponent is currently an uncalibrated, deliberately loose backstop. See
    # _SC2_MEMORY_SCALING_EXPONENT in
    # internal/steps/bgp_attribute_storage_varying_combinations_custom_step.py
    # for the re-derivation this needs from the first clean run.
    GATE_SC2_MEMORY_GROWTH: GATE_MODE_BLOCKING,
    # Deduplicator-size constancy across the route sweep -- observe.
    GATE_SC3_MEMORY_DEDUP: GATE_MODE_PERMISSIVE,
    # Transient (peak - stable) memory flatness across the route sweep -- observe.
    GATE_SC3_MEMORY_TRANSIENT: GATE_MODE_PERMISSIVE,
    # Transient (peak - stable) memory flatness across the ingress-sender sweep.
    # This IS the SC4 claim -- the convergence burst must not buffer per sender --
    # and is the first of these to calibrate and flip. Observe until then.
    GATE_SC4_MEMORY_TRANSIENT: GATE_MODE_PERMISSIVE,
    # Stable memory across the ingress-sender sweep is a GROWTH gate, not a
    # flatness one: n senders advertise the same prefixes, so the path count
    # scales with n (50K -> 800K) and steady-state memory is expected to grow.
    # What must hold is that it grows SUB-linearly (<= sqrt(k), k = path scale),
    # i.e. paths share attribute storage. Observe until calibrated.
    GATE_SC4_MEMORY_GROWTH: GATE_MODE_PERMISSIVE,
    # Steady-state CPU across the ingress-sender sweep -- the egress fan-out is
    # constant (25M sent at every point), so this should be flat. Observe.
    GATE_SC4_CPU_STABLE: GATE_MODE_PERMISSIVE,
    # Packing correctness: any non-last UPDATE in an attribute group below the
    # packed-size floor is a real regression, not a tuning question -- blocking
    # from the start (and already enforced as such before it was registered).
    GATE_SC5_UPDATE_PACKING: GATE_MODE_BLOCKING,
    # Anti-vacuousness for the same step: if the capture or parse produced
    # errors, the packing verdict is meaningless and must not pass silently.
    GATE_SC5_CAPTURE_INTEGRITY: GATE_MODE_BLOCKING,
    # Anti-vacuousness: a run where the DUT advertised nothing satisfies "all
    # non-last UPDATEs are packed" while checking nothing. Gate on ADVERTISED
    # NLRI rather than UPDATE count -- UPDATE count falls as packing improves,
    # so an UPDATE-count floor would fail a genuinely better-packing device.
    # The floor is per-config (step default 0) so one device's calibration
    # cannot gate another's. Blocking.
    GATE_SC5_ADVERTISED_NLRI: GATE_MODE_BLOCKING,
    # Anti-vacuousness on the SWEPT AXIS. Nothing else proves the background
    # route scale actually changed between iterations: if a prefix-pool resize
    # silently no-ops, every scale runs at the same load and P(N) comes back
    # perfectly FLAT -- which reads as a pass. The test would confirm its own
    # claim by never varying the variable. Calibration-free, so blocking.
    GATE_SC6_ROUTE_SCALE: GATE_MODE_BLOCKING,
    # Anti-vacuousness: the per-scale pass criterion is
    # `convergence is None or convergence <= threshold`, so a scale whose
    # capture produced NO measurement passes silently. Require a real
    # measurement at every scale. Calibration-free -- blocking from the start.
    GATE_SC6_CHURN_MEASURED: GATE_MODE_BLOCKING,
    # Absolute ceiling on churn reconvergence. Churning 100 routes should take
    # seconds; anything past ~10s is a red flag. Permissive for the first run
    # only, to confirm the ceiling holds at the 50K background before enforcing.
    GATE_SC6_CHURN_LATENCY: GATE_MODE_PERMISSIVE,
    # THE SC6 claim: churn processing is ~independent of background route scale.
    # Flatness of the per-scale reconvergence series. Permissive until
    # calibrated.
    GATE_SC6_CHURN_PROCESSING: GATE_MODE_PERMISSIVE,
    # Egress-queue backpressure accumulated DURING each churn window. Gated on
    # block DURATION, not block COUNT: count scales with work volume, duration
    # is the health signal. Permissive until calibrated.
    GATE_SC6_QUEUE_BACKPRESSURE: GATE_MODE_PERMISSIVE,
    # Convergence-burst CPU across the ingress-sender sweep. Unlike SC1's, this
    # one has no strong a-priori shape: absorbing 16x the paths may legitimately
    # cost more CPU. Collect first, then decide flatness vs growth.
    GATE_SC4_CPU_TRANSIENT: GATE_MODE_PERMISSIVE,
}


def register_all_gates() -> None:
    """Register every catalog gate (with its default mode) into gate_control."""
    for name, mode in GATE_DEFAULT_MODES.items():
        register_gate(name, mode)


# Populate the process-wide registry on import so any consumer of a gate-name
# constant gets the registered default without a separate setup call.
register_all_gates()
