# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-ignore-all-errors
#
# Broad suppression justified: this file installs a `sys.modules` stub for
# `neteng.test_infra.dne.taac.test_configs` at import time (line ~16) so the
# orchestrator can be constructed without pulling in every TestConfig factory
# in the tree. The stub returns `ModuleType` rather than the concrete module
# type, and the extensive mock injections (`SimpleNamespace`, `MagicMock`,
# `AsyncMock`) into orchestrator/runner attributes are structurally
# compatible but nominally not. Targeted `
# ~40 markers without meaningful safety gain.

import logging
import os
import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from taac.libs.ixia_candidate import (
    normalize_ixia_candidates,
    select_ixia_candidates,
)

TAAC_OSS = os.environ.get("TAAC_OSS", "").lower() in ("1", "true", "yes")

_TEST_CONFIGS_MODULE = "neteng.test_infra.dne.taac.test_configs"
_test_configs = types.ModuleType(_TEST_CONFIGS_MODULE)
_test_configs.get_test_config = lambda config: config
sys.modules[_TEST_CONFIGS_MODULE] = _test_configs

from taac.libs import (
    test_setup_orchestrator as _test_setup_orchestrator,
    traffic_generator as _traffic_generator,
)
from taac.libs.taac_runner import (
    _start_test_case_time_window,
    TaacRunner,
)
from taac.libs.test_setup_orchestrator import (
    TestSetupOrchestrator,
)
from taac.libs.traffic_generator import TrafficGenerator
from taac.utils.oss_taac_constants import (
    IxiaChassisUnavailableError,
    IxiaFallbackExhaustedError,
    IxiaPortUnavailableError,
)
from taac.test_as_a_config import types as taac_types


# ShipIt rewrites import statements (neteng.test_infra.dne.taac. -> taac.) but
# not string literals, so a hardcoded dotted path would only be correct in one
# of the two worlds. These two modules are same-layer imports this file already
# holds, so read the name straight off the imported module — that is guaranteed
# to be the module patch() must target.
_MODULE = _test_setup_orchestrator.__name__
_TRAFFIC_GENERATOR_MODULE = _traffic_generator.__name__

# Selected by env rather than imported: internal/ is stripped by ShipIt, so an
# import statement here would both break OSS and add a libs -> internal BUCK
# edge that the OSS layering rules disallow.
_INTERNAL_UTILS_MODULE = (
    "taac.internal.internal_utils"
    if TAAC_OSS
    else "neteng.test_infra.dne.taac.internal.internal_utils"
)

if TAAC_OSS:
    # Register a stub under the name test_setup_orchestrator's lazy import
    # resolves to after export, so the internal teardown path stays patchable.
    _internal_pkg = types.ModuleType("taac.internal")
    _internal_utils_stub = types.ModuleType(_INTERNAL_UTILS_MODULE)
    _internal_utils_stub.async_release_devices_in_basset = None
    sys.modules.setdefault("taac.internal", _internal_pkg)
    sys.modules.setdefault(_INTERNAL_UTILS_MODULE, _internal_utils_stub)


def _endpoint(interface: str, ixia_port: str) -> taac_types.Endpoint:
    return taac_types.Endpoint(
        name="dut1",
        dut=True,
        direct_ixia_connections=[
            taac_types.DirectIxiaConnection(
                interface=interface,
                ixia_port=ixia_port,
                ixia_chassis_ip="192.0.2.10",
            )
        ],
    )


def _config(
    secondary_endpoint: taac_types.Endpoint | None = None,
    primary_setup_tasks=None,
    primary_teardown_tasks=None,
    secondary_setup_tasks=None,
    secondary_teardown_tasks=None,
) -> taac_types.TestConfig:
    secondary_profile = None
    if secondary_endpoint is not None:
        secondary_profile = taac_types.IxiaSetupProfile(
            name="secondary",
            api_server_ip="192.0.2.20",
            endpoints=[secondary_endpoint],
            setup_tasks=secondary_setup_tasks or [],
            teardown_tasks=secondary_teardown_tasks or [],
        )
    return taac_types.TestConfig(
        name="IXIA_FALLBACK_UNIT_TEST",
        basset_pool="",
        playbooks=[],
        endpoints=[_endpoint("eth1/1/1", "1/1")],
        setup_tasks=primary_setup_tasks,
        teardown_tasks=primary_teardown_tasks,
        secondary_ixia_profile=secondary_profile,
    )


class TaacRunnerTimeWindowTest(unittest.TestCase):
    def test_start_clears_previous_playbook_end_time(self) -> None:
        jq_vars = {
            "test_case_start_time": 100,
            "test_case_end_time": 150,
            "unrelated": "preserved",
        }

        _start_test_case_time_window(jq_vars, 200)

        self.assertEqual(200, jq_vars["test_case_start_time"])
        self.assertNotIn("test_case_end_time", jq_vars)
        self.assertEqual("preserved", jq_vars["unrelated"])


class TaacRunnerFailurePrecedenceTest(unittest.IsolatedAsyncioTestCase):
    async def test_teardown_failure_keeps_stage_primary_first(self) -> None:
        logger = logging.getLogger("taac-runner-failure-precedence-test")
        logger.setLevel(logging.INFO)
        runner = TaacRunner(_config(), logger=logger)
        stage = taac_types.Stage(id="failing-stage")
        playbook = taac_types.Playbook(name="failure-precedence", stages=[stage])
        test_device = SimpleNamespace(name="dut1")
        primary = RuntimeError("stage primary")
        teardown = ValueError("strict teardown")

        runner.test_summary = MagicMock()
        runner.async_test_case_setUp = AsyncMock()
        runner.initialize_and_setup_snapshot_checks = AsyncMock(return_value=[])
        runner.inject_validation_stages = MagicMock(return_value=[stage])
        runner.async_run_snapshot_checks = AsyncMock()
        runner.async_run_stage = AsyncMock(side_effect=primary)
        runner._log_post_test_results = AsyncMock()
        runner.async_test_case_tearDown = AsyncMock(side_effect=teardown)
        runner._publish_npi_result = AsyncMock()

        with self.assertRaises(ExceptionGroup) as context:
            await runner.run_test_case(playbook, test_device)

        self.assertEqual((primary, teardown), context.exception.exceptions)
        runner.async_test_case_tearDown.assert_awaited_once()
        runner._publish_npi_result.assert_awaited_once()


class IxiaCandidateTest(unittest.TestCase):
    def test_normalizes_fully_materialized_secondary(self) -> None:
        candidates = normalize_ixia_candidates(_config(_endpoint("eth1/1/1", "2/2")))

        self.assertEqual(
            [candidate.name for candidate in candidates], ["primary", "secondary"]
        )
        self.assertEqual(candidates[1].api_server_ip, "192.0.2.20")
        self.assertEqual(
            candidates[1].endpoints[0].direct_ixia_connections[0].interface, "eth1/1/1"
        )
        self.assertEqual(candidates[1].basic_port_configs, ())

    def test_rejects_secondary_without_ixia_endpoints(self) -> None:
        config = _config(taac_types.Endpoint(name="dut1", dut=True))

        with self.assertRaisesRegex(ValueError, "both require IXIA"):
            normalize_ixia_candidates(config)

    def test_explicit_override_disables_automatic_fallback(self) -> None:
        candidates = normalize_ixia_candidates(_config(_endpoint("eth1/1/1", "2/2")))

        selected = select_ixia_candidates(
            candidates, "auto", explicit_ixia_override=True
        )

        self.assertEqual(selected, (candidates[0],))

    def test_forced_primary_and_secondary_select_exact_candidate(self) -> None:
        candidates = normalize_ixia_candidates(_config(_endpoint("eth1/1/1", "2/2")))

        primary = select_ixia_candidates(
            candidates, "primary", explicit_ixia_override=False
        )
        secondary = select_ixia_candidates(
            candidates, "secondary", explicit_ixia_override=False
        )

        self.assertEqual(primary, (candidates[0],))
        self.assertEqual(secondary, (candidates[1],))

    def test_rejects_secondary_endpoint_name_mismatch(self) -> None:
        secondary = taac_types.Endpoint(
            name="dut2",
            dut=True,
            direct_ixia_connections=[
                taac_types.DirectIxiaConnection(
                    interface="eth1/1/1",
                    ixia_port="2/2",
                    ixia_chassis_ip="192.0.2.20",
                )
            ],
        )

        with self.assertRaisesRegex(ValueError, "same endpoint names"):
            normalize_ixia_candidates(_config(secondary))

    def test_rejects_secondary_dut_mismatch(self) -> None:
        secondary = _endpoint("eth1/1/1", "2/2")(dut=False)

        with self.assertRaisesRegex(ValueError, "same DUTs"):
            normalize_ixia_candidates(_config(secondary))

    def test_allows_candidate_specific_pre_ixia_task_payloads(self) -> None:
        shared = taac_types.Task(task_name="shared", params=taac_types.Params())
        primary_only = taac_types.Task(
            task_name="primary-only", params=taac_types.Params()
        )
        secondary_only = taac_types.Task(
            task_name="secondary-only", params=taac_types.Params()
        )
        config = _config(
            _endpoint("eth1/1/1", "2/2"),
            primary_setup_tasks=[shared, primary_only],
            secondary_setup_tasks=[shared, secondary_only],
        )

        primary, secondary = normalize_ixia_candidates(config)
        self.assertEqual(2, len(primary.setup_tasks))
        self.assertEqual(2, len(secondary.setup_tasks))

    def test_rejects_pre_ixia_task_count_mismatch(self) -> None:
        shared = taac_types.Task(task_name="shared", params=taac_types.Params())
        extra = taac_types.Task(task_name="extra", params=taac_types.Params())
        config = _config(
            _endpoint("eth1/1/1", "2/2"),
            primary_setup_tasks=[shared, extra],
            secondary_setup_tasks=[shared],
        )

        with self.assertRaisesRegex(ValueError, "non-IXIA setup tasks"):
            normalize_ixia_candidates(config)

    def test_rejects_secondary_with_otg_backend(self) -> None:
        config = _config(
            _endpoint("eth1/1/1", "2/2"),
        )(traffic_generator_backend=taac_types.TrafficGeneratorBackend.OTG)

        with self.assertRaisesRegex(ValueError, "only by the RESTPY"):
            normalize_ixia_candidates(config)

    def test_forced_profile_collects_only_selected_pre_ixia_tasks(self) -> None:
        primary_task = taac_types.Task(
            task_name="primary-pre", params=taac_types.Params()
        )
        config = _config(
            _endpoint("eth1/1/1", "2/2"),
            primary_setup_tasks=[primary_task],
            secondary_setup_tasks=[primary_task],
        )

        primary = TestSetupOrchestrator(config, MagicMock(), ixia_profile="primary")
        secondary = TestSetupOrchestrator(config, MagicMock(), ixia_profile="secondary")

        self.assertEqual(primary.ixia_candidates_to_try[0].setup_tasks, (primary_task,))
        self.assertEqual(
            secondary.ixia_candidates_to_try[0].setup_tasks, (primary_task,)
        )

    def test_rejects_basic_port_config_count_mismatch(self) -> None:
        # Per-config differences on `endpoint` / `device_group_configs` are
        # legitimate under dual-chassis (each config carries the DUT interface
        # of its own profile). Rejection now fires only on count mismatch.
        port_a = taac_types.BasicPortConfig(
            endpoint="dut1:eth1/1/1",
            device_group_configs=[
                taac_types.DeviceGroupConfig(device_group_index=0, tag_name="EBGP")
            ],
        )
        port_b = taac_types.BasicPortConfig(
            endpoint="dut1:eth1/1/2",
            device_group_configs=[
                taac_types.DeviceGroupConfig(device_group_index=1, tag_name="IBGP")
            ],
        )
        config = _config(_endpoint("eth1/1/1", "2/2"))
        config = config(
            basic_port_configs=[port_a, port_b],
            secondary_ixia_profile=config.secondary_ixia_profile(
                basic_port_configs=[port_a]
            ),
        )

        with self.assertRaisesRegex(ValueError, "basic port configurations"):
            normalize_ixia_candidates(config)

    def test_rejects_traffic_item_name_mismatch(self) -> None:
        primary_item = taac_types.BasicTrafficItemConfig(
            name="traffic",
            src_endpoints=[
                taac_types.TrafficEndpoint(name="dut1", device_group_index=0)
            ],
            dest_endpoints=[],
        )
        secondary_item = taac_types.BasicTrafficItemConfig(
            name="traffic-different-identity",
            src_endpoints=[
                taac_types.TrafficEndpoint(name="dut1", device_group_index=0)
            ],
            dest_endpoints=[],
        )
        config = _config(_endpoint("eth1/1/1", "2/2"))
        config = config(
            basic_traffic_item_configs=[primary_item],
            secondary_ixia_profile=config.secondary_ixia_profile(
                basic_traffic_item_configs=[secondary_item]
            ),
        )

        with self.assertRaisesRegex(ValueError, "traffic item identities"):
            normalize_ixia_candidates(config)

    def test_allows_traffic_configuration_field_differences(self) -> None:
        # Same identity (name), differing per-endpoint device_group_index —
        # allowed under dual-chassis compilation.
        primary_item = taac_types.BasicTrafficItemConfig(
            name="traffic",
            src_endpoints=[
                taac_types.TrafficEndpoint(name="dut1", device_group_index=0)
            ],
            dest_endpoints=[],
        )
        secondary_item = taac_types.BasicTrafficItemConfig(
            name="traffic",
            src_endpoints=[
                taac_types.TrafficEndpoint(name="dut1", device_group_index=1)
            ],
            dest_endpoints=[],
        )
        config = _config(_endpoint("eth1/1/1", "2/2"))
        config = config(
            basic_traffic_item_configs=[primary_item],
            secondary_ixia_profile=config.secondary_ixia_profile(
                basic_traffic_item_configs=[secondary_item]
            ),
        )

        primary, secondary = normalize_ixia_candidates(config)
        self.assertEqual(1, len(primary.basic_traffic_item_configs))
        self.assertEqual(1, len(secondary.basic_traffic_item_configs))

    def test_rejects_snake_configuration_count_mismatch(self) -> None:
        snake = taac_types.SnakeConfig(
            source="dut1",
            destination="dut1",
            source_ip="2001:db8::1",
            destination_ip="2001:db8::2",
        )
        config = _config(_endpoint("eth1/1/1", "2/2"))
        config = config(
            snake_configs=[snake],
            secondary_ixia_profile=config.secondary_ixia_profile(snake_configs=[]),
        )

        with self.assertRaisesRegex(ValueError, "snake configurations"):
            normalize_ixia_candidates(config)

    def test_single_ixia_config_normalizes_to_one_candidate(self) -> None:
        # Regression: existing single-IXIA TestConfigs without
        # `secondary_ixia_profile` must keep the pre-change one-attempt path.
        candidates = normalize_ixia_candidates(_config())

        self.assertEqual([c.name for c in candidates], ["primary"])
        self.assertEqual(
            select_ixia_candidates(candidates, "auto", explicit_ixia_override=False),
            (candidates[0],),
        )

    def test_simultaneous_multi_chassis_endpoints_do_not_enable_fallback(self) -> None:
        # Regression: an existing endpoint that carries multiple
        # DirectIxiaConnection entries (i.e., "one session across several
        # chassis") is not implicitly converted into a fallback candidate list.
        multi_chassis_endpoint = taac_types.Endpoint(
            name="dut1",
            dut=True,
            direct_ixia_connections=[
                taac_types.DirectIxiaConnection(
                    interface="eth1/1/1",
                    ixia_port="1/1",
                    ixia_chassis_ip="192.0.2.10",
                ),
                taac_types.DirectIxiaConnection(
                    interface="eth1/1/2",
                    ixia_port="1/2",
                    ixia_chassis_ip="192.0.2.11",
                ),
            ],
        )
        config = taac_types.TestConfig(
            name="EXISTING_MULTI_CHASSIS",
            basset_pool="",
            playbooks=[],
            endpoints=[multi_chassis_endpoint],
        )
        candidates = normalize_ixia_candidates(config)

        self.assertEqual([c.name for c in candidates], ["primary"])
        self.assertEqual(
            [
                connection.ixia_chassis_ip
                for connection in candidates[0].endpoints[0].direct_ixia_connections
            ],
            ["192.0.2.10", "192.0.2.11"],
        )

    def test_rejects_missing_parent_traffic_item_reference(self) -> None:
        config = _config(_endpoint("eth1/1/1", "2/2"))(
            traffic_items_to_start=["missing-traffic"]
        )

        with self.assertRaisesRegex(ValueError, "missing-traffic"):
            normalize_ixia_candidates(config)


class IxiaChassisResolutionTest(unittest.IsolatedAsyncioTestCase):
    async def test_hostname_resolution_failure_is_fallback_eligible(self) -> None:
        generator = TrafficGenerator(
            endpoints=[], primary_chassis_ip="unreachable-ixia.example"
        )
        resolution_error = OSError("DNS lookup failed")

        with patch(
            f"{_TRAFFIC_GENERATOR_MODULE}.async_get_ip_from_hostname",
            new=AsyncMock(side_effect=resolution_error),
        ):
            with self.assertRaises(IxiaChassisUnavailableError) as context:
                await generator.async_get_primary_ixia_chassis_ip()

        self.assertIs(context.exception.__cause__, resolution_error)


class IxiaFallbackTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.config = _config(_endpoint("eth1/1/1", "2/2"))
        self.logger = MagicMock()
        self.orchestrator = TestSetupOrchestrator(self.config, self.logger)
        self.chunker = MagicMock()
        self.chunker.async_create_test_bed = AsyncMock(
            return_value=SimpleNamespace(devices=[])
        )

    async def _run_setup(self) -> None:
        with (
            patch(f"{_MODULE}.TAAC_OSS", True),
            patch(f"{_MODULE}.OssTestBedChunker", return_value=self.chunker),
        ):
            await self.orchestrator.async_setUp()

    async def test_healthy_primary_does_not_attempt_secondary(self) -> None:
        primary_ixia = SimpleNamespace(session_id=11)
        self.orchestrator.async_create_ixia_setup = AsyncMock(return_value=primary_ixia)

        await self._run_setup()

        self.assertEqual(self.orchestrator.selected_ixia_candidate.name, "primary")
        self.orchestrator.async_create_ixia_setup.assert_awaited_once()

    async def test_normal_teardown_is_not_disabled_with_failed_setup_cleanup(
        self,
    ) -> None:
        teardown = MagicMock()
        orchestrator = TestSetupOrchestrator(
            self.config,
            self.logger,
            cleanup_failed_setup=False,
        )
        orchestrator.traffic_generator = SimpleNamespace(teardown_ixia_setup=teardown)

        await orchestrator.async_teardown_ixia_setup()

        teardown.assert_called_once()

    async def test_internal_teardown_attempts_every_resource(self) -> None:
        orchestrator = TestSetupOrchestrator(
            self.config,
            self.logger,
            skip_testbed_isolation=False,
        )
        restore = AsyncMock(side_effect=RuntimeError("restore failed"))
        release = AsyncMock(side_effect=RuntimeError("release failed"))
        ixia_cleanup = AsyncMock(side_effect=RuntimeError("IXIA cleanup failed"))
        orchestrator.test_bed_chunker = SimpleNamespace(
            async_restore_test_bed_connectivity=restore
        )
        orchestrator.basset_butler = object()
        orchestrator.async_teardown_ixia_setup = ixia_cleanup

        with (
            patch(f"{_MODULE}.TAAC_OSS", False),
            patch(
                f"{_INTERNAL_UTILS_MODULE}.async_release_devices_in_basset",
                new=release,
            ),
        ):
            with self.assertRaises(ExceptionGroup) as context:
                await orchestrator.async_tearDown(strict_ixia_cleanup=True)

        self.assertEqual(len(context.exception.exceptions), 3)
        restore.assert_awaited_once()
        release.assert_awaited_once_with(orchestrator.basset_butler, self.logger)
        ixia_cleanup.assert_awaited_once_with(strict=True)

    async def test_port_failure_cleans_primary_and_selects_secondary(self) -> None:
        teardown = MagicMock()

        async def create_ixia(candidate, *_args):
            if candidate.name == "primary":
                self.orchestrator.traffic_generator = SimpleNamespace(
                    teardown_ixia_setup=teardown
                )
                raise IxiaPortUnavailableError("primary port unavailable")
            return SimpleNamespace(session_id=22)

        self.orchestrator.async_create_ixia_setup = AsyncMock(side_effect=create_ixia)

        await self._run_setup()

        self.assertEqual(self.orchestrator.selected_ixia_candidate.name, "secondary")
        self.assertEqual(self.orchestrator.async_create_ixia_setup.await_count, 2)
        teardown.assert_called_once_with()

    async def test_noneligible_failure_does_not_fallback(self) -> None:
        self.orchestrator.async_create_ixia_setup = AsyncMock(
            side_effect=ValueError("invalid test config")
        )

        with self.assertRaisesRegex(ValueError, "invalid test config"):
            await self._run_setup()

        self.orchestrator.async_create_ixia_setup.assert_awaited_once()

    async def test_both_candidate_failures_are_aggregated(self) -> None:
        teardown_primary = MagicMock()
        teardown_secondary = MagicMock()

        async def create_ixia(candidate, *_args):
            teardown = (
                teardown_primary if candidate.name == "primary" else teardown_secondary
            )
            self.orchestrator.traffic_generator = SimpleNamespace(
                teardown_ixia_setup=teardown
            )
            raise IxiaPortUnavailableError(f"{candidate.name} failed")

        self.orchestrator.async_create_ixia_setup = AsyncMock(side_effect=create_ixia)

        with self.assertRaises(IxiaFallbackExhaustedError) as context:
            await self._run_setup()

        self.assertEqual(
            [name for name, _error in context.exception.failures],
            ["primary", "secondary"],
        )
        teardown_primary.assert_called_once_with()
        teardown_secondary.assert_called_once_with()

    async def test_cleanup_failure_aborts_before_secondary(self) -> None:
        teardown = MagicMock(side_effect=RuntimeError("cleanup failed"))

        async def create_ixia(_candidate, *_args):
            self.orchestrator.traffic_generator = SimpleNamespace(
                teardown_ixia_setup=teardown
            )
            raise IxiaPortUnavailableError("primary failed")

        self.orchestrator.async_create_ixia_setup = AsyncMock(side_effect=create_ixia)

        with self.assertRaisesRegex(RuntimeError, "cleanup failed"):
            await self._run_setup()

        self.orchestrator.async_create_ixia_setup.assert_awaited_once()
        self.assertIsNotNone(self.orchestrator.traffic_generator)


class SetupOnlyTest(unittest.IsolatedAsyncioTestCase):
    async def test_skips_playbook_execution(self) -> None:
        logger = MagicMock()
        runner = TaacRunner(_config(), setup_only=True, logger=logger)
        runner.run_test_case = AsyncMock()

        await runner.run_tests()

        runner.run_test_case.assert_not_awaited()
        logger.warning.assert_called_once_with(
            "Setup-only mode: setup completed; skipping all playbooks"
        )


class IxiaDiagnosticsDefaultTest(unittest.TestCase):
    def test_collection_is_enabled_by_default(self) -> None:
        runner = TaacRunner(_config())

        self.assertTrue(runner.collect_ixia_diagnostics)

    def test_collection_can_be_disabled(self) -> None:
        runner = TaacRunner(_config(), collect_ixia_diagnostics=False)

        self.assertFalse(runner.collect_ixia_diagnostics)


class SelectedCandidateTaskTest(unittest.IsolatedAsyncioTestCase):
    async def test_secondary_post_setup_and_teardown_tasks_are_used(self) -> None:
        pre_task = taac_types.Task(task_name="common-pre", params=taac_types.Params())
        primary_post = taac_types.Task(
            task_name="primary-post", params=taac_types.Params(), ixia_needed=True
        )
        secondary_post = taac_types.Task(
            task_name="secondary-post", params=taac_types.Params(), ixia_needed=True
        )
        primary_teardown = taac_types.Task(
            task_name="primary-teardown", params=taac_types.Params()
        )
        secondary_teardown = taac_types.Task(
            task_name="secondary-teardown", params=taac_types.Params()
        )
        config = _config(
            _endpoint("eth1/1/1", "2/2"),
            primary_setup_tasks=[pre_task, primary_post],
            primary_teardown_tasks=[primary_teardown],
            secondary_setup_tasks=[pre_task, secondary_post],
            secondary_teardown_tasks=[secondary_teardown],
        )
        logger = logging.getLogger("taac-fallback-selected-task-test")
        logger.setLevel(logging.INFO)
        # This test asserts run_tasks call order by index; skip the OSS
        # setup-task stage so its extra run_tasks call does not shift them.
        runner = TaacRunner(config, logger=logger, skip_oss_setup_tasks=True)
        runner.run_tasks = AsyncMock()
        runner._add_oss_mock_device_data = MagicMock()
        runner._add_host_to_device_os_type_data = MagicMock()
        runner._add_host_driver_args_data = MagicMock()
        runner.filter_custom_test_handlers_by_tags = MagicMock(return_value=[])

        async def select_secondary() -> None:
            runner.test_setup_orchestrator.selected_ixia_candidate = (
                runner.ixia_candidates[1]
            )
            runner.test_setup_orchestrator.ixia = None
            runner.test_setup_orchestrator.test_topology = SimpleNamespace(devices=[])

        runner.test_setup_orchestrator.async_setUp = AsyncMock(
            side_effect=select_secondary
        )

        await runner.async_test_setUp()

        self.assertEqual(runner.run_tasks.await_args_list[0].args[0], [pre_task])
        self.assertEqual(runner.run_tasks.await_args_list[1].args[0], [secondary_post])

        runner.run_tasks.reset_mock()
        teardown_events = []

        async def run_selected_teardown(_tasks) -> None:
            teardown_events.append("selected-tasks")

        async def release_resources(**_kwargs) -> None:
            teardown_events.append("orchestrator")

        runner.run_tasks.side_effect = run_selected_teardown
        runner.test_setup_orchestrator.async_tearDown = AsyncMock(
            side_effect=release_resources
        )
        summary = MagicMock()
        summary.start_section.return_value = MagicMock()
        summary.sections = []
        summary.async_upload_and_log_summary = AsyncMock()
        runner.test_summary = summary

        await runner.async_test_tearDown()

        runner.run_tasks.assert_awaited_once_with((secondary_teardown,))
        self.assertEqual(teardown_events, ["selected-tasks", "orchestrator"])

    async def test_teardown_task_failure_still_releases_resources(self) -> None:
        config = _config()
        logger = logging.getLogger("taac-fallback-task-failure-test")
        logger.setLevel(logging.INFO)
        runner = TaacRunner(config, logger=logger)
        runner.selected_ixia_candidate = runner.ixia_candidates[0]
        runner.run_tasks = AsyncMock(side_effect=RuntimeError("task cleanup failed"))
        runner.test_setup_orchestrator.async_tearDown = AsyncMock()
        summary = MagicMock()
        summary.start_section.return_value = MagicMock()
        summary.sections = []
        summary.async_upload_and_log_summary = AsyncMock()
        runner.test_summary = summary

        with self.assertRaisesRegex(RuntimeError, "task cleanup failed"):
            await runner.async_test_tearDown()

        runner.test_setup_orchestrator.async_tearDown.assert_awaited_once()

    async def test_setup_only_strict_teardown_failure_fails_run(self) -> None:
        config = _config()
        logger = logging.getLogger("taac-fallback-setup-only-test")
        logger.setLevel(logging.INFO)
        runner = TaacRunner(config, setup_only=True, logger=logger)
        runner.selected_ixia_candidate = runner.ixia_candidates[0]
        runner.run_tasks = AsyncMock()
        runner.test_setup_orchestrator.async_tearDown = AsyncMock(
            side_effect=RuntimeError("session delete failed")
        )
        summary = MagicMock()
        summary.start_section.return_value = MagicMock()
        summary.sections = []
        summary.async_upload_and_log_summary = AsyncMock()
        runner.test_summary = summary

        with self.assertRaisesRegex(RuntimeError, "session delete failed"):
            await runner.async_test_tearDown()

        runner.test_setup_orchestrator.async_tearDown.assert_awaited_once_with(
            strict_ixia_cleanup=True
        )
