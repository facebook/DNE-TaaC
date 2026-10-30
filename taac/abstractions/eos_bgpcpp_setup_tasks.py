# Copyright (c) Meta Platforms, Inc. and affiliates.

"""Concrete setup-task renderers owned by the EOS BGP++ backend."""

import base64
import ipaddress
import json
import shlex
import typing as t
from dataclasses import dataclass
from pathlib import PurePosixPath

from taac.abstractions.topology.model import (
    OpenRMode,
    OpenRStandaloneEndpoint,
    OpenRStandaloneLink,
)
from taac.constants import (
    BgpPlusPlusProfile,
    DEFAULT_OPENR_START_IPV4S,
    DEFAULT_OPENR_START_IPV6S,
    OpenRRouteAction,
)
from taac.task_definitions import (
    create_configure_bgpcpp_startup_task,
    create_openr_route_action_task,
    create_run_commands_on_shell_task,
)
from taac.test_as_a_config.types import Params, Task

_INTERFACE_STATE_NEXTHOP_FLAG = "bgp_resolve_nexthops_from_interface_state"
_BGPCPP_CONFIG_PATH = "/mnt/flash/bgpcpp_config"
POLICY_EVALUATION_SOURCE_CONFIG_PATH = (
    "/mnt/flash/taac_policy_evaluation_source_config.json"
)
_OPENR_STANDALONE_ROUTE_COUNT = 63
_OPENR_STANDALONE_ROUTE_STEP = 2
_RUN_BGPCPP_SCRIPT_PATH = "/usr/sbin/run_bgpcpp.sh"


def _build_bgpcpp_logging_script(
    logging_config: str,
    script_path: str = _RUN_BGPCPP_SCRIPT_PATH,
) -> str:
    if not logging_config or any(char in logging_config for char in "\x00\r\n"):
        raise ValueError("logging_config must be a non-empty single-line value")

    expected_assignment = f"LOGGING={shlex.quote(logging_config)}"
    expected_assignment_bytes = expected_assignment.encode("utf-8")
    return "\n".join(
        [
            "import os",
            "import shutil",
            "import tempfile",
            "from pathlib import Path",
            f"path = Path({script_path!r})",
            "content = path.read_bytes()",
            "lines = content.splitlines(keepends=True)",
            'matches = [i for i, line in enumerate(lines) if line.startswith(b"LOGGING=")]',
            "if len(matches) != 1:",
            "    raise RuntimeError(",
            '        f"expected exactly one LOGGING= assignment in {path}, "',
            '        f"found {len(matches)}"',
            "    )",
            f"expected = {expected_assignment_bytes!r}",
            "index = matches[0]",
            'line_body = lines[index].rstrip(b"\\r\\n")',
            "line_ending = lines[index][len(line_body):]",
            "lines[index] = expected + line_ending",
            'updated_content = b"".join(lines)',
            "metadata = path.stat()",
            'fd, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")',
            "temporary_path = Path(temporary_name)",
            "try:",
            '    with os.fdopen(fd, "wb") as temporary_file:',
            "        temporary_file.write(updated_content)",
            "        temporary_file.flush()",
            "        os.fsync(temporary_file.fileno())",
            "    temporary_metadata = temporary_path.stat()",
            "    if (temporary_metadata.st_uid, temporary_metadata.st_gid) != (",
            "        metadata.st_uid, metadata.st_gid",
            "    ):",
            "        os.chown(temporary_path, metadata.st_uid, metadata.st_gid)",
            "    shutil.copymode(path, temporary_path)",
            "    os.replace(temporary_path, path)",
            "finally:",
            "    temporary_path.unlink(missing_ok=True)",
            "if path.read_bytes() != updated_content:",
            '    raise RuntimeError(f"failed to verify {expected!r} in {path}")',
            "",
        ]
    )


def create_bgpcpp_logging_setup_task(
    hostname: str,
    logging_config: str,
) -> Task:
    script = _build_bgpcpp_logging_script(logging_config)
    encoded_script = base64.b64encode(script.encode("utf-8")).decode("ascii")
    pipeline = f"printf '%s' {shlex.quote(encoded_script)} | base64 -d | sudo python3 -"
    command = f"bash {pipeline}"
    task = create_run_commands_on_shell_task(
        hostname=hostname,
        cmds=[command],
        set_outer_hostname=True,
        ixia_needed=True,
        validate_output=True,
    )
    # RunCommandsOnShell logs the BGPCPP_LOG_LEVEL marker for this key.
    params = json.loads(task.params.json_params or "{}")
    params["bgpcpp_logging_config"] = logging_config
    return task(params=Params(json_params=json.dumps(params)))


def _validate_bgpcpp_config_path(path: str, field_name: str) -> None:
    parsed_path = PurePosixPath(path)
    if (
        not path.startswith("/")
        or not path.isascii()
        or ".." in parsed_path.parts
        or any(not (char.isalnum() or char in "/._-") for char in path)
    ):
        raise ValueError(f"{field_name} must be a shell-safe absolute path")


def build_bgpcpp_policy_overlay_script(  # noqa: C901
    *,
    source_config_path: str,
    policy_name: str,
    peer_group_names: t.Sequence[str],
    expected_peers: t.Sequence[t.Mapping[str, t.Any]],
    expected_local_as_4_byte: int,
    expect_update_group_enabled: bool,
    target_config_path: str = _BGPCPP_CONFIG_PATH,
) -> str:
    """Build a fail-closed policy-only overlay for an installed BGP++ config."""
    _validate_bgpcpp_config_path(source_config_path, "source_config_path")
    _validate_bgpcpp_config_path(target_config_path, "target_config_path")
    if not policy_name or any(char in policy_name for char in "\x00\r\n"):
        raise ValueError("policy_name must be a non-empty single-line value")
    expected_groups = tuple(peer_group_names)
    if (
        not expected_groups
        or any(
            not name or any(char in name for char in "\x00\r\n")
            for name in expected_groups
        )
        or len(set(expected_groups)) != len(expected_groups)
    ):
        raise ValueError("peer_group_names must be distinct non-empty values")
    required_peer_fields = {
        "remote_as_4_byte",
        "local_addr",
        "peer_addr",
        "next_hop4",
        "next_hop6",
        "description",
        "peer_id",
        "peer_group_name",
    }
    expected_peer_configs = tuple(dict(peer) for peer in expected_peers)
    if not expected_peer_configs:
        raise ValueError("expected_peers must be non-empty")
    for peer in expected_peer_configs:
        if set(peer) != required_peer_fields:
            raise ValueError(
                "expected_peers must contain complete compiled BGP++ peer configs"
            )
        try:
            for field in ("local_addr", "peer_addr", "next_hop4", "next_hop6"):
                ipaddress.ip_address(peer[field])
        except (TypeError, ValueError) as error:
            raise ValueError(
                "expected_peers must contain valid IP addresses"
            ) from error
        remote_as = peer["remote_as_4_byte"]
        if (
            isinstance(remote_as, bool)
            or not isinstance(remote_as, int)
            or not 1 <= remote_as <= (1 << 32) - 1
        ):
            raise ValueError("expected_peers must contain valid 32-bit remote ASNs")
        if (
            not isinstance(peer["description"], str)
            or not peer["description"]
            or peer["peer_id"] != peer["peer_addr"]
            or peer["peer_group_name"] not in expected_groups
        ):
            raise ValueError("expected_peers contain an invalid compiled peer identity")
    expected_addresses = tuple(peer["peer_addr"] for peer in expected_peer_configs)
    if len(set(expected_addresses)) != len(expected_addresses):
        raise ValueError("expected_peers must have distinct peer addresses")
    if {peer["peer_group_name"] for peer in expected_peer_configs} != set(
        expected_groups
    ):
        raise ValueError("expected_peers must cover exactly the selected peer groups")
    _validate_bgpcpp_peer_replacement_inputs(
        target_config_path,
        None,
        expected_local_as_4_byte,
    )
    if not isinstance(expect_update_group_enabled, bool):
        raise TypeError("expect_update_group_enabled must be a bool")

    return "\n".join(
        [
            "import copy",
            "import json",
            "import os",
            "import shutil",
            "import tempfile",
            "from pathlib import Path",
            f"source_path = Path({source_config_path!r})",
            f"target_path = Path({target_config_path!r})",
            f"policy_name = {policy_name!r}",
            f"expected_groups = {expected_groups!r}",
            f"expected_peers = {expected_peer_configs!r}",
            f"expected_local_as = {expected_local_as_4_byte!r}",
            f"expected_update_group = {expect_update_group_enabled!r}",
            "source = json.loads(source_path.read_text())",
            "target = json.loads(target_path.read_text())",
            "if not isinstance(source, dict) or not isinstance(target, dict):",
            '    raise RuntimeError("BGP++ policy overlay inputs must be JSON objects")',
            "source_policies = source.get('policies', {}).get('bgp_policy_statements')",
            "target_policies = target.get('policies', {}).get('bgp_policy_statements')",
            "target_groups = target.get('peer_groups')",
            "if not isinstance(source_policies, list) or not isinstance(target_policies, list):",
            '    raise RuntimeError("BGP++ policy overlay requires policy statement lists")',
            "if not isinstance(target_groups, list):",
            '    raise RuntimeError("BGP++ policy overlay requires a peer_groups list")',
            "target_peers = target.get('peers')",
            "if not isinstance(target_peers, list):",
            '    raise RuntimeError("BGP++ policy overlay requires a peers list")',
            "expected_peers_by_address = {item['peer_addr']: item for item in expected_peers}",
            "observed_peers_by_address = {item.get('peer_addr'): item for item in target_peers if isinstance(item, dict)}",
            "if len(observed_peers_by_address) != len(target_peers) or observed_peers_by_address != expected_peers_by_address:",
            '    raise RuntimeError(f"bound peer verification failed: expected={expected_peers_by_address!r}, observed={observed_peers_by_address!r}")',
            "if target.get('local_as_4_byte') != expected_local_as:",
            "    raise RuntimeError(f\"bound local AS verification failed: expected={expected_local_as!r}, observed={target.get('local_as_4_byte')!r}\")",
            "observed_update_group = target.get('bgp_setting_config', {}).get('enable_update_group')",
            "if observed_update_group is not expected_update_group:",
            '    raise RuntimeError(f"bound update-group verification failed: expected={expected_update_group!r}, observed={observed_update_group!r}")',
            "matches = [item for item in source_policies if isinstance(item, dict) and item.get('name') == policy_name]",
            "if len(matches) != 1:",
            '    raise RuntimeError(f"expected one source policy {policy_name!r}, found {len(matches)}")',
            "selected_policy = copy.deepcopy(matches[0])",
            "matching_groups = [item for item in target_groups if isinstance(item, dict) and item.get('name') in expected_groups]",
            "observed_groups = tuple(item['name'] for item in matching_groups)",
            "if len(matching_groups) != len(expected_groups) or set(observed_groups) != set(expected_groups):",
            '    raise RuntimeError(f"exact peer-group selection failed: requested={expected_groups!r}, observed={observed_groups!r}")',
            "preserved = copy.deepcopy({key: value for key, value in target.items() if key not in {'peer_groups', 'policies'}})",
            "for group in matching_groups:",
            "    group['ingress_policy_name'] = policy_name",
            "target_policy_indices = [index for index, item in enumerate(target_policies) if isinstance(item, dict) and item.get('name') == policy_name]",
            "if len(target_policy_indices) > 1:",
            '    raise RuntimeError(f"target config contains duplicate policy {policy_name!r}")',
            "if target_policy_indices:",
            "    target_policies[target_policy_indices[0]] = selected_policy",
            "else:",
            "    target_policies.append(selected_policy)",
            "if {key: value for key, value in target.items() if key not in {'peer_groups', 'policies'}} != preserved:",
            '    raise RuntimeError("policy overlay modified a non-policy BGP++ field")',
            "metadata = target_path.stat()",
            "updated_content = json.dumps(target, indent=2).encode()",
            'fd, temporary_name = tempfile.mkstemp(dir=target_path.parent, prefix=f".{target_path.name}.policy-overlay.")',
            "temporary_path = Path(temporary_name)",
            "try:",
            '    with os.fdopen(fd, "wb") as temporary_file:',
            "        temporary_file.write(updated_content)",
            "        temporary_file.flush()",
            "        os.fsync(temporary_file.fileno())",
            "    if json.loads(temporary_path.read_text()) != target:",
            '        raise RuntimeError("policy overlay candidate failed verification")',
            "    temporary_metadata = temporary_path.stat()",
            "    if (temporary_metadata.st_uid, temporary_metadata.st_gid) != (metadata.st_uid, metadata.st_gid):",
            "        os.chown(temporary_path, metadata.st_uid, metadata.st_gid)",
            "    shutil.copymode(target_path, temporary_path)",
            "    os.replace(temporary_path, target_path)",
            "finally:",
            "    temporary_path.unlink(missing_ok=True)",
            "installed = json.loads(target_path.read_text())",
            "if installed != target:",
            '    raise RuntimeError("installed policy overlay differs from verified candidate")',
            "installed_groups = {item.get('name'): item.get('ingress_policy_name') for item in installed.get('peer_groups', []) if isinstance(item, dict) and item.get('name') in expected_groups}",
            "if installed_groups != {name: policy_name for name in expected_groups}:",
            '    raise RuntimeError(f"failed to verify installed peer-group policies: {installed_groups!r}")',
            "if {key: value for key, value in installed.items() if key not in {'peer_groups', 'policies'}} != preserved:",
            '    raise RuntimeError("installed policy overlay changed a non-policy BGP++ field")',
            "source_path.unlink(missing_ok=True)",
            'print(f"Installed policy-only overlay {policy_name} for {expected_groups}")',
            "",
        ]
    )


def build_bgpcpp_policy_overlay_cmd(
    *,
    source_config_path: str,
    policy_name: str,
    peer_group_names: t.Sequence[str],
    expected_peers: t.Sequence[t.Mapping[str, t.Any]],
    expected_local_as_4_byte: int,
    expect_update_group_enabled: bool,
    target_config_path: str = _BGPCPP_CONFIG_PATH,
) -> str:
    script = build_bgpcpp_policy_overlay_script(
        source_config_path=source_config_path,
        policy_name=policy_name,
        peer_group_names=peer_group_names,
        expected_peers=expected_peers,
        expected_local_as_4_byte=expected_local_as_4_byte,
        expect_update_group_enabled=expect_update_group_enabled,
        target_config_path=target_config_path,
    )
    encoded_script = base64.b64encode(script.encode("utf-8")).decode("ascii")
    pipeline = f"printf '%s' {shlex.quote(encoded_script)} | base64 -d | sudo python3 -"
    return f"bash {pipeline}"


@dataclass(frozen=True)
class OpenRStandaloneTeardownTasks:
    route_withdrawal: Task
    link_cleanup: tuple[Task, ...]


def openr_mode_for_bgpcpp_profile(profile: BgpPlusPlusProfile) -> OpenRMode:
    if profile is BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R:
        return OpenRMode.STANDALONE
    if profile is BgpPlusPlusProfile.BGP_PLUS_PLUS_WITHOUT_OPEN_R:
        return OpenRMode.NONE
    raise ValueError(f"unsupported BGP++ profile: {profile!r}")


def _validate_bgpcpp_peer_replacement_inputs(
    config_path: str,
    router_id: str | None,
    local_as_4_byte: int | None,
) -> None:
    _validate_bgpcpp_config_path(config_path, "config_path")
    if router_id is not None:
        try:
            ipaddress.IPv4Address(router_id)
        except ipaddress.AddressValueError as error:
            raise ValueError("router_id must be an IPv4 address") from error
    if local_as_4_byte is not None and (
        isinstance(local_as_4_byte, bool)
        or not isinstance(local_as_4_byte, int)
        or not 1 <= local_as_4_byte <= (1 << 32) - 1
    ):
        raise ValueError("local_as_4_byte must be a valid 32-bit ASN")


def create_bgpcpp_peer_replacement_tasks(
    hostname: str,
    router_id: str | None,
    peers: t.Sequence[t.Mapping[str, t.Any]],
    config_path: str = _BGPCPP_CONFIG_PATH,
    local_as_4_byte: int | None = None,
) -> list[Task]:
    _validate_bgpcpp_peer_replacement_inputs(
        config_path,
        router_id,
        local_as_4_byte,
    )
    peers_json = json.dumps([dict(peer) for peer in peers])
    peers_b64 = base64.b64encode(peers_json.encode()).decode()
    # Even an empty peer sequence encodes as non-empty JSON (`[]`), so the
    # first chunk always creates the temporary input file.
    chunks = [
        peers_b64[index : index + 20000] for index in range(0, len(peers_b64), 20000)
    ]
    chunk_commands = [
        (
            f"bash echo '{chunk}' > /tmp/peers.b64"
            if index == 0
            else f"bash echo '{chunk}' >> /tmp/peers.b64"
        )
        for index, chunk in enumerate(chunks)
    ]
    chunk_commands.extend(
        [
            "bash base64 -d /tmp/peers.b64 > /tmp/experiment_peers.json",
            "bash rm -f /tmp/peers.b64",
        ]
    )

    local_as_line = (
        f"c['local_as_4_byte']={local_as_4_byte}; "
        if local_as_4_byte is not None
        else ""
    )
    router_id_line = f"c['router_id']='{router_id}'; " if router_id is not None else ""
    router_id_display = (
        "c['router_id']" if router_id is not None else "c.get('router_id')"
    )
    merge_script = (
        f'sudo python3 -c "'
        f"import json; "
        f"f=open('{config_path}'); c=json.load(f); f.close(); "
        f"p=open('/tmp/experiment_peers.json'); "
        f"c['peers']=json.load(p); p.close(); "
        f"{router_id_line}"
        f"{local_as_line}"
        f"f=open('{config_path}','w'); "
        f"json.dump(c,f,indent=2); f.close(); "
        f"print('Updated peers:',len(c['peers']),"
        f"'router_id:',{router_id_display},"
        f"'local_as_4_byte:',c.get('local_as_4_byte'))"
        f'"'
    )
    return [
        create_run_commands_on_shell_task(
            hostname=hostname,
            cmds=chunk_commands,
            ixia_needed=True,
        ),
        create_run_commands_on_shell_task(
            hostname=hostname,
            cmds=[f"bash {merge_script}"],
            ixia_needed=True,
        ),
    ]


def get_bgpcpp_startup_tasks_for_openr_mode(
    hostname: str,
    openr_mode: OpenRMode,
) -> list[Task]:
    if openr_mode is not OpenRMode.NONE:
        return []
    return [
        create_configure_bgpcpp_startup_task(
            hostname=hostname,
            flags={_INTERFACE_STATE_NEXTHOP_FLAG: "true"},
            use_managed_shell=True,
            set_outer_hostname=True,
            ixia_needed=True,
        )
    ]


def _openr_port_channel_command(
    link: OpenRStandaloneLink,
    endpoint: OpenRStandaloneEndpoint,
    peer: OpenRStandaloneEndpoint,
) -> str:
    return (
        "configure\n"
        f"default interface {endpoint.member_interface}\n"
        "!\n"
        f"interface {link.interface_name}\n"
        f"description OPENR_STANDALONE_TO_{peer.hostname}\n"
        "load-interval 5\n"
        "mtu 9192\n"
        "no switchport\n"
        f"ip address {endpoint.ipv4_cidr}\n"
        f"ipv6 address {endpoint.ipv6_cidr}\n"
        f"ipv6 address {endpoint.link_local_cidr} link-local\n"
        "ipv6 nd ra disabled\n"
        "!\n"
        f"interface {endpoint.member_interface}\n"
        "no shutdown\n"
        "mtu 9000\n"
        f"speed {link.speed}\n"
        "no switchport\n"
        "ipv6 enable\n"
        "ipv6 address auto-config\n"
        "ipv6 nd ra rx accept default-route\n"
        f"channel-group {link.port_channel_id} mode active\n"
        "end"
    )


def get_openr_standalone_setup_tasks(
    link: OpenRStandaloneLink,
    start_ipv4s: t.Sequence[str] | None = None,
    start_ipv6s: t.Sequence[str] | None = None,
) -> list[Task]:
    """Render the standardized EOS standalone link and KvStore sequence.

    OpenR mode selection and placement in the complete setup sequence belong to
    ``EosBgpCppCompiler``. This renderer owns only the EOS commands emitted once
    that compiler has selected ``OpenRMode.STANDALONE``.

    Args:
        link: Owner/helper standalone link to render.
        start_ipv4s: Per-plane IPv4 next hops to inject reachability for. These
            must match the next hops the topology's emulated peers advertise,
            or those routes never resolve. Defaults to the ixia11 set.
        start_ipv6s: IPv6 counterpart of ``start_ipv4s``.
    """
    return [
        create_run_commands_on_shell_task(
            hostname=endpoint.hostname,
            cmds=[_openr_port_channel_command(link, endpoint, peer)],
            set_outer_hostname=True,
            ixia_needed=True,
        )
        for endpoint, peer in (
            (link.helper, link.owner),
            (link.owner, link.helper),
        )
    ] + [
        create_openr_route_action_task(
            device_name=link.owner.hostname,
            action=OpenRRouteAction.INJECT.value,
            start_ipv4s=list(start_ipv4s or DEFAULT_OPENR_START_IPV4S),
            start_ipv6s=list(start_ipv6s or DEFAULT_OPENR_START_IPV6S),
            local_link=link.kv_link(link.owner),
            other_link=link.kv_link(link.helper),
            count=_OPENR_STANDALONE_ROUTE_COUNT,
            step=_OPENR_STANDALONE_ROUTE_STEP,
            ixia_needed=True,
            set_outer_hostname=True,
        )
    ]


def get_openr_standalone_teardown_tasks(
    link: OpenRStandaloneLink,
    start_ipv4s: t.Sequence[str] | None = None,
    start_ipv6s: t.Sequence[str] | None = None,
) -> OpenRStandaloneTeardownTasks:
    """Render the standalone link teardown, withdrawing the injected routes.

    Args:
        link: Owner/helper standalone link to tear down.
        start_ipv4s: Per-plane IPv4 next hops to withdraw. Must match what
            setup injected, or the withdrawal misses. Defaults to the ixia11 set.
        start_ipv6s: IPv6 counterpart of ``start_ipv4s``.
    """
    route_withdrawal = create_openr_route_action_task(
        device_name=link.owner.hostname,
        action=OpenRRouteAction.DELETE.value,
        start_ipv4s=list(start_ipv4s or DEFAULT_OPENR_START_IPV4S),
        start_ipv6s=list(start_ipv6s or DEFAULT_OPENR_START_IPV6S),
        local_link=link.kv_link(link.owner),
        other_link=link.kv_link(link.helper),
        count=_OPENR_STANDALONE_ROUTE_COUNT,
        step=_OPENR_STANDALONE_ROUTE_STEP,
        ixia_needed=True,
        set_outer_hostname=True,
    )
    link_cleanup = []
    for endpoint in (link.owner, link.helper):
        link_cleanup.append(
            create_run_commands_on_shell_task(
                hostname=endpoint.hostname,
                cmds=[
                    "configure\n"
                    f"interface {endpoint.member_interface}\n"
                    f"no channel-group {link.port_channel_id}\n"
                    "no ipv6 nd ra rx accept default-route\n"
                    "no ipv6 address auto-config\n"
                    "no ipv6 enable\n"
                    "!\n"
                    f"no interface {link.interface_name}\n"
                    "end"
                ],
                set_outer_hostname=True,
                ixia_needed=True,
            )
        )
    return OpenRStandaloneTeardownTasks(
        route_withdrawal=route_withdrawal,
        link_cleanup=tuple(link_cleanup),
    )
