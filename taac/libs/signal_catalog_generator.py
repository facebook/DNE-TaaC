# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""
Signal Catalog Generator for TAAC.

Reads the TAAC health check and step registries via Python introspection
and outputs a structured YAML file listing every check, step, and helper
function with its metadata (OS compatibility, parameters, base class, etc.).

The generated file is consumed by the taac-copilot skill so it always has
an accurate, up-to-date inventory of what's available.

Usage:
    buck2 run fbcode//neteng/test_infra/dne/taac/libs:signal_catalog_generator

    # Write to a specific file:
    buck2 run fbcode//neteng/test_infra/dne/taac/libs:signal_catalog_generator -- \
        --output /path/to/signal-catalog.yaml
"""

import inspect
import json
import os
import sys
import typing as t

from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
    AbstractIxiaHealthCheck,
    AbstractTopologyHealthCheck,
)
from taac.health_checks.abstract_snapshot_health_check import (
    AbstractSnapshotHealthCheck,
)
from taac.health_checks.all_health_checks import ALL_HEALTH_CHECKS
from taac.steps.all_steps import ALL_STEPS


def _get_category(cls: type) -> str:
    """Determine the health check category from its base class."""
    if issubclass(cls, AbstractSnapshotHealthCheck):
        return "snapshot"
    if issubclass(cls, AbstractIxiaHealthCheck):
        return "ixia"
    if issubclass(cls, AbstractTopologyHealthCheck):
        return "topology"
    if issubclass(cls, AbstractDeviceHealthCheck):
        return "device"
    return "unknown"


def _get_operating_systems(cls: type) -> t.List[str]:
    """Get the list of supported operating systems from the class."""
    os_list = getattr(cls, "OPERATING_SYSTEMS", [])
    return [os.name for os in os_list]


def _has_method(cls: type, method_name: str) -> bool:
    """Check if a class defines its own implementation of a method (not inherited)."""
    if method_name not in dir(cls):
        return False
    # Check if the method is defined on this class, not just inherited
    for klass in cls.__mro__:
        if method_name in klass.__dict__:
            return klass is cls
    return False


def _get_check_params_from_docstring(cls: type) -> t.Dict[str, str]:
    """Extract check_params documentation from the _run method's docstring."""
    run_method = getattr(cls, "_run", None)
    if run_method is None:
        return {}

    docstring = inspect.getdoc(run_method)
    if not docstring:
        return {}

    params = {}
    in_check_params = False
    for line in docstring.split("\n"):
        stripped = line.strip()
        if "check_params" in stripped.lower() and "dict" in stripped.lower():
            in_check_params = True
            continue
        if in_check_params:
            if stripped.startswith("- "):
                # Parse "- param_name: description" or "- param_name (optional)"
                param_text = stripped[2:].strip()
                if ":" in param_text:
                    name, desc = param_text.split(":", 1)
                    params[name.strip()] = desc.strip()
                else:
                    params[param_text] = ""
            elif stripped.startswith("Returns") or stripped.startswith("Args"):
                break
            elif stripped == "" and params:
                break
    return params


def _get_input_type_name(cls: type) -> str:
    """Get the generic type argument name (the input type)."""
    for base in getattr(cls, "__orig_bases__", []):
        args = t.get_args(base)
        if args:
            arg = args[0]
            if hasattr(arg, "__name__"):
                return arg.__name__
            return str(arg)
    return "unknown"


def _get_source_file(cls: type) -> str:
    """Get the relative source file path for a class."""
    try:
        full_path = inspect.getfile(cls)
        # Use rfind to get the LAST occurrence — buck link-tree paths
        # contain the marker twice, we want the real source path
        marker = "neteng/test_infra/dne/taac/"
        idx = full_path.rfind(marker)
        if idx >= 0:
            return full_path[idx + len(marker) :]
        return full_path
    except (TypeError, OSError):
        return "unknown"


def generate_health_checks_catalog() -> t.List[t.Dict[str, t.Any]]:
    """Generate catalog entries for all health checks."""
    entries = []
    for cls in ALL_HEALTH_CHECKS:
        check_name = cls.CHECK_NAME.name
        category = _get_category(cls)
        operating_systems = _get_operating_systems(cls)
        has_arista = _has_method(cls, "_run_arista")
        has_fboss = _has_method(cls, "_run_fboss")
        check_params = _get_check_params_from_docstring(cls)
        input_type = _get_input_type_name(cls)
        source = _get_source_file(cls)

        entry: t.Dict[str, t.Any] = {
            "name": check_name,
            "category": category,
            "input_type": input_type,
            "source": source,
        }

        if operating_systems:
            entry["operating_systems"] = operating_systems

        if category == "device":
            entry["has_arista_impl"] = has_arista
            entry["has_fboss_impl"] = has_fboss

        if check_params:
            entry["check_params"] = check_params

        entries.append(entry)
    return entries


def generate_steps_catalog() -> t.List[t.Dict[str, t.Any]]:
    """Generate catalog entries for all steps."""
    entries = []
    for cls in ALL_STEPS:
        step_name = cls.STEP_NAME.name
        input_type = _get_input_type_name(cls)
        source = _get_source_file(cls)

        # Check if setUp/tearDown are overridden
        has_setup = _has_method(cls, "setUp")
        has_teardown = _has_method(cls, "tearDown")

        entry = {
            "name": step_name,
            "input_type": input_type,
            "has_setup": has_setup or False,
            "has_teardown": has_teardown or False,
            "source": source,
        }
        entries.append(entry)
    return entries


def generate_step_helpers_catalog() -> t.List[t.Dict[str, t.Any]]:
    """Generate catalog entries for helper functions in step_definitions.py."""
    try:
        from taac.steps import step_definitions
    except ImportError:
        return []

    entries = []
    for name, obj in inspect.getmembers(step_definitions, inspect.isfunction):
        if not name.startswith("create_"):
            continue

        sig = inspect.signature(obj)
        params = {}
        for pname, param in sig.parameters.items():
            param_info = {}
            if param.annotation != inspect.Parameter.empty:
                ann = param.annotation
                if hasattr(ann, "__name__"):
                    param_info["type"] = ann.__name__
                else:
                    param_info["type"] = str(ann)
            if param.default != inspect.Parameter.empty:
                try:
                    # Only include defaults that are JSON-serializable
                    json.dumps(param.default)
                    param_info["default"] = param.default
                except (TypeError, ValueError):
                    param_info["default"] = str(param.default)
            else:
                param_info["required"] = True
            params[pname] = param_info

        docstring = inspect.getdoc(obj) or ""
        summary = docstring.split("\n")[0] if docstring else ""

        entry = {
            "name": name,
            "summary": summary,
            "parameters": params,
        }
        entries.append(entry)
    return entries


def format_yaml_output(
    health_checks: t.List[t.Dict],
    steps: t.List[t.Dict],
    helpers: t.List[t.Dict],
) -> str:
    """Format the catalog as YAML (manual formatting to avoid PyYAML dependency)."""
    lines = []
    lines.append("# Auto-generated by signal_catalog_generator.py")
    lines.append("# DO NOT EDIT - regenerate with:")
    lines.append(
        "#   buck2 run fbcode//neteng/test_infra/dne/taac/libs:signal_catalog_generator"
    )
    lines.append("")

    # Health Checks
    lines.append("health_checks:")
    for hc in sorted(health_checks, key=lambda x: x["name"]):
        lines.append(f"  {hc['name']}:")
        lines.append(f"    category: {hc['category']}")
        if "operating_systems" in hc:
            os_str = ", ".join(hc["operating_systems"])
            lines.append(f"    operating_systems: [{os_str}]")
        if "has_arista_impl" in hc:
            lines.append(f"    has_arista_impl: {str(hc['has_arista_impl']).lower()}")
        if "has_fboss_impl" in hc:
            lines.append(f"    has_fboss_impl: {str(hc['has_fboss_impl']).lower()}")
        lines.append(f"    input_type: {hc['input_type']}")
        if hc.get("check_params"):
            lines.append("    check_params:")
            for pname, pdesc in hc["check_params"].items():
                if pdesc:
                    lines.append(f"      {pname}: {pdesc}")
                else:
                    lines.append(f"      {pname}:")
        lines.append(f"    source: {hc['source']}")
        lines.append("")

    # Steps
    lines.append("steps:")
    for step in sorted(steps, key=lambda x: x["name"]):
        lines.append(f"  {step['name']}:")
        lines.append(f"    input_type: {step['input_type']}")
        lines.append(f"    has_setup: {str(step['has_setup']).lower()}")
        lines.append(f"    has_teardown: {str(step['has_teardown']).lower()}")
        lines.append(f"    source: {step['source']}")
        lines.append("")

    # Step helpers
    lines.append("step_helpers:")
    for helper in sorted(helpers, key=lambda x: x["name"]):
        lines.append(f"  {helper['name']}:")
        if helper["summary"]:
            lines.append(f'    summary: "{helper["summary"]}"')
        if helper["parameters"]:
            lines.append("    parameters:")
            for pname, pinfo in helper["parameters"].items():
                parts = []
                if pinfo.get("required"):
                    parts.append("required")
                if "type" in pinfo:
                    parts.append(f"type={pinfo['type']}")
                if "default" in pinfo:
                    parts.append(f"default={pinfo['default']}")
                detail = ", ".join(parts) if parts else ""
                lines.append(f"      {pname}: {detail}")
        lines.append("")

    return "\n".join(lines) + "\n"


def main() -> None:
    output_path = None
    if "--output" in sys.argv:
        idx = sys.argv.index("--output")
        if idx + 1 < len(sys.argv):
            output_path = sys.argv[idx + 1]

    health_checks = generate_health_checks_catalog()
    steps = generate_steps_catalog()
    helpers = generate_step_helpers_catalog()

    yaml_output = format_yaml_output(health_checks, steps, helpers)

    if output_path:
        output_path = os.path.abspath(output_path)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w") as f:
            f.write(yaml_output)
        print(f"Signal catalog written to {output_path}")
        print(
            f"  {len(health_checks)} health checks, {len(steps)} steps, {len(helpers)} helpers"
        )
    else:
        print(yaml_output)


if __name__ == "__main__":
    main()
