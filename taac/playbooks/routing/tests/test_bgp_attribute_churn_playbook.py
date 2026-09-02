# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

import functools
import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from taac.constants import BgpPlusPlusProfile
from taac.playbooks.routing.bgp_ebb_playbooks import (
    _ebb_drained_prefix_descriptors,
    get_bgp_ebb_attribute_churn_playbook,
    get_bgp_ebb_fauu_drain_undrain_playbook,
    get_bgp_ebb_plane_drain_undrain_playbook,
)
from taac.stages.stage_definitions import (
    create_bgp_ebb_attribute_churn_stage,
    create_fauu_drain_undrain_stage,
    create_plane_drain_undrain_stage,
)
from taac.steps.step_definitions import (
    create_bgp_attribute_churn_step,
)
from taac.testconfigs.routing.cicd_ebb_int_tc import (
    BAG012_STAGE1_FULL_SCALE_TEST_CONFIG_NO_UG,
    BAG012_STAGE1_FULL_SCALE_TEST_CONFIG_UG,
)
from taac.testconfigs.routing.factories.bgp_ebb_full_scale import (
    _DEFAULT_EBGP_PREFIX_COUNT,
    _get_bgp_ebb_full_scale_playbooks,
    _TC7_PLAYBOOK_NAMES,
    create_bgp_ebb_full_scale_test_config,
)
from taac.test_as_a_config import types as taac_types


EXPECTED_POOLS = {
    "ipv4": {
        "1": "PREFIX_POOL_IBGP_IPV4_PLANE_1_REMOTE_EB",
        "2": "PREFIX_POOL_IBGP_IPV4_PLANE_2_REMOTE_EB",
        "3": "PREFIX_POOL_IBGP_IPV4_PLANE_3_REMOTE_EB",
        "4": "PREFIX_POOL_IBGP_IPV4_PLANE_4_REMOTE_EB",
    },
    "ipv6": {
        "1": "PREFIX_POOL_IBGP_IPV6_PLANE_1_REMOTE_EB",
        "2": "PREFIX_POOL_IBGP_IPV6_PLANE_2_REMOTE_EB",
        "3": "PREFIX_POOL_IBGP_IPV6_PLANE_3_REMOTE_EB",
        "4": "PREFIX_POOL_IBGP_IPV6_PLANE_4_REMOTE_EB",
    },
}

EXPECTED_MATRIX = {
    "local_pref": {
        "plane_1_preferred": 200,
        "reference": 100,
        "plane_1_nonpreferred": 50,
    },
    "med": {
        "plane_1_preferred": 100,
        "reference": 200,
        "plane_1_nonpreferred": 300,
    },
    "origin": {
        "plane_1_preferred": "igp",
        "reference": "egp",
        "plane_1_nonpreferred": "incomplete",
    },
}


# The complete flat CustomStep payload the production Playbook serializes.
#
# The golden manifest stores only a hash and seven structural counts, and no
# factory snapshot covers `get_bgp_ebb_*` factories, so without this literal a
# reviewer cannot see which field of the payload a diff changed -- only that
# some byte moved. Frozen against the Playbook factory rather than the Step
# factory because the Playbook is where the production values are authored.
_FROZEN_CHURN_PAYLOAD: dict = {
    "custom_step_name": "bgp_attribute_churn",
    "hostname": "dut.example.com",
    "prefix_pool_names": EXPECTED_POOLS,
    "attribute_matrix": EXPECTED_MATRIX,
    "openr_mode": "standalone",
    "peer_count_per_plane": 62,
    "selected_block_count_per_afi": 7,
    "samples_per_block": 2,
    "routes_per_block": 750,
    "duration_seconds": 3_600,
    "max_iterations": 100_000,
    "cadence_seconds": 60,
    "poll_interval_seconds": 5,
    "transition_timeout_seconds": 60,
    "convergence_hard_timeout_seconds": 300,
    "reference_setup_timeout_seconds": 120,
    "restore_timeout_seconds": 120,
    "quiet_window_seconds": 120,
    "max_lookup_concurrency": 8,
}


def _locked_step_kwargs() -> dict:
    return {
        "hostname": "dut.example.com",
        "prefix_pool_names": EXPECTED_POOLS,
        "peer_count_per_plane": 62,
        "selected_block_count_per_afi": 7,
        "samples_per_block": 2,
        "routes_per_block": 750,
        "duration_seconds": 3_600,
        "max_iterations": 100_000,
        "cadence_seconds": 60,
        "poll_interval_seconds": 5,
        "transition_timeout_seconds": 60,
        "convergence_hard_timeout_seconds": 300,
        "reference_setup_timeout_seconds": 120,
        "restore_timeout_seconds": 120,
        "quiet_window_seconds": 120,
        "max_lookup_concurrency": 8,
        "openr_mode": "standalone",
        "attribute_matrix": EXPECTED_MATRIX,
    }


# The fauu captures assert ORIGIN and LOCAL_PREF on the drained prefixes, so the
# factory requires the window; the plane factory takes no such argument. Bind it
# here so the shared loops below can pass identical kwargs to both.
_DRAINED_WINDOW: list[dict] = [
    {
        "start_prefix": "120.0.0.0",
        "prefix_step": 256,
        "prefix_length": 24,
        "start_index": 0,
        "end_index": 96,
    }
]
_fauu_stage_with_window = functools.partial(
    create_fauu_drain_undrain_stage, drained_prefix_descriptors=_DRAINED_WINDOW
)


def _step_payload(step: taac_types.Step) -> dict:
    params = step.step_params
    if params is None:
        raise AssertionError("custom step is missing step_params")
    json_params = params.json_params
    if json_params is None:
        raise AssertionError("custom step is missing serialized json_params")
    return json.loads(json_params)


def _sequential_steps(playbook: taac_types.Playbook) -> list[taac_types.Step]:
    return [step for stage in playbook.stages for step in stage.steps]


def _serialized_stage_steps(playbook: taac_types.Playbook) -> str:
    serialized: list[str] = []
    for step in _sequential_steps(playbook):
        if step.description:
            serialized.append(step.description)
        if step.input_json:
            serialized.append(step.input_json)
        if step.step_params and step.step_params.json_params:
            serialized.append(step.step_params.json_params)
    return "\n".join(serialized)


def _stage_steps(stage: object) -> list[taac_types.Step]:
    """Flatten a stage factory's return value.

    The two factories differ: fauu returns a single Stage, plane returns the
    six-stage list, and either can hold concurrent steps.
    """
    if isinstance(stage, list):
        return [step for entry in stage for step in _stage_steps(entry)]
    steps = list(getattr(stage, "steps", None) or [])
    for concurrent in getattr(stage, "concurrent_steps", None) or []:
        steps.extend(concurrent.steps or [])
    return steps


def _count_convergence_verifiers(
    test: unittest.TestCase, stage: object
) -> tuple[int, int]:
    """Count (counter polls, pcap verifiers), asserting each carries sane args."""
    polls = 0
    pcap_verifiers = 0
    for step in _stage_steps(stage):
        if step.name != taac_types.StepName.CUSTOM_STEP or step.step_params is None:
            continue
        payload = _step_payload(step)
        if payload.get("custom_step_name") != "verify_drain_convergence":
            continue
        if payload["use_pcap_analysis"]:
            # A pcap verifier without a filename would download nothing.
            test.assertTrue(payload["pcap_filename"])
            pcap_verifiers += 1
        else:
            # A counter poll never opens a capture, so naming one is the bug
            # this contract exists to catch.
            test.assertIsNone(payload["pcap_filename"])
            polls += 1
    return polls, pcap_verifiers


def _convergence_contract(
    playbook: taac_types.Playbook,
) -> tuple[set[str], dict[str, set[str]]]:
    verifier_pcaps: set[str] = set()
    report_interfaces: dict[str, set[str]] = {}
    for step in _sequential_steps(playbook):
        if step.name != taac_types.StepName.CUSTOM_STEP or step.step_params is None:
            continue
        payload = _step_payload(step)
        if payload.get("custom_step_name") == "verify_drain_convergence":
            # Counter-poll verifiers have no capture behind them and report
            # pcap_filename=None. Only None is skipped, so an empty name on a
            # genuine pcap verifier still fails this contract.
            pcap_filename = payload["pcap_filename"]
            if pcap_filename is not None:
                verifier_pcaps.add(pcap_filename)
        if (
            payload.get("custom_step_name")
            == "generate_consolidated_convergence_report"
        ):
            report_interfaces[payload["phase"]] = set(payload["pcap_files"])
    return verifier_pcaps, report_interfaces


class BgpAttributeChurnPlaybookTest(unittest.TestCase):
    def test_drain_playbooks_keep_core_verdicts_without_auxiliary_monitor(
        self,
    ) -> None:
        playbooks = (
            (
                get_bgp_ebb_fauu_drain_undrain_playbook(
                    device_name="dut.example.com",
                    peergroup_ibgp_v6="IBGP_V6",
                    peergroup_ibgp_v4="IBGP_V4",
                    tcp_dump_capture_interface_ebgp="Ethernet1",
                    tcp_dump_capture_interface_ibgp="Ethernet2",
                ),
                {
                    "bgp_fauu_drain_ebgp.pcap",
                    "bgp_fauu_drain_ibgp.pcap",
                    "bgp_fauu_undrain_ebgp.pcap",
                    "bgp_fauu_undrain_ibgp.pcap",
                },
                {"ebgp_source", "ibgp_receiver"},
            ),
            (
                get_bgp_ebb_plane_drain_undrain_playbook(
                    device_name="dut.example.com",
                    peergroup_ibgp_v6="IBGP_V6",
                    peergroup_ibgp_v4="IBGP_V4",
                    tcp_dump_capture_interface_ebgp="Ethernet1",
                    tcp_dump_capture_interface_ibgp="Ethernet2",
                ),
                {
                    "bgp_plane_drain_ebgp.pcap",
                    "bgp_plane_drain_ibgp_source.pcap",
                    "bgp_plane_undrain_ebgp.pcap",
                    "bgp_plane_undrain_ibgp_source.pcap",
                },
                {"ebgp", "ibgp_source"},
            ),
        )

        for playbook, expected_pcaps, expected_interfaces in playbooks:
            with self.subTest(playbook=playbook.name):
                verifier_pcaps, report_interfaces = _convergence_contract(playbook)
                self.assertEqual(expected_pcaps, verifier_pcaps)
                self.assertEqual(
                    {"drain": expected_interfaces, "undrain": expected_interfaces},
                    report_interfaces,
                )
                self.assertNotIn("bgpmon", _serialized_stage_steps(playbook).casefold())

    def test_drain_playbooks_ignore_auxiliary_monitor_when_available(self) -> None:
        playbooks = (
            (
                get_bgp_ebb_fauu_drain_undrain_playbook(
                    device_name="dut.example.com",
                    peergroup_ibgp_v6="IBGP_V6",
                    peergroup_ibgp_v4="IBGP_V4",
                    tcp_dump_capture_interface_ebgp="Ethernet1",
                    tcp_dump_capture_interface_ibgp="Ethernet2",
                    tcp_dump_capture_interface_bgpmon="Ethernet3",
                ),
                {
                    "bgp_fauu_drain_ebgp.pcap",
                    "bgp_fauu_drain_ibgp.pcap",
                    "bgp_fauu_undrain_ebgp.pcap",
                    "bgp_fauu_undrain_ibgp.pcap",
                },
                {"ebgp_source", "ibgp_receiver"},
            ),
            (
                get_bgp_ebb_plane_drain_undrain_playbook(
                    device_name="dut.example.com",
                    peergroup_ibgp_v6="IBGP_V6",
                    peergroup_ibgp_v4="IBGP_V4",
                    tcp_dump_capture_interface_ebgp="Ethernet1",
                    tcp_dump_capture_interface_ibgp="Ethernet2",
                    tcp_dump_capture_interface_bgpmon="Ethernet3",
                ),
                {
                    "bgp_plane_drain_ebgp.pcap",
                    "bgp_plane_drain_ibgp_source.pcap",
                    "bgp_plane_undrain_ebgp.pcap",
                    "bgp_plane_undrain_ibgp_source.pcap",
                },
                {"ebgp", "ibgp_source"},
            ),
        )

        for playbook, expected_pcaps, expected_interfaces in playbooks:
            with self.subTest(playbook=playbook.name):
                verifier_pcaps, report_interfaces = _convergence_contract(playbook)
                self.assertEqual(expected_pcaps, verifier_pcaps)
                self.assertEqual(
                    {"drain": expected_interfaces, "undrain": expected_interfaces},
                    report_interfaces,
                )
                self.assertNotIn("bgpmon", _serialized_stage_steps(playbook).casefold())

    def test_convergence_mode_selects_the_verification_mechanism(self) -> None:
        """Each mode must emit exactly the verifiers it claims to run.

        Guards the failure this contract was written for: a verifier that
        carries a pcap filename but runs a counter poll because
        use_pcap_analysis was never passed, so the capture is taken and never
        read.
        """
        stages = (
            ("fauu", _fauu_stage_with_window, ".*EBGP.*"),
            ("plane", create_plane_drain_undrain_stage, ".*IBGP.*PLANE_.*"),
        )
        # counter: poll only, no capture. pcap: capture only, no poll.
        # hybrid: the poll gates the wait, then tshark reads the capture.
        expected = {"counter": (2, 0), "pcap": (0, 4), "hybrid": (2, 4)}
        for name, stage_factory, prefix_pool_regex in stages:
            for mode, (expected_polls, expected_pcap_verifiers) in expected.items():
                with self.subTest(stage=name, convergence_mode=mode):
                    stage = stage_factory(
                        device_name="dut.example.com",
                        prefix_pool_regex=prefix_pool_regex,
                        tcp_dump_capture_interface_ebgp="Ethernet1",
                        tcp_dump_capture_interface_ibgp="Ethernet2",
                        convergence_mode=mode,
                    )
                    polls, pcap_verifiers = _count_convergence_verifiers(self, stage)
                    self.assertEqual(expected_polls, polls)
                    self.assertEqual(expected_pcap_verifiers, pcap_verifiers)

    def test_drained_window_follows_the_selected_pools(self) -> None:
        """A single-AFI drain must not demand coverage of the other pool.

        prefix_pool_regex is configurable and the capture asserts that every
        described prefix was advertised, so describing both families while
        draining one would fail a healthy run on the untouched family.
        """
        both = _ebb_drained_prefix_descriptors(96)
        self.assertEqual(
            ["120.0.0.0", "2402:db00::"],
            sorted(d["start_prefix"] for d in both),
        )

        v4_only = _ebb_drained_prefix_descriptors(96, prefix_pool_regex=".*IPV4_EBGP.*")
        self.assertEqual(["120.0.0.0"], [d["start_prefix"] for d in v4_only])

        v6_only = _ebb_drained_prefix_descriptors(
            96, prefix_pool_regex="PREFIX_POOL_IPV6_EBGP"
        )
        self.assertEqual(["2402:db00::"], [d["start_prefix"] for d in v6_only])

        # A regex matching no pool means the drain touches nothing, which is a
        # typo rather than a valid narrowing.
        with self.assertRaises(ValueError) as raised:
            _ebb_drained_prefix_descriptors(96, prefix_pool_regex=".*IBGP.*")

        self.assertIn("matches none of the EBB", str(raised.exception))

    def test_playbook_scopes_the_window_to_its_own_pool_regex(self) -> None:
        """The window must follow the regex the playbook hands the drain."""
        playbook = get_bgp_ebb_fauu_drain_undrain_playbook(
            device_name="dut.example.com",
            peergroup_ibgp_v6="IBGP_V6",
            peergroup_ibgp_v4="IBGP_V4",
            tcp_dump_capture_interface_ebgp="Ethernet1",
            tcp_dump_capture_interface_ibgp="Ethernet2",
            prefix_pool_regex=".*IPV4_EBGP.*",
        )
        windows = [
            payload["expected_attribute_prefixes"]
            for payload in (
                _step_payload(step)
                for step in _sequential_steps(playbook)
                if step.name == taac_types.StepName.CUSTOM_STEP
                and step.step_params is not None
            )
            if payload.get("custom_step_name") == "verify_drain_convergence"
            and payload.get("use_pcap_analysis")
        ]
        self.assertTrue(windows)
        for window in windows:
            self.assertEqual(["120.0.0.0"], [d["start_prefix"] for d in window])

    def test_captures_without_a_drained_window_are_rejected_at_construction(
        self,
    ) -> None:
        """A missing window must fail here, not 35 minutes into a hardware run.

        Every pcap step sets an attribute expectation, and an expectation with
        no window is rejected at verification time as a misconfiguration. That
        verdict arrives only after the drain has already run, so the factory
        refuses to build the stage instead.
        """
        with self.assertRaises(ValueError) as raised:
            create_fauu_drain_undrain_stage(
                device_name="dut.example.com",
                prefix_pool_regex=".*EBGP.*",
                tcp_dump_capture_interface_ebgp="Ethernet1",
                tcp_dump_capture_interface_ibgp="Ethernet2",
            )

        self.assertIn("drained_prefix_descriptors is required", str(raised.exception))

        # Counter-only mode takes no capture, so it has nothing to scope and
        # must still build.
        create_fauu_drain_undrain_stage(
            device_name="dut.example.com",
            prefix_pool_regex=".*EBGP.*",
            tcp_dump_capture_interface_ebgp="Ethernet1",
            tcp_dump_capture_interface_ibgp="Ethernet2",
            convergence_mode="counter",
        )

    def test_pcap_legs_expect_local_pref_per_bgp_semantics(self) -> None:
        """LOCAL_PREF does not survive the eBGP hop, ORIGIN does.

        RFC 4271 5.1.5: a speaker MUST ignore a LOCAL_PREF received from an
        external peer and originates its own toward internal peers. So the eBGP
        capture must carry the value IXIA set (120 while drained) and the iBGP
        capture the DUT's own default (100 in both phases), while ORIGIN is
        identical on both legs. Expecting the tester's 120 on the iBGP leg
        failed a hardware run against a correctly behaving DUT.
        """
        expected = {
            "bgp_fauu_drain_ebgp.pcap": ("incomplete", 120),
            "bgp_fauu_drain_ibgp.pcap": ("incomplete", 100),
            "bgp_fauu_undrain_ebgp.pcap": ("igp", 100),
            "bgp_fauu_undrain_ibgp.pcap": ("igp", 100),
        }
        steps = _stage_steps(
            _fauu_stage_with_window(
                device_name="dut.example.com",
                prefix_pool_regex=".*EBGP.*",
                tcp_dump_capture_interface_ebgp="Ethernet1",
                tcp_dump_capture_interface_ibgp="Ethernet2",
            )
        )
        payloads = [
            _step_payload(step)
            for step in steps
            if step.name == taac_types.StepName.CUSTOM_STEP
            and step.step_params is not None
        ]
        observed = {
            payload["pcap_filename"]: (
                payload.get("expected_origin"),
                payload.get("expected_local_pref"),
            )
            for payload in payloads
            if payload.get("custom_step_name") == "verify_drain_convergence"
            and payload.get("use_pcap_analysis")
        }
        self.assertEqual(expected, observed)

    def test_drain_stages_bracket_the_run_with_a_restoration_gate(self) -> None:
        """The undrain must be compared against the exact pre-drain state.

        The postcheck chain proves sessions are up and that RIB, FIB Agent and
        hardware FIB agree with each other; all three stay self-consistent when
        an undrain restores the wrong view or leaves a -DRAIN egress policy
        applied. The gate is only meaningful if the baseline is taken before
        any drain step and the comparison is the last thing the stage does.
        """
        stages = (
            ("fauu", _fauu_stage_with_window, ".*EBGP.*"),
            ("plane", create_plane_drain_undrain_stage, ".*IBGP.*PLANE_.*"),
        )
        for name, stage_factory, prefix_pool_regex in stages:
            with self.subTest(stage=name):
                steps = _stage_steps(
                    stage_factory(
                        device_name="dut.example.com",
                        prefix_pool_regex=prefix_pool_regex,
                        tcp_dump_capture_interface_ebgp="Ethernet1",
                        tcp_dump_capture_interface_ibgp="Ethernet2",
                    )
                )
                payloads = [
                    _step_payload(step)
                    for step in steps
                    if step.name == taac_types.StepName.CUSTOM_STEP
                    and step.step_params is not None
                ]
                custom_names = [payload.get("custom_step_name") for payload in payloads]
                self.assertEqual(
                    1, custom_names.count("snapshot_bgp_restoration_baseline")
                )
                self.assertEqual("snapshot_bgp_restoration_baseline", custom_names[0])

                # The probe shares the custom step, so count by role: exactly
                # one blocking gate and exactly one report-only sample.
                comparisons = [
                    payload
                    for payload in payloads
                    if payload.get("custom_step_name")
                    == "verify_bgp_restoration_against_baseline"
                ]
                blocking = [p for p in comparisons if not p["report_only"]]
                report_only = [p for p in comparisons if p["report_only"]]
                self.assertEqual(1, len(blocking))
                self.assertEqual(1, len(report_only))
                # The gate is last; the probe sits between the baseline and it.
                self.assertIs(blocking[0], comparisons[-1])
                self.assertEqual(
                    "verify_bgp_restoration_against_baseline", custom_names[-1]
                )

    def test_drain_stage_restoration_halves_agree_on_key_and_scope(self) -> None:
        """A snapshot and a verify that disagree would compare nothing."""
        stages = (
            ("fauu", _fauu_stage_with_window, ".*EBGP.*"),
            ("plane", create_plane_drain_undrain_stage, ".*IBGP.*PLANE_.*"),
        )
        for name, stage_factory, prefix_pool_regex in stages:
            with self.subTest(stage=name):
                payloads = {}
                for step in _stage_steps(
                    stage_factory(
                        device_name="dut.example.com",
                        prefix_pool_regex=prefix_pool_regex,
                    )
                ):
                    if (
                        step.name != taac_types.StepName.CUSTOM_STEP
                        or step.step_params is None
                    ):
                        continue
                    payload = _step_payload(step)
                    custom_step_name = payload.get("custom_step_name")
                    if custom_step_name == "snapshot_bgp_restoration_baseline":
                        payloads[custom_step_name] = payload
                    elif custom_step_name == "verify_bgp_restoration_against_baseline":
                        # Key the two comparisons apart: the probe shares the
                        # custom step name and would otherwise overwrite the gate.
                        role = "probe" if payload["report_only"] else "gate"
                        payloads[role] = payload

                snapshot = payloads["snapshot_bgp_restoration_baseline"]
                verify = payloads["gate"]
                probe = payloads["probe"]
                # The probe is only comparable to the gate if it reads the same
                # state against the same baseline.
                self.assertEqual(snapshot["snapshot_key"], probe["snapshot_key"])
                self.assertEqual(snapshot["peer_scope"], probe["peer_scope"])
                self.assertEqual(
                    snapshot["compare_route_count"], probe["compare_route_count"]
                )
                self.assertEqual(snapshot["snapshot_key"], verify["snapshot_key"])
                self.assertEqual(snapshot["peer_scope"], verify["peer_scope"])
                self.assertEqual(
                    snapshot["compare_route_count"], verify["compare_route_count"]
                )
                # Anything above zero would let the reported 192-route shortfall
                # through, and a floor of zero peers makes the whole comparison
                # vacuous.
                self.assertEqual(0, verify["route_count_tolerance"])
                self.assertGreater(snapshot["expected_min_peers"], 0)

    def test_mid_stage_probe_can_never_fail_the_stage(self) -> None:
        """The probe exists to say WHERE the state diverged.

        A diagnostic that can turn a run red is worse than no diagnostic, and a
        gate that is silently report-only is worse still, so the two roles are
        pinned here rather than left to the call site.
        """
        stages = (
            ("fauu", _fauu_stage_with_window, ".*EBGP.*"),
            ("plane", create_plane_drain_undrain_stage, ".*IBGP.*PLANE_.*"),
        )
        for name, stage_factory, prefix_pool_regex in stages:
            with self.subTest(stage=name):
                comparisons = [
                    _step_payload(step)
                    for step in _stage_steps(
                        stage_factory(
                            device_name="dut.example.com",
                            prefix_pool_regex=prefix_pool_regex,
                        )
                    )
                    if step.name == taac_types.StepName.CUSTOM_STEP
                    and step.step_params is not None
                    and _step_payload(step).get("custom_step_name")
                    == "verify_bgp_restoration_against_baseline"
                ]
                probe = next(p for p in comparisons if p["report_only"])
                gate = next(p for p in comparisons if not p["report_only"])

                # One sample, not a settle window: the probe measures a moment.
                self.assertEqual(0, probe["settle_timeout_seconds"])
                # A distinct result row, so the probe is never read as a verdict.
                self.assertIn("probe", probe["check_name"])
                self.assertNotIn("check_name", gate)
                # The gate still waits for the drain tail to finish.
                self.assertGreater(gate["settle_timeout_seconds"], 0)

    def test_drain_stages_can_opt_out_of_the_restoration_gate(self) -> None:
        stages = (
            ("fauu", _fauu_stage_with_window, ".*EBGP.*"),
            ("plane", create_plane_drain_undrain_stage, ".*IBGP.*PLANE_.*"),
        )
        for name, stage_factory, prefix_pool_regex in stages:
            with self.subTest(stage=name):
                steps = _stage_steps(
                    stage_factory(
                        device_name="dut.example.com",
                        prefix_pool_regex=prefix_pool_regex,
                        verify_restoration=False,
                    )
                )
                custom_names = {
                    _step_payload(step).get("custom_step_name")
                    for step in steps
                    if step.name == taac_types.StepName.CUSTOM_STEP
                    and step.step_params is not None
                }
                self.assertNotIn("snapshot_bgp_restoration_baseline", custom_names)
                self.assertNotIn(
                    "verify_bgp_restoration_against_baseline", custom_names
                )

    def test_pcap_verifiers_require_their_capture_to_carry_updates(self) -> None:
        """An empty required capture used to be logged and passed over."""
        stages = (
            ("fauu", _fauu_stage_with_window, ".*EBGP.*"),
            ("plane", create_plane_drain_undrain_stage, ".*IBGP.*PLANE_.*"),
        )
        for name, stage_factory, prefix_pool_regex in stages:
            with self.subTest(stage=name):
                verifiers = 0
                for step in _stage_steps(
                    stage_factory(
                        device_name="dut.example.com",
                        prefix_pool_regex=prefix_pool_regex,
                        tcp_dump_capture_interface_ebgp="Ethernet1",
                        tcp_dump_capture_interface_ibgp="Ethernet2",
                    )
                ):
                    if (
                        step.name != taac_types.StepName.CUSTOM_STEP
                        or step.step_params is None
                    ):
                        continue
                    payload = _step_payload(step)
                    if payload.get(
                        "custom_step_name"
                    ) != "verify_drain_convergence" or not payload.get(
                        "use_pcap_analysis"
                    ):
                        continue
                    verifiers += 1
                    self.assertTrue(payload["require_updates"])
                self.assertEqual(4, verifiers)

    def test_playbook_payload_matches_frozen_contract(self) -> None:
        """Byte-level oracle for the serialized CustomStep payload.

        A field-by-field diff on failure, which neither the hash-only golden
        manifest nor the `create_*_playbook`-only factory snapshots provide for
        this Playbook. Any intended payload change updates this literal in the
        same diff, so the change is visible in review.
        """
        playbook = get_bgp_ebb_attribute_churn_playbook(
            device_name="dut.example.com",
            peergroup_ibgp_v6="IBGP_V6",
            peergroup_ibgp_v4="IBGP_V4",
            total_session_count=1272,
            profile=BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R,
        )

        # characterization defaults to DISABLED, so no START/STOP bracket is
        # added and the churn Stage is the only one. Production wraps it; that
        # composition is asserted separately.
        self.assertEqual(1, len(playbook.stages))
        self.assertEqual(1, len(playbook.stages[0].steps))

        self.assertEqual(
            _FROZEN_CHURN_PAYLOAD, _step_payload(playbook.stages[0].steps[0])
        )

    def test_step_factory_serializes_locked_contract(self) -> None:
        step = create_bgp_attribute_churn_step(**_locked_step_kwargs())

        self.assertEqual(taac_types.StepName.CUSTOM_STEP, step.name)
        payload = _step_payload(step)
        self.assertEqual("bgp_attribute_churn", payload["custom_step_name"])
        self.assertEqual(EXPECTED_POOLS, payload["prefix_pool_names"])
        self.assertEqual(EXPECTED_MATRIX, payload["attribute_matrix"])
        self.assertEqual(7, payload["selected_block_count_per_afi"])
        self.assertEqual(3_600, payload["duration_seconds"])
        self.assertEqual(100_000, payload["max_iterations"])
        self.assertEqual(300, payload["convergence_hard_timeout_seconds"])

    def test_step_factory_rejects_incomplete_pool_geometry(self) -> None:
        kwargs = _locked_step_kwargs()
        kwargs["prefix_pool_names"] = {
            "ipv4": EXPECTED_POOLS["ipv4"],
            "ipv6": {"1": EXPECTED_POOLS["ipv6"]["1"]},
        }

        with self.assertRaises(ValueError):
            create_bgp_attribute_churn_step(**kwargs)

    def test_step_factory_allows_zero_quiet_window(self) -> None:
        kwargs = _locked_step_kwargs()
        kwargs["quiet_window_seconds"] = 0

        payload = _step_payload(create_bgp_attribute_churn_step(**kwargs))

        self.assertEqual(0, payload["quiet_window_seconds"])

    def test_step_factory_rejects_negative_quiet_window(self) -> None:
        kwargs = _locked_step_kwargs()
        kwargs["quiet_window_seconds"] = -1

        with self.assertRaisesRegex(ValueError, "must be non-negative"):
            create_bgp_attribute_churn_step(**kwargs)

    def test_step_factory_requires_two_selected_blocks_per_afi(self) -> None:
        kwargs = _locked_step_kwargs()
        kwargs["selected_block_count_per_afi"] = 1

        with self.assertRaisesRegex(
            ValueError,
            "selected_block_count_per_afi must be at least 2",
        ):
            create_bgp_attribute_churn_step(**kwargs)

    def test_step_factory_requires_hard_timeout_above_soft_timeouts(self) -> None:
        kwargs = _locked_step_kwargs()
        kwargs["convergence_hard_timeout_seconds"] = 120

        with self.assertRaisesRegex(ValueError, "must exceed"):
            create_bgp_attribute_churn_step(**kwargs)

    def test_stage_contains_only_the_audited_custom_step(self) -> None:
        stage = create_bgp_ebb_attribute_churn_stage(**_locked_step_kwargs())

        self.assertEqual(1, len(stage.steps))
        payload = _step_payload(stage.steps[0])
        self.assertEqual("bgp_attribute_churn", payload["custom_step_name"])

    def test_playbook_wires_production_geometry_and_timing(self) -> None:
        playbook = get_bgp_ebb_attribute_churn_playbook(
            device_name="dut.example.com",
            peergroup_ibgp_v6="IBGP_V6",
            peergroup_ibgp_v4="IBGP_V4",
            total_session_count=1272,
            profile=BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R,
        )

        self.assertEqual(1, len(playbook.stages))
        self.assertEqual(1, len(playbook.stages[0].steps))
        payload = _step_payload(playbook.stages[0].steps[0])
        self.assertEqual(EXPECTED_POOLS, payload["prefix_pool_names"])
        self.assertEqual(EXPECTED_MATRIX, payload["attribute_matrix"])
        self.assertEqual(
            {
                "peer_count_per_plane": 62,
                "selected_block_count_per_afi": 7,
                "samples_per_block": 2,
                "routes_per_block": 750,
                "duration_seconds": 3_600,
                "max_iterations": 100_000,
                "cadence_seconds": 60,
                "poll_interval_seconds": 5,
                "transition_timeout_seconds": 60,
                "convergence_hard_timeout_seconds": 300,
                "reference_setup_timeout_seconds": 120,
                "restore_timeout_seconds": 120,
                "quiet_window_seconds": 120,
                "max_lookup_concurrency": 8,
                "openr_mode": "standalone",
            },
            {
                key: payload[key]
                for key in (
                    "peer_count_per_plane",
                    "selected_block_count_per_afi",
                    "samples_per_block",
                    "routes_per_block",
                    "duration_seconds",
                    "max_iterations",
                    "cadence_seconds",
                    "poll_interval_seconds",
                    "transition_timeout_seconds",
                    "convergence_hard_timeout_seconds",
                    "reference_setup_timeout_seconds",
                    "restore_timeout_seconds",
                    "quiet_window_seconds",
                    "max_lookup_concurrency",
                    "openr_mode",
                )
            },
        )

    def test_playbook_allows_ad_hoc_duration_override(self) -> None:
        playbook = get_bgp_ebb_attribute_churn_playbook(
            device_name="dut.example.com",
            peergroup_ibgp_v6="IBGP_V6",
            peergroup_ibgp_v4="IBGP_V4",
            total_session_count=1272,
            profile=BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R,
            duration_seconds=6 * 60 * 60,
        )

        payload = _step_payload(playbook.stages[0].steps[0])
        self.assertEqual(21_600, payload["duration_seconds"])

    def test_playbook_wires_non_openr_topology_mode(self) -> None:
        playbook = get_bgp_ebb_attribute_churn_playbook(
            device_name="dut.example.com",
            peergroup_ibgp_v6="IBGP_V6",
            peergroup_ibgp_v4="IBGP_V4",
            total_session_count=1272,
            profile=BgpPlusPlusProfile.BGP_PLUS_PLUS_WITHOUT_OPEN_R,
        )

        payload = _step_payload(playbook.stages[0].steps[0])
        self.assertEqual("none", payload["openr_mode"])

    def test_openr_profile_enables_ibgp_pnh_check(self) -> None:
        target = (
            "neteng.test_infra.dne.taac.playbooks.routing."
            "bgp_ebb_playbooks.get_profile_checks"
        )
        with patch(target) as get_checks:
            get_checks.return_value = SimpleNamespace(
                prechecks=[],
                postchecks=[],
                snapshot_checks=[],
            )
            get_bgp_ebb_attribute_churn_playbook(
                device_name="dut.example.com",
                peergroup_ibgp_v6="IBGP_V6",
                peergroup_ibgp_v4="IBGP_V4",
                total_session_count=1272,
                profile=BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R,
            )

        self.assertTrue(get_checks.call_args.args[1].check_ibgp_pnh)

    def test_full_scale_factory_does_not_require_observer_parent(self) -> None:
        inventory = MagicMock()
        inventory.device_name = "dut.example.com"
        inventory.ixia_ports = [["Ethernet1"], ["Ethernet2"]]
        inventory.openr_standalone_link.owner = "owner"
        inventory.openr_standalone_link.helper = "helper"
        inventory.openr_standalone_link.kv_link.return_value = {}
        target = (
            "neteng.test_infra.dne.taac.testconfigs.routing.factories."
            "bgp_ebb_full_scale.get_bgp_ebb_attribute_churn_playbook"
        )

        with patch(target) as playbook_factory:
            playbook_factory.return_value = MagicMock()
            _get_bgp_ebb_full_scale_playbooks(
                inventory,
                BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R,
                bound=MagicMock(),
                ebgp_prefix_count=_DEFAULT_EBGP_PREFIX_COUNT,
                selected_tc7_playbooks=set(),
            )

        self.assertNotIn(
            "observer_peer_parent_prefix", playbook_factory.call_args.kwargs
        )

    def test_full_scale_factory_rejects_missing_port_map_roles(self) -> None:
        inventory = MagicMock()
        inventory.device_name = "dut.example.com"
        inventory.ixia_ports = [["Ethernet1"], ["Ethernet2"]]

        for port_map, missing_role in (
            ({"uplink": 0}, "ibgp"),
            ({"ibgp": 1}, "uplink"),
        ):
            with (
                self.subTest(missing_role=missing_role),
                self.assertRaisesRegex(
                    ValueError,
                    rf"missing required roles: \['{missing_role}'\]",
                ),
            ):
                _get_bgp_ebb_full_scale_playbooks(
                    inventory,
                    BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R,
                    bound=MagicMock(),
                    ebgp_prefix_count=_DEFAULT_EBGP_PREFIX_COUNT,
                    selected_tc7_playbooks=set(),
                    port_map=port_map,
                )

    def test_full_scale_factory_rejects_out_of_range_port_map_indices(
        self,
    ) -> None:
        inventory = MagicMock()
        inventory.device_name = "dut.example.com"
        inventory.ixia_ports = [["Ethernet1"], ["Ethernet2"]]

        for port_map, role, index in (
            ({"uplink": -1, "ibgp": 1}, "uplink", -1),
            ({"uplink": 0, "ibgp": 2}, "ibgp", 2),
            ({"uplink": 0, "ibgp": 1, "bgpmon": 2}, "bgpmon", 2),
        ):
            with (
                self.subTest(role=role, index=index),
                self.assertRaisesRegex(
                    ValueError,
                    rf"out-of-range indices.*'{role}': {index}",
                ),
            ):
                _get_bgp_ebb_full_scale_playbooks(
                    inventory,
                    BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R,
                    bound=MagicMock(),
                    ebgp_prefix_count=_DEFAULT_EBGP_PREFIX_COUNT,
                    selected_tc7_playbooks=set(),
                    port_map=port_map,
                )

    def test_full_scale_factory_wires_update_group_mode_to_ebb16(self) -> None:
        inventory = MagicMock()
        inventory.device_name = "dut.example.com"
        inventory.ixia_ports = [["Ethernet1"], ["Ethernet2"]]
        inventory.openr_standalone_link.owner = "owner"
        inventory.openr_standalone_link.helper = "helper"
        inventory.openr_standalone_link.kv_link.return_value = {}
        target = (
            "neteng.test_infra.dne.taac.testconfigs.routing.factories."
            "bgp_ebb_full_scale.get_bgp_ebb_nexthop_group_count_threshold_playbook"
        )

        with patch(target, return_value=MagicMock()) as playbook_factory:
            _get_bgp_ebb_full_scale_playbooks(
                inventory,
                BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R,
                bound=MagicMock(),
                ebgp_prefix_count=_DEFAULT_EBGP_PREFIX_COUNT,
                selected_tc7_playbooks=set(),
                enable_update_group=False,
            )

        self.assertFalse(playbook_factory.call_args.kwargs["enable_update_group"])

    def test_full_scale_factory_wires_optional_bgp_monitor_port(self) -> None:
        fauu_target = (
            "neteng.test_infra.dne.taac.testconfigs.routing.factories."
            "bgp_ebb_full_scale.get_bgp_ebb_fauu_drain_undrain_playbook"
        )
        plane_target = (
            "neteng.test_infra.dne.taac.testconfigs.routing.factories."
            "bgp_ebb_full_scale.get_bgp_ebb_plane_drain_undrain_playbook"
        )

        for ports in (
            ["Ethernet1", "Ethernet2"],
            ["Ethernet1", "Ethernet2", "Ethernet3"],
        ):
            inventory = MagicMock()
            inventory.device_name = "dut.example.com"
            inventory.ixia_ports = [[port] for port in ports]
            inventory.openr_standalone_link.owner = "owner"
            inventory.openr_standalone_link.helper = "helper"
            inventory.openr_standalone_link.kv_link.return_value = {}
            with (
                self.subTest(port_count=len(ports)),
                patch(fauu_target, return_value=MagicMock()) as fauu_factory,
                patch(plane_target, return_value=MagicMock()) as plane_factory,
            ):
                _get_bgp_ebb_full_scale_playbooks(
                    inventory,
                    BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R,
                    bound=MagicMock(),
                    ebgp_prefix_count=_DEFAULT_EBGP_PREFIX_COUNT,
                    selected_tc7_playbooks=set(),
                )

                for factory in (fauu_factory, plane_factory):
                    self.assertEqual(
                        "Ethernet1",
                        factory.call_args.kwargs["tcp_dump_capture_interface_ebgp"],
                    )
                    self.assertEqual(
                        "Ethernet2",
                        factory.call_args.kwargs["tcp_dump_capture_interface_ibgp"],
                    )
                    self.assertNotIn(
                        "tcp_dump_capture_interface_bgpmon",
                        factory.call_args.kwargs,
                    )

    def test_full_scale_factory_enables_churn_baseline_only_when_selected(
        self,
    ) -> None:
        inventory = MagicMock()
        inventory.device_name = "dut.example.com"
        compiled = SimpleNamespace(
            endpoints=[],
            host_os_type_map={},
            setup_tasks=[],
            teardown_tasks=[],
            basic_port_configs=[],
        )
        topology_target = (
            "neteng.test_infra.dne.taac.testconfigs.routing.factories."
            "bgp_ebb_full_scale.ebb_full_scale_topology"
        )
        playbooks_target = (
            "neteng.test_infra.dne.taac.testconfigs.routing.factories."
            "bgp_ebb_full_scale._get_bgp_ebb_full_scale_playbooks"
        )

        for selected, expected_churn, expected_ebgp_prefix_count, expected_shards in (
            (None, True, 850, True),
            (["bgp_ebb_attribute_churn_playbook"], True, 750, False),
            (["bgp_ebb_route_storm_playbook"], False, 750, True),
            (["bgp_ebb_route_registry_runtime_update_playbook"], False, 850, False),
        ):
            available_playbooks = []
            if selected:
                available_playbooks = [taac_types.Playbook(name=selected[0])]
            with (
                self.subTest(selected=selected),
                patch(playbooks_target, return_value=available_playbooks),
                patch(topology_target) as topology_factory,
            ):
                topology_factory.return_value.bind_to_inventory.return_value.compile.return_value = compiled
                create_bgp_ebb_full_scale_test_config(
                    inventory,
                    name="test",
                    playbooks_selected=selected,
                    profile=BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R,
                )

            self.assertEqual(
                expected_churn,
                topology_factory.call_args.kwargs["enable_attribute_churn"],
            )
            self.assertEqual(
                expected_ebgp_prefix_count,
                topology_factory.call_args.kwargs["ebgp_prefix_count"],
            )
            self.assertEqual(
                expected_shards,
                topology_factory.call_args.kwargs["route_storm_shards"],
            )
            self.assertIsNone(
                topology_factory.call_args.kwargs["ebgp_static_prefix_count"]
            )
            self.assertEqual(
                "STANDALONE",
                topology_factory.call_args.kwargs["openr_mode"].name,
            )

    def test_full_scale_factory_makes_auxiliary_observers_inventory_optional(
        self,
    ) -> None:
        compiled = SimpleNamespace(
            endpoints=[],
            host_os_type_map={},
            setup_tasks=[],
            teardown_tasks=[],
            basic_port_configs=[],
        )
        topology_target = (
            "neteng.test_infra.dne.taac.testconfigs.routing.factories."
            "bgp_ebb_full_scale.ebb_full_scale_topology"
        )
        playbooks_target = (
            "neteng.test_infra.dne.taac.testconfigs.routing.factories."
            "bgp_ebb_full_scale._get_bgp_ebb_full_scale_playbooks"
        )

        for port_count, expected_auxiliary_observers in ((2, False), (3, True)):
            inventory = MagicMock()
            inventory.ixia_ports = [
                [f"Ethernet{index}", f"1/{index}"] for index in range(1, port_count + 1)
            ]
            available = [taac_types.Playbook(name="bgp_ebb_attribute_churn_playbook")]
            with (
                self.subTest(port_count=port_count),
                patch(playbooks_target, return_value=available),
                patch(topology_target) as topology_factory,
            ):
                topology_factory.return_value.bind_to_inventory.return_value.compile.return_value = compiled
                create_bgp_ebb_full_scale_test_config(
                    inventory,
                    name="test",
                    playbooks_selected=["bgp_ebb_attribute_churn_playbook"],
                    profile=BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R,
                )

                self.assertEqual(
                    expected_auxiliary_observers,
                    topology_factory.call_args.kwargs["include_bgpmon"],
                )

    def test_bag012_stage1_uses_default_port_assignment(self) -> None:
        for config in (
            BAG012_STAGE1_FULL_SCALE_TEST_CONFIG_NO_UG,
            BAG012_STAGE1_FULL_SCALE_TEST_CONFIG_UG,
        ):
            with self.subTest(config=config.name):
                endpoint = next(
                    endpoint
                    for endpoint in config.endpoints
                    if endpoint.name == "bag012.ash6"
                )
                connections = endpoint.direct_ixia_connections
                self.assertIsNotNone(connections)
                assert connections is not None
                self.assertCountEqual(
                    [
                        ("Ethernet3/36/1", "8/1"),
                        ("Ethernet3/36/2", "8/2"),
                        ("Ethernet3/36/3", "8/3"),
                    ],
                    [
                        (connection.interface, connection.ixia_port)
                        for connection in connections
                    ],
                )

        route_storm = next(
            playbook
            for playbook in BAG012_STAGE1_FULL_SCALE_TEST_CONFIG_UG.playbooks
            if playbook.name == "bgp_ebb_route_storm_playbook"
        )
        payload = next(
            payload
            for payload in (
                _step_payload(step)
                for step in _sequential_steps(route_storm)
                if step.step_params is not None
                and step.step_params.json_params is not None
            )
            if payload.get("custom_step_name") == "bgp_route_storm"
        )
        self.assertEqual("Ethernet3/36/2", payload["ixia_interface_mimic_ibgp"])
        self.assertNotIn("ixia_interfaces_mimic_ibgp", payload)

    def test_full_scale_factory_rejects_invalid_playbook_selections(self) -> None:
        inventory = MagicMock()
        available = [taac_types.Playbook(name=name) for name in ("first", "second")]
        target = (
            "neteng.test_infra.dne.taac.testconfigs.routing.factories."
            "bgp_ebb_full_scale._get_bgp_ebb_full_scale_playbooks"
        )
        topology_target = (
            "neteng.test_infra.dne.taac.testconfigs.routing.factories."
            "bgp_ebb_full_scale.ebb_full_scale_topology"
        )
        topology = MagicMock()
        topology.bind_to_inventory.return_value = MagicMock()
        available_names = str(sorted(set(_TC7_PLAYBOOK_NAMES) | {"first", "second"}))

        for selected, message in (
            (
                ["unknown"],
                "Unknown BGP EBB playbook selections: ['unknown']; "
                f"available: {available_names}",
            ),
            (
                ["unknown", "also_unknown"],
                "Unknown BGP EBB playbook selections: ['unknown', 'also_unknown']; "
                f"available: {available_names}",
            ),
            (["first", "first"], "Duplicate BGP EBB playbook selections: ['first']"),
        ):
            with (
                self.subTest(selected=selected),
                patch(target, return_value=available),
                patch(topology_target, return_value=topology),
            ):
                with self.assertRaises(ValueError) as context:
                    create_bgp_ebb_full_scale_test_config(
                        inventory,
                        name="test",
                        playbooks_selected=selected,
                    )
                self.assertEqual(message, str(context.exception))

    def test_full_scale_factory_preserves_requested_playbook_order(self) -> None:
        inventory = MagicMock()
        inventory.device_name = "dut.example.com"
        compiled = SimpleNamespace(
            endpoints=[],
            host_os_type_map={},
            setup_tasks=[],
            teardown_tasks=[],
            basic_port_configs=[],
        )
        available = [
            taac_types.Playbook(name=name) for name in ("first", "second", "third")
        ]
        playbooks_target = (
            "neteng.test_infra.dne.taac.testconfigs.routing.factories."
            "bgp_ebb_full_scale._get_bgp_ebb_full_scale_playbooks"
        )
        topology_target = (
            "neteng.test_infra.dne.taac.testconfigs.routing.factories."
            "bgp_ebb_full_scale.ebb_full_scale_topology"
        )

        with (
            patch(playbooks_target, return_value=available),
            patch(topology_target) as topology_factory,
        ):
            topology_factory.return_value.bind_to_inventory.return_value.compile.return_value = compiled
            test_config = create_bgp_ebb_full_scale_test_config(
                inventory,
                name="test",
                playbooks_selected=["third", "first"],
            )

        self.assertEqual(
            ["third", "first"],
            [playbook.name for playbook in test_config.playbooks],
        )
