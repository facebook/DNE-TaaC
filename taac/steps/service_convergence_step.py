# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe


import time
import typing as t

from taac.steps.step import Step
from taac.test_as_a_config import types as taac_types


class ServiceConvergenceStep(Step[taac_types.ServiceConvergenceInput]):
    STEP_NAME = taac_types.StepName.SERVICE_CONVERGENCE_STEP

    async def run(
        self,
        input: taac_types.ServiceConvergenceInput,
        params: t.Dict[str, t.Any],
    ) -> None:
        if any(
            agent in [taac_types.Service.AGENT, taac_types.Service.FBOSS_SW_AGENT]
            for agent in input.services
        ):
            timeout = (
                input.service_convergence_timeout.get(taac_types.Service.AGENT)
                or input.service_convergence_timeout.get(
                    taac_types.Service.FBOSS_SW_AGENT
                )
                or input.timeout
            )
            start_time = time.time()
            await self.driver.async_wait_for_agent_configured(timeout)
            end_time = time.time()
            self.logger.info(
                f"Agent reached configured state in {end_time - start_time} seconds"
            )
        if taac_types.Service.BGP in input.services:
            if self.ixia and "rsw" in self.hostname:
                self.ixia.restart_bgp_peers([self.hostname.upper()])
            timeout = (
                input.service_convergence_timeout.get(taac_types.Service.BGP)
                or input.timeout
            )
            start_time = time.time()
            await self.driver.async_wait_for_bgp_convergence(timeout)
            end_time = time.time()
            self.logger.info(f"Bgpd converged in {end_time - start_time} seconds")
        if taac_types.Service.QSFP_SERVICE in input.services and self.is_fboss:
            timeout = (
                input.service_convergence_timeout.get(taac_types.Service.QSFP_SERVICE)
                or input.timeout
            )
            start_time = time.time()
            # pyre-ignore
            await self.driver.async_wait_for_qsfp_service_state_active(timeout)
            end_time = time.time()
            self.logger.info(
                f"qsfp_service reached active state in {end_time - start_time} seconds"
            )
        if taac_types.Service.FSDB in input.services and self.is_fboss:
            timeout = (
                input.service_convergence_timeout.get(taac_types.Service.FSDB)
                or input.timeout
            )
            start_time = time.time()
            # pyre-ignore
            await self.driver.async_wait_for_fsdb_state_active(timeout)
            end_time = time.time()
            self.logger.info(
                f"fsdb reached active state in {end_time - start_time} seconds"
            )
