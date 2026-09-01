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
mirrors how the testbed dirs already keep variant configs (see
``taac/testbed_configs/1-RSW/``).

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

SUPPORTED_PY_FUNCS: t.FrozenSet[str] = frozenset(
    {
        "remove_bgp_peers",
        "configure_bgp_switch_limit",
        "configure_bgp_peer_group",
        "add_peer_group_patcher",
        "add_bgp_peers",
        "configure_vlans",
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
    absent. Merge, not replace: two ports on one vlan arrive as two patchers,
    and the second must not clobber the first's addresses."""
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


FUNCS = {
    "remove_bgp_peers": remove_bgp_peers,
    "configure_bgp_switch_limit": configure_bgp_switch_limit,
    "configure_bgp_peer_group": configure_bgp_peer_group,
    "add_peer_group_patcher": add_peer_group_patcher,
    "add_bgp_peers": add_bgp_peers,
    "configure_vlans": configure_vlans,
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
    sit alongside as the two selectable variants, mirroring how the workspace
    keeps ``rsw2/agent.conf`` next to ``rsw2/agent.patched.conf``. Activating
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
