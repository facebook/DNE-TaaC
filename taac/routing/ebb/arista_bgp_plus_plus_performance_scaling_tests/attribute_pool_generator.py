# pyre-unsafe
"""
Attribute Pool Generator for BGP++ Performance Tests

This module generates small, constant pools of BGP attributes (AS paths, communities,
extended communities) that can be used across different routes to test attribute storage efficiency.
"""

from typing import List


def generate_as_path_pool(
    count: int = 10, base_as: int = 65001, as_path_length: int = 3
) -> List[str]:
    """
    Generate a pool of AS paths for testing.

    Args:
        count: Number of AS paths to generate
        base_as: Starting AS number
        as_path_length: Length of each AS path (number of AS numbers). Default: 3

    Returns:
        List of AS path strings, where each path has the specified length

    Example:
        >>> generate_as_path_pool(count=3, base_as=65001, as_path_length=3)
        ['65001 65002 65003', '65004 65005 65006', '65007 65008 65009']

        >>> generate_as_path_pool(count=2, base_as=65001, as_path_length=5)
        ['65001 65002 65003 65004 65005', '65006 65007 65008 65009 65010']
    """
    as_paths = []
    as_offset = 0
    for _ in range(count):
        # Generate AS path with fixed length
        as_numbers = [str(base_as + as_offset + j) for j in range(as_path_length)]
        as_paths.append(" ".join(as_numbers))
        # Move to next AS block for next path
        as_offset += as_path_length
    return as_paths


def generate_community_pool(count: int = 20, base_community: int = 100) -> List[str]:
    """
    Generate a pool of standard BGP communities.

    Args:
        count: Number of communities to generate
        base_community: Base community number

    Returns:
        List of community strings in format "asn:value"

    Example:
        >>> generate_community_pool(3, 100)
        ['100:1', '100:2', '100:3']
    """
    communities = []
    for i in range(count):
        community_value = i + 1
        communities.append(f"{base_community}:{community_value}")
    return communities


def generate_community_combinations_for_prefixes(
    community_pool: List[str],
    prefix_count: int,
    communities_per_prefix: int,
) -> List[List[str]]:
    """
    Generate diverse combinations of communities for each prefix.

    This creates different combinations by using a sliding window approach with
    wraparound, ensuring maximum variety while reusing the same community pool.

    Args:
        community_pool: Pool of unique communities
        prefix_count: Number of prefixes needing community assignments
        communities_per_prefix: Number of communities per prefix

    Returns:
        List of community lists, one per prefix, each containing communities_per_prefix communities

    Example:
        With pool=["100:1", "100:2", "100:3", "100:4"], communities_per_prefix=2:
        Prefix 1: ["100:1", "100:2"]
        Prefix 2: ["100:2", "100:3"]
        Prefix 3: ["100:3", "100:4"]
        Prefix 4: ["100:4", "100:1"]  (wraps around)
        Prefix 5: ["100:1", "100:2"]  (cycles back)

    With 20 communities and 10 per prefix, this generates 20 unique starting positions
    before cycling, creating diverse combinations from the same pool.
    """
    pool_size = len(community_pool)
    combinations = []

    for prefix_idx in range(prefix_count):
        # Use modulo arithmetic to create different starting positions
        start_idx = prefix_idx % pool_size
        prefix_communities = []

        for i in range(communities_per_prefix):
            # Select community with wraparound
            community_idx = (start_idx + i) % pool_size
            prefix_communities.append(community_pool[community_idx])

        combinations.append(prefix_communities)

    return combinations


def generate_extended_community_pool(count: int = 10, base_rt: int = 100) -> List[str]:
    """
    Generate a pool of extended BGP communities (Route Targets).

    Args:
        count: Number of extended communities to generate
        base_rt: Base route target number

    Returns:
        List of extended community strings in format "rt:asn:value"

    Example:
        >>> generate_extended_community_pool(3, 100)
        ['rt:100:1', 'rt:100:2', 'rt:100:3']
    """
    extended_communities = []
    for i in range(count):
        rt_value = i + 1
        extended_communities.append(f"rt:{base_rt}:{rt_value}")
    return extended_communities


def generate_extended_community_combinations_for_prefixes(
    extended_community_pool: List[str],
    prefix_count: int,
    extended_communities_per_prefix: int,
) -> List[List[str]]:
    """
    Generate diverse combinations of extended communities for each prefix.

    This creates different combinations by using a sliding window approach with
    wraparound, ensuring maximum variety while reusing the same extended community pool.

    Args:
        extended_community_pool: Pool of unique extended communities
        prefix_count: Number of prefixes needing extended community assignments
        extended_communities_per_prefix: Number of extended communities per prefix

    Returns:
        List of extended community lists, one per prefix, each containing
        extended_communities_per_prefix extended communities

    Example:
        With pool=["rt:100:1", "rt:100:2", "rt:100:3", "rt:100:4"],
        extended_communities_per_prefix=2:
        Prefix 1: ["rt:100:1", "rt:100:2"]
        Prefix 2: ["rt:100:2", "rt:100:3"]
        Prefix 3: ["rt:100:3", "rt:100:4"]
        Prefix 4: ["rt:100:4", "rt:100:1"]  (wraps around)
        Prefix 5: ["rt:100:1", "rt:100:2"]  (cycles back)

    With 10 extended communities and 3 per prefix, this generates 10 unique
    starting positions before cycling, creating diverse combinations from the same pool.
    """
    pool_size = len(extended_community_pool)
    combinations = []

    for prefix_idx in range(prefix_count):
        # Use modulo arithmetic to create different starting positions
        start_idx = prefix_idx % pool_size
        prefix_extended_communities = []

        for i in range(extended_communities_per_prefix):
            # Select extended community with wraparound
            ext_community_idx = (start_idx + i) % pool_size
            prefix_extended_communities.append(
                extended_community_pool[ext_community_idx]
            )

        combinations.append(prefix_extended_communities)

    return combinations


def generate_attribute_pools_from_production(
    production_routes_file: str,
) -> dict:
    """
    Extract unique attributes from production EBB device route table.

    This function analyzes a production route table dump and extracts the most
    common/representative attributes to create a realistic test attribute pool.

    Args:
        production_routes_file: Path to file containing production BGP routes

    Returns:
        Dictionary containing:
            - 'as_paths': List of AS path strings
            - 'communities': List of community strings
            - 'extended_communities': List of extended community strings

    Note:
        This is a placeholder. Implementation should parse actual production data.
    """
    # TODO: Implement actual parsing of production route table
    # For now, return generated pools
    return {
        "as_paths": generate_as_path_pool(),
        "communities": generate_community_pool(),
        "extended_communities": generate_extended_community_pool(),
    }
