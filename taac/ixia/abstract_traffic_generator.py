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
"""

import typing as t
from abc import ABC, abstractmethod


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

    # -- Protocols / BGP (called by steps) --

    @abstractmethod
    def restart_bgp_peers(
        self, patterns: t.Optional[t.Union[str, t.List[str]]] = None
    ) -> None:
        """Restart BGP peers matching the pattern(s), or all."""
        ...

    @abstractmethod
    def find_bgp_peers(
        self,
        regex: t.Optional[str] = None,
        ignore_case: bool = False,
    ) -> t.List:
        """Return BGP peers matching regex, or all."""
        ...

    # -- Teardown --

    @abstractmethod
    def tear_down(self) -> None:
        """Release all resources (stop capture, clean up sessions)."""
        ...
