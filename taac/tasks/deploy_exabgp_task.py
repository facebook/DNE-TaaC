# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe

import os
import shutil
import subprocess
import tempfile
import typing as t

from neteng.netcastle.utils.paramiko_utils import ParamikoClient
from taac.tasks.base_task import BaseTask


class DeployExaBGPTask(BaseTask):
    """Deploy ExaBGP PAR files from fbpkg to a FBOSS device.

    Fetches the exabgp fbpkg on the test runner (sandcastle), then SCPs
    both exabgpd.par and exabgpcli.par binaries to the target device
    via Paramiko SFTP.
    """

    NAME = "deploy_exabgp"

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        hostname = params["hostname"]
        remote_path = params.get("remote_path", "/tmp/exabgpd.par")
        cli_remote_path = params.get("cli_remote_path", "/tmp/exabgpcli.par")
        fbpkg_name = params.get("fbpkg_name", "exabgp")
        deploy_cli = params.get("deploy_cli", True)

        self.hostname = hostname
        await self._setup()

        self.logger.info(
            f"Deploying ExaBGP from fbpkg '{fbpkg_name}' to {hostname}:{remote_path}"
        )

        local_dir = tempfile.mkdtemp(prefix="exabgp_deploy_")
        try:
            subprocess.run(
                ["fbpkg", "fetch", fbpkg_name, "-d", local_dir],
                check=True,
                capture_output=True,
                text=True,
                timeout=300,
            )
            self.logger.info(f"Fetched fbpkg '{fbpkg_name}' to {local_dir}")

            local_par = os.path.join(local_dir, "exabgpd.par")
            if not os.path.exists(local_par):
                raise FileNotFoundError(
                    f"exabgpd.par not found in fbpkg '{fbpkg_name}' at {local_dir}. "
                    f"Contents: {os.listdir(local_dir)}"
                )

            client = ParamikoClient(hostname)
            client.scp(local_path=local_par, remote_path=remote_path)
            self.logger.info(f"SCPed exabgpd.par to {hostname}:{remote_path}")

            await self.driver().async_run_cmd_on_shell(f"chmod +x {remote_path}")
            self.logger.info(f"Made {remote_path} executable on {hostname}")

            if deploy_cli:
                local_cli = os.path.join(local_dir, "exabgpcli.par")
                if not os.path.exists(local_cli):
                    self.logger.warning(
                        f"exabgpcli.par not found in fbpkg '{fbpkg_name}' at {local_dir}. "
                        f"Skipping CLI deployment. Contents: {os.listdir(local_dir)}"
                    )
                else:
                    client.scp(local_path=local_cli, remote_path=cli_remote_path)
                    self.logger.info(
                        f"SCPed exabgpcli.par to {hostname}:{cli_remote_path}"
                    )

                    await self.driver().async_run_cmd_on_shell(
                        f"chmod +x {cli_remote_path}"
                    )
                    self.logger.info(f"Made {cli_remote_path} executable on {hostname}")

        finally:
            shutil.rmtree(local_dir, ignore_errors=True)


class CleanupExaBGPTask(BaseTask):
    """Stop ExaBGP and clean up deployed files on a FBOSS device."""

    NAME = "cleanup_exabgp"

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        hostname = params["hostname"]
        remote_path = params.get("remote_path", "/tmp/exabgpd.par")
        config_path = params.get("config_path", "/tmp/exabgp.conf")
        restart_bgpd = params.get("restart_bgpd", True)

        self.hostname = hostname
        await self._setup()

        self.logger.info(f"Cleaning up ExaBGP on {hostname}")

        await self.driver().async_run_cmd_on_shell("pkill -f exabgp || true")
        self.logger.info("Stopped ExaBGP process")

        cleanup_paths = [
            remote_path,
            config_path,
            "/tmp/exabgp_routes.py",
            "/tmp/exabgp.log",
            "/tmp/exabgp_stdout.log",
        ]
        await self.driver().async_run_cmd_on_shell(f"rm -f {' '.join(cleanup_paths)}")
        self.logger.info("Cleaned up ExaBGP files")

        if restart_bgpd:
            await self.driver().async_run_cmd_on_shell("sudo systemctl start bgpd")
            self.logger.info("Restarted BGP++ on device")
