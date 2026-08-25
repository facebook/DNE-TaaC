# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from dataclasses import replace

from taac.abstractions.topologies.bounded_ecmp import BOUNDED_ECMP


PROFILE_FREE_BOUNDED_ECMP = replace(
    BOUNDED_ECMP,
    name="profile_free_bounded_ecmp",
    legacy_profile=None,
    device_groups=tuple(
        replace(
            group,
            ixia_children=tuple(
                replace(
                    child,
                    legacy_ixia_device_group_name=None,
                    legacy_ixia_bgp_peer_name=None,
                    legacy_ixia_device_group_index=None,
                    legacy_ixia_prefix_pool_name=None,
                )
                for child in group.ixia_children
            ),
        )
        for group in BOUNDED_ECMP.device_groups
    ),
)


def _acceptance_group_name(group_name: str) -> str:
    if not group_name.startswith("dg_"):
        raise ValueError(
            f"bounded-ECMP device group name must start with 'dg_': {group_name}"
        )
    return f"dg_acceptance_{group_name.removeprefix('dg_')}"


_VARIANT_GROUP_NAMES = {
    group.name: _acceptance_group_name(group.name)
    for group in PROFILE_FREE_BOUNDED_ECMP.device_groups
}
PROFILE_FREE_BOUNDED_ECMP_VARIANT = replace(
    PROFILE_FREE_BOUNDED_ECMP,
    name="profile_free_bounded_ecmp_variant",
    device_groups=tuple(
        replace(group, name=_VARIANT_GROUP_NAMES[group.name])
        for group in PROFILE_FREE_BOUNDED_ECMP.device_groups
    ),
    route_senders=tuple(
        replace(
            sender,
            device_group=_VARIANT_GROUP_NAMES[sender.device_group],
        )
        for sender in PROFILE_FREE_BOUNDED_ECMP.route_senders
    ),
)


__all__ = (
    "PROFILE_FREE_BOUNDED_ECMP",
    "PROFILE_FREE_BOUNDED_ECMP_VARIANT",
)
