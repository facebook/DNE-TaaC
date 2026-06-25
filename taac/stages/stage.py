# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""
Abstract base class for named Stage implementations + registry.

Stages with custom execution logic (beyond the default sequential/concurrent
step execution) should subclass this ABC and register a StageName in the
Thrift enum.

The default stage execution behavior lives in the runner. This ABC is for
stages that need to override that behavior — e.g., retry-until-converge,
conditional step skipping, or custom iteration patterns.
"""

import os
import typing as t
from abc import ABC, abstractmethod

from neteng.test_infra.dne.taac.constants import TestDevice, TestResult, TestTopology
from taac.ixia.taac_ixia import TaacIxia
from taac.libs.parameter_evaluator import ParameterEvaluator
from taac.utils.oss_taac_lib_utils import (
    ConsoleFileLogger,
    get_root_logger,
)
from taac.test_as_a_config import types as taac_types


class Stage(ABC):
    STAGE_NAME: str = "UNDEFINED"

    def __init__(
        self,
        stage: taac_types.Stage,
        devices: t.List[TestDevice],
        topology: TestTopology,
        test_case_results: t.List[TestResult],
        test_config: taac_types.TestConfig,
        test_case_name: str,
        test_case_start_time: float,
        parameter_evaluator: ParameterEvaluator,
        ixia: t.Optional[TaacIxia] = None,
        logger: t.Optional[ConsoleFileLogger] = None,
    ) -> None:
        self.stage = stage
        self.devices = devices
        self.topology = topology
        self.test_case_results = test_case_results
        self.test_config = test_config
        self.test_case_name = test_case_name
        self.test_case_start_time = test_case_start_time
        self.parameter_evaluator = parameter_evaluator
        self.ixia = ixia
        self.logger = logger or get_root_logger()

    @abstractmethod
    async def run(self) -> None:
        pass

    async def setUp(self) -> None:  # noqa: B027
        pass

    async def cleanUp(self) -> None:  # noqa: B027
        pass


# =============================================================================
# Stage Registry
# =============================================================================
# Maps stage names to Stage implementation classes. Stages without a registered
# implementation use the runner's default sequential/concurrent step execution
# logic.

TAAC_OSS = os.environ.get("TAAC_OSS", "").lower() in ("1", "true", "yes")

OSS_STAGES: t.List[t.Type[Stage]] = [
    # Add OSS-safe stage implementations here
]

if not TAAC_OSS:
    INTERNAL_STAGES: t.List[t.Type[Stage]] = [
        # Add internal-only stage implementations here
    ]
else:
    INTERNAL_STAGES = []

ALL_STAGES: t.List[t.Type[Stage]] = OSS_STAGES + INTERNAL_STAGES

NAME_TO_STAGE: t.Dict[str, t.Type[Stage]] = {
    stage.STAGE_NAME: stage for stage in ALL_STAGES
}
