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


# =============================================================================
# ECMP-ONLY (non-DLB) platform sizing.
#
# For ASICs that have NO DLB (e.g. Kodiak-3 / G200), the resource playbooks
# stress the plain ECMP group/member tables instead. The sizing law (validated
# on Wedge400/TH3, assuming sum-of-widths member accounting) is:
#     total members consumed = network_group_multiplier
#     groups programmed      = network_group_multiplier / ecmp_width
# So both profiles advertise all `max_ecmp_members` members; width selects
# whether you fill the GROUP table (narrow) or the MEMBER table (wide).
# =============================================================================
class EcmpAsic(Enum):
    """ASIC families supported by the ECMP-only (non-DLB) resource playbooks.

    Membership here means "the ECMP-only playbooks can target this ASIC", NOT
    "this ASIC lacks DLB". Tomahawk4 does support DLB/ARS
    (``Tomahawk4Asic.cpp`` advertises ``Feature::ARS``); running it through the
    ECMP-only suite deliberately exercises the plain ECMP group/member tables
    and leaves DLB to the 3-port Wedge400/IcePack configs.
    """

    G200 = "g200"  # Kodiak-3 (KO3) — ECMP only, no DLB
    TOMAHAWK4 = "tomahawk4"  # Elbert / Minipack2 — has DLB, tested ECMP-only here


@dataclass(frozen=True)
class EcmpResourceProfile:
    """Per-ASIC ECMP table limits + expected resource-stickiness values.

    The ``*_counts`` dicts are passed verbatim as the ``expected_counts`` entry
    to ``create_dlb_resource_stickiness_check`` for the Main prefix bucket. For
    ECMP-only platforms we assert ``total`` (group count) + ``max_next_hops``
    (width) — never the ``dlb``/``other_modes`` split.
    """

    # ECMP table limits the test targets. These are the ResourceAccountant
    # ENFORCED ceilings, i.e. the raw silicon limits already multiplied by
    # FLAGS_ecmp_resource_percentage (75, see fboss/agent/AgentFeatures.cpp).
    # ResourceAccountant::checkEcmpResource applies that derate to BOTH
    # getMaxEcmpGroups() and getMaxEcmpMembers() for the final state, so a CSV
    # sized to the raw limit would be rejected and the in-budget "Main" traffic
    # would lose by design. Store the derated number here.
    max_ecmp_groups: int
    max_ecmp_members: int
    max_group_width: int
    # Device-wide UNIQUE next-hop budget. The CSV generator draws every group's
    # next-hop subset from `range(max_unique_next_hops)`, so the union of unique
    # NHs across all groups stays within this cap regardless of width/group count
    # (the sliding-window CustomNetworkGroupConfig approach could not respect it).
    max_unique_next_hops: int
    # Main (in-budget) class. Both profiles advertise all `max_ecmp_members`
    # member entries; `*_width` selects whether they fill the GROUP table
    # (narrow -> more groups) or the MEMBER table (wide -> fewer groups):
    #   - GROUP-util:  max_ecmp_members @ group_util_width  (e.g. 13,629 @ ~17-18
    #                  -> 768 groups; fills the GROUP table)
    #   - MEMBER-util: max_ecmp_members @ member_util_width (e.g. 13,629 @ 128
    #                  -> 106 full groups + a 107th partial group; fills the
    #                  MEMBER table)
    # The MEMBER-util playbooks switch width at runtime via
    # `modify_network_group_ecmp_width(...)`.
    group_util_width: int
    group_util_counts: dict
    member_util_width: int
    member_util_counts: dict
    # Rouge (overflow) class — sized so Main + Rouge exceed the ECMP limits in
    # the overcommit playbooks (routes rejected -> 100% loss on Rouge traffic).
    rouge_network_group_multiplier: int
    rouge_ecmp_width: int
    # NDP-supporting next-hop pool size (IXIA-side NDP responders). Must cover
    # every unique NH the CSV advertises, i.e. >= max_unique_next_hops (the
    # anchor-pair CSV draws NHs only from range(max_unique_next_hops)).
    ndp_pool_multiplier: int


# Keyed by ASIC. Add new ECMP-only ASICs here rather than hardcoding numbers in
# the testconfig/playbooks. Counts are SIZING TARGETS — re-tune after the first
# hardware run for the platform.
ECMP_RESOURCE_PROFILES: dict = {
    # Kodiak-3 / G200: 768 groups, 13,629 members, 128 max width, 500 unique NHs.
    #   GROUP-util:  13,629 members @ width ~17-18 -> 768 groups (fills the GROUP table).
    #   MEMBER-util: 13,629 members @ width 128    -> 106 full groups @128 + 1
    #                partial @61 = 107 groups (fills the MEMBER table).
    EcmpAsic.G200: EcmpResourceProfile(
        max_ecmp_groups=768,
        max_ecmp_members=13629,
        max_group_width=128,
        max_unique_next_hops=500,
        group_util_width=17,
        group_util_counts={"total": 768, "max_next_hops": 18},
        member_util_width=128,
        member_util_counts={"total": 107, "max_next_hops": 128},
        rouge_network_group_multiplier=8160,
        rouge_ecmp_width=17,
        ndp_pool_multiplier=500,
    ),
    # Tomahawk4 / Elbert (Minipack2). Raw silicon (Tomahawk4Asic.h): 2048
    # groups, 56,000 members, getMaxWideEcmpSize()=128. Derated by the 75%
    # ecmp_resource_percentage -> 1536 groups / 42,000 members.
    #   GROUP-util:  42,000 members @ width 27 -> 528x28 + 1008x27 = 1536 groups.
    #   MEMBER-util: 42,000 members @ width 128 -> 328x128 + 1x16 = 329 groups.
    # max_unique_next_hops=512 (also TH4's getMaxVariableWidthEcmpSize) rather
    # than 500: gen_ecmp_csv's _BODY_STRIDE=37 divides (500-56)=444, which
    # collapses the body window to 12 offsets and touches only 368 unique NHs.
    # 512 leaves a body range of 456, coprime with 37, so all 512 get used.
    EcmpAsic.TOMAHAWK4: EcmpResourceProfile(
        max_ecmp_groups=1536,
        max_ecmp_members=42000,
        max_group_width=128,
        max_unique_next_hops=512,
        group_util_width=27,
        group_util_counts={"total": 1536, "max_next_hops": 28},
        member_util_width=128,
        member_util_counts={"total": 329, "max_next_hops": 128},
        # 900 groups @ width 27. Main + Rouge = 2436 groups / 66,300 members,
        # over both derated ceilings -> Rouge rejected in the overcommit runs.
        rouge_network_group_multiplier=24300,
        rouge_ecmp_width=27,
        ndp_pool_multiplier=512,
    ),
}
