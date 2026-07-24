# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""Per-role DUT-config helpers (peer_groups, route_maps, communities).

PhysicalInventory instances in ``physical_inventory.py`` call these helpers to populate
their role-keyed dicts. Factory code does NOT branch on DUT role —
it just reads standard role keys (uplink_v6, downlink_v6, ibgp_v6,
ebgp_v6, ...) from the PhysicalInventory dicts.

See ``README.md`` §2 "DUT roles and role-defaults helpers".
"""


def ebb_peer_groups() -> dict[str, str]:
    """Standard EBB BGPCPP peer-group names (bag*, eb0N.lab, jsw002, fsw*).

    Values match ``testconfigs/routing/util/bgp_ebb_constants.py``
    (``PEERGROUP_IBGP_V6/V4``, ``PEERGROUP_EBGP_V6/V4``).
    """
    return {
        "ibgp_v6": "EB-EB-V6",
        "ebgp_v6": "EB-FA-V6",
        "ibgp_v4": "EB-EB-V4",
        "ebgp_v4": "EB-FA-V4",
    }
