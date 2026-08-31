# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""Point-in-time GAR capacity checks for production VF and injected scale routes."""

from __future__ import annotations

import logging
import typing as t

from taac.constants import TestTopology
from taac.health_checks.abstract_health_check import (
    AbstractTopologyHealthCheck,
)
from taac.libs.fpf.fpf_gar import (
    wait_for_gar_pairs,
    wait_for_gar_prefixes,
)
from taac.health_check.health_check import types as hc_types


async def _run_gar_capacity_check(
    *,
    check_kind: str,
    check_params: dict[str, t.Any],
    logger: logging.Logger,
) -> hc_types.HealthCheckResult:
    pairs = list(check_params.get("pairs") or [])
    if not pairs:
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.FAIL,
            message=f"{check_kind} GAR check requires a non-empty pairs list",
        )

    timeout_sec = float(check_params.get("timeout_sec", 120))
    poll_interval_sec = float(check_params.get("poll_interval_sec", 5))
    try:
        if check_kind == "VF":
            prefixes = list(check_params.get("prefixes") or [])
            if not prefixes:
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.FAIL,
                    message="VF GAR check requires a non-empty prefixes list",
                )
            summaries = await wait_for_gar_prefixes(
                pairs=pairs,
                prefixes=prefixes,
                timeout_sec=timeout_sec,
                poll_interval_sec=poll_interval_sec,
                logger=logger,
            )
        else:
            summaries = await wait_for_gar_pairs(
                pairs=pairs,
                prefix_base=str(check_params["prefix_base"]),
                prefix_count=int(check_params["prefix_count"]),
                increment_step=str(check_params.get("increment_step", "0:0:1::")),
                timeout_sec=timeout_sec,
                poll_interval_sec=poll_interval_sec,
                logger=logger,
            )
    except (KeyError, TypeError, ValueError, RuntimeError) as error:
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.FAIL,
            message=f"{check_kind} GAR capacity validation failed: {error}",
        )

    return hc_types.HealthCheckResult(
        status=hc_types.HealthCheckStatus.PASS,
        message=f"{check_kind} GAR capacity validation passed\n" + "\n".join(summaries),
    )


class FpfGarVfCapacityHealthCheck(
    AbstractTopologyHealthCheck[hc_types.BaseHealthCheckIn]
):
    """Validate one or more production VF prefixes across a GAR pair."""

    CHECK_NAME = hc_types.CheckName.FPF_GAR_VF_CAPACITY_CHECK

    async def _run(
        self,
        obj: TestTopology,
        input: hc_types.BaseHealthCheckIn,
        check_params: dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        return await _run_gar_capacity_check(
            check_kind="VF",
            check_params=check_params,
            logger=self.logger,
        )


class FpfGarScaleCapacityHealthCheck(
    AbstractTopologyHealthCheck[hc_types.BaseHealthCheckIn]
):
    """Validate the complete injected prefix set across a GAR pair."""

    CHECK_NAME = hc_types.CheckName.FPF_GAR_SCALE_CAPACITY_CHECK

    async def _run(
        self,
        obj: TestTopology,
        input: hc_types.BaseHealthCheckIn,
        check_params: dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        return await _run_gar_capacity_check(
            check_kind="scale",
            check_params=check_params,
            logger=self.logger,
        )
