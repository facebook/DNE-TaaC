# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import sys
import typing as t

from taac.health_checks.constants import COMPARISON_OPERATORS
from neteng.test_infra.dne.taac.utils.common import async_everpaste_str, async_get_fburl
from taac.health_check.health_check import types as hc_types


def evaluate_comparison(
    val1: float,
    comparison_type: hc_types.ComparisonType,
    val2: t.Union[str, float],
    lower_bound_str: t.Optional[str] = None,
    upper_bound_str: t.Optional[str] = None,
) -> bool:
    if comparison_type == hc_types.ComparisonType.BETWEEN:
        lower_bound = float(lower_bound_str) if lower_bound_str else 0
        upper_bound = float(upper_bound_str) if upper_bound_str else sys.maxsize
        # pyrefly: ignore [bad-argument-count]
        return COMPARISON_OPERATORS[comparison_type](val1, lower_bound, upper_bound)
    # pyrefly: ignore [missing-argument]
    return COMPARISON_OPERATORS[comparison_type](val1, float(val2))


async def async_get_everpaste_fburl_if_needed(
    str_val: t.Optional[str],
    min_chars: int = 1000,
    max_chars: int = 10_000,
    shorten_fburl: bool = False,
) -> t.Optional[str]:
    """Return ``str_val`` as-is when short; otherwise upload it to Everpaste and
    return a clickable link.

    - ``min_chars``: messages at or below this are returned unchanged (no
      network call). Bumped from 100 to 1000 to avoid hitting the everpaste
      service for routine health-check messages that are already
      human-readable inline.
    - ``max_chars``: if the message is larger than this, truncate before
      uploading. Prevents pathologically large messages (giant tracebacks,
      multi-MB payloads) from punishing the upload service.
    - ``shorten_fburl``: when ``True``, additionally shorten the (already
      clickable) Everpaste URL through the ``fburl`` tier. Defaults to ``False``
      so the common path never touches the globally throttled ``fburl`` tier —
      an Everpaste URL is itself a clickable internalfb.com link. Callers should
      set this only for failure-class results where the shortest possible link
      aids triage.
    """
    if not str_val:
        return None
    if len(str_val) <= min_chars:
        return str_val
    truncated = (
        str_val
        if len(str_val) <= max_chars
        else str_val[:max_chars] + " ...[truncated]"
    )
    everpaste_url = await async_everpaste_str(truncated)
    if shorten_fburl:
        return await async_get_fburl(everpaste_url)
    return everpaste_url
