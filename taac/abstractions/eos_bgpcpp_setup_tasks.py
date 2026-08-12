# Copyright (c) Meta Platforms, Inc. and affiliates.

"""Concrete setup-task renderers owned by the EOS BGP++ backend."""

import base64
import ipaddress
import json
import shlex
import typing as t
from dataclasses import dataclass

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
from taac.test_as_a_config.types import Task

_INTERFACE_STATE_NEXTHOP_FLAG = "bgp_resolve_nexthops_from_interface_state"
_BGPCPP_CONFIG_PATH = "/mnt/flash/bgpcpp_config"
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
    return create_run_commands_on_shell_task(
        hostname=hostname,
        cmds=[command],
        set_outer_hostname=True,
        ixia_needed=True,
        validate_output=True,
    )


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
    if (
        not config_path.startswith("/")
        or not config_path.isascii()
        or any(not (char.isalnum() or char in "/._-") for char in config_path)
    ):
        raise ValueError("config_path must be a shell-safe absolute path")
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
