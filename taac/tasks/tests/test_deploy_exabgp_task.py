# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe

import argparse
import asyncio
import sys
import typing as t

from taac.tasks.deploy_exabgp_task import (
    CleanupExaBGPTask,
    DeployExaBGPTask,
)
from taac.utils.oss_taac_lib_utils import get_root_logger


async def test_deploy(hostname: str, fbpkg_name: str, remote_path: str) -> None:
    logger = get_root_logger()
    logger.info(f"=== Testing DeployExaBGPTask on {hostname} ===")

    task = DeployExaBGPTask(hostname=hostname, logger=logger)
    params: t.Dict[str, t.Any] = {
        "hostname": hostname,
        "fbpkg_name": fbpkg_name,
        "remote_path": remote_path,
    }

    await task.run(params)
    logger.info(f"=== Deploy test PASSED on {hostname} ===")


async def test_cleanup(hostname: str, remote_path: str, restart_bgpd: bool) -> None:
    logger = get_root_logger()
    logger.info(f"=== Testing CleanupExaBGPTask on {hostname} ===")

    task = CleanupExaBGPTask(hostname=hostname, logger=logger)
    params: t.Dict[str, t.Any] = {
        "hostname": hostname,
        "remote_path": remote_path,
        "restart_bgpd": restart_bgpd,
    }

    await task.run(params)
    logger.info(f"=== Cleanup test PASSED on {hostname} ===")


async def test_deploy_and_cleanup(
    hostname: str, fbpkg_name: str, remote_path: str, restart_bgpd: bool
) -> None:
    await test_deploy(hostname, fbpkg_name, remote_path)
    await test_cleanup(hostname, remote_path, restart_bgpd)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Test ExaBGP deploy/cleanup tasks on a real device"
    )
    parser.add_argument("hostname", help="Target device hostname")
    parser.add_argument(
        "--action",
        choices=["deploy", "cleanup", "both"],
        default="both",
        help="Which task to test (default: both)",
    )
    parser.add_argument(
        "--fbpkg-name", default="exabgp", help="fbpkg name (default: exabgp)"
    )
    parser.add_argument(
        "--remote-path",
        default="/tmp/exabgpd.par",
        help="Remote path for PAR file (default: /tmp/exabgpd.par)",
    )
    parser.add_argument(
        "--no-restart-bgpd",
        action="store_true",
        help="Skip restarting bgpd during cleanup",
    )

    args = parser.parse_args()

    if args.action == "deploy":
        coro = test_deploy(args.hostname, args.fbpkg_name, args.remote_path)
    elif args.action == "cleanup":
        coro = test_cleanup(args.hostname, args.remote_path, not args.no_restart_bgpd)
    else:
        coro = test_deploy_and_cleanup(
            args.hostname, args.fbpkg_name, args.remote_path, not args.no_restart_bgpd
        )

    asyncio.run(coro)


if __name__ == "__main__":
    main()
