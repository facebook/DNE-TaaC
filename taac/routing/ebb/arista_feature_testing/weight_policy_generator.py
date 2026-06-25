# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-strict

"""
BGP Weight Policy Generator for EOS BGP++.

This module generates BGP++ JSON policies that match communities and set weight values.
"""

from typing import Any

from taac.policy_generator.base import (
    MatchCriteriaBuilder,
    PolicyGenerator,
)


class CommunityMatchBuilder(MatchCriteriaBuilder):
    """Builds community-based match criteria for policy entries."""

    def __init__(self, community: str) -> None:
        """
        Initialize the community match builder.

        Args:
            community: Community string in format "asn:value" (e.g., "65001:10")
        """
        self.community: str = community
        self.community_name: str = f"COMM_{community.replace(':', '_')}"

    def build_match_entry(self) -> dict[str, Any]:
        """Build a community match entry."""
        community_member = {
            "community": {
                "type": 1,
                "name": self.community_name,
                "value": self.community,
            }
        }

        community_definition = {
            "name": self.community_name,
            "description": "",
            "communities": [self.community],
            "boolean_operator": 1,
            "members": [community_member],
        }

        return {
            "type": 3,
            "communities_filter": community_definition,
            "community_list": {"community_list": community_definition},
            "match_logic_type": 0,
        }


class WeightPolicyGenerator(PolicyGenerator):
    """
    Generate BGP policy that matches communities and sets weight values.

    This generator creates policy entries where each entry matches a specific
    BGP community and sets a corresponding weight value.

    Example:
        generator = WeightPolicyGenerator(
            policy_name="SET_WEIGHT_BY_COMMUNITY",
            direction="ingress",
            community_weight_map={
                "65001:10": 10,
                "65001:20": 20,
            },
        )
        policy = generator.generate()
    """

    def __init__(
        self,
        policy_name: str,
        direction: str,
        community_weight_map: dict[str, int],
        description: str | None = None,
    ) -> None:
        """
        Initialize the weight policy generator.

        Args:
            policy_name: Name of the policy (e.g., "SET_WEIGHT_BY_COMMUNITY")
            direction: Policy direction - "ingress" or "egress"
            community_weight_map: Dict mapping community strings to weight values
                                  e.g., {"65001:10": 10, "65001:20": 20}
            description: Optional custom description
        """
        super().__init__(policy_name, direction, description)
        self.community_weight_map = community_weight_map

    def _default_description(self) -> str:
        """Generate default description for weight policy."""
        return (
            f"{self.direction.capitalize()} policy that sets weight "
            f"based on community matching"
        )

    def _generate_policy_entries(self) -> list[dict[str, Any]]:
        """Generate policy entries for each community->weight mapping."""
        entries = []

        for idx, (community, weight) in enumerate(
            self.community_weight_map.items(), start=1
        ):
            entry = self._generate_weight_entry(idx, community, weight)
            entries.append(entry)

        return entries

    def _generate_weight_entry(
        self, rule_num: int, community: str, weight: int
    ) -> dict[str, Any]:
        """
        Generate a single policy entry that matches community and sets weight.

        Args:
            rule_num: Rule number for naming
            community: Community string (e.g., "65001:10")
            weight: Weight value to set

        Returns:
            Policy entry dictionary
        """
        builder = CommunityMatchBuilder(community)
        match_entry = builder.build_match_entry()

        direction_suffix = "IN" if self.direction == "ingress" else "OUT"

        return {
            "name": f"RULE_WEIGHT_{weight}_{direction_suffix}_{rule_num}",
            "description": (f"Match community {community} and set weight {weight}"),
            "policy_match_entries": {
                "name": "",
                "description": "",
                "match_logic_type": 1,
                "match_entries": [match_entry],
            },
            "policy_action_entries": [
                {
                    "type": 15,  # Weight action type
                    "weight_action": {
                        "weight_value": weight,
                        "weight_action_type": 1,  # Set weight
                    },
                },
                {
                    "type": 5,  # Flow action - accept
                    "action_type": {"flow_action": 1},
                },
            ],
            "term_miss_action": 3,
            "policy_matches": [
                {
                    "name": "",
                    "description": "",
                    "match_logic_type": 1,
                    "match_entries": [match_entry],
                }
            ],
            "policy_actions": [
                {
                    "type": 15,
                    "weight_action": {
                        "weight_value": weight,
                        "weight_action_type": 1,
                    },
                },
                {
                    "type": 5,
                    "action_type": {"flow_action": 1},
                },
            ],
        }


def generate_weight_policy_json(
    policy_name: str,
    community_weight_map: dict[str, int],
) -> dict[str, Any]:
    """
    Generate a complete BGP++ weight policy JSON structure.

    Args:
        policy_name: Name for the policy
        community_weight_map: Dict mapping communities to weight values

    Returns:
        Complete policy structure ready for BGP++ configuration

    Example:
        policy = generate_weight_policy_json(
            policy_name="SET_WEIGHT_BY_COMMUNITY",
            community_weight_map={
                "65001:10": 10,
                "65001:20": 20,
            },
        )
    """
    generator = WeightPolicyGenerator(
        policy_name=policy_name,
        direction="ingress",
        community_weight_map=community_weight_map,
    )
    return {"bgp_policy_statements": [generator.generate()]}
