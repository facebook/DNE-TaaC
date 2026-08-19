# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

"""
The OSS setup-task stage: which tasks run, and on which devices.

TAAC in OSS needs a small set of setup tasks that run without every test config
having to declare them. An OSS config should not have to know which tasks the
OSS environment needs in order to make drain testable -- it should just get a
device in a state where a drain produces an observable signal.

``TestConfig.oss_setup_tasks`` is how a config adds to or overrides that set.
Both lists are first expanded across endpoints, then merged per device, so the
unit of override is a *(task_name, hostname)* pair rather than a task name:

- The defaults in ``DEFAULT_OSS_SETUP_TASKS`` run even when the field is unset.
  They set no hostname, so each expands to one task per endpoint.
- A declared task with no hostname also covers every endpoint, so if it shares a
  default's name it replaces that default everywhere.
- A declared task **with** a hostname replaces the default only on that device.
  Every other endpoint still gets the default. That is the point: retuning
  ``setup_base_configs`` for one switch should not silently stop it running on
  the rest of the testbed.
- A declared task whose name is not a default is simply added.
- ``skip_default_oss_setup_tasks`` merges in no defaults at all.
"""

import typing as t

from taac.utils.driver_factory import (
    TAAC_OSS,
    TAAC_OSS_META_INTERNAL,
)
from taac.test_as_a_config import types as taac_types


# Tasks every OSS run gets for free. Order is preserved through the merge, and a
# task that replaces one of these inherits its position -- so if this list grows
# to something order-dependent, overriding a task will not reorder the stage.
DEFAULT_OSS_SETUP_TASKS: t.Tuple[taac_types.Task, ...] = (
    taac_types.Task(
        task_name="setup_base_configs",
        params=taac_types.Params(),
        description="Generate live and soft-drain BGP configs (OSS default)",
    ),
)


def oss_setup_tasks_enabled() -> bool:
    """Whether the OSS setup-task stage should run at all.

    Requires OSS *and* the OSS drivers. ``TAAC_OSS_META_INTERNAL=1`` runs the
    OSS stack against Meta lab hardware with the internal drivers, and the
    default tasks are not safe there: ``setup_base_configs`` rewrites
    ``/etc/coop/bgpcpp/current``, which COOP owns internally and will
    re-materialize. That mode also restores the Arista and Cisco drivers, so its
    endpoints are not guaranteed to be FBOSS the way a pure-OSS run's are.
    """
    return TAAC_OSS and not TAAC_OSS_META_INTERNAL


def _device_key(task: taac_types.Task) -> t.Tuple[str, t.Optional[str]]:
    return (task.task_name, task.hostname)


def merge_expanded_tasks(
    defaults: t.Sequence[taac_types.Task],
    declared: t.Sequence[taac_types.Task],
) -> t.List[taac_types.Task]:
    """Merge two already-expanded task lists, keyed by (task_name, hostname).

    Both inputs must already have hostnames -- see ``expand_over_endpoints``.
    Keying on the pair rather than the name alone is what lets a config retune
    a default for one device without disabling it on the others: the declared
    task wins on the hosts it names, and the default survives everywhere else.

    A declared task keeps the position of the default it replaces, so growing
    ``DEFAULT_OSS_SETUP_TASKS`` into something order-dependent will not have
    overrides silently reordering the stage.
    """
    overrides: t.Dict[t.Tuple[str, t.Optional[str]], t.List[taac_types.Task]] = {}
    for task in declared:
        overrides.setdefault(_device_key(task), []).append(task)

    merged: t.List[taac_types.Task] = []
    consumed: t.Set[t.Tuple[str, t.Optional[str]]] = set()
    for default in defaults:
        key = _device_key(default)
        if key in overrides:
            merged.extend(overrides[key])
            consumed.add(key)
        else:
            merged.append(default)

    merged.extend(task for task in declared if _device_key(task) not in consumed)
    return merged


def expand_over_endpoints(
    tasks: t.Sequence[taac_types.Task],
    endpoints: t.Sequence[taac_types.Endpoint],
) -> t.List[taac_types.Task]:
    """Give every task a hostname, fanning out the ones that lack one.

    A task with ``hostname`` already set is passed through untouched -- that is
    a config deliberately targeting one device. A task without one becomes one
    task per endpoint, which is what makes the defaults testbed-wide.

    Fanning out to *every* endpoint rather than just the DUTs is safe because
    this only runs under pure OSS, where ``driver_factory`` can hand out nothing
    but ``FbossSwitch`` -- see ``oss_setup_tasks_enabled``.
    """
    expanded: t.List[taac_types.Task] = []
    for task in tasks:
        if task.hostname:
            expanded.append(task)
            continue
        # thrift-python structs are immutable; calling one returns a copy with
        # the named fields replaced.
        expanded.extend(task(hostname=endpoint.name) for endpoint in endpoints)
    return expanded


def resolve_oss_setup_tasks(
    test_config: taac_types.TestConfig,
) -> t.List[taac_types.Task]:
    """Full stage contents for a config: expand both lists, then merge per device.

    Expansion has to happen before the merge. A declared task that names one
    host only conflicts with the default on *that* host, and that is only
    visible once the default has been fanned out across the endpoints.

    Returns an empty list when the stage is disabled, so the caller does not
    need to repeat the gate.
    """
    if not oss_setup_tasks_enabled():
        return []

    endpoints = test_config.endpoints
    declared = expand_over_endpoints(test_config.oss_setup_tasks or [], endpoints)
    if test_config.skip_default_oss_setup_tasks:
        return declared

    defaults = expand_over_endpoints(DEFAULT_OSS_SETUP_TASKS, endpoints)
    return merge_expanded_tasks(defaults, declared)
