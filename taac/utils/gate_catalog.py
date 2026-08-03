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
GATE_SC1_MEMORY_STABLE = "sc1_memory_stable"
GATE_SC1_MEMORY_TRANSIENT = "sc1_memory_transient"
GATE_SC1_ROUTES_ADVERTISED = "sc1_routes_advertised"
# SC2 -- constant-attribute-storage (ingress-only) varying-combinations test:
GATE_SC2_ROUTES_ACCEPTANCE = "sc2_routes_acceptance"
GATE_SC2_MEMORY_GROWTH = "sc2_memory_growth"
# SC5 -- maximally-packed UPDATE messages. Both gate the same custom step that
# BAG012's update-packing test already drives; they were previously bare
# `raise TestCaseFailure` calls, so the enforcement was real but invisible to
# the registry. Registering them keeps the behaviour identical while making the
# mode explicit and centrally controllable.
GATE_SC5_UPDATE_PACKING = "sc5_update_packing"
GATE_SC5_CAPTURE_INTEGRITY = "sc5_capture_integrity"
GATE_SC5_ADVERTISED_NLRI = "sc5_advertised_nlri"
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
GATE_DEFAULT_MODES: dict[str, str] = {
    # Transient (peak - stable) memory flatness across the egress-peer sweep --
    # observe until calibrated.
    GATE_SC1_MEMORY_TRANSIENT: GATE_MODE_PERMISSIVE,
    # Stable (soak-mean) memory flatness across the egress-peer sweep -- observe
    # (some small per-peer session overhead is expected, hence a tolerance).
    GATE_SC1_MEMORY_STABLE: GATE_MODE_PERMISSIVE,
    # Stable (soak-mean) CPU flatness across the egress-peer sweep -- the core
    # "constant computation" characteristic (compute once per update-group, not
    # per peer). Observe until calibrated.
    GATE_SC1_CPU_STABLE: GATE_MODE_PERMISSIVE,
    # Transient (peak - stable) CPU flatness across the egress-peer sweep (the
    # convergence-burst compute) -- observe.
    GATE_SC1_CPU_TRANSIENT: GATE_MODE_PERMISSIVE,
    # Anti-vacuousness: the DUT must advertise the ingress route set OUT to its
    # iBGP egress peers (per-peer postpolicy_sent_prefix_count) -- observe until
    # the advertised floor is calibrated, then flip to blocking.
    GATE_SC1_ROUTES_ADVERTISED: GATE_MODE_PERMISSIVE,
    # Anti-vacuousness: routes must reach the RIB -- hard from the start.
    GATE_SC2_ROUTES_ACCEPTANCE: GATE_MODE_BLOCKING,
    # Stable memory must grow sub-linearly (<= √k, k = path scale) across the
    # combination sweep -- calibrated on bag010 (fit p~=0.36, gated at 0.5),
    # blocking.
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
