# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""
TAAC Step for injecting (or withdrawing) BGP prefixes into GTSW/STSW devices
via the BGP++ thrift addNetworks/delNetworks API.

Wraps the reusable helpers from neteng.test_infra.dne.taac.libs.fpf.inject_bgp_prefixes so that
prefix injection can be driven declaratively from a TAAC test config playbook
instead of requiring a manual buck2 run invocation.

Typical usage in a test config:
    create_fpf_bgp_prefix_injection_step(
        devices=["gtsw001.l1002.c087.mwg2"],
        prefix_base="5000:dd::/64",
        count=16,
        community_list="gtsw",
    )
"""

import asyncio
import typing as t

from taac.internal.driver.fboss_switch_internal import (
    FbossSwitchInternal,
)
from taac.libs.fpf.inject_bgp_prefixes import (
    build_communities,
    build_tip_prefix,
    COMMUNITY_PRESETS,
    expand_prefix_range,
    inject_prefixes,
    withdraw_prefixes,
)
from taac.steps.step import Step
from taac.test_as_a_config import types as taac_types


class FpfBgpPrefixInjectionStep(Step[taac_types.BaseInput]):
    """Inject or withdraw BGP prefixes on one or more FBOSS devices.

    Params (via step_params.json_params):
        devices: List of device hostnames to inject/withdraw on.
        prefix_base: Base CIDR prefix (e.g. "5000:dd::/64").
        count: Number of prefixes to generate from prefix_base (default: 1).
        increment_step: IPv6 string controlling which hextet to advance
            each iteration (default: "0:0:1::").
        community_list: Preset name ("gtsw" or "stsw") to select a built-in
            community set. Overrides ``communities`` if both are provided.
        communities: Explicit list of "ASN:VALUE" community strings.
            Used only when ``community_list`` is not set.
        withdraw_only: If True, only withdraw (delNetworks) the prefixes
            without injecting. Default False.
    """

    STEP_NAME = taac_types.StepName.FPF_BGP_PREFIX_INJECTION_STEP

    def __init__(self, *args: t.Any, **kwargs: t.Any) -> None:
        super().__init__(*args, **kwargs)
        self._devices: t.List[str] = []
        self._withdraw_only: bool = False
        self._prefixes: t.List[t.Any] = []
        self._communities: t.List[t.Any] = []

    async def setUp(
        self,
        input: taac_types.BaseInput,
        params: t.Dict[str, t.Any],
    ) -> None:
        await super().setUp(input, params)

        # --- Parse params ---
        self._devices = params["devices"]
        prefix_base: str = params["prefix_base"]
        count: int = params.get("count", 1)
        increment_step: str = params.get("increment_step", "0:0:1::")
        community_list: t.Optional[str] = params.get("community_list")
        communities_raw: t.Optional[t.List[str]] = params.get("communities")
        self._withdraw_only = params.get("withdraw_only", False)

        # --- Build prefix list ---
        prefix_strs = expand_prefix_range(prefix_base, count, increment_step)
        self._prefixes = [build_tip_prefix(p) for p in prefix_strs]
        self.logger.info(
            f"Built {len(self._prefixes)} prefix(es) from base {prefix_base}"
        )

        # --- Build communities ---
        if community_list:
            if community_list not in COMMUNITY_PRESETS:
                raise ValueError(
                    f"Unknown community_list preset '{community_list}'. "
                    f"Valid presets: {sorted(COMMUNITY_PRESETS.keys())}"
                )
            community_strs = COMMUNITY_PRESETS[community_list]
            self.logger.info(
                f"Using community preset '{community_list}' "
                f"({len(community_strs)} communities)"
            )
        elif communities_raw:
            community_strs = communities_raw
        else:
            raise ValueError(
                "Either 'community_list' or 'communities' must be provided "
                "in step params"
            )

        self._communities = build_communities(community_strs)

    async def run(
        self,
        input: taac_types.BaseInput,
        params: t.Dict[str, t.Any],
    ) -> None:
        if self._withdraw_only:
            self.logger.info(
                f"Withdraw-only mode: withdrawing {len(self._prefixes)} "
                f"prefix(es) from {len(self._devices)} device(s)"
            )
            await asyncio.gather(
                *(self._withdraw_on_device(device) for device in self._devices)
            )
        else:
            self.logger.info(
                f"Injecting {len(self._prefixes)} prefix(es) with "
                f"{len(self._communities)} communities on "
                f"{len(self._devices)} device(s)"
            )
            await asyncio.gather(
                *(self._inject_on_device(device) for device in self._devices)
            )

    async def _inject_on_device(self, device: str) -> None:
        self.logger.info(f"Connecting to {device} for prefix injection ...")
        driver = FbossSwitchInternal(hostname=device, logger=self.logger)
        await inject_prefixes(driver, self._prefixes, self._communities)
        self.logger.info(f"Injection complete on {device}")

    async def _withdraw_on_device(self, device: str) -> None:
        self.logger.info(f"Connecting to {device} for prefix withdrawal ...")
        driver = FbossSwitchInternal(hostname=device, logger=self.logger)
        await withdraw_prefixes(driver, self._prefixes)
        self.logger.info(f"Withdrawal complete on {device}")

    async def cleanUp(
        self,
        input: taac_types.BaseInput,
        params: t.Dict[str, t.Any],
    ) -> None:
        # Cleanup is intentionally a no-op. Prefix withdrawal is handled
        # via a separate cleanup_steps entry in the playbook, or by running
        # this step again with withdraw_only=True.
        pass
