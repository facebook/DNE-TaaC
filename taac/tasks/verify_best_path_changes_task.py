# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe

import typing as t

from taac.tasks.base_task import BaseTask
from taac.utils.health_check_utils import ip_ntop


class VerifyBestPathChangesTask(BaseTask):
    """Task to verify that BGP local_pref churn triggers best-path recalculation.

    Runs TWO independent verification approaches and reports results for both.
    The task passes if EITHER approach detects changes.

    Approach 1 — "rib_path_count": Count the number of paths per CHURN prefix
    in the bgpcpp RIB. Before churn, each prefix has N paths (one per iBGP
    peer).  After origin churn sets some peers to INCOMPLETE, those paths are
    deprioritised → fewer paths in the best-path group.

    Approach 2 — "rib_version": Track rib_version from TRibEntry. This counter
    increments every time bgpcpp re-evaluates the entry, proving the decision
    process ran even if the winner doesn't change.

    Two modes:
      - "baseline": Record snapshots from all sources
      - "verify": Compare current snapshots to baseline, report all results
    """

    NAME = "verify_best_path_changes"

    # Class-level storage for baseline snapshots, keyed by hostname.
    _baseline_snapshots: t.ClassVar[t.Dict[str, t.Dict[str, t.Any]]] = {}

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        hostname = params.get("hostname") or self.hostname
        if not hostname:
            raise ValueError("hostname is required")

        mode = params.get("mode", "baseline")
        min_changed_ratio = params.get("min_changed_ratio", 0.3)
        max_probes = params.get("max_probes", 50)

        # Patterns to match CHURN prefixes (substring match on prefix string).
        churn_patterns = params.get("churn_patterns", ["102.100.", "6000:a001:"])

        self.logger.warning(
            f"VerifyBestPathChanges [{mode}] on {hostname} "
            f"(churn_patterns={churn_patterns}, max_probes={max_probes})"
        )

        # Run RIB-based approaches and collect snapshots
        (
            rib_snapshot,
            rib_version_snapshot,
            rib_path_count_snapshot,
        ) = await self._get_rib_snapshot(hostname, churn_patterns, max_probes)

        self.logger.warning(
            f"Discovered: RIB={len(rib_snapshot)} prefixes, "
            f"rib_version={len(rib_version_snapshot)} entries, "
            f"path_counts={len(rib_path_count_snapshot)} entries"
        )

        if not rib_snapshot:
            raise RuntimeError(
                f"No CHURN prefixes found in RIB on {hostname} "
                f"(patterns={churn_patterns}). Cannot proceed with {mode}."
            )

        if mode == "baseline":
            self._run_baseline(
                hostname,
                rib_snapshot,
                rib_version_snapshot,
                rib_path_count_snapshot,
            )
        elif mode == "verify":
            self._run_verify(
                hostname,
                rib_snapshot,
                rib_version_snapshot,
                rib_path_count_snapshot,
                min_changed_ratio,
            )
        else:
            raise ValueError(f"Unknown mode: {mode}. Must be 'baseline' or 'verify'.")

    # ------------------------------------------------------------------
    # bgpcpp RIB — best_next_hop + rib_version + path_count per prefix
    # ------------------------------------------------------------------

    async def _get_rib_snapshot(
        self,
        hostname: str,
        churn_patterns: t.List[str],
        max_probes: int,
    ) -> t.Tuple[t.Dict[str, str], t.Dict[str, str], t.Dict[str, str]]:
        """Query bgpcpp getRibEntries() and extract best_next_hop, rib_version, path_count."""
        nh_snapshot: t.Dict[str, str] = {}
        ver_snapshot: t.Dict[str, str] = {}
        path_count_snapshot: t.Dict[str, str] = {}
        try:
            from taac.internal.utils.bgp_client_helper import (
                BgpClientHelper,
            )

            bgp_helper = BgpClientHelper(hostname)
            rib_entries = await bgp_helper.async_get_bgp_rib_entries()

            self.logger.warning(
                f"  [RIB] Retrieved {len(rib_entries)} bgpcpp RIB entries from {hostname}"
            )

            discovered: t.Dict[str, t.Tuple[str, str, str]] = {}
            for entry in rib_entries:
                try:
                    prefix_ip = ip_ntop(entry.prefix.prefix_bin)
                    prefix_str = f"{prefix_ip}/{entry.prefix.num_bits}"
                except Exception:
                    continue

                if not any(pat in prefix_str for pat in churn_patterns):
                    continue

                # Extract best_next_hop
                best_nh = "none"
                if hasattr(entry, "best_next_hop") and entry.best_next_hop:
                    try:
                        best_nh = ip_ntop(entry.best_next_hop.prefix_bin)
                    except Exception:
                        best_nh = f"binary:{entry.best_next_hop.prefix_bin.hex()}"

                # Extract rib_version
                rib_ver = "unknown"
                if hasattr(entry, "rib_version"):
                    rib_ver = str(entry.rib_version)

                # Count paths (number of peers advertising this prefix)
                path_count = 0
                if hasattr(entry, "paths") and entry.paths:
                    for paths_list in entry.paths.values():
                        path_count += len(paths_list)

                discovered[prefix_str] = (best_nh, rib_ver, str(path_count))

            self.logger.warning(f"  [RIB] Found {len(discovered)} CHURN-range prefixes")

            for key in sorted(discovered.keys())[:max_probes]:
                best_nh, rib_ver, p_count = discovered[key]
                nh_snapshot[key] = best_nh
                ver_snapshot[key] = rib_ver
                path_count_snapshot[key] = p_count
                self.logger.warning(
                    f"    [RIB] {key} -> best_nh={best_nh}, "
                    f"rib_ver={rib_ver}, paths={p_count}"
                )

        except Exception as e:
            self.logger.warning(
                f"  [RIB] Failed to query bgpcpp RIB on {hostname}: {e}"
            )

        return nh_snapshot, ver_snapshot, path_count_snapshot

    # ------------------------------------------------------------------
    # Baseline / Verify logic
    # ------------------------------------------------------------------

    def _run_baseline(
        self,
        hostname: str,
        rib_snapshot: t.Dict[str, str],
        rib_version_snapshot: t.Dict[str, str],
        rib_path_count_snapshot: t.Dict[str, str],
    ) -> None:
        """Record baseline snapshots."""
        VerifyBestPathChangesTask._baseline_snapshots[hostname] = {
            "rib": rib_snapshot,
            "rib_version": rib_version_snapshot,
            "rib_path_count": rib_path_count_snapshot,
        }

        self.logger.warning(
            f"Baseline recorded for {hostname}: "
            f"RIB={len(rib_snapshot)} prefixes, "
            f"rib_version={len(rib_version_snapshot)} entries, "
            f"path_counts={len(rib_path_count_snapshot)} entries"
        )

        if rib_snapshot:
            self.logger.warning(
                f"{'Prefix':<45} {'best_next_hop':<40} {'rib_ver':<12} {'paths'}"
            )
            self.logger.warning("-" * 105)
            for key in sorted(rib_snapshot.keys()):
                nh = rib_snapshot[key]
                ver = rib_version_snapshot.get(key, "?")
                pc = rib_path_count_snapshot.get(key, "?")
                self.logger.warning(f"{key:<45} {nh:<40} {ver:<12} {pc}")

    def _run_verify(
        self,
        hostname: str,
        rib_current: t.Dict[str, str],
        rib_version_current: t.Dict[str, str],
        rib_path_count_current: t.Dict[str, str],
        min_changed_ratio: float,
    ) -> None:
        """Compare current snapshots to baseline."""
        baselines = VerifyBestPathChangesTask._baseline_snapshots.get(hostname)
        if not baselines:
            raise RuntimeError(
                f"No baseline snapshot found for {hostname}. "
                f"Run with mode='baseline' first."
            )

        rib_baseline = baselines.get("rib", {})
        rib_ver_baseline = baselines.get("rib_version", {})
        path_count_baseline = baselines.get("rib_path_count", {})

        # Approach 1: RIB path count (origin churn → fewer valid paths)
        pc_result = self._compare_path_counts(
            hostname, path_count_baseline, rib_path_count_current
        )
        # Approach 2: rib_version (any re-evaluation increments it)
        ver_result = self._compare_rib_versions(
            hostname, rib_ver_baseline, rib_version_current
        )
        # Also compare RIB best_next_hop for informational purposes
        rib_result = self._compare_snapshots("RIB", hostname, rib_baseline, rib_current)

        # Report summary
        self.logger.warning("=" * 80)
        self.logger.warning("VERIFICATION SUMMARY")
        self.logger.warning("=" * 80)
        self.logger.warning(
            f"  [PATH_COUNT] path count changed: {pc_result[0]}/{pc_result[1]} "
            f"= {pc_result[2]:.1%}"
        )
        self.logger.warning(
            f"  [RIB_VERSION] rib_version increased: {ver_result[0]}/{ver_result[1]} "
            f"= {ver_result[2]:.1%}"
        )
        self.logger.warning(
            f"  [RIB] best_next_hop changed: {rib_result[0]}/{rib_result[1]} "
            f"= {rib_result[2]:.1%} (informational)"
        )
        self.logger.warning(f"  Threshold: {min_changed_ratio:.0%}")

        # Pass if ANY approach shows sufficient changes
        pc_passed = pc_result[1] > 0 and pc_result[2] >= min_changed_ratio
        ver_passed = ver_result[1] > 0 and ver_result[2] >= min_changed_ratio

        if pc_passed:
            self.logger.warning(
                f"  [PATH_COUNT] PASSED — path count changed for {pc_result[2]:.1%} "
                f"of prefixes. Origin churn IS deprioritising paths."
            )
        else:
            self.logger.warning(
                f"  [PATH_COUNT] path count: {pc_result[2]:.1%} changed "
                f"(need >= {min_changed_ratio:.0%})"
            )

        if ver_passed:
            self.logger.warning(
                f"  [RIB_VERSION] PASSED — {ver_result[2]:.1%} of entries "
                f"re-evaluated (rib_version increased). bgpcpp IS processing "
                f"route changes."
            )
        else:
            self.logger.warning(
                f"  [RIB_VERSION] rib_version: {ver_result[2]:.1%} increased "
                f"(need >= {min_changed_ratio:.0%})"
            )

        if pc_passed or ver_passed:
            self.logger.warning(
                "Best-path verification PASSED (at least one approach succeeded)."
            )
        else:
            raise AssertionError(
                f"Best-path verification FAILED on {hostname}: "
                f"PATH_COUNT={pc_result[0]}/{pc_result[1]} ({pc_result[2]:.1%}), "
                f"RIB_VERSION={ver_result[0]}/{ver_result[1]} ({ver_result[2]:.1%}). "
                f"No approach detected >= {min_changed_ratio:.0%} changes. "
                f"Attribute churn may not be reaching the DUT."
            )

    def _compare_snapshots(
        self,
        label: str,
        hostname: str,
        baseline: t.Dict[str, str],
        current: t.Dict[str, str],
    ) -> t.Tuple[int, int, float]:
        """Compare baseline vs current snapshot, return (changed, total, ratio)."""
        if not baseline:
            self.logger.warning(f"  [{label}] No baseline data — skipping comparison")
            return (0, 0, 0.0)

        changed_count = 0
        total_compared = 0

        self.logger.warning(f"[{label}] Comparison for {hostname}:")
        self.logger.warning(
            f"{'Prefix':<45} {'Baseline':<45} {'Current':<45} {'Changed?'}"
        )
        self.logger.warning("-" * 145)

        for key in sorted(baseline.keys()):
            baseline_val = baseline[key]
            current_val = current.get(key)
            if current_val is None:
                self.logger.warning(
                    f"{key:<45} {baseline_val[:44]:<45} {'missing':<45} -"
                )
                continue
            changed = baseline_val != current_val
            if changed:
                changed_count += 1
            total_compared += 1
            self.logger.warning(
                f"{key:<45} {baseline_val[:44]:<45} {current_val[:44]:<45} "
                f"{'YES' if changed else 'no'}"
            )

        if total_compared == 0:
            self.logger.warning(f"  [{label}] No entries to compare")
            return (0, 0, 0.0)

        ratio = changed_count / total_compared
        self.logger.warning(
            f"  [{label}] Changed: {changed_count}/{total_compared} = {ratio:.1%}"
        )
        return (changed_count, total_compared, ratio)

    def _compare_path_counts(
        self,
        hostname: str,
        baseline: t.Dict[str, str],
        current: t.Dict[str, str],
    ) -> t.Tuple[int, int, float]:
        """Compare path counts baseline vs current, return (changed, total, ratio).

        After origin churn (some peers set to INCOMPLETE), path counts should
        decrease because INCOMPLETE-origin paths are deprioritised by bgpcpp.
        """
        if not baseline:
            self.logger.warning("  [PATH_COUNT] No baseline data — skipping comparison")
            return (0, 0, 0.0)

        changed_count = 0
        total_compared = 0

        self.logger.warning(f"[PATH_COUNT] Comparison for {hostname}:")
        self.logger.warning(
            f"{'Prefix':<45} {'Baseline':<12} {'Current':<12} {'Changed?'}"
        )
        self.logger.warning("-" * 80)

        for key in sorted(baseline.keys()):
            baseline_val = baseline[key]
            current_val = current.get(key)
            if current_val is None:
                self.logger.warning(f"{key:<45} {baseline_val:<12} {'missing':<12} -")
                continue

            total_compared += 1
            changed = baseline_val != current_val
            if changed:
                changed_count += 1
            self.logger.warning(
                f"{key:<45} {baseline_val:<12} {current_val:<12} "
                f"{'YES' if changed else 'no'}"
            )

        if total_compared == 0:
            self.logger.warning("  [PATH_COUNT] No entries to compare")
            return (0, 0, 0.0)

        ratio = changed_count / total_compared
        self.logger.warning(
            f"  [PATH_COUNT] Changed: {changed_count}/{total_compared} = {ratio:.1%}"
        )
        return (changed_count, total_compared, ratio)

    def _compare_rib_versions(
        self,
        hostname: str,
        baseline: t.Dict[str, str],
        current: t.Dict[str, str],
    ) -> t.Tuple[int, int, float]:
        """Compare rib_version baseline vs current, return (increased, total, ratio)."""
        if not baseline:
            self.logger.warning(
                "  [RIB_VERSION] No baseline data — skipping comparison"
            )
            return (0, 0, 0.0)

        increased_count = 0
        total_compared = 0

        self.logger.warning(f"[RIB_VERSION] Comparison for {hostname}:")
        self.logger.warning(
            f"{'Prefix':<45} {'Baseline ver':<15} {'Current ver':<15} {'Increased?'}"
        )
        self.logger.warning("-" * 85)

        for key in sorted(baseline.keys()):
            baseline_ver = baseline[key]
            current_ver = current.get(key)
            if current_ver is None:
                self.logger.warning(f"{key:<45} {baseline_ver:<15} {'missing':<15} -")
                continue

            total_compared += 1
            try:
                increased = int(current_ver) > int(baseline_ver)
            except (ValueError, TypeError):
                increased = current_ver != baseline_ver

            if increased:
                increased_count += 1
            self.logger.warning(
                f"{key:<45} {baseline_ver:<15} {current_ver:<15} "
                f"{'YES' if increased else 'no'}"
            )

        if total_compared == 0:
            self.logger.warning("  [RIB_VERSION] No entries to compare")
            return (0, 0, 0.0)

        ratio = increased_count / total_compared
        self.logger.warning(
            f"  [RIB_VERSION] Increased: {increased_count}/{total_compared} "
            f"= {ratio:.1%}"
        )
        return (increased_count, total_compared, ratio)
