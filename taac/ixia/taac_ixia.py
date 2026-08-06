# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import ipaddress
import os
import threading
import time
import typing as t
from collections import defaultdict
from threading import Thread

TAAC_OSS = os.environ.get("TAAC_OSS", "").lower() in ("1", "true", "yes")

from ixia.ixia import types as ixia_types
from ixnetwork_restpy.assistants.statistics.statviewassistant import (
    StatViewAssistant as IxnStatViewAssistant,
)
from ixnetwork_restpy.files import Files
from taac.ixia.abstract_traffic_generator import (
    AbstractTrafficGenerator,
)
from taac.ixia.ixia import Ixia
from taac.utils.oss_taac_lib_utils import (  # oss-rewrite (force ShipIt re-export to taac.* root)
    none_throws,
    retryable,
)
from uhd_restpy.assistants.statistics.statviewassistant import (
    StatViewAssistant as UhdStatViewAssistant,
)

StatViewAssistant = t.Union[IxnStatViewAssistant, UhdStatViewAssistant]

# Background periodic stat sampler interval (Scuba logging support).
# Each sample takes a `DefaultSnapshotSettings` snapshot on the IXIA chassis,
# which is a global per-chassis resource. On shared chassis (e.g. ixia19+ixia20)
# a too-aggressive interval contends with both our own foreground HCs and other
# tenants' snapshot calls, producing the chassis-side
# `Snapshot DefaultSnapshotSettings already in progress` error and stalling
# both threads. Empirically a 2s interval was observed to hang IcePack
# cpu_queue runs at the very first postcheck's IxiaPacketLossHealthCheck on
# a busy chassis.
#
# Default remains 2s for back-compat with existing TestConfigs that rely on
# per-stage Scuba telemetry freshness. Override via env
# `TAAC_IXIA_SAMPLE_INTERVAL_S` to raise the cadence on a per-run basis;
# set to `0` to disable the periodic sampler entirely (foreground HC stat
# reads still work via the direct-snapshot fallback in `get_latest_stats`).
_DEFAULT_SAMPLE_INTERVAL_FALLBACK_S = 2
try:
    DEFAULT_SAMPLE_RATE = int(
        os.environ.get(
            "TAAC_IXIA_SAMPLE_INTERVAL_S",
            str(_DEFAULT_SAMPLE_INTERVAL_FALLBACK_S),
        )
    )
except (TypeError, ValueError):
    DEFAULT_SAMPLE_RATE = _DEFAULT_SAMPLE_INTERVAL_FALLBACK_S

VIEW_TO_IDENTIFIER: t.Dict[str, str] = {
    "Traffic Item Statistics": "Traffic Item",
}

TRAFFIC_ITEM_VIEW = "Traffic Item Statistics"

PTP_DRILL_DOWN_VIEW = "PTP Drill Down"


PTP_CONFIGURED_ROLE = "Configured Role"
PTP_STATE = "PTP State"
PTP_PROTOCOL = "Protocol"
PTP_DEVICE_NUM = "Device#"
PTP_OFFSET_NS = "Offset [ns]"


class TaacIxia(Ixia, Thread, AbstractTrafficGenerator):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        Thread.__init__(self, daemon=True)
        self.capturing: bool = False
        self.captured_stats = defaultdict(dict)
        self.captured_stats_traffic = defaultdict(dict)
        self.captured_ptp_drill_down_stats = defaultdict(dict)
        self.sample_time: int = DEFAULT_SAMPLE_RATE
        self.test_case_uuid: t.Optional[str] = None
        self.paused = False
        self._in_flight = False
        self.saved_configs = {}
        self._snapshot_lock = threading.Lock()

        self.traffic_item_view_assistant = None
        self.ptp_drill_down_view_assistant = None

        # Per-view StatViewAssistant cache. Created lazily by
        # get_or_create_stat_view(); reused across HC invocations so we pay the
        # ~10-15s subscription/ready-wait cost ONCE per view per test run instead
        # of on every call. Rows reads off the cached assistant always fetch
        # fresh data on access.
        self._stat_view_cache: t.Dict[str, StatViewAssistant] = {}
        # _stat_view_index_lock protects the cache dict + the per-view lock
        # registry below. It is held ONLY for the brief dict get/set — never
        # across StatViewAssistant construction.
        self._stat_view_index_lock = threading.Lock()
        # Per-view-name locks. A first-time access to view A only blocks other
        # first-time accesses to view A; concurrent first-time accesses to
        # different views proceed in parallel.
        self._stat_view_construction_locks: t.Dict[str, threading.Lock] = {}

    def _get_stat_view_construction_lock(self, view_name: str) -> threading.Lock:
        """Get (or create) the per-view construction lock under index lock."""
        with self._stat_view_index_lock:
            lock = self._stat_view_construction_locks.get(view_name)
            if lock is None:
                lock = threading.Lock()
                self._stat_view_construction_locks[view_name] = lock
            return lock

    def get_or_create_stat_view(
        self,
        view_name: str,
        timeout: int = 30,
    ) -> StatViewAssistant:
        """Cached factory for `StatViewAssistant` instances, keyed by view_name.

        First call constructs the assistant (subscribes to the view + waits
        for ReadyState). Subsequent calls with the same view_name return the
        cached assistant — `.Rows` always returns fresh data on access, so
        no manual refresh is needed.

        Caveats:
        - `timeout` is honored ONLY on the first call for a given view_name.
          Subsequent callers receive the cached assistant constructed with the
          original timeout. If you need a different timeout, invalidate first.
        - Concurrent first-time accesses to DIFFERENT views proceed in parallel
          (each view has its own construction lock); only same-view first-time
          accesses serialize.

        Use this instead of `StatViewAssistant(self.ixnetwork, view_name)` from
        any code path that runs more than once per test (HCs, periodic tasks,
        traffic/protocol verifications).
        """
        # Fast path: dict read under brief index lock.
        with self._stat_view_index_lock:
            cached = self._stat_view_cache.get(view_name)
            if cached is not None:
                return cached
        # Slow path: serialize first-time construction PER view_name, so a
        # construction of view A does NOT block a construction of view B.
        construction_lock = self._get_stat_view_construction_lock(view_name)
        with construction_lock:
            # Re-check under the per-view lock to avoid two threads racing past
            # the index-lock fast path and both constructing the same view.
            with self._stat_view_index_lock:
                cached = self._stat_view_cache.get(view_name)
                if cached is not None:
                    return cached
            stat_view_cls = (
                UhdStatViewAssistant if self.is_uhd_chassis else IxnStatViewAssistant
            )
            assistant = stat_view_cls(self.ixnetwork, view_name, Timeout=timeout)
            with self._stat_view_index_lock:
                self._stat_view_cache[view_name] = assistant
            return assistant

    def invalidate_stat_view_cache(self, view_name: t.Optional[str] = None) -> None:
        """Drop cached StatViewAssistant(s).

        Call when the IXIA session is recreated or topology is destroyed. With
        `view_name=None`, clears all entries; otherwise drops just that view.
        Per-view construction locks are NOT dropped — they're cheap to keep and
        the next call will re-use them safely.
        """
        with self._stat_view_index_lock:
            if view_name is None:
                self._stat_view_cache.clear()
            else:
                self._stat_view_cache.pop(view_name, None)

    @retryable(sleep_time=2, num_tries=100, print_ex=True)
    def start_capturing(self, sample_time: int):
        """
        Start capturing statistics.
        Args:
            sample_time (int): Time interval between samples.
        """

        while self.capturing:
            try:
                if not self.paused:
                    self._in_flight = True
                    timestamp = int(time.time())
                    uuid = none_throws(self.test_case_uuid)
                    with self._snapshot_lock:
                        # Capture traffic rate statistics
                        self._capture_traffic_rate_stats(
                            self.traffic_item_view_assistant, uuid, timestamp
                        )
                        # Capture packet loss statistics
                        self._capture_packet_loss_stats(
                            self.traffic_item_view_assistant, uuid, timestamp
                        )
                        # Capture PTP drill down statistics
                        self._capture_ptp_drill_down_stats(
                            self.ptp_drill_down_view_assistant, uuid, timestamp
                        )
            finally:
                self._in_flight = False
            time.sleep(sample_time)

    def _capture_traffic_rate_stats(
        self,
        view_assistant: t.Optional[StatViewAssistant],
        uuid: str,
        timestamp: float,
    ):
        """
        Capture traffic rate statistics.
        """
        if not view_assistant:
            return
        try:
            latest_stats_traffic = self.get_traffic_rate_statistics(view_assistant)
            self.captured_stats_traffic[uuid][timestamp] = latest_stats_traffic
            self.captured_stats_traffic[uuid]["latest"] = latest_stats_traffic
        except Exception as e:
            self.logger.debug(
                f"Encountered error when capturing traffic rate statistics: {e}"
            )

    def _capture_packet_loss_stats(
        self,
        view_assistant: t.Optional[StatViewAssistant],
        uuid: str,
        timestamp: float,
    ):
        """
        Capture packet loss statistics
        """
        if not view_assistant:
            return
        try:
            latest_stats = self.get_packet_loss_statistics(view_assistant)
            self.captured_stats[uuid][timestamp] = latest_stats
            self.captured_stats[uuid]["latest"] = latest_stats
        except Exception as e:
            self.logger.debug(
                f"Encountered error when capturing packet loss statistics: {e}"
            )

    def _capture_ptp_drill_down_stats(
        self,
        ptp_drill_down_view_assistant: t.Optional[StatViewAssistant],
        uuid: str,
        timestamp: float,
    ):
        """
        Capture PTP drill down statistics.
        """
        if not ptp_drill_down_view_assistant:
            return
        try:
            latest_ptp_drill_down_stats = self.get_ptp_drill_down_statistics(
                ptp_drill_down_view_assistant
            )
            self.captured_ptp_drill_down_stats[uuid][timestamp] = (
                latest_ptp_drill_down_stats
            )
        except Exception as e:
            self.logger.debug(
                f"Encountered error when capturing PTP drill down statistics: {e}"
            )

    @retryable(sleep_time=2, num_tries=100)
    def get_packet_loss_statistics(
        self,
        view: StatViewAssistant,
    ) -> t.List:
        stats = []
        view_name = view._ViewName
        for row in view.Rows:
            stat = {}
            stat["identifier"] = row[VIEW_TO_IDENTIFIER[view_name]]
            if "Packet Loss Duration (ms)" in row.Columns:
                raw = row["Packet Loss Duration (ms)"]
                stat["packet_loss_duration"] = float(raw) if raw != "" else 0.0
            if "Loss %" in row.Columns:
                raw = row["Loss %"]
                stat["packet_loss_percentage"] = float(raw) if raw != "" else 0.0
            if "Frames Delta" in row.Columns:
                raw = row["Frames Delta"]
                stat["frame_delta"] = float(raw) if raw != "" else 0.0
            stat["view"] = view_name
            stats.append(stat)
        return stats

    @retryable(sleep_time=2, num_tries=100)
    def get_traffic_rate_statistics(
        self,
        view: StatViewAssistant,
    ) -> t.List:
        stats = []
        view_name = view._ViewName
        for row in view.Rows:
            stat = {}
            stat["identifier"] = row[VIEW_TO_IDENTIFIER[view_name]]
            if "Tx Rate (Mbps)" in row.Columns:
                stat["Tx Rate"] = float(row["Tx Rate (Mbps)"])
            if "Rx Rate (Mbps)" in row.Columns:
                stat["Rx Rate"] = float(row["Rx Rate (Mbps)"])
            stat["view"] = view_name
            stats.append(stat)
        return stats

    @retryable(sleep_time=2, num_tries=100)
    def get_ptp_drill_down_statistics(
        self, ptp_drill_down_view: StatViewAssistant
    ) -> t.Dict:
        ptp_stats = {}
        for row in ptp_drill_down_view.Rows:
            id = f"{row[PTP_PROTOCOL]}_{row[PTP_DEVICE_NUM]}"
            stat = {
                "clock_role": row[PTP_CONFIGURED_ROLE],
                "offset_ns": int(row[PTP_OFFSET_NS]),
                "ptp_state": row[PTP_STATE],
            }
            ptp_stats[id] = stat
        return ptp_stats

    def log_to_scuba_ixia_packet_loss(self, test_case_uuid: str) -> None:
        if TAAC_OSS:
            self.logger.info(
                f"OSS mode: Skipping Scuba logging for test case {test_case_uuid}. "
                "Packet loss stats available via get_packet_loss_stats()."
            )
            return

        from rfe.scubadata.scubadata_py3 import Sample, ScubaData

        samples = []
        while self._in_flight:
            time.sleep(0.1)
        for timestamp, stats in self.captured_stats[test_case_uuid].items():
            if timestamp == "latest":
                continue
            for stat in stats:
                sample = Sample()
                sample.addTimestamp(ScubaData.TIME_COLUMN, timestamp)
                sample.addNormalValue("identifier", stat["identifier"])
                sample.addNormalValue("view", stat["view"])
                sample.addNormalValue("test_case_uuid", test_case_uuid)
                if "packet_loss_duration" in stat:
                    sample.addDoubleValue(
                        "packet_loss_duration", stat["packet_loss_duration"]
                    )
                if "packet_loss_percentage" in stat:
                    sample.addDoubleValue(
                        "packet_loss_percentage", stat["packet_loss_percentage"]
                    )
                if "frame_delta" in stat:
                    sample.addDoubleValue("frame_delta", stat["frame_delta"])
                samples.append(sample)
        self.logger.info(f"Logging {len(samples)} samples to scuba")
        with ScubaData("ixia_packet_loss") as scubadata:
            try:
                for sample in samples:
                    scubadata.add_sample(sample)
            except Exception as ex:
                self.logger.error(f"Error logging result to scuba: {ex}")

    @retryable(sleep_time=2, num_tries=3)
    def get_latest_stats(
        self,
        max_timeout_sec: int = 180,
        since_time: float = 0,
    ) -> t.List:
        """
        Get the latest packet loss stats
        Args:
            max_timeout_sec (int, optional): Maximum timeout in seconds. Defaults to 120.
            since_time (float, optional): If provided, only return stats with a timestamp >= since_time.
        """
        timeout_time = time.time() + max_timeout_sec
        packet_loss_stats = self.captured_stats[self.test_case_uuid]
        try:
            # Short-circuit when the background sampler is disabled
            # (sample_time=0 → self.capturing never gets set). The cached
            # stats will never refresh, so don't waste max_timeout_sec waiting.
            if not self.capturing:
                raise Exception("Periodic sampler disabled; using direct snapshot")
            while not (
                packet_loss_stats and next(reversed(packet_loss_stats)) > since_time
            ):
                if time.time() > timeout_time:
                    raise Exception("Timeout waiting for stats")
                time.sleep(0.1)
            return packet_loss_stats["latest"]
        except Exception:
            # Acquire lock to serialize with the background capture thread's
            # TakeCsvSnapshot calls. The IXIA chassis only allows one snapshot
            # at a time ("Snapshot DefaultSnapshotSettings already in progress").
            # Use a timeout to avoid blocking the asyncio event loop indefinitely.
            if not self._snapshot_lock.acquire(timeout=600):
                self.logger.warning(
                    "Timed out waiting for IXIA snapshot lock, proceeding without lock"
                )
                return self.get_packet_loss_statistics(self.traffic_item_view_assistant)
            try:
                return self.get_packet_loss_statistics(self.traffic_item_view_assistant)
            finally:
                self._snapshot_lock.release()

    def get_latest_stats_traffic(
        self,
        max_timeout_sec: int = 120,
        since_time: float = 0,
    ) -> t.List:
        """
        Get the latest traffic rate stats.
        Args:
            max_timeout_sec (int, optional): Maximum timeout in seconds. Defaults to 120.
            since_time (float, optional): If provided, only return stats with a timestamp >= since_time.
        """
        timeout_time = time.time() + max_timeout_sec
        traffic_rate_stats = self.captured_stats_traffic[self.test_case_uuid]
        while not (
            traffic_rate_stats and next(reversed(traffic_rate_stats)) > since_time
        ):
            if time.time() > timeout_time:
                raise Exception("Timeout waiting for stats")
            time.sleep(0.1)
        return self.captured_stats_traffic[self.test_case_uuid]["latest"]

    def run(self):
        # sample_time=0 disables the background periodic sampler entirely.
        # Foreground HC stat reads (get_latest_stats) still work via the
        # fallback direct-snapshot path; only the continuous Scuba-logging
        # loop is skipped. Use for TestConfigs that don't need per-stage
        # Scuba telemetry and run on heavily-shared IXIA chassis where the
        # default polling cadence triggers DefaultSnapshotSettings lockdown.
        if self.sample_time <= 0:
            self.logger.info(
                "TaacIxia periodic stat sampler DISABLED "
                "(sample_time=0; override via TAAC_IXIA_SAMPLE_INTERVAL_S env)"
            )
            self.capturing = False
            return
        self.capturing = True
        self.start_capturing(self.sample_time)

    def export_json_config(self) -> str:
        json_config = self.session.Ixnetwork.ResourceManager.ExportConfig(
            ["/descendant-or-self::*"],
            False,
            "json",
        )
        return json_config

    def export_and_save_config(self) -> None:
        self.logger.info(f"Saving ixia config for {self.test_case_uuid}")
        json_config = self.export_json_config()
        self.saved_configs[self.test_case_uuid] = json_config

    def import_json_config(self, json_config: str) -> None:
        self.session.Ixnetwork.ResourceManager.ImportConfig(json_config, False)
        self.start_and_verify_protocols()
        self.enable_traffic()
        self.start_traffic(regenerate_traffic_items=True)
        time.sleep(5)
        self.stop_traffic()
        self.enable_traffic(enable=False)

    def import_saved_config(self) -> None:
        self.logger.info(f"Importing saved ixia config for {self.test_case_uuid}")
        self.import_json_config(self.saved_configs[self.test_case_uuid])

    # =========================================================================
    # .ixncfg file-based caching methods (for chassis persistence)
    # =========================================================================

    def save_config_to_chassis(self, config_path: str) -> bool:
        """
        Save current IXIA configuration to chassis as .ixncfg file.

        This allows the configuration to be reloaded on subsequent test runs,
        significantly reducing IXIA setup time.

        Args:
            config_path: Full path on chassis where to save the config
                         (e.g., "/root/taac_configs/bag002_snc1.ixncfg")

        Returns:
            True if save was successful, False otherwise
        """
        try:
            self.logger.info(f"Saving IXIA config to chassis: {config_path}")
            # `SaveConfig(Arg1)` expects a `Files` handle, not a raw string.
            # Passing a bare string causes IxNetwork to fall back to its default
            # storage location with just the basename — the directory part of
            # our absolute path is silently dropped. Wrap with
            # `Files(path, local_file=False)` so the server treats the value
            # as an absolute server-side write target.
            self.session.Ixnetwork.SaveConfig(Files(config_path, local_file=False))
            self.logger.info(f"Successfully saved IXIA config: {config_path}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to save IXIA config to chassis: {e}")
            return False

    def load_config_from_chassis(self, config_path: str) -> bool:
        """
        Load IXIA configuration from chassis .ixncfg file.

        If the config file exists and can be loaded, this is much faster than
        setting up IXIA from scratch (~1-2 min vs ~10-15 min).

        Args:
            config_path: Full path on chassis to load config from
                         (e.g., "/root/taac_configs/bag002_snc1.ixncfg")

        Returns:
            True if load was successful, False otherwise (fallback to full setup)
        """
        try:
            self.logger.info(
                f"Attempting to load IXIA config from chassis: {config_path}"
            )
            # `LoadConfig(Arg1)` expects a `Files` handle — see SaveConfig
            # comment above. `local_file=False` tells the server to read from
            # the exact absolute path provided (not upload from client + load
            # from server default).
            self.session.Ixnetwork.LoadConfig(Files(config_path, local_file=False))
            self.logger.info(f"Successfully loaded IXIA config: {config_path}")

            # LoadConfig restores vport definitions and their `location`
            # attributes but does NOT re-bind them to physical chassis ports —
            # start_protocols then fails with `No ports assigned to the Port
            # Group`. `AssignPorts(True)` reads the saved `location` on each
            # vport and re-acquires the underlying hardware port (True = clear
            # ownership first to handle stale grabs). Discovered via bag012
            # e2e 2026-06-05 when Tier 2 LoadConfig succeeded but protocol
            # start failed.
            self.session.Ixnetwork.AssignPorts(True)
            self.start_and_verify_protocols()
            return True
        except Exception as e:
            self.logger.info(
                f"Could not load IXIA config from {config_path}: {e}. "
                "Will fall back to full setup."
            )
            return False

    def enable_protocol(self, enable: bool = True) -> None:
        if enable:
            self.logger.info("Enabling protocols")
            self.start_protocols()
        else:
            self.logger.info("Disabling protocols")
            self.stop_protocols()

    def wait_for_view_assistants_ready(self):
        self.traffic_item_view_assistant = self._get_traffic_item_view()
        self.ptp_drill_down_view_assistant = self._get_ptp_drill_down_view()

    @retryable(sleep_time=5, num_tries=2)
    def _get_ptp_drill_down_view(
        self,
    ) -> t.Optional[StatViewAssistant]:
        StatViewAssistant = (
            UhdStatViewAssistant if self.is_uhd_chassis else IxnStatViewAssistant
        )
        ptp_enabled = False
        protocols_summary = StatViewAssistant(self.ixnetwork, "Protocols Summary")
        for row in protocols_summary.Rows:
            if row["Protocol Type"] == "PTP":
                self.logger.info("PTP is enabled in the ixia setup")
                ptp_enabled = True
                break
        if not ptp_enabled:
            self.logger.debug("PTP is not enabled in the ixia setup")
            return
        try:
            _view = self.ixnetwork.Statistics.View.find(Caption=PTP_DRILL_DOWN_VIEW)
            _view.Refresh()
            view = StatViewAssistant(self.ixnetwork, PTP_DRILL_DOWN_VIEW, Timeout=60)
            return view
        except Exception as e:
            if "has no data available" in str(e):
                raise e
            self.logger.error(f"Error getting PTP drill down view: {e}")

    @retryable(sleep_time=5, num_tries=2)
    def _get_traffic_item_view(self) -> t.Optional[StatViewAssistant]:
        StatViewAssistant = (
            UhdStatViewAssistant if self.is_uhd_chassis else IxnStatViewAssistant
        )
        all_traffic_items = self.get_traffic_items()
        enabled_traffic_items = [
            traffic_item for traffic_item in all_traffic_items if traffic_item.Enabled
        ]
        traffic_item_tracking_enabled = False
        for traffic_item in enabled_traffic_items:
            if (
                ixia_types.TRAFFIC_STATS_TRACKING_TYPE_MAP[
                    ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM
                ]
                in traffic_item.Tracking.find().TrackBy
            ):
                self.logger.debug(
                    f"Traffic item tracking is enabled for {traffic_item}"
                )
                traffic_item_tracking_enabled = True
                break
        if not traffic_item_tracking_enabled:
            self.logger.debug(
                f"Traffic item tracking is not enabled for {enabled_traffic_items}"
            )
            return
        try:
            traffic_item_view = StatViewAssistant(
                self.ixnetwork, TRAFFIC_ITEM_VIEW, Timeout=60
            )
            return traffic_item_view
        except Exception as e:
            self.logger.error(f"Error getting traffic item views: {e}")
            raise e

    # ------------------------------------------------------------------
    # Formulaic EBB route helpers. This is deliberately narrower than the DLB
    # mutation path below: it owns sparse prefixes, external next hops, and
    # baseline attributes only.
    # ------------------------------------------------------------------

    def _find_formulaic_bgp_route_shell(
        self,
        device_group_name: str,
        prefix_pool_name: str,
        afi: str,
    ):
        device_groups = [
            device_group
            for topology in self.ixnetwork.Topology.find()
            for device_group in topology.DeviceGroup.find()
            if device_group.Name == device_group_name
        ]
        if len(device_groups) != 1:
            raise RuntimeError(
                f"expected one device group {device_group_name!r}; "
                f"found {len(device_groups)}"
            )
        device_group = device_groups[0]
        pool_attr = "Ipv4PrefixPools" if afi == "v4" else "Ipv6PrefixPools"
        route_attr = "BgpIPRouteProperty" if afi == "v4" else "BgpV6IPRouteProperty"
        matches = []
        for network_group in device_group.NetworkGroup.find():
            for prefix_pool in getattr(network_group, pool_attr).find():
                if prefix_pool.Name == prefix_pool_name:
                    matches.append((network_group, prefix_pool))
        if len(matches) != 1:
            raise RuntimeError(
                f"expected one {afi} prefix pool {prefix_pool_name!r} under "
                f"{device_group_name!r}; found {len(matches)}"
            )
        network_group, prefix_pool = matches[0]
        route_properties = list(getattr(prefix_pool, route_attr).find())
        if len(route_properties) != 1:
            raise RuntimeError(
                f"expected one route property for {prefix_pool_name!r}; "
                f"found {len(route_properties)}"
            )
        return device_group, network_group, prefix_pool, route_properties[0]

    @staticmethod
    def _formulaic_prefix_values(prefix: t.Dict[str, t.Any]) -> t.List[str]:
        start = ipaddress.ip_address(prefix["start"])
        step = prefix["step"]
        count = prefix["count"]
        excluded = set(prefix["excluded_indices"])
        values = []
        for candidate in range(count + len(excluded)):
            if candidate not in excluded:
                values.append(str(type(start)(int(start) + candidate * step)))
        if len(values) != count:
            raise ValueError(
                "formulaic prefix exclusions did not yield the requested count"
            )
        return values

    @staticmethod
    def _required_next_hop_address_count(
        distribution: str,
        prefix_distribution: str,
        peer_count: int,
        prefixes_per_peer: int,
    ) -> int:
        if prefix_distribution not in {"shared", "disjoint"}:
            raise ValueError(f"unsupported prefix distribution {prefix_distribution!r}")
        if distribution == "shared":
            return 1
        if distribution == "per_peer":
            return peer_count
        if distribution == "per_prefix":
            return (
                prefixes_per_peer
                if prefix_distribution == "shared"
                else peer_count * prefixes_per_peer
            )
        if distribution == "per_peer_prefix":
            return peer_count * prefixes_per_peer
        raise ValueError(f"unsupported next-hop distribution {distribution!r}")

    @staticmethod
    def _next_hop_address_index(
        distribution: str,
        prefix_distribution: str,
        peer_index: int,
        prefix_index: int,
        prefixes_per_peer: int,
    ) -> int:
        if distribution == "shared":
            return 0
        if distribution == "per_peer":
            return peer_index
        if distribution == "per_prefix":
            return (
                prefix_index
                if prefix_distribution == "shared"
                else peer_index * prefixes_per_peer + prefix_index
            )
        if distribution == "per_peer_prefix":
            return peer_index * prefixes_per_peer + prefix_index
        raise AssertionError(
            f"validated next-hop distribution changed: {distribution!r}"
        )

    @staticmethod
    def _validate_formulaic_route_attributes(
        key: t.Tuple[str, str, str],
        route_attributes: t.Optional[t.Dict[str, t.Any]],
    ) -> None:
        if route_attributes is None:
            return
        try:
            TaacIxia._formulaic_route_attribute_distribution(
                route_attributes.get("distribution")
            )
        except ValueError as error:
            raise ValueError(
                f"unsupported route attribute distribution for {key!r}: "
                f"{route_attributes.get('distribution')!r}"
            ) from error
        for field_name in ("community_rows", "extended_community_rows"):
            rows = route_attributes.get(field_name, [])
            if any(not row for row in rows):
                raise ValueError(f"empty {field_name} row for {key!r}")
            if rows and len({len(row) for row in rows}) != 1:
                raise ValueError(f"inconsistent {field_name} widths for {key!r}")

    @staticmethod
    def _formulaic_route_attribute_distribution(
        distribution: t.Any,
    ) -> ixia_types.DistribitionType:
        if distribution == "round_robin":
            return ixia_types.DistribitionType.ROUND_ROBIN
        if distribution == "randomize":
            return ixia_types.DistribitionType.RANDOMIZE
        raise ValueError(f"unsupported route attribute distribution {distribution!r}")

    @staticmethod
    def _formulaic_next_hop_values(
        mutation: t.Dict[str, t.Any],
        *,
        flatten_prefix_pool: bool = False,
    ) -> t.List[str]:
        next_hop = mutation["next_hop"]
        peer_count = mutation["peer_count"]
        prefixes_per_peer = mutation["prefixes_per_peer"]
        prefix_distribution = mutation["prefix"]["distribution"]
        distribution = next_hop["distribution"]
        required_address_count = TaacIxia._required_next_hop_address_count(
            distribution,
            prefix_distribution,
            peer_count,
            prefixes_per_peer,
        )
        if next_hop["kind"] == "formulaic":
            first = ipaddress.ip_address(next_hop["start"])
            step = next_hop["step"]

            def address_at(index: int) -> str:
                return str(type(first)(int(first) + index * step))

        elif next_hop["kind"] == "explicit":
            addresses = next_hop["addresses"]
            if len(addresses) != required_address_count:
                raise ValueError(
                    "explicit next-hop cardinality mismatch: expected "
                    f"{required_address_count}, got {len(addresses)}"
                )

            def address_at(index: int) -> str:
                return addresses[index]

        else:
            raise ValueError(f"unsupported next-hop kind {next_hop['kind']!r}")

        if distribution == "per_peer" and not flatten_prefix_pool:
            return [address_at(peer_index) for peer_index in range(peer_count)]

        values = []
        for peer_index in range(peer_count):
            for prefix_index in range(prefixes_per_peer):
                index = TaacIxia._next_hop_address_index(
                    distribution,
                    prefix_distribution,
                    peer_index,
                    prefix_index,
                    prefixes_per_peer,
                )
                values.append(address_at(index))
        return values

    def _prepare_formulaic_bgp_routes(
        self,
        mutations: t.List[t.Dict[str, t.Any]],
    ) -> t.List[t.Tuple[t.Any, t.Any, t.Any, t.Any]]:
        prepared = []
        seen = set()
        for mutation in mutations:
            key = (
                mutation["device_group_name"],
                mutation["prefix_pool_name"],
                mutation["afi"],
            )
            if key in seen:
                raise ValueError(f"duplicate formulaic BGP route target {key!r}")
            seen.add(key)
            shell = self._find_formulaic_bgp_route_shell(*key)
            device_group, network_group, prefix_pool, _route_property = shell
            if device_group.Multiplier != mutation["peer_count"]:
                raise ValueError(
                    f"peer count mismatch for {key!r}: expected "
                    f"{mutation['peer_count']}, got {device_group.Multiplier}"
                )
            prefix = mutation["prefix"]
            # Payloads serialized before this flag was introduced retain compact
            # geometry unless sparse membership already requires flattening.
            flatten_prefix_pool = bool(
                mutation.get("flat_prefix_geometry", False)
                or prefix["excluded_indices"]
            )
            prefixes_per_peer = mutation["prefixes_per_peer"]
            if flatten_prefix_pool:
                compact_geometry = (
                    network_group.Multiplier in (None, 1)
                    and prefix_pool.NumberOfAddresses == prefixes_per_peer
                )
                flat_geometry = (
                    network_group.Multiplier == prefixes_per_peer
                    and prefix_pool.NumberOfAddresses == 1
                )
                if not compact_geometry and not flat_geometry:
                    raise ValueError(
                        f"flat prefix geometry mismatch for {key!r}: expected "
                        f"(network group, pool)=((1, {prefixes_per_peer}) or "
                        f"({prefixes_per_peer}, 1)), got "
                        f"({network_group.Multiplier}, "
                        f"{prefix_pool.NumberOfAddresses})"
                    )
            elif prefix_pool.NumberOfAddresses != prefixes_per_peer:
                raise ValueError(
                    f"prefix count mismatch for {key!r}: expected "
                    f"{prefixes_per_peer}, got {prefix_pool.NumberOfAddresses}"
                )
            prefix_values = None
            if flatten_prefix_pool:
                prefix_values = self._formulaic_prefix_values(prefix)
                expected_prefix_count = (
                    prefixes_per_peer
                    if prefix["distribution"] == "shared"
                    else mutation["peer_count"] * prefixes_per_peer
                )
                if len(prefix_values) != expected_prefix_count:
                    raise ValueError(
                        f"prefix inventory mismatch for {key!r}: expected "
                        f"{expected_prefix_count}, got {len(prefix_values)}"
                    )
                if prefix["distribution"] == "shared":
                    prefix_values *= mutation["peer_count"]
            next_hop_values = (
                self._formulaic_next_hop_values(
                    mutation,
                    flatten_prefix_pool=flatten_prefix_pool,
                )
                if mutation["next_hop"] is not None
                else None
            )
            attributes = mutation["attributes"]
            for attribute in ("med", "local_pref", "origin"):
                if attribute not in attributes:
                    raise ValueError(
                        f"missing route attribute {attribute!r} for {key!r}"
                    )
            self._validate_formulaic_route_attributes(
                key,
                mutation.get("route_attributes"),
            )
            prepared.append((mutation, shell, prefix_values, next_hop_values))
        return prepared

    def _apply_formulaic_bgp_route(
        self,
        mutation: t.Dict[str, t.Any],
        shell: t.Tuple[t.Any, t.Any, t.Any, t.Any],
        prefix_values: t.Optional[t.List[str]],
        next_hop_values: t.Optional[t.List[str]],
    ) -> None:
        device_group, network_group, pool, route = shell
        if prefix_values is not None:
            for attempt in range(4):
                try:
                    network_group.Multiplier = mutation["prefixes_per_peer"]
                    break
                except Exception as error:
                    if (
                        "Changing the Multiplier in a started" not in str(error)
                        or attempt == 3
                    ):
                        raise
                    device_group.Stop()
                    network_group.Stop()
                    time.sleep(3)
            pool.NumberOfAddresses = 1
            pool.NetworkAddress.ValueList(prefix_values)
        if next_hop_values is not None:
            route.NextHopType.Single(
                ixia_types.SET_NEXT_HOP_TYPE_MAP[ixia_types.SetNextHopType.MANUALLY]
            )
            route.NextHopIPType.Single("ipv4" if mutation["afi"] == "v4" else "ipv6")
            next_hop_field = (
                route.Ipv4NextHop if mutation["afi"] == "v4" else route.Ipv6NextHop
            )
            next_hop_field.ValueList(next_hop_values)
        attributes = mutation["attributes"]
        if hasattr(route, "EnableLocalPreference"):
            route.EnableLocalPreference.Single(True)
        if hasattr(route, "LocalPreference"):
            route.LocalPreference.Single(attributes["local_pref"])
        if hasattr(route, "Origin"):
            route.Origin.Single(attributes["origin"])
        if hasattr(route, "EnableMultiExitDiscriminator"):
            route.EnableMultiExitDiscriminator.Single(attributes["med"] is not None)
        if attributes["med"] is not None and hasattr(route, "MultiExitDiscriminator"):
            route.MultiExitDiscriminator.Single(attributes["med"])
        route_attributes = mutation.get("route_attributes")
        if route_attributes is not None:
            distribution_type = self._formulaic_route_attribute_distribution(
                route_attributes.get("distribution")
            )
            configs = []
            for field_name, attribute in (
                ("community_rows", ixia_types.BgpAttribute.COMMUNITIES),
                ("extended_community_rows", ixia_types.BgpAttribute.EXT_COMMUNITIES),
            ):
                rows = route_attributes.get(field_name, [])
                if rows:
                    configs.append(
                        ixia_types.BgpAttributeConfig(
                            attribute=attribute,
                            value_lists=rows,
                            distribution_type=distribution_type,
                        )
                    )
            if configs:
                self.configure_bgp_attributes(route, configs)

    def _restart_formulaic_bgp_routes(
        self,
        stopped: t.List[t.Tuple[str, t.Any]],
        *,
        best_effort: bool,
    ) -> None:
        while stopped:
            component_name, component = stopped[-1]
            try:
                component.Start()
            except Exception:
                if not best_effort:
                    raise
                self.logger.exception(
                    "failed to restore formulaic BGP route %s", component_name
                )
            stopped.pop()

    def configure_formulaic_bgp_routes(
        self,
        mutations: t.List[t.Dict[str, t.Any]],
    ) -> None:
        """Apply formulaic route intent using each mutation's requested geometry."""
        prepared = self._prepare_formulaic_bgp_routes(mutations)
        if not prepared:
            return

        stopped = []
        try:
            for (
                _mutation,
                (device_group, network_group, _pool, _route),
                _prefix_values,
                _next_hop_values,
            ) in prepared:
                device_group.Stop()
                stopped.append(("device group", device_group))
                network_group.Stop()
                stopped.append(("network group", network_group))

            for mutation, shell, prefix_values, next_hop_values in prepared:
                self._apply_formulaic_bgp_route(
                    mutation,
                    shell,
                    prefix_values,
                    next_hop_values,
                )

            self.apply_changes()
            self._restart_formulaic_bgp_routes(stopped, best_effort=False)
        except Exception:
            self._restart_formulaic_bgp_routes(stopped, best_effort=True)
            raise

    # DLB hardening helpers used by its existing CSV injection workflows.
    def _find_dlb_ng_dg(self, pool_name: str):
        """Locate the named NetworkGroup, its parent DeviceGroup, its
        single Ipv6PrefixPool, and its BgpV6IPRouteProperty in the
        IxNetwork session.

        Returns (parent_dg, parent_ng, parent_pool, route_prop) or
        raises RuntimeError if no matching NG is found.
        """
        for topo in self.ixnetwork.Topology.find():
            for dg in topo.DeviceGroup.find():
                for ng in dg.NetworkGroup.find():
                    if ng.Name != pool_name:
                        continue
                    pool = next(iter(ng.Ipv6PrefixPools.find()), None)
                    if pool is None:
                        raise RuntimeError(f"NG {pool_name!r} has no Ipv6PrefixPools")
                    rp = next(iter(pool.BgpV6IPRouteProperty.find()), None)
                    if rp is None:
                        raise RuntimeError(
                            f"pool in NG {pool_name!r} has no BgpV6IPRouteProperty"
                        )
                    return dg, ng, pool, rp
        raise RuntimeError(f"No NetworkGroup named {pool_name!r} found")

    def _mutate_pool_config_only(
        self, csv_path: str, pool_name: str
    ) -> t.Tuple[t.Any, t.Any, int, int, int]:
        """Pure IxNetwork config mutation — NO protocol restart, NO traffic touch.

        Applies CSV -> (NG.Multiplier, NetworkAddress ValueList, Ipv6NextHop
        ValueList, AddPath enable, MvNextHopCount, AddPathId ValueList,
        route_prop.Active=True) after dg.Stop()+ng.Stop(). Callers MUST later
        run ng.Start()+dg.Start() and typically StartAllProtocols(sync) via
        ``apply_pool_mutations``.

        Returns (dg, ng, total_rows, distinct_prefixes, width).
        """
        import csv as _csv
        import os as _os
        import time as _time

        prefixes_in_order: t.List[str] = []
        nhs_in_order: t.List[str] = []
        with open(csv_path) as f:
            reader = _csv.reader(f)
            next(reader, None)
            for row in reader:
                if len(row) < 2:
                    continue
                prefixes_in_order.append(row[0])
                nhs_in_order.append(row[1])
        total_rows = len(prefixes_in_order)
        if total_rows == 0:
            raise ValueError(f"CSV {csv_path} has no data rows")
        distinct_prefixes = len(dict.fromkeys(prefixes_in_order))
        w = total_rows // distinct_prefixes if distinct_prefixes else 0
        self.logger.info(
            f"[_mutate_pool_config_only] {csv_path}: rows={total_rows} "
            f"distinct_prefixes={distinct_prefixes} width={w}"
        )

        scratch_dir = "/tmp/taac_dlb_inject"
        _os.makedirs(scratch_dir, exist_ok=True)
        prefix_col = _os.path.join(scratch_dir, f"_pfx_{pool_name}.csv")
        nh_col = _os.path.join(scratch_dir, f"_nh_{pool_name}.csv")
        with open(prefix_col, "w") as f:
            f.write("\n".join(prefixes_in_order) + "\n")
        with open(nh_col, "w") as f:
            f.write("\n".join(nhs_in_order) + "\n")

        dg, ng, pool, route_prop = self._find_dlb_ng_dg(pool_name)
        self.logger.info(f"[_mutate_pool_config_only] target dg={dg.Name} ng={ng.Name}")

        MAX_STOP_RETRY = 4
        for attempt in range(MAX_STOP_RETRY):
            try:
                dg.Stop()
            except Exception as e:
                self.logger.warning(
                    f"dg.Stop() attempt {attempt + 1} failed (continuing): {e}"
                )
            try:
                ng.Stop()
            except Exception as e:
                self.logger.warning(
                    f"ng.Stop() attempt {attempt + 1} failed (continuing): {e}"
                )
            try:
                ng.Multiplier = total_rows
                break
            except Exception as e:
                msg = str(e)
                if (
                    "Changing the Multiplier in a started" in msg
                    and attempt + 1 < MAX_STOP_RETRY
                ):
                    self.logger.warning(
                        f"NG.Multiplier write rejected (NG still started); "
                        f"retry {attempt + 1}/{MAX_STOP_RETRY} after 3s"
                    )
                    _time.sleep(3)
                    continue
                raise
        pool.NumberOfAddresses = 1
        pool.PrefixLength.Single(64)
        pool.NetworkAddress.ValueList(prefix_col)
        route_prop.Ipv6NextHop.ValueList(nh_col)
        route_prop.EnableAddPath.Single(True)
        route_prop.MvNextHopCount.Single(w)
        route_prop.AddPathId.ValueList([str(i + 1) for i in range(total_rows)])
        try:
            route_prop.Active.Single(True)
        except Exception as e:
            self.logger.warning(f"route_prop.Active.Single(True) failed: {e}")
        for attr_name in ("EnableFlap", "EnableFlapping", "RouteFlap"):
            attr = getattr(route_prop, attr_name, None)
            if attr is None:
                continue
            try:
                attr.Single(False)
                break
            except Exception:
                pass
        return dg, ng, total_rows, distinct_prefixes, w

    def apply_pool_mutations(self, pool_csvs: t.List[t.Tuple[str, str]]) -> None:
        """Batch mutation: apply N pool CSV changes with ONE traffic
        stop/regen/apply cycle at the end.

        ``pool_csvs`` is a list of ``(csv_path, pool_name)`` tuples. For each
        entry we do the pure-config mutation via ``_mutate_pool_config_only``
        (dg.Stop / ng.Stop / write config), then at the end we do ONE:
        Traffic.Stop -> per-pool ng.Start + dg.Start -> StartAllProtocols(sync)
        -> convergence settle scaled by total rows -> Traffic.Regenerate +
        Traffic.Apply (with retry backoff).

        This replaces the per-pool ``mutate_dlb_pool_from_csv`` pattern that
        did the entire cycle N times and caused Traffic Item corruption
        (Run 20 CASE_05: double-StartAllProtocols left traffic in kUnapplied
        state permanently; Run 20b: setup-time Traffic-Started state broke
        Regenerate). One clean cycle avoids both classes.
        """
        import time as _time

        if not pool_csvs:
            self.logger.warning("apply_pool_mutations called with empty list")
            return

        try:
            self.ixnetwork.Traffic.Stop()
            _time.sleep(2)
        except Exception as e:
            self.logger.warning(f"Traffic.Stop() at batch start failed: {e}")

        mutated: t.List[t.Tuple[t.Any, t.Any, int, str]] = []
        total_rows_sum = 0
        for csv_path, pool_name in pool_csvs:
            dg, ng, total_rows, _, _ = self._mutate_pool_config_only(
                csv_path, pool_name
            )
            mutated.append((dg, ng, total_rows, pool_name))
            total_rows_sum += total_rows

        for dg, ng, _, pool_name in mutated:
            try:
                ng.Start()
            except Exception as e:
                self.logger.warning(f"ng.Start() {pool_name} failed (continuing): {e}")
            try:
                dg.Start()
            except Exception as e:
                self.logger.warning(f"dg.Start() {pool_name} failed (continuing): {e}")

        try:
            self.ixnetwork.StartAllProtocols(Arg1="sync")
        except Exception as e:
            self.logger.warning(f"StartAllProtocols failed (continuing): {e}")

        settle_s = max(30, total_rows_sum // 250)
        self.logger.info(
            f"[apply_pool_mutations] settling {settle_s}s "
            f"(~{total_rows_sum} total advertised rows across {len(mutated)} pool(s))"
        )
        _time.sleep(settle_s)

        try:
            for ti in self.ixnetwork.Traffic.TrafficItem.find():
                try:
                    ti.Generate()
                except Exception as e:
                    self.logger.warning(
                        f"TrafficItem.Generate() failed (continuing): {e}"
                    )
            for attempt in range(5):
                try:
                    self.ixnetwork.Traffic.Apply()
                    self.logger.info(
                        f"[apply_pool_mutations] Traffic.Apply() OK on "
                        f"attempt {attempt + 1}"
                    )
                    break
                except Exception as e:
                    if attempt == 4:
                        self.logger.warning(
                            f"Traffic.Apply() failed after 5 retries "
                            f"(continuing anyway; start_traffic will retry): {e}"
                        )
                    else:
                        _time.sleep(15)
        except Exception as e:
            self.logger.warning(f"Traffic re-apply block failed (continuing): {e}")

        for _, ng, _, pool_name in mutated:
            self.logger.info(
                f"[apply_pool_mutations] {pool_name} committed: "
                f"NG.Multiplier={ng.Multiplier}"
            )

    def mutate_dlb_pool_from_csv(
        self, csv_path: str, pool_name: str = "DLB_GOLD_PREFIX_POOL"
    ) -> None:
        """Single-pool convenience wrapper around ``apply_pool_mutations``.

        Kept for backward compatibility with standalone injection scripts
        (``ixia_csv_inject.py``, ``ixia_nh_inject.py``). Testconfigs mutating
        multiple pools should call ``apply_pool_mutations`` directly to avoid
        the double-cycle traffic-item corruption class.
        """
        self.apply_pool_mutations([(csv_path, pool_name)])

    def stop_all_protocols(self) -> None:
        """Stop all emulated protocols on the IXIA chassis.

        Used by ``case_23_cold_start_cycle`` to disconnect IXIA-side BGP
        sessions cleanly (mirrors the ``StartAllProtocols`` call already
        made at the end of ``mutate_dlb_pool_from_csv``). DUT will see all
        peers go IDLE and withdraw routes; a later ``start_all_protocols``
        re-establishes everything.
        """
        try:
            self.ixnetwork.StopAllProtocols(Arg1="sync")
            self.logger.info("[stop_all_protocols] StopAllProtocols OK")
        except Exception as e:
            self.logger.warning(f"StopAllProtocols failed (continuing): {e}")

    def start_all_protocols(self) -> None:
        """Start all emulated protocols on the IXIA chassis.

        Pair to ``stop_all_protocols`` for the cold-start cycle.
        Idempotent for protocols already started; used standalone after
        a ``stop_all_protocols`` to re-establish BGP sessions.
        """
        try:
            self.ixnetwork.StartAllProtocols(Arg1="sync")
            self.logger.info("[start_all_protocols] StartAllProtocols OK")
        except Exception as e:
            self.logger.warning(f"StartAllProtocols failed (continuing): {e}")

    def toggle_dlb_pool_enabled(self, pool_name: str, enabled: bool) -> None:
        """Toggle the parent DeviceGroup's start/stop state for the
        named NetworkGroup. Used by case_15 (rollback) and case_19
        (continuous switching) to enable/disable Silver advertisement
        without touching the Gold session.

        Empirical caveat (to be verified at first use): dg.Stop tears
        down the per-DG BGP session. Gold session is on a SEPARATE DG
        so toggling Silver should NOT affect Gold. Confirm with a
        BGP-summary probe in the playbook postcheck.
        """
        dg, ng, _pool, _rp = self._find_dlb_ng_dg(pool_name)
        if enabled:
            try:
                ng.Start()
            except Exception as e:
                self.logger.warning(f"ng.Start() failed: {e}")
            try:
                dg.Start()
            except Exception as e:
                self.logger.warning(f"dg.Start() failed: {e}")
        else:
            try:
                dg.Stop()
            except Exception as e:
                self.logger.warning(f"dg.Stop() failed: {e}")
            try:
                ng.Stop()
            except Exception as e:
                self.logger.warning(f"ng.Stop() failed: {e}")
        self.logger.info(f"[toggle_dlb_pool_enabled] {pool_name} → enabled={enabled}")

    def configure_traffic_item(
        self,
        traffic_item_name: str,
        line_rate: t.Optional[int] = None,
        line_rate_type: t.Optional[ixia_types.RateType] = None,
        frame_size_setting: t.Optional[ixia_types.FrameSize] = None,
        qos_config: t.Optional[ixia_types.QoSConfig] = None,
    ) -> None:
        self.configure_traffic_items_on_the_fly(
            traffic_item_name,
            line_rate,
            line_rate_type,
            frame_size_setting,
            qos_config,
        )
        self.apply_traffic()

    def prepare_traffic(self) -> None:
        self.regenerate_traffic_items()
        self.apply_traffic()
        self.wait_for_view_assistants_ready()

    def begin_test_case(self, test_case_uuid, traffic_regexes=None) -> None:
        self.test_case_uuid = test_case_uuid
        self.enable_traffic(traffic_regexes)
        self.prepare_traffic()
        if not self.capturing:
            self.start()
        else:
            self.paused = False

    def end_test_case(self, traffic_regexes=None) -> None:
        self.paused = True
        self.log_to_scuba_ixia_packet_loss(none_throws(self.test_case_uuid))
        self.enable_traffic(traffic_regexes, enable=False)
