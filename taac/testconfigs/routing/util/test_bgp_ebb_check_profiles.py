# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
import json
import unittest

from taac.health_checks.healthcheck_definitions import (
    create_bgp_convergence_check,
    create_bgp_rib_fib_consistency_check,
    create_bgp_route_count_verification_check,
    create_bgp_session_establish_check,
    create_core_dumps_snapshot_check,
)
from taac.health_checks.retry_policy import (
    DEFAULT_RETRY_SPEC,
    get_retry_kwargs,
)
from taac.testconfigs.routing.util.bgp_ebb_check_profiles import (
    CheckProfile,
    get_profile_checks,
    ProfileChecks,
    ProfileContext,
)
from taac.testconfigs.routing.util.bgp_ebb_health_checks import (
    bgp_mon_ignore_prefix,
    BgpMonScope,
    create_standard_postchecks,
    create_standard_prechecks,
    create_standard_snapshot_checks,
)
from taac.health_check.health_check import types as hc_types

# The prefix a default (ixia11) BgpMonScope resolves to.
DEFAULT_BGP_MON_PREFIX = bgp_mon_ignore_prefix()


def _ignored_parent_prefixes(checks) -> list[str]:
    """Collect every ``parent_prefixes_to_ignore`` entry across a phase's checks.

    Reads the serialized params rather than the factory kwargs, so the
    assertion survives a reshaping of how the scope is plumbed through.

    Args:
        checks: The resolved checks for one phase (pre, post or snapshot).

    Returns:
        Every ignored parent prefix found, in check order (may repeat when
        several checks in the phase ignore the same prefix).
    """
    prefixes: list[str] = []
    for check in checks:
        params = getattr(check, "check_params", None)
        raw = getattr(params, "json_params", None) if params else None
        if not raw:
            continue
        prefixes.extend(json.loads(raw).get("parent_prefixes_to_ignore", []))
    return prefixes


class CheckProfileRegistryTest(unittest.TestCase):
    def test_bounded_ecmp_profile_shape(self):
        checks = get_profile_checks(
            CheckProfile.PERF_SCALING_BOUNDED_ECMP, ProfileContext()
        )

        self.assertIsInstance(checks, ProfileChecks)
        # No prechecks for this profile (matches the prior inline playbook).
        self.assertEqual(checks.prechecks, [])
        # Postchecks: session establish, RIB/FIB consistency, convergence.
        self.assertEqual(
            [c.name for c in checks.postchecks],
            [
                hc_types.CheckName.BGP_SESSION_ESTABLISH_CHECK,
                hc_types.CheckName.BGP_RIB_FIB_CONSISTENCY_CHECK,
                hc_types.CheckName.BGP_CONVERGENCE_CHECK,
            ],
        )
        # Snapshot: core dumps + bgp session snapshot.
        self.assertEqual(len(checks.snapshot_checks), 2)
        self.assertEqual(
            checks.snapshot_checks[0].name, hc_types.CheckName.CORE_DUMPS_CHECK
        )

    def test_retry_is_baked_from_ssot(self):
        # Every postcheck must carry the uniform SSOT retry spec (P1/P3): the
        # profile never hand-passes retry numbers.
        checks = get_profile_checks(
            CheckProfile.PERF_SCALING_BOUNDED_ECMP, ProfileContext()
        )

        for check in checks.postchecks:
            self.assertIsNotNone(check.check_params)
            payload = json.loads(check.check_params.json_params)
            self.assertEqual(payload["retry_count"], DEFAULT_RETRY_SPEC.retry_count)
            self.assertEqual(
                payload["retry_delay_seconds"],
                DEFAULT_RETRY_SPEC.retry_delay_seconds,
            )
            self.assertEqual(
                payload["retry_delay_multiplier"],
                DEFAULT_RETRY_SPEC.retry_delay_multiplier,
            )

    def test_convergence_functional_params_are_explicit(self):
        # Functional params (per check, phase) are explicit/visible in the
        # profile — the "change and look" property.
        checks = get_profile_checks(
            CheckProfile.PERF_SCALING_BOUNDED_ECMP, ProfileContext()
        )

        convergence = next(
            c
            for c in checks.postchecks
            if c.name == hc_types.CheckName.BGP_CONVERGENCE_CHECK
        )
        payload = json.loads(convergence.check_params.json_params)
        self.assertEqual(payload["convergence_threshold"], 600)
        self.assertEqual(payload["fail_on_eor_expired"], True)
        self.assertEqual(convergence.check_id, "postcheck_bgp_convergence_time")

    def test_each_call_returns_fresh_objects(self):
        # Thrift structs are mutable; callers must not share instances.
        first = get_profile_checks(
            CheckProfile.PERF_SCALING_BOUNDED_ECMP, ProfileContext()
        )
        second = get_profile_checks(
            CheckProfile.PERF_SCALING_BOUNDED_ECMP, ProfileContext()
        )

        self.assertIsNot(first.postchecks[0], second.postchecks[0])

    def test_unknown_profile_raises(self):
        with self.assertRaises(ValueError):
            get_profile_checks("not_a_real_profile", ProfileContext())

    def test_default_cpu_baseline_matches_standard_playbooks(self):
        # cpu_baseline is consumed only by the standard-shape profiles, whose
        # playbook entry points default to 8.0. An empty ProfileContext() built
        # for one of those profiles must therefore get 8.0, not the factory 4.0.
        self.assertEqual(ProfileContext().cpu_baseline, 8.0)

    # --- Standard-shape profiles: parity with the create_standard_* factories ---

    def test_daemon_restart_matches_factory(self):
        """DAEMON_RESTART reproduces the exact create_standard_* calls the
        bgp_daemon_restart playbook used before migration (parity-first)."""
        ctx = ProfileContext(
            peergroup_ibgp_v6="PG_IBGP_V6",
            peergroup_ibgp_v4="PG_IBGP_V4",
            cpu_baseline=8.0,
            check_ibgp_pnh=False,
            expected_peer_identity={"2401:db00::a": "2401:db00::b"},
            parent_prefixes_to_ignore=["10.0.0.0/24"],
            expected_established_sessions=42,
            bgp_mon=BgpMonScope(exclude=True),
        )
        checks = get_profile_checks(CheckProfile.DAEMON_RESTART, ctx)

        self.assertEqual(
            checks.prechecks,
            create_standard_prechecks(
                peergroup_ibgp_v6="PG_IBGP_V6",
                peergroup_ibgp_v4="PG_IBGP_V4",
                precheck_thresholds=None,
                expected_established_sessions=42,
                cpu_baseline=8.0,
                check_ibgp_pnh=False,
                bgp_mon=BgpMonScope(exclude=True),
            ),
        )
        self.assertEqual(
            checks.postchecks,
            create_standard_postchecks(
                postcheck_thresholds=None,
                convergence_hard_timeout_seconds=1200,
                expected_established_session_count=42,
                expected_restarted_services=["Bgp"],
                restart_start_time_jq_var="daemon_restart_time",
                bgp_mon=BgpMonScope(exclude=True),
            ),
        )
        self.assertEqual(
            checks.snapshot_checks,
            create_standard_snapshot_checks(
                skip_flap_check=True,
                skip_uptime_check=True,
                expected_peer_identity={"2401:db00::a": "2401:db00::b"},
                parent_prefixes_to_ignore=["10.0.0.0/24"],
                bgp_mon=BgpMonScope(exclude=True),
            ),
        )

    def test_cold_start_matches_factory(self):
        """COLD_START reproduces the exact create_standard_* calls the
        bgp_cold_start playbook used before migration (EOR tolerated, full
        snapshot)."""
        ctx = ProfileContext(
            peergroup_ibgp_v6="PG_IBGP_V6",
            peergroup_ibgp_v4="PG_IBGP_V4",
            cpu_baseline=8.0,
            check_ibgp_pnh=False,
            expected_peer_identity={"2401:db00::a": "2401:db00::b"},
            expected_established_sessions=42,
            bgp_mon=BgpMonScope(exclude=True),
            fail_on_eor_expired=False,
        )
        checks = get_profile_checks(CheckProfile.COLD_START, ctx)

        self.assertEqual(
            checks.prechecks,
            create_standard_prechecks(
                peergroup_ibgp_v6="PG_IBGP_V6",
                peergroup_ibgp_v4="PG_IBGP_V4",
                precheck_thresholds=None,
                cpu_baseline=8.0,
                check_ibgp_pnh=False,
                bgp_mon=BgpMonScope(exclude=True),
            ),
        )
        self.assertEqual(
            checks.postchecks,
            create_standard_postchecks(
                postcheck_thresholds=None,
                convergence_hard_timeout_seconds=1200,
                fail_on_eor_expired=False,
                expected_established_session_count=42,
                expected_restarted_services=["Bgp"],
                restart_start_time_jq_var="daemon_restart_time",
                bgp_mon=BgpMonScope(exclude=True),
            ),
        )
        self.assertEqual(
            checks.snapshot_checks,
            create_standard_snapshot_checks(
                expected_peer_identity={"2401:db00::a": "2401:db00::b"},
                bgp_mon=BgpMonScope(exclude=True),
            ),
        )

    def test_oscillation_with_skips_matches_factory(self):
        """OSCILLATION with both snapshot skips reproduces the session/tornado
        oscillation playbooks' create_standard_* calls (conv OFF)."""
        ctx = ProfileContext(
            peergroup_ibgp_v6="PG_IBGP_V6",
            peergroup_ibgp_v4="PG_IBGP_V4",
            expected_established_sessions=42,
            cpu_baseline=8.0,
            check_ibgp_pnh=False,
            expected_peer_identity={"2401:db00::a": "2401:db00::b"},
            parent_prefixes_to_ignore=["10.0.0.0/24"],
            bgp_mon=BgpMonScope(exclude=True),
            snapshot_skip_flap=True,
            snapshot_skip_uptime=True,
        )
        checks = get_profile_checks(CheckProfile.OSCILLATION, ctx)

        self.assertEqual(
            checks.prechecks,
            create_standard_prechecks(
                peergroup_ibgp_v6="PG_IBGP_V6",
                peergroup_ibgp_v4="PG_IBGP_V4",
                precheck_thresholds=None,
                expected_established_sessions=42,
                cpu_baseline=8.0,
                check_ibgp_pnh=False,
                bgp_mon=BgpMonScope(exclude=True),
            ),
        )
        self.assertEqual(
            checks.postchecks,
            create_standard_postchecks(
                postcheck_thresholds=None,
                check_bgp_convergence=False,
                bgp_mon=BgpMonScope(exclude=True),
            ),
        )
        self.assertEqual(
            checks.snapshot_checks,
            create_standard_snapshot_checks(
                skip_flap_check=True,
                skip_uptime_check=True,
                expected_peer_identity={"2401:db00::a": "2401:db00::b"},
                parent_prefixes_to_ignore=["10.0.0.0/24"],
                bgp_mon=BgpMonScope(exclude=True),
            ),
        )

    def test_oscillation_no_skips_matches_factory(self):
        """OSCILLATION with no snapshot skips reproduces the ibgp_route
        oscillation playbook's snapshot."""
        ctx = ProfileContext(
            peergroup_ibgp_v6="PG_IBGP_V6",
            peergroup_ibgp_v4="PG_IBGP_V4",
            cpu_baseline=8.0,
            bgp_mon=BgpMonScope(exclude=True),
        )
        checks = get_profile_checks(CheckProfile.OSCILLATION, ctx)

        self.assertEqual(
            checks.snapshot_checks,
            create_standard_snapshot_checks(
                expected_peer_identity=None,
                bgp_mon=BgpMonScope(exclude=True),
            ),
        )

    def test_drain_undrain_matches_factory(self):
        """DRAIN_UNDRAIN reproduces the fauu/plane drain playbooks' calls
        (iBGP-PNH off, convergence OFF, snapshot skips flap only)."""
        ctx = ProfileContext(
            peergroup_ibgp_v6="PG_IBGP_V6",
            peergroup_ibgp_v4="PG_IBGP_V4",
            expected_established_sessions=12,
            bgp_mon=BgpMonScope(exclude=True),
        )
        checks = get_profile_checks(CheckProfile.DRAIN_UNDRAIN, ctx)

        self.assertEqual(
            checks.prechecks,
            create_standard_prechecks(
                peergroup_ibgp_v6="PG_IBGP_V6",
                peergroup_ibgp_v4="PG_IBGP_V4",
                expected_established_sessions=12,
                check_ibgp_pnh=False,
                bgp_mon=BgpMonScope(exclude=True),
            ),
        )
        self.assertEqual(
            checks.postchecks,
            create_standard_postchecks(
                check_bgp_convergence=False,
                bgp_mon=BgpMonScope(exclude=True),
            ),
        )
        self.assertEqual(
            checks.snapshot_checks,
            create_standard_snapshot_checks(
                skip_flap_check=True,
                bgp_mon=BgpMonScope(exclude=True),
            ),
        )

    def test_churn_storm_route_storm_matches_factory(self):
        """CICD-EBB-11 uses final session checks and in-workflow stability gates."""
        ctx = ProfileContext(
            peergroup_ibgp_v6="PG_IBGP_V6",
            peergroup_ibgp_v4="PG_IBGP_V4",
            expected_established_sessions=42,
            check_cpu_load_average=False,
            check_ibgp_pnh=True,
            bgp_mon=BgpMonScope(exclude=True),
        )
        checks = get_profile_checks(CheckProfile.CHURN_STORM, ctx)

        self.assertEqual(
            checks.prechecks,
            create_standard_prechecks(
                peergroup_ibgp_v6="PG_IBGP_V6",
                peergroup_ibgp_v4="PG_IBGP_V4",
                expected_established_sessions=42,
                check_cpu_load_average=False,
                check_ibgp_pnh=True,
                bgp_mon=BgpMonScope(exclude=True),
            ),
        )
        self.assertEqual(
            checks.postchecks,
            create_standard_postchecks(
                check_bgp_convergence=False,
                expected_established_session_count=42,
                bgp_mon=BgpMonScope(exclude=True),
            ),
        )
        # Core-dumps ONLY — no bgp-session snapshot for this profile.
        self.assertEqual(
            checks.snapshot_checks,
            [create_core_dumps_snapshot_check()],
        )

    def test_churn_storm_supports_attribute_churn_full_session_snapshot(self):
        ctx = ProfileContext(
            peergroup_ibgp_v6="PG_IBGP_V6",
            peergroup_ibgp_v4="PG_IBGP_V4",
            expected_established_sessions=42,
            check_ibgp_pnh=True,
            expected_peer_identity={"2401:db00::a": "2401:db00::b"},
            parent_prefixes_to_ignore=["10.0.0.0/24"],
            bgp_mon=BgpMonScope(exclude=True),
            full_session_snapshot=True,
        )

        checks = get_profile_checks(CheckProfile.CHURN_STORM, ctx)

        self.assertEqual(
            checks.prechecks,
            create_standard_prechecks(
                peergroup_ibgp_v6="PG_IBGP_V6",
                peergroup_ibgp_v4="PG_IBGP_V4",
                expected_established_sessions=42,
                check_ibgp_pnh=True,
                bgp_mon=BgpMonScope(exclude=True),
            ),
        )
        self.assertEqual(
            checks.postchecks,
            create_standard_postchecks(
                check_bgp_convergence=False,
                expected_established_session_count=42,
                bgp_mon=BgpMonScope(exclude=True),
            ),
        )
        self.assertEqual(
            checks.snapshot_checks,
            create_standard_snapshot_checks(
                expected_peer_identity={"2401:db00::a": "2401:db00::b"},
                parent_prefixes_to_ignore=["10.0.0.0/24"],
                bgp_mon=BgpMonScope(exclude=True),
            ),
        )

    def test_igp_instability_pnh_metric_matches_factory(self):
        """PNH metric oscillation relies on session snapshots and postchecks."""
        ctx = ProfileContext(
            peergroup_ibgp_v6="PG_IBGP_V6",
            peergroup_ibgp_v4="PG_IBGP_V4",
            expected_established_sessions=42,
            cpu_baseline=8.0,
            check_ibgp_pnh=False,
            expected_peer_identity={"2401:db00::a": "2401:db00::b"},
            bgp_mon=BgpMonScope(exclude=True),
        )
        checks = get_profile_checks(CheckProfile.IGP_INSTABILITY, ctx)

        self.assertEqual(
            checks.prechecks,
            create_standard_prechecks(
                peergroup_ibgp_v6="PG_IBGP_V6",
                peergroup_ibgp_v4="PG_IBGP_V4",
                expected_established_sessions=42,
                cpu_baseline=8.0,
                check_ibgp_pnh=False,
                bgp_mon=BgpMonScope(exclude=True),
            ),
        )
        self.assertEqual(
            checks.postchecks,
            create_standard_postchecks(
                check_bgp_convergence=False,
                bgp_mon=BgpMonScope(exclude=True),
            ),
        )
        self.assertEqual(
            checks.snapshot_checks,
            create_standard_snapshot_checks(
                expected_peer_identity={"2401:db00::a": "2401:db00::b"},
                bgp_mon=BgpMonScope(exclude=True),
            ),
        )

    def test_igp_instability_unresolvable_pnhs_matches_factory(self):
        """Unresolvable-PNHs validates BGP++ UPDATE sends in its stage."""
        ctx = ProfileContext(
            peergroup_ibgp_v6="PG_IBGP_V6",
            peergroup_ibgp_v4="PG_IBGP_V4",
            expected_established_sessions=42,
            cpu_baseline=8.0,
            check_ibgp_pnh=False,
            expected_peer_identity={"2401:db00::a": "2401:db00::b"},
            bgp_mon=BgpMonScope(exclude=True),
        )
        checks = get_profile_checks(CheckProfile.IGP_INSTABILITY, ctx)

        self.assertEqual(
            checks.postchecks,
            create_standard_postchecks(
                check_bgp_convergence=False,
                bgp_mon=BgpMonScope(exclude=True),
            ),
        )

    def test_soak_readiness_gated_nexthop_matches_factory(self):
        """CICD-EBB-16 blocks stimulus on sessions, EOR, routes, and RIB/FIB."""
        ctx = ProfileContext(
            check_bgp_convergence=True,
            convergence_threshold=600,
            expected_established_sessions=1272,
            route_count_expected=750,
            bgp_mon=BgpMonScope(
                exclude=True,
                parent_network="2401:db00:e50d:22:a",
            ),
        )
        checks = get_profile_checks(CheckProfile.SOAK_READINESS_GATED, ctx)

        self.assertEqual(
            checks.prechecks,
            [
                create_bgp_session_establish_check(
                    expected_established_sessions_static=1272,
                    parent_prefixes_to_ignore=["2401:db00:e50d:22:a::/80"],
                    check_id="startup_bgp_session_verification",
                    **get_retry_kwargs(hc_types.CheckName.BGP_SESSION_ESTABLISH_CHECK),
                ),
                create_bgp_convergence_check(
                    convergence_threshold=600,
                    hard_timeout_seconds=600,
                    stability_window_seconds=30.0,
                    fail_on_eor_expired=False,
                    validate_sequence=False,
                    extra_json_params={"start_event": "3", "end_event": "4"},
                    check_id="startup_all_eor_received",
                ),
                create_bgp_route_count_verification_check(
                    json_params={
                        "exact_peer_group_names": ["EB-FA-V6", "EB-FA-V4"],
                        "direction": "received",
                        "expected_count": 750,
                        "policy_type": "post_policy",
                    },
                    check_id="startup_bgp_route_count_verification",
                ),
                create_bgp_rib_fib_consistency_check(
                    check_id="rib_fib_consistency_precheck",
                    **get_retry_kwargs(
                        hc_types.CheckName.BGP_RIB_FIB_CONSISTENCY_CHECK
                    ),
                ),
            ],
        )
        self.assertEqual(
            checks.postchecks,
            create_standard_postchecks(
                convergence_threshold=600,
                fail_on_eor_expired=False,
                expected_established_session_count=1272,
                bgp_mon=BgpMonScope(
                    exclude=True,
                    parent_network="2401:db00:e50d:22:a",
                ),
            ),
        )
        self.assertEqual(
            checks.snapshot_checks,
            create_standard_snapshot_checks(
                skip_flap_check=True,
                skip_uptime_check=True,
                bgp_mon=BgpMonScope(
                    exclude=True,
                    parent_network="2401:db00:e50d:22:a",
                ),
            ),
        )

    def test_runtime_update_matches_factory(self):
        """RUNTIME_UPDATE reproduces the route-registry prefix-list runtime-update
        playbook (standard prechecks + a route-count verification add-on,
        postchecks convergence ON but EOR tolerated)."""
        ctx = ProfileContext(
            peergroup_ibgp_v6="PG_IBGP_V6",
            peergroup_ibgp_v4="PG_IBGP_V4",
            cpu_baseline=6.0,
            expected_established_sessions=42,
            check_ibgp_pnh=False,
            bgp_mon=BgpMonScope(exclude=True),
            route_count_expected=650,
        )
        checks = get_profile_checks(CheckProfile.RUNTIME_UPDATE, ctx)

        self.assertEqual(
            checks.prechecks,
            create_standard_prechecks(
                peergroup_ibgp_v6="PG_IBGP_V6",
                peergroup_ibgp_v4="PG_IBGP_V4",
                cpu_baseline=6.0,
                expected_established_sessions=42,
                check_ibgp_pnh=False,
                bgp_mon=BgpMonScope(exclude=True),
            )
            + [
                create_bgp_route_count_verification_check(
                    json_params={
                        "exact_peer_group_names": ["EB-FA-V6", "EB-FA-V4"],
                        "direction": "received",
                        "expected_count": 650,
                        "policy_type": "post_policy",
                    },
                    check_id="startup_bgp_session_verification",
                ),
            ],
        )
        self.assertEqual(
            checks.postchecks,
            create_standard_postchecks(
                fail_on_eor_expired=False,
                bgp_mon=BgpMonScope(exclude=True),
            ),
        )
        self.assertEqual(
            checks.snapshot_checks,
            create_standard_snapshot_checks(
                bgp_mon=BgpMonScope(exclude=True),
            ),
        )

    def test_runtime_update_omits_unset_exact_session_count(self):
        checks = get_profile_checks(
            CheckProfile.RUNTIME_UPDATE,
            ProfileContext(
                peergroup_ibgp_v6="PG_IBGP_V6",
                peergroup_ibgp_v4="PG_IBGP_V4",
                expected_established_sessions=0,
                route_count_expected=650,
            ),
        )

        self.assertEqual(
            checks.prechecks,
            create_standard_prechecks(
                peergroup_ibgp_v6="PG_IBGP_V6",
                peergroup_ibgp_v4="PG_IBGP_V4",
                cpu_baseline=8.0,
                expected_established_sessions=None,
            )
            + [
                create_bgp_route_count_verification_check(
                    json_params={
                        "exact_peer_group_names": ["EB-FA-V6", "EB-FA-V4"],
                        "direction": "received",
                        "expected_count": 650,
                        "policy_type": "post_policy",
                    },
                    check_id="startup_bgp_session_verification",
                ),
            ],
        )

    def test_soak_no_precheck_longevity_matches_factory(self):
        """SOAK_NO_PRECHECK with convergence OFF reproduces the longevity-soak
        playbook (no prechecks, no convergence postcheck, snapshot skips flap +
        uptime)."""
        ctx = ProfileContext(
            check_bgp_convergence=False,
            bgp_mon=BgpMonScope(exclude=True),
        )
        checks = get_profile_checks(CheckProfile.SOAK_NO_PRECHECK, ctx)

        self.assertEqual(checks.prechecks, [])
        self.assertEqual(
            checks.postchecks,
            create_standard_postchecks(
                check_bgp_convergence=False,
                bgp_mon=BgpMonScope(exclude=True),
            ),
        )
        self.assertEqual(
            checks.snapshot_checks,
            create_standard_snapshot_checks(
                skip_flap_check=True,
                skip_uptime_check=True,
                bgp_mon=BgpMonScope(exclude=True),
            ),
        )

    def test_secondary_chassis_reaches_every_standard_phase(self):
        """A non-default BGP-MON chassis must reach the pre, post AND snapshot
        checks of every standard-shape profile.

        This is the regression that motivated binding the exclusion flag and the
        parent network into one ``BgpMonScope``: when they were two independent
        kwargs, ``_soak_no_precheck`` threaded ``exclude_bgp_mon`` into its
        postchecks but not the parent network, so those postchecks silently
        excluded the default chassis' prefix instead of the configured one. It
        was latent only because no config paired that profile with a secondary
        chassis. Asserting on the resolved prefix (not on the kwargs) keeps the
        guarantee even if the plumbing is reshaped again.
        """
        secondary = "2401:db00:eeee:e80d:33"
        expected_prefix = f"{secondary}::/80"
        ctx = ProfileContext(
            peergroup_ibgp_v6="EB-FA-V6",
            peergroup_ibgp_v4="EB-FA-V4",
            expected_established_sessions=1272,
            route_count_expected=750,
            bgp_mon=BgpMonScope(exclude=True, parent_network=secondary),
        )

        # The bounded-ECMP characteristic profiles are the exception, and both
        # for the same reason: their playbooks build them from a bare
        # `ProfileContext()`, so no BGP-MON chassis is ever configured for the
        # checks to thread. They scope to the eBGP population via
        # IBGP_MIMIC_PARENTS instead, which is why their phases DO carry ignored
        # parent prefixes and so cannot simply be skipped by the `not ignored`
        # guard below. Every other profile is standard-shape and must honour a
        # configured secondary chassis.
        bounded_ecmp_profiles = {
            CheckProfile.PERF_SCALING_BOUNDED_ECMP,
            CheckProfile.SC9_BOUNDED_ECMP,
        }
        standard_profiles = [p for p in CheckProfile if p not in bounded_ecmp_profiles]
        for profile in standard_profiles:
            with self.subTest(profile=profile):
                checks = get_profile_checks(profile, ctx)
                phases = {
                    "prechecks": checks.prechecks,
                    "postchecks": checks.postchecks,
                    "snapshot_checks": checks.snapshot_checks,
                }
                for phase_name, phase_checks in phases.items():
                    ignored = _ignored_parent_prefixes(phase_checks)
                    if not ignored:
                        # Phases that legitimately carry no session check (e.g.
                        # SOAK_NO_PRECHECK has no prechecks at all).
                        continue
                    self.assertIn(
                        expected_prefix,
                        ignored,
                        f"{profile} {phase_name} ignores {ignored}, not the "
                        f"configured secondary chassis {expected_prefix}",
                    )
                    self.assertNotIn(
                        DEFAULT_BGP_MON_PREFIX,
                        ignored,
                        f"{profile} {phase_name} still ignores the default "
                        f"chassis prefix despite a secondary chassis",
                    )
