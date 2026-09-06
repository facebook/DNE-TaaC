# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-strict

"""IXIA route and multivalue geometry used by multiple churn adapters."""

from __future__ import annotations

import copy
import dataclasses
import ipaddress
import json
import time
import typing as t
import urllib.parse

from taac.constants import TestCaseFailure


@dataclasses.dataclass(frozen=True)
class IxiaPatternSnapshot:
    pattern: str
    payload: t.Mapping[str, t.Any]

    _SUPPORTED_PATTERNS: t.ClassVar[frozenset[str]] = frozenset(
        {
            "singleValue",
            "counter",
            "valueList",
            "repeatableRandomRange",
            "repeatableRandom",
            "alternate",
            "customDistributed",
            "string",
            "custom",
        }
    )

    @classmethod
    def capture(cls, handle: t.Any, label: str) -> IxiaPatternSnapshot:
        # RestPy populates the active pattern payload while resolving Pattern.
        getattr(handle, "Pattern", None)
        properties = getattr(handle, "_properties", None)
        if not isinstance(properties, dict):
            raise TestCaseFailure(f"{label} has no restorable IXIA _properties")

        pattern = properties.get("pattern")
        if not isinstance(pattern, str):
            raise TestCaseFailure(f"{label} has no restorable IXIA pattern")
        if pattern == "random":
            raise TestCaseFailure(f"{label} uses non-repeatable IXIA random pattern")
        if pattern not in cls._SUPPORTED_PATTERNS:
            raise TestCaseFailure(f"{label} has unsupported IXIA pattern {pattern!r}")
        payload = properties.get(pattern)
        if not isinstance(payload, dict):
            raise TestCaseFailure(f"{label} has unsupported IXIA pattern {pattern!r}")
        cls._validate_payload(pattern, payload, label)
        return cls(pattern, copy.deepcopy(payload))

    @classmethod
    def _validate_payload(
        cls, pattern: str, payload: t.Mapping[str, t.Any], label: str
    ) -> None:
        required_fields = {
            "singleValue": ("value",),
            "valueList": ("values",),
            "alternate": ("value",),
            "custom": ("start", "step"),
        }.get(pattern, ())
        cls._require_fields(payload, required_fields, label, pattern)
        if pattern == "valueList":
            cls._payload_sequence(payload["values"], label, pattern)
        elif pattern == "customDistributed":
            records = cls._payload_sequence(payload.get("values", ()), label, pattern)
            for index, record in enumerate(records):
                record_label = f"{label} {pattern} entry {index}"
                if not isinstance(record, dict):
                    raise TestCaseFailure(f"{record_label} must be a mapping")
                cls._require_fields(record, ("arg1", "arg2"), record_label, pattern)
        elif pattern == "custom":
            cls._validate_custom_increments(payload.get("increment", ()), label)

    @staticmethod
    def _require_fields(
        payload: t.Mapping[str, t.Any],
        fields: t.Iterable[str],
        label: str,
        pattern: str,
    ) -> None:
        missing = [field for field in fields if field not in payload]
        if missing:
            raise TestCaseFailure(
                f"{label} IXIA {pattern} pattern is missing required fields {missing}"
            )

    @staticmethod
    def _payload_sequence(value: t.Any, label: str, pattern: str) -> tuple[t.Any, ...]:
        if isinstance(value, (str, bytes)):
            raise TestCaseFailure(f"{label} IXIA {pattern} values must be iterable")
        try:
            return tuple(value)
        except TypeError as error:
            raise TestCaseFailure(
                f"{label} IXIA {pattern} values must be iterable"
            ) from error

    @classmethod
    def _validate_custom_increments(cls, increments: t.Any, label: str) -> None:
        records = cls._payload_sequence(increments, label, "custom")
        for index, record in enumerate(records):
            record_label = f"{label} custom increment {index}"
            if not isinstance(record, dict):
                raise TestCaseFailure(f"{record_label} must be a mapping")
            cls._require_fields(record, ("value", "count"), record_label, "custom")
            cls._validate_custom_increments(record.get("increment", ()), record_label)

    def restore(self, handle: t.Any) -> None:
        payload = self.payload
        if self.pattern == "singleValue":
            handle.Single(payload["value"])
        elif self.pattern == "counter":
            setter = (
                handle.Decrement
                if payload.get("direction") == "decrement"
                else handle.Increment
            )
            setter(
                payload.get("start"),
                payload.get("step"),
                payload.get("count"),
            )
        elif self.pattern == "valueList":
            handle.ValueList(list(payload["values"]))
        elif self.pattern == "repeatableRandomRange":
            handle.RandomRange(
                payload.get("min"),
                payload.get("max"),
                payload.get("step"),
                payload.get("seed"),
            )
        elif self.pattern == "repeatableRandom":
            handle.RandomMask(
                payload.get("fixed"),
                payload.get("mask"),
                payload.get("seed"),
                payload.get("count"),
            )
        elif self.pattern == "alternate":
            handle.Alternate(payload["value"])
        elif self.pattern == "customDistributed":
            values = [
                (value["arg1"], value["arg2"]) for value in payload.get("values", ())
            ]
            handle.Distributed(payload.get("algorithm"), payload.get("mode"), values)
        elif self.pattern == "string":
            handle.String(payload.get("pattern"))
        elif self.pattern == "custom":
            handle.Custom(
                payload.get("start"),
                payload.get("step"),
                self._custom_increments(payload.get("increment", ())),
            )
        else:
            raise TestCaseFailure(
                f"unsupported IXIA pattern {self.pattern!r} during restore"
            )

    @classmethod
    def _custom_increments(
        cls, increments: t.Iterable[t.Mapping[str, t.Any]]
    ) -> list[t.Tuple[t.Any, t.Any, list[t.Any]]]:
        return [
            (
                increment["value"],
                increment["count"],
                cls._custom_increments(increment.get("increment", ())),
            )
            for increment in increments
        ]


def _read_values(field: t.Any, label: str) -> tuple[t.Any, ...]:
    raw_values = getattr(field, "Values", field)
    if raw_values is None or isinstance(raw_values, (str, bytes)):
        raise TestCaseFailure(f"{label} must be an iterable of values")
    try:
        return tuple(raw_values)
    except TypeError as error:
        raise TestCaseFailure(f"{label} must be an iterable of values") from error


@dataclasses.dataclass(frozen=True)
class IxiaRouteGeometry:
    peer_count: int
    routes_per_peer: int
    physical_row_count: int
    addresses_per_row: int
    starts: tuple[str, ...]
    lasts: tuple[str, ...]
    prefix_lengths: tuple[int, ...]
    peers: tuple[str, ...]
    label: str

    @classmethod
    def from_pool(
        cls,
        pool: t.Any,
        peers: t.Sequence[str],
        *,
        peer_count: int,
        routes_per_peer: int,
        label: str,
    ) -> IxiaRouteGeometry:
        physical_row_count = int(pool.Count)
        addresses_per_row = int(pool.NumberOfAddresses)
        allowed = {
            (peer_count, routes_per_peer),
            (peer_count * routes_per_peer, 1),
        }
        actual = (physical_row_count, addresses_per_row)
        if actual not in allowed:
            raise TestCaseFailure(
                f"{label}: unsupported IXIA route geometry {actual}; "
                f"expected one of {sorted(allowed)}"
            )

        starts = tuple(
            str(value)
            for value in _read_values(pool.NetworkAddress, f"{label}: NetworkAddress")
        )
        lasts = tuple(
            str(value)
            for value in _read_values(
                pool.LastNetworkAddress, f"{label}: LastNetworkAddress"
            )
        )
        prefix_lengths = tuple(
            int(value)
            for value in _read_values(pool.PrefixLength, f"{label}: PrefixLength")
        )
        normalized_peers = tuple(peers)
        for name, values in (
            ("NetworkAddress", starts),
            ("LastNetworkAddress", lasts),
        ):
            if len(values) != physical_row_count:
                raise TestCaseFailure(
                    f"{label}: {name} has {len(values)} rows, "
                    f"expected {physical_row_count}"
                )
        if len(prefix_lengths) not in {1, physical_row_count}:
            raise TestCaseFailure(
                f"{label}: PrefixLength has {len(prefix_lengths)} values, "
                f"expected 1 or {physical_row_count}"
            )
        if len(normalized_peers) != peer_count:
            raise TestCaseFailure(
                f"{label}: mapped peer count is {len(normalized_peers)}, "
                f"expected {peer_count}"
            )
        return cls(
            peer_count=peer_count,
            routes_per_peer=routes_per_peer,
            physical_row_count=physical_row_count,
            addresses_per_row=addresses_per_row,
            starts=starts,
            lasts=lasts,
            prefix_lengths=prefix_lengths,
            peers=normalized_peers,
            label=label,
        )

    @property
    def flattened(self) -> bool:
        return self.addresses_per_row == 1

    @property
    def route_row_count(self) -> int:
        return self.peer_count * self.routes_per_peer

    def route_rows_for_peer(self, peer: int) -> tuple[int, ...]:
        if peer < 0 or peer >= self.peer_count:
            raise TestCaseFailure(f"{self.label}: logical peer row {peer} is invalid")
        start = peer * self.routes_per_peer
        return tuple(range(start, start + self.routes_per_peer))

    def physical_rows_for_peer(self, peer: int) -> tuple[int, ...]:
        if peer < 0 or peer >= self.peer_count:
            raise TestCaseFailure(f"{self.label}: logical peer row {peer} is invalid")
        if not self.flattened:
            return (peer,)
        start = peer * self.routes_per_peer
        return tuple(range(start, start + self.routes_per_peer))

    def physical_rows_for_peers(self, peers: t.Iterable[int]) -> tuple[int, ...]:
        logical_peers = tuple(peers)
        if len(set(logical_peers)) != len(logical_peers):
            raise TestCaseFailure(f"{self.label}: duplicate logical peer rows")
        return tuple(
            physical
            for peer in logical_peers
            for physical in self.physical_rows_for_peer(peer)
        )

    def endpoint_rows_for_peer(self, peer: int) -> tuple[int, ...]:
        rows = self.physical_rows_for_peer(peer)
        return (rows[0],) if len(rows) == 1 else (rows[0], rows[-1])

    def prefix_range_for_peer(self, peer: int) -> tuple[str, str, int]:
        rows = self.physical_rows_for_peer(peer)
        lengths = {
            int(self.value_at(self.prefix_lengths, row, "PrefixLength")) for row in rows
        }
        if len(lengths) != 1:
            raise TestCaseFailure(
                f"{self.label}: logical peer row {peer} has mixed prefix lengths"
            )
        return self.starts[rows[0]], self.lasts[rows[-1]], lengths.pop()

    def prefix_for_peer_route(self, peer: int, route: int) -> str:
        if route < 0 or route >= self.routes_per_peer:
            raise TestCaseFailure(
                f"{self.label}: route index {route} is invalid for peer {peer}"
            )
        rows = self.physical_rows_for_peer(peer)
        if self.flattened:
            row, offset = rows[route], 0
        else:
            row_index, offset = divmod(route, self.addresses_per_row)
            if row_index >= len(rows):
                raise TestCaseFailure(
                    f"{self.label}: route index {route} exceeds peer {peer} rows"
                )
            row = rows[row_index]
        length = int(self.value_at(self.prefix_lengths, row, "PrefixLength"))
        start_address = self.starts[row].split("/")[0]
        start = ipaddress.ip_network(f"{start_address}/{length}", strict=False)
        prefix = ipaddress.ip_network(
            f"{start.network_address + offset * start.num_addresses}/{length}",
            strict=False,
        )
        last_address = self.lasts[rows[-1]].split("/")[0]
        last = ipaddress.ip_network(f"{last_address}/{length}", strict=False)
        if prefix.version != last.version:
            raise TestCaseFailure(
                f"{self.label}: peer {peer} prefix range mixes address families"
            )
        if int(prefix.network_address) > int(last.network_address):
            raise TestCaseFailure(
                f"{self.label}: route index {route} exceeds peer {peer} prefix range"
            )
        return str(prefix)

    def expand_peer_values(self, values: t.Sequence[t.Any]) -> list[t.Any]:
        if len(values) != self.peer_count:
            raise TestCaseFailure(
                f"{self.label}: logical pattern has {len(values)} values, "
                f"expected {self.peer_count}"
            )
        return [
            values[peer]
            for peer in range(self.peer_count)
            for _ in self.physical_rows_for_peer(peer)
        ]

    def value_at(
        self,
        values: t.Sequence[t.Any],
        physical_row: int,
        label: str,
    ) -> t.Any:
        if physical_row < 0 or physical_row >= self.physical_row_count:
            raise TestCaseFailure(
                f"{self.label}: {label} row {physical_row} is invalid"
            )
        if len(values) == 1:
            return values[0]
        if len(values) != self.physical_row_count:
            raise TestCaseFailure(
                f"{self.label}: {label} has {len(values)} values, "
                f"expected 1 or {self.physical_row_count}"
            )
        return values[physical_row]


@dataclasses.dataclass(frozen=True)
class IxiaValueVector:
    handle: t.Any
    values: tuple[t.Any, ...]
    expanded_row_count: int = 0
    label: str = "IXIA vector"
    compact_row_count: int = 0
    pattern: IxiaPatternSnapshot | None = None

    def __post_init__(self) -> None:
        count = self.expanded_row_count or len(self.values)
        object.__setattr__(self, "expanded_row_count", count)
        compact = self.compact_row_count or count
        object.__setattr__(self, "compact_row_count", compact)
        if compact <= 0 or count % compact:
            raise TestCaseFailure(
                f"{self.label} compact row count {compact} does not divide {count}"
            )
        self._validate(self.values)

    @classmethod
    def capture(
        cls,
        handle: t.Any,
        expanded_row_count: int,
        label: str,
        compact_row_count: int | None = None,
    ) -> IxiaValueVector:
        return cls(
            handle=handle,
            values=tuple(handle.Values),
            expanded_row_count=expanded_row_count,
            label=label,
            compact_row_count=compact_row_count or expanded_row_count,
            pattern=IxiaPatternSnapshot.capture(handle, label),
        )

    def _validate(self, values: t.Sequence[t.Any]) -> None:
        allowed = {1, self.compact_row_count, self.expanded_row_count}
        if len(values) not in allowed:
            raise TestCaseFailure(
                f"{self.label} has {len(values)} values, "
                f"expected one of {sorted(allowed)}"
            )

    def _at(self, values: t.Sequence[t.Any], row: int) -> t.Any:
        self._validate(values)
        if row < 0 or row >= self.expanded_row_count:
            raise TestCaseFailure(f"{self.label} row {row} is invalid")
        if len(values) == 1:
            return values[0]
        if len(values) == self.compact_row_count:
            return values[row // (self.expanded_row_count // self.compact_row_count)]
        return values[row]

    def current_values(self) -> tuple[t.Any, ...]:
        values = tuple(self.handle.Values)
        self._validate(values)
        return values

    def current_value(self, row: int) -> t.Any:
        return self.value_from(self.current_values(), row)

    def value_from(self, values: t.Sequence[t.Any], row: int) -> t.Any:
        return self._at(values, row)

    def baseline_value(self, row: int) -> t.Any:
        return self._at(self.values, row)

    def write_rows(self, rows: t.Iterable[int], value: t.Any) -> None:
        current = self.current_values()
        expanded = [self._at(current, row) for row in range(self.expanded_row_count)]
        for row in tuple(rows):
            if row < 0 or row >= self.expanded_row_count:
                raise TestCaseFailure(f"{self.label} row {row} is invalid")
            expanded[row] = value
        self.handle.ValueList(expanded)

    def plan_fixed_count_write(
        self, rows: t.Iterable[int], value: t.Any
    ) -> tuple[tuple[t.Any, ...], tuple[t.Any, ...]]:
        count = self._fixed_count()
        current = self._fixed_count_values(count)
        expanded = [self._at(current, row) for row in range(self.expanded_row_count)]
        for row in tuple(rows):
            if row < 0 or row >= self.expanded_row_count:
                raise TestCaseFailure(f"{self.label} row {row} is invalid")
            expanded[row] = value
        expected = tuple(expanded)
        return expected, self._compress_fixed_count(expected, count)

    def write_fixed_count(self, values: t.Sequence[t.Any]) -> None:
        count = self._fixed_count()
        if len(values) != count:
            raise TestCaseFailure(
                f"{self.label} write has {len(values)} values, expected Count {count}"
            )
        self.handle.ValueList(list(values))

    def assert_exact_fixed_count_readback(
        self, expected_expanded: t.Sequence[t.Any]
    ) -> None:
        count = self._fixed_count()
        if len(expected_expanded) != self.expanded_row_count:
            raise TestCaseFailure(
                f"{self.label} expected readback has {len(expected_expanded)} values, "
                f"expected {self.expanded_row_count}"
            )
        expected = self._compress_fixed_count(tuple(expected_expanded), count)
        current = self._fixed_count_values(count)
        if len(current) == 1:
            if any(value != expected_expanded[0] for value in expected_expanded):
                raise TestCaseFailure(
                    f"{self.label} singleton readback cannot represent mixed values"
                )
            expected = (expected_expanded[0],)
        if current != expected:
            raise TestCaseFailure(
                f"{self.label} effective Values readback does not match the write"
            )

    def _fixed_count(self) -> int:
        raw_count = getattr(self.handle, "Count", None)
        if raw_count is None:
            raise TestCaseFailure(f"{self.label} is missing fixed Count")
        try:
            count = int(raw_count)
        except (TypeError, ValueError) as error:
            raise TestCaseFailure(
                f"{self.label} has invalid fixed Count {raw_count!r}"
            ) from error
        if count != self.compact_row_count:
            raise TestCaseFailure(
                f"{self.label} fixed Count is {count}, expected "
                f"{self.compact_row_count}"
            )
        return count

    def _fixed_count_values(self, count: int) -> tuple[t.Any, ...]:
        raw_values = getattr(self.handle, "Values", None)
        if raw_values is None or isinstance(raw_values, (str, bytes)):
            raise TestCaseFailure(f"{self.label} effective Values is not iterable")
        try:
            values = tuple(raw_values)
        except TypeError as error:
            raise TestCaseFailure(
                f"{self.label} effective Values is not iterable"
            ) from error
        if len(values) not in {1, count}:
            raise TestCaseFailure(
                f"{self.label} effective Values has {len(values)} values, "
                f"expected 1 or fixed Count {count}"
            )
        return values

    def _compress_fixed_count(
        self, values: tuple[t.Any, ...], count: int
    ) -> tuple[t.Any, ...]:
        block_size = self.expanded_row_count // count
        compressed: list[t.Any] = []
        for block in range(count):
            start = block * block_size
            block_values = values[start : start + block_size]
            if any(value != block_values[0] for value in block_values[1:]):
                raise TestCaseFailure(
                    f"{self.label} expanded block {block} is not representable by "
                    f"fixed Count {count}"
                )
            compressed.append(block_values[0])
        return tuple(compressed)

    def restore(self) -> None:
        if self.pattern is not None:
            self.pattern.restore(self.handle)
        elif len(self.values) == 1:
            self.handle.Single(value=self.values[0])
        else:
            self.handle.ValueList(list(self.values))

    def is_exactly_restored(self) -> bool:
        values_match = tuple(self.handle.Values) == self.values
        if self.pattern is None:
            return values_match
        return (
            values_match
            and IxiaPatternSnapshot.capture(self.handle, self.label) == self.pattern
        )


@dataclasses.dataclass(frozen=True)
class IxiaOverlay:
    index: int
    count: int
    value: t.Any


@dataclasses.dataclass
class IxiaOverlayVector:
    """Sparse IXIA mutations over an immutable topology-defined base pattern."""

    _CREATE_RECONCILE_TIMEOUT_SECONDS: t.ClassVar[float] = 30.0
    _CREATE_RECONCILE_POLL_SECONDS: t.ClassVar[float] = 0.25

    handle: t.Any
    baseline_value_raw: t.Any
    expanded_row_count: int
    label: str = "IXIA overlay vector"
    expected_overlays: tuple[IxiaOverlay, ...] = ()
    touched: bool = False

    @classmethod
    def capture(
        cls,
        handle: t.Any,
        expanded_row_count: int,
        label: str,
    ) -> IxiaOverlayVector:
        vector = cls(handle, None, expanded_row_count, label)
        count, pattern_type, pattern = vector._fresh_base()
        if count != expanded_row_count:
            raise TestCaseFailure(
                f"{label} Count is {count}, expected {expanded_row_count}"
            )
        if pattern_type != "Single":
            raise TestCaseFailure(
                f"{label} base pattern is {pattern_type!r}, expected 'Single'"
            )
        vector.baseline_value_raw = pattern
        overlays = vector._read_overlays()
        if overlays:
            raise TestCaseFailure(
                f"{label} has pre-existing overlays; topology baseline is ambiguous"
            )
        return vector

    @property
    def compact_row_count(self) -> int:
        return self.expanded_row_count

    @property
    def values(self) -> tuple[t.Any, ...]:
        return (self.baseline_value_raw,)

    def baseline_value(self, row: int) -> t.Any:
        self._validate_row(row)
        return self.baseline_value_raw

    def current_value(self, row: int) -> t.Any:
        self._validate_row(row)
        one_based = row + 1
        for overlay in self.expected_overlays:
            if overlay.index <= one_based < overlay.index + overlay.count:
                return overlay.value
        return self.baseline_value_raw

    def write_rows(self, rows: t.Iterable[int], value: t.Any) -> None:
        ranges = self._row_ranges(rows)
        planned = tuple(
            IxiaOverlay(start + 1, end - start + 1, value) for start, end in ranges
        )
        entries = self._read_overlay_entries()
        observed = self._parse_overlays(entries)
        if tuple(self._overlay_key(item) for item in observed) != tuple(
            self._overlay_key(item) for item in self.expected_overlays
        ):
            raise TestCaseFailure(
                f"{self.label} overlay readback mismatch before write: "
                f"expected={self.expected_overlays!r}, observed={observed!r}"
            )
        observed_shape = tuple((item.index, item.count) for item in observed)
        planned_shape = tuple((item.index, item.count) for item in planned)
        if observed and planned_shape != observed_shape:
            raise TestCaseFailure(
                f"{self.label} overlay shape changed: "
                f"expected={observed_shape!r}, planned={planned_shape!r}"
            )
        writes_baseline = bool(planned) and all(
            self._canonical_value(item.value)
            == self._canonical_value(self.baseline_value_raw)
            for item in planned
        )
        if writes_baseline:
            if observed:
                self.touched = True
                self.handle.ClearOverlays()
            self.expected_overlays = ()
            return
        self.touched = True
        if not observed:
            ambiguous_create_errors: list[Exception] = []
            for overlay in planned:
                if error := self._post_overlay(overlay):
                    ambiguous_create_errors.append(error)
            reconciled = self._reconcile_created_overlays(planned)
            if reconciled is None:
                failure = TestCaseFailure(
                    f"{self.label} created overlays did not converge to the "
                    "planned effective ranges"
                )
                if ambiguous_create_errors:
                    raise failure from ambiguous_create_errors[-1]
                raise failure
            planned = reconciled
        else:
            connection = self._connection()
            entries_by_shape = {
                (overlay.index, overlay.count): entry
                for overlay, entry in zip(
                    (self._parse_overlay(item) for item in entries), entries
                )
            }
            updates = tuple(
                (
                    self._overlay_href(
                        entries_by_shape[(overlay.index, overlay.count)]
                    ),
                    overlay,
                )
                for overlay in planned
            )
            hrefs = tuple(href for href, _ in updates)
            if len(hrefs) != len(set(hrefs)):
                raise TestCaseFailure(
                    f"{self.label} overlay readback has duplicate child links"
                )
            for href, overlay in updates:
                connection._update(
                    href,
                    {
                        "count": overlay.count,
                        "index": overlay.index,
                        "indexStep": 1,
                        "value": overlay.value,
                    },
                )
        self.expected_overlays = planned

    def append_rows(self, rows: t.Iterable[int], value: t.Any) -> None:
        additions = tuple(
            IxiaOverlay(start + 1, end - start + 1, value)
            for start, end in self._row_ranges(rows)
        )
        if not additions:
            return
        if all(
            self._canonical_value(item.value)
            == self._canonical_value(self.baseline_value_raw)
            for item in additions
        ):
            raise TestCaseFailure(
                f"{self.label} cannot append overlays equal to the base value"
            )
        observed = self._parse_overlays(self._read_overlay_entries())
        observed_effective = self._coalesce_adjacent_overlays(observed)
        expected_effective = self._coalesce_adjacent_overlays(self.expected_overlays)
        if self._overlay_keys(observed_effective) != self._overlay_keys(
            expected_effective
        ):
            raise TestCaseFailure(
                f"{self.label} overlay readback mismatch before append: "
                f"expected={self.expected_overlays!r}, observed={observed!r}"
            )
        planned = self._ordered_nonoverlapping((*observed, *additions))
        self.touched = True
        ambiguous_create_errors: list[Exception] = []
        for overlay in additions:
            if error := self._post_overlay(overlay):
                ambiguous_create_errors.append(error)
        reconciled = self._reconcile_created_overlays(planned)
        if reconciled is None:
            failure = TestCaseFailure(
                f"{self.label} appended overlays did not converge to the "
                "planned effective ranges"
            )
            if ambiguous_create_errors:
                raise failure from ambiguous_create_errors[-1]
            raise failure
        self.expected_overlays = reconciled

    def _post_overlay(self, overlay: IxiaOverlay) -> Exception | None:
        connection = self._connection()
        handle_href = getattr(self.handle, "_href", None)
        if not isinstance(handle_href, str) or not handle_href:
            raise TestCaseFailure(f"{self.label} has no usable multivalue href")
        normalize_url = getattr(connection, "_normalize_url", None)
        request = getattr(connection, "_request", None)
        raw_headers = getattr(connection, "_headers", None)
        if (
            not callable(normalize_url)
            or not callable(request)
            or not isinstance(raw_headers, dict)
        ):
            try:
                self.handle.Overlay(
                    overlay.index,
                    overlay.value,
                    count=overlay.count,
                )
            except Exception as error:
                if not self._is_overlay_child_not_found(error):
                    raise
                # RESTPy can finish the POST before IXIA exposes its child URI.
                # Parent collection reconciliation disambiguates that result.
                return error
            return None
        _connection_url, url = t.cast(
            tuple[t.Any, str], normalize_url(f"{handle_href}/overlay")
        )
        headers = dict(raw_headers)
        headers["Content-Type"] = "application/json"
        response = t.cast(
            t.Any,
            request(
                method="POST",
                url=url,
                data=json.dumps(
                    {
                        "count": overlay.count,
                        "index": overlay.index,
                        "indexStep": 1,
                        "value": overlay.value,
                    }
                ),
                headers=headers,
                verify=getattr(connection, "_verify_cert", True),
                allow_redirects=False,
            ),
        )
        if getattr(response, "status_code", None) != 201:
            process_error = getattr(connection, "_process_response_status_code", None)
            if callable(process_error):
                process_error(url, headers, response)
            raise TestCaseFailure(
                f"{self.label} overlay POST returned unexpected status "
                f"{getattr(response, 'status_code', None)!r}"
            )
        try:
            response_body = response.json()
        except Exception as error:
            raise TestCaseFailure(
                f"{self.label} overlay POST returned malformed JSON"
            ) from error
        if not isinstance(response_body, dict):
            raise TestCaseFailure(f"{self.label} overlay POST returned malformed JSON")
        self._overlay_href(response_body)
        return None

    def _reconcile_created_overlays(
        self, expected: t.Sequence[IxiaOverlay]
    ) -> tuple[IxiaOverlay, ...] | None:
        expected_effective = self._coalesce_adjacent_overlays(expected)
        deadline = time.monotonic() + self._CREATE_RECONCILE_TIMEOUT_SECONDS
        last_child_visibility_error: Exception | None = None
        while True:
            try:
                observed = self._read_overlays()
                observed_effective = self._coalesce_adjacent_overlays(observed)
            except TimeoutError:
                raise
            except Exception as error:
                if not self._is_overlay_child_not_found(error):
                    raise
                last_child_visibility_error = error
            else:
                if self._overlay_keys(observed_effective) == self._overlay_keys(
                    expected_effective
                ):
                    return observed
                if not self._overlay_ranges_are_subset(
                    observed_effective, expected_effective
                ):
                    return None
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                if last_child_visibility_error is not None:
                    raise TestCaseFailure(
                        f"{self.label} overlay child visibility did not converge"
                    ) from last_child_visibility_error
                return None
            time.sleep(min(self._CREATE_RECONCILE_POLL_SECONDS, remaining))

    def _coalesce_adjacent_overlays(
        self, overlays: t.Sequence[IxiaOverlay]
    ) -> tuple[IxiaOverlay, ...]:
        ordered = self._ordered_nonoverlapping(overlays)
        merged: list[IxiaOverlay] = []
        for overlay in ordered:
            if (
                merged
                and merged[-1].index + merged[-1].count == overlay.index
                and self._canonical_value(merged[-1].value)
                == self._canonical_value(overlay.value)
            ):
                previous = merged[-1]
                merged[-1] = IxiaOverlay(
                    previous.index,
                    previous.count + overlay.count,
                    previous.value,
                )
            else:
                merged.append(overlay)
        return tuple(merged)

    def _overlay_ranges_are_subset(
        self,
        observed: t.Sequence[IxiaOverlay],
        expected: t.Sequence[IxiaOverlay],
    ) -> bool:
        return all(
            any(
                self._canonical_value(actual.value)
                == self._canonical_value(planned.value)
                and planned.index <= actual.index
                and actual.index + actual.count <= planned.index + planned.count
                for planned in expected
            )
            for actual in observed
        )

    def _overlay_keys(
        self, overlays: t.Sequence[IxiaOverlay]
    ) -> tuple[tuple[int, int, t.Any], ...]:
        return tuple(self._overlay_key(item) for item in overlays)

    def _is_overlay_child_not_found(self, error: Exception) -> bool:
        message = str(error)
        if "cannot be found" not in message.lower():
            return False
        handle_href = getattr(self.handle, "_href", None)
        if not isinstance(handle_href, str) or not handle_href:
            return False
        expected_parent = (
            f"{urllib.parse.urlsplit(handle_href).path.rstrip('/')}/overlay/"
        )
        start = message.find(expected_parent)
        if start < 0:
            return False
        child = message[start + len(expected_parent) :]
        return bool(child) and child[0].isdigit()

    def validate_rows(self, rows: t.Iterable[int]) -> None:
        self.assert_exact_readback()
        self._row_ranges(rows)

    def assert_exact_readback(self, *, refresh_base: bool = False) -> None:
        if refresh_base:
            self._assert_base_unchanged()
        observed = self._read_overlays()
        expected_keys = tuple(
            self._overlay_key(item) for item in self.expected_overlays
        )
        observed_keys = tuple(self._overlay_key(item) for item in observed)
        if observed_keys != expected_keys:
            raise TestCaseFailure(
                f"{self.label} overlay readback mismatch: "
                f"expected={self.expected_overlays!r}, observed={observed!r}"
            )

    def audit_rows(self) -> tuple[int, ...]:
        rows = {0, self.expanded_row_count - 1}
        for overlay in self.expected_overlays:
            start = overlay.index - 1
            end = start + overlay.count - 1
            rows.update((start, end))
            if start > 0:
                rows.add(start - 1)
            if end + 1 < self.expanded_row_count:
                rows.add(end + 1)
        return tuple(sorted(rows))

    def restore(self) -> None:
        if self.touched:
            self.handle.ClearOverlays()
            self.expected_overlays = ()

    def is_exactly_restored(self) -> bool:
        self._assert_base_unchanged()
        return not self._read_overlays()

    def _assert_base_unchanged(self) -> None:
        count, pattern_type, pattern = self._fresh_base()
        if count != self.expanded_row_count:
            raise TestCaseFailure(
                f"{self.label} Count changed from {self.expanded_row_count} to {count}"
            )
        if pattern_type != "Single":
            raise TestCaseFailure(
                f"{self.label} base pattern changed from 'Single' to {pattern_type!r}"
            )
        if self._canonical_value(pattern) != self._canonical_value(
            self.baseline_value_raw
        ):
            raise TestCaseFailure(
                f"{self.label} topology base changed from "
                f"{self.baseline_value_raw!r} to {pattern!r}"
            )

    def _fresh_base(self) -> tuple[int, str, t.Any]:
        parent = getattr(self.handle, "_parent", None)
        mode = getattr(parent, "_mode", None)
        if mode and mode[0] == "config":
            raise TestCaseFailure(
                f"{self.label} sparse overlays require a runtime IXIA handle"
            )
        refresh = getattr(self.handle, "_custom_select", None)
        if not callable(refresh):
            raise TestCaseFailure(f"{self.label} cannot refresh the IXIA topology base")
        refresh()
        count = self._strict_positive_int(self.handle.Count, "Count")
        return count, str(self.handle.PatternType), self.handle.Pattern

    def _read_overlays(self) -> tuple[IxiaOverlay, ...]:
        entries = self._read_overlay_entries()
        return self._parse_overlays(entries)

    def _read_overlay_entries(self) -> tuple[t.Any, ...]:
        connection = self._connection()
        href = getattr(self.handle, "_href", None)
        if not href:
            raise TestCaseFailure(f"{self.label} cannot read IXIA overlays")
        return self._overlay_entries(connection._read(f"{href}/overlay"))

    def _parse_overlays(self, entries: t.Sequence[t.Any]) -> tuple[IxiaOverlay, ...]:
        overlays = tuple(self._parse_overlay(item) for item in entries)
        return self._ordered_nonoverlapping(overlays)

    def _connection(self) -> t.Any:
        connection = getattr(self.handle, "_connection", None)
        if connection is None:
            raise TestCaseFailure(f"{self.label} cannot access the IXIA connection")
        return connection

    def _overlay_href(self, entry: t.Any) -> str:
        if not isinstance(entry, dict):
            raise TestCaseFailure(f"{self.label} overlay links are malformed")
        links = entry.get("links")
        if not isinstance(links, (list, tuple)) or any(
            not isinstance(link, dict) for link in links
        ):
            raise TestCaseFailure(f"{self.label} overlay links are malformed")
        typed_links = t.cast(tuple[dict[str, t.Any], ...], tuple(links))
        self_link = self._single_overlay_link(typed_links, "self")
        meta_link = self._single_overlay_link(typed_links, "meta")
        handle_href = getattr(self.handle, "_href", None)
        if not isinstance(handle_href, str) or not handle_href:
            raise TestCaseFailure(f"{self.label} has no usable multivalue href")
        expected_parent = (
            f"{urllib.parse.urlsplit(handle_href).path.rstrip('/')}/overlay/"
        )
        overlay_id = None
        if "id" in entry:
            overlay_id = str(self._strict_positive_int(entry["id"], "overlay id"))
        if self_link is None and (meta_link is None or overlay_id is None):
            raise TestCaseFailure(
                f"{self.label} overlay readback has no trusted child link"
            )
        path, child = self._overlay_link_path(
            self_link or t.cast(dict[str, t.Any], meta_link),
            expected_parent,
        )
        if self_link is not None and meta_link is not None:
            meta_path, _ = self._overlay_link_path(meta_link, expected_parent)
            if meta_path != path:
                raise TestCaseFailure(
                    f"{self.label} overlay self and meta links conflict"
                )
        if overlay_id is not None and child != overlay_id:
            raise TestCaseFailure(
                f"{self.label} overlay child link conflicts with its id"
            )
        return path

    def _single_overlay_link(
        self,
        links: t.Sequence[dict[str, t.Any]],
        rel: str,
    ) -> dict[str, t.Any] | None:
        matches = tuple(link for link in links if link.get("rel") == rel)
        if len(matches) > 1:
            raise TestCaseFailure(
                f"{self.label} overlay readback has multiple {rel} links"
            )
        return matches[0] if matches else None

    def _overlay_link_path(
        self,
        link: dict[str, t.Any],
        expected_parent: str,
    ) -> tuple[str, str]:
        href = link.get("href")
        if not isinstance(href, str) or not href:
            raise TestCaseFailure(f"{self.label} overlay child link has no usable href")
        parsed = urllib.parse.urlsplit(href)
        child = parsed.path.removeprefix(expected_parent)
        if (
            not parsed.path.startswith(expected_parent)
            or not child
            or "/" in child
            or not child.isdigit()
            or parsed.query
            or parsed.fragment
        ):
            raise TestCaseFailure(
                f"{self.label} overlay child link is outside its multivalue"
            )
        return parsed.path, child

    def _overlay_entries(self, raw: t.Any) -> tuple[t.Any, ...]:
        if isinstance(raw, dict):
            if "overlay" in raw:
                raw = raw["overlay"]
            elif "index" in raw:
                raw = [raw]
            elif not raw:
                raw = []
        if not isinstance(raw, (list, tuple)):
            raise TestCaseFailure(f"{self.label} overlay readback is not a collection")
        return tuple(raw)

    def _parse_overlay(self, item: t.Any) -> IxiaOverlay:
        if not isinstance(item, dict):
            raise TestCaseFailure(
                f"{self.label} overlay readback contains a malformed entry"
            )
        try:
            index = self._strict_positive_int(item["index"], "overlay index")
            count = self._strict_positive_int(item.get("count", 1), "overlay count")
            index_step = self._strict_positive_int(
                item.get("indexStep", 1), "overlay indexStep"
            )
            value = item["value"]
        except KeyError as error:
            raise TestCaseFailure(
                f"{self.label} overlay readback contains a malformed entry"
            ) from error
        if index_step != 1:
            raise TestCaseFailure(
                f"{self.label} overlay indexStep is {index_step}, expected 1"
            )
        if index + count - 1 > self.expanded_row_count:
            raise TestCaseFailure(
                f"{self.label} overlay [{index}, {index + count - 1}] "
                f"exceeds Count {self.expanded_row_count}"
            )
        return IxiaOverlay(index, count, value)

    def _ordered_nonoverlapping(
        self, overlays: t.Sequence[IxiaOverlay]
    ) -> tuple[IxiaOverlay, ...]:
        ordered = tuple(sorted(overlays, key=lambda item: (item.index, item.count)))
        for previous, current in zip(ordered, ordered[1:]):
            if current.index <= previous.index + previous.count - 1:
                raise TestCaseFailure(
                    f"{self.label} overlay readback contains overlapping ranges"
                )
        return ordered

    def _row_ranges(self, rows: t.Iterable[int]) -> tuple[tuple[int, int], ...]:
        raw_rows = tuple(rows)
        if any(type(row) is not int for row in raw_rows):
            raise TestCaseFailure(f"{self.label} rows must be integers")
        ordered = tuple(sorted(raw_rows))
        if len(ordered) != len(set(ordered)):
            raise TestCaseFailure(f"{self.label} rows contain duplicates")
        for row in ordered:
            self._validate_row(row)
        ranges: list[tuple[int, int]] = []
        for row in ordered:
            if not ranges or row != ranges[-1][1] + 1:
                ranges.append((row, row))
            else:
                ranges[-1] = (ranges[-1][0], row)
        return tuple(ranges)

    def _validate_row(self, row: int) -> None:
        if type(row) is not int or row < 0 or row >= self.expanded_row_count:
            raise TestCaseFailure(f"{self.label} row {row} is invalid")

    def _overlay_key(self, overlay: IxiaOverlay) -> tuple[int, int, t.Any]:
        return overlay.index, overlay.count, self._canonical_value(overlay.value)

    def _canonical_value(self, value: t.Any) -> t.Any:
        baseline = self.baseline_value_raw
        if isinstance(baseline, bool) or str(baseline).lower() in {"true", "false"}:
            normalized = str(value).lower()
            if isinstance(value, bool):
                return "bool", value
            if normalized not in {"true", "false"}:
                raise TestCaseFailure(
                    f"{self.label} overlay value {value!r} is not boolean"
                )
            return "bool", normalized == "true"
        baseline_text = str(baseline)
        if type(baseline) is int or self._is_canonical_integer(baseline_text):
            return "integer", self._strict_int(value, "overlay value")
        return "text", str(value)

    @staticmethod
    def _is_canonical_integer(value: str) -> bool:
        if value == "0":
            return True
        if value.startswith("-"):
            return value[1:].isdigit() and not value[1:].startswith("0")
        return value.isdigit() and not value.startswith("0")

    @classmethod
    def _strict_positive_int(cls, value: t.Any, field: str) -> int:
        parsed = cls._strict_int(value, field)
        if parsed < 1:
            raise TestCaseFailure(f"{field} must be positive, got {value!r}")
        return parsed

    @staticmethod
    def _strict_int(value: t.Any, field: str) -> int:
        if type(value) is int:
            return value
        if isinstance(value, str) and IxiaOverlayVector._is_canonical_integer(value):
            return int(value)
        raise TestCaseFailure(f"{field} must be an integer, got {value!r}")
