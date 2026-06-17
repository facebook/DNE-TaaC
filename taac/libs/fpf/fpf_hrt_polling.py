#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

from __future__ import annotations

import asyncio
import socket
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from host_reach_tracker.hostreachtracker_ctrl.clients import HostReachTrackerCtrl
from taac.libs.fpf.fpf_hrt_capture import format_readable_ts
from servicerouter.py3 import ClientParams, get_sr_client


@dataclass
class PrefixPollSample:
    timestamp: str
    poll_index: int
    reachable_planes: list[int]
    failed_planes: list[int]


SampleCallback = Callable[[PrefixPollSample], None]


def to_fqdn(host: str) -> str:
    if not host.endswith(".facebook.com"):
        return f"{host}.facebook.com"
    return host


def resolve_ipv6(fqdn: str) -> str:
    results = socket.getaddrinfo(fqdn, None, socket.AF_INET6)
    if results:
        return str(results[0][4][0])
    raise RuntimeError(f"Cannot resolve {fqdn} to IPv6")


def _normalize_prefix(prefix: str) -> str:
    return prefix.strip().lower()


async def get_hrt_client(host: str):
    fqdn = to_fqdn(host)
    ip_addr = resolve_ipv6(fqdn)
    client_params = (
        ClientParams()
        .setSingleHost(ipAddr=ip_addr, port=5909)
        .setOverallTimeoutMs(10000)
    )
    client_params.setProcessingTimeoutMs(10000)
    return get_sr_client(HostReachTrackerCtrl, "", params=client_params)


async def run_capture_loop(
    host: str,
    prefix: str,
    interval_sec: float,
    device_id: int,
    on_sample: SampleCallback,
    stop_event: asyncio.Event,
) -> None:
    target_prefix = _normalize_prefix(prefix)
    poll_index = 0

    async with await get_hrt_client(host) as client:
        while not stop_event.is_set():
            now = datetime.now().astimezone()
            sample_ts = format_readable_ts(now)
            pfx_task = asyncio.create_task(client.getPrefixTable())
            neg_task = asyncio.create_task(client.getRemoteFailures())
            prefixes = await pfx_task
            neg_routes = await neg_task

            reachable_planes: list[int] = []
            for p in prefixes:
                if _normalize_prefix(p.prefix) != target_prefix:
                    continue
                if p.device_id != device_id:
                    continue
                reachable_planes = sorted(
                    pl.plane_id for pl in p.planes if not pl.is_drained
                )
                break

            failed_planes: list[int] = []
            for nr in neg_routes:
                if _normalize_prefix(nr.prefix) != target_prefix:
                    continue
                if nr.device_id != device_id:
                    continue
                failed_planes = sorted(nr.failed_planes)
                break

            on_sample(
                PrefixPollSample(
                    timestamp=sample_ts,
                    poll_index=poll_index,
                    reachable_planes=reachable_planes,
                    failed_planes=failed_planes,
                )
            )
            poll_index += 1

            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval_sec)
            except asyncio.TimeoutError:
                pass
