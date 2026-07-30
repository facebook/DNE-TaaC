# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""Routing Playbook package discovery hook.

Force-import domain modules and subpackages so construction-gate tests reach
every routing ``Playbook(...)`` site. Consumers import the owning module or
subpackage directly; this initializer is not a root-level symbol facade.
"""

from taac.playbooks.routing import (  # noqa: F401
    bgp_ebb_playbooks,
    factories,
)
