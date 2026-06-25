# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe
"""Unit tests for ``create_fpf_link_event_disrupt_playbook`` ODS-check shape.

Covers the ``ods_discard_informational`` knob added for tc36 (STSW all
connections down): when True the disrupt playbook emits the same four
ODS-counter checks as ``_build_fpf_generic_checks`` with the two DISCARD
checks (``in_dst_null_discard``, ``in_discard``) marked informational and the
two CONGESTION checks (``in_congestion``, ``out_congestion``) kept hard. When
False the default behaviour is preserved (no four-check informational block;
the ``flip_discards=True`` path still emits the ``loss_expected`` peak check).
"""

import json
import unittest

from taac.playbooks.playbook_definitions import (
    _build_fpf_generic_checks,
    create_fpf_link_event_disrupt_playbook,
)


_GTSWS = ["gtsw001.l1002.c087.mwg2"]
_HOSTS = ["rtptest1555.mwg2"]
_TRIGGER_STSWS = ["stsw001.s001.l202.mwg2"]
_INJECTED_LANES = [0, 1]
_IMPACTED_LANES = [0]
_IMPACTED_BY_HOST_GPU = {"rtptest1555.mwg2": {0: [0]}}
_IMPACTED_BETHS = {"rtptest1555.mwg2": ["beth0"]}
_IMPACTED_PLANES = {"rtptest1555.mwg2": [0]}


def _build(**overrides):
    kwargs = {
        "gtsws": _GTSWS,
        "hosts": _HOSTS,
        "trigger_stsws": _TRIGGER_STSWS,
        "disruption_steps": [],
        "prefix_count": 1000,
        "community_list": "stsw",
        "stabilization_delay_sec": 10,
        "injected_lanes": _INJECTED_LANES,
        "impacted_lanes": _IMPACTED_LANES,
        "impacted_lanes_by_host_gpu": _IMPACTED_BY_HOST_GPU,
        "impacted_beths_by_host": _IMPACTED_BETHS,
        "impacted_planes_by_host": _IMPACTED_PLANES,
    }
    kwargs.update(overrides)
    return create_fpf_link_event_disrupt_playbook(**kwargs)


def _checks_by_id(playbook) -> dict:
    return {c.check_id: c for c in playbook.postchecks or [] if c.check_id}


def _params(check) -> dict:
    return json.loads(check.check_params.json_params)


class TestOdsDiscardInformationalKnob(unittest.TestCase):
    """The ``ods_discard_informational`` knob mirrors the service-restart
    playbook plumbing: the two DISCARD <= checks come in informational, the
    two CONGESTION <= checks stay hard."""

    def test_informational_true_emits_four_checks_with_correct_flags(self):
        pb = _build(
            flip_fsdb_session=False,
            flip_discards=False,
            ods_discard_informational=True,
        )
        by_id = _checks_by_id(pb)
        # All four ODS counter checks present.
        for cid in (
            "ods_in_dst_null_discard",
            "ods_in_discard",
            "ods_in_congestion",
            "ods_out_congestion",
        ):
            self.assertIn(cid, by_id, f"missing {cid}")
        # Discard checks: informational=True.
        self.assertIs(_params(by_id["ods_in_dst_null_discard"])["informational"], True)
        self.assertIs(_params(by_id["ods_in_discard"])["informational"], True)
        # Congestion checks: informational=False (or absent => default False).
        self.assertFalse(
            _params(by_id["ods_in_congestion"]).get("informational", False)
        )
        self.assertFalse(
            _params(by_id["ods_out_congestion"]).get("informational", False)
        )
        # The hard "loss expected" peak check (used by tc15/tc37) MUST NOT
        # coexist when the informational block is in use.
        self.assertNotIn("ods_in_discard_loss_expected", by_id)

    def test_informational_false_default_emits_no_four_check_block(self):
        # flip_discards=False (drain) AND ods_discard_informational=False
        # (default) -> no ODS discard/congestion checks at all from this block.
        pb = _build(
            flip_fsdb_session=False,
            flip_discards=False,
        )
        by_id = _checks_by_id(pb)
        for cid in (
            "ods_in_dst_null_discard",
            "ods_in_discard",
            "ods_in_congestion",
            "ods_out_congestion",
            "ods_in_discard_loss_expected",
        ):
            self.assertNotIn(cid, by_id, f"unexpected {cid}")

    def test_flip_discards_true_default_emits_loss_expected_check(self):
        # tc15/tc37 contract: flip_discards=True, ods_discard_informational=False
        # -> the hard "loss expected" peak check is present; the four-check
        # informational block is NOT added.
        pb = _build(
            flip_fsdb_session=True,
            flip_discards=True,
        )
        by_id = _checks_by_id(pb)
        self.assertIn("ods_in_discard_loss_expected", by_id)
        for cid in (
            "ods_in_dst_null_discard",
            "ods_in_discard",
            "ods_in_congestion",
            "ods_out_congestion",
        ):
            self.assertNotIn(cid, by_id, f"unexpected {cid}")
        # The loss-expected peak check is hard (not informational) and uses
        # max/any aggregation.
        loss = _params(by_id["ods_in_discard_loss_expected"])
        self.assertFalse(loss.get("informational", False))
        self.assertEqual(loss.get("aggregate"), "max")
        self.assertEqual(loss.get("require"), "any")


class TestBuildGenericChecksDiscardInformational(unittest.TestCase):
    """``_build_fpf_generic_checks`` (the helper shared by the
    hardening/service-restart playbooks) routes ``ods_discard_informational``
    to ONLY the two DISCARD ODS checks; the two CONGESTION checks stay hard.
    This is the same contract the link-event playbook reproduces inline."""

    def _generic_postchecks_by_id(self, *, ods_discard_informational: bool) -> dict:
        _, postchecks, _ = _build_fpf_generic_checks(
            hosts=_HOSTS,
            services=["fboss"],
            gtsws=_GTSWS,
            trigger_stsws=_TRIGGER_STSWS,
            # ODS discard/congestion checks are dropped in minimal (skip-SSH)
            # mode, so keep SSH checks ON to exercise the informational routing.
            skip_ssh_dependent_checks=False,
            fsdb_sessions_per_host=None,
            prod_prefixes=None,
            hrt_memory_hosts=None,
            hrt_driver_hosts=None,
            spray_hosts=None,
            ods_entities=None,
            ods_discard_informational=ods_discard_informational,
        )
        return {c.check_id: c for c in postchecks if c.check_id}

    def test_true_marks_only_the_two_discard_checks_informational(self):
        by_id = self._generic_postchecks_by_id(ods_discard_informational=True)
        for cid in (
            "ods_in_dst_null_discard",
            "ods_in_discard",
            "ods_in_congestion",
            "ods_out_congestion",
        ):
            self.assertIn(cid, by_id, f"missing {cid}")
        # ONLY the two discard checks are informational.
        self.assertIs(_params(by_id["ods_in_dst_null_discard"])["informational"], True)
        self.assertIs(_params(by_id["ods_in_discard"])["informational"], True)
        # Congestion checks stay hard.
        self.assertFalse(
            _params(by_id["ods_in_congestion"]).get("informational", False)
        )
        self.assertFalse(
            _params(by_id["ods_out_congestion"]).get("informational", False)
        )

    def test_false_default_keeps_all_four_checks_hard(self):
        by_id = self._generic_postchecks_by_id(ods_discard_informational=False)
        for cid in (
            "ods_in_dst_null_discard",
            "ods_in_discard",
            "ods_in_congestion",
            "ods_out_congestion",
        ):
            self.assertFalse(
                _params(by_id[cid]).get("informational", False),
                f"{cid} should be hard by default",
            )


if __name__ == "__main__":
    unittest.main()
