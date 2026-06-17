# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
import asyncio
import copy
import json
import os
import re
import time
import typing as t
import uuid
from datetime import datetime

TAAC_OSS = os.environ.get("TAAC_OSS", "").lower() in ("1", "true", "yes")

from urllib.parse import quote  # noqa: F401

if not TAAC_OSS:
    from neteng.netcastle.exceptions import TestbedError
else:
    # OSS stub — netcastle isn't shipped. The only use site is an
    # `except TestbedError:` precheck-failure handler against Meta-internal
    # testbeds; nothing under OSS raises this, so the handler simply never
    # matches.
    class TestbedError(Exception):
        pass


from taac.constants import (
    DNE_LOG_DIR,
    FAILED_HC_STATUSES,
    FBOSS_LOG_DIR,
    FbossPackage,
    TestCaseFailure,
    TestDevice,
    TestResult,
)
from taac.custom_test_handlers.base_custom_test_handler import (
    BaseCustomTestHandler,
)
from taac.custom_test_handlers.registry import (
    CUSTOM_TEST_HANDLERS,
)
from taac.health_checks.abstract_snapshot_health_check import (
    AbstractDeviceSnapshotHealthCheck,
    AbstractSnapshotHealthCheck,
    AbstractTopologySnapshotHealthCheck,
)
from taac.health_checks.all_health_checks import (
    HEALTH_CHECK_NAME_TO_INPUT,
    NAME_TO_HEALTH_CHECK,
    SNAPSHOT_HEALTH_CHECKS,
)
from taac.ixia.taac_ixia import TaacIxia

if not TAAC_OSS:
    from taac.libs.fpf.fpf_collector_registry import (
        set_test_case_start_time,
    )
else:
    # OSS stub - taac.libs.fpf.* pulls in neteng.netcastle / taac.internal
    # via fpf_stress_checks and friends. FPF collector is for Meta-internal
    # performance flows; the recorded start time is read only by FPF
    # collectors, which aren't registered under OSS, so a no-op stub is
    # safe and the call site simply has no observable effect.
    def set_test_case_start_time(*args, **kwargs):  # type: ignore
        """OSS stub - FPF collector isn't shipped."""
        pass


from taac.libs.parameter_evaluator import ParameterEvaluator
from taac.libs.periodic_task_executor import PeriodicTaskExecutor
from taac.libs.test_setup_orchestrator import (
    TestSetupOrchestrator,
)

if not TAAC_OSS:
    from taac.stages.stage_definitions import create_steps_stage
else:
    # OSS stub - taac.stages package isn't vendored in this slice
    # (new in upstream main and Meta-internal-only). Stub raises
    # NotImplementedError so any OSS code path that constructs a
    # steps-stage fails clearly.
    def create_steps_stage(*args, **kwargs):  # type: ignore
        raise NotImplementedError(
            "create_steps_stage requires Meta-internal taac.stages.stage_definitions; "
            "not shipped under OSS."
        )


from neteng.test_infra.dne.taac.steps.all_steps import NAME_TO_STEP, STEP_NAME_TO_INPUT
from taac.steps.step import Step
from taac.steps.step_definitions import ValidationStep
from taac.tasks.utils import run_task
from taac.test_configs import get_test_config
from taac.utils.common import (
    async_everpaste_str,
    async_write_test_result,
    tabulate_test_results,
)
from taac.utils.deploy_utils import (
    async_create_rsyslog_configuration,
    async_delete_rsyslog_configuration,
)
from taac.utils.driver_factory import (
    add_host_to_device_os_type_data,
    add_host_to_driver_args_data,
    async_get_device_driver,
)
from taac.utils.json_thrift_utils import (
    json_to_thrift,
    thrift_to_json,
    try_thrift_to_dict,
)
from taac.utils.oss_taac_lib_utils import (
    async_retryable,
    ConsoleFileLogger,
    get_root_logger,
    none_throws,
)
from taac.utils.taac_log_formatter import (
    log_phase_end,
    log_phase_start,
    log_playbook_header,
    log_results_table,
    log_section,
    log_subsection,
    suppress_console_logs,
)
from taac.utils.taac_test_summary import (
    SectionResult,
    SectionStatus,
    TaacTestSummary,
)

if not TAAC_OSS:
    from taac.utp.npi_result_publisher import (
        async_publish_npi_aggregated_result,
        extract_scope_from_device,
    )
else:
    # OSS stubs - NPI result publishing requires Meta-internal XDB
    async def async_publish_npi_aggregated_result(*args, **kwargs) -> None:  # type: ignore
        """OSS stub - NPI result publishing not available"""
        pass

    def extract_scope_from_device(test_device: t.Any) -> t.Dict[str, str]:  # type: ignore
        """OSS stub - returns empty scope"""
        return {"network_type": "", "device_role": "", "platform": ""}


if not TAAC_OSS:
    from taac.utp.utp_test_catalog import UTP_TEST_CATALOG
else:
    # OSS stub - UTP catalog lives under Meta-internal taac.utp
    UTP_TEST_CATALOG: t.List[t.Any] = []
from taac.health_check.health_check import types as hc_types
from taac.test_as_a_config import types as taac_types
from tabulate import tabulate

if not TAAC_OSS:
    from taac.internal.netwhoami_utils import (
        add_oss_mock_device_data,
    )
    from taac.internal.tasks.ixia_diagnostics_collection_task import (
        IxiaDiagnosticsCollectionTask,
    )

DEFAULT_PRE_SNAPSHOT_CHECKPOINT_ID: str = "test_case_start"
DEFAULT_POST_SNAPSHOT_CHECKPOINT_ID: str = "test_case_end"


class TaacRunner:
    def __init__(
        self,
        test_config: t.Union[taac_types.TestConfig, str],
        ixia_api_server: t.Optional[str] = None,
        ixia_session_id: t.Optional[int] = None,
        skip_ixia_setup: bool = False,
        skip_ixia_cleanup: bool = False,
        skip_testbed_isolation: bool = True,
        # Use with CAUTION!!  Should only be used for debugging or development purposes
        skip_basset_reservation: bool = False,
        desired_pkg_versions: t.Optional[t.Dict[FbossPackage, str]] = None,
        dsf_sequential_update: bool = False,
        allow_disruptive_configs: bool = False,
        skip_package_update: bool = False,
        override_ixia_traffic_items: bool = False,
        cleanup_failed_setup: bool = True,
        skip_setup_tasks: bool = False,
        skip_teardown_tasks: bool = False,
        skip_all_tasks: bool = False,
        skip_periodic_tasks: bool = False,
        skip_ptp_setup: bool = False,
        logger: t.Optional[ConsoleFileLogger] = None,
        # Netcastle runner specific
        is_autotester_run: bool = False,
        test_results: t.Optional[t.List[TestResult]] = None,
        # EOS image ID for Arista device image deployment
        eos_image_id: t.Optional[str] = None,
        # Whether to clear old EOS images from flash before deployment
        clear_old_eos_images: bool = False,
        # NPI name for UTP result tracking
        npi_name: str = "",
        # Allow overwriting failed/blocked NPI results with new results
        overwrite_previous_results: bool = False,
        # NPI module-based playbook selection
        npi_modules: t.Optional[t.List[str]] = None,
        npi_status: str = "",
        # Trigger Confucius triage agent on failures
        call_triage_minion: bool = False,
        # Continue executing playbook stages even if prechecks fail (dev only)
        continue_on_precheck_failure: bool = False,
        # Skip prechecks entirely — go straight to stages (dev only)
        skip_prechecks: bool = False,
        # Skip FBOSS rsyslog configuration setup/teardown
        skip_fboss_rsyslog: bool = False,
        # Opt-in: pull Keysight chassis diagnostics archive at Ixia teardown
        # and upload to Manifold. Best-effort — failures never break teardown.
        collect_ixia_diagnostics: bool = False,
    ) -> None:
        self.test_config = (
            get_test_config(test_config)
            if isinstance(test_config, str)
            else test_config
        )
        self._validate_no_test_config_level_checks()
        # results of the entire test run. test_results can be passed in as an empty list
        self.test_run_results = test_results if test_results is not None else []
        self.logger = logger or get_root_logger()
        self.duts: t.List[str] = [
            endpoint.name for endpoint in self.test_config.endpoints if endpoint.dut
        ]
        self.skip_package_update = skip_package_update
        self.dsf_sequential_update = dsf_sequential_update
        self.skip_setup_tasks = skip_setup_tasks
        self.skip_teardown_tasks = skip_teardown_tasks
        self.skip_all_tasks = skip_all_tasks
        self.skip_periodic_tasks = skip_periodic_tasks
        # Skip PTP setup on IXIA
        if skip_ptp_setup:
            # pyrefly: ignore [read-only]
            self.test_config.ptp_configs = []
        # EOS image ID for Arista device image deployment
        self.eos_image_id = eos_image_id or ""
        # Whether to clear old EOS images from flash before deployment
        self.clear_old_eos_images = clear_old_eos_images
        # NPI name for UTP result tracking
        self.npi_name = npi_name
        self.overwrite_previous_results = overwrite_previous_results
        # NPI module-based playbook selection
        self.npi_modules = [m.upper() for m in npi_modules] if npi_modules else []
        self.npi_status = npi_status.lower() if npi_status else ""
        # Per-iteration outcomes for NPI aggregation (populated during playbook runs)
        self._npi_iteration_outcomes: t.List[t.Tuple[str, t.Optional[str]]] = []
        # Trigger Confucius triage agent on failures
        self.call_triage_minion = call_triage_minion
        self.continue_on_precheck_failure = continue_on_precheck_failure
        self.skip_prechecks = skip_prechecks
        self.skip_fboss_rsyslog = skip_fboss_rsyslog
        self.collect_ixia_diagnostics = collect_ixia_diagnostics

        # Netcastle runner specific variables
        self.is_autotester_run = is_autotester_run

        self.ixia: t.Optional[TaacIxia] = None
        self.topology = ...
        self.device_to_rsyslog_services = {}
        self.test_setup_orchestrator = TestSetupOrchestrator(
            self.test_config,
            self.logger,
            ixia_api_server,
            ixia_session_id,
            skip_ixia_setup,
            skip_ixia_cleanup,
            skip_basset_reservation,
            skip_testbed_isolation,
            desired_pkg_versions,
            dsf_sequential_update,
            allow_disruptive_configs,
            skip_package_update,
            override_ixia_traffic_items,
            cleanup_failed_setup,
            eos_image_id=eos_image_id,
            clear_old_eos_images=clear_old_eos_images,
        )
        self.test_case_uuid = ""
        self.custom_test_handlers = []
        self.started_capture: bool = False
        # pyrefly: ignore [bad-assignment]
        self._current_playbook: taac_types.Playbook = ...
        # pyrefly: ignore [bad-assignment]
        self._current_stage: taac_types.Stage = ...
        self._current_snapshot_checks: t.List[AbstractSnapshotHealthCheck] = []

        self.jq_vars: t.Dict[str, t.Any] = {}
        self.dynamic_vars: t.Dict[str, str] = {}
        self.parameter_evaluator = ParameterEvaluator(self.jq_vars, self.dynamic_vars)
        self.periodic_task_executor: t.Optional[PeriodicTaskExecutor] = None
        self.test_case_periodic_task_executor: t.Optional[PeriodicTaskExecutor] = None
        # Shared data dictionary that persists across all tasks (setup, test, teardown)
        # This allows tasks to share information (e.g., backup filenames) across execution
        self.shared_task_data: t.Dict[t.Any, t.Any] = {}
        self.test_summary = TaacTestSummary(self.logger)
        self._current_playbook_section: t.Optional[SectionResult] = None
        self._last_completed_playbook_section: t.Optional[SectionResult] = None

    def _validate_no_test_config_level_checks(self) -> None:
        """Validate that deprecated TestConfig-level checks are not used.

        prechecks, postchecks, snapshot_checks, and periodic_tasks should be
        defined at the Playbook level, not at the TestConfig level.
        """
        deprecated_fields = {
            "prechecks": self.test_config.prechecks,
            "postchecks": self.test_config.postchecks,
            "snapshot_checks": self.test_config.snapshot_checks,
            "periodic_tasks": self.test_config.periodic_tasks,
        }
        violations = [
            field_name for field_name, value in deprecated_fields.items() if value
        ]
        if violations:
            raise ValueError(
                f"TestConfig '{self.test_config.name}' defines {', '.join(violations)} "
                f"at the TestConfig level. These fields are deprecated and must be "
                f"defined at the Playbook level instead. Move them to each Playbook's "
                f"corresponding field."
            )

    def filter_custom_test_handlers_by_tags(
        self, tags: t.List[str]
    ) -> t.List[t.Type[BaseCustomTestHandler]]:
        handlers = []
        for handler in CUSTOM_TEST_HANDLERS:
            if any(tag in handler.SUPPORTED_TAGS for tag in tags):
                handlers.append(handler)
        self.logger.info(
            # pyrefly: ignore [missing-attribute]
            f"Found {len(handlers)} custom test handlers: {[handler.__name__ for handler in handlers]}"
        )
        # pyrefly: ignore [bad-return]
        return handlers

    @staticmethod
    def _get_task_description(task: taac_types.Task) -> str:
        """Build a human-readable description for a task from its params."""
        desc_parts = [task.description or task.task_name]
        try:
            params = json.loads(task.params.json_params or "{}") if task.params else {}
            hostname = task.hostname or params.get("hostname")
            if hostname:
                desc_parts.append(f"host={hostname}")
            patcher_name = params.get("patcher_name")
            if patcher_name:
                desc_parts.append(f"patcher={patcher_name}")
            config_name = params.get("config_name")
            if config_name:
                desc_parts.append(f"config={config_name}")
        except Exception:
            pass
        return " | ".join(desc_parts)

    @async_retryable(retries=2, sleep_time=60, exceptions=(Exception,))
    async def run_tasks(self, tasks: t.List[taac_types.Task]) -> None:
        total = len(tasks)
        for idx, task in enumerate(tasks, 1):
            task_desc = task.description or task.task_name
            self.logger.warning(
                f"[Task {idx}/{total}] Running: {task_desc} (host: {task.hostname})"
            )
            start = time.time()
            dict_params = self.parameter_evaluator.evaluate(task.params)
            await run_task(
                task, dict_params, self.ixia, self.logger, self.shared_task_data
            )
            elapsed = time.time() - start
            self.logger.warning(
                f"[Task {idx}/{total}] Completed: {task_desc} ({elapsed:.1f}s)"
            )

    def populate_jq_vars(self) -> None:
        # pyrefly: ignore [missing-attribute]
        for device in self.topology.devices:
            self.jq_vars[device.name] = {
                "interfaces": [
                    try_thrift_to_dict(interface) for interface in device.interfaces
                ]
            }

    async def async_test_setUp(self) -> None:
        log_section("TEST CONFIG SETUP", logger=self.logger)
        setup_start = time.time()
        skip_setup_tasks = self.skip_all_tasks or self.skip_setup_tasks
        setup_tasks = self.test_config.setup_tasks or []

        self._add_oss_mock_device_data()
        self._add_host_to_device_os_type_data()
        self._add_host_driver_args_data()

        log_section("PRE-IXIA SETUP TASKS", logger=self.logger)
        with self.test_summary.tracked_section("Pre-IXIA setup tasks"):
            with suppress_console_logs(self.logger):
                await self.run_tasks(
                    [task for task in setup_tasks if not task.ixia_needed]
                    if not skip_setup_tasks
                    else []
                )

        log_section("IXIA & TOPOLOGY SETUP", logger=self.logger)
        with self.test_summary.tracked_section("Test orchestrator setup"):
            with suppress_console_logs(self.logger):
                await self.test_setup_orchestrator.async_setUp()
                self.ixia = self.test_setup_orchestrator.ixia
                # pyrefly: ignore [bad-assignment]
                self.topology = self.test_setup_orchestrator.test_topology
                self.populate_jq_vars()

        log_section("POST-IXIA SETUP TASKS", logger=self.logger)
        with self.test_summary.tracked_section("Post-IXIA setup tasks"):
            with suppress_console_logs(self.logger):
                await self.run_tasks(
                    [task for task in setup_tasks if task.ixia_needed]
                    if not skip_setup_tasks
                    else []
                )

        # pyrefly: ignore [bad-assignment]
        self.topology = self.test_setup_orchestrator.test_topology
        self.populate_jq_vars()

        with suppress_console_logs(self.logger):
            self.custom_test_handlers = [
                # pyrefly: ignore [bad-argument-type]
                handler(self.topology, logger=self.logger)
                for handler in self.filter_custom_test_handlers_by_tags(
                    # pyrefly: ignore [bad-argument-type]
                    self.test_config.tags or []
                )
            ]
            await asyncio.gather(
                *[handler.setUp() for handler in self.custom_test_handlers]
            )
            if self.ixia:
                self.ixia.enable_traffic(enable=False)

            rsyslog_services_overrides = (
                self.test_config.rsyslog_services_overrides or {}
            )
            # pyrefly: ignore [missing-attribute]
            for device in self.topology.devices:
                self.device_to_rsyslog_services[device.name] = (
                    rsyslog_services_overrides.get(device.name)
                    or self.test_config.rsyslog_services
                )
            for handler in self.custom_test_handlers:
                await handler._async_test_setUp()
            # Deprecated - periodic_tasks should be defined at playbook level
            # TestConfig-level periodic tasks are no longer started here

        await self.run_startup_checks()
        log_phase_end(
            "TEST CONFIG SETUP",
            duration_secs=time.time() - setup_start,
            logger=self.logger,
        )

    async def run_startup_checks(self) -> None:
        """
        Run startup_checks once during test setup, before any test cases begin.
        These checks are test-agnostic and verify the initial state of the test environment.
        """
        startup_checks = self.test_config.startup_checks
        if not startup_checks:
            return

        if TAAC_OSS:
            self.logger.warning(
                "Startup checks skipped in OSS mode (requires ValidationStep with Meta-internal dependencies)"
            )
            return

        log_section("STARTUP HEALTH CHECKS", logger=self.logger)

        # Run startup checks on all DUTs
        for dut_name in self.duts:
            # pyrefly: ignore [missing-attribute]
            test_device = self.topology.get_device_by_name(dut_name)
            # pyrefly: ignore [bad-argument-type]
            await self.run_startup_checks_for_device(startup_checks, test_device)

    async def run_startup_checks_for_device(
        self,
        startup_checks: t.List[taac_types.PointInTimeHealthCheck],
        test_device: TestDevice,
    ) -> None:
        """
        Run startup checks for a specific device using ValidationStep for proper reporting
        """

        self.logger.info(
            f"Running {len(startup_checks)} startup check(s) for {test_device.name}"
        )

        # Create a validation step specifically for startup checks with proper reporting
        validation_input = taac_types.ValidationInput(
            point_in_time_checks=startup_checks,
            stage=taac_types.ValidationStage.PRE_TEST,
            fail_fast=True,  # Fail fast on startup checks since they verify initial state
        )

        # Create a results list for startup checks reporting
        startup_check_results = []

        # Create the validation step with proper test case context for reporting
        validation_step = ValidationStep(
            name="startup_checks",
            device=test_device,
            ixia=self.ixia,
            test_case_results=startup_check_results,  # Use dedicated results list for startup checks
            test_config=self.test_config,
            test_case_name="startup_checks",
            test_case_start_time=int(time.time()),
            logger=self.logger,
            parameter_evaluator=self.parameter_evaluator,
            # pyrefly: ignore [bad-argument-type]
            topology=self.topology,
            step=taac_types.Step(name=taac_types.StepName.VALIDATION_STEP),
        )

        validation_step._input = validation_input
        validation_step._step_params = {}

        # Run the startup checks through ValidationStep for proper table reporting
        try:
            await validation_step._run(validation_input, {})
            self.logger.info(f"Startup checks passed for {test_device.name}")
        except Exception as e:
            self.logger.error(f"Startup checks failed for {test_device.name}: {e}")
            # The ValidationStep will have already logged the failure in the table
            raise TestCaseFailure(
                f"Startup checks failed for {test_device.name}. "
                f"Initial environment state is not as expected: {e}"
            )

    def inject_validation_stages(
        self, playbook: taac_types.Playbook
    ) -> t.List[taac_types.Stage]:
        """
        Inject user defined prechecks, postchecks into the playbook.
        Note: startup_checks are now run once during test setup, not per playbook.
        """
        # deep copy the stages to avoid modifying the original playbook
        stages = list(copy.deepcopy(playbook.stages))

        prechecks = self.get_checks_to_run(
            playbook.prechecks,
            None,  # Deprecated - prechecks should be defined at playbook level
            playbook.skip_test_config_prechecks,
            playbook.prechecks_to_skip,
            playbook.check_ids_to_skip,
            playbook.override_duplicate_checks,
        )
        postchecks = self.get_checks_to_run(
            playbook.postchecks,
            None,  # Deprecated - postchecks should be defined at playbook level
            playbook.skip_test_config_postchecks,
            playbook.postchecks_to_skip,
            playbook.check_ids_to_skip,
            playbook.override_duplicate_checks,
        )

        if prechecks and self.skip_prechecks:
            self.logger.warning(
                "[--skip-prechecks] Skipping %d precheck(s) — "
                "going straight to stage execution",
                len(prechecks),
            )
            prechecks = []

        if prechecks:
            # Phase 5 v2 C1: runtime-dynamic Stage. Shape is static (single
            # VALIDATION_STEP wrapped in a Stage) — only the inner
            # point_in_time_checks list is runtime-derived. Use centralized
            # create_steps_stage factory.
            precheck_stage = create_steps_stage(
                stage_id="prechecks",
                description="Prechecks",
                steps=[
                    taac_types.Step(
                        name=taac_types.StepName.VALIDATION_STEP,
                        input_json=thrift_to_json(
                            taac_types.ValidationInput(
                                point_in_time_checks=prechecks,
                                stage=taac_types.ValidationStage.PRE_TEST,
                            )
                        ),
                    )
                ],
            )
            stages.insert(0, precheck_stage)

        if postchecks:
            # Phase 5 v2 C1: see precheck_stage note above. Same static-shape /
            # runtime-content pattern.
            postcheck_stage = create_steps_stage(
                stage_id="postchecks",
                description="Post-health Checks",
                steps=[
                    taac_types.Step(
                        name=taac_types.StepName.VALIDATION_STEP,
                        input_json=thrift_to_json(
                            taac_types.ValidationInput(
                                point_in_time_checks=postchecks,
                                stage=taac_types.ValidationStage.POST_TEST,
                            )
                        ),
                    )
                ],
            )
            stages.append(postcheck_stage)
        return stages

    def _initialize_step(
        self,
        step: taac_types.Step,
        device: TestDevice,
        test_case_name: str,
        test_case_start_time: int,
        test_case_results: t.List[TestResult],
    ) -> Step:
        step_cls = NAME_TO_STEP[step.name]
        step_obj = step_cls(
            name=step.id or uuid.uuid4().hex,
            device=device,
            ixia=self.ixia,
            test_case_results=test_case_results,
            test_config=self.test_config,
            test_case_name=test_case_name,
            test_case_start_time=test_case_start_time,
            logger=self.logger,
            parameter_evaluator=self.parameter_evaluator,
            # pyrefly: ignore [bad-argument-type]
            topology=self.topology,
            step=step,
        )
        step_obj._input = (
            json_to_thrift(step.input_json, STEP_NAME_TO_INPUT[step.name])
            if step.input_json
            else STEP_NAME_TO_INPUT[step.name]()
        )
        step_obj._step_params = self.parameter_evaluator.evaluate(
            step.step_params, {"dut": device.name}
        )
        step_obj._initialize_and_run_step_callable = self.initialize_and_run_steps
        return step_obj

    async def initialize_and_run_concurrent_steps(
        self,
        concurrent_steps: t.Sequence[taac_types.ConcurrentStep],
        test_device: TestDevice,
        test_case_name: str,
        test_case_start_time: int,
        test_case_results: t.List[TestResult],
    ) -> None:
        run_coros = []
        for concurrent_step in concurrent_steps:
            coro = asyncio.create_task(
                self.initialize_and_run_steps(
                    concurrent_step.steps,
                    test_device,
                    test_case_name,
                    test_case_start_time,
                    test_case_results,
                )
            )
            run_coros.append(coro)
        await asyncio.gather(*run_coros)

    async def initialize_and_run_steps(
        self,
        steps: t.Sequence[taac_types.Step],
        test_device: TestDevice,
        test_case_name: str,
        test_case_start_time: int,
        test_case_results: t.List[TestResult],
        iteration: int = 1,
    ) -> None:
        step_objs_list = []
        for step in steps:
            if step.attribute_filters:
                test_devices = self._get_devices_matching_attribute_filters(
                    # pyre-fixme[6]: For 2nd argument expected `Dict[str,
                    #  List[str]]` but got `Mapping[str, Sequence[str]]`.
                    self.topology.devices,
                    # pyre-fixme[6]: For 2nd argument expected `Dict[str,
                    #  List[str]]` but got `Mapping[str, Sequence[str]]`.
                    step.attribute_filters,
                )
            elif step.device_regexes:
                test_devices = [
                    device
                    # pyrefly: ignore [missing-attribute]
                    for device in self.topology.devices
                    if any(
                        re.match(regex, device.name) for regex in step.device_regexes
                    )
                ]
            else:
                test_devices = [test_device]
            step_objs_list.append(
                [
                    self._initialize_step(
                        step,
                        device,
                        test_case_name,
                        test_case_start_time,
                        test_case_results,
                    )
                    for device in test_devices
                ]
            )
        for step_objs in step_objs_list:
            await self.run_steps(step_objs, iteration)

    @staticmethod
    def _get_devices_matching_attribute_filters(
        devices: t.List[TestDevice],
        filters: t.Dict[str, t.List[str]],
    ) -> t.List[TestDevice]:
        """Filter devices by SwitchAttributes flat string fields.

        Args:
            devices: List of test devices to filter.
            filters: Map of SwitchAttributes field names to allowed values.
                     A device matches if ALL keys match (AND logic).
                     e.g. {"role": ["FDSW", "FSW"]} matches devices with role FDSW or FSW.
        """
        matched = []
        for device in devices:
            match = True
            for field, allowed_values in filters.items():
                actual = getattr(device.attributes, field, "")
                if actual not in allowed_values:
                    match = False
                    break
            if match:
                matched.append(device)
        return matched

    async def run_test_case(
        self,
        playbook: taac_types.Playbook,
        test_device: TestDevice,
    ) -> None:
        """
        Compile a playbook into a test case and run it
        """
        test_case_name = playbook.name
        # Track per-iteration outcomes for NPI aggregation:
        # list of (status, error_type) where status is "passed"/"failed"/"error"
        npi_iteration_outcomes: t.List[t.Tuple[str, t.Optional[str]]] = []
        self._npi_iteration_outcomes = npi_iteration_outcomes
        _run_exc: t.Optional[BaseException] = None
        _npi_iteration_count = 0

        try:
            for _ in range(playbook.iteration if not self.is_autotester_run else 1):
                _npi_iteration_count += 1
                self._current_playbook_section = self.test_summary.start_section(
                    f"Playbook: {playbook.name} | {test_device.name}"
                )
                self.jq_vars["test_case_start_time"] = int(time.time())
                with suppress_console_logs(self.logger):
                    await self.async_test_case_setUp(playbook, test_device)
                test_case_start_time = int(time.time())
                set_test_case_start_time(float(test_case_start_time))
                log_playbook_header(
                    playbook_name=playbook.name,
                    device_name=test_device.name,
                    logger=self.logger,
                )
                # results of a single playbook run
                test_case_results = []
                # Deprecated - snapshot_checks should be defined at playbook level
                snapshot_checks = [
                    snapshot_check
                    for snapshot_check in (playbook.snapshot_checks or [])
                    if snapshot_check.name
                    not in (playbook.snapshot_checks_to_skip or [])
                ]
                # Execute playbook setup_steps first, before snapshot checks
                with suppress_console_logs(self.logger):
                    if playbook.setup_steps:
                        await self.initialize_and_run_steps(
                            playbook.setup_steps,
                            test_device=test_device,
                            test_case_name=test_case_name,
                            test_case_start_time=test_case_start_time,
                            test_case_results=test_case_results,
                        )
                    snapshot_check_objs = (
                        await self.initialize_and_setup_snapshot_checks(
                            snapshot_checks,
                            test_device,
                        )
                    )
                    self._current_snapshot_checks = snapshot_check_objs
                    stages = self.inject_validation_stages(playbook)
                    await self.async_run_snapshot_checks(
                        snapshot_check_objs,
                        DEFAULT_PRE_SNAPSHOT_CHECKPOINT_ID,
                        int(time.time()),
                        test_case_results,
                        playbook.name,
                    )
                try:
                    for stage in stages:
                        self._current_stage = stage
                        if not stage.id:
                            stage = stage(id=uuid.uuid4().hex)
                        try:
                            with suppress_console_logs(self.logger):
                                await self.async_run_snapshot_checks(
                                    snapshot_check_objs,
                                    f"stage.{stage.id}.start",
                                    int(time.time()),
                                    test_case_results,
                                    playbook.name,
                                )
                                if stage.attribute_filters:
                                    test_devices = self._get_devices_matching_attribute_filters(
                                        # pyre-fixme[6]: For 2nd argument expected
                                        #  `Dict[str, List[str]]` but got `Mapping[str,
                                        #  Sequence[str]]`.
                                        self.topology.devices,
                                        # pyre-fixme[6]: For 2nd argument expected
                                        #  `Dict[str, List[str]]` but got `Mapping[str,
                                        #  Sequence[str]]`.
                                        stage.attribute_filters,
                                    )
                                elif stage.device_regexes:
                                    test_devices = [
                                        device
                                        # pyrefly: ignore [missing-attribute]
                                        for device in self.topology.devices
                                        if any(
                                            re.match(regex, device.name)
                                            for regex in stage.device_regexes
                                        )
                                    ]
                                else:
                                    test_devices = [test_device]

                            await asyncio.gather(
                                *[
                                    self.async_run_stage(
                                        stage,
                                        test_device,
                                        playbook.name,
                                        test_case_start_time,
                                        test_case_results,
                                    )
                                    for test_device in test_devices
                                ]
                            )
                        except TestbedError:
                            if self.continue_on_precheck_failure:
                                self.logger.warning(
                                    f"[--continue-on-precheck-failure] "
                                    f"Prechecks failed for stage '{stage.id}' "
                                    f"but continuing playbook execution"
                                )
                            else:
                                raise
                        with suppress_console_logs(self.logger):
                            await self.async_run_snapshot_checks(
                                self._current_snapshot_checks,
                                f"stage.{stage.id}.end",
                                int(time.time()),
                                test_case_results,
                                test_case_name,
                            )
                finally:
                    # always run post-snapshot checks for observability, regardless of stage failures
                    with suppress_console_logs(self.logger):
                        try:
                            await self.async_run_snapshot_checks(
                                snapshot_check_objs,
                                DEFAULT_POST_SNAPSHOT_CHECKPOINT_ID,
                                int(time.time()),
                                test_case_results,
                                test_case_name,
                            )
                            self.logger.info(
                                f"Post-snapshot checks completed for {test_case_name}"
                            )
                        except Exception as e:
                            self.logger.error(
                                f"Failed to run post-snapshot checks for {test_case_name}: {e}"
                            )
                        if playbook.cleanup_steps:
                            log_subsection(
                                f"Cleanup Steps — Playbook '{playbook.name}'",
                                logger=self.logger,
                            )
                            log_phase_start(
                                f"Cleanup Steps ({len(playbook.cleanup_steps)} step(s))",
                                logger=self.logger,
                            )
                            _cleanup_start = time.time()
                            await self.initialize_and_run_steps(
                                playbook.cleanup_steps,
                                test_device=test_device,
                                test_case_name=test_case_name,
                                test_case_start_time=test_case_start_time,
                                test_case_results=test_case_results,
                            )
                            log_phase_end(
                                f"Cleanup Steps ({len(playbook.cleanup_steps)} step(s))",
                                duration_secs=time.time() - _cleanup_start,
                                logger=self.logger,
                            )
                        self.jq_vars["test_case_end_time"] = int(time.time())

                    # Log POST_TEST health check results table
                    await self._log_post_test_results(test_case_results)

                    _teardown_exc = None
                    with suppress_console_logs(self.logger):
                        try:
                            await self.async_test_case_tearDown(
                                playbook,
                                test_device,
                                test_case_results,
                                test_case_start_time,
                            )
                        except Exception as e:
                            _teardown_exc = e

                    if _teardown_exc is not None:
                        raise _teardown_exc
        except Exception as e:
            _run_exc = e
            if self.npi_name and test_case_name:
                if len(npi_iteration_outcomes) < _npi_iteration_count:
                    # No outcome was recorded for this iteration (e.g. setUp
                    # failure, setup_steps error, or tearDown crashed early).
                    npi_iteration_outcomes.append(("error", str(e)))
                elif (
                    npi_iteration_outcomes and npi_iteration_outcomes[-1][0] == "passed"
                ):
                    # tearDown recorded "passed" but the iteration actually
                    # errored (e.g. stage crash that isn't reflected in health
                    # check results). Correct it to "error".
                    npi_iteration_outcomes[-1] = ("error", str(e))
        finally:
            # Publish NPI result immediately after all iterations complete,
            # before returning to run_tests for the next playbook.
            # This ensures the result reflects the full aggregated outcome
            # across all iterations and is persisted before moving on.
            await self._publish_npi_result(
                test_case_name, npi_iteration_outcomes, test_device
            )
            if _run_exc is not None:
                raise _run_exc

    async def _publish_npi_result(
        self,
        test_case_name: str,
        npi_iteration_outcomes: t.List[t.Tuple[str, t.Optional[str]]],
        test_device: TestDevice,
    ) -> None:
        """Publish aggregated NPI result to XDB after all iterations complete."""
        if not self.npi_name or not test_case_name:
            return
        if not npi_iteration_outcomes:
            self.logger.warning(
                f"NPI: no iteration outcomes recorded for {test_case_name}; "
                f"skipping NPI publish"
            )
            return
        self.logger.info(
            f"\033[36m[NPI]\033[0m Publishing result for "
            f"\033[1m{test_case_name}\033[0m "
            f"(npi={self.npi_name}, outcomes={npi_iteration_outcomes})"
        )
        try:
            # Upload playbook section log to everpaste for NPI tracking.
            # Use _last_completed_playbook_section since _current_playbook_section
            # is cleared at the end of each iteration in run_test_case teardown.
            test_log_url = ""
            section = (
                self._current_playbook_section or self._last_completed_playbook_section
            )
            if section is not None:
                try:
                    test_log_url = await self.test_summary.async_upload_section_logs(
                        section
                    )
                except Exception as e:
                    self.logger.warning(
                        f"NPI: failed to upload playbook log for {test_case_name}: {e}"
                    )
                if self.npi_name and test_case_name and npi_iteration_outcomes:
                    try:
                        scope = extract_scope_from_device(test_device)
                        await async_publish_npi_aggregated_result(
                            npi_name=self.npi_name,
                            playbook_name=test_case_name,
                            iteration_outcomes=npi_iteration_outcomes,
                            network_type=scope["network_type"],
                            device_role=scope["device_role"],
                            platform=scope["platform"],
                            overwrite_previous=self.overwrite_previous_results,
                        )
                    except Exception as e:
                        self.logger.warning(
                            f"NPI result publish failed (non-fatal): {e}"
                        )

            scope = extract_scope_from_device(test_device)
            self.logger.info(
                f"\033[36m[NPI]\033[0m Scope: network_type={scope['network_type']}, "
                f"device_role={scope['device_role']}, platform={scope['platform']}"
            )
            await async_publish_npi_aggregated_result(
                npi_name=self.npi_name,
                playbook_name=test_case_name,
                iteration_outcomes=npi_iteration_outcomes,
                network_type=scope["network_type"],
                device_role=scope["device_role"],
                platform=scope["platform"],
                overwrite_previous=self.overwrite_previous_results,
                test_log_url=test_log_url,
                logger=self.logger,
            )
        except Exception as e:
            self.logger.warning(f"NPI result publish failed (non-fatal): {e}")

    def check_failure(self, test_case_results: t.List[TestResult]) -> bool:
        return any(
            result.test_status in [hc_status.name for hc_status in FAILED_HC_STATUSES]
            for result in test_case_results
        )

    async def initialize_and_setup_snapshot_checks(
        self,
        snapshot_checks: t.List[taac_types.SnapshotHealthCheck],
        test_device: TestDevice,
    ) -> t.List[AbstractSnapshotHealthCheck]:
        checks = []
        for check in snapshot_checks:
            check_impl = NAME_TO_HEALTH_CHECK[check.name]
            if check_impl not in SNAPSHOT_HEALTH_CHECKS:
                raise ValueError(
                    f"{check_impl} is not a valid snapshot health check. Please check the list of supported snapshot health checks"
                )
            input_struct = HEALTH_CHECK_NAME_TO_INPUT[check.name]
            check_input = (
                json_to_thrift(check.input_json, input_struct)
                if check.input_json
                else None
            )
            default_input = input_struct()
            if issubclass(check_impl, AbstractDeviceSnapshotHealthCheck):
                obj = test_device
            elif issubclass(check_impl, AbstractTopologySnapshotHealthCheck):
                obj = self.topology
            else:
                raise
            checks.append(
                # pyrefly: ignore [bad-argument-type]
                check_impl(
                    # pyrefly: ignore [bad-argument-type]
                    obj=obj,
                    input=check_input or default_input,
                    check_params=self.parameter_evaluator.evaluate(check.check_params),
                    pre_snapshot_checkpoint_id=check.pre_snapshot_checkpoint_id
                    or DEFAULT_PRE_SNAPSHOT_CHECKPOINT_ID,
                    post_snapshot_checkpoint_id=check.post_snapshot_checkpoint_id
                    or DEFAULT_POST_SNAPSHOT_CHECKPOINT_ID,
                    logger=self.logger,
                )
            )
        await asyncio.gather(*[check.setup(obj) for check in checks])  # pyre-ignore
        # pyrefly: ignore [bad-return]
        return checks

    async def async_run_snapshot_checks(
        self,
        snapshot_checks: t.List[AbstractSnapshotHealthCheck],
        id: str,
        current_timestamp: int,
        test_case_results: t.List[TestResult],
        test_case_name: str,
    ) -> None:
        for check in snapshot_checks:
            if check._pre_snapshot_checkpoint_id == id:
                self.logger.info(
                    f"  [Snapshot] Capturing pre-snapshot: {check.__class__.CHECK_NAME.name}"
                )
                check._pre_snapshot = await check._capture_pre_snapshot(
                    check._obj, check._input, check._check_params, current_timestamp
                )
            elif check._post_snapshot_checkpoint_id == id:
                self.logger.info(
                    f"  [Snapshot] Capturing post-snapshot: {check.__class__.CHECK_NAME.name}"
                )
                check._post_snapshot = await check._capture_post_snapshot(
                    check._obj, check._input, check._check_params, current_timestamp
                )
                if check._pre_snapshot is ...:
                    self.logger.warning(
                        f"  [Snapshot] Skipping comparison for {check.__class__.CHECK_NAME.name}: "
                        f"pre-snapshot was never captured (checkpoint '{check._pre_snapshot_checkpoint_id}' did not fire)"
                    )
                    continue
                self.logger.info(
                    f"  [Snapshot] Comparing snapshots: {check.__class__.CHECK_NAME.name}"
                )
                check_result = await check._compare_snapshots(
                    check._obj,
                    check._input,
                    check._check_params,
                    check._pre_snapshot,
                    check._post_snapshot,
                )
                test_result = await async_write_test_result(
                    test_case_name,
                    devices=(
                        [check._obj]
                        if isinstance(check, AbstractDeviceSnapshotHealthCheck)
                        else check._obj.devices
                    ),
                    test_status=check_result.status,
                    check_stage=taac_types.ValidationStage.SNAPSHOT,
                    start_time=check._post_snapshot.timestamp,
                    end_time=check._post_snapshot.timestamp,
                    check_name=check.__class__.CHECK_NAME.name,
                    message=check_result.message,
                )
                test_case_results.append(test_result)

    def _get_stage_display_name(self, stage: taac_types.Stage) -> str:
        """Get a human-readable display name for a stage.

        Priority:
        1. stage.description (user-defined description)
        2. stage.id (if it looks like a meaningful name, not a UUID)
        3. Falls back to 'Stage <id>'
        """
        if stage.description:
            return stage.description
        if stage.id:
            # Check if the ID looks like a UUID (32 hex chars)
            # If so, use a generic "Stage" prefix; otherwise use the ID as-is
            if len(stage.id) == 32 and all(c in "0123456789abcdef" for c in stage.id):
                return f"Stage {stage.id}"
            return stage.id
        return "Unnamed Stage"

    async def _log_post_test_results(
        self, test_case_results: t.List[TestResult]
    ) -> None:
        """Log a summary table of POST_TEST health check results.

        Filters test_case_results to only include POST_TEST checks and logs
        them in a formatted table showing check name, status, and any failure message.
        For failed checks, uploads the full failure details to Everpaste and
        appends the URL to the message.
        """
        # Filter for POST_TEST health check results
        post_test_results = [
            result
            for result in test_case_results
            if result.check_stage and "POST_TEST" in str(result.check_stage)
        ]

        if not post_test_results:
            return

        # Format results for the table
        formatted_results = []
        for result in post_test_results:
            status = result.test_status or "UNKNOWN"
            # Normalize status display
            if status.upper() in ("PASS", "PASSED", "SUCCESS"):
                display_status = "PASS"
            elif status.upper() in ("FAIL", "FAILED", "FAILURE"):
                display_status = "FAIL"
            else:
                display_status = status

            message = result.message or ""

            # For failed checks, upload details to Everpaste and append URL
            if display_status == "FAIL" and message:
                try:
                    detail_lines = [
                        f"Health Check: {result.check_name}",
                        f"Device: {result.hostnames or 'N/A'}",
                        f"Stage: {result.check_stage or 'N/A'}",
                        f"Time: {result.start_time} - {result.end_time}",
                        "",
                        "Details:",
                        message,
                    ]
                    url = await async_everpaste_str("\n".join(detail_lines))
                    message = f"{message}  |  Details: {url}"
                except Exception:
                    pass

            formatted_results.append(
                {
                    "check_name": result.check_name or "Unknown",
                    "status": display_status,
                    "message": message,
                }
            )

        log_results_table(
            title="POST-HEALTH CHECK RESULTS",
            results=formatted_results,
            logger=self.logger,
        )

    def _log_failed_health_checks(self, failed_checks: t.List[TestResult]) -> None:
        """Log detailed information about failed health checks."""
        self.logger.info("=" * 80)
        self.logger.info(f"{'FAILED HEALTH CHECK DETAILS':^80}")
        self.logger.info("=" * 80)
        self.logger.info("")

        for i, check in enumerate(failed_checks, 1):
            self.logger.info(f"  [{i}] {check.check_name or 'Unknown Check'}")
            self.logger.info(f"      Stage: {check.check_stage or 'N/A'}")
            self.logger.info(f"      Device: {check.hostnames or 'N/A'}")
            self.logger.info(f"      Time: {check.start_time} - {check.end_time}")
            if check.message:
                # Log full message, splitting long messages across lines
                msg_lines = check.message.split("\n")
                for j, line in enumerate(msg_lines[:10]):  # Limit to 10 lines
                    prefix = "      Error: " if j == 0 else "             "
                    self.logger.info(f"{prefix}{line[:100]}")
                if len(msg_lines) > 10:
                    self.logger.info(
                        f"             ... ({len(msg_lines) - 10} more lines)"
                    )
            self.logger.info("")

        self.logger.info("=" * 80)
        self.logger.info("")

    async def async_run_stage(
        self,
        stage: taac_types.Stage,
        test_device: TestDevice,
        test_case_name: str,
        test_case_start_time: int,
        test_case_results: t.List[TestResult],
    ) -> None:
        stage_name = self._get_stage_display_name(stage)
        stage_section = self.test_summary.start_section(stage_name, indent_level=1)
        stage_start_time = time.time()
        self.logger.info("")
        self.logger.info(f"\033[1m\033[33m  {'─' * 50}\033[0m")
        self.logger.info(
            f"\033[1m\033[33m  Stage: {stage_name}\033[0m"
            f" \033[2m(x{stage.iteration} iteration(s))\033[0m"
        )
        step_names = [s.name.name if s.name else "unknown" for s in (stage.steps or [])]
        for i, name in enumerate(step_names):
            connector = "└─" if i == len(step_names) - 1 else "├─"
            self.logger.info(f"\033[36m    {connector} {name}\033[0m")
        self.logger.info(f"\033[1m\033[33m  {'─' * 50}\033[0m")
        step_names = [s.name.name if s.name else "unknown" for s in (stage.steps or [])]
        self.logger.info(
            f"\033[36m  ├─ Steps: \033[0m{', '.join(step_names)}"
            f" \033[2m(x{stage.iteration} iteration(s))\033[0m"
        )
        _stage_error = None
        try:
            for _ in range(stage.iteration):
                if stage.concurrent:
                    concurrent_steps = stage.concurrent_steps
                    if not concurrent_steps and stage.steps:
                        # Wrap each step as its own ConcurrentStep so they
                        # run in parallel when only steps= + concurrent=True
                        # is set (no explicit concurrent_steps).
                        concurrent_steps = [
                            taac_types.ConcurrentStep(steps=[s]) for s in stage.steps
                        ]
                    await self.initialize_and_run_concurrent_steps(
                        none_throws(concurrent_steps),
                        test_device,
                        test_case_name,
                        test_case_start_time,
                        test_case_results,
                    )
                else:
                    await self.initialize_and_run_steps(
                        stage.steps,
                        test_device,
                        test_case_name,
                        test_case_start_time,
                        test_case_results,
                    )
        except Exception as e:
            _stage_error = e
            raise
        finally:
            stage_duration = time.time() - stage_start_time
            log_phase_end(
                stage_name,
                duration_secs=stage_duration,
                logger=self.logger,
            )
            if _stage_error:
                self.test_summary.end_section(
                    stage_section, SectionStatus.FAIL, str(_stage_error)
                )
            else:
                self.test_summary.end_section(stage_section, SectionStatus.PASS)

    async def _resolve_npi_playbooks(
        self,
    ) -> t.List[taac_types.Playbook]:
        """Resolve playbooks to run based on NPI module + status filters.

        Queries XDB for the NPI's test cases in the requested modules,
        filters by status, then maps to playbooks in the test config.
        Skips and logs test cases that are 'skipped' in XDB or have no
        playbook_name in the UTP catalog.
        """
        from taac.utp import npi_xdb

        self.logger.info("")
        self.logger.info(f"\033[1m\033[36m{'=' * 70}\033[0m")
        self.logger.info(
            "\033[1m\033[36m  NPI Module Selection: "
            f"modules={self.npi_modules}, status={self.npi_status}\033[0m"
        )
        self.logger.info(f"\033[1m\033[36m{'=' * 70}\033[0m")

        # Fetch test cases from XDB for the requested modules
        all_npi_rows: t.List[t.Dict[str, t.Any]] = []
        for module in self.npi_modules:
            rows = await npi_xdb.get_npi_test_cases(
                npi_name=self.npi_name,
                module=module,
            )
            all_npi_rows.extend(rows)

        if not all_npi_rows:
            self.logger.warning(
                f"NPI '{self.npi_name}': no test cases found for "
                f"modules {self.npi_modules}. No playbooks will run."
            )
            return []

        # Build catalog lookup: test_case_id -> UTPTestCase
        catalog_by_id = {tc.id: tc for tc in UTP_TEST_CATALOG}

        # Build test config playbook lookup
        config_playbooks = {pb.name: pb for pb in self.test_config.playbooks}

        # Filter by status and resolve to playbooks
        target_playbook_names: t.List[str] = []
        skipped_cases: t.List[str] = []
        no_playbook_cases: t.List[str] = []
        no_config_playbook_cases: t.List[str] = []
        status_filtered_out: t.List[str] = []
        seen_tc_ids: t.Set[str] = set()

        for row in all_npi_rows:
            tc_id = str(row.get("test_case_id", ""))
            xdb_status = str(row.get("status", "pending"))
            module = str(row.get("module", ""))

            # Deduplicate: same test case may appear across multiple scopes
            if tc_id in seen_tc_ids:
                continue
            seen_tc_ids.add(tc_id)

            # Always skip 'skipped' test cases
            if xdb_status == "skipped":
                skipped_cases.append(f"{tc_id} ({module})")
                continue

            # Filter by requested status
            if self.npi_status != "all" and xdb_status != self.npi_status:
                status_filtered_out.append(f"{tc_id} ({module}, status={xdb_status})")
                continue

            # Look up the UTP catalog entry to get the playbook name
            catalog_tc = catalog_by_id.get(tc_id)
            if catalog_tc is None or not catalog_tc.playbook_name:
                no_playbook_cases.append(f"{tc_id} ({module})")
                continue

            playbook_name = catalog_tc.playbook_name
            # Check if this playbook exists in the test config
            if playbook_name not in config_playbooks:
                no_config_playbook_cases.append(
                    f"{tc_id} ({module}) -> {playbook_name}"
                )
                continue

            if playbook_name not in target_playbook_names:
                target_playbook_names.append(playbook_name)

        # Log what was skipped/excluded
        if skipped_cases:
            self.logger.info(
                f"\033[2m  Skipping {len(skipped_cases)} test case(s) "
                f"marked 'skipped' in NPI:\033[0m"
            )
            for case in skipped_cases:
                self.logger.info(f"\033[2m    – {case}\033[0m")

        if no_playbook_cases:
            self.logger.warning(
                f"  Skipping {len(no_playbook_cases)} test case(s) "
                f"with no playbook_name in UTP catalog:"
            )
            for case in no_playbook_cases:
                self.logger.warning(f"    – {case}")

        if no_config_playbook_cases:
            self.logger.warning(
                f"  Skipping {len(no_config_playbook_cases)} test case(s) "
                f"whose playbook is not in the test config:"
            )
            for case in no_config_playbook_cases:
                self.logger.warning(f"    – {case}")

        if status_filtered_out:
            self.logger.info(
                f"\033[2m  Filtered out {len(status_filtered_out)} test case(s) "
                f"not matching status='{self.npi_status}':\033[0m"
            )
            for case in status_filtered_out:
                self.logger.info(f"\033[2m    – {case}\033[0m")

        if target_playbook_names:
            self.logger.info(
                f"\033[32m  Resolved {len(target_playbook_names)} playbook(s) "
                f"to run:\033[0m"
            )
            for name in target_playbook_names:
                self.logger.info(f"\033[32m    ▸ {name}\033[0m")
        else:
            self.logger.warning(
                "  No playbooks resolved from NPI filters. Nothing to run."
            )

        return [config_playbooks[name] for name in target_playbook_names]

    async def run_tests(
        self,
        playbooks: t.Optional[t.List[t.Union[str, taac_types.Playbook]]] = None,
        duts: t.Optional[t.List[str]] = None,
    ) -> None:
        """
        By default, all playbooks defined in the test config are ran.
        However, users can choose to run specific playbooks and select DUT
        on which to run the tests.

        When --npi-modules and --npi-status are provided, playbooks are
        auto-resolved from the NPI catalog instead.
        """
        # NPI module-based playbook selection
        if self.npi_name and self.npi_modules and self.npi_status:
            npi_playbooks = await self._resolve_npi_playbooks()
            if not npi_playbooks:
                self.logger.warning("No playbooks to run from NPI selection.")
                return
            # pyre-fixme[9]: playbooks has type `Optional[List[Union[str,
            #  Playbook]]]`; used as `List[Playbook]`.
            playbooks = npi_playbooks
            # Fall through to normal execution with resolved playbooks
        else:
            all_playbooks = {
                playbook.name: playbook for playbook in self.test_config.playbooks
            }
            playbooks = [
                (all_playbooks[playbook] if isinstance(playbook, str) else playbook)
                for playbook in playbooks or self.test_config.playbooks
            ]
        duts = none_throws(duts or self.duts)
        # pyre-fixme[16]: `Optional` has no attribute `__iter__`.
        enabled_playbooks = [p for p in playbooks if p.enabled]
        total_playbooks = len(enabled_playbooks)
        failed_playbooks: t.List[t.Tuple[str, str, Exception]] = []
        for dut in duts:
            # pyrefly: ignore [missing-attribute]
            test_device = self.topology.get_device_by_name(dut)
            for pb_idx, playbook in enumerate(enabled_playbooks, 1):
                self.logger.info("")
                self.logger.info(f"\033[1m\033[36m{'=' * 70}\033[0m")
                self.logger.info(
                    # pyrefly: ignore [missing-attribute]
                    f"\033[1m\033[36m  [{pb_idx}/{total_playbooks}] "
                    f"{playbook.name} | {dut}\033[0m"
                )
                self.logger.info(f"\033[1m\033[36m{'=' * 70}\033[0m")
                # pyrefly: ignore [bad-assignment]
                self._current_playbook = playbook
                try:
                    # pyrefly: ignore [bad-argument-type]
                    await self.run_test_case(playbook, test_device)
                except Exception as e:
                    # pyrefly: ignore [missing-attribute]
                    failed_playbooks.append((playbook.name, dut, e))
                    self.logger.error(
                        # pyrefly: ignore [missing-attribute]
                        f"\033[31m  Playbook '{playbook.name}' failed on "
                        f"{dut}: {e}\033[0m"
                    )
                    self.logger.info(
                        f"\033[33m  Continuing to next playbook "
                        f"({pb_idx}/{total_playbooks} complete)...\033[0m"
                    )
        if failed_playbooks:
            # Include each failed playbook's exception message in the outer
            # TestCaseFailure so the per-HC detail (introduced in D107926440
            # for the inner TestCaseFailure at line 1827) propagates through
            # to test_case_compiler.py → AssertionError → pyunit/Sandcastle.
            # Without this, the outer wrapper would collapse to
            # "N playbook(s) failed: <names>" and downstream consumers would
            # see a uninformative AssertionError that requires log-diving.
            # The `from failed_playbooks[-1][2]` chain is preserved so the
            # full traceback remains available, but it's no longer the only
            # carrier of the actual failure reason.
            detail_lines = [
                f"- {name} ({dut}): {exc}" for name, dut, exc in failed_playbooks
            ]
            raise TestCaseFailure(
                f"{len(failed_playbooks)} playbook(s) failed:\n"
                + "\n".join(detail_lines)
            ) from failed_playbooks[-1][2]

    async def run_steps(
        self,
        steps: t.List[Step],
        iteration: int = 1,
    ) -> None:
        for _ in range(iteration):
            for step_obj in steps:
                try:
                    await self.run_step(step_obj)
                except Exception as e:
                    self.logger.error(
                        f"Step {step_obj.STEP_NAME.name} failed on {step_obj.device.name}: {e}"
                    )
                    raise e

    async def run_step(
        self,
        step: Step,
    ) -> None:
        step_name = step.step.name.name if step.step.name else "unknown"
        device_name = step.device.name if step.device else "unknown"
        _step_start = time.time()
        self.logger.info("")
        self.logger.info(
            f"\033[33m    ▶ {step_name}\033[0m on \033[36m{device_name}\033[0m"
        )
        stage_context = (
            f"stage.{self._current_stage.id}"
            if self._current_stage is not ... and hasattr(self._current_stage, "id")
            else "setup"
        )

        with suppress_console_logs(self.logger):
            await self.async_run_snapshot_checks(
                self._current_snapshot_checks,
                f"{stage_context}.step.{step.name}.start",
                int(time.time()),
                step.test_case_results,
                self._current_playbook.name,
            )
            retryable_run = async_retryable(
                retries=step.step.retryable_num,
                sleep_time=step.step.retryable_delay,
                exceptions=(Exception,),
            )(step._run)
            await retryable_run(step._input, step._step_params)
        _step_elapsed = time.time() - _step_start
        self.logger.info(
            f"\033[32m    ✓ {step_name}\033[0m \033[2m({_step_elapsed:.0f}s)\033[0m"
        )
        with suppress_console_logs(self.logger):
            await self.async_run_snapshot_checks(
                self._current_snapshot_checks,
                f"{stage_context}.step.{step.name}.end",
                int(time.time()),
                step.test_case_results,
                self._current_playbook.name,
            )
        if step.step.delay:
            self.logger.info(
                f"\033[2m    ⏳ Post-step delay: {step.step.delay}s...\033[0m"
            )
            await asyncio.sleep(step.step.delay)

    async def async_test_case_setUp(
        self, playbook: taac_types.Playbook, test_device: TestDevice
    ) -> None:
        # Executed at the beginning of each test
        self.fail_on_periodic_task_error_if_exists(self.periodic_task_executor)
        self.test_case_uuid = uuid.uuid4().hex
        self.parameter_evaluator.set_cache_uuid(self.test_case_uuid)
        ixia = self.ixia
        if ixia:
            ixia.test_case_uuid = self.test_case_uuid
            if playbook.backup_and_restore_ixia_config:
                ixia.export_and_save_config()
            if playbook.traffic_items_to_configure:
                for (
                    traffic_item_name,
                    settings,
                ) in playbook.traffic_items_to_configure.items():
                    ixia.configure_traffic_items_on_the_fly(
                        traffic_item_name,
                        settings.line_rate,
                        settings.line_rate_type,
                        settings.frame_size_settings,
                        settings.qos_config,
                    )
                    ixia.apply_traffic()
            ixia.enable_traffic(
                playbook.traffic_items_to_start
                or self.test_config.traffic_items_to_start
            )
            # Regenerate and reapply all enabled traffic items so that
            # configuration changes (DSCP, frame size, line rate) and
            # enable/disable state are fully committed before traffic starts.
            ixia.regenerate_traffic_items()
            ixia.apply_traffic()
            ixia.wait_for_view_assistants_ready()
            if not self.started_capture:
                ixia.start()
                self.started_capture = True
            else:
                ixia.paused = False
            await asyncio.sleep(10)
        # Run custom test case set up logics
        for handler in self.custom_test_handlers:
            await handler._async_test_case_setUp()
        if playbook.periodic_tasks:
            self.test_case_periodic_task_executor = PeriodicTaskExecutor(
                list(playbook.periodic_tasks),
                self.logger,
                self.ixia,
            )
            self.test_case_periodic_task_executor.create_periodic_tasks()
        if not self.skip_fboss_rsyslog:
            await self.async_create_fboss_ryslog_configuration()

    def convert_unixtime_to_log_timestamp(self, unix_time: int) -> str:
        """
        Timestamps in the log files are in the format of "Jan  1 00:00:00"
        """
        dt = datetime.fromtimestamp(unix_time)
        # Convert datetime object to desired format
        converted_timestamp = dt.strftime("%b %e %H:%M:%S")
        return converted_timestamp

    def get_fboss_hosts(self, hosts: t.List[TestDevice]) -> t.List[str]:
        return [
            host.name for host in hosts if host.attributes.operating_system == "FBOSS"
        ]

    async def async_fboss_collect_and_print_logs(
        self,
        start_time: int,
    ) -> None:
        log_subsection("Collecting Device Logs", logger=self.logger)
        start_timestamp = self.convert_unixtime_to_log_timestamp(start_time)
        end_timestamp = self.convert_unixtime_to_log_timestamp(int(time.time()))
        # pyrefly: ignore [missing-attribute]
        fboss_hosts = self.get_fboss_hosts(self.topology.devices)
        # Prepare coroutines for all hosts
        coros = [
            self.async_collect_logs_for_host(hostname, start_timestamp, end_timestamp)
            for hostname in fboss_hosts
        ]
        # Run all host log collections in parallel
        agent_logs = await asyncio.gather(*coros)
        flattened_logs = []
        for host_logs in agent_logs:
            flattened_logs.extend(host_logs)

        agent_logs_table = tabulate(
            flattened_logs,
            headers=["Device", "Service", "Logs URL"],
            tablefmt="grid",
        )
        self.logger.info(f"Binary log files:\n {agent_logs_table}")

    async def async_collect_logs_for_host(
        self,
        hostname: str,
        start_timestamp: str,
        end_timestamp: str,
    ) -> list:
        rsyslog_services = self.device_to_rsyslog_services.get(hostname, [])
        driver = await async_get_device_driver(hostname)
        # pyre-fixme[16]: `AbstractSwitch` has no attribute `async_is_netos`.
        is_netos = await driver.async_is_netos()

        log_timeout = getattr(self.test_config, "log_collection_timeout", 180)

        max_everpaste_size = 50 * 1024 * 1024  # 50MB
        results = []
        for service in rsyslog_services:
            service_name = taac_types.SERVICE_NAME_MAP[service]
            try:
                if is_netos:
                    self.logger.info(f"Capturing logs for {service_name} on {hostname}")
                    file_name = f"{FBOSS_LOG_DIR}/{service_name}.log"
                    cmd = f'awk \'$0 >= "{start_timestamp}" && $0 <= "{end_timestamp}"\' {file_name}'
                    output = await asyncio.wait_for(
                        driver.async_run_cmd_on_shell(cmd), timeout=log_timeout
                    )
                else:
                    log_file_name = f"{DNE_LOG_DIR}/{service_name}.log"
                    output = await asyncio.wait_for(
                        driver.async_read_file(log_file_name), timeout=log_timeout
                    )
                if len(output) > max_everpaste_size:
                    original_size = len(output)
                    output = output[-max_everpaste_size:]
                    self.logger.warning(
                        f"Log for {hostname} {service_name} truncated from "
                        f"{original_size} to {max_everpaste_size} chars "
                        f"(keeping tail)"
                    )
                # The Everpaste URL is already a clickable internalfb.com link;
                # don't additionally shorten it through the throttled fburl tier
                # (this collects per host x service at test-case teardown).
                everpaste_url = await async_everpaste_str(output)
                results.append((hostname, service_name, everpaste_url))
            except asyncio.TimeoutError:
                self.logger.error(
                    f"Timeout ({log_timeout}s) while collecting logs for {hostname} {service_name}"
                )
                results.append((hostname, service_name, f"Timeout ({log_timeout}s)"))
            except Exception as e:
                self.logger.error(
                    f"Error collecting logs for {hostname} {service_name}: {e}"
                )
                results.append((hostname, service_name, f"Error: {e}"))
        return results

    async def async_test_case_tearDown(
        self,
        playbook: taac_types.Playbook,
        test_device: TestDevice,
        test_case_results: t.List[TestResult],
        test_case_start_time: int,
    ) -> None:
        # Executed at the end of each test
        ixia = self.ixia
        test_case_name = playbook.name
        if ixia:
            ixia.paused = True
            ixia.log_to_scuba_ixia_packet_loss(
                self.test_case_uuid,
            )
            ixia.enable_traffic(
                playbook.traffic_items_to_start
                or self.test_config.traffic_items_to_start,
                enable=False,
            )
            if playbook.backup_and_restore_ixia_config:
                ixia.import_saved_config()
        if self.test_case_periodic_task_executor:
            await self.async_run_periodic_task_checks(
                test_case_results,
                test_device,
                test_case_name,
                test_case_start_time,
                self.test_case_periodic_task_executor,
            )
        test_case_raise = None
        try:
            if test_case_results:
                log_subsection(
                    f"Test Case Results: {test_device.name}",
                    logger=self.logger,
                )
                self.logger.info(f"\n{tabulate_test_results(test_case_results)}")
                self.test_run_results.extend(test_case_results)
                if self.check_failure(test_case_results):
                    await self.async_fboss_collect_and_print_logs(test_case_start_time)
                    # Only mark as postcheck failure if ALL failures
                    # are from POST_TEST health checks. Pre-check failures
                    # and stage execution errors remain as ERROR.
                    failed_statuses = [
                        hc_status.name for hc_status in FAILED_HC_STATUSES
                    ]
                    failed_results = [
                        result
                        for result in test_case_results
                        if result.test_status in failed_statuses
                    ]
                    postcheck_only = bool(failed_results) and all(
                        result.check_stage is not None
                        and "POST_TEST" in str(result.check_stage)
                        for result in failed_results
                    )
                    # Thread per-HC failure_detail into the exception so the
                    # specific reason (e.g. "queue 9 7.11 pps below threshold
                    # 10") flows through TestCaseFailure → AssertionError →
                    # pyunit → Sandcastle/Conveyor instead of being collapsed
                    # to "Please check the logs for more details". Without
                    # this, every TAAC HC failure looks identical in the UI
                    # and consumers have to dig into worker logs.
                    hc_details = "\n".join(
                        f"  - {result.check_name or '<unnamed>'} "
                        f"({result.check_stage or '<unknown_stage>'}): "
                        f"{result.message or '<no detail>'}"
                        for result in failed_results
                    )
                    raise TestCaseFailure(
                        f"Health check failed for {test_case_name} on "
                        f"{test_device.name} ({len(failed_results)} "
                        f"failing check(s)):\n{hc_details}",
                        is_postcheck_failure=postcheck_only,
                    )
        except TestCaseFailure as e:
            test_case_raise = e

        # Run custom test case tear down logics
        for handler in self.custom_test_handlers:
            await handler._async_test_case_tearDown()
        if not self.skip_fboss_rsyslog:
            await self.async_delete_fboss_ryslog_configuration()
        await self.teardown_period_task_executor_if_exists(
            self.test_case_periodic_task_executor, skip_log_upload=True
        )
        test_case_periodic_task_executor_raise = None
        try:
            self.fail_on_periodic_task_error_if_exists(
                self.test_case_periodic_task_executor
            )
        except TestCaseFailure as e:
            test_case_periodic_task_executor_raise = e

        periodic_task_executor_raise = None
        try:
            self.fail_on_periodic_task_error_if_exists(self.periodic_task_executor)
        except TestCaseFailure as e:
            periodic_task_executor_raise = e
        # Combine all exceptions into a single raise
        exceptions = [
            exc
            for exc in [
                test_case_raise,
                test_case_periodic_task_executor_raise,
                periodic_task_executor_raise,
            ]
            if exc is not None
        ]
        # Finalize playbook section in test summary
        if self._current_playbook_section is not None:
            if exceptions:
                self.test_summary.end_section(
                    self._current_playbook_section,
                    SectionStatus.FAIL,
                    "; ".join(str(e) for e in exceptions),
                )
            else:
                self.test_summary.end_section(
                    self._current_playbook_section, SectionStatus.PASS
                )
            self._last_completed_playbook_section = self._current_playbook_section
            self._current_playbook_section = None

        # Record iteration outcome for NPI aggregation (published after all iterations)
        if self.npi_name and test_case_name:
            if exceptions:
                # Distinguish health check failures from unhandled errors
                has_hc_failure = self.check_failure(test_case_results)
                if has_hc_failure:
                    self._npi_iteration_outcomes.append(("failed", "health_check"))
                else:
                    self._npi_iteration_outcomes.append(("error", str(exceptions[0])))
            else:
                self._npi_iteration_outcomes.append(("passed", None))

        if exceptions:
            error_messages = [str(exc) for exc in exceptions]
            failure_string = "Failure detected in test case teardown:\n"
            combined_message = "\n".join([f"- {msg}" for msg in error_messages])
            # Propagate is_postcheck_failure if the primary failure was a postcheck
            is_postcheck = getattr(test_case_raise, "is_postcheck_failure", False)
            raise TestCaseFailure(
                failure_string + combined_message,
                is_postcheck_failure=is_postcheck,
            )

    async def async_create_fboss_ryslog_configuration(self) -> None:
        # pyrefly: ignore [missing-attribute]
        fboss_hosts = self.get_fboss_hosts(self.topology.devices)
        coroutines = []
        for host in fboss_hosts:
            driver = await async_get_device_driver(host)
            # pyre-fixme[16]: `AbstractSwitch` has no attribute `async_is_netos`.
            is_netos = await driver.async_is_netos()
            if is_netos:
                continue
            rsyslog_services = self.device_to_rsyslog_services.get(host, [])
            coroutines.append(
                async_create_rsyslog_configuration(host, rsyslog_services)
            )
        await asyncio.gather(*coroutines)

    async def async_delete_fboss_ryslog_configuration(self) -> None:
        # pyrefly: ignore [missing-attribute]
        fboss_hosts = self.get_fboss_hosts(self.topology.devices)
        coroutines = []
        for host in fboss_hosts:
            driver = await async_get_device_driver(host)
            # pyre-fixme[16]: `AbstractSwitch` has no attribute `async_is_netos`.
            is_netos = await driver.async_is_netos()
            if is_netos:
                continue
            rsyslog_services = self.device_to_rsyslog_services.get(host, [])
            coroutines.append(
                async_delete_rsyslog_configuration(host, rsyslog_services)
            )
        await asyncio.gather(*coroutines)

    async def _async_trigger_triage_minion(self) -> None:
        """Trigger the DNE PIT CI Triage Agent via Confucius Thrift API."""
        if TAAC_OSS:
            self.logger.info("Triage minion not available in OSS mode, skipping")
            return
        try:
            from urllib.parse import quote  # noqa: F811

            from confucius.confucius_service.clients import ConfuciusService
            from confucius.confucius_service.types import (
                ContentType,
                Message,
                MessageContent,
                MessageContext,
                MessageStatus,
                MessageType,
                NewSessionRequest,
                RunStatus,
                SessionType,
                TextInputResponse,
                TextInputResponseType,
                WriteRequest,
            )
            from libfb.py.employee import get_current_unix_user_fbid
            from servicerouter.py3 import ClientParams, get_sr_client

            AGENT_NAME = "DNE PIT CI Triage Agent"
            CF_PROD_TIER = "confucius.server.prod"

            # Collect full logs from the test summary
            all_logs = self.test_summary._log_handler.get_all_logs()

            # Build the prompt with test run context
            test_config_name = (
                self.test_config.name if self.test_config.name else "unknown"
            )
            failed_sections = [
                s.name
                for s in self.test_summary.sections
                if s.status == SectionStatus.FAIL
            ]
            prompt = (
                f"Analyze the following TAAC test run logs and provide a detailed "
                f"analysis of all failures. Include root cause analysis, identify "
                f"whether failures are infrastructure issues or genuine test failures, "
                f"and suggest next steps.\n\n"
                f"Test Config: {test_config_name}\n"
                f"Failed Sections: {', '.join(failed_sections)}\n"
            )
            if self.npi_name:
                prompt += f"NPI: {self.npi_name}\n"
            prompt += f"\n--- TAAC Run Logs ---\n{all_logs}"

            self.logger.info("")
            self.logger.info(
                "\033[1m\033[35m  Triggering DNE PIT CI Triage Agent...\033[0m"
            )

            fbid = get_current_unix_user_fbid()
            params = ClientParams().setProcessingTimeoutMs(60000)

            # Create a new Confucius session
            new_session_request = NewSessionRequest(
                fbid=fbid,
                timeout_ms=3600 * 5 * 1000,
                warning_timeout_ms=3600 * 5 * 1000 - 600_000,
                namespace_id=[],
                type=SessionType.CHAT,
            )
            async with get_sr_client(
                ConfuciusService, CF_PROD_TIER, params=params
            ) as cf_client:
                response = await cf_client.newSession(new_session_request)
                session_uuid = response.session.uuid

            # Send the prompt to the agent
            context = MessageContext(
                entry_name=AGENT_NAME,
                run_status=RunStatus.UNKNOWN,
            )
            text_input_response = TextInputResponse(
                input=prompt,
                type=TextInputResponseType.NORMAL,
                entry_name=AGENT_NAME,
            )
            message_content = MessageContent(
                type=ContentType.TEXT_INPUT_RESPONSE,
                context=context,
                text_input_response=text_input_response,
            )
            message = Message(
                uuid="",
                session_uuid=session_uuid,
                type=MessageType.HUMAN,
                content=message_content,
                status=MessageStatus.UNREAD,
            )
            write_request = WriteRequest(fbid=fbid, message=message)

            async with get_sr_client(
                ConfuciusService, CF_PROD_TIER, params=params
            ) as cf_client:
                await cf_client.write(write_request)

            # Build the Confucius UI URL
            session_url = (
                f"https://www.internalfb.com/confucius"
                f"?session_id={session_uuid}"
                f"&entry_name={quote(AGENT_NAME)}"
                f"&tab=Chat"
            )

            self.logger.info(
                "\033[1m\033[35m  Triage Agent triggered successfully!\033[0m"
            )
            self.logger.info(
                f"\033[1m\033[35m  Follow the analysis: {session_url}\033[0m"
            )
            self.logger.info("")
        except Exception as e:
            self.logger.warning(f"Failed to trigger triage minion (non-fatal): {e}")

    async def _async_collect_ixia_diagnostics_if_enabled(self, ixia: TaacIxia) -> None:
        """Run IxiaDiagnosticsCollectionTask when the CLI flag opts in.

        Best-effort: any failure is logged and swallowed so diagnostics never
        turn a green test red. Must run BEFORE
        `test_setup_orchestrator.async_tearDown()` so the Ixia object still has
        live chassis credentials. Skipped entirely in TAAC_OSS mode (no Manifold).
        """
        if not self.collect_ixia_diagnostics or TAAC_OSS:
            return
        try:
            task = IxiaDiagnosticsCollectionTask(
                hostname=ixia.primary_chassis_ip,
                description="Ixia diagnostics teardown collection",
                ixia=ixia,
                logger=self.logger,
                shared_data=self.shared_task_data,
            )
            await task.run({"run_id": self.test_config.name})
        except Exception as exc:
            self.logger.error(
                f"ixia diagnostics: collection task raised "
                f"(swallowed to protect teardown): {exc!r}"
            )

    async def async_test_tearDown(self) -> None:
        log_section("TEST CONFIG TEARDOWN", logger=self.logger)
        teardown_start = time.time()
        teardown_section = self.test_summary.start_section("TEST CONFIG TEARDOWN")
        _teardown_error = None
        try:
            with suppress_console_logs(self.logger):
                await self.teardown_period_task_executor_if_exists(
                    self.periodic_task_executor
                )
                ixia = self.ixia
                if ixia:
                    ixia.capturing = False
                    await self._async_collect_ixia_diagnostics_if_enabled(ixia)
                await self.test_setup_orchestrator.async_tearDown()
                for handler in self.custom_test_handlers:
                    await handler._async_test_tearDown()
                await self.run_tasks(
                    # pyrefly: ignore [bad-argument-type]
                    self.test_config.teardown_tasks or []
                    if not (self.skip_all_tasks or self.skip_teardown_tasks)
                    else []
                )
        except Exception as e:
            _teardown_error = e
        finally:
            log_phase_end(
                "TEST CONFIG TEARDOWN",
                duration_secs=time.time() - teardown_start,
                logger=self.logger,
            )
            if _teardown_error:
                self.test_summary.end_section(
                    teardown_section, SectionStatus.FAIL, str(_teardown_error)
                )
            else:
                self.test_summary.end_section(teardown_section, SectionStatus.PASS)
            # Generate and upload test execution summary - always print even on errors
            try:
                await self.test_summary.async_upload_and_log_summary()
            except Exception as e:
                self.logger.error(f"Failed to generate test summary: {e}")
            # Trigger triage minion if enabled and there were failures
            has_failures = _teardown_error is not None or any(
                s.status == SectionStatus.FAIL for s in self.test_summary.sections
            )
            if self.call_triage_minion and has_failures:
                await self._async_trigger_triage_minion()
            self.test_summary.cleanup()
        if _teardown_error:
            raise _teardown_error

    def get_checks_to_run(
        self,
        playbook_checks: t.Optional[t.Sequence[taac_types.PointInTimeHealthCheck]],
        test_config_checks: t.Optional[t.Sequence[taac_types.PointInTimeHealthCheck]],
        skip_test_config_checks: bool,
        checks_to_skip: t.Optional[t.Sequence[hc_types.CheckName]] = None,
        check_ids_to_skip: t.Optional[t.Sequence[str]] = None,
        override_duplicate_checks: bool = True,
    ) -> t.Sequence[taac_types.PointInTimeHealthCheck]:
        playbook_checks = playbook_checks or []
        test_config_checks = test_config_checks or []
        checks_to_run = []
        if skip_test_config_checks:
            checks_to_run = playbook_checks
        else:
            all_checks = list(test_config_checks) + list(playbook_checks)
            if override_duplicate_checks:
                checks_without_id = {
                    check.name: check
                    for check in test_config_checks
                    if not check.check_id
                }
                checks_without_id.update(
                    {
                        check.name: check
                        for check in playbook_checks
                        if not check.check_id
                    }
                )
                checks_with_id = [check for check in all_checks if check.check_id]
                checks_to_run = list(checks_without_id.values()) + checks_with_id
            else:
                checks_to_run = all_checks

        if checks_to_skip:
            checks_to_run = [
                check for check in checks_to_run if check.name not in checks_to_skip
            ]
        if check_ids_to_skip:
            checks_to_run = [
                check
                for check in checks_to_run
                if not check.check_id or check.check_id not in check_ids_to_skip
            ]
        return checks_to_run

    def fail_on_periodic_task_error_if_exists(
        self, periodic_task_executor: t.Optional[PeriodicTaskExecutor]
    ) -> None:
        if periodic_task_executor and periodic_task_executor.has_error():
            raise TestCaseFailure(
                "Periodic task has error. Please check the logs for more details"
            )

    async def teardown_period_task_executor_if_exists(
        self,
        periodic_task_executor: t.Optional[PeriodicTaskExecutor],
        skip_log_upload: bool = False,
    ) -> None:
        if periodic_task_executor:
            await periodic_task_executor.teardown(skip_log_upload=skip_log_upload)

    def _add_oss_mock_device_data(self) -> None:
        """Add OSS-compatible mock device data using string fields."""
        for host, device_info in (self.test_config.oss_mock_device_data or {}).items():
            add_oss_mock_device_data(host, device_info)

    def _add_host_to_device_os_type_data(self) -> None:
        for host, device_os_type in (self.test_config.host_os_type_map or {}).items():
            add_host_to_device_os_type_data(host, device_os_type)

    def _add_host_driver_args_data(self) -> None:
        for host, driver_args in (self.test_config.host_driver_args or {}).items():
            # pyrefly: ignore [bad-argument-type]
            add_host_to_driver_args_data(host, driver_args)

    async def async_run_periodic_task_checks(
        self,
        test_case_results: t.List[TestResult],
        test_device: TestDevice,
        test_case_name: str,
        test_case_start_time: int,
        periodic_task_executor: PeriodicTaskExecutor,
    ) -> None:
        # First, teardown all workers to generate everpaste log URLs
        for periodic_task_worker in periodic_task_executor.periodic_task_workers:
            await periodic_task_worker.teardown()

        # Now run final checks with log URLs available
        for periodic_task_worker in periodic_task_executor.periodic_task_workers:
            periodic_check_result = await periodic_task_worker.run_final_check()
            if periodic_check_result:
                # Append log URL to the message if available
                message = periodic_check_result.message
                if periodic_task_worker._log_everpaste_url:
                    message += f"\nLog: {periodic_task_worker._log_everpaste_url}"

                result = await async_write_test_result(
                    test_case_name,
                    devices=[test_device],
                    test_status=periodic_check_result.status,
                    start_time=test_case_start_time,
                    check_name=periodic_check_result.name,
                    # async_write_test_result already everpaste-shortens long
                    # messages (no fburl); pass it through directly instead of
                    # everpasting + fburl-ing here. This removes a duplicate
                    # upload and a per-worker fburl-tier call at every test-case
                    # teardown, and resolves the >100 vs >1000 gate conflict.
                    message=message,
                )
                test_case_results.append(result)
