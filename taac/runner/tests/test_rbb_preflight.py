#!/usr/bin/env python3
# pyre-unsafe

import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import TestCase


class TestRbbPreflight(TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_dir = Path(self.temp_dir.name) / "rbb-config"
        self.repo_root = Path(__file__).resolve().parents[3]
        self.runner = self.repo_root / "scripts" / "run-rbb-srv6.sh"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _clean_environment(self):
        environment = {
            name: value
            for name, value in os.environ.items()
            if not name.startswith("TAAC_")
        }
        environment["PYTHONPATH"] = str(self.repo_root)
        return environment

    def _run_init(self) -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                str(self.runner),
                "--config-dir",
                str(self.config_dir),
                "--init",
            ],
            cwd=self.repo_root,
            env=self._clean_environment(),
            text=True,
            capture_output=True,
            check=False,
        )

    def _run_check(
        self,
        *,
        with_traffic: bool = False,
        setup_duts: bool = False,
        setup_dut_edges: bool = False,
    ) -> subprocess.CompletedProcess:
        command = [
            sys.executable,
            "-m",
            "taac.runner.rbb_preflight",
            "--config-dir",
            str(self.config_dir),
        ]
        if with_traffic:
            command.append("--with-traffic")
        if setup_duts:
            command.append("--setup-duts")
        if setup_dut_edges:
            command.append("--setup-dut-edges")
        return subprocess.run(
            command,
            cwd=self.repo_root,
            env=self._clean_environment(),
            text=True,
            capture_output=True,
            check=False,
        )

    def _write_valid_config(
        self, *, ixia_credentials: bool = True, dut_username: str = "dut-user"
    ) -> None:
        self.config_dir.mkdir(mode=0o700)
        (self.config_dir / "rbb.env").write_text(
            "\n".join(
                (
                    "TAAC_OSS=1",
                    "TAAC_RBB_R1_HOST=rbb-r1.lab.local",
                    "TAAC_RBB_R2_HOST=rbb-r2.lab.local",
                    "TAAC_RBB_R1_HARDWARE=TEST_FBOSS",
                    "TAAC_RBB_R2_HARDWARE=TEST_FBOSS",
                    "TAAC_RBB_IXIA_CHASSIS=10.0.0.3",
                    "TAAC_IXIA_API_SERVER=10.0.0.4",
                    "TAAC_RBB_IXIA_TAIL_PREFIX=2001:db8:beef::",
                    "TAAC_RBB_IXIA_TAIL_PREFIX_LEN=64",
                    "TAAC_RBB_IXIA_TAIL_PREFIX_COUNT=1",
                    "TAAC_RBB_TAIL_PREFIX=2001:db8:beef::/64",
                    "",
                )
            ),
            encoding="utf-8",
        )
        secrets = {
            "version": 1,
            "dut": {"username": dut_username, "password": "dut-secret"},
            "ixia": {
                "username": "ixia-user" if ixia_credentials else "",
                "password": "ixia-secret" if ixia_credentials else "",
            },
        }
        secrets_path = self.config_dir / "secrets.json"
        secrets_path.write_text(json.dumps(secrets), encoding="utf-8")
        secrets_path.chmod(0o600)
        (self.config_dir / "device_info.csv").write_text(
            "rbb-r1.lab.local,,,,RBB,FBOSS,TEST_FBOSS\n"
            "rbb-r2.lab.local,,,,RBB,FBOSS,TEST_FBOSS\n",
            encoding="utf-8",
        )
        (self.config_dir / "circuit_info.csv").write_text(
            "rbb-r1.lab.local,eth1/1,FBOSS,port-channel1,"
            "rbb-r2.lab.local,eth1/1,FBOSS,port-channel1,3,\n"
            "rbb-r1.lab.local,eth1/2,FBOSS,,ixia,1/1,IXIA,,3,IXIA\n"
            "rbb-r2.lab.local,eth1/2,FBOSS,,ixia,1/2,IXIA,,3,IXIA\n",
            encoding="utf-8",
        )

    def _replace_dut_credentials(self, dut_credentials) -> None:
        secrets_path = self.config_dir / "secrets.json"
        secrets = json.loads(secrets_path.read_text(encoding="utf-8"))
        secrets["dut"] = dut_credentials
        secrets_path.write_text(json.dumps(secrets), encoding="utf-8")
        secrets_path.chmod(0o600)

    def test_init_creates_private_templates_without_overwriting(self) -> None:
        result = self._run_init()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            stat.S_IMODE(self.config_dir.stat().st_mode),
            0o700,
        )
        self.assertEqual(
            stat.S_IMODE((self.config_dir / "secrets.json").stat().st_mode),
            0o600,
        )
        for filename in (
            "rbb.env",
            "secrets.json",
            "device_info.csv",
            "circuit_info.csv",
        ):
            self.assertTrue((self.config_dir / filename).is_file())

        profile_path = self.config_dir / "rbb.env"
        profile_path.write_text("sentinel\n", encoding="utf-8")
        second_result = self._run_init()
        self.assertEqual(second_result.returncode, 0, second_result.stderr)
        self.assertEqual(profile_path.read_text(encoding="utf-8"), "sentinel\n")
        self.assertIn("Kept existing file", second_result.stdout)

    def test_init_refuses_unignored_repository_directory(self) -> None:
        result = subprocess.run(
            [
                str(self.runner),
                "--config-dir",
                str(self.repo_root),
                "--init",
            ],
            cwd=self.repo_root,
            env=self._clean_environment(),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("must be under .taac", result.stderr)

    def test_fresh_image_traffic_requires_edge_setup_flag(self) -> None:
        result = subprocess.run(
            [str(self.runner), "--setup-duts", "--with-traffic"],
            cwd=self.repo_root,
            env=self._clean_environment(),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("requires --setup-dut-edges", result.stderr)

    def test_check_accepts_device_path_without_ixia_credentials(self) -> None:
        self._write_valid_config(ixia_credentials=False)
        result = self._run_check()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Configuration check passed", result.stdout)
        self.assertIn("device path (no IXIA)", result.stdout)
        self.assertNotIn("dut-secret", result.stdout + result.stderr)

    def test_check_accepts_complete_traffic_configuration(self) -> None:
        self._write_valid_config()
        result = self._run_check(with_traffic=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("live IXIA traffic", result.stdout)
        self.assertNotIn("ixia-secret", result.stdout + result.stderr)

    def test_check_accepts_distinct_per_host_dut_credentials(self) -> None:
        self._write_valid_config()
        self._replace_dut_credentials(
            {
                "username": "",
                "password": "",
                "hosts": {
                    "rbb-r1.lab.local": {
                        "username": "r1-user",
                        "password": "r1-secret",
                    },
                    "rbb-r2.lab.local": {
                        "username": "r2-user",
                        "password": "r2-secret",
                    },
                },
            }
        )

        result = self._run_check(with_traffic=True)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("r1-secret", result.stdout + result.stderr)
        self.assertNotIn("r2-secret", result.stdout + result.stderr)

    def test_check_rejects_missing_effective_per_host_credential(self) -> None:
        self._write_valid_config(ixia_credentials=False)
        self._replace_dut_credentials(
            {
                "username": "",
                "password": "",
                "hosts": {
                    "rbb-r1.lab.local": {
                        "username": "r1-user",
                        "password": "r1-secret",
                    },
                    "rbb-r2.lab.local": {"username": "r2-user"},
                },
            }
        )

        result = self._run_check()

        self.assertEqual(result.returncode, 1)
        self.assertIn("password", result.stderr)
        self.assertIn("rbb-r2.lab.local", result.stderr)
        self.assertNotIn("r1-secret", result.stdout + result.stderr)

    def test_check_rejects_ixia_prefix_with_host_bits(self) -> None:
        self._write_valid_config()
        profile = self.config_dir / "rbb.env"
        profile.write_text(
            profile.read_text(encoding="utf-8").replace(
                "TAAC_RBB_IXIA_TAIL_PREFIX=2001:db8:beef::",
                "TAAC_RBB_IXIA_TAIL_PREFIX=2001:db8:beef::1",
            ),
            encoding="utf-8",
        )
        result = self._run_check(with_traffic=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("must be the network address", result.stderr)

    def test_check_rejects_steered_prefix_with_host_bits(self) -> None:
        self._write_valid_config()
        profile = self.config_dir / "rbb.env"
        profile.write_text(
            profile.read_text(encoding="utf-8").replace(
                "TAAC_RBB_TAIL_PREFIX=2001:db8:beef::/64",
                "TAAC_RBB_TAIL_PREFIX=2001:db8:beef::1/64",
            ),
            encoding="utf-8",
        )
        result = self._run_check(with_traffic=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("tail-prefix contract is not valid", result.stderr)

    def test_check_accepts_fresh_image_bootstrap_configuration(self) -> None:
        self._write_valid_config(ixia_credentials=False, dut_username="root")
        result = self._run_check(setup_duts=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("temporary DUT bootstrap", result.stdout)
        self.assertNotIn("dut-secret", result.stdout + result.stderr)

    def test_bootstrap_rejects_non_root_credential_before_device_contact(self) -> None:
        self._write_valid_config(ixia_credentials=False)
        result = self._run_check(setup_duts=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("requires dut.username 'root'", result.stderr)

    def test_bootstrap_accepts_distinct_root_credentials(self) -> None:
        self._write_valid_config(ixia_credentials=False)
        self._replace_dut_credentials(
            {
                "username": "",
                "password": "",
                "hosts": {
                    "rbb-r1.lab.local": {
                        "username": "root",
                        "password": "r1-secret",
                    },
                    "rbb-r2.lab.local": {
                        "username": "root",
                        "password": "r2-secret",
                    },
                },
            }
        )

        result = self._run_check(setup_duts=True)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("r1-secret", result.stdout + result.stderr)
        self.assertNotIn("r2-secret", result.stdout + result.stderr)

    def test_bootstrap_rejects_non_root_per_host_credential(self) -> None:
        self._write_valid_config(ixia_credentials=False)
        self._replace_dut_credentials(
            {
                "username": "root",
                "password": "shared-secret",
                "hosts": {
                    "rbb-r2.lab.local": {"username": "operator"},
                },
            }
        )

        result = self._run_check(setup_duts=True)

        self.assertEqual(result.returncode, 1)
        self.assertIn("requires dut.username 'root'", result.stderr)
        self.assertIn("rbb-r2.lab.local", result.stderr)
        self.assertNotIn("shared-secret", result.stdout + result.stderr)

    def test_edge_setup_rejects_non_root_credential_before_device_contact(self) -> None:
        self._write_valid_config()
        result = self._run_check(with_traffic=True, setup_dut_edges=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("--setup-dut-edges requires dut.username 'root'", result.stderr)

    def test_edge_setup_requires_traffic_mode(self) -> None:
        self._write_valid_config(ixia_credentials=False, dut_username="root")
        result = self._run_check(setup_dut_edges=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("--setup-dut-edges requires --with-traffic", result.stderr)

    def test_fresh_image_preflight_requires_edge_setup_for_traffic(self) -> None:
        self._write_valid_config(dut_username="root")
        result = self._run_check(with_traffic=True, setup_duts=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("fresh-image traffic requires --setup-dut-edges", result.stderr)

    def test_bootstrap_rejects_multi_member_lag_before_device_contact(self) -> None:
        self._write_valid_config(ixia_credentials=False, dut_username="root")
        with (self.config_dir / "circuit_info.csv").open(
            "a", encoding="utf-8"
        ) as circuits:
            circuits.write(
                "rbb-r1.lab.local,eth1/3,FBOSS,port-channel1,"
                "rbb-r2.lab.local,eth1/3,FBOSS,port-channel1,3,\n"
            )
        result = self._run_check(setup_duts=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("exactly one member", result.stderr)

    def test_bootstrap_rejects_shell_active_device_path(self) -> None:
        self._write_valid_config(ixia_credentials=False, dut_username="root")
        with (self.config_dir / "rbb.env").open("a", encoding="utf-8") as profile:
            profile.write("TAAC_RBB_AGENT_CONFIG_PATH=/etc/coop/agent.conf;reboot\n")
        result = self._run_check(setup_duts=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("canonical absolute paths", result.stderr)

    def test_edge_setup_rejects_shell_active_device_path(self) -> None:
        self._write_valid_config(dut_username="root")
        with (self.config_dir / "rbb.env").open("a", encoding="utf-8") as profile:
            profile.write("TAAC_RBB_BGP_CONFIG_PATH=/opt/bgpd/bgp.json;reboot\n")
        result = self._run_check(with_traffic=True, setup_dut_edges=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("canonical absolute paths", result.stderr)

    def test_check_rejects_missing_traffic_credentials(self) -> None:
        self._write_valid_config(ixia_credentials=False)
        result = self._run_check(with_traffic=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("TAAC_IXIA_PASSWORD", result.stderr)
        self.assertIn("TAAC_IXIA_USERNAME", result.stderr)
        self.assertNotIn("dut-secret", result.stdout + result.stderr)

    def test_check_rejects_unmodified_endpoint_placeholders(self) -> None:
        result = self._run_init()
        self.assertEqual(result.returncode, 0, result.stderr)
        secrets_path = self.config_dir / "secrets.json"
        secrets_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "dut": {"username": "dut-user", "password": "dut-secret"},
                    "ixia": {"username": "", "password": ""},
                }
            ),
            encoding="utf-8",
        )
        result = self._run_check()
        self.assertEqual(result.returncode, 1)
        self.assertIn("Replace the placeholder value", result.stderr)
        self.assertNotIn("dut-secret", result.stdout + result.stderr)

    def test_check_rejects_credentials_in_nonsecret_profile(self) -> None:
        self._write_valid_config()
        with (self.config_dir / "rbb.env").open("a", encoding="utf-8") as profile:
            profile.write("TAAC_SSH_PASSWORD=must-not-be-printed\n")
        result = self._run_check()
        self.assertEqual(result.returncode, 1)
        self.assertIn("must not contain credentials", result.stderr)
        self.assertNotIn("must-not-be-printed", result.stdout + result.stderr)


if __name__ == "__main__":
    import unittest

    unittest.main()
