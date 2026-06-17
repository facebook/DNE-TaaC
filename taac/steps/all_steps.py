# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import os
import typing as t

from taac.internal.steps.custom_step import CustomStep
from taac.steps.step import Step
from taac.steps.step_definitions import (
    AllocateCgroupSliceMemory,
    ChronosNode,
    DrainUndrainStep,
    DummyStep,
    EcmpMemberStaticRouteStep,
    InterfaceFlapStep,
    InvokeIxiaApiStep,
    LongevityStep,
    MassBgpPeerToggle,
    ModulePowerToggleStep,
    RegisterPatcherStep,
    RegisterPortChannelMinLinkPercentagePatchers,
    RegisterSpeedFlipPatcherStep,
    RunSSHCmdStep,
    RunTaskStep,
    ServiceConvergenceStep,
    ServiceInterruptionStep,
    SystemRebootStep,
    ValidationStep,
    VerifyFileModificationTimeStep,
    VerifyPortOperationalStateStep,
    VerifyPortSpeedStep,
)
from taac.test_as_a_config import types as taac_types

TAAC_OSS = os.environ.get("TAAC_OSS", "").lower() in ("1", "true", "yes")

OSS_STEPS: t.List[t.Type[Step]] = [
    DummyStep,
    ServiceInterruptionStep,
    ServiceConvergenceStep,
    DrainUndrainStep,
    InterfaceFlapStep,
    LongevityStep,
    RunSSHCmdStep,
    SystemRebootStep,
    ValidationStep,
    CustomStep,
    RegisterPatcherStep,
    InvokeIxiaApiStep,
    AllocateCgroupSliceMemory,
    RunTaskStep,
    ChronosNode,
    MassBgpPeerToggle,
    EcmpMemberStaticRouteStep,
    RegisterPortChannelMinLinkPercentagePatchers,
    VerifyPortOperationalStateStep,
    ModulePowerToggleStep,
    VerifyPortSpeedStep,
    VerifyFileModificationTimeStep,
    RegisterSpeedFlipPatcherStep,
]

if not TAAC_OSS:
    from taac.internal.steps.internal_steps import INTERNAL_STEPS
else:
    INTERNAL_STEPS = []

ALL_STEPS: t.List[t.Type[Step]] = OSS_STEPS + INTERNAL_STEPS


STEP_NAME_TO_INPUT = {
    # pyre-ignore
    step.STEP_NAME: t.get_args(step.__orig_bases__[0])[0]
    for step in ALL_STEPS
}


NAME_TO_STEP: t.Dict[taac_types.StepName, t.Type[Step]] = {
    step.STEP_NAME: step for step in ALL_STEPS
}
