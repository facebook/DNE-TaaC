# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict
"""Resolve the thrift port to use when talking to FBOSS services on a device.

FBOSS agent, qsfp_service and fsdb each bind two thrift ports: the legacy one
and a "migrated" one at ``legacy + 50``. Both are served by the same
ThriftServer, so they are interchangeable -- same handler, same TLS, same ACLs.

    fboss/agent/SwAgentInitializer.cpp:256   ports = {5909, 5959}
    fboss/qsfp_service/QsfpServer.cpp:74     ports = {5910, 5960}
    fboss/fsdb/common/Flags.cpp:12           5908 -> 5958

The migrated range exists because 5908-5910 sits inside the well-known VNC
range 5900-5910, which On-Demand hosts drop on egress. Code running on an OD
must therefore dial the migrated port; everywhere else the legacy port is
fine and is what the fleet has always used.

Only ports we open *as a client, to a remote device* belong here. Ports that
get written into on-device config (e.g. Open/R's ``fib_agent_port``) or that
address localhost on the switch itself must keep their legacy value -- the
client's environment says nothing about them.
"""

import os
import platform

# Migrated port == legacy port + 50. Set by FBOSS, see module docstring.
MIGRATED_PORT_OFFSET: int = 50

# Escape hatch: force the offset regardless of where we are running.
#   TAAC_FBOSS_PORT_OFFSET=0    always use the legacy port
#   TAAC_FBOSS_PORT_OFFSET=50   always use the migrated port
PORT_OFFSET_ENV_VAR: str = "TAAC_FBOSS_PORT_OFFSET"


def is_ondemand() -> bool:
    """True when running on an On-Demand host.

    Mirrors ``libfb.py.testutil.is_ondemand()`` rather than importing it, so
    that this module stays free of Meta-internal deps and OSS-safe.
    """
    try:
        return ".od." in platform.node()
    except Exception:
        return False


def fboss_thrift_port(legacy_port: int) -> int:
    """Port to dial for a FBOSS service whose legacy thrift port is ``legacy_port``."""
    override = os.environ.get(PORT_OFFSET_ENV_VAR)
    if override:
        try:
            return legacy_port + int(override)
        except ValueError:
            # A malformed override should not silently pick a random port.
            raise ValueError(
                f"{PORT_OFFSET_ENV_VAR} must be an integer, got {override!r}"
            ) from None
    return legacy_port + MIGRATED_PORT_OFFSET if is_ondemand() else legacy_port
