# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import ipaddress
import math
import os
import random
import socket
import time
import typing as t

TAAC_OSS = os.environ.get("TAAC_OSS", "").lower() in ("1", "true", "yes")

from taac.health_checks.constants import (
    CORE_DUMP_IGNORE_WORDS,
    EOS_CORE_DUMP_PATH,
    EOS_CRITICAL_CORE_DUMPS,
    FBOSS_CORE_DUMP_PATH,
    FBOSS_CRITICAL_CORE_DUMPS,
)
from taac.utils.driver_factory import async_get_device_driver
from taac.utils.oss_taac_lib_utils import (
    ConsoleFileLogger,
    get_root_logger,
    none_throws,
)

LOGGER: ConsoleFileLogger = get_root_logger()

FBOSS_FB303_PORT: int = 5909
FBOSS_MNPU_FB303_PORT: int = 5931


async def get_fb303_client(host: str):
    """Get fb303 client.
    In OSS mode, raises NotImplementedError since fb303 requires Meta-internal thrift.
    """
    if TAAC_OSS:
        # TODO: Implement fb303 client with direct TCP thrift connection
        # for OSS. Use host:5909 (or 5931 for MNPU) with standard thrift transport.
        raise NotImplementedError(
            "fb303 client requires Meta-internal get_direct_client. "
            "Not yet available in OSS mode."
        )

    from fb303.clients import FacebookService
    from libfb.py.asyncio.thrift import ClientType, get_direct_client

    driver = await async_get_device_driver(host)
    # pyre-fixme[16]: `AbstractSwitch` has no attribute `async_is_multi_switch`.
    is_multi_switch = await driver.async_is_multi_switch()
    port = FBOSS_MNPU_FB303_PORT if is_multi_switch else FBOSS_FB303_PORT
    return get_direct_client(
        FacebookService,
        host=host,
        port=port,
        client_type=ClientType.THRIFT_ROCKET_CLIENT_TYPE,
    )


def ip_ntop(addr):
    if len(addr) == 4:
        return socket.inet_ntop(socket.AF_INET, addr)
    elif len(addr) == 16:
        return socket.inet_ntop(socket.AF_INET6, addr)
    else:
        raise ValueError("bad binary address %r" % (addr,))


def is_parent_prefix(prefix: str, parent_prefix: str) -> bool:
    prefix_network = ipaddress.ip_network(prefix, strict=False)
    parent_prefix_network = ipaddress.ip_network(parent_prefix, strict=False)
    if prefix_network.version != parent_prefix_network.version:
        return False
    # pyrefly: ignore [bad-argument-type]
    result = prefix_network.subnet_of(parent_prefix_network)
    return result


async def async_get_core_dump_config(hostname: str) -> t.Tuple[str, t.List[str]]:
    """
    Get OS-specific core dump configuration.

    Returns:
        Tuple of (core_dump_path, critical_processes)
    """
    if TAAC_OSS:
        return FBOSS_CORE_DUMP_PATH, FBOSS_CRITICAL_CORE_DUMPS

    else:
        from taac.internal.netwhoami_utils import fetch_whoami
        from netwhoami.types import OperatingSystem

    try:
        whoami = await fetch_whoami(hostname)
        if whoami.operating_system == OperatingSystem.EOS:
            return EOS_CORE_DUMP_PATH, EOS_CRITICAL_CORE_DUMPS
        else:
            return FBOSS_CORE_DUMP_PATH, FBOSS_CRITICAL_CORE_DUMPS
    except Exception:
        return EOS_CORE_DUMP_PATH, EOS_CRITICAL_CORE_DUMPS


async def async_find_critical_core_dumps(
    hostname: str, start_time: float = 0
) -> t.Dict[str, int]:
    """
    Find critical core dumps on a device that occurred after the specified start_time.

    Args:
        hostname: Name of the device to check
        start_time: Unix timestamp - only find core dumps newer than this time.
                   If 0 or not provided, finds all core dumps.

    Returns:
        Dictionary mapping core dump filenames to their timestamps
    """
    driver = await async_get_device_driver(hostname)

    # Get OS-specific core dump configuration
    core_dump_path, critical_processes = await async_get_core_dump_config(hostname)

    if TAAC_OSS:
        # OSS mode: always FBOSS, use find command approach
        core_dump_find_cmd = f"find {core_dump_path} -type f -printf '%T@ %p\n'"
        core_dump_output = none_throws(
            await driver.async_run_cmd_on_shell(cmd=core_dump_find_cmd)
        )
        critical_core_dumps = {}
        for line in core_dump_output.splitlines() or []:
            timestamp, core_file_full_path = line.split(" ")
            timestamp = int(float(timestamp))
            core_filename = core_file_full_path[len(core_dump_path) :]
            if await async_is_critical_core_dump(
                core_file_full_path, critical_processes
            ):
                critical_core_dumps[core_filename] = int(timestamp)
        return critical_core_dumps
    else:
        from taac.internal.netwhoami_utils import fetch_whoami
        from netwhoami.types import OperatingSystem

    whoami = await fetch_whoami(hostname)
    if whoami.operating_system == OperatingSystem.EOS:
        # For Arista/EOS devices, use the driver's API with custom critical processes
        core_dump_files = await driver.async_check_for_core_dump(
            start_time=start_time, critical_processes=critical_processes
        )

        LOGGER.debug("Checking for core dump files in %s", core_dump_path)

        # Convert the result to our expected format with timestamps
        critical_core_dumps = {}
        for core_file in core_dump_files.critical_core_dumps:
            # Use current time as timestamp since the API doesn't provide timestamps
            timestamp = int(time.time())
            critical_core_dumps[core_file] = timestamp

        LOGGER.info(
            f"Found {len(critical_core_dumps)} critical core dumps on {hostname}"
        )
        return critical_core_dumps
    else:
        # For FBOSS/Linux devices, use the original find command approach
        core_dump_find_cmd = f"find {core_dump_path} -type f -printf '%T@ %p\n'"
        core_dump_output = none_throws(
            await driver.async_run_cmd_on_shell(
                cmd=core_dump_find_cmd,
            )
        )
        critical_core_dumps = {}
        for line in core_dump_output.splitlines() or []:
            timestamp, core_file_full_path = line.split(" ")
            timestamp = int(float(timestamp))
            core_filename = core_file_full_path[len(core_dump_path) :]
            if await async_is_critical_core_dump(
                core_file_full_path, critical_processes
            ):
                critical_core_dumps[core_filename] = int(timestamp)
        return critical_core_dumps


async def async_is_critical_core_dump(
    core_dump_filename: str,
    critical_core_dump_keywords: t.Optional[t.List[str]] = None,
) -> bool:
    if any(ignore_word in core_dump_filename for ignore_word in CORE_DUMP_IGNORE_WORDS):
        return False
    elif critical_core_dump_keywords and any(
        filename in core_dump_filename for filename in critical_core_dump_keywords
    ):
        return True
    return False


def format_timestamp(timestamp: t.Union[int, float, str]) -> str:
    """
    Convert a timestamp to readable format.

    Args:
        timestamp: Unix timestamp as int, float, or string

    Returns:
        Human-readable timestamp string in format "YYYY-MM-DD HH:MM:SS"
    """
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(timestamp)))


def generate_prefix_nh_list_map(
    nh_list: t.List[str], max_member: int, max_group: int
) -> t.List[t.Set[str]]:
    """
    ECMP Group Generator for Network Testing

    This function creates a list of unique sets of next hop addresses for ECMP testing.
    It's designed to stress test ECMP implementations by generating a specific number
    of unique groups with a specific total number of members.

    Requirements:
    - Generate exactly max_group unique sets of next hops
    - Total number of next hop entries across all sets must equal max_member
    - Each set must be unique (no duplicate sets)
    - Set sizes should vary to test different ECMP group sizes
    - Use only the provided next hop addresses without modification

    Args:
        nh_list: List of next hop addresses to use in the sets
        max_member: Maximum total number of members across all groups
        max_group: Maximum number of groups (length of the list)

    Returns:
        List of sets where:
        - The length of the list equals exactly max_group
        - The sum of lengths of all sets equals max_member
        - Sets have varying sizes based on distribution algorithm
        - The sets are unique in the list
        - Each set contains elements from nh_list
    """

    if len(nh_list) < 2:
        raise ValueError("nh_list must contain at least two elements")

    # Calculate theoretical maximum combinations possible
    max_possible_combinations = 0
    for k in range(2, min(len(nh_list) + 1, 37)):
        max_possible_combinations += math.comb(len(nh_list), k)

    if max_possible_combinations < max_group:
        LOGGER.warning(
            f"The provided nh_list can generate at most {max_possible_combinations} unique combinations"
        )

    # Calculate group sizes based on remaining members and groups
    group_sizes = []
    remaining_members = max_member
    remaining_groups = max_group
    min_size, max_size = 2, min(36, len(nh_list) // 4)

    # Create a distribution of group sizes using a mix of strategies:
    # 1. Some groups at min_size
    # 2. Some groups at max_size
    # 3. Some groups with random sizes in between
    # 4. Some groups around the average size
    avg_size = remaining_members / remaining_groups

    # First pass: assign initial sizes with variety
    for i in range(max_group):
        if remaining_groups <= 0:
            break

        # Decide which strategy to use for this group
        strategy = i % 4

        if strategy == 0 and remaining_members >= min_size * remaining_groups:
            size = min_size
        elif (
            strategy == 1
            and remaining_members >= (remaining_groups - 1) * min_size + max_size
        ):
            size = max_size
        elif (
            strategy == 2
            and remaining_members > (remaining_groups - 1) * min_size + min_size
        ):
            max_possible = min(
                max_size, remaining_members - (remaining_groups - 1) * min_size
            )
            size = random.randint(min_size, max(min_size, max_possible))
        else:
            max_possible = min(
                max_size, remaining_members - (remaining_groups - 1) * min_size
            )
            target = int(avg_size)
            size = min(max(min_size, target), max_possible)

        group_sizes.append(size)
        remaining_members -= size
        remaining_groups -= 1

    # Second pass: adjust sizes to exactly match max_member
    while remaining_members > 0:
        # Distribute leftover members
        indices = list(range(len(group_sizes)))
        random.shuffle(indices)
        made_progress = False
        for idx in indices:
            if remaining_members <= 0:
                break
            if group_sizes[idx] < max_size:
                group_sizes[idx] += 1
                remaining_members -= 1
                made_progress = True
        if not made_progress:
            break
    while remaining_members < 0:
        # Remove excess members from largest groups
        indices = sorted(
            range(len(group_sizes)), key=lambda i: group_sizes[i], reverse=True
        )
        made_progress = False
        for idx in indices:
            if remaining_members >= 0:
                break
            if group_sizes[idx] > min_size:
                group_sizes[idx] -= 1
                remaining_members += 1
                made_progress = True
        if not made_progress:
            break

    # Verify our calculations
    assert len(group_sizes) == max_group, (
        f"Expected {max_group} groups, got {len(group_sizes)}"
    )
    assert sum(group_sizes) == max_member, (
        f"Expected {max_member} total members, got {sum(group_sizes)}"
    )

    # Generate unique combinations
    result = []
    used_combinations = set()

    # For each group size, generate a unique combination
    for size in group_sizes:
        max_attempts = 1000
        for attempt in range(max_attempts):
            # Generate a random combination
            combination = frozenset(random.sample(nh_list, size))

            # Check if this combination is unique
            if combination not in used_combinations:
                used_combinations.add(combination)
                result.append(set(combination))
                break

            # If we've tried too many times, use a different approach
            if attempt == max_attempts - 1:
                # Try to find a unique combination by modifying an existing one
                base_combination = set(random.sample(nh_list, size))

                # Replace elements until we find a unique combination
                for _ in range(size * 2):
                    if len(base_combination) < size:
                        available = [nh for nh in nh_list if nh not in base_combination]
                        if available:
                            base_combination.add(random.choice(available))
                    else:
                        to_remove = random.choice(list(base_combination))
                        base_combination.remove(to_remove)
                        available = [nh for nh in nh_list if nh not in base_combination]
                        if available:
                            base_combination.add(random.choice(available))

                    frozen = frozenset(base_combination)
                    if (
                        frozen not in used_combinations
                        and len(base_combination) == size
                    ):
                        used_combinations.add(frozen)
                        result.append(base_combination)
                        break

                # If we still couldn't find a unique combination, raise an error
                if len(result) < len(group_sizes[: len(result) + 1]):
                    raise RuntimeError(
                        "Unable to generate enough unique combinations. Please provide a larger nh_list."
                    )

    # Final verification
    assert len(result) == max_group, f"Expected {max_group} groups, got {len(result)}"
    assert sum(len(s) for s in result) == max_member, (
        f"Expected {max_member} total members, got {sum(len(s) for s in result)}"
    )
    assert len(used_combinations) == max_group, (
        f"Expected {max_group} unique combinations, got {len(used_combinations)}"
    )

    # Summary of the generated artifact
    LOGGER.info(
        f"Generated {len(result)} ECMP groups with {sum(len(s) for s in result)} total next hops"
    )

    return result
