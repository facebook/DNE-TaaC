# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""Routing testconfig helper package.

Intentionally side-effect free.

This ``__init__`` previously force-imported every sibling helper module
(``bgp_dc_healthchecks``, ``bgp_dc_tc_checks``, ``bgp_ebb_*``, ...) so that a
bare ``import ...testconfigs.routing.util`` would reach all of them. That made
the package import order-sensitive and created a load-time cycle in any build
that actually executes this file::

    playbooks.playbook_definitions    (imports bgp_dc_healthchecks near the top)
      -> testconfigs.routing.util     (this __init__)
        -> bgp_dc_tc_checks           (force-imported here)
          -> playbooks.playbook_definitions  <- partially initialized -> ImportError

The cycle stayed invisible in the internal Buck build because Buck substitutes
an empty ``__init__.py`` for the package, so the force-import block never ran.
The OSS export ships this file verbatim, so the cycle fired there and broke
``taac.runner.oss_entry_point``. Keeping this module import-free removes the
whole class of failure rather than reordering a single edge — mirroring the fix
already applied one level up in ``testconfigs/routing/__init__.py``.

Consumers import the specific helper module they need, e.g.::

    from taac.testconfigs.routing.util.bgp_ebb_constants import (
        SOME_CONSTANT,
    )
"""
