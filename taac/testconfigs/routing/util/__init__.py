# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""Routing testconfig helper package — single re-export point.

Testconfig factories under ``testconfigs/routing/factories/`` and the
routing playbooks import EBB helper symbols (setup tasks, constants,
IXIA port configs, health checks, check profiles, periodic tasks) from
this package's sibling modules.

Force-import the sibling modules so downstream force-import via
``import neteng.test_infra.dne.taac.testconfigs.routing.util`` reaches
every helper module (mirrors the ``playbooks/routing/__init__.py``
pattern).
"""

import os

TAAC_OSS = os.environ.get("TAAC_OSS", "").lower() in ("1", "true", "yes")

# Gated because bgp_dc_tc_checks → playbook_definitions creates a circular
# import when the force-import eagerly loads all submodules.
if not TAAC_OSS:
    from taac.testconfigs.routing.util import (  # noqa: F401
        bgp_dc_healthchecks,
        bgp_dc_stages,
        bgp_dc_tc_checks,
        bgp_ebb_check_profiles,
        bgp_ebb_constants,
        bgp_ebb_health_checks,
        bgp_ebb_ixia_config,
        bgp_ebb_lab_wiring,
        bgp_ebb_periodic_tasks,
        bgp_ebb_setup_tasks,
        bgpcpp_peers_modification,
    )
