# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""
FBOSS-compatible custom step for checking BGP fiber queue depths.

Makes a single thrift call via BgpClientHelper to collect queue stats
and logs the results. Works on any device with BGP thrift service on
port 6909 (both FBOSS and EOS).
"""

import typing as t

from taac.internal.utils.bgp_client_helper import BgpClientHelper


class BgpQueueMonitorFbossCustomStep:
    """
    Simple BGP queue depth check via thrift.

    Connects to the BGP thrift service, calls getMonitoredQueueSizes(),
    and logs aggregate queue depths for focused queues.
    """

    def __init__(self, step: t.Any) -> None:
        self.step: t.Any = step
        self.logger: t.Any = step.logger

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        """
        Collect and log BGP fiber queue stats via thrift.

        Args:
            params: Dictionary containing:
                - hostname: Device hostname
                - focused_queues: Queue names to highlight
                  (default: AdjRibIn, RibOut, RibIn)
        """
        hostname = params["hostname"]
        focused_queues = params.get("focused_queues", ["AdjRibIn", "RibOut", "RibIn"])

        self.logger.info("=" * 60)
        self.logger.info("BGP QUEUE DEPTH CHECK")
        self.logger.info(f"Device: {hostname}")
        self.logger.info("=" * 60)

        bgp_helper = BgpClientHelper(host=hostname)
        queue_stats = await bgp_helper.async_get_fiber_queue_stats()

        total_queues = queue_stats.get("total_queues", 0)
        max_depth = queue_stats.get("max_queue_depth", 0)
        queue_details = queue_stats.get("queue_details", {})

        self.logger.info(f"Total queues: {total_queues}")
        self.logger.info(f"Max queue depth: {max_depth}")

        # Queue name mapping (BGP++ internal names to friendly names)
        queue_name_mapping = {
            "ingress_adjrib_in": "AdjRibIn",
            "egress_rib_out": "RibOut",
            "ingress_rib_in": "RibIn",
        }

        # Aggregate focused queue depths
        aggregate = {q: 0 for q in focused_queues}
        for queue_name, depth in queue_details.items():
            # Check per-peer queues (peer_manager.session_manager.<IP>.<type>)
            if "peer_manager.session_manager." in queue_name:
                parts = queue_name.split(".")
                if len(parts) >= 4:
                    friendly = queue_name_mapping.get(parts[-1])
                    if friendly and friendly in aggregate:
                        aggregate[friendly] += depth
            # Check global queues (rib.<type>)
            elif queue_name.startswith("rib."):
                bgp_type = queue_name.split(".", 1)[1] if "." in queue_name else None
                if bgp_type:
                    friendly = queue_name_mapping.get(bgp_type)
                    if friendly and friendly in aggregate:
                        aggregate[friendly] += depth

        self.logger.info("\nFocused queue depths (aggregate):")
        for queue_name, depth in aggregate.items():
            self.logger.info(f"  {queue_name}: {depth} items")

        # Log top active queues
        active_queues = {
            name: depth for name, depth in queue_details.items() if depth > 0
        }
        if active_queues:
            self.logger.info(f"\nActive queues ({len(active_queues)}):")
            for name, depth in sorted(
                active_queues.items(), key=lambda x: x[1], reverse=True
            )[:10]:
                self.logger.info(f"  {name}: {depth}")

        self.logger.info("=" * 60)
