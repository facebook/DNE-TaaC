# pyre-strict

"""
Community-based BGP policy generator.

This module provides functionality to generate BGP policy statements that match
on community attributes.
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
            community: Community string in format "asn:value" (e.g., "5000:5000")
        """
        self.community: str = community
        self.community_name: str = f"COMM_{community.replace(':', '_')}"

    def build_match_entry(self) -> dict[str, Any]:
        """
        Build a community match entry.

        Returns:
            Community match entry dictionary in FBOSS format
        """
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


class CommunityPolicyGenerator(PolicyGenerator):
    """
    Generate BGP policy statements that match on community attributes.

    This generator creates policy entries where each entry matches a specific
    BGP community value. Communities can be generated sequentially or with
    custom step values.

    Example:
        # Generate policy with 200 community rules
        generator = CommunityPolicyGenerator(
            policy_name="SCALE-TEST-IN",
            direction="ingress",
            community_start=5000,
            community_end=5199,
            step=1,
        )
        policy = generator.generate()
    """

    def __init__(
        self,
        policy_name: str,
        direction: str,
        community_start: int,
        count: int,
        step: int = 1,
        description: str | None = None,
        custom_communities: list[str] | None = None,
    ) -> None:
        """
        Initialize the community policy generator.

        Args:
            policy_name: Name of the policy (e.g., "SCALE-TEST-IN")
            direction: Policy direction - "ingress" or "egress"
            community_start: Starting community value (e.g., 5000)
            count: Number of community rules to generate (e.g., 200)
            step: Increment between community values (default: 1)
            description: Optional custom description
            custom_communities: Optional list of custom community strings
                              to use instead of auto-generated range
        """
        super().__init__(policy_name, direction, description)
        self.community_start = community_start
        self.count = count
        self.step = step
        self.custom_communities = custom_communities

    def _default_description(self) -> str:
        """Generate default description for community policy."""
        num_rules = self._calculate_num_rules()
        return (
            f"{self.direction.capitalize()} policy with {num_rules} "
            f"community match statements"
        )

    def _calculate_num_rules(self) -> int:
        """Calculate the number of rules that will be generated."""
        if self.custom_communities:
            return len(self.custom_communities)
        return self.count

    def _generate_communities(self) -> list[str]:
        """
        Generate the list of community strings.

        Returns:
            List of community strings in format "asn:value"
        """
        if self.custom_communities:
            return self.custom_communities

        communities = []
        current_value = self.community_start
        for _ in range(self.count):
            communities.append(f"{current_value}:{current_value}")
            current_value += self.step
        return communities

    def _generate_policy_entries(self) -> list[dict[str, Any]]:
        """
        Generate policy entries for each community.

        Returns:
            List of policy entry dictionaries
        """
        communities = self._generate_communities()
        entries = []

        for idx, community in enumerate(communities, start=1):
            entry = self._generate_community_entry(idx, community)
            entries.append(entry)

        return entries

    def _generate_community_entry(
        self, rule_num: int, community: str
    ) -> dict[str, Any]:
        """
        Generate a single policy entry for a community.

        Args:
            rule_num: Rule number for naming
            community: Community string (e.g., "5000:5000")

        Returns:
            Policy entry dictionary
        """
        builder = CommunityMatchBuilder(community)
        match_entry = builder.build_match_entry()

        direction_suffix = "IN" if self.direction == "ingress" else "OUT"

        return {
            "name": f"RULE_COMM_{direction_suffix}_{rule_num}",
            "description": (
                f"{direction_suffix} policy for community {community} "
                f"(statement {rule_num})"
            ),
            "policy_match_entries": {
                "name": "",
                "description": "",
                "match_logic_type": 1,
                "match_entries": [match_entry],
            },
            "policy_action_entries": [{"type": 5, "action_type": {"flow_action": 1}}],
            "term_miss_action": 3,
            "policy_matches": [
                {
                    "name": "",
                    "description": "",
                    "match_logic_type": 1,
                    "match_entries": [match_entry],
                }
            ],
            "policy_actions": [{"type": 5, "action_type": {"flow_action": 1}}],
        }
