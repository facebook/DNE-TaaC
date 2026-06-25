# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe
import time
import typing as t

from taac.custom_test_handlers.base_custom_test_handler import (
    BaseCustomTestHandler,
)
from taac.internal.internal_utils import (
    generate_cubism_dive_urls,
    generate_cubism_overview_url,
)
from taac.utils.oss_taac_lib_utils import none_throws
from tabulate import tabulate


FBOSS_DSF_CONTEXTS: t.List[str] = [
    "l1_errors",
    "out_errors",
    "in_discards",
    "out_discards",
    "out_congestion_discards",
    "out_pfc",
    "voq_deletes",
    "voq_tail_drops",
    "hw_update_failures",
    "fabric_topology_errors",
    "asic_errors",
    "agent_unclean_exits",
    "stats_collection_failed",
    "global_fabric_drops",
    "route_congestion_drops",
    "failed_dsf_subscription",
    "fabric_overdrained",
    "pfc_deadlock_detected",
    "dsf_gr_expired",
    "dsf_update_failed",
    "packet_integrity_drop",
    "reachability_drops",
    "fsdb_unclean_exits",
    "fsdb_dropped_state",
]

CUBISM_GROUP_NAME: str = "fbossdsf"


class DsfTestHandler(BaseCustomTestHandler):
    SUPPORTED_TAGS = ["dsf"]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.test_case_start_time: float = 0.0

    async def async_test_case_setUp(
        self,
    ) -> None:
        self.test_case_start_time = time.time()

    async def async_test_case_tearDown(
        self,
    ) -> None:
        test_end_time = int(time.time())
        cluster_name = none_throws(self.test_topology.devices[0].attributes.ai_zone)
        dash_dive_params = {
            "cluster_name": cluster_name,
            "scuba_granularity": "auto",
            "time_end_unix_seconds": str(test_end_time),
            "time_start_unix_seconds": str(self.test_case_start_time),
        }
        overview_params = {
            "auto": "false",
            "c": cluster_name,
            "transpose": "true",
            "start_time": str(self.test_case_start_time),
            "end_time": str(test_end_time),
        }
        dash_urls = generate_cubism_dive_urls(
            CUBISM_GROUP_NAME, FBOSS_DSF_CONTEXTS, dash_dive_params
        )
        overview_url = generate_cubism_overview_url(CUBISM_GROUP_NAME, overview_params)
        tabulated = tabulate(
            [[context, url] for context, url in zip(FBOSS_DSF_CONTEXTS, dash_urls)],
            headers=["Context", "Cubism Dive URL"],
            tablefmt="simple_grid",
        )
        self.logger.info(f"Cubism Overview URL:\n{overview_url}")
        self.logger.info(f"Cubism Dash Dive URLs:\n{tabulated}")
