# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
import dataclasses
import ipaddress
import typing as t

from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.health_checks.convergence_observer import (
    ConvergenceOutcome,
    ConvergenceSample,
    FatalPredicateError,
    observe_convergence,
)
from taac.utils.health_check_utils import (
    ip_ntop,
    is_parent_prefix,
)
from taac.health_check.health_check import types as hc_types


class _BaselineNotReady(ValueError):
    """A required AFI has no multipath prefixes YET.

    Distinct from every other ``ValueError`` reachable during a discovery
    attempt -- an unsupported `required_address_families` entry, or a malformed
    prefix from the device -- because this one, and only this one, can heal by
    waiting. The polling path retries it and surfaces the others immediately.

    Subclasses ``ValueError`` on purpose: the one-shot path lets it escape to
    the caller's broad handler and report ERROR, and that behaviour, along with
    any caller catching ``ValueError``, must not change.
    """


@dataclasses.dataclass(frozen=True)
class _DiscoveryAttempt:
    """One complete measurement of the eBGP multipath distribution.

    ``not_ready_reason`` is None when the measurement satisfied the sanity
    bounds. Otherwise it carries the operator-facing explanation, which doubles
    as the FAIL message on the one-shot path and as the non-converged detail on
    the polling path -- so both paths report the same thing for the same state.
    """

    widths: t.Dict[int, int]
    prefixes: t.Set[str]
    distribution_summary: t.Dict[int, int]
    skipped_ibgp_count: int
    not_ready_reason: t.Optional[str]


class BgpMultipathNextHopCountHealthCheck(
    AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]
):
    """
    Health check to verify BGP multipath group (next-hop count) for prefixes.

    This check queries the BGP++ RIB and validates that prefixes have the expected
    number of next-hops in their multipath group. This is essential for verifying
    that BGP session oscillations correctly affect the multipath group size.

    Supports two modes:
        1. Discovery mode (discover_baseline=True): Walks the eBGP RIB, builds the
           next-hop-count distribution, and stores BOTH the modal width and the
           prefix set at that width. No exact-match selector required — the test
           portably adapts to whatever ECMP fanout the testbed actually produces.
           Optional sanity bounds (expected_min_baseline_width /
           expected_max_baseline_width) can fail the discovery if the measurement
           falls outside an expected range.
        2. Validation mode (default): Validates that prefixes have the expected
           number of next-hops. With use_discovered_width=True, the expected count
           is derived from the stored width minus peers_stopped_delta — letting
           reduce/restore checks read the live measurement rather than recomputing
           from external constants.

    Supports:
        - Exact next-hop count validation
        - Minimum next-hop count validation
        - Maximum next-hop count validation
        - Range-based validation (min and max)
        - Width-relative validation (derived from discovered baseline width)

    check_params:
        - discover_baseline: If True, measure the modal eBGP NH-count and store
        - baseline_nexthop_count: DEPRECATED selector (exact-match filter, legacy)
        - expected_min_baseline_width: Optional lower sanity bound for measured width
        - expected_max_baseline_width: Optional upper sanity bound for measured width
        - min_multipath_width: Floor for the distribution scan (default 2 — single-NH
          prefixes are excluded because they aren't part of any multipath group)
        - use_discovered_width: If True, validation derives expected_nexthop_count
          from the stored baseline width minus peers_stopped_delta
        - peers_stopped_delta: Number of peers currently stopped (default 0 / restore)
        - prefix_subnets: Optional list of prefix subnets to check (e.g., ["10.0.0.0/8", "2001:db8::/32"])
        - parent_prefixes_to_ignore: Optional list of parent prefixes to ignore
        - expected_nexthop_count: Optional exact number of next-hops expected
        - min_nexthop_count: Optional minimum number of next-hops expected
        - max_nexthop_count: Optional maximum number of next-hops expected
        - sample_size: Optional number of prefixes to sample for validation (default: 10)
        - ebgp_only: If True, only consider eBGP routes (routes with non-empty AS_PATH). Default: True for discovery mode.
    """

    # TODO: Change to BGP_MULTIPATH_NEXT_HOP_COUNT_CHECK once thrift enum lands
    CHECK_NAME = hc_types.CheckName.NEXT_HOP_COUNT_CHECK
    OPERATING_SYSTEMS = ["EOS"]

    # TAAC does not schedule concurrent tests against one reserved device. Keying
    # worker-local state by device prevents unrelated devices from sharing it.
    _discovered_baselines: t.ClassVar[
        t.Dict[str, t.Tuple[t.Set[str], t.Dict[int, int]]]
    ] = {}

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        """
        Run the BGP multipath next-hop count check for Arista devices.

        Args:
            obj: Test device
            input: Base health check input
            check_params: Dictionary containing:
                - discover_baseline: If True, discover and store prefixes with baseline next-hop count
                - baseline_nexthop_count: Expected next-hop count for baseline discovery
                - prefix_subnets: Optional list of prefix subnets to check
                - parent_prefixes_to_ignore: Optional list of parent prefixes to ignore
                - expected_nexthop_count: Optional exact next-hop count
                - min_nexthop_count: Optional minimum next-hop count
                - max_nexthop_count: Optional maximum next-hop count
                - sample_size: Number of prefixes to sample (default: 10)

        Returns:
            HealthCheckResult: Result of the health check
        """
        self.logger.debug(
            f"Executing BGP multipath next-hop count check on {obj.name}."
        )

        discover_baseline = check_params.get("discover_baseline", False)

        if discover_baseline:
            return await self._run_discovery_mode(obj, check_params)
        else:
            return await self._run_validation_mode(obj, check_params)

    async def _run_discovery_mode(
        self,
        obj: TestDevice,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        """
        Discovery mode: Measure the eBGP RIB's next-hop-count distribution and
        store the modal width + the prefixes at that width as the baseline.

        Picking the mode (rather than asserting an external constant) lets the
        same playbook port across testbeds with different ECMP fanouts.
        Optional sanity bounds catch the case where the measurement is wildly
        outside what the testbed should produce.
        """
        # A failed discovery must never leave a later validation reading state
        # captured by an earlier run against this device. Hoisted above the
        # poll so it fires exactly once, not once per iteration.
        BgpMultipathNextHopCountHealthCheck._discovered_baselines.pop(obj.name, None)

        try:
            # Opt-in: DETECT steady state instead of assuming it. Without a hard
            # timeout this is the historical single read, byte-for-byte the same
            # decisions in the same order.
            hard_timeout = check_params.get("convergence_hard_timeout_seconds")
            if hard_timeout is None:
                attempt = await self._attempt_baseline_discovery(check_params)
            else:
                attempt = await self._poll_for_baseline(
                    check_params, float(hard_timeout)
                )

            if attempt.not_ready_reason is not None:
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.FAIL,
                    message=attempt.not_ready_reason,
                )

            BgpMultipathNextHopCountHealthCheck._discovered_baselines[obj.name] = (
                set(attempt.prefixes),
                dict(attempt.widths),
            )

            success_message = (
                f"BGP multipath baseline discovery PASSED.\n"
                f"  - Measured baseline widths: {attempt.widths}\n"
                f"  - Prefixes at baseline width: {len(attempt.prefixes)}\n"
                f"  - Distribution: {attempt.distribution_summary}\n"
                f"  - Skipped {attempt.skipped_ibgp_count} iBGP/local routes\n"
                f"  - Sample prefixes: {list(attempt.prefixes)[:5]}"
            )
            self.logger.info(success_message)
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.PASS,
                message=success_message,
            )

        except Exception as e:
            error_message = f"Error during BGP multipath baseline discovery: {str(e)}"
            self.logger.error(error_message)
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.ERROR,
                message=error_message,
            )

    async def _attempt_baseline_discovery(
        self,
        check_params: t.Dict[str, t.Any],
    ) -> _DiscoveryAttempt:
        """One complete measurement of the eBGP multipath distribution.

        Reads the device and evaluates the sanity bounds; stores nothing, so it
        is safe to call repeatedly. ``not_ready_reason`` carries the verbatim
        message the one-shot path used to return, so wrapping this in a poll
        does not change what an operator reads for the same device state.

        Deliberately does NOT catch the ``_BaselineNotReady`` that
        ``_discover_by_afi`` raises when a required AFI has no multipath
        prefixes yet. On the one-shot path that must keep escaping to the
        caller's broad handler and reporting ERROR, exactly as before; only the
        polling path reinterprets it as "not yet", because only there is
        retrying meaningful -- and it reinterprets ONLY that type, so a
        deterministic error is not retried into a timeout.
        """
        min_multipath_width = check_params.get("min_multipath_width", 2)

        (
            distribution,
            skipped_ibgp_count,
            skipped_originated_count,
        ) = await self._measure_nexthop_distribution(check_params)

        distribution_summary = {
            width: len(prefixes) for width, prefixes in sorted(distribution.items())
        }
        self.logger.info(
            f"Next-hop count distribution (eBGP only={check_params.get('ebgp_only', True)}, "
            f"min_multipath_width={min_multipath_width}): {distribution_summary}"
        )
        self.logger.info(
            f"Skipped: {skipped_originated_count} originated, {skipped_ibgp_count} iBGP/local routes"
        )

        if not distribution:
            return _DiscoveryAttempt(
                widths={},
                prefixes=set(),
                distribution_summary=distribution_summary,
                skipped_ibgp_count=skipped_ibgp_count,
                not_ready_reason=(
                    f"No multipath eBGP prefixes (>= {min_multipath_width}-way) "
                    f"found in BGP RIB (skipped {skipped_ibgp_count} iBGP/local routes)"
                ),
            )

        required_afis = self._required_address_families(check_params)
        discovered_widths: t.Dict[int, int]
        if required_afis:
            discovered_widths, discovered_prefixes = self._discover_by_afi(
                distribution, required_afis
            )
        else:
            discovered_width, discovered_prefixes = max(
                distribution.items(), key=lambda kv: len(kv[1])
            )
            discovered_widths = {
                ipaddress.ip_network(prefix, strict=False).version: discovered_width
                for prefix in discovered_prefixes
            }

        sanity_failures = [
            f"IPv{afi}: {failure}"
            for afi, discovered_width in sorted(discovered_widths.items())
            for failure in self._baseline_sanity_failures(
                discovered_width, check_params
            )
        ]
        return _DiscoveryAttempt(
            widths=discovered_widths,
            prefixes=discovered_prefixes,
            distribution_summary=distribution_summary,
            skipped_ibgp_count=skipped_ibgp_count,
            not_ready_reason=(
                f"BGP multipath baseline discovery sanity-check FAILED: "
                f"{'; '.join(sanity_failures)}. Distribution: {distribution_summary}"
                if sanity_failures
                else None
            ),
        )

    async def _poll_for_baseline(
        self,
        check_params: t.Dict[str, t.Any],
        hard_timeout_seconds: float,
    ) -> _DiscoveryAttempt:
        """Poll until the measured width satisfies the sanity bounds and HOLDS.

        Steady state is a property of the device, not of the clock, so this
        replaces a fixed pre-read settle: too short and the baseline is captured
        mid-convergence, too long and every run pays for the worst case.

        The holding requirement is the part a plain retry loop cannot express.
        ``observe_convergence`` resets its confirmation window on any failing
        observation AND on any predicate error, so a width that touches the
        expected value once and falls back does not satisfy this.
        """
        predicate_timeout = check_params.get("convergence_predicate_timeout_seconds")
        last: t.Dict[str, _DiscoveryAttempt] = {}

        async def _predicate() -> ConvergenceSample:
            try:
                attempt = await self._attempt_baseline_discovery(check_params)
            except _BaselineNotReady as e:
                # A required AFI with no multipath prefixes YET is the ordinary
                # mid-convergence state, not a fault. Returning it as a
                # non-converged sample keeps the poll going; letting it raise
                # would burn an entry in predicate_errors and reset the window.
                return ConvergenceSample(converged=False, detail=str(e))
            except ValueError as e:
                # Everything else a discovery attempt can raise is DETERMINISTIC
                # -- an unsupported `required_address_families` entry, or a
                # malformed prefix -- so retrying it cannot help. Catching those
                # as "not yet" spent the whole hard timeout and then reported
                # `did not reach a steady state`, hiding a config error behind a
                # timeout; the one-shot path had always reported them as ERROR.
                # FatalPredicateError propagates straight out of
                # observe_convergence to the caller's broad handler, which
                # restores exactly that.
                raise FatalPredicateError(
                    f"BGP multipath baseline discovery failed with a "
                    f"non-retryable {type(e).__name__}: {e}"
                ) from e
            last["attempt"] = attempt
            return ConvergenceSample(
                converged=attempt.not_ready_reason is None,
                detail=(
                    attempt.not_ready_reason
                    if attempt.not_ready_reason is not None
                    else f"baseline widths {attempt.widths}"
                ),
            )

        result = await observe_convergence(
            _predicate,
            # No SLA classification wanted: the question is "did it settle",
            # not "did it settle fast enough". With this None the success
            # outcome is CONVERGED and never WITHIN_SLA, so the gate below must
            # not test for WITHIN_SLA.
            soft_threshold_seconds=None,
            hard_timeout_seconds=hard_timeout_seconds,
            poll_interval_seconds=float(
                check_params.get("convergence_poll_interval_seconds", 10.0)
            ),
            stability_window_seconds=float(
                check_params.get("convergence_stability_window_seconds", 0.0)
            ),
            predicate_timeout_seconds=(
                float(predicate_timeout) if predicate_timeout is not None else None
            ),
        )

        attempt = last.get("attempt")
        if (
            result.outcome is not ConvergenceOutcome.NOT_CONVERGED
            and attempt is not None
        ):
            self.logger.info(
                f"BGP multipath baseline reached a steady state after "
                f"{result.attempts} polls ({result.convergence_time_seconds}s to "
                f"first satisfy, confirmed over the stability window)"
            )
            return attempt

        # Timed out. Report the last thing actually seen rather than a bare
        # timeout, and say how many polls errored -- last_observation is not
        # updated by an errored poll, so it can be stale without that count.
        reason = (
            f"BGP multipath baseline did not reach a steady state within "
            f"{hard_timeout_seconds}s ({result.attempts} polls, "
            f"{len(result.predicate_errors)} of them errored). "
            f"Last observation: {result.last_observation or 'none'}"
        )
        if attempt is None:
            return _DiscoveryAttempt(
                widths={},
                prefixes=set(),
                distribution_summary={},
                skipped_ibgp_count=0,
                not_ready_reason=reason,
            )
        return dataclasses.replace(attempt, not_ready_reason=reason)

    def _required_address_families(
        self, check_params: t.Dict[str, t.Any]
    ) -> t.Tuple[int, ...]:
        normalized = []
        for family in check_params.get("required_address_families", []):
            value = str(family).lower()
            if value not in {"ipv4", "ipv6"}:
                raise ValueError(f"unsupported required address family {family!r}")
            version = 4 if value == "ipv4" else 6
            if version not in normalized:
                normalized.append(version)
        return tuple(normalized)

    def _discover_by_afi(
        self,
        distribution: t.Dict[int, t.Set[str]],
        required_afis: t.Tuple[int, ...],
    ) -> t.Tuple[t.Dict[int, int], t.Set[str]]:
        widths: t.Dict[int, int] = {}
        prefixes: t.Set[str] = set()
        for afi in required_afis:
            family_distribution = {
                width: {
                    prefix
                    for prefix in candidates
                    if ipaddress.ip_network(prefix, strict=False).version == afi
                }
                for width, candidates in distribution.items()
            }
            family_distribution = {
                width: candidates
                for width, candidates in family_distribution.items()
                if candidates
            }
            if not family_distribution:
                raise _BaselineNotReady(f"no IPv{afi} multipath eBGP baseline prefixes")
            width, family_prefixes = max(
                family_distribution.items(), key=lambda item: len(item[1])
            )
            widths[afi] = width
            prefixes.update(family_prefixes)
        return widths, prefixes

    async def _measure_nexthop_distribution(
        self,
        check_params: t.Dict[str, t.Any],
    ) -> t.Tuple[t.Dict[int, t.Set[str]], int, int]:
        """
        Walk the BGP RIB and build the next-hop-count distribution as
        { width: set_of_prefixes }, restricted to multipath eBGP routes.

        Returns the distribution plus the iBGP/local and self-originated skip
        counts for diagnostic logging.
        """
        parent_prefixes_to_ignore = check_params.get("parent_prefixes_to_ignore", [])
        ebgp_only = check_params.get("ebgp_only", True)
        min_multipath_width = check_params.get("min_multipath_width", 2)

        # pyrefly: ignore [missing-attribute]
        bgp_rib_entries = await self.driver.async_get_bgp_rib_entries()
        self.logger.debug(f"Retrieved {len(bgp_rib_entries)} BGP++ RIB entries")

        # pyrefly: ignore [missing-attribute]
        bgp_originated_routes = await self.driver.async_get_bgp_originated_routes()
        bgp_originated_prefixes = {
            f"{ip_ntop(originated_route.prefix.prefix_bin)}/{originated_route.prefix.num_bits}"
            for originated_route in bgp_originated_routes
        }

        distribution: t.Dict[int, t.Set[str]] = {}
        skipped_ibgp_count = 0
        skipped_originated_count = 0
        sample_entries_logged = 0
        path_structure_logged = False

        for entry in bgp_rib_entries:
            ip_str = ip_ntop(entry.prefix.prefix_bin)
            prefix_str = f"{ip_str}/{entry.prefix.num_bits}"

            if prefix_str in bgp_originated_prefixes:
                skipped_originated_count += 1
                continue

            if any(
                is_parent_prefix(ip_str, parent_prefix)
                for parent_prefix in parent_prefixes_to_ignore
            ):
                continue

            if not path_structure_logged:
                self._log_path_structure_for_debugging(entry)
                path_structure_logged = True

            if ebgp_only and not self._is_ebgp_route(entry):
                skipped_ibgp_count += 1
                continue

            nexthop_count = self._count_nexthops(entry)
            if nexthop_count < min_multipath_width:
                continue

            distribution.setdefault(nexthop_count, set()).add(prefix_str)

            if sample_entries_logged < 5:
                self.logger.debug(
                    f"Sample eBGP prefix: {prefix_str}, nexthop_count={nexthop_count}"
                )
                sample_entries_logged += 1

        return distribution, skipped_ibgp_count, skipped_originated_count

    def _baseline_sanity_failures(
        self,
        discovered_width: int,
        check_params: t.Dict[str, t.Any],
    ) -> t.List[str]:
        """
        Fail loudly if the measured baseline width is implausible for the
        testbed (e.g., a regression from 32-way to 1-way). Returns the list of
        sanity-check failure messages (empty when the measurement is accepted).
        """
        expected_min_baseline_width = check_params.get("expected_min_baseline_width")
        expected_max_baseline_width = check_params.get("expected_max_baseline_width")
        # Legacy / sanity selector — if supplied, the measured width must match.
        legacy_baseline = check_params.get("baseline_nexthop_count")

        sanity_failures = []
        if (
            expected_min_baseline_width is not None
            and discovered_width < expected_min_baseline_width
        ):
            sanity_failures.append(
                f"measured width {discovered_width} < expected_min_baseline_width "
                f"{expected_min_baseline_width}"
            )
        if (
            expected_max_baseline_width is not None
            and discovered_width > expected_max_baseline_width
        ):
            sanity_failures.append(
                f"measured width {discovered_width} > expected_max_baseline_width "
                f"{expected_max_baseline_width}"
            )
        if legacy_baseline is not None and discovered_width != legacy_baseline:
            sanity_failures.append(
                f"measured width {discovered_width} != legacy "
                f"baseline_nexthop_count {legacy_baseline}"
            )
        return sanity_failures

    async def _run_validation_mode(
        self,
        obj: TestDevice,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        """
        Validation mode: Check that prefixes have the expected next-hop count.
        Uses discovered baseline prefixes if available, otherwise uses prefix_subnets.
        """
        prefix_subnets = check_params.get("prefix_subnets", [])
        parent_prefixes_to_ignore = check_params.get("parent_prefixes_to_ignore", [])
        expected_nexthop_count = check_params.get("expected_nexthop_count")
        min_nexthop_count = check_params.get("min_nexthop_count")
        max_nexthop_count = check_params.get("max_nexthop_count")
        sample_size = check_params.get("sample_size", 10)
        use_discovered_prefixes = check_params.get("use_discovered_prefixes", False)
        use_discovered_width = check_params.get("use_discovered_width", False)
        peers_stopped_delta = check_params.get("peers_stopped_delta", 0)
        discovered_prefixes, discovered_widths = (
            BgpMultipathNextHopCountHealthCheck._discovered_baselines.get(
                obj.name, (set(), {})
            )
        )

        # Width-relative validation: derive expected_nexthop_count from the
        # measured baseline. Lets reduce/restore checks read the live
        # measurement instead of recomputing from external constants.
        if use_discovered_width:
            if not discovered_widths:
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.FAIL,
                    message=("Validation failed: no baseline width discovered"),
                )
            if any(
                width - peers_stopped_delta < 0 for width in discovered_widths.values()
            ):
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.ERROR,
                    message=(
                        f"peers_stopped_delta ({peers_stopped_delta}) exceeds "
                        "a discovered baseline width "
                        f"({discovered_widths})"
                    ),
                )
            self.logger.info(
                "Width-relative expected next-hop counts = "
                f"{discovered_widths} - {peers_stopped_delta}"
            )

        # Get discovered prefixes if requested
        selected_discovered_prefixes = None
        if use_discovered_prefixes:
            if not discovered_prefixes:
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.FAIL,
                    message="Validation failed: no baseline prefixes have been discovered",
                )
            selected_discovered_prefixes = discovered_prefixes
            self.logger.debug(
                f"Using {len(discovered_prefixes)} discovered baseline prefixes"
            )

        # Validate that at least one validation criterion is provided
        if (
            not use_discovered_width
            and expected_nexthop_count is None
            and min_nexthop_count is None
            and max_nexthop_count is None
        ):
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.ERROR,
                message="At least one of expected_nexthop_count, min_nexthop_count, or max_nexthop_count must be provided",
            )

        try:
            # Get BGP++ RIB entries
            # pyrefly: ignore [missing-attribute]
            bgp_rib_entries = await self.driver.async_get_bgp_rib_entries()
            self.logger.debug(f"Retrieved {len(bgp_rib_entries)} BGP++ RIB entries")

            # Get self-originated prefixes to exclude
            # pyrefly: ignore [missing-attribute]
            bgp_originated_routes = await self.driver.async_get_bgp_originated_routes()
            bgp_originated_prefixes = {
                f"{ip_ntop(originated_route.prefix.prefix_bin)}/{originated_route.prefix.num_bits}"
                for originated_route in bgp_originated_routes
            }

            # Process BGP RIB entries and extract next-hop counts
            prefix_nexthop_counts = {}
            for entry in bgp_rib_entries:
                ip_str = ip_ntop(entry.prefix.prefix_bin)
                prefix_str = f"{ip_str}/{entry.prefix.num_bits}"

                # Skip self-originated prefixes
                if prefix_str in bgp_originated_prefixes:
                    continue

                # Skip parent prefixes to ignore
                if any(
                    is_parent_prefix(ip_str, parent_prefix)
                    for parent_prefix in parent_prefixes_to_ignore
                ):
                    continue

                # If using discovered prefixes, only check those
                if selected_discovered_prefixes is not None:
                    if prefix_str not in selected_discovered_prefixes:
                        continue
                # Otherwise, filter by specific prefix subnets if provided
                elif prefix_subnets and not self._matches_prefix_subnets(
                    ip_str, prefix_subnets
                ):
                    continue

                # Count next-hops
                nexthop_count = self._count_nexthops(entry)
                prefix_nexthop_counts[prefix_str] = nexthop_count

            if not prefix_nexthop_counts:
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.FAIL,
                    message="No matching prefixes found in BGP RIB",
                )

            if selected_discovered_prefixes is not None:
                missing_prefixes = sorted(
                    selected_discovered_prefixes - prefix_nexthop_counts.keys()
                )
                if missing_prefixes:
                    return hc_types.HealthCheckResult(
                        status=hc_types.HealthCheckStatus.FAIL,
                        message=(
                            "BGP multipath validation lost baseline prefixes: "
                            f"missing={len(missing_prefixes)}/"
                            f"{len(selected_discovered_prefixes)}, sample={missing_prefixes[:10]}"
                        ),
                    )
                if use_discovered_width:
                    required_versions = {
                        ipaddress.ip_network(prefix, strict=False).version
                        for prefix in selected_discovered_prefixes
                    }
                    missing_versions = sorted(
                        required_versions - discovered_widths.keys()
                    )
                    if missing_versions:
                        missing_afis = ", ".join(
                            f"IPv{version}" for version in missing_versions
                        )
                        return hc_types.HealthCheckResult(
                            status=hc_types.HealthCheckStatus.FAIL,
                            message=(
                                "BGP multipath validation has no discovered "
                                f"baseline width for {missing_afis}"
                            ),
                        )

            # Validate next-hop counts
            failures = []
            validated_count = 0
            sample_results = []

            for prefix, nexthop_count in prefix_nexthop_counts.items():
                is_valid = True
                failure_reason = None

                prefix_expected = expected_nexthop_count
                if use_discovered_width:
                    version = ipaddress.ip_network(prefix, strict=False).version
                    baseline_width = discovered_widths.get(version)
                    if baseline_width is None:
                        failures.append(
                            {
                                "prefix": prefix,
                                "reason": f"no IPv{version} baseline width",
                            }
                        )
                        continue
                    prefix_expected = baseline_width - peers_stopped_delta

                if prefix_expected is not None:
                    if nexthop_count != prefix_expected:
                        is_valid = False
                        failure_reason = (
                            f"expected exactly {prefix_expected}, got {nexthop_count}"
                        )

                if min_nexthop_count is not None and is_valid:
                    if nexthop_count < min_nexthop_count:
                        is_valid = False
                        failure_reason = f"expected at least {min_nexthop_count}, got {nexthop_count}"

                if max_nexthop_count is not None and is_valid:
                    if nexthop_count > max_nexthop_count:
                        is_valid = False
                        failure_reason = (
                            f"expected at most {max_nexthop_count}, got {nexthop_count}"
                        )

                if is_valid:
                    validated_count += 1
                else:
                    failures.append(
                        {
                            "prefix": prefix,
                            "reason": failure_reason
                            or "multipath validation failed without a reason",
                        }
                    )

                # Collect sample results for logging
                if len(sample_results) < sample_size:
                    sample_results.append(
                        {
                            "prefix": prefix,
                            "nexthop_count": nexthop_count,
                            "valid": is_valid,
                        }
                    )

            total_checked = len(prefix_nexthop_counts)

            if failures:
                # Limit number of failures to report
                failure_sample = failures[:10]
                error_details = "\n".join(
                    f"  - {f['prefix']}: {f['reason']}" for f in failure_sample
                )
                error_message = (
                    f"BGP multipath next-hop count check FAILED.\n"
                    f"  - Total prefixes checked: {total_checked}\n"
                    f"  - Failures: {len(failures)}\n"
                    f"  - Sample failures (first 10):\n{error_details}"
                )
                self.logger.error(error_message)
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.FAIL,
                    message=error_message,
                )

            # Build success message
            criteria = []
            if use_discovered_width:
                criteria.append(f"the per-AFI baseline minus {peers_stopped_delta}")
            elif expected_nexthop_count is not None:
                criteria.append(f"exactly {expected_nexthop_count}")
            if min_nexthop_count is not None:
                criteria.append(f"at least {min_nexthop_count}")
            if max_nexthop_count is not None:
                criteria.append(f"at most {max_nexthop_count}")

            success_message = (
                f"BGP multipath next-hop count check PASSED.\n"
                f"  - Total prefixes checked: {total_checked}\n"
                f"  - All prefixes have {' and '.join(criteria)} next-hops"
            )
            self.logger.info(success_message)
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.PASS,
                message=success_message,
            )

        except Exception as e:
            error_message = f"Error during BGP multipath next-hop count check: {str(e)}"
            self.logger.error(error_message)
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.ERROR,
                message=error_message,
            )

    def _count_nexthops(self, entry: t.Any) -> int:
        """Extract next-hop count from a BGP RIB entry's best group."""
        next_hops = []
        if hasattr(entry, "paths") and entry.paths and hasattr(entry, "best_group"):
            best_group = entry.best_group
            if best_group and best_group in entry.paths:
                for path in entry.paths[best_group]:
                    if hasattr(path, "next_hop") and path.next_hop:
                        next_hops.append(ip_ntop(path.next_hop.prefix_bin))
        return len(next_hops)

    def _is_ebgp_route(self, entry: t.Any) -> bool:
        """
        Check if a BGP RIB entry is an eBGP route.

        eBGP routes have a non-empty AS_PATH because the first AS in the path
        is the neighbor's AS. iBGP routes from the same AS may have an empty
        AS_PATH or only contain our own AS.

        Returns:
            True if any path in the best group has a non-empty AS_PATH (eBGP route),
            False otherwise (iBGP or local route).
        """
        if not hasattr(entry, "paths") or not entry.paths:
            return False

        if not hasattr(entry, "best_group") or not entry.best_group:
            return False

        best_group = entry.best_group
        if best_group not in entry.paths:
            return False

        # Check if any path in the best group has a non-empty AS_PATH
        for path in entry.paths[best_group]:
            # Try different attribute names that BGP++ might use for AS_PATH
            # Common variants: as_path, asPath, as_path_segments, aspath
            as_path_value = None
            for attr_name in ["as_path", "asPath", "as_path_segments", "aspath"]:
                if hasattr(path, attr_name):
                    as_path_value = getattr(path, attr_name)
                    if as_path_value:
                        return True

            # Also check for path_attributes dict-style access
            if hasattr(path, "path_attributes") and path.path_attributes:
                attrs = path.path_attributes
                for key in [
                    "as_path",
                    "asPath",
                    "AS_PATH",
                    "2",
                ]:  # 2 is AS_PATH type code
                    if key in attrs and attrs[key]:
                        return True

        return False

    def _matches_prefix_subnets(self, ip_str: str, prefix_subnets: t.List[str]) -> bool:
        """Check if IP address matches any of the specified prefix subnets"""
        try:
            ip_addr = ipaddress.ip_address(ip_str)
            for subnet_str in prefix_subnets:
                try:
                    subnet = ipaddress.ip_network(subnet_str, strict=False)
                    if ip_addr in subnet:
                        return True
                except ValueError:
                    continue
            return False
        except ValueError:
            return False

    def _log_path_structure_for_debugging(self, entry: t.Any) -> None:
        """
        Log the structure of a BGP RIB entry for debugging purposes.
        This helps identify the correct attribute names for AS_PATH and other fields.
        """
        try:
            prefix_str = "unknown"
            try:
                ip_str = ip_ntop(entry.prefix.prefix_bin)
                prefix_str = f"{ip_str}/{entry.prefix.num_bits}"
            except Exception:
                pass

            self.logger.info(f"[DEBUG] Sample RIB entry structure for {prefix_str}:")

            # Log entry-level attributes
            try:
                entry_attrs = [attr for attr in dir(entry) if not attr.startswith("_")]
                self.logger.info(
                    f"[DEBUG] Entry attributes: {entry_attrs[:20]}"
                )  # Limit to first 20
            except Exception as e:
                self.logger.info(f"[DEBUG] Could not get entry attributes: {e}")

            if hasattr(entry, "paths") and entry.paths:
                try:
                    self.logger.info(
                        f"[DEBUG] paths keys: {list(entry.paths.keys())[:5]}"
                    )  # Limit to first 5
                except Exception as e:
                    self.logger.info(f"[DEBUG] Could not get paths keys: {e}")

                if hasattr(entry, "best_group") and entry.best_group:
                    best_group = entry.best_group
                    self.logger.info(f"[DEBUG] best_group: {best_group}")

                    if best_group in entry.paths:
                        try:
                            paths = entry.paths[best_group]
                            self.logger.info(
                                f"[DEBUG] Number of paths in best_group: {len(paths)}"
                            )

                            if paths:
                                first_path = paths[0]
                                try:
                                    path_attrs = [
                                        attr
                                        for attr in dir(first_path)
                                        if not attr.startswith("_")
                                    ]
                                    self.logger.info(
                                        f"[DEBUG] First path attributes: {path_attrs[:30]}"  # Limit to first 30
                                    )
                                except Exception as e:
                                    self.logger.info(
                                        f"[DEBUG] Could not get path attributes: {e}"
                                    )

                                # Log specific AS_PATH related attributes
                                for attr_name in [
                                    "as_path",
                                    "asPath",
                                    "as_path_segments",
                                    "aspath",
                                    "path_attributes",
                                    "peer_as",
                                    "source_as",
                                ]:
                                    try:
                                        if hasattr(first_path, attr_name):
                                            attr_value = getattr(first_path, attr_name)
                                            # Truncate long values
                                            str_value = str(attr_value)[:200]
                                            self.logger.info(
                                                f"[DEBUG] {attr_name} = {str_value} (type: {type(attr_value).__name__})"
                                            )
                                    except Exception as e:
                                        self.logger.info(
                                            f"[DEBUG] Error reading {attr_name}: {e}"
                                        )
                        except Exception as e:
                            self.logger.info(f"[DEBUG] Error accessing paths: {e}")
        except Exception as e:
            self.logger.warning(f"[DEBUG] Error logging path structure: {e}")
