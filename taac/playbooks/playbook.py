# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""
Abstract base class for named Playbook implementations.

Playbooks with custom orchestration logic (beyond the default sequential
stage execution) should subclass this ABC and register a PlaybookName.

The default playbook execution behavior lives in the runner. This ABC is
for playbooks that need to override that behavior — e.g., conditional
stage execution, dynamic stage generation, or custom retry strategies.
"""

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


class Playbook(ABC):
    PLAYBOOK_NAME: str = "UNDEFINED"

    def __init__(
        self,
        playbook: taac_types.Playbook,
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
        self.playbook = playbook
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


# ----- Registry (merged from playbooks/all.py during Phase 4 v2 closeout) -----
import os  # noqa: E402

TAAC_OSS = os.environ.get("TAAC_OSS", "").lower() in ("1", "true", "yes")

OSS_PLAYBOOKS: t.List[t.Type[Playbook]] = [
    # Add OSS-safe playbook implementations here
]

if not TAAC_OSS:
    INTERNAL_PLAYBOOKS: t.List[t.Type[Playbook]] = [
        # Add internal-only playbook implementations here
    ]
else:
    INTERNAL_PLAYBOOKS = []

ALL_PLAYBOOKS: t.List[t.Type[Playbook]] = OSS_PLAYBOOKS + INTERNAL_PLAYBOOKS

NAME_TO_PLAYBOOK: t.Dict[str, t.Type[Playbook]] = {
    playbook.PLAYBOOK_NAME: playbook for playbook in ALL_PLAYBOOKS
}
