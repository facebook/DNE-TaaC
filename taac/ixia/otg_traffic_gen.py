# pyre-unsafe
"""
Idiomatic OTG/snappi traffic generator — implements AbstractTrafficGenerator.

Consumes the same IxiaConfig thrift struct that the restpy path uses, but
translates it to snappi's declarative model (set_config, get_metrics, polling).
"""

import collections.abc
import ipaddress
import logging
import re
import threading
import time
import typing as t

if t.TYPE_CHECKING:
    import snappi  # pyre-ignore[21]
else:
    try:
        import snappi
    except ImportError:
        snappi = None

from ixia.ixia import types as ixia_types
from taac.ixia.abstract_traffic_generator import (
    AbstractTrafficGenerator,
)


def _canon_ip(addr: t.Any) -> str:
    """Canonical text form of an IP address, for dict keys and lookups.

    OTG reports ND neighbours expanded ("2001:0db8:0001:...:0002") while configs
    are written compressed ("2001:db8:1::2").  Same address, different string, so
    comparing them silently dropped every IPv6 flow with "No resolved v6 MAC".
    IPv4 was unaffected — dotted quads have one representation.

    Non-address input passes through unchanged.
    """
    try:
        return str(ipaddress.ip_address(str(addr)))
    except ValueError:
        return str(addr)


def _offset_ip(base: str, increment: t.Optional[str], count: int) -> str:
    """`base` advanced by `count` times `increment`, as text.

    Used to place each simulated device of a multi-device group on its own
    address, mirroring how restpy expands a device-group multiplier.
    """
    if not count:
        return base
    try:
        base_addr = ipaddress.ip_address(base)
        step = int(ipaddress.ip_address(increment)) if increment else 1
    except ValueError:
        return base
    return str(base_addr.__class__(int(base_addr) + count * step))


def _nonempty_sequence(value: t.Any) -> bool:
    """True when `value` is a populated, non-string sequence.

    Thrift optional lists arrive as ``thrift.python.types.List``, which is NOT a
    ``list`` or ``tuple``, so an ``isinstance(x, (list, tuple))`` check silently
    drops real config.  ``str`` is itself a Sequence, hence excluded.
    """
    return (
        isinstance(value, collections.abc.Sequence)
        and not isinstance(value, (str, bytes))
        and len(value) > 0
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

# Why a peer is exempt from the setup-time all-sessions-up gate.  DISABLED peers
# are additionally driven back down after every protocol start; REPLAY peers are
# left wherever the DUT's handling of their UPDATEs puts them.
UNREQUIRED_REPLAY = "replay sequence"
UNREQUIRED_DISABLED = "device group disabled"

# Consecutive destination addresses a prefix-targeted flow sweeps.  One fixed
# destination hashes to one next-hop, so an ECMP assertion built on it cannot see
# selection spread across members.  64 gives the hash plenty to vary on while
# staying far below any per-flow address limit.
PREFIX_TARGETED_DST_COUNT = 64

# Deliberately narrow restpy-PacketHeader -> snappi translation table.
#
# restpy describes a packet by regex-querying IxNetwork's *remote* stack tree and
# setting vendor attribute names on what it finds; snappi is the inverse, a
# declarative local schema with typed attributes.  No general mapping exists, so
# only the stacks/fields below are understood and everything else raises
# NotImplementedError rather than being dropped.  Keys are lowercased restpy
# field-query regexes.
_PACKET_HEADER_FIELD_MAP: t.Dict[str, t.Dict[str, str]] = {
    "ethernet": {
        "destination mac address": "dst",
        "source mac address": "src",
    },
    "ipv4": {
        "source address": "src",
        "destination address": "dst",
    },
    "ipv6": {
        "source address": "src",
        "destination address": "dst",
    },
    "tcp": {
        "tcp-source-port": "src_port",
        "tcp-dest-port": "dst_port",
    },
    "udp": {
        "udp-source-port": "src_port",
        "udp-dest-port": "dst_port",
    },
}


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
            raise ImportError(
                "snappi is not installed. Install with: pip install snappi"
            )

        self.logger = logger or _get_logger()
        self.ixia_config = ixia_config
        self._location = location or chassis_ip or "https://localhost:8443"

        self.api: "snappi.Api" = snappi.api(location=self._location)
        self.config: "snappi.Config" = self.api.config()

        # Built during _build_config
        self._bgp_peer_names: t.List[str] = []

        # Peers present in the pushed config but not required Established before
        # setup completes, mapped to the set of reasons why.  Two reasons qualify:
        # a replay peer's session state is the thing under test rather than a
        # precondition, and a disabled group's peer is meant to be down so a
        # playbook can bring it up.  A peer can be both — the malformed speaker is
        # — and enabling it must not clear the replay exemption, hence a set
        # rather than a single reason.
        self._unrequired_peers: t.Dict[str, t.Set[str]] = {}

        self._device_group_info: t.Dict[t.Tuple[str, int], t.Dict[str, t.Any]] = {}

        # (port_name, device_group_index, network_group_index, af) -> the BGP
        # prefix advertised there.  Lets a TrafficEndpoint with
        # network_group_index set address INTO an advertised range instead of at
        # the device group's own interface — i.e. traffic that actually traverses
        # BGP routes rather than the DUT's connected subnets.
        self._advertised_prefixes: t.Dict[
            t.Tuple[str, int, int, str], t.Dict[str, t.Any]
        ] = {}

        # Device group name -> (port_name, device_group_index).  Lets playbook
        # steps address groups by name/regex; _device_group_info stays keyed
        # positionally because flow resolution depends on that.
        self._device_group_keys: t.Dict[str, t.Tuple[str, int]] = {}

        # TaacRunner-facing state
        self.test_case_uuid: t.Optional[str] = None
        self.paused: bool = False
        self.capturing: bool = False
        self._traffic_start_time: float = 0.0
        self._disabled_flows: t.Set[str] = set()

        # Background stats capture
        self._capture_thread: t.Optional[threading.Thread] = None
        self._capture_stop: threading.Event = threading.Event()
        # Float keys, not int: the capture interval jitters either side of a
        # second boundary, so truncating collides two polls onto one key and
        # loses a sample -- and a truncated 10.9 reads as older than a
        # since_time of 10.5, hiding a fresh snapshot from its caller.
        self._captured_stats: t.Dict[float, t.List[t.Dict[str, t.Any]]] = {}
        self._capture_lock: threading.Lock = threading.Lock()

        # Per-flow cumulative loss duration tracking
        self._flow_loss_start: t.Dict[str, t.Optional[float]] = {}
        self._flow_loss_accumulated: t.Dict[str, float] = {}

        # Snapshot of the last config pushed via set_config, used to skip
        # redundant re-pushes that would reset protocols for no reason.
        self._last_pushed_config: t.Optional[str] = None

        # (port_name, device_name) -> synthetic IPv4 router ID, for v6-only
        # BGP speakers.  Must stay distinct per speaker; see _derive_router_id.
        self._router_ids: t.Dict[t.Tuple[str, str], str] = {}

        self._build_config()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def setup(self, bgp_timeout: int = BGP_VERIFY_TIMEOUT) -> None:
        """Push config, start protocols, verify connectivity.

        Both BGP and non-BGP configs use a two-phase approach:
        1. Push device groups (no flows) to start protocols and resolve ARP.
           For BGP, also wait for session convergence.
        2. Rebuild flows as explicit port-level frames with resolved gateway
           MACs, re-push config, and restart protocols.

        Device-level flows (flow.tx_rx.device) are not reliably supported
        by all OTG controllers, so we always use port-level flows with
        explicit MAC/IP headers.
        """
        self.logger.info("[OTG] Pushing configuration...")
        if self._bgp_peer_names:
            self._setup_bgp_with_explicit_flows(bgp_timeout)
        else:
            self._setup_with_explicit_flows()

        self.logger.info("[OTG] Setup complete")

    def _setup_bgp_with_explicit_flows(self, bgp_timeout: int) -> None:
        """Two-phase setup for BGP: establish sessions, then rebuild flows."""
        saved_traffic_items = self.ixia_config.traffic_items or []
        self.config.flows.clear()

        self.logger.info("[OTG] Phase 1: pushing devices + BGP (no flows)...")
        self._push_config()
        self._start_protocols()
        self._wait_for_bgp(timeout=bgp_timeout)

        gw_macs = self._get_resolved_gw_macs()
        if not gw_macs:
            self.logger.warning(
                "[OTG] No gateway MACs resolved, skipping explicit flows"
            )
            return

        self.logger.info(
            f"[OTG] Phase 2: rebuilding flows with resolved MACs: {gw_macs}"
        )
        self._build_explicit_flows(saved_traffic_items, gw_macs)

        self._push_config()
        self._start_protocols()
        self._wait_for_bgp(timeout=bgp_timeout)

    def _setup_with_explicit_flows(self) -> None:
        """Two-phase setup: resolve ARP first, then rebuild with explicit flows."""
        saved_traffic_items = self.ixia_config.traffic_items or []
        self.config.flows.clear()

        self.logger.info("[OTG] Phase 1: pushing device groups (no flows) for ARP...")
        self._push_config()
        self._start_protocols()
        self._wait_for_arp()

        gw_macs = self._get_resolved_gw_macs()
        if not gw_macs:
            self.logger.warning(
                "[OTG] No gateway MACs resolved, skipping explicit flows"
            )
            return

        self.logger.info(
            f"[OTG] Phase 2: rebuilding flows with resolved MACs: {gw_macs}"
        )
        self._build_explicit_flows(saved_traffic_items, gw_macs)

        self._push_config()
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
                            ip_addr = _canon_ip(getattr(n, ip_field))
                            result[ip_addr] = mac
                            self.logger.info(f"[OTG]   {label}: {ip_addr} -> {mac}")
            except Exception as e:
                self.logger.warning(f"[OTG] Failed to query {label} state: {e}")
        return result

    def _build_explicit_flows(
        self,
        traffic_items: t.Sequence,
        gw_macs: t.Dict[str, str],
    ) -> None:
        """Rebuild traffic items as explicit port-level flows with resolved MACs."""
        for ti in traffic_items:
            for src_ep in ti.source_endpoints or []:
                for dst_ep in ti.dest_endpoints or []:
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
                        "bidirectional",
                        False,
                    )
                    if bidir:
                        pairs.append((dst, src))

                    # A packet_headers item specifies its own L2/L3, so it does
                    # not depend on ARP/ND having resolved the gateway MAC.
                    packet_headers = getattr(ti, "packet_headers", None)
                    if not _nonempty_sequence(packet_headers):
                        packet_headers = None

                    # A packet_headers item declares its own AF; otherwise the
                    # traffic item's traffic_type decides, since a dual-stack
                    # device group cannot disambiguate on its own.
                    if ti.traffic_type == ixia_types.TrafficType.IPV6:
                        af_label = "v6"
                    elif ti.traffic_type == ixia_types.TrafficType.IPV4:
                        af_label = "v4"
                    else:
                        af_label = src.get("af", "v4")

                    for tx, rx in pairs:
                        tx_addrs = self._af_addrs(tx, af_label)
                        rx_addrs = self._af_addrs(rx, af_label)
                        if not packet_headers and (not tx_addrs or not rx_addrs):
                            self.logger.warning(
                                f"[OTG] {ti.name}: device group "
                                f"{tx.get('name')} or {rx.get('name')} has no "
                                f"{af_label} address; skipping flow"
                            )
                            continue

                        tx_gw_mac = gw_macs.get(
                            _canon_ip(
                                (tx_addrs or {}).get(
                                    "gateway", tx.get("gateway", "")
                                )
                            )
                        )
                        if not tx_gw_mac and not packet_headers:
                            self.logger.warning(
                                f"[OTG] No resolved {af_label} MAC for gateway "
                                f"{(tx_addrs or {}).get('gateway')}, "
                                f"skipping flow {ti.name}"
                            )
                            continue

                        # The rx PORT is deliberately absent from this key, so
                        # two destination endpoints on different ports sharing a
                        # device_group_index would collide.  Renaming is not free
                        # -- flow names appear in loss reporting and in the
                        # regexes playbooks match on -- so the key stays and the
                        # collision is an error instead.  Add rx['port'] here
                        # when you need a multi-destination traffic item.
                        flow_name = f"{ti.name or 'flow'}_{tx['port']}_{tx['dg_idx']}_to_{rx['dg_idx']}"
                        self._assert_unique_flow_name(flow_name)
                        flow = self.config.flows.flow(name=flow_name)[-1]
                        flow.tx_rx.port.tx_name = tx["port"]
                        flow.tx_rx.port.rx_names = [rx["port"]]

                        flow_src = flow_dst = ""
                        if packet_headers:
                            # Caller fully specifies the frame (e.g. control-plane
                            # traffic aimed at the DUT CPU), so do not synthesize
                            # the default routed-flow L2/L3 headers.
                            stacks = self.apply_packet_headers(flow, packet_headers)
                        else:
                            eth = flow.packet.ethernet()[-1]
                            eth.src.value = tx["mac"]
                            eth.dst.value = tx_gw_mac
                            if af_label == "v6":
                                stacks = {"ipv6": flow.packet.ipv6()[-1]}
                                ip_hdr = stacks["ipv6"]
                            else:
                                stacks = {"ipv4": flow.packet.ipv4()[-1]}
                                ip_hdr = stacks["ipv4"]
                            # KNOWN LIMITATION: `tx is src` is an identity
                            # comparison on the resolved endpoint dicts.  For a
                            # bidirectional item whose source and destination
                            # resolve to the SAME endpoint, both legs take the
                            # first branch and the reverse leg addresses itself.
                            # No current profile pairs an endpoint with itself.
                            tx_ep, rx_ep = (
                                (src_ep, dst_ep) if tx is src else (dst_ep, src_ep)
                            )
                            flow_src = self._flow_endpoint_address(
                                tx_ep, tx_addrs, af_label
                            )
                            flow_dst = self._flow_endpoint_address(
                                rx_ep, rx_addrs, af_label
                            )
                            ip_hdr.src.value = flow_src
                            dst_span = None
                            if getattr(rx_ep, "network_group_index", None) is not None:
                                dst_span = self._prefix_host_span(
                                    rx_ep.port_name,
                                    rx_ep.device_group_index,
                                    rx_ep.network_group_index,
                                    af_label,
                                )
                            if dst_span and dst_span[1] > 1:
                                # Sweep the prefix so the DUT's ECMP hash has
                                # something to vary on; a single destination
                                # pins every frame to one next-hop.
                                start, count = dst_span
                                ip_hdr.dst.increment.start = start
                                ip_hdr.dst.increment.step = (
                                    "::1" if af_label == "v6" else "0.0.0.1"
                                )
                                ip_hdr.dst.increment.count = count
                                flow_dst = f"{start}+{count}"
                            else:
                                ip_hdr.dst.value = flow_dst
                        self._apply_flow_qos(stacks, ti)

                        if getattr(ti, "enabled", True) is False:
                            # Honor an item that ships disabled (e.g. a flood
                            # a playbook enables on demand).
                            self._disabled_flows.add(flow_name)

                        self._configure_flow_rate(flow, ti)
                        self._configure_flow_size(flow, ti)
                        self._configure_flow_duration(flow, ti)
                        flow.metrics.enable = True

                        self.logger.info(
                            f"[OTG]   Explicit flow {flow_name} [{af_label}]: "
                            f"{flow_src or '(packet_headers)'} -> "
                            f"{flow_dst or '(packet_headers)'} via {tx_gw_mac}"
                        )

    def _assert_unique_flow_name(self, flow_name: str) -> None:
        """Refuse a duplicate flow name.

        `config.flows.flow(name=...)` appends rather than replaces, so a
        collision yields two flows with one name and every later lookup -- loss
        reporting, the disabled set, transmit -- addresses whichever it finds
        first.  Failing here is the difference between a config error and a test
        that silently measures the wrong flow.
        """
        if any(f.name == flow_name for f in self.config.flows):
            raise ValueError(
                f"duplicate flow name {flow_name!r}: the name key omits the rx "
                f"port, so two destinations on different ports with the same "
                f"device_group_index collide. Add rx['port'] to the key."
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

    def _match_flows(self, regexes: t.Optional[t.List[str]]) -> t.Set[str]:
        """Flow names matching any regex, or all flow names when None."""
        names = [f.name for f in self.config.flows]
        if regexes is None:
            return set(names)
        return {n for n in names for r in regexes if re.search(r, n)}

    def enable_traffic(
        self,
        regexes: t.Optional[t.List[str]] = None,
        enable: bool = True,
    ) -> None:
        """Enable or disable flows matching the regex(es), or all when None.

        Signature-compatible with the restpy API so playbook args_dict
        payloads work unchanged, including its behavior that enabling a
        specific set explicitly disables everything else, so only the
        requested flows run.

        Mutates only the disabled-flow set and transmit state, never self.config,
        so a subsequent _prepare_traffic() sees an unchanged serialization and
        skips the re-push — which would otherwise restart protocols and flap every
        session.  Tests asserting session stability depend on that.
        """
        all_names = {f.name for f in self.config.flows}
        matched = self._match_flows(regexes)

        self._enable_traffic(regexes, enable=enable)

        non_matching: t.Set[str] = set()
        if enable and regexes is not None:
            non_matching = all_names - matched
            self._disabled_flows |= non_matching

        if matched:
            self._transmit(start=enable, flow_names=sorted(matched))
        if non_matching:
            self._transmit(start=False, flow_names=sorted(non_matching))

        action = "Enabled" if enable else "Disabled"
        self.logger.info(f"[OTG] {action} flow(s) {sorted(matched)}")
        if non_matching:
            self.logger.info(
                f"[OTG] Disabled non-matching flow(s) {sorted(non_matching)}"
            )
        if not matched:
            self.logger.warning(f"[OTG] No flows matched {regexes!r}")

    def _push_config(self) -> None:
        """Push self.config and record exactly what was pushed.

        The record is not bookkeeping: _prepare_traffic() compares against it to
        decide whether a re-push is needed, and a re-push restarts protocols and
        flaps every session.  A push that skips the record leaves the next
        comparison lying — either forcing a needless flap or skipping a needed
        push — so every push of self.config goes through here.
        """
        self._log_api_warnings(self.api.set_config(self.config), "set_config")
        self._last_pushed_config = self.config.serialize()

    def _log_api_warnings(self, response, action: str) -> None:
        """Surface warnings the controller returned.

        OTG uses warnings for "accepted, but" — a peer it declined to start, a
        capability it does not support.  Nothing raises, so discarding the
        response means the controller's own account of a half-applied config is
        lost, and the failure shows up later as an unexplained timeout.
        """
        for warning in getattr(response, "warnings", None) or []:
            self.logger.warning(f"[OTG] {action} warning: {warning}")

    def _prepare_traffic(self) -> None:
        """
        Finalize traffic config before starting.

        Skip when config is unchanged to avoid resetting protocols needlessly.

        When the config HAS changed, use set_config (full replacement) and
        re-converge protocols.  The OTG PATCH /config (update_config) only
        supports in-flight flow rate/size and ISIS updates — not adding
        devices, BGP peers, or route ranges — so structural changes still
        require set_config.
        """
        current = self.config.serialize()
        if current == self._last_pushed_config:
            self.logger.info("[OTG] Config unchanged, skipping re-push")
            return
        self.logger.info("[OTG] Config changed, re-pushing via set_config...")
        self._push_config()
        self._start_protocols()
        if self._bgp_peer_names:
            self._wait_for_bgp()

    def start_traffic(self, regenerate_traffic_items: bool = False) -> None:
        """Start enabled flows."""
        enabled = [
            f.name for f in self.config.flows if f.name not in self._disabled_flows
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

    def restart_bgp_peers(self, regexes: t.Optional[t.List[str]] = None) -> None:
        """Stop then start BGP peers matching the regex(es) (or all)."""
        matched: t.List[str] = []
        if regexes:
            for p in regexes:
                matched.extend(self._match_bgp_peers(p))
        else:
            matched = list(self._bgp_peer_names)
        if not matched:
            self.logger.warning("[OTG] No BGP peers matched for restart")
            return
        self.logger.info(f"[OTG] Restarting BGP peers: {matched}")
        for state_val in ["DOWN", "UP"]:
            self._set_bgp_peer_state(matched, state_val)

    def _set_bgp_peer_state(self, peer_names: t.Sequence[str], state: str) -> None:
        """Drive the named BGP peers to "UP" or "DOWN" via control_state."""
        cs = self.api.control_state()
        cs.choice = cs.PROTOCOL
        cs.protocol.choice = cs.protocol.BGP
        cs.protocol.bgp.peers.peer_names = list(peer_names)
        cs.protocol.bgp.peers.state = getattr(cs.protocol.bgp.peers, state)
        self._log_api_warnings(
            self.api.set_control_state(cs), f"bgp peers {state}"
        )

    def _match_device_groups(
        self,
        device_group_name_regex: str,
        exception_device_groups: t.Optional[t.List[str]] = None,
    ) -> t.List[str]:
        """Device group names matching the regex, minus any exception substring."""
        try:
            pattern = re.compile(device_group_name_regex)
        except re.error as ex:
            raise ValueError(
                f"Invalid device group regex {device_group_name_regex!r}: {ex}"
            ) from ex
        exceptions = exception_device_groups or []
        return [
            name
            for name in sorted(self._device_group_keys)
            if pattern.search(name)
            and not any(exc in name for exc in exceptions)
        ]

    def toggle_device_groups(
        self,
        enable: bool,
        device_group_name_regex: str,
        all_bgp_peers: bool = False,
        exception_device_groups: t.Optional[t.List[str]] = None,
        sleep_time_before_applying_change: int = 30,
    ) -> None:
        """Bring the matching device groups' BGP peers up or down.

        Signature-compatible with the restpy API so playbook args_dict payloads
        work unchanged; `all_bgp_peers` exists only for that compatibility, since
        OTG resolves peers per matching group either way.

        OTG has no live "disable device group" primitive, and a structural change
        needs a full set_config that restarts protocols and flaps every session.
        Driving just this group's peers UP/DOWN advertises or withdraws the same
        routes — same RIB/FIB and ECMP pressure, blast radius scoped to the group
        under test.
        """
        matched_groups = self._match_device_groups(
            device_group_name_regex, exception_device_groups
        )
        if not matched_groups:
            self.logger.warning(
                f"[OTG] No device groups matched {device_group_name_regex!r} "
                f"(known: {sorted(self._device_group_keys)}); nothing to toggle"
            )
            return

        # Dedupe on the resolved (port, device_group_index) key.  A multiplied
        # group matches once per simulated device, but every one of those device
        # names resolves to the same key, whose info already lists all N peers --
        # so iterating device names would add the whole list N times.
        peer_names: t.List[str] = []
        seen_keys: t.Set[t.Tuple[str, int]] = set()
        for name in matched_groups:
            key = self._device_group_keys[name]
            if key in seen_keys:
                continue
            seen_keys.add(key)
            info = self._device_group_info.get(key, {})
            peer_names.extend(info.get("peers") or [])

        if not peer_names:
            self.logger.warning(
                f"[OTG] Device groups {matched_groups} have no BGP peers; "
                f"nothing to toggle"
            )
            return

        if sleep_time_before_applying_change:
            self.logger.info(
                f"[OTG] Waiting {sleep_time_before_applying_change}s "
                f"before applying change"
            )
            time.sleep(sleep_time_before_applying_change)

        self._set_bgp_peer_state(peer_names, "UP" if enable else "DOWN")

        # Track the group's intended state so a later config re-push — which
        # restarts protocols and re-applies the hold-down — does not silently
        # revert what a playbook just did.  Only the disabled reason moves; a
        # replay peer stays exempt from the setup gate either way.
        for peer_name in peer_names:
            if enable:
                self._clear_unrequired(peer_name, UNREQUIRED_DISABLED)
            else:
                self._mark_unrequired(peer_name, UNREQUIRED_DISABLED)

        self.logger.info(
            f"[OTG] {'Enabled' if enable else 'Disabled'} device group(s) "
            f"{matched_groups} ({len(peer_names)} BGP peer(s): {peer_names})"
        )

    def _start_protocols(self) -> None:
        cs = self.api.control_state()
        cs.choice = cs.PROTOCOL
        cs.protocol.choice = cs.protocol.ALL
        cs.protocol.all.state = cs.protocol.all.START
        self._log_api_warnings(
            self.api.set_control_state(cs), "start protocols"
        )
        self._hold_disabled_peers_down()

    def _mark_unrequired(self, peer_name: str, reason: str) -> None:
        self._unrequired_peers.setdefault(peer_name, set()).add(reason)

    def _clear_unrequired(self, peer_name: str, reason: str) -> None:
        reasons = self._unrequired_peers.get(peer_name)
        if not reasons:
            return
        reasons.discard(reason)
        if not reasons:
            del self._unrequired_peers[peer_name]

    def _hold_disabled_peers_down(self) -> None:
        """Drive the peers of `enable=False` device groups back down.

        OTG has no device-level disable and protocol start is all-or-nothing, so
        honouring `enable` means building the group normally and putting its peers
        down immediately afterwards.  A peer may establish briefly first; what
        matters is that it is down before any playbook runs, so the playbook's
        `toggle_device_groups(enable=True)` drives a real transition rather than a
        no-op against a session that has been up since setup.
        """
        peers = [
            name
            for name, reasons in self._unrequired_peers.items()
            if UNREQUIRED_DISABLED in reasons
        ]
        if not peers:
            return
        self.logger.info(f"[OTG] Holding disabled device-group peers down: {peers}")
        self._set_bgp_peer_state(peers, "DOWN")

    def _wait_for_arp(self, timeout: int = ARP_RESOLVE_TIMEOUT) -> None:
        """Wait for ARP/ND resolution after protocol start (non-BGP topologies)."""
        has_v4 = any(
            info["af"] == "v4" and info["ip"]
            for info in self._device_group_info.values()
        )
        has_v6 = any(
            info["af"] == "v6" and info["ip"]
            for info in self._device_group_info.values()
        )
        if not has_v4 and not has_v6:
            return

        label = "/".join(
            filter(None, ["ARP" if has_v4 else "", "ND" if has_v6 else ""])
        )
        self.logger.info(
            f"[OTG] Waiting for {label} resolution (timeout={timeout}s)..."
        )
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
                            1
                            for n in states.ipv4_neighbors
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
                            1
                            for n in states.ipv6_neighbors
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
        """Block until every peer whose state is a precondition reports up.

        Peers in `_unrequired_peers` are reported but not required, for two
        reasons.  A replay peer's UPDATE sequence is re-sent on every
        re-establishment, so a DUT that answers one with a NOTIFICATION — the
        correct response to several RFC 7606 malformations — leaves it in a flap
        loop; gating setup on it makes startup a race against the flap cycle, one
        that bgpd's widening idle-hold backoff steadily loses.  A disabled group's
        peer is deliberately held down so a playbook can bring it up.
        """
        expected = [
            n for n in self._bgp_peer_names if n not in self._unrequired_peers
        ]
        self.logger.info(
            f"[OTG] Verifying BGP sessions (timeout={timeout}s); "
            f"required: {expected}"
        )
        deadline = time.time() + timeout
        last_seen: t.Dict[str, str] = {}
        while time.time() < deadline:
            metrics = self._get_bgp_metrics()
            required = [m for m in metrics if m.name not in self._unrequired_peers]
            last_seen = {m.name: m.session_state for m in metrics}
            if metrics and all(m.session_state == "up" for m in required):
                self.logger.info(f"[OTG] All {len(required)} BGP session(s) up")
                for m in metrics:
                    reasons = self._unrequired_peers.get(m.name)
                    if not reasons:
                        continue
                    self.logger.info(
                        f"[OTG]   {m.name}: {m.session_state} "
                        f"(not required — {', '.join(sorted(reasons))})"
                    )
                    # The hold-down is issued once, right after protocol start,
                    # and never confirmed.  If it raced peer instantiation the
                    # peer is still up, and the playbook's toggle-up then acts on
                    # an established session -- measuring nothing while reporting
                    # green.  This is the only thing that catches that, and it
                    # rides on this poll deliberately: by the time the required
                    # peers are up the DOWN has had seconds to land, so an "up"
                    # here is a real failure rather than a race with the check.
                    if (
                        UNREQUIRED_DISABLED in reasons
                        and m.session_state == "up"
                    ):
                        self.logger.warning(
                            f"[OTG] {m.name} belongs to a disabled device group "
                            f"but is UP — the hold-down did not take. A playbook "
                            f"toggling this group on will be a no-op and its "
                            f"assertions will measure nothing."
                        )
                return
            if metrics:
                down = [m.name for m in required if m.session_state != "up"]
                self.logger.info(f"[OTG] Waiting for BGP sessions: {down}")
            else:
                # Distinct failure from "peer down": the controller has no BGP
                # peers to report on at all.  Usually the ports never came up, so
                # the protocol engine never instantiated them.  Logging nothing
                # here turns the whole timeout into a silent hang.
                self.logger.warning(
                    f"[OTG] Controller reported no BGP metrics; expected "
                    f"{expected}. Ports down, or protocols never started?"
                )
            time.sleep(BGP_VERIFY_POLL_INTERVAL)
        # Whether the gateway resolved splits the two causes that look identical
        # from here: unreachable at L2/L3 (cabling, port link, interface
        # addressing, wrong subnet) versus reachable but not peering (missing or
        # mismatched bgpd neighbour, wrong ASN, ACL).  Without it every failure
        # reads the same and the search starts from scratch each time.
        try:
            neighbours = self._get_resolved_gw_macs()
        except Exception as ex:  # never mask the real timeout
            neighbours = {}
            self.logger.debug(f"[OTG] Could not read neighbour state: {ex}")
        raise TimeoutError(
            f"BGP sessions not up within {timeout}s; required {expected}, "
            f"last reported "
            f"{last_seen or 'nothing (controller listed no BGP peers)'}; "
            + (
                f"gateways resolved {neighbours} — reachable, so look at the "
                f"DUT's bgpd neighbour config (peer address, ASN, ACLs)"
                if neighbours
                else "no gateway resolved — check port link state, cabling and "
                "interface addressing before looking at bgpd"
            )
        )

    def _get_bgp_metrics(self) -> t.List:
        has_v4 = any(n.endswith("_v4") for n in self._bgp_peer_names)
        has_v6 = any(n.endswith("_v6") for n in self._bgp_peer_names)
        queries = []
        if has_v4:
            queries.append(("bgpv4", "bgpv4", "bgpv4_metrics"))
        if has_v6:
            queries.append(("bgpv6", "bgpv6", "bgpv6_metrics"))

        all_metrics = []
        for choice, req_attr, resp_attr in queries:
            try:
                mr = self.api.metrics_request()
                mr.choice = choice
                getattr(mr, req_attr).peer_names = []
                resp = self.api.get_metrics(mr)
                if resp:
                    metrics = getattr(resp, resp_attr, None)
                    if metrics:
                        all_metrics.extend(metrics)
            except Exception as e:
                self.logger.warning(f"[OTG] Failed to fetch {choice} metrics: {e}")
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
    # Traffic reconfiguration
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_flow_rate(
        flow,
        line_rate: t.Optional[int],
        line_rate_type: t.Optional[ixia_types.RateType],
    ) -> None:
        if line_rate is None:
            return
        rate_type = line_rate_type or ixia_types.RateType.PERCENT_LINE_RATE
        if rate_type == ixia_types.RateType.PERCENT_LINE_RATE:
            flow.rate.percentage = line_rate
        elif rate_type == ixia_types.RateType.FRAMES_PER_SECOND:
            flow.rate.pps = line_rate

    @staticmethod
    def _apply_flow_frame_size(flow, frame_size_setting: ixia_types.FrameSize) -> None:
        if frame_size_setting.type == ixia_types.FrameSizeType.FIXED:
            flow.size.fixed = frame_size_setting.fixed_size or 400
        elif frame_size_setting.type == ixia_types.FrameSizeType.INCREMENT:
            flow.size.increment.start = frame_size_setting.increment_from or 64
            flow.size.increment.end = frame_size_setting.increment_to or 1500
            flow.size.increment.step = frame_size_setting.increment_step or 100

    def configure_traffic_item(
        self,
        traffic_item_name: str,
        line_rate: t.Optional[int] = None,
        line_rate_type: t.Optional[ixia_types.RateType] = None,
        frame_size_setting: t.Optional[ixia_types.FrameSize] = None,
        qos_config: t.Optional[ixia_types.QoSConfig] = None,
    ) -> None:
        flow = next((f for f in self.config.flows if f.name == traffic_item_name), None)
        if flow is None:
            self.logger.debug(f"[OTG] Flow {traffic_item_name} not found. Skipping...")
            return

        self._apply_flow_rate(flow, line_rate, line_rate_type)

        if frame_size_setting is not None:
            self._apply_flow_frame_size(flow, frame_size_setting)

        if qos_config is not None:
            self.logger.debug(
                f"[OTG] QoS reconfiguration for {traffic_item_name} is not "
                "yet supported — skipping QoS update"
            )

        self.logger.info(
            f"[OTG] Reconfigured flow {traffic_item_name}, pushing config..."
        )
        self._push_config()

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
            results.append(
                {
                    "name": fm.name,
                    "frames_tx": tx,
                    "frames_rx": rx,
                    "loss": loss,
                }
            )
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
            stats.append(
                {
                    "identifier": name,
                    "packet_loss_duration": accumulated * 1000.0,
                    "packet_loss_percentage": loss_pct,
                    "frame_delta": float(tx - rx),
                }
            )
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
                    for ts in sorted(self._captured_stats.keys(), reverse=True):
                        if ts > since_time:
                            return self._flow_metrics_to_stats(self._captured_stats[ts])
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
                violations.append(
                    {
                        "name": m["name"],
                        "loss_pct": loss,
                        "frames_tx": m["frames_tx"],
                        "frames_rx": m["frames_rx"],
                    }
                )
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
                        with self._capture_lock:
                            self._update_flow_loss_state(metrics, ts)
                            self._captured_stats[ts] = metrics
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

            start = self._flow_loss_start.get(name)
            if is_losing and start is None:
                self._flow_loss_start[name] = ts
            elif not is_losing and start is not None:
                elapsed = ts - start
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

    @staticmethod
    def _device_group_name(port_name, dg_cfg, dg_index) -> str:
        """Resolve a device group's snappi device name.

        Honors DeviceGroupConfig.device_group_name, then tag_name, so
        playbooks can address groups by regex (e.g. "ECMP_2").  Falls back
        to the positional name when neither is set.  Both thrift fields are
        `optional string`, so anything non-str is treated as unset.
        """
        for attr in ("device_group_name", "tag_name"):
            value = getattr(dg_cfg, attr, None)
            if isinstance(value, str) and value:
                return value
        return f"{port_name}_DG{dg_index}"

    def _build_device_group(self, port_name, dg_cfg) -> None:
        """Expand one device group into `multiplier` simulated devices.

        Each device gets its own name, MAC, addresses (advanced by the config's
        increment) and BGP peer.  N devices advertising the same prefixes is what
        gives the DUT N next-hops per prefix, i.e. real ECMP members — this is
        the mechanism restpy provides and the OTG backend previously ignored,
        building exactly one device regardless of `multiplier`.

        Every device counts against ixia-c community edition's cap of 4
        control-plane interfaces and 4 sessions, so a multiplied group needs a
        licensed deployment.  See taac/otg/HARDENING_SETUP.md.
        """
        dg_index = dg_cfg.device_group_index
        base_name = self._device_group_name(port_name, dg_cfg, dg_index)
        multiplier = max(1, int(getattr(dg_cfg, "multiplier", 1) or 1))
        enabled = bool(getattr(dg_cfg, "enable", True))
        ip_cfg = dg_cfg.ip_addresses_config

        port_idx = next(
            (
                i
                for i, p in enumerate(self.ixia_config.port_configs)
                if p.port_name == port_name
            ),
            0,
        )

        info: t.Dict[str, t.Any] = {
            "port": port_name,
            "dg_idx": dg_index,
            "name": base_name,
            "count": multiplier,
            "peers": [],
            "mac": "",
            "ip": "",
            "gateway": "",
            "af": "v4",
            "addrs": {},
        }

        for offset in range(multiplier):
            # Single-device groups keep their bare name so device-group regexes
            # and existing configs behave exactly as before.
            device_name = base_name if multiplier == 1 else f"{base_name}_{offset + 1}"
            device = self.config.devices.device(name=device_name)[-1]

            mac = (
                f"00:00:{port_idx + 1:02x}:{dg_index:02x}:"
                f"{(offset >> 8) & 0xFF:02x}:{offset & 0xFF:02x}"
            )
            eth = device.ethernets.ethernet(name=f"{device_name}_eth")[-1]
            eth.connection.port_name = port_name
            eth.mac = mac

            # Record BOTH address families.  A dual-stack group has a v4 and a v6
            # address on one ethernet, and a flow must use the pair matching its
            # own family — including the gateway, since a v6 flow needs the v6
            # gateway's MAC from ND rather than the v4 one from ARP.
            addrs: t.Dict[str, t.Dict[str, str]] = {}
            if ip_cfg:
                addrs = self._build_ip_stack(
                    eth, device_name, ip_cfg, offset=offset
                ) or {}

            if offset == 0:
                # The first device represents the group for flow resolution:
                # traffic sources from one address, not all of them.
                af = "v4" if "v4" in addrs else ("v6" if "v6" in addrs else "v4")
                info.update(
                    mac=mac,
                    addrs=addrs,
                    af=af,
                    ip=addrs.get(af, {}).get("ip", ""),
                    gateway=addrs.get(af, {}).get("gateway", ""),
                )

            self._device_group_keys[device_name] = (port_name, dg_index)

            if dg_cfg.bgp_config:
                # _build_bgp_config appends to _bgp_peer_names; capture the delta
                # so toggle_device_groups can resolve a group to just its peers —
                # all of them, across every simulated device.
                peers_before = len(self._bgp_peer_names)
                self._build_bgp_config(
                    device,
                    device_name,
                    dg_cfg.bgp_config,
                    port_name=port_name,
                    dg_index=dg_index,
                    # Distinct router IDs are mandatory: N devices sharing one
                    # would fail to establish.
                    force_derived_router_id=multiplier > 1,
                )
                info["peers"].extend(self._bgp_peer_names[peers_before:])

        # A disabled group is built in full — addresses, peers, route ranges — so
        # that a playbook toggling it on has something to bring up.  Only its
        # peers' expected state differs.
        if not enabled:
            for peer_name in info["peers"]:
                self._mark_unrequired(peer_name, UNREQUIRED_DISABLED)
            self.logger.info(
                f"[OTG]   Device group {base_name} is disabled: "
                f"{len(info['peers'])} peer(s) held down until a playbook "
                f"enables it"
            )

        self._device_group_info[(port_name, dg_index)] = info
        if multiplier > 1:
            self.logger.info(
                f"[OTG]   Device group {base_name}: {multiplier} devices "
                f"({len(info['peers'])} BGP peer(s))"
            )

    def _build_bgp_on_port(self, port_name, port_cfg) -> None:
        bgp_info = getattr(port_cfg, "bgp_config_info", None)
        if not bgp_info:
            return
        device_name = f"{port_name}_PORT"
        device = self.config.devices.device(name=device_name)[-1]

        port_idx = next(
            (
                i
                for i, p in enumerate(self.ixia_config.port_configs)
                if p.port_name == port_name
            ),
            0,
        )
        eth = device.ethernets.ethernet(name=f"{device_name}_eth")[-1]
        eth.connection.port_name = port_name
        eth.mac = f"00:00:{port_idx + 1:02x}:00:00:01"

        ip_addresses = getattr(port_cfg, "ip_addresses", None)
        if ip_addresses:
            self._build_ip_stack(eth, device_name, ip_addresses)
        self._build_bgp_config(device, device_name, bgp_info, port_name=port_name)

    def _build_ip_stack(self, eth, device_name, ip_cfg, offset: int = 0):
        """Attach IP stacks to `eth`, returning {af: {ip, gateway}}.

        `offset` is the simulated device's index within its device group; each
        address is advanced by that many increments so every device of a
        multiplied group gets its own address.  The gateway advances by
        gateway_increment_ip, which is normally zero — every device peers with
        the same DUT address.
        """
        applied: t.Dict[str, t.Dict[str, str]] = {}

        if ip_cfg.ipv4_addresses_config:
            v4 = ip_cfg.ipv4_addresses_config
            address = _offset_ip(
                v4.starting_ip, getattr(v4, "increment_ip", None), offset
            )
            gateway = _offset_ip(
                v4.gateway_starting_ip,
                getattr(v4, "gateway_increment_ip", None) or "0.0.0.0",
                offset,
            )
            eth.ipv4_addresses.ipv4(
                name=getattr(v4, "ip_obj_name", None) or f"{device_name}_ipv4",
                address=address,
                gateway=gateway,
                prefix=v4.subnet_mask,
            )
            applied["v4"] = {"ip": address, "gateway": gateway}

        if ip_cfg.ipv6_addresses_config:
            v6 = ip_cfg.ipv6_addresses_config
            address = _offset_ip(
                v6.starting_ip, getattr(v6, "increment_ip", None), offset
            )
            gateway = _offset_ip(
                v6.gateway_starting_ip,
                getattr(v6, "gateway_increment_ip", None) or "::",
                offset,
            )
            eth.ipv6_addresses.ipv6(
                name=getattr(v6, "ip_obj_name", None) or f"{device_name}_ipv6",
                address=address,
                gateway=gateway,
                prefix=v6.subnet_mask,
            )
            applied["v6"] = {"ip": address, "gateway": gateway}

        if applied:
            return applied

        # The legacy ip_addr_1 shape predates `multiplier` and has no increment
        # to advance, so it silently ignores `offset`: N devices would land on
        # one address, sharing a router ID and establishing no sessions, with
        # nothing in the config looking wrong.  Unreachable from the current
        # configs, so refusing costs nothing and removes the trap.
        if offset and hasattr(ip_cfg, "ip_addr_1") and ip_cfg.ip_addr_1:
            raise ValueError(
                f"Device group {device_name} uses the legacy ip_addr_1 address "
                f"config, which cannot express per-device offsets, but was given "
                f"multiplier offset {offset}. Use ipv4_addresses_config / "
                f"ipv6_addresses_config for multiplied groups."
            )

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

    def _derive_router_id(self, port_name, device_name) -> str:
        """Allocate a distinct synthetic IPv4 router ID for a v6-only speaker.

        Allocation is sequential within the RFC 5737 TEST-NET-1 documentation
        prefix (192.0.2.0/24) and memoised per device, so repeated calls for
        the same device return the same ID.
        """
        key = (port_name, device_name)
        existing = self._router_ids.get(key)
        if existing:
            return existing
        if len(self._router_ids) >= 254:
            raise RuntimeError(
                "Exhausted synthetic router IDs in 192.0.2.0/24 "
                f"({len(self._router_ids)} allocated); v6-only BGP device "
                "groups need explicit IPv4 router IDs at this scale"
            )
        router_id = f"192.0.2.{len(self._router_ids) + 1}"
        self._router_ids[key] = router_id
        self.logger.info(
            f"[OTG]   Derived router_id {router_id} for {device_name} "
            f"(v6-only peer on {port_name})"
        )
        return router_id

    def _build_bgp_config(
        self,
        device,
        device_name,
        bgp_info,
        port_name,
        dg_index=None,
        force_derived_router_id: bool = False,
    ) -> None:
        router_id_set = False
        for af_label, bgp_cfg in [
            ("v4", bgp_info.bgp_v4_config),
            ("v6", bgp_info.bgp_v6_config),
        ]:
            if not bgp_cfg:
                continue
            peer_cfg = bgp_cfg.bgp_peer_config
            if not router_id_set:
                local_ip = peer_cfg.local_peer_starting_ip
                if force_derived_router_id or ":" in local_ip:
                    # router_id must be a dotted quad, so derive a synthetic one.
                    # Every speaker needs a DISTINCT ID or sessions fail to
                    # establish, hence keying on (port, device).  port_name is
                    # passed in because it cannot be inferred from device_name,
                    # which callers override via device_group_name.
                    local_ip = self._derive_router_id(port_name, device_name)
                device.bgp.router_id = local_ip
                router_id_set = True
            peer_name = f"{device_name}_bgp_{af_label}"
            as_type = (
                "ebgp" if peer_cfg.peer_type == ixia_types.BgpPeerType.EBGP else "ibgp"
            )
            self._bgp_peer_names.append(peer_name)

            if af_label == "v4":
                iface = device.bgp.ipv4_interfaces.v4interface()[-1]
                iface.ipv4_name = f"{device_name}_ipv4"
                peer = iface.peers.v4peer()[-1]
                peer.name = peer_name
                peer.peer_address = peer_cfg.remote_peer_starting_ip
                peer.as_type = as_type
                peer.as_number = peer_cfg.local_as or peer_cfg.local_as_4_bytes or 0
            else:
                iface = device.bgp.ipv6_interfaces.v6interface()[-1]
                iface.ipv6_name = f"{device_name}_ipv6"
                peer = iface.peers.v6peer()[-1]
                peer.name = peer_name
                peer.peer_address = peer_cfg.remote_peer_starting_ip
                peer.as_type = as_type
                peer.as_number = peer_cfg.local_as or peer_cfg.local_as_4_bytes or 0

            if hasattr(peer, "advanced"):
                adv = peer.advanced
                if peer_cfg.hold_timer:
                    adv.hold_time_interval = peer_cfg.hold_timer
                if peer_cfg.keepalive_timer:
                    adv.keep_alive_interval = peer_cfg.keepalive_timer

            if hasattr(peer, "capability") and peer_cfg.capabilities:
                cap = peer.capability
                cap_map = {
                    ixia_types.BgpCapability.IpV4Unicast: "ipv4_unicast",
                    ixia_types.BgpCapability.IpV6Unicast: "ipv6_unicast",
                    ixia_types.BgpCapability.RouteRefresh: "route_refresh",
                }
                requested = {
                    cap_map[c] for c in peer_cfg.capabilities if c in cap_map
                }
                for attr in ("ipv4_unicast", "ipv6_unicast", "route_refresh"):
                    if hasattr(cap, attr):
                        setattr(cap, attr, attr in requested)

            effective_as = peer_cfg.local_as or peer_cfg.local_as_4_bytes or 0
            self.logger.info(
                f"[OTG]   BGP peer {peer_name}: "
                f"AS {effective_as} -> {peer_cfg.remote_peer_starting_ip}"
            )

            if bgp_cfg.bgp_prefix_configs:
                for prefix_cfg in bgp_cfg.bgp_prefix_configs:
                    self._build_bgp_prefix(peer, af_label, prefix_cfg, device_name)
                    if dg_index is not None:
                        self._record_advertised_prefix(
                            port_name, dg_index, af_label, prefix_cfg
                        )

            self._build_bgp_update_sequence(
                peer, getattr(bgp_cfg, "update_sequence", None), peer_name
            )

    def _build_bgp_update_sequence(self, peer, update_sequence, peer_name) -> None:
        """Attach an ordered raw-UPDATE sequence to a snappi BGP peer.

        OTG sends these after the session establishes and on every
        re-establishment, so a peer down/up re-triggers them without touching the
        pushed config — which is what lets a playbook drive this via
        control_state instead of set_config.  It is the only path to bytes the
        declarative route-range model cannot express.
        """
        entries = getattr(update_sequence, "updates", None) if update_sequence else None
        if not _nonempty_sequence(entries):
            return
        if not hasattr(peer, "replay_updates"):
            self.logger.warning(
                f"[OTG] Installed snappi has no peer.replay_updates; "
                f"dropping {len(entries)} UPDATE(s) for {peer_name}"
            )
            return

        replay = peer.replay_updates
        replay.choice = "raw_bytes"
        for entry in entries:
            update_bytes = getattr(entry, "update_bytes", None)
            if not isinstance(update_bytes, str) or not update_bytes:
                raise ValueError(
                    f"BgpUpdateSequenceEntry for {peer_name} has no update_bytes; "
                    f"only the raw-bytes arm is wired to OTG"
                )
            one = replay.raw_bytes.updates.oneupdatereplay()[-1]
            one.update_bytes = update_bytes
            one.time_gap = getattr(entry, "time_gap_ms", 0) or 0

        self._mark_unrequired(peer_name, UNREQUIRED_REPLAY)
        self.logger.info(
            f"[OTG]   BGP update sequence on {peer_name}: "
            f"{len(entries)} raw UPDATE(s); session state not required at setup"
        )

    def _record_advertised_prefix(
        self, port_name, dg_index, af_label, prefix_cfg
    ) -> None:
        """Index an advertised prefix so flows can address into it."""
        ng_index = getattr(prefix_cfg, "network_group_index", None)
        if ng_index is None:
            return
        key = (port_name, dg_index, ng_index, af_label)
        self._advertised_prefixes[key] = {
            "address": prefix_cfg.starting_ip,
            "prefix_len": prefix_cfg.prefix_length
            or (64 if af_label == "v6" else 24),
        }

    def _prefix_host_span(self, port_name, dg_index, ng_index, af_label):
        """(first host address, how many consecutive hosts to use), or None.

        A prefix-targeted flow with one src/dst pair lands in a single hash
        bucket, so it resolves one next-hop regardless of how many ECMP members
        the prefix has — enough to show a path works, not enough to show
        selection is spread.  Sweeping the destination across the prefix gives
        the DUT's hash something to vary on.
        """
        start = self._prefix_host_address(port_name, dg_index, ng_index, af_label)
        if start is None:
            return None
        info = self._advertised_prefixes[(port_name, dg_index, ng_index, af_label)]
        width = 128 if af_label == "v6" else 32
        # Hosts excluding the network address itself; a /31 or /32 leaves very
        # few, so never promise more than the prefix actually holds.
        available = max(1, (1 << (width - int(info["prefix_len"]))) - 1)
        return start, min(PREFIX_TARGETED_DST_COUNT, available)

    def _prefix_host_address(self, port_name, dg_index, ng_index, af_label):
        """First host address inside the prefix advertised at this endpoint.

        Returns None when nothing is advertised there, so the caller can fall
        back to the device group's own interface address.
        """
        info = self._advertised_prefixes.get(
            (port_name, dg_index, ng_index, af_label)
        )
        if not info:
            return None
        try:
            network = ipaddress.ip_network(
                f"{info['address']}/{info['prefix_len']}", strict=False
            )
        except ValueError as ex:
            self.logger.warning(
                f"[OTG] Cannot address into advertised prefix "
                f"{info['address']}/{info['prefix_len']}: {ex}"
            )
            return None
        # +1 lands on the first host of the range, which the DUT reaches via the
        # BGP route rather than a connected route.
        return str(network.network_address + 1)

    @staticmethod
    def _af_addrs(dg_info, af_label):
        """Per-AF {ip, gateway} for a device group, or None if absent.

        Tolerates the pre-`addrs` shape (a single ip/gateway pair tagged with its
        own `af`), since callers may still construct that.
        """
        addrs = dg_info.get("addrs")
        if isinstance(addrs, dict) and addrs:
            return addrs.get(af_label)
        if dg_info.get("af", "v4") == af_label and dg_info.get("ip"):
            return {
                "ip": dg_info["ip"],
                "gateway": dg_info.get("gateway", ""),
            }
        return None

    def _flow_endpoint_address(self, ep, af_addrs, af_label):
        """Destination/source address for one traffic endpoint.

        With network_group_index set, address into the BGP-advertised prefix so
        the frame is routed via BGP.  Otherwise use the device group's own
        interface address, which the DUT reaches over a connected route.
        """
        ng_index = getattr(ep, "network_group_index", None)
        if ng_index is not None:
            addr = self._prefix_host_address(
                ep.port_name, ep.device_group_index, ng_index, af_label
            )
            if addr:
                return addr
            self.logger.warning(
                f"[OTG] Endpoint {ep.port_name} dg={ep.device_group_index} "
                f"network_group={ng_index} has no advertised {af_label} prefix; "
                f"falling back to the interface address"
            )
        return (af_addrs or {}).get("ip", "")

    def _prefix_step(self, increment_ip, prefix_length, af_label) -> int:
        """Convert an address-delta increment into snappi's block-count step.

        `increment_ip` is an address delta ("0.0.1.0"); snappi's route-range
        step counts prefix BLOCKS.  Dividing by the block size is therefore
        mandatory, and getting it wrong fails silently: the range simply walks
        2**host_bits times too far and overlaps whatever else is advertised
        there, so two speakers end up competing over prefixes the config says
        are distinct.  Both families go through here for exactly that reason --
        this was fixed for v6 alone once, and the v4 baseline stayed broken.
        """
        if af_label == "v4":
            width, default_len = 32, 24
            raw = int(ipaddress.IPv4Address(increment_ip))
        else:
            width, default_len = 128, 64
            raw = int(ipaddress.IPv6Address(increment_ip))

        plen = prefix_length or default_len
        host_bits = width - plen
        step = raw >> host_bits if host_bits > 0 else raw

        if step == 0:
            self.logger.warning(
                f"[OTG] Prefix step {increment_ip} is smaller than one /{plen} "
                f"block; every prefix would collapse onto one address. Using 1."
            )
            return 1
        if step > 0xFFFFFFFF:
            self.logger.warning(
                f"[OTG] Prefix step {increment_ip} exceeds uint32 for /{plen} "
                f"(got {step}); using 1."
            )
            return 1
        return step

    def _build_bgp_prefix(self, peer, af_label, prefix_cfg, device_name="") -> None:
        route_name = prefix_cfg.prefix_name or f"{device_name}_route_{af_label}"
        if af_label == "v4":
            route_range = peer.v4_routes.v4routerange()[-1]
            route_range.name = route_name
            addr = route_range.addresses.v4routeaddress()[-1]
            addr.address = prefix_cfg.starting_ip
            addr.prefix = prefix_cfg.prefix_length or 24
            addr.count = prefix_cfg.count or 1
            if prefix_cfg.increment_ip:
                addr.step = self._prefix_step(
                    prefix_cfg.increment_ip, prefix_cfg.prefix_length, "v4"
                )
        else:
            route_range = peer.v6_routes.v6routerange()[-1]
            route_range.name = route_name
            addr = route_range.addresses.v6routeaddress()[-1]
            addr.address = prefix_cfg.starting_ip
            addr.prefix = prefix_cfg.prefix_length or 64
            addr.count = prefix_cfg.count or 1
            if prefix_cfg.increment_ip:
                addr.step = self._prefix_step(
                    prefix_cfg.increment_ip, prefix_cfg.prefix_length, "v6"
                )

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
            tx_names = [
                self._resolve_endpoint(ep) for ep in (ti.source_endpoints or [])
            ]
            rx_names = [self._resolve_endpoint(ep) for ep in (ti.dest_endpoints or [])]

            bidir = getattr(
                getattr(ti, "traffic_flow_config", None),
                "bidirectional",
                False,
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
                # snappi serializes a default "bidirectional" field that
                # some OTG controllers reject; remove it since we handle
                # bidirectional flows by creating separate flow objects.
                props = getattr(flow.tx_rx.device, "_properties", {})
                props.pop("bidirectional", None)

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
                        tcp.dst_port.value = getattr(l4, "tcp_dst_port", 0)
                    elif hasattr(l4, "udp_src_port") and l4.udp_src_port:
                        udp = flow.packet.udp()
                        udp.src_port.value = l4.udp_src_port
                        udp.dst_port.value = getattr(l4, "udp_dst_port", 0)

                self._configure_flow_rate(flow, ti)
                self._configure_flow_size(flow, ti)
                self._configure_flow_duration(flow, ti)

                flow.metrics.enable = True

                self.logger.info(f"[OTG]   Flow {flow_name}: {tx} -> {rx}")

    # ------------------------------------------------------------------
    # restpy PacketHeader -> snappi translation (narrow; see the field map)
    # ------------------------------------------------------------------

    @staticmethod
    def _packet_header_stack(header) -> str:
        """Extract the lowercased stack name from a PacketHeader query regex."""
        regex = getattr(getattr(header, "query", None), "regex", "") or ""
        return regex.strip("^$").strip().lower()

    @staticmethod
    def _is_zero_step(step) -> bool:
        """True when an increment step is a no-op (all-zero address or 0)."""
        if step is None:
            return True
        if isinstance(step, (int, float)):
            return step == 0
        return all(ch in "0:." for ch in str(step))

    @staticmethod
    def _attr_value(attr) -> t.Any:
        """Unwrap an ixia AttrValue union to a plain Python value."""
        value = getattr(attr, "value", None)
        if value is None:
            return None
        for field in ("str", "integer", "str_list", "integer_list", "boolean"):
            unwrapped = getattr(value, field, None)
            if unwrapped is not None:
                return unwrapped
        return None

    @classmethod
    def _field_attrs(cls, field) -> t.Dict[str, t.Any]:
        """Collapse a Field's Attr list into a {name: value} dict.

        By the time a PacketHeader reaches OtgTrafficGen, the TrafficGenerator
        pipeline (create_packet_headers) has already flattened attrs_json AND
        resolved every Reference into this same Attr list — so there is no
        reference indirection left to handle here.
        """
        return {
            attr.name: cls._attr_value(attr)
            for attr in (getattr(field, "attrs", None) or [])
        }

    def apply_packet_headers(
        self,
        flow,
        packet_headers: t.Sequence,
    ) -> t.Dict[str, t.Any]:
        """Translate an ixia PacketHeader list onto a snappi flow.

        Returns {stack_name: snappi header} so callers can post-process (e.g.
        apply QoS to the L3 header).

        Only the stacks and fields in _PACKET_HEADER_FIELD_MAP are understood.
        Anything else raises NotImplementedError naming the offending
        stack/field — a silent drop would produce a flow that looks configured
        but sends the wrong frames.
        """
        stacks: t.Dict[str, t.Any] = {}
        for header in packet_headers:
            stack = self._packet_header_stack(header)
            field_map = _PACKET_HEADER_FIELD_MAP.get(stack)
            if field_map is None:
                raise NotImplementedError(
                    f"OTG packet-header translation does not support stack "
                    f"{stack!r} (supported: {sorted(_PACKET_HEADER_FIELD_MAP)})"
                )
            builder = getattr(flow.packet, stack, None)
            if builder is None:
                raise NotImplementedError(
                    f"snappi has no {stack!r} packet header builder"
                )
            hdr = builder()[-1]
            stacks[stack] = hdr

            for field in getattr(header, "fields", None) or []:
                raw_name = getattr(getattr(field, "query", None), "regex", "") or ""
                attr = field_map.get(raw_name.strip().lower())
                if attr is None:
                    raise NotImplementedError(
                        f"OTG packet-header translation does not support field "
                        f"{raw_name!r} on stack {stack!r} "
                        f"(supported: {sorted(field_map)})"
                    )
                self._apply_packet_field(getattr(hdr, attr), field, stack, attr)
        return stacks

    def _apply_packet_field(self, target, field, stack, attr) -> None:
        """Apply one Field's value pattern onto a snappi field."""
        attrs = self._field_attrs(field)
        value_type = str(attrs.get("ValueType", "") or "").lower()
        where = f"{stack}.{attr}"

        if not value_type:
            if "SingleValue" not in attrs:
                raise NotImplementedError(
                    f"OTG packet-header translation needs ValueType or "
                    f"SingleValue for {where}; got {sorted(attrs)}"
                )
            target.value = attrs["SingleValue"]
            return

        if value_type == "increment":
            start = attrs.get("StartValue")
            if start is None:
                raise NotImplementedError(
                    f"OTG packet-header translation needs a StartValue attr "
                    f"for the increment on {where}; got {sorted(attrs)}"
                )
            step = attrs.get("StepValue")
            count = attrs.get("CountValue") or 1
            # A count-1 or zero-step increment is a fixed value.  Emit it as
            # one so controllers that reject degenerate increments still
            # accept the flow.
            if count == 1 or self._is_zero_step(step):
                target.value = start
            else:
                target.increment.start = start
                target.increment.step = step
                target.increment.count = count
            return

        if value_type == "valuelist":
            values = attrs.get("ValueList")
            if values is None:
                raise NotImplementedError(
                    f"OTG packet-header translation needs a ValueList attr "
                    f"for the valueList on {where}; got {sorted(attrs)}"
                )
            if not isinstance(values, (list, tuple)):
                values = [values]
            values = list(values)
            if len(values) == 1:
                target.value = values[0]
            else:
                target.values = values
            return

        raise NotImplementedError(
            f"OTG packet-header translation does not support ValueType "
            f"{value_type!r} on {where} (supported: increment, valueList, "
            f"SingleValue)"
        )

    def _apply_flow_qos(self, stacks, ti) -> None:
        """Apply BasicTrafficItemConfig.qos_config DSCP to a flow's L3 header.

        IPv4 carries DSCP in the 6-bit PHB of the priority field; IPv6 carries
        it in the top 6 bits of the 8-bit traffic class, hence the << 2.
        """
        qos = getattr(ti, "qos_config", None)
        dscp = getattr(qos, "dscp_value", None) if qos is not None else None
        if not isinstance(dscp, int):
            return
        if "ipv4" in stacks:
            stacks["ipv4"].priority.dscp.phb.value = dscp
            self.logger.info(f"[OTG]     DSCP {dscp} on ipv4")
        elif "ipv6" in stacks:
            stacks["ipv6"].traffic_class.value = dscp << 2
            self.logger.info(f"[OTG]     DSCP {dscp} (tc {dscp << 2}) on ipv6")
        else:
            self.logger.warning(
                f"[OTG] qos_config DSCP {dscp} ignored: flow has no ipv4/ipv6 header"
            )

    def _resolve_endpoint(self, ep) -> str:
        if ep.endpoint_type == ixia_types.EndpointType.BGP_PREFIX:
            return ep.bgp_prefix_name or f"{ep.port_name}_route"
        info = self._device_group_info.get(
            (ep.port_name, ep.device_group_index)
        )
        dg_name = (
            info["name"]
            if info and isinstance(info.get("name"), str)
            else f"{ep.port_name}_DG{ep.device_group_index}"
        )
        for port_cfg in self.ixia_config.port_configs:
            if port_cfg.port_name != ep.port_name:
                continue
            for dg_cfg in port_cfg.device_group_configs or []:
                if dg_cfg.device_group_index != ep.device_group_index:
                    continue
                ip_cfg = dg_cfg.ip_addresses_config
                if ip_cfg:
                    if ip_cfg.ipv4_addresses_config:
                        return (
                            getattr(ip_cfg.ipv4_addresses_config, "ip_obj_name", None)
                            or f"{dg_name}_ipv4"
                        )
                    if ip_cfg.ipv6_addresses_config:
                        return (
                            getattr(ip_cfg.ipv6_addresses_config, "ip_obj_name", None)
                            or f"{dg_name}_ipv6"
                        )
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
