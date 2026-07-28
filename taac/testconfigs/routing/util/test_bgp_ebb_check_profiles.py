# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
import json
import unittest

from taac.health_checks.healthcheck_definitions import (
    create_bgp_route_count_verification_check,
    create_core_dumps_snapshot_check,
)
from taac.health_checks.retry_policy import DEFAULT_RETRY_SPEC
from taac.testconfigs.routing.util.bgp_ebb_check_profiles import (
    CheckProfile,
    get_profile_checks,
    ProfileChecks,
    ProfileContext,
)
from taac.testconfigs.routing.util.bgp_ebb_health_checks import (
    create_standard_postchecks,
    create_standard_prechecks,
    create_standard_snapshot_checks,
)
from taac.health_check.health_check import types as hc_types


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
            exclude_bgp_mon=True,
        )
        checks = get_profile_checks(CheckProfile.DAEMON_RESTART, ctx)

        self.assertEqual(
            checks.prechecks,
            create_standard_prechecks(
                peergroup_ibgp_v6="PG_IBGP_V6",
                peergroup_ibgp_v4="PG_IBGP_V4",
                precheck_thresholds=None,
                cpu_baseline=8.0,
                check_ibgp_pnh=False,
                exclude_bgp_mon=True,
            ),
        )
        self.assertEqual(
            checks.postchecks,
            create_standard_postchecks(
                postcheck_thresholds=None,
                expected_restarted_services=["Bgp"],
                restart_start_time_jq_var="daemon_restart_time",
                exclude_bgp_mon=True,
            ),
        )
        self.assertEqual(
            checks.snapshot_checks,
            create_standard_snapshot_checks(
                skip_uptime_check=True,
                expected_peer_identity={"2401:db00::a": "2401:db00::b"},
                parent_prefixes_to_ignore=["10.0.0.0/24"],
                exclude_bgp_mon=True,
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
            exclude_bgp_mon=True,
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
                exclude_bgp_mon=True,
            ),
        )
        self.assertEqual(
            checks.postchecks,
            create_standard_postchecks(
                postcheck_thresholds=None,
                fail_on_eor_expired=False,
                expected_restarted_services=["Bgp"],
                restart_start_time_jq_var="daemon_restart_time",
                exclude_bgp_mon=True,
            ),
        )
        self.assertEqual(
            checks.snapshot_checks,
            create_standard_snapshot_checks(
                expected_peer_identity={"2401:db00::a": "2401:db00::b"},
                exclude_bgp_mon=True,
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
            exclude_bgp_mon=True,
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
                exclude_bgp_mon=True,
            ),
        )
        self.assertEqual(
            checks.postchecks,
            create_standard_postchecks(
                postcheck_thresholds=None,
                check_bgp_convergence=False,
                exclude_bgp_mon=True,
            ),
        )
        self.assertEqual(
            checks.snapshot_checks,
            create_standard_snapshot_checks(
                skip_flap_check=True,
                skip_uptime_check=True,
                expected_peer_identity={"2401:db00::a": "2401:db00::b"},
                parent_prefixes_to_ignore=["10.0.0.0/24"],
                exclude_bgp_mon=True,
            ),
        )

    def test_oscillation_no_skips_matches_factory(self):
        """OSCILLATION with no snapshot skips reproduces the ibgp_route
        oscillation playbook's snapshot."""
        ctx = ProfileContext(
            peergroup_ibgp_v6="PG_IBGP_V6",
            peergroup_ibgp_v4="PG_IBGP_V4",
            cpu_baseline=8.0,
            exclude_bgp_mon=True,
        )
        checks = get_profile_checks(CheckProfile.OSCILLATION, ctx)

        self.assertEqual(
            checks.snapshot_checks,
            create_standard_snapshot_checks(
                expected_peer_identity=None,
                exclude_bgp_mon=True,
            ),
        )

    def test_drain_undrain_matches_factory(self):
        """DRAIN_UNDRAIN reproduces the fauu/plane drain playbooks' calls
        (iBGP-PNH off, convergence OFF, snapshot skips flap only)."""
        ctx = ProfileContext(
            peergroup_ibgp_v6="PG_IBGP_V6",
            peergroup_ibgp_v4="PG_IBGP_V4",
            expected_established_sessions=12,
            exclude_bgp_mon=True,
        )
        checks = get_profile_checks(CheckProfile.DRAIN_UNDRAIN, ctx)

        self.assertEqual(
            checks.prechecks,
            create_standard_prechecks(
                peergroup_ibgp_v6="PG_IBGP_V6",
                peergroup_ibgp_v4="PG_IBGP_V4",
                expected_established_sessions=12,
                check_ibgp_pnh=False,
                exclude_bgp_mon=True,
            ),
        )
        self.assertEqual(
            checks.postchecks,
            create_standard_postchecks(
                check_bgp_convergence=False,
                exclude_bgp_mon=True,
            ),
        )
        self.assertEqual(
            checks.snapshot_checks,
            create_standard_snapshot_checks(
                skip_flap_check=True,
                exclude_bgp_mon=True,
            ),
        )

    def test_churn_storm_attribute_matches_factory(self):
        """CHURN_STORM with no rib_fib_json_params reproduces the bag010
        attribute-churn playbook (convergence OFF, expected session count
        enforced, core-dumps-ONLY snapshot)."""
        ctx = ProfileContext(
            peergroup_ibgp_v6="PG_IBGP_V6",
            peergroup_ibgp_v4="PG_IBGP_V4",
            expected_established_sessions=42,
            check_ibgp_pnh=True,
            exclude_bgp_mon=True,
        )
        checks = get_profile_checks(CheckProfile.CHURN_STORM, ctx)

        self.assertEqual(
            checks.prechecks,
            create_standard_prechecks(
                peergroup_ibgp_v6="PG_IBGP_V6",
                peergroup_ibgp_v4="PG_IBGP_V4",
                expected_established_sessions=42,
                check_ibgp_pnh=True,
                exclude_bgp_mon=True,
            ),
        )
        self.assertEqual(
            checks.postchecks,
            create_standard_postchecks(
                check_bgp_convergence=False,
                expected_established_session_count=42,
                exclude_bgp_mon=True,
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
            exclude_bgp_mon=True,
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
                exclude_bgp_mon=True,
            ),
        )
        self.assertEqual(
            checks.postchecks,
            create_standard_postchecks(
                check_bgp_convergence=False,
                expected_established_session_count=42,
                exclude_bgp_mon=True,
            ),
        )
        self.assertEqual(
            checks.snapshot_checks,
            create_standard_snapshot_checks(
                expected_peer_identity={"2401:db00::a": "2401:db00::b"},
                parent_prefixes_to_ignore=["10.0.0.0/24"],
                exclude_bgp_mon=True,
            ),
        )

    def test_churn_storm_route_storm_matches_factory(self):
        """CHURN_STORM with rib_fib_json_params reproduces the bag010 route-storm
        playbook (route-storm RIB-FIB invariants threaded into the postcheck)."""
        rib_fib_params = {
            "debug_route_attributes": True,
            "expected_as_path_length": 255,
            "expected_pool_size": 10,
        }
        ctx = ProfileContext(
            peergroup_ibgp_v6="PG_IBGP_V6",
            peergroup_ibgp_v4="PG_IBGP_V4",
            expected_established_sessions=42,
            check_ibgp_pnh=True,
            exclude_bgp_mon=True,
            rib_fib_json_params=rib_fib_params,
        )
        checks = get_profile_checks(CheckProfile.CHURN_STORM, ctx)

        self.assertEqual(
            checks.postchecks,
            create_standard_postchecks(
                check_bgp_convergence=False,
                expected_established_session_count=42,
                rib_fib_json_params=rib_fib_params,
                exclude_bgp_mon=True,
            ),
        )
        self.assertEqual(
            checks.snapshot_checks,
            [create_core_dumps_snapshot_check()],
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
            exclude_bgp_mon=True,
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
                exclude_bgp_mon=True,
            ),
        )
        self.assertEqual(
            checks.postchecks,
            create_standard_postchecks(
                check_bgp_convergence=False,
                exclude_bgp_mon=True,
            ),
        )
        self.assertEqual(
            checks.snapshot_checks,
            create_standard_snapshot_checks(
                expected_peer_identity={"2401:db00::a": "2401:db00::b"},
                exclude_bgp_mon=True,
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
            exclude_bgp_mon=True,
        )
        checks = get_profile_checks(CheckProfile.IGP_INSTABILITY, ctx)

        self.assertEqual(
            checks.postchecks,
            create_standard_postchecks(
                check_bgp_convergence=False,
                exclude_bgp_mon=True,
            ),
        )

    def test_soak_no_precheck_nexthop_matches_factory(self):
        """SOAK_NO_PRECHECK with convergence ON reproduces the nexthop-group-count
        threshold playbook (no prechecks, convergence postcheck at the threshold,
        snapshot skips flap + uptime)."""
        ctx = ProfileContext(
            check_bgp_convergence=True,
            convergence_threshold=600,
            exclude_bgp_mon=True,
        )
        checks = get_profile_checks(CheckProfile.SOAK_NO_PRECHECK, ctx)

        # No prechecks — the playbook leaves the optional field unset.
        self.assertEqual(checks.prechecks, [])
        self.assertEqual(
            checks.postchecks,
            create_standard_postchecks(
                convergence_threshold=600,
                exclude_bgp_mon=True,
            ),
        )
        self.assertEqual(
            checks.snapshot_checks,
            create_standard_snapshot_checks(
                skip_flap_check=True,
                skip_uptime_check=True,
                exclude_bgp_mon=True,
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
            exclude_bgp_mon=True,
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
                exclude_bgp_mon=True,
            )
            + [
                create_bgp_route_count_verification_check(
                    json_params={
                        "descriptions_to_ignore": ["IBGP"],
                        "descriptions_to_check": ["EBGP"],
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
                exclude_bgp_mon=True,
            ),
        )
        self.assertEqual(
            checks.snapshot_checks,
            create_standard_snapshot_checks(
                exclude_bgp_mon=True,
            ),
        )

    def test_soak_no_precheck_longevity_matches_factory(self):
        """SOAK_NO_PRECHECK with convergence OFF reproduces the longevity-soak
        playbook (no prechecks, no convergence postcheck, snapshot skips flap +
        uptime)."""
        ctx = ProfileContext(
            check_bgp_convergence=False,
            exclude_bgp_mon=True,
        )
        checks = get_profile_checks(CheckProfile.SOAK_NO_PRECHECK, ctx)

        self.assertEqual(checks.prechecks, [])
        self.assertEqual(
            checks.postchecks,
            create_standard_postchecks(
                check_bgp_convergence=False,
                exclude_bgp_mon=True,
            ),
        )
        self.assertEqual(
            checks.snapshot_checks,
            create_standard_snapshot_checks(
                skip_flap_check=True,
                skip_uptime_check=True,
                exclude_bgp_mon=True,
            ),
        )
