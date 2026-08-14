# pyre-unsafe
"""
Thin abstract interface for TAAC traffic generators.

Defines only the methods that TaacRunner, health checks, and steps call —
the contract between the test framework and whatever traffic backend is in use.
Restpy-specific internals (StatViewAssistant, apply_changes, etc.) stay on
the concrete classes and are NOT part of this interface.

Implementations:
  - TaacIxia (restpy): full ixnetwork-restpy wrapper, background StatViewAssistant
  - OtgTrafficGen (OTG/snappi): idiomatic OTG, declarative set_config, simple polling

── Adding new methods ──────────────────────────────────────────────────
Before adding a method here, ask:

  "Can BOTH backends provide a meaningful implementation?"

  YES → Add it here. The implementations don't need to be identical —
        just semantically equivalent (e.g. configure_traffic_item mutates
        ConfigElements+Apply on restpy, mutates flow+set_config on OTG).

  NO  → Do NOT add it here. Instead, guard the call in taac_runner.py
        with hasattr()/isinstance() and add the attr name to
        NON_ABC_ALLOWED in test_otg_traffic_gen.py::
          TestAbstractTrafficGeneratorABC::
            test_taac_runner_ixia_calls_are_on_abc_or_guarded.

  NEVER add a method here with `raise NotImplementedError` on
  OtgTrafficGen — that just defers a crash from import-time to
  call-time. A CI test enforces this.
────────────────────────────────────────────────────────────────────────
"""

import typing as t
from abc import ABC, abstractmethod

from ixia.ixia import types as ixia_types


class AbstractTrafficGenerator(ABC):
    """
    Traffic generator interface consumed by TaacRunner.
    """

    # -- Test case lifecycle (called by TaacRunner) --

    @abstractmethod
    def begin_test_case(
        self,
        test_case_uuid: str,
        traffic_regexes: t.Optional[t.List[str]] = None,
    ) -> None:
        """
        Prepare traffic for a new test case iteration.

        Called at the start of each test case. Implementations should:
        1. Store test_case_uuid for stats keying
        2. Enable only the flows matching traffic_regexes (None = all)
        3. Finalize traffic config (restpy: regen/apply/init views; OTG: set_config)
        4. Start or resume background stats capture
        """
        ...

    @abstractmethod
    def end_test_case(
        self,
        traffic_regexes: t.Optional[t.List[str]] = None,
    ) -> None:
        """
        Wind down traffic after a test case iteration.

        Called at the end of each test case. Implementations should:
        1. Pause background stats capture
        2. Disable the flows matching traffic_regexes (None = all)
        """
        ...

    # -- Traffic control (called by steps) --

    @abstractmethod
    def start_traffic(self, regenerate_traffic_items: bool = False) -> None:
        """Start transmitting enabled flows."""
        ...

    @abstractmethod
    def stop_traffic(self) -> None:
        """Stop all flows."""
        ...

    # -- Stats (called by health checks) --

    @abstractmethod
    def get_latest_stats(
        self,
        max_timeout_sec: int = 180,
        since_time: float = 0,
    ) -> t.List[t.Dict[str, t.Any]]:
        """
        Return packet loss stats as list of dicts.

        Each dict has: identifier, packet_loss_duration, packet_loss_percentage,
        frame_delta.
        """
        ...

    @abstractmethod
    def clear_traffic_stats(self) -> None:
        """Clear captured stats between measurements."""
        ...

    @abstractmethod
    def get_traffic_start_time(self) -> float:
        """
        Wall-clock timestamp of the most recent start_traffic() call,
        or 0.0 if traffic has never been started.
        """
        ...

    @abstractmethod
    def has_traffic_items(self) -> bool:
        """Return True if any traffic items/flows are configured."""
        ...

    @abstractmethod
    def get_traffic_items(self) -> t.List:
        """
        Return configured traffic items.

        Restpy returns restpy TrafficItem objects. OTG returns flow name strings.
        """
        ...

    # -- Declarative configuration (read-only introspection) --
    #
    # These expose the thrift IxiaConfig the generator was BUILT from, not live
    # chassis state, so they involve no REST/API call and cannot block or raise.
    # Concrete (not abstract) with an empty default so a backend that carries no
    # declarative config still satisfies the interface.

    def get_port_configs(self) -> t.List[ixia_types.PortConfig]:
        """
        Return the thrift port configs this generator was configured with.

        Includes each port's L1 config, notably the PFC priority-to-queue map,
        which is otherwise only visible as a debug-logged Python repr.
        """
        return []

    def get_traffic_item_configs(self) -> t.List[ixia_types.TrafficItem]:
        """
        Return the thrift traffic-item configs this generator was configured with.

        Unlike ``get_traffic_items``, this is the declarative source config
        (endpoints, rate, frame size, QoS) rather than live backend objects.
        """
        return []

    # -- Protocols / BGP (called by steps) --

    @abstractmethod
    def restart_bgp_peers(self, regexes: t.Optional[t.List[str]] = None) -> None:
        """Restart BGP peers matching the regex(es), or all."""
        ...

    @abstractmethod
    def find_bgp_peers(
        self,
        regex: t.Optional[str] = None,
        ignore_case: bool = False,
    ) -> t.List:
        """Return BGP peers matching regex, or all."""
        ...

    # -- Traffic reconfiguration --

    @abstractmethod
    def configure_traffic_item(
        self,
        traffic_item_name: str,
        line_rate: t.Optional[int] = None,
        line_rate_type: t.Optional["ixia_types.RateType"] = None,
        frame_size_setting: t.Optional["ixia_types.FrameSize"] = None,
        qos_config: t.Optional["ixia_types.QoSConfig"] = None,
    ) -> None:
        """
        Reconfigure a traffic item/flow and commit the change.

        Modify rate, frame size, and/or QoS on the named traffic item,
        then apply the change so it takes effect immediately. Backends
        handle the commit internally (restpy: Generate + Apply; OTG:
        set_config).

        No-op if the named traffic item does not exist.
        """
        ...

    # -- Teardown --

    @abstractmethod
    def tear_down(self) -> None:
        """Release all resources (stop capture, clean up sessions)."""
        ...
