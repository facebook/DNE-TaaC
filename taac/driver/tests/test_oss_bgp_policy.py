# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

import json
import unittest

from configerator.structs.neteng.robotron.bgp_policy.thrift_types import (
    BgpAttrChangeActionType,
    BgpPolicyActionType,
    BgpPolicyAtomicMatchType,
    CommunityType,
    FlowControlAction,
)
from configerator.structs.neteng.robotron.routing_policy.thrift_types import (
    BooleanOperator,
    ComparisonOperator,
    MatchValueLogicOperator,
)
from taac.driver import oss_bgp_policy
from pyre_extensions import none_throws

# Shaped like the statements InjectBgpPolicyStatements sends: thrift field names,
# enums as their integer values.
_TERM = {
    "name": "TERM_1",
    "term_miss_action": 3,
    "match_logic_type": 2,
    "policy_action_entries": [
        {"type": 5, "action_type": {"flow_action": 1}},
        {
            "type": 3,
            "action_type": {"route_action": 3},
            "set_local_pref": {"local_pref": 200, "boolean_operator": 2},
        },
        {
            "type": 2,
            "community_list": {
                "community_list": {
                    "name": "ADD",
                    "members": [{"community_name": "C1"}],
                }
            },
        },
    ],
    "policy_matches": [
        {
            "match_logic_type": 1,
            "match_entries": [
                {
                    "type": 5,
                    "prefix_list": {
                        "prefix_list": {
                            "prefixes": [
                                {
                                    "base_prefix": "2001:db8::/32",
                                    "prefix_len_ranges": [
                                        {"value": 48, "compare_operator": 3}
                                    ],
                                }
                            ]
                        }
                    },
                },
                {
                    "type": 3,
                    "community_list": {
                        "community_list": {
                            "members": [{"type": 1, "name": "C2", "value": "65000:2"}]
                        }
                    },
                },
            ],
        }
    ],
}


class CreatePolicyStatementTest(unittest.TestCase):
    def test_statement_from_coop_args(self) -> None:
        statement = oss_bgp_policy.create_policy_statement(
            {
                "name": "PROPAGATE_X_OUT",
                "description": "d",
                "policy_entries": json.dumps([_TERM]),
            }
        )
        self.assertEqual("PROPAGATE_X_OUT", statement.name)
        (term,) = statement.policy_entries
        self.assertEqual(FlowControlAction.NEXT_TERM, term.term_miss_action)
        self.assertEqual(BooleanOperator.OR, term.match_logic_type)

        permit, local_pref, community = term.policy_action_entries
        self.assertEqual(BgpPolicyActionType.PERMIT, permit.type)
        self.assertEqual(
            FlowControlAction.ACCEPT, none_throws(permit.action_type).flow_action
        )
        self.assertEqual(
            BgpAttrChangeActionType.SET_LOCAL_PREF,
            none_throws(local_pref.action_type).route_action,
        )
        self.assertEqual(200, none_throws(local_pref.set_local_pref).local_pref)
        community_list = none_throws(community.community_list).community_list
        self.assertEqual("ADD", community_list.name)
        self.assertEqual(
            ["C1"], [m.community_name for m in none_throws(community_list.members)]
        )

        (match,) = none_throws(term.policy_matches)
        prefix_match, community_match = match.match_entries
        self.assertEqual(BgpPolicyAtomicMatchType.PREFIX_LIST, prefix_match.type)
        prefix_list = none_throws(prefix_match.prefix_list).prefix_list
        # COOP's defaults where the input leaves a field out.
        self.assertEqual(BooleanOperator.OR, prefix_list.boolean_operator)
        self.assertEqual(1, prefix_list.version)
        (entry,) = none_throws(prefix_list.prefixes)
        self.assertEqual(MatchValueLogicOperator.EQUAL, entry.match_logic)
        self.assertEqual(
            ComparisonOperator.LE,
            none_throws(entry.prefix_len_ranges)[0].compare_operator,
        )
        members = none_throws(
            none_throws(community_match.community_list).community_list.members
        )
        self.assertEqual(CommunityType.NORMAL, members[0].community.type)
        self.assertEqual("65000:2", members[0].community.value)

    def test_policy_entries_may_be_a_list(self) -> None:
        statement = oss_bgp_policy.create_policy_statement(
            {"name": "S", "description": "", "policy_entries": [_TERM]}
        )
        self.assertEqual(["TERM_1"], [t.name for t in statement.policy_entries])

    def test_unknown_values_fall_back_as_coop_does(self) -> None:
        term = oss_bgp_policy.create_policy_term(
            {
                "term_miss_action": 99,
                "match_logic_type": 99,
                "policy_action_entries": [
                    {"type": 5, "action_type": {"flow_action": 99}},
                    {"type": 1, "action_type": {"route_action": 99}},
                ],
            }
        )
        self.assertEqual(FlowControlAction.NEXT_TERM, term.term_miss_action)
        self.assertEqual(BooleanOperator.AND, term.match_logic_type)
        flow, route = term.policy_action_entries
        self.assertEqual(
            FlowControlAction.ACCEPT, none_throws(flow.action_type).flow_action
        )
        self.assertEqual(
            BgpAttrChangeActionType.AS_PATH_PREPEND,
            none_throws(route.action_type).route_action,
        )

    def test_enums_may_be_given_by_name(self) -> None:
        term = oss_bgp_policy.create_policy_term({"term_miss_action": "DENY"})
        self.assertEqual(FlowControlAction.DENY, term.term_miss_action)

    def test_an_invalid_value_without_a_default_raises(self) -> None:
        with self.assertRaises(ValueError):
            oss_bgp_policy.create_policy_actions([{"type": 999}])


class MalformedPolicyEntriesTest(unittest.TestCase):
    def test_malformed_json_raises_instead_of_an_empty_statement(self) -> None:
        with self.assertRaisesRegex(ValueError, "not valid JSON"):
            oss_bgp_policy.create_policy_statement(
                {"name": "S", "description": "d", "policy_entries": "[{"}
            )


class MatchingPrefixTermTest(unittest.TestCase):
    def test_ingress_term_sets_local_pref(self) -> None:
        term = oss_bgp_policy.matching_prefix_term("5000::/16", is_in_stmt=True)
        entry = none_throws(term.policy_match_entries).match_entries[0]
        prefix = none_throws(none_throws(entry.prefix_filters).prefixes)[0]
        self.assertEqual("5000::/16", prefix.base_prefix)
        length = none_throws(prefix.prefix_len_ranges)[0]
        self.assertEqual(
            (ComparisonOperator.GE, 16), (length.compare_operator, length.value)
        )
        (action,) = term.policy_action_entries
        self.assertEqual(100, none_throws(action.set_local_pref).local_pref)

    def test_egress_term_only_matches(self) -> None:
        term = oss_bgp_policy.matching_prefix_term("5000::/16", is_in_stmt=False)
        self.assertEqual([], list(term.policy_action_entries))
