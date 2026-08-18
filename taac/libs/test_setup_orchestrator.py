# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import asyncio
import os
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

if not TAAC_OSS:
    from neteng.netcastle.teams.dne_regression.utils.package_fetcher_utils import (
        DnePackageFetcher,
    )
    from taac.internal.test_bed_chunker import TestBedChunker


# IIE-2 260605 two-tier IXIA topology cache: default-on for every TestConfig
# that does not opt out via an explicit `ixia_config_cache=IxiaConfigCache(...)`
# override (e.g. `enabled=False`). bag011 BGP_RESTART + bag013 EBB full scale
# both measured ~4x setup time reduction on warm runs (15m cold → 4m warm).
# Tier 1 path is the IxNetwork API server's documented persistent storage dir
# (survives session teardown — confirmed on bag011/012/013 chassis). Tier 2 is
# omitted in OSS builds because the Manifold helper is internal-only.
_DEFAULT_IXIA_CONFIG_CACHE: taac_types.IxiaConfigCache = taac_types.IxiaConfigCache(
    enabled=True,
    chassis_local_dir="/root/.local/share/Ixia/sdmStreamManager/common/taac_ixia_configs",
    manifold_bucket=None if TAAC_OSS else "taac_ixia_topology_cache",
)


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

    async def _async_setUp_internal(self, test_device_names: t.List[str]) -> None:
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
            _log("\033[36m[SETUP]\033[0m Phase 1: Reserving devices in Basset...")
            with timed_phase("Basset device reservation", logger=self.logger):
                success, self.basset_butler = await async_reserve_devices_in_basset(
                    self.test_config, test_device_names, self.logger
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

    async def _async_tearDown_internal(self, strict_ixia_cleanup: bool) -> None:
        """
        Internal (Meta) teardown path:
        1. Restore test bed connectivity
        2. Release Basset reservation
        3. IXIA teardown
        """
        errors: t.List[Exception] = []
        if not self._skip_testbed_isolation:
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

        # IIE-2 260605: two-tier IXIA topology cache. Default-on for every
        # TestConfig that has no explicit `ixia_config_cache` (see
        # `_DEFAULT_IXIA_CONFIG_CACHE` above). TestConfigs that intentionally
        # need cold setup (snake tests, anything probing `create_basic_setup`
        # itself) must opt out by setting `ixia_config_cache=IxiaConfigCache(
        # enabled=False)`. Cache misses fall through to cold setup; cache
        # exceptions are swallowed in `TrafficGenerator.async_create_ixia_setup`
        # so a broken cache never reds a green test.
        ixia_config_cache = (
            getattr(self.test_config, "ixia_config_cache", None)
            or _DEFAULT_IXIA_CONFIG_CACHE
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
