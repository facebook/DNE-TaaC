# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

"""
Async client for the Keysight Ixia chassis DiagnosticService REST API.

Wraps `/platform/api/v2/diagnostics/*` so TAAC test runs can collect chassis
diagnostic archives (IxNetwork session logs incl. BGP++, port logs, etc.) at
teardown.

Vendor warning: every collection costs time + disk on the chassis. The class
ALWAYS pairs a download with a DELETE in a try/finally so archives do not
accumulate, even when the test fails mid-flight.

State and status code values below were confirmed by an end-to-end probe
against a Keysight IxNetwork Web Edition chassis (2026-06-03):

  POST   /diagnostics              -> 202, body has `id`
  GET    /diagnostics/{id}         -> 200, body has `state` + `progress`
                                     state cycles IN_PROGRESS -> SUCCESS
  GET    /diagnostics/{id}/result  -> 200, body is binary tar.gz
  DELETE /diagnostics/{id}/result  -> 200 (NOT 204 as some docs imply)
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import time
from dataclasses import dataclass
from pathlib import Path

from aiohttp import BasicAuth, ClientSession, ClientTimeout
from neteng.netcastle.constants_not_thrift import RestAPI
from neteng.netcastle.utils.common import json_dumps
from neteng.netcastle.utils.ixia_utils import (
    async_get_ixia_api_key,
    async_get_platform_url,
    async_make_ixia_api_call,
)


logger: logging.Logger = logging.getLogger(__name__)

_DIAGNOSTICS_ENDPOINT = "diagnostics"
_COMPONENTS_ENDPOINT = "diagnostics/components"

DEFAULT_POLL_INTERVAL_S = 5
DEFAULT_POLL_TIMEOUT_S = 300
DEFAULT_DOWNLOAD_TIMEOUT_S = 600

# Display names from Keysight; POST /diagnostics accepts these verbatim.
# Confirmed against a live IxNetwork Web Edition chassis — see module docstring.
COMPONENT_IXNETWORK = "IxNetwork Web Edition (System logs)"
COMPONENT_PORT_LOGS = "Port logs"
COMPONENT_CHASSIS = "Chassis (System logs)"
COMPONENT_NETWORK_CONFORMANCE = "Network Conformance (System logs)"

# Recommended default when a TestConfig opts into diagnostics without naming
# components: covers the BGP/protocol-engine logs that live in the IxNetwork
# app plus per-port L1/SFP transitions, skipping the larger chassis HW dump.
DEFAULT_SESSION_COMPONENTS: tuple[str, ...] = (
    COMPONENT_IXNETWORK,
    COMPONENT_PORT_LOGS,
)

_TERMINAL_SUCCESS_STATES = frozenset(
    {"SUCCESS", "COMPLETED", "Completed", "complete", "success"}
)
_TERMINAL_FAILURE_STATES = frozenset(
    {"ERROR", "FAILED", "CANCELLED", "error", "failed", "cancelled"}
)


@dataclass(frozen=True)
class DiagnosticsArchive:
    """Outcome of a successful collect_and_download call.

    Only constructed on the happy path: any error in start / poll / download
    re-raises out of `collect_and_download` before this is built, so callers
    that receive an instance can rely on `path` pointing to a real file.
    """

    async_id: str
    path: Path
    size_bytes: int
    components: tuple[str, ...]


class IxiaDiagnosticsCollectionError(Exception):
    """Raised when the chassis reports a terminal failure state for a collection."""


def _url_safe_host(host: str) -> str:
    """RFC 3986: an IPv6 literal in an authority MUST be wrapped in `[...]`.

    Many TAAC EBB testbeds register chassis as bare IPv6 literals (e.g.
    `2401:db00:2066:303b::3001`). Without bracketing, `https://{host}/...`
    fails URL parsing because the colons are interpreted as port separators
    (aiohttp raises `InvalidUrlClientError`). DNS names and IPv4 addresses
    pass through unchanged. Already-bracketed hosts are also passed through.
    """
    if host.startswith("["):
        return host
    try:
        ipaddress.IPv6Address(host)
    except (ValueError, ipaddress.AddressValueError):
        return host
    return f"[{host}]"


class IxiaDiagnosticsClient:
    """Stateless async client for Keysight DiagnosticService.

    Callers own the lifecycle. For one-shot collection use `collect_and_download`,
    which handles start/poll/download/delete with try/finally cleanup.
    """

    def __init__(
        self,
        chassis_hostname: str,
        username: str,
        password: str,
    ) -> None:
        # Bracket-wrap IPv6 literals so f"https://{host}/..." parses correctly.
        # Production conveyor failures (e.g. bag010 @ 2401:db00:2066:303b::3001)
        # silently failed with `InvalidUrlClientError` before this fix.
        self._chassis = _url_safe_host(chassis_hostname)
        self._username = username
        self._password = password

    async def list_components(self) -> list[str]:
        """Returns the flat list of every component (parents + leaves).

        The chassis tolerates posting a parent name (e.g. "Chassis (System logs)")
        as a shorthand for "collect all its descendants".
        """
        url = await async_get_platform_url(
            self._chassis, _COMPONENTS_ENDPOINT, api_prefix=""
        )
        resp = await async_make_ixia_api_call(
            ixia_hostname=self._chassis,
            api_endpoint=url,
            rest_method=RestAPI.GET,
            username=self._username,
            password=self._password,
        )
        if isinstance(resp, list):
            return _flatten_components(resp)
        if isinstance(resp, dict):
            for key in ("components", "items", "data"):
                value = resp.get(key)
                if isinstance(value, list):
                    return _flatten_components(value)
        raise RuntimeError(
            f"Unexpected /diagnostics/components response shape: {type(resp).__name__}"
        )

    async def start_collection(self, components: list[str] | None) -> str:
        """POST /diagnostics. Returns the chassis-assigned async id.

        `components=None` means collect every component (vendor default).
        """
        url = await async_get_platform_url(
            self._chassis, _DIAGNOSTICS_ENDPOINT, api_prefix=""
        )
        body = json_dumps({"components": components}) if components else json_dumps({})
        resp = await async_make_ixia_api_call(
            ixia_hostname=self._chassis,
            api_endpoint=url,
            rest_method=RestAPI.POST,
            request_body=body,
            username=self._username,
            password=self._password,
            success_status_code=202,
        )
        async_id = (
            resp.get("id") or resp.get("asyncId") or resp.get("operationId")
            if isinstance(resp, dict)
            else None
        )
        if not async_id:
            raise RuntimeError(f"POST /diagnostics did not return an id: {resp!r}")
        return str(async_id)

    async def wait_for_completion(
        self,
        async_id: str,
        timeout_s: int = DEFAULT_POLL_TIMEOUT_S,
        poll_interval_s: int = DEFAULT_POLL_INTERVAL_S,
    ) -> None:
        """Polls GET /diagnostics/{id} until state is terminal."""
        url = await async_get_platform_url(
            self._chassis,
            f"{_DIAGNOSTICS_ENDPOINT}/{async_id}",
            api_prefix="",
        )
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            resp = await async_make_ixia_api_call(
                ixia_hostname=self._chassis,
                api_endpoint=url,
                rest_method=RestAPI.GET,
                username=self._username,
                password=self._password,
            )
            state = resp.get("state") if isinstance(resp, dict) else None
            progress = resp.get("progress") if isinstance(resp, dict) else None
            logger.info(
                f"ixia diagnostics {async_id}: state={state} progress={progress}"
            )
            if state in _TERMINAL_SUCCESS_STATES:
                return
            if state in _TERMINAL_FAILURE_STATES:
                raise IxiaDiagnosticsCollectionError(
                    f"Diagnostics {async_id} terminal failure: {resp!r}"
                )
            await asyncio.sleep(poll_interval_s)
        raise TimeoutError(f"Diagnostics {async_id} did not finish within {timeout_s}s")

    async def download_archive_to_file(
        self,
        async_id: str,
        dest_path: Path,
        timeout_s: int = DEFAULT_DOWNLOAD_TIMEOUT_S,
        chunk_size: int = 64 * 1024,
    ) -> int:
        """Streams the archive to disk; returns byte count.

        Uses raw aiohttp because `async_make_rest_api_call` UTF-8-decodes the
        response body (rest_api_utils.py:91), which corrupts binary blobs.
        Streaming keeps memory bounded on Chronos containers; archives can be
        300-500 MiB under load.
        """
        url = await async_get_platform_url(
            self._chassis,
            f"{_DIAGNOSTICS_ENDPOINT}/{async_id}/result",
            api_prefix="",
        )
        api_key = await async_get_ixia_api_key(
            self._chassis, self._username, self._password
        )
        headers = {"x-api-key": api_key}
        auth = BasicAuth(login=self._username, password=self._password)
        total = 0
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        async with ClientSession(timeout=ClientTimeout(total=timeout_s)) as session:
            async with session.get(url, headers=headers, auth=auth, ssl=False) as resp:
                if resp.status != 200:
                    raise RuntimeError(
                        f"archive download returned HTTP {resp.status}: "
                        f"{(await resp.text())[:200]!r}"
                    )
                with dest_path.open("wb") as fh:
                    async for chunk in resp.content.iter_chunked(chunk_size):
                        fh.write(chunk)
                        total += len(chunk)
        return total

    async def delete_archive(self, async_id: str) -> None:
        """DELETE /diagnostics/{id}/result. Chassis returns HTTP 200."""
        url = await async_get_platform_url(
            self._chassis,
            f"{_DIAGNOSTICS_ENDPOINT}/{async_id}/result",
            api_prefix="",
        )
        await async_make_ixia_api_call(
            ixia_hostname=self._chassis,
            api_endpoint=url,
            rest_method=RestAPI.DELETE,
            username=self._username,
            password=self._password,
            success_status_code=200,
        )

    async def collect_and_download(
        self,
        dest_path: Path,
        components: list[str] | None = None,
        poll_timeout_s: int = DEFAULT_POLL_TIMEOUT_S,
        download_timeout_s: int = DEFAULT_DOWNLOAD_TIMEOUT_S,
    ) -> DiagnosticsArchive:
        """End-to-end: start → wait → download → delete.

        DELETE always runs (in finally) — even if the download fails — so the
        chassis stays clean. If `components` is None, uses the TAAC framework
        default subset (`DEFAULT_SESSION_COMPONENTS`: IxNetwork app + Port
        logs), NOT the vendor's "collect everything" default. Pass an explicit
        list of names to override; use `start_collection(None)` if you really
        want the vendor-default full collection.
        """
        effective_components = (
            list(components) if components else list(DEFAULT_SESSION_COMPONENTS)
        )
        async_id = await self.start_collection(effective_components)
        logger.info(
            f"ixia diagnostics: started async_id={async_id} on {self._chassis} "
            f"components={effective_components}"
        )
        try:
            await self.wait_for_completion(async_id, timeout_s=poll_timeout_s)
            size = await self.download_archive_to_file(
                async_id, dest_path, timeout_s=download_timeout_s
            )
            logger.info(
                f"ixia diagnostics: downloaded async_id={async_id} "
                f"size={size} bytes ({size / 1024 / 1024:.1f} MiB) -> {dest_path}"
            )
        finally:
            try:
                await self.delete_archive(async_id)
                logger.info(
                    f"ixia diagnostics: deleted async_id={async_id} from chassis"
                )
            except Exception as exc:
                logger.error(
                    f"ixia diagnostics: FAILED to delete async_id={async_id} "
                    f"from chassis: {exc!r}. Manual cleanup may be required."
                )
        # Only reached on the happy path: any exception above re-raises through
        # the finally block, never reaching this return.
        return DiagnosticsArchive(
            async_id=async_id,
            path=dest_path,
            size_bytes=size,
            components=tuple(effective_components),
        )


def _flatten_components(nodes: list[dict]) -> list[str]:
    """Walk Keysight's nested {componentName, subComponents} tree."""
    out: list[str] = []
    for node in nodes:
        name = node.get("componentName")
        if name:
            out.append(str(name))
        subs = node.get("subComponents") or []
        if isinstance(subs, list) and subs:
            out.extend(_flatten_components(subs))
    return out
