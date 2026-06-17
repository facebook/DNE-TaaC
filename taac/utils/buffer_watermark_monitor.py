# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""
Real-time buffer watermark and congestion drop monitor for Kodiak3 (Chenab ASIC)
FBOSS switches.

Polls fb303 counters at a configurable interval and produces live-updating
matplotlib graphs grouped by:
  1. Device-level watermark (buffer_watermark_device)
  2. Global pool watermarks (global_shared, global_headroom)
  3. CPU buffer watermarks — per-queue peak usage (buffer_watermark_cpu)
  4. Per-port per-queue unicast watermarks (buffer_watermark_ucast)
  5. Per-port per-PG headroom/shared watermarks (buffer_watermark_pg_*)
  6. Per-port per-queue congestion drops (out_congestion_discards) — packets
     dropped due to buffer overflow (tail drops), shown per queue and per port
  7. Fabric/core watermarks (core_rci, dtl_queue, egress_core, etc.)

Congestion drops are the primary signal for tail-drop events and appear as
packets/60s (the sum over the last 60 seconds). These are complementary to the
buffer watermark graphs: watermarks show how full buffers are, while congestion
drops show when traffic is actually being discarded.

Usage:
    # Basic monitoring — shows all graphs including congestion drops:
    buck2 run fbcode//neteng/test_infra/dne/taac/utils:buffer_watermark_monitor -- \\
        --device rb001-01.qxt1 --interval 2

    # Monitor specific ports only (reduces noise for targeted debugging):
    buck2 run fbcode//neteng/test_infra/dne/taac/utils:buffer_watermark_monitor -- \\
        --device rb001-01.qxt1 --interval 1 --ports eth1/63/1 eth1/63/5

    # Save graph snapshots to a directory (PNG images updated every 5 samples):
    buck2 run fbcode//neteng/test_infra/dne/taac/utils:buffer_watermark_monitor -- \\
        --device rb001-01.qxt1 --interval 2 --output-dir /tmp/buffer_graphs

    # Export raw CSV data (includes watermarks + congestion drop columns):
    buck2 run fbcode//neteng/test_infra/dne/taac/utils:buffer_watermark_monitor -- \\
        --device rb001-01.qxt1 --interval 2 --csv /tmp/buffer_data.csv

    # Discover all available buffer/congestion counters on a device:
    buck2 run fbcode//neteng/test_infra/dne/taac/utils:buffer_watermark_monitor -- \\
        --device rb001-01.qxt1 --discover
"""

import argparse
import asyncio
import csv
import logging
import os
import re
import time
import typing as t
from collections import defaultdict
from datetime import datetime

import matplotlib

matplotlib.use("Agg")  # Non-interactive backend; switched to TkAgg if --live
import matplotlib.pyplot as plt
from fb303.clients import FacebookService
from libfb.py.asyncio.thrift import ClientType, get_direct_client
from matplotlib.animation import FuncAnimation  # noqa: F401


logger = logging.getLogger(__name__)

# Kodiak3 MMU size in bytes (150 MB)
KODIAK3_MMU_BYTES: int = 150 * 1024 * 1024

# Counter patterns we care about
BUFFER_COUNTER_PATTERNS: t.List[str] = [
    "buffer_watermark_device.",
    "buffer_watermark_global_shared.",
    "buffer_watermark_global_headroom.",
    "buffer_watermark_ucast.",
    "buffer_watermark_pg_headroom.",
    "buffer_watermark_pg_shared.",
]

# Regex to parse counter names (we only keep .p100.60 counters)
RE_DEVICE_WM = re.compile(r"^buffer_watermark_device\.p100\.60$")
RE_GLOBAL_SHARED = re.compile(r"^buffer_watermark_global_shared\.p100\.60$")
RE_GLOBAL_HEADROOM = re.compile(r"^buffer_watermark_global_headroom\.p100\.60$")
RE_UCAST = re.compile(r"^buffer_watermark_ucast\.(.+?)\.queue(\d+)\.(.+?)\.p100\.60$")
RE_PG_HEADROOM = re.compile(r"^buffer_watermark_pg_headroom\.(.+?)\.pg(\d+)\.p100\.60$")
RE_PG_SHARED = re.compile(r"^buffer_watermark_pg_shared\.(.+?)\.pg(\d+)\.p100\.60$")
RE_CPU_QUEUE = re.compile(r"^buffer_watermark_cpu\.queue(\d+)\.p100\.60$")
# Fabric/core counters (single-value, no per-port breakdown)
RE_SIMPLE_WM = re.compile(
    r"^buffer_watermark_(core_rci|dtl_queue|egress_core|fdr_fifo|fdr_rci)\.p100\.60$"
)
# Congestion drop counters (per-queue and per-port)
RE_CONGESTION_QUEUE = re.compile(
    r"^(.+?)\.queue(\d+)\.(.+?)\.out_congestion_discards\.sum\.60$"
)
RE_CONGESTION_PORT = re.compile(r"^(.+?)\.out_congestion_discards\.sum\.60$")


class BufferWatermarkData:
    """Stores time-series data for all buffer watermark counters."""

    def __init__(self, max_samples: int = 600) -> None:
        self.max_samples = max_samples
        self.timestamps: t.List[float] = []

        # Device-level: list of values
        self.device_wm: t.List[int] = []

        # Global pool: list of values
        self.global_shared: t.List[int] = []
        self.global_headroom: t.List[int] = []

        # Per-port per-queue: {port -> {queue_label -> [values]}}
        self.ucast_wm: t.Dict[str, t.Dict[str, t.List[int]]] = (  # pyre-ignore[8]
            defaultdict(lambda: defaultdict(list))
        )

        # Per-port per-PG: {port -> {pg_label -> [values]}}
        self.pg_headroom: t.Dict[str, t.Dict[str, t.List[int]]] = (  # pyre-ignore[8]
            defaultdict(lambda: defaultdict(list))
        )
        self.pg_shared: t.Dict[str, t.Dict[str, t.List[int]]] = (  # pyre-ignore[8]
            defaultdict(lambda: defaultdict(list))
        )

        # CPU queue watermarks: {queue_label -> [values]}
        self.cpu_queues: t.Dict[str, t.List[int]] = defaultdict(list)

        # Fabric/core watermarks: {counter_name -> [values]}
        self.fabric_wm: t.Dict[str, t.List[int]] = defaultdict(list)

        # Per-port per-queue congestion drops: {port -> {queue_label -> [values]}}
        self.congestion_drops: t.Dict[  # pyre-ignore[8]
            str, t.Dict[str, t.List[int]]
        ] = defaultdict(lambda: defaultdict(list))
        # Per-port total congestion drops: {port -> [values]}
        self.congestion_drops_port: t.Dict[str, t.List[int]] = defaultdict(list)

    def _trim(self, lst: t.List) -> None:
        """Keep only the last max_samples entries."""
        if len(lst) > self.max_samples:
            del lst[: len(lst) - self.max_samples]

    def add_sample(  # noqa: C901
        self,
        ts: float,
        counters: t.Dict[str, int],
        port_filter: t.Optional[t.Set[str]] = None,
        no_pg: bool = False,
    ) -> None:
        """Parse and store a set of counter values at timestamp ts."""
        self.timestamps.append(ts)
        self._trim(self.timestamps)

        device_val = 0
        global_shared_val = 0
        global_headroom_val = 0

        # Track which port/queue/pg combos we've seen this sample
        seen_ucast: t.Set[t.Tuple[str, str]] = set()
        seen_pg_hr: t.Set[t.Tuple[str, str]] = set()
        seen_pg_sh: t.Set[t.Tuple[str, str]] = set()
        seen_cpu: t.Set[str] = set()
        seen_fabric: t.Set[str] = set()
        seen_cong_q: t.Set[t.Tuple[str, str]] = set()
        seen_cong_p: t.Set[str] = set()

        for name, value in counters.items():
            m = RE_DEVICE_WM.match(name)
            if m:
                device_val = value
                continue

            m = RE_GLOBAL_SHARED.match(name)
            if m:
                global_shared_val = value
                continue

            m = RE_GLOBAL_HEADROOM.match(name)
            if m:
                global_headroom_val = value
                continue

            m = RE_UCAST.match(name)
            if m:
                port, queue_id, queue_name = m.group(1), m.group(2), m.group(3)
                if port_filter and port not in port_filter:
                    continue
                label = f"q{queue_id}.{queue_name}"
                self.ucast_wm[port][label].append(value)
                self._trim(self.ucast_wm[port][label])
                seen_ucast.add((port, label))
                continue

            if not no_pg:
                m = RE_PG_HEADROOM.match(name)
                if m:
                    port, pg_id = m.group(1), m.group(2)
                    if port_filter and port not in port_filter:
                        continue
                    label = f"pg{pg_id}"
                    self.pg_headroom[port][label].append(value)
                    self._trim(self.pg_headroom[port][label])
                    seen_pg_hr.add((port, label))
                    continue

                m = RE_PG_SHARED.match(name)
                if m:
                    port, pg_id = m.group(1), m.group(2)
                    if port_filter and port not in port_filter:
                        continue
                    label = f"pg{pg_id}"
                    self.pg_shared[port][label].append(value)
                    self._trim(self.pg_shared[port][label])
                    seen_pg_sh.add((port, label))
                    continue

            m = RE_CPU_QUEUE.match(name)
            if m:
                label = f"cpu_q{m.group(1)}"
                self.cpu_queues[label].append(value)
                self._trim(self.cpu_queues[label])
                seen_cpu.add(label)
                continue

            m = RE_SIMPLE_WM.match(name)
            if m:
                label = m.group(1)
                self.fabric_wm[label].append(value)
                self._trim(self.fabric_wm[label])
                seen_fabric.add(label)
                continue

            # Per-queue congestion drops (check before per-port to avoid
            # the per-port regex swallowing queue-level counters)
            m = RE_CONGESTION_QUEUE.match(name)
            if m:
                port, queue_id, queue_name = m.group(1), m.group(2), m.group(3)
                if port_filter and port not in port_filter:
                    continue
                label = f"q{queue_id}.{queue_name}"
                self.congestion_drops[port][label].append(value)
                self._trim(self.congestion_drops[port][label])
                seen_cong_q.add((port, label))
                continue

            # Per-port total congestion drops
            m = RE_CONGESTION_PORT.match(name)
            if m:
                port = m.group(1)
                if port_filter and port not in port_filter:
                    continue
                self.congestion_drops_port[port].append(value)
                self._trim(self.congestion_drops_port[port])
                seen_cong_p.add(port)
                continue

        self.device_wm.append(device_val)
        self._trim(self.device_wm)
        self.global_shared.append(global_shared_val)
        self._trim(self.global_shared)
        self.global_headroom.append(global_headroom_val)
        self._trim(self.global_headroom)

        # For any previously seen port/queue/pg combos not in this sample, append 0
        for port, queues in self.ucast_wm.items():
            for label, vals in queues.items():
                if (port, label) not in seen_ucast and len(vals) < len(self.timestamps):
                    vals.append(0)
                    self._trim(vals)
        for port, pgs in self.pg_headroom.items():
            for label, vals in pgs.items():
                if (port, label) not in seen_pg_hr and len(vals) < len(self.timestamps):
                    vals.append(0)
                    self._trim(vals)
        for port, pgs in self.pg_shared.items():
            for label, vals in pgs.items():
                if (port, label) not in seen_pg_sh and len(vals) < len(self.timestamps):
                    vals.append(0)
                    self._trim(vals)
        for label, vals in self.cpu_queues.items():
            if label not in seen_cpu and len(vals) < len(self.timestamps):
                vals.append(0)
                self._trim(vals)
        for label, vals in self.fabric_wm.items():
            if label not in seen_fabric and len(vals) < len(self.timestamps):
                vals.append(0)
                self._trim(vals)
        for port, queues in self.congestion_drops.items():
            for label, vals in queues.items():
                if (port, label) not in seen_cong_q and len(vals) < len(
                    self.timestamps
                ):
                    vals.append(0)
                    self._trim(vals)
        for port, vals in self.congestion_drops_port.items():
            if port not in seen_cong_p and len(vals) < len(self.timestamps):
                vals.append(0)
                self._trim(vals)


FBOSS_FB303_PORT: int = 5909
FBOSS_MNPU_FB303_PORT: int = 5931

# Cache the working port after first successful connection
_resolved_port: t.Optional[int] = None


async def fetch_buffer_counters(  # noqa: C901
    hostname: str, port: int = 0, discover: bool = False
) -> t.Dict[str, int]:
    """Fetch all buffer_watermark counters from a device via fb303.

    If port is 0, tries MNPU port (5931) first, then falls back to 5909.
    If discover is True, fetches ALL counters and filters for buffer_watermark
    (useful for finding available counter names on a new platform).
    """
    global _resolved_port
    if port != 0:
        ports_to_try = [port]
    elif _resolved_port is not None:
        ports_to_try = [_resolved_port]
    else:
        ports_to_try = [FBOSS_MNPU_FB303_PORT, FBOSS_FB303_PORT]

    for p in ports_to_try:
        try:
            if _resolved_port is None:
                print(f"  \033[2mTrying fb303 port {p}...\033[0m", flush=True)
            async with get_direct_client(
                FacebookService,
                host=hostname,
                port=p,
                client_type=ClientType.THRIFT_ROCKET_CLIENT_TYPE,
            ) as client:
                if discover:
                    all_counters = await client.getCounters()
                    print(
                        f"  \033[2mgetCounters() returned {len(all_counters)} total counters\033[0m",
                        flush=True,
                    )
                    result = {
                        k: v for k, v in all_counters.items() if "buffer_watermark" in k
                    }
                else:
                    # Use getCounters() and filter — getRegexCounters may not
                    # support prefix matching on all fb303 implementations
                    all_counters = await client.getCounters()
                    result = {
                        k: v
                        for k, v in all_counters.items()
                        if (k.startswith("buffer_watermark") and ".p100.60" in k)
                        or k.endswith("out_congestion_discards.sum.60")
                    }
                    if not result:
                        # Fallback: any buffer_watermark or congestion counter
                        result = {
                            k: v
                            for k, v in all_counters.items()
                            if k.startswith("buffer_watermark")
                            or "out_congestion_discards" in k
                        }
            if _resolved_port is None:
                print(
                    f"  \033[2mPort {p}: found {len(result)} buffer_watermark counters\033[0m",
                    flush=True,
                )
            if result or p == ports_to_try[-1]:
                if result and _resolved_port is None:
                    _resolved_port = p
                return result
        except Exception as e:
            print(
                f"  \033[33mPort {p} failed: {e}\033[0m",
                flush=True,
            )
            if p == ports_to_try[-1]:
                raise
    return {}


def _bytes_to_mb(val: int) -> float:
    return val / (1024 * 1024)


def _relative_times(timestamps: t.List[float]) -> t.List[float]:
    """Convert absolute timestamps to seconds relative to the first sample."""
    if not timestamps:
        return []
    t0 = timestamps[0]
    return [t - t0 for t in timestamps]


def build_plots(  # noqa: C901
    data: BufferWatermarkData,
    device_name: str,
) -> plt.Figure:
    """Build a multi-panel figure from the collected data.

    Layout (2 columns):
      Row 0:   Device watermark (col 0) | Global pool watermarks (col 1)
      Row 1:   CPU buffer watermarks (col 0) | Fabric/core watermarks (col 1)
      Per-port watermark rows:
               Queue watermarks (col 0) | PG watermarks (col 1)
      Per-port congestion drop rows (if data present):
               Per-queue congestion drops (col 0) | Port-total drops (col 1)
    """
    ports_with_ucast = sorted(data.ucast_wm.keys())
    ports_with_pg = sorted(
        set(list(data.pg_headroom.keys()) + list(data.pg_shared.keys()))
    )
    ports_with_congestion = sorted(
        set(
            list(data.congestion_drops.keys()) + list(data.congestion_drops_port.keys())
        )
    )
    all_wm_ports = sorted(set(ports_with_ucast + ports_with_pg))
    has_congestion = bool(data.congestion_drops) or bool(data.congestion_drops_port)

    # Layout: row 0 (device+global) + row 1 (CPU+fabric, always shown)
    #        + 1 row per watermark port + 1 row per congestion port
    n_wm_port_rows = len(all_wm_ports)
    n_cong_port_rows = len(ports_with_congestion) if has_congestion else 0
    n_rows = 2 + n_wm_port_rows + n_cong_port_rows
    if n_rows < 2:
        n_rows = 2  # at least 2 rows to avoid layout issues

    fig, axes = plt.subplots(
        n_rows,
        2,
        figsize=(18, 4 * n_rows),
        squeeze=False,
    )
    fig.suptitle(
        f"Buffer Watermark Monitor — {device_name}\n"
        f"Last updated: {datetime.now().strftime('%H:%M:%S')}",
        fontsize=14,
        fontweight="bold",
    )

    rel_times = _relative_times(data.timestamps)

    # ── Row 0, Col 0: Device watermark ──
    ax = axes[0][0]
    if data.device_wm:
        mb_vals = [_bytes_to_mb(v) for v in data.device_wm]
        ax.plot(rel_times[: len(data.device_wm)], mb_vals, "b-", linewidth=1.5)
        mmu_mb = _bytes_to_mb(KODIAK3_MMU_BYTES)
        peak_mb = max(mb_vals) if mb_vals else 0
        # Only show MMU reference line if data is within visible range
        if peak_mb > mmu_mb * 0.3:
            ax.axhline(
                y=mmu_mb,
                color="r",
                linestyle="--",
                alpha=0.5,
                label=f"MMU={mmu_mb:.0f}MB",
            )
        if ax.get_legend_handles_labels()[1]:
            ax.legend(fontsize=8)
        if peak_mb > 0:
            ax.set_ylim(bottom=0, top=max(peak_mb * 1.1, 1))
    ax.set_title("Device Watermark (peak buffer utilization)", fontsize=10)
    ax.set_ylabel("MB")
    ax.set_xlabel("Time (s)")
    ax.grid(True, alpha=0.3)

    # ── Row 0, Col 1: Global shared + headroom ──
    ax = axes[0][1]
    if data.global_shared:
        ax.plot(
            rel_times[: len(data.global_shared)],
            [_bytes_to_mb(v) for v in data.global_shared],
            "g-",
            linewidth=1.5,
            label="global_shared",
        )
    if data.global_headroom:
        ax.plot(
            rel_times[: len(data.global_headroom)],
            [_bytes_to_mb(v) for v in data.global_headroom],
            "m-",
            linewidth=1.5,
            label="global_headroom",
        )
    ax.set_title("Global Pool Watermarks", fontsize=10)
    ax.set_ylabel("MB")
    ax.set_xlabel("Time (s)")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)

    # ── Row 1, Col 0: CPU buffer watermarks (always shown) ──
    ax = axes[1][0]
    for label in sorted(data.cpu_queues.keys()):
        vals = data.cpu_queues[label]
        ax.plot(
            rel_times[: len(vals)],
            [_bytes_to_mb(v) for v in vals],
            linewidth=1,
            label=label,
        )
    ax.set_title("CPU Buffer Watermarks (per-queue peak usage)", fontsize=10)
    ax.set_ylabel("MB")
    ax.set_xlabel("Time (s)")
    ax.legend(fontsize=8, ncol=4)
    ax.grid(True, alpha=0.3)

    # ── Row 1, Col 1: Fabric/core watermarks ──
    ax = axes[1][1]
    for label in sorted(data.fabric_wm.keys()):
        vals = data.fabric_wm[label]
        ax.plot(
            rel_times[: len(vals)],
            [_bytes_to_mb(v) for v in vals],
            linewidth=1,
            label=label,
        )
    ax.set_title("Fabric/Core Watermarks", fontsize=10)
    ax.set_ylabel("MB")
    ax.set_xlabel("Time (s)")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)

    # ── Per-port watermark rows (queue + PG) ──
    port_row_offset = 2
    for i, port in enumerate(all_wm_ports):
        row = i + port_row_offset

        # Col 0: Unicast queue watermarks
        ax = axes[row][0]
        if port in data.ucast_wm:
            for label in sorted(data.ucast_wm[port].keys()):
                vals = data.ucast_wm[port][label]
                mb_vals = [_bytes_to_mb(v) for v in vals]
                n = min(len(rel_times), len(mb_vals))
                ax.plot(
                    rel_times[:n],
                    mb_vals[:n],
                    linewidth=1,
                    label=label,
                )
        ax.set_title(f"{port} — Queue Watermarks (peak buffer per queue)", fontsize=9)
        ax.set_ylabel("MB")
        ax.set_xlabel("Time (s)")
        ax.relim()
        ax.autoscale_view()
        ax.set_ylim(bottom=0)
        ax.legend(fontsize=7, ncol=4, loc="upper left")
        ax.grid(True, alpha=0.3)

        # Col 1: PG headroom + shared
        ax = axes[row][1]
        if port in data.pg_headroom:
            for label in sorted(data.pg_headroom[port].keys()):
                vals = data.pg_headroom[port][label]
                ax.plot(
                    rel_times[: len(vals)],
                    [_bytes_to_mb(v) for v in vals],
                    linewidth=1,
                    linestyle="-",
                    label=f"{label}_hr",
                )
        if port in data.pg_shared:
            for label in sorted(data.pg_shared[port].keys()):
                vals = data.pg_shared[port][label]
                ax.plot(
                    rel_times[: len(vals)],
                    [_bytes_to_mb(v) for v in vals],
                    linewidth=1,
                    linestyle="--",
                    label=f"{label}_sh",
                )
        ax.set_title(f"{port} — PG Watermarks (hr=headroom, sh=shared)", fontsize=9)
        ax.set_ylabel("MB")
        ax.set_xlabel("Time (s)")
        if ax.get_legend_handles_labels()[1]:
            ax.legend(fontsize=7, ncol=4, loc="upper left")
        ax.grid(True, alpha=0.3)

    # ── Per-port congestion drop rows ──
    cong_row_offset = port_row_offset + n_wm_port_rows
    for i, port in enumerate(ports_with_congestion):
        row = i + cong_row_offset

        # Col 0: Per-queue congestion drops
        ax = axes[row][0]
        if port in data.congestion_drops:
            for label in sorted(data.congestion_drops[port].keys()):
                vals = data.congestion_drops[port][label]
                n = min(len(rel_times), len(vals))
                ax.plot(
                    rel_times[:n],
                    vals[:n],
                    linewidth=1,
                    label=label,
                )
        ax.set_title(
            f"{port} — Per-Queue Congestion Drops (pkts/60s)",
            fontsize=9,
        )
        ax.set_ylabel("Packets")
        ax.set_xlabel("Time (s)")
        ax.relim()
        ax.autoscale_view()
        ax.set_ylim(bottom=0)
        ax.legend(fontsize=7, ncol=4, loc="upper left")
        ax.grid(True, alpha=0.3)

        # Col 1: Port-level total congestion drops
        ax = axes[row][1]
        if port in data.congestion_drops_port:
            vals = data.congestion_drops_port[port]
            n = min(len(rel_times), len(vals))
            ax.plot(
                rel_times[:n],
                vals[:n],
                "r-",
                linewidth=1.5,
                label="total",
            )
        ax.set_title(
            f"{port} — Port Total Congestion Drops (pkts/60s)",
            fontsize=9,
        )
        ax.set_ylabel("Packets")
        ax.set_xlabel("Time (s)")
        ax.relim()
        ax.autoscale_view()
        ax.set_ylim(bottom=0)
        ax.legend(fontsize=7, loc="upper left")
        ax.grid(True, alpha=0.3)

    fig.tight_layout(rect=[0, 0, 1, 0.96])
    return fig


def build_per_port_plots(
    data: BufferWatermarkData,
    device_name: str,
    output_dir: str,
) -> None:
    """Save a separate PNG per port with individual queue subplots."""
    rel_times = _relative_times(data.timestamps)

    for port in sorted(data.ucast_wm.keys()):
        queues = data.ucast_wm[port]
        n_queues = len(queues)
        if n_queues == 0:
            continue

        fig, axes = plt.subplots(n_queues, 1, figsize=(14, 3 * n_queues), squeeze=False)
        fig.suptitle(
            f"{device_name} — {port} Queue Watermarks\n"
            f"Last updated: {datetime.now().strftime('%H:%M:%S')}",
            fontsize=12,
            fontweight="bold",
        )

        for i, label in enumerate(sorted(queues.keys())):
            ax = axes[i][0]
            vals = queues[label]
            mb_vals = [_bytes_to_mb(v) for v in vals]
            ax.plot(
                rel_times[: len(vals)],
                mb_vals,
                "b-",
                linewidth=1.5,
            )
            ax.set_title(f"{label}", fontsize=10)
            ax.set_ylabel("MB")
            ax.set_xlabel("Time (s)")
            if mb_vals:
                max_v = max(mb_vals)
                if max_v > 0:
                    ax.set_ylim(bottom=0, top=max_v * 1.1)
            ax.grid(True, alpha=0.3)

        fig.tight_layout(rect=[0, 0, 1, 0.95])
        safe_port = port.replace("/", "_")
        path = os.path.join(output_dir, f"buffer_{safe_port}_queues.png")
        fig.savefig(path, dpi=100)
        plt.close(fig)


def print_summary(data: BufferWatermarkData, device_name: str) -> None:  # noqa: C901
    """Print a text summary of the latest sample to the console."""
    if not data.timestamps:
        return

    now_str = datetime.now().strftime("%H:%M:%S")
    sample_count = len(data.timestamps)

    lines = [
        f"\033[1m\033[36m{'=' * 70}\033[0m",
        f"\033[1m  Buffer Watermark — {device_name} | {now_str} | sample #{sample_count}\033[0m",
        f"\033[1m\033[36m{'=' * 70}\033[0m",
    ]

    # Device
    if data.device_wm:
        val = data.device_wm[-1]
        pct = (val / KODIAK3_MMU_BYTES) * 100
        lines.append(
            f"  Device WM: {_bytes_to_mb(val):.2f} MB ({pct:.1f}% of {_bytes_to_mb(KODIAK3_MMU_BYTES):.0f} MB)"
        )

    # Global
    if data.global_shared:
        lines.append(
            f"  Global Shared WM: {_bytes_to_mb(data.global_shared[-1]):.2f} MB"
        )
    if data.global_headroom:
        lines.append(
            f"  Global Headroom WM: {_bytes_to_mb(data.global_headroom[-1]):.2f} MB"
        )

    # Per-port queues
    for port in sorted(data.ucast_wm.keys()):
        queue_vals = []
        for label in sorted(data.ucast_wm[port].keys()):
            vals = data.ucast_wm[port][label]
            if vals:
                queue_vals.append(f"{label}={_bytes_to_mb(vals[-1]):.3f}MB")
        if queue_vals:
            lines.append(f"  {port} queues: {', '.join(queue_vals)}")

    # Per-port PGs
    for port in sorted(
        set(list(data.pg_headroom.keys()) + list(data.pg_shared.keys()))
    ):
        pg_vals = []
        for label in sorted((data.pg_headroom.get(port, {})).keys()):
            vals = data.pg_headroom[port][label]
            if vals:
                pg_vals.append(f"{label}_hr={_bytes_to_mb(vals[-1]):.3f}MB")
        for label in sorted((data.pg_shared.get(port, {})).keys()):
            vals = data.pg_shared[port][label]
            if vals:
                pg_vals.append(f"{label}_sh={_bytes_to_mb(vals[-1]):.3f}MB")
        if pg_vals:
            lines.append(f"  {port} PGs: {', '.join(pg_vals)}")

    # CPU queues
    cpu_vals = []
    for label in sorted(data.cpu_queues.keys()):
        vals = data.cpu_queues[label]
        if vals:
            cpu_vals.append(f"{label}={_bytes_to_mb(vals[-1]):.3f}MB")
    if cpu_vals:
        lines.append(f"  CPU queues: {', '.join(cpu_vals)}")

    # Fabric/core counters
    fabric_vals = []
    for label in sorted(data.fabric_wm.keys()):
        vals = data.fabric_wm[label]
        if vals:
            fabric_vals.append(f"{label}={_bytes_to_mb(vals[-1]):.3f}MB")
    if fabric_vals:
        lines.append(f"  Fabric/Core: {', '.join(fabric_vals)}")

    # Per-port per-queue congestion drops
    cong_ports = sorted(
        set(
            list(data.congestion_drops.keys()) + list(data.congestion_drops_port.keys())
        )
    )
    if cong_ports:
        lines.append("  \033[33m-- Congestion Drops (pkts/60s) --\033[0m")
    for port in cong_ports:
        cong_vals = []
        if port in data.congestion_drops:
            for label in sorted(data.congestion_drops[port].keys()):
                vals = data.congestion_drops[port][label]
                if vals:
                    cong_vals.append(f"{label}={vals[-1]}")
        port_total = ""
        if port in data.congestion_drops_port:
            vals = data.congestion_drops_port[port]
            if vals:
                port_total = f" (port_total={vals[-1]})"
        if cong_vals or port_total:
            lines.append(f"  {port} drops: {', '.join(cong_vals)}{port_total}")

    lines.append("")
    print("\n".join(lines), flush=True)


def write_csv_row(
    writer: t.Any,  # csv.writer object
    ts: float,
    data: BufferWatermarkData,
) -> None:
    """Append a row to the CSV with the latest sample values."""
    row: t.List[t.Any] = [datetime.fromtimestamp(ts).isoformat()]

    row.append(data.device_wm[-1] if data.device_wm else 0)
    row.append(data.global_shared[-1] if data.global_shared else 0)
    row.append(data.global_headroom[-1] if data.global_headroom else 0)

    # Flatten per-port per-queue watermarks
    for port in sorted(data.ucast_wm.keys()):
        for label in sorted(data.ucast_wm[port].keys()):
            vals = data.ucast_wm[port][label]
            row.append(vals[-1] if vals else 0)

    # Flatten per-port per-queue congestion drops
    for port in sorted(data.congestion_drops.keys()):
        for label in sorted(data.congestion_drops[port].keys()):
            vals = data.congestion_drops[port][label]
            row.append(vals[-1] if vals else 0)
    # Per-port total congestion drops
    for port in sorted(data.congestion_drops_port.keys()):
        vals = data.congestion_drops_port[port]
        row.append(vals[-1] if vals else 0)

    writer.writerow(row)


async def monitor_loop(  # noqa: C901
    device_name: str,
    interval: float,
    data: BufferWatermarkData,
    port_filter: t.Optional[t.Set[str]],
    output_dir: t.Optional[str],
    csv_path: t.Optional[str],
    live: bool,
    fb303_port: int,
    no_pg: bool = False,
) -> None:
    """Main polling loop: fetch counters, store, optionally save graphs/CSV."""
    csv_file = None
    csv_writer = None
    if csv_path:
        csv_file = open(csv_path, "w", newline="")
        csv_writer = csv.writer(csv_file)
        # Header written after first sample when we know the columns

    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    sample_num = 0
    csv_header_written = False

    print(
        f"\033[1m\033[32mStarting buffer watermark monitor for {device_name}\033[0m\n"
        f"  Polling interval: {interval}s\n"
        f"  Port filter: {sorted(port_filter) if port_filter else 'all'}\n"
        f"  Output dir: {output_dir or 'none (console only)'}\n"
        f"  CSV file: {csv_path or 'none'}\n"
        f"  Live plot: {live}\n",
        flush=True,
    )

    while True:
        t_start = time.time()
        try:
            counters = await fetch_buffer_counters(device_name, port=fb303_port)
            fetch_duration = time.time() - t_start

            ts = time.time()
            data.add_sample(ts, counters, port_filter, no_pg=no_pg)
            sample_num += 1

            # Console summary
            print_summary(data, device_name)
            print(
                f"  \033[2m(fetched {len(counters)} counters in {fetch_duration:.2f}s)\033[0m\n",
                flush=True,
            )

            # CSV
            if csv_writer:
                if not csv_header_written:
                    header = [
                        "timestamp",
                        "device_wm",
                        "global_shared",
                        "global_headroom",
                    ]
                    for port in sorted(data.ucast_wm.keys()):
                        for label in sorted(data.ucast_wm[port].keys()):
                            header.append(f"{port}.{label}")
                    for port in sorted(data.congestion_drops.keys()):
                        for label in sorted(data.congestion_drops[port].keys()):
                            header.append(f"{port}.{label}.cong_drops")
                    for port in sorted(data.congestion_drops_port.keys()):
                        header.append(f"{port}.cong_drops_total")
                    csv_writer.writerow(header)
                    csv_header_written = True
                write_csv_row(csv_writer, ts, data)
                if csv_file:
                    csv_file.flush()

            # Save graph to file
            if output_dir and sample_num % 5 == 0:  # save every 5 samples
                # Debug: show data ranges per queue
                for port in sorted(data.ucast_wm.keys()):
                    for label in sorted(data.ucast_wm[port].keys()):
                        vals = data.ucast_wm[port][label]
                        if vals:
                            mx = _bytes_to_mb(max(vals))
                            if mx > 0.01:
                                print(
                                    f"  \033[2m  graph debug: {port}.{label} len={len(vals)} max={mx:.3f}MB\033[0m",
                                    flush=True,
                                )
                fig = build_plots(data, device_name)
                path = os.path.join(output_dir, "buffer_watermark_latest.png")
                fig.savefig(path, dpi=100)
                plt.close(fig)
                build_per_port_plots(data, device_name, output_dir)
                print(
                    f"  \033[2mGraphs saved to {output_dir}/\033[0m\n"
                    f"  \033[2mTo view: run `code {output_dir}/buffer_watermark_latest.png` in VS Code terminal\033[0m",
                    flush=True,
                )

            # Live plot update
            if live and sample_num % 3 == 0:
                fig = build_plots(data, device_name)
                fig.savefig("/tmp/buffer_watermark_live.png", dpi=100)
                plt.close(fig)

        except Exception as e:
            print(f"\033[31mError fetching counters: {e}\033[0m", flush=True)

        # Sleep for the remainder of the interval
        elapsed = time.time() - t_start
        sleep_time = max(0, interval - elapsed)
        await asyncio.sleep(sleep_time)


async def _discover_counters(hostname: str, port: int) -> None:
    """Fetch and display all available buffer_watermark and congestion counters."""
    print(
        f"\033[1mDiscovering buffer_watermark and congestion counters on {hostname}...\033[0m\n"
    )
    counters = await fetch_buffer_counters(hostname, port=port, discover=True)

    # Also discover congestion drop counters
    try:
        ports_to_try = (
            [port] if port != 0 else [FBOSS_MNPU_FB303_PORT, FBOSS_FB303_PORT]
        )
        for p in ports_to_try:
            try:
                async with get_direct_client(
                    FacebookService,
                    host=hostname,
                    port=p,
                    client_type=ClientType.THRIFT_ROCKET_CLIENT_TYPE,
                ) as client:
                    all_counters = await client.getCounters()
                    cong_counters = {
                        k: v
                        for k, v in all_counters.items()
                        if "out_congestion_discards" in k
                    }
                    counters.update(cong_counters)
                    break
            except Exception:
                if p == ports_to_try[-1]:
                    pass  # already handled below
    except Exception:
        pass  # congestion counters are optional

    if not counters:
        print(
            f"\033[31mNo buffer_watermark or congestion counters found on {hostname}.\033[0m\n"
            "Possible reasons:\n"
            "  - Wrong fb303 port (try --fb303-port 5909 or 5931)\n"
            "  - Device doesn't expose buffer watermark counters\n"
            "  - Device is unreachable\n"
        )
        return

    wm_counters = {
        k: v for k, v in counters.items() if k.startswith("buffer_watermark")
    }
    cong_counters = {
        k: v for k, v in counters.items() if "out_congestion_discards" in k
    }

    if wm_counters:
        print(f"\033[32mFound {len(wm_counters)} buffer_watermark counters:\033[0m\n")
        for name in sorted(wm_counters.keys()):
            val = wm_counters[name]
            print(f"  {name} = {val} ({_bytes_to_mb(val):.3f} MB)")

    if cong_counters:
        print(
            f"\n\033[32mFound {len(cong_counters)} congestion drop counters:\033[0m\n"
        )
        for name in sorted(cong_counters.keys()):
            val = cong_counters[name]
            print(f"  {name} = {val} pkts")

    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Real-time buffer watermark and congestion drop monitor for Kodiak3 "
            "FBOSS switches. Polls fb303 counters and produces graphs for buffer "
            "utilization (device, global, CPU, per-port queues, PGs) and congestion "
            "drops (per-port per-queue tail drops). Use --discover to see which "
            "counters are available on a device before monitoring."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--device",
        required=True,
        help=(
            "Device hostname to monitor (e.g. rb001-01.qxt1). The script connects "
            "via fb303 Thrift to read buffer watermark and congestion counters."
        ),
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=2.0,
        help=(
            "Polling interval in seconds (default: 2). Lower values give finer "
            "granularity but increase load on the device. Values below 1s are "
            "not recommended for production switches."
        ),
    )
    parser.add_argument(
        "--ports",
        nargs="+",
        default=None,
        help=(
            "Only monitor these specific ports (e.g. --ports eth1/63/1 eth1/63/5). "
            "Filters both watermark and congestion drop counters. Useful for "
            "reducing noise when debugging a specific link. Default: all ports."
        ),
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help=(
            "Directory to save graph snapshots as PNG images. Graphs are updated "
            "every 5 samples. Includes a combined overview graph and individual "
            "per-port queue detail graphs. Default: none (console output only)."
        ),
    )
    parser.add_argument(
        "--csv",
        default=None,
        help=(
            "Path to write raw counter data as CSV. Each row is one sample with "
            "columns for device/global watermarks, per-port queue watermarks, and "
            "per-port per-queue congestion drops. Default: none."
        ),
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help=(
            "Enable live graph updates (saved to /tmp/buffer_watermark_live.png "
            "every 3 samples). Open this file in an image viewer that auto-refreshes "
            "to see a near-real-time dashboard."
        ),
    )
    parser.add_argument(
        "--max-samples",
        type=int,
        default=600,
        help=(
            "Maximum number of samples to keep in memory for graphing (default: 600). "
            "At 2s interval, 600 samples = 20 minutes of history. Increase for "
            "longer monitoring sessions."
        ),
    )
    parser.add_argument(
        "--fb303-port",
        type=int,
        default=0,
        help=(
            "fb303 Thrift port on the device (default: auto-detect). Auto-detection "
            "tries MNPU port 5931 first, then falls back to standard port 5909. "
            "Set explicitly if the device uses a non-standard port."
        ),
    )
    parser.add_argument(
        "--no-pg",
        action="store_true",
        help=(
            "Suppress per-port priority group (PG) headroom/shared watermark "
            "counters from graphs and console output. Useful on devices with many "
            "PGs where the PG data creates visual noise."
        ),
    )
    parser.add_argument(
        "--discover",
        action="store_true",
        help=(
            "Discovery mode: connect to the device, list all available "
            "buffer_watermark and congestion drop counters with their current "
            "values, then exit. Useful for verifying which counters a device "
            "exposes before starting a monitoring session."
        ),
    )

    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)

    if args.discover:
        asyncio.run(_discover_counters(args.device, args.fb303_port))
        return

    port_filter = set(args.ports) if args.ports else None
    data = BufferWatermarkData(max_samples=args.max_samples)

    try:
        asyncio.run(
            monitor_loop(
                device_name=args.device,
                interval=args.interval,
                data=data,
                port_filter=port_filter,
                output_dir=args.output_dir,
                csv_path=args.csv,
                live=args.live,
                fb303_port=args.fb303_port,
                no_pg=args.no_pg,
            )
        )
    except KeyboardInterrupt:
        print("\n\033[1mMonitor stopped.\033[0m")
        # Save final graph
        if data.timestamps:
            fig = build_plots(data, args.device)
            final_path = args.output_dir or "/tmp"
            os.makedirs(final_path, exist_ok=True)
            path = os.path.join(final_path, "buffer_watermark_final.png")
            fig.savefig(path, dpi=150)
            plt.close(fig)
            print(
                f"Final graph saved to {path}\n"
                f"To view: run `code {path}` in VS Code terminal"
            )

        # Save final CSV summary
        if data.timestamps:
            print(f"\nTotal samples collected: {len(data.timestamps)}")
            if data.device_wm:
                peak = max(data.device_wm)
                print(
                    f"Peak device watermark: {_bytes_to_mb(peak):.2f} MB "
                    f"({(peak / KODIAK3_MMU_BYTES) * 100:.1f}%)"
                )


if __name__ == "__main__":
    main()
