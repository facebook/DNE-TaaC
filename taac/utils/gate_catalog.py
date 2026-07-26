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
GATE_SC1_MEMORY_TRANSIENT = "sc1_memory_transient"
# SC2 -- constant-attribute-storage (ingress-only) varying-combinations test:
GATE_SC2_ROUTES_ACCEPTANCE = "sc2_routes_acceptance"
GATE_SC2_MEMORY_GROWTH = "sc2_memory_growth"
# SC3 -- transient-memory route-scale sweep test:
GATE_SC3_MEMORY_DEDUP = "sc3_memory_dedup"
GATE_SC3_MEMORY_TRANSIENT = "sc3_memory_transient"

# The central control point: gate name -> default enforcement mode. Flip a gate
# globally by editing its mode here; override for a single run via the call site.
GATE_DEFAULT_MODES: dict[str, str] = {
    # Transient (peak - stable) memory flatness across the egress-peer sweep --
    # observe until calibrated.
    GATE_SC1_MEMORY_TRANSIENT: GATE_MODE_PERMISSIVE,
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
}


def register_all_gates() -> None:
    """Register every catalog gate (with its default mode) into gate_control."""
    for name, mode in GATE_DEFAULT_MODES.items():
        register_gate(name, mode)


# Populate the process-wide registry on import so any consumer of a gate-name
# constant gets the registered default without a separate setup call.
register_all_gates()
