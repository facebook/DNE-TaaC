# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe
"""
Open/R Scale Testing — TAAC TestConfigs
========================================

This package contains TAAC TestConfig factories, lifecycle binding modules,
and supporting utilities for Open/R scale testing in the DNE PIT lab.

These TestConfigs automate what were previously manual processes: driving a
port-channel sub-interface plan or the scale_test_server injector against a DUT
and asserting the resulting Open/R state against baselines — producing a
deterministic pass/fail result suitable for CI/CD gating.

Test Cases
----------
- Test 1 (OPENR_PORTCHANNEL_SUBIF_SCALE_TEST_CONFIG): create N dot1q routed
  sub-interfaces on the port-channel between DUT and helper and verify Open/R
  establishes an adjacency on each. N defaults to 1024 (2x the 512 adjacencies
  a leaf must support); the dot1q ceiling is 4094.
- Test 2 (OPENR_SCALE_KVSTORE_INJECTION_TEST_CONFIG): run the pre-staged
  scale_test_server on the helper to inject a synthetic BBF fabric into the
  DUT's KvStore, and assert the DUT holds the full injected key population.

Both tests must run with ``--skip-testbed-isolation``: they depend on the
pre-existing Port-Channel1910 interconnect, which testbed isolation shuts.

Lab Environment
---------------
- DUT: Jericho2-based chassis (EOS 4.36)
- Helper / peer: Second EB-class device
- Results: Published to internal Scuba dataset

References
----------
- Requirements & Design: https://docs.google.com/document/d/1F1pkyhYx2sVxJxADitWBZVVpRIs-LoYFM87zkeHYb_8/edit?usp=sharing
"""

from taac.testconfigs.routing.openr.openr_portchannel_subif_test_config import (
    OPENR_PORTCHANNEL_SUBIF_SCALE_TEST_CONFIG,
)

__all__ = [
    "OPENR_PORTCHANNEL_SUBIF_SCALE_TEST_CONFIG",
]
