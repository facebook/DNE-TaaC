# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""Routing Playbook package discovery hook.

Force-import domain modules and subpackages so construction-gate tests reach
every routing ``Playbook(...)`` site. Consumers import the owning module or
subpackage directly; this initializer is not a root-level symbol facade.
"""

import os

TAAC_OSS = os.environ.get("TAAC_OSS", "").lower() in ("1", "true", "yes")

from taac.playbooks.routing import factories  # noqa: F401

if not TAAC_OSS:
    from taac.playbooks.routing import bgp_ebb_playbooks  # noqa: F401
