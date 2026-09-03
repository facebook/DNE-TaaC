# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""RBB SRv6 qualification lifecycle bindings.

Concrete ``TestConfig`` constants selected by
``netcastle_taac --test-config <NAME>``. TC1 exercises the full head→mid→tail
3-uSID SRv6 chain with the TE_AGENT direct-route install/verify/delete
lifecycle; TC2 is the TE baseline (tail via BGPD throughout).

Lab binding (R1/R2 hostnames, IXIA chassis) and SSH credentials come from
``TAAC_RBB_*`` / ``TAAC_SSH_*`` environment variables — nothing hardcoded here.
"""

from taac.test_as_a_config.types import TestConfig
from taac.testconfigs.routing.factories.qual_rbb.rbb_srv6_test_config import (
    create_rbb_srv6_3_usids_test_config,
    create_rbb_srv6_te_baseline_test_config,
)

# ─── TC1 — SRv6 3-uSID chain + TE_AGENT direct-route lifecycle ────────────
RBB_SRV6_3_USIDS_TEST_CONFIG: TestConfig = create_rbb_srv6_3_usids_test_config()

# ─── TC2 — SRv6 TE baseline (BGPD-owned tail throughout) ──────────────────
RBB_SRV6_TE_BASELINE_TEST_CONFIG: TestConfig = create_rbb_srv6_te_baseline_test_config()

__all__ = [
    "RBB_SRV6_3_USIDS_TEST_CONFIG",
    "RBB_SRV6_TE_BASELINE_TEST_CONFIG",
]
