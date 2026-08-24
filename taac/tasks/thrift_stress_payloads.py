# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""
Per-platform / per-variant thrift stress payloads for ThriftStressPeriodicTask.

A "payload" is a `List[ThriftStressCall]`. Each entry says "call this async
method on the device driver, with these args, this many times concurrently per
burst." The task fires every entry's `requests_per_burst` copies into a single
`asyncio.gather(...)` per burst, then sleeps the inter-burst interval, repeat.

Add a new platform by adding a builder function. Disruptive variants whose
calls need DUT context (e.g. interface lists for qsfp flaps) are functions
that take that context and return the call list — testconfigs invoke them at
build time. The naming convention is `<platform>_<variant>(...)`.

Reference shape (Pavan): `scripts/pavanpatil/thrift_call_disruptive.py`.
"""

import dataclasses
import typing as t


def _tuples_to_lists(value: t.Any) -> t.Any:
    """Recursively convert tuples to lists. Used for JSON-safe serialization."""
    if isinstance(value, tuple):
        return [_tuples_to_lists(v) for v in value]
    if isinstance(value, list):
        return [_tuples_to_lists(v) for v in value]
    if isinstance(value, dict):
        return {k: _tuples_to_lists(v) for k, v in value.items()}
    return value


@dataclasses.dataclass(frozen=True)
class ThriftStressCall:
    """One API call shape inside a thrift stress burst.

    Attributes:
        method: Async method name on the device driver (e.g. FbossSwitch).
            Must be a coroutine function — checked at runtime via
            `inspect.iscoroutinefunction`.
        args: Positional args passed each invocation. Must be JSON-serializable
            (so tuples survive as lists across the params boundary — see
            `to_dict()` / `from_dict()`).
        requests_per_burst: Concurrent invocations per burst. Read-only calls
            typically default to 10000 (matches the original script). Single-
            shot disruptive calls like rapid-flap should set this to 1 because
            the method internally iterates `total_flaps` times.
    """

    method: str
    args: t.Tuple[t.Any, ...] = ()
    requests_per_burst: int = 10000

    def to_dict(self) -> t.Dict[str, t.Any]:
        """JSON-safe dict form. Nested tuples are recursively converted to lists
        so the contract holds whether or not the dict subsequently round-trips
        through `json.dumps` (which would do the same flattening)."""
        return {
            "method": self.method,
            "args": _tuples_to_lists(self.args),
            "requests_per_burst": self.requests_per_burst,
        }

    @classmethod
    def from_dict(cls, d: t.Dict[str, t.Any]) -> "ThriftStressCall":
        """Rebuild from the JSON-safe dict form."""
        return cls(
            method=d["method"],
            args=tuple(d.get("args", ())),
            requests_per_burst=int(d.get("requests_per_burst", 10000)),
        )


# =============================================================================
# Universal FBOSS read-only baseline
# Used as-is by every NPI THFT testconfig that doesn't need platform-specific
# disruptive calls. All 7 APIs are present on every FBOSS driver regardless of
# silicon (TH4/TH5/TH6/Janga/Tahan).
# =============================================================================

READ_ONLY_FBOSS_APIS: t.List[ThriftStressCall] = [
    ThriftStressCall("async_get_fib_table_entries_count"),
    ThriftStressCall("async_get_all_interfaces"),
    ThriftStressCall("get_sai_hw_objects"),
    ThriftStressCall("get_route_table_details_count"),
    ThriftStressCall("get_bgp_table_length"),
    ThriftStressCall("get_bgp_sessions_count"),
    # Note: Pavan's script referenced `async_get_qsfp_info_map`, which does not
    # exist on TAAC's FbossSwitch. The real method is `_get_qsfp_info_map`
    # (underscore prefix), used by `OpticsTemperatureTask` and verified on
    # `gtsw001.l1001.c085.ash6` via `scripts/probe_thrift_stress_apis.py`.
    ThriftStressCall("_get_qsfp_info_map"),
]


# =============================================================================
# Disruptive variant — universal across FBOSS platforms. Caller passes the
# DUT-specific interface list (e.g. STSW-adjacent uplinks when DUT is a GTSW,
# GTSW-adjacent uplinks when DUT is an STSW, etc.).
#
# Mirrors the `THRIFT_REQUEST_API_COUNTS` flap entry in
# `scripts/pavanpatil/thrift_call_disruptive.py`, routed through TAAC's
# `async_do_rapid_interface_flaps` driver method (qsfp-service-driven via
# `wedge_qsfp_util -tx_disable/-tx_enable`, defined at
# `taac/driver/fboss_switch.py:2509`).
# =============================================================================


def fboss_qsfp_flaps_only(
    interfaces: t.Sequence[str],
    interval_to_link_up: int = 4,
    total_flaps: int = 100,
) -> t.List[ThriftStressCall]:
    """The qsfp-flap entry, with NO read-only thrift baseline attached.

    Runs as its OWN `PeriodicTask`, separate from the thrift storm. There used
    to be a combined `fboss_with_qsfp_flaps` builder that returned
    `READ_ONLY_FBOSS_APIS + this`; it was removed because putting both in one
    `asyncio.gather` means one burst timeout has to cover two workloads whose
    runtimes differ by two orders of magnitude:

      - the read-only calls are capped by the agent's
        `thriftApiToRateLimitInQps` (1-2 qps for most APIs), so excess is
        rejected in microseconds and a burst finishes in seconds;
      - the flap needs `total_flaps` x (interval_to_link_up +
        wedge_qsfp_util runtime), measured at ~7.2s per flap on Kodiak3 =
        ~720s for the default 100.

    Sized for the thrift calls, every burst was cancelled mid-flap-loop —
    the storm never completed a cycle and only ~15 of 100 flaps landed, while
    every postcheck still passed (a silent false green). Sized for the flap,
    the thrift cadence collapses to one burst per ~12 min. Two tasks, two
    timeouts, two independent processes is the only shape that works, so the
    combined builder is deliberately gone rather than left as a footgun.

    Args:
        interfaces: DUT-side ports to flap. EXCLUDE ports carrying test IXIA
            traffic — flapping those breaks the IxiaPacketLossCheck postcheck.
        interval_to_link_up: Sleep inside the flap method between consecutive
            flap iterations. Default 4 matches Pavan's original.
        total_flaps: Flap iterations executed by ONE driver call. Default 100
            matches Pavan's original.
    """
    return [
        ThriftStressCall(
            method="async_do_rapid_interface_flaps",
            args=(tuple(interfaces), interval_to_link_up, total_flaps),
            requests_per_burst=1,
        ),
    ]


# =============================================================================
# Named catalog (string-keyed lookup; optional convenience layer).
# Lambdas accept **kwargs and ignore unknown keys so the same call site can
# pass `interfaces=[...]` for variants that don't use them.
# =============================================================================

PAYLOAD_BUILDERS: t.Dict[str, t.Callable[..., t.List[ThriftStressCall]]] = {
    "fboss_readonly": lambda **_: list(READ_ONLY_FBOSS_APIS),
    "fboss_qsfp_flaps_only": fboss_qsfp_flaps_only,
}
