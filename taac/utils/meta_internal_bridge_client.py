# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-strict

"""Client for the narrow Meta-only credential broker used by OSS TAAC CI."""

import json
import os
import socket
import typing as t


BRIDGE_SOCKET_ENV: str = "TAAC_META_INTERNAL_BRIDGE_SOCKET"
_MAX_RESPONSE_BYTES: int = 64 * 1024


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
