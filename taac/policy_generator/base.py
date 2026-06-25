# pyre-strict

"""
Base classes and interfaces for BGP policy generation.

This module defines the core abstractions for generating BGP policy statements
that are compatible with BGP++ and FBOSS.
"""

from abc import ABC, abstractmethod
from typing import Any


class PolicyGenerator(ABC):
    """
    Abstract base class for all policy generators.

    Each generator implementation should define how to create policy entries
    based on specific match criteria (communities, AS paths, prefixes, etc.).
    """

    def __init__(
        self,
        policy_name: str,
        direction: str,
        description: str | None = None,
    ) -> None:
        """
        Initialize the policy generator.

        Args:
            policy_name: Name of the policy (e.g., "SCALE-TEST-IN")
            direction: Policy direction - "ingress" or "egress"
            description: Optional description of the policy
        """
        self.policy_name: str = policy_name
        self.direction: str = direction
        self.description: str = description or self._default_description()

    @abstractmethod
    def _default_description(self) -> str:
        """Generate default description for this policy type."""
        pass

    @abstractmethod
    def _generate_policy_entries(self) -> list[dict[str, Any]]:
        """
        Generate the list of policy entries.

        Returns:
            List of policy entry dictionaries in FBOSS format
        """
        pass

    def generate(self) -> dict[str, Any]:
        """
        Generate the complete policy statement.

        Returns:
            Complete policy statement dictionary in FBOSS format
        """
        entries = self._generate_policy_entries()

        # Add final accept-all rule
        entries.append(self._generate_accept_all_entry())

        return {
            "name": self.policy_name,
            "description": self.description,
            "policy_version": "",
            "policy_entries": entries,
        }

    def _generate_accept_all_entry(self) -> dict[str, Any]:
        """
        Generate the final accept-all policy entry.

        Returns:
            Accept-all policy entry dictionary
        """
        return {
            "name": f"RULE_ACCEPT_ALL_{self.policy_name}",
            "description": f"Accept all remaining prefixes for {self.policy_name}",
            "policy_match_entries": {
                "name": "",
                "description": "",
                "match_logic_type": 1,
                "match_entries": [],
            },
            "policy_action_entries": [{"type": 5, "action_type": {"flow_action": 1}}],
            "term_miss_action": 3,
            "policy_matches": [
                {
                    "name": "",
                    "description": "",
                    "match_logic_type": 1,
                    "match_entries": [],
                }
            ],
            "policy_actions": [{"type": 5, "action_type": {"flow_action": 1}}],
        }


class MatchCriteriaBuilder(ABC):
    """
    Abstract base class for building match criteria in policy entries.

    Different match types (community, AS path, prefix) implement this interface.
    """

    @abstractmethod
    def build_match_entry(self) -> dict[str, Any]:
        """
        Build a match entry for use in policy_match_entries.

        Returns:
            Match entry dictionary in FBOSS format
        """
        pass
