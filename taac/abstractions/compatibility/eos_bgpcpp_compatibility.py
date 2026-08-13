# pyre-unsafe
"""EOS/BGP++ spelling and command compatibility data."""

import base64
import shlex
import typing as t


# =============================================================================
# BGP Peer Group Names (Standard EBB naming convention)
# =============================================================================
PEERGROUP_IBGP_V6 = "EB-EB-V6"
PEERGROUP_IBGP_V4 = "EB-EB-V4"
PEERGROUP_EBGP_V6 = "EB-FA-V6"
PEERGROUP_EBGP_V4 = "EB-FA-V4"
PEERGROUP_BGP_MON = "BGP-MON"


# =============================================================================
# BGP++ Daemon Names (for arista_daemon_control tasks)
#
# ORDER MATTERS -- this list is the sequential (re)start order, and it follows
# the FIB-programming dependency chain so each daemon's downstream target is
# already up before it starts:
#
#   FibGrpc / FibBgpGrpc  (EosSdkRpc gRPC backends, ports 9544 / 9545)
#     -> FibAgent / FibAgentBgp  (FIB agents, thrift 5912 / 5913)
#       -> Openr / Bgp  (routing daemons)
#
# Bgp MUST be last: BGP++ (the ``Bgp`` daemon) programs routes into
# ``FibAgentBgp`` (thrift 5913 -> FibBgpGrpc 9545) and resolves nexthops via the
# Open-R FIB agent, so those agents/backends must be (re)started BEFORE ``Bgp``.
# If ``Bgp`` starts first it converges its full RIB before its FIB agent exists,
# the FIB agent is then restarted out from under it, and at init BGP++ has
# nothing to program to ("Fib agent is not connected. Skipping fib batch
# programming.") -- forcing a churny resync. See T274256815.
#
# ``Openr`` is enabled only for profiles that require it (see
# _get_control_plane_tasks). ``RouteGrpc`` (EosSdkRpc backing the EOS RouteAgent,
# port 9547) is intentionally excluded: it is not on the BGP++ FIB-programming
# path and nothing in the BGP++ conveyor health/post checks uses it.
# =============================================================================
BGPCPP_DAEMONS = [
    "FibGrpc",
    "FibBgpGrpc",
    "FibAgent",
    "FibAgentBgp",
    "Openr",
    "Bgp",
]

# Ordered phase-3 control-plane recipe. Keep the lists ordered because their
# repr is embedded in the on-device script and daemon startup is order-sensitive.
THRIFT_ACL_FILES = [
    "/usr/facebook/thrift_acls/Bgpd_lab.json",
    "/usr/facebook/thrift_acls/FibAgent.json",
    "/usr/facebook/thrift_acls/FibAgent_lab.json",
]

INTERN_USER_IDS = [
    "1179835461009564",
    "1414546347",
    "1531998838006730",
]

_ADD_INTERN_USER_IDS_SCRIPT = f"""\
import json
import os
import sys

UIDS = {repr(INTERN_USER_IDS)}
FILES = {repr(THRIFT_ACL_FILES)}

for f in FILES:
    if not os.path.exists(f):
        print(f"SKIP {{f}}: does not exist")
        continue
    try:
        with open(f) as fh:
            data = json.load(fh)
        modified = False
        for perm in data.get("permissions", []):
            entries = perm.setdefault("entries", [])
            existing_ids = set(
                e.get("identity", {{}}).get("id_data") for e in entries
            )
            for uid in UIDS:
                if uid not in existing_ids:
                    entries.append({{"identity": {{"id_type": "USER", "id_data": uid}}}})
                    modified = True
        if modified:
            with open(f, "w") as fh:
                json.dump(data, fh, indent=4)
            print(f"UPDATED {{f}}")
        else:
            print(f"OK {{f}}: all uids already present")
    except Exception as e:
        print(f"ERROR {{f}}: {{e}}", file=sys.stderr)
        sys.exit(1)
"""

_ADD_INTERN_USER_IDS_SCRIPT_B64 = base64.b64encode(
    _ADD_INTERN_USER_IDS_SCRIPT.encode("utf-8")
).decode("utf-8")
ADD_INTERN_USER_IDS_CMD = (
    f"bash printf '%s' {shlex.quote(_ADD_INTERN_USER_IDS_SCRIPT_B64)} "
    "| base64 -d | sudo python3 -"
)


def _on_device_python_command(script: str) -> str:
    encoded_script = base64.b64encode(script.encode("utf-8")).decode("ascii")
    return (
        f"bash printf '%s' {shlex.quote(encoded_script)} | base64 -d | sudo python3 -"
    )


_REQUIRE_THRIFT_ACL_FILES_SCRIPT = "\n".join(
    [
        "from pathlib import Path",
        f"paths = {THRIFT_ACL_FILES!r}",
        "missing = [path for path in paths if not Path(path).is_file()]",
        "if missing:",
        '    raise RuntimeError(f"missing required Thrift ACL files: {missing}")',
        'print(f"Found required Thrift ACL files: {paths}")',
        "",
    ]
)
REQUIRE_THRIFT_ACL_FILES_CMD = _on_device_python_command(
    _REQUIRE_THRIFT_ACL_FILES_SCRIPT
)

_VERIFY_THRIFT_ACL_USER_IDS_SCRIPT = "\n".join(
    [
        "import json",
        "from pathlib import Path",
        f"paths = {THRIFT_ACL_FILES!r}",
        f"expected = set({INTERN_USER_IDS!r})",
        "errors = []",
        "for path in paths:",
        "    permissions = json.loads(Path(path).read_text()).get('permissions', [])",
        "    if not permissions:",
        '        errors.append(f"{path}: no permissions")',
        "        continue",
        "    for index, permission in enumerate(permissions):",
        "        actual = {",
        "            entry.get('identity', {}).get('id_data')",
        "            for entry in permission.get('entries', [])",
        "        }",
        "        missing = sorted(expected - actual)",
        "        if missing:",
        '            errors.append(f"{path}: permissions[{index}] missing {missing}")',
        "if errors:",
        '    raise RuntimeError("; ".join(errors))',
        'print("Verified required user IDs in all Thrift ACL permissions")',
        "",
    ]
)
VERIFY_THRIFT_ACL_USER_IDS_CMD = _on_device_python_command(
    _VERIFY_THRIFT_ACL_USER_IDS_SCRIPT
)

POST_ACL_RESTART_DAEMONS = ["FibAgent", "FibAgentBgp", "Bgp"]

EBB_BGPCPP_LOGGING_CONFIG = "DBG5;default:async=true"


def build_update_group_setting_override_cmd(
    enable_update_group: bool,
    *,
    config_path: str = "/mnt/flash/bgpcpp_config",
) -> str:
    enabled_literal = repr(enable_update_group)
    script = "\n".join(
        [
            "import json",
            "import os",
            "import shutil",
            "import tempfile",
            "from pathlib import Path",
            f"config_path = Path({config_path!r})",
            "config = json.loads(config_path.read_text())",
            "bgp_settings = config.setdefault('bgp_setting_config', {})",
            f"bgp_settings['enable_update_group'] = {enabled_literal}",
            "updated_content = (json.dumps(config, indent=2) + '\\n').encode()",
            "metadata = config_path.stat()",
            "fd, temporary_name = tempfile.mkstemp(",
            "    dir=config_path.parent, prefix=f'.{config_path.name}.'",
            ")",
            "temporary_path = Path(temporary_name)",
            "try:",
            "    with os.fdopen(fd, 'wb') as temporary_file:",
            "        temporary_file.write(updated_content)",
            "        temporary_file.flush()",
            "        os.fsync(temporary_file.fileno())",
            "    temporary_metadata = temporary_path.stat()",
            "    if (temporary_metadata.st_uid, temporary_metadata.st_gid) != (",
            "        metadata.st_uid, metadata.st_gid",
            "    ):",
            "        os.chown(temporary_path, metadata.st_uid, metadata.st_gid)",
            "    shutil.copymode(config_path, temporary_path)",
            "    os.replace(temporary_path, config_path)",
            "finally:",
            "    temporary_path.unlink(missing_ok=True)",
            "if config_path.read_bytes() != updated_content:",
            "    raise RuntimeError('failed to verify BGP++ config replacement')",
            f"print('Set bgp_setting_config.enable_update_group={str(enable_update_group).lower()}')",
            "",
        ]
    )
    return _on_device_python_command(script)


# =============================================================================
# BGP++ Update Group Config (UpdateGroupConfig thrift struct, D100093369)
# Field names are camelCase to match the on-device JSON serialization of the
# thrift struct (UpdateGroupConfig in bgp_config.thrift).
# Used by the *_UPDATE_GROUP variants of the conveyor test configs.
# =============================================================================
UPDATE_GROUP_ALLOW_SLOW_PEER_DETACH = False
UPDATE_GROUP_SLOW_PEER_TIME_THRESHOLD_MS = 50000
UPDATE_GROUP_SLOW_PEER_BLOCK_COUNT_THRESHOLD = 10
UPDATE_GROUP_SLOW_PEER_BLOCK_COUNT_WINDOW_MS = 1000
UPDATE_GROUP_ENABLE_SERIALIZE_GROUP_PDU = True

UPDATE_GROUP_CONFIG: t.Dict[str, t.Any] = {
    "allowSlowPeerDetach": UPDATE_GROUP_ALLOW_SLOW_PEER_DETACH,
    "slowPeerTimeThresholdMs": UPDATE_GROUP_SLOW_PEER_TIME_THRESHOLD_MS,
    "slowPeerBlockCountThreshold": UPDATE_GROUP_SLOW_PEER_BLOCK_COUNT_THRESHOLD,
    "slowPeerBlockCountWindowMs": UPDATE_GROUP_SLOW_PEER_BLOCK_COUNT_WINDOW_MS,
    "enableSerializeGroupPdu": UPDATE_GROUP_ENABLE_SERIALIZE_GROUP_PDU,
}


# =============================================================================
# BGP++ Supporting Agent Config Files (required for FibAgent daemons)
# Deployed via embedded base64 to avoid arista_create_file_from_config
# which silently fails on some devices.
# Generated from: configerator/raw_configs/taac/ebb_ci_cd_configs/
# To regenerate: cat <file> | base64 -w0
# =============================================================================
FIBAGENT_BGP_CONF_DEVICE_PATH = "/mnt/fb/agent_configs/fib_agent_bgp.conf"
FIBAGENT_BGP_CONF_B64 = "eyIxIjp7InJlYyI6eyIxIjp7ImkzMiI6NjAxMDB9LCIyIjp7ImkzMiI6NDh9LCIzIjp7ImkzMiI6NX0sIjQiOnsiaTMyIjoxNX0sIjUiOnsic3RyIjoiIn0sIjYiOnsic3RyIjoiL3BlcnNpc3Qvc2VjdXJlL2NhcGkucGVtIn0sIjciOnsic3RyIjoiL3BlcnNpc3Qvc2VjdXJlL2NhcGlrZXkucGVtIn0sIjgiOnsic3RyIjoiL21udC9mYi9jZXJ0cy9BcmlzdGFGaWJBZ2VudF9zZXJ2ZXIucGVtIn0sIjkiOnsiaTMyIjo1OTEzfSwiMTAiOnsic3RyIjoiL3Zhci9mYWNlYm9vay9yb290Y2FuYWwvY2EucGVtIn0sIjExIjp7InRmIjoxfSwiMTIiOnsidGYiOjF9LCIxMyI6eyJzdHIiOiJGaWJTZXJ2aWNlIn0sIjE0Ijp7ImkzMiI6MX0sIjE1Ijp7ImkzMiI6MX0sIjE2Ijp7InRmIjoxfSwiMTciOnsidGYiOjF9LCIxOCI6eyJzdHIiOiIvdXNyL2ZhY2Vib29rL3RocmlmdF9hY2xzL0ZpYkFnZW50X2xhYi5qc29uIn0sIjE5Ijp7InN0ciI6Ii91c3IvZmFjZWJvb2svdGhyaWZ0X2FjbHMvYXV0aF9raWxsX3N3aXRjaF9maWxlIn0sIjIwIjp7InRmIjowfSwiMjEiOnsiaTMyIjo3MjAwfSwiMjIiOnsidGYiOjF9LCIyMyI6eyJ0ZiI6MX0sIjI0Ijp7ImkzMiI6LTF9LCIyNSI6eyJzdHIiOiJGaWIgYWdlbnQgaXMgZGVzaWduZWQgdG8gZXhlY3V0ZSByZW1vdGUgcHJvZ3JhbW1pbmcgcmVxdWVzdHMgZnJvbSBPcGVuL1IgdG8gY2hhbmdlIE9wZW4vUiByb3V0ZXMgYWRtaW4gZGlzdGFuY2VzIHRvIGluZmx1ZW5jZSBiZXN0IHBhdGggc2VsZWN0aW9ucy4ifSwiMjYiOnsiaTMyIjo5NTQ1fSwiMjciOnsic3RyIjoiIn19fSwiMiI6eyJ0ZiI6MH0sIjMiOnsidGYiOjF9LCI0Ijp7ImkzMiI6Nzg3fSwiNSI6eyJpMzIiOjIwMH0sIjYiOnsiaTMyIjo0MH0sIjciOnsidGYiOjF9fQo="  # noqa: E501
FIBAGENT_BGP_CONF_DEPLOY_CMD = (
    f"bash echo '{FIBAGENT_BGP_CONF_B64}' | base64 -d > {FIBAGENT_BGP_CONF_DEVICE_PATH}"
)

FIBAGENT_CONF_DEVICE_PATH = "/mnt/fb/agent_configs/fib_agent.conf"
FIBAGENT_CONF_B64 = "eyIxIjp7InJlYyI6eyIxIjp7ImkzMiI6NjAxMDB9LCIyIjp7ImkzMiI6NDh9LCIzIjp7ImkzMiI6NX0sIjQiOnsiaTMyIjoxNX0sIjUiOnsic3RyIjoiIn0sIjYiOnsic3RyIjoiL3BlcnNpc3Qvc2VjdXJlL2NhcGkucGVtIn0sIjciOnsic3RyIjoiL3BlcnNpc3Qvc2VjdXJlL2NhcGlrZXkucGVtIn0sIjgiOnsic3RyIjoiL21udC9mYi9jZXJ0cy9BcmlzdGFGaWJBZ2VudF9zZXJ2ZXIucGVtIn0sIjkiOnsiaTMyIjo1OTEyfSwiMTAiOnsic3RyIjoiL3Zhci9mYWNlYm9vay9yb290Y2FuYWwvY2EucGVtIn0sIjExIjp7InRmIjoxfSwiMTIiOnsidGYiOjF9LCIxMyI6eyJzdHIiOiJGaWJTZXJ2aWNlIn0sIjE0Ijp7ImkzMiI6MX0sIjE1Ijp7ImkzMiI6MX0sIjE2Ijp7InRmIjoxfSwiMTciOnsidGYiOjF9LCIxOCI6eyJzdHIiOiIvdXNyL2ZhY2Vib29rL3RocmlmdF9hY2xzL0ZpYkFnZW50X2xhYi5qc29uIn0sIjE5Ijp7InN0ciI6Ii91c3IvZmFjZWJvb2svdGhyaWZ0X2FjbHMvYXV0aF9raWxsX3N3aXRjaF9maWxlIn0sIjIwIjp7InRmIjowfSwiMjEiOnsiaTMyIjo3MjAwfSwiMjIiOnsidGYiOjF9LCIyMyI6eyJ0ZiI6MX0sIjI0Ijp7ImkzMiI6LTF9LCIyNSI6eyJzdHIiOiJGaWIgYWdlbnQgaXMgZGVzaWduZWQgdG8gZXhlY3V0ZSByZW1vdGUgcHJvZ3JhbW1pbmcgcmVxdWVzdHMgZnJvbSBPcGVuL1IgdG8gY2hhbmdlIE9wZW4vUiByb3V0ZXMgYWRtaW4gZGlzdGFuY2VzIHRvIGluZmx1ZW5jZSBiZXN0IHBhdGggc2VsZWN0aW9ucy4ifSwiMjYiOnsiaTMyIjo5NTQ0fSwiMjciOnsic3RyIjoiIn19fSwiMiI6eyJ0ZiI6MH0sIjMiOnsidGYiOjF9LCI0Ijp7ImkzMiI6Nzg2fSwiNSI6eyJpMzIiOjEwfSwiNiI6eyJpMzIiOjQwfSwiNyI6eyJ0ZiI6MH19"  # noqa: E501
FIBAGENT_CONF_DEPLOY_CMD = (
    f"bash echo '{FIBAGENT_CONF_B64}' | base64 -d > {FIBAGENT_CONF_DEVICE_PATH}"
)


# =============================================================================
# Control Plane ACLs
# These ACLs permit BGP++, FibAgent, and other control plane traffic.
# =============================================================================
ACL_COMMANDS = (
    "configure\n"
    "ipv6 access-list aiv6-control-plane-acl\n"
    "counters per-entry\n"
    "10 permit icmpv6 any any\n"
    "20 permit ipv6 any any tracked\n"
    "30 permit udp any any eq bfd hop-limit eq 255\n"
    "40 permit udp any any eq bfd-echo hop-limit eq 254\n"
    "50 permit udp any any eq multihop-bfd\n"
    "60 permit udp any any eq micro-bfd\n"
    "70 permit udp any any eq sbfd\n"
    "80 permit udp any eq sbfd any eq sbfd-initiator\n"
    "90 permit 51 any any\n"
    "100 permit 50 any any\n"
    "110 permit tcp any any eq ssh www snmp bgp https gnmi\n"
    "120 permit udp any any eq bootps bootpc ntp snmp\n"
    "130 permit tcp any any range 5900 5910\n"
    "140 permit tcp any any range 50000 50100\n"
    "150 permit udp any any range 51000 51100\n"
    "160 permit udp any any eq dhcpv6-client dhcpv6-server\n"
    "170 permit tcp any eq bgp any\n"
    "180 permit tcp any any eq 6040\n"
    "200 permit tcp any any eq 9200\n"
    "245 permit tcp any any eq 6909\n"
    "300 permit tcp any any eq 2018\n"
    "310 permit udp any any eq 6666\n"
    "320 permit tcp any any eq 5921\n"
    "340 permit tcp any any eq 10701\n"
    "350 permit tcp any any eq 1610\n"
    "360 permit tcp any any eq 12112\n"
    "370 permit tcp any any range 5911 5919\n"
    "!\n"
    "ipv6 access-list ebbv6-control-plane-acl\n"
    "counters per-entry\n"
    "10 permit icmpv6 any any\n"
    "20 permit ipv6 any any tracked\n"
    "30 permit udp any any eq bfd hop-limit eq 255\n"
    "40 permit udp any any eq bfd-echo hop-limit eq 254\n"
    "50 permit udp any any eq multihop-bfd\n"
    "60 permit udp any any eq micro-bfd\n"
    "70 permit ospf any any\n"
    "80 permit 51 any any\n"
    "90 permit 50 any any\n"
    "100 permit tcp any any eq ssh snmp bgp https 1610\n"
    "110 permit udp any any eq bootps bootpc ntp snmp\n"
    "120 permit tcp any any eq mlag hop-limit eq 255\n"
    "130 permit udp any any eq mlag hop-limit eq 255\n"
    "140 permit tcp any any range 5900 5910\n"
    "145 permit tcp any any range 5911 5919\n"
    "150 permit tcp any any range 50000 50100\n"
    "160 permit udp any any range 51000 51100\n"
    "170 permit udp any any eq dhcpv6-client dhcpv6-server\n"
    "180 permit tcp any eq bgp any\n"
    "190 permit tcp any any eq nat hop-limit eq 255\n"
    "200 permit udp any any eq nat hop-limit eq 255\n"
    "210 permit rsvp any any\n"
    "220 permit pim any any\n"
    "230 permit udp any any eq 6666\n"
    "240 permit tcp any any eq 2018\n"
    "245 permit tcp any any eq 6909\n"
    "250 permit tcp any any eq 6666\n"
    "260 permit tcp any any eq 60001\n"
    "270 permit tcp any any eq 60002\n"
    "280 permit tcp any any eq 60006\n"
    "290 permit tcp any any eq 60009\n"
    "300 permit tcp any any eq 60100\n"
    "310 permit tcp any any eq 60101\n"
    "330 permit udp any eq lsp-ping any\n"
    "340 permit tcp any any eq 9543\n"
    "!\n"
    "ip access-list ebb-control-plane-acl\n"
    "counters per-entry\n"
    "10 permit icmp any any\n"
    "20 permit ip any any tracked\n"
    "30 permit udp any any eq bfd ttl eq 255\n"
    "40 permit udp any any eq bfd-echo ttl eq 254\n"
    "50 permit udp any any eq multihop-bfd\n"
    "60 permit udp any any eq micro-bfd\n"
    "70 permit ospf any any\n"
    "80 permit tcp any any eq ssh snmp bgp https msdp ldp netconf-ssh gnmi\n"
    "90 permit udp any any eq bootps bootpc ntp snmp rip ldp\n"
    "100 permit tcp any any eq mlag ttl eq 255\n"
    "110 permit udp any any eq mlag ttl eq 255\n"
    "120 permit vrrp any any\n"
    "130 permit ahp any any\n"
    "140 permit pim any any\n"
    "150 permit igmp any any\n"
    "160 permit tcp any any range 5900 5910\n"
    "165 permit tcp any any range 5911 5919\n"
    "170 permit tcp any any range 50000 50100\n"
    "180 permit udp any any range 51000 51100\n"
    "190 permit tcp any any eq 3333\n"
    "200 permit tcp any any eq nat ttl eq 255\n"
    "210 permit tcp any eq bgp any\n"
    "220 permit rsvp any any\n"
    "230 permit tcp any any eq 6666\n"
    "240 permit tcp any any eq 60101\n"
    "245 permit tcp any any eq 6909\n"
    "260 permit udp any eq lsp-ping any\n"
    "!\n"
    "end"
)
