"""Single-DUT 1-RSW TestConfig generator.

`gen_rsw_test_config()` composes an OSS single-DUT RSW test config —
one DUT acting as a rack switch, peering eBGP with IXIA-emulated
neighbors over its downlink — by wrapping Meta's conveyor factory
(`test_config_for_bgp_and_fboss_platform_hardening_in_conveyor`) and
applying the OSS-specific adaptations in ONE reviewable place.

What this generator provides is **general to single-DUT RSW tests**
(not tied to any one playbook):

  * an IXIA-emulated eBGP block on BOTH ports (4 peers each: downlink at
    2001:db8:3::2..::5, uplink at 2001:db8:4::2..::5) + a single
    cross-port (downlink<->uplink) loss-probe traffic item;
  * the conveyor-factory wrapping (54 unused BGP-topology params → None),
    the BGP_SESSION_ESTABLISH_CHECK re-point at the IXIA peer ranges, the
    fresh-IXIA-setup (cache-off) safeguard, and a skip-list for checks
    with no OSS path yet.

The **playbook bundle is a parameter** (``playbooks=``). It defaults to
the agent-restart suite below, but any single-DUT RSW playbook set can
be passed — e.g. a longevity or feature-qual suite — reusing all of the
scaffolding above.

Note: the per-playbook check tuning (SERVICE_RESTART allowlist,
IXIA-loss ``clear``/``sleep`` windows) is keyed by the agent-restart
playbook *names* and no-ops for any other playbook — so those are
agent-restart-aware defaults, not general behavior. A different RSW
suite that needs its own loss/restart tuning would extend
``_annotate_check`` / the per-playbook spec dicts accordingly.

This is the RSW analogue of `taac/testconfigs/snake/test_test_config.py`
(`gen_snake_test_config`): the caller (an OSS config in
`taac/testconfigs/oss/`) resolves the DUT + IXIA wiring from the
topology/CSVs and passes them in as plain args; all the Meta-factory
adaptation lives here so the OSS config file stays a thin
topology-picker and this file is the single merge-conflict surface on
upstream sync.

Default playbook bundle (overridable via ``playbooks=``; see
`taac.playbooks.playbook_definitions`):
  - TEST_FBOSS_SW_AGENT_WARMBOOT_PLAYBOOK   (Service.FBOSS_SW_AGENT)
  - TEST_FBOSS_SW_AGENT_CRASH_PLAYBOOK      (Service.FBOSS_SW_AGENT)
  - TEST_FBOSS_HW_AGENT_0_RESTART_PLAYBOOK  (Service.FBOSS_HW_AGENT_0)
  - TEST_FBOSS_HW_AGENT_0_CRASH_PLAYBOOK    (Service.FBOSS_HW_AGENT_0)

The remaining 54 BGP-topology params of the factory are required args
but are only consumed by the factory's default playbook chain (replaced
by our explicit `playbooks`) and the BGP-specific tc_pre/postchecks — so
all 54 are passed as ``None``.

BGP_SESSION_ESTABLISH_CHECK fires against 8 IXIA-emulated peers
(remote-AS 65000): 4 downlink peers at ``2001:db8:3::2..::5`` and 4
uplink peers at ``2001:db8:4::2..::5``, peering with the DUT-side bgpd
(AS 65001) at ``2001:db8:3::1/64`` / ``2001:db8:4::1/64``. The DUT-side
agent.conf + ``/etc/coop/bgpcpp.conf`` must be pre-provisioned with that
L3 addressing and 4 BGP peer entries per port (see the parameters listed
below); the IXIA side is brought up by the
runner from the ``basic_port_configs`` blocks attached here.
"""

import ipaddress
import json

from ixia.ixia import types as ixia_types

from taac.health_check.health_check import types as hc_types
from taac.playbooks.playbook_definitions import (
    create_agent_and_bgpd_restart_playbook,
    create_agent_coldboot_playbook,
    create_bgpd_and_fsdb_restart_playbook,
    create_cgroup_system_slice_oom_kill_policy_playbook,
    create_fsdb_and_qsfp_service_restart_playbook,
    create_bgp_malformed_packet_test_playbook,
    create_cpu_high_priority_queue_overload_playbook,
    create_hardening_of_arp_overload_entries_playbook,
    create_hardening_of_ndp_overload_entries_playbook,
    create_qsfp_service_restart_playbook,
    create_longevity_activate_deactivate_all_prefixes_playbook,
    create_longevity_continuous_toggle_device_group_playbook,
    create_longevity_no_prefix_no_session_flap_playbook,
    create_longevity_prefix_flap_all_prefixes_playbook,
    create_longevity_session_flap_all_prefixes_playbook,
    create_qsfp_service_warmboot_and_agent_coldboot_playbook,
    create_qsfp_service_warmboot_and_tx_flap_playbook,
    TEST_AGENT_CRASH_PLAYBOOK,
    TEST_AGENT_WARMBOOT_AND_FSDB_RESTART_PLAYBOOK,
    TEST_AGENT_WARMBOOT_PLAYBOOK,
    TEST_BGPD_RESTART_PLAYBOOK,
    TEST_DEVICE_DRAIN_PLAYBOOK,
    TEST_FBOSS_HW_AGENT_0_CRASH_PLAYBOOK,
    TEST_FBOSS_HW_AGENT_0_RESTART_PLAYBOOK,
    TEST_FBOSS_SW_AGENT_CRASH_PLAYBOOK,
    TEST_FBOSS_SW_AGENT_WARMBOOT_PLAYBOOK,
    TEST_FSDB_CRASH_PLAYBOOK,
    TEST_FSDB_RESTART_PLAYBOOK,
    TEST_QSPF_RESTART_PLAYBOOK,
    TEST_QSPF_SERVICE_CRASH_PLAYBOOK,
)
from taac.health_checks.healthcheck_definitions import (
    create_cpu_queue_snapshot_check,
)
from taac.packet_headers import (
    ARP_REQUEST_TRAFFIC_PACKET_HEADERS,
    ARP_RESPONSE_TRAFFIC_PACKET_HEADERS,
    BGP_CP_TRAFFIC_PACKET_HEADERS,
    DHCP_V4_DISCOVER_TO_SERVER_TRAFFIC_PACKET_HEADERS,
    DHCP_V4_DISCOVER_TRAFFIC_PACKET_HEADERS,
    DHCP_V6_TRAFFIC_PACKET_HEADERS,
    HOP_LIMIT_0_IPV6_TRAFFIC_PACKET_HEADERS,
    HOP_LIMIT_1_IPV6_TRAFFIC_PACKET_HEADERS,
    ICMP_V4_ECHO_REQUEST_TRAFFIC_PACKET_HEADERS,
    ICMP_V6_REQUEST_TRAFFIC_PACKET_HEADERS,
    LACP_SLOW_TIMER_TRAFFIC_PACKET_HEADERS,
    LLDP_TRAFFIC_PACKET_HEADERS,
    NDP_NS_MULTICAST_TRAFFIC_PACKET_HEADERS,
    TTL_0_IPV4_TRAFFIC_PACKET_HEADERS,
    TTL_1_IPV4_TRAFFIC_PACKET_HEADERS,
)
from taac.stages.stage_definitions import create_steps_stage
from taac.steps.step_definitions import create_longevity_step
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.thrift_types import Params, PointInTimeHealthCheck
from taac.testconfigs.fboss_solution_tests.fboss_bgp_and_platform_hardening_conveyor import (
    test_config_for_bgp_and_fboss_platform_hardening_in_conveyor,
)
from taac.utils.json_thrift_utils import thrift_to_json

# Services SERVICE_RESTART_CHECK monitors on agent-restart playbooks.
# Modeled on Meta's ``SERVICES_TO_MONITOR_DURING_AGENT_RESTART = [coop,
# fsdb, qsfp_service]`` (taac/health_checks/constants.py) — the "stable
# through an agent bounce" set — minus ``coop``, which ships with the
# Meta-internal FBOSS image but may not be active on OSS FBOSS DUT
# images (unit exists but ``ActiveState=inactive``). Plus the two
# services these playbooks intentionally restart (``fboss_sw_agent``,
# ``fboss_hw_agent@0``) so the check also verifies they came back up.
_AGENT_RESTART_SERVICES = [
    "fsdb",
    "qsfp_service",
    "fboss_sw_agent",
    "fboss_hw_agent@0",
]

# Map from playbook name to the systemd service(s) that playbook
# intentionally restarts. Used to inject ``expected_restarted_services``
# into SERVICE_RESTART_CHECK's check_params so the check doesn't flag
# the playbook's OWN restart as a failure. Both sw_agent and hw_agent@0
# are listed for every playbook because the two are FSDB-coupled in
# FBOSS — restarting one cascades a restart of the other in some
# playbook stages (observed empirically).
_PLAYBOOK_INTENDED_RESTARTS = {
    "test_fboss_sw_agent_warmboot": ["fboss_sw_agent", "fboss_hw_agent@0"],
    "test_fboss_sw_agent_crash": ["fboss_sw_agent", "fboss_hw_agent@0"],
    "test_fboss_hw_agent_0_restart": ["fboss_sw_agent", "fboss_hw_agent@0"],
    "test_fboss_hw_agent_0_crash": ["fboss_sw_agent", "fboss_hw_agent@0"],
    # Generic agent restart/crash/warmboot (bounce the split agent).
    "test_agent_warmboot": ["fboss_sw_agent", "fboss_hw_agent@0"],
    "test_agent_crash": ["fboss_sw_agent", "fboss_hw_agent@0"],
    # Combined agent-warmboot + fsdb-restart.
    "test_agent_warmboot_and_fsdb_restart": [
        "fboss_sw_agent",
        "fboss_hw_agent@0",
        "fsdb",
    ],
    # bgpd restart (bgpd recovery is separately verified by the BGP checks;
    # here we only assert the stable set stayed up).
    "test_bgpd_restart": ["bgpd"],
    # qsfp_service restart / crash.
    "test_qsfp_restart": ["qsfp_service"],
    "test_qsfp_service_restart": ["qsfp_service"],
    "test_qspf_service_crash": ["qsfp_service"],
    # fsdb restart / crash.
    "test_fsdb_restart": ["fsdb"],
    "test_fsdb_crash": ["fsdb"],
    # Combined / concurrent restart playbooks. bgpd is listed for
    # completeness even though it's not in the monitored set.
    "test_bgpd_and_fsdb_restart": ["bgpd", "fsdb"],
    "test_agent_and_bgpd_restart": [
        "fboss_sw_agent",
        "fboss_hw_agent@0",
        "bgpd",
    ],
    "test_fsdb_and_qsfp_service_restart": ["fsdb", "qsfp_service"],
    # Agent coldboot (SYSTEMCTL_RESTART + cold_boot_once file) bounces the
    # split agent like a warmboot from systemd's perspective.
    "test_agent_coldboot": ["fboss_sw_agent", "fboss_hw_agent@0"],
    "test_qsfp_service_warmboot_and_agent_coldboot": [
        "qsfp_service",
        "fboss_sw_agent",
        "fboss_hw_agent@0",
    ],
    "test_qsfp_service_warmboot_and_tx_flap": ["qsfp_service"],
}

# Playbooks that intentionally SIGKILL / abort a service — an unclean
# exit is the whole POINT of the playbook, not a bug. UNCLEAN_EXIT_CHECK's
# ``exclude_services`` param drops these from its query so the intentional
# termination doesn't flag as a health failure. Distinct from
# ``_PLAYBOOK_INTENDED_RESTARTS`` (used by SERVICE_RESTART_CHECK /
# SYSTEMCTL_ACTIVE_STATE_CHECK): a clean restart (warmboot) MUST NOT get
# this exclusion — the check needs to catch the case where a warmboot
# silently produced a core dump (SIGABRT on shutdown), which the previous
# point-in-time OSS path missed and the collector-backed path with
# journalctl fallback now surfaces.
_PLAYBOOK_INTENDED_UNCLEAN_EXITS = {
    # Only the service the playbook actually SIGKILL's / abort()s belongs
    # here. Services that merely *restart* via induced coupling
    # (``fboss_hw_agent@0`` bouncing when ``fboss_sw_agent`` is killed,
    # via FSDB) go through the normal restart path and MUST NOT produce
    # an unclean exit — if one does, that is the same crash-on-shutdown
    # class of bug the check is designed to surface (mirrors the
    # deliberate omission of warmboot playbooks from this dict).
    "test_fboss_sw_agent_crash": ["fboss_sw_agent"],
    "test_fboss_hw_agent_0_crash": ["fboss_hw_agent@0"],
    "test_agent_crash": ["fboss_sw_agent", "fboss_hw_agent@0"],  # both SIGKILLed by pkill -f fboss_
    "test_qspf_service_crash": ["qsfp_service"],
    "test_fsdb_crash": ["fsdb"],
}

# CheckNames the factory's tc_prechecks/postchecks include that don't
# work on our OSS setup today. Filtered out (per playbook) before the
# TestConfig is returned.
_SKIP_CHECKS = {
    # META-INTERNAL-IMPL — impl class is not in the public slice. No OSS
    # path possible until upstream ships it (or the factory drops it).
    hc_types.CheckName.PREFIX_LIMIT_CHECK,
}

# Traffic item name used to probe dataplane packet loss during the
# playbook. Hairpins IPv6 traffic through a single device group of 4
# emulated peers, split into two network groups (src advertises
# ``2001:db8:1::/64``, dest advertises ``2001:db8:2::/64``). See
# ``_build_loss_probe_traffic_item`` for the layout.
_LOSS_PROBE_TRAFFIC_NAME_TMPL = "{host_upper}_BGP_AGENT_RESTART_LOSS_PROBE_V6"

# Per-playbook IXIA_PACKET_LOSS_CHECK spec. Threshold is ``"0"`` for all;
# any measured loss fails. ``clear_traffic_stats`` is chosen per the event's
# expected data-plane impact (FBOSS design intent):
#
# * CUMULATIVE (``clear=False``) — events that are LOSSLESS by design, so any
#   loss over the whole run is a regression:
#     - sw_agent warmboot: fastpath preserved through the restart.
# * POST-RECOVERY only (``clear=True``) — events that DO disrupt the datapath
#   because the hardware agent restarts and the ASIC is reprogrammed; the signal
#   is clean forwarding ONCE recovered. ``sleep_time`` sizes that window.
#     - sw_agent CRASH: on the wedge800 split-agent DUT, ``pkill -9
#       fboss_sw_agent`` cascades into a fboss_hw_agent@0 restart via the
#       FSDB coupling, so the ASIC gets reprogrammed and traffic is
#       interrupted (~3.8k pkts observed under load, not lossless). The
#       original spec here was ``clear=False`` based on the "hw_agent + ASIC
#       keep forwarding" assumption from a different platform; live smoke on
#       a live smoke disproved that assumption for this wedge800 build. Measure
#       post-recovery only, matching the other agent-crash playbooks.
#     - hw_agent restart / crash (60s — heavier ASIC reprogram).
#     - generic agent crash (``Service.AGENT`` -> ``pkill -9 -f fboss_`` kills
#       BOTH sw AND hw agent on this split/multi-switch DUT, so the hw agent
#       restarts and traffic is interrupted by design; 30s window).
#     - generic agent warmboot (``Service.AGENT`` SYSTEMCTL_RESTART -> on this
#       split/multi-switch DUT ``async_restart_service`` fans out to restart
#       BOTH ``fboss_sw_agent`` + ``fboss_hw_agent@0``; the hw-agent restart
#       reinits the ASIC, so ~1-2k pkts are dropped transiently and forwarding
#       recovers — measure post-recovery like the hw_agent restart (60s). NOTE:
#       this is NOT a "pure" warmboot (which would be lossless); it includes a
#       hw-agent restart by our chosen AGENT->both-agents mapping. If a lossless
#       control-plane-only warmboot is wanted instead, map AGENT->fboss_sw_agent
#       only in async_restart_service (then this would move to clear=False).
#     - agent warmboot + fsdb restart: same hw-agent reinit as above (60s).
#
# Other new service tests (qsfp/fsdb restart+crash, bgpd restart) don't touch
# the datapath and aren't listed here.
_PLAYBOOK_LOSS_CHECK_SPEC = {
    "test_fboss_sw_agent_warmboot":         {"clear": False, "sleep": 10},
    "test_fboss_sw_agent_crash":            {"clear": True,  "sleep": 30},
    "test_fboss_hw_agent_0_restart":        {"clear": True,  "sleep": 60},
    "test_fboss_hw_agent_0_crash":          {"clear": True,  "sleep": 60},
    "test_agent_crash":                     {"clear": True,  "sleep": 30},
    "test_agent_warmboot":                  {"clear": True,  "sleep": 60},
    "test_agent_warmboot_and_fsdb_restart": {"clear": True,  "sleep": 60},
    # Coldboot / combined-restart / tx-flap playbooks all restart the hw
    # agent (ASIC reprogram) or drop every link's laser — datapath loss is
    # by design, so measure the post-recovery window only.
    "test_agent_coldboot":                  {"clear": True,  "sleep": 60},
    "test_agent_and_bgpd_restart":          {"clear": True,  "sleep": 60},
    "test_qsfp_service_warmboot_and_agent_coldboot": {"clear": True, "sleep": 60},
    "test_qsfp_service_warmboot_and_tx_flap":        {"clear": True, "sleep": 60},
    # Malformed-UPDATE test: the NEXT_HOP-stripped announcements are
    # treat-as-withdrawn for the whole 1000s hold, so the probe blackholes
    # BY DESIGN (measured ~1000s of loss). The signal is clean forwarding
    # once the attribute is restored — measure post-recovery only.
    "test_bgp_malformed_packet_test":       {"clear": True,  "sleep": 60},
}

# BGP / IXIA peering parameters — kept in sync with the ``bgpcpp.conf`` +
# ``agent.conf`` shipped on the DUT:
#   DUT-AS: 65001; eBGP listeners at 2001:db8:3::1/64 (downlink SVI) and
#   2001:db8:4::1/64 (uplink SVI).
#   IXIA-emulated peers: 4 sessions per port, remote-AS 65000, from
#   2001:db8:3::2..::5 (downlink) and 2001:db8:4::2..::5 (uplink).
# The downlink peers advertise 2001:db8:1::/64-based routes, the uplink
# peers 2001:db8:2::/64-based ones; the loss probe rides downlink<->uplink
# between those two ranges.
_IXIA_BGP_LOCAL_AS = 65000
_IXIA_BGP_PEER_COUNT = 4
_DOWNLINK_BGP_GATEWAY_V6 = "2001:db8:3::1"
_DOWNLINK_BGP_PEER_STARTING_V6 = "2001:db8:3::2"
_UPLINK_BGP_GATEWAY_V6 = "2001:db8:4::1"
_UPLINK_BGP_PEER_STARTING_V6 = "2001:db8:4::2"
_DOWNLINK_ADVERTISED_PREFIX_V6 = "2001:db8:1::"
_UPLINK_ADVERTISED_PREFIX_V6 = "2001:db8:2::"
# IPv4 interfaces on each port (no v4 BGP) — gateway is the DUT's SVI v4 on
# that port. The downlink one lets IPv4 CPU-punt headers (ICMP-v4) resolve
# DST_GATEWAY_IPV4 / SRC_IPV4 references; the uplink one additionally serves
# as the ARP-overload playbook's good-entry device group.
_DOWNLINK_V4_GATEWAY = "10.0.3.1"
_DOWNLINK_V4_STARTING = "10.0.3.10"
_UPLINK_V4_GATEWAY = "10.0.4.1"
_UPLINK_V4_STARTING = "10.0.4.10"

# Override the factory's hardcoded ``ignore_all_prefixes_except`` list in
# BGP_SESSION_HEALTHCHECK_NO_V6_LOSS_EXPECTED (which targets Meta's
# internal range — our IXIA peers don't live there). Our peers are at
# 2001:db8:3::2..::5 + 2001:db8:4::2..::5; the check should validate
# sessions to both ranges.
_IXIA_BGP_PEER_PREFIXES = [
    f"{subnet}{i:x}"
    for subnet in ("2001:db8:3::", "2001:db8:4::")
    for i in range(2, 2 + _IXIA_BGP_PEER_COUNT)
]


def _build_bgp_port_config(
    dut_name,
    ixia_interface,
    *,
    peer_starting_v6,
    gateway_v6,
    advertised_prefix_v6,
    v4_starting,
    v4_gateway,
):
    """Build one port's BasicPortConfig with 4 IXIA-emulated IPv6 BGP peers.

    Called once per IXIA port (downlink + uplink). Expects the DUT-side
    ``/etc/coop/bgpcpp.conf`` to be provisioned with matching 4 BGP peer
    entries per port (local-AS 65001, remote-AS 65000; downlink peers at
    ``2001:db8:3::2..::5``, uplink at ``2001:db8:4::2..::5``) and the
    matching SVI addressing in ``agent.conf``.
    """
    return taac_types.BasicPortConfig(
        endpoint=f"{dut_name}:{ixia_interface}",
        device_group_configs=[
            taac_types.DeviceGroupConfig(
                device_group_index=0,
                multiplier=_IXIA_BGP_PEER_COUNT,
                v6_addresses_config=taac_types.IpAddressesConfig(
                    starting_ip=peer_starting_v6,
                    mask=64,
                    gateway_starting_ip=gateway_v6,
                ),
                v6_bgp_config=taac_types.BgpConfig(
                    local_as_4_bytes=_IXIA_BGP_LOCAL_AS,
                    local_as_increment=0,
                    enable_4_byte_local_as=True,
                    # Each port's 4 emulated peers advertise one /64 range
                    # (downlink: 2001:db8:1::, uplink: 2001:db8:2::). The
                    # loss probe sends between the two ports' ranges, so
                    # the DUT genuinely forwards downlink<->uplink.
                    route_scales=[
                        taac_types.RouteScaleSpec(
                            network_group_index=0,
                            v6_route_scale=taac_types.RouteScale(
                                multiplier=1,
                                prefix_count=100,
                                prefix_length=64,
                                starting_prefixes=advertised_prefix_v6,
                                prefix_step="0:0:0:1::",
                                ip_address_family=ixia_types.IpAddressFamily.IPV6,
                            ),
                        ),
                    ],
                ),
            ),
            # Device group index 1: an IPv4 interface (no v4 BGP), gateway = the
            # DUT's SVI v4 on this port. On the downlink this exists so IPv4
            # CPU-punt headers that reference ``device_group_index=1`` (e.g.
            # ICMP-v4-echo's SRC_IPV4 / DST_GATEWAY_IPV4, matching the Meta
            # factory's dg1=v4 convention) resolve; on the uplink it doubles as
            # the ARP-overload playbook's good-entry device group (the playbook
            # regex-matches device groups by interface name). IPv6 items use dg0.
            taac_types.DeviceGroupConfig(
                device_group_index=1,
                multiplier=1,
                v4_addresses_config=taac_types.IpAddressesConfig(
                    starting_ip=v4_starting,
                    mask=24,
                    gateway_starting_ip=v4_gateway,
                ),
            ),
            # Device group index 2: plain IPv6 hosts (no BGP) inside the same
            # SVI /64, at ::a000+. This is the NDP-overload playbook's target:
            # ``configure_ipv6_entries`` skips BGP-bearing v6 stacks (dg0) and
            # v4-only groups (dg1), so without this group the NDP injection
            # would silently no-op. Multiplier 1 at rest; the playbook scales
            # it up and back via its steps/cleanup.
            taac_types.DeviceGroupConfig(
                device_group_index=2,
                multiplier=1,
                v6_addresses_config=taac_types.IpAddressesConfig(
                    # Hosts live at gateway+0xa000 inside the SVI /64 (proper
                    # address arithmetic — string-slicing the gateway breaks
                    # for any gateway not ending in a bare ::1).
                    starting_ip=str(ipaddress.IPv6Address(gateway_v6) + 0xA000),
                    mask=64,
                    gateway_starting_ip=gateway_v6,
                ),
            ),
        ],
    )


def _build_loss_probe_traffic_item(dut_name, downlink_interface, uplink_interface):
    """Build the IPv6 packet-loss probe traffic item for IXIA_PACKET_LOSS_CHECK.

    Cross-port probe: the downlink port's 4 emulated peers (advertising
    ``2001:db8:1::/64``) exchange traffic with the uplink port's 4 peers
    (advertising ``2001:db8:2::/64``), so the DUT forwards every probe
    packet downlink<->uplink — the real RSW host-to-fabric path. That
    round-trip is what IXIA_PACKET_LOSS_CHECK measures across the
    disruption window. Rate is deliberately low (``line_rate=1`` %) — a
    steady probe stream, not a stress test.
    """
    return taac_types.BasicTrafficItemConfig(
        src_endpoints=[
            taac_types.TrafficEndpoint(
                name=f"{dut_name}:{downlink_interface}",
                device_group_index=0,
                network_group_index=0,
            ),
        ],
        dest_endpoints=[
            taac_types.TrafficEndpoint(
                name=f"{dut_name}:{uplink_interface}",
                device_group_index=0,
                network_group_index=0,
            ),
        ],
        name=_LOSS_PROBE_TRAFFIC_NAME_TMPL.format(host_upper=dut_name.upper()),
        traffic_type=ixia_types.TrafficType.IPV6,
        line_rate=1,
        line_rate_type=ixia_types.RateType.PERCENT_LINE_RATE,
        # MANY_TO_MANY fans out flows across every ordered pair of
        # (src emulated peer, dest emulated peer): 4×4 = 16 flows per
        # direction at 1% line rate.
        src_dest_mesh=ixia_types.SrcDestMeshType.MANY_TO_MANY,
        bidirectional=True,
    )


def _override_check_params(
    check: PointInTimeHealthCheck, overrides: dict
) -> PointInTimeHealthCheck:
    params_obj = check.check_params or Params(json_params="{}")
    params_dict = json.loads(params_obj.json_params or "{}")
    params_dict.update(overrides)
    # Copy the original Params via thrift-struct-callable so any fields we
    # don't touch (jq_params, static_params, transform_params, cache_params)
    # survive intact.
    return check(check_params=params_obj(json_params=json.dumps(params_dict)))


def _annotate_check(
    check: PointInTimeHealthCheck, playbook_name: str, dut_name: str
) -> PointInTimeHealthCheck:
    """Inject per-playbook overrides into a check's ``check_params``.

    * ``SERVICE_RESTART_CHECK`` — add a flat 3x10s retry budget (all
      playbooks) so a transient "Connection lost" probe failure recovers;
      and, for intentional-restart playbooks, override the (broad) default
      services list with the agent-restart set and inject
      ``expected_restarted_services`` so the check doesn't flag the
      playbook's OWN intentional restart.
    * ``BGP_SESSION_ESTABLISH_CHECK`` — re-point ``ignore_all_prefixes_except``
      at our IXIA peers (2001:db8:3::2..::5), pin the expected session
      count, and widen the retry budget (10 × 15s flat) so BGP has time
      to reconverge after an agent restart.
    * ``IXIA_PACKET_LOSS_CHECK`` — replace the entire ``input_json`` so the
      threshold points at our single hairpin probe with the per-playbook
      ``clear_traffic_stats`` / ``sleep_time`` from ``_PLAYBOOK_LOSS_CHECK_SPEC``.

    ``jq_params`` is preserved in every branch. All other checks return
    unchanged.
    """
    if check.name == hc_types.CheckName.SERVICE_RESTART_CHECK:
        # Retry the whole probe a few times. On this OSS split-agent DUT the
        # per-service thrift/uptime probe intermittently returns a transient
        # "Connection lost" (seen right after a ``pkill -9`` crash of a
        # *different* service, and once as a one-off blip during a long
        # longevity hold) even though the service stays up the entire time
        # (verified via systemd ActiveEnterTimestamp — no real restart). The
        # framework re-runs the full data-fetch + validation on a FAIL verdict
        # (ServiceRestartHealthCheck inherits RETRY_ON_FAIL=True), so a flat
        # 3x10s budget lets the transient connection recover and re-probe. A
        # genuinely inactive/restarted service still fails every attempt and is
        # reported — this adds tolerance for the flaky probe, not blindness to
        # real outages. Applied to ALL playbooks (incl. those with no intended
        # restart, e.g. longevity, whose check keeps its default service set).
        #
        # Also ALWAYS pin the monitored ``services`` to the DUT's real
        # always-up set (``_AGENT_RESTART_SERVICES``) rather than the factory/
        # runtime default, which includes ``openr`` + ``wedge_agent`` — neither
        # exists on this split-agent OSS DUT (both permanently INACTIVE), so the
        # default set fails EVERY playbook on phantom services, even a passive
        # longevity hold that restarts nothing. This is persistent (not a
        # transient the retry above can clear), so it must be corrected here.
        # ``expected_restarted_services`` is added only for playbooks that
        # intentionally restart something, so the check still flags an
        # *unexpected* restart of any monitored service.
        overrides = {
            "retry_count": 3,
            "retry_delay_seconds": 10,
            "retry_delay_multiplier": 1.0,
            "services": _AGENT_RESTART_SERVICES,
        }
        expected = _PLAYBOOK_INTENDED_RESTARTS.get(playbook_name)
        if expected:
            overrides["expected_restarted_services"] = expected
        return _override_check_params(check, overrides)
    if check.name == hc_types.CheckName.SYSTEMCTL_ACTIVE_STATE_CHECK:
        # Under the OSS collector-backed path this check is now window-based
        # rather than point-in-time: the collector samples every N seconds and
        # this check flags any service whose ``ActiveState`` was not
        # ``active`` at any sample in the window. That correctly catches
        # unintended flaps, but it also catches the *intentional* transient
        # ``deactivating`` / ``activating`` states of a service the playbook
        # itself restarts. Inject the same ``expected_restarted_services``
        # allowlist SERVICE_RESTART_CHECK already uses so the check subtracts
        # those before evaluating.
        expected = _PLAYBOOK_INTENDED_RESTARTS.get(playbook_name)
        if expected:
            return _override_check_params(
                check, {"expected_restarted_services": expected}
            )
        return check
    if check.name == hc_types.CheckName.UNCLEAN_EXIT_CHECK:
        # Playbooks that intentionally SIGKILL / abort a service produce a
        # real unclean exit that the collector's Result sampling AND the
        # journalctl fallback both flag — correctly, since the process WAS
        # terminated abnormally. Suppress the finding via
        # ``exclude_services`` for exactly those playbooks so their own
        # intended crash doesn't false-fail the postcheck. NOT applied to
        # warmboot playbooks: a clean systemctl-restart should not produce
        # an unclean exit, so if one shows up (e.g. an abort() during the
        # shutdown path) the check MUST surface it — that is precisely the
        # signal the collector migration + journalctl fallback exists to
        # catch.
        expected_unclean = _PLAYBOOK_INTENDED_UNCLEAN_EXITS.get(playbook_name)
        if expected_unclean:
            return _override_check_params(
                check, {"exclude_services": expected_unclean}
            )
        return check
    if check.name == hc_types.CheckName.BGP_SESSION_ESTABLISH_CHECK:
        # After ``fboss_hw_agent@0`` restart all BGP sessions go IDLE and
        # take ~70-80s+ to climb back to ESTABLISHED. Widen the retry
        # budget (10 × 15s = 150s flat; ``retry_delay_multiplier=1.0``
        # disables the default 1.5× backoff) so BGP has time to reconverge
        # under the playbook-level timeout. ``expected_established_session_count``
        # is required so a fully-filtered session set can't fall into the
        # "all established" backward-compat branch and PASS on 0 sessions.
        return _override_check_params(
            check,
            {
                "ignore_all_prefixes_except": _IXIA_BGP_PEER_PREFIXES,
                "expected_established_session_count": len(_IXIA_BGP_PEER_PREFIXES),
                "retry_count": 10,
                "retry_delay_seconds": 15,
                "retry_delay_multiplier": 1.0,
            },
        )
    if check.name == hc_types.CheckName.IXIA_PACKET_LOSS_CHECK:
        # Replace the check's entire ``input_json`` so its threshold list
        # points at our single hairpin probe instead of the factory's
        # DOWNLINK/UPLINK / NDP items. Per-playbook: warmboot measures
        # cumulative loss; the others clear stats and measure only the
        # post-recovery window. Threshold is always 0.
        spec = _PLAYBOOK_LOSS_CHECK_SPEC.get(playbook_name)
        if spec is None:
            return check
        input_ = hc_types.IxiaPacketLossHealthCheckIn(
            thresholds=[
                hc_types.PacketLossThreshold(
                    names=[
                        _LOSS_PROBE_TRAFFIC_NAME_TMPL.format(
                            host_upper=dut_name.upper()
                        )
                    ],
                    str_value="0",
                    expect_packet_loss=False,
                ),
            ],
            sleep_time=spec["sleep"],
            clear_traffic_stats=spec["clear"],
        )
        return check(input_json=thrift_to_json(input_))
    return check


# ---------------------------------------------------------------------------
# CPU control-plane punt suite (verify ARP / BGP-CP traffic is trapped to the
# CPU HIGH queue). These reuse the shared RSW IXIA/BGP scaffolding but add
# their own RAW traffic items + a CPU-queue snapshot check.
# ---------------------------------------------------------------------------
# The 1-RSW DUT is a wedge800 (WEDGE800BNHP). ``get_cpu_queue_constants``
# (netwhoami) doesn't know wedge800, so pin the queues here from the DUT's
# agent.conf cpuQueues: 0=low, 2=mid, 9=high (matches MONTBLANC/MINIPACK3BA).
_CPU_LOW_QUEUE = 0
_CPU_MID_QUEUE = 2
_CPU_HIGH_QUEUE = 9

# Default min egress pps the HIGH queue must show for a punt playbook to pass.
# This is the original/reference threshold; platforms that punt a given control
# protocol slower can lower it per-playbook via
# ``gen_rsw_test_config(cpu_punt_min_pps_overrides=...)`` without changing the
# default for everyone else. (The wedge800 1-RSW DUT's IPv6-oriented CoPP has no
# high-rate policer for IPv4 ARP, so ARP only trickles to the high queue at
# ~1pps — see the OSS picker, which overrides just the two ARP playbooks.)
_DEFAULT_CPU_PUNT_MIN_PPS = 10

# RAW punt traffic items -> playbook that starts each. The playbook's
# ``traffic_items_to_start`` starts ONLY its item (so these never disturb the
# agent-restart loss probe, and vice versa). Multiple playbooks may reference the
# same ``traffic_item_name`` (the item is created once — see
# ``_build_cpu_punt_traffic_items``). Fields:
#   (playbook_name, traffic_item_name, packet_headers, active_queues,
#    no_discard_queues, default_min_pps)
# ``active_queues`` are the CPU queue(s) the DUT's CoPP is expected to punt this
# protocol to (the check asserts each saw >= ``default_min_pps`` pps, overridable
# per-playbook via ``cpu_punt_min_pps_overrides``); ``no_discard_queues`` are the
# queues that must show no discards. For a NEGATIVE test (traffic must NOT punt)
# ``active_queues`` is empty and every queue is a no-discard queue. Note the LOW
# queue is rate-capped and legitimately discards under load, so low-queue punt
# tests assert no-discard on MID/HIGH only.
_CPU_PUNT_SUITE = [
    (
        "test_arp_traffic_punted_to_cpu_high_queue",
        "TEST_RAW_ARP_REQUEST_TRAFFIC",
        ARP_REQUEST_TRAFFIC_PACKET_HEADERS,
        [_CPU_HIGH_QUEUE],
        [_CPU_HIGH_QUEUE],
        _DEFAULT_CPU_PUNT_MIN_PPS,
    ),
    (
        "test_arp_response_traffic_punted_to_cpu_high_queue",
        "TEST_RAW_ARP_RESPONSE_TRAFFIC",
        ARP_RESPONSE_TRAFFIC_PACKET_HEADERS,
        [_CPU_HIGH_QUEUE],
        [_CPU_HIGH_QUEUE],
        _DEFAULT_CPU_PUNT_MIN_PPS,
    ),
    (
        "test_bgp_cp_traffic_punted_to_cpu_high_queue",
        "TEST_RAW_BGP_CP_TRAFFIC",
        BGP_CP_TRAFFIC_PACKET_HEADERS,
        [_CPU_HIGH_QUEUE],
        [_CPU_HIGH_QUEUE],
        _DEFAULT_CPU_PUNT_MIN_PPS,
    ),
    # DHCP relay traffic punts to the MID queue (rxReason DHCP -> queue 2).
    (
        "test_dhcp_v6_traffic_punted_to_cpu_mid_queue",
        "TEST_RAW_DHCP_V6_TRAFFIC",
        DHCP_V6_TRAFFIC_PACKET_HEADERS,
        [_CPU_MID_QUEUE],
        [_CPU_MID_QUEUE],
        _DEFAULT_CPU_PUNT_MIN_PPS,
    ),
    (
        "test_dhcp_v4_discover_traffic_punted_to_cpu_mid_queue",
        "TEST_RAW_DHCP_V4_DISCOVER_TRAFFIC",
        DHCP_V4_DISCOVER_TRAFFIC_PACKET_HEADERS,
        [_CPU_MID_QUEUE],
        [_CPU_MID_QUEUE],
        _DEFAULT_CPU_PUNT_MIN_PPS,
    ),
    (
        "test_dhcp_v4_discover_to_server_traffic_punted_to_cpu_mid_queue",
        "TEST_RAW_DHCP_V4_DISCOVER_TO_SERVER_TRAFFIC",
        DHCP_V4_DISCOVER_TO_SERVER_TRAFFIC_PACKET_HEADERS,
        [_CPU_MID_QUEUE],
        [_CPU_MID_QUEUE],
        _DEFAULT_CPU_PUNT_MIN_PPS,
    ),
    # Generic per-queue class-of-service checks: BGP-CP exercises the HIGH
    # queue, LLDP (rxReason LLDP -> queue 2) the MID queue.
    (
        "test_cpu_high_queue_traffic",
        "TEST_RAW_CPU_HIGH_QUEUE_TRAFFIC",
        BGP_CP_TRAFFIC_PACKET_HEADERS,
        [_CPU_HIGH_QUEUE],
        [_CPU_HIGH_QUEUE],
        _DEFAULT_CPU_PUNT_MIN_PPS,
    ),
    (
        "test_cpu_mid_queue_traffic",
        "TEST_RAW_LLDP_TRAFFIC",
        LLDP_TRAFFIC_PACKET_HEADERS,
        [_CPU_MID_QUEUE],
        [_CPU_MID_QUEUE],
        _DEFAULT_CPU_PUNT_MIN_PPS,
    ),
    # LLDP -> MID (shares the LLDP item above); LACP slow-protocol -> HIGH
    # (rxReason LACP -> queue 9).
    (
        "test_lldp_traffic_punted_to_cpu_mid_queue",
        "TEST_RAW_LLDP_TRAFFIC",
        LLDP_TRAFFIC_PACKET_HEADERS,
        [_CPU_MID_QUEUE],
        [_CPU_MID_QUEUE],
        _DEFAULT_CPU_PUNT_MIN_PPS,
    ),
    (
        "test_lacp_traffic_punted_to_cpu_high_queue",
        "TEST_RAW_LACP_TRAFFIC",
        LACP_SLOW_TIMER_TRAFFIC_PACKET_HEADERS,
        [_CPU_HIGH_QUEUE],
        [_CPU_HIGH_QUEUE],
        _DEFAULT_CPU_PUNT_MIN_PPS,
    ),
    # ICMP echo/request to the DUT's own SVI (my-IP) punts to the MID queue.
    (
        "test_icmp_v6_request_traffic_punted_to_cpu_mid_queue",
        "TEST_RAW_ICMP_V6_REQUEST_TRAFFIC",
        ICMP_V6_REQUEST_TRAFFIC_PACKET_HEADERS,
        [_CPU_MID_QUEUE],
        [_CPU_MID_QUEUE],
        _DEFAULT_CPU_PUNT_MIN_PPS,
    ),
    (
        "test_icmp_v4_echo_request_traffic_punted_to_cpu_mid_queue",
        "TEST_RAW_ICMP_V4_ECHO_REQUEST_TRAFFIC",
        ICMP_V4_ECHO_REQUEST_TRAFFIC_PACKET_HEADERS,
        [_CPU_MID_QUEUE],
        [_CPU_MID_QUEUE],
        _DEFAULT_CPU_PUNT_MIN_PPS,
    ),
    # NDP neighbour-solicitation (multicast) -> HIGH queue (rxReason NDP -> q9).
    (
        "test_ndp_ns_multicast_traffic_punted_to_cpu_high_queue",
        "TEST_RAW_NDP_NS_MULTICAST_TRAFFIC",
        NDP_NS_MULTICAST_TRAFFIC_PACKET_HEADERS,
        [_CPU_HIGH_QUEUE],
        [_CPU_HIGH_QUEUE],
        _DEFAULT_CPU_PUNT_MIN_PPS,
    ),
    # IPv6 hop-limit (the v6 analogue of IPv4 TTL). A hop-limit-1 packet is
    # routed, decremented to 0, and punted to the LOW queue (rxReason TTL_1 ->
    # queue 0); the LOW queue is rate-capped so it discards the excess -> assert
    # no-discard on MID/HIGH only.
    (
        "test_nexthop_limit_1_punted_to_cpu_low_queue",
        "TEST_RAW_HOP_LIMIT_1_IPV6_TRAFFIC",
        HOP_LIMIT_1_IPV6_TRAFFIC_PACKET_HEADERS,
        [_CPU_LOW_QUEUE],
        [_CPU_MID_QUEUE, _CPU_HIGH_QUEUE],
        _DEFAULT_CPU_PUNT_MIN_PPS,
    ),
    # Negative test: a hop-limit-0 packet is expected to be dropped in hardware
    # and NOT punted to CPU (no active queue; no discards on any queue).
    #
    # KNOWN FAILURE on wedge800: this ASIC traps hop-limit-0 to the
    # CPU LOW queue just like hop-limit-1 (measured ~500pps admitted + ~1400pps
    # discarded at 2000fps offered), so the no-discard-on-LOW assertion fails.
    # That is a genuine platform behavior difference from the reference ASIC
    # (which drops hop-limit-0 in hardware), NOT a config bug -- leave the check
    # faithful so it reports the real deviation rather than masking it.
    (
        "test_nexthop_limit_0_not_punted_to_cpu",
        "TEST_RAW_HOP_LIMIT_0_IPV6_TRAFFIC",
        HOP_LIMIT_0_IPV6_TRAFFIC_PACKET_HEADERS,
        [],
        [_CPU_LOW_QUEUE, _CPU_MID_QUEUE, _CPU_HIGH_QUEUE],
        _DEFAULT_CPU_PUNT_MIN_PPS,
    ),
    # IPv4 TTL — the v4 twin of the hop-limit tests above (v4 refs use the dg1
    # v4 interface). TTL-1 is routed, decremented to 0, punted to the LOW queue;
    # TTL-0 must NOT punt (negative test, faithful no-discard on all queues).
    # NOTE (same as hop-limit-0): this ASIC (wedge800) also traps TTL-0 to the
    # LOW queue, so test_ttl_0_... is expected to FAIL here — a genuine platform
    # difference, left unmasked rather than circumvented.
    (
        "test_ttl_1_ipv4_traffic_punted_to_cpu_low_queue",
        "TEST_RAW_TTL_1_IPV4_TRAFFIC",
        TTL_1_IPV4_TRAFFIC_PACKET_HEADERS,
        [_CPU_LOW_QUEUE],
        [_CPU_MID_QUEUE, _CPU_HIGH_QUEUE],
        _DEFAULT_CPU_PUNT_MIN_PPS,
    ),
    (
        "test_ttl_0_ipv4_traffic_not_punted_to_cpu",
        "TEST_RAW_TTL_0_IPV4_TRAFFIC",
        TTL_0_IPV4_TRAFFIC_PACKET_HEADERS,
        [],
        [_CPU_LOW_QUEUE, _CPU_MID_QUEUE, _CPU_HIGH_QUEUE],
        _DEFAULT_CPU_PUNT_MIN_PPS,
    ),
]


def _build_cpu_punt_traffic_items(dut_name, ixia_interface):
    """RAW control-plane traffic items injected on the single downlink port.

    Single-port: src == dest (the DUT traps the frame to CPU, so it is not
    forwarded back). ``allow_self_destined`` opts into the same-port endpoint
    set (as the loss probe does).
    """
    endpoint = f"{dut_name}:{ixia_interface}"
    items = []
    seen = set()
    for _name, item_name, headers, _active, _no_discard, _min_pps in _CPU_PUNT_SUITE:
        # Several playbooks may share one traffic item (e.g. LLDP feeds both
        # test_cpu_mid_queue_traffic and test_lldp_...); create it only once.
        if item_name in seen:
            continue
        seen.add(item_name)
        items.append(
            taac_types.BasicTrafficItemConfig(
                src_endpoints=[
                    taac_types.TrafficEndpoint(name=endpoint, device_group_index=0),
                ],
                dest_endpoints=[
                    taac_types.TrafficEndpoint(name=endpoint, device_group_index=0),
                ],
                name=item_name,
                line_rate_type=ixia_types.RateType.FRAMES_PER_SECOND,
                line_rate=2000,
                traffic_type=ixia_types.TrafficType.RAW,
                bidirectional=False,
                allow_self_destined=True,
                packet_headers=headers,
            )
        )
    return items


def _build_cpu_punt_playbooks(min_pps_overrides=None):
    """One playbook per RAW punt item: run 60s of traffic, then snapshot the
    CPU queues and assert the item's target queue saw the punted traffic with
    no drops.

    ``min_pps_overrides`` maps playbook name -> target-queue min pps, overriding
    the per-playbook default in ``_CPU_PUNT_SUITE`` for that platform only
    (e.g. the wedge800 1-RSW DUT lowers the two ARP playbooks without affecting
    the original threshold on other platforms).
    """
    overrides = min_pps_overrides or {}
    playbooks = [
        taac_types.Playbook(
            name=pb_name,
            enabled=True,
            traffic_items_to_start=[item_name],
            stages=[
                create_steps_stage(steps=[create_longevity_step(duration=60)]),
            ],
            snapshot_checks=[
                create_cpu_queue_snapshot_check(
                    active_queues=active_queues,
                    no_discard_queues=no_discard_queues,
                    active_min_out_pps_per_queue={
                        q: overrides.get(pb_name, default_min_pps)
                        for q in active_queues
                    },
                ),
            ],
        )
        for pb_name, item_name, _headers, active_queues, no_discard_queues, default_min_pps in _CPU_PUNT_SUITE
    ]
    # Queue prioritization: start burst-ish traffic to the LOW and MID queues
    # (TTL-1 -> low, DHCP-v6 -> mid) alongside BGP-CP (-> high), and assert the
    # HIGH queue takes NO drops even while low/mid are congested. Multi-item
    # (doesn't fit the single-item suite), so built explicitly; reuses the
    # suite's existing traffic items.
    playbooks.append(
        taac_types.Playbook(
            name="test_queue_prioritization_high_queue_no_drops",
            enabled=True,
            traffic_items_to_start=[
                "TEST_RAW_TTL_1_IPV4_TRAFFIC",
                "TEST_RAW_DHCP_V6_TRAFFIC",
                "TEST_RAW_BGP_CP_TRAFFIC",
            ],
            stages=[
                create_steps_stage(steps=[create_longevity_step(duration=60)]),
            ],
            snapshot_checks=[
                create_cpu_queue_snapshot_check(
                    active_queues=[_CPU_LOW_QUEUE, _CPU_MID_QUEUE, _CPU_HIGH_QUEUE],
                    no_discard_queues=[_CPU_HIGH_QUEUE],
                ),
            ],
        )
    )
    return playbooks


def gen_rsw_test_config(
    *,
    name: str = "OSS_SINGLE_DUT_RSW",
    dut_name: str,
    local_mac_address,
    ixia_downlink_interface: str,
    ixia_uplink_interface: str,
    ixia_connections,
    playbooks=None,
    cpu_punt_min_pps_overrides=None,
    basset_pool: str = "",
) -> taac_types.TestConfig:
    """Build a single-DUT 1-RSW ``TestConfig``.

    Args:
        name: Registered ``TestConfig.name``.
        dut_name: Single DUT hostname (the 1-RSW DUT).
        local_mac_address: DUT MAC (from ``device_info.csv``); may be
            ``None`` for inspection-only construction.
        ixia_downlink_interface: DUT-side interface facing the IXIA that
            carries the downlink BGP peering (``2001:db8:3::``) + the
            CPU-punt RAW items (e.g. ``"eth1/31/1"``).
        ixia_uplink_interface: Second IXIA-facing interface, carrying the
            uplink BGP peering (``2001:db8:4::``) and the far end of the
            cross-port loss probe (e.g. ``"eth1/32/1"``).
        ixia_connections: ``DirectIxiaConnection`` list for the DUT's
            IXIA circuits (both ports are exposed on the endpoint).
        playbooks: Playbook bundle to run. ``None`` (default) uses the
            agent-restart suite (warmboot/crash of the sw/hw agent); pass
            an explicit list to run any other single-DUT RSW suite on top
            of the same IXIA/BGP scaffolding.
        cpu_punt_min_pps_overrides: Optional ``{playbook_name: min_pps}`` map
            lowering (or raising) the HIGH-queue min-pps threshold for the
            CPU-punt playbooks on this platform only. Unlisted playbooks keep
            the ``_CPU_PUNT_SUITE`` default (``_DEFAULT_CPU_PUNT_MIN_PPS``), so
            other platforms are unaffected. Values are ints (thrift map). A 0
            floor still asserts the HIGH queue saw traffic (the check fails a
            queue with no packet increase) but drops the pps floor; the wedge800
            1-RSW DUT uses 0 for the two ARP playbooks (its v6 CoPP punts IPv4
            ARP at ~1pps).
        basset_pool: Basset reservation pool ("" for OSS).

    Returns:
        A ready-to-run ``TestConfig`` with the given (or default agent-
        restart) playbooks, per-playbook check tuning, the IXIA BGP
        block, and the hairpin loss-probe traffic item.
    """
    if playbooks is None:
        # WARMBOOT + RESTART + BGPD_RESTART ship ``enabled=False`` in
        # playbook_definitions.py, so we call them ``(enabled=True)`` to
        # flip them on. The CRASH / cgroup / device-drain playbooks inherit
        # the thrift default ``enabled = true``, so they're passed bare.
        # TEST_DEVICE_DRAIN_PLAYBOOK is tagged ``attribute_filters={"role":
        # ["FDSW"]}`` upstream; clear it so it runs on this RSW DUT.
        playbooks = [
            TEST_FBOSS_SW_AGENT_WARMBOOT_PLAYBOOK(enabled=True),
            TEST_FBOSS_SW_AGENT_CRASH_PLAYBOOK,
            TEST_FBOSS_HW_AGENT_0_RESTART_PLAYBOOK(enabled=True),
            TEST_FBOSS_HW_AGENT_0_CRASH_PLAYBOOK,
            TEST_BGPD_RESTART_PLAYBOOK(enabled=True),
            create_cgroup_system_slice_oom_kill_policy_playbook(),
            TEST_DEVICE_DRAIN_PLAYBOOK(attribute_filters={}),
            # qsfp_service restart/crash (service-interruption; qsfp_service runs
            # on the DUT). Names: test_qsfp_restart / test_qspf_service_crash
            # (the CRASH playbook's name carries an upstream misspelling).
            TEST_QSPF_RESTART_PLAYBOOK,
            # Multi-iteration variant (5x systemctl restart + convergence per
            # cycle) — distinct upstream playbook from single-shot
            # test_qsfp_restart above.
            create_qsfp_service_restart_playbook(),
            TEST_QSPF_SERVICE_CRASH_PLAYBOOK,
            # agent warmboot + FSDB (fsdb runs on the DUT) crash/restart, plus
            # the combined agent-warmboot+fsdb-restart. Service-interruption
            # tests; FSDB_RESTART ships enabled=False so it's flipped on.
            TEST_AGENT_CRASH_PLAYBOOK,
            TEST_AGENT_WARMBOOT_PLAYBOOK,
            TEST_AGENT_WARMBOOT_AND_FSDB_RESTART_PLAYBOOK,
            TEST_FSDB_CRASH_PLAYBOOK,
            TEST_FSDB_RESTART_PLAYBOOK(enabled=True),
            # BGP_DC longevity suite — churn (prefix/session flap, toggle) over
            # the config's device group; ``is_all_*_groups`` so they act on the
            # single downlink group without needing factory tags. These are
            # LONG (prefix/no-flap ~1000s, session-flap ~3600s).
            create_longevity_prefix_flap_all_prefixes_playbook(),
            create_longevity_session_flap_all_prefixes_playbook(),
            create_longevity_activate_deactivate_all_prefixes_playbook(),
            create_longevity_no_prefix_no_session_flap_playbook(),
            create_longevity_continuous_toggle_device_group_playbook(),
            # Combined / concurrent service-restart playbooks (all default
            # enabled=True).
            create_bgpd_and_fsdb_restart_playbook(),
            create_agent_and_bgpd_restart_playbook(),
            create_fsdb_and_qsfp_service_restart_playbook(),
            # Agent coldboot (drops the cold_boot_once file, so the agent
            # rebuilds hardware state from scratch), plus the qsfp-warmboot
            # combos layered on top of it / on a full-port TX flap.
            create_agent_coldboot_playbook(),
            create_qsfp_service_warmboot_and_agent_coldboot_playbook(),
            # Explicit interfaces: the playbook's default jq resolution
            # (."{dut}".interfaces) is empty on OSS topologies and crashes
            # the flap step; flap exactly the two IXIA-facing ports.
            create_qsfp_service_warmboot_and_tx_flap_playbook(
                interfaces=[ixia_downlink_interface, ixia_uplink_interface],
            ),
            # ARP overload-table hardening. Good entries land on the uplink
            # port's v4 device group, rogue on the downlink one (the
            # playbook's IXIA steps regex-match device groups by interface
            # name); counts follow the kodiak3-rbb reference config.
            create_hardening_of_arp_overload_entries_playbook(
                downlink_iface=ixia_downlink_interface,
                uplink_iface=ixia_uplink_interface,
                good_arp_entries=100,
                rogue_arp_entries=100,
                # Toggles are no-ops here (see analysis doc) — don't pay the
                # default 2x30s sleep per toggled device group (4 non-BGP
                # groups x 3 steps ~= 12 min of dead wait per playbook).
                sleep_time_between_toggle_s=5,
                # NOTE: the IXIA-emulated v4 hosts don't answer FBOSS's ARP
                # probes, so with the default arpTimeoutSeconds=60 all entries
                # purge within ~6 min (measured) and the postcheck reads an
                # empty table. Handled DUT-side: the testbed's agent.conf sets
                # arpTimeoutSeconds=1800 (REACHABLE lifetime 0.5-1.5x => 900s
                # min), so injected entries outlive the 600s hold. The entries
                # themselves come from the multiplier-change ApplyOnTheFly in
                # configure_ipv4_entries (the new hosts ARP the SVI on
                # re-init); the steps' toggle flags are historically no-ops
                # (see docs/rsw_new_playbooks_failure_analysis.md).
            ),
            # NDP overload-table hardening — the v6 twin. Scales the per-port
            # v6 host device groups (dg2, ::a000+ inside each SVI /64; the
            # BGP-bearing dg0 is skipped by configure_ipv6_entries). Aging is
            # covered by the same agent.conf knob: ApplyThriftConfig slaves
            # the NDP timeout to arpTimeoutSeconds (=1800). Step order is
            # good(dl) -> good(ul) -> rogue(dl), so the downlink group ends at
            # the rogue count: final table ~= rogue + good_ul (+ BGP peers /
            # link-locals), which must sit inside
            # (good_dl + good_ul, NDP_SOFT_LIMIT=4000).
            create_hardening_of_ndp_overload_entries_playbook(
                device_name=dut_name,
                downlink_iface=ixia_downlink_interface,
                uplink_iface=ixia_uplink_interface,
                good_ndp_entries_downlink=100,
                good_ndp_entries_uplink=100,
                rogue_ndp_entries=1000,
                sleep_time_between_toggle_s=5,
            ),
            # BGP malformed-UPDATE hardening: IXIA withholds the NEXT_HOP
            # attribute on the advertised routes (RFC 7606 treat-as-withdraw
            # exercise) for 1000s, then restores. Our network groups are named
            # BGP_PREFIX_V6_* (not the Meta tag names the default regex
            # expects). The BGP session postchecks are the real assertion:
            # all 8 sessions must survive the malformed announcements.
            create_bgp_malformed_packet_test_playbook(
                device_name=dut_name,
                network_group_regex="BGP_PREFIX_V6",
            ),
            # CPU high-queue overload: flood BGP-CP-destined traffic 150s,
            # then verify via pre/post snapshots that the real BGP sessions
            # never flapped (CoPP protection). Uses our RAW BGP-CP item (the
            # default regex names a Meta factory item); no rogue churn peers
            # on this config, so the snapshot ignore list is omitted. NOTE:
            # the item runs at 2000fps, which this DUT's high queue absorbs
            # without discards (see the punt suite) — this validates CoPP
            # sanity rather than a true saturation overload.
            create_cpu_high_priority_queue_overload_playbook(
                ixia_rogue_ic_parent_network_v6=None,
                ixia_rogue_ic_parent_network_v4=None,
                bgp_cp_traffic_regex="TEST_RAW_BGP_CP_TRAFFIC",
                # After the flood, switch back to the loss probe rather than
                # plain-disabling the CP item: on this config the CP item is
                # the only one running, and zero enabled items drops IXIA's
                # traffic module to kUnapplied (fails the 120s settle hold).
                background_traffic_regex=_LOSS_PROBE_TRAFFIC_NAME_TMPL.format(
                    host_upper=dut_name.upper()
                ),
            ),
        ]

    tc = test_config_for_bgp_and_fboss_platform_hardening_in_conveyor(
        test_config_name=name,
        device_name=dut_name,
        local_mac_address=local_mac_address,
        ixia_downlink_interface=ixia_downlink_interface,
        ixia_uplink_interface=ixia_uplink_interface,
        direct_ixia_connections=ixia_connections,
        # The 54 BGP-topology kwargs below are required args of the factory
        # but are only consumed by the default playbook chain and the
        # BGP-specific tc_pre/postchecks — both replaced/stripped for our
        # agent-restart smoke, so all 54 are passed as ``None``.
        peergroup_uplink_mimic_v6=None,
        peergroup_uplink_mimic_v4=None,
        peergroup_downlink_mimic_v6=None,
        peergroup_downlink_mimic_v4=None,
        peergroup_rogue_mimic_v6=None,
        peergroup_rogue_mimic_v4=None,
        route_map_uplink_ingress=None,
        route_map_uplink_egress=None,
        route_map_downlink_ingress=None,
        route_map_downlink_egress=None,
        route_map_rogue_ingress=None,
        route_map_rogue_egress=None,
        ixia_downlink_ic_parent_network_v6=None,
        ixia_uplink_ic_parent_network_v6=None,
        ixia_rogue_ic_parent_network_v6=None,
        ixia_downlink_ic_parent_network_v4=None,
        ixia_uplink_ic_parent_network_v4=None,
        ixia_rogue_ic_parent_network_v4=None,
        good_ndp_entry_network_v6=None,
        rogue_ndp_entry_network_v6=None,
        good_arp_entry_network_v4=None,
        rogue_arp_entry_network_v4=None,
        prefix_limit=None,
        per_peer_max_route_limit=None,
        downlink_peer_count=None,
        uplink_peer_count=None,
        rogue_peer_count=None,
        remote_downlink_as_4byte=None,
        remote_uplink_as_4byte=None,
        remote_rogue_as_4byte=None,
        is_uplink_peer_confed=None,
        is_downlink_peer_confed=None,
        is_rogue_peer_confed=None,
        ixia_downlink_prefix_count_v6=None,
        ixia_uplink_prefix_count_v6=None,
        ixia_rogue_prefix_count_v6=None,
        ixia_downlink_prefix_count_v4=None,
        ixia_uplink_prefix_count_v4=None,
        ixia_rogue_prefix_count_v4=None,
        ixia_uplink_good_ndp_network=None,
        ixia_downlink_good_ndp_network=None,
        ixia_downlink_communities=None,
        ixia_uplink_communities=None,
        downlink_peer_tag=None,
        uplink_peer_tag=None,
        ecmp_group_limit=None,
        good_ndp_entries_uplink=None,
        good_ndp_entries_downlink=None,
        rogue_ndp_entries=None,
        good_arp_entries=None,
        rogue_arp_entries=None,
        good_mac_entry_count=None,
        rogue_mac_entry_count=None,
        bgp_induced_ecmp_group_count=None,
        playbooks=playbooks,
        basset_pool=basset_pool,
    )

    loss_probe_name = _LOSS_PROBE_TRAFFIC_NAME_TMPL.format(
        host_upper=dut_name.upper()
    )
    return tc(
        # Agent-restart playbooks: scope traffic to the loss probe (so they
        # don't also start the CPU-punt RAW items now in the config —
        # ``traffic_items_to_start=None`` would start ALL of them), skip the
        # CheckNames in _SKIP_CHECKS, and route each survivor through
        # _annotate_check. Then append the CPU-punt suite (each of those starts
        # only its own RAW item).
        playbooks=[
            pb(
                traffic_items_to_start=[loss_probe_name],
                prechecks=[
                    _annotate_check(c, pb.name, dut_name)
                    for c in (pb.prechecks or [])
                    if c.name not in _SKIP_CHECKS
                ],
                postchecks=[
                    _annotate_check(c, pb.name, dut_name)
                    for c in (pb.postchecks or [])
                    if c.name not in _SKIP_CHECKS
                ],
            )
            for pb in tc.playbooks
        ]
        + _build_cpu_punt_playbooks(cpu_punt_min_pps_overrides),
        endpoints=[
            taac_types.Endpoint(
                name=dut_name,
                dut=True,
                ixia_ports=[ixia_downlink_interface, ixia_uplink_interface],
                mac_address=local_mac_address,
                direct_ixia_connections=ixia_connections,
            ),
        ],
        basic_port_configs=[
            _build_bgp_port_config(
                dut_name,
                ixia_downlink_interface,
                peer_starting_v6=_DOWNLINK_BGP_PEER_STARTING_V6,
                gateway_v6=_DOWNLINK_BGP_GATEWAY_V6,
                advertised_prefix_v6=_DOWNLINK_ADVERTISED_PREFIX_V6,
                v4_starting=_DOWNLINK_V4_STARTING,
                v4_gateway=_DOWNLINK_V4_GATEWAY,
            ),
            _build_bgp_port_config(
                dut_name,
                ixia_uplink_interface,
                peer_starting_v6=_UPLINK_BGP_PEER_STARTING_V6,
                gateway_v6=_UPLINK_BGP_GATEWAY_V6,
                advertised_prefix_v6=_UPLINK_ADVERTISED_PREFIX_V6,
                v4_starting=_UPLINK_V4_STARTING,
                v4_gateway=_UPLINK_V4_GATEWAY,
            ),
        ],
        # Single cross-port IPv6 traffic item so IXIA_PACKET_LOSS_CHECK has
        # traffic to measure against (replaces the factory's default 6
        # items, which reference None-valued BGP-topology kwargs).
        basic_traffic_item_configs=[
            _build_loss_probe_traffic_item(
                dut_name, ixia_downlink_interface, ixia_uplink_interface
            )
        ]
        + _build_cpu_punt_traffic_items(dut_name, ixia_downlink_interface),
        # Agent-restart smokes don't need PTP; keeping the factory's
        # PTPConfig would add setup time and another failure surface.
        ptp_configs=[],
        # The factory's setup_tasks are coop-patcher registrations,
        # configure_parallel_bgp_peers (calls async_register_python_patcher),
        # and add_stress_static_routes (calls async_add_static_route_patcher)
        # — all resolve to COOP patcher APIs that are not available in OSS.
        # Override with an empty list so nothing attempts those calls.
        setup_tasks=[],
        teardown_tasks=[],
        # Force a fresh IXIA setup every run — the default Tier-1 ixncfg
        # cache key doesn't cover ``basic_traffic_item_configs``, so a
        # cache HIT reloads a stale topology (0 traffic items) and the
        # loss check SKIPs, silently hiding regressions.
        ixia_config_cache=taac_types.IxiaConfigCache(enabled=False),
    )
