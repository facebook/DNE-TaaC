# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import os
import typing as t

TAAC_OSS = os.environ.get("TAAC_OSS", "").lower() in ("1", "true", "yes")

# CustomStep lives under taac.internal which isn't shipped in the OSS slice.
# SystemRebootStep and ValidationStep are now public via taac.steps.step_definitions
# (upstream restructure), so only CustomStep still needs gating.
# `t.TYPE_CHECKING or` keeps CustomStep visible to Pyre so the conditional
# OSS_STEPS.append(CustomStep) below doesn't trip "may be uninitialized".
if t.TYPE_CHECKING or not TAAC_OSS:
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

OSS_STEPS: t.List[t.Type[Step]] = [
    DummyStep,
    ServiceInterruptionStep,
    ServiceConvergenceStep,
    DrainUndrainStep,
    InterfaceFlapStep,
    LongevityStep,
    RunSSHCmdStep,
    # SystemRebootStep is selectable under OSS but its run() calls
    # wait_for_ping_reachable (netcastle, gated) and will raise
    # NotImplementedError at execution time.
    SystemRebootStep,
    ValidationStep,
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

# CustomStep lives under taac.internal — only add to OSS_STEPS when running
# against the Meta-internal environment.
if not TAAC_OSS:
    OSS_STEPS.append(CustomStep)

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
