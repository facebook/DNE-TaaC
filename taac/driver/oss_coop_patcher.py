#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""OSS stand-in for Meta's COOP python-patcher mechanism.

In Meta mode a test config mutates a DUT's running config by registering
Python patchers with the COOP agent (``driver.async_register_python_patcher``
-> ``async_apply_patchers``). COOP does not exist in OSS, so ``FbossSwitch``
raises ``AttributeError`` and every patcher-based NPI config -- the whole
``cpu_queue_test_config`` family -- dies at setup with::

    'FbossSwitch' object has no attribute 'async_register_python_patcher'

This module implements the same contract against plain config files, which is
all COOP ultimately does:

* ``register`` queues a mutation in an in-process registry (nothing on the DUT
  changes yet -- matching COOP's register/apply split).
* ``apply`` snapshots the live config to ``<config>.baseline.conf`` (once),
  replays every queued mutation onto it, writes the result to
  ``<config>.patched.conf``, then *activates* that file by installing it at the
  path the service reads and restarting the service.
* ``restore`` puts ``<config>.baseline.conf`` back, for teardown.

Keeping the patched and baseline variants side by side on the DUT means the
active config is always inspectable and one ``cp`` from being reverted, which
mirrors how testbed config directories already keep variant configs side by
side.

The mutations run *on the DUT* via a generated script rather than by pulling
the config back over SSH: a bgpcpp config is ~1.7 MB, and writing that back
through ``async_run_cmd_on_shell`` would mean dozens of chunked round trips.
The script and its arguments are a few KB, so one call does it.

Only the operations the OSS test configs actually use are implemented; an
unknown ``py_func_name`` raises rather than silently no-op'ing, so a config
relying on an unported patcher fails loudly instead of running against a DUT
that was never configured.
"""

import base64
import json
import logging
import typing as t
from dataclasses import dataclass, field


logger = logging.getLogger(__name__)

# config_name -> (path the service reads, systemd unit to restart)
CONFIG_FILES: t.Dict[str, t.Tuple[str, str]] = {
    "agent": ("/etc/coop/agent.conf", "fboss_sw_agent"),
    # Same path as config_modifiers.LIVE_CONFIG_PATH; older images read
    # /etc/coop/bgpd.conf instead, kept in step by activate/restore if present.
    "bgpcpp": ("/etc/coop/bgpcpp.conf", "bgpd"),
}

# Meta fans some patchers out to a soft-drain variant of the bgpcpp config.
# OSS DUTs have no such file; the caller's `is_host_drainable` already gates
# most of this, but ignore the name defensively so a drainable host does not
# fail on a config that does not exist here.
IGNORED_CONFIGS: t.FrozenSet[str] = frozenset({"bgpcpp_softdrain", "bgpcpp_drain"})

# Patchers that configure Meta-only telemetry with no consumer in an OSS run.
# ``configure_ingress_sflow_mirror_sampling`` mirrors sampled ingress traffic to
# an sFlow collector on the IXIA downlink; no OSS health check or playbook step
# reads it, and the QoS / BGP-DC configs that register it passed on hardware
# before the native patcher path existed (they ran with --skip-setup-tasks, so
# the mirror was never configured). Registering it is a logged no-op rather than
# a NotImplementedError so those configs stay runnable; anything with an OSS
# consumer still fails loudly below.
IGNORED_PY_FUNCS: t.FrozenSet[str] = frozenset({"configure_ingress_sflow_mirror_sampling"})

SUPPORTED_PY_FUNCS: t.FrozenSet[str] = frozenset(
    {
        "remove_bgp_peers",
        "configure_bgp_switch_limit",
        "configure_bgp_peer_group",
        "add_bgp_policy_statement",
        "change_port_admin_state",
        "change_port_queue_config",
        "change_port_speed",
        "add_bgp_policy_match_prefix_to_propagate_routes",
        "add_peer_group_patcher",
        "add_bgp_peers",
        "configure_vlans",
        "add_static_routes",
        "change_interface_mtu",
    }
)


@dataclass
class OssPatcher:
    """Mirrors the attribute surface callers read off a COOP patcher.

    ``taac/tasks/all.py`` filters registered patchers by ``.name`` and
    ``.owner``, so both must exist. COOP stamps ``owner`` with the registering
    user; OSS has no such notion, and the unregister path matches on
    ``owner is None`` by default, so ``None`` is the compatible value.
    """

    name: str
    config_name: str
    py_func_name: str
    args: t.Dict[str, t.Any] = field(default_factory=dict)
    desc: str = ""
    owner: t.Optional[str] = None


# hostname -> config_name -> ordered patchers. Module-level rather than per
# driver instance because `async_get_device_driver` may hand back a fresh
# object per call, and register/apply are separate calls.
_REGISTRY: t.Dict[str, t.Dict[str, t.List[OssPatcher]]] = {}


def register(host: str, config_name: str, patcher: OssPatcher) -> None:
    if config_name in IGNORED_CONFIGS:
        logger.debug("oss-patcher: ignoring %s config on %s", config_name, host)
        return
    if config_name not in CONFIG_FILES:
        raise ValueError(
            f"oss-patcher: unknown config_name {config_name!r} "
            f"(known: {sorted(CONFIG_FILES)})"
        )
    if patcher.py_func_name in IGNORED_PY_FUNCS:
        logger.warning(
            "oss-patcher: ignoring %s (%s) on %s -- Meta-only telemetry, no OSS consumer",
            patcher.name, patcher.py_func_name, host,
        )
        return
    if patcher.py_func_name not in SUPPORTED_PY_FUNCS:
        raise NotImplementedError(
            f"oss-patcher: py_func_name {patcher.py_func_name!r} is not ported "
            f"to OSS (supported: {sorted(SUPPORTED_PY_FUNCS)}). Port it in "
            f"taac/driver/oss_coop_patcher.py rather than letting the test run "
            f"against an unconfigured DUT."
        )
    slot = _REGISTRY.setdefault(host, {}).setdefault(config_name, [])
    # COOP keys patchers by name; re-registering the same name replaces it.
    for i, existing in enumerate(slot):
        if existing.name == patcher.name:
            slot[i] = patcher
            return
    slot.append(patcher)


def list_patchers(host: str, config_name: str) -> t.List[OssPatcher]:
    return list(_REGISTRY.get(host, {}).get(config_name, []))


def unregister(host: str, config_name: str, patcher_name: str) -> None:
    slot = _REGISTRY.get(host, {}).get(config_name)
    if not slot:
        return
    _REGISTRY[host][config_name] = [p for p in slot if p.name != patcher_name]


def pending_configs(host: str) -> t.List[str]:
    return [c for c, p in _REGISTRY.get(host, {}).items() if p]


def clear(host: str) -> None:
    _REGISTRY.pop(host, None)


# --------------------------------------------------------------------------
# The on-DUT mutation script.
#
# Written to run under the DUT's stock python3 with no imports beyond the
# stdlib. Reads the baseline, replays the patcher list, writes the patched
# file. Deliberately does NOT activate -- the driver does that separately so a
# failed mutation cannot leave a half-written config installed.
# --------------------------------------------------------------------------
_PATCH_SCRIPT = r'''
import json, sys

baseline, out_path, payload = sys.argv[1], sys.argv[2], sys.argv[3]
patchers = json.load(open(payload))
cfg = json.load(open(baseline))


def _peers(c):
    return c.setdefault("peers", [])


def remove_bgp_peers(c, a):
    if str(a.get("delete_all", "")).lower() == "true":
        c["peers"] = []
        return
    drop = set(json.loads(a.get("peer_addrs", "[]")))
    c["peers"] = [p for p in _peers(c) if p.get("peer_addr") not in drop]


def configure_bgp_switch_limit(c, a):
    lim = c.setdefault("switch_limit_config", {})
    if "prefix_limit" in a:
        lim["prefix_limit"] = int(a["prefix_limit"])


# FlowControlAction: 1 = ACCEPT, 2 = DENY.
_POLICY_ACCEPT = 1
_POLICY_VERSION = "1"


def add_bgp_policy_statement(c, a):
    """Splice in a policy statement, replacing any statement of the same name.

    Callers pass only name/description/policy_entries, so `result` and
    `policy_version` have to be defaulted here -- and `result` is load-bearing:
    2 is DENY, so a permit-all policy defaulted that way rejects every prefix
    while reading as correct. Both defaults mirror
    `config_modifiers.build_propagate_policies`, which builds these same
    statements in OSS python; keep them in step with it.

    Replace-by-name rather than append matches COOP keying patchers by name and
    `configure_bgp_peer_group`'s update-in-place, so re-applying is idempotent.
    """
    stmt = {
        "name": a["name"],
        "description": a.get("description", ""),
        "policy_version": a.get("policy_version", _POLICY_VERSION),
        "result": _coerce(a.get("result", _POLICY_ACCEPT)),
        "policy_entries": json.loads(a.get("policy_entries", "[]")),
    }
    stmts = c.setdefault("policies", {}).setdefault("bgp_policy_statements", [])
    for i, existing in enumerate(stmts):
        if existing.get("name") == stmt["name"]:
            stmts[i] = stmt
            return
    stmts.append(stmt)


def add_bgp_policy_match_prefix_to_propagate_routes(c, a):
    """Permit `matching_prefix` through the named ingress/egress statements.

    Term shape is a type-5 prefix_filters match with an EMPTY
    policy_action_entries, because a term that matches permits by default
    (PolicyTerm.cpp, quoted in config_modifiers.build_propagate_policies).
    Verified against generated patches that open a down-leg policy to an
    additional prefix range.

    Prepended rather than appended: these policies are first-match, so a term
    added after an existing reject would never be reached and the prefix still
    would not propagate -- which is the one thing this patcher exists to do.

    Only the literal "RANDOM" sentinel is skipped -- callers pass it for
    out_stmt_name to mean "no egress statement". Any OTHER name that is absent
    RAISES. Skipping those silently drops the permit this patcher exists to add,
    and the config then reads as though the prefix had been allowed: that is
    exactly how a permissive-ingress alias turned an in_stmt_name of
    "<policy>_DRAIN" into a statement nothing ever splices, with no log line.
    """
    prefix = a["matching_prefix"]
    try:
        plen = int(prefix.split("/")[1])
    except (IndexError, ValueError):
        raise ValueError(
            "oss-patcher: add_bgp_policy_match_prefix_to_propagate_routes: "
            "matching_prefix %r has no /length" % prefix
        )
    term = {
        "name": "",
        "description": "",
        "policy_match_entries": {
            "name": "",
            "description": "",
            "match_logic_type": 1,
            "match_entries": [
                {
                    "type": 5,
                    "prefix_filters": {
                        "name": "",
                        "description": "",
                        "prefixes": [
                            {
                                "base_prefix": prefix,
                                "prefix_len_ranges": [
                                    {"value": plen, "compare_operator": 2}
                                ],
                                "match_logic": 0,
                            }
                        ],
                        "prefix_list_names": [],
                        "boolean_operator": 2,
                    },
                    "match_logic_type": 0,
                }
            ],
        },
        "policy_action_entries": [],
        "term_miss_action": 3,
        "match_logic_type": 1,
    }
    wanted = {a.get("in_stmt_name"), a.get("out_stmt_name")} - {None, "RANDOM"}
    by_name = {
        s.get("name"): s
        for s in c.get("policies", {}).get("bgp_policy_statements", [])
    }
    for name in sorted(wanted):
        stmt = by_name.get(name)
        if stmt is None:
            raise KeyError(
                "oss-patcher: add_bgp_policy_match_prefix_to_propagate_routes: "
                "no policy statement %r to permit %r through (have: %s). "
                "Skipping would silently drop the permit."
                % (name, prefix, sorted(by_name))
            )
        stmt.setdefault("policy_entries", []).insert(0, json.loads(json.dumps(term)))


# cfg::PortState from the FBOSS thrift enum: DOWN=0, DISABLED=1, ENABLED=2.
_PORT_STATE = {"enable": 2, "disable": 1}


def change_port_admin_state(c, a):
    """agent.conf: set each named port's admin state.

    Args are a flat {port_name: "enable"|"disable"} mapping. An unknown port
    name raises rather than no-opping: the callers use this to bring the IXIA
    ports up, and silently skipping would start the test with the port still
    down -- a failure that surfaces much later as unexplained traffic loss.
    """
    by_name = {p.get("name"): p for p in c["sw"].get("ports", [])}
    for port_name, want in a.items():
        if port_name not in by_name:
            raise KeyError(
                "oss-patcher: change_port_admin_state: no port %r in agent "
                "config (have %d ports)" % (port_name, len(by_name))
            )
        if want not in _PORT_STATE:
            raise ValueError(
                "oss-patcher: change_port_admin_state: %r must be one of %s, "
                "got %r" % (port_name, sorted(_PORT_STATE), want)
            )
        by_name[port_name]["state"] = _PORT_STATE[want]



def change_port_queue_config(c, a):
    """agent.conf: rebind each named port to a different portQueueConfigName.

    Args are a flat {port_name: queue_config_name} mapping.

    This exists because the binding carries a rate shaper, not just queue
    names. A queue config whose queues set portQueueRate.kbitsPerSec
    {min,max} caps that port's egress at that rate. A port bound to a queue
    config sized for a slower link therefore forwards at the cap and drops
    everything above it, at a ratio fixed by cap/offered-rate -- which reads
    as a large, perfectly steady loss percentage in IXIA_PACKET_LOSS_CHECK and
    not as any configuration error. Rebinding the traffic-generator ports to a
    queue config that declares no portQueueRate removes the cap. Confirm the
    target config's queues carry no portQueueRate before using it here.

    Both an unknown port and an unknown queue-config name raise rather than
    no-op: either way the port silently stays shaped and the failure surfaces
    much later, as unexplained packet loss far from its cause.
    """
    by_name = {p.get("name"): p for p in c["sw"].get("ports", [])}
    known = c["sw"].get("portQueueConfigs", {})
    for port_name, want in a.items():
        if port_name not in by_name:
            raise KeyError(
                "oss-patcher: change_port_queue_config: no port %r in agent "
                "config (have %d ports)" % (port_name, len(by_name))
            )
        if want not in known:
            raise ValueError(
                "oss-patcher: change_port_queue_config: %r names no entry in "
                "sw.portQueueConfigs (have: %s)" % (want, sorted(known))
            )
        by_name[port_name]["portQueueConfigName"] = want


def _load_platform_mapping(a):
    """The box's platform mapping, for per-port profile fitting; None if the
    image does not ship exactly one readable descriptor."""
    import glob

    path = a.get("platform_mapping_path")
    hits = [path] if path else glob.glob(
        "/opt/fboss/share/platform_descriptors/*/*/platform_mapping.json"
    )
    if len(hits) != 1:
        return None
    try:
        return json.load(open(hits[0]))
    except (OSError, ValueError):
        return None


def change_port_speed(c, a):
    """agent.conf: set each named port's speed and a profileID that fits it.

    Args: {"ports": JSON list of names, "speed": Mbps, "profile_id": the
    requested cfg.PortProfileID value}.

    A port that offers the requested profile takes it verbatim. A port that
    does not -- media families are assigned per CAGE, so on a mixed-media link
    the two ends need different profile ids for the same signal (e.g.
    optical-family 23 vs copper-family 22 at 100G) -- takes the ONE profile it
    offers that is wire-identical to the request (speed, lanes, modulation,
    FEC per the platform mapping). No unique stand-in raises: guessing a
    profile programs lanes the far end cannot match, which surfaces much later
    as a link that never comes back. Without a readable platform mapping the
    requested profile is used as-is.

    A whole-cage profile (all 8 lanes, e.g. 800G on /1) leaves no lanes for
    the cage's other subports, so those are DISABLED unless also named.
    Downshifting does not re-enable a subsumed mate -- name it explicitly.
    """
    ports = json.loads(a["ports"])
    speed = int(a["speed"])
    requested = int(a["profile_id"])
    pm = _load_platform_mapping(a)
    offered_by_port, wire = {}, {}
    if pm is not None:
        for p in pm.get("ports", {}).values():
            offered_by_port[p["mapping"]["name"]] = set(
                int(k) for k in p.get("supportedProfiles", {})
            )
        for e in pm.get("platformSupportedProfiles", []):
            iphy = e["profile"]["iphy"]
            wire.setdefault(
                e["factor"]["profileID"],
                (
                    e["profile"]["speed"],
                    iphy.get("numLanes"),
                    iphy.get("modulation"),
                    iphy.get("fec"),
                ),
            )

    by_name = {p.get("name"): p for p in c["sw"].get("ports", [])}
    chosen = {}
    for name in ports:
        if name not in by_name:
            raise KeyError(
                "oss-patcher: change_port_speed: no port %r in agent config "
                "(have %d ports)" % (name, len(by_name))
            )
        pid = requested
        offered = offered_by_port.get(name)
        if offered is not None and requested not in offered:
            want = wire.get(requested)
            cands = [o for o in sorted(offered) if want and wire.get(o) == want]
            if len(cands) != 1:
                raise ValueError(
                    "oss-patcher: change_port_speed: %r does not offer profile "
                    "%d and has no unique wire-identical stand-in at %d Mbps "
                    "(candidates %s of offered %s)"
                    % (name, requested, speed, cands, sorted(offered))
                )
            pid = cands[0]
        entry = by_name[name]
        entry["speed"] = speed
        entry["profileID"] = pid
        entry["state"] = 2
        chosen[name] = pid
        sys.stderr.write("port %s -> %d Mbps, profile %d\n" % (name, speed, pid))

    for name, pid in chosen.items():
        lanes = wire[pid][1] if pid in wire else None
        whole_cage = (lanes == 8) if lanes is not None else speed >= 800000
        if not whole_cage:
            continue
        cage = name.rsplit("/", 1)[0] + "/"
        for other, entry in by_name.items():
            if other.startswith(cage) and other not in chosen and entry.get("state") == 2:
                entry["state"] = 1
                sys.stderr.write(
                    "port %s disabled: %s takes the whole cage\n" % (other, name)
                )


def _coerce(v):
    """Patcher args arrive as strings ("True"/"20000"); the config is typed."""
    if isinstance(v, str):
        if v.lower() in ("true", "false"):
            return v.lower() == "true"
        if v.isdigit():
            return int(v)
    return v


def configure_bgp_peer_group(c, a):
    """COOP's update-in-place. A no-op on a group that does not exist, which
    is exactly COOP's behaviour -- peers would then reference an undefined
    group, so surface it as a warning rather than inventing the group."""
    name = a["name"]
    attrs = json.loads(a.get("attributes_to_update_json", "{}"))
    for g in c.get("peer_groups", []):
        if g.get("name") == name:
            for k, v in attrs.items():
                if k == "max_routes":
                    g.setdefault("pre_filter", {})["max_routes"] = _coerce(v)
                else:
                    g[k] = _coerce(v)
            return
    sys.stderr.write("WARN: peer_group %s not found; update skipped\n" % name)


def add_peer_group_patcher(c, a):
    """Create a peer group from the flat kwargs COOP accepts."""
    name = a["name"]
    timers = {
        "hold_time_seconds": int(a.get("bgp_peer_timers_hold_time_seconds", 30)),
        "keep_alive_seconds": int(a.get("bgp_peer_timers_keep_alive_seconds", 10)),
        "out_delay_seconds": int(a.get("bgp_peer_timers_out_delay_seconds", 0)),
        "withdraw_unprog_delay_seconds": int(
            a.get("bgp_peer_timers_withdraw_unprog_delay_seconds", 0)
        ),
    }
    g = {
        "name": name,
        "description": a.get("description", ""),
        "next_hop_self": _coerce(a.get("next_hop_self", "True")),
        "disable_ipv4_afi": _coerce(a.get("disable_ipv4_afi", "False")),
        "disable_ipv6_afi": _coerce(a.get("disable_ipv6_afi", "False")),
        "is_confed_peer": _coerce(a.get("is_confed_peer", "False")),
        "ingress_policy_name": a.get("ingress_policy_name"),
        "egress_policy_name": a.get("egress_policy_name"),
        "peer_tag": a.get("peer_tag", ""),
        "v4_over_v6_nexthop": _coerce(a.get("v4_over_v6_nexthop", "False")),
        "bgp_peer_timers": timers,
        "pre_filter": {
            "max_routes": _coerce(a.get("max_routes", 45000)),
            "warning_only": _coerce(a.get("warning_only", "True")),
            "warning_limit": _coerce(a.get("warning_limit", "0")),
        },
    }
    groups = c.setdefault("peer_groups", [])
    for i, ex in enumerate(groups):
        if ex.get("name") == name:
            groups[i] = g
            return
    groups.append(g)


def _ip_add(ip, step):
    """Advance an IPv4/IPv6 literal by `step` (both given as addresses)."""
    import ipaddress

    return str(ipaddress.ip_address(ip) + int(ipaddress.ip_address(step)))


def add_bgp_peers(c, a):
    """Append peers from either shape `peer_configs` arrives in: concrete
    peers (`local_addr`/...) from ConfigureParallelBgpPeers, or per-interface
    session specs (`starting_ip`/`num_sessions`/...) registered directly."""
    specs = json.loads(a["peer_configs"])
    if isinstance(specs, dict):
        specs = [s for group in specs.values() for s in group]
    seq = {}
    for p in [s for s in specs if "local_addr" in s]:
        desc = p.get("description", "peer")
        seq[desc] = seq.get(desc, 0) + 1
        _peers(c).append(
            {
                "local_addr": p["local_addr"],
                "peer_addr": p["peer_addr"],
                "next_hop4": "0.0.0.0",
                "next_hop6": p["local_addr"] if ":" in p["local_addr"] else "::",
                "description": p.get("description", ""),
                "peer_id": "%s:%d" % (desc, seq[desc]),
                "remote_as_4_byte": int(p["remote_as_4_byte"]),
                "peer_group_name": p["peer_group_name"],
            }
        )
    for spec in [s for s in specs if "local_addr" not in s]:
        local = spec["starting_ip"]
        remote = spec["gateway_starting_ip"]
        asn = int(spec["remote_as_4_byte"])
        step = int(spec.get("remote_as_4_byte_step", 0))
        inc_l = spec.get("increment_ip", "::0")
        inc_r = spec.get("gateway_increment_ip", inc_l)
        for n in range(int(spec["num_sessions"])):
            _peers(c).append(
                {
                    "local_addr": local,
                    "peer_addr": remote,
                    "next_hop4": "0.0.0.0",
                    "next_hop6": local if ":" in local else "::",
                    "description": spec.get("description", ""),
                    "peer_id": "%s:%d" % (spec.get("description", "peer"), n + 1),
                    "remote_as_4_byte": asn + step * n,
                    "peer_group_name": spec["peer_group_name"],
                }
            )
            local = _ip_add(local, inc_l)
            remote = _ip_add(remote, inc_r)


def configure_vlans(c, a):
    """agent.conf: merge addresses into a vlan interface, creating it if
    absent, and move the spec's ports into that vlan.

    Merge, not replace: two ports on one vlan arrive as two patchers, and the
    second must not clobber the first's addresses."""
    sw = c["sw"]
    for vlan_name, blob in a.items():
        spec = json.loads(blob)
        vid = int(spec.get("vlan_id") or spec.get("vlanID"))
        addrs = spec["ip_addresses"]
        for i in sw.get("interfaces", []):
            if i.get("vlanID") == vid:
                have = i.get("ipAddresses", [])
                i["ipAddresses"] = have + [x for x in addrs if x not in have]
                addrs = i["ipAddresses"]
                break
        else:
            sw.setdefault("interfaces", []).append(
                {
                    "intfID": vid,
                    "routerID": 0,
                    "vlanID": vid,
                    "name": vlan_name,
                    "ipAddresses": list(addrs),
                    "mtu": 9000,
                    "isVirtual": False,
                    "isStateSyncDisabled": False,
                    "type": 1,
                    "scope": 0,
                }
            )
        for v in sw.get("vlans", []):
            if v.get("id") == vid:
                have = v.get("ipAddresses", [])
                new = [x.split("/")[0] for x in addrs]
                v["ipAddresses"] = have + [x for x in new if x not in have]
                break
        else:
            sw.setdefault("vlans", []).append(
                {
                    "name": vlan_name,
                    "id": vid,
                    "intfID": vid,
                    "recordStats": True,
                    "routable": True,
                    "ipAddresses": [x.split("/")[0] for x in addrs],
                }
            )

        # Move the named ports into this vlan. COOP's version consumes the
        # "ports" key; dropping it leaves each traffic-generator port on
        # whatever vlan it already had. Where that is one shared vlan, the two
        # SVIs collapse into a single interface, there is no routed path
        # between the downlink and uplink directions, and directional-traffic
        # checks see total loss. A port must end up in exactly one vlan, so
        # the old vlanPorts entry goes as the new one arrives.
        by_id = {p.get("logicalID"): p for p in sw.get("ports", [])}
        for port_id in spec.get("ports", []) or []:
            port = by_id.get(port_id)
            if port is None:
                raise KeyError(
                    "oss-patcher: configure_vlans: no port with logicalID %r "
                    "in agent config (have %d ports)" % (port_id, len(by_id))
                )
            if port.get("ingressVlan") == vid:
                continue
            port["ingressVlan"] = vid
            vps = sw.setdefault("vlanPorts", [])
            sw["vlanPorts"] = [
                x for x in vps if x.get("logicalPort") != port_id
            ] + [
                {
                    "vlanID": vid,
                    "logicalPort": port_id,
                    "spanningTreeState": 2,
                    "emitTags": False,
                }
            ]



def add_static_routes(c, a):
    """agent.conf: install static routes with explicit next hops.

    Args are {"<prefix>/<mask>": '["<nexthop>", ...]'} -- the shape
    `OssCustomStep.register_cpu_queue_static_route_patcher` builds from the
    IXIA device-group mimic IP. Replace by prefix instead of appending: the
    UNH playbooks re-register the same patcher on every iteration, and a
    duplicate prefix would leave two entries for the agent to reconcile.

    Deliberately NOT the thrift ClientID.STATIC_ROUTE path
    (`async_add_static_route_patcher`): the UNH playbooks restart the agent
    immediately after registering, and ConfigApplier drops thrift static
    routes on every config apply. Written into agent.conf, the restart is
    what installs the route.
    """
    sw = c["sw"]
    routes = sw.setdefault("staticRoutesWithNhops", [])
    for prefix, nhops in a.items():
        parsed = json.loads(nhops) if isinstance(nhops, str) else list(nhops)
        if not parsed:
            raise ValueError(
                "oss-patcher: add_static_routes: %r has no next hop" % (prefix,)
            )
        routes = [r for r in routes if r.get("prefix") != prefix]
        routes.append({"routerID": 0, "prefix": prefix, "nexthops": parsed})
    sw["staticRoutesWithNhops"] = routes


def change_interface_mtu(c, a):
    """agent.conf: set the L3 interface MTU for the vlan a port sits in.

    Args are {"interface": "<port name>", "mtu": <int>}. The MTU the agent
    reports for a port (`fboss2 show interface <port>` -> MTU column) is the
    `sw.interfaces[]` entry whose vlanID matches the port's ingressVlan --
    verified on hardware: the IXIA-facing port sits on a vlan whose interface
    reports the jumbo MTU, which is that interface's mtu, NOT the port's
    maxFrameSize.
    So the MTU-exceed punt is driven from here, not from the port entry.
    """
    sw = c["sw"]
    name = a["interface"]
    mtu = int(a["mtu"])
    port = next((p for p in sw.get("ports", []) if p.get("name") == name), None)
    if port is None:
        raise KeyError(
            "oss-patcher: change_interface_mtu: no port %r in agent config "
            "(have %d ports)" % (name, len(sw.get("ports", [])))
        )
    vlan = port.get("ingressVlan")
    intf = next(
        (i for i in sw.get("interfaces", []) if i.get("vlanID") == vlan), None
    )
    if intf is None:
        raise KeyError(
            "oss-patcher: change_interface_mtu: port %r is on vlan %r but no "
            "interface has that vlanID" % (name, vlan)
        )
    intf["mtu"] = mtu


FUNCS = {
    "remove_bgp_peers": remove_bgp_peers,
    "configure_bgp_switch_limit": configure_bgp_switch_limit,
    "configure_bgp_peer_group": configure_bgp_peer_group,
    "add_bgp_policy_statement": add_bgp_policy_statement,
    "change_port_admin_state": change_port_admin_state,
    "change_port_queue_config": change_port_queue_config,
    "change_port_speed": change_port_speed,
    "add_bgp_policy_match_prefix_to_propagate_routes": add_bgp_policy_match_prefix_to_propagate_routes,
    "add_peer_group_patcher": add_peer_group_patcher,
    "add_bgp_peers": add_bgp_peers,
    "configure_vlans": configure_vlans,
    "add_static_routes": add_static_routes,
    "change_interface_mtu": change_interface_mtu,
}

for p in patchers:
    FUNCS[p["py_func_name"]](cfg, p["args"])
    sys.stderr.write("applied %s (%s)\n" % (p["name"], p["py_func_name"]))

with open(out_path, "w") as f:
    json.dump(cfg, f, indent=2)
    f.write("\n")
print("OK %d patcher(s)" % len(patchers))
'''


def variant_paths(config_name: str) -> t.Tuple[str, str, str]:
    """(live, baseline, patched) paths for a config.

    Three names, not two, because the service reads a fixed path --
    ``bgpd.service`` hardcodes ``--config /etc/coop/bgpcpp.conf`` -- so "active"
    must always live there. ``<stem>.baseline.conf`` and ``<stem>.patched.conf``
    sit alongside as the two selectable variants, mirroring how a testbed config
    directory keeps ``agent.conf`` next to ``agent.patched.conf``. Activating
    is a copy over the live path; restoring copies the baseline back.
    """
    live, _ = CONFIG_FILES[config_name]
    stem = live[: -len(".conf")] if live.endswith(".conf") else live
    return live, f"{stem}.baseline.conf", f"{stem}.patched.conf"


def build_apply_command(config_name: str, patchers: t.List[OssPatcher]) -> str:
    """Shell command that materialises `patchers` into <stem>.patched.conf.

    Script + payload are base64'd so no amount of JSON quoting can break the
    shell line. Does not activate -- see `build_activate_command`.
    """
    live, baseline, patched = variant_paths(config_name)
    payload = json.dumps(
        [
            {"name": p.name, "py_func_name": p.py_func_name, "args": p.args}
            for p in patchers
        ]
    )
    b64s = base64.b64encode(_PATCH_SCRIPT.encode()).decode()
    b64p = base64.b64encode(payload.encode()).decode()
    seed = ""
    if config_name == "bgpcpp":
        # Older images only have /etc/coop/bgpd.conf; seed the live path from it.
        seed = f"[ -e {live} ] || cp -a /etc/coop/bgpd.conf {live}; "
    return (
        f"set -e; {seed}"
        # snapshot the pristine config exactly once, so repeated applies in a
        # session keep rebasing on the original rather than on a patched file
        f"[ -f {baseline} ] || cp -a {live} {baseline}; "
        f"echo '{b64s}' | base64 -d > /tmp/_oss_patch.$$.py; "
        f"echo '{b64p}' | base64 -d > /tmp/_oss_patch.$$.json; "
        f"python3 /tmp/_oss_patch.$$.py {baseline} {patched} /tmp/_oss_patch.$$.json; "
        f"rm -f /tmp/_oss_patch.$$.py /tmp/_oss_patch.$$.json"
    )


def build_activate_command(config_name: str) -> str:
    """Install the patched config where the service reads it."""
    live, _baseline, patched = variant_paths(config_name)
    cmd = (
        f"set -e; python3 -c \"import json;json.load(open('{patched}'))\"; "
        f"cp -a {patched} {live}"
    )
    if config_name == "bgpcpp":
        # Keep the older-image /etc/coop/bgpd.conf sibling in step if present.
        cmd += (
            "; if [ -e /etc/coop/bgpd.conf ]; then"
            " cp -a /etc/coop/bgpcpp.conf /etc/coop/bgpd.conf; fi"
        )
    # The caller cannot see the shell exit status; give it a success marker.
    return cmd + "; echo ACTIVATED"


def build_restore_command(config_name: str) -> str:
    """Put the pristine config back (teardown)."""
    live, baseline, _patched = variant_paths(config_name)
    cmd = f"if [ -f {baseline} ]; then cp -a {baseline} {live}; fi"
    if config_name == "bgpcpp":
        cmd += (
            "; if [ -e /etc/coop/bgpd.conf ]; then"
            " cp -a /etc/coop/bgpcpp.conf /etc/coop/bgpd.conf; fi"
        )
    return cmd
