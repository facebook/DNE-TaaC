# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-strict

"""Shared naming, configuration, and log format for bgpcpp CPU/RSS characterization.

Two measurements exist today, each implemented as an embeddable START/STOP
bracket (see ``internal/steps/bgp_cpu_percentile_transient_custom_step.py`` and
``internal/steps/bgp_rss_delta_bracket_custom_step.py``):

  cpu_percentile  bgpcpp CPU percentiles over the bracketed window
  rss_delta       bgpcpp RSS growth over a settled pre-window baseline, plus peak

This module owns the three things those brackets must agree on across every
playbook that uses them:

1. **Session keys.** One canonical shape, so a log line identifies the
   measurement, the playbook, the phase, and the device without a lookup table.
2. **jq variable names.** The STOP step stashes its summary into a jq var that
   the matching postcheck reads back. The producer and the consumer must use the
   same string; both now take it from here instead of repeating a literal.
3. **The summary log line.** One token, ``TAAC_CHAR``, and key=value fields, so a
   whole nightly run can be reduced to a table with a single grep.

Nothing here constructs a Stage or a Step, and it has no TAAC imports, so both
the step implementations and the stage/playbook factories can depend on it
without a cycle.

Extraction across a run:

    grep -h TAAC_CHAR <logs> | sed 's/.*TAAC_CHAR //'
"""

import dataclasses
import typing as t

# Single grep token for every characterization summary line, both kinds.
CHARACTERIZATION_LOG_TOKEN: str = "TAAC_CHAR"

# Measurement kinds. Used in session keys and as the ``kind=`` log field.
KIND_CPU_PERCENTILE: str = "cpu_percentile"
KIND_RSS_DELTA: str = "rss_delta"

# Base jq variable names the STOP steps stash summaries into, read back by the
# CPU_PERCENTILE_CHECK / RSS_DELTA_CHECK postchecks. jq-safe: no dots or colons.
#
# These name a KIND, not a span. Do not hand one to a bracket directly: two
# brackets of the same kind in one playbook would write the same var and the
# second would silently overwrite the first, with the postcheck reporting one
# span's number under both. Call characterization_summary_jq_var(), which
# qualifies the base name with the span.
CPU_SUMMARY_JQ_VAR: str = "cpu_percentile_summary"
RSS_SUMMARY_JQ_VAR: str = "rss_delta_summary"

_SUMMARY_JQ_VAR_BY_KIND: t.Mapping[str, str] = {
    KIND_CPU_PERCENTILE: CPU_SUMMARY_JQ_VAR,
    KIND_RSS_DELTA: RSS_SUMMARY_JQ_VAR,
}

# Canonical phase names. The phase says WHICH part of the playbook the bracket
# encloses, so measurements are comparable across tests that share a shape.
#
#   PHASE_CONVERGENCE  bgpcpp is converging: cold start, daemon restart.
#                      Baseline is pre-toggle idle, so RSS growth is the cost of
#                      holding the route load and CPU covers the convergence burst.
#   PHASE_WORKLOAD     a stress workload runs against an already converged DUT:
#                      churn, route storm, oscillation, IGP instability.
#                      Baseline is the settled converged footprint, so RSS growth
#                      is workload-attributable and CPU is the sustained cost.
#   PHASE_SOAK         a long steady-state hold: longevity. Growth over the soak
#                      is the leak signal.
PHASE_CONVERGENCE: str = "convergence"
PHASE_WORKLOAD: str = "workload"
PHASE_SOAK: str = "soak"

_FIELD_SEPARATOR: str = "|"


@dataclasses.dataclass(frozen=True)
class CharacterizationConfig:
    """Which brackets to place around a span, and how densely to sample.

    Gating is NOT configured here. This object decides whether a measurement is
    collected; the threshold that turns a collected measurement into a verdict
    lives on the postcheck config (``CpuCharacterizationConfig.gate_threshold_pct``
    and ``RssDeltaConfig.max_growth_pct``). Collection and gating are separated
    deliberately so a playbook can report a number for weeks before anyone has to
    defend a threshold for it.

    Attributes:
        enable_cpu: Collect the bgpcpp CPU percentile bracket.
        enable_rss: Collect the bgpcpp RSS delta bracket.
        cpu_interval_seconds: CPU sampling interval. Denser sampling costs more
            device round trips; 2s over a multi-minute span is ample for p95.
            Ignored when cpu_on_device is set.
        cpu_on_device: Run the CPU sampler ON the DUT as a detached loop and
            read its log once at STOP, instead of one FCR round-trip per
            sample. Two device queries per span rather than ~800, at a true
            fixed 1s cadence instead of the ~4.7s effective period the
            per-sample path actually achieves. This is the mechanism that makes
            the bracket cheap enough for route-storm, whose periodic tasks were
            removed for distorting transition timing.
        cpu_on_device_compare: Run the legacy per-sample sampler ALONGSIDE the
            on-device loop and log both p95 values for the identical span. For
            validation runs only, since it re-incurs the ~800 round trips the
            on-device path exists to remove. Its purpose is to make a single
            run answer "do the two mechanisms agree" without a second run and
            without a cross-run confound. Note that the two are NOT expected to
            agree at high percentiles: the coarser grid averages bursts away.
        rss_on_device: Run the RSS sampler on the DUT too, by the same
            mechanism. The per-sample path measured 5.84s effective against a
            3.0s nominal interval on bag011, so once CPU moved on-device the
            RSS bracket became the expensive half of the span. Also yields
            VmHWM, which the per-sample path never read.
        keep_ondevice_log: Leave the DUT-side sampler log in place after STOP
            instead of deleting it, so the raw per-sample records can be
            inspected on the device. The devserver-side dump is written either
            way; this is for when you want to look at the file in situ.
        rss_interval_seconds: VmRSS sampling interval, which sets the
            resolution of the reported peak. Honored on both paths: the DUT
            loop's sleep when rss_on_device is set, the background sampler's
            interval otherwise.
        rss_baseline_settle_max_seconds: Cap on how long START waits for RSS to
            plateau before taking the baseline. Raise it for spans whose entry
            point is still climbing; the bracket takes the baseline early rather
            than never, and says so in the log.
    """

    enable_cpu: bool = True
    enable_rss: bool = True
    cpu_interval_seconds: float = 2.0
    cpu_on_device: bool = False
    cpu_on_device_compare: bool = False
    rss_on_device: bool = False
    keep_ondevice_log: bool = False
    rss_interval_seconds: float = 3.0
    rss_baseline_settle_max_seconds: float = 90.0


# Collect both measurements, gate on neither. The default for adding a bracket to
# a playbook that has never carried one: it produces the data needed to choose a
# threshold without being able to fail a run while that data does not exist.
OBSERVE_ONLY: CharacterizationConfig = CharacterizationConfig()

# As OBSERVE_ONLY, but BOTH samplers run on the DUT. Proven on bag011 over a
# 3832s attribute-churn span: the CPU loop held 1.0066s against a 1s target for
# an hour under load, at two device queries instead of ~800.
#
# ``keep_ondevice_log`` is deliberately left off. It does NOT decide whether the
# raw per-sample records survive: ``dump_raw`` writes them devserver-side on the
# STOP path and on the salvage path alike, before the DUT-side copy is removed.
# All it buys is a duplicate under the DUT's /tmp, and because the log name
# carries a per-run stamp nothing ever overwrites it, so those duplicates
# accumulate one span at a time on a box that CI keeps reusing. Set it per call
# site when you specifically want to read the file in situ.
OBSERVE_ONLY_ON_DEVICE: CharacterizationConfig = CharacterizationConfig(
    cpu_on_device=True,
    rss_on_device=True,
)

# As OBSERVE_ONLY_ON_DEVICE, but ALSO runs the legacy per-sample CPU sampler
# over the same span for a direct A/B. Costs the ~800 round trips the on-device
# path exists to remove, so use it to validate a mechanism change, not to
# collect numbers.
OBSERVE_ONLY_ON_DEVICE_COMPARE: CharacterizationConfig = dataclasses.replace(
    OBSERVE_ONLY_ON_DEVICE, cpu_on_device_compare=True
)

# Collect nothing. For spans where the measurement would be meaningless, e.g. a
# span too short to plateau an RSS baseline.
DISABLED: CharacterizationConfig = CharacterizationConfig(
    enable_cpu=False, enable_rss=False
)


def characterization_summary_jq_var(kind: str, span: str) -> str:
    """Build the jq variable name one bracket's STOP step writes and its
    postcheck reads.

    Both sides MUST call this with the same (kind, span) pair. That is the whole
    point of it existing: the producer is a Step built in the stage layer and the
    consumer is a postcheck built in the check-profile layer, and nothing else
    ties the two strings together.

    Qualifying by span is what makes more than one bracket of a kind safe in a
    single playbook. ``span`` is normally the phase (PHASE_CONVERGENCE,
    PHASE_WORKLOAD, PHASE_SOAK); pass a distinct label when one playbook brackets
    the same phase twice, e.g. "workload_pre" and "workload_post".

    Args:
        kind: KIND_CPU_PERCENTILE or KIND_RSS_DELTA.
        span: Span label, normally a PHASE_* value. Must be jq-safe: letters,
            digits, and underscores only.

    Returns:
        "<base var for kind>_<span>", e.g. "cpu_percentile_summary_workload".

    Raises:
        ValueError: Unknown kind, or a span that is empty or not jq-safe.
    """
    base = _SUMMARY_JQ_VAR_BY_KIND.get(kind)
    if base is None:
        raise ValueError(
            f"Unknown characterization kind {kind!r}: "
            f"expected one of {sorted(_SUMMARY_JQ_VAR_BY_KIND)}"
        )
    # A dot or colon in a jq var silently changes how the expression parses, so
    # reject anything outside the safe set at construction instead of shipping a
    # postcheck that reads nothing.
    if not span or not span.replace("_", "").isalnum():
        raise ValueError(
            f"Characterization span {span!r} is not jq-safe: "
            "expected a non-empty string of letters, digits, and underscores"
        )
    return f"{base}_{span}"


def characterization_session_key(
    kind: str,
    playbook: str,
    phase: str,
    device_name: str,
) -> str:
    """Build the canonical session key that ties a START to its STOP.

    The key is also the identity carried in every log line for the bracket, which
    is why it encodes the playbook and phase rather than being an opaque handle.

    Args:
        kind: KIND_CPU_PERCENTILE or KIND_RSS_DELTA.
        playbook: Playbook name, e.g. "bgp_ebb_attribute_churn_playbook".
        phase: One of PHASE_CONVERGENCE, PHASE_WORKLOAD, PHASE_SOAK.
        device_name: DUT hostname.

    Returns:
        "<kind>|<playbook>|<phase>|<device_name>"
    """
    return _FIELD_SEPARATOR.join((kind, playbook, phase, device_name))


def parse_session_key(session_key: str) -> t.Optional[t.Dict[str, str]]:
    """Recover the parts of a canonical session key.

    Returns None for a key that does not have the canonical shape, so a caller
    can degrade to logging without the identity fields rather than raising. Keys
    predating this convention, and any hand-written key, take that path.

    Args:
        session_key: The key handed to the START/STOP steps.

    Returns:
        {"kind", "playbook", "phase", "device_name"}, or None if not canonical.
    """
    parts = session_key.split(_FIELD_SEPARATOR)
    if len(parts) != 4 or not all(parts):
        return None
    return {
        "kind": parts[0],
        "playbook": parts[1],
        "phase": parts[2],
        "device_name": parts[3],
    }


def format_characterization_summary(
    kind: str,
    session_key: str,
    fields: t.Mapping[str, t.Any],
) -> str:
    """Render the one canonical summary line for a completed bracket.

    Emitted once per bracket at STOP, in addition to whatever human-readable
    lines the step already logs. Field order is caller-controlled and stable, so
    the output is safe to parse positionally or by key.

    Floats are rendered to two decimals; everything else uses str(). Values are
    not quoted, so callers must keep them whitespace-free for the line to remain
    splittable on spaces.

    Args:
        kind: KIND_CPU_PERCENTILE or KIND_RSS_DELTA.
        session_key: Canonical session key; contributes playbook/phase/host when
            it parses, and is echoed as session= when it does not.
        fields: Measurement fields, e.g. {"p95": 228.9, "window_s": 3612.4}.

    Returns:
        A single line beginning with CHARACTERIZATION_LOG_TOKEN.
    """
    parsed = parse_session_key(session_key)
    head: t.List[str] = [CHARACTERIZATION_LOG_TOKEN, f"kind={kind}"]
    if parsed is None:
        head.append(f"session={session_key}")
    else:
        head.append(f"playbook={parsed['playbook']}")
        head.append(f"phase={parsed['phase']}")
        head.append(f"host={parsed['device_name']}")
    for key, value in fields.items():
        if isinstance(value, float):
            head.append(f"{key}={value:.2f}")
        else:
            head.append(f"{key}={value}")
    return " ".join(head)
