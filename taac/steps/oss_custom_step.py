# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe

"""OSS implementation of ``StepName.CUSTOM_STEP``.

The Meta build takes ``CustomStep`` from ``taac.internal.steps.custom_step``,
which is not part of the OSS slice. Without a replacement ``NAME_TO_STEP`` has
no CUSTOM_STEP entry at all, so ``TaacRunner._initialize_step`` dies on
``NAME_TO_STEP[step.name]`` with a bare ``KeyError(StepName.CUSTOM_STEP)``:
the stage ends in 0.0s before its first step runs and the playbook reports
``<StepName.CUSTOM_STEP: 1001>`` as its whole error. Observed on hardware for
npi_cpu_036/037/038 (unresolved next hop) and npi_cpu_039 (MTU exceed).

Only the handlers OSS playbooks actually reach are ported. An unported
``custom_step_name`` raises and names what is supported, the same contract
``taac/driver/oss_coop_patcher.py`` applies to ``py_func_name``: a playbook
that needs a new handler gets it added here rather than silently running
against an unconfigured DUT.
"""

import fnmatch
import json
import time
import typing as t

from taac.constants import TestCaseFailure
from taac.steps.step import Step as StepBase
from taac.test_as_a_config import types as taac_types


class OssCustomStep(StepBase[taac_types.CustomStepInput]):
    STEP_NAME = taac_types.StepName.CUSTOM_STEP

    async def run(
        self,
        input: taac_types.CustomStepInput,
        params: t.Dict[str, t.Any],
    ) -> None:
        name = params.get("custom_step_name")
        if not name:
            raise ValueError(
                "oss-custom-step: step_params carry no 'custom_step_name' "
                f"(params: {sorted(params)}); create_custom_step() requires it."
            )
        handler = _HANDLERS.get(name)
        if handler is None:
            raise NotImplementedError(
                f"oss-custom-step: custom_step_name {name!r} is not ported to "
                f"OSS (supported: {sorted(_HANDLERS)}). Port it in "
                f"taac/steps/oss_custom_step.py rather than letting the "
                f"playbook fail with a bare KeyError."
            )
        await handler(self, params)

    def _vport_entry(self, egress_port: str) -> t.Any:
        """The IXIA vport entry for ``<this DUT>:<egress_port>``.

        ``vport_indices`` is keyed by the identifier IXIA composed at
        assign_ports() time. Two things go wrong in practice and both need to
        be legible from the exception rather than from a bare KeyError:

        * a topology-cache HIT skips assign_ports(), so the dict is empty;
        * the key can carry a different host spelling (FQDN vs UQDN) than the
          TestDevice name, so the strict key misses a port that is present.

        The suffix fallback covers the second case but refuses to guess when
        more than one host offers the same port.
        """
        ixia = self.ixia
        if ixia is None:
            raise ValueError(
                "oss-custom-step: no IXIA on the step; "
                "register_cpu_queue_static_route_patcher needs the "
                "traffic-generator topology to resolve its next hop."
            )
        # Via __class__ because get_port_identifier is a staticmethod on the
        # IXIA class, matching how the internal step composes the key.
        key = ixia.__class__.get_port_identifier(f"{self.hostname}:{egress_port}")
        vport_indices = ixia.vport_indices
        if key in vport_indices:
            return vport_indices[key]

        suffix = f":{key.split(':', 1)[1]}" if ":" in key else key
        candidates = [k for k in vport_indices if k.endswith(suffix)]
        if len(candidates) == 1:
            self.logger.warning(
                f"oss-custom-step: no IXIA vport under {key!r}; falling back "
                f"to {candidates[0]!r}, which matches on {suffix!r}. The DUT "
                f"name and the IXIA topology disagree on host spelling."
            )
            return vport_indices[candidates[0]]
        raise KeyError(
            f"oss-custom-step: no IXIA vport for {key!r}. "
            f"Available keys: {sorted(vport_indices)}. "
            f"Suffix-match candidates: {sorted(candidates)}. "
            "An empty list means the IXIA topology cache HIT and "
            "assign_ports() never populated vport_indices."
        )

    async def register_cpu_queue_static_route_patcher(
        self, params: t.Dict[str, t.Any]
    ) -> None:
        """Route the traffic destination at the IXIA port about to be shut.

        The UNH playbooks (npi_cpu_036/037/038) point a static route at the
        IXIA-side device-group mimic IP on ``next_hop_egress_port``, restart
        the agent so the route is programmed, then disable that port. The next
        hop becomes unresolved, and traffic for the prefix is punted to the
        low CPU queue -- which is what their CPU_QUEUE_CHECK measures.
        """
        egress_port = params["next_hop_egress_port"]
        mask = params["static_route_mask"]
        patcher_name = params.get("patcher_name", "cpu_queue_static_route_patcher")
        device_group_index = params.get("device_group_index", 0)

        entry = self._vport_entry(egress_port)
        device_group = entry.device_group_indices[device_group_index]
        if device_group.ipv6 is None:
            raise ValueError(
                f"oss-custom-step: device group {device_group_index} on "
                f"{egress_port} has no IPv6 stack, so it exposes no next hop."
            )
        next_hop = device_group.ipv6.Address.Values[0]

        # ``VportIndex.device_group_indices`` and
        # ``DeviceGroupIndex.network_group_indices`` are BOTH
        # ``Dict[int, ...]`` (taac/ixia/ixia.py:706-727), so the network
        # groups have to be walked with .values() -- iterating the mapping
        # yields its integer keys and every attribute access then fails with
        # "'int' object has no attribute 'network_group'". Seen for real on
        # hardware; the internal step's test mock models these as
        # lists of objects, which hides it.
        patcher_args = {}
        for network_group_index in device_group.network_group_indices.values():
            pools = network_group_index.network_group.Ipv6PrefixPools.find()
            for pool in pools:
                for prefix in pool.NetworkAddress.Values:
                    patcher_args[f"{prefix}/{mask}"] = json.dumps([next_hop])
        if not patcher_args:
            raise ValueError(
                f"oss-custom-step: device group {device_group_index} on "
                f"{egress_port} exposes no IPv6 prefix pool, so there is no "
                "prefix to point at the next hop."
            )

        self.logger.info(
            f"{self.hostname}: static route(s) {sorted(patcher_args)} via "
            f"{next_hop} ({egress_port}), patcher {patcher_name}"
        )
        # pyre-fixme[16]
        await self.driver.async_register_python_patcher(
            patcher_name=patcher_name,
            patcher_args=patcher_args,
            config_name="agent",
            py_func_name="add_static_routes",
            patcher_desc="",
        )
        # Registering is COOP's materialise step internally -- the config lands
        # on the box and the playbook's next AGENT restart picks it up. OSS
        # registration only fills an in-process registry, so without this the
        # route would never reach the DUT and the punt would never happen.
        #
        # ponytail: async_apply_patchers restarts the agent itself, so the
        # playbook's own service-interruption step is a second restart (~2 min).
        # Split the write/activate out of the driver if that wall-clock starts
        # to matter.
        # pyre-fixme[16]
        await self.driver.async_apply_patchers()


    async def change_interface_mtu_patcher(
        self, params: t.Dict[str, t.Any]
    ) -> None:
        """Shrink the DUT egress interface MTU so oversize frames punt.

        npi_cpu_039 sends 1700-byte frames at an interface it first drops to
        1500. The silicon does not re-read the MTU until the port is bounced,
        which the playbook does itself with two INTERFACE_FLAP_STEPs right
        after this step.
        """
        interface = params["interface"]
        mtu = params["mtu"]
        patcher_name = params.get("patcher_name", "mtu_exceed_patcher")
        self.logger.info(
            f"{self.hostname}: setting {interface} interface MTU to {mtu} "
            f"(patcher {patcher_name})"
        )
        # pyre-fixme[16]
        await self.driver.async_register_python_patcher(
            patcher_name=patcher_name,
            patcher_args={"interface": interface, "mtu": str(mtu)},
            config_name="agent",
            py_func_name="change_interface_mtu",
            patcher_desc="",
        )
        # Write + activate but do NOT restart: this playbook declares no
        # expected service restarts and bounces the port itself right after.
        # Restarting here failed its SERVICE_RESTART_CHECK and churned BGP for
        # the playbooks that followed.
        # pyre-fixme[16]
        await self.driver.async_apply_patchers(restart_services=False)
        # ...but activating the file alone leaves the RUNNING agent on its old
        # view, so the port bounce re-programs silicon from the stale MTU and
        # verify_interface_mtu still read the jumbo MTU. reloadConfig
        # is what COOP effectively does on apply: the agent re-reads the config
        # in place, no restart, so the postcheck stays clean.
        # pyre-fixme[16]
        await self.driver.async_agent_config_reload()

    async def verify_interface_mtu(self, params: t.Dict[str, t.Any]) -> None:
        """Fail loudly if the MTU change did not reach the agent.

        Without this the CPU_QUEUE_CHECK downstream would be asked to explain
        a missing punt while the interface was still at its jumbo MTU.
        """
        interface = params["interface"]
        expected = int(params["expected_mtu"])
        # pyre-fixme[16]
        interfaces = await self.driver.async_get_all_interfaces()
        for detail in interfaces.values():
            if interface in (detail.portNames or []):
                if detail.mtu != expected:
                    raise TestCaseFailure(
                        f"oss-custom-step: {self.hostname}:{interface} reports "
                        f"MTU {detail.mtu}, expected {expected} (interface "
                        f"{detail.interfaceName}, vlan {detail.vlanId}). The "
                        "patcher + port bounce did not reach the agent."
                    )
                self.logger.warning(
                    f"{self.hostname}: {interface} MTU is {detail.mtu} "
                    f"(interface {detail.interfaceName})"
                )
                return
        raise TestCaseFailure(
            f"oss-custom-step: no agent interface carries port {interface!r} "
            f"on {self.hostname} (checked {len(interfaces)} interfaces), so "
            "its MTU cannot be verified."
        )

    async def fpf_rapid_flap_lldp(self, params: t.Dict[str, t.Any]) -> None:
        """Rapid-flap the local ports whose LLDP neighbour matches, for a fixed window.

        Ports are resolved from LLDP rather than named, so the same step works on any bed
        where the neighbour is cabled to a different port set. ``neighbor_hosts`` is an exact
        match on the domain-stripped remote name and wins over ``neighbor_pattern`` when both
        are given -- an over-broad glob would flap links the playbook never meant to touch.

        The window is wall-clock bound and each pass flaps once, so the step stops on time
        even when flapping many ports takes longer than expected.
        """
        if params.get("fail_closed"):
            raise NotImplementedError(
                "oss-custom-step: fpf_rapid_flap_lldp fail_closed mode is not ported "
                "(it needs expected_interfaces reconciliation and the final-up poll). "
                "No OSS playbook sets it; port it here if one starts to."
            )

        duration_sec = int(params["duration_sec"])
        down_time_sec = float(params.get("down_time_sec", 6.0))
        up_time_sec = float(params.get("up_time_sec", down_time_sec))
        interval_to_link_up = int(params.get("flap_interval_sec", 1))
        hosts = params.get("neighbor_hosts")
        pattern = params.get("neighbor_pattern")

        # pyre-fixme[16]
        lldp = await self.driver.async_get_lldp_neighbors()
        if hosts:
            wanted = {h.split(".")[0].lower() for h in hosts}
            interfaces = tuple(
                sorted(
                    local
                    for local, data in lldp.items()
                    if (data.remote_device_name or "").split(".")[0].lower() in wanted
                )
            )
        elif pattern:
            glob = pattern.lower()
            interfaces = tuple(
                sorted(
                    local
                    for local, data in lldp.items()
                    if fnmatch.fnmatch((data.remote_device_name or "").lower(), glob)
                )
            )
        else:
            raise TestCaseFailure(
                "oss-custom-step: fpf_rapid_flap_lldp needs neighbor_hosts or "
                "neighbor_pattern; got neither."
            )

        if not interfaces:
            raise TestCaseFailure(
                f"oss-custom-step: no LLDP neighbour on {self.hostname} matches "
                f"{hosts or pattern!r} (saw "
                f"{sorted({(d.remote_device_name or '?') for d in lldp.values()})}), so "
                "there is nothing to flap. A stale pattern silently flapping nothing would "
                "make the playbook pass without testing anything."
            )

        self.logger.warning(
            f"{self.hostname}: rapid-flapping {interfaces} (LLDP neighbour "
            f"{hosts or pattern!r}) for {duration_sec}s, "
            f"down {down_time_sec}s / up {up_time_sec}s per cycle"
        )
        start = time.time()
        flaps = 0
        while time.time() - start < duration_sec:
            # pyre-fixme[16]
            await self.driver.async_do_rapid_interface_flaps(
                interface_names=interfaces,
                interval_to_link_up=interval_to_link_up,
                total_flaps=1,
                down_time_sec=down_time_sec,
                up_time_sec=up_time_sec,
            )
            flaps += 1
        self.logger.warning(
            f"{self.hostname}: rapid flap done, {flaps} cycle(s) in {duration_sec}s"
        )

    async def dump_traffic_item_stats(self, params: t.Dict[str, t.Any]) -> None:
        """Log IXIA Tx/Rx for named traffic items. Diagnostic only.

        npi_cpu_039 uses this to disambiguate "no output packet increase on
        queue 0": nonzero Tx means the silicon did not punt, zero Tx means
        IXIA never sent. It must never be the reason a playbook fails, so
        every error here is logged and swallowed.
        """
        names = params.get("traffic_item_names") or []
        if self.ixia is None:
            self.logger.warning(
                "oss-custom-step: dump_traffic_item_stats has no IXIA; skipping"
            )
            return
        # WARNING, not INFO, throughout: the whole point of this step is to be
        # readable in a FAILED run's output, and TAAC's console formatter does
        # not surface step-level INFO -- the dump was invisible in the very
        # run that needed it.
        #
        # Two sources, because get_latest_stats() reads the packet-loss capture,
        # which is empty when IXIA_PACKET_LOSS_CHECK is skipped -- that
        # silently produced no output at all. The traffic
        # variant falls back to a direct chassis read, so it survives that.
        found = 0
        for getter in ("get_latest_stats_traffic", "get_latest_stats"):
            fn = getattr(self.ixia, getter, None)
            if fn is None:
                continue
            try:
                got = fn() or []
            except Exception as exc:  # diagnostic only: never fail the playbook
                self.logger.warning(
                    f"[traffic-item-stats] {getter} raised {exc!r}; continuing"
                )
                continue
            self.logger.warning(
                f"[traffic-item-stats] {getter}: {len(got)} sample(s)"
            )
            for stat in got:
                ident = stat.get("identifier") if isinstance(stat, dict) else None
                if not names or ident in names:
                    found += 1
                    self.logger.warning(f"[traffic-item-stats] {stat}")
        if not found:
            self.logger.warning(
                f"[traffic-item-stats] nothing for {names or 'any item'} -- "
                "cannot say whether IXIA transmitted, so a missing punt is "
                "unclassified from this run"
            )


_HANDLERS: t.Dict[str, t.Callable[..., t.Awaitable[None]]] = {
    "register_cpu_queue_static_route_patcher": (
        OssCustomStep.register_cpu_queue_static_route_patcher
    ),
    "change_interface_mtu_patcher": OssCustomStep.change_interface_mtu_patcher,
    "verify_interface_mtu": OssCustomStep.verify_interface_mtu,
    "dump_traffic_item_stats": OssCustomStep.dump_traffic_item_stats,
    "fpf_rapid_flap_lldp": OssCustomStep.fpf_rapid_flap_lldp,
}
