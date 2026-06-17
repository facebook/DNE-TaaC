# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""KERNEL_STATE_SNAPSHOT_CHECK — composite kernel-state preservation HC for TAAC.

Captures kernel-side state on a FBOSS device pre and post a wedge_agent restart
(or other potentially-disruptive action) and verifies the L2 reconciliation path
did not orphan or lose any TUN interfaces, IP rules/addresses, FBOSS-installed
routes (proto 80), or trigger interface flaps.

Sections captured:
  - TUN interfaces (link + addresses) via `ip -br link/addr show type tun`
  - IP rules v4/v6 via `ip [-6] rule show`
  - IP addresses v4/v6 via `ip -br -[46] addr show`
  - Route counts by proto v4/v6 via `ip [-6] route show table all`
  - Proto-80 full route dumps v4/v6
  - Interface flap counters via `fboss2 show interface flaps`

Verdict matrix (from project_p41_taac_hc_design.md §2):
  - `expect_kernel_changes=False` (pure restart) — TUN / IP rules / proto-80 must
    be identical; BGP-like proto counts within `bgp_route_tolerance_pct`; any flap
    delta surfaces as WARN.
  - `expect_kernel_changes=True` (cp-swap / port-delete TCs) — TUN drift and
    proto-80 drift are reported not failed; IP rules still strict.

DSF-specific (`fboss2 show systemport`) deferred for Phase 4-1.
"""

import asyncio
import re
import typing as t

from taac.constants import TestDevice
from taac.health_checks.abstract_snapshot_health_check import (
    AbstractDeviceSnapshotHealthCheck,
)
from taac.health_checks.constants import Snapshot
from taac.health_check.health_check import types as hc_types


_DEFAULT_BGP_ROUTE_TOLERANCE_PCT = 5
# Leading "<priority>:" prefix from `ip rule show` output. Used to optionally
# strip the kernel-auto-assigned priority when comparing rules — a pure
# wedge_agent restart will re-install the same rule set but the auto-assigned
# priorities can shift (e.g. 32689 → 32678) without any functional change.
_IP_RULE_PRIORITY_PREFIX = re.compile(r"^\d+:\s*")
# Max entries to list inline before summarizing as "+N more" — keeps the
# operator message scannable when an HC fails with a large delta.
_DIFF_SAMPLE_LIMIT = 3


def _format_diff_samples(
    added: t.List[str], removed: t.List[str], limit: int = _DIFF_SAMPLE_LIMIT
) -> str:
    """Format added/removed lists for compact diff display in HC messages."""
    parts: t.List[str] = []
    if added:
        sample = ", ".join(added[:limit])
        more = f", and {len(added) - limit} more" if len(added) > limit else ""
        parts.append(f"+{len(added)} [{sample}{more}]")
    if removed:
        sample = ", ".join(removed[:limit])
        more = f", and {len(removed) - limit} more" if len(removed) > limit else ""
        parts.append(f"-{len(removed)} [{sample}{more}]")
    return " ".join(parts) or "no delta"


class TmKernelStateSnapshotHealthCheck(
    AbstractDeviceSnapshotHealthCheck[hc_types.BaseHealthCheckIn]
):
    """Composite kernel-state preservation check (pre/post snapshot)."""

    CHECK_NAME: hc_types.CheckName = hc_types.CheckName.KERNEL_STATE_SNAPSHOT_CHECK
    OPERATING_SYSTEMS: t.List[str] = ["FBOSS"]

    async def capture_pre_snapshot(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
        timestamp: int,
    ) -> Snapshot:
        data = await self._capture_kernel_state(obj)
        self.logger.info(
            f"[kernel_state] pre-snapshot on {obj.name}: "
            f"tun={len(data['tun_interfaces']['intfs'])} "
            f"proto80_v4={len(data['proto80_routes']['v4'])} "
            f"proto80_v6={len(data['proto80_routes']['v6'])}"
        )
        return Snapshot(data=data, timestamp=timestamp)

    async def capture_post_snapshot(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
        timestamp: int,
    ) -> Snapshot:
        data = await self._capture_kernel_state(obj)
        self.logger.info(
            f"[kernel_state] post-snapshot on {obj.name}: "
            f"tun={len(data['tun_interfaces']['intfs'])} "
            f"proto80_v4={len(data['proto80_routes']['v4'])} "
            f"proto80_v6={len(data['proto80_routes']['v6'])}"
        )
        return Snapshot(data=data, timestamp=timestamp)

    async def _capture_kernel_state(self, obj: TestDevice) -> t.Dict[str, t.Any]:
        """Capture all kernel-state sections in parallel via the device driver."""
        (
            tun_link_out,
            ip_rules_v4_out,
            ip_rules_v6_out,
            ip_addrs_v4_out,
            ip_addrs_v6_out,
            route_protos_v4_out,
            route_protos_v6_out,
            proto80_v4_out,
            proto80_v6_out,
            flaps_out,
        ) = await asyncio.gather(
            self._sh("ip -br link show type tun"),
            self._sh("ip rule show"),
            self._sh("ip -6 rule show"),
            self._sh("ip -br -4 addr show"),
            self._sh("ip -br -6 addr show"),
            self._sh(
                "ip -4 route show table all | "
                "grep -oE 'proto [a-zA-Z0-9_]+' | sort | uniq -c"
            ),
            self._sh(
                "ip -6 route show table all | "
                "grep -oE 'proto [a-zA-Z0-9_]+' | sort | uniq -c"
            ),
            self._sh("ip -4 route show table all | grep 'proto 80' || true"),
            self._sh("ip -6 route show table all | grep 'proto 80' || true"),
            self._sh("fboss2 show interface flaps"),
        )
        tun_intf_names = self._parse_tun_link(tun_link_out)
        ip_addresses_v4 = self._parse_br_addr(ip_addrs_v4_out)
        ip_addresses_v6 = self._parse_br_addr(ip_addrs_v6_out)
        # Derive TUN addresses from the already-captured `ip -br -[46] addr show`
        # output rather than running N extra `ip -br addr show <intf>` commands —
        # the latter spawns N concurrent SSH calls that throttle on platforms with
        # 100+ TUN interfaces.
        tun_addrs = {
            name: sorted(ip_addresses_v4.get(name, []) + ip_addresses_v6.get(name, []))
            for name in tun_intf_names
        }
        return {
            "tun_interfaces": {"intfs": tun_intf_names, "addrs": tun_addrs},
            "ip_rules": {
                "v4": self._parse_lines_sorted(ip_rules_v4_out),
                "v6": self._parse_lines_sorted(ip_rules_v6_out),
            },
            "ip_addresses": {
                "v4": ip_addresses_v4,
                "v6": ip_addresses_v6,
            },
            "route_counts": {
                "v4": self._parse_proto_counts(route_protos_v4_out),
                "v6": self._parse_proto_counts(route_protos_v6_out),
            },
            "proto80_routes": {
                "v4": self._parse_lines_sorted(proto80_v4_out),
                "v6": self._parse_lines_sorted(proto80_v6_out),
            },
            "flap_counters": self._parse_flap_counters(flaps_out),
        }

    async def _sh(self, cmd: str) -> str:
        # pyrefly: ignore [missing-attribute]
        result = await self.driver.async_run_cmd_on_shell(cmd)
        return result or ""

    @staticmethod
    def _parse_tun_link(output: str) -> t.List[str]:
        """`ip -br link show type tun` → sorted interface names (strip @ifNN suffix)."""
        names = []
        for line in output.splitlines():
            line = line.strip()
            if not line:
                continue
            name = line.split()[0].split("@")[0]
            names.append(name)
        return sorted(names)

    @staticmethod
    def _parse_lines_sorted(output: str) -> t.List[str]:
        return sorted(line.rstrip() for line in output.splitlines() if line.strip())

    @staticmethod
    def _parse_br_addr(output: str) -> t.Dict[str, t.List[str]]:
        """`ip -br -[46] addr show` → dict[intf → sorted list of addr/prefix]."""
        result: t.Dict[str, t.List[str]] = {}
        for line in output.splitlines():
            parts = line.split()
            if not parts:
                continue
            intf = parts[0].split("@")[0]
            addrs = sorted(p for p in parts[2:] if "/" in p)
            result[intf] = addrs
        return result

    @staticmethod
    def _parse_proto_counts(output: str) -> t.Dict[str, int]:
        """`uniq -c proto X` → dict[proto_name → count]."""
        result: t.Dict[str, int] = {}
        for line in output.splitlines():
            parts = line.split()
            if len(parts) >= 3 and parts[1] == "proto":
                try:
                    result[parts[2]] = int(parts[0])
                except ValueError:
                    continue
        return result

    @staticmethod
    def _parse_flap_counters(output: str) -> t.Dict[str, int]:
        """`fboss2 show interface flaps` → dict[intf → flap_count].

        Skips header line(s) and any line whose last column is not an integer.
        """
        result: t.Dict[str, int] = {}
        for line in output.splitlines():
            parts = line.split()
            if len(parts) < 2:
                continue
            try:
                result[parts[0]] = int(parts[-1])
            except ValueError:
                continue
        return result

    async def compare_snapshots(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
        pre_snapshot: Snapshot,
        post_snapshot: Snapshot,
    ) -> hc_types.HealthCheckResult:
        """Apply per-section verdict matrix from design memo §2."""
        expect_kernel_changes = bool(check_params.get("expect_kernel_changes", False))
        bgp_tolerance_pct = int(
            check_params.get(
                "bgp_route_tolerance_pct", _DEFAULT_BGP_ROUTE_TOLERANCE_PCT
            )
        )
        proto80_strict = bool(check_params.get("proto80_strict", True))
        ignore_ip_rule_priority = bool(
            check_params.get("ignore_ip_rule_priority", True)
        )
        pre = pre_snapshot.data
        post = post_snapshot.data
        sections: t.List[str] = []
        verdict = "PASS"

        verdict = self._compare_tun(pre, post, expect_kernel_changes, sections, verdict)
        verdict = self._compare_ip_rules(
            pre, post, ignore_ip_rule_priority, sections, verdict
        )
        verdict = self._compare_ip_addresses(
            pre, post, expect_kernel_changes, sections, verdict
        )
        verdict = self._compare_route_counts(
            pre, post, bgp_tolerance_pct, sections, verdict
        )
        verdict = self._compare_proto80(
            pre, post, expect_kernel_changes, proto80_strict, sections, verdict
        )
        verdict = self._compare_flaps(pre, post, sections, verdict)

        message = "[kernel_state] " + " | ".join(sections) + f" | verdict={verdict}"
        # WARN tolerated as PASS so the overall test can proceed
        status = (
            hc_types.HealthCheckStatus.FAIL
            if verdict == "FAIL"
            else hc_types.HealthCheckStatus.PASS
        )
        return hc_types.HealthCheckResult(status=status, message=message)

    @staticmethod
    def _compare_tun(
        pre: t.Dict,
        post: t.Dict,
        expect_changes: bool,
        sections: t.List[str],
        verdict: str,
    ) -> str:
        pre_t = pre["tun_interfaces"]
        post_t = post["tun_interfaces"]
        pre_intfs = pre_t["intfs"]
        post_intfs = post_t["intfs"]
        if pre_intfs == post_intfs and pre_t["addrs"] == post_t["addrs"]:
            sections.append(
                f"tun_intfs: {len(pre_intfs)}→{len(post_intfs)} preserved ✓"
            )
            return verdict
        if expect_changes:
            added = sorted(set(post_intfs) - set(pre_intfs))
            removed = sorted(set(pre_intfs) - set(post_intfs))
            sections.append(
                f"tun_intfs: {len(pre_intfs)}→{len(post_intfs)} "
                f"added={added} removed={removed}"
            )
            return verdict
        missing = sorted(set(pre_intfs) - set(post_intfs))
        if missing:
            sections.append(
                f"tun_intfs: {len(pre_intfs)}→{len(post_intfs)} MISSING {missing} ✗"
            )
        else:
            # Intf set identical but addresses drifted — surface the per-intf diff
            addr_diff = [
                f"{i}: {pre_t['addrs'].get(i, [])}→{post_t['addrs'].get(i, [])}"
                for i in pre_intfs
                if pre_t["addrs"].get(i) != post_t["addrs"].get(i)
            ]
            sections.append(
                f"tun_intfs: {len(pre_intfs)}→{len(post_intfs)} "
                f"addr drift on {len(addr_diff)} intf(s): "
                f"{addr_diff[:_DIFF_SAMPLE_LIMIT]} ✗"
            )
        return "FAIL"

    @staticmethod
    def _compare_ip_rules(
        pre: t.Dict,
        post: t.Dict,
        ignore_priority: bool,
        sections: t.List[str],
        verdict: str,
    ) -> str:
        for ver in ("v4", "v6"):
            pre_r = pre["ip_rules"][ver]
            post_r = post["ip_rules"][ver]
            if ignore_priority:
                pre_cmp = sorted(_IP_RULE_PRIORITY_PREFIX.sub("", r) for r in pre_r)
                post_cmp = sorted(_IP_RULE_PRIORITY_PREFIX.sub("", r) for r in post_r)
            else:
                pre_cmp, post_cmp = pre_r, post_r
            if pre_cmp == post_cmp:
                sections.append(
                    f"ip_rules_{ver}: {len(pre_r)}→{len(post_r)} preserved ✓"
                )
                continue
            added = sorted(set(post_cmp) - set(pre_cmp))
            removed = sorted(set(pre_cmp) - set(post_cmp))
            sections.append(
                f"ip_rules_{ver}: {len(pre_r)}→{len(post_r)} "
                f"{_format_diff_samples(added, removed)} ✗"
            )
            verdict = "FAIL"
        return verdict

    @staticmethod
    def _compare_ip_addresses(
        pre: t.Dict,
        post: t.Dict,
        expect_changes: bool,
        sections: t.List[str],
        verdict: str,
    ) -> str:
        for ver in ("v4", "v6"):
            pre_a = pre["ip_addresses"][ver]
            post_a = post["ip_addresses"][ver]
            if pre_a == post_a:
                sections.append(f"ip_addrs_{ver}: preserved ✓")
                continue
            drifted = sorted(
                intf
                for intf in (set(pre_a) | set(post_a))
                if pre_a.get(intf) != post_a.get(intf)
            )
            if expect_changes:
                non_tun_diff = [
                    intf for intf in drifted if not intf.startswith("fboss")
                ]
                if non_tun_diff:
                    drift_detail = [
                        f"{i}: {pre_a.get(i, [])}→{post_a.get(i, [])}"
                        for i in non_tun_diff[:_DIFF_SAMPLE_LIMIT]
                    ]
                    sections.append(f"ip_addrs_{ver}: non-TUN drift {drift_detail} ✗")
                    verdict = "FAIL"
                else:
                    sections.append(
                        f"ip_addrs_{ver}: TUN drift on "
                        f"{len(drifted)} intf(s) (expected) ⚠"
                    )
                continue
            drift_detail = [
                f"{i}: {pre_a.get(i, [])}→{post_a.get(i, [])}"
                for i in drifted[:_DIFF_SAMPLE_LIMIT]
            ]
            more = (
                f" (+{len(drifted) - _DIFF_SAMPLE_LIMIT} more)"
                if len(drifted) > _DIFF_SAMPLE_LIMIT
                else ""
            )
            sections.append(f"ip_addrs_{ver}: drift {drift_detail}{more} ✗")
            verdict = "FAIL"
        return verdict

    @staticmethod
    def _compare_route_counts(
        pre: t.Dict,
        post: t.Dict,
        tolerance_pct: int,
        sections: t.List[str],
        verdict: str,
    ) -> str:
        for ver in ("v4", "v6"):
            pre_c = pre["route_counts"][ver]
            post_c = post["route_counts"][ver]
            beyond: t.List[str] = []
            for proto in sorted(set(pre_c) | set(post_c)):
                if proto == "80":
                    continue
                pre_n = pre_c.get(proto, 0)
                post_n = post_c.get(proto, 0)
                if pre_n == 0:
                    if post_n > 0:
                        beyond.append(f"{proto}:0→{post_n}")
                    continue
                diff_pct = abs(post_n - pre_n) / pre_n * 100
                if diff_pct > tolerance_pct:
                    beyond.append(f"{proto}:{pre_n}→{post_n}({diff_pct:.1f}%)")
            if beyond:
                sections.append(f"route_{ver}: beyond tol {beyond} ⚠")
                if verdict == "PASS":
                    verdict = "WARN"
            else:
                sections.append(f"route_{ver}: within tol ✓")
        return verdict

    @staticmethod
    def _compare_proto80(
        pre: t.Dict,
        post: t.Dict,
        expect_changes: bool,
        strict: bool,
        sections: t.List[str],
        verdict: str,
    ) -> str:
        for ver in ("v4", "v6"):
            pre_p = pre["proto80_routes"][ver]
            post_p = post["proto80_routes"][ver]
            if pre_p == post_p:
                sections.append(
                    f"proto_80_{ver}: {len(pre_p)}→{len(post_p)} preserved ✓"
                )
                continue
            if expect_changes:
                added = sorted(set(post_p) - set(pre_p))
                removed = sorted(set(pre_p) - set(post_p))
                sections.append(
                    f"proto_80_{ver}: {len(pre_p)}→{len(post_p)} "
                    f"added={len(added)} removed={len(removed)}"
                )
                continue
            if strict:
                added = sorted(set(post_p) - set(pre_p))
                removed = sorted(set(pre_p) - set(post_p))
                sections.append(
                    f"proto_80_{ver}: {len(pre_p)}→{len(post_p)} "
                    f"drift {_format_diff_samples(added, removed)} ✗"
                )
                verdict = "FAIL"
            else:
                added = sorted(set(post_p) - set(pre_p))
                removed = sorted(set(pre_p) - set(post_p))
                sections.append(
                    f"proto_80_{ver}: drift (non-strict) "
                    f"{_format_diff_samples(added, removed)} ⚠"
                )
                if verdict == "PASS":
                    verdict = "WARN"
        return verdict

    @staticmethod
    def _compare_flaps(
        pre: t.Dict, post: t.Dict, sections: t.List[str], verdict: str
    ) -> str:
        pre_f = pre["flap_counters"]
        post_f = post["flap_counters"]
        per_intf = sorted(
            (
                (k, post_f.get(k, 0) - pre_f.get(k, 0))
                for k in (set(pre_f) | set(post_f))
                if post_f.get(k, 0) - pre_f.get(k, 0) > 0
            ),
            key=lambda x: -x[1],
        )
        delta = sum(d for _, d in per_intf)
        if delta == 0:
            sections.append("flaps: delta=0 ✓")
            return verdict
        top = ", ".join(f"{i}:+{d}" for i, d in per_intf[:_DIFF_SAMPLE_LIMIT])
        more = (
            f", +{len(per_intf) - _DIFF_SAMPLE_LIMIT} more"
            if len(per_intf) > _DIFF_SAMPLE_LIMIT
            else ""
        )
        sections.append(f"flaps: delta={delta} [{top}{more}] ⚠")
        if verdict == "PASS":
            verdict = "WARN"
        return verdict
