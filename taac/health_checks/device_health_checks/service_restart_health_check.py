# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
import time
import typing as t

from taac.constants import TestDevice
from taac.driver.driver_constants import (
    ARISTA_CRITICAL_SAND_AGENTS,
    AristaAgentStatus,
    FbossSystemctlServiceName,
)
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.health_checks.constants import DEFAULT_SERVICE_NAMES
from taac.utils.arista_utils import (
    DaemonStatus,
    get_daemon_status_comprehensive,
    parse_uptime_to_seconds,
)
from taac.health_check.health_check import types as hc_types

SERVICE_NAME_TO_DRIVER_ENUM = {
    "wedge_agent": FbossSystemctlServiceName.AGENT,
    "bgpd": FbossSystemctlServiceName.BGP,
    "qsfp_service": FbossSystemctlServiceName.QSFP,
    "fsdb": FbossSystemctlServiceName.FSDB,
    "openr": FbossSystemctlServiceName.OPENR,
    "fboss_sw_agent": FbossSystemctlServiceName.FBOSS_SW_AGENT,
    "fboss_hw_agent@0": FbossSystemctlServiceName.FBOSS_HW_AGENT_0,
    "coop": FbossSystemctlServiceName.COOP,
}

SERVICES_TO_IGNORE_FOR_NETOS = ["coop"]


class ServiceRestartHealthCheck(AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]):
    """
    Health check to ensure services are not restarting during test execution.

    This health check monitors specified services and verifies their uptime
    to detect if any service restarted during the test execution period.

    Supports both FBOSS and EOS (Arista) systems with appropriate daemon monitoring.
    """

    CHECK_NAME = hc_types.CheckName.SERVICE_RESTART_CHECK
    OPERATING_SYSTEMS = [
        "FBOSS",
        "EOS",
    ]

    async def _check_services_active_state(
        self, obj: TestDevice, services: t.List[str]
    ) -> t.Tuple[t.List[str], t.List[str]]:
        """
        Check if services are in ACTIVE state.

        Args:
            obj: TestDevice object
            services: List of service names to check

        Returns:
            Tuple of (failed_services, inactive_services)
        """
        failed_services: t.List[str] = []
        inactive_services: t.List[str] = []

        self.logger.info(
            f"Checking service status for {len(services)} services: {services}"
        )
        # pyrefly: ignore [missing-attribute]
        is_netos = await self.driver.async_is_netos()
        for service in services:
            try:
                if service == "fboss_hw_agent@1":
                    self.logger.debug(
                        f"Service {service} is 'fboss_hw_agent@1' - skipping as it's not applicable"
                    )
                    continue
                if is_netos and service in SERVICES_TO_IGNORE_FOR_NETOS:
                    self.logger.debug(
                        f"Service {service} does not run NetOS, skipping..."
                    )
                    continue

                # Convert service name string to Service enum if needed
                if service in SERVICE_NAME_TO_DRIVER_ENUM:
                    service_enum = SERVICE_NAME_TO_DRIVER_ENUM[service]
                else:
                    self.logger.warning(
                        f"Service {service} not found in SERVICE_NAME_TO_DRIVER_ENUM mapping. Available services: {list(SERVICE_NAME_TO_DRIVER_ENUM.keys())}"
                    )
                    failed_services.append(
                        f"{service}: not found in service enum mapping"
                    )
                    continue

                # pyrefly: ignore [missing-attribute]
                service_status = await self.driver.async_get_service_status(
                    service_enum
                )

                # Check if status is ACTIVE (comparing enum values)
                if service_status.name.lower() != "active":
                    inactive_services.append(
                        f"{service} (status: {service_status.name})"
                    )
                    self.logger.warning(
                        f"Service {service} on {obj.name} is not ACTIVE, current status: {service_status.name}"
                    )
            except Exception as e:
                error_msg = f"Failed to check service status for {service} on {obj.name}: {str(e)}"
                self.logger.error(error_msg)
                failed_services.append(f"{service}: {str(e)}")

        return failed_services, inactive_services

    async def _check_services_uptime(
        self,
        obj: TestDevice,
        services: t.List[str],
        test_duration: int,
        expected_restarted_services: t.Optional[t.List[str]] = None,
    ) -> t.Tuple[t.List[str], t.List[str]]:
        """
        Check service uptimes to detect restarts during test execution.

        Args:
            obj: TestDevice object
            services: List of service names to check
            test_duration: Duration of the test in seconds
            expected_restarted_services: List of services that are expected to
                restart (e.g. during warmboot). These will be skipped.

        Returns:
            Tuple of (failed_services, restarted_services)
        """
        failed_services: t.List[str] = []
        restarted_services: t.List[str] = []
        expected_set = set(expected_restarted_services or [])

        if expected_set:
            self.logger.info(
                f"Services expected to restart (will be skipped): {sorted(expected_set)}"
            )

        self.logger.info("Getting agent uptimes for restart detection")
        self.logger.info(f"Passing services list to get_agents_uptime: {services}")
        # pyrefly: ignore [missing-attribute]
        is_netos = await self.driver.async_is_netos()
        try:
            if is_netos:
                services = [
                    service
                    for service in services
                    if service not in SERVICES_TO_IGNORE_FOR_NETOS
                ]
            # pyrefly: ignore [missing-attribute]
            agent_uptimes = await self.driver.get_agents_uptime(services=services)
            self.logger.info(f"Retrieved agent uptimes: {agent_uptimes}")

            for service in services:
                if service == "fboss_hw_agent@1":
                    self.logger.info(
                        f"Skipping uptime check for {service} as it's not applicable"
                    )
                    continue
                if service in expected_set:
                    self.logger.info(
                        f"Skipping uptime check for {service} (expected restart)"
                    )
                    continue
                if service in agent_uptimes:
                    uptime_seconds = agent_uptimes[service]
                    if uptime_seconds < test_duration:
                        restart_time_ago = test_duration - uptime_seconds
                        self.logger.warning(
                            f"RESTART DETECTED: Service {service} on {obj.name} restarted during test execution. "
                            f"Uptime: {uptime_seconds}s, Test duration: {test_duration}s, "
                            f"Restarted {restart_time_ago}s ago"
                        )
                        restarted_services.append(
                            f"{service} (uptime: {uptime_seconds}s, restarted {restart_time_ago}s ago)"
                        )
                else:
                    self.logger.warning(
                        f"Service {service} not found in agent uptime results for {obj.name}. "
                        f"Available services in uptime results: {list(agent_uptimes.keys())}"
                    )
                    failed_services.append(f"{service}: not found in uptime results")

        except Exception as e:
            error_msg = f"Failed to get agent uptimes for {obj.name}: {str(e)}"
            self.logger.error(error_msg)
            failed_services.append(error_msg)

        return failed_services, restarted_services

    async def _check_arista_daemons(
        self,
        obj: TestDevice,
        daemons: t.List[str],
        test_duration: int,
        expected_restarted_services: t.Optional[t.List[str]] = None,
        duration_since_restart: t.Optional[int] = None,
    ) -> t.Tuple[t.List[str], t.List[str]]:
        """
        Check Arista EOS daemons for restarts by examining their uptime.

        Args:
            obj: TestDevice object
            daemons: List of daemon names to check
            test_duration: Duration of the test in seconds (from test_case_start_time)
            expected_restarted_services: List of daemon names that were intentionally
                restarted during the test. For these daemons, uptime is compared against
                duration_since_restart instead of the full test_duration.
            duration_since_restart: Time elapsed in seconds since the intentional restart
                completed (from restart_start_time). Used only for daemons in
                expected_restarted_services. If a daemon's uptime is less than this
                value, it indicates a silent crash after the intentional restart.

        Returns:
            Tuple of (failed_daemons, restarted_daemons)
        """
        failed_daemons: t.List[str] = []
        restarted_daemons: t.List[str] = []
        expected_set = set(expected_restarted_services or [])

        self.logger.info(f"Checking {len(daemons)} Arista daemons for restarts")
        if expected_set:
            self.logger.info(
                f"Expected restarted daemons: {expected_set} "
                f"(duration since restart: {duration_since_restart}s)"
            )

        for daemon in daemons:
            try:
                # Get current daemon status
                status: DaemonStatus = await get_daemon_status_comprehensive(
                    self.driver, daemon
                )

                if not status.is_running:
                    restarted_daemons.append(f"{daemon}: not running")
                    self.logger.warning(f"Daemon {daemon} on {obj.name} is not running")
                    continue

                # Check daemon uptime for restart detection
                if status.uptime:
                    uptime_seconds = parse_uptime_to_seconds(status.uptime)
                    if uptime_seconds is not None:
                        if (
                            daemon in expected_set
                            and duration_since_restart is not None
                        ):
                            # For intentionally restarted daemons, compare uptime
                            # against the time elapsed since the restart completed.
                            # If uptime < duration_since_restart, the daemon crashed
                            # and restarted again after the intentional restart.
                            if uptime_seconds < duration_since_restart:
                                restart_time_ago = (
                                    duration_since_restart - uptime_seconds
                                )
                                self.logger.warning(
                                    f"UNEXPECTED RESTART DETECTED: Daemon {daemon} on {obj.name} "
                                    f"was intentionally restarted but appears to have crashed again. "
                                    f"Uptime: {uptime_seconds}s ({status.uptime}), "
                                    f"Time since intentional restart: {duration_since_restart}s, "
                                    f"Crashed ~{restart_time_ago}s after intentional restart"
                                )
                                restarted_daemons.append(
                                    f"{daemon} (uptime: {status.uptime}, restarted {restart_time_ago}s "
                                    f"after intentional restart, possible silent crash)"
                                )
                            else:
                                self.logger.info(
                                    f"Daemon {daemon} (expected restart) is stable - "
                                    f"uptime {uptime_seconds}s ({status.uptime}) >= "
                                    f"time since restart {duration_since_restart}s"
                                )
                        elif uptime_seconds < test_duration:
                            restart_time_ago = test_duration - uptime_seconds
                            self.logger.warning(
                                f"RESTART DETECTED: Daemon {daemon} on {obj.name} restarted during test execution. "
                                f"Uptime: {uptime_seconds}s ({status.uptime}), Test duration: {test_duration}s, "
                                f"Restarted {restart_time_ago}s ago"
                            )
                            restarted_daemons.append(
                                f"{daemon} (uptime: {status.uptime}, restarted {restart_time_ago}s ago)"
                            )
                        else:
                            self.logger.debug(
                                f"Daemon {daemon} is stable - uptime {uptime_seconds}s > test duration {test_duration}s"
                            )
                    else:
                        self.logger.warning(
                            f"Failed to parse uptime '{status.uptime}' for daemon {daemon}"
                        )
                        failed_daemons.append(
                            f"{daemon}: failed to parse uptime '{status.uptime}'"
                        )
                else:
                    self.logger.warning(
                        f"No uptime information available for daemon {daemon}"
                    )
                    failed_daemons.append(f"{daemon}: no uptime information")

            except Exception as e:
                error_msg = f"Failed to check daemon {daemon}: {str(e)}"
                self.logger.error(error_msg)
                failed_daemons.append(error_msg)

        return failed_daemons, restarted_daemons

    async def _build_critical_agents_list(self) -> t.List[str]:
        """
        Build the full list of critical Sand agents to monitor by combining
        the static ARISTA_CRITICAL_SAND_AGENTS list with dynamically discovered
        per-linecard and per-fabric agents from the device.
        """
        agents = list(ARISTA_CRITICAL_SAND_AGENTS)
        try:
            # pyrefly: ignore [missing-attribute]
            lc_agents = await self.driver.async_get_lc_agent_names()
            if lc_agents:
                self.logger.info(f"Discovered linecard agents: {lc_agents}")
                agents.extend(lc_agents)
        except Exception as e:
            self.logger.warning(f"Failed to discover linecard agents: {e}")
        try:
            # pyrefly: ignore [missing-attribute]
            fabric_agents = await self.driver.async_get_fabric_agent()
            if fabric_agents:
                self.logger.info(f"Discovered fabric agents: {fabric_agents}")
                agents.extend(fabric_agents)
        except Exception as e:
            self.logger.warning(f"Failed to discover fabric agents: {e}")
        # Deduplicate while preserving order
        seen = set()
        deduped = []
        for a in agents:
            if a not in seen:
                seen.add(a)
                deduped.append(a)
        return deduped

    async def _check_arista_agents(
        self,
        obj: TestDevice,
        agents: t.List[str],
        start_time: float,
        expected_restarted_services: t.Optional[t.List[str]] = None,
    ) -> t.Tuple[t.List[str], t.List[str]]:
        """
        Check Arista EOS agents for restarts using 'show agent <name> uptime | json'.

        Compares each agent's agentStartTime against the test start_time.
        If the agent started after the test began, it restarted during the test.

        Args:
            obj: TestDevice object
            agents: List of agent names to check
            start_time: Unix timestamp when the test started
            expected_restarted_services: Agents to skip (the test trigger)
        """
        failed_agents: t.List[str] = []
        restarted_agents: t.List[str] = []
        expected_set = set(expected_restarted_services or [])

        if expected_set:
            self.logger.info(
                f"Agents expected to restart (will be skipped): {sorted(expected_set)}"
            )

        self.logger.info(
            f"Checking {len(agents)} EOS agents on {obj.name} via 'show agent <name> uptime'"
        )

        # pyrefly: ignore [missing-attribute]
        agent_statuses = await self.driver.async_get_agent_statuses(agents)

        for agent, status in agent_statuses.items():
            if agent in expected_set:
                self.logger.info(f"Skipping agent {agent} (expected restart)")
                continue
            try:
                if status.status == AristaAgentStatus.INACTIVE:
                    restarted_agents.append(f"{agent}: not running")
                    self.logger.warning(f"Agent {agent} on {obj.name} is not running")
                    continue

                if status.restart_count > 0:
                    self.logger.info(
                        f"Agent {agent} has restart_count={status.restart_count}, "
                        f"agentStartTime={status.uptime}"
                    )

                # agentStartTime is the timestamp when the agent last started.
                # Try to parse it as an epoch float to detect mid-test restarts.
                try:
                    agent_start_epoch = float(status.uptime)
                    if agent_start_epoch > start_time:
                        restart_ago = int(time.time() - agent_start_epoch)
                        self.logger.warning(
                            f"RESTART DETECTED: Agent {agent} on {obj.name} restarted during test. "
                            f"agentStartTime={status.uptime}, test_start={start_time}, "
                            f"restarted {restart_ago}s ago"
                        )
                        restarted_agents.append(
                            f"{agent} (started at {status.uptime}, restarted {restart_ago}s ago)"
                        )
                    else:
                        self.logger.debug(
                            f"Agent {agent} is stable - started before test"
                        )
                except (ValueError, TypeError):
                    # agentStartTime may not be a parseable epoch; log and skip
                    self.logger.debug(
                        f"Agent {agent} uptime '{status.uptime}' is not epoch-parseable, "
                        f"checking restart_count only"
                    )

            except Exception as e:
                error_msg = f"Failed to check agent {agent}: {str(e)}"
                self.logger.error(error_msg)
                failed_agents.append(error_msg)

        return failed_agents, restarted_agents

    def _build_restart_check_result(
        self,
        issues: t.List[str],
        failures: t.List[str],
        total_checked: int,
        test_duration: int,
        label: str = "agents/daemons",
    ) -> hc_types.HealthCheckResult:
        """Build a HealthCheckResult from restart check issues and failures."""
        if issues:
            message = f"Issues detected in {label}: {'; '.join(issues)}"
            if failures:
                message += f"\nFailed to check: {'; '.join(failures)}"
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=message,
            )
        elif failures:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=f"Failed to check some {label}: {'; '.join(failures)}",
            )
        else:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.PASS,
                message=f"No restarts detected: All {total_checked} EOS {label} remained stable during {test_duration}s test execution",
            )

    async def _run_arista(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        """
        Monitor Arista EOS agents and daemons for unexpected restarts.

        Uses 'show agent <name> uptime | json' for Sand agent monitoring and
        'show daemon <name>' for daemon monitoring.

        Args:
            obj: TestDevice object
            input: Base health check input
            check_params: Dictionary containing:
                - start_time: When the test started (unix timestamp)
                - services: Optional list of agents/daemons to monitor.
                    Defaults to ARISTA_CRITICAL_SAND_AGENTS + dynamically
                    discovered linecard/fabric agents.
                - expected_restarted_services: Optional list of agents that were
                    intentionally restarted (e.g., the agent being tested).
                    These are skipped during the check.
                - restart_start_time: Unix timestamp of when the intentional restart
                    completed. Used for daemon-based checks.
                - use_daemon_check: If True, use the legacy 'show daemon' check
                    instead of 'show agent uptime'. Defaults to False.
                - daemons: Optional list of EOS daemons to check via 'show daemon'.
                    Unlike agents (checked via 'show agent uptime'), daemons are
                    processes managed by EOS's daemon infrastructure and must be
                    checked with 'show daemon <name>'. Can be used alongside
                    'services' (agents) to check both in a single health check.

        Returns:
            HealthCheckResult with PASS if all agents are stable, FAIL otherwise
        """
        start_time = check_params.get("start_time", 0)
        expected_restarted_services = check_params.get(
            "expected_restarted_services", None
        )
        restart_start_time = check_params.get("restart_start_time", None)
        use_daemon_check = check_params.get("use_daemon_check", False)

        current_time = int(time.time())
        test_duration = current_time - int(start_time)

        # Legacy daemon-based check (for backward compatibility)
        if use_daemon_check:
            daemons = check_params.get("services", ["Bgp", "FibBgp", "FibAgent"])
            duration_since_restart = None
            if expected_restarted_services and restart_start_time is not None:
                duration_since_restart = current_time - int(restart_start_time)

            self.logger.info(
                f"ServiceRestartHealthCheck starting on {obj.name} (EOS, daemon mode)"
            )
            self.logger.info(f"Monitoring {len(daemons)} EOS daemons: {daemons}")

            failed_daemons, restarted_daemons = await self._check_arista_daemons(
                obj,
                daemons,
                test_duration,
                expected_restarted_services=expected_restarted_services,
                duration_since_restart=duration_since_restart,
            )

            return self._build_restart_check_result(
                restarted_daemons,
                failed_daemons,
                len(daemons),
                test_duration,
                "daemons",
            )

        # Agent-based check (default)
        if "services" in check_params:
            agents = check_params["services"]
        else:
            agents = await self._build_critical_agents_list()

        self.logger.info(
            f"ServiceRestartHealthCheck starting on {obj.name} (EOS, agent mode)"
        )
        self.logger.info(f"Monitoring {len(agents)} EOS agents: {agents}")
        if expected_restarted_services:
            self.logger.info(
                f"Expected restarted agents (will be skipped): {expected_restarted_services}"
            )

        failed_agents, restarted_agents = await self._check_arista_agents(
            obj,
            agents,
            float(start_time),
            expected_restarted_services=expected_restarted_services,
        )

        # Also check daemons if specified (daemons use 'show daemon' instead
        # of 'show agent uptime' because they are managed by EOS's daemon
        # infrastructure rather than the Sand agent framework)
        daemons_to_check = check_params.get("daemons", [])
        failed_daemons: t.List[str] = []
        restarted_daemons: t.List[str] = []
        if daemons_to_check:
            duration_since_restart = None
            if expected_restarted_services and restart_start_time is not None:
                duration_since_restart = current_time - int(restart_start_time)

            self.logger.info(
                f"Also checking {len(daemons_to_check)} EOS daemons via 'show daemon': {daemons_to_check}"
            )
            failed_daemons, restarted_daemons = await self._check_arista_daemons(
                obj,
                daemons_to_check,
                test_duration,
                expected_restarted_services=expected_restarted_services,
                duration_since_restart=duration_since_restart,
            )

        all_issues = restarted_agents + restarted_daemons
        all_failures = failed_agents + failed_daemons
        total_checked = len(agents) + len(daemons_to_check)

        return self._build_restart_check_result(
            all_issues, all_failures, total_checked, test_duration
        )

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        """
        Monitor services for unexpected restarts during test execution using uptime comparison.

        Args:
            obj: TestDevice object
            input: Base health check input
            check_params: Dictionary containing:
                - start_time: When the test started (unix timestamp)
                - services: Optional list of services to monitor (defaults to DEFAULT_SERVICE_NAMES)

        Returns:
            HealthCheckResult with PASS if no restarts detected, FAIL otherwise
        """

        start_time = check_params.get("start_time", 0)
        services = check_params.get("services", DEFAULT_SERVICE_NAMES)
        expected_restarted_services = check_params.get(
            "expected_restarted_services", None
        )

        self.logger.info(f"Services: {services}")

        current_time = int(time.time())
        test_duration = current_time - int(start_time)

        self.logger.info(f"ServiceRestartHealthCheck starting on {obj.name}:")
        self.logger.info(
            f"  - Services to monitor: {services} (count: {len(services)})"
        )
        if expected_restarted_services:
            self.logger.info(
                f"  - Expected restarted services (allowlist): {expected_restarted_services}"
            )

        # Check if services are in ACTIVE state
        (
            failed_services_active,
            inactive_services,
        ) = await self._check_services_active_state(obj, services)

        # If any services are not active, fail immediately
        if inactive_services:
            message = f"Services not in ACTIVE state: {', '.join(inactive_services)}"
            if failed_services_active:
                message += (
                    f"\nFailed to check services: {', '.join(failed_services_active)}"
                )
            self.logger.error(f"Health check FAILED: {message}")
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=message,
            )

        # Check service uptimes to detect restarts during test execution
        (
            failed_services_uptime,
            restarted_services,
        ) = await self._check_services_uptime(
            obj, services, test_duration, expected_restarted_services
        )

        # Combine failed services from both checks
        all_failed_services = failed_services_active + failed_services_uptime

        # Determine overall status
        if restarted_services:
            message = f"Services restarted during test execution: {', '.join(restarted_services)}"
            self.logger.warning(message)
            if all_failed_services:
                message += (
                    f"\nFailed to check services: {', '.join(all_failed_services)}"
                )
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=message,
            )
        elif all_failed_services:
            message = f"Failed to check some services: {', '.join(all_failed_services)}"
            self.logger.warning(message)
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=message,
            )
        else:
            self.logger.info(
                f"All {len(services)} services on {obj.name} have been running throughout "
                f"the test duration"
            )
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.PASS,
                message="All services running continuously for the test duration",
            )
