# pyre-unsafe
# Copyright (c) Meta Platforms, Inc. and affiliates.
"""Unit tests for OTG traffic generator support."""

import asyncio
import threading
import time
import typing as t
import unittest
from unittest.mock import MagicMock, patch

from taac.ixia.abstract_traffic_generator import AbstractTrafficGenerator


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
):
    dg = MagicMock()
    dg.device_group_index = index
    dg.bgp_config = bgp_config
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
        tgen = OtgTrafficGen.__new__(OtgTrafficGen)
        tgen.logger = MagicMock()
        tgen.ixia_config = kwargs.get("ixia_config", _make_ixia_config())
        tgen._location = kwargs.get("location", "https://localhost:8443")
        tgen.api = mock_api
        tgen.config = mock_config
        tgen._bgp_peer_names = []
        tgen._device_group_info = {}
        tgen.test_case_uuid = None
        tgen.paused = False
        tgen.capturing = False
        tgen._traffic_start_time = 0.0
        tgen._disabled_flows = set()
        tgen._capture_thread = None
        tgen._capture_stop = threading.Event()
        tgen._captured_stats = {}
        tgen._capture_lock = threading.Lock()
        tgen._flow_loss_start = {}
        tgen._flow_loss_accumulated = {}
    return tgen


# -- AbstractTrafficGenerator ABC contract ------------------------------------

class TestAbstractTrafficGeneratorABC(unittest.TestCase):

    def test_cannot_instantiate_abc(self):
        with self.assertRaises(TypeError):
            AbstractTrafficGenerator()

    def test_abc_has_required_methods(self):
        expected = {
            "begin_test_case", "end_test_case",
            "start_traffic", "stop_traffic",
            "get_latest_stats", "clear_traffic_stats",
            "get_traffic_start_time",
            "has_traffic_items", "get_traffic_items",
            "restart_bgp_peers", "find_bgp_peers",
            "tear_down",
        }
        actual = {
            name for name, method in vars(AbstractTrafficGenerator).items()
            if getattr(method, "__isabstractmethod__", False)
        }
        self.assertEqual(actual, expected)

    def test_otg_traffic_gen_implements_abc(self):
        from taac.ixia.otg_traffic_gen import OtgTrafficGen
        self.assertTrue(issubclass(OtgTrafficGen, AbstractTrafficGenerator))


# -- _enable_traffic: regex matching + disabled-set bookkeeping ---------------

class TestEnableTraffic(unittest.TestCase):

    def setUp(self):
        self.tgen = _create_otg_tgen()
        flow_a = MagicMock(); flow_a.name = "routed_flow_p1_0_to_0"
        flow_b = MagicMock(); flow_b.name = "routed_flow_p2_0_to_0"
        flow_c = MagicMock(); flow_c.name = "bgp_flow_1"
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
            "routed_flow_p1_0_to_0", "routed_flow_p2_0_to_0", "bgp_flow_1"
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
        flow = MagicMock(); flow.name = "f1"
        self.tgen.config.flows = [flow]
        before = time.time()
        self.tgen.start_traffic()
        self.assertGreaterEqual(self.tgen.get_traffic_start_time(), before)

    def test_start_skips_when_all_disabled(self):
        flow = MagicMock(); flow.name = "f1"
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
        flow = MagicMock(); flow.name = "flow1"
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
            "p1_DG0_bgp_v4", "p1_DG0_bgp_v6", "p2_DG0_bgp_v4",
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

    def test_restart_string_pattern_coerced_to_list(self):
        self.tgen.restart_bgp_peers(patterns="p2")
        self.assertEqual(self.tgen.api.set_control_state.call_count, 2)

    def test_restart_no_match_warns_without_api_call(self):
        self.tgen.restart_bgp_peers(patterns=["nonexistent"])
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
        pc = _make_port_config("p1", port_location="", chassis_ip="10.0.0.1", slot=2, port=3)
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
            ipv4_start=None, ipv6_start="2001:db8::1", ipv6_gw="2001:db8::2",
        )
        info = self._build(dg)._device_group_info[("p1", 0)]
        self.assertEqual(info["af"], "v6")
        self.assertEqual(info["ip"], "2001:db8::1")



# -- Config builders: flow translation -----------------------------------------

class TestBuildTrafficFlows(unittest.TestCase):

    def _make_traffic_item(self, name="flow1", traffic_type=None, bidir=False,
                           l4_protocol_config=None, rate_info=None,
                           flow_config=None):
        from ixia.ixia import types as ixia_types
        ti = MagicMock()
        ti.name = name
        ti.traffic_type = traffic_type or ixia_types.TrafficType.IPV4
        ti.l4_protocol_config = l4_protocol_config
        ti.traffic_rate_info = rate_info
        ti.traffic_flow_config = flow_config or MagicMock(
            bidirectional=bidir, frame_size=None, transmission_control=None,
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
        pc1 = _make_port_config("p1", device_group_configs=[
            _make_device_group_config(index=0, ipv4_start="10.0.1.1"),
        ])
        pc2 = _make_port_config("p2", device_group_configs=[
            _make_device_group_config(index=0, ipv4_start="10.0.2.1"),
        ])
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
        pc = _make_port_config("p1", device_group_configs=[
            _make_device_group_config(index=0, ipv4_start="10.0.1.1"),
        ])
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
            rate_type=ixia_types.RateType.FRAMES_PER_SECOND, rate_value=1000,
        )
        tgen._configure_flow_rate(flow, ti)
        self.assertEqual(flow.rate.pps, 1000)

    def test_percent(self):
        from ixia.ixia import types as ixia_types
        tgen = _create_otg_tgen()
        flow = MagicMock()
        ti = MagicMock()
        ti.traffic_rate_info = MagicMock(
            rate_type=ixia_types.RateType.PERCENT_LINE_RATE, rate_value=50,
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
                type=ixia_types.FrameSizeType.FIXED, fixed_size=512,
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
                increment_from=64, increment_to=1500, increment_step=100,
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
                duration=30, frame_count=None,
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
                frame_count=5000, duration=None,
            ),
        )
        tgen._configure_flow_duration(flow, ti)
        self.assertEqual(flow.duration.fixed_packets.packets, 5000)


# -- BGP config builders ------------------------------------------------------

class TestBgpConfigBuilders(unittest.TestCase):

    def _make_bgp_peer_config(self, peer_type=None, local_as=65000,
                               local_ip="10.0.1.1", remote_ip="10.0.1.2"):
        from ixia.ixia import types as ixia_types
        cfg = MagicMock()
        cfg.peer_type = peer_type or ixia_types.BgpPeerType.EBGP
        cfg.local_as = local_as
        cfg.local_peer_starting_ip = local_ip
        cfg.remote_peer_starting_ip = remote_ip
        return cfg

    def _make_bgp_info(self, v4_peer_config=None, v6_peer_config=None,
                        v4_prefixes=None, v6_prefixes=None):
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
            peer_type=ixia_types.BgpPeerType.EBGP, local_as=65001,
        )
        bgp_info = self._make_bgp_info(v4_peer_config=peer_cfg)
        tgen._build_bgp_config(device, "p1_DG0", bgp_info)
        self.assertIn("p1_DG0_bgp_v4", tgen._bgp_peer_names)
        peer = device.bgp.ipv4_interfaces.v4interface.return_value[-1].peers.v4peer.return_value[-1]
        self.assertEqual(peer.as_type, "ebgp")
        self.assertEqual(peer.as_number, 65001)

    def test_v6_peer(self):
        from ixia.ixia import types as ixia_types
        tgen = _create_otg_tgen()
        device = MagicMock()
        peer_cfg = self._make_bgp_peer_config(peer_type=ixia_types.BgpPeerType.EBGP)
        bgp_info = self._make_bgp_info(v6_peer_config=peer_cfg)
        tgen._build_bgp_config(device, "p1_DG0", bgp_info)
        self.assertIn("p1_DG0_bgp_v6", tgen._bgp_peer_names)

    def test_ibgp_as_type(self):
        from ixia.ixia import types as ixia_types
        tgen = _create_otg_tgen()
        device = MagicMock()
        peer_cfg = self._make_bgp_peer_config(peer_type=ixia_types.BgpPeerType.IBGP)
        bgp_info = self._make_bgp_info(v4_peer_config=peer_cfg)
        tgen._build_bgp_config(device, "p1_DG0", bgp_info)
        peer = device.bgp.ipv4_interfaces.v4interface.return_value[-1].peers.v4peer.return_value[-1]
        self.assertEqual(peer.as_type, "ibgp")

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
        with patch.object(tgen, "_wait_for_bgp") as mock_wait, \
             patch.object(tgen, "_start_protocols"):
            tgen.setup()
            mock_wait.assert_called_once()
            tgen.api.set_config.assert_called_with(tgen.config)

    def test_explicit_flows_bidirectional(self):
        tgen = _create_otg_tgen()
        tgen._device_group_info = {
            ("p1", 0): {"port": "p1", "dg_idx": 0, "mac": "00:00:01:00:00:01",
                        "ip": "10.0.1.1", "gateway": "10.0.1.2", "af": "v4"},
            ("p2", 0): {"port": "p2", "dg_idx": 0, "mac": "00:00:02:00:00:01",
                        "ip": "10.0.2.1", "gateway": "10.0.2.2", "af": "v4"},
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
            ("p1", 0): {"port": "p1", "dg_idx": 0, "mac": "00:00:01:00:00:01",
                        "ip": "10.0.1.1", "gateway": "10.0.1.2", "af": "v4"},
            ("p2", 0): {"port": "p2", "dg_idx": 0, "mac": "00:00:02:00:00:01",
                        "ip": "10.0.2.1", "gateway": "10.0.2.2", "af": "v4"},
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
        f1 = MagicMock(); f1.name = "flow_a"
        f2 = MagicMock(); f2.name = "flow_b"
        tgen.config.flows = [f1, f2]
        self.assertEqual(tgen.get_traffic_items(), ["flow_a", "flow_b"])

    def test_has_traffic_items(self):
        tgen = _create_otg_tgen()
        tgen.config.flows = []
        self.assertFalse(tgen.has_traffic_items())
        f = MagicMock(); f.name = "f1"
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
        with patch("taac.libs.test_setup_orchestrator.TAAC_OSS", True):
            from taac.libs.test_setup_orchestrator import TestSetupOrchestrator
            orch = TestSetupOrchestrator(
                test_config=test_config, logger=MagicMock(),
            )
        return orch

    def test_otg_backend_detection(self):
        self.assertEqual(self._make_orchestrator(backend_value=1)._traffic_generator_backend, "otg")

    def test_restpy_backend_default(self):
        self.assertEqual(self._make_orchestrator(backend_value=0)._traffic_generator_backend, "restpy")

    def test_restpy_when_none(self):
        self.assertEqual(self._make_orchestrator(backend_value=None)._traffic_generator_backend, "restpy")


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
        from taac.libs.otg_traffic_generator import OtgTrafficGenerator
        otg = OtgTrafficGenerator.__new__(OtgTrafficGenerator)
        conn = self._make_connection(chassis_ip="https://otg:8443")
        otg.endpoints = [self._make_endpoint(connections=[conn])]
        self.assertEqual(otg._otg_controller_from_endpoints(), "https://otg:8443")

    def test_controller_none_when_missing(self):
        from taac.libs.otg_traffic_generator import OtgTrafficGenerator
        otg = OtgTrafficGenerator.__new__(OtgTrafficGenerator)
        conn = self._make_connection(chassis_ip=None)
        otg.endpoints = [self._make_endpoint(connections=[conn])]
        self.assertIsNone(otg._otg_controller_from_endpoints())

    def test_mesh_endpoints(self):
        from taac.libs.otg_traffic_generator import OtgTrafficGenerator
        otg = OtgTrafficGenerator.__new__(OtgTrafficGenerator)
        conn1 = self._make_connection(interface="eth1")
        conn2 = self._make_connection(interface="eth2")
        otg.endpoints = [self._make_endpoint(name="sw1", connections=[conn1, conn2])]
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                otg._async_build_full_mesh_endpoints()
            )
        finally:
            loop.close()
        self.assertEqual(len(result), 2)


if __name__ == "__main__":
    unittest.main()
