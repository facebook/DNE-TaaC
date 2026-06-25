# pyre-strict

"""
Policy writer for BGP policy JSON files.

This module handles writing BGP policy statements to JSON files in the format
compatible with BGP++ and FBOSS.
"""

import json
import os
from typing import Any


class PolicyWriter:
    """
    Handles writing BGP policy statements to JSON files.

    This class manages the serialization and writing of policy statements
    to disk in the FBOSS-compatible JSON format.
    """

    def __init__(self, output_path: str) -> None:
        """
        Initialize the policy writer.

        Args:
            output_path: Path where the policy JSON file should be written
        """
        self.output_path = output_path

    def write(self, policies: list[dict[str, Any]]) -> None:
        """
        Write one or more policy statements to a JSON file.

        Args:
            policies: List of policy statement dictionaries

        Raises:
            IOError: If the file cannot be written
        """
        # Ensure directory exists
        os.makedirs(os.path.dirname(self.output_path), exist_ok=True)

        # Wrap policies in the required format
        output_data = {"bgp_policy_statements": policies}

        # Write to file
        with open(self.output_path, "w") as f:
            json.dump(output_data, f, indent=2)

    def write_single(self, policy: dict[str, Any]) -> None:
        """
        Write a single policy statement to a JSON file.

        Args:
            policy: Policy statement dictionary
        """
        self.write([policy])

    def append_to_existing(self, policy: dict[str, Any]) -> None:
        """
        Append a policy to an existing policy file.

        If the file doesn't exist, creates a new one.

        Args:
            policy: Policy statement dictionary to append

        Raises:
            IOError: If the file cannot be read or written
            json.JSONDecodeError: If the existing file is not valid JSON
        """
        existing_policies = []

        # Read existing policies if file exists
        if os.path.exists(self.output_path):
            with open(self.output_path, "r") as f:
                data = json.load(f)
                existing_policies = data.get("bgp_policy_statements", [])

        # Append new policy
        existing_policies.append(policy)

        # Write back
        self.write(existing_policies)

    @staticmethod
    def format_json_string(data: dict[str, Any]) -> str:
        """
        Format a dictionary as a JSON string.

        Args:
            data: Dictionary to format

        Returns:
            Formatted JSON string
        """
        return json.dumps(data, indent=2)
