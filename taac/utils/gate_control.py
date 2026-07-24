# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-strict
"""Centralized gate control for TAAC test checks.

A "gate" is a named pass/fail check whose enforcement is either BLOCKING (raise
``TestCaseFailure`` on breach, failing the test) or PERMISSIVE (log a WARNING and
continue -- observe-only). Historically each test/step reimplemented this
raise-vs-warn branch and threaded its own ``<gate>_gate_mode`` param, so there
was no single place to see or flip which checks actually fail a run.

This module centralizes that so ANY test or step can either:

  * enforce a gate in an explicit mode via :func:`apply_gate` (the primitive), or
  * register a named gate's mode once and enforce it by name through the shared
    registry (:func:`register_gate` / :func:`set_gate_mode` /
    :func:`apply_registered_gate`) -- one place controls whether each check
    blocks or merely observes.

New gates default to PERMISSIVE: a freshly added check observes until it is
calibrated on a real run, then is flipped to BLOCKING centrally without touching
any call site. An unrecognized mode always raises up front so a typo can never
silently downgrade a blocking gate to permissive.
"""

import typing as t

from taac.constants import TestCaseFailure

GATE_MODE_BLOCKING = "blocking"
GATE_MODE_PERMISSIVE = "permissive"
_VALID_GATE_MODES: t.Tuple[str, ...] = (GATE_MODE_BLOCKING, GATE_MODE_PERMISSIVE)


def _validate_mode(mode: str) -> None:
    if mode not in _VALID_GATE_MODES:
        raise ValueError(
            f"Invalid gate mode {mode!r}; expected "
            f"{GATE_MODE_BLOCKING!r} or {GATE_MODE_PERMISSIVE!r}"
        )


def apply_gate(logger: t.Any, breached: bool, message: str, mode: str) -> None:
    """Enforce a single gate in blocking or permissive mode.

    On breach: ``blocking`` raises ``TestCaseFailure(message)``; ``permissive``
    logs a WARNING and continues. A non-breach is a no-op (the caller logs its
    own PASS line). An unrecognized ``mode`` raises ``ValueError`` up front.
    """
    _validate_mode(mode)

    if not breached:
        return

    if mode == GATE_MODE_BLOCKING:
        raise TestCaseFailure(message)

    logger.warning(f"[PERMISSIVE GATE] {message}")


class GateRegistry:
    """A central ``name -> mode`` registry for test gates.

    Register a gate once (default PERMISSIVE until calibrated), flip its mode in
    a single place with :meth:`set_mode`, and enforce it by name with
    :meth:`apply`. Tests that only need the raise-vs-warn primitive can call the
    module-level :func:`apply_gate` directly without registering anything.
    """

    def __init__(self, default_mode: str = GATE_MODE_PERMISSIVE) -> None:
        _validate_mode(default_mode)
        self._default_mode = default_mode
        self._modes: t.Dict[str, str] = {}

    def register(self, name: str, mode: t.Optional[str] = None) -> None:
        """Register (or re-register) ``name``; ``None`` uses the registry default."""
        resolved = self._default_mode if mode is None else mode
        _validate_mode(resolved)
        self._modes[name] = resolved

    def set_mode(self, name: str, mode: str) -> None:
        """Flip a gate's mode (registering it if new)."""
        _validate_mode(mode)
        self._modes[name] = mode

    def get_mode(self, name: str) -> str:
        """The registered mode for ``name``, or the registry default if unregistered."""
        return self._modes.get(name, self._default_mode)

    def is_registered(self, name: str) -> bool:
        return name in self._modes

    def registered_gates(self) -> t.Dict[str, str]:
        """A copy of the current ``name -> mode`` map (for reporting/debugging)."""
        return dict(self._modes)

    def apply(
        self,
        logger: t.Any,
        name: str,
        breached: bool,
        message: str,
        mode: t.Optional[str] = None,
    ) -> None:
        """Enforce gate ``name``; an explicit ``mode`` overrides the registry."""
        effective = self.get_mode(name) if mode is None else mode
        apply_gate(logger, breached, message, effective)


# Process-wide default registry + a thin free-function facade so callers don't
# have to thread a registry instance around.
_DEFAULT_REGISTRY = GateRegistry()


def register_gate(name: str, mode: t.Optional[str] = None) -> None:
    """Register a gate on the process-wide default registry."""
    _DEFAULT_REGISTRY.register(name, mode)


def set_gate_mode(name: str, mode: str) -> None:
    """Flip a gate's mode on the process-wide default registry."""
    _DEFAULT_REGISTRY.set_mode(name, mode)


def get_gate_mode(name: str) -> str:
    """The mode registered for ``name`` (default registry), or PERMISSIVE default."""
    return _DEFAULT_REGISTRY.get_mode(name)


def apply_registered_gate(
    logger: t.Any,
    name: str,
    breached: bool,
    message: str,
    mode: t.Optional[str] = None,
) -> None:
    """Enforce a registered gate by name via the process-wide default registry.

    An explicit ``mode`` (e.g. from a test-config param) overrides whatever the
    gate was registered with, so per-run overrides keep working during migration.
    """
    _DEFAULT_REGISTRY.apply(logger, name, breached, message, mode)
