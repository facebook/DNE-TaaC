# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-strict

"""Client for the narrow Meta-only host bridge used by OSS TAAC CI."""

import asyncio
import json
import os
import socket
import subprocess
import typing as t


BRIDGE_SOCKET_ENV: str = "TAAC_META_INTERNAL_BRIDGE_SOCKET"
# Log collection sends command output in the JSON response. Agent and qsfp
# logs routinely exceed 64 KiB, so retain a bounded limit large enough for the
# same diagnostic reads supported by the direct SSH implementation.
_MAX_RESPONSE_BYTES: int = 64 * 1024 * 1024


class MetaInternalBridgeError(RuntimeError):
    pass


def bridge_enabled() -> bool:
    return os.environ.get("TAAC_OSS_META_INTERNAL", "").lower() in (
        "1",
        "true",
        "yes",
    ) and bool(os.environ.get(BRIDGE_SOCKET_ENV))


def _socket_path() -> str:
    path = os.environ.get(BRIDGE_SOCKET_ENV)
    if not path:
        raise MetaInternalBridgeError(
            f"{BRIDGE_SOCKET_ENV} must point to the mounted Meta bridge socket"
        )
    return path


def _validate_response(response: t.Any) -> dict[str, t.Any]:
    if not isinstance(response, dict):
        raise MetaInternalBridgeError("Meta bridge returned a non-object response")
    if not response.get("ok"):
        raise MetaInternalBridgeError(
            str(response.get("error") or "Meta bridge failed")
        )
    result = response.get("result")
    if not isinstance(result, dict):
        raise MetaInternalBridgeError("Meta bridge response has no result object")
    return result


def _request(request: dict[str, t.Any], timeout_sec: int = 30) -> dict[str, t.Any]:
    payload = (json.dumps(request) + "\n").encode()
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(timeout_sec)
            client.connect(_socket_path())
            client.sendall(payload)
            with client.makefile("rb") as response_file:
                response_data = response_file.readline(_MAX_RESPONSE_BYTES + 1)
    except OSError as error:
        raise MetaInternalBridgeError(f"Cannot reach Meta bridge: {error}") from error

    if not response_data:
        raise MetaInternalBridgeError("Meta bridge returned an empty response")
    if len(response_data) > _MAX_RESPONSE_BYTES:
        raise MetaInternalBridgeError("Meta bridge response exceeded the size limit")
    try:
        return _validate_response(json.loads(response_data))
    except json.JSONDecodeError as error:
        raise MetaInternalBridgeError("Meta bridge returned invalid JSON") from error


def fetch_ixia_password(
    secret_name: str | None = None,
    secret_group: str | None = None,
) -> str:
    request: dict[str, t.Any] = {"operation": "get_ixia_password"}
    if secret_name is not None:
        request["secret_name"] = secret_name
    if secret_group is not None:
        request["secret_group"] = secret_group
    result = _request(request)
    password = result.get("password")
    if not isinstance(password, str) or not password:
        raise MetaInternalBridgeError("Meta bridge returned an empty IXIA password")
    return password


async def ssh_exec(
    *,
    hostname: str,
    command: str,
    timeout_sec: int = 300,
    block: bool = True,
    return_on_msg: str | None = None,
    port: int = 22,
    username: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Execute a DUT shell command through the authenticated host bridge."""
    request: dict[str, t.Any] = {
        "operation": "ssh_exec",
        "host": hostname,
        "command": command,
        "timeout_sec": timeout_sec,
        "block": block,
        "return_on_msg": return_on_msg,
        "port": port,
        "username": username,
    }
    result = await asyncio.to_thread(_request, request, timeout_sec + 30)
    stdout = result.get("stdout")
    stderr = result.get("stderr")
    returncode = result.get("returncode")
    if not isinstance(stdout, str) or not isinstance(stderr, str):
        raise MetaInternalBridgeError("Meta bridge returned invalid SSH output")
    if not isinstance(returncode, int):
        raise MetaInternalBridgeError("Meta bridge returned an invalid SSH return code")
    if returncode != 0:
        error_output = stderr.strip() or stdout.strip() or "no output"
        raise MetaInternalBridgeError(
            f"SSH command failed on {hostname} with exit code {returncode}: "
            f"{error_output}"
        )
    return subprocess.CompletedProcess(
        args=command,
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )
