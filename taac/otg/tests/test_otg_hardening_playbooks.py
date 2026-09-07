# pyre-unsafe
"""Unit tests for the OTG hardening playbook factories
(``taac/otg/otg_hardening_playbooks.py``).

Each factory is verified for:
- Expected playbook ``name`` (including the two deliberate deviations from
  upstream — see the design doc's fidelity analysis).
- Stage and cleanup step composition.
- Required postcheck CheckNames present.
- ixia API step names and args propagated into the JSON params.
- The CPU-queue stage/step IDs the snapshot checkpoints reference by string.

The test configs themselves are NOT unit-tested — they exist to be run against a
real DUT and OTG endpoint.  Validate one with a dry run:

  ./docker/run_taac_docker.sh --regen run env TAAC_OSS=1 \\
      python3 -m taac.runner.oss_entry_point \\
      --test-configs /workspace/taac/otg/otg_hardening_restarts_test_config.py \\
      --dut device \\
      --device-info-csv /workspace/examples/topology/otg_hardening_device_info.csv \\
      --circuit-info-csv /workspace/examples/topology/otg_hardening_circuit_info.csv \\
      --dry-run
"""

import json
import re
import unittest

from taac.otg import otg_hardening_playbooks as hp


RESTART_PLAYBOOKS = (
    "test_agent_warmboot",
    "test_bgpd_restart",
    "test_qsfp_service_restart",
    "test_fsdb_restart",
)


def _json_params(obj):
    """Decode a Step's or HealthCheck's step_params/check_params JSON blob."""
    params = getattr(obj, "step_params", None) or getattr(obj, "check_params", None)
    raw = getattr(params, "json_params", None) if params else None
    return json.loads(raw) if raw else {}


def _api_steps(steps):
    """[(api_name, args_dict)] for each InvokeIxiaApi step in `steps`.

    ixia API args are double-encoded: the step's json_params carries an
    `args_json` string that is itself JSON.
    """
    out = []
    for step in steps or []:
        params = _json_params(step)
        if "api_name" in params:
            out.append(
                (params["api_name"], json.loads(params.get("args_json") or "{}"))
            )
    return out


def _check_names(checks):
    return [str(c.name) for c in (checks or [])]


def _checkpoint_ids(check):
    """Both checkpoint anchors on a snapshot check, unset ones dropped."""
    return [
        cid
        for cid in (
            check.pre_snapshot_checkpoint_id,
            check.post_snapshot_checkpoint_id,
        )
        if cid
    ]


class DeviceGroupRegexContractTest(unittest.TestCase):
    """The playbooks address device groups by regex; the test config names them.
    A mismatch fails *silently* — toggle_device_groups logs a warning, returns,
    and the playbook reports green having done nothing.

    Drift is prevented by construction: both the regexes and the name builder
    live in otg_hardening_playbooks, and the config imports them rather than
    restating the strings.  These tests verify that shared definition is
    self-consistent, which is all that remains to check.
    """

    def all_names(self):
        """Every device group name the config can produce, both ports."""
        return [
            hp.device_group_name(prefix, port)
            for port in (0, 1)
            for prefix in (
                hp.MEASURED_DEVICE_GROUP_PREFIX,
                hp.ECMP_1_DEVICE_GROUP_PREFIX,
                hp.ECMP_2_DEVICE_GROUP_PREFIX,
                hp.MALFORMED_BGP_DEVICE_GROUP_PREFIX,
            )
        ]

    def test_ecmp_2_regex_matches_only_the_ecmp_2_groups(self):
        matched = [
            n for n in self.all_names() if re.search(hp.ECMP_2_DEVICE_GROUP_REGEX, n)
        ]
        self.assertEqual(
            matched,
            [
                hp.device_group_name(hp.ECMP_2_DEVICE_GROUP_PREFIX, 0),
                hp.device_group_name(hp.ECMP_2_DEVICE_GROUP_PREFIX, 1),
            ],
        )

    def test_ecmp_2_regex_does_not_match_ecmp_1(self):
        """ECMP_1 must stay up: it supplies the baseline next-hops that the
        member/group overload is measured against."""
        self.assertIsNone(
            re.search(
                hp.ECMP_2_DEVICE_GROUP_REGEX,
                hp.device_group_name(hp.ECMP_1_DEVICE_GROUP_PREFIX, 0),
            )
        )

    def test_ecmp_2_regex_does_not_match_the_measured_path(self):
        """Over-matching would toggle down the path whose loss is asserted."""
        self.assertIsNone(
            re.search(
                hp.ECMP_2_DEVICE_GROUP_REGEX,
                hp.device_group_name(hp.MEASURED_DEVICE_GROUP_PREFIX, 0),
            )
        )

    def test_malformed_bgp_regex_matches_only_the_malformed_groups(self):
        matched = [
            n
            for n in self.all_names()
            if re.search(hp.MALFORMED_BGP_DEVICE_GROUP_REGEX, n)
        ]
        self.assertEqual(
            matched,
            [
                hp.device_group_name(hp.MALFORMED_BGP_DEVICE_GROUP_PREFIX, 0),
                hp.device_group_name(hp.MALFORMED_BGP_DEVICE_GROUP_PREFIX, 1),
            ],
        )

    def test_malformed_bgp_regex_does_not_match_the_measured_path(self):
        """Toggling this group is what replays the malformed UPDATEs; matching
        the measured path would flap it and void its packet-loss check."""
        for prefix in (
            hp.MEASURED_DEVICE_GROUP_PREFIX,
            hp.ECMP_1_DEVICE_GROUP_PREFIX,
            hp.ECMP_2_DEVICE_GROUP_PREFIX,
        ):
            self.assertIsNone(
                re.search(
                    hp.MALFORMED_BGP_DEVICE_GROUP_REGEX,
                    hp.device_group_name(prefix, 0),
                ),
                prefix,
            )

    def test_every_prefix_yields_a_distinct_name(self):
        names = self.all_names()
        self.assertEqual(len(names), len(set(names)), names)

    def test_names_are_per_port(self):
        self.assertNotEqual(
            hp.device_group_name(hp.ECMP_2_DEVICE_GROUP_PREFIX, 0),
            hp.device_group_name(hp.ECMP_2_DEVICE_GROUP_PREFIX, 1),
        )


class HardeningPlaybookSetTest(unittest.TestCase):
    def setUp(self):
        self.playbooks = hp.create_otg_hardening_playbooks()
        self.by_name = {p.name: p for p in self.playbooks}

    def test_expected_playbooks_in_execution_order(self):
        """Exact list, because two of these names encode design decisions:

        - `test_bgp_malformed_packet_test` ships, but by a different mechanism
          than upstream: byte-exact UPDATE injection via BgpUpdateSequence
          rather than a NEXT_HOP attribute flag.
        - the member test is `test_otg_ecmp_member_overload_limit`, not
          `test_ecmp_member_overload_limit`.  It is a redesign, not a port —
          upstream's member pressure came from a COOP patcher — and the name
          must not claim otherwise.

        Order matters too: restarts run first, so the disruptive ECMP and
        CPU-queue tests operate on a DUT already known to survive process
        churn.
        """
        self.assertEqual(
            [p.name for p in self.playbooks],
            [
                *RESTART_PLAYBOOKS,
                "test_bgp_malformed_packet_test",
                "test_ecmp_group_overload_limit",
                "test_otg_ecmp_member_overload_limit",
                "test_cpu_high_priority_queue_overload",
            ],
        )

    def test_restart_iterations_are_plumbed(self):
        pbs = hp.create_otg_hardening_playbooks(process_restart_iterations=3)
        by_name = {p.name: p for p in pbs}
        for name in RESTART_PLAYBOOKS:
            self.assertEqual(by_name[name].stages[0].iteration, 3, name)

    def test_rogue_prefixes_reach_the_cpu_queue_snapshot_checks(self):
        pbs = hp.create_otg_hardening_playbooks(
            rogue_parent_prefixes_to_ignore=["2001:db8:dead::/80"]
        )
        pb = {p.name: p for p in pbs}["test_cpu_high_priority_queue_overload"]
        for check in pb.snapshot_checks:
            self.assertEqual(
                _json_params(check)["parent_prefixes_to_ignore"],
                ["2001:db8:dead::/80"],
            )


class ServiceRestartPlaybooksTest(unittest.TestCase):
    def setUp(self):
        self.by_name = {
            p.name: p for p in hp.create_otg_hardening_playbooks()
        }

    def test_all_restart_playbooks_assert_packet_loss(self):
        """These keep the measured path running, so loss is the core signal."""
        for name in RESTART_PLAYBOOKS:
            names = _check_names(self.by_name[name].postchecks)
            self.assertTrue(
                [n for n in names if "PACKET_LOSS" in n], f"{name}: {names}"
            )

    def test_all_restart_playbooks_check_service_restart(self):
        for name in RESTART_PLAYBOOKS:
            names = _check_names(self.by_name[name].postchecks)
            self.assertTrue(
                [n for n in names if "SERVICE_RESTART" in n], f"{name}: {names}"
            )

    def test_all_restart_playbooks_check_core_dumps(self):
        for name in RESTART_PLAYBOOKS:
            names = _check_names(self.by_name[name].postchecks)
            self.assertTrue(
                [n for n in names if "CORE_DUMP" in n], f"{name}: {names}"
            )

    def test_bgp_affecting_restarts_check_convergence(self):
        """Agent and bgpd restarts drop sessions; qsfp and fsdb do not."""
        for name in ("test_agent_warmboot", "test_bgpd_restart"):
            names = _check_names(self.by_name[name].postchecks)
            self.assertTrue(
                [n for n in names if "BGP_CONVERGENCE" in n], f"{name}: {names}"
            )

    def test_fsdb_restart_settles_rather_than_converges(self):
        """fsdb has no convergence step upstream; a short settle is enough."""
        steps = self.by_name["test_fsdb_restart"].stages[0].steps
        names = [str(s.name) for s in steps]
        self.assertTrue([n for n in names if "LONGEVITY" in n], names)
        self.assertFalse([n for n in names if "CONVERGENCE" in n], names)


class EcmpOverloadPlaybooksTest(unittest.TestCase):
    def setUp(self):
        self.by_name = {
            p.name: p for p in hp.create_otg_hardening_playbooks()
        }
        self.group = self.by_name["test_ecmp_group_overload_limit"]
        self.member = self.by_name["test_otg_ecmp_member_overload_limit"]

    def test_group_playbook_toggles_ecmp_2_up(self):
        apis = _api_steps(self.group.stages[0].steps)
        self.assertEqual(len(apis), 1)
        api_name, args = apis[0]
        self.assertEqual(api_name, "toggle_device_groups")
        self.assertTrue(args["enable"])
        self.assertEqual(
            args["device_group_name_regex"], hp.ECMP_2_DEVICE_GROUP_REGEX
        )

    def test_both_ecmp_playbooks_clean_up_by_toggling_down(self):
        """Leaving ECMP_2 up would corrupt every later playbook's baseline."""
        for name, pb in (
            ("group", self.group),
            ("member", self.member),
        ):
            apis = _api_steps(pb.cleanup_steps)
            self.assertEqual(len(apis), 1, name)
            api_name, args = apis[0]
            self.assertEqual(api_name, "toggle_device_groups", name)
            self.assertFalse(args["enable"], name)

    def test_member_playbook_restarts_the_agent(self):
        """The redesign asserts the agent survives member-table overflow."""
        names = [str(s.name) for s in self.member.stages[0].steps]
        self.assertTrue(
            [n for n in names if "SERVICE_INTERRUPTION" in n], names
        )
        self.assertTrue(
            [n for n in names if "SERVICE_CONVERGENCE" in n], names
        )
        self.assertTrue(
            [n for n in _check_names(self.member.postchecks)
             if "SERVICE_RESTART" in n]
        )

    def test_both_ecmp_playbooks_assert_packet_loss(self):
        """Existing traffic must keep forwarding while the tables are stressed.

        Both playbooks drive ECMP_2 up and then put the DUT under pressure — the
        group one by prefix count, the member one by restarting the agent with the
        next-hop count elevated. Without a packet-loss postcheck a run that
        black-holed the ECMP-routed prefixes would still pass on services being up
        and no core dumps, which is the weakest thing either test could claim.
        """
        for name, pb in (("group", self.group), ("member", self.member)):
            with self.subTest(playbook=name):
                names = _check_names(pb.postchecks)
                self.assertTrue([n for n in names if "PACKET_LOSS" in n], names)


class CpuHighPriorityQueueOverloadPlaybookTest(unittest.TestCase):
    def setUp(self):
        self.pb = hp.create_otg_cpu_high_priority_queue_overload_playbook()

    def test_floods_then_stops_then_restores_then_clears_stats(self):
        apis = _api_steps(self.pb.stages[0].steps)
        self.assertEqual(
            [a[0] for a in apis],
            [
                "enable_traffic",
                "enable_traffic",
                "enable_traffic",
                "clear_traffic_stats",
            ],
        )
        self.assertTrue(apis[0][1]["enable"], "start the CP flood")
        self.assertFalse(apis[1][1]["enable"], "stop the CP flood")
        self.assertTrue(apis[2][1]["enable"], "restore the measured path")
        self.assertEqual(
            apis[2][1]["regexes"],
            [hp.MEASURED_DEVICE_GROUP_PREFIX],
            "must not be None — that would transmit-start the flood again",
        )

    def test_restore_step_names_the_measured_path_not_everything(self):
        """`regexes=None` would transmit-start every flow, flood included.

        The settle step that both snapshot checks pivot on runs *after* this, so
        restarting the flood there would take the "sessions recovered" reading
        while the DUT is still being flooded — the one condition under which it
        measures nothing.
        """
        apis = _api_steps(self.pb.stages[0].steps)
        restore = apis[2][1]
        self.assertEqual(restore["regexes"], [hp.MEASURED_DEVICE_GROUP_PREFIX])
        self.assertTrue(restore["enable"])

    def test_targets_the_cp_flow(self):
        apis = _api_steps(self.pb.stages[0].steps)
        for api_name, args in apis[:2]:
            self.assertEqual(api_name, "enable_traffic")
            self.assertEqual(args["regexes"], [hp.HIGH_QUEUE_BGP_CP_TRAFFIC])

    def test_checkpoint_ids_match_stage_and_step_ids(self):
        """The snapshot checkpoints are string references into these IDs, so a
        rename on either side silently breaks checkpoint resolution."""
        expected = (
            f"stage.{hp.CPU_QUEUE_STAGE_ID}.step."
            f"{hp.CPU_QUEUE_SETTLE_STEP_ID}.end"
        )
        self.assertEqual(self.pb.stages[0].id, hp.CPU_QUEUE_STAGE_ID)
        step_ids = [s.id for s in self.pb.stages[0].steps if s.id]
        self.assertIn(hp.CPU_QUEUE_SETTLE_STEP_ID, step_ids)

        anchors = [
            cid
            for check in self.pb.snapshot_checks
            for cid in _checkpoint_ids(check)
        ]
        self.assertEqual(
            anchors,
            [expected, expected],
            "both snapshot checks should anchor at the settle step",
        )

    def test_has_two_bgp_session_snapshot_checks(self):
        """One asserts sessions did not flap during the flood; the other, with
        the flap check skipped, asserts they recovered afterwards."""
        self.assertEqual(len(self.pb.snapshot_checks or []), 2)
        for check in self.pb.snapshot_checks:
            self.assertIn("BGP_SESSION", str(check.name))

        skip_flags = [
            _json_params(c).get("skip_flap_check") for c in self.pb.snapshot_checks
        ]
        self.assertEqual(
            sorted(skip_flags, key=str),
            [None, True],
            "exactly one check should skip the flap assertion",
        )

    def test_has_no_packet_loss_postcheck(self):
        """enable_traffic stops the measured flows for the duration (matching
        restpy), so a packet-loss postcheck would fail by construction."""
        names = _check_names(self.pb.postchecks)
        self.assertFalse([n for n in names if "PACKET_LOSS" in n], names)

    def test_settle_step_runs_after_the_flood_stops(self):
        steps = self.pb.stages[0].steps
        settle_idx = next(
            i for i, s in enumerate(steps)
            if s.id == hp.CPU_QUEUE_SETTLE_STEP_ID
        )
        disable_idx = next(
            i for i, s in enumerate(steps)
            if _json_params(s).get("api_name") == "enable_traffic"
            and json.loads(_json_params(s).get("args_json") or "{}")["enable"]
            is False
        )
        self.assertGreater(settle_idx, disable_idx)


if __name__ == "__main__":
    unittest.main()
