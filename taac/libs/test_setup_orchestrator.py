# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import asyncio
import dataclasses
import json
import os
import re
import time
import typing as t

from taac.constants import (  # oss-rewrite (force ShipIt re-export to taac.* root)
    FbossPackage,
    TestTopology,
)
from taac.ixia.abstract_traffic_generator import (
    AbstractTrafficGenerator,
)
from taac.ixia.taac_ixia import TaacIxia
from taac.libs.ixia_candidate import (
    IxiaCandidate,
    normalize_ixia_candidates,
    select_ixia_candidates,
)
from taac.libs.ixia_config_cache_manager import (
    DEFAULT_IXIA_CONFIG_CACHE,
)
from taac.libs.oss_test_bed_chunker import OssTestBedChunker
from taac.libs.otg_traffic_generator import OtgTrafficGenerator
from taac.libs.traffic_generator import TrafficGenerator
from taac.utils.driver_factory import async_get_device_driver
from taac.utils.oss_taac_constants import (
    IxiaCandidateSetupError,
    IxiaFallbackExhaustedError,
)
from taac.utils.oss_taac_lib_utils import (
    ConsoleFileLogger,
    convert_to_async,
    none_throws,
)
from taac.utils.taac_log_formatter import (
    log_subsection,
    timed_phase,
)
from taac.test_as_a_config import types as taac_types

TAAC_OSS = os.environ.get("TAAC_OSS", "").lower() in ("1", "true", "yes")

_JQ_ENDPOINT_ACCESS_PATTERN = re.compile(
    r'(?P<dot>\.)(?P<dot_key>"(?:\\.|[^"\\])*")'
    r'|(?P<bracket>\.\s*\[\s*)(?P<bracket_key>"(?:\\.|[^"\\])*")'
    r"(?P<close>\s*\])"
)

if not TAAC_OSS:
    from taac.internal.test_bed_chunker import TestBedChunker


# IIE-2 260610 soft recovery of the IXIA REST API tier (`ixnetworkweb`
# platform app) when chassis hardware is healthy but the Jetty backend rejects
# new `SessionAssistant` creation with 5xx. Default-on for every TestConfig
# that does not opt out via an explicit
# `ixia_recovery=IxiaRecovery(enabled=False)` override. TestConfigs that
# intentionally exercise failure modes of `_create_basic_setup` (snake tests,
# anything probing the connect path) MUST opt out.
_DEFAULT_IXIA_RECOVERY: taac_types.IxiaRecovery = taac_types.IxiaRecovery(
    enabled=True,
    max_attempts=1,
    cooldown_minutes=30,
)


class TestSetupOrchestrator:
    def __init__(
        self,
        test_config: taac_types.TestConfig,
        logger: ConsoleFileLogger,
        ixia_api_server: t.Optional[str] = None,
        ixia_session_id: t.Optional[int] = None,
        skip_ixia_setup: bool = False,
        skip_ixia_cleanup: bool = False,
        skip_post_setup_wait: bool = False,
        skip_basset_reservation: bool = False,
        skip_testbed_isolation: bool = True,
        desired_pkg_versions: t.Optional[t.Dict[FbossPackage, str]] = None,
        dsf_sequential_update: bool = False,
        allow_disruptive_configs: bool = False,
        skip_package_update: bool = False,
        override_ixia_traffic_items: bool = False,
        cleanup_failed_setup: bool = True,
        eos_image_id: t.Optional[str] = None,
        clear_old_eos_images: bool = False,
        ixia_candidates: t.Optional[t.Sequence[IxiaCandidate]] = None,
        ixia_profile: str = "auto",
        trace_ixia_api: bool = False,
    ) -> None:
        self.test_config = test_config
        self.logger = logger
        # Ixia specific parameters and knobs
        # Ixia chassis ip address
        self._ixia_api_server = ixia_api_server
        # Ixia is required but the an ixia session has already been created.
        self._ixia_session_id = ixia_session_id
        # Ixia is not required. Primarily used for testing purposes
        self._skip_ixia_setup = skip_ixia_setup
        self._skip_ixia_cleanup = skip_ixia_cleanup
        self._skip_post_setup_wait = skip_post_setup_wait
        self._skip_basset_reservation = skip_basset_reservation
        self._skip_testbed_isolation = skip_testbed_isolation
        self._desired_pkg_versions = desired_pkg_versions or {}
        self._dsf_sequential_update = dsf_sequential_update
        self._allow_disruptive_configs = allow_disruptive_configs
        self._skip_package_update = skip_package_update
        self._override_ixia_traffic_items = override_ixia_traffic_items
        self._cleanup_failed_setup = cleanup_failed_setup
        self._trace_ixia_api = trace_ixia_api
        # EOS image ID for Arista device image deployment
        self._eos_image_id = eos_image_id or ""
        # Whether to clear old EOS images from flash before deployment
        self._clear_old_eos_images = clear_old_eos_images
        normalized_candidates = (
            tuple(ixia_candidates)
            if ixia_candidates
            else (normalize_ixia_candidates(test_config, ixia_api_server))
        )
        self.ixia_candidates = normalized_candidates
        self._ixia_candidates_to_try = select_ixia_candidates(
            normalized_candidates,
            ixia_profile,
            explicit_ixia_override=bool(ixia_api_server or ixia_session_id),
        )
        self.selected_ixia_candidate: t.Optional[IxiaCandidate] = None
        self._traffic_generator_backend = (
            "otg"
            if getattr(test_config, "traffic_generator_backend", None)
            == taac_types.TrafficGeneratorBackend.OTG
            else "restpy"
        )

        # The following are to be dynamically populated
        self.basset_butler: t.Any = None
        self._query_basset_butler: t.Any = None
        self._query_basset_resources: t.List[t.Any] = []
        self._query_reserved_device_names: t.Set[str] = set()
        self.ixia: t.Optional[AbstractTrafficGenerator] = None
        self.traffic_generator: t.Optional[TrafficGenerator] = None
        self.test_bed_chunker: t.Any = None
        self.test_topology: TestTopology = None  # pyre-ignore[8]

        self.devices_under_test: t.List[str] = [
            endpoint.name
            for endpoint in self.ixia_candidates[0].endpoints
            if endpoint.dut
        ]

    @property
    def ixia_candidates_to_try(self) -> t.Tuple[IxiaCandidate, ...]:
        return self._ixia_candidates_to_try

    @staticmethod
    def _resolve_endpoint_reference(
        value: t.Optional[str],
        bindings: t.Mapping[str, str],
    ) -> t.Optional[str]:
        if value is None:
            return None
        for logical_name, hostname in bindings.items():
            if value == logical_name:
                return hostname
            prefix = f"{logical_name}:"
            if value.startswith(prefix):
                return f"{hostname}{value[len(logical_name) :]}"
        return value

    @classmethod
    def _resolve_jq_endpoint_references(
        cls,
        expression: str,
        bindings: t.Mapping[str, str],
    ) -> str:
        def replace_endpoint_access(match: re.Match[str]) -> str:
            quoted_key = match.group("dot_key") or match.group("bracket_key")
            logical_name = json.loads(quoted_key)
            hostname = bindings.get(logical_name)
            if hostname is None:
                return match.group(0)
            resolved_key = json.dumps(hostname)
            if match.group("dot") is not None:
                return f".{resolved_key}"
            return f"{match.group('bracket')}{resolved_key}{match.group('close')}"

        return _JQ_ENDPOINT_ACCESS_PATTERN.sub(replace_endpoint_access, expression)

    @classmethod
    def _resolve_json_endpoint_references(
        cls,
        value: t.Any,
        bindings: t.Mapping[str, str],
    ) -> t.Any:
        if isinstance(value, str):
            return cls._resolve_endpoint_reference(value, bindings)
        if isinstance(value, list):
            return [
                cls._resolve_json_endpoint_references(item, bindings) for item in value
            ]
        if isinstance(value, dict):
            return {
                key: cls._resolve_json_endpoint_references(item, bindings)
                for key, item in value.items()
            }
        return value

    @classmethod
    def _resolve_param_value(
        cls,
        value: taac_types.ParamValue,
        bindings: t.Mapping[str, str],
    ) -> taac_types.ParamValue:
        if value.get_type() == taac_types.ParamValue.Type.string_value:
            return taac_types.ParamValue(
                string_value=none_throws(
                    cls._resolve_endpoint_reference(value.string_value, bindings)
                )
            )
        if value.get_type() == taac_types.ParamValue.Type.string_list:
            return taac_types.ParamValue(
                string_list=[
                    none_throws(cls._resolve_endpoint_reference(item, bindings))
                    for item in value.string_list
                ]
            )
        return value

    @classmethod
    def _resolve_json_params(
        cls,
        json_params: t.Optional[str],
        bindings: t.Mapping[str, str],
    ) -> t.Optional[str]:
        if not json_params:
            return json_params
        return json.dumps(
            cls._resolve_json_endpoint_references(json.loads(json_params), bindings)
        )

    @classmethod
    def _resolve_params(
        cls,
        params: t.Optional[taac_types.Params],
        bindings: t.Mapping[str, str],
    ) -> t.Optional[taac_types.Params]:
        if params is None:
            return None
        static_params = params.static_params
        if static_params is not None:
            static_params = {
                name: cls._resolve_param_value(value, bindings)
                for name, value in static_params.items()
            }
        jq_params = params.jq_params
        if jq_params is not None:
            jq_params = {
                name: cls._resolve_jq_endpoint_references(expression, bindings)
                for name, expression in jq_params.items()
            }
        transform_params = params.transform_params
        if transform_params is not None:
            transform_params = {
                name: [
                    transform(
                        static_params=(
                            {
                                key: cls._resolve_param_value(value, bindings)
                                for key, value in transform.static_params.items()
                            }
                            if transform.static_params is not None
                            else None
                        ),
                        json_params=cls._resolve_json_params(
                            transform.json_params, bindings
                        ),
                    )
                    for transform in transforms
                ]
                for name, transforms in transform_params.items()
            }
        return params(
            static_params=static_params,
            json_params=cls._resolve_json_params(params.json_params, bindings),
            jq_params=jq_params,
            transform_params=transform_params,
        )

    @classmethod
    def _resolve_task_endpoint_references(
        cls,
        task: taac_types.Task,
        bindings: t.Mapping[str, str],
    ) -> taac_types.Task:
        return task(
            hostname=cls._resolve_endpoint_reference(task.hostname, bindings),
            params=cls._resolve_params(task.params, bindings),
        )

    @classmethod
    def _resolve_step_endpoint_references(
        cls,
        step: taac_types.Step,
        bindings: t.Mapping[str, str],
    ) -> taac_types.Step:
        return step(
            input_json=cls._resolve_json_params(step.input_json, bindings),
            step_params=cls._resolve_params(step.step_params, bindings),
            device_regexes=(
                [
                    none_throws(cls._resolve_endpoint_reference(value, bindings))
                    for value in step.device_regexes
                ]
                if step.device_regexes is not None
                else None
            ),
        )

    @classmethod
    def _resolve_health_check_endpoint_references(
        cls,
        health_check: t.Any,
        bindings: t.Mapping[str, str],
    ) -> t.Any:
        return health_check(
            input_json=cls._resolve_json_params(health_check.input_json, bindings),
            check_params=cls._resolve_params(health_check.check_params, bindings),
        )

    @classmethod
    def _resolve_periodic_task_endpoint_references(
        cls,
        periodic_task: taac_types.PeriodicTask,
        bindings: t.Mapping[str, str],
    ) -> taac_types.PeriodicTask:
        return periodic_task(
            task=cls._resolve_task_endpoint_references(periodic_task.task, bindings),
            params_list=(
                [
                    none_throws(cls._resolve_params(params, bindings))
                    for params in params_list
                ]
                if (params_list := periodic_task.params_list) is not None
                else None
            ),
        )

    @classmethod
    def _resolve_stage_endpoint_references(
        cls,
        stage: taac_types.Stage,
        bindings: t.Mapping[str, str],
    ) -> taac_types.Stage:
        return stage(
            steps=[
                cls._resolve_step_endpoint_references(step, bindings)
                for step in stage.steps
            ],
            concurrent_steps=(
                [
                    concurrent_step(
                        steps=[
                            cls._resolve_step_endpoint_references(step, bindings)
                            for step in concurrent_step.steps
                        ]
                    )
                    for concurrent_step in concurrent_steps
                ]
                if (concurrent_steps := stage.concurrent_steps) is not None
                else None
            ),
            device_regexes=(
                [
                    none_throws(cls._resolve_endpoint_reference(value, bindings))
                    for value in stage.device_regexes
                ]
                if stage.device_regexes is not None
                else None
            ),
        )

    @classmethod
    def _resolve_playbook_endpoint_references(
        cls,
        playbook: taac_types.Playbook,
        bindings: t.Mapping[str, str],
    ) -> taac_types.Playbook:
        def resolve_health_checks(checks: t.Any) -> t.Any:
            return (
                [
                    cls._resolve_health_check_endpoint_references(check, bindings)
                    for check in checks
                ]
                if checks is not None
                else None
            )

        def resolve_steps(steps: t.Any) -> t.Any:
            return (
                [
                    cls._resolve_step_endpoint_references(step, bindings)
                    for step in steps
                ]
                if steps is not None
                else None
            )

        return playbook(
            stages=[
                cls._resolve_stage_endpoint_references(stage, bindings)
                for stage in playbook.stages
            ],
            prechecks=resolve_health_checks(playbook.prechecks),
            postchecks=resolve_health_checks(playbook.postchecks),
            snapshot_checks=resolve_health_checks(playbook.snapshot_checks),
            cleanup_steps=resolve_steps(playbook.cleanup_steps),
            setup_steps=resolve_steps(playbook.setup_steps),
            periodic_tasks=(
                [
                    cls._resolve_periodic_task_endpoint_references(task, bindings)
                    for task in periodic_tasks
                ]
                if (periodic_tasks := playbook.periodic_tasks) is not None
                else None
            ),
            device_regexes=(
                [
                    none_throws(cls._resolve_endpoint_reference(value, bindings))
                    for value in playbook.device_regexes
                ]
                if playbook.device_regexes is not None
                else None
            ),
        )

    @staticmethod
    def _resolve_hostname_keyed_map(
        values: t.Optional[t.Mapping[str, t.Any]],
        bindings: t.Mapping[str, str],
        field_name: str,
    ) -> t.Optional[t.Dict[str, t.Any]]:
        if values is None:
            return None
        resolved = {}
        for key, value in values.items():
            resolved_key = bindings.get(key, key)
            if resolved_key in resolved:
                raise ValueError(
                    f"Resolving Basset endpoints creates duplicate {field_name} "
                    f"key {resolved_key!r}"
                )
            resolved[resolved_key] = value
        return resolved

    @classmethod
    def _resolve_ptp_config(
        cls,
        config: t.Any,
        bindings: t.Mapping[str, str],
    ) -> t.Any:
        def resolve_endpoint(endpoint: t.Any) -> t.Any:
            return endpoint(
                name=none_throws(
                    cls._resolve_endpoint_reference(endpoint.name, bindings)
                )
            )

        return config(
            server_endpoint=resolve_endpoint(config.server_endpoint),
            client_endpoints=[
                resolve_endpoint(endpoint) for endpoint in config.client_endpoints
            ],
            server_port_name=cls._resolve_endpoint_reference(
                config.server_port_name, bindings
            ),
            client_port_name_list=(
                [
                    none_throws(cls._resolve_endpoint_reference(name, bindings))
                    for name in config.client_port_name_list
                ]
                if config.client_port_name_list is not None
                else None
            ),
        )

    @classmethod
    def _resolve_candidate_endpoints(
        cls,
        candidate: IxiaCandidate,
        bindings: t.Mapping[str, str],
    ) -> IxiaCandidate:
        def resolve_port_config(
            config: t.Optional[taac_types.BasicPortConfig],
        ) -> t.Optional[taac_types.BasicPortConfig]:
            if config is None:
                return None
            return config(
                endpoint=cls._resolve_endpoint_reference(config.endpoint, bindings)
            )

        def resolve_traffic_endpoint(
            endpoint: taac_types.TrafficEndpoint,
        ) -> taac_types.TrafficEndpoint:
            return endpoint(
                name=none_throws(
                    cls._resolve_endpoint_reference(endpoint.name, bindings)
                )
            )

        def resolve_ixia_endpoint(endpoint: t.Any) -> t.Any:
            return endpoint(
                port_name=none_throws(
                    cls._resolve_endpoint_reference(endpoint.port_name, bindings)
                )
            )

        return dataclasses.replace(
            candidate,
            endpoints=tuple(
                endpoint(
                    name=bindings.get(endpoint.name, endpoint.name),
                    basset_query=None,
                )
                for endpoint in candidate.endpoints
            ),
            setup_tasks=tuple(
                cls._resolve_task_endpoint_references(task, bindings)
                for task in candidate.setup_tasks
            ),
            teardown_tasks=tuple(
                cls._resolve_task_endpoint_references(task, bindings)
                for task in candidate.teardown_tasks
            ),
            basic_port_configs=tuple(
                none_throws(resolve_port_config(config))
                for config in candidate.basic_port_configs
            ),
            basic_traffic_item_configs=tuple(
                config(
                    src_endpoints=[
                        resolve_traffic_endpoint(endpoint)
                        for endpoint in config.src_endpoints
                    ],
                    dest_endpoints=[
                        resolve_traffic_endpoint(endpoint)
                        for endpoint in config.dest_endpoints
                    ],
                )
                for config in candidate.basic_traffic_item_configs
            ),
            default_basic_port_config=resolve_port_config(
                candidate.default_basic_port_config
            ),
            user_defined_traffic_items=tuple(
                item(
                    source_endpoints=[
                        resolve_ixia_endpoint(endpoint)
                        for endpoint in item.source_endpoints
                    ],
                    dest_endpoints=[
                        resolve_ixia_endpoint(endpoint)
                        for endpoint in item.dest_endpoints
                    ],
                )
                for item in candidate.user_defined_traffic_items
            ),
            snake_configs=tuple(
                config(
                    source=none_throws(
                        cls._resolve_endpoint_reference(config.source, bindings)
                    ),
                    destination=none_throws(
                        cls._resolve_endpoint_reference(config.destination, bindings)
                    ),
                )
                for config in candidate.snake_configs
            ),
            ptp_configs=tuple(
                cls._resolve_ptp_config(config, bindings)
                for config in candidate.ptp_configs
            ),
        )

    @classmethod
    def _resolve_ixia_profile_endpoint_references(
        cls,
        profile: taac_types.IxiaSetupProfile,
        bindings: t.Mapping[str, str],
        candidate: t.Optional[IxiaCandidate] = None,
    ) -> taac_types.IxiaSetupProfile:
        if candidate is None:
            candidate = cls._resolve_candidate_endpoints(
                IxiaCandidate(
                    name=profile.name,
                    api_server_ip=profile.api_server_ip,
                    endpoints=tuple(profile.endpoints),
                    setup_tasks=tuple(profile.setup_tasks),
                    teardown_tasks=tuple(profile.teardown_tasks),
                    basic_port_configs=tuple(profile.basic_port_configs),
                    basic_traffic_item_configs=tuple(
                        profile.basic_traffic_item_configs
                    ),
                    default_basic_port_config=profile.default_basic_port_config,
                    user_defined_traffic_items=tuple(
                        profile.user_defined_traffic_items
                    ),
                    snake_configs=tuple(profile.snake_configs),
                    ptp_configs=tuple(profile.ptp_configs),
                ),
                bindings,
            )
        return profile(
            endpoints=list(candidate.endpoints),
            setup_tasks=list(candidate.setup_tasks),
            teardown_tasks=list(candidate.teardown_tasks),
            basic_port_configs=list(candidate.basic_port_configs),
            basic_traffic_item_configs=list(candidate.basic_traffic_item_configs),
            default_basic_port_config=candidate.default_basic_port_config,
            user_defined_traffic_items=list(candidate.user_defined_traffic_items),
            snake_configs=list(candidate.snake_configs),
            ptp_configs=[
                cls._resolve_ptp_config(ptp_config, bindings)
                for ptp_config in profile.ptp_configs
            ],
        )

    async def _async_release_query_resources(
        self,
        basset_butler: t.Any,
        resources: t.Iterable[t.Any],
    ) -> t.List[Exception]:
        errors = []
        released = set()
        for resource in resources:
            resource_key = id(resource)
            if resource_key in released:
                continue
            released.add(resource_key)
            try:
                await basset_butler.async_release(resource)
            except Exception as error:
                self.logger.exception(
                    f"Failed to release query-backed Basset resource {resource!r}"
                )
                errors.append(error)
        return errors

    async def async_resolve_basset_endpoints(  # noqa: C901
        self,
    ) -> t.Dict[str, str]:
        """Reserve endpoints and bind query-backed IXIA profiles."""
        primary_endpoints = self.ixia_candidates[0].endpoints
        query_endpoints = [
            endpoint
            for endpoint in primary_endpoints
            if endpoint.basset_query is not None
        ]
        if not query_endpoints:
            if any(
                endpoint.basset_query is not None
                for candidate in self.ixia_candidates[1:]
                for endpoint in candidate.endpoints
            ):
                raise ValueError("Basset queries must be declared on primary endpoints")
            await self._async_reserve_static_endpoints()
            return {}
        if not TAAC_OSS:
            from taac.internal.internal_utils import (
                async_reserve_basset_queries,
            )
        else:
            raise ValueError("Basset-backed endpoints are not supported in OSS mode")
        if self._skip_basset_reservation:
            raise ValueError(
                "Basset-backed endpoints cannot be used with --skip-basset-reservation"
            )
        if any(
            not none_throws(endpoint.basset_query).strip()
            for endpoint in query_endpoints
        ):
            raise ValueError("Endpoint Basset queries must not be empty")

        queries = {
            endpoint.name: none_throws(endpoint.basset_query)
            for endpoint in query_endpoints
        }
        if len(queries) != len(query_endpoints):
            raise ValueError("Basset-backed endpoint names must be unique")
        for candidate in self.ixia_candidates[1:]:
            for endpoint in candidate.endpoints:
                if endpoint.basset_query is not None and endpoint.basset_query != (
                    queries.get(endpoint.name)
                ):
                    raise ValueError(
                        "IXIA profiles must use the same Basset query for endpoint "
                        f"{endpoint.name!r}"
                    )

        (
            bindings,
            basset_butler,
            reserved_resources,
        ) = await async_reserve_basset_queries(
            queries,
            self.test_config.basset_reservation_time_hr * 3600,
            self.logger,
        )
        resolved_names = {hostname.casefold() for hostname in bindings.values()}
        if len(resolved_names) != len(bindings):
            await self._async_release_query_resources(basset_butler, reserved_resources)
            raise ValueError("Basset queries selected the same endpoint more than once")
        static_names = {
            endpoint.name.casefold()
            for endpoint in primary_endpoints
            if endpoint.basset_query is None
        }
        overlap = static_names & resolved_names
        if overlap:
            await self._async_release_query_resources(basset_butler, reserved_resources)
            raise ValueError(
                "A Basset query selected an explicitly configured endpoint: "
                f"{sorted(overlap)}"
            )

        candidate_indices = {
            id(candidate): index for index, candidate in enumerate(self.ixia_candidates)
        }
        config = self.test_config
        try:
            resolved_candidates = tuple(
                self._resolve_candidate_endpoints(candidate, bindings)
                for candidate in self.ixia_candidates
            )
            resolved_candidates_to_try = tuple(
                resolved_candidates[candidate_indices[id(candidate)]]
                for candidate in self._ixia_candidates_to_try
            )
            primary_candidate = resolved_candidates[0]
            secondary_profile = config.secondary_ixia_profile
            if secondary_profile is not None:
                secondary_profile = self._resolve_ixia_profile_endpoint_references(
                    secondary_profile,
                    bindings,
                    resolved_candidates[1] if len(resolved_candidates) > 1 else None,
                )
            oss_mock_device_data = self._resolve_hostname_keyed_map(
                config.oss_mock_device_data,
                bindings,
                "oss_mock_device_data",
            )
            if oss_mock_device_data is not None:
                oss_mock_device_data = {
                    hostname: device_info(
                        name=bindings.get(device_info.name, device_info.name)
                    )
                    for hostname, device_info in oss_mock_device_data.items()
                }
            resolved_config = config(
                endpoints=list(primary_candidate.endpoints),
                setup_tasks=list(primary_candidate.setup_tasks),
                teardown_tasks=list(primary_candidate.teardown_tasks),
                basic_port_configs=list(primary_candidate.basic_port_configs),
                basic_traffic_item_configs=list(
                    primary_candidate.basic_traffic_item_configs
                ),
                default_basic_port_config=(primary_candidate.default_basic_port_config),
                user_defined_traffic_items=list(
                    primary_candidate.user_defined_traffic_items
                ),
                snake_configs=list(primary_candidate.snake_configs),
                ptp_configs=(
                    [
                        self._resolve_ptp_config(ptp_config, bindings)
                        for ptp_config in config.ptp_configs
                    ]
                    if config.ptp_configs is not None
                    else None
                ),
                playbooks=[
                    self._resolve_playbook_endpoint_references(playbook, bindings)
                    for playbook in config.playbooks
                ],
                periodic_tasks=(
                    [
                        self._resolve_periodic_task_endpoint_references(
                            periodic_task, bindings
                        )
                        for periodic_task in config.periodic_tasks
                    ]
                    if config.periodic_tasks is not None
                    else None
                ),
                prechecks=(
                    [
                        self._resolve_health_check_endpoint_references(
                            health_check, bindings
                        )
                        for health_check in config.prechecks
                    ]
                    if config.prechecks is not None
                    else None
                ),
                postchecks=(
                    [
                        self._resolve_health_check_endpoint_references(
                            health_check, bindings
                        )
                        for health_check in config.postchecks
                    ]
                    if config.postchecks is not None
                    else None
                ),
                snapshot_checks=(
                    [
                        self._resolve_health_check_endpoint_references(
                            health_check, bindings
                        )
                        for health_check in config.snapshot_checks
                    ]
                    if config.snapshot_checks is not None
                    else None
                ),
                startup_checks=(
                    [
                        self._resolve_health_check_endpoint_references(
                            health_check, bindings
                        )
                        for health_check in config.startup_checks
                    ]
                    if config.startup_checks is not None
                    else None
                ),
                oss_setup_tasks=(
                    [
                        self._resolve_task_endpoint_references(task, bindings)
                        for task in config.oss_setup_tasks
                    ]
                    if config.oss_setup_tasks is not None
                    else None
                ),
                rsyslog_services_overrides=self._resolve_hostname_keyed_map(
                    config.rsyslog_services_overrides,
                    bindings,
                    "rsyslog_services_overrides",
                ),
                host_os_type_map=self._resolve_hostname_keyed_map(
                    config.host_os_type_map, bindings, "host_os_type_map"
                ),
                host_driver_args=self._resolve_hostname_keyed_map(
                    config.host_driver_args, bindings, "host_driver_args"
                ),
                oss_mock_device_data=oss_mock_device_data,
                secondary_ixia_profile=secondary_profile,
            )
        except Exception:
            await self._async_release_query_resources(basset_butler, reserved_resources)
            raise

        self._query_basset_butler = basset_butler
        self._query_basset_resources = reserved_resources
        self._query_reserved_device_names = set(bindings.values())
        self.ixia_candidates = resolved_candidates
        self._ixia_candidates_to_try = resolved_candidates_to_try
        self.test_config = resolved_config
        self.devices_under_test = [
            endpoint.name for endpoint in primary_candidate.endpoints if endpoint.dut
        ]
        for logical_name, hostname in bindings.items():
            self.logger.info(
                f"Resolved Basset endpoint {logical_name!r} to {hostname!r}"
            )
        await self._async_reserve_static_endpoints()
        return bindings

    async def _async_reserve_static_endpoints(self) -> None:
        if TAAC_OSS or self._skip_basset_reservation or self.basset_butler is not None:
            return
        static_device_names = [
            endpoint.name
            for endpoint in self.ixia_candidates[0].endpoints
            if endpoint.name not in self._query_reserved_device_names
        ]
        if not static_device_names:
            return
        if not self.test_config.basset_pool:
            raise ValueError("Static Basset endpoints require a non-empty basset_pool")

        from taac.internal.internal_utils import (
            async_reserve_devices_in_basset,
        )

        success, self.basset_butler = await async_reserve_devices_in_basset(
            self.test_config, static_device_names, self.logger
        )
        if not success:
            raise Exception("Failed to reserve test devices in Basset")

    async def async_setUp(self) -> None:
        test_device_names = [
            endpoint.name for endpoint in self.ixia_candidates[0].endpoints
        ]

        if TAAC_OSS:
            await self._async_setUp_oss(test_device_names)
        else:
            await self._async_setUp_internal(test_device_names)

    async def _async_setUp_oss(self, test_device_names: t.List[str]) -> None:
        """
        OSS test setup path:
        1. Create test bed from CSV topology data
        2. IXIA setup (if needed)

        No Basset reservation, package updates, or testbed isolation in OSS mode.
        """
        # Step 1: Create test bed from CSV data
        with timed_phase("Test bed creation (OSS)", logger=self.logger):
            self.test_bed_chunker = OssTestBedChunker(
                test_device_names,
                self.logger,
            )
            self.test_topology = await self.test_bed_chunker.async_create_test_bed()

        # Step 2: IXIA setup
        if not self._skip_ixia_setup:
            await self.async_setup_ixia_candidates()
        else:
            self.logger.info("Skipping IXIA setup (user requested).")
            self.selected_ixia_candidate = self._ixia_candidates_to_try[0]

        # Wait additional time for interfaces to stabilize after boot, but
        # only when there are real devices and the caller hasn't asked us to
        # skip. Empty/synthetic configs (no devices) and explicit overrides
        # bypass the wait so smoke tests aren't blocked on it.
        has_real_devices = bool(self.test_topology and self.test_topology.devices)
        if self._skip_post_setup_wait or not has_real_devices:
            reason = (
                "skip_post_setup_wait=True"
                if self._skip_post_setup_wait
                else "no devices in topology"
            )
            self.logger.info(
                f"  Skipping post-setup interface stabilization wait ({reason})."
            )
        else:
            self.logger.info("  Waiting 180s for interfaces to stabilize after boot...")
            await asyncio.sleep(180)

    async def _async_setUp_internal(  # noqa: C901
        self, test_device_names: t.List[str]
    ) -> None:
        """
        Internal (Meta) test setup path:
        1. Reserve devices in Basset
        2. Create test bed from Skynet/NetWhoAmI topology discovery
        3. Isolate test bed connectivity
        4. Update packages (FBOSS agent, BGP, etc.)
        5. IXIA setup (if needed)
        """
        from taac.internal.internal_utils import (
            async_reserve_devices_in_basset,
            update_devices_with_desired_packages,
        )

        # Use warning level so messages pass through suppress_console_logs
        _log = self.logger.warning

        _log(
            f"\033[36m\033[1m[SETUP]\033[0m Devices: "
            f"\033[33m{', '.join(test_device_names)}\033[0m"
        )

        # Step 1: Basset device reservation
        if not self._skip_basset_reservation:
            static_device_names = [
                name
                for name in test_device_names
                if name not in self._query_reserved_device_names
            ]
            if not static_device_names:
                _log(
                    "\033[32m[SETUP]\033[0m Phase 1: Basset reservation "
                    "completed during endpoint resolution"
                )
            elif self.basset_butler is not None:
                _log(
                    "\033[32m[SETUP]\033[0m Phase 1: Static Basset reservation "
                    "completed before setup tasks"
                )
            else:
                _log("\033[36m[SETUP]\033[0m Phase 1: Reserving devices in Basset...")
                with timed_phase("Basset device reservation", logger=self.logger):
                    success, self.basset_butler = await async_reserve_devices_in_basset(
                        self.test_config, static_device_names, self.logger
                    )
                    if not success:
                        raise Exception("Failed to reserve test devices in Basset")
                _log("\033[32m[SETUP]\033[0m Phase 1: Basset reservation complete")
        else:
            _log("\033[2m[SETUP] Phase 1: Skipping Basset reservation\033[0m")

        # Step 2: Create test bed from internal topology discovery
        _log(
            "\033[36m[SETUP]\033[0m Phase 2: Creating test bed (topology, interfaces, circuits)..."
        )
        _tb_start = time.time()
        with timed_phase("Test bed creation", logger=self.logger):
            self.test_bed_chunker = TestBedChunker(
                test_device_names,
                self.test_config.basset_pool,
                self.logger,
                ignore_circuit_fbnet_status=self.test_config.ignore_circuit_fbnet_status,
                ignore_down_circuits=self.test_config.ignore_down_circuits,
                ixia_interface_names=self._get_ixia_interface_names(),
            )
            self.test_topology = await self.test_bed_chunker.async_create_test_bed()
        _log(
            f"\033[32m[SETUP]\033[0m Phase 2: Test bed created in "
            f"\033[33m{time.time() - _tb_start:.0f}s\033[0m"
        )

        # Step 3: Testbed isolation
        if not self._skip_testbed_isolation:
            _log("\033[36m[SETUP]\033[0m Phase 3: Isolating test bed connectivity...")
            _iso_start = time.time()
            with timed_phase("Test bed isolation", logger=self.logger):
                await self.test_bed_chunker.async_isolate_test_bed_connectivity()
            _log(
                f"\033[32m[SETUP]\033[0m Phase 3: Isolation complete in "
                f"\033[33m{time.time() - _iso_start:.0f}s\033[0m"
            )
        else:
            _log("\033[2m[SETUP] Phase 3: Skipping test bed isolation\033[0m")

        # Step 4: EOS image deployment + Package updates
        if self._eos_image_id:
            _log(
                f"\033[36m[SETUP]\033[0m Phase 4: Deploying EOS image {self._eos_image_id}..."
            )
            with timed_phase("EOS image deployment", logger=self.logger):
                await self._deploy_eos_image()
        else:
            _log("\033[2m[SETUP] Phase 4: No EOS image deployment needed\033[0m")

        if not self._skip_package_update:
            if self._dsf_sequential_update:
                _log(
                    "\033[36m[SETUP]\033[0m Phase 5: Updating packages (DSF sequential)..."
                )
                fdsw_devices = [
                    hostname
                    for hostname in test_device_names
                    if "fdsw" in hostname.lower()
                ]
                other_devices = list(set(test_device_names) - set(fdsw_devices))
                with timed_phase("Package update (FDSW devices)", logger=self.logger):
                    for fdsw in fdsw_devices:
                        _log(f"\033[36m[SETUP]\033[0m   Updating {fdsw}")
                        update_devices_with_desired_packages(
                            [fdsw],
                            self._desired_pkg_versions,
                            self._allow_disruptive_configs,
                            self.logger,
                        )
                        if self.test_config.ignore_down_circuits:
                            await self.async_wait_for_interfaces_to_stabilize()
                with timed_phase("Package update (other devices)", logger=self.logger):
                    update_devices_with_desired_packages(
                        other_devices,
                        self._desired_pkg_versions,
                        self._allow_disruptive_configs,
                        self.logger,
                    )
                    if self.test_config.ignore_down_circuits:
                        await self.async_wait_for_interfaces_to_stabilize()
            else:
                _log(
                    f"\033[36m[SETUP]\033[0m Phase 5: Updating packages on "
                    f"\033[33m{', '.join(test_device_names)}\033[0m..."
                )
                with timed_phase("Package update (all devices)", logger=self.logger):
                    update_devices_with_desired_packages(
                        test_device_names,
                        self._desired_pkg_versions,
                        self._allow_disruptive_configs,
                        self.logger,
                    )
                    if self.test_config.ignore_down_circuits:
                        await self.async_wait_for_interfaces_to_stabilize()
        else:
            _log("\033[2m[SETUP] Phase 5: Skipping package update\033[0m")

        # Step 5: IXIA setup
        if not self._skip_ixia_setup:
            await self.async_setup_ixia_candidates()
        else:
            _log("\033[2m[SETUP] Phase 6: Skipping IXIA setup\033[0m")
            self.selected_ixia_candidate = self._ixia_candidates_to_try[0]

    @staticmethod
    def _get_ixia_endpoints(
        candidate: IxiaCandidate,
    ) -> t.List[taac_types.Endpoint]:
        return [
            endpoint
            for endpoint in candidate.endpoints
            if endpoint.ixia_needed
            or endpoint.direct_ixia_connections
            or endpoint.ixia_ports
        ]

    async def async_setup_ixia_candidates(self) -> None:
        failures: t.List[t.Tuple[str, BaseException]] = []
        candidate_count = len(self._ixia_candidates_to_try)
        for index, candidate in enumerate(self._ixia_candidates_to_try, 1):
            ixia_endpoints = self._get_ixia_endpoints(candidate)
            if not ixia_endpoints:
                self.selected_ixia_candidate = candidate
                self.logger.warning(
                    f"[IXIA CANDIDATE] selected={candidate.name} ixia_endpoints=0"
                )
                return

            attempt_start = time.time()
            self.logger.warning(
                f"[IXIA CANDIDATE] attempt={index}/{candidate_count} "
                f"name={candidate.name} api_server="
                f"{candidate.api_server_ip or 'auto-discover'}"
            )
            try:
                self.ixia = await self.async_create_ixia_setup(
                    candidate,
                    self._ixia_session_id,
                    self._skip_ixia_cleanup,
                )
            except IxiaCandidateSetupError as error:
                failures.append((candidate.name, error))
                self.logger.warning(
                    f"[IXIA CANDIDATE] failed name={candidate.name} "
                    f"failure={type(error).__name__} "
                    f"elapsed_s={time.time() - attempt_start:.1f}"
                )
                if not self._cleanup_failed_setup or self._skip_ixia_cleanup:
                    raise
                await self.async_cleanup_failed_ixia_candidate(candidate)
                if index == candidate_count:
                    if candidate_count == 1:
                        raise
                    raise IxiaFallbackExhaustedError(failures) from error
                self.logger.warning(
                    f"[IXIA CANDIDATE] fallback_from={candidate.name} "
                    f"fallback_to={self._ixia_candidates_to_try[index].name}"
                )
                continue

            self.selected_ixia_candidate = candidate
            self.logger.warning(
                f"[IXIA CANDIDATE] selected={candidate.name} "
                f"session_id={getattr(self.ixia, 'session_id', 'n/a')} "
                f"elapsed_s={time.time() - attempt_start:.1f}"
            )
            return

    async def async_cleanup_failed_ixia_candidate(
        self, candidate: IxiaCandidate
    ) -> None:
        cleanup_start = time.time()
        self.logger.warning(f"[IXIA CANDIDATE] cleanup_start name={candidate.name}")
        try:
            await self.async_teardown_ixia_setup(strict=True)
        except Exception as error:
            self.logger.warning(
                f"[IXIA CANDIDATE] cleanup_failed name={candidate.name} "
                f"failure={type(error).__name__} "
                f"elapsed_s={time.time() - cleanup_start:.1f}"
            )
            raise
        self.ixia = None
        self.traffic_generator = None
        self.logger.warning(
            f"[IXIA CANDIDATE] cleanup_complete name={candidate.name} "
            f"elapsed_s={time.time() - cleanup_start:.1f}"
        )

    async def async_tearDown(self, strict_ixia_cleanup: bool = False) -> None:
        if TAAC_OSS:
            await self._async_tearDown_oss(strict_ixia_cleanup)
        else:
            await self._async_tearDown_internal(strict_ixia_cleanup)

    async def _async_tearDown_oss(self, strict_ixia_cleanup: bool) -> None:
        """
        OSS teardown path:
        1. IXIA teardown

        No Basset release or testbed restoration in OSS mode.
        """
        await self.async_teardown_ixia_setup(strict=strict_ixia_cleanup)

    async def _async_tearDown_internal(  # noqa: C901
        self, strict_ixia_cleanup: bool
    ) -> None:
        """
        Internal (Meta) teardown path:
        1. Restore test bed connectivity
        2. Release Basset reservation
        3. IXIA teardown
        """
        errors: t.List[Exception] = []
        if not self._skip_testbed_isolation and self.test_bed_chunker is not None:
            try:
                await self.test_bed_chunker.async_restore_test_bed_connectivity()
            except Exception as error:
                errors.append(error)

        if not self._skip_basset_reservation and self.basset_butler:
            from taac.internal.internal_utils import (
                async_release_devices_in_basset,
            )

            try:
                await async_release_devices_in_basset(self.basset_butler, self.logger)
            except Exception as error:
                errors.append(error)

        if not self._skip_basset_reservation and self._query_basset_butler:
            errors.extend(
                await self._async_release_query_resources(
                    self._query_basset_butler,
                    self._query_basset_resources,
                )
            )
            self._query_basset_resources = []

        try:
            await self.async_teardown_ixia_setup(strict=strict_ixia_cleanup)
        except Exception as error:
            errors.append(error)

        if len(errors) == 1:
            raise errors[0]
        if errors:
            raise ExceptionGroup("Multiple TAAC resources failed to clean up", errors)

    async def async_wait_for_interfaces_to_stabilize(self) -> None:
        coroutines = []
        for test_device in self.test_topology.devices:
            interfaces = [
                interface.interface_name
                for interface in test_device.interfaces + test_device.ixia_interfaces
            ]
            driver = await async_get_device_driver(test_device.name)
            coroutines.append(driver.async_check_interfaces_status(interfaces, True))
        await asyncio.gather(*coroutines)

    async def async_create_ixia_setup(
        self,
        candidate: IxiaCandidate,
        ixia_session_id: t.Optional[int] = None,
        skip_ixia_cleanup: bool = False,
    ) -> TaacIxia:
        log_subsection(
            "CREATING IXIA SETUP",
            logger=self.logger,
        )

        # Use warning level so messages pass through suppress_console_logs
        _log = self.logger.warning

        # Log endpoint details
        ixia_endpoints = self._get_ixia_endpoints(candidate)
        for ep in ixia_endpoints:
            ixia_ports = []
            if ep.direct_ixia_connections:
                ixia_ports = [c.interface for c in ep.direct_ixia_connections]
            _log(
                f"\033[36m[IXIA]\033[0m Endpoint: \033[1m{ep.name}\033[0m"
                f" | Ixia ports: \033[33m{ixia_ports or 'auto-discover'}\033[0m"
            )

        # Log basic port configs
        basic_port_configs = candidate.basic_port_configs
        if basic_port_configs:
            for bpc in basic_port_configs:
                n_dg = len(bpc.device_group_configs) if bpc.device_group_configs else 0
                _log(
                    f"\033[36m[IXIA]\033[0m Port config: "
                    f"\033[33m{bpc.endpoint}\033[0m "
                    f"({n_dg} device group(s))"
                )

        # Log session info
        session_info = (
            f"session_id=\033[33m{ixia_session_id}\033[0m (reusing)"
            if ixia_session_id
            else "session_id=\033[33mnew\033[0m"
        )
        chassis_info = (
            f"chassis=\033[33m{candidate.api_server_ip}\033[0m"
            if candidate.api_server_ip
            else "chassis=\033[33mauto-discover\033[0m"
        )
        _log(f"\033[36m[IXIA]\033[0m {session_info} | {chassis_info}")

        # IIE-2 260605: two-tier IXIA topology cache. The default is disabled,
        # so TestConfigs must explicitly opt in with
        # `ixia_config_cache=IxiaConfigCache(enabled=True)`. Cache misses and
        # rehydration failures fall through to cold setup; cache exceptions are
        # swallowed in `TrafficGenerator.async_create_ixia_setup` so a broken
        # cache never reds a green test.
        ixia_config_cache = (
            getattr(self.test_config, "ixia_config_cache", None)
            or DEFAULT_IXIA_CONFIG_CACHE
        )
        # IIE-2 260610: default-on soft recovery of the ixnetworkweb platform
        # app when SessionAssistant creation fails with 5xx. TestConfigs that
        # intentionally exercise create_basic_setup failure modes must opt
        # out with `ixia_recovery=IxiaRecovery(enabled=False)`.
        ixia_recovery = (
            getattr(self.test_config, "ixia_recovery", None) or _DEFAULT_IXIA_RECOVERY
        )
        tgen_cls = (
            OtgTrafficGenerator
            if self._traffic_generator_backend == "otg"
            else TrafficGenerator
        )
        self.traffic_generator = tgen_cls(
            ixia_endpoints,
            basset_pool=self.test_config.basset_pool,
            session_name=self.test_config.name,
            logger=self.logger,
            cleanup_config=True if not ixia_session_id else False,
            tear_down_session=not skip_ixia_cleanup,
            primary_chassis_ip=candidate.api_server_ip,
            session_id=ixia_session_id,
            user_defined_traffic_items=candidate.user_defined_traffic_items,
            basic_traffic_item_configs=candidate.basic_traffic_item_configs,
            basic_port_configs=candidate.basic_port_configs,
            default_basic_port_config=candidate.default_basic_port_config,
            override_traffic_items=self._override_ixia_traffic_items,
            cleanup_failed_setup=self._cleanup_failed_setup,
            snake_configs=candidate.snake_configs,
            ptp_configs=candidate.ptp_configs,
            skip_advertised_prefixes_check=self.test_config.skip_advertised_prefixes_check,
            skip_ixia_protocol_verification=self.test_config.skip_ixia_protocol_verification,
            ixia_protocol_verification_timeout=self.test_config.ixia_protocol_verification_timeout,
            ixia_config_cache=ixia_config_cache,
            ixia_recovery=ixia_recovery,
            trace_api_calls=self._trace_ixia_api,
            wait_for_lldp_reconvergence=not self._skip_package_update,
            # v3 IXIA topology-cache key folds in setup_tasks so cache
            # auto-invalidates when an engineer edits a setup task during
            # testconfig development. See
            # `ixia_config_cache_manager.py:_CACHE_VERSION` history.
            setup_tasks=candidate.setup_tasks,
            cache_candidate_name=(
                candidate.name if candidate is not self.ixia_candidates[0] else None
            ),
        )

        _log(
            "\033[36m\033[1m[IXIA]\033[0m Starting IXIA setup "
            "(connect -> ports -> topologies -> protocols -> traffic)..."
        )
        traffic_generator = none_throws(self.traffic_generator)
        _ixia_start = time.time()
        await traffic_generator.async_create_ixia_setup()
        _ixia_elapsed = time.time() - _ixia_start

        ixia = none_throws(traffic_generator.ixia)
        _log(
            f"\033[32m\033[1m[IXIA]\033[0m Setup complete in "
            f"\033[33m{_ixia_elapsed:.0f}s\033[0m — "
            f"session ID: \033[33m{getattr(ixia, 'session_id', 'n/a')}\033[0m, "
            f"session name: \033[33m{getattr(ixia, 'session_name', 'n/a')}\033[0m"
        )
        # pyre-fixme[16]: `t.Optional` has no attribute `ixia`
        return ixia

    async def async_teardown_ixia_setup(
        self,
        strict: bool = False,
    ) -> None:
        # Intentional behavior change: normal teardown no longer gates on
        # `self._cleanup_failed_setup`. `cleanup_failed_setup` governs cleanup
        # of a FAILED candidate's partial session during fallback; it must not
        # also suppress the normal end-of-run teardown, or a run with
        # cleanup_failed_setup=False would leak the selected session. Covered by
        # `test_normal_teardown_is_not_disabled_with_failed_setup_cleanup`.
        if self.traffic_generator and not self._skip_ixia_cleanup:
            log_subsection(
                "TEARING DOWN IXIA SETUP",
                logger=self.logger,
            )
            try:
                await convert_to_async(self.traffic_generator.teardown_ixia_setup)()
            except Exception as ex:
                self.logger.exception(
                    "Following error occurred while attempting to teardown the "
                    f"IXIA setup: {ex}"
                )
                if strict:
                    raise

    async def _deploy_eos_image(self) -> None:
        """Deploy EOS image to all DUT devices using the DeployEosImageTask."""
        from taac.tasks.all import DeployEosImageTask

        task = DeployEosImageTask(logger=self.logger)
        for hostname in self.devices_under_test:
            params = {
                "hostname": hostname,
                "eos_image_id": self._eos_image_id,
                "clear_old_images": self._clear_old_eos_images,
            }
            await task.run(params)

    def _get_ixia_interface_names(self) -> t.Dict[str, t.Set[str]]:
        """Extract known Ixia-facing interface names from the test config.

        This ensures testbed isolation does not disable ports that are
        connected to Ixia, even when LLDP-based discovery fails to
        detect them (e.g. direct Ixia connections).
        """
        ixia_intfs: t.Dict[str, t.Set[str]] = {}
        for candidate in self.ixia_candidates:
            for endpoint in candidate.endpoints:
                hostname = endpoint.name
                if endpoint.direct_ixia_connections:
                    ixia_intfs.setdefault(hostname, set()).update(
                        conn.interface for conn in endpoint.direct_ixia_connections
                    )
            for bpc in candidate.basic_port_configs:
                if bpc.endpoint and ":" in bpc.endpoint:
                    hostname, intf = bpc.endpoint.split(":", 1)
                    ixia_intfs.setdefault(hostname, set()).add(intf)
        return ixia_intfs
