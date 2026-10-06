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
SC1_GATE_NAMES: tuple[str, ...] = (
    GATE_SC1_CPU_STABLE,
    GATE_SC1_CPU_TRANSIENT,
    GATE_SC1_MEMORY_LEAK,
    GATE_SC1_MEMORY_STABLE,
    GATE_SC1_MEMORY_TRANSIENT,
    GATE_SC1_ROUTES_ADVERTISED,
)
SC1_HIGH_CPU_BUDGET_SECONDS = 120
SC1_HIGH_CPU_SAMPLE_INTERVAL_SECONDS = 5
SC1_HIGH_CPU_SAMPLE_CEILING = (
    SC1_HIGH_CPU_BUDGET_SECONDS // SC1_HIGH_CPU_SAMPLE_INTERVAL_SECONDS
)
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
# SC6 -- churn-processing P(N): a fixed route batch is applied at each point
# of a route-scale sweep, and processing must not degrade as the background
# scale grows.
GATE_SC6_ROUTE_SCALE = "sc6_route_scale"
GATE_SC6_CHURN_MEASURED = "sc6_churn_measured"
GATE_SC6_CHURN_LATENCY = "sc6_churn_latency"
GATE_SC6_CHURN_PROCESSING = "sc6_churn_processing"
GATE_SC6_QUEUE_MEASURED = "sc6_queue_measured"
GATE_SC6_QUEUE_BACKPRESSURE = "sc6_queue_backpressure"
# SC4 -- transient-memory eBGP-INGRESS-sender-scale sweep test.
GATE_SC4_MEASUREMENT_INTEGRITY = "sc4_measurement_integrity"
GATE_SC4_MEMORY_CEILING = "sc4_memory_ceiling"
GATE_SC4_RIB_OUT_COVERAGE = "sc4_rib_out_coverage"
GATE_SC4_ROUTES_ACCEPTANCE = "sc4_routes_acceptance"
GATE_SC4_CPU_STABLE = "sc4_cpu_stable"
GATE_SC4_CPU_TRANSIENT = "sc4_cpu_transient"
GATE_SC4_MEMORY_GROWTH = "sc4_memory_growth"
GATE_SC4_MEMORY_TRANSIENT = "sc4_memory_transient"
GATE_SC4_MEMORY_TRANSIENT_FLATNESS = "sc4_memory_transient_flatness"
SC4_MAX_PEAK_MEMORY_MB = 5 * 1024
SC4_STABLE_SAMPLE_WINDOW_SECONDS = 30
SC4_TRANSIENT_MEMORY_CEILING_MB = 50.0
SC4_TRANSIENT_MEMORY_FLATNESS_CEILING_MB = 50.0
SC4_STABLE_MEMORY_GROWTH_PCT_CEILING = 20.0
SC4_STABLE_CPU_GROWTH_CEILING_PERCENTAGE_POINTS = 10.0
SC4_TRANSIENT_CPU_FLATNESS_CEILING_PERCENTAGE_POINTS = 25.0
SC4_GATE_NAMES: tuple[str, ...] = (
    GATE_SC4_ROUTES_ACCEPTANCE,
    GATE_SC4_RIB_OUT_COVERAGE,
    GATE_SC4_MEASUREMENT_INTEGRITY,
    GATE_SC4_MEMORY_CEILING,
    GATE_SC4_MEMORY_TRANSIENT,
    GATE_SC4_MEMORY_TRANSIENT_FLATNESS,
    GATE_SC4_MEMORY_GROWTH,
    GATE_SC4_CPU_STABLE,
    GATE_SC4_CPU_TRANSIENT,
)
# SC3 -- transient-memory route-scale sweep test:
GATE_SC3_MEMORY_ADJRIB_OUT = "sc3_memory_adjrib_out"
GATE_SC3_MEMORY_DEDUP = "sc3_memory_dedup"
GATE_SC3_MEMORY_TRANSIENT = "sc3_memory_transient"
SC3_GATE_NAMES: tuple[str, ...] = (
    GATE_SC3_MEMORY_ADJRIB_OUT,
    GATE_SC3_MEMORY_DEDUP,
    GATE_SC3_MEMORY_TRANSIENT,
)

# The central control point: gate name -> default enforcement mode. Flip a gate
# globally by editing its mode here; override for a single run via the call site.
# SC1 defaults are blocking. Thresholds remain overridable per test config so a
# hardware-specific calibration can change policy without changing evaluators.
GATE_DEFAULT_MODES: dict[str, str] = {
    # Per-stage transient memory is bounded as a percentage above stable RSS.
    GATE_SC1_MEMORY_TRANSIENT: GATE_MODE_BLOCKING,
    # Intra-soak memory leak: the soak TAIL (last 20% of samples) must not sit
    # above the soak MEAN. A converged process is flat; a tail riding above the
    # average is the moving average still climbing.
    GATE_SC1_MEMORY_LEAK: GATE_MODE_BLOCKING,
    # Steady memory must grow SUB-PROPORTIONALLY with the related-peer count.
    # Distinct from the leak gate above: that one looks within a single soak,
    # this one looks ACROSS the sweep. Peers grow 5x (202 -> 1002); memory grew
    # 545.1 -> 624.4MB = 14.5%, i.e. ~99KB/peer of route-independent per-peer
    # overhead (socket buffers, per-peer AdjRibOut bookkeeping, session state).
    # Proportional growth would be 400%. Gated at 50% (~340KB/peer) rather than
    # near the observation: one run gives no read on variance, and jemalloc
    # retention can move RSS without a logical change.
    GATE_SC1_MEMORY_STABLE: GATE_MODE_BLOCKING,
    # Stable (soak-mean) CPU must remain bounded as the egress-peer count grows.
    GATE_SC1_CPU_STABLE: GATE_MODE_BLOCKING,
    # Convergence-burst CPU may remain above 50% for up to
    # SC1_HIGH_CPU_SAMPLE_CEILING samples, approximately two minutes at the
    # configured five-second cadence.
    GATE_SC1_CPU_TRANSIENT: GATE_MODE_BLOCKING,
    # Anti-vacuousness: the DUT must advertise the ingress route set OUT to its
    # iBGP egress peers (per-peer postpolicy_sent_prefix_count).
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
    # Fixed attribute bundles and sub-attribute pools must stay bounded as the
    # route count grows.
    GATE_SC3_MEMORY_DEDUP: GATE_MODE_BLOCKING,
    # Stable RSS growth must remain below the raw Adj-RIB-Out payload that a
    # complete fallback to per-peer storage would require. This conservative
    # lower-bound check does not attempt to detect partial loss of sharing.
    GATE_SC3_MEMORY_ADJRIB_OUT: GATE_MODE_BLOCKING,
    # The sampled convergence peak may exceed post-convergence stable RSS by no
    # more than the configured absolute memory ceiling.
    GATE_SC3_MEMORY_TRANSIENT: GATE_MODE_BLOCKING,
    # Exact workload proof: the fixed total route/path population must reach the
    # RIB at every sender-count point.
    GATE_SC4_ROUTES_ACCEPTANCE: GATE_MODE_BLOCKING,
    # Every configured iBGP egress peer must retain the fixed route set through
    # the stable window; otherwise the resource sample used a smaller workload.
    GATE_SC4_RIB_OUT_COVERAGE: GATE_MODE_BLOCKING,
    # Missing samples or a bgpd PID change invalidates every resource series.
    GATE_SC4_MEASUREMENT_INTEGRITY: GATE_MODE_BLOCKING,
    # Hard device-safety ceiling over the process-lifetime VmHWM; a missing or
    # zero high-water mark also fails closed.
    GATE_SC4_MEMORY_CEILING: GATE_MODE_BLOCKING,
    # The process-lifetime high-water mark may exceed post-convergence stable
    # RSS by no more than the configured per-point safety ceiling.
    GATE_SC4_MEMORY_TRANSIENT: GATE_MODE_BLOCKING,
    # The defining SC4 characteristic: cold-start transient memory must remain
    # approximately flat while sender count changes at fixed route/path work.
    GATE_SC4_MEMORY_TRANSIENT_FLATNESS: GATE_MODE_BLOCKING,
    # Fixed route/path work permits only conservative cross-point growth in
    # stable RSS. This is separate from both absolute device safety gates.
    GATE_SC4_MEMORY_GROWTH: GATE_MODE_BLOCKING,
    # Stable CPU must remain within its explicit cross-point trend bound across
    # the complete five-point sweep.
    GATE_SC4_CPU_STABLE: GATE_MODE_BLOCKING,
    # Two complete BAG012 sweeps produced 26.86- and 78.66-point peak spreads
    # while stable CPU, memory, convergence, and workload-integrity gates all
    # passed. A single sampled peak is not yet a repeatable blocking statistic;
    # retain the 25-point signal as a permissive calibration warning.
    GATE_SC4_CPU_TRANSIENT: GATE_MODE_PERMISSIVE,
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
    # Exact swept-axis proof: each point must hold N selected IPv6 prefixes,
    # N * iBGP-peer-count active paths, zero unresolved prefixes, and the full
    # eBGP peer set must each advertise exactly N prefixes. Calibration-free.
    GATE_SC6_ROUTE_SCALE: GATE_MODE_BLOCKING,
    # Anti-vacuousness: the targeted iBGP source must emit exactly the configured
    # 100-prefix churn set and every eBGP receiver must observe that complete set
    # after ingress, producing a finite positive cross-port time. Blocking.
    GATE_SC6_CHURN_MEASURED: GATE_MODE_BLOCKING,
    # Absolute ceiling on 100-route cross-port churn processing. BAG012 held all
    # eight 5K-through-50K churn/revert transitions to 1.57-1.74s against the
    # 10s ceiling, so the qualified gate is blocking.
    GATE_SC6_CHURN_LATENCY: GATE_MODE_BLOCKING,
    # THE SC6 claim: cross-port churn processing is ~independent of background
    # route scale. BAG012 measured 1.10x churn and 1.06x revert flatness against
    # the 2.0x tolerance, so the qualified gate is blocking.
    GATE_SC6_CHURN_PROCESSING: GATE_MODE_BLOCKING,
    # A missing queue sample cannot prove absence of backpressure. Evidence
    # integrity is calibration-free and therefore blocking from the start.
    GATE_SC6_QUEUE_MEASURED: GATE_MODE_BLOCKING,
    # Egress-queue backpressure accumulated DURING each churn window. Gated on
    # block DURATION, not block COUNT: count scales with work volume, duration
    # is the health signal. BAG012 measured 0ms in all eight windows against the
    # 0ms ceiling, so the qualified gate is blocking.
    GATE_SC6_QUEUE_BACKPRESSURE: GATE_MODE_BLOCKING,
}


def register_all_gates() -> None:
    """Register every catalog gate (with its default mode) into gate_control."""
    for name, mode in GATE_DEFAULT_MODES.items():
        register_gate(name, mode)


# Populate the process-wide registry on import so any consumer of a gate-name
# constant gets the registered default without a separate setup call.
register_all_gates()
