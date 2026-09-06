# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""TAAC setup/teardown task that injects (or withdraws) BGP prefixes on STSW/GTSW
devices via the BGP++ thrift addNetworks/delNetworks API.

This makes the inject-then-disrupt FPF configs fully self-contained: a netcastle
run injects its own stress prefixes from a SETUP TASK (no external inject
script), then withdraws them in teardown. It supports MULTIPLE injection groups
in one task so the 8-STSW split-per-VF injection (VF1 5000:dd on s001-s004, VF2
5000:ee on s005-s008) is a single setup task.

Params (via json_params):
    groups: list of group dicts, each:
        devices: list[str]            STSW/GTSW hostnames to inject on
        prefix_base: str              base CIDR (e.g. "5000:dd::/64")
        count: int                    prefixes generated per device (default 1)
        increment_step: str           hextet-advance delta (default "0:0:1::")
        community_list: str|None       preset name "gtsw"/"stsw"
        communities: list[str]|None    explicit "ASN:VALUE" list (used if no preset)
        pods: int|None                 Pod Mosaic bucket count
        prefixes_per_pod: int|None     expected prefixes in each pod bucket
        base_asn_path: int|None        first Pod Mosaic origin ASN
        increment_asn_per_pod: int     origin-ASN delta per pod (default 1)
        batch_size: int                prefixes per BGP thrift RPC (default count)
    withdraw: bool                    True -> delNetworks (teardown). Default False.
    settle_sec: int                   sleep after a successful inject (default 0).

On inject failure the task RAISES (aborting the test setup). On withdraw it is
best-effort (logs and continues) so a teardown never masks the real result.
"""

import asyncio
import typing as t

from taac.internal.driver.fboss_switch_internal import (
    FbossSwitchInternal,
)
from taac.libs.fpf.inject_bgp_prefixes import (
    build_communities,
    build_pod_mosaic_as_path_map,
    build_tip_prefix,
    COMMUNITY_PRESETS,
    expand_prefix_range,
    inject_prefixes,
    pod_mosaic_loop_deny_violations,
    withdraw_prefixes,
)
from taac.tasks.base_task import BaseTask


def _build_communities_for_group(group: t.Dict[str, t.Any]) -> t.List[t.Any]:
    community_list = group.get("community_list")
    communities_raw = group.get("communities")
    if community_list:
        if community_list not in COMMUNITY_PRESETS:
            raise ValueError(
                f"Unknown community_list preset '{community_list}'. "
                f"Valid presets: {sorted(COMMUNITY_PRESETS.keys())}"
            )
        community_strs = COMMUNITY_PRESETS[community_list]
    elif communities_raw:
        community_strs = communities_raw
    else:
        raise ValueError(
            "Each injection group must set 'community_list' or 'communities'"
        )
    return build_communities(community_strs)


def _build_pod_mosaic_for_group(
    group: t.Dict[str, t.Any], prefixes: t.List[t.Any]
) -> t.Optional[t.Dict[t.Any, t.List[int]]]:
    pods_raw = group.get("pods")
    if pods_raw is None:
        return None
    pods = int(pods_raw)
    if pods < 2:
        raise ValueError(f"Pod Mosaic requires pods >= 2, got {pods}")
    base_asn_raw = group.get("base_asn_path")
    if base_asn_raw is None:
        raise ValueError("Pod Mosaic requires base_asn_path")
    step = int(group.get("increment_asn_per_pod", 1))
    if step == 0:
        raise ValueError("increment_asn_per_pod must be non-zero")
    prefixes_per_pod_raw = group.get("prefixes_per_pod")
    if prefixes_per_pod_raw is not None:
        expected = pods * int(prefixes_per_pod_raw)
        if len(prefixes) != expected:
            raise ValueError(
                f"Pod Mosaic expected {pods} x {prefixes_per_pod_raw} = "
                f"{expected} prefixes, got {len(prefixes)}"
            )
    pod_asns = [int(base_asn_raw) + i * step for i in range(pods)]
    violations = pod_mosaic_loop_deny_violations(pod_asns)
    if violations:
        raise ValueError(
            f"Pod Mosaic ASN(s) {violations} would be dropped by BGP loop detection"
        )
    return build_pod_mosaic_as_path_map(prefixes, pod_asns)


class FpfInjectBgpPrefixesTask(BaseTask):
    """Inject or withdraw one or more BGP prefix groups across FBOSS devices."""

    NAME = "fpf_inject_bgp_prefixes"

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        groups: t.List[t.Dict[str, t.Any]] = params["groups"]
        withdraw: bool = params.get("withdraw", False)
        settle_sec: int = params.get("settle_sec", 0)

        # Build (device, prefixes, communities) work items across all groups.
        inject_items: t.List[
            t.Tuple[
                str,
                t.List[t.Any],
                t.List[t.Any],
                t.Optional[t.Dict[t.Any, t.List[int]]],
                int,
            ]
        ] = []
        for group in groups:
            devices: t.List[str] = group["devices"]
            prefix_base: str = group["prefix_base"]
            count: int = group.get("count", 1)
            increment_step: str = group.get("increment_step", "0:0:1::")
            prefix_strs = expand_prefix_range(prefix_base, count, increment_step)
            tip_prefixes = [build_tip_prefix(p) for p in prefix_strs]
            communities = _build_communities_for_group(group)
            prefix_as_path = _build_pod_mosaic_for_group(group, tip_prefixes)
            batch_size = int(group.get("batch_size", len(tip_prefixes)))
            if batch_size < 1:
                raise ValueError(f"batch_size must be >= 1, got {batch_size}")
            for device in devices:
                inject_items.append(
                    (device, tip_prefixes, communities, prefix_as_path, batch_size)
                )

        action = "Withdrawing" if withdraw else "Injecting"
        self.logger.info(
            f"[FpfInjectBgpPrefixes] {action} {len(groups)} group(s) across "
            f"{len(inject_items)} (device, group) pairs"
        )

        async def _do(
            device: str,
            tip_prefixes: t.List[t.Any],
            communities: t.List[t.Any],
            prefix_as_path: t.Optional[t.Dict[t.Any, t.List[int]]],
            batch_size: int,
        ) -> None:
            driver = FbossSwitchInternal(hostname=device, logger=self.logger)
            if withdraw:
                await withdraw_prefixes(
                    driver,
                    tip_prefixes,
                    batch_size=batch_size,
                )
            else:
                await inject_prefixes(
                    driver,
                    tip_prefixes,
                    communities,
                    prefix_as_path=prefix_as_path,
                    batch_size=batch_size,
                )

        if withdraw:
            # Teardown: best-effort. Never let a withdrawal error mask the result.
            results = await asyncio.gather(
                *(_do(d, p, c, a, b) for d, p, c, a, b in inject_items),
                return_exceptions=True,
            )
            for (device, _p, _c, _a, _b), res in zip(inject_items, results):
                if isinstance(res, Exception):
                    self.logger.error(
                        f"[FpfInjectBgpPrefixes] withdraw on {device} "
                        f"best-effort failed: {res}"
                    )
            return

        # Setup: any injection failure aborts the test.
        await asyncio.gather(*(_do(d, p, c, a, b) for d, p, c, a, b in inject_items))
        self.logger.info(
            f"[FpfInjectBgpPrefixes] injection complete on "
            f"{len(inject_items)} (device, group) pairs"
        )
        if settle_sec > 0:
            self.logger.info(
                f"[FpfInjectBgpPrefixes] settling {settle_sec}s for prefixes to "
                f"program on GTSW/HRT"
            )
            await asyncio.sleep(settle_sec)
