# pyre-unsafe
# Copyright (c) Meta Platforms, Inc. and affiliates.
"""Unit tests for OTG traffic generator support."""

import asyncio
import collections.abc
import threading
import time
import typing as t
import unittest
from unittest.mock import MagicMock, patch

from taac.ixia.abstract_traffic_generator import (
    AbstractTrafficGenerator,
)
from taac.ixia.otg_traffic_gen import _nonempty_sequence


def _make_ixia_config(port_configs=None, traffic_items=None):
    cfg = MagicMock()
    cfg.port_configs = port_configs or []
    cfg.traffic_items = traffic_items or []
    return cfg


def _make_port_config(
    port_name: str,
    port_location: str = "",
    chassis_ip: str = "otg",
    slot: int = 1,
    port: int = 1,
    device_group_configs=None,
    bgp_config_info=None,
):
    pc = MagicMock()
    pc.port_name = port_name
    pc.port_location = port_location or None
    pc.phy_port_config = MagicMock()
    pc.phy_port_config.chassis_ip = chassis_ip
    pc.phy_port_config.slot_number = slot
    pc.phy_port_config.port_number = port
    pc.device_group_configs = device_group_configs or []
    pc.bgp_config_info = bgp_config_info
    return pc


def _make_device_group_config(
    index: int = 0,
    ipv4_start: t.Optional[str] = "10.0.1.1",
    ipv4_gw: str = "10.0.1.2",
    ipv4_mask: int = 24,
    ipv6_start: t.Optional[str] = None,
    ipv6_gw: t.Optional[str] = None,
    bgp_config=None,
    enable: bool = True,
):
    dg = MagicMock()
    dg.device_group_index = index
    dg.bgp_config = bgp_config
    dg.enable = enable
    ip_cfg = MagicMock()
    if ipv4_start:
        v4 = MagicMock()
        v4.starting_ip = ipv4_start
        v4.gateway_starting_ip = ipv4_gw
        v4.subnet_mask = ipv4_mask
        v4.ip_obj_name = None
        ip_cfg.ipv4_addresses_config = v4
    else:
        ip_cfg.ipv4_addresses_config = None
    if ipv6_start:
        v6 = MagicMock()
        v6.starting_ip = ipv6_start
        v6.gateway_starting_ip = ipv6_gw
        v6.subnet_mask = 64
        v6.ip_obj_name = None
        ip_cfg.ipv6_addresses_config = v6
    else:
        ip_cfg.ipv6_addresses_config = None
    dg.ip_addresses_config = ip_cfg
    return dg


def _create_otg_tgen(**kwargs):
    """Create an OtgTrafficGen with mocked snappi API."""
    from taac.ixia.otg_traffic_gen import OtgTrafficGen

    mock_snappi = MagicMock()
    mock_api = MagicMock()
    mock_config = MagicMock()
    mock_config.ports = MagicMock()
    mock_config.devices = MagicMock()
    mock_config.flows = []
    mock_snappi.api.return_value = mock_api
    mock_api.config.return_value = mock_config

    with patch("taac.ixia.otg_traffic_gen.snappi", mock_snappi):
        # Run the REAL __init__ so instance state cannot drift from it — this
        # helper used to mirror every attribute by hand, and each new one broke
        # every test with AttributeError until the list was updated.
        #
        # Construct against an EMPTY ixia_config so __init__'s _build_config()
        # is a guaranteed no-op, then swap in the caller's config.  Building at
        # construction time would double-build for tests that also call the
        # builders explicitly, which could mask a broken builder.
        tgen = OtgTrafficGen(
            ixia_config=_make_ixia_config(),
            location=kwargs.get("location", "https://localhost:8443"),
            logger=MagicMock(),
        )
        if "ixia_config" in kwargs:
            tgen.ixia_config = kwargs["ixia_config"]
    return tgen


# -- AbstractTrafficGenerator ABC contract ------------------------------------


class TestAbstractTrafficGeneratorABC(unittest.TestCase):
    def test_cannot_instantiate_abc(self):
        with self.assertRaises(TypeError):
            AbstractTrafficGenerator()

    def test_abc_has_required_methods(self):
        expected = {
            "begin_test_case",
            "end_test_case",
            "start_traffic",
            "stop_traffic",
            "get_latest_stats",
            "clear_traffic_stats",
            "get_traffic_start_time",
            "has_traffic_items",
            "get_traffic_items",
            "restart_bgp_peers",
            "find_bgp_peers",
            "configure_traffic_item",
            "tear_down",
        }
        actual = {
            name
            for name, method in vars(AbstractTrafficGenerator).items()
            if getattr(method, "__isabstractmethod__", False)
        }
        self.assertEqual(actual, expected)

    def test_otg_traffic_gen_implements_abc(self):
        from taac.ixia.otg_traffic_gen import OtgTrafficGen

        self.assertTrue(issubclass(OtgTrafficGen, AbstractTrafficGenerator))

    def test_taac_runner_ixia_calls_are_on_abc_or_guarded(self):
        """Scan taac_runner.py for attribute accesses on the ixia variable.

        Every attribute access on `self.ixia` or the local `ixia` alias must
        either:
          1. Be part of the AbstractTrafficGenerator ABC interface, OR
          2. Appear in NON_ABC_ALLOWED and be guarded with hasattr/isinstance
             in the source.

        This test catches new unguarded restpy-only calls that would crash
        the OTG backend at runtime.

        ── Decision framework ──────────────────────────────────────────
        When you need to call a method on `self.ixia` in taac_runner.py:

        PREFER adding to the ABC when:
          • The *intent* is backend-agnostic (e.g. "change a flow's rate"),
            even if the mechanism differs between restpy and OTG.
          • Both backends can provide a meaningful implementation — it
            doesn't have to be identical, just semantically equivalent.

        Use NON_ABC_ALLOWED + a guard when:
          • The operation is inherently tied to one backend's architecture
            (e.g. restpy's ResourceManager export/import, IxNetwork session
            health checks).
          • There is no useful OTG equivalent — not even a no-op — and
            adding a stub would mislead future readers into thinking the
            feature is supported.

        DO NOT add a method to the ABC with `raise NotImplementedError`
        on OtgTrafficGen just to make this test pass — that is caught by
        test_no_notimplementederror_stubs_on_otg (below).
        ────────────────────────────────────────────────────────────────
        """
        import ast
        import inspect
        import os

        # -- Attributes that are NOT on the ABC but are used with guards ------
        # Every entry here MUST have a corresponding hasattr() or isinstance()
        # guard in taac_runner.py — this is enforced below.
        #
        # To add a new entry:
        #   1. Add the hasattr/isinstance guard in taac_runner.py FIRST.
        #   2. Add the name here with a comment explaining why it can't be
        #      on the ABC (what makes it backend-specific?).
        #   3. The test will verify the guard exists in the source.
        NON_ABC_ALLOWED = {
            # backup/restore — restpy ResourceManager serializes the entire
            # IxNetwork session state as JSON. OTG has no session state to
            # serialize (config is a snappi object held in memory).
            "export_and_save_config",
            "import_saved_config",
            # background stat capture flag — present on both backends today
            # but is an implementation detail, not an operational contract.
            # Guarded with hasattr.
            "capturing",
            # restpy-only chassis liveness probe — checks IxNetwork REST API
            # health via session object. OTG has no equivalent session concept.
            # Guarded with isinstance(self.ixia, TaacIxia).
            "ensure_ixia_alive",
            # chassis IP — used for diagnostics collection (Manifold upload).
            # OTG deployments don't have a chassis IP in the same sense.
            "primary_chassis_ip",
        }

        abc_attrs = {
            name
            for name, method in vars(AbstractTrafficGenerator).items()
            if not name.startswith("_")
        }

        # Locate taac_runner.py relative to abstract_traffic_generator.py
        abc_file = inspect.getfile(AbstractTrafficGenerator)
        taac_runner_path = os.path.join(
            os.path.dirname(os.path.dirname(abc_file)),
            "libs",
            "taac_runner.py",
        )
        with open(taac_runner_path) as f:
            source = f.read()
        tree = ast.parse(source, filename=taac_runner_path)

        # Collect all `ixia.X` and `self.ixia.X` attribute accesses
        accessed = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            # self.ixia.attr
            if (
                isinstance(node.value, ast.Attribute)
                and isinstance(node.value.value, ast.Name)
                and node.value.value.id == "self"
                and node.value.attr == "ixia"
            ):
                accessed.add(node.attr)
            # ixia.attr  (local alias: `ixia = self.ixia`)
            elif isinstance(node.value, ast.Name) and node.value.id == "ixia":
                accessed.add(node.attr)

        # 1) Every accessed attr must be on ABC or in the allowlist
        unknown = accessed - abc_attrs - NON_ABC_ALLOWED
        self.assertEqual(
            unknown,
            set(),
            f"taac_runner.py accesses these attributes on `ixia` that are "
            f"not in the AbstractTrafficGenerator ABC and not in the "
            f"NON_ABC_ALLOWED list: {unknown}.\n\n"
            f"  → To fix, read the 'Decision framework' in this test's "
            f"docstring and choose the right path.",
        )

        # 2) Every NON_ABC_ALLOWED entry that is actually accessed must have
        #    a guard (hasattr or isinstance) in the source
        guarded_attrs = accessed & NON_ABC_ALLOWED
        for attr in guarded_attrs:
            has_hasattr_guard = f'hasattr(ixia, "{attr}")' in source
            has_isinstance_guard = "isinstance(self.ixia, TaacIxia)" in source
            self.assertTrue(
                has_hasattr_guard or has_isinstance_guard,
                f"'{attr}' is in NON_ABC_ALLOWED but taac_runner.py has no "
                f"hasattr/isinstance guard for it. Add a guard before the "
                f"call site:\n"
                f'  if hasattr(ixia, "{attr}"):\n'
                f"      ixia.{attr}(...)",
            )

    def test_no_notimplementederror_stubs_on_otg(self):
        """Catch ABC methods that OtgTrafficGen 'implements' with NotImplementedError.

        If an ABC method doesn't have a real OTG equivalent, it should NOT
        be on the ABC — it should be in NON_ABC_ALLOWED with a guard.
        Adding `raise NotImplementedError` is the wrong fix; it just defers
        the crash from import-time to call-time and misleads readers into
        thinking the operation is supported.
        """
        import dis
        import inspect

        try:
            from taac.ixia.otg_traffic_gen import OtgTrafficGen
        except ImportError:
            self.skipTest("OtgTrafficGen not importable in this environment")

        abc_methods = {
            name
            for name, method in vars(AbstractTrafficGenerator).items()
            if getattr(method, "__isabstractmethod__", False)
        }

        stubs = []
        for method_name in abc_methods:
            method = getattr(OtgTrafficGen, method_name, None)
            if method is None:
                continue
            # Check if the method body is just `raise NotImplementedError`
            # by inspecting the bytecode for RAISE_VARARGS with
            # NotImplementedError loaded.
            try:
                source = inspect.getsource(method)
                if "NotImplementedError" in source:
                    # Verify it's actually raised, not just referenced
                    instructions = list(dis.get_instructions(method))
                    raises_nie = any(
                        instr.opname == "RAISE_VARARGS"
                        and i > 0
                        and "NotImplementedError" in str(instructions[i - 1])
                        for i, instr in enumerate(instructions)
                    )
                    if raises_nie:
                        stubs.append(method_name)
            except (OSError, TypeError):
                continue

        self.assertEqual(
            stubs,
            [],
            f"OtgTrafficGen has NotImplementedError stubs for these ABC "
            f"methods: {stubs}. This means the method was added to the ABC "
            f"without a real OTG implementation.\n\n"
            f"  → If there's no meaningful OTG equivalent, remove the method "
            f"from the ABC. Use NON_ABC_ALLOWED + a hasattr/isinstance guard "
            f"in taac_runner.py instead.\n"
            f"  → If there IS an OTG equivalent, implement it properly.",
        )


# -- _enable_traffic: regex matching + disabled-set bookkeeping ---------------


class TestEnableTraffic(unittest.TestCase):
    def setUp(self):
        self.tgen = _create_otg_tgen()
        flow_a = MagicMock()
        flow_a.name = "routed_flow_p1_0_to_0"
        flow_b = MagicMock()
        flow_b.name = "routed_flow_p2_0_to_0"
        flow_c = MagicMock()
        flow_c.name = "bgp_flow_1"
        self.tgen.config.flows = [flow_a, flow_b, flow_c]

    def test_disable_all_none_regex(self):
        self.tgen._enable_traffic(regexes=None, enable=False)
        self.assertEqual(
            self.tgen._disabled_flows,
            {"routed_flow_p1_0_to_0", "routed_flow_p2_0_to_0", "bgp_flow_1"},
        )

    def test_enable_all_none_regex(self):
        self.tgen._disabled_flows = {"routed_flow_p1_0_to_0", "bgp_flow_1"}
        self.tgen._enable_traffic(regexes=None, enable=True)
        self.assertEqual(self.tgen._disabled_flows, set())

    def test_disable_by_regex_partial_match(self):
        self.tgen._enable_traffic(regexes=["routed_flow"], enable=False)
        self.assertEqual(
            self.tgen._disabled_flows,
            {"routed_flow_p1_0_to_0", "routed_flow_p2_0_to_0"},
        )

    def test_enable_by_regex_partial_match(self):
        self.tgen._disabled_flows = {
            "routed_flow_p1_0_to_0",
            "routed_flow_p2_0_to_0",
            "bgp_flow_1",
        }
        self.tgen._enable_traffic(regexes=["p1"], enable=True)
        self.assertEqual(
            self.tgen._disabled_flows,
            {"routed_flow_p2_0_to_0", "bgp_flow_1"},
        )

    def test_no_match_is_noop(self):
        self.tgen._enable_traffic(regexes=["nonexistent"], enable=False)
        self.assertEqual(self.tgen._disabled_flows, set())


# -- start/stop traffic: guard clauses + timestamp ----------------------------


class TestStartStopTraffic(unittest.TestCase):
    def setUp(self):
        self.tgen = _create_otg_tgen()

    def test_start_traffic_records_timestamp(self):
        flow = MagicMock()
        flow.name = "f1"
        self.tgen.config.flows = [flow]
        before = time.time()
        self.tgen.start_traffic()
        self.assertGreaterEqual(self.tgen.get_traffic_start_time(), before)

    def test_start_skips_when_all_disabled(self):
        flow = MagicMock()
        flow.name = "f1"
        self.tgen.config.flows = [flow]
        self.tgen._disabled_flows = {"f1"}
        self.tgen.start_traffic()
        self.tgen.api.set_control_state.assert_not_called()

    def test_stop_noop_when_no_flows(self):
        self.tgen.config.flows = []
        self.tgen.stop_traffic()
        self.tgen.api.set_control_state.assert_not_called()


# -- begin/end test case lifecycle --------------------------------------------


class TestBeginEndTestCase(unittest.TestCase):
    def setUp(self):
        self.tgen = _create_otg_tgen()
        flow = MagicMock()
        flow.name = "flow1"
        self.tgen.config.flows = [flow]

    def test_begin_sets_uuid_and_clears_loss_state(self):
        self.tgen._flow_loss_start = {"flow1": 100.0}
        self.tgen._flow_loss_accumulated = {"flow1": 5.0}
        self.tgen._disabled_flows = {"flow1"}
        self.tgen.begin_test_case("uuid-123", traffic_regexes=None)
        self.assertEqual(self.tgen.test_case_uuid, "uuid-123")
        self.assertEqual(self.tgen._flow_loss_start, {})
        self.assertEqual(self.tgen._flow_loss_accumulated, {})
        self.assertEqual(self.tgen._disabled_flows, set())

    def test_end_pauses_and_disables(self):
        self.tgen.paused = False
        self.tgen.end_test_case(traffic_regexes=None)
        self.assertTrue(self.tgen.paused)
        self.assertEqual(self.tgen._disabled_flows, {"flow1"})


# -- find_bgp_peers: pure list filtering --------------------------------------


class TestFindBgpPeers(unittest.TestCase):
    def setUp(self):
        self.tgen = _create_otg_tgen()
        self.tgen._bgp_peer_names = [
            "p1_DG0_bgp_v4",
            "p1_DG0_bgp_v6",
            "p2_DG0_bgp_v4",
        ]

    def test_find_all(self):
        self.assertEqual(self.tgen.find_bgp_peers(), self.tgen._bgp_peer_names)

    def test_find_by_regex(self):
        self.assertEqual(
            self.tgen.find_bgp_peers(regex="v4"),
            ["p1_DG0_bgp_v4", "p2_DG0_bgp_v4"],
        )

    def test_find_case_insensitive(self):
        self.assertEqual(
            self.tgen.find_bgp_peers(regex="P1", ignore_case=True),
            ["p1_DG0_bgp_v4", "p1_DG0_bgp_v6"],
        )

    def test_find_no_match(self):
        self.assertEqual(self.tgen.find_bgp_peers(regex="nonexistent"), [])

    def test_restart_with_regex_list(self):
        self.tgen.restart_bgp_peers(regexes=["p2"])
        self.assertEqual(self.tgen.api.set_control_state.call_count, 2)

    def test_restart_no_match_warns_without_api_call(self):
        self.tgen.restart_bgp_peers(regexes=["nonexistent"])
        self.tgen.api.set_control_state.assert_not_called()


# -- _flow_metrics_to_stats: pure data transform ------------------------------


class TestFlowMetricsToStats(unittest.TestCase):
    def setUp(self):
        self.tgen = _create_otg_tgen()

    def test_format_matches_health_check_contract(self):
        metrics = [
            {"name": "flow1", "frames_tx": 1000, "frames_rx": 990, "loss": 1.0},
            {"name": "flow2", "frames_tx": 500, "frames_rx": 500, "loss": 0.0},
        ]
        stats = self.tgen._flow_metrics_to_stats(metrics)
        self.assertEqual(stats[0]["identifier"], "flow1")
        self.assertEqual(stats[0]["packet_loss_percentage"], 1.0)
        self.assertEqual(stats[0]["frame_delta"], 10.0)
        self.assertEqual(stats[1]["frame_delta"], 0.0)

    def test_accumulated_loss_converted_to_milliseconds(self):
        self.tgen._flow_loss_accumulated = {"f1": 2.5}
        metrics = [{"name": "f1", "frames_tx": 100, "frames_rx": 100, "loss": 0}]
        stats = self.tgen._flow_metrics_to_stats(metrics)
        self.assertAlmostEqual(stats[0]["packet_loss_duration"], 2500.0, places=0)


# -- _update_flow_loss_state: loss duration state machine ---------------------


class TestFlowLossTracking(unittest.TestCase):
    def setUp(self):
        self.tgen = _create_otg_tgen()

    def test_loss_starts_tracking_on_tx_rx_gap(self):
        self.tgen._update_flow_loss_state(
            [{"name": "f1", "frames_tx": 100, "frames_rx": 90}], ts=1000.0
        )
        self.assertEqual(self.tgen._flow_loss_start["f1"], 1000.0)

    def test_recovery_accumulates_elapsed_loss(self):
        self.tgen._flow_loss_start["f1"] = 1000.0
        self.tgen._update_flow_loss_state(
            [{"name": "f1", "frames_tx": 100, "frames_rx": 100}], ts=1005.0
        )
        self.assertIsNone(self.tgen._flow_loss_start["f1"])
        self.assertAlmostEqual(self.tgen._flow_loss_accumulated["f1"], 5.0)

    def test_zero_tx_does_not_start_loss(self):
        self.tgen._update_flow_loss_state(
            [{"name": "f1", "frames_tx": 0, "frames_rx": 0}], ts=1000.0
        )
        self.assertNotIn("f1", self.tgen._flow_loss_start)

    def test_multiple_loss_periods_accumulate(self):
        self.tgen._flow_loss_accumulated["f1"] = 3.0
        self.tgen._flow_loss_start["f1"] = 1000.0
        self.tgen._update_flow_loss_state(
            [{"name": "f1", "frames_tx": 100, "frames_rx": 100}], ts=1002.0
        )
        self.assertAlmostEqual(self.tgen._flow_loss_accumulated["f1"], 5.0)


# -- clear_traffic_stats ------------------------------------------------------


class TestClearTrafficStats(unittest.TestCase):
    def test_clears_all_state(self):
        tgen = _create_otg_tgen()
        tgen._captured_stats = {1: [{"name": "f"}]}
        tgen._flow_loss_start = {"f": 1.0}
        tgen._flow_loss_accumulated = {"f": 2.0}
        tgen.clear_traffic_stats()
        self.assertEqual(tgen._captured_stats, {})
        self.assertEqual(tgen._flow_loss_start, {})
        self.assertEqual(tgen._flow_loss_accumulated, {})


# -- tear_down ----------------------------------------------------------------


class TestTearDown(unittest.TestCase):
    def test_teardown_is_alias_for_tear_down(self):
        from taac.ixia.otg_traffic_gen import OtgTrafficGen

        self.assertIs(OtgTrafficGen.teardown, OtgTrafficGen.tear_down)

    def test_error_during_teardown_is_swallowed(self):
        tgen = _create_otg_tgen()
        with patch("taac.ixia.otg_traffic_gen.snappi") as mock_snappi:
            mock_snappi.Config.return_value = MagicMock()
            tgen.api.set_config.side_effect = Exception("connection refused")
            tgen.tear_down()


# -- _build_ports: port_location vs chassis;slot;port fallback ----------------


class TestBuildPorts(unittest.TestCase):
    def test_uses_port_location_when_set(self):
        tgen = _create_otg_tgen()
        pc = _make_port_config("p1", port_location="eth1")
        tgen.ixia_config.port_configs = [pc]
        tgen._build_ports()
        tgen.config.ports.port.assert_called_with(name="p1", location="eth1")

    def test_falls_back_to_chassis_slot_port(self):
        tgen = _create_otg_tgen()
        pc = _make_port_config(
            "p1", port_location="", chassis_ip="10.0.0.1", slot=2, port=3
        )
        tgen.ixia_config.port_configs = [pc]
        tgen._build_ports()
        tgen.config.ports.port.assert_called_with(name="p1", location="10.0.0.1;2;3")


# -- _build_device_group: populates _device_group_info dict -------------------


class TestBuildDeviceGroup(unittest.TestCase):
    def _build(self, dg_cfg, port_name="p1"):
        tgen = _create_otg_tgen()
        pc = _make_port_config(port_name, device_group_configs=[dg_cfg])
        tgen.ixia_config.port_configs = [pc]
        mock_device = MagicMock()
        tgen.config.devices.device.return_value = [mock_device]
        mock_device.ethernets.ethernet.return_value = [MagicMock()]
        tgen._build_device_group(port_name, dg_cfg)
        return tgen

    def test_ipv4_device_group(self):
        dg = _make_device_group_config(ipv4_start="10.0.1.1", ipv4_gw="10.0.1.2")
        info = self._build(dg)._device_group_info[("p1", 0)]
        self.assertEqual(info["ip"], "10.0.1.1")
        self.assertEqual(info["gateway"], "10.0.1.2")
        self.assertEqual(info["af"], "v4")

    def test_ipv6_device_group(self):
        dg = _make_device_group_config(
            ipv4_start=None,
            ipv6_start="2001:db8::1",
            ipv6_gw="2001:db8::2",
        )
        info = self._build(dg)._device_group_info[("p1", 0)]
        self.assertEqual(info["af"], "v6")
        self.assertEqual(info["ip"], "2001:db8::1")


# -- Config builders: flow translation -----------------------------------------


class TestBuildTrafficFlows(unittest.TestCase):
    def _make_traffic_item(
        self,
        name="flow1",
        traffic_type=None,
        bidir=False,
        l4_protocol_config=None,
        rate_info=None,
        flow_config=None,
    ):
        from ixia.ixia import types as ixia_types

        ti = MagicMock()
        ti.name = name
        ti.traffic_type = traffic_type or ixia_types.TrafficType.IPV4
        ti.l4_protocol_config = l4_protocol_config
        ti.traffic_rate_info = rate_info
        ti.traffic_flow_config = flow_config or MagicMock(
            bidirectional=bidir,
            frame_size=None,
            transmission_control=None,
        )
        ep_src = MagicMock()
        ep_src.port_name = "p1"
        ep_src.device_group_index = 0
        ep_src.endpoint_type = ixia_types.EndpointType.IXIA_PORT
        ep_dst = MagicMock()
        ep_dst.port_name = "p2"
        ep_dst.device_group_index = 0
        ep_dst.endpoint_type = ixia_types.EndpointType.IXIA_PORT
        ti.source_endpoints = [ep_src]
        ti.dest_endpoints = [ep_dst]
        return ti

    def _setup_tgen_with_flows(self, traffic_items):
        tgen = _create_otg_tgen()
        pc1 = _make_port_config(
            "p1",
            device_group_configs=[
                _make_device_group_config(index=0, ipv4_start="10.0.1.1"),
            ],
        )
        pc2 = _make_port_config(
            "p2",
            device_group_configs=[
                _make_device_group_config(index=0, ipv4_start="10.0.2.1"),
            ],
        )
        tgen.ixia_config.port_configs = [pc1, pc2]
        tgen.ixia_config.traffic_items = traffic_items
        mock_flow = MagicMock()
        flows_mock = MagicMock()
        flows_mock.flow.return_value = [mock_flow]
        flows_mock.__iter__ = lambda self: iter([])
        flows_mock.__bool__ = lambda self: False
        tgen.config.flows = flows_mock
        return tgen, mock_flow

    def test_bidirectional_creates_two_flows(self):
        ti = self._make_traffic_item(bidir=True)
        tgen, _ = self._setup_tgen_with_flows([ti])
        tgen._build_traffic_flows()
        self.assertEqual(tgen.config.flows.flow.call_count, 2)
        names = [c.kwargs["name"] for c in tgen.config.flows.flow.call_args_list]
        self.assertIn("flow1", names)
        self.assertIn("flow1_reverse", names)

    def test_no_traffic_items_is_noop(self):
        tgen = _create_otg_tgen()
        tgen.ixia_config.traffic_items = []
        flows_mock = MagicMock()
        tgen.config.flows = flows_mock
        tgen._build_traffic_flows()
        flows_mock.flow.assert_not_called()


# -- Config builders: _resolve_endpoint ----------------------------------------


class TestResolveEndpoint(unittest.TestCase):
    def test_device_group_returns_ipv4_name(self):
        from ixia.ixia import types as ixia_types

        tgen = _create_otg_tgen()
        pc = _make_port_config(
            "p1",
            device_group_configs=[
                _make_device_group_config(index=0, ipv4_start="10.0.1.1"),
            ],
        )
        tgen.ixia_config.port_configs = [pc]
        ep = MagicMock()
        ep.port_name = "p1"
        ep.device_group_index = 0
        ep.endpoint_type = ixia_types.EndpointType.IXIA_PORT
        result = tgen._resolve_endpoint(ep)
        self.assertEqual(result, "p1_DG0_ipv4")

    def test_bgp_prefix_returns_prefix_name(self):
        from ixia.ixia import types as ixia_types

        tgen = _create_otg_tgen()
        ep = MagicMock()
        ep.endpoint_type = ixia_types.EndpointType.BGP_PREFIX
        ep.bgp_prefix_name = "my_route_v4"
        ep.port_name = "p1"
        result = tgen._resolve_endpoint(ep)
        self.assertEqual(result, "my_route_v4")


# -- Config builders: flow rate/size/duration ----------------------------------


class TestConfigureFlowRate(unittest.TestCase):
    def test_pps(self):
        from ixia.ixia import types as ixia_types

        tgen = _create_otg_tgen()
        flow = MagicMock()
        ti = MagicMock()
        ti.traffic_rate_info = MagicMock(
            rate_type=ixia_types.RateType.FRAMES_PER_SECOND,
            rate_value=1000,
        )
        tgen._configure_flow_rate(flow, ti)
        self.assertEqual(flow.rate.pps, 1000)

    def test_percent(self):
        from ixia.ixia import types as ixia_types

        tgen = _create_otg_tgen()
        flow = MagicMock()
        ti = MagicMock()
        ti.traffic_rate_info = MagicMock(
            rate_type=ixia_types.RateType.PERCENT_LINE_RATE,
            rate_value=50,
        )
        tgen._configure_flow_rate(flow, ti)
        self.assertEqual(flow.rate.percentage, 50)


class TestConfigureFlowSize(unittest.TestCase):
    def test_fixed(self):
        from ixia.ixia import types as ixia_types

        tgen = _create_otg_tgen()
        flow = MagicMock()
        ti = MagicMock()
        ti.traffic_flow_config = MagicMock(
            frame_size=MagicMock(
                type=ixia_types.FrameSizeType.FIXED,
                fixed_size=512,
            ),
        )
        tgen._configure_flow_size(flow, ti)
        self.assertEqual(flow.size.fixed, 512)

    def test_increment(self):
        from ixia.ixia import types as ixia_types

        tgen = _create_otg_tgen()
        flow = MagicMock()
        ti = MagicMock()
        ti.traffic_flow_config = MagicMock(
            frame_size=MagicMock(
                type=ixia_types.FrameSizeType.INCREMENT,
                increment_from=64,
                increment_to=1500,
                increment_step=100,
            ),
        )
        tgen._configure_flow_size(flow, ti)
        self.assertEqual(flow.size.increment.start, 64)
        self.assertEqual(flow.size.increment.end, 1500)
        self.assertEqual(flow.size.increment.step, 100)


class TestConfigureFlowDuration(unittest.TestCase):
    def test_continuous_default(self):
        tgen = _create_otg_tgen()
        flow = MagicMock()
        ti = MagicMock()
        ti.traffic_flow_config = None
        tgen._configure_flow_duration(flow, ti)
        self.assertEqual(flow.duration.choice, flow.duration.CONTINUOUS)

    def test_fixed_duration_seconds(self):
        from ixia.ixia import types as ixia_types

        tgen = _create_otg_tgen()
        flow = MagicMock()
        ti = MagicMock()
        ti.traffic_flow_config = MagicMock(
            transmission_control=MagicMock(
                type=ixia_types.TransmissionControlType.FIXED_DURATION,
                duration=30,
                frame_count=None,
            ),
        )
        tgen._configure_flow_duration(flow, ti)
        self.assertEqual(flow.duration.fixed_seconds.seconds, 30)

    def test_fixed_frame_count(self):
        from ixia.ixia import types as ixia_types

        tgen = _create_otg_tgen()
        flow = MagicMock()
        ti = MagicMock()
        ti.traffic_flow_config = MagicMock(
            transmission_control=MagicMock(
                type=ixia_types.TransmissionControlType.FIXED_FRAME_COUNT,
                frame_count=5000,
                duration=None,
            ),
        )
        tgen._configure_flow_duration(flow, ti)
        self.assertEqual(flow.duration.fixed_packets.packets, 5000)


# -- BGP config builders ------------------------------------------------------


class TestBgpConfigBuilders(unittest.TestCase):
    def _make_bgp_peer_config(
        self, peer_type=None, local_as=65000, local_ip="10.0.1.1", remote_ip="10.0.1.2"
    ):
        from ixia.ixia import types as ixia_types

        cfg = MagicMock()
        cfg.peer_type = peer_type or ixia_types.BgpPeerType.EBGP
        cfg.local_as = local_as
        cfg.local_peer_starting_ip = local_ip
        cfg.remote_peer_starting_ip = remote_ip
        return cfg

    def _make_bgp_info(
        self,
        v4_peer_config=None,
        v6_peer_config=None,
        v4_prefixes=None,
        v6_prefixes=None,
    ):
        bgp_info = MagicMock()
        if v4_peer_config:
            bgp_info.bgp_v4_config = MagicMock()
            bgp_info.bgp_v4_config.bgp_peer_config = v4_peer_config
            bgp_info.bgp_v4_config.bgp_prefix_configs = v4_prefixes or []
        else:
            bgp_info.bgp_v4_config = None
        if v6_peer_config:
            bgp_info.bgp_v6_config = MagicMock()
            bgp_info.bgp_v6_config.bgp_peer_config = v6_peer_config
            bgp_info.bgp_v6_config.bgp_prefix_configs = v6_prefixes or []
        else:
            bgp_info.bgp_v6_config = None
        return bgp_info

    def test_v4_ebgp_peer(self):
        from ixia.ixia import types as ixia_types

        tgen = _create_otg_tgen()
        device = MagicMock()
        peer_cfg = self._make_bgp_peer_config(
            peer_type=ixia_types.BgpPeerType.EBGP,
            local_as=65001,
        )
        bgp_info = self._make_bgp_info(v4_peer_config=peer_cfg)
        tgen._build_bgp_config(device, "p1_DG0", bgp_info, port_name="p1")
        self.assertIn("p1_DG0_bgp_v4", tgen._bgp_peer_names)
        peer = device.bgp.ipv4_interfaces.v4interface.return_value[
            -1
        ].peers.v4peer.return_value[-1]
        self.assertEqual(peer.as_type, "ebgp")
        self.assertEqual(peer.as_number, 65001)

    def test_v6_peer(self):
        from ixia.ixia import types as ixia_types

        tgen = _create_otg_tgen()
        device = MagicMock()
        peer_cfg = self._make_bgp_peer_config(peer_type=ixia_types.BgpPeerType.EBGP)
        bgp_info = self._make_bgp_info(v6_peer_config=peer_cfg)
        tgen._build_bgp_config(device, "p1_DG0", bgp_info, port_name="p1")
        self.assertIn("p1_DG0_bgp_v6", tgen._bgp_peer_names)

    def test_v6_only_peer_gets_derived_ipv4_router_id(self):
        """A v6 local IP cannot be a router_id; a v4 one must be derived."""
        tgen = _create_otg_tgen()
        device = MagicMock()
        peer_cfg = self._make_bgp_peer_config(
            local_ip="2001:db8:1::1", remote_ip="2001:db8:1::2"
        )
        bgp_info = self._make_bgp_info(v6_peer_config=peer_cfg)
        tgen._build_bgp_config(device, "p1_DG0", bgp_info, port_name="p1")
        self.assertEqual(device.bgp.router_id, "192.0.2.1")

    def test_v6_only_device_groups_get_distinct_router_ids(self):
        """Duplicate router IDs break eBGP establishment, so each speaker
        must get its own — including groups whose device_group_name does not
        embed the port name (regression guard for port-index inference)."""
        tgen = _create_otg_tgen()
        assigned = []
        for device_name in ("ECMP_1_eth1", "ECMP_2_eth1", "ECMP_2_eth2"):
            device = MagicMock()
            peer_cfg = self._make_bgp_peer_config(
                local_ip="2001:db8:1::1", remote_ip="2001:db8:1::2"
            )
            bgp_info = self._make_bgp_info(v6_peer_config=peer_cfg)
            tgen._build_bgp_config(device, device_name, bgp_info, port_name="p1")
            assigned.append(device.bgp.router_id)

        self.assertEqual(len(set(assigned)), len(assigned), assigned)

    def test_router_id_is_stable_for_same_device(self):
        tgen = _create_otg_tgen()
        first = tgen._derive_router_id("p1", "ECMP_1_eth1")
        second = tgen._derive_router_id("p1", "ECMP_1_eth1")
        self.assertEqual(first, second)

    def test_v4_local_ip_used_as_router_id_verbatim(self):
        tgen = _create_otg_tgen()
        device = MagicMock()
        peer_cfg = self._make_bgp_peer_config(local_ip="10.0.1.1")
        bgp_info = self._make_bgp_info(v4_peer_config=peer_cfg)
        tgen._build_bgp_config(device, "p1_DG0", bgp_info, port_name="p1")
        self.assertEqual(device.bgp.router_id, "10.0.1.1")
        self.assertEqual(tgen._router_ids, {})

    def test_route_refresh_capability_honored(self):
        """RouteRefresh was absent from cap_map, so it was always set False."""
        from ixia.ixia import types as ixia_types

        tgen = _create_otg_tgen()
        device = MagicMock()
        peer_cfg = self._make_bgp_peer_config()
        peer_cfg.capabilities = [
            ixia_types.BgpCapability.IpV4Unicast,
            ixia_types.BgpCapability.RouteRefresh,
        ]
        bgp_info = self._make_bgp_info(v4_peer_config=peer_cfg)
        tgen._build_bgp_config(device, "p1_DG0", bgp_info, port_name="p1")
        cap = device.bgp.ipv4_interfaces.v4interface.return_value[
            -1
        ].peers.v4peer.return_value[-1].capability
        self.assertTrue(cap.ipv4_unicast)
        self.assertTrue(cap.route_refresh)
        self.assertFalse(cap.ipv6_unicast)

    def test_ibgp_as_type(self):
        from ixia.ixia import types as ixia_types

        tgen = _create_otg_tgen()
        device = MagicMock()
        peer_cfg = self._make_bgp_peer_config(peer_type=ixia_types.BgpPeerType.IBGP)
        bgp_info = self._make_bgp_info(v4_peer_config=peer_cfg)
        tgen._build_bgp_config(device, "p1_DG0", bgp_info, port_name="p1")
        peer = device.bgp.ipv4_interfaces.v4interface.return_value[
            -1
        ].peers.v4peer.return_value[-1]
        self.assertEqual(peer.as_type, "ibgp")

    def _prefix_cfg(self, starting_ip, prefix_length, increment_ip, count=100):
        cfg = MagicMock()
        cfg.prefix_name = "r"
        cfg.starting_ip = starting_ip
        cfg.prefix_length = prefix_length
        cfg.count = count
        cfg.increment_ip = increment_ip
        cfg.bgp_communities = []
        cfg.as_path_prepend = None
        return cfg

    def test_prefix_step_is_in_blocks_not_addresses(self):
        """snappi's route-range step counts prefix blocks, not addresses.

        `increment_ip` is an address delta, so it must be divided by the block
        size.  Skipping that walks the range 2**host_bits times too far, which
        silently overlaps other speakers' ranges instead of failing — the v4
        baseline advertised 100.1.0.0..100.100.0.0 rather than ..100.1.99.0.
        """
        for af, start, plen, inc, expected in (
            ("v4", "100.1.0.0", 24, "0.0.1.0", 1),
            ("v4", "10.0.0.0", 16, "0.1.0.0", 1),
            ("v4", "192.0.2.0", 32, "0.0.0.1", 1),
            ("v6", "2001:db8:1100::", 64, "0:0:0:1::", 1),
            ("v6", "2001:db8::", 48, "0:0:1::", 1),
        ):
            with self.subTest(af=af, prefix_length=plen, increment=inc):
                tgen = _create_otg_tgen()
                peer = MagicMock()
                tgen._build_bgp_prefix(
                    peer, af, self._prefix_cfg(start, plen, inc)
                )
                routes = (
                    peer.v4_routes.v4routerange if af == "v4"
                    else peer.v6_routes.v6routerange
                )
                addrs = (
                    routes.return_value[-1].addresses.v4routeaddress
                    if af == "v4"
                    else routes.return_value[-1].addresses.v6routeaddress
                )
                self.assertEqual(addrs.return_value[-1].step, expected)

    def test_a_step_smaller_than_one_block_falls_back_to_one(self):
        """Shifting down to 0 would collapse every prefix onto one address."""
        for af, start, plen, inc in (
            ("v4", "100.1.0.0", 24, "0.0.0.1"),
            ("v6", "2001:db8:1100::", 64, "::1"),
        ):
            with self.subTest(af=af, increment=inc):
                tgen = _create_otg_tgen()
                peer = MagicMock()
                tgen._build_bgp_prefix(
                    peer, af, self._prefix_cfg(start, plen, inc)
                )
                addrs = (
                    peer.v4_routes.v4routerange.return_value[-1]
                    .addresses.v4routeaddress
                    if af == "v4"
                    else peer.v6_routes.v6routerange.return_value[-1]
                    .addresses.v6routeaddress
                )
                self.assertEqual(addrs.return_value[-1].step, 1)
                self.assertTrue(
                    tgen.logger.warning.called, "collapsing must be reported"
                )

    def test_bgp_prefix_v4_route(self):
        tgen = _create_otg_tgen()
        peer = MagicMock()
        prefix_cfg = MagicMock()
        prefix_cfg.prefix_name = "route_v4"
        prefix_cfg.starting_ip = "192.168.0.0"
        prefix_cfg.prefix_length = 24
        prefix_cfg.count = 10
        prefix_cfg.increment_ip = None
        prefix_cfg.bgp_communities = []
        prefix_cfg.as_path_prepend = None
        tgen._build_bgp_prefix(peer, "v4", prefix_cfg)
        route = peer.v4_routes.v4routerange.return_value[-1]
        self.assertEqual(route.name, "route_v4")
        addr = route.addresses.v4routeaddress.return_value[-1]
        self.assertEqual(addr.address, "192.168.0.0")
        self.assertEqual(addr.prefix, 24)
        self.assertEqual(addr.count, 10)

    def test_bgp_prefix_with_communities(self):
        tgen = _create_otg_tgen()
        peer = MagicMock()
        comm = MagicMock()
        comm.as_number = 65000
        comm.as_custom = 100
        prefix_cfg = MagicMock()
        prefix_cfg.prefix_name = "route_v4"
        prefix_cfg.starting_ip = "10.0.0.0"
        prefix_cfg.prefix_length = 24
        prefix_cfg.count = 1
        prefix_cfg.increment_ip = None
        prefix_cfg.bgp_communities = [comm]
        prefix_cfg.as_path_prepend = None
        tgen._build_bgp_prefix(peer, "v4", prefix_cfg)
        route = peer.v4_routes.v4routerange.return_value[-1]
        c = route.communities.bgpcommunity.return_value[-1]
        self.assertEqual(c.as_number, 65000)
        self.assertEqual(c.as_custom, 100)

    def test_bgp_prefix_with_as_path(self):
        tgen = _create_otg_tgen()
        peer = MagicMock()
        prefix_cfg = MagicMock()
        prefix_cfg.prefix_name = "route_v4"
        prefix_cfg.starting_ip = "10.0.0.0"
        prefix_cfg.prefix_length = 24
        prefix_cfg.count = 1
        prefix_cfg.increment_ip = None
        prefix_cfg.bgp_communities = []
        prefix_cfg.as_path_prepend = MagicMock(as_numbers=[65001, 65002])
        tgen._build_bgp_prefix(peer, "v4", prefix_cfg)
        route = peer.v4_routes.v4routerange.return_value[-1]
        seg = route.as_path.segments.bgpaspathsegment.return_value[-1]
        self.assertEqual(seg.as_numbers, [65001, 65002])


# -- Addressing into an advertised prefix -------------------------------------


class TestPrefixTargetedDestinations(unittest.TestCase):
    """A prefix-targeted flow must span more than one hash bucket.

    A single src/dst pair hashes to one next-hop no matter how many ECMP members
    exist, so it can only prove that *one* path resolves — not that selection is
    spread across the members. Varying the destination inside the advertised
    prefix is what makes wrong next-hop selection observable.
    """

    def _tgen_with_prefix(self, af="v6", address="2001:db8:ec00::", prefix_len=64):
        tgen = _create_otg_tgen()
        tgen._advertised_prefixes[("p1", 1, 0, af)] = {
            "address": address,
            "prefix_len": prefix_len,
        }
        return tgen

    def test_returns_a_span_not_a_single_address(self):
        tgen = self._tgen_with_prefix()
        start, count = tgen._prefix_host_span("p1", 1, 0, "v6")
        self.assertEqual(start, "2001:db8:ec00::1")
        self.assertGreater(count, 1)

    def test_span_is_bounded_by_a_tiny_prefix(self):
        """A /31 has two addresses; the span must not promise more than exist."""
        tgen = self._tgen_with_prefix(af="v4", address="198.51.100.0", prefix_len=31)
        _, count = tgen._prefix_host_span("p1", 1, 0, "v4")
        self.assertLessEqual(count, 2)
        self.assertGreaterEqual(count, 1)

    def test_absent_prefix_yields_no_span(self):
        tgen = _create_otg_tgen()
        self.assertIsNone(tgen._prefix_host_span("p1", 9, 0, "v6"))


# -- Flow-name collisions fail loudly ----------------------------------------


class TestDuplicateFlowNameRaises(unittest.TestCase):
    """The flow-name key omits the rx port, so collisions are possible.

    `config.flows.flow(name=...)` appends rather than replaces, so a collision
    would silently produce two flows sharing a name — and every later lookup
    (loss reporting, _disabled_flows, transmit) would address whichever one it
    found first. Renaming is not free because playbooks match flow names by
    regex, so the key is left alone and the collision is made an error instead.
    """

    def test_a_repeated_flow_name_raises(self):
        tgen = _create_otg_tgen()
        tgen.config.flows = [_make_flow("dup_p1_0_to_0")]
        with self.assertRaises(ValueError) as ctx:
            tgen._assert_unique_flow_name("dup_p1_0_to_0")
        self.assertIn("rx port", str(ctx.exception))

    def test_a_fresh_flow_name_is_accepted(self):
        tgen = _create_otg_tgen()
        tgen.config.flows = [_make_flow("other_p1_0_to_0")]
        tgen._assert_unique_flow_name("dup_p1_0_to_0")


# -- Controller warnings must not be discarded --------------------------------


class TestControllerWarnings(unittest.TestCase):
    """snappi returns a Warning object from set_config/set_control_state.

    OTG uses warnings for "accepted, but" — a peer the controller declined to
    start, an unsupported capability.  They are not errors, so nothing raises and
    nothing else surfaces them; discarding the return value makes the
    controller's own explanation of a failure invisible.
    """

    @staticmethod
    def _with_warnings(*messages):
        resp = MagicMock()
        resp.warnings = list(messages)
        return resp

    def test_push_config_logs_controller_warnings(self):
        tgen = _create_otg_tgen()
        tgen.api.set_config.return_value = self._with_warnings(
            "bgp peer NO_PACKET_LOSS_EXPECTED_PORT1_bgp_v4 not started"
        )
        tgen._push_config()
        logged = " ".join(str(c) for c in tgen.logger.warning.call_args_list)
        self.assertIn("not started", logged)

    def test_start_protocols_logs_controller_warnings(self):
        tgen = _create_otg_tgen()
        tgen.api.set_control_state.return_value = self._with_warnings(
            "protocol engine declined to start"
        )
        tgen._start_protocols()
        logged = " ".join(str(c) for c in tgen.logger.warning.call_args_list)
        self.assertIn("declined to start", logged)

    def test_a_response_with_nothing_to_report_is_quiet(self):
        """Empty list and absent attribute (older snappi returns None)."""
        for label, response in (("empty", self._with_warnings()), ("none", None)):
            with self.subTest(response=label):
                tgen = _create_otg_tgen()
                tgen.api.set_config.return_value = response
                tgen._push_config()
                self.assertEqual(tgen.logger.warning.call_count, 0)


# -- Degraded setup must not force a re-push ----------------------------------


class TestDegradedSetupSkipsRepush(unittest.TestCase):
    """A setup that bailed early still recorded what it pushed.

    Otherwise `_last_pushed_config` stays None, the next `_prepare_traffic()`
    sees a difference and does a full set_config plus protocol restart — the
    exact flap the skip-if-unchanged check exists to avoid, landing on a run
    that is already degraded.
    """

    def test_arp_path_records_pushed_config(self):
        tgen = _create_otg_tgen()
        with (
            patch.object(tgen, "_get_resolved_gw_macs", return_value={}),
            patch.object(tgen, "_start_protocols"),
            patch.object(tgen, "_wait_for_arp"),
        ):
            tgen._setup_with_explicit_flows()
        pushes = tgen.api.set_config.call_count
        tgen._prepare_traffic()
        self.assertEqual(tgen.api.set_config.call_count, pushes)

    def test_bgp_path_records_pushed_config(self):
        tgen = _create_otg_tgen()
        with (
            patch.object(tgen, "_get_resolved_gw_macs", return_value={}),
            patch.object(tgen, "_start_protocols"),
            patch.object(tgen, "_wait_for_bgp"),
        ):
            tgen._setup_bgp_with_explicit_flows(90)
        pushes = tgen.api.set_config.call_count
        tgen._prepare_traffic()
        self.assertEqual(tgen.api.set_config.call_count, pushes)


# -- DeviceGroupConfig.enable -------------------------------------------------


class TestDeviceGroupEnable(unittest.TestCase):
    """A disabled group is built but held down.

    OTG has no device-level disable, so honouring `enable=False` means building
    the group normally and driving its peers DOWN once protocols start.  That is
    what makes a playbook's later toggle-up a real transition instead of a no-op
    against an already-established peer.
    """

    PEER = "p1_DG0_bgp_v4"

    def _build(self, enable):
        tgen = _create_otg_tgen()
        dg = _make_device_group_config(bgp_config=MagicMock(), enable=enable)
        tgen.ixia_config.port_configs = [
            _make_port_config("p1", device_group_configs=[dg])
        ]
        mock_device = MagicMock()
        tgen.config.devices.device.return_value = [mock_device]
        mock_device.ethernets.ethernet.return_value = [MagicMock()]
        # Mirror the real contract: _build_bgp_config appends to _bgp_peer_names.
        with patch.object(
            tgen,
            "_build_bgp_config",
            side_effect=lambda *a, **k: tgen._bgp_peer_names.append(self.PEER),
        ):
            tgen._build_device_group("p1", dg)
        return tgen

    def test_disabled_group_is_still_built(self):
        tgen = self._build(enable=False)
        self.assertIn(self.PEER, tgen._bgp_peer_names)
        self.assertEqual(tgen._device_group_info[("p1", 0)]["peers"], [self.PEER])

    def test_disabled_group_peers_not_required_at_setup(self):
        self.assertIn(self.PEER, self._build(enable=False)._unrequired_peers)

    def test_enabled_group_peers_are_required_at_setup(self):
        self.assertNotIn(self.PEER, self._build(enable=True)._unrequired_peers)

    def test_starting_protocols_holds_disabled_peers_down(self):
        tgen = self._build(enable=False)
        cs = tgen.api.control_state.return_value
        tgen._start_protocols()
        self.assertEqual(cs.protocol.bgp.peers.peer_names, [self.PEER])
        self.assertIs(cs.protocol.bgp.peers.state, cs.protocol.bgp.peers.DOWN)

    def test_starting_protocols_issues_no_peer_state_call_when_all_enabled(self):
        """Exactly one control_state call — the protocol START, no hold-down.

        Asserting on the mock's `peer_names` instead would pass vacuously: an
        unset MagicMock attribute never equals a list, so that assertion holds
        even if the method does nothing. Counting the calls can actually fail.
        """
        tgen = self._build(enable=True)
        tgen.api.set_control_state.reset_mock()
        tgen._start_protocols()
        self.assertEqual(tgen.api.set_control_state.call_count, 1)

    def test_enabling_a_disabled_group_is_sticky(self):
        """A later config re-push must not silently undo a playbook's toggle-up.

        `begin_test_case` reaches `_prepare_traffic`, which re-pushes and restarts
        protocols when the config changed.  On restpy this cannot happen — config
        build is one-shot — so OTG has to stop treating the group as disabled once
        a playbook has enabled it.
        """
        tgen = self._build(enable=False)
        tgen.toggle_device_groups(
            enable=True,
            device_group_name_regex=".*",
            sleep_time_before_applying_change=0,
        )
        self.assertNotIn(self.PEER, tgen._unrequired_peers)

        cs = tgen.api.control_state.return_value
        cs.protocol.bgp.peers.peer_names = None
        tgen._start_protocols()
        self.assertIsNone(cs.protocol.bgp.peers.peer_names)

    def test_disabling_a_group_again_re_arms_the_hold(self):
        tgen = self._build(enable=False)
        for state in (True, False):
            tgen.toggle_device_groups(
                enable=state,
                device_group_name_regex=".*",
                sleep_time_before_applying_change=0,
            )
        self.assertIn(self.PEER, tgen._unrequired_peers)

    def test_disabled_peer_down_does_not_block_setup(self):
        tgen = self._build(enable=False)
        tgen._bgp_peer_names.append("other_bgp_v4")
        down = MagicMock(session_state="down")
        down.name = self.PEER
        up = MagicMock(session_state="up")
        up.name = "other_bgp_v4"
        with patch.object(tgen, "_get_bgp_metrics", return_value=[up, down]):
            tgen._wait_for_bgp(timeout=1)


# -- BGP session gate ---------------------------------------------------------


class TestWaitForBgp(unittest.TestCase):
    """Replay peers flap by design and must not gate setup."""

    @staticmethod
    def _metric(name, state):
        # `name` is reserved by the MagicMock constructor, so set it after.
        m = MagicMock(session_state=state)
        m.name = name
        return m

    def test_replay_peer_down_does_not_block(self):
        tgen = _create_otg_tgen()
        tgen._bgp_peer_names = ["good_bgp_v4", "rogue_bgp_v4"]
        tgen._unrequired_peers = {"rogue_bgp_v4": {"replay sequence"}}
        metrics = [self._metric("good_bgp_v4", "up"), self._metric("rogue_bgp_v4", "down")]
        with patch.object(tgen, "_get_bgp_metrics", return_value=metrics):
            tgen._wait_for_bgp(timeout=1)

    def test_non_replay_peer_down_still_blocks(self):
        tgen = _create_otg_tgen()
        tgen._bgp_peer_names = ["good_bgp_v4", "rogue_bgp_v4"]
        tgen._unrequired_peers = {"rogue_bgp_v4": {"replay sequence"}}
        metrics = [self._metric("good_bgp_v4", "down"), self._metric("rogue_bgp_v4", "up")]
        with patch.object(tgen, "_get_bgp_metrics", return_value=metrics):
            with self.assertRaises(TimeoutError):
                tgen._wait_for_bgp(timeout=1)

    def test_empty_metrics_is_not_a_silent_timeout(self):
        """The controller reporting no peers must not look like the peers being
        down.  Without this the whole 90s produces no output at all — the
        per-poll line is inside `if metrics` — so the failure is unfalsifiable.
        """
        tgen = _create_otg_tgen()
        tgen._bgp_peer_names = ["good_bgp_v4"]
        with patch.object(tgen, "_get_bgp_metrics", return_value=[]):
            with self.assertRaises(TimeoutError):
                tgen._wait_for_bgp(timeout=1)
        logged = " ".join(
            str(c) for c in tgen.logger.warning.call_args_list
        )
        self.assertIn("good_bgp_v4", logged)

    def test_a_held_down_peer_reading_up_is_a_warning(self):
        """The hold-down is fire-and-forget; this is the only thing checking it.

        If the DOWN races peer instantiation the peer stays up, and then
        toggle_device_groups(enable=True) is a no-op against an established
        session — the playbook measures nothing and reports green. Riding on this
        poll rather than checking right after the DOWN avoids false positives:
        by the time the required peers are up, the DOWN has had seconds to land.
        """
        tgen = _create_otg_tgen()
        tgen._bgp_peer_names = ["good_bgp_v4", "held_bgp_v4"]
        tgen._unrequired_peers = {"held_bgp_v4": {"device group disabled"}}
        metrics = [
            self._metric("good_bgp_v4", "up"),
            self._metric("held_bgp_v4", "up"),
        ]
        with patch.object(tgen, "_get_bgp_metrics", return_value=metrics):
            tgen._wait_for_bgp(timeout=1)
        logged = " ".join(str(c) for c in tgen.logger.warning.call_args_list)
        self.assertIn("held_bgp_v4", logged)

    def test_a_held_down_peer_reading_down_is_not_a_warning(self):
        tgen = _create_otg_tgen()
        tgen._bgp_peer_names = ["good_bgp_v4", "held_bgp_v4"]
        tgen._unrequired_peers = {"held_bgp_v4": {"device group disabled"}}
        metrics = [
            self._metric("good_bgp_v4", "up"),
            self._metric("held_bgp_v4", "down"),
        ]
        with patch.object(tgen, "_get_bgp_metrics", return_value=metrics):
            tgen._wait_for_bgp(timeout=1)
        self.assertEqual(tgen.logger.warning.call_count, 0)

    def test_a_replay_peer_reading_up_is_not_a_warning(self):
        """Only the disabled reason implies it should be down."""
        tgen = _create_otg_tgen()
        tgen._bgp_peer_names = ["good_bgp_v4", "rogue_bgp_v4"]
        tgen._unrequired_peers = {"rogue_bgp_v4": {"replay sequence"}}
        metrics = [
            self._metric("good_bgp_v4", "up"),
            self._metric("rogue_bgp_v4", "up"),
        ]
        with patch.object(tgen, "_get_bgp_metrics", return_value=metrics):
            tgen._wait_for_bgp(timeout=1)
        self.assertEqual(tgen.logger.warning.call_count, 0)

    def test_timeout_reports_neighbour_resolution(self):
        """Splits "cannot reach the gateway" from "bgpd is not peering".

        Both surface identically as a down session, but the fixes live in
        different places -- cabling/port/addressing versus bgpd config -- so the
        timeout has to say which layer got as far as resolving.
        """
        for neighbours, expected in (
            ({}, "no gateway"),
            ({"10.0.1.2": "aa:bb"}, "10.0.1.2"),
        ):
            with self.subTest(resolved=bool(neighbours)):
                tgen = _create_otg_tgen()
                tgen._bgp_peer_names = ["good_bgp_v4"]
                metrics = [self._metric("good_bgp_v4", "down")]
                with (
                    patch.object(tgen, "_get_bgp_metrics", return_value=metrics),
                    patch.object(
                        tgen, "_get_resolved_gw_macs", return_value=neighbours
                    ),
                ):
                    with self.assertRaises(TimeoutError) as ctx:
                        tgen._wait_for_bgp(timeout=1)
                self.assertIn(expected, str(ctx.exception).lower())

    def test_timeout_message_names_the_required_peers(self):
        tgen = _create_otg_tgen()
        tgen._bgp_peer_names = ["good_bgp_v4", "rogue_bgp_v4"]
        tgen._unrequired_peers = {"rogue_bgp_v4": {"replay sequence"}}
        metrics = [self._metric("good_bgp_v4", "down")]
        with patch.object(tgen, "_get_bgp_metrics", return_value=metrics):
            with self.assertRaises(TimeoutError) as ctx:
                tgen._wait_for_bgp(timeout=1)
        message = str(ctx.exception)
        self.assertIn("good_bgp_v4", message)
        self.assertNotIn("rogue_bgp_v4", message)

    def test_update_sequence_registers_replay_peer(self):
        tgen = _create_otg_tgen()
        peer = MagicMock()
        entry = MagicMock(update_bytes="ffff0013", time_gap_ms=0)
        tgen._build_bgp_update_sequence(peer, MagicMock(updates=[entry]), "rogue_bgp_v4")
        self.assertIn("rogue_bgp_v4", tgen._unrequired_peers)


# -- Two-phase setup ----------------------------------------------------------


class TestTwoPhaseSetup(unittest.TestCase):
    def test_setup_non_bgp_calls_explicit_flows(self):
        tgen = _create_otg_tgen()
        tgen._bgp_peer_names = []
        with patch.object(tgen, "_setup_with_explicit_flows") as mock_explicit:
            tgen.setup()
            mock_explicit.assert_called_once()

    def test_setup_bgp_calls_wait_for_bgp(self):
        tgen = _create_otg_tgen()
        tgen._bgp_peer_names = ["peer1"]
        with (
            patch.object(tgen, "_wait_for_bgp") as mock_wait,
            patch.object(tgen, "_start_protocols"),
        ):
            tgen.setup()
            mock_wait.assert_called_once()
            tgen.api.set_config.assert_called_with(tgen.config)

    def test_explicit_flows_bidirectional(self):
        tgen = _create_otg_tgen()
        tgen._device_group_info = {
            ("p1", 0): {
                "port": "p1",
                "dg_idx": 0,
                "mac": "00:00:01:00:00:01",
                "ip": "10.0.1.1",
                "gateway": "10.0.1.2",
                "af": "v4",
            },
            ("p2", 0): {
                "port": "p2",
                "dg_idx": 0,
                "mac": "00:00:02:00:00:01",
                "ip": "10.0.2.1",
                "gateway": "10.0.2.2",
                "af": "v4",
            },
        }
        ti = MagicMock()
        ti.name = "flow1"
        ti.traffic_flow_config = MagicMock(bidirectional=True)
        ti.traffic_rate_info = None
        src_ep = MagicMock(port_name="p1", device_group_index=0)
        dst_ep = MagicMock(port_name="p2", device_group_index=0)
        ti.source_endpoints = [src_ep]
        ti.dest_endpoints = [dst_ep]
        gw_macs = {"10.0.1.2": "aa:bb:cc:00:01:02", "10.0.2.2": "aa:bb:cc:00:02:02"}
        mock_flow = MagicMock()
        flows_mock = MagicMock()
        flows_mock.flow.return_value = [mock_flow]
        tgen.config.flows = flows_mock
        tgen._build_explicit_flows([ti], gw_macs)
        self.assertEqual(flows_mock.flow.call_count, 2)

    def test_explicit_flows_skips_unresolved_gw(self):
        tgen = _create_otg_tgen()
        tgen._device_group_info = {
            ("p1", 0): {
                "port": "p1",
                "dg_idx": 0,
                "mac": "00:00:01:00:00:01",
                "ip": "10.0.1.1",
                "gateway": "10.0.1.2",
                "af": "v4",
            },
            ("p2", 0): {
                "port": "p2",
                "dg_idx": 0,
                "mac": "00:00:02:00:00:01",
                "ip": "10.0.2.1",
                "gateway": "10.0.2.2",
                "af": "v4",
            },
        }
        ti = MagicMock()
        ti.name = "flow1"
        ti.traffic_flow_config = MagicMock(bidirectional=False)
        ti.traffic_rate_info = None
        src_ep = MagicMock(port_name="p1", device_group_index=0)
        dst_ep = MagicMock(port_name="p2", device_group_index=0)
        ti.source_endpoints = [src_ep]
        ti.dest_endpoints = [dst_ep]
        flows_mock = MagicMock()
        tgen.config.flows = flows_mock
        tgen._build_explicit_flows([ti], gw_macs={})
        flows_mock.flow.assert_not_called()
        tgen.logger.warning.assert_called()

    def test_get_resolved_gw_macs_parses_arp(self):
        tgen = _create_otg_tgen()
        neighbor = MagicMock()
        neighbor.link_layer_address = "aa:bb:cc:00:00:01"
        neighbor.ipv4_address = "10.0.1.2"
        states_resp = MagicMock()
        states_resp.ipv4_neighbors = [neighbor]
        states_resp.ipv6_neighbors = None
        tgen.api.get_states.return_value = states_resp
        result = tgen._get_resolved_gw_macs()
        self.assertEqual(result["10.0.1.2"], "aa:bb:cc:00:00:01")


# -- Stats pipeline ------------------------------------------------------------


class TestStatsPipeline(unittest.TestCase):
    def test_get_latest_stats_on_demand(self):
        tgen = _create_otg_tgen()
        tgen._capture_thread = None
        fm = MagicMock()
        fm.name = "f1"
        fm.frames_tx = 100
        fm.frames_rx = 95
        fm.loss = 5.0
        resp = MagicMock()
        resp.flow_metrics = [fm]
        tgen.api.get_metrics.return_value = resp
        stats = tgen.get_latest_stats()
        self.assertEqual(len(stats), 1)
        self.assertEqual(stats[0]["identifier"], "f1")
        self.assertEqual(stats[0]["packet_loss_percentage"], 5.0)

    def test_get_latest_stats_from_capture(self):
        tgen = _create_otg_tgen()
        thread = MagicMock()
        thread.is_alive.return_value = True
        tgen._capture_thread = thread
        tgen._captured_stats = {
            100: [{"name": "f1", "frames_tx": 50, "frames_rx": 50, "loss": 0}],
            200: [{"name": "f1", "frames_tx": 100, "frames_rx": 90, "loss": 10}],
        }
        stats = tgen.get_latest_stats(since_time=150)
        self.assertEqual(stats[0]["identifier"], "f1")
        self.assertEqual(stats[0]["packet_loss_percentage"], 10.0)

    def test_get_flow_metrics_computes_loss_when_null(self):
        tgen = _create_otg_tgen()
        fm = MagicMock()
        fm.name = "f1"
        fm.frames_tx = 200
        fm.frames_rx = 180
        fm.loss = None
        resp = MagicMock()
        resp.flow_metrics = [fm]
        tgen.api.get_metrics.return_value = resp
        metrics = tgen.get_flow_metrics()
        self.assertAlmostEqual(metrics[0]["loss"], 10.0)

    def test_check_packet_loss_returns_violations(self):
        tgen = _create_otg_tgen()
        fm1 = MagicMock(name="ok", frames_tx=100, frames_rx=100, loss=0.0)
        fm1.name = "ok"
        fm2 = MagicMock(name="bad", frames_tx=100, frames_rx=90, loss=10.0)
        fm2.name = "bad"
        resp = MagicMock()
        resp.flow_metrics = [fm1, fm2]
        tgen.api.get_metrics.return_value = resp
        violations = tgen.check_packet_loss(max_loss_pct=1.0)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0]["name"], "bad")

    def test_get_traffic_items_returns_names(self):
        tgen = _create_otg_tgen()
        f1 = MagicMock()
        f1.name = "flow_a"
        f2 = MagicMock()
        f2.name = "flow_b"
        tgen.config.flows = [f1, f2]
        self.assertEqual(tgen.get_traffic_items(), ["flow_a", "flow_b"])

    def test_has_traffic_items(self):
        tgen = _create_otg_tgen()
        tgen.config.flows = []
        self.assertFalse(tgen.has_traffic_items())
        f = MagicMock()
        f.name = "f1"
        tgen.config.flows = [f]
        self.assertTrue(tgen.has_traffic_items())


# -- Background capture --------------------------------------------------------


class TestBackgroundCapture(unittest.TestCase):
    def test_start_capture_idempotent(self):
        tgen = _create_otg_tgen()
        thread = MagicMock()
        thread.is_alive.return_value = True
        tgen._capture_thread = thread
        tgen._start_capture()
        tgen.logger.warning.assert_called()

    def test_stop_capture_joins_thread(self):
        tgen = _create_otg_tgen()
        thread = MagicMock()
        thread.is_alive.return_value = True
        tgen._capture_thread = thread
        tgen._stop_capture()
        thread.join.assert_called_once_with(timeout=10)
        self.assertIsNone(tgen._capture_thread)

    def test_capture_skips_when_paused(self):
        tgen = _create_otg_tgen()
        tgen.paused = True
        tgen._capture_stop.set()
        tgen._capture_loop(interval=0.01)
        tgen.api.get_metrics.assert_not_called()

    def test_two_snapshots_within_one_second_are_both_kept(self):
        """A 1.0s capture interval jitters either side of a second boundary.

        Truncating the key to an int makes two polls collide and the later one
        overwrite the earlier, silently losing a sample.
        """
        tgen = _create_otg_tgen()
        tgen.paused = False
        stamps = [10.1, 10.9]

        def fake_get_flow_metrics():
            if len(tgen._captured_stats) >= 1:
                tgen._capture_stop.set()
            return [{"name": "f1", "frames_tx": 10, "frames_rx": 10, "loss": 0.0}]

        with (
            patch.object(tgen, "get_flow_metrics", side_effect=fake_get_flow_metrics),
            patch(
                "taac.ixia.otg_traffic_gen.time.time",
                side_effect=lambda: stamps.pop(0) if stamps else 11.0,
            ),
        ):
            tgen._capture_loop(interval=0)

        self.assertEqual(len(tgen._captured_stats), 2)

    def test_subsecond_snapshot_is_newer_than_subsecond_since_time(self):
        """An int key truncates 10.9 to 10, which then reads as older than 10.5."""
        tgen = _create_otg_tgen()
        tgen.paused = False
        stamps = [10.9]

        def fake_get_flow_metrics():
            tgen._capture_stop.set()
            return [{"name": "f1", "frames_tx": 10, "frames_rx": 9, "loss": 10.0}]

        with (
            patch.object(tgen, "get_flow_metrics", side_effect=fake_get_flow_metrics),
            patch(
                "taac.ixia.otg_traffic_gen.time.time",
                side_effect=lambda: stamps.pop(0) if stamps else 11.0,
            ),
        ):
            tgen._capture_loop(interval=0)

        self.assertTrue(any(ts > 10.5 for ts in tgen._captured_stats))

    def test_capture_survives_api_error(self):
        tgen = _create_otg_tgen()
        tgen.paused = False
        call_count = 0

        def side_effect(*a, **kw):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("refused")
            tgen._capture_stop.set()
            resp = MagicMock()
            resp.flow_metrics = []
            return resp

        tgen.api.get_metrics.side_effect = side_effect
        tgen._capture_loop(interval=0.01)
        self.assertGreaterEqual(call_count, 1)


# -- Backend dispatch in TestSetupOrchestrator --------------------------------


class TestBackendDispatch(unittest.TestCase):
    def _make_orchestrator(self, backend_value=None):
        test_config = MagicMock()
        test_config.endpoints = []
        test_config.traffic_generator_backend = backend_value
        test_config.name = "test"
        test_config.secondary_ixia_profile = None
        with patch("taac.libs.test_setup_orchestrator.TAAC_OSS", True):
            from taac.libs.test_setup_orchestrator import (
                TestSetupOrchestrator,
            )

            orch = TestSetupOrchestrator(
                test_config=test_config,
                logger=MagicMock(),
            )
        return orch

    def test_otg_backend_detection(self):
        self.assertEqual(
            self._make_orchestrator(backend_value=1)._traffic_generator_backend, "otg"
        )

    def test_restpy_backend_default(self):
        self.assertEqual(
            self._make_orchestrator(backend_value=0)._traffic_generator_backend,
            "restpy",
        )

    def test_restpy_when_none(self):
        self.assertEqual(
            self._make_orchestrator(backend_value=None)._traffic_generator_backend,
            "restpy",
        )


# -- OtgTrafficGenerator wrapper -----------------------------------------------


class TestOtgTrafficGeneratorWrapper(unittest.TestCase):
    def _make_endpoint(self, name="dut1", connections=None):
        ep = MagicMock()
        ep.name = name
        ep.direct_ixia_connections = connections or []
        ep.ixia_ports = []
        ep.ixia_needed = False
        return ep

    def _make_connection(self, interface="eth1", chassis_ip=None):
        conn = MagicMock()
        conn.interface = interface
        conn.ixia_chassis_ip = chassis_ip
        return conn

    def test_controller_from_endpoints(self):
        from taac.libs.otg_traffic_generator import (
            OtgTrafficGenerator,
        )

        otg = OtgTrafficGenerator.__new__(OtgTrafficGenerator)
        conn = self._make_connection(chassis_ip="https://otg:8443")
        otg.endpoints = [self._make_endpoint(connections=[conn])]
        self.assertEqual(otg._otg_controller_from_endpoints(), "https://otg:8443")

    def test_controller_none_when_missing(self):
        from taac.libs.otg_traffic_generator import (
            OtgTrafficGenerator,
        )

        otg = OtgTrafficGenerator.__new__(OtgTrafficGenerator)
        conn = self._make_connection(chassis_ip=None)
        otg.endpoints = [self._make_endpoint(connections=[conn])]
        self.assertIsNone(otg._otg_controller_from_endpoints())

    def test_mesh_endpoints(self):
        from taac.libs.otg_traffic_generator import (
            OtgTrafficGenerator,
        )

        otg = OtgTrafficGenerator.__new__(OtgTrafficGenerator)
        conn1 = self._make_connection(interface="eth1")
        conn2 = self._make_connection(interface="eth2")
        otg.endpoints = [self._make_endpoint(name="sw1", connections=[conn1, conn2])]
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(otg._async_build_full_mesh_endpoints())
        finally:
            loop.close()
        self.assertEqual(len(result), 2)


# ===========================================================================
# Step-facing APIs used by the OTG hardening playbooks
# (taac/otg/otg_hardening_playbooks.py).
# ===========================================================================


def _make_flow(name):
    flow = MagicMock()
    flow.name = name
    return flow


def _make_attr(name, value, kind="str"):
    """Build an ixia Attr-alike; AttrValue is a union, so only one arm is set."""
    attr = MagicMock()
    attr.name = name
    attr.value = MagicMock()
    for arm in ("str", "integer", "str_list", "integer_list", "boolean"):
        setattr(attr.value, arm, None)
    setattr(attr.value, kind, value)
    return attr


def _make_field(regex, attrs):
    field = MagicMock()
    field.query.regex = regex
    field.attrs = attrs
    return field


def _make_header(stack_regex, fields):
    header = MagicMock()
    header.query.regex = stack_regex
    header.fields = fields
    return header


# -- device group naming ------------------------------------------------------


class TestDeviceGroupNaming(unittest.TestCase):
    """Playbooks address device groups by regex, so names must be honored."""

    def _dg(self, device_group_name=None, tag_name=None):
        dg = MagicMock()
        dg.device_group_name = device_group_name
        dg.tag_name = tag_name
        return dg

    def test_device_group_name_wins(self):
        tgen = _create_otg_tgen()
        name = tgen._device_group_name(
            "p1", self._dg(device_group_name="ECMP_2_PORT1", tag_name="TAG"), 2
        )
        self.assertEqual(name, "ECMP_2_PORT1")

    def test_tag_name_is_fallback(self):
        tgen = _create_otg_tgen()
        name = tgen._device_group_name("p1", self._dg(tag_name="ECMP_1"), 1)
        self.assertEqual(name, "ECMP_1")

    def test_positional_fallback_when_unset(self):
        tgen = _create_otg_tgen()
        name = tgen._device_group_name("p1", self._dg(), 3)
        self.assertEqual(name, "p1_DG3")

    def test_non_string_treated_as_unset(self):
        """Both thrift fields are `optional string`; anything else is unset."""
        tgen = _create_otg_tgen()
        dg = MagicMock()  # auto-attributes are MagicMocks, not strings
        self.assertEqual(tgen._device_group_name("p1", dg, 0), "p1_DG0")


# -- toggle_device_groups -----------------------------------------------------


class TestToggleDeviceGroups(unittest.TestCase):
    def setUp(self):
        self.tgen = _create_otg_tgen()
        self.tgen._device_group_keys = {
            "NO_PACKET_LOSS_EXPECTED_PORT1": ("p1", 0),
            "ECMP_1_PORT1": ("p1", 1),
            "ECMP_2_PORT1": ("p1", 2),
            "ECMP_2_PORT2": ("p2", 2),
        }
        self.tgen._device_group_info = {
            ("p1", 0): {"peers": ["dg0_bgp_v4", "dg0_bgp_v6"]},
            ("p1", 1): {"peers": ["ecmp1_p1_bgp_v6"]},
            ("p1", 2): {"peers": ["ecmp2_p1_bgp_v6"]},
            ("p2", 2): {"peers": ["ecmp2_p2_bgp_v6"]},
        }

    def _peer_state_calls(self):
        """Extract (peer_names, state) from each set_control_state call."""
        calls = []
        for call in self.tgen.api.set_control_state.call_args_list:
            cs = call.args[0]
            calls.append((cs.protocol.bgp.peers.peer_names, cs.protocol.bgp.peers.state))
        return calls

    def test_matches_both_ports_and_brings_peers_up(self):
        self.tgen.toggle_device_groups(
            enable=True,
            device_group_name_regex="ECMP_2",
            sleep_time_before_applying_change=0,
        )
        calls = self._peer_state_calls()
        self.assertEqual(len(calls), 1)
        peer_names, _ = calls[0]
        self.assertEqual(
            sorted(peer_names), ["ecmp2_p1_bgp_v6", "ecmp2_p2_bgp_v6"]
        )

    def test_multiplied_group_sends_each_peer_once(self):
        """A multiplier expands one group into N device names sharing one key.

        `_device_group_keys` is keyed per device, but the info behind that key
        holds all N peers — so resolving per device name yields N copies of an
        N-element list. Harmless at multiplier 1; at the documented
        LICENSED_ECMP_MULTIPLIERS of (8, 24) that is 576 entries in a single
        control_state call, and a wrong peer count in the log.
        """
        self.tgen._device_group_keys.update(
            {
                "ECMP_2_PORT1_1": ("p1", 3),
                "ECMP_2_PORT1_2": ("p1", 3),
                "ECMP_2_PORT1_3": ("p1", 3),
            }
        )
        self.tgen._device_group_info[("p1", 3)] = {
            "peers": ["m1_bgp_v6", "m2_bgp_v6", "m3_bgp_v6"]
        }
        self.tgen.toggle_device_groups(
            enable=True,
            device_group_name_regex="ECMP_2_PORT1_",
            sleep_time_before_applying_change=0,
        )
        peer_names, _ = self._peer_state_calls()[0]
        self.assertEqual(
            sorted(peer_names), ["m1_bgp_v6", "m2_bgp_v6", "m3_bgp_v6"]
        )

    def test_disable_uses_down_state(self):
        self.tgen.toggle_device_groups(
            enable=False,
            device_group_name_regex="ECMP_2_PORT1",
            sleep_time_before_applying_change=0,
        )
        calls = self._peer_state_calls()
        self.assertEqual(len(calls), 1)
        peers = self.tgen.api.control_state.return_value.protocol.bgp.peers
        self.assertIs(calls[0][1], peers.DOWN)

    def test_enable_uses_up_state(self):
        self.tgen.toggle_device_groups(
            enable=True,
            device_group_name_regex="ECMP_2_PORT1",
            sleep_time_before_applying_change=0,
        )
        peers = self.tgen.api.control_state.return_value.protocol.bgp.peers
        self.assertIs(self._peer_state_calls()[0][1], peers.UP)

    def test_does_not_repush_config(self):
        """A set_config would restart protocols and flap unrelated sessions."""
        self.tgen.toggle_device_groups(
            enable=True,
            device_group_name_regex="ECMP_2",
            sleep_time_before_applying_change=0,
        )
        self.tgen.api.set_config.assert_not_called()

    def test_exception_device_groups_excluded(self):
        self.tgen.toggle_device_groups(
            enable=True,
            device_group_name_regex="ECMP_2",
            exception_device_groups=["PORT2"],
            sleep_time_before_applying_change=0,
        )
        peer_names, _ = self._peer_state_calls()[0]
        self.assertEqual(peer_names, ["ecmp2_p1_bgp_v6"])

    def test_no_match_is_a_warning_not_an_error(self):
        self.tgen.toggle_device_groups(
            enable=True,
            device_group_name_regex="NO_SUCH_GROUP",
            sleep_time_before_applying_change=0,
        )
        self.tgen.api.set_control_state.assert_not_called()
        self.tgen.logger.warning.assert_called()

    def test_group_without_bgp_peers_is_a_warning(self):
        self.tgen._device_group_info[("p1", 2)] = {"peers": []}
        self.tgen.toggle_device_groups(
            enable=True,
            device_group_name_regex="ECMP_2_PORT1",
            sleep_time_before_applying_change=0,
        )
        self.tgen.api.set_control_state.assert_not_called()
        self.tgen.logger.warning.assert_called()

    def test_invalid_regex_raises(self):
        with self.assertRaises(ValueError):
            self.tgen.toggle_device_groups(
                enable=True,
                device_group_name_regex="ECMP_2(",
                sleep_time_before_applying_change=0,
            )


# -- enable_traffic -----------------------------------------------------------


class TestEnableTrafficPublicApi(unittest.TestCase):
    def setUp(self):
        self.tgen = _create_otg_tgen()
        # enable_traffic issues two _transmit calls (start matched, stop the
        # rest).  A shared control_state mock would show only the last
        # assignment for both, so hand out a fresh one per call.
        self.tgen.api.control_state.side_effect = lambda: MagicMock()
        self.tgen.config.flows = [
            _make_flow("NO_PACKET_LOSS_EXPECTED_V4_p1_0_to_0"),
            _make_flow("NO_PACKET_LOSS_EXPECTED_V6_p1_0_to_0"),
            _make_flow("HIGH_QUEUE_BGP_CP_TRAFFIC_p1_0_to_0"),
        ]

    def _transmit_calls(self):
        """(flow_names, state) per set_control_state call."""
        out = []
        for call in self.tgen.api.set_control_state.call_args_list:
            cs = call.args[0]
            out.append(
                (
                    cs.traffic.flow_transmit.flow_names,
                    cs.traffic.flow_transmit.state,
                )
            )
        return out

    def test_enabling_everything_restarts_the_cp_flood(self):
        """Characterises the trap: regexes=None does NOT mean "restore".

        It clears the disabled set *and* transmit-starts every name it matched,
        the CP flood included. Anything wanting "put the measured path back"
        must name the measured flows, so the disable-non-matching branch stops
        the flood instead of restarting it.
        """
        self.tgen.enable_traffic(regexes=None, enable=True)
        started = [
            names for names, state in self._transmit_calls() if names
        ]
        self.assertIn("HIGH_QUEUE_BGP_CP_TRAFFIC_p1_0_to_0", started[0])

    def test_restoring_the_measured_path_stops_the_cp_flood(self):
        """Naming the measured prefix leaves the flood explicitly disabled."""
        self.tgen.enable_traffic(
            regexes=["NO_PACKET_LOSS_EXPECTED"], enable=True
        )
        self.assertEqual(
            self.tgen._disabled_flows, {"HIGH_QUEUE_BGP_CP_TRAFFIC_p1_0_to_0"}
        )
        calls = self._transmit_calls()
        stopped = [names for names, state in calls if names and "HIGH" in names[0]]
        self.assertTrue(stopped, "the flood must be transmit-stopped, not left running")

    def test_enabling_one_flow_disables_the_rest(self):
        """Matches restpy: enabling a subset stops every non-matching item."""
        self.tgen.enable_traffic(regexes=["HIGH_QUEUE_BGP_CP_TRAFFIC"], enable=True)
        self.assertEqual(
            self.tgen._disabled_flows,
            {
                "NO_PACKET_LOSS_EXPECTED_V4_p1_0_to_0",
                "NO_PACKET_LOSS_EXPECTED_V6_p1_0_to_0",
            },
        )

    def test_enabling_transmits_matched_and_stops_non_matching(self):
        self.tgen.enable_traffic(regexes=["HIGH_QUEUE_BGP_CP_TRAFFIC"], enable=True)
        calls = self._transmit_calls()
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][0], ["HIGH_QUEUE_BGP_CP_TRAFFIC_p1_0_to_0"])
        self.assertEqual(
            calls[1][0],
            [
                "NO_PACKET_LOSS_EXPECTED_V4_p1_0_to_0",
                "NO_PACKET_LOSS_EXPECTED_V6_p1_0_to_0",
            ],
        )

    def test_disabling_leaves_other_flows_alone(self):
        self.tgen.enable_traffic(regexes=["HIGH_QUEUE_BGP_CP_TRAFFIC"], enable=False)
        self.assertEqual(
            self.tgen._disabled_flows, {"HIGH_QUEUE_BGP_CP_TRAFFIC_p1_0_to_0"}
        )
        calls = self._transmit_calls()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], ["HIGH_QUEUE_BGP_CP_TRAFFIC_p1_0_to_0"])

    def test_does_not_repush_config(self):
        """The CPU-queue test asserts BGP sessions did NOT flap; a set_config
        here would restart protocols and fail that check spuriously."""
        self.tgen.enable_traffic(regexes=["HIGH_QUEUE_BGP_CP_TRAFFIC"], enable=True)
        self.tgen.api.set_config.assert_not_called()

    def test_prepare_traffic_skips_repush_after_enable_traffic(self):
        """End-to-end of the above: the serialized config is unchanged, so
        _prepare_traffic() short-circuits."""
        self.tgen.config.serialize.return_value = "SERIALIZED"
        self.tgen._last_pushed_config = "SERIALIZED"
        self.tgen.enable_traffic(regexes=["HIGH_QUEUE_BGP_CP_TRAFFIC"], enable=True)
        self.tgen._prepare_traffic()
        self.tgen.api.set_config.assert_not_called()

    def test_none_regex_targets_all_flows(self):
        self.tgen.enable_traffic(regexes=None, enable=False)
        self.assertEqual(len(self.tgen._disabled_flows), 3)

    def test_no_match_warns(self):
        self.tgen.enable_traffic(regexes=["NOPE"], enable=True)
        self.tgen.logger.warning.assert_called()


# -- packet header translation ------------------------------------------------


class TestPacketHeaderTranslation(unittest.TestCase):
    def setUp(self):
        self.tgen = _create_otg_tgen()
        self.flow = MagicMock()

    def test_single_value_and_reference_resolved_upstream(self):
        """References are already flattened into attrs by the pipeline."""
        headers = [
            _make_header(
                "^ethernet$",
                [
                    _make_field(
                        "Destination MAC Address",
                        [
                            _make_attr("ValueType", "increment"),
                            _make_attr("StepValue", "00:00:00:00:00:00"),
                            _make_attr("CountValue", 1, kind="integer"),
                            _make_attr("StartValue", "02:00:00:00:00:01"),
                        ],
                    ),
                    _make_field(
                        "Source MAC Address",
                        [_make_attr("SingleValue", "00:00:00:11:22:33")],
                    ),
                ],
            ),
        ]
        stacks = self.tgen.apply_packet_headers(self.flow, headers)
        eth = stacks["ethernet"]
        self.assertEqual(eth.dst.value, "02:00:00:00:00:01")
        self.assertEqual(eth.src.value, "00:00:00:11:22:33")

    def test_tcp_ports(self):
        headers = [
            _make_header(
                "^tcp$",
                [
                    _make_field(
                        "TCP-Dest-Port",
                        [_make_attr("SingleValue", 179, kind="integer")],
                    ),
                ],
            ),
        ]
        stacks = self.tgen.apply_packet_headers(self.flow, headers)
        self.assertEqual(stacks["tcp"].dst_port.value, 179)

    def test_degenerate_increment_collapses_to_fixed_value(self):
        """Count 1 with a zero step is a fixed value; emit it as one."""
        headers = [
            _make_header(
                "^ipv4$",
                [
                    _make_field(
                        "Destination Address",
                        [
                            _make_attr("ValueType", "increment"),
                            _make_attr("StepValue", "0.0.0.0"),
                            _make_attr("CountValue", 1, kind="integer"),
                            _make_attr("StartValue", "10.0.1.2"),
                        ],
                    ),
                ],
            ),
        ]
        stacks = self.tgen.apply_packet_headers(self.flow, headers)
        self.assertEqual(stacks["ipv4"].dst.value, "10.0.1.2")

    def test_real_increment_is_preserved(self):
        headers = [
            _make_header(
                "^ipv4$",
                [
                    _make_field(
                        "Source Address",
                        [
                            _make_attr("ValueType", "increment"),
                            _make_attr("StepValue", "0.0.0.1"),
                            _make_attr("CountValue", 10, kind="integer"),
                            _make_attr("StartValue", "10.0.1.1"),
                        ],
                    ),
                ],
            ),
        ]
        stacks = self.tgen.apply_packet_headers(self.flow, headers)
        src = stacks["ipv4"].src
        self.assertEqual(src.increment.start, "10.0.1.1")
        self.assertEqual(src.increment.step, "0.0.0.1")
        self.assertEqual(src.increment.count, 10)

    def test_value_list_of_one_becomes_a_value(self):
        headers = [
            _make_header(
                "^tcp$",
                [
                    _make_field(
                        "TCP-Source-Port",
                        [
                            _make_attr("ValueType", "valueList"),
                            _make_attr("ValueList", [179], kind="integer_list"),
                        ],
                    ),
                ],
            ),
        ]
        stacks = self.tgen.apply_packet_headers(self.flow, headers)
        self.assertEqual(stacks["tcp"].src_port.value, 179)

    def test_value_list_of_many_becomes_values(self):
        headers = [
            _make_header(
                "^tcp$",
                [
                    _make_field(
                        "TCP-Source-Port",
                        [
                            _make_attr("ValueType", "valueList"),
                            _make_attr(
                                "ValueList", [179, 180], kind="integer_list"
                            ),
                        ],
                    ),
                ],
            ),
        ]
        stacks = self.tgen.apply_packet_headers(self.flow, headers)
        self.assertEqual(stacks["tcp"].src_port.values, [179, 180])

    def test_unsupported_stack_raises_naming_it(self):
        headers = [_make_header("^mpls$", [])]
        with self.assertRaises(NotImplementedError) as ctx:
            self.tgen.apply_packet_headers(self.flow, headers)
        self.assertIn("mpls", str(ctx.exception))

    def test_unsupported_field_raises_naming_it(self):
        headers = [
            _make_header(
                "^ethernet$",
                [_make_field("Ethernet-Type", [_make_attr("SingleValue", 1)])],
            ),
        ]
        with self.assertRaises(NotImplementedError) as ctx:
            self.tgen.apply_packet_headers(self.flow, headers)
        self.assertIn("Ethernet-Type", str(ctx.exception))

    def test_unsupported_value_type_raises(self):
        headers = [
            _make_header(
                "^ethernet$",
                [
                    _make_field(
                        "Source MAC Address",
                        [_make_attr("ValueType", "random")],
                    )
                ],
            ),
        ]
        with self.assertRaises(NotImplementedError) as ctx:
            self.tgen.apply_packet_headers(self.flow, headers)
        self.assertIn("random", str(ctx.exception))

    def test_increment_without_start_raises(self):
        headers = [
            _make_header(
                "^ethernet$",
                [
                    _make_field(
                        "Source MAC Address",
                        [_make_attr("ValueType", "increment")],
                    )
                ],
            ),
        ]
        with self.assertRaises(NotImplementedError):
            self.tgen.apply_packet_headers(self.flow, headers)


# -- QoS / DSCP ---------------------------------------------------------------


class TestFlowQos(unittest.TestCase):
    def _ti(self, dscp):
        ti = MagicMock()
        ti.qos_config.dscp_value = dscp
        return ti

    def test_dscp_on_ipv4_uses_phb(self):
        tgen = _create_otg_tgen()
        stacks = {"ipv4": MagicMock()}
        tgen._apply_flow_qos(stacks, self._ti(48))
        self.assertEqual(stacks["ipv4"].priority.dscp.phb.value, 48)

    def test_dscp_on_ipv6_shifts_into_traffic_class(self):
        tgen = _create_otg_tgen()
        stacks = {"ipv6": MagicMock()}
        tgen._apply_flow_qos(stacks, self._ti(48))
        self.assertEqual(stacks["ipv6"].traffic_class.value, 48 << 2)

    def test_no_qos_config_is_a_noop(self):
        """A flow without qos_config must keep snappi's default priority."""
        tgen = _create_otg_tgen()
        ti = MagicMock()
        ti.qos_config = None
        ipv4 = MagicMock()
        sentinel = ipv4.priority.dscp.phb.value
        tgen._apply_flow_qos({"ipv4": ipv4}, ti)
        self.assertIs(ipv4.priority.dscp.phb.value, sentinel)

    def test_non_integer_dscp_is_a_noop(self):
        """qos_config is optional thrift; a non-int dscp_value means unset."""
        tgen = _create_otg_tgen()
        ti = MagicMock()  # dscp_value auto-mocks to a MagicMock, not an int
        ipv4 = MagicMock()
        sentinel = ipv4.priority.dscp.phb.value
        tgen._apply_flow_qos({"ipv4": ipv4}, ti)
        self.assertIs(ipv4.priority.dscp.phb.value, sentinel)

    def test_dscp_without_l3_header_warns(self):
        tgen = _create_otg_tgen()
        tgen._apply_flow_qos({"ethernet": MagicMock()}, self._ti(48))
        tgen.logger.warning.assert_called()

# -- BGP update sequence (raw UPDATE replay) ----------------------------------


class _ThriftLikeList(collections.abc.Sequence):
    """Stands in for thrift.python.types.List, which is a Sequence but NOT a
    list or tuple.  An isinstance(x, (list, tuple)) guard silently drops it —
    that bug shipped once already, in the packet_headers path."""

    def __init__(self, items):
        self._items = list(items)

    def __getitem__(self, i):
        return self._items[i]

    def __len__(self):
        return len(self._items)


def _make_update_entry(update_bytes, time_gap_ms=0):
    entry = MagicMock()
    entry.update_bytes = update_bytes
    entry.time_gap_ms = time_gap_ms
    return entry


def _make_update_sequence(entries, container=list):
    seq = MagicMock()
    seq.updates = container(entries)
    return seq


class TestNonEmptySequence(unittest.TestCase):
    """Guards the helper both isinstance bugs came down to."""

    def test_accepts_list_and_tuple(self):
        self.assertTrue(_nonempty_sequence([1]))
        self.assertTrue(_nonempty_sequence((1,)))

    def test_accepts_a_thrift_style_sequence(self):
        self.assertTrue(_nonempty_sequence(_ThriftLikeList([1])))

    def test_rejects_empty(self):
        self.assertFalse(_nonempty_sequence([]))
        self.assertFalse(_nonempty_sequence(_ThriftLikeList([])))

    def test_rejects_none_and_mocks(self):
        self.assertFalse(_nonempty_sequence(None))
        self.assertFalse(_nonempty_sequence(MagicMock()))

    def test_rejects_strings(self):
        """str is a Sequence; treating one as a list of fields would be wrong."""
        self.assertFalse(_nonempty_sequence("abc"))
        self.assertFalse(_nonempty_sequence(b"abc"))


class TestBuildBgpUpdateSequence(unittest.TestCase):
    def setUp(self):
        self.tgen = _create_otg_tgen()
        self.peer = MagicMock()

    def _replayed(self):
        """(update_bytes, time_gap) for each replayed entry, in order."""
        calls = self.peer.replay_updates.raw_bytes.updates.oneupdatereplay
        out = []
        for c in calls.return_value.__getitem__.call_args_list:
            pass
        # oneupdatereplay()[-1] returns the same mock each call, so read the
        # recorded assignments instead.
        return out

    def test_sets_raw_bytes_choice(self):
        seq = _make_update_sequence([_make_update_entry("ffab")])
        self.tgen._build_bgp_update_sequence(self.peer, seq, "peer1")
        self.assertEqual(self.peer.replay_updates.choice, "raw_bytes")

    def test_creates_one_entry_per_update(self):
        seq = _make_update_sequence(
            [_make_update_entry("aa"), _make_update_entry("bb"), _make_update_entry("cc")]
        )
        self.tgen._build_bgp_update_sequence(self.peer, seq, "peer1")
        self.assertEqual(
            self.peer.replay_updates.raw_bytes.updates.oneupdatereplay.call_count, 3
        )

    def test_works_with_a_thrift_style_list(self):
        """Regression guard: thrift lists are not list/tuple instances."""
        seq = _make_update_sequence(
            [_make_update_entry("aa")], container=_ThriftLikeList
        )
        self.tgen._build_bgp_update_sequence(self.peer, seq, "peer1")
        self.assertEqual(
            self.peer.replay_updates.raw_bytes.updates.oneupdatereplay.call_count, 1
        )

    def test_last_entry_values_are_applied(self):
        seq = _make_update_sequence([_make_update_entry("dead", time_gap_ms=250)])
        self.tgen._build_bgp_update_sequence(self.peer, seq, "peer1")
        one = self.peer.replay_updates.raw_bytes.updates.oneupdatereplay.return_value[-1]
        self.assertEqual(one.update_bytes, "dead")
        self.assertEqual(one.time_gap, 250)

    def test_missing_time_gap_defaults_to_zero(self):
        entry = MagicMock()
        entry.update_bytes = "beef"
        entry.time_gap_ms = None
        self.tgen._build_bgp_update_sequence(
            self.peer, _make_update_sequence([entry]), "peer1"
        )
        one = self.peer.replay_updates.raw_bytes.updates.oneupdatereplay.return_value[-1]
        self.assertEqual(one.time_gap, 0)

    def test_no_sequence_is_a_noop(self):
        self.tgen._build_bgp_update_sequence(self.peer, None, "peer1")
        self.peer.replay_updates.raw_bytes.updates.oneupdatereplay.assert_not_called()

    def test_empty_sequence_is_a_noop(self):
        self.tgen._build_bgp_update_sequence(
            self.peer, _make_update_sequence([]), "peer1"
        )
        self.peer.replay_updates.raw_bytes.updates.oneupdatereplay.assert_not_called()

    def test_entry_without_bytes_raises(self):
        """Only the raw-bytes arm is wired; a structured entry must not be
        silently dropped, which would send nothing and still report green."""
        entry = MagicMock()
        entry.update_bytes = None
        with self.assertRaises(ValueError):
            self.tgen._build_bgp_update_sequence(
                self.peer, _make_update_sequence([entry]), "peer1"
            )

    def test_warns_when_snappi_lacks_replay_updates(self):
        """Older snappi has no peer.replay_updates; warn rather than crash."""
        peer = MagicMock(spec=["v4_routes"])
        self.tgen._build_bgp_update_sequence(
            peer, _make_update_sequence([_make_update_entry("aa")]), "peer1"
        )
        self.tgen.logger.warning.assert_called()


if __name__ == "__main__":
    unittest.main()


class TestLegacyIpStackRejectsMultiplier(unittest.TestCase):
    """The legacy `ip_addr_1` path predates `multiplier` and ignores `offset`.

    A multiplied group taking it would put N devices on one address: no distinct
    router IDs, no sessions, and nothing in the config that looks wrong. Refusing
    the combination is cheaper than the latent bug, and it is unreachable in the
    current configs so the raise costs nothing today.
    """

    def _legacy_ip_cfg(self):
        cfg = MagicMock(
            spec=["ip_addr_1", "ipv4_addresses_config", "ipv6_addresses_config"]
        )
        cfg.ipv4_addresses_config = None
        cfg.ipv6_addresses_config = None
        addr_info = MagicMock(spec=["ipv4_addr_info", "ipv6_addr_info"])
        v4 = MagicMock()
        v4.starting_ip = "10.0.1.1"
        v4.gateway_starting_ip = "10.0.1.2"
        v4.subnet_mask = 24
        v4.ip_obj_name = None
        addr_info.ipv4_addr_info = v4
        addr_info.ipv6_addr_info = None
        cfg.ip_addr_1 = addr_info
        return cfg

    def test_offset_zero_still_works(self):
        tgen = _create_otg_tgen()
        eth = MagicMock()
        tgen._build_ip_stack(eth, "dev", self._legacy_ip_cfg(), offset=0)
        eth.ipv4_addresses.ipv4.assert_called()

    def test_a_nonzero_offset_raises(self):
        tgen = _create_otg_tgen()
        with self.assertRaises(ValueError) as ctx:
            tgen._build_ip_stack(
                MagicMock(), "dev", self._legacy_ip_cfg(), offset=1
            )
        self.assertIn("multiplier", str(ctx.exception).lower())
