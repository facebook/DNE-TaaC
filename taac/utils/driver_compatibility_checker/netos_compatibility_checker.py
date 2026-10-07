#!/usr/bin/env fbpython
# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

"""Validate wedge_agent restart support across FBOSS OS variants."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from dataclasses import asdict, dataclass

from taac.driver.driver_constants import FbossSystemctlServiceName
from taac.utils.driver_factory import async_get_device_driver


DEFAULT_DEVICES: tuple[str, ...] = (
    "rsw004.p005.f01.qza1.tfbnw.net",
    "rsw001.p006.f01.qzd1",
    "fsw001.p001.f01.qzd1",
)


@dataclass(frozen=True)
class CompatibilityResult:
    hostname: str
    driver: str
    os_type: str
    fboss_cli_reachable: bool
    service: str
    agent_configured: bool
    bgp_converged: bool


async def check_device(
    hostname: str,
    *,
    timeout: int,
    check_bgp: bool,
) -> CompatibilityResult:
    """Restart wedge_agent once and validate recovery on one device."""
    driver = await async_get_device_driver(hostname)
    service = FbossSystemctlServiceName.AGENT
    # All built-in targets are FBOSS devices; the factory's shared return type
    # intentionally exposes only the cross-platform AbstractSwitch surface.
    # pyrefly: ignore [missing-attribute]
    os_type = await driver.async_get_fboss_os_type()
    fboss_version = await driver.async_run_cmd_on_shell("fboss2 show version")
    if not fboss_version or not fboss_version.strip():
        raise RuntimeError(f"{hostname}: fboss2 show version returned no output")

    logging.info(
        "%s: restarting %s through %s",
        hostname,
        service.value,
        type(driver).__name__,
    )
    await driver.async_restart_service(service)
    await driver.async_wait_for_agent_configured(timeout=timeout)
    if check_bgp:
        await driver.async_wait_for_bgp_convergence(timeout=timeout)

    return CompatibilityResult(
        hostname=hostname,
        driver=type(driver).__name__,
        os_type=os_type.value,
        fboss_cli_reachable=True,
        service=service.value,
        agent_configured=True,
        bgp_converged=check_bgp,
    )


async def run_checks(args: argparse.Namespace) -> int:
    """Run checks sequentially to avoid simultaneous control-plane disruption."""
    devices = tuple(args.device or DEFAULT_DEVICES)
    results: list[CompatibilityResult] = []
    failures: dict[str, str] = {}

    for hostname in devices:
        try:
            results.append(
                await check_device(
                    hostname,
                    timeout=args.timeout,
                    check_bgp=not args.skip_bgp_check,
                )
            )
        except Exception as error:
            logging.exception("%s: compatibility check failed", hostname)
            failures[hostname] = str(error)

    print(
        json.dumps(
            {
                "compatible": not failures,
                "results": [asdict(result) for result in results],
                "failures": failures,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 1 if failures else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Restart wedge_agent through the TAAC FBOSS driver and validate "
            "agent/BGP recovery across NetOS and classic OS devices."
        )
    )
    parser.add_argument(
        "--device",
        action="append",
        help="Device to check. Repeat to override the built-in three-device matrix.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Seconds to wait for agent and BGP recovery (default: 300).",
    )
    parser.add_argument(
        "--skip-bgp-check",
        action="store_true",
        help="Validate only wedge_agent restart and configured state.",
    )
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    raise SystemExit(asyncio.run(run_checks(parse_args())))


if __name__ == "__main__":
    main()
