# pyre-strict

"""
AS Path-based BGP policy generator.

This module provides functionality to generate BGP policy statements that match
on AS path attributes.
"""

from typing import Any

from taac.policy_generator.base import (
    MatchCriteriaBuilder,
    PolicyGenerator,
)


class AsPathMatchBuilder(MatchCriteriaBuilder):
    """Builds AS path-based match criteria for policy entries."""

    def __init__(self, as_path_regex: str, name: str | None = None) -> None:
        """
        Initialize the AS path match builder.

        Args:
            as_path_regex: AS path regex pattern (e.g., "^6500_")
            name: Optional name for the AS path filter
        """
        self.as_path_regex: str = as_path_regex
        self.filter_name: str = (
            name
            or f"AS_PATH_{as_path_regex.replace('^', '').replace('_', '').replace('$', '')}"
        )

    def build_match_entry(self) -> dict[str, Any]:
        """
        Build an AS path match entry.

        Returns:
            AS path match entry dictionary in FBOSS format
        """
        return {
            "type": 4,
            "as_path_filter": {
                "name": self.filter_name,
                "description": f"Match AS path: {self.as_path_regex}",
                "as_path_regex": self.as_path_regex,
            },
            "match_logic_type": 0,
        }


class AsPathPolicyGenerator(PolicyGenerator):
    """
    Generate BGP policy statements that match on AS path attributes.

    This generator creates policy entries where each entry matches a specific
    AS path regex pattern.

    Example:
        # Generate policy with AS path rules
        generator = AsPathPolicyGenerator(
            policy_name="ASPATH-FILTER-IN",
            direction="ingress",
            as_path_patterns=[
                "^6500_",
                "^32934_",
                "_15169$",
            ],
        )
        policy = generator.generate()
    """

    def __init__(
        self,
        policy_name: str,
        direction: str,
        as_path_patterns: list[str],
        description: str | None = None,
    ) -> None:
        """
        Initialize the AS path policy generator.

        Args:
            policy_name: Name of the policy (e.g., "ASPATH-FILTER-IN")
            direction: Policy direction - "ingress" or "egress"
            as_path_patterns: List of AS path regex patterns to match
            description: Optional custom description
        """
        super().__init__(policy_name, direction, description)
        self.as_path_patterns = as_path_patterns

    def _default_description(self) -> str:
        """Generate default description for AS path policy."""
        num_rules = len(self.as_path_patterns)
        return (
            f"{self.direction.capitalize()} policy with {num_rules} "
            f"AS path match statements"
        )

    def _generate_policy_entries(self) -> list[dict[str, Any]]:
        """
        Generate policy entries for each AS path pattern.

        Returns:
            List of policy entry dictionaries
        """
        entries = []

        for idx, pattern in enumerate(self.as_path_patterns, start=1):
            entry = self._generate_aspath_entry(idx, pattern)
            entries.append(entry)

        return entries

    def _generate_aspath_entry(self, rule_num: int, pattern: str) -> dict[str, Any]:
        """
        Generate a single policy entry for an AS path pattern.

        Args:
            rule_num: Rule number for naming
            pattern: AS path regex pattern (e.g., "^6500_")

        Returns:
            Policy entry dictionary
        """
        builder = AsPathMatchBuilder(pattern)
        match_entry = builder.build_match_entry()

        direction_suffix = "IN" if self.direction == "ingress" else "OUT"

        return {
            "name": f"RULE_ASPATH_{direction_suffix}_{rule_num}",
            "description": (
                f"{direction_suffix} policy for AS path {pattern} "
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
