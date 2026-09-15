# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-strict

"""IXIA-owned operations used by reusable route churn."""

from __future__ import annotations

import re
import typing as t

from taac.constants import TestCaseFailure


class RouteStormPool(t.Protocol):
    @property
    def name(self) -> str: ...

    @property
    def route(self) -> t.Any: ...

    @property
    def route_count(self) -> int: ...

    @property
    def selected_indices(self) -> tuple[int, ...]: ...

    @property
    def device_group(self) -> t.Any: ...

    @property
    def network_group(self) -> t.Any: ...


class IxiaRouteChurnOperations:
    def __init__(self, ixia: t.Any) -> None:
        self._ixia = ixia

    def matching_prefix_pools(self, regex: str) -> list[t.Any]:
        return list(self._ixia.get_prefix_pools_by_regexes(prefix_pool_regex=regex))

    def bgp_peer(self, prefix_pool: t.Any) -> t.Any:
        return self._ixia.map_prefix_pool_to_bgp_peer(prefix_pool)

    def network_group(self, prefix_pool: t.Any) -> t.Any:
        return self._ixia.map_prefix_pool_to_network_group(prefix_pool)

    def apply_changes(self) -> None:
        self._ixia.apply_changes()


class IxiaRouteStormOperations:
    """Own the IXIA API surface required by the EBB route-storm runtime."""

    def __init__(self, ixia: t.Any) -> None:
        self._ixia = ixia

    def matching_prefix_pools(self, names: t.Sequence[str]) -> tuple[t.Any, ...]:
        regex = f"^(?:{'|'.join(re.escape(name) for name in names)})$"
        return tuple(self._ixia.get_prefix_pools_by_regexes(prefix_pool_regex=regex))

    def mapped_structure_targets(self, pool: t.Any) -> tuple[t.Any, t.Any]:
        device_group = self._ixia.map_prefix_pool_to_device_group(pool)
        network_group = self._ixia.map_prefix_pool_to_network_group(pool)
        missing = [
            label
            for label, target in (
                ("device group", device_group),
                ("network group", network_group),
            )
            if target is None
        ]
        if missing:
            raise TestCaseFailure(
                f"IXIA pool {str(getattr(pool, 'Name', ''))!r} has no mapped "
                f"{' or '.join(missing)}"
            )
        return device_group, network_group

    def mapped_peer_values(self, pool: t.Any) -> tuple[t.Any, ...]:
        peer = self._ixia.map_prefix_pool_to_bgp_peer(pool)
        return tuple(peer.parent.Address.Values)

    def bgp_update_statistics(
        self,
        *,
        hostname: str | None = None,
        interface: str | None = None,
    ) -> t.Sequence[t.Mapping[str, t.Any]]:
        if hostname is None and interface is None:
            return self._ixia.get_bgp_update_statistics_strict()
        if hostname is None or interface is None:
            raise ValueError("hostname and interface must be provided together")
        return self._ixia.get_bgp_update_statistics_strict(
            hostname=hostname,
            interface=interface,
        )

    def configure_as_path_segments(
        self,
        route: t.Any,
        segment_pools: t.Sequence[tuple[str, t.Sequence[str]]],
    ) -> None:
        self._ixia.configure_as_path_segment_pools_on_route_property(
            route,
            segment_pools,
        )

    def configure_communities(
        self, route: t.Any, values: t.Sequence[t.Sequence[str]]
    ) -> None:
        self._ixia.configure_community_pool_on_route_property(route, values)

    def configure_extended_communities(
        self, route: t.Any, values: t.Sequence[t.Sequence[str]]
    ) -> None:
        self._ixia.configure_extended_community_pool_on_route_property(route, values)

    def apply_changes(self) -> None:
        self._ixia.apply_changes()

    def set_network_groups_running(
        self, pools: t.Sequence[RouteStormPool], running: bool
    ) -> None:
        self._set_components_running(
            self._unique_components(pool.network_group for pool in pools),
            running,
            "network groups",
        )

    def set_structure_targets_running(
        self, pools: t.Sequence[RouteStormPool], running: bool
    ) -> None:
        components = self._unique_components(
            component
            for pool in pools
            for component in (pool.device_group, pool.network_group)
        )
        if running:
            # Children must be armed before their parent starts the IXIA subtree.
            components.reverse()
        self._set_components_running(components, running, "structure targets")

    def set_route_rows_running(
        self,
        pools: t.Sequence[RouteStormPool],
        running: bool,
        *,
        selected_only: bool = False,
    ) -> None:
        transitioned: list[tuple[RouteStormPool, list[int]]] = []
        try:
            for pool in pools:
                zero_based_indices: t.Iterable[int] = (
                    pool.selected_indices if selected_only else range(pool.route_count)
                )
                session_indices = [index + 1 for index in zero_based_indices]
                operation = pool.route.Start if running else pool.route.Stop
                operation(SessionIndices=session_indices)
                transitioned.append((pool, session_indices))
        except Exception as operation_error:
            rollback_failures: dict[str, str] = {}
            for pool, session_indices in reversed(transitioned):
                try:
                    rollback = pool.route.Stop if running else pool.route.Start
                    rollback(SessionIndices=session_indices)
                except Exception as rollback_error:
                    rollback_failures[pool.name] = (
                        f"{type(rollback_error).__name__}: {rollback_error}"
                    )
            if transitioned:
                try:
                    self.apply_changes()
                except Exception as rollback_error:
                    rollback_failures["apply changes"] = (
                        f"{type(rollback_error).__name__}: {rollback_error}"
                    )
            if rollback_failures:
                action = "start" if running else "stop"
                raise TestCaseFailure(
                    f"failed to {action} IXIA route rows: "
                    f"{type(operation_error).__name__}: {operation_error}; "
                    f"rollback failures: {rollback_failures}"
                ) from operation_error
            raise

    def _set_components_running(
        self,
        components: t.Sequence[t.Any],
        running: bool,
        label: str,
    ) -> None:
        transitioned: list[t.Any] = []
        try:
            for component in components:
                operation = component.Start if running else component.Stop
                operation()
                transitioned.append(component)
        except Exception as operation_error:
            rollback_failures = self.rollback_structure_targets(transitioned, running)
            if rollback_failures:
                action = "start" if running else "stop"
                raise TestCaseFailure(
                    f"failed to {action} IXIA {label}: "
                    f"{type(operation_error).__name__}: {operation_error}; "
                    f"rollback failures: {rollback_failures}"
                ) from operation_error
            raise

    def rollback_structure_targets(
        self, transitioned: t.Sequence[t.Any], running: bool
    ) -> dict[str, str]:
        rollback_failures: dict[str, str] = {}
        for component in reversed(transitioned):
            try:
                rollback = component.Stop if running else component.Start
                rollback()
            except Exception as rollback_error:
                label = str(getattr(component, "href", id(component)))
                rollback_failures[label] = (
                    f"{type(rollback_error).__name__}: {rollback_error}"
                )
        if transitioned:
            try:
                self.apply_changes()
            except Exception as rollback_error:
                rollback_failures["apply changes"] = (
                    f"{type(rollback_error).__name__}: {rollback_error}"
                )
        return rollback_failures

    @staticmethod
    def _unique_components(components: t.Iterable[t.Any]) -> list[t.Any]:
        unique: list[t.Any] = []
        seen: set[str | int] = set()
        for component in components:
            href = getattr(component, "href", None)
            identity: str | int = str(href) if href is not None else id(component)
            if identity in seen:
                continue
            unique.append(component)
            seen.add(identity)
        return unique
