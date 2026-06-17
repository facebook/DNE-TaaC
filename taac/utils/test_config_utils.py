# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import logging
from dataclasses import dataclass
from typing import Any, List

from ixia.ixia import types as ixia_types
from taac.utils.common import async_everpaste_str
from taac.utils.oss_taac_lib_utils import await_sync
from taac.test_as_a_config import types as taac_types

logger = logging.getLogger(__name__)


@dataclass
class TrafficDeviceProperty:
    """
    Represents traffic device properties for endpoint configuration.

    Attributes:
        device_name: Name of the device
        interface_name: Name of the interface
        device_group_index: Device group index for the endpoint (defaults to 0)
    """

    device_name: str
    interface_name: str
    device_group_index: int = 0


def create_downlink_to_dual_uplink_traffic_item(
    downlink_traffic_device_property: TrafficDeviceProperty,
    uplink_traffic_device_property: List[TrafficDeviceProperty],
) -> taac_types.BasicTrafficItemConfig:
    """
    Create a traffic item configuration for downlink to uplink traffic.

    Args:
        downlink_traffic_device_property: TrafficDeviceProperty for the downlink device
        uplink_traffic_device_property: List of TrafficDeviceProperty objects for uplink devices

    Returns:
        BasicTrafficItemConfig: Configured traffic item for downlink to uplink traffic
    """
    # Generate traffic item name based on devices involved
    uplink_names = [prop.device_name.upper() for prop in uplink_traffic_device_property]
    uplink_names_str = "_AND_".join(uplink_names)
    traffic_name = (
        f"{downlink_traffic_device_property.device_name.upper()}_TO_{uplink_names_str}"
    )

    # Create source endpoint from downlink device
    src_endpoint = taac_types.TrafficEndpoint(
        name=f"{downlink_traffic_device_property.device_name.upper()}:{downlink_traffic_device_property.interface_name.upper()}",
        network_group_index=0,
        device_group_index=downlink_traffic_device_property.device_group_index,
    )

    # Create destination endpoints from uplink devices
    dest_endpoints = []
    for uplink_prop in uplink_traffic_device_property:
        dest_endpoint = taac_types.TrafficEndpoint(
            name=f"{uplink_prop.device_name.upper()}:{uplink_prop.interface_name.upper()}",
            network_group_index=0,
            device_group_index=uplink_prop.device_group_index,
        )
        dest_endpoints.append(dest_endpoint)

    return taac_types.BasicTrafficItemConfig(
        name=traffic_name,
        bidirectional=False,
        merge_destinations=True,
        line_rate=10,
        src_dest_mesh=ixia_types.SrcDestMeshType.ONE_TO_ONE,
        src_endpoints=[src_endpoint],
        dest_endpoints=dest_endpoints,
        traffic_type=ixia_types.TrafficType.IPV6,
        tracking_types=[ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM],
    )


def format_config_for_human(obj: Any, indent: int = 0) -> str:
    """
    Format a TestConfig object or any nested structure in a human-readable hierarchical format.

    Args:
        obj: The object to format (TestConfig, dict, list, or primitive)
        indent: Current indentation level

    Returns:
        A formatted string representation of the object
    """
    indent_str = "  " * indent

    # Handle None
    if obj is None:
        return f"{indent_str}None"

    # Handle primitive types
    if isinstance(obj, (str, int, float, bool)):
        return f"{indent_str}{obj}"

    # Handle lists
    if isinstance(obj, list):
        if not obj:
            return f"{indent_str}[]"

        result = f"{indent_str}[\n"
        for item in obj:
            # For simple items in a list, don't add extra indentation levels
            if isinstance(item, (str, int, float, bool)):
                result += f"{indent_str}  {item},\n"
            else:
                result += f"{format_config_for_human(item, indent + 1)},\n"
        result += f"{indent_str}]"
        return result

    # Handle TestConfig objects
    if hasattr(obj, "__dict__"):
        attrs = {}
        for key in dir(obj):
            if not key.startswith("_"):  # Skip private attributes
                try:
                    value = getattr(obj, key)
                    # Skip methods and callable attributes
                    if not callable(value):
                        attrs[key] = value
                except Exception:
                    # Skip attributes that can't be accessed
                    pass

        # Format as dictionary
        return format_config_for_human(attrs, indent)

    # Handle dictionaries
    if isinstance(obj, dict):
        if not obj:
            return f"{indent_str}{{}}"

        result = f"{indent_str}{{\n"
        for key, value in obj.items():
            # Skip None values to reduce clutter
            if value is None:
                continue

            # Skip empty lists to reduce clutter
            if isinstance(value, list) and not value:
                continue

            result += f"{indent_str}  {key}: "

            # For simple values, print on the same line
            if isinstance(value, (str, int, float, bool)):
                result += f"{value},\n"
            else:
                # For complex values, print on new lines with increased indentation
                result += "\n" + format_config_for_human(value, indent + 2) + ",\n"

        result += f"{indent_str}}}"
        return result

    # Handle other objects
    return f"{indent_str}{str(obj)}"


def flatten_multiple_test_configs(
    test_configs: List[taac_types.TestConfig],
    config_name: str,
    additive_basic_traffic_item_configs=None,
) -> taac_types.TestConfig:
    """
    Flattens multiple TestConfig objects into a single TestConfig.

    For attributes that are lists (like setup_tasks), it combines them.
    For string attributes, it uses the value from the first test config.
    For numeric attributes, it uses the highest value.

    Special handling for specific attributes:
    - startup_checks, prechecks and postchecks: If provided in any config, the values from the last config with them defined are used,
      completely replacing any existing values (not combined)
    - basic_traffic_item_configs: If additive_basic_traffic_item_configs is provided (not None), these traffic items
      will be used directly. Otherwise, all traffic items from all configs are combined.
    - endpoints: All available endpoints are added as is
    - traffic_items_to_start: All items from all configs are combined
    - basic_port_configs: All items from all configs are combined
    - setup_tasks: All items from all configs are added
    - teardown_tasks: All items from all configs are added

    Args:
        test_configs: List of TestConfig objects to flatten
        config_name: Name to use for the flattened config
        additive_basic_traffic_item_configs: Optional list of traffic item configs to use directly.
                                           If provided, these will be used instead of combining from all configs.

    Returns:
        A single TestConfig object that combines all input configs
    """
    if not test_configs:
        raise ValueError("No test configs provided to flatten")

    # Use the first config as the base
    base_config = test_configs[0]

    # If there's only one config, return it directly
    if len(test_configs) == 1:
        return base_config

    # Create a new TestConfig with combined attributes
    flattened_config_dict = {}

    # Handle setup_tasks explicitly
    all_setup_tasks = []
    for config in test_configs:
        if hasattr(config, "setup_tasks") and config.setup_tasks is not None:
            all_setup_tasks.extend(config.setup_tasks)
    flattened_config_dict["setup_tasks"] = all_setup_tasks

    # Handle prechecks explicitly (use values from the last config that has them defined)
    last_prechecks = None
    for config in test_configs:
        if hasattr(config, "prechecks") and config.prechecks is not None:
            last_prechecks = config.prechecks
    if last_prechecks is not None:
        # pyrefly: ignore [unsupported-operation]
        flattened_config_dict["prechecks"] = last_prechecks

    # Handle postchecks explicitly (use values from the last config that has them defined)
    last_postchecks = None
    for config in test_configs:
        if hasattr(config, "postchecks") and config.postchecks is not None:
            last_postchecks = config.postchecks
    if last_postchecks is not None:
        # pyrefly: ignore [unsupported-operation]
        flattened_config_dict["postchecks"] = last_postchecks

    # Handle startup_checks explicitly (use values from the last config that has them defined)
    last_startup_checks = None
    for config in test_configs:
        if hasattr(config, "startup_checks") and config.startup_checks is not None:
            last_startup_checks = config.startup_checks
    if last_startup_checks is not None:
        # pyrefly: ignore [unsupported-operation]
        flattened_config_dict["startup_checks"] = last_startup_checks

    # Handle basic_traffic_item_configs explicitly
    # First, combine traffic items from all configs
    all_traffic_configs = []
    for config in test_configs:
        if (
            hasattr(config, "basic_traffic_item_configs")
            and config.basic_traffic_item_configs is not None
        ):
            all_traffic_configs.extend(config.basic_traffic_item_configs)

    # Then add the additive traffic items if provided
    if additive_basic_traffic_item_configs is not None:
        all_traffic_configs.extend(additive_basic_traffic_item_configs)

    # pyrefly: ignore [unsupported-operation]
    flattened_config_dict["basic_traffic_item_configs"] = all_traffic_configs

    # Handle endpoints explicitly
    all_endpoints = []
    for config in test_configs:
        if hasattr(config, "endpoints") and config.endpoints is not None:
            all_endpoints.extend(config.endpoints)
    # pyrefly: ignore [unsupported-operation]
    flattened_config_dict["endpoints"] = all_endpoints

    # Handle traffic_items_to_start explicitly (similar to endpoints)
    all_traffic_items_to_start = []
    for config in test_configs:
        if (
            hasattr(config, "traffic_items_to_start")
            and config.traffic_items_to_start is not None
        ):
            all_traffic_items_to_start.extend(config.traffic_items_to_start)
    # pyrefly: ignore [unsupported-operation]
    flattened_config_dict["traffic_items_to_start"] = all_traffic_items_to_start

    # Handle basic_port_configs explicitly (similar to endpoints)
    all_basic_port_configs = []
    for config in test_configs:
        if (
            hasattr(config, "basic_port_configs")
            and config.basic_port_configs is not None
        ):
            all_basic_port_configs.extend(config.basic_port_configs)
    # pyrefly: ignore [unsupported-operation]
    flattened_config_dict["basic_port_configs"] = all_basic_port_configs

    # Handle teardown_tasks explicitly
    all_teardown_tasks = []
    for config in test_configs:
        if hasattr(config, "teardown_tasks") and config.teardown_tasks is not None:
            all_teardown_tasks.extend(config.teardown_tasks)
    flattened_config_dict["teardown_tasks"] = all_teardown_tasks

    # Get all attributes from the first config
    for attr_name in dir(base_config):
        # Skip special methods, internal attributes, and already handled attributes
        if attr_name.startswith("_") or attr_name in [
            "setup_tasks",
            "teardown_tasks",
            "prechecks",
            "postchecks",
            "startup_checks",
            "basic_traffic_item_configs",
            "endpoints",
            "traffic_items_to_start",
            "basic_port_configs",
        ]:
            continue

        attr_value = getattr(base_config, attr_name)
        if isinstance(attr_value, list):
            # For list attributes, combine them from all configs
            combined_list = []
            for config in test_configs:
                config_attr = getattr(config, attr_name, [])
                if config_attr is not None and isinstance(config_attr, list):
                    combined_list.extend(config_attr)
            flattened_config_dict[attr_name] = combined_list
        elif isinstance(attr_value, int):
            # For numeric attributes, use the highest value
            max_value = attr_value
            for config in test_configs[1:]:
                config_value = getattr(config, attr_name, 0)
                if isinstance(config_value, int) and config_value > max_value:
                    max_value = config_value
            # pyrefly: ignore [unsupported-operation]
            flattened_config_dict[attr_name] = max_value
        elif isinstance(attr_value, bool):
            # For boolean attributes, use OR operation (True if any is True)
            any_true = attr_value
            for config in test_configs[1:]:
                config_value = getattr(config, attr_name, False)
                if isinstance(config_value, bool) and config_value:
                    any_true = True
                    break
            # pyrefly: ignore [unsupported-operation]
            flattened_config_dict[attr_name] = any_true
        else:
            # For string and other attributes, use the value from the first config
            flattened_config_dict[attr_name] = attr_value

    # pyrefly: ignore [unsupported-operation]
    flattened_config_dict["name"] = config_name

    # Create a new TestConfig with the flattened attributes
    # pyrefly: ignore [bad-argument-type]
    flattened_config = taac_types.TestConfig(**flattened_config_dict)

    # Format the flattened config in a human-readable format and put it in everpaste
    formatted_config = format_config_for_human(flattened_config)

    # Use everpaste to share the formatted config
    try:
        paste_url = await_sync(
            async_everpaste_str(
                formatted_config,
            )
        )
    except Exception as e:
        logger.error(f"Failed to create everpaste: {e}")
        logger.info(formatted_config)

    return flattened_config
