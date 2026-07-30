# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""Routing testconfig factories package.

Each ``<domain>.py`` file (or ``<domain>/`` subpackage) exposes
``create_<domain>_<workflow>_test_config`` factories consumed by lifecycle
binding modules in the parent package. Force-import domain modules so downstream
``import ...testconfigs.routing.factories`` reaches every factory (parallels
the sibling ``playbooks/routing/__init__.py`` pattern).

See ``../../../docs/routing/TESTCONFIGS.md`` for the factory contract.
"""

from taac.testconfigs.routing.factories import (  # noqa: F401
    bgp_dc_chronos_node,
    bgp_ebb_characteristic,
    bgp_ebb_full_scale,
    bgp_ebb_full_scale_mimic,
    bgp_features,
    cte_ucmp,
    qual_bgp_update_group,
)
