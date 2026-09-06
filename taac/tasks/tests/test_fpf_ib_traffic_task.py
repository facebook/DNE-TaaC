# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

import posixpath
import subprocess
import unittest
from unittest.mock import AsyncMock, patch

from neteng.test_infra.dne.taac.tasks import fpf_ib_traffic_task as task_module
from taac.tasks.fpf_ib_traffic_task import (
    build_ib_binary_probe_cmd,
    build_ib_process_snapshot_cmd,
    build_ib_write_bw_cmd,
    DEFAULT_KEY_DESC,
    launch_validated_ib_process,
    parse_background_pid,
    parse_ib_process_snapshot,
    validate_ib_ods_egress,
    validate_ib_process_snapshot,
    validate_remote_ib_binary,
    validate_remote_ib_process,
)


class FpfIbTrafficProcessValidationTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.expected_cmd = build_ib_write_bw_cmd(
            device="mlx5_bveth0",
            gid_index=3,
            port=15000,
            msg_size=4096,
            qp=4,
            tclass=224,
            iters=1000,
        )
        self.valid_row = (
            f"PID=12345\tCMD={self.expected_cmd} "
            "\tCGROUP=0::/system.slice/sshd.service;"
        )

    def test_snapshot_command_has_no_duplicate_zero_fallback(self) -> None:
        command = build_ib_process_snapshot_cmd()

        self.assertIn("/proc/[0-9]*", command)
        self.assertIn('[ "$first" = /usr/bin/ib_write_bw ]', command)
        self.assertNotIn("|| echo 0", command)
        self.assertIn("$proc/cmdline", command)
        self.assertIn("$proc/cgroup", command)

    def test_custom_binary_is_used_by_command_and_process_inventory(self) -> None:
        binary_path = "/root/ib_write_bw"
        command = build_ib_write_bw_cmd(
            device="mlx5_bveth0",
            gid_index=3,
            binary_path=binary_path,
        )

        self.assertTrue(command.startswith(f"{binary_path} "))
        self.assertIn(
            f'[ "$first" = {binary_path} ]', build_ib_process_snapshot_cmd(binary_path)
        )

    def test_binary_path_must_be_absolute(self) -> None:
        with self.assertRaisesRegex(ValueError, "absolute path"):
            build_ib_write_bw_cmd(binary_path="tmp/fpf_ib_write_bw")

    def test_binary_path_rejects_world_writable_staging_roots(self) -> None:
        for binary_path in (
            "/tmp/fpf_ib_write_bw",
            "/var/tmp/fpf_ib_write_bw",
            posixpath.join("/dev", "shm", "fpf_ib_write_bw"),
        ):
            with self.subTest(binary_path=binary_path):
                with self.assertRaisesRegex(ValueError, "not trusted"):
                    build_ib_write_bw_cmd(binary_path=binary_path)

    def test_binary_path_rejects_noncanonical_alias(self) -> None:
        with self.assertRaisesRegex(ValueError, "canonical"):
            build_ib_write_bw_cmd(binary_path="/root/../tmp/fpf_ib_write_bw")

    def test_binary_probe_checks_exists_regular_and_executable(self) -> None:
        command = build_ib_binary_probe_cmd("/root/ib_write_bw")

        self.assertIn("[ ! -e /root/ib_write_bw ]", command)
        self.assertIn("[ ! -f /root/ib_write_bw ]", command)
        self.assertIn("[ ! -x /root/ib_write_bw ]", command)
        self.assertIn("stat -Lc '%u %a'", command)
        self.assertIn("NOT_ROOT_OWNED", command)
        self.assertIn("GROUP_OR_WORLD_WRITABLE", command)
        self.assertIn("$((0$mode & 022))", command)

    def test_binary_probe_mode_check_accepts_root_owned_0755(self) -> None:
        result = subprocess.run(
            [
                "/bin/sh",
                "-c",
                "candidate=/root/ib_write_bw; mode=0755; "
                + task_module._build_ib_mode_validation_cmd()
                + 'printf "OK\\n"',
            ],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "OK\n")

    def test_binary_probe_mode_check_rejects_group_or_world_write(self) -> None:
        for mode in ("0775", "0757"):
            with self.subTest(mode=mode):
                result = subprocess.run(
                    [
                        "/bin/sh",
                        "-c",
                        f"candidate=/root/ib_write_bw; mode={mode}; "
                        + task_module._build_ib_mode_validation_cmd()
                        + 'printf "UNREACHABLE\\n"',
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                )

                self.assertEqual(result.returncode, 7)
                self.assertEqual(
                    result.stdout,
                    f"GROUP_OR_WORLD_WRITABLE:/root/ib_write_bw:{mode}\n",
                )

    def test_exact_process_preserves_pid_cmdline_and_cgroup(self) -> None:
        process = validate_ib_process_snapshot(
            self.valid_row,
            host="server.mwg2",
            role="server",
            expected_cmd=self.expected_cmd,
        )

        self.assertEqual(process.pid, 12345)
        self.assertEqual(process.cmdline, self.expected_cmd)
        self.assertEqual(process.cgroup, "0::/system.slice/sshd.service;")

    def test_zero_processes_fail(self) -> None:
        with self.assertRaisesRegex(ValueError, "found 0"):
            validate_ib_process_snapshot(
                "",
                host="server.mwg2",
                role="server",
                expected_cmd=self.expected_cmd,
            )

    def test_legacy_duplicate_zero_output_is_malformed(self) -> None:
        with self.assertRaisesRegex(ValueError, "malformed"):
            parse_ib_process_snapshot("0\n0\n")

    def test_malformed_process_output_fails(self) -> None:
        with self.assertRaisesRegex(ValueError, "malformed"):
            parse_ib_process_snapshot("PID=123 CMD=missing-tabs")

    def test_wrong_device_or_client_peer_fails(self) -> None:
        wrong_cmd = build_ib_write_bw_cmd(
            device="mlx5_34",
            gid_index=3,
            port=15000,
            msg_size=4096,
            qp=4,
            tclass=224,
            iters=1000,
            server="wrong-server.mwg2",
        )
        wrong_row = (
            f"PID=12345\tCMD={wrong_cmd} \tCGROUP=0::/system.slice/sshd.service;"
        )

        with self.assertRaisesRegex(ValueError, "command mismatch"):
            validate_ib_process_snapshot(
                wrong_row,
                host="client.mwg2",
                role="client",
                expected_cmd=build_ib_write_bw_cmd(
                    device="mlx5_bveth0",
                    gid_index=3,
                    port=15000,
                    msg_size=4096,
                    qp=4,
                    tclass=224,
                    iters=1000,
                    server="server.mwg2",
                ),
            )

    def test_background_pid_must_be_one_integer(self) -> None:
        self.assertEqual(
            parse_background_pid("12345\n", host="server.mwg2", role="server"),
            12345,
        )
        for output in ("", "12345\nextra\n", "not-a-pid\n"):
            with self.subTest(output=output):
                with self.assertRaisesRegex(ValueError, "malformed"):
                    parse_background_pid(output, host="server.mwg2", role="server")

    async def test_immediate_exit_between_validation_samples_fails(self) -> None:
        ssh_run = AsyncMock(
            side_effect=[
                (0, self.valid_row, ""),
                (0, "", ""),
            ]
        )

        with self.assertRaisesRegex(RuntimeError, "found 0"):
            await validate_remote_ib_process(
                host="server.mwg2",
                role="server",
                expected_cmd=self.expected_cmd,
                ssh_run=ssh_run,
                attempts=2,
                interval_sec=0,
            )

    async def test_process_inventory_ssh_error_fails(self) -> None:
        ssh_run = AsyncMock(return_value=(255, "", "permission denied"))

        with self.assertRaisesRegex(RuntimeError, "SSH failed"):
            await validate_remote_ib_process(
                host="server.mwg2",
                role="server",
                expected_cmd=self.expected_cmd,
                ssh_run=ssh_run,
                attempts=1,
            )

    async def test_missing_remote_binary_fails(self) -> None:
        ssh_run = AsyncMock(return_value=(2, "MISSING\n", ""))

        with self.assertRaisesRegex(RuntimeError, "MISSING"):
            await validate_remote_ib_binary(
                host="server.mwg2",
                binary_path="/root/ib_write_bw",
                ssh_run=ssh_run,
            )

    async def test_non_executable_remote_binary_fails(self) -> None:
        ssh_run = AsyncMock(return_value=(4, "NOT_EXECUTABLE\n", ""))

        with self.assertRaisesRegex(RuntimeError, "NOT_EXECUTABLE"):
            await validate_remote_ib_binary(
                host="server.mwg2",
                binary_path="/root/ib_write_bw",
                ssh_run=ssh_run,
            )

    async def test_non_regular_remote_binary_fails(self) -> None:
        ssh_run = AsyncMock(return_value=(3, "NOT_REGULAR\n", ""))

        with self.assertRaisesRegex(RuntimeError, "NOT_REGULAR"):
            await validate_remote_ib_binary(
                host="server.mwg2",
                binary_path="/root/ib_write_bw",
                ssh_run=ssh_run,
            )

    async def test_remote_binary_validation_passes_only_on_exact_ok(self) -> None:
        ssh_run = AsyncMock(return_value=(0, "OK\n", ""))

        await validate_remote_ib_binary(
            host="server.mwg2",
            binary_path="/root/ib_write_bw",
            ssh_run=ssh_run,
        )

    async def test_launch_revalidates_binary_immediately_before_execution(self) -> None:
        launch_cmd = "setsid nohup /root/ib_write_bw --run_infinitely & echo $!"
        ssh_run = AsyncMock(
            side_effect=[
                (0, "OK\n", ""),
                (0, "12345\n", ""),
            ]
        )

        result = await launch_validated_ib_process(
            host="server.mwg2",
            binary_path="/root/ib_write_bw",
            launch_cmd=launch_cmd,
            ssh_run=ssh_run,
        )

        self.assertEqual(result, (0, "12345\n", ""))
        self.assertEqual(ssh_run.await_count, 2)
        self.assertIn("stat -Lc '%u %a'", ssh_run.await_args_list[0].args[1])
        self.assertEqual(ssh_run.await_args_list[1].args[1], launch_cmd)

    async def test_exact_process_survives_bounded_validation(self) -> None:
        ssh_run = AsyncMock(return_value=(0, self.valid_row, ""))

        with patch("asyncio.sleep", new=AsyncMock()) as sleep:
            snapshots = await validate_remote_ib_process(
                host="server.mwg2",
                role="server",
                expected_cmd=self.expected_cmd,
                ssh_run=ssh_run,
                attempts=2,
                interval_sec=1,
            )

        self.assertEqual([snapshot.pid for snapshot in snapshots], [12345, 12345])
        sleep.assert_awaited_once_with(1)

    async def test_custom_binary_drives_exact_process_inventory(self) -> None:
        expected_cmd = build_ib_write_bw_cmd(
            device="mlx5_bveth0",
            gid_index=3,
            binary_path="/root/ib_write_bw",
        )
        ssh_run = AsyncMock(
            return_value=(
                0,
                f"PID=12345\tCMD={expected_cmd} "
                "\tCGROUP=0::/system.slice/sshd.service;",
                "",
            )
        )

        await validate_remote_ib_process(
            host="server.mwg2",
            role="server",
            expected_cmd=expected_cmd,
            ssh_run=ssh_run,
            attempts=1,
        )

        await_args = ssh_run.await_args
        assert await_args is not None
        inventory_cmd = await_args.args[1]
        self.assertIn('[ "$first" = /root/ib_write_bw ]', inventory_cmd)

    async def test_ods_no_data_fails_closed(self) -> None:
        with (
            patch.object(
                task_module, "async_query_ods", new=AsyncMock(return_value={})
            ),
            patch.object(
                task_module,
                "async_generate_ods_url",
                new=AsyncMock(return_value="https://ods.example/query"),
            ),
            patch.object(
                task_module,
                "async_get_fburl",
                new=AsyncMock(return_value="https://fburl.com/traffic"),
            ),
            patch.object(task_module, "register_artifact"),
        ):
            with self.assertRaisesRegex(RuntimeError, "no ODS egress data"):
                await validate_ib_ods_egress(hosts=["server.mwg2", "client.mwg2"])

    async def test_ods_requires_every_host_and_returns_evidence(self) -> None:
        data = {
            "HOSTNAME::server.mwg2:sum": {DEFAULT_KEY_DESC: {100: 80.0}},
            "HOSTNAME::client.mwg2:sum": {DEFAULT_KEY_DESC: {100: 81.0}},
        }
        with (
            patch.object(
                task_module, "async_query_ods", new=AsyncMock(return_value=data)
            ),
            patch.object(
                task_module,
                "async_generate_ods_url",
                new=AsyncMock(return_value="https://ods.example/query"),
            ),
            patch.object(
                task_module,
                "async_get_fburl",
                new=AsyncMock(return_value="https://fburl.com/traffic"),
            ),
            patch.object(task_module, "register_artifact") as register,
        ):
            details, url = await validate_ib_ods_egress(
                hosts=["server.mwg2", "client.mwg2"], artifact_label="recovery"
            )

        self.assertEqual(
            details, ["server.mwg2: 80.00 Gbps", "client.mwg2: 81.00 Gbps"]
        )
        self.assertEqual(url, "https://fburl.com/traffic")
        register.assert_called_once_with("ods", "recovery", "https://fburl.com/traffic")


if __name__ == "__main__":
    unittest.main()
