# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe

import asyncio
import functools
import ipaddress
import json
import random
import threading
import time
import typing as t

from ixnetwork_restpy.errors import BadRequestError
from neteng.fboss.switch_config.thrift_types import PortSpeed
from taac.ixia.ixia import Ipv4PrefixPools
from taac.tasks.base_task import BaseTask
from taac.utils.common import get_default_bgp_configs
from taac.utils.driver_factory import async_get_device_driver
from taac.utils.oss_taac_lib_utils import (  # oss-rewrite (force ShipIt re-export to taac.* root)
    none_throws,
    retryable,
)


def _resolve_prefix_slots(
    prefix_pool_obj: t.Any,
    network_group_multiplier: int,
    total_route_ranges: int,
    prefix_start_index: int,
    prefix_end_index: t.Optional[int],
) -> t.Tuple[t.List[t.Tuple[int, int]], int]:
    """Route-property rows to modify for a ``[start, end)`` prefix window.

    A flat pool has one physical route-property row per logical prefix, so a
    prefix subrange maps directly to the repeated per-peer row geometry. A
    compact pool has one physical row per advertiser and stores the logical
    prefix cardinality in ``NumberOfAddresses``. Its physical row cannot select
    a logical-prefix subrange; callers must resize the pool and select all rows.

    Returns ``(slots, resolved_end_index)`` where ``slots`` is a list of
    ``(route_range_index, within_peer_index)`` pairs (the within-peer index lets
    callers cycle per-slot values, e.g. Origin) and ``resolved_end_index`` is the
    clamped end, for logging.

    Raises ``ValueError`` when prefix geometry is non-positive or when a compact
    pool is asked to select a partial logical-prefix range.
    """
    number_of_addresses = int(prefix_pool_obj.NumberOfAddresses)
    prefixes_per_peer = network_group_multiplier * number_of_addresses
    if prefixes_per_peer <= 0:
        raise ValueError(
            "prefixes_per_peer must be positive; verify network_group_multiplier "
            "and NumberOfAddresses configuration"
        )
    if network_group_multiplier == 1 and number_of_addresses > 1:
        if prefix_start_index != 0 or prefix_end_index not in {
            None,
            number_of_addresses,
        }:
            raise ValueError(
                "IXIA compact prefix pool cannot select a partial logical-prefix "
                "range; resize NumberOfAddresses and select the full pool"
            )
        return [(index, 0) for index in range(total_route_ranges)], number_of_addresses
    end_idx = min(prefix_end_index or prefixes_per_peer, prefixes_per_peer)
    slots = [
        (i, i % prefixes_per_peer)
        for i in range(total_route_ranges)
        if prefix_start_index <= (i % prefixes_per_peer) < end_idx
    ]
    return slots, end_idx


_IXIA_PREFIX_CONFIG_LOCK = threading.RLock()
_IXIA_BUSY_OPERATION_RETRY_TIMEOUT_SECONDS = 300.0
_IXIA_BUSY_OPERATION_RETRY_DELAY_SECONDS = 30.0


def _is_ixia_busy_operation_error(error: Exception) -> bool:
    message = str(error)
    return (
        isinstance(error, BadRequestError)
        and "exec not allowed currently since an operation (" in message
        and ") is in progress" in message
    )


def _retry_ixia_busy_operation(function):
    @functools.wraps(function)
    def wrapper(*args, **kwargs):
        deadline = time.monotonic() + _IXIA_BUSY_OPERATION_RETRY_TIMEOUT_SECONDS
        attempt = 1
        while True:
            try:
                return function(*args, **kwargs)
            except BadRequestError as error:
                if not _is_ixia_busy_operation_error(error):
                    raise
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise
                delay = min(_IXIA_BUSY_OPERATION_RETRY_DELAY_SECONDS, remaining)
                task = args[0]
                task.logger.warning(
                    "IXIA chassis operation is busy; retrying prefix mutation "
                    f"after {delay:.1f}s (attempt {attempt + 1}): {error}"
                )
                time.sleep(delay)
                attempt += 1

    return wrapper


def _serialized_ixia_prefix_config(function):
    @functools.wraps(function)
    def wrapper(*args, **kwargs):
        with _IXIA_PREFIX_CONFIG_LOCK:
            return function(*args, **kwargs)

    return wrapper


class IxiaEnableDisableBgpPrefixes(BaseTask):
    NAME = "ixia_enable_disable_bgp_prefixes"

    @staticmethod
    def _strict_active_bool(value: object, *, context: str) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized == "true":
                return True
            if normalized == "false":
                return False
        raise ValueError(
            f"IXIA Active.Values {context} must be a strict true/false value, "
            f"got {value!r}"
        )

    @classmethod
    def _normalized_active_values(
        cls, values: t.Iterable[object], *, context: str
    ) -> list[bool]:
        return [
            cls._strict_active_bool(value, context=f"{context} index {index}")
            for index, value in enumerate(values)
        ]

    @staticmethod
    def _route_property(prefix_pool_obj: t.Any) -> t.Any:
        properties = (
            prefix_pool_obj.BgpIPRouteProperty.find()
            if isinstance(prefix_pool_obj, Ipv4PrefixPools)
            else prefix_pool_obj.BgpV6IPRouteProperty.find()
        )
        if len(properties) != 1:
            raise ValueError(
                f"IXIA prefix pool {prefix_pool_obj.Name!r} has "
                f"{len(properties)} BGP route properties, expected 1"
            )
        return properties[0]

    def _exact_prefix_pools(
        self, prefix_pool_regex: str, expected_prefix_pool_count: int
    ) -> list[t.Any]:
        pools = list(
            self.ixia.get_prefix_pools_by_regexes(prefix_pool_regex=prefix_pool_regex)
        )
        if not pools:
            raise ValueError(
                f"No IXIA prefix pools matched regex {prefix_pool_regex!r}"
            )
        if len(pools) != expected_prefix_pool_count:
            raise ValueError(
                f"IXIA prefix-pool regex {prefix_pool_regex!r} matched "
                f"{len(pools)} pools, expected {expected_prefix_pool_count}: "
                f"{[pool.Name for pool in pools]}"
            )
        return pools

    def _fresh_active_values(
        self,
        prefix_pool_regex: str,
        expected_prefix_pool_count: int,
    ) -> dict[str, list[bool]]:
        return {
            name: state["active"]
            for name, state in self._fresh_pool_states(
                prefix_pool_regex, expected_prefix_pool_count
            ).items()
        }

    def _fresh_pool_states(
        self,
        prefix_pool_regex: str,
        expected_prefix_pool_count: int,
    ) -> dict[str, dict[str, t.Any]]:
        states: dict[str, dict[str, t.Any]] = {}
        for pool in self._exact_prefix_pools(
            prefix_pool_regex, expected_prefix_pool_count
        ):
            refresh_pool = getattr(pool, "refresh", None)
            if callable(refresh_pool):
                refresh_pool()
            route_property = self._route_property(pool)
            refresh_property = getattr(route_property, "refresh", None)
            if callable(refresh_property):
                refresh_property()
            name = str(pool.Name)
            states[name] = {
                "active": self._normalized_active_values(
                    route_property.Active.Values,
                    context=f"readback for {name!r}",
                ),
                "number_of_addresses": (
                    int(pool.NumberOfAddresses)
                    if getattr(pool, "NumberOfAddresses", None) is not None
                    else None
                ),
            }
        return states

    def _verify_fresh_active_values(
        self,
        prefix_pool_regex: str,
        expected_prefix_pool_count: int,
        expected_by_pool: t.Mapping[str, list[bool]],
        expected_number_of_addresses: int | None = None,
        expected_number_of_addresses_by_pool: t.Mapping[str, int] | None = None,
    ) -> None:
        if (
            expected_number_of_addresses is not None
            and expected_number_of_addresses_by_pool is not None
        ):
            raise ValueError(
                "Specify one NumberOfAddresses readback expectation, not both"
            )
        observed_states = self._fresh_pool_states(
            prefix_pool_regex, expected_prefix_pool_count
        )
        observed_by_pool = {
            name: state["active"] for name, state in observed_states.items()
        }
        if observed_by_pool != expected_by_pool:
            raise ValueError(
                "IXIA prefix-pool Active.Values readback mismatch from fresh lookup: "
                f"expected={dict(expected_by_pool)}, observed={observed_by_pool}"
            )
        if (
            expected_number_of_addresses is not None
            or expected_number_of_addresses_by_pool is not None
        ):
            observed_counts = {
                name: state["number_of_addresses"]
                for name, state in observed_states.items()
            }
            expected_counts = (
                dict(expected_number_of_addresses_by_pool)
                if expected_number_of_addresses_by_pool is not None
                else dict.fromkeys(expected_by_pool, expected_number_of_addresses)
            )
            if observed_counts != expected_counts:
                raise ValueError(
                    "IXIA prefix-pool NumberOfAddresses readback mismatch from "
                    f"fresh lookup: expected={expected_counts}, "
                    f"observed={observed_counts}"
                )

    def _verify_fresh_inactive_values(
        self,
        prefix_pool_regex: str,
        expected_prefix_pool_count: int,
        expected_number_of_addresses: int,
        expected_active_value_counts: t.Mapping[str, int] | None = None,
    ) -> None:
        observed_states = self._fresh_pool_states(
            prefix_pool_regex, expected_prefix_pool_count
        )
        observed_counts = {
            name: state["number_of_addresses"]
            for name, state in observed_states.items()
        }
        expected_counts = dict.fromkeys(observed_states, expected_number_of_addresses)
        if observed_counts != expected_counts:
            raise ValueError(
                "IXIA prefix-pool NumberOfAddresses readback mismatch from "
                f"fresh lookup: expected={expected_counts}, "
                f"observed={observed_counts}"
            )
        observed_active_value_counts: dict[str, int] = {}
        for name, state in observed_states.items():
            values = state["active"]
            if not values:
                raise ValueError(
                    f"IXIA prefix pool {name!r} returned no fresh Active.Values"
                )
            if any(values):
                raise ValueError(
                    f"IXIA prefix pool {name!r} is not fully inactive after resize"
                )
            observed_active_value_counts[name] = len(values)
        if (
            expected_active_value_counts is not None
            and observed_active_value_counts != expected_active_value_counts
        ):
            raise ValueError(
                "IXIA prefix-pool Active.Values cardinality mismatch after resize: "
                f"expected={dict(expected_active_value_counts)}, "
                f"observed={observed_active_value_counts}"
            )

    def _write_all_fresh_active_values_inactive(
        self,
        prefix_pool_regex: str,
        expected_prefix_pool_count: int,
        expected_pool_names: t.Collection[str],
    ) -> None:
        pools = self._exact_prefix_pools(prefix_pool_regex, expected_prefix_pool_count)
        if {str(pool.Name) for pool in pools} != set(expected_pool_names):
            raise ValueError("IXIA prefix-pool set changed before full withdrawal")
        for pool in pools:
            refresh_pool = getattr(pool, "refresh", None)
            if callable(refresh_pool):
                refresh_pool()
            route_property = self._route_property(pool)
            refresh_property = getattr(route_property, "refresh", None)
            if callable(refresh_property):
                refresh_property()
            values = self._normalized_active_values(
                route_property.Active.Values,
                context=f"full withdrawal for {pool.Name!r}",
            )
            if not values:
                raise ValueError(
                    f"IXIA prefix pool {pool.Name!r} returned no Active.Values"
                )
            route_property.Active.ValueList([False] * len(values))
        self.ixia.apply_changes()

    @staticmethod
    def _run_cleanup_operations(
        operations: t.Iterable[t.Callable[[], None]],
    ) -> list[Exception]:
        failures = []
        for operation in operations:
            try:
                operation()
            except Exception as error:
                failures.append(error)
        return failures

    def _restore_safe_active_values(
        self,
        pools: t.Sequence[t.Any],
        prefix_pool_regex: str,
        expected_prefix_pool_count: int,
        safe_values_by_pool: t.Mapping[str, list[bool]],
        failures: list[Exception],
    ) -> None:
        operations: list[t.Callable[[], None]] = [
            lambda pool=pool: self._route_property(pool).Active.ValueList(
                safe_values_by_pool[str(pool.Name)]
            )
            for pool in pools
        ]
        failures.extend(self._run_cleanup_operations(operations))

        def apply_and_verify() -> None:
            self.ixia.apply_changes()
            self._verify_fresh_active_values(
                prefix_pool_regex,
                expected_prefix_pool_count,
                safe_values_by_pool,
            )

        failures.extend(self._run_cleanup_operations((apply_and_verify,)))

    def _read_safe_active_value_count(
        self,
        pool: t.Any,
        active_value_counts_by_pool: dict[str, int],
    ) -> None:
        route_property = self._route_property(pool)
        current_values = self._normalized_active_values(
            route_property.Active.Values,
            context=f"fail-closed withdrawal for {pool.Name!r}",
        )
        route_property_count = int(route_property.Count)
        if len(current_values) != route_property_count:
            raise ValueError(
                f"IXIA compact prefix pool {pool.Name!r} has "
                f"{len(current_values)} Active.Values for route-property "
                f"Count={route_property_count}"
            )
        active_value_counts_by_pool[str(pool.Name)] = route_property_count

    def _resize_prefix_pools(
        self,
        prefix_pool_regex: str,
        expected_prefix_pool_count: int,
        target_number_of_addresses: int,
        expected_pool_names: t.Collection[str] | None = None,
    ) -> None:
        pools = self._exact_prefix_pools(prefix_pool_regex, expected_prefix_pool_count)
        if expected_pool_names is not None and {
            str(pool.Name) for pool in pools
        } != set(expected_pool_names):
            raise ValueError("IXIA prefix-pool set changed before compact resize")
        for pool in pools:
            pool.NumberOfAddresses = target_number_of_addresses
        self.ixia.apply_changes()

    def _verify_safe_compact_capacity(
        self,
        prefix_pool_regex: str,
        expected_prefix_pool_count: int,
        safe_number_of_addresses: int,
        active_value_counts_by_pool: t.Mapping[str, int],
    ) -> None:
        self._verify_fresh_inactive_values(
            prefix_pool_regex,
            expected_prefix_pool_count,
            safe_number_of_addresses,
            active_value_counts_by_pool or None,
        )

    def _restore_safe_compact_capacity(
        self,
        pools: t.Sequence[t.Any],
        prefix_pool_regex: str,
        expected_prefix_pool_count: int,
        safe_values_by_pool: t.Mapping[str, list[bool]],
        safe_number_of_addresses: int,
        failures: list[Exception],
    ) -> None:
        active_value_counts_by_pool: dict[str, int] = {}
        failures.extend(
            self._run_cleanup_operations(
                lambda pool=pool: self._read_safe_active_value_count(
                    pool, active_value_counts_by_pool
                )
                for pool in pools
            )
        )

        def withdraw_and_resize() -> None:
            self._write_all_fresh_active_values_inactive(
                prefix_pool_regex,
                expected_prefix_pool_count,
                safe_values_by_pool,
            )
            self._resize_prefix_pools(
                prefix_pool_regex,
                expected_prefix_pool_count,
                safe_number_of_addresses,
            )

        def withdraw_and_verify() -> None:
            self._write_all_fresh_active_values_inactive(
                prefix_pool_regex,
                expected_prefix_pool_count,
                safe_values_by_pool,
            )
            self._verify_safe_compact_capacity(
                prefix_pool_regex,
                expected_prefix_pool_count,
                safe_number_of_addresses,
                active_value_counts_by_pool,
            )

        failures.extend(
            self._run_cleanup_operations((withdraw_and_resize, withdraw_and_verify))
        )

    def _force_fail_closed_withdrawal(
        self,
        prefix_pool_regex: str,
        expected_prefix_pool_count: int,
        safe_values_by_pool: t.Mapping[str, list[bool]],
        safe_number_of_addresses: int | None = None,
    ) -> None:
        pools = self._exact_prefix_pools(prefix_pool_regex, expected_prefix_pool_count)
        if {str(pool.Name) for pool in pools} != set(safe_values_by_pool):
            raise ValueError(
                "IXIA prefix-pool set changed during fail-closed withdrawal"
            )
        failures: list[Exception] = []
        if safe_number_of_addresses is None:
            self._restore_safe_active_values(
                pools,
                prefix_pool_regex,
                expected_prefix_pool_count,
                safe_values_by_pool,
                failures,
            )
        else:
            self._restore_safe_compact_capacity(
                pools,
                prefix_pool_regex,
                expected_prefix_pool_count,
                safe_values_by_pool,
                safe_number_of_addresses,
                failures,
            )
        if failures:
            raise ValueError(
                f"IXIA fail-closed withdrawal had {len(failures)} failures"
            ) from ExceptionGroup("IXIA fail-closed withdrawal failures", failures)

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        prefix_pool_regex = params["prefix_pool_regex"]
        prefix_start_index = params.get("prefix_start_index", 0)
        prefix_end_index = params.get("prefix_end_index")
        expected_prefix_pool_count = params.get("expected_prefix_pool_count")
        expected_number_of_addresses = params.get("expected_number_of_addresses")
        target_number_of_addresses = params.get("target_number_of_addresses")
        allowed_current_number_of_addresses = params.get(
            "allowed_current_number_of_addresses"
        )
        safe_number_of_addresses = params.get("safe_number_of_addresses")
        runtime_route_operation = params.get("runtime_route_operation", False)
        enable = params["enable"]
        legacy_args = (
            enable,
            prefix_pool_regex,
            prefix_start_index,
            prefix_end_index,
            expected_prefix_pool_count,
        )
        extended_values = (
            expected_number_of_addresses,
            target_number_of_addresses,
            allowed_current_number_of_addresses,
            safe_number_of_addresses,
            runtime_route_operation,
        )
        has_extended_values = any(
            value is not None for value in extended_values[:-1]
        ) or bool(runtime_route_operation)
        args = (*legacy_args, *extended_values) if has_extended_values else legacy_args
        await asyncio.to_thread(self.configure_bgp_prefixes_active_state, *args)

    @_serialized_ixia_prefix_config
    @_retry_ixia_busy_operation
    def configure_bgp_prefixes_active_state(
        self,
        active_state: bool,
        prefix_pool_regex: str,
        prefix_start_index: int = 0,
        prefix_end_index: t.Optional[int] = None,
        expected_prefix_pool_count: t.Optional[int] = None,
        expected_number_of_addresses: t.Optional[int] = None,
        target_number_of_addresses: t.Optional[int] = None,
        allowed_current_number_of_addresses: t.Optional[t.Sequence[int]] = None,
        safe_number_of_addresses: t.Optional[int] = None,
        runtime_route_operation: bool = False,
    ) -> None:
        """
        Advertise or withdraw BGP prefixes within a specified range for matching prefix pools.

        This method controls BGP prefix advertisement by setting the active state in IXIA:
        - Active (True) = Prefixes are advertised to BGP peers
        - Inactive (False) = Prefixes are withdrawn from BGP peers

        The method operates by:
        1. Finding all prefix pools matching the provided regex pattern
        2. For each prefix pool, selecting prefixes within the specified index range
        3. Setting the active state (advertised/withdrawn) for those prefixes
        4. Applying the changes to the IXIA configuration

        The method handles both IPv4 and IPv6 prefix pools and uses modulo arithmetic
        to map prefix indices to their position within the network group multiplier.

        Args:
            active_state: True to advertise prefixes, False to withdraw them
            prefix_pool_regex: Regex pattern to match prefix pool names
            prefix_start_index: Starting index (inclusive) within the network group multiplier.
                Defaults to 0.
            prefix_end_index: Ending index (exclusive) within the network group multiplier.
                If None, uses the network group multiplier value (all remaining prefixes).
            expected_prefix_pool_count: If set, require exactly this many matching
                prefix pools. Must be a positive integer.
        """
        allowed_counts = self._validate_prefix_mutation_inputs(
            active_state=active_state,
            prefix_start_index=prefix_start_index,
            prefix_end_index=prefix_end_index,
            expected_prefix_pool_count=expected_prefix_pool_count,
            expected_number_of_addresses=expected_number_of_addresses,
            target_number_of_addresses=target_number_of_addresses,
            allowed_current_number_of_addresses=allowed_current_number_of_addresses,
            safe_number_of_addresses=safe_number_of_addresses,
            runtime_route_operation=runtime_route_operation,
        )
        mutation_plan, safe_values_by_pool, current_counts_by_pool, active_counts = (
            self._build_prefix_mutation_plan(
                active_state=active_state,
                prefix_pool_regex=prefix_pool_regex,
                prefix_start_index=prefix_start_index,
                prefix_end_index=prefix_end_index,
                expected_prefix_pool_count=expected_prefix_pool_count,
                expected_number_of_addresses=expected_number_of_addresses,
                target_number_of_addresses=target_number_of_addresses,
                allowed_counts=allowed_counts,
                safe_number_of_addresses=safe_number_of_addresses,
            )
        )
        self._apply_prefix_mutation_plan(
            active_state=active_state,
            prefix_pool_regex=prefix_pool_regex,
            prefix_start_index=prefix_start_index,
            expected_prefix_pool_count=expected_prefix_pool_count,
            expected_number_of_addresses=expected_number_of_addresses,
            target_number_of_addresses=target_number_of_addresses,
            safe_number_of_addresses=safe_number_of_addresses,
            runtime_route_operation=runtime_route_operation,
            mutation_plan=mutation_plan,
            safe_values_by_pool=safe_values_by_pool,
            current_counts_by_pool=current_counts_by_pool,
            active_value_counts_by_pool=active_counts,
        )

    @staticmethod
    def _validate_positive_optional_int(name: str, value: t.Any) -> None:
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
        ):
            raise ValueError(
                f"{name} must be a positive non-bool integer, got {value!r}"
            )

    @staticmethod
    def _validate_compact_resize_inputs(
        *,
        active_state: bool,
        prefix_start_index: int,
        prefix_end_index: int | None,
        expected_prefix_pool_count: int | None,
        allowed_counts: tuple[int, ...],
        safe_number_of_addresses: int | None,
    ) -> None:
        if active_state:
            raise ValueError("IXIA compact prefix-pool resize requires enable=False")
        if prefix_start_index != 0 or prefix_end_index is not None:
            raise ValueError(
                "IXIA compact prefix-pool resize requires a full-pool withdrawal"
            )
        if expected_prefix_pool_count is None:
            raise ValueError(
                "IXIA compact prefix-pool resize requires exact pool cardinality"
            )
        if not allowed_counts:
            raise ValueError(
                "IXIA compact prefix-pool resize requires allowed current counts"
            )
        if safe_number_of_addresses is None:
            raise ValueError(
                "IXIA compact prefix-pool resize requires a fail-closed count"
            )

    @classmethod
    def _validate_prefix_mutation_inputs(
        cls,
        *,
        active_state: bool,
        prefix_start_index: int,
        prefix_end_index: int | None,
        expected_prefix_pool_count: int | None,
        expected_number_of_addresses: int | None,
        target_number_of_addresses: int | None,
        allowed_current_number_of_addresses: t.Sequence[int] | None,
        safe_number_of_addresses: int | None,
        runtime_route_operation: bool,
    ) -> tuple[int, ...]:
        cls._validate_positive_optional_int(
            "expected_prefix_pool_count", expected_prefix_pool_count
        )
        for name, value in (
            ("expected_number_of_addresses", expected_number_of_addresses),
            ("target_number_of_addresses", target_number_of_addresses),
            ("safe_number_of_addresses", safe_number_of_addresses),
        ):
            cls._validate_positive_optional_int(name, value)
        allowed_counts = (
            tuple(allowed_current_number_of_addresses)
            if allowed_current_number_of_addresses is not None
            else ()
        )
        if not isinstance(runtime_route_operation, bool):
            raise ValueError(
                "runtime_route_operation must be a boolean, got "
                f"{runtime_route_operation!r}"
            )
        if runtime_route_operation and expected_prefix_pool_count != 1:
            raise ValueError(
                "IXIA runtime route operation requires exact pool cardinality 1"
            )
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
            for value in allowed_counts
        ):
            raise ValueError(
                "allowed_current_number_of_addresses must contain only positive "
                f"non-bool integers, got {allowed_counts!r}"
            )
        if target_number_of_addresses is not None:
            cls._validate_compact_resize_inputs(
                active_state=active_state,
                prefix_start_index=prefix_start_index,
                prefix_end_index=prefix_end_index,
                expected_prefix_pool_count=expected_prefix_pool_count,
                allowed_counts=allowed_counts,
                safe_number_of_addresses=safe_number_of_addresses,
            )
        return allowed_counts

    def _raise_resize_precondition(
        self,
        error: Exception,
        *,
        target_number_of_addresses: int | None,
        prefix_pool_regex: str,
        expected_prefix_pool_count: int | None,
        safe_values_by_pool: t.Mapping[str, list[bool]],
        safe_number_of_addresses: int | None,
    ) -> t.NoReturn:
        if target_number_of_addresses is None:
            raise error
        try:
            self._force_fail_closed_withdrawal(
                prefix_pool_regex,
                t.cast(int, expected_prefix_pool_count),
                safe_values_by_pool,
                safe_number_of_addresses,
            )
        except Exception as cleanup_error:
            raise ValueError(
                "IXIA compact prefix-pool precondition and fail-closed "
                f"restoration failed: precondition={error!r}, "
                f"cleanup={cleanup_error!r}"
            ) from ExceptionGroup(
                "IXIA compact resize precondition and cleanup failures",
                [error, cleanup_error],
            )
        raise error

    @staticmethod
    def _resolve_prefix_pool_current_count(
        prefix_pool_obj: t.Any,
        *,
        network_group_multiplier: t.Any,
        expected_number_of_addresses: int | None,
        target_number_of_addresses: int | None,
        allowed_counts: tuple[int, ...],
        raise_precondition: t.Callable[[Exception], t.NoReturn],
    ) -> int | None:
        if target_number_of_addresses is not None:
            if int(network_group_multiplier) != 1:
                raise_precondition(
                    ValueError(
                        "IXIA compact prefix-pool resize requires NetworkGroup "
                        f"Multiplier=1 for {prefix_pool_obj.Name!r}, got "
                        f"{network_group_multiplier!r}"
                    )
                )
            current_count = int(prefix_pool_obj.NumberOfAddresses)
            if current_count not in allowed_counts:
                raise_precondition(
                    ValueError(
                        f"IXIA prefix pool {prefix_pool_obj.Name!r} has "
                        f"NumberOfAddresses={current_count}, expected one of "
                        f"{allowed_counts!r}"
                    )
                )
            return current_count
        if (
            expected_number_of_addresses is not None
            and int(prefix_pool_obj.NumberOfAddresses) != expected_number_of_addresses
        ):
            raise ValueError(
                f"IXIA prefix pool {prefix_pool_obj.Name!r} has "
                f"NumberOfAddresses={prefix_pool_obj.NumberOfAddresses}, "
                f"expected {expected_number_of_addresses}"
            )
        return None

    def _prepare_prefix_active_values(
        self,
        prefix_pool_obj: t.Any,
        route_property: t.Any,
        current_count: int | None,
        raise_precondition: t.Callable[[Exception], t.NoReturn],
    ) -> tuple[list[bool], list[bool], int | None]:
        try:
            active_values = self._normalized_active_values(
                route_property.Active.Values,
                context=f"initial values for {prefix_pool_obj.Name!r}",
            )
        except Exception as error:
            raise_precondition(error)
        safe_values = list(active_values)
        if current_count is None:
            return active_values, safe_values, None
        route_property_count = int(route_property.Count)
        if not active_values or len(active_values) != route_property_count:
            raise_precondition(
                ValueError(
                    f"IXIA compact prefix pool {prefix_pool_obj.Name!r} "
                    f"has {len(active_values)} Active.Values for route-property "
                    f"Count={route_property_count}"
                )
            )
        return (
            [False] * len(active_values),
            [False] * len(safe_values),
            route_property_count,
        )

    @staticmethod
    def _resolve_active_slots(
        prefix_pool_obj: t.Any,
        network_group_multiplier: int,
        active_value_count: int,
        prefix_start_index: int,
        prefix_end_index: int | None,
        raise_precondition: t.Callable[[Exception], t.NoReturn],
    ) -> tuple[list[tuple[int, int]], int]:
        number_of_addresses = int(prefix_pool_obj.NumberOfAddresses)
        if network_group_multiplier == 1 and number_of_addresses > 1:
            if prefix_start_index != 0 or prefix_end_index not in {
                None,
                number_of_addresses,
            }:
                raise_precondition(
                    ValueError(
                        f"IXIA compact prefix pool {prefix_pool_obj.Name!r} "
                        "cannot select a partial logical-prefix range; resize "
                        "NumberOfAddresses and select the full pool"
                    )
                )
            return list(enumerate([0] * active_value_count)), number_of_addresses
        return _resolve_prefix_slots(
            prefix_pool_obj,
            network_group_multiplier,
            active_value_count,
            prefix_start_index,
            prefix_end_index,
        )

    def _build_prefix_mutation_entry(
        self,
        prefix_pool_obj: t.Any,
        *,
        active_state: bool,
        prefix_start_index: int,
        prefix_end_index: int | None,
        expected_number_of_addresses: int | None,
        target_number_of_addresses: int | None,
        allowed_counts: tuple[int, ...],
        raise_precondition: t.Callable[[Exception], t.NoReturn],
    ) -> tuple[
        tuple[t.Any, t.Any, list[bool], int, tuple[int, ...]],
        list[bool],
        int | None,
        int | None,
    ]:
        try:
            route_property = self._route_property(prefix_pool_obj)
        except Exception as error:
            raise_precondition(error)
        try:
            network_group_multiplier = self.ixia.map_prefix_pool_to_network_group(
                prefix_pool_obj
            ).Multiplier
        except Exception as error:
            raise_precondition(error)
        current_count = self._resolve_prefix_pool_current_count(
            prefix_pool_obj,
            network_group_multiplier=network_group_multiplier,
            expected_number_of_addresses=expected_number_of_addresses,
            target_number_of_addresses=target_number_of_addresses,
            allowed_counts=allowed_counts,
            raise_precondition=raise_precondition,
        )
        active_values, safe_values, active_value_count = (
            self._prepare_prefix_active_values(
                prefix_pool_obj,
                route_property,
                current_count,
                raise_precondition,
            )
        )
        if (
            int(network_group_multiplier) == 1
            and int(prefix_pool_obj.NumberOfAddresses) > 1
            and (not active_values or len(active_values) != int(route_property.Count))
        ):
            raise_precondition(
                ValueError(
                    f"IXIA compact prefix pool {prefix_pool_obj.Name!r} has "
                    f"{len(active_values)} Active.Values for route-property "
                    f"Count={route_property.Count}"
                )
            )
        slots, resolved_end_index = self._resolve_active_slots(
            prefix_pool_obj,
            int(network_group_multiplier),
            len(active_values),
            prefix_start_index,
            prefix_end_index,
            raise_precondition,
        )
        for index, _within_peer_index in slots:
            active_values[index] = active_state
            safe_values[index] = False
        return (
            (
                prefix_pool_obj,
                route_property,
                active_values,
                resolved_end_index,
                tuple(index + 1 for index, _ in slots),
            ),
            safe_values,
            current_count,
            active_value_count,
        )

    def _build_prefix_mutation_plan(
        self,
        *,
        active_state: bool,
        prefix_pool_regex: str,
        prefix_start_index: int,
        prefix_end_index: int | None,
        expected_prefix_pool_count: int | None,
        expected_number_of_addresses: int | None,
        target_number_of_addresses: int | None,
        allowed_counts: tuple[int, ...],
        safe_number_of_addresses: int | None,
    ) -> tuple[
        list[tuple[t.Any, t.Any, list[bool], int, tuple[int, ...]]],
        dict[str, list[bool]],
        dict[str, int],
        dict[str, int],
    ]:
        pools = (
            self._exact_prefix_pools(prefix_pool_regex, expected_prefix_pool_count)
            if expected_prefix_pool_count is not None
            else self.ixia.get_prefix_pools_by_regexes(
                prefix_pool_regex=prefix_pool_regex
            )
        )
        mutation_plan = []
        safe_values_by_pool = (
            {str(pool.Name): [] for pool in pools}
            if target_number_of_addresses is not None
            else {}
        )
        current_counts_by_pool = {}
        active_value_counts_by_pool = {}

        def raise_precondition(error: Exception) -> t.NoReturn:
            self._raise_resize_precondition(
                error,
                target_number_of_addresses=target_number_of_addresses,
                prefix_pool_regex=prefix_pool_regex,
                expected_prefix_pool_count=expected_prefix_pool_count,
                safe_values_by_pool=safe_values_by_pool,
                safe_number_of_addresses=safe_number_of_addresses,
            )

        for pool in pools:
            entry, safe_values, current_count, active_value_count = (
                self._build_prefix_mutation_entry(
                    pool,
                    active_state=active_state,
                    prefix_start_index=prefix_start_index,
                    prefix_end_index=prefix_end_index,
                    expected_number_of_addresses=expected_number_of_addresses,
                    target_number_of_addresses=target_number_of_addresses,
                    allowed_counts=allowed_counts,
                    raise_precondition=raise_precondition,
                )
            )
            name = str(pool.Name)
            mutation_plan.append(entry)
            safe_values_by_pool[name] = safe_values
            if current_count is not None:
                current_counts_by_pool[name] = current_count
            if active_value_count is not None:
                active_value_counts_by_pool[name] = active_value_count
        return (
            mutation_plan,
            safe_values_by_pool,
            current_counts_by_pool,
            active_value_counts_by_pool,
        )

    def _write_prefix_mutation_plan(
        self,
        mutation_plan: t.Sequence[
            tuple[t.Any, t.Any, list[bool], int, tuple[int, ...]]
        ],
        *,
        prefix_start_index: int,
        active_state: bool,
    ) -> None:
        for pool, route_property, values, end_index, _ in mutation_plan:
            route_property.Active.ValueList(values)
            self.logger.info(
                f"Configured prefixes in range {prefix_start_index} - "
                f"{end_index} active state to {active_state} for {pool.Name}"
            )
        self.ixia.apply_changes()

    def _apply_prefix_mutation_plan(
        self,
        *,
        active_state: bool,
        prefix_pool_regex: str,
        prefix_start_index: int,
        expected_prefix_pool_count: int | None,
        expected_number_of_addresses: int | None,
        target_number_of_addresses: int | None,
        safe_number_of_addresses: int | None,
        runtime_route_operation: bool,
        mutation_plan: t.Sequence[
            tuple[t.Any, t.Any, list[bool], int, tuple[int, ...]]
        ],
        safe_values_by_pool: t.Mapping[str, list[bool]],
        current_counts_by_pool: t.Mapping[str, int],
        active_value_counts_by_pool: t.Mapping[str, int],
    ) -> None:
        expected_values_by_pool = {
            str(pool.Name): values for pool, _, values, _, _ in mutation_plan
        }

        def set_running(running: bool) -> None:
            for _, route_property, _, _, indices in mutation_plan:
                operation = route_property.Start if running else route_property.Stop
                operation(SessionIndices=list(indices))

        def mutate() -> None:
            self._write_prefix_mutation_plan(
                mutation_plan,
                prefix_start_index=prefix_start_index,
                active_state=active_state,
            )

        if expected_prefix_pool_count is None:
            mutate()
            return
        try:
            if runtime_route_operation:
                set_running(False)
            mutate()
            self._verify_fresh_active_values(
                prefix_pool_regex,
                expected_prefix_pool_count,
                expected_values_by_pool,
                expected_number_of_addresses,
                current_counts_by_pool
                if target_number_of_addresses is not None
                else None,
            )
            if target_number_of_addresses is not None:
                self._resize_prefix_pools(
                    prefix_pool_regex,
                    expected_prefix_pool_count,
                    target_number_of_addresses,
                    expected_values_by_pool,
                )
                self._write_all_fresh_active_values_inactive(
                    prefix_pool_regex,
                    expected_prefix_pool_count,
                    expected_values_by_pool,
                )
                self._verify_fresh_inactive_values(
                    prefix_pool_regex,
                    expected_prefix_pool_count,
                    target_number_of_addresses,
                    active_value_counts_by_pool,
                )
            if runtime_route_operation and active_state:
                set_running(True)
        except Exception as mutation_error:
            cleanup_failures = self._run_cleanup_operations(
                (lambda: set_running(False),) if runtime_route_operation else ()
            )
            cleanup_failures.extend(
                self._run_cleanup_operations(
                    (
                        lambda: self._force_fail_closed_withdrawal(
                            prefix_pool_regex,
                            expected_prefix_pool_count,
                            safe_values_by_pool,
                            safe_number_of_addresses,
                        ),
                    )
                )
            )
            if cleanup_failures:
                cleanup_error = ExceptionGroup(
                    "IXIA prefix mutation cleanup failures", cleanup_failures
                )
                raise ValueError(
                    "IXIA prefix mutation and fail-closed withdrawal failed: "
                    f"mutation={mutation_error!r}, cleanup={cleanup_error!r}"
                ) from ExceptionGroup(
                    "IXIA prefix mutation and cleanup failures",
                    [mutation_error, cleanup_error],
                )
            raise
        self.logger.info(
            "Verified fresh Active.Values readback for "
            f"{sorted(expected_values_by_pool)}"
        )


class IxiaRandomizeBgpPrefixLocalPreference(BaseTask):
    NAME = "ixia_randomize_bgp_prefix_local_preference"

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        prefix_pool_regex = params["prefix_pool_regex"]
        prefix_start_index = params.get("prefix_start_index", 0)
        prefix_end_index = params.get("prefix_end_index")
        start_value: int = params["start_value"]
        end_value: int = params["end_value"]
        prefix_pool_obj_list = self.ixia.get_prefix_pools_by_regexes(
            prefix_pool_regex=prefix_pool_regex
        )
        for prefix_pool_obj in prefix_pool_obj_list:
            self.configure_bgp_prefix_local_preference(
                prefix_pool_obj,
                start_value,
                end_value,
                prefix_start_index,
                prefix_end_index,
            )
        self.ixia.apply_changes()

    @retryable(num_tries=2)
    def configure_bgp_prefix_local_preference(
        self,
        prefix_pool_obj,
        start_value: int,
        end_value: int,
        prefix_start_index: int = 0,
        prefix_end_index: t.Optional[int] = None,
    ) -> None:
        """
        Randomize BGP local preference values for prefixes within a specified range.

        This method configures BGP prefix local preference by assigning random values
        to influence BGP path selection. Local preference is a well-known BGP attribute
        used to prefer certain paths over others within an autonomous system.

        The method operates by:
        1. Determining whether the prefix pool is IPv4 or IPv6 and accessing the
           appropriate BGP route property
        2. Selecting prefixes within the specified index range using modulo arithmetic
           to map indices to their position within the network group multiplier
        3. Assigning a random local preference value (between start_value and end_value)
           to each selected prefix
        4. Applying the updated local preference values to the IXIA configuration

        The method handles both IPv4 and IPv6 prefix pools and uses the network group
        multiplier to correctly map prefix indices.

        Args:
            prefix_pool_obj: Prefix pool object, either Ipv4PrefixPools or IPv6.
            start_value: Minimum local preference value (inclusive) for randomization.
            end_value: Maximum local preference value (exclusive) for randomization.
            prefix_start_index: Starting index (inclusive) within the network group multiplier.
                Defaults to 0.
            prefix_end_index: Ending index (exclusive) within the network group multiplier.
                If None, uses the network group multiplier value (all remaining prefixes).
        """
        bgp_ip_route_property = (
            (prefix_pool_obj.BgpIPRouteProperty.find())
            if isinstance(prefix_pool_obj, Ipv4PrefixPools)
            else prefix_pool_obj.BgpV6IPRouteProperty.find()
        )[0]
        network_group_multiplier = self.ixia.map_prefix_pool_to_network_group(
            prefix_pool_obj
        ).Multiplier
        local_preference_values = bgp_ip_route_property.LocalPreference.Values
        slots, prefix_pool_prefix_end_index = _resolve_prefix_slots(
            prefix_pool_obj,
            network_group_multiplier,
            len(local_preference_values),
            prefix_start_index,
            prefix_end_index,
        )
        for i, _mod in slots:
            local_preference_values[i] = random.randrange(start_value, end_value)
        bgp_ip_route_property.LocalPreference.ValueList(local_preference_values)
        self.logger.info(
            f"Configured local preference of prefixes in range {prefix_start_index} - {prefix_pool_prefix_end_index}"
            f" to a randomized number between {start_value} and {end_value} for {prefix_pool_obj.Name}"
        )


class IxiaModifyBgpPrefixesOriginValue(BaseTask):
    NAME = "ixia_modify_bgp_prefixes_origin_value"

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        prefix_pool_regex = params["prefix_pool_regex"]
        prefix_start_index = params.get("prefix_start_index", 0)
        prefix_end_index = params.get("prefix_end_index")
        # Either single scalar (legacy) or list-of-strings for per-slot cycling.
        # ``origin_values`` (list) takes precedence when supplied; otherwise
        # fall back to ``origin_value`` (single scalar broadcast).
        origin_values = params.get("origin_values")
        origin_value = params.get("origin_value")
        prefix_pool_obj_list = self.ixia.get_prefix_pools_by_regexes(
            prefix_pool_regex=prefix_pool_regex
        )
        for prefix_pool_obj in prefix_pool_obj_list:
            self.configure_bgp_prefix_origin_value(
                prefix_pool_obj,
                origin_value,
                prefix_start_index,
                prefix_end_index,
                origin_values=origin_values,
            )
        self.ixia.apply_changes()

    @retryable(num_tries=2)
    def configure_bgp_prefix_origin_value(
        self,
        prefix_pool_obj,
        origin_value: t.Optional[str],
        prefix_start_index: int = 0,
        prefix_end_index: t.Optional[int] = None,
        origin_values: t.Optional[t.List[str]] = None,
    ) -> None:
        bgp_ip_route_property = (
            (prefix_pool_obj.BgpIPRouteProperty.find())
            if isinstance(prefix_pool_obj, Ipv4PrefixPools)
            else prefix_pool_obj.BgpV6IPRouteProperty.find()
        )[0]
        network_group_multiplier = self.ixia.map_prefix_pool_to_network_group(
            prefix_pool_obj
        ).Multiplier
        origin_value_list = bgp_ip_route_property.Origin.Values
        slots, prefix_pool_prefix_end_index = _resolve_prefix_slots(
            prefix_pool_obj,
            network_group_multiplier,
            len(origin_value_list),
            prefix_start_index,
            prefix_end_index,
        )
        for i, mod in slots:
            if origin_values:
                # Cycle through supplied list -- gives spec-loyal per-slot
                # variety (e.g. ``["igp", "egp", "incomplete"]``) which
                # exercises the DUT's per-prefix Origin handling in the
                # heavy-attr storm.
                origin_value_list[i] = origin_values[
                    (mod - prefix_start_index) % len(origin_values)
                ]
            else:
                origin_value_list[i] = origin_value
        bgp_ip_route_property.Origin.ValueList(origin_value_list)
        applied = f"cycling {origin_values}" if origin_values else f"= {origin_value}"
        self.logger.info(
            f"Configured origin of prefixes in range {prefix_start_index} - {prefix_pool_prefix_end_index}"
            f" ({applied}) for {prefix_pool_obj.Name}"
        )


class IxiaModifyBgpPrefixesMedValue(BaseTask):
    NAME = "ixia_modify_bgp_prefixes_med_value"

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        prefix_pool_regex = params["prefix_pool_regex"]
        prefix_start_index = params.get("prefix_start_index", 0)
        prefix_end_index = params.get("prefix_end_index")
        med_value: int = params["med_value"]
        prefix_pool_obj_list = self.ixia.get_prefix_pools_by_regexes(
            prefix_pool_regex=prefix_pool_regex
        )
        for prefix_pool_obj in prefix_pool_obj_list:
            self.configure_bgp_prefix_med_value(
                prefix_pool_obj, med_value, prefix_start_index, prefix_end_index
            )
        self.ixia.apply_changes()

    @retryable(num_tries=2)
    def configure_bgp_prefix_med_value(
        self,
        prefix_pool_obj,
        med_value: int,
        prefix_start_index: int = 0,
        prefix_end_index: t.Optional[int] = None,
    ) -> None:
        """
        Configure BGP MED (Multi-Exit Discriminator) value for prefixes within a specified range.

        MED is a BGP attribute used to influence inbound traffic routing decisions from
        neighboring autonomous systems. Lower MED values are preferred over higher values.

        The method operates by:
        1. Determining whether the prefix pool is IPv4 or IPv6 and accessing the
           appropriate BGP route property
        2. Selecting prefixes within the specified index range using modulo arithmetic
           to map indices to their position within the network group multiplier
        3. Setting the MED value for each selected prefix
        4. Applying the updated MED values to the IXIA configuration

        The method handles both IPv4 and IPv6 prefix pools and uses the network group
        multiplier to correctly map prefix indices.

        Args:
            prefix_pool_obj: Prefix pool object, either Ipv4PrefixPools or IPv6.
            med_value: MED (Multi-Exit Discriminator) value to set for the prefixes. If -1, randomly select a value between 10, 100
            prefix_start_index: Starting index (inclusive) within the network group multiplier.
                Defaults to 0.
            prefix_end_index: Ending index (exclusive) within the network group multiplier.
                If None, uses the network group multiplier value (all remaining prefixes).
        """
        bgp_ip_route_property = (
            (prefix_pool_obj.BgpIPRouteProperty.find())
            if isinstance(prefix_pool_obj, Ipv4PrefixPools)
            else prefix_pool_obj.BgpV6IPRouteProperty.find()
        )[0]
        # Enable MED advertisement - this is required for MED values to be sent
        bgp_ip_route_property.EnableMultiExitDiscriminator.Single(True)
        self.logger.info(f"Enabled MED advertisement for {prefix_pool_obj.Name}")
        network_group_multiplier = self.ixia.map_prefix_pool_to_network_group(
            prefix_pool_obj
        ).Multiplier
        med_value_list = bgp_ip_route_property.MultiExitDiscriminator.Values
        slots, prefix_pool_prefix_end_index = _resolve_prefix_slots(
            prefix_pool_obj,
            network_group_multiplier,
            len(med_value_list),
            prefix_start_index,
            prefix_end_index,
        )
        for i, _mod in slots:
            if med_value < 0:
                med_value_list[i] = random.randint(10, 100)
            else:
                med_value_list[i] = med_value
        bgp_ip_route_property.MultiExitDiscriminator.ValueList(med_value_list)
        med_value_str = str(med_value) if med_value >= 0 else "randomly selected"
        self.logger.info(
            f"Configured MED of prefixes in range {prefix_start_index} - {prefix_pool_prefix_end_index}"
            f" to {med_value_str} for {prefix_pool_obj.Name}"
        )


class IxiaModifyBgpPrefixesCommunities(BaseTask):
    NAME = "ixia_modify_communities"

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        prefix_pool_regex = params["prefix_pool_regex"]
        count = params["count"]
        to_add = params["to_add"]
        # Optional value-level swap: a list of community strings in
        # "<asn>:<value>" form. When present, peer's BgpCommunitiesList
        # slots are written to these values after the count update — enabling
        # true value-level mutation without chassis-wide BGP reset (still
        # flaps the peer owning the prefix pool, which is OK).
        community_values = params.get("community_values")
        broadcast_to_all_slots = bool(params.get("broadcast_to_all_slots", False))
        prefix_pool_obj_list = self.ixia.get_prefix_pools_by_regexes(
            prefix_pool_regex=prefix_pool_regex
        )
        for prefix_pool_obj in prefix_pool_obj_list:
            self.configure_bgp_prefix_communities(
                prefix_pool_obj,
                count,
                to_add,
                community_values=community_values,
                broadcast_to_all_slots=broadcast_to_all_slots,
            )
        self.ixia.apply_changes()

    @retryable(num_tries=3)
    def configure_bgp_prefix_communities(
        self,
        prefix_pool_obj,
        count: int,
        to_add: bool,
        community_values: t.Optional[t.List[str]] = None,
        broadcast_to_all_slots: bool = False,
    ) -> None:
        """
        Add or remove a certain count of communities, optionally with
        value-level swap.

        Args:
            prefix_pool_obj: Prefix pool object, either Ipv4PrefixPools or IPv6.
            count: Number of communities to add/remove.
            to_add: Either to add or remove.
            community_values: Optional list of community values in canonical
                ``"<asn>:<value>"`` form (e.g. ``["65529:1234"]``). When
                provided, the per-slot ``AsNumber`` / ``LastTwoOctets`` fields
                on the peer's ``BgpCommunitiesList`` are written from these
                values starting at index 0 — enabling value-level community
                mutation (routes get re-advertised with a NEW community).
                When None, legacy count-only behavior preserved.
            broadcast_to_all_slots: When True and ``community_values`` has
                exactly one entry, replicate that value across ALL slots on
                the peer's ``BgpCommunitiesList`` rather than only slot 0.
                Needed when the IXIA setup seeded the initial community
                round-robin across multiple slots per route — otherwise a
                slot-0-only overwrite leaves stragglers in higher slots.
        """
        bgp_peer_obj = self.ixia.map_prefix_pool_to_bgp_peer(prefix_pool_obj)
        bgp_peer_obj.Stop()
        self.logger.info(
            f"Stopped BGP peer {bgp_peer_obj.Name} before modifying communities"
        )

        bgp_ip_route_property_list = (
            prefix_pool_obj.BgpIPRouteProperty.find()
            if isinstance(prefix_pool_obj, Ipv4PrefixPools)
            else prefix_pool_obj.BgpV6IPRouteProperty.find()
        )

        if not bgp_ip_route_property_list:
            self.logger.error(
                f"No BGP IP route property found for {prefix_pool_obj.Name}. "
                f"Is this prefix pool properly configured with BGP?"
            )
            bgp_peer_obj.Start()
            self.logger.info(f"Started BGP peer {bgp_peer_obj.Name} after error")
            return

        bgp_ip_route_property = bgp_ip_route_property_list[0]

        # Set the number of communities. Clamp at 0 for the remove path so
        # callers passing count > current don't drive NoOfCommunities negative —
        # surface the over-remove explicitly so callers don't think the full
        # ``count`` slots were removed when fewer existed.
        if to_add:
            bgp_ip_route_property.NoOfCommunities = (
                bgp_ip_route_property.NoOfCommunities + count
            )
        else:
            current = bgp_ip_route_property.NoOfCommunities
            if count > current:
                self.logger.warning(
                    f"remove count={count} exceeds current NoOfCommunities="
                    f"{current} on {prefix_pool_obj.Name}; clamping at 0 "
                    f"(only {current} slot(s) actually removed)"
                )
            bgp_ip_route_property.NoOfCommunities = max(0, current - count)

        self.logger.info(
            f"Set NoOfCommunities to {bgp_ip_route_property.NoOfCommunities} for {prefix_pool_obj.Name}"
        )

        if community_values:
            # Commit the ``NoOfCommunities`` mutation BEFORE ``find()`` so
            # ``_write_community_value_slots`` sees the freshly-added slots.
            # Without this, callers passing ``to_add=True, count>0,
            # community_values=[...new values for added slots]`` would have
            # ``BgpCommunitiesList.find()`` return the pre-bump slot count,
            # silently dropping writes to the new slots.
            self.ixia.apply_changes()
            self._write_community_value_slots(
                bgp_ip_route_property,
                prefix_pool_obj,
                community_values,
                broadcast_to_all_slots=broadcast_to_all_slots,
            )
            # Commit the per-slot ValueList writes BEFORE the peer restarts.
            # Without this, ``bgp_peer_obj.Start()`` below re-establishes the
            # BGP session and IXIA re-advertises every prefix using the LAST
            # COMMITTED ``BgpCommunitiesList`` state — which is the pre-write
            # state — so the new community values never reach the wire. The
            # legacy ``configure_community_pool`` works because
            # ``restart_protocols()`` implicitly applies pending changes;
            # the peer-scoped ``Stop()``/``Start()`` path does not.
            self.ixia.apply_changes()

        bgp_peer_obj.Start()
        self.logger.info(
            f"Started BGP peer {bgp_peer_obj.Name} after modifying communities"
        )

    def _write_community_value_slots(
        self,
        bgp_ip_route_property,
        prefix_pool_obj,
        community_values: t.List[str],
        broadcast_to_all_slots: bool = False,
    ) -> None:
        """Write each ``"<asn>:<value>"`` entry to a successive slot of the
        peer's ``BgpCommunitiesList``.

        ``BgpCommunitiesList.find()`` returns a list of per-slot objects (one
        per configured community position). Per-slot writes broadcast a single
        value across all routes in that slot via ``AsNumber.ValueList([asn])``
        / ``LastTwoOctets.ValueList([low])`` — the canonical pattern in
        ``ixia.py::configure_community_pool``. Calling ``Single(x)`` in a loop
        on the SAME slot object would only retain the last scalar, so we
        index per slot instead. Caller MUST have stopped the BGP peer first
        (so the change takes effect on the next Start).

        When ``broadcast_to_all_slots=True`` ``community_values`` MUST have
        exactly one entry; that value is replicated across ALL slots (needed
        when the IXIA setup seeded the initial community round-robin across
        slots per route so slot-0-only overwrites leave stragglers). A
        broadcast request with any other length raises ``ValueError`` — a
        broadcast caller that supplied N values almost certainly made a
        mistake (e.g., passed the full list twice); silently falling back to
        per-slot writes would produce a mis-configured wire state that only
        shows up under test.
        """
        bgp_community_objs = bgp_ip_route_property.BgpCommunitiesList.find()
        if not bgp_community_objs:
            self.logger.warning(
                f"community_values={community_values!r} requested but "
                f"BgpCommunitiesList is empty on {prefix_pool_obj.Name} — "
                "ensure NoOfCommunities>0 before passing value swap"
            )
            return
        effective_values = self._compute_effective_community_values(
            community_values=community_values,
            slot_count=len(bgp_community_objs),
            broadcast_to_all_slots=broadcast_to_all_slots,
            prefix_pool_obj=prefix_pool_obj,
        )
        if not effective_values:
            return
        written_slots: t.List[int] = []
        for slot_idx, value_str in enumerate(effective_values):
            parsed = self._parse_community_value(value_str, slot_idx)
            if parsed is None:
                continue
            asn, low = parsed
            self._write_community_slot(
                slot_obj=bgp_community_objs[slot_idx],
                asn=asn,
                low=low,
                slot_idx=slot_idx,
                prefix_pool_obj=prefix_pool_obj,
            )
            written_slots.append(slot_idx)
        if written_slots:
            self.logger.info(
                f"Wrote {len(written_slots)} community slot(s) "
                f"({written_slots}) on {prefix_pool_obj.Name}"
            )

    def _compute_effective_community_values(
        self,
        *,
        community_values: t.List[str],
        slot_count: int,
        broadcast_to_all_slots: bool,
        prefix_pool_obj,
    ) -> t.List[str]:
        """Compose the final per-slot value list, truncated to ``slot_count``.
        Raises ``ValueError`` on a broadcast request that supplied != 1 value.
        Warns (once, at the top) when the input is longer than ``slot_count``.
        """
        if broadcast_to_all_slots:
            if len(community_values) != 1:
                raise ValueError(
                    f"broadcast_to_all_slots=True requires exactly 1 entry in "
                    f"community_values on {prefix_pool_obj.Name}; got "
                    f"{len(community_values)}: {community_values!r}"
                )
            self.logger.info(
                f"broadcast_to_all_slots=True: replicating "
                f"{community_values[0]!r} across all {slot_count} slot(s) on "
                f"{prefix_pool_obj.Name}"
            )
            return [community_values[0]] * slot_count
        if len(community_values) > slot_count:
            self.logger.warning(
                f"community_values has {len(community_values)} entries but "
                f"only {slot_count} slot(s) exist on {prefix_pool_obj.Name}; "
                f"truncating to {slot_count} — increase NoOfCommunities to match"
            )
        return list(community_values)[:slot_count]

    def _parse_community_value(
        self, value_str: str, slot_idx: int
    ) -> t.Optional[t.Tuple[int, int]]:
        """Parse a ``"<asn>:<value>"`` string. Returns ``(asn, low)`` or
        ``None`` (with a warning) on any parse / 16-bit-range failure.

        BGP RFC 1997 communities are 32-bit split as ``AS(16)|value(16)``.
        IXIA silently TRUNCATES ``ValueList`` writes to 16 bits (e.g.
        99999 -> 99999 mod 65536 = 34463), so out-of-range values are
        rejected here rather than landing on the wire as unexpected values.
        """
        if ":" not in value_str:
            self.logger.warning(
                f"community value {value_str!r} not in '<asn>:<value>' form; "
                f"skipping slot {slot_idx}"
            )
            return None
        asn_str, low_str = value_str.split(":", 1)
        try:
            asn = int(asn_str)
            low = int(low_str)
        except ValueError:
            self.logger.warning(
                f"community value {value_str!r} has non-int parts; skipping "
                f"slot {slot_idx}"
            )
            return None
        if not (0 <= asn <= 0xFFFF and 0 <= low <= 0xFFFF):
            self.logger.warning(
                f"community value {value_str!r} out of 16-bit range "
                f"(asn={asn}, low={low}); IXIA would silently truncate. "
                f"Skipping slot {slot_idx}."
            )
            return None
        return asn, low

    def _write_community_slot(
        self,
        *,
        slot_obj,
        asn: int,
        low: int,
        slot_idx: int,
        prefix_pool_obj,
    ) -> None:
        """Write PER-ROW OVERRIDES on the given ``BgpCommunitiesList`` slot.

        IXIA setup-time per-route community configuration installs per-row
        overrides on ``BgpCommunitiesList[slot].AsNumber`` / ``LastTwoOctets``.
        A scalar ``ValueList([v])`` only sets the Multivalue Pattern, which
        per-row overrides supersede — so scalar writes silently no-op on the
        wire. Passing a list of length equal to the current per-row count
        (from ``AsNumber.Values``) writes the value as an override on every
        row, which IXIA honors on re-advertise after DG/NG restart.
        """
        try:
            row_count = len(list(slot_obj.AsNumber.Values))
        except AttributeError as exc:
            self.logger.debug(
                f"slot {slot_idx} on {prefix_pool_obj.Name}: "
                f"AsNumber.Values access raised {exc!r}; "
                "falling back to scalar broadcast (row_count=1)"
            )
            row_count = 1
        slot_obj.AsNumber.ValueList([asn] * row_count)
        slot_obj.LastTwoOctets.ValueList([low] * row_count)
        self.logger.info(
            f"Set community slot {slot_idx} on {prefix_pool_obj.Name}: "
            f"AsNumber={asn} LastTwoOctets={low} (per-row overrides × "
            f"{row_count} rows)"
        )


class IxiaChangeAsPathLength(BaseTask):
    NAME = "ixia_change_as_path_length"

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        prefix_pool_regex = params["prefix_pool_regex"]
        as_path_length = params.get("as_path_length", 1)

        prefix_pool_obj_list = self.ixia.get_prefix_pools_by_regexes(
            prefix_pool_regex=prefix_pool_regex
        )

        for prefix_pool_obj in prefix_pool_obj_list:
            self.configure_bgp_prefix_as_path_prepend(prefix_pool_obj, as_path_length)

        self.ixia.apply_changes()

    @retryable(num_tries=2)
    def configure_bgp_prefix_as_path_prepend(
        self,
        prefix_pool_obj,
        as_path_length: int = 1,
    ) -> None:
        """
        Configure size of AS_PATH

        Args:
            prefix_pool_obj: Prefix pool object, either Ipv4PrefixPools or IPv6.
            as_path_length: Total number of AS Numbers
        """
        bgp_peer_obj = self.ixia.map_prefix_pool_to_bgp_peer(prefix_pool_obj)
        bgp_peer_obj.Stop()
        self.logger.info(
            f"Stopped BGP peer {bgp_peer_obj.Name} before modifying AS path"
        )

        bgp_ip_route_property = (
            (prefix_pool_obj.BgpIPRouteProperty.find())
            if isinstance(prefix_pool_obj, Ipv4PrefixPools)
            else prefix_pool_obj.BgpV6IPRouteProperty.find()
        )[0]
        bgp_as_path_segment_list = bgp_ip_route_property.BgpAsPathSegmentList.find()
        for bgp_as_path_segment_obj in bgp_as_path_segment_list:
            bgp_as_path_segment_obj.NumberOfAsNumberInSegment = as_path_length
            as_number_list_obj_list = bgp_as_path_segment_obj.BgpAsNumberList.find()
            for i in range(len(as_number_list_obj_list)):
                as_number_list_obj_list[i].EnableASNumber.Single(True)

        bgp_peer_obj.Start()
        self.logger.info(
            f"Started BGP peer {bgp_peer_obj.Name} after modifying AS path"
        )


class IxiaDrainUndrainBgpPeers(BaseTask):
    NAME = "ixia_drain_undrain_bgp_peers"

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        prefix_pool_regex = params["prefix_pool_regex"]
        as_numbers = params.get("as_numbers", ["65099"])
        prefix_pool_obj_list = self.ixia.get_prefix_pools_by_regexes(
            prefix_pool_regex=prefix_pool_regex
        )
        drain = params["drain"]
        prefix_pool_names = [
            prefix_pool_obj.Name for prefix_pool_obj in prefix_pool_obj_list
        ]
        self.logger.info(
            f"{'Draining' if drain else 'Undraining'} prefixes in prefix pools {prefix_pool_names}"
        )
        for prefix_pool_obj in prefix_pool_obj_list:
            self.drain_undrain_prefix_pool(
                drain,
                prefix_pool_obj,
                as_numbers,
            )
        self.ixia.apply_changes()

    def _get_as_number_and_enabled_as_number_values(
        self,
        as_number_list_obj,
    ) -> list:
        as_numbers_list = as_number_list_obj.AsNumber.Values
        last_two_octets_list = as_number_list_obj.EnableASNumber.Values
        return list(zip(as_numbers_list, last_two_octets_list))

    def configure_as_number_for_drain_undrain(
        self,
        drain: bool,
        prefix_pool_obj,
        as_numbers: t.List[str],
    ) -> None:
        """
        Configure AS numbers for drain or undrain operation on BGP route properties.
        Args:
            drain: True to configure drain AS numbers, False to undrain.
            prefix_pool_obj: Prefix pool object, either IPv4 or IPv6.
            as_numbers: List of AS numbers to apply for drain or remove for undrain.
        """
        if isinstance(prefix_pool_obj, Ipv4PrefixPools):
            bgp_ip_route_property = prefix_pool_obj.BgpIPRouteProperty.find()[0]
        else:
            bgp_ip_route_property = prefix_pool_obj.BgpV6IPRouteProperty.find()[0]
        bgp_as_path_segment_list = bgp_ip_route_property.BgpAsPathSegmentList.find()
        as_numbers_added_or_removed = set()
        for bgp_as_path_segment_obj in bgp_as_path_segment_list:
            as_number_list_obj_list = bgp_as_path_segment_obj.BgpAsNumberList.find()
            for as_number_list_obj in as_number_list_obj_list:
                if as_number_list_obj.AsNumber.Single in as_numbers:
                    as_number_list_obj.EnableASNumber.Single(drain)
                    as_numbers_added_or_removed.add(as_number_list_obj.AsNumber.Single)
        as_numbers_not_added = set(as_numbers) - as_numbers_added_or_removed
        if as_numbers_not_added:
            bgp_as_path_segment_obj.NumberOfAsNumberInSegment = (
                bgp_as_path_segment_obj.NumberOfAsNumberInSegment
                + len(as_numbers_not_added)
            )
            as_number_list_obj_list = bgp_as_path_segment_obj.BgpAsNumberList.find()
            for i, as_number in enumerate(as_numbers_not_added):
                reverse_i = -(i + 1)
                as_number_list_obj_list[reverse_i].AsNumber.Single(as_number)
                as_number_list_obj_list[reverse_i].EnableASNumber.Single(True)
        origin_value = "incomplete" if drain else "igp"
        bgp_ip_route_property.Origin.Single(origin_value)
        self.logger.info(
            f"Successfully {'drained' if drain else 'undrained'} all prefixes in "
            f"{prefix_pool_obj.Name} by {'adding' if drain else 'removing'} AS numbers {as_numbers} {'to' if drain else 'from'} AS path "
            f"and set origin value to {origin_value}"
        )

    @retryable(num_tries=2)
    def drain_undrain_prefix_pool(
        self,
        drain: bool,
        prefix_pool_obj,
        as_numbers: t.List[str],
    ) -> None:
        bgp_peer_obj = self.ixia.map_prefix_pool_to_bgp_peer(prefix_pool_obj)
        bgp_peer_obj.Stop()
        self.logger.info(
            f"Stopped BGP peer {bgp_peer_obj.Name} before configuring AS numbers"
        )
        self.configure_as_number_for_drain_undrain(drain, prefix_pool_obj, as_numbers)
        bgp_peer_obj.Start()
        self.logger.info(
            f"Started BGP peer {bgp_peer_obj.Name} after configuring AS numbers"
        )


class IxiaRestartBgpSessions(BaseTask):
    NAME = "ixia_restart_bgp_sessions"

    def get_randomized_session_indices(
        self, total_sessions: int, num_session: int
    ) -> str:
        full_range = list(range(1, total_sessions + 1))
        picked_numbers = random.sample(full_range, min(num_session, len(full_range)))
        picked_numbers.sort()
        ranges = []
        range_start = picked_numbers[0]
        range_end = range_start
        for num in picked_numbers[1:]:
            if num == range_end + 1:
                range_end = num
            else:
                ranges.append(f"{range_start}-{range_end}")
                range_start = range_end = num
        ranges.append(f"{range_start}-{range_end}")
        return ";".join(ranges) + ";"

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        bgp_peer_regex = params.get("bgp_peer_regex")
        session_indices = params.get("session_indices")
        random_session_num = params.get("random_session_num")
        bgp_peer_obj_list = self.ixia.find_bgp_peers(bgp_peer_regex)
        self.logger.info(
            f"Restarting bgp peers: {[bgp_peer_obj.Name for bgp_peer_obj in bgp_peer_obj_list]}"
        )
        for bgp_peer_obj in bgp_peer_obj_list:
            if random_session_num:
                bgp_peer_session_indices = self.get_randomized_session_indices(
                    bgp_peer_obj.Count, random_session_num
                )
            else:
                bgp_peer_session_indices = session_indices or f"1-{bgp_peer_obj.Count}"
            bgp_peer_obj.Stop(bgp_peer_session_indices)
            bgp_peer_obj.Start(bgp_peer_session_indices)
            self.logger.info(
                f"Successfully restarted sessions {bgp_peer_session_indices} of {bgp_peer_obj.Name}"
            )
        self.ixia.apply_changes()


class ConfigureIxiaInterfaces(BaseTask):
    NAME = "configure_ixia_interfaces"

    ADD_BGP_PEER_PY_FUNC_NAME = "add_bgp_peer"
    CONFIGURE_VLAN_PY_FUNC_NAME = "configure_vlans"
    CHANGE_SPEED_PY_FUNC_NAME = "change_speed"
    CHANGE_PORT_ADMIN_STATE_PY_FUNC_NAME = "change_port_admin_state"

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        port_configs = params["port_configs"]
        hostname = params["hostname"]
        driver = await async_get_device_driver(hostname)
        for port_config in port_configs:
            interface = port_config["interface"]
            ip_address = port_config["ip_address"]
            remote_as_4_byte = port_config["remote_as_4_byte"]
            peer_group_name = port_config["peer_group_name"]
            speed_in_gbps = port_config.get("speed_in_gbps")
            profile_id = port_config.get("profile_id")
            mtu = port_config.get("mtu", 9000)
            ip_interface = ipaddress.ip_interface(ip_address)
            add_bgp_peer_kwargs = {
                "remote_as_4_byte": str(remote_as_4_byte),
                "peer_group_name": peer_group_name,
                "local_addr": str(ip_interface.ip),
                "peer_addr": str(ip_interface.network),
                "description": f"Ixia {interface} peer",
            }
            # pyre-fixme[16]: `AbstractSwitch` has no attribute
            #  `async_get_all_interfaces_info`.
            interface_info = (await driver.async_get_all_interfaces_info())[interface]
            port_num = interface_info.port_id
            vlan_id = interface_info.vlan_id
            vlan_name = f"vlan{vlan_id}"
            configure_vlan_kwargs = {
                vlan_name: json.dumps(
                    {
                        "ports": [port_num],
                        "vlan_id": vlan_id,
                        "mtu": mtu,
                        "ip_addresses": [ip_address],
                    }
                )
            }
            for config in get_default_bgp_configs(hostname):
                # pyre-fixme[16]: `AbstractSwitch` has no attribute
                #  `async_register_python_patcher`.
                await driver.async_register_python_patcher(
                    config,
                    f"add_bgp_peer_{interface}",
                    self.ADD_BGP_PEER_PY_FUNC_NAME,
                    add_bgp_peer_kwargs,
                )
            # pyrefly: ignore [missing-attribute]
            await driver.async_register_python_patcher(
                "agent",
                f"configure_vlan_{interface}",
                self.CONFIGURE_VLAN_PY_FUNC_NAME,
                configure_vlan_kwargs,
            )
            if speed_in_gbps and profile_id:
                try:
                    speed_name = PortSpeed(speed_in_gbps * 1000).name
                except ValueError:
                    self.logger.error(
                        f"Invalid speed {speed_in_gbps}. Skipping speed configuration."
                    )
                    continue
                change_speed_kwargs = {
                    "intfs": interface,
                    "speed": speed_name,
                    "profile_id": profile_id,
                }
                # pyrefly: ignore [missing-attribute]
                await driver.async_register_python_patcher(
                    "agent",
                    f"change_speed_{interface}_{speed_in_gbps}G_{profile_id}",
                    self.CHANGE_SPEED_PY_FUNC_NAME,
                    change_speed_kwargs,
                )
            else:
                self.logger.info(
                    f"Speed and profile_id not provided for {interface}, Skipping speed configuration."
                )
        change_port_admin_state_kwargs = {
            port_config["interface"]: "enable" for port_config in port_configs
        }
        # pyrefly: ignore [missing-attribute]
        await driver.async_register_python_patcher(
            "agent",
            "change_ixia_port_admin_state",
            self.CHANGE_PORT_ADMIN_STATE_PY_FUNC_NAME,
            change_port_admin_state_kwargs,
        )


class IxiaSetBgpPrefixesLocalPreference(BaseTask):
    NAME = "ixia_set_bgp_prefixes_local_preference"

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        prefix_pool_regex = params["prefix_pool_regex"]
        local_pref_value = params["local_pref_value"]
        prefix_start_index = params.get("prefix_start_index", 0)
        prefix_end_index = params.get("prefix_end_index")

        prefix_pool_obj_list = self.ixia.get_prefix_pools_by_regexes(
            prefix_pool_regex=prefix_pool_regex
        )
        for prefix_pool_obj in prefix_pool_obj_list:
            self.configure_bgp_peer_local_preference(
                prefix_pool_obj,
                local_pref_value,
                prefix_start_index,
                prefix_end_index,
            )
        self.ixia.apply_changes()

    @retryable(num_tries=2)
    def configure_bgp_peer_local_preference(
        self,
        prefix_pool_obj,
        local_pref_value: int,
        prefix_start_index: int = 0,
        prefix_end_index: t.Optional[int] = None,
    ) -> None:
        """
        Configure BGP local preference for prefixes within a specified range.

        This method modifies the local preference attribute for prefixes in the
        specified prefix pool. Local preference is a well-known BGP attribute
        used to prefer certain paths over others within an autonomous system.

        The method operates by:
        1. Determining whether the prefix pool is IPv4 or IPv6 and accessing the
           appropriate BGP route property
        2. Selecting prefixes within the specified index range using modulo arithmetic
           to map indices to their position within the network group multiplier
        3. Setting the local preference value for each selected prefix
        4. Applying the updated local preference values to the IXIA configuration

        Args:
            prefix_pool_obj: Prefix pool object, either Ipv4PrefixPools or IPv6.
            local_pref_value: Local preference value to set
            prefix_start_index: Starting index (inclusive) within the network group multiplier.
                Defaults to 0.
            prefix_end_index: Ending index (exclusive) within the network group multiplier.
                If None, uses the network group multiplier value (all remaining prefixes).
        """
        bgp_peer_obj = self.ixia.map_prefix_pool_to_bgp_peer(prefix_pool_obj)

        bgp_ip_route_property = (
            (prefix_pool_obj.BgpIPRouteProperty.find())
            if isinstance(prefix_pool_obj, Ipv4PrefixPools)
            else prefix_pool_obj.BgpV6IPRouteProperty.find()
        )[0]

        network_group_multiplier = self.ixia.map_prefix_pool_to_network_group(
            prefix_pool_obj
        ).Multiplier

        local_preference_values = bgp_ip_route_property.LocalPreference.Values
        slots, prefix_pool_prefix_end_index = _resolve_prefix_slots(
            prefix_pool_obj,
            network_group_multiplier,
            len(local_preference_values),
            prefix_start_index,
            prefix_end_index,
        )
        for i, _mod in slots:
            local_preference_values[i] = local_pref_value

        bgp_ip_route_property.LocalPreference.ValueList(local_preference_values)

        self.logger.info(
            f"Configured local preference to {local_pref_value} for prefixes in range "
            f"{prefix_start_index}-{prefix_pool_prefix_end_index} of {prefix_pool_obj.Name} "
            f"(BGP peer: {bgp_peer_obj.Name})"
        )


class IxiaPacketCaptureTask(BaseTask):
    NAME = "ixia_packet_capture"

    # Store vport_href and pcap_path for stop/save/verify operations
    _vport_href_storage: t.Dict[str, str] = {}
    _pcap_path_storage: t.Dict[str, str] = {}

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        """
        Manage IXIA packet capture lifecycle.

        This task handles starting, stopping, and saving packet captures on IXIA ports.
        It captures at the BGP monitor (IXIA side) for accurate convergence measurement.

        Args (from params dict):
            hostname: Device hostname (for interface lookup)
            interface: Interface name on device
            mode: "start", "stop", or "save"
            capture_filter: BPF filter (default: "tcp port 179")
            pcap_filename: Filename for saved PCAP (for save mode)
            capture_id: Unique ID to track vport_href across steps
        """
        mode = params["mode"]
        hostname = params["hostname"]
        interface = params["interface"]
        capture_id = params.get("capture_id", f"{hostname}:{interface}")

        ixia = none_throws(self.ixia)

        if mode == "start":
            # Default: no filter, capture all packets (tshark filters during analysis)
            capture_filter = params.get("capture_filter", "")

            if capture_filter:
                self.logger.info(
                    f"Starting IXIA packet capture on {hostname}:{interface} "
                    f"with filter '{capture_filter}'"
                )
            else:
                self.logger.info(
                    f"Starting IXIA packet capture on {hostname}:{interface} "
                    f"(capturing all packets - tshark will filter during analysis)"
                )

            vport_href = ixia.start_packet_capture(
                hostname=hostname,
                interface=interface,
                capture_filter=capture_filter,
            )

            # Store vport_href for later use
            IxiaPacketCaptureTask._vport_href_storage[capture_id] = vport_href

            self.logger.info(f"IXIA packet capture started, vport_href: {vport_href}")

        elif mode == "stop":
            vport_href = IxiaPacketCaptureTask._vport_href_storage.get(capture_id)
            if not vport_href:
                raise ValueError(
                    f"No vport_href found for capture_id '{capture_id}'. "
                    "Did you start capture first?"
                )

            self.logger.info(f"Stopping IXIA packet capture (vport: {vport_href})")
            ixia.stop_packet_capture(vport_href)
            self.logger.info("IXIA packet capture stopped")

        elif mode == "save":
            vport_href = IxiaPacketCaptureTask._vport_href_storage.get(capture_id)
            if not vport_href:
                raise ValueError(
                    f"No vport_href found for capture_id '{capture_id}'. "
                    "Did you start capture first?"
                )

            pcap_filename = params.get("pcap_filename", "bgp_capture.pcap")

            self.logger.info(
                f"Saving IXIA packet capture to {pcap_filename} (vport: {vport_href})"
            )
            pcap_path = ixia.save_capture_to_pcap(vport_href, pcap_filename)
            self.logger.info(f"IXIA packet capture saved to {pcap_path}")

            # Store pcap_path for later retrieval by verification step
            IxiaPacketCaptureTask._pcap_path_storage[pcap_filename] = pcap_path

            # Clean up stored vport_href
            del IxiaPacketCaptureTask._vport_href_storage[capture_id]

        else:
            raise ValueError(
                f"Invalid mode: {mode}. Must be 'start', 'stop', or 'save'"
            )


class InvokeIxiaApiTask(BaseTask):
    NAME = "invoke_ixia_api"

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        """
        Invoke an IXIA API method with the specified parameters.

        Expected params:
        - api_name: The name of the IXIA API method to call
        - args_json: JSON string containing the arguments for the API method
        """
        ixia = none_throws(self.ixia)
        api_name = params["api_name"]
        api_func = getattr(ixia, api_name)
        if not api_func:
            raise ValueError(f"Invalid ixia API name: {api_name}")
        args = json.loads(params.get("args_json", "{}"))
        assert isinstance(args, dict), (
            f"Invalid args_json: {args}: {type(args)}. Args must be a dict"
        )
        api_func(**args)
