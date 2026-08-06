"""Config-time topology descriptor passed from the entry point to test configs.

The entry point builds a ConfigTopology from the circuit CSV (and
potentially other sources in the future) and passes it to callable
test configs so they don't need to import topology loaders directly.

This is distinct from ``TestTopology`` (taac/constants.py), which is
the full runtime topology built by OssTestBedChunker during
async_test_setUp — that structure carries SwitchAttributes,
TestInterface objects with neighbor info, etc.  ConfigTopology is a
lighter pre-config extraction: just enough for a config factory to
know what devices and ports exist so it can populate endpoints and
step parameters without hardcoding.
"""

from __future__ import annotations

import enum
import typing as t
from dataclasses import dataclass


class LinkType(enum.Enum):
    DUT = "dut"
    TGEN = "tgen"
    SNAKE = "snake"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class CircuitLink:
    local_host: str
    local_port: str
    remote_host: str
    remote_port: str
    link_type: LinkType


@dataclass(frozen=True)
class ConfigTopology:
    """Testbed topology extracted from circuit/device CSVs.

    The primary data is ``links`` — a tuple of :class:`CircuitLink`
    objects, each classified by :class:`LinkType`.  Convenience
    properties like ``dut_ports`` filter and reshape links for common
    access patterns.
    """

    links: t.Tuple[CircuitLink, ...] = ()

    @property
    def dut_ports(self) -> t.Dict[str, t.List[str]]:
        result: t.Dict[str, t.List[str]] = {}
        for link in self.links:
            if link.link_type == LinkType.DUT:
                ports = result.setdefault(link.local_host, [])
                if link.local_port not in ports:
                    ports.append(link.local_port)
        for host in result:
            result[host].sort()
        return result


def topology_aware(fn: t.Callable) -> t.Callable:
    """Mark a test config factory as accepting a ``topology`` argument.

    Decorated functions receive a :class:`ConfigTopology` from the
    entry point instead of having to import topology loaders directly.

    Usage in a test config::

        @topology_aware
        def test_config(topology: ConfigTopology) -> TestConfig:
            ...
    """
    fn._accepts_topology = True  # type: ignore[attr-defined]
    return fn
