"""OSS single-DUT 1-RSW test config — statically-defined topology.

Entry point for single-DUT RSW tests (one DUT acting as a rack switch,
peering eBGP with IXIA-emulated neighbors) — the RSW analogue of
``snake_config.py``. All the Meta-conveyor-factory adaptation (IXIA BGP
block on both ports, cross-port loss probe, per-playbook health-check
tuning, and the playbook bundle) lives in the shared generator
``taac.testconfigs.single_dut_rsw.gen_rsw_test_config``; every
device-specific value comes from a constants module — by default
``taac.testconfigs.single_dut_rsw.rsw_constants``, overridable at runtime
with ``TAAC_RSW_CONSTANTS_PATH=/path/to/other_constants.py`` so
retargeting the suite needs no repo edit.

This follows the statically-defined-topology pattern
(``taac/testconfigs/npi/wedge800_npi_test_config.py`` +
``w800_constants.py``): the ``TestConfig`` is a module-level constant
built at import time — no ``@topology_aware`` injection, and no
``device_info.csv`` / ``circuit_info.csv`` needed at runtime, so
``--device-info-csv`` / ``--circuit-info-csv`` can be omitted from the
invocation. The entry point discovers the ``TEST_CONFIG`` attribute
directly.

Both IXIA ports carry 4 BGP peers each (downlink 2001:db8:3::, uplink
2001:db8:4::) with the loss probe forwarding cross-port between them; the
DUT-side agent.conf/bgpd.conf must be pre-provisioned to match; see the
BGP / IXIA peering parameters documented in
``single_dut_rsw_test_config.py``.

Live runs need ``--ixia-api-server``. Keep ``--skip-setup-tasks`` /
``--skip-teardown-tasks`` — the factory's setup/teardown tasks include a
Meta-internal coop-patcher API absent on OSS FBOSS.
"""

import importlib.util
import os

from taac.test_as_a_config import types as taac_types
from taac.testconfigs.single_dut_rsw import gen_rsw_test_config

# Constants module resolution: default to the in-repo rsw_constants.py, but
# allow a different testbed's constants file to be supplied at runtime via
# TAAC_RSW_CONSTANTS_PATH (same convention as the topology loader's
# TAAC_DEVICE_INFO_PATH / TAAC_CIRCUIT_INFO_PATH) — so retargeting the suite
# doesn't require editing the repo.
_CONSTANTS_PATH_ENV = "TAAC_RSW_CONSTANTS_PATH"

# Every name the constants module must define (the contract this config
# builds against). Validated up front so a partial override file fails with
# an actionable message instead of an AttributeError mid-construction.
_REQUIRED_CONSTANTS = [
    "RSW_DEVICE_NAME",
    "RSW_LOCAL_MAC_ADDRESS",
    "RSW_IXIA_CHASSIS",
    "RSW_IXIA_DOWNLINK_INTERFACE",
    "RSW_IXIA_DOWNLINK_PORT",
    "RSW_IXIA_UPLINK_INTERFACE",
    "RSW_IXIA_UPLINK_PORT",
    "RSW_CPU_PUNT_MIN_PPS_OVERRIDES",
]


def _load_constants():
    path = os.environ.get(_CONSTANTS_PATH_ENV)
    if not path:
        from taac.testconfigs.single_dut_rsw import rsw_constants

        return rsw_constants
    spec = importlib.util.spec_from_file_location("rsw_constants_override", path)
    if spec is None or spec.loader is None:
        raise ValueError(
            f"{_CONSTANTS_PATH_ENV}={path!r} is not a loadable Python file"
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    missing = [n for n in _REQUIRED_CONSTANTS if not hasattr(module, n)]
    if missing:
        raise ValueError(
            f"Constants file {path!r} ({_CONSTANTS_PATH_ENV}) is missing "
            f"required names: {missing}. See "
            f"taac/testconfigs/single_dut_rsw/rsw_constants.py for the "
            f"reference definition of each."
        )
    return module


rsw = _load_constants()

_IXIA_CONNECTIONS = [
    taac_types.DirectIxiaConnection(
        interface=rsw.RSW_IXIA_DOWNLINK_INTERFACE,
        ixia_port=rsw.RSW_IXIA_DOWNLINK_PORT,
        ixia_chassis_ip=rsw.RSW_IXIA_CHASSIS,
    ),
    taac_types.DirectIxiaConnection(
        interface=rsw.RSW_IXIA_UPLINK_INTERFACE,
        ixia_port=rsw.RSW_IXIA_UPLINK_PORT,
        ixia_chassis_ip=rsw.RSW_IXIA_CHASSIS,
    ),
]

TEST_CONFIG = gen_rsw_test_config(
    name="OSS_SINGLE_DUT_RSW",
    dut_name=rsw.RSW_DEVICE_NAME,
    # TAAC_DUT_MAC stays as the one runtime override (e.g. after a DUT swap,
    # before the constants file catches up): the CPU-punt RAW traffic items
    # target the DUT via DST_MAC_ADDRESS references, so a MAC is required.
    local_mac_address=os.environ.get("TAAC_DUT_MAC")
    or rsw.RSW_LOCAL_MAC_ADDRESS,
    ixia_downlink_interface=rsw.RSW_IXIA_DOWNLINK_INTERFACE,
    ixia_uplink_interface=rsw.RSW_IXIA_UPLINK_INTERFACE,
    ixia_connections=_IXIA_CONNECTIONS,
    cpu_punt_min_pps_overrides=rsw.RSW_CPU_PUNT_MIN_PPS_OVERRIDES,
    basset_pool="",
)
