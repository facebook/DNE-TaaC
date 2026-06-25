# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""Platform-aware DLB (Dynamic Load Balancing) resource sizing constants.

The number of unique ECMP groups a switch can program for DLB ("ARS groups")
is an ASIC hardware property, so the DLB resource-stickiness checks must assert
different expected values per platform. Centralizing those numbers here (rather
than hardcoding them in ``playbook_definitions.py``) lets the same ECMP-resource
playbooks serve multiple platforms — the playbook looks up a profile by ASIC and
the per-platform numbers live in exactly one place.

Empirical DLB cap references:
- Tomahawk3 (Wedge400): max 10 DLB ECMP groups on c085 despite
  ``Tomahawk3Asic.cpp getMaxArsGroups()=16`` with
  ``FLAGS_use_full_dlb_scale=true``. See T267963572.
- Tomahawk5 (Minipack3): max 94 DLB ECMP groups.
"""

from dataclasses import dataclass
from enum import Enum


class DlbAsic(Enum):
    """ASIC families supported by the ECMP-resource DLB playbooks."""

    TOMAHAWK3 = "tomahawk3"  # Wedge400
    TOMAHAWK5 = "tomahawk5"  # Minipack3


@dataclass(frozen=True)
class DlbResourceProfile:
    """Per-ASIC expected values for the DLB resource-stickiness checks.

    Each ``*_counts`` field is the ``expected_counts`` entry passed verbatim to
    ``create_dlb_resource_stickiness_check`` for the matching prefix bucket.
    ``max_dlb_groups`` is the ASIC's DLB ECMP-group ceiling, asserted as
    ``expected_totals["dlb"]``.
    """

    # expected_totals["dlb"] — ASIC DLB ECMP-group ceiling.
    max_dlb_groups: int
    # Steady-state (base / coldboot) expected_counts entries.
    gold_counts: dict
    silver_counts: dict
    # Overcommit (Rouge enabled) silver entry. TH3 asserts a floor
    # (``min_total``) because groups spill once the ASIC cap is hit; TH5 has
    # headroom and asserts the full ``total``.
    overcommit_silver_counts: dict


# Keyed by ASIC. Values preserve the historical per-platform numbers:
# Tomahawk5 keeps the original dlb=94 sizing; Tomahawk3 (Wedge400) uses the
# empirical dlb=10 cap. Add new ASICs here rather than editing the playbook.
DLB_RESOURCE_PROFILES: dict = {
    DlbAsic.TOMAHAWK3: DlbResourceProfile(
        max_dlb_groups=10,
        gold_counts={"total": 110, "max_next_hops": 64},
        silver_counts={"total": 1380, "max_next_hops": 25},
        overcommit_silver_counts={"min_total": 10, "max_next_hops": 25},
    ),
    DlbAsic.TOMAHAWK5: DlbResourceProfile(
        max_dlb_groups=94,
        gold_counts={"total": 110},
        silver_counts={"total": 1380},
        overcommit_silver_counts={"total": 1380, "max_next_hops": 25},
    ),
}
