# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict
"""fb303 counter access, multi-NPU endpoint resolution, and report formatting.

Open an fb303 client at an explicit ``host:port``, read regex-matched counters,
resolve which fb303 monitoring endpoints to scrape for a switch (the swagent
``:5909`` on a monolithic box, or the swagent plus one hwagent ``:5931 +
switchIndex`` per NPU on a multi-switch DNX box), and render the fan-out as a
readable report.

No counter semantics live here: units, DNX-vs-XGS queue numbering, VOQ
redirection and warmboot resets are the knowledge tool's job. The one thing the
report does guarantee is that three outcomes a reader could conflate stay apart:

* ``matched 0 keys``: the counter is ABSENT on that endpoint.
* matched keys valued zero: the counter exists and reads zero, a real "no drops".
* an errored endpoint: nothing was learned, which is not evidence of absence.

Values are rendered for every matched key only while the whole fan-out stays
under ``_MAX_RENDERED_COUNTER_KEYS``. Past that the report refuses: it keeps the
header and every errored endpoint, replaces the values with a histogram of
counter-name stems, and asks for a narrower regex. A ``.*`` read of a
17-endpoint DNX box matches hundreds of thousands of keys, which is megabytes of
prompt in a single tool result.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import cast, Protocol, TYPE_CHECKING

from taac.driver.driver_constants import (
    DEFAULT_AGENT_REMOTE_PORT,
    HW_AGENT_BASE_PORT,
)
from taac.utils.driver_factory import async_get_device_driver

if TYPE_CHECKING:
    from fb303.clients import FacebookService

logger: logging.Logger = logging.getLogger(__name__)

TAAC_OSS: bool = os.environ.get("TAAC_OSS", "").lower() in ("1", "true", "yes")

# A regex chosen to match no real counter, used only by the bounded NPU-probe
# fallback to check whether an hwagent port is live.
_LIVENESS_PROBE_REGEX: str = "__taac_query_counters_liveness_probe__"

# Upper bound on the bounded, contiguous NPU probe fallback (switchIndex 0..N-1),
# reached only when multi-switch is confirmed but the run-state gave no indices.
_MAX_NPU_PROBE: int = 16

# ``get_direct_client`` defaults to a 1 second thrift timeout, which a bulk
# regex read against an agent exporting tens of thousands of counters routinely
# blows; that would surface as an errored endpoint on every read.
_READ_TIMEOUT_SECONDS: float = 30.0

# A rendered counter line averages about 40 characters, so 5,000 keys is roughly
# 200KB or ~50k tokens: a sane ceiling for one tool result against a 1M-token
# window that has to hold the prompt, every prior turn, and every later one.
# Bounds the whole fan-out, not one endpoint: the joined string is what lands in
# the prompt, and a 17-endpoint DNX box multiplies a per-endpoint bound by 17.
_MAX_RENDERED_COUNTER_KEYS: int = 5_000

# Enough stems to name what dominates a match without becoming a second dump.
_MAX_REPORTED_STEMS: int = 20
_STEM_DISPLAY_WIDTH: int = 37
_ELISION: str = ".."

# The trailing component of an fb303 counter name that says how it was
# aggregated rather than what it counts. Percentiles are matched separately
# because their exact set (p50, p95, p99, p999, ...) is open-ended.
_AGGREGATION_SUFFIXES: frozenset[str] = frozenset(
    {"sum", "rate", "avg", "count", "min", "max", "pct"}
)
_PERCENTILE_SUFFIX: re.Pattern[str] = re.compile(r"^p\d+$")

# Digit runs that a network engineer reads as part of the name rather than as an
# index. Folding these would merge two protocols into one histogram row.
_PROTOCOL_TOKENS: frozenset[str] = frozenset({"ipv4", "ipv6", "mpls4", "mpls6"})
# Leftmost-first alternation: a protected token wins over the digit run inside
# it, because the scan consumes the whole token before reaching its digits.
_INDEX_OR_PROTECTED: re.Pattern[str] = re.compile(
    "|".join([*sorted(_PROTOCOL_TOKENS), r"\d+"]), re.IGNORECASE
)
_INDEX_PLACEHOLDER: str = "*"

_BYTES_PER_MEGABYTE: int = 1024 * 1024


class CounterSource(StrEnum):
    """Which of a switch's fb303 endpoints to read."""

    AUTO = "auto"
    SW_AGENT = "sw_agent"
    HW_AGENT = "hw_agent"


@dataclass(frozen=True)
class FbEndpoint:
    """One fb303 endpoint to scrape: a human-readable label and its TCP port."""

    label: str
    port: int


@dataclass(frozen=True)
class EndpointCounters:
    """Raw counters read from a single fb303 endpoint, labeled by its role/NPU.

    ``error`` is non-``None`` only when the read itself failed; the fan-out is
    best-effort, so one endpoint erroring never suppresses the others.
    """

    label: str
    counters: Mapping[str, int]
    error: str | None = None


class _MultiSwitchRunStateLike(Protocol):
    """Structural view of ``MultiSwitchRunState``, the two fields we read.

    ``async_get_device_driver`` is typed to return the abstract ``AbstractSwitch``
    base, which does not declare the multi-switch accessors; the concrete FBOSS
    driver does. A ``Protocol`` + ``cast`` narrows to that capability without a
    pyre suppression, and a non-FBOSS driver simply raises at call time (caught
    by the caller's best-effort fan-out).
    """

    @property
    def multiSwitchEnabled(self) -> bool: ...

    @property
    def hwIndexToRunState(self) -> Mapping[int, object]: ...


class _MultiSwitchDriverLike(Protocol):
    async def async_get_multi_switch_run_state(self) -> _MultiSwitchRunStateLike: ...


def make_fb303_client(host: str, port: int) -> "FacebookService":
    """Return an un-entered thrift-py3 fb303 client for ``host:port``.

    The returned client is an async context manager: enter it with ``async
    with``; do NOT await this function. Targets an explicit port so a caller can
    fan out across per-NPU hwagent ports, the port-agnostic primitive that
    ``health_check_utils.get_fb303_client`` also delegates to.
    """
    if TAAC_OSS:
        raise NotImplementedError(
            "fb303 client requires the Meta-internal get_direct_client; not "
            "available in OSS mode."
        )
    from fb303.clients import FacebookService
    from libfb.py.asyncio.thrift import ClientType, get_direct_client

    return get_direct_client(
        FacebookService,
        host=host,
        port=port,
        timeout=_READ_TIMEOUT_SECONDS,
        client_type=ClientType.THRIFT_ROCKET_CLIENT_TYPE,
    )


async def async_get_regex_counters(
    client: "FacebookService", pattern: str
) -> dict[str, int]:
    """Read the fb303 counters whose names match ``pattern`` from ``client``.

    ``client`` is an un-entered client from ``make_fb303_client``; this enters
    it, issues ``getRegexCounters``, and returns a plain mutable dict.
    """
    async with client as entered:
        return dict(await entered.getRegexCounters(pattern))


async def async_resolve_fb303_endpoints(
    host: str, source: CounterSource
) -> list[FbEndpoint]:
    """Resolve which fb303 endpoints to scrape for ``host`` given ``source``.

    ``SW_AGENT`` gives the swagent only; ``HW_AGENT`` gives the per-NPU hwagent
    ports (falling back to the swagent on a monolith, where hardware counters
    are in-process); ``AUTO`` gives the swagent plus every hwagent NPU on a
    multi-switch box, and just the swagent on a monolith.
    """
    swagent = FbEndpoint(
        label=f"swagent(:{DEFAULT_AGENT_REMOTE_PORT})", port=DEFAULT_AGENT_REMOTE_PORT
    )
    if source is CounterSource.SW_AGENT:
        return [swagent]
    npus = await _resolve_npu_endpoints(host)
    if source is CounterSource.HW_AGENT:
        return npus or [swagent]
    return [swagent, *npus]


async def _resolve_npu_endpoints(host: str) -> list[FbEndpoint]:
    """The per-NPU hwagent endpoints of a multi-switch box (``[]`` if monolithic).

    Uses the authoritative ``getMultiSwitchRunState`` accessor: its
    ``hwIndexToRunState`` keys are the valid switch indices. On any error the box
    is treated as single-switch (swagent-only) rather than guessed at.
    """
    try:
        driver = await async_get_device_driver(host)
        state = await cast(
            _MultiSwitchDriverLike, driver
        ).async_get_multi_switch_run_state()
        is_multi = state.multiSwitchEnabled
        indices = sorted(state.hwIndexToRunState.keys())
    except Exception:
        logger.warning(
            "multi-switch run-state unavailable for %s; treating as single-switch",
            host,
            exc_info=True,
        )
        return []
    if not is_multi:
        return []
    if indices:
        return [
            FbEndpoint(
                label=f"npu{index}(:{HW_AGENT_BASE_PORT + index})",
                port=HW_AGENT_BASE_PORT + index,
            )
            for index in indices
        ]
    return await _probe_npu_endpoints(host)


async def _probe_npu_endpoints(host: str) -> list[FbEndpoint]:
    """Bounded, contiguous hwagent-port probe, a clearly-caveated fallback.

    Reached only when multi-switch is confirmed but ``getMultiSwitchRunState``
    returned no switch indices. Probes ``5931, 5932, ...`` with a no-match regex
    and stops at the first port that does not answer, so it can never run
    unbounded. Endpoints found this way are labeled ``[probed]``.
    """
    endpoints: list[FbEndpoint] = []
    for index in range(_MAX_NPU_PROBE):
        port = HW_AGENT_BASE_PORT + index
        try:
            client = make_fb303_client(host, port)
            await async_get_regex_counters(client, _LIVENESS_PROBE_REGEX)
        except Exception:
            break
        endpoints.append(FbEndpoint(label=f"npu{index}(:{port})[probed]", port=port))
    return endpoints


async def async_query_counters(hostname: str, regex: str, source: str) -> str:
    """Resolve the endpoints, fan the regex read out across them, and format.

    ``source`` arrives as a raw string from a tool call and is parsed into
    ``CounterSource`` here, at the boundary; everything below is typed.
    Non-fatal: every failure becomes an ``ERROR:`` string, never an exception.
    """
    try:
        parsed_source = CounterSource(source)
    except ValueError:
        valid = ", ".join(member.value for member in CounterSource)
        return f"ERROR: invalid source '{source}'. Valid: {valid}."
    try:
        endpoints = await async_resolve_fb303_endpoints(hostname, parsed_source)
        results = await asyncio.gather(
            *(_read_endpoint(hostname, endpoint, regex) for endpoint in endpoints)
        )
        return format_counter_report(hostname, regex, list(results))
    except Exception as exc:
        logger.warning("query_counters failed", exc_info=True)
        return f"ERROR: query_counters failed: {exc!r}"


async def _read_endpoint(
    host: str, endpoint: FbEndpoint, regex: str
) -> EndpointCounters:
    """One endpoint erroring becomes a row, not a sunk fan-out."""
    try:
        client = make_fb303_client(host, endpoint.port)
        counters = await async_get_regex_counters(client, regex)
        return EndpointCounters(label=endpoint.label, counters=counters)
    except Exception as exc:
        logger.warning(
            "query_counters read failed for %s %s", host, endpoint.label, exc_info=True
        )
        return EndpointCounters(label=endpoint.label, counters={}, error=repr(exc))


def format_counter_report(
    hostname: str, regex: str, endpoints: list[EndpointCounters]
) -> str:
    """Render the fan-out result of a regex counter read into one readable string."""
    read_ok = [endpoint for endpoint in endpoints if endpoint.error is None]
    errored = [endpoint for endpoint in endpoints if endpoint.error is not None]
    total_matched = sum(len(endpoint.counters) for endpoint in read_ok)
    labels = ", ".join(endpoint.label for endpoint in endpoints) or "(none)"
    header = [
        f"Counters on {hostname} matching regex /{regex}/",
        f"Endpoints queried: {labels}",
        f"Total matched keys: {total_matched} across {len(read_ok)} endpoint(s) read "
        f"OK; {len(errored)} endpoint(s) errored (an errored endpoint reports "
        "nothing and is NOT evidence that a counter is absent).",
        "",
    ]
    body: list[str] = []
    if total_matched > _MAX_RENDERED_COUNTER_KEYS:
        body = _render_refusal(read_ok, errored, total_matched)
    else:
        for endpoint in endpoints:
            body.extend(_render_endpoint(endpoint))
    return "\n".join([*header, *body])


def _render_refusal(
    read_ok: list[EndpointCounters],
    errored: list[EndpointCounters],
    total_matched: int,
) -> list[str]:
    """The over-threshold body: no values, a stem histogram, and the remedy.

    Errored endpoints are still enumerated one by one. The refusal is about the
    volume the endpoints that answered would render, and says nothing about the
    ones that did not, so collapsing them here would turn "nothing was learned"
    into "nothing is there".
    """
    megabytes = _rendered_bytes(read_ok) / _BYTES_PER_MEGABYTE
    lines = [
        f"REFUSED: {total_matched} matched keys is too many to return "
        f"(roughly {megabytes:.1f} MB). Values omitted.",
        "Counter-name stems present, with key counts:",
        *_render_stems(read_ok),
        "Re-run with a regex narrow enough to match under "
        f"{_MAX_RENDERED_COUNTER_KEYS} keys.",
    ]
    if errored:
        lines.append("")
        for endpoint in errored:
            lines.extend(_render_endpoint(endpoint))
    return lines


def _rendered_bytes(read_ok: list[EndpointCounters]) -> int:
    """What the omitted ``  key=value`` lines would have cost, exactly."""
    return sum(
        len(key) + len(str(value)) + len("  =\n")
        for endpoint in read_ok
        for key, value in endpoint.counters.items()
    )


def _render_stems(read_ok: list[EndpointCounters]) -> list[str]:
    """The counter families behind a refused match, largest first."""
    stems: Counter[str] = Counter()
    for endpoint in read_ok:
        for key in endpoint.counters:
            stems[_counter_stem(key)] += 1
    ranked = sorted(stems.items(), key=lambda item: (-item[1], item[0]))
    shown = ranked[:_MAX_REPORTED_STEMS]
    name_width = max((len(_elide(stem)) for stem, _ in shown), default=0)
    count_width = max((len(str(count)) for _, count in shown), default=0)
    lines = [
        f"  {_elide(stem):<{name_width}}  {count:>{count_width}}"
        for stem, count in shown
    ]
    remaining = len(ranked) - len(shown)
    if remaining:
        lines.append(f"  (and {remaining} more stems)")
    return lines


def _counter_stem(name: str) -> str:
    """The counter family ``name`` belongs to, indices and aggregation removed.

    ``bcm.port12.queue3.voq_exhaustion_drops.sum.60`` gives
    ``bcm.port*.queue*.voq_exhaustion_drops``, so every port and queue of one
    family lands on one histogram row with a count worth ranking by. Without the
    index fold the top rows are whichever family sorts first alphabetically,
    each with a count of however many aggregations fb303 exports, which tells a
    reader nothing about what dominates the match.
    """
    parts = name.split(".")
    while len(parts) > 1 and parts[-1].isdigit():
        parts.pop()
    if len(parts) > 1 and _is_aggregation(parts[-1]):
        parts.pop()
    return _fold_indices(".".join(parts))


def _fold_indices(name: str) -> str:
    """Every digit run replaced by ``*``, except inside a protocol token."""
    return _INDEX_OR_PROTECTED.sub(
        lambda match: (
            match.group()
            if match.group().lower() in _PROTOCOL_TOKENS
            else _INDEX_PLACEHOLDER
        ),
        name,
    )


def _is_aggregation(part: str) -> bool:
    return part in _AGGREGATION_SUFFIXES or _PERCENTILE_SUFFIX.match(part) is not None


def _elide(stem: str) -> str:
    """``stem`` narrowed to a column, cut in the middle rather than the end.

    Counter families differ by an index (a port, a queue, a peer) that sits at
    the end of the stem, so dropping the tail renders whole runs of distinct
    stems as the same string and turns the histogram into one repeated row.
    """
    if len(stem) <= _STEM_DISPLAY_WIDTH:
        return stem
    budget = _STEM_DISPLAY_WIDTH - len(_ELISION)
    head = (budget + 1) // 2
    return f"{stem[:head]}{_ELISION}{stem[len(stem) - (budget - head) :]}"


def _render_endpoint(endpoint: EndpointCounters) -> list[str]:
    if endpoint.error is not None:
        return [
            f"[{endpoint.label}] READ FAILED: {endpoint.error} (nothing was read "
            "from this endpoint; this is NOT a counter-absent result)."
        ]
    matched = len(endpoint.counters)
    if matched == 0:
        return [
            f"[{endpoint.label}] matched 0 keys: counter ABSENT on this endpoint "
            "(NOT a zero-valued counter / not the same as 'no drops')."
        ]
    zero_note = (
        " (all matched counters are 0)"
        if all(value == 0 for value in endpoint.counters.values())
        else ""
    )
    lines = [f"[{endpoint.label}] matched {matched} keys{zero_note}:"]
    lines.extend(
        f"  {key}={endpoint.counters[key]}" for key in sorted(endpoint.counters)
    )
    return lines
