# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

"""
BGP Policy Generator Task for TAAC.

This module provides tasks for dynamically generating BGP policy statements
for scale testing and other use cases. The generated policies are written to
files and can be injected using InjectBgpPolicyStatements task.
"""

import typing as t

from taac.policy_generator.community_generator import (
    CommunityPolicyGenerator,
)
from taac.policy_generator.policy_writer import PolicyWriter
from taac.tasks.base_task import BaseTask


class GenerateCommunityBgpPolicyTask(BaseTask):
    """
    Generate BGP policy statements based on community matches.

    This task generates BGP policies with community match criteria and writes
    them to a JSON file. The generated policies can then be applied to devices
    using the InjectBgpPolicyStatements task.

    Example params:
        {
            "policy_name": "SCALE-TEST-IN",
            "direction": "ingress",  # or "egress"
            "community_start": 5000,
            "count": 200,
            "step": 1,
            "output_file": "/path/to/policy.json",
            "description": "Optional custom description",
            "custom_communities": ["65001:100", "65002:200"]  # Optional
        }
    """

    NAME = "generate_community_bgp_policy"

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        """
        Generate community-based BGP policy.

        Args:
            params: Dictionary containing:
                - policy_name: Name of the policy (required)
                - direction: "ingress" or "egress" (required)
                - community_start: Starting community value (required if not using custom_communities)
                - count: Number of community rules to generate (required if not using custom_communities)
                - step: Increment between communities (default: 1)
                - output_file: Path to output JSON file (required)
                - description: Optional policy description
                - custom_communities: Optional list of custom community strings
        """
        policy_name = params["policy_name"]
        direction = params["direction"]
        output_file = params["output_file"]

        community_start = params.get("community_start", 0)
        count = params.get("count", 0)
        step = params.get("step", 1)
        description = params.get("description")
        custom_communities = params.get("custom_communities")

        # Validate parameters
        if direction not in ["ingress", "egress"]:
            raise ValueError("direction must be either 'ingress' or 'egress'")

        if not custom_communities and (community_start == 0 or count == 0):
            raise ValueError(
                "Must provide either custom_communities or both community_start and count"
            )

        community_end = community_start + (count - 1) * step
        self.logger.info(
            f"Generating {direction} BGP policy '{policy_name}' "
            f"with {count} communities from {community_start}:{community_start} to {community_end}:{community_end}"
        )

        # Generate the policy
        generator = CommunityPolicyGenerator(
            policy_name=policy_name,
            direction=direction,
            community_start=community_start,
            count=count,
            step=step,
            description=description,
            custom_communities=custom_communities,
        )

        policy = generator.generate()

        # Write to file
        writer = PolicyWriter(output_file)
        writer.write_single(policy)

        num_entries = len(policy["policy_entries"])
        self.logger.info(
            f"Successfully generated policy '{policy_name}' with {num_entries} entries "
            f"to {output_file}"
        )


class GenerateMultipleCommunityBgpPoliciesTask(BaseTask):
    """
    Generate multiple community-based BGP policy statements in a single file.

    This task allows generating both ingress and egress policies (or multiple
    policies of any direction) and writing them all to one file.

    Example params:
        {
            "policies": [
                {
                    "policy_name": "SCALE-TEST-IN",
                    "direction": "ingress",
                    "community_start": 5000,
                    "community_end": 5199,
                    "step": 1,
                    "description": "Ingress scale test policy"
                },
                {
                    "policy_name": "SCALE-TEST-OUT",
                    "direction": "egress",
                    "community_start": 5000,
                    "community_end": 5199,
                    "step": 1,
                    "description": "Egress scale test policy"
                }
            ],
            "output_file": "/path/to/policies.json"
        }
    """

    NAME = "generate_multiple_community_bgp_policies"

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        """
        Generate multiple community-based BGP policies.

        Args:
            params: Dictionary containing:
                - policies: List of policy configurations (each with same params as GenerateCommunityBgpPolicyTask)
                - output_file: Path to output JSON file (required)
        """
        policies_config = params["policies"]
        output_file = params["output_file"]

        if not isinstance(policies_config, list) or len(policies_config) == 0:
            raise ValueError("policies must be a non-empty list")

        self.logger.info(
            f"Generating {len(policies_config)} BGP policies to {output_file}"
        )

        generated_policies = []

        for policy_config in policies_config:
            policy_name = policy_config["policy_name"]
            direction = policy_config["direction"]
            community_start = policy_config.get("community_start", 0)
            count = policy_config.get("count", 0)
            step = policy_config.get("step", 1)
            description = policy_config.get("description")
            custom_communities = policy_config.get("custom_communities")

            # Validate
            if direction not in ["ingress", "egress"]:
                raise ValueError(
                    f"direction must be either 'ingress' or 'egress' for policy {policy_name}"
                )

            if not custom_communities and (community_start == 0 or count == 0):
                raise ValueError(
                    f"Policy {policy_name}: Must provide either custom_communities or both community_start and count"
                )

            community_end = community_start + (count - 1) * step
            self.logger.info(
                f"Generating {direction} policy '{policy_name}' "
                f"with {count} communities from {community_start}:{community_start} to {community_end}:{community_end}"
            )

            # Generate the policy
            generator = CommunityPolicyGenerator(
                policy_name=policy_name,
                direction=direction,
                community_start=community_start,
                count=count,
                step=step,
                description=description,
                custom_communities=custom_communities,
            )

            policy = generator.generate()
            generated_policies.append(policy)

            num_entries = len(policy["policy_entries"])
            self.logger.info(
                f"Generated policy '{policy_name}' with {num_entries} entries"
            )

        # Write all policies to file
        writer = PolicyWriter(output_file)
        writer.write(generated_policies)

        self.logger.info(
            f"Successfully wrote {len(generated_policies)} policies to {output_file}"
        )


class GenerateCommunityBgpPolicyAndInjectTask(BaseTask):
    """
    Generate and immediately inject community-based BGP policy to a device.

    This task combines policy generation and injection into a single step.
    It generates the policy, writes it to a file, and applies it to the device.

    Example params:
        {
            "hostname": "rsw001.p001.f01.abc1",
            "policy_name": "SCALE-TEST-IN",
            "direction": "ingress",
            "community_start": 5000,
            "community_end": 5199,
            "step": 1,
            "output_file": "/tmp/generated_policy.json",
            "config_name": "bgpcpp",
            "description": "Optional custom description"
        }
    """

    NAME = "generate_and_inject_community_bgp_policy"

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        """
        Generate and inject community-based BGP policy.

        Args:
            params: Dictionary containing all parameters from GenerateCommunityBgpPolicyTask
                    plus hostname and config_name for injection
        """
        # Import here to avoid circular dependency
        from taac.tasks.all import InjectBgpPolicyStatements

        hostname = params["hostname"]
        config_name = params.get("config_name", "bgpcpp")
        output_file = params["output_file"]

        # Step 1: Generate the policy
        self.logger.info(f"Step 1: Generating BGP policy for {hostname}")
        generate_task = GenerateCommunityBgpPolicyTask(logger=self.logger)
        await generate_task.run(params)

        # Step 2: Inject the policy
        self.logger.info(f"Step 2: Injecting BGP policy to {hostname}")
        inject_task = InjectBgpPolicyStatements(logger=self.logger)

        inject_params = {
            "hostname": hostname,
            "file_path": output_file,
            "config_name": config_name,
        }

        await inject_task.run(inject_params)

        self.logger.info(
            f"Successfully generated and injected BGP policy to {hostname}"
        )
