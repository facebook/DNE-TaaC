#!/usr/bin/env python3
# pyre-unsafe

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from taac.runner.cli_parser import create_argument_parser
from taac.runner.oss_exceptions import OSSConfigError
from taac.runner.oss_secrets import get_oss_dut_credentials, load_oss_secrets
from taac.utils.oss_driver_utils import AsyncSSHClient, ParamikoClient


_CREDENTIAL_ENV_NAMES = {
    "TAAC_SSH_USER",
    "TAAC_SSH_PASSWORD",
    "TAAC_IXIA_USERNAME",
    "TAAC_IXIA_PASSWORD",
}


class TestOSSSecrets(TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "taac.secrets.json"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write(self, data, mode: int = 0o600) -> None:
        self.path.write_text(json.dumps(data), encoding="utf-8")
        self.path.chmod(mode)

    @staticmethod
    def _document():
        return {
            "version": 1,
            "dut": {"username": "dut-user", "password": "dut-secret"},
            "ixia": {"username": "ixia-user", "password": "ixia-secret"},
        }

    def test_cli_accepts_secrets_file(self) -> None:
        args = create_argument_parser().parse_args(
            [
                "--test-configs",
                "test.py",
                "--secrets-file",
                "secrets.json",
                "--dut",
                "dut1",
            ]
        )
        self.assertEqual(args.secrets_file, "secrets.json")

    def test_loads_all_supported_credentials(self) -> None:
        self._write(self._document())
        clean_env = {
            key: value
            for key, value in os.environ.items()
            if key not in _CREDENTIAL_ENV_NAMES
        }

        with patch.dict(os.environ, clean_env, clear=True):
            loaded = load_oss_secrets(str(self.path))

            self.assertEqual(loaded, _CREDENTIAL_ENV_NAMES)
            self.assertEqual(os.environ["TAAC_SSH_USER"], "dut-user")
            self.assertEqual(os.environ["TAAC_SSH_PASSWORD"], "dut-secret")
            self.assertEqual(os.environ["TAAC_IXIA_USERNAME"], "ixia-user")
            self.assertEqual(os.environ["TAAC_IXIA_PASSWORD"], "ixia-secret")
            self.assertEqual(
                get_oss_dut_credentials("unlisted-dut"),
                ("dut-user", "dut-secret"),
            )

    def test_hostname_credentials_override_and_inherit_shared_values(self) -> None:
        document = self._document()
        document["dut"]["hosts"] = {
            "RBB-R1.LAB.LOCAL.": {
                "username": "r1-user",
                "password": "r1-secret",
            },
            "rbb-r2.lab.local": {"password": "r2-secret"},
        }
        self._write(document)

        with patch.dict(os.environ, {}, clear=True):
            load_oss_secrets(str(self.path))

            self.assertEqual(
                get_oss_dut_credentials("rbb-r1.lab.local"),
                ("r1-user", "r1-secret"),
            )
            self.assertEqual(
                get_oss_dut_credentials("RBB-R2.LAB.LOCAL."),
                ("dut-user", "r2-secret"),
            )
            self.assertEqual(
                get_oss_dut_credentials("rbb-r3.lab.local"),
                ("dut-user", "dut-secret"),
            )

    def test_ssh_clients_select_credentials_by_destination_hostname(self) -> None:
        document = self._document()
        document["dut"]["hosts"] = {
            "rbb-r1.lab.local": {
                "username": "r1-user",
                "password": "r1-secret",
            },
            "rbb-r2.lab.local": {
                "username": "r2-user",
                "password": "r2-secret",
            },
        }
        self._write(document)

        with patch.dict(os.environ, {}, clear=True):
            load_oss_secrets(str(self.path))
            async_client = AsyncSSHClient("rbb-r1.lab.local")
            paramiko_client = ParamikoClient("rbb-r2.lab.local")

            self.assertEqual(async_client._username, "r1-user")
            self.assertEqual(async_client._password, "r1-secret")
            self.assertEqual(paramiko_client._username, "r2-user")
            self.assertEqual(paramiko_client._password, "r2-secret")

    def test_hostname_credentials_are_available_in_a_fresh_worker(self) -> None:
        document = self._document()
        document["dut"]["hosts"] = {
            "rbb-r1.lab.local": {
                "username": "r1-user",
                "password": "r1-secret",
            }
        }
        self._write(document)

        with patch.dict(os.environ, {}, clear=True):
            load_oss_secrets(str(self.path))
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "from taac.runner.oss_secrets import "
                    "get_oss_dut_credentials; import sys; "
                    "sys.exit(get_oss_dut_credentials('rbb-r1.lab.local') "
                    "!= ('r1-user', 'r1-secret'))",
                ],
                env=os.environ.copy(),
                check=False,
            )

        self.assertEqual(result.returncode, 0)

    def test_explicit_environment_has_precedence(self) -> None:
        document = self._document()
        document["dut"]["hosts"] = {
            "rbb-r1.lab.local": {
                "username": "host-user",
                "password": "host-secret",
            }
        }
        self._write(document)

        with patch.dict(
            os.environ,
            {
                "TAAC_SSH_USER": "one-run-user",
                "TAAC_SSH_PASSWORD": "one-run-secret",
            },
            clear=True,
        ):
            load_oss_secrets(str(self.path))
            self.assertEqual(os.environ["TAAC_SSH_USER"], "one-run-user")
            self.assertEqual(
                get_oss_dut_credentials("rbb-r1.lab.local"),
                ("one-run-user", "one-run-secret"),
            )

    def test_empty_template_values_are_ignored(self) -> None:
        self._write(
            {
                "version": 1,
                "dut": {"username": "", "password": ""},
                "ixia": {"username": "", "password": ""},
            }
        )

        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(load_oss_secrets(str(self.path)), set())
            self.assertFalse(_CREDENTIAL_ENV_NAMES & set(os.environ))

    def test_rejects_group_or_world_permissions(self) -> None:
        self._write(self._document(), mode=0o640)

        with self.assertRaisesRegex(OSSConfigError, "chmod 600"):
            load_oss_secrets(str(self.path))

    def test_rejects_unknown_fields_without_exposing_values(self) -> None:
        document = self._document()
        document["ixia"]["token"] = "must-not-appear-in-error"
        self._write(document)

        with self.assertRaises(OSSConfigError) as context:
            load_oss_secrets(str(self.path))

        self.assertIn("unsupported", str(context.exception))
        self.assertNotIn("token", str(context.exception))
        self.assertNotIn("must-not-appear-in-error", str(context.exception))

    def test_rejects_unknown_host_fields_without_exposing_values(self) -> None:
        document = self._document()
        document["dut"]["hosts"] = {
            "rbb-r1.lab.local": {"token": "must-not-appear-in-error"}
        }
        self._write(document)

        with self.assertRaises(OSSConfigError) as context:
            load_oss_secrets(str(self.path))

        self.assertIn("unsupported", str(context.exception))
        self.assertNotIn("token", str(context.exception))
        self.assertNotIn("must-not-appear-in-error", str(context.exception))

    def test_rejects_non_object_host_credentials(self) -> None:
        document = self._document()
        document["dut"]["hosts"] = {"rbb-r1.lab.local": "must-not-appear"}
        self._write(document)

        with self.assertRaises(OSSConfigError) as context:
            load_oss_secrets(str(self.path))

        self.assertIn("non-object", str(context.exception))
        self.assertNotIn("must-not-appear", str(context.exception))

    def test_rejects_duplicate_normalized_hostnames(self) -> None:
        document = self._document()
        document["dut"]["hosts"] = {
            "rbb-r1.lab.local": {"username": "first"},
            "RBB-R1.LAB.LOCAL.": {"username": "second"},
        }
        self._write(document)

        with self.assertRaisesRegex(OSSConfigError, "duplicate normalized"):
            load_oss_secrets(str(self.path))

    def test_rejects_duplicate_json_keys(self) -> None:
        self.path.write_text(
            '{"version": 1, "dut": {"username": "first", "username": "second"}}',
            encoding="utf-8",
        )
        self.path.chmod(0o600)

        with self.assertRaisesRegex(OSSConfigError, "not valid JSON"):
            load_oss_secrets(str(self.path))

    def test_rejects_nul_without_exposing_the_secret(self) -> None:
        document = self._document()
        document["dut"]["password"] = "must-not-appear\x00suffix"
        self._write(document)

        with self.assertRaises(OSSConfigError) as context:
            load_oss_secrets(str(self.path))

        self.assertIn("NUL", str(context.exception))
        self.assertNotIn("must-not-appear", str(context.exception))
