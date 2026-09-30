# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""Playbook factories package (per-qualification-project subpackages).

Each subpackage under this directory groups playbook factories by
qualification project (matching the sibling ``testconfigs/routing/factories/``
subpackage layout).

Force-import the subpackages so downstream force-import via
``import neteng.test_infra.dne.taac.playbooks.routing`` reaches every
playbook factory and their ``Playbook(...)`` construction sites get
registered by ``tests/test_no_inline_playbook_construction.py``.
"""

import os

TAAC_OSS = os.environ.get("TAAC_OSS", "").lower() in ("1", "true", "yes")

if TAAC_OSS:
    from taac.playbooks.routing.factories import qual_rbb  # noqa: F401
else:
    from taac.playbooks.routing.factories import (  # noqa: F401
        qual_bgp_update_group,
    )
