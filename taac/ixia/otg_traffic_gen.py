# pyre-unsafe
"""
Idiomatic OTG/snappi traffic generator — implements AbstractTrafficGenerator.

Consumes the same IxiaConfig thrift struct that the restpy path uses, but
translates it to snappi's declarative model (set_config, get_metrics, polling).
"""

import ipaddress
import logging
import re
import threading
import time
import typing as t

try:
    import snappi
except ImportError:
    snappi = None  # type: ignore[assignment]

from ixia.ixia import types as ixia_types
from taac.ixia.abstract_traffic_generator import (
    AbstractTrafficGenerator,
)


def _get_logger() -> logging.Logger:
    logger = logging.getLogger("OtgTrafficGen")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
    return logger


BGP_VERIFY_TIMEOUT = 90
BGP_VERIFY_POLL_INTERVAL = 5
ARP_RESOLVE_TIMEOUT = 30
ARP_RESOLVE_POLL_INTERVAL = 5


class OtgTrafficGen(AbstractTrafficGenerator):
    """
    Idiomatic OTG traffic generator for TAAC tests.

    Port locations come from PortConfig.port_location (set in thrift config).
    When port_location is unset, falls back to PhyPortConfig chassis;slot;port.

    Usage:
        tgen = OtgTrafficGen(ixia_config=cfg, location="https://otg:8443")
        tgen.setup()           # push config, verify connectivity
        tgen.start_traffic()   # start all flows
        ...                    # do disruptive action
        tgen.stop_traffic()    # stop flows
        losses = tgen.check_packet_loss(max_pct=0.0)
        tgen.tear_down()
    """

    def __init__(
        self,
        ixia_config: ixia_types.IxiaConfig,
        location: t.Optional[str] = None,
        chassis_ip: t.Optional[str] = None,
        logger: t.Optional[logging.Logger] = None,
    ) -> None:
        if snappi is None:
            raise ImportError("snappi is not installed. Install with: pip install snappi")

        self.logger = logger or _get_logger()
        self.ixia_config = ixia_config
        self._location = location or chassis_ip or "https://localhost:8443"

        self.api: "snappi.Api" = snappi.api(location=self._location)
        self.config: "snappi.Config" = self.api.config()

        # Built during _build_config
        self._bgp_peer_names: t.List[str] = []
        self._device_group_info: t.Dict[t.Tuple[str, int], t.Dict[str, t.Any]] = {}

        # TaacRunner-facing state
        self.test_case_uuid: t.Optional[str] = None
        self.paused: bool = False
        self.capturing: bool = False
        self._traffic_start_time: float = 0.0
        self._disabled_flows: t.Set[str] = set()

        # Background stats capture
        self._capture_thread: t.Optional[threading.Thread] = None
        self._capture_stop: threading.Event = threading.Event()
        self._captured_stats: t.Dict[int, t.List[t.Dict[str, t.Any]]] = {}
        self._capture_lock: threading.Lock = threading.Lock()

        # Per-flow cumulative loss duration tracking
        self._flow_loss_start: t.Dict[str, t.Optional[float]] = {}
        self._flow_loss_accumulated: t.Dict[str, float] = {}

        self._build_config()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def setup(self, bgp_timeout: int = BGP_VERIFY_TIMEOUT) -> None:
        """Push config, start protocols, verify connectivity.

        BGP configs push once and wait for convergence.
        Non-BGP configs use a two-phase approach: push device groups first
        to resolve ARP, then rebuild flows as explicit port-level frames
        with resolved gateway MACs.
        """
        self.logger.info("[OTG] Pushing configuration...")
        if self._bgp_peer_names:
            self.api.set_config(self.config)
            self._start_protocols()
            self._wait_for_bgp(timeout=bgp_timeout)
        else:
            self._setup_with_explicit_flows()

        self.logger.info("[OTG] Setup complete")

    def _setup_with_explicit_flows(self) -> None:
        """Two-phase setup: resolve ARP first, then rebuild with explicit flows."""
        saved_traffic_items = self.ixia_config.traffic_items or []
        self.config.flows.clear()

        self.logger.info("[OTG] Phase 1: pushing device groups (no flows) for ARP...")
        self.api.set_config(self.config)
        self._start_protocols()
        self._wait_for_arp()

        gw_macs = self._get_resolved_gw_macs()
        if not gw_macs:
            self.logger.warning("[OTG] No gateway MACs resolved, skipping explicit flows")
            return

        self.logger.info(f"[OTG] Phase 2: rebuilding flows with resolved MACs: {gw_macs}")
        self._build_explicit_flows(saved_traffic_items, gw_macs)

        self.api.set_config(self.config)
        self._start_protocols()

    def _get_resolved_gw_macs(self) -> t.Dict[str, str]:
        """Query ARP/ND neighbor state and return {ip: mac} for resolved entries."""
        result: t.Dict[str, str] = {}
        for attr, ip_field, label in [
            ("ipv4_neighbors", "ipv4_address", "ARP"),
            ("ipv6_neighbors", "ipv6_address", "ND"),
        ]:
            try:
                sr = self.api.states_request()
                sr.choice = attr
                getattr(sr, attr).ethernet_names = []
                states = self.api.get_states(sr)
                neighbors = getattr(states, attr, None) if states else None
                if neighbors:
                    for n in neighbors:
                        mac = getattr(n, "link_layer_address", None)
                        if mac:
                            ip_addr = getattr(n, ip_field)
                            result[ip_addr] = mac
                            self.logger.info(
                                f"[OTG]   {label}: {ip_addr} -> {mac}"
                            )
            except Exception as e:
                self.logger.warning(f"[OTG] Failed to query {label} state: {e}")
        return result

    def _build_explicit_flows(
        self,
        traffic_items: t.List,
        gw_macs: t.Dict[str, str],
    ) -> None:
        """Rebuild traffic items as explicit port-level flows with resolved MACs."""
        for ti in traffic_items:
            for src_ep in (ti.source_endpoints or []):
                for dst_ep in (ti.dest_endpoints or []):
                    src = self._device_group_info.get(
                        (src_ep.port_name, src_ep.device_group_index)
                    )
                    dst = self._device_group_info.get(
                        (dst_ep.port_name, dst_ep.device_group_index)
                    )
                    if not src or not dst:
                        continue

                    pairs = [(src, dst)]
                    bidir = getattr(
                        getattr(ti, "traffic_flow_config", None),
                        "bidirectional", False,
                    )
                    if bidir:
                        pairs.append((dst, src))

                    for tx, rx in pairs:
                        tx_gw_mac = gw_macs.get(tx.get("gateway", ""))
                        if not tx_gw_mac:
                            self.logger.warning(
                                f"[OTG] No resolved MAC for gateway {tx.get('gateway')}, "
                                f"skipping flow {ti.name}"
                            )
                            continue

                        flow_name = f"{ti.name or 'flow'}_{tx['port']}_{tx['dg_idx']}_to_{rx['dg_idx']}"
                        flow = self.config.flows.flow(name=flow_name)[-1]
                        flow.tx_rx.port.tx_name = tx["port"]
                        flow.tx_rx.port.rx_names = [rx["port"]]

                        eth = flow.packet.ethernet()[-1]
                        eth.src.value = tx["mac"]
                        eth.dst.value = tx_gw_mac
                        if tx.get("af") == "v6":
                            ip_hdr = flow.packet.ipv6()[-1]
                        else:
                            ip_hdr = flow.packet.ipv4()[-1]
                        ip_hdr.src.value = tx["ip"]
                        ip_hdr.dst.value = rx["ip"]

                        self._configure_flow_rate(flow, ti)
                        self._configure_flow_size(flow, ti)
                        self._configure_flow_duration(flow, ti)
                        flow.metrics.enable = True

                        self.logger.info(
                            f"[OTG]   Explicit flow {flow_name}: "
                            f"{tx['ip']} -> {rx['ip']} via {tx_gw_mac}"
                        )

    def tear_down(self) -> None:
        """Stop capture thread and push empty config to release all resources."""
        self.logger.info("[OTG] Tearing down")
        self._stop_capture()
        try:
            self.api.set_config(snappi.Config())
        except Exception as e:
            self.logger.warning(f"[OTG] Teardown error: {e}")

    # Alias for callers that use the underscore-free name
    teardown = tear_down

    # ------------------------------------------------------------------
    # Test case lifecycle — called by TaacRunner
    # ------------------------------------------------------------------

    def begin_test_case(
        self,
        test_case_uuid: str,
        traffic_regexes: t.Optional[t.List[str]] = None,
    ) -> None:
        self.test_case_uuid = test_case_uuid
        self._flow_loss_start.clear()
        self._flow_loss_accumulated.clear()
        self._enable_traffic(traffic_regexes)
        self._prepare_traffic()
        if self._capture_thread is None or not self._capture_thread.is_alive():
            self._start_capture()
        else:
            self.paused = False

    def end_test_case(
        self,
        traffic_regexes: t.Optional[t.List[str]] = None,
    ) -> None:
        self.paused = True
        self._enable_traffic(traffic_regexes, enable=False)

    # ------------------------------------------------------------------
    # Traffic control — internal helpers + step-facing API
    # ------------------------------------------------------------------

    def _enable_traffic(
        self,
        regexes: t.Optional[t.List[str]] = None,
        enable: bool = True,
    ) -> None:
        """
        Enable or disable flows by regex. Tracks state in _disabled_flows;
        start_traffic() will only transmit enabled flows.
        """
        if regexes is None:
            if enable:
                self._disabled_flows.clear()
            else:
                self._disabled_flows = {f.name for f in self.config.flows}
        else:
            matched: t.Set[str] = set()
            for flow in self.config.flows:
                for regex in regexes:
                    if re.search(regex, flow.name):
                        matched.add(flow.name)
                        break
            if enable:
                self._disabled_flows -= matched
            else:
                self._disabled_flows |= matched

    def _prepare_traffic(self) -> None:
        """
        Finalize traffic config before starting.

        OTG is declarative — re-push config via set_config().
        """
        self.logger.info("[OTG] Preparing traffic (re-pushing config)...")
        self.api.set_config(self.config)

    def start_traffic(self, regenerate_traffic_items: bool = False) -> None:
        """Start enabled flows."""
        enabled = [
            f.name for f in self.config.flows
            if f.name not in self._disabled_flows
        ]
        if not enabled:
            self.logger.info("[OTG] No enabled flows to start")
            return
        self.logger.info(f"[OTG] Starting traffic ({len(enabled)} flows)")
        self._transmit(start=True, flow_names=enabled)
        self._traffic_start_time = time.time()

    def get_traffic_start_time(self) -> float:
        return self._traffic_start_time

    def stop_traffic(self) -> None:
        """Stop all flows."""
        if not self.config.flows:
            return
        self.logger.info("[OTG] Stopping traffic")
        self._transmit(start=False)

    def _transmit(
        self,
        start: bool,
        flow_names: t.Optional[t.List[str]] = None,
    ) -> None:
        cs = self.api.control_state()
        cs.choice = cs.TRAFFIC
        cs.traffic.choice = cs.traffic.FLOW_TRANSMIT
        cs.traffic.flow_transmit.state = (
            cs.traffic.flow_transmit.START if start else cs.traffic.flow_transmit.STOP
        )
        if flow_names is not None:
            cs.traffic.flow_transmit.flow_names = flow_names
        self.api.set_control_state(cs)

    # ------------------------------------------------------------------
    # Protocol control
    # ------------------------------------------------------------------

    def restart_bgp_peers(
        self, patterns: t.Optional[t.Union[str, t.List[str]]] = None
    ) -> None:
        """Stop then start BGP peers matching the pattern(s) (or all)."""
        if isinstance(patterns, str):
            patterns = [patterns]
        matched: t.List[str] = []
        if patterns:
            for p in patterns:
                matched.extend(self._match_bgp_peers(p))
        else:
            matched = list(self._bgp_peer_names)
        if not matched:
            self.logger.warning("[OTG] No BGP peers matched for restart")
            return
        self.logger.info(f"[OTG] Restarting BGP peers: {matched}")
        for state_val in ["DOWN", "UP"]:
            cs = self.api.control_state()
            cs.choice = cs.PROTOCOL
            cs.protocol.choice = cs.protocol.BGP
            cs.protocol.bgp.peers.peer_names = matched
            cs.protocol.bgp.peers.state = getattr(cs.protocol.bgp.peers, state_val)
            self.api.set_control_state(cs)

    def _start_protocols(self) -> None:
        cs = self.api.control_state()
        cs.choice = cs.PROTOCOL
        cs.protocol.choice = cs.protocol.ALL
        cs.protocol.all.state = cs.protocol.all.START
        self.api.set_control_state(cs)

    def _wait_for_arp(self, timeout: int = ARP_RESOLVE_TIMEOUT) -> None:
        """Wait for ARP/ND resolution after protocol start (non-BGP topologies)."""
        has_v4 = any(info["af"] == "v4" and info["ip"] for info in self._device_group_info.values())
        has_v6 = any(info["af"] == "v6" and info["ip"] for info in self._device_group_info.values())
        if not has_v4 and not has_v6:
            return

        label = "/".join(filter(None, ["ARP" if has_v4 else "", "ND" if has_v6 else ""]))
        self.logger.info(f"[OTG] Waiting for {label} resolution (timeout={timeout}s)...")
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                total = resolved_count = 0
                if has_v4:
                    sr = self.api.states_request()
                    sr.choice = sr.IPV4_NEIGHBORS
                    sr.ipv4_neighbors.ethernet_names = []
                    states = self.api.get_states(sr)
                    if states and states.ipv4_neighbors:
                        total += len(states.ipv4_neighbors)
                        resolved_count += sum(
                            1 for n in states.ipv4_neighbors
                            if getattr(n, "link_layer_address", None)
                        )
                if has_v6:
                    sr = self.api.states_request()
                    sr.choice = sr.IPV6_NEIGHBORS
                    sr.ipv6_neighbors.ethernet_names = []
                    states = self.api.get_states(sr)
                    if states and states.ipv6_neighbors:
                        total += len(states.ipv6_neighbors)
                        resolved_count += sum(
                            1 for n in states.ipv6_neighbors
                            if getattr(n, "link_layer_address", None)
                        )
                if total > 0 and resolved_count == total:
                    self.logger.info(
                        f"[OTG] {label} resolved: {resolved_count}/{total} neighbors"
                    )
                    return
                self.logger.info(
                    f"[OTG] {label}: {resolved_count}/{total} resolved, waiting..."
                )
            except Exception as e:
                self.logger.debug(f"[OTG] {label} poll error: {e}")
            time.sleep(ARP_RESOLVE_POLL_INTERVAL)
        self.logger.warning(
            f"[OTG] {label} resolution timeout after {timeout}s, proceeding"
        )

    def _wait_for_bgp(self, timeout: int = BGP_VERIFY_TIMEOUT) -> None:
        self.logger.info(f"[OTG] Verifying BGP sessions (timeout={timeout}s)...")
        deadline = time.time() + timeout
        while time.time() < deadline:
            metrics = self._get_bgp_metrics()
            if metrics and all(m.session_state == "up" for m in metrics):
                self.logger.info(f"[OTG] All {len(metrics)} BGP session(s) up")
                return
            if metrics:
                down = [m.name for m in metrics if m.session_state != "up"]
                self.logger.info(f"[OTG] Waiting for BGP sessions: {down}")
            time.sleep(BGP_VERIFY_POLL_INTERVAL)
        raise TimeoutError(f"BGP sessions not up within {timeout}s")

    def _get_bgp_metrics(self) -> t.List:
        all_metrics = []
        for choice, req_attr, resp_attr in [
            ("bgpv4", "bgpv4", "bgpv4_metrics"),
            ("bgpv6", "bgpv6", "bgpv6_metrics"),
        ]:
            try:
                mr = self.api.metrics_request()
                mr.choice = choice
                getattr(mr, req_attr).peer_names = []
                resp = self.api.get_metrics(mr)
                if resp:
                    metrics = getattr(resp, resp_attr, None)
                    if metrics:
                        all_metrics.extend(metrics)
            except Exception:
                pass
        return all_metrics

    def find_bgp_peers(
        self,
        regex: t.Optional[str] = None,
        ignore_case: bool = False,
    ) -> t.List[str]:
        """Return BGP peer names matching regex (or all). TaacRunner/task API."""
        if not regex:
            return list(self._bgp_peer_names)
        flags = re.IGNORECASE if ignore_case else 0
        return [n for n in self._bgp_peer_names if re.search(regex, n, flags)]

    def _match_bgp_peers(self, pattern: t.Optional[str]) -> t.List[str]:
        if not pattern:
            return list(self._bgp_peer_names)
        return [n for n in self._bgp_peer_names if re.search(pattern, n)]

    # ------------------------------------------------------------------
    # Traffic item queries — TaacRunner / health check API
    # ------------------------------------------------------------------

    def has_traffic_items(self) -> bool:
        return bool(self.config.flows)

    def get_traffic_items(self) -> t.List[str]:
        """Return flow names. OTG returns strings (restpy returns restpy objects)."""
        return [f.name for f in self.config.flows]

    # ------------------------------------------------------------------
    # Stats — on demand + background capture
    # ------------------------------------------------------------------

    def get_flow_metrics(self) -> t.List[t.Dict[str, t.Any]]:
        """Fetch current flow metrics from the OTG controller."""
        mr = self.api.metrics_request()
        mr.flow.flow_names = []
        resp = self.api.get_metrics(mr)
        if not resp or not resp.flow_metrics:
            return []
        results = []
        for fm in resp.flow_metrics:
            tx = int(fm.frames_tx or 0)
            rx = int(fm.frames_rx or 0)
            loss = fm.loss
            if loss is None and tx > 0:
                loss = (tx - rx) / tx * 100.0
            results.append({
                "name": fm.name,
                "frames_tx": tx,
                "frames_rx": rx,
                "loss": loss,
            })
        return results

    def _flow_metrics_to_stats(
        self, metrics: t.List[t.Dict[str, t.Any]]
    ) -> t.List[t.Dict[str, t.Any]]:
        """
        Convert OTG flow metrics to the dict format that health checks expect:
        {identifier, packet_loss_duration, packet_loss_percentage, frame_delta}
        """
        now = time.time()
        stats = []
        for m in metrics:
            name = m["name"]
            tx = int(m.get("frames_tx") or 0)
            rx = int(m.get("frames_rx") or 0)
            loss_pct = float(m["loss"]) if m.get("loss") is not None else 0.0
            accumulated = self._flow_loss_accumulated.get(name, 0.0)
            loss_start = self._flow_loss_start.get(name)
            if loss_start is not None:
                accumulated += now - loss_start
            stats.append({
                "identifier": name,
                "packet_loss_duration": accumulated * 1000.0,
                "packet_loss_percentage": loss_pct,
                "frame_delta": float(tx - rx),
            })
        return stats

    def get_latest_stats(
        self,
        max_timeout_sec: int = 180,
        since_time: float = 0,
    ) -> t.List[t.Dict[str, t.Any]]:
        """
        Return packet loss stats in the format health checks expect.

        If background capture is running, returns the most recent snapshot
        with timestamp > since_time. Otherwise fetches on demand.
        """
        deadline = time.time() + max_timeout_sec

        # Try captured stats first
        while time.time() < deadline:
            with self._capture_lock:
                if self._captured_stats:
                    # Find most recent snapshot after since_time
                    for ts in reversed(sorted(self._captured_stats.keys())):
                        if ts > since_time:
                            return self._flow_metrics_to_stats(
                                self._captured_stats[ts]
                            )
            # If no capture thread, fetch directly
            if self._capture_thread is None or not self._capture_thread.is_alive():
                return self._flow_metrics_to_stats(self.get_flow_metrics())
            time.sleep(0.5)

        # Timeout — fetch directly as fallback
        return self._flow_metrics_to_stats(self.get_flow_metrics())

    def clear_traffic_stats(self) -> None:
        """Clear captured stats. Called by health checks between measurements."""
        with self._capture_lock:
            self._captured_stats.clear()
        self._flow_loss_start.clear()
        self._flow_loss_accumulated.clear()

    def check_packet_loss(
        self, max_loss_pct: float = 0.0
    ) -> t.List[t.Dict[str, t.Any]]:
        """
        Return a list of violations — flows exceeding the loss threshold.
        Empty list means all flows pass.
        """
        violations = []
        for m in self.get_flow_metrics():
            loss = float(m["loss"]) if m["loss"] is not None else 0.0
            if loss > max_loss_pct:
                violations.append({
                    "name": m["name"],
                    "loss_pct": loss,
                    "frames_tx": m["frames_tx"],
                    "frames_rx": m["frames_rx"],
                })
        return violations

    # ------------------------------------------------------------------
    # Background capture — start/stop
    # ------------------------------------------------------------------

    def _start_capture(self, interval: float = 1.0) -> None:
        if self._capture_thread is not None and self._capture_thread.is_alive():
            self.logger.warning("[OTG] Capture already running")
            return

        self.paused = False
        self._capture_stop.clear()
        self._capture_thread = threading.Thread(
            target=self._capture_loop,
            args=(interval,),
            daemon=True,
            name="otg-stats-capture",
        )
        self._capture_thread.start()
        self.logger.info(
            f"[OTG] Background stats capture started (interval={interval}s)"
        )

    def _stop_capture(self) -> None:
        if self._capture_thread is None or not self._capture_thread.is_alive():
            return
        self._capture_stop.set()
        self._capture_thread.join(timeout=10)
        self._capture_thread = None
        self.capturing = False
        self.logger.info(
            f"[OTG] Background stats capture stopped "
            f"({len(self._captured_stats)} snapshots)"
        )

    def _capture_loop(self, interval: float) -> None:
        """Background thread target: poll flow metrics until stopped."""
        while not self._capture_stop.is_set():
            try:
                if not self.paused:
                    metrics = self.get_flow_metrics()
                    if metrics:
                        ts = time.time()
                        self._update_flow_loss_state(metrics, ts)
                        with self._capture_lock:
                            self._captured_stats[int(ts)] = metrics
                        for m in metrics:
                            self.logger.info(
                                f"[OTG] {m['name']}: "
                                f"tx={m['frames_tx']} rx={m['frames_rx']} "
                                f"loss={m['loss']}%"
                            )
            except Exception as e:
                self.logger.warning(f"[OTG] Stats capture error: {e}")
            self._capture_stop.wait(interval)

    def _update_flow_loss_state(
        self, metrics: t.List[t.Dict[str, t.Any]], ts: float
    ) -> None:
        """Track per-flow cumulative loss duration to match restpy chassis semantics."""
        for m in metrics:
            name = m["name"]
            tx = int(m.get("frames_tx") or 0)
            rx = int(m.get("frames_rx") or 0)
            is_losing = tx > 0 and rx < tx

            if is_losing and self._flow_loss_start.get(name) is None:
                self._flow_loss_start[name] = ts
            elif not is_losing and self._flow_loss_start.get(name) is not None:
                elapsed = ts - self._flow_loss_start[name]
                self._flow_loss_accumulated[name] = (
                    self._flow_loss_accumulated.get(name, 0.0) + elapsed
                )
                self._flow_loss_start[name] = None

    # ==================================================================
    # Config builders — translate Thrift IxiaConfig → snappi Config
    # ==================================================================

    def _build_config(self) -> None:
        self._build_ports()
        self._build_devices_and_bgp()
        self._build_traffic_flows()

    def _build_ports(self) -> None:
        for port_cfg in self.ixia_config.port_configs:
            port_name = port_cfg.port_name
            if getattr(port_cfg, "port_location", None):
                location = port_cfg.port_location
            else:
                phy = port_cfg.phy_port_config
                location = f"{phy.chassis_ip};{phy.slot_number};{phy.port_number}"
            self.config.ports.port(name=port_name, location=location)
            self.logger.info(f"[OTG]   Port {port_name} -> {location}")

    def _build_devices_and_bgp(self) -> None:
        for port_cfg in self.ixia_config.port_configs:
            port_name = port_cfg.port_name
            if getattr(port_cfg, "bgp_config_info", None):
                self._build_bgp_on_port(port_name, port_cfg)
            if port_cfg.device_group_configs:
                for dg_cfg in port_cfg.device_group_configs:
                    self._build_device_group(port_name, dg_cfg)

    def _build_device_group(self, port_name, dg_cfg) -> None:
        dg_index = dg_cfg.device_group_index
        device_name = f"{port_name}_DG{dg_index}"
        device = self.config.devices.device(name=device_name)[-1]

        port_idx = next(
            (i for i, p in enumerate(self.ixia_config.port_configs)
             if p.port_name == port_name), 0
        )
        mac = f"00:00:{port_idx + 1:02x}:00:00:{dg_index + 1:02x}"
        eth = device.ethernets.ethernet(name=f"{device_name}_eth")[-1]
        eth.connection.port_name = port_name
        eth.mac = mac

        ip = gateway = ""
        af = "v4"
        ip_cfg = dg_cfg.ip_addresses_config
        if ip_cfg:
            self._build_ip_stack(eth, device_name, ip_cfg)
            if ip_cfg.ipv4_addresses_config:
                ip = ip_cfg.ipv4_addresses_config.starting_ip
                gateway = ip_cfg.ipv4_addresses_config.gateway_starting_ip
            elif ip_cfg.ipv6_addresses_config:
                af = "v6"
                ip = ip_cfg.ipv6_addresses_config.starting_ip
                gateway = ip_cfg.ipv6_addresses_config.gateway_starting_ip

        self._device_group_info[(port_name, dg_index)] = {
            "port": port_name,
            "dg_idx": dg_index,
            "mac": mac,
            "ip": ip,
            "gateway": gateway,
            "af": af,
        }

        if dg_cfg.bgp_config:
            self._build_bgp_config(device, device_name, dg_cfg.bgp_config)

    def _build_bgp_on_port(self, port_name, port_cfg) -> None:
        bgp_info = getattr(port_cfg, "bgp_config_info", None)
        if not bgp_info:
            return
        device_name = f"{port_name}_PORT"
        device = self.config.devices.device(name=device_name)[-1]

        eth = device.ethernets.ethernet(name=f"{device_name}_eth")[-1]
        eth.connection.port_name = port_name
        eth.mac = "00:00:01:00:00:01"

        ip_addresses = getattr(port_cfg, "ip_addresses", None)
        if ip_addresses:
            self._build_ip_stack(eth, device_name, ip_addresses)
        self._build_bgp_config(device, device_name, bgp_info)

    def _build_ip_stack(self, eth, device_name, ip_cfg) -> None:
        if ip_cfg.ipv4_addresses_config:
            v4 = ip_cfg.ipv4_addresses_config
            eth.ipv4_addresses.ipv4(
                name=getattr(v4, "ip_obj_name", None) or f"{device_name}_ipv4",
                address=v4.starting_ip,
                gateway=v4.gateway_starting_ip,
                prefix=v4.subnet_mask,
            )

        if ip_cfg.ipv6_addresses_config:
            v6 = ip_cfg.ipv6_addresses_config
            eth.ipv6_addresses.ipv6(
                name=getattr(v6, "ip_obj_name", None) or f"{device_name}_ipv6",
                address=v6.starting_ip,
                gateway=v6.gateway_starting_ip,
                prefix=v6.subnet_mask,
            )

        if not ip_cfg.ipv4_addresses_config and not ip_cfg.ipv6_addresses_config:
            if hasattr(ip_cfg, "ip_addr_1") and ip_cfg.ip_addr_1:
                addr_info = ip_cfg.ip_addr_1
                if hasattr(addr_info, "ipv4_addr_info") and addr_info.ipv4_addr_info:
                    v4 = addr_info.ipv4_addr_info
                    eth.ipv4_addresses.ipv4(
                        name=getattr(v4, "ip_obj_name", None) or f"{device_name}_ipv4",
                        address=v4.starting_ip,
                        gateway=v4.gateway_starting_ip,
                        prefix=v4.subnet_mask,
                    )
                elif hasattr(addr_info, "ipv6_addr_info") and addr_info.ipv6_addr_info:
                    v6 = addr_info.ipv6_addr_info
                    eth.ipv6_addresses.ipv6(
                        name=getattr(v6, "ip_obj_name", None) or f"{device_name}_ipv6",
                        address=v6.starting_ip,
                        gateway=v6.gateway_starting_ip,
                        prefix=v6.subnet_mask,
                    )

    def _build_bgp_config(self, device, device_name, bgp_info) -> None:
        router_id_set = False
        for af_label, bgp_cfg in [
            ("v4", bgp_info.bgp_v4_config),
            ("v6", bgp_info.bgp_v6_config),
        ]:
            if not bgp_cfg:
                continue
            peer_cfg = bgp_cfg.bgp_peer_config
            if not router_id_set:
                device.bgp.router_id = peer_cfg.local_peer_starting_ip
                router_id_set = True
            peer_name = f"{device_name}_bgp_{af_label}"
            as_type = "ebgp" if peer_cfg.peer_type == ixia_types.BgpPeerType.EBGP else "ibgp"
            self._bgp_peer_names.append(peer_name)

            if af_label == "v4":
                iface = device.bgp.ipv4_interfaces.v4interface()[-1]
                iface.ipv4_name = f"{device_name}_ipv4"
                peer = iface.peers.v4peer()[-1]
                peer.name = peer_name
                peer.peer_address = peer_cfg.remote_peer_starting_ip
                peer.as_type = as_type
                peer.as_number = peer_cfg.local_as or 0
            else:
                iface = device.bgp.ipv6_interfaces.v6interface()[-1]
                iface.ipv6_name = f"{device_name}_ipv6"
                peer = iface.peers.v6peer()[-1]
                peer.name = peer_name
                peer.peer_address = peer_cfg.remote_peer_starting_ip
                peer.as_type = as_type
                peer.as_number = peer_cfg.local_as or 0

            self.logger.info(
                f"[OTG]   BGP peer {peer_name}: "
                f"AS {peer_cfg.local_as} -> {peer_cfg.remote_peer_starting_ip}"
            )

            if bgp_cfg.bgp_prefix_configs:
                for prefix_cfg in bgp_cfg.bgp_prefix_configs:
                    self._build_bgp_prefix(peer, af_label, prefix_cfg)

    def _build_bgp_prefix(self, peer, af_label, prefix_cfg) -> None:
        route_name = prefix_cfg.prefix_name or f"route_{af_label}"
        if af_label == "v4":
            route_range = peer.v4_routes.v4routerange()[-1]
            route_range.name = route_name
            addr = route_range.addresses.v4routeaddress()[-1]
            addr.address = prefix_cfg.starting_ip
            addr.prefix = prefix_cfg.prefix_length or 24
            addr.count = prefix_cfg.count or 1
            if prefix_cfg.increment_ip:
                addr.step = int(ipaddress.IPv4Address(prefix_cfg.increment_ip))
        else:
            route_range = peer.v6_routes.v6routerange()[-1]
            route_range.name = route_name
            addr = route_range.addresses.v6routeaddress()[-1]
            addr.address = prefix_cfg.starting_ip
            addr.prefix = prefix_cfg.prefix_length or 64
            addr.count = prefix_cfg.count or 1
            if prefix_cfg.increment_ip:
                addr.step = int(ipaddress.IPv6Address(prefix_cfg.increment_ip))

        if prefix_cfg.bgp_communities:
            for comm in prefix_cfg.bgp_communities:
                c = route_range.communities.bgpcommunity()[-1]
                c.as_number = comm.as_number if hasattr(comm, "as_number") else 0
                c.as_custom = comm.as_custom if hasattr(comm, "as_custom") else 0

        if prefix_cfg.as_path_prepend and prefix_cfg.as_path_prepend.as_numbers:
            seg = route_range.as_path.segments.bgpaspathsegment()[-1]
            seg.type = seg.AS_SEQ
            seg.as_numbers = [int(asn) for asn in prefix_cfg.as_path_prepend.as_numbers]

        self.logger.info(
            f"[OTG]     Route {route_name}: "
            f"{prefix_cfg.starting_ip}/{prefix_cfg.prefix_length or 24} "
            f"x{prefix_cfg.count or 1}"
        )

    def _build_traffic_flows(self) -> None:
        if not self.ixia_config.traffic_items:
            self.logger.info("[OTG] No traffic items to configure")
            return

        for ti in self.ixia_config.traffic_items:
            tx_names = [self._resolve_endpoint(ep) for ep in (ti.source_endpoints or [])]
            rx_names = [self._resolve_endpoint(ep) for ep in (ti.dest_endpoints or [])]

            bidir = getattr(
                getattr(ti, "traffic_flow_config", None),
                "bidirectional", False,
            )
            directions = [(tx_names, rx_names)]
            if bidir:
                directions.append((rx_names, tx_names))

            for i, (tx, rx) in enumerate(directions):
                suffix = "" if i == 0 else "_reverse"
                flow_name = f"{ti.name or 'flow'}{suffix}"
                flow = self.config.flows.flow(name=flow_name)[-1]

                flow.tx_rx.device.tx_names = tx
                flow.tx_rx.device.rx_names = rx

                if ti.traffic_type == ixia_types.TrafficType.IPV4:
                    flow.packet.ethernet().ipv4()
                elif ti.traffic_type == ixia_types.TrafficType.IPV6:
                    flow.packet.ethernet().ipv6()
                else:
                    flow.packet.ethernet()

                if ti.l4_protocol_config:
                    l4 = ti.l4_protocol_config
                    if hasattr(l4, "tcp_src_port") and l4.tcp_src_port:
                        tcp = flow.packet.tcp()
                        tcp.src_port.value = l4.tcp_src_port
                        tcp.dst_port.value = l4.tcp_dst_port
                    elif hasattr(l4, "udp_src_port") and l4.udp_src_port:
                        udp = flow.packet.udp()
                        udp.src_port.value = l4.udp_src_port
                        udp.dst_port.value = l4.udp_dst_port

                self._configure_flow_rate(flow, ti)
                self._configure_flow_size(flow, ti)
                self._configure_flow_duration(flow, ti)

                flow.metrics.enable = True

                self.logger.info(f"[OTG]   Flow {flow_name}: {tx} -> {rx}")

    def _resolve_endpoint(self, ep) -> str:
        if ep.endpoint_type == ixia_types.EndpointType.BGP_PREFIX:
            return ep.bgp_prefix_name or f"{ep.port_name}_route"
        dg_name = f"{ep.port_name}_DG{ep.device_group_index}"
        for port_cfg in self.ixia_config.port_configs:
            if port_cfg.port_name != ep.port_name:
                continue
            for dg_cfg in (port_cfg.device_group_configs or []):
                if dg_cfg.device_group_index != ep.device_group_index:
                    continue
                ip_cfg = dg_cfg.ip_addresses_config
                if ip_cfg:
                    if ip_cfg.ipv4_addresses_config:
                        return getattr(ip_cfg.ipv4_addresses_config, "ip_obj_name", None) or f"{dg_name}_ipv4"
                    if ip_cfg.ipv6_addresses_config:
                        return getattr(ip_cfg.ipv6_addresses_config, "ip_obj_name", None) or f"{dg_name}_ipv6"
        return dg_name

    def _configure_flow_rate(self, flow, ti) -> None:
        rate_info = ti.traffic_rate_info
        if not rate_info:
            return
        if rate_info.rate_type == ixia_types.RateType.PERCENT_LINE_RATE:
            flow.rate.percentage = rate_info.rate_value
        elif rate_info.rate_type == ixia_types.RateType.FRAMES_PER_SECOND:
            flow.rate.pps = rate_info.rate_value

    def _configure_flow_size(self, flow, ti) -> None:
        flow_cfg = ti.traffic_flow_config
        if not flow_cfg or not flow_cfg.frame_size:
            return
        fs = flow_cfg.frame_size
        if fs.type == ixia_types.FrameSizeType.FIXED:
            flow.size.fixed = fs.fixed_size or 400
        elif fs.type == ixia_types.FrameSizeType.INCREMENT:
            flow.size.increment.start = fs.increment_from or 64
            flow.size.increment.end = fs.increment_to or 1500
            flow.size.increment.step = fs.increment_step or 100

    def _configure_flow_duration(self, flow, ti) -> None:
        flow_cfg = ti.traffic_flow_config
        if not flow_cfg or not flow_cfg.transmission_control:
            flow.duration.choice = flow.duration.CONTINUOUS
            return
        tc = flow_cfg.transmission_control
        if tc.type == ixia_types.TransmissionControlType.CONTINUOUS:
            flow.duration.choice = flow.duration.CONTINUOUS
        elif tc.type == ixia_types.TransmissionControlType.FIXED_DURATION:
            flow.duration.fixed_seconds.seconds = tc.duration or 10
        elif tc.type == ixia_types.TransmissionControlType.FIXED_FRAME_COUNT:
            flow.duration.fixed_packets.packets = tc.frame_count or 1000
