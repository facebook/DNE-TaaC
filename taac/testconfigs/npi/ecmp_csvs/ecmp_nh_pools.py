# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe

"""IxNetwork next-hop pool definitions for ECMP-only resource testing.

One pool per (platform, device) under test -- see ``KO3_MAIN_ECMP_POOL`` and
``FUJI_SSW_MAIN_ECMP_POOL`` below.

An ``EcmpNhPool`` is the single build-time source of truth that ties together
the prefix/next-hop addressing baked into the generated CSV (via
``gen_ecmp_csv.*_for_pool``) and the IxNetwork NetworkGroup the CSV is later
injected into. It is deliberately independent of the DLB ``NhPool`` in
``dlb_asic_profiles.py`` so this tree carries no DLB deps.

The pool's ``size`` is the device-wide UNIQUE next-hop budget. The generator
draws every group's next-hop subset from ``range(size)``, so the union of unique
NHs across all groups can never exceed it -- which is exactly what the
sliding-window ``CustomNetworkGroupConfig`` approach could not guarantee.

Consistency contract (all must agree or routes blackhole / the mutate step
raises "No NetworkGroup named ..."):
  * ``prefix_base`` / ``nh_network`` / ``nh_host_start`` must match the baseline
    ``CustomNetworkGroupConfig`` (``prefix_start_value`` / ``nexthop_start_value``)
    in the testconfig, and the NDP-supporting device group must cover
    ``nh_network::(nh_host_start .. nh_host_start + size - 1)``.
  * the IxNetwork NetworkGroup name (see ``pool_name`` / the testconfig's
    ``network_group_name``) is the runtime match key for ``apply_pool_mutations``.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class EcmpNhPool:
    """An IxNetwork-side NH range that ECMP route advertisements draw from.

    ``name``          : label, also used as an on-disk CSV sub-path component.
    ``prefix_base``   : IPv6 prefix the advertised routes live in (e.g. ``5000:dd::``).
    ``nh_network``    : /64 the next-hops live in; must be NDP-resolvable from the DUT.
    ``nh_host_start`` : first NH host offset within ``nh_network`` (e.g. ``0xA001``).
    ``size``          : pool size in UNIQUE next-hops -- the device-wide cap.
                        Must equal the profile's ``max_unique_next_hops``
                        (``gen_for_profile_pool`` raises otherwise).
    ``pool_name``     : the IxNetwork NetworkGroup name the CSV mutates in place.
    ``csv_prefix``    : filename stem for the generated CSVs
                        (``f"{csv_prefix}_ecmp_max_groups.csv"``). Deliberately
                        NOT derived from ``name``: the generated path is an
                        ``apply_pool_mutations`` step argument and therefore part
                        of the TestConfig golden hash, so an existing pool's
                        prefix must stay pinned even if ``name`` changes.
    """

    name: str
    prefix_base: str
    nh_network: str
    nh_host_start: int
    size: int
    pool_name: str
    csv_prefix: str


# KO3 Main ECMP pool for rb002-02.qxt1 (rogue port `eth1/64/5`, parent /64
# `2401:db00:206a:1::`). `size=500` is the KO3 unique-NH cap; the NDP-supporting
# device group must advertise at least 500 NHs starting at ::a001. `pool_name`
# matches the baseline `CustomNetworkGroupConfig.network_group_name` on the Main
# device group.
KO3_MAIN_ECMP_POOL: EcmpNhPool = EcmpNhPool(
    name="ko3_main",
    prefix_base="5000:dd::",
    nh_network="2401:db00:206a:1",
    nh_host_start=0xA001,
    size=500,
    pool_name="MAIN_ECMP_PREFIXES",
    csv_prefix="ko3",
)


# Fuji (Tomahawk4) Main ECMP pool for ssw002.s002.f01.qzd1 (rogue port
# `eth9/16/1`, parent /80 `2401:db00:e50d:111:9::`, which the DC-wide
# dne_lab_ixia CoopOverride puts on that port permanently). Fuji and Elbert
# both instantiate Tomahawk4Asic, so they share
# `ECMP_RESOURCE_PROFILES[EcmpAsic.TOMAHAWK4]`; `size=512` matches its
# `max_unique_next_hops` and the NDP-supporting device group must advertise all
# 512 NHs starting at ::a001. `prefix_base` differs from KO3's only to keep the
# two platforms' advertised routes visually distinct in captures.
FUJI_SSW_MAIN_ECMP_POOL: EcmpNhPool = EcmpNhPool(
    name="fuji_ssw_main",
    prefix_base="5001:dd::",
    nh_network="2401:db00:e50d:111:9",
    nh_host_start=0xA001,
    size=512,
    pool_name="MAIN_ECMP_PREFIXES",
    csv_prefix="fuji_ssw",
)
