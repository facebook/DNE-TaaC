# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""Routing testconfig factories package.

Each ``<domain>.py`` file (or ``<domain>/`` subpackage) exposes
``create_<domain>_<workflow>_test_config`` factories consumed by lifecycle
binding modules in the parent package. Force-import domain modules so downstream
``import ...testconfigs.routing.factories`` reaches every factory (parallels
the sibling ``playbooks/routing/__init__.py`` pattern).

See ``fbcode/neteng/test_infra/routing_qualification/docs/taac/TESTCONFIGS.md``
for the factory contract.
"""

import importlib as _importlib
import logging as _logging

_logger = _logging.getLogger(__name__)

# Force-imported domain modules. Kept as names rather than a plain
# ``from . import a, b, c`` so a module whose dependencies are not shipped to
# OSS can be skipped individually instead of taking the whole package down.
# Import roots that exist only inside Meta and are never shipped to OSS. A
# factory that needs one of these is skipped rather than taking the whole
# package down; anything else is a real error and still raises. Kept as an
# explicit list -- catching every ModuleNotFoundError would hide genuine typos
# and missing OSS dependencies.
_META_ONLY_ROOTS: tuple = (
    "taac.abstractions",
    "neteng",
)

_FACTORY_MODULES = (
    "bgp_dc_chronos_node",
    "bgp_ebb_characteristic",
    "bgp_ebb_full_scale",
    "bgp_ebb_full_scale_mimic",
    "bgp_features",
    "cte_ucmp",
    "qual_bgp_update_group",
)

for _name in _FACTORY_MODULES:
    try:
        _importlib.import_module(f"{__name__}.{_name}")
    except ModuleNotFoundError as _e:
        # Six of these factories depend on ``taac.abstractions``, which is
        # Meta-internal and not shipped to OSS. Eagerly importing them made the
        # whole package unimportable under TAAC_OSS, which in turn broke every
        # OSS config that only wanted an OSS-shippable factory out of it — e.g.
        # ``wedge800_npi_test_config`` importing ``bgp_dc_chronos_node`` died
        # with ``No module named 'taac.abstractions'``. Skip just the
        # unavailable module; anything else is a real error and still raises.
        if (_e.name or "").startswith(_META_ONLY_ROOTS):
            _logger.debug(
                "factories: skipping %s — Meta-only dependency %s not available",
                _name,
                _e.name,
            )
            continue
        raise
del _name
