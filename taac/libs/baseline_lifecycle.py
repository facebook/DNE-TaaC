# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-strict

"""Nested restoration boundaries for reusable TAAC test environments."""

from __future__ import annotations

import asyncio
import dataclasses
import enum
import typing as t


class BaselineScope(enum.StrEnum):
    TOPOLOGY = "topology"
    PLAYBOOK = "playbook"


class BaselineOperationTimeoutError(TimeoutError):
    def __init__(
        self,
        scope: BaselineScope,
        participant: str,
        operation: str,
        timeout_seconds: float,
    ) -> None:
        self.scope = scope
        self.participant = participant
        self.operation = operation
        self.timeout_seconds = timeout_seconds
        super().__init__(
            f"{scope.value} baseline {operation} for {participant} exceeded "
            f"the {timeout_seconds:g}s deadline"
        )


@dataclasses.dataclass(frozen=True)
class BaselineContext:
    test_config_name: str
    invocation_id: str
    playbook_name: str | None = None


class BaselineParticipant(t.Protocol):
    @property
    def name(self) -> str: ...

    async def capture(self, context: BaselineContext) -> object: ...

    async def restore(self, context: BaselineContext, snapshot: object) -> None: ...

    async def verify(self, context: BaselineContext, snapshot: object) -> None: ...

    async def release(self, context: BaselineContext, snapshot: object) -> None: ...


@dataclasses.dataclass(frozen=True)
class BaselineTimeouts:
    capture_seconds: float
    restore_seconds: float
    verify_seconds: float
    release_seconds: float

    def __post_init__(self) -> None:
        for field in dataclasses.fields(self):
            value = t.cast(float, getattr(self, field.name))
            if value <= 0:
                raise ValueError(f"{field.name} must be positive")


@dataclasses.dataclass(frozen=True)
class BaselineEvent:
    scope: BaselineScope
    participant: str
    operation: str
    status: str
    error: str | None = None


@dataclasses.dataclass(frozen=True)
class _Capture:
    participant: BaselineParticipant
    snapshot: object


@dataclasses.dataclass(frozen=True)
class _Frame:
    scope: BaselineScope
    context: BaselineContext
    captures: tuple[_Capture, ...]


class BaselineLifecycle:
    """Own nested baselines until their resources are restored or released."""

    def __init__(self, timeouts: BaselineTimeouts) -> None:
        self._timeouts = timeouts
        self._frames: list[_Frame] = []
        self._events: list[BaselineEvent] = []
        self._restoration_failures: list[BaseException] = []

    @property
    def active_scopes(self) -> tuple[BaselineScope, ...]:
        return tuple(frame.scope for frame in self._frames)

    @property
    def events(self) -> tuple[BaselineEvent, ...]:
        return tuple(self._events)

    @property
    def is_healthy(self) -> bool:
        return not self._restoration_failures

    @property
    def restoration_failures(self) -> tuple[BaseException, ...]:
        return tuple(self._restoration_failures)

    async def capture(
        self,
        scope: BaselineScope,
        context: BaselineContext,
        participants: t.Iterable[BaselineParticipant],
    ) -> None:
        self._validate_capture(scope, context)
        ordered = tuple(participants)
        self._validate_participants(ordered)
        captures: list[_Capture] = []
        try:
            for participant in ordered:
                snapshot = await self._run(
                    scope,
                    participant,
                    "capture",
                    self._timeouts.capture_seconds,
                    participant.capture(context),
                )
                captures.append(_Capture(participant, snapshot))
        except asyncio.CancelledError as cancellation:
            await self._rollback_cancelled_capture(
                scope, context, captures, cancellation
            )
            raise
        except Exception as primary_error:
            await self._rollback_failed_capture(scope, context, captures, primary_error)
        self._frames.append(_Frame(scope, context, tuple(captures)))

    async def _rollback_cancelled_capture(
        self,
        scope: BaselineScope,
        context: BaselineContext,
        captures: list[_Capture],
        cancellation: asyncio.CancelledError,
    ) -> None:
        rollback_errors = await self._restore_captures(
            scope,
            context,
            tuple(captures),
            operation_prefix="capture_rollback",
        )
        self._restoration_failures.extend(rollback_errors)
        for error in rollback_errors:
            cancellation.add_note(
                "Baseline capture rollback also failed: "
                f"{type(error).__name__}: {error}"
            )

    async def _rollback_failed_capture(
        self,
        scope: BaselineScope,
        context: BaselineContext,
        captures: list[_Capture],
        primary_error: BaseException,
    ) -> t.NoReturn:
        rollback_errors = await self._restore_captures(
            scope,
            context,
            tuple(captures),
            operation_prefix="capture_rollback",
        )
        self._restoration_failures.extend(rollback_errors)
        self._raise_with_cleanup_errors(
            "baseline capture and rollback failed",
            primary_error,
            rollback_errors,
        )

    async def restore(
        self, scope: BaselineScope, context: BaselineContext
    ) -> tuple[BaseException, ...]:
        if not self._frames:
            return ()
        frame = self._frames[-1]
        if frame.scope is not scope:
            raise RuntimeError(
                f"baseline restore must be LIFO: requested={scope.value}; "
                f"active={frame.scope.value}"
            )
        if frame.context != context:
            raise RuntimeError(
                f"baseline ownership mismatch for {scope.value}: "
                f"active_invocation={frame.context.invocation_id}; "
                f"requested_invocation={context.invocation_id}"
            )
        self._frames.pop()
        errors = await self._restore_captures(
            scope, context, frame.captures, operation_prefix="restore"
        )
        self._restoration_failures.extend(errors)
        return errors

    async def restore_all(self) -> tuple[BaseException, ...]:
        errors: list[BaseException] = []
        while self._frames:
            frame = self._frames[-1]
            errors.extend(await self.restore(frame.scope, frame.context))
        return tuple(errors)

    def _validate_capture(self, scope: BaselineScope, context: BaselineContext) -> None:
        if not self.is_healthy:
            raise RuntimeError(
                "baseline lifecycle is unsafe after a restoration failure; "
                "the test environment must be rebuilt before another capture"
            )
        if not context.test_config_name:
            raise ValueError("baseline context requires a TestConfig name")
        if not context.invocation_id:
            raise ValueError("baseline context requires an invocation ID")
        if scope is BaselineScope.TOPOLOGY:
            if self._frames:
                raise RuntimeError("topology baseline must be the root scope")
            if context.playbook_name is not None:
                raise ValueError("topology baseline cannot be owned by a Playbook")
            return
        if context.playbook_name is None:
            raise ValueError("playbook baseline requires a Playbook name")
        if not self._frames or self._frames[-1].scope is not BaselineScope.TOPOLOGY:
            raise RuntimeError("playbook baseline requires an active topology baseline")
        topology_context = self._frames[-1].context
        if (
            context.test_config_name != topology_context.test_config_name
            or context.invocation_id != topology_context.invocation_id
        ):
            raise RuntimeError(
                "playbook baseline must belong to its active topology baseline"
            )

    @staticmethod
    def _validate_participants(
        participants: tuple[BaselineParticipant, ...],
    ) -> None:
        names = [participant.name for participant in participants]
        if any(not name for name in names):
            raise ValueError("baseline participant names must be nonempty")
        if len(names) != len(set(names)):
            raise ValueError(f"duplicate baseline participant names: {names}")

    async def _restore_captures(
        self,
        scope: BaselineScope,
        context: BaselineContext,
        captures: tuple[_Capture, ...],
        *,
        operation_prefix: str,
    ) -> tuple[BaseException, ...]:
        errors: list[BaseException] = []
        for capture in reversed(captures):
            participant = capture.participant
            try:
                await self._run(
                    scope,
                    participant,
                    operation_prefix,
                    self._timeouts.restore_seconds,
                    participant.restore(context, capture.snapshot),
                )
                await self._run(
                    scope,
                    participant,
                    f"{operation_prefix}_verify",
                    self._timeouts.verify_seconds,
                    participant.verify(context, capture.snapshot),
                )
            except asyncio.CancelledError:
                raise
            except Exception as error:
                errors.append(error)
            finally:
                try:
                    await self._run(
                        scope,
                        participant,
                        f"{operation_prefix}_release",
                        self._timeouts.release_seconds,
                        participant.release(context, capture.snapshot),
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    errors.append(error)
        return tuple(errors)

    async def _run(
        self,
        scope: BaselineScope,
        participant: BaselineParticipant,
        operation: str,
        timeout_seconds: float,
        awaitable: t.Awaitable[t.Any],
    ) -> t.Any:
        self._events.append(
            BaselineEvent(scope, participant.name, operation, "started")
        )
        timeout = asyncio.timeout(timeout_seconds)
        try:
            async with timeout:
                result = await awaitable
        except TimeoutError as error:
            if timeout.expired():
                deadline_error = BaselineOperationTimeoutError(
                    scope,
                    participant.name,
                    operation,
                    timeout_seconds,
                )
                self._events.append(
                    BaselineEvent(
                        scope,
                        participant.name,
                        operation,
                        "failed",
                        f"{type(deadline_error).__name__}: {deadline_error}",
                    )
                )
                raise deadline_error from error
            self._events.append(
                BaselineEvent(
                    scope,
                    participant.name,
                    operation,
                    "failed",
                    f"{type(error).__name__}: {error}",
                )
            )
            raise
        except BaseException as error:
            self._events.append(
                BaselineEvent(
                    scope,
                    participant.name,
                    operation,
                    "failed",
                    f"{type(error).__name__}: {error}",
                )
            )
            raise
        self._events.append(
            BaselineEvent(scope, participant.name, operation, "completed")
        )
        return result

    @staticmethod
    def _raise_with_cleanup_errors(
        message: str,
        primary_error: BaseException,
        cleanup_errors: tuple[BaseException, ...],
    ) -> t.NoReturn:
        if not cleanup_errors:
            raise primary_error
        errors = [primary_error, *cleanup_errors]
        if all(isinstance(error, Exception) for error in errors):
            raise ExceptionGroup(message, t.cast(list[Exception], errors))
        raise BaseExceptionGroup(message, errors)
