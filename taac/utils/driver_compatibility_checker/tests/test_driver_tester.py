# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import later.unittest
from neteng.models.network_topology.types import Role
from taac.utils.driver_compatibility_checker.driver_tester import (
    _create_coop_snapshot,
    _first_neighbor_role,
    _recover_without_masking,
    _restore_coop_snapshot,
    build_probe_matrix,
    CURATED_PROBES,
    execute_probe,
    ProbeSpec,
    public_driver_api,
    RawArtifact,
    RecoveryFailed,
    run_probe_specs,
    RunContext,
    serialize,
    UncallableProbe,
    validate_probe_coverage,
    write_summaries,
)


class FakeDriver:
    def __init__(self) -> None:
        self.mutating_calls = 0

    async def succeeds(self) -> dict[str, bool]:
        return {"ok": True}

    async def fails(self) -> None:
        raise RuntimeError("contained failure")

    async def async_mutate_without_recovery(self) -> None:
        self.mutating_calls += 1

    async def crash_fails(self, service: object) -> None:
        raise RuntimeError("primary probe failure")

    async def crash_succeeds(self, service: object) -> None:
        return None

    async def async_restart_service(self, service: object) -> None:
        raise RuntimeError("recovery failure")

    async def async_wait_for_bgp_convergence(self) -> None:
        return None

    async def async_disable_agent(self, agent_name: str) -> None:
        return None

    async def enable_agent(self, agent_name: str) -> None:
        raise RuntimeError("automatic recovery failure")


class FailingAutoProbeDriver(FakeDriver):
    async def async_disable_agent(self, agent_name: str) -> None:
        raise RuntimeError("automatic primary failure")


class UncallableAutoProbeDriver(FakeDriver):
    def __init__(self) -> None:
        super().__init__()
        self.recovery_calls = 0

    async def async_disable_agent(self, agent_name: str) -> None:
        raise UncallableProbe("mutation was not applied")

    async def enable_agent(self, agent_name: str) -> None:
        self.recovery_calls += 1


class FailingPatcherCleanupDriver(FakeDriver):
    async def async_register_patcher_to_shut_ports_persistently(
        self, patcher_name: str, interfaces: list[str]
    ) -> None:
        return None

    async def async_coop_unregister_patchers(
        self, patcher_name: str, config_name: str
    ) -> None:
        raise RuntimeError("patcher cleanup failed")


class FbossDriverCompatibilityCheckerTest(later.unittest.TestCase):
    async def test_neighbor_role_falls_back_when_device_has_no_lldp_peers(
        self,
    ) -> None:
        driver = SimpleNamespace(async_get_lldp_neighbors=AsyncMock(return_value={}))

        self.assertEqual(Role.FSW, await _first_neighbor_role(driver))

    async def test_cleanup_failure_chains_primary_exception(self) -> None:
        primary_error = RuntimeError("primary probe failure")
        cleanup_error = RuntimeError("recovery failure")

        async def cleanup() -> None:
            raise cleanup_error

        with self.assertRaises(RecoveryFailed) as raised:
            async with _recover_without_masking(cleanup, "test cleanup"):
                raise primary_error

        self.assertIs(raised.exception.__cause__, primary_error)
        self.assertIs(raised.exception.cleanup_error, cleanup_error)

    async def test_cleanup_failure_preserves_cancellation(self) -> None:
        cleanup = AsyncMock(side_effect=RuntimeError("recovery failure"))

        async def cancel_during_probe() -> None:
            async with _recover_without_masking(cleanup, "test cleanup"):
                raise asyncio.CancelledError()

        with self.assertRaises(asyncio.CancelledError):
            await cancel_during_probe()
        cleanup.assert_awaited_once_with()

    async def test_coop_snapshot_is_verified_before_reset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            driver = SimpleNamespace(async_run_cmd_on_shell=AsyncMock())
            context = RunContext("device", "eth1/1/1", "peer", "run", Path(directory))

            snapshot = await _create_coop_snapshot(driver, context)

            command = driver.async_run_cmd_on_shell.await_args.args[0]
            self.assertIn("git bundle verify", command)
            self.assertIn(snapshot, command)

    async def test_coop_restore_clones_and_validates_before_swap(self) -> None:
        driver = SimpleNamespace(
            async_get_systemctl_service_name=AsyncMock(
                return_value="netos.service.fboss_coop"
            ),
            async_run_cmd_on_shell=AsyncMock(
                side_effect=["/run/netos/coop-export\n", ""]
            ),
            async_agent_config_reload=AsyncMock(),
            async_wait_for_agent_state_configured=AsyncMock(),
            async_wait_for_bgp_convergence=AsyncMock(),
        )

        await _restore_coop_snapshot(driver, "/tmp/driver-tester/coop.bundle")

        command = driver.async_run_cmd_on_shell.await_args_list[1].args[0]
        self.assertIn("systemd-run --wait --collect --service-type=exec", command)
        self.assertIn("/bin/bash -c", command)
        self.assertEqual(
            driver.async_run_cmd_on_shell.await_args_list[1].kwargs["timeout"], 600
        )
        self.assertLess(command.index("git clone"), command.index("systemctl stop"))
        self.assertLess(
            command.index("test -s"), command.index("mv /run/netos/coop-export")
        )
        self.assertLess(
            command.index("trap restore_on_error ERR"),
            command.index("systemctl stop"),
        )
        self.assertIn("if test -d", command)
        self.assertIn("systemctl start netos.service.fboss_coop", command)
        self.assertNotIn("wedge_agent", command)
        self.assertNotIn("systemctl start bgpd", command)
        self.assertLess(
            command.rindex("trap - ERR"),
            command.rindex("rm -rf"),
        )
        driver.async_agent_config_reload.assert_awaited_once_with()
        driver.async_wait_for_agent_state_configured.assert_awaited_once_with()
        driver.async_wait_for_bgp_convergence.assert_awaited_once_with()

    def test_raw_artifact_ranges_are_exact_and_append_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "raw.log"
            artifact = RawArtifact(path)
            first = artifact.append("one", {"result": "alpha\nbeta"})
            second = artifact.append("two", {"result": 2})
            lines = path.read_text(encoding="utf-8").splitlines()

            self.assertEqual(first[0], 1)
            self.assertEqual(lines[first[0] - 1], "===== BEGIN one =====")
            self.assertEqual(lines[first[1] - 1], "===== END one =====")
            self.assertEqual(second[0], first[1] + 1)
            self.assertEqual(lines[second[1] - 1], "===== END two =====")

    async def test_exception_isolation_continues_to_next_probe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            context = RunContext("device", "eth1/1/1", "peer", "run", path)
            results = await run_probe_specs(
                FakeDriver(),
                context,
                RawArtifact(path / "raw.log"),
                (
                    ProbeSpec("fails", "test"),
                    ProbeSpec("succeeds", "test"),
                ),
            )

            self.assertEqual([result.status for result in results], ["FAIL", "PASS"])
            self.assertIn("contained failure", results[0].error)

    async def test_generated_mutation_without_recovery_is_not_invoked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            driver = FakeDriver()
            result = await execute_probe(
                driver,
                RunContext("device", "eth1/1/1", "peer", "run", path),
                ProbeSpec(
                    "async_mutate_without_recovery",
                    "test",
                    handler="auto",
                ),
                RawArtifact(path / "raw.log"),
            )

            self.assertEqual(result.status, "SKIPPED_UNCALLABLE")
            self.assertEqual(driver.mutating_calls, 0)

    async def test_cleanup_failure_does_not_mask_primary_probe_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            result = await execute_probe(
                FakeDriver(),
                RunContext("device", "eth1/1/1", "peer", "run", path),
                ProbeSpec("crash_fails", "system", handler="crash_bgp"),
                RawArtifact(path / "raw.log"),
            )

            self.assertEqual(result.status, "FAIL")
            self.assertIn("primary probe failure", result.error)
            self.assertIn("recovery failure", result.error)

    async def test_cleanup_failure_fails_successful_probe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            result = await execute_probe(
                FakeDriver(),
                RunContext("device", "eth1/1/1", "peer", "run", path),
                ProbeSpec("crash_succeeds", "system", handler="crash_bgp"),
                RawArtifact(path / "raw.log"),
            )

            self.assertEqual(result.status, "RECOVERY_FAILED")
            self.assertIn("recovery failure", result.error)

    async def test_auto_cleanup_failure_fails_successful_probe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            result = await execute_probe(
                FakeDriver(),
                RunContext("device", "eth1/1/1", "peer", "run", path),
                ProbeSpec("async_disable_agent", "agent", handler="auto"),
                RawArtifact(path / "raw.log"),
            )

            self.assertEqual(result.status, "RECOVERY_FAILED")
            self.assertIn("automatic recovery failure", result.error)

    async def test_curated_patcher_cleanup_failure_is_not_reported_as_pass(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            result = await execute_probe(
                FailingPatcherCleanupDriver(),
                RunContext("device", "eth1/1/1", "peer", "run", path),
                ProbeSpec(
                    "async_register_patcher_to_shut_ports_persistently",
                    "coop",
                    handler="persistent_port_shutdown",
                ),
                RawArtifact(path / "raw.log"),
            )

            self.assertEqual(result.status, "RECOVERY_FAILED")
            self.assertIn("patcher cleanup failed", result.error)

    async def test_auto_recovery_is_skipped_when_probe_is_uncallable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            driver = UncallableAutoProbeDriver()
            result = await execute_probe(
                driver,
                RunContext("device", "eth1/1/1", "peer", "run", path),
                ProbeSpec("async_disable_agent", "agent", handler="auto"),
                RawArtifact(path / "raw.log"),
            )

            self.assertEqual(result.status, "SKIPPED_UNCALLABLE")
            self.assertEqual(driver.recovery_calls, 0)

    async def test_auto_cleanup_failure_retains_primary_probe_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            result = await execute_probe(
                FailingAutoProbeDriver(),
                RunContext("device", "eth1/1/1", "peer", "run", path),
                ProbeSpec("async_disable_agent", "agent", handler="auto"),
                RawArtifact(path / "raw.log"),
            )

            self.assertEqual(result.status, "FAIL")
            self.assertIn("automatic primary failure", result.error)
            self.assertIn("automatic recovery failure", result.error)

    def test_matrix_covers_complete_inherited_driver_surface(self) -> None:
        specs = build_probe_matrix()
        validate_probe_coverage(specs)
        self.assertEqual({spec.method_name for spec in specs}, public_driver_api())
        self.assertGreater(len(specs), len(CURATED_PROBES))

    def test_curated_probe_overrides_generated_probe(self) -> None:
        specs = {spec.method_name: spec for spec in build_probe_matrix()}
        self.assertEqual(specs["async_get_qsfp_client"].handler, "qsfp_client")
        self.assertEqual(specs["async_get_all_interfaces"].handler, "auto")
        self.assertEqual(specs["async_coop_generate_configs"].args, (False,))
        self.assertEqual(specs["async_agent_config_reload"].handler, "default")
        self.assertEqual(
            specs["async_agent_config_reload"].timeout_seconds,
            180,
        )

    async def test_serialization_and_all_summary_formats(self) -> None:
        self.assertEqual(serialize({2: {"b", "a"}}), {"2": ["a", "b"]})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            driver = FakeDriver()
            context = RunContext("device", "eth1/1/1", "peer", "run", path)
            artifact = RawArtifact(path / "raw.log")
            result = await execute_probe(
                driver, context, ProbeSpec("succeeds", "test"), artifact
            )
            write_summaries([result], path)
            for filename in ("summary.csv", "summary.json", "summary.md"):
                self.assertTrue((path / filename).read_text(encoding="utf-8"))
