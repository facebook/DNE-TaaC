# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-strict

"""BGP policy statements built from COOP's patcher arguments, as immutable thrift.

A port of the ``_create_policy_*`` helpers in COOP's ``patchers.py``, which the
``add_bgp_policy_statement`` and
``add_bgp_policy_match_prefix_to_propagate_routes`` patchers use. The input is
thrift-shaped dicts with enums as their integer values; a missing or unknown
value falls back to the same per-field default COOP uses, which is not always
thrift's own default.
"""

from __future__ import annotations

import json
import typing as t

from configerator.structs.neteng.robotron.bgp_policy.thrift_types import (
    BgpAttrChangeActionType,
    BgpPolicyAction,
    BgpPolicyActionType,
    BgpPolicyActionTypes,
    BgpPolicyAtomicMatch,
    BgpPolicyAtomicMatchType,
    BgpPolicyMatch,
    BgpPolicyStatement,
    BgpPolicyTerm,
    Community,
    CommunityAction,
    CommunityActionType,
    CommunityList,
    CommunityListType,
    CommunityRefType,
    CommunityType,
    FlowControlAction,
    LocalPreference,
    Origin,
    SetAsPathPrepend,
    SetNextHop,
)
from configerator.structs.neteng.robotron.routing_policy.thrift_types import (
    BooleanOperator,
    CompareNumericValue,
    ComparisonOperator,
    MatchValueLogicOperator,
    NextHop,
    PrefixList,
    PrefixListEntry,
    PrefixListType,
)
from thrift.python.types import Enum


_E = t.TypeVar("_E", bound=Enum)
_Data = t.Mapping[str, t.Any]


def _enum(cls: t.Type[_E], value: t.Any, default: t.Optional[_E] = None) -> _E:
    """``value`` as a member of ``cls``: an integer value or a member name.
    Anything else is ``default``, or an error when there is none."""
    if isinstance(value, cls):
        return value
    member: t.Any = None
    if isinstance(value, str):
        member = getattr(cls, value, None)
    else:
        try:
            member = cls(value)
        except (ValueError, TypeError):
            pass
    if isinstance(member, cls):
        return member
    if default is None:
        raise ValueError(f"{value!r} is not a valid {cls.__name__}")
    return default


def parse_policy_entries(data: t.Union[str, t.Sequence[t.Any]]) -> t.List[t.Any]:
    if isinstance(data, str):
        try:
            return json.loads(data)
        except json.JSONDecodeError as e:
            # COOP logs and installs a statement with no terms; a policy that
            # silently matches nothing changes routing without a trace.
            raise ValueError(f"policy_entries is not valid JSON: {e}") from e
    return list(data)


def create_policy_statement(my_args: _Data) -> BgpPolicyStatement:
    return BgpPolicyStatement(
        name=my_args["name"],
        description=my_args["description"],
        policy_entries=[
            create_policy_term(entry)
            for entry in parse_policy_entries(my_args.get("policy_entries", []))
        ],
    )


def create_policy_term(entry: _Data) -> BgpPolicyTerm:
    fields: t.Dict[str, t.Any] = {
        "name": entry.get("name", ""),
        "description": entry.get("description", ""),
    }
    if "term_miss_action" in entry:
        fields["term_miss_action"] = _enum(
            FlowControlAction,
            entry["term_miss_action"],
            FlowControlAction.NEXT_TERM,
        )
    if "match_logic_type" in entry:
        fields["match_logic_type"] = _enum(
            BooleanOperator, entry["match_logic_type"], BooleanOperator.AND
        )
    if entry.get("policy_action_entries"):
        fields["policy_action_entries"] = create_policy_actions(
            entry["policy_action_entries"]
        )
    if entry.get("policy_match_entries"):
        fields["policy_match_entries"] = create_policy_match(
            entry["policy_match_entries"]
        )
    if entry.get("policy_matches"):
        fields["policy_matches"] = [
            create_policy_match(match) for match in entry["policy_matches"]
        ]
    return BgpPolicyTerm(**fields)


def _action_type(data: _Data) -> t.Optional[BgpPolicyActionTypes]:
    if "flow_action" in data:
        return BgpPolicyActionTypes(
            flow_action=_enum(
                FlowControlAction, data["flow_action"], FlowControlAction.ACCEPT
            )
        )
    if "route_action" in data:
        return BgpPolicyActionTypes(
            route_action=_enum(
                BgpAttrChangeActionType,
                data["route_action"],
                BgpAttrChangeActionType.AS_PATH_PREPEND,
            )
        )
    return None


def _set_nexthop(data: _Data) -> SetNextHop:
    fields: t.Dict[str, t.Any] = {}
    if "set_self" in data:
        set_self = data["set_self"]
        fields["set_self"] = (
            set_self.lower() == "true" if isinstance(set_self, str) else set_self
        )
    next_hop = data.get("next_hop")
    if isinstance(next_hop, dict):
        fields["next_hop"] = NextHop(
            **{k: next_hop[k] for k in ("version", "next_hop_prefix") if k in next_hop}
        )
    return SetNextHop(**fields)


def _local_pref(data: _Data) -> LocalPreference:
    fields: t.Dict[str, t.Any] = {
        k: data[k] for k in ("name", "description", "local_pref") if k in data
    }
    if "boolean_operator" in data:
        fields["boolean_operator"] = _enum(
            BooleanOperator, data["boolean_operator"], BooleanOperator.OR
        )
    return LocalPreference(**fields)


def _community_action(data: _Data) -> CommunityAction:
    fields: t.Dict[str, t.Any] = {
        k: data[k] for k in ("name", "description") if k in data
    }
    if isinstance(data.get("communities"), list):
        fields["communities"] = data["communities"]
    if "action_type" in data:
        fields["action_type"] = _enum(CommunityActionType, data["action_type"])
    return CommunityAction(**fields)


def create_policy_actions(  # noqa: C901
    actions: t.Sequence[_Data],
) -> t.List[BgpPolicyAction]:
    policy_actions = []
    for action in actions:
        fields: t.Dict[str, t.Any] = {}
        if "action_type" in action:
            action_type = _action_type(action["action_type"])
            if action_type is not None:
                fields["action_type"] = action_type
        if "type" in action:
            fields["type"] = _enum(BgpPolicyActionType, action["type"])
        if "next_term_id" in action:
            fields["next_term_id"] = action["next_term_id"]
        if "set_origin" in action:
            fields["set_origin"] = _enum(Origin, action["set_origin"])
        prepend = action.get("set_as_path_prepend")
        if isinstance(prepend, dict):
            fields["set_as_path_prepend"] = SetAsPathPrepend(
                **{k: prepend[k] for k in ("asn", "repeat_times") if k in prepend}
            )
        if isinstance(action.get("community_action"), dict):
            fields["community_action"] = _community_action(action["community_action"])
        community_list = action.get("community_list")
        if isinstance(community_list, dict) and isinstance(
            community_list.get("community_list"), dict
        ):
            fields["community_list"] = CommunityListType(
                community_list=_action_community_list(community_list["community_list"])
            )
        if isinstance(action.get("as_path_overwrite_list"), list):
            fields["as_path_overwrite_list"] = action["as_path_overwrite_list"]
        if isinstance(action.get("set_nexthop"), dict):
            fields["set_nexthop"] = _set_nexthop(action["set_nexthop"])
        if isinstance(action.get("set_local_pref"), dict):
            fields["set_local_pref"] = _local_pref(action["set_local_pref"])
        policy_actions.append(BgpPolicyAction(**fields))
    return policy_actions


def create_policy_match(data: _Data) -> BgpPolicyMatch:
    fields: t.Dict[str, t.Any] = {
        "name": data.get("name", ""),
        "description": data.get("description", ""),
        "match_logic_type": _enum(BooleanOperator, data.get("match_logic_type", 1)),
    }
    if "match_entries" in data:
        fields["match_entries"] = [
            create_atomic_match(entry) for entry in data["match_entries"]
        ]
    return BgpPolicyMatch(**fields)


def create_atomic_match(data: _Data) -> BgpPolicyAtomicMatch:
    fields: t.Dict[str, t.Any] = {
        "type": _enum(BgpPolicyAtomicMatchType, data["type"]),
    }
    if "community_list" in data:
        fields["community_list"] = _community_list_type(data["community_list"])
    if "communities_filter" in data:
        fields["communities_filter"] = _community_list(
            data["communities_filter"], boolean_default=BooleanOperator.OR
        )
    if "prefix_list" in data:
        fields["prefix_list"] = _prefix_list_type(data["prefix_list"])
    if "prefix_filters" in data:
        fields["prefix_filters"] = _prefix_list(data["prefix_filters"])
    if "match_logic_type" in data:
        fields["match_logic_type"] = _enum(
            MatchValueLogicOperator,
            data["match_logic_type"],
            MatchValueLogicOperator.EQUAL,
        )
    return BgpPolicyAtomicMatch(**fields)


def _prefix_entry(data: _Data) -> PrefixListEntry:
    fields: t.Dict[str, t.Any] = {
        "base_prefix": data.get("base_prefix", ""),
        "match_logic": _enum(
            MatchValueLogicOperator,
            data.get("match_logic", 0),
            MatchValueLogicOperator.EQUAL,
        ),
    }
    if "prefix_len_ranges" in data:
        fields["prefix_len_ranges"] = [
            CompareNumericValue(
                value=r.get("value", 0),
                compare_operator=_enum(
                    ComparisonOperator,
                    r.get("compare_operator", 1),
                    ComparisonOperator.EQ,
                ),
            )
            for r in data["prefix_len_ranges"]
        ]
    return PrefixListEntry(**fields)


def _prefix_list(data: _Data) -> PrefixList:
    fields: t.Dict[str, t.Any] = {
        "name": data.get("name", ""),
        "description": data.get("description", ""),
        "version": data.get("version", 1),
        "boolean_operator": _enum(
            BooleanOperator, data.get("boolean_operator", 2), BooleanOperator.OR
        ),
    }
    if "prefixes" in data:
        fields["prefixes"] = [_prefix_entry(p) for p in data["prefixes"]]
    if "prefix_list_names" in data:
        fields["prefix_list_names"] = data["prefix_list_names"]
    return PrefixList(**fields)


def _prefix_list_type(data: _Data) -> PrefixListType:
    if "prefix_list" in data:
        return PrefixListType(prefix_list=_prefix_list(data["prefix_list"]))
    if "prefix_list_name" in data:
        return PrefixListType(prefix_list_name=data["prefix_list_name"])
    return PrefixListType(prefix_list=_prefix_list({}))


def _community_list(
    data: _Data, boolean_default: t.Optional[BooleanOperator]
) -> CommunityList:
    """For a match. ``boolean_default`` is what an absent or unknown
    ``boolean_operator`` becomes; ``None`` keeps COOP's behaviour for a
    ``community_list`` match: AND when absent, the value as given otherwise."""
    fields: t.Dict[str, t.Any] = {
        "name": data.get("name", ""),
        "description": data.get("description", ""),
        "boolean_operator": (
            _enum(BooleanOperator, data.get("boolean_operator", 1))
            if boolean_default is None
            else _enum(
                BooleanOperator, data.get("boolean_operator", 2), boolean_default
            )
        ),
    }
    if "communities" in data:
        fields["communities"] = data["communities"]
    if "members" in data:
        fields["members"] = create_community_members(data["members"])
    return CommunityList(**fields)


def _action_community_list(data: _Data) -> CommunityList:
    fields: t.Dict[str, t.Any] = {
        k: data[k] for k in ("name", "description") if k in data
    }
    if "boolean_operator" in data:
        fields["boolean_operator"] = _enum(BooleanOperator, data["boolean_operator"])
    if isinstance(data.get("members"), list):
        fields["members"] = create_community_members(data["members"])
    return CommunityList(**fields)


def _community_list_type(data: _Data) -> CommunityListType:
    if "community_list" in data:
        return CommunityListType(
            community_list=_community_list(data["community_list"], boolean_default=None)
        )
    if "community_list_name" in data:
        return CommunityListType(community_list_name=data["community_list_name"])
    return CommunityListType(community_list_name="")


def _community(data: _Data) -> Community:
    return Community(
        type=_enum(CommunityType, data["type"]),
        name=data["name"],
        value=data["value"],
    )


def create_community_members(
    members: t.Sequence[_Data],
) -> t.List[CommunityRefType]:
    refs = []
    for member in members:
        if "community" in member:
            refs.append(CommunityRefType(community=_community(member["community"])))
        elif "community_name" in member:
            refs.append(CommunityRefType(community_name=member["community_name"]))
        elif {"type", "name", "value"} <= member.keys():
            refs.append(CommunityRefType(community=_community(member)))
    return refs


def matching_prefix_term(matching_prefix: str, is_in_stmt: bool) -> BgpPolicyTerm:
    """COOP's ``_create_matching_prefix_patchers`` for one prefix: match the
    prefix and anything longer; an ingress term also sets local-pref 100."""
    actions = (
        [
            BgpPolicyAction(
                type=BgpPolicyActionType.SET_LOCAL_PREF,
                action_type=BgpPolicyActionTypes(
                    route_action=BgpAttrChangeActionType.SET_LOCAL_PREF
                ),
                set_local_pref=LocalPreference(
                    local_pref=100, boolean_operator=BooleanOperator.OR
                ),
            )
        ]
        if is_in_stmt
        else []
    )
    return BgpPolicyTerm(
        policy_match_entries=BgpPolicyMatch(
            match_entries=[
                BgpPolicyAtomicMatch(
                    type=BgpPolicyAtomicMatchType.PREFIX_LIST,
                    prefix_filters=PrefixList(
                        prefixes=[
                            PrefixListEntry(
                                base_prefix=matching_prefix,
                                prefix_len_ranges=[
                                    CompareNumericValue(
                                        compare_operator=ComparisonOperator.GE,
                                        value=int(matching_prefix.split("/")[1]),
                                    )
                                ],
                            )
                        ]
                    ),
                )
            ]
        ),
        policy_action_entries=actions,
    )
