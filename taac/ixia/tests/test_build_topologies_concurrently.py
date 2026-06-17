# pyre-unsafe — extensive MagicMock substitution for the IxNetwork REST
# objects (Vport, Topology, DeviceGroup, Multivalue) used by the helper
# under test; pyre cannot resolve attribute types through these mocks and
# strict mode would require per-line ignores on nearly every assertion.
# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""Unit tests for `_build_topologies_and_device_groups_concurrently`."""

import threading
import unittest
from unittest.mock import MagicMock, patch

from taac.ixia.ixia import Ixia


def _make_port_config(port_name: str, has_l1_config: bool = False):
    port = MagicMock()
    port.port_name = port_name
    port.device_group_configs = [MagicMock()]
    port.l1_config = MagicMock() if has_l1_config else None
    return port


def _make_vport_index():
    idx = MagicMock()
    idx.topology_name = None
    return idx


def _create_ixia_instance():
    with patch.object(Ixia, "__init__", lambda self: None):
        ixia = Ixia()
    ixia.logger = MagicMock()
    ixia.ixnetwork = MagicMock()
    ixia.vport_indices = {}
    # Mocks for the per-port worker's calls
    ixia.create_topology = MagicMock(return_value=MagicMock(Name="TOPOLOGY_MOCK"))
    ixia.create_device_groups = MagicMock()
    ixia.configure_l1_settings = MagicMock()
    return ixia


class BuildTopologiesConcurrentlyTest(unittest.TestCase):
    """Tests for the parallel Step 3 helper.

    Behavioural contract:
      * every port's `create_topology` + `create_device_groups` is invoked once
      * `vport_indices[port_id].topology_name` is set per port
      * `l1_config` honored only when present
      * exception in one port → that port retried sequentially → still raises
        if retry also fails
      * cross-port-name uniqueness preserved under parallelism (no lost writes)
    """

    def setUp(self):
        self.ixia = _create_ixia_instance()
        # Pre-populate vport_indices entries — production assign_ports() does this
        for i in range(8):
            self.ixia.vport_indices[f"PORT_{i}"] = _make_vport_index()

    def test_all_ports_built_once(self):
        ports = [_make_port_config(f"PORT_{i}") for i in range(8)]
        self.ixia._build_topologies_and_device_groups_concurrently(
            ports, _log=MagicMock()
        )
        self.assertEqual(self.ixia.create_topology.call_count, 8)
        self.assertEqual(self.ixia.create_device_groups.call_count, 8)
        # Every port's topology_name got set
        for i in range(8):
            self.assertEqual(
                self.ixia.vport_indices[f"PORT_{i}"].topology_name,
                "TOPOLOGY_MOCK",
            )

    def test_l1_config_invoked_only_when_present(self):
        ports = [
            _make_port_config("PORT_0", has_l1_config=True),
            _make_port_config("PORT_1", has_l1_config=False),
            _make_port_config("PORT_2", has_l1_config=True),
        ]
        self.ixia._build_topologies_and_device_groups_concurrently(
            ports, _log=MagicMock()
        )
        self.assertEqual(self.ixia.configure_l1_settings.call_count, 2)

    def test_single_port_failure_raises_no_retry(self):
        """Single-attempt parallel: a port failure raises immediately.

        Retry was deliberately removed because `create_device_groups` is
        non-idempotent — retrying after a partial failure would produce
        duplicate DGs / duplicate tag-list entries. Let the outer
        `create_basic_setup` wrapper tear down the whole session.
        """
        ports = [_make_port_config(f"PORT_{i}") for i in range(4)]
        attempts = {p.port_name: 0 for p in ports}
        lock = threading.Lock()

        def _maybe_fail(port_id, dg_configs, topology):
            with lock:
                attempts[port_id] += 1
                if port_id == "PORT_2":
                    raise RuntimeError("transient REST blip")

        self.ixia.create_device_groups.side_effect = _maybe_fail

        with self.assertRaises(RuntimeError) as cm:
            self.ixia._build_topologies_and_device_groups_concurrently(
                ports, _log=MagicMock()
            )
        self.assertIn("Parallel topology setup failed for 1 port(s)", str(cm.exception))
        # PORT_2 attempted exactly once (no retry); other ports attempted once
        # each, but whether they completed depends on race timing — only PORT_2
        # is guaranteed to have attempted.
        self.assertEqual(attempts["PORT_2"], 1)

    def test_persistent_port_failure_raises_runtime_error(self):
        ports = [_make_port_config(f"PORT_{i}") for i in range(3)]

        def _always_fail_port_1(port_id, dg_configs, topology):
            if port_id == "PORT_1":
                raise RuntimeError("permanent failure")

        self.ixia.create_device_groups.side_effect = _always_fail_port_1
        with self.assertRaises(RuntimeError) as cm:
            self.ixia._build_topologies_and_device_groups_concurrently(
                ports, _log=MagicMock()
            )
        # New error message — no retry semantics
        self.assertIn("Parallel topology setup failed", str(cm.exception))

    def test_concurrent_vport_indices_writes_no_lost_updates(self):
        """8 ports, each writes to its own vport_indices key concurrently.

        Without the lock, this would be vulnerable to dict-resize races
        (CPython mostly handles them, but custom subclasses might not).
        Verifies that all 8 writes land.
        """
        ports = [_make_port_config(f"PORT_{i}") for i in range(8)]
        self.ixia._build_topologies_and_device_groups_concurrently(
            ports, _log=MagicMock()
        )
        for i in range(8):
            self.assertEqual(
                self.ixia.vport_indices[f"PORT_{i}"].topology_name,
                "TOPOLOGY_MOCK",
            )

    def test_lazy_lock_init_does_not_overwrite_existing(self):
        """Calling the helper twice keeps the same lock instance (lazy init)."""
        ports = [_make_port_config(f"PORT_{i}") for i in range(2)]
        self.ixia._build_topologies_and_device_groups_concurrently(
            ports, _log=MagicMock()
        )
        first_lock = self.ixia._vport_indices_lock
        self.ixia._build_topologies_and_device_groups_concurrently(
            ports, _log=MagicMock()
        )
        self.assertIs(self.ixia._vport_indices_lock, first_lock)
