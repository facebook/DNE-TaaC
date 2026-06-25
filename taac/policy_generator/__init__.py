# pyre-strict

"""
BGP Policy Generator Engine

This module provides a flexible framework for generating BGP policy statements
compatible with BGP++ and FBOSS. It supports various match criteria including
communities, AS paths, prefix lists, and more.

Example usage:
    from taac.policy_generator import CommunityPolicyGenerator

    generator = CommunityPolicyGenerator(
        policy_name="TEST-IN",
        direction="ingress",
        community_start=5000,
        community_end=5199,
        step=1,
    )
    policy_json = generator.generate()
"""

from taac.policy_generator.community_generator import (
    CommunityPolicyGenerator,
)
from taac.policy_generator.policy_writer import PolicyWriter

__all__ = [
    "CommunityPolicyGenerator",
    "PolicyWriter",
]
