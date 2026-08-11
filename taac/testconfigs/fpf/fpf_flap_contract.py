# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe

"""Disrupt-window health-check contract for the FPF cont-interface-flap configs.

The flap configs (tc40 + tc42/43/44 flaps+restart) flap the GTSW<->GPU DOWNLINKS
of all 8 GTSWs facing one rtptest host (and optionally restart a service in
parallel). The disrupt (first) playbook asserts this contract; the SECOND
(longevity) playbook is full stable-state (create_fpf_hardening_playbook_v2) and
is unchanged.

Contract for the flap DISRUPT playbook (per test owner):
  SAME AS STABLE STATE (uplinks are NOT touched — only gtsw<->rtptest downlinks):
    - BGP_SESSION_ESTABLISH   (gtsw<->stsw sessions don't flap)
    - SYSTEMCTL_ACTIVE_STATE  (a graceful service restart still ends active)
    - UNCLEAN_EXIT            (graceful restart = clean exit)
    - DEVICE_CORE_DUMPS
    - MEMORY_UTILIZATION
    - FPF_HRT_SYSTEM_MEMORY / FPF_HRT_DRIVER_DISCONNECT
    - FPF_BGP_RIB_CONVERGENCE / FPF_FSDB_RIBMAP_CONVERGENCE (per observed GTSW)
  SKIPPED in the disrupt window (churn during flaps; judged in longevity):
    - PORT_STATE              (downlinks are being flapped)
    - FPF_HRT_FSDB_SESSION    (sessions churn as downlinks flap)
    - FPF_PROD_HRT_PREFIX_STABILITY
    - FPF_HRT_BULK_CONVERGENCE / FPF_HRT_REMOTE_FAILURE
    - FPF_HOST_SPRAY          (per-lane egress churns as downlinks flap)
  ODS (ALL informational during the flap window):
    - in/out CONGESTION discards: EXPECTED during parallel flaps (egress
      microbursts) -> captured informationally, never fails. Stays HARD ==0 in
      the longevity/stable playbook where a steady-state regression must surface.
    - in_dst_null / in_discard: discards EXPECTED during flaps -> captured
      informationally (peak + ODS link recorded, never fails)
"""

from taac.health_checks.healthcheck_definitions import (
    create_bgp_session_establish_check,
    create_device_core_dumps_check,
    create_fpf_bgp_rib_convergence_check,
    create_fpf_fsdb_ribmap_convergence_check,
    create_fpf_hrt_driver_disconnect_check,
    create_fpf_hrt_system_memory_check,
    create_fpf_ods_counter_check,
    create_memory_utilization_check,
    create_systemctl_active_state_check,
    create_unclean_exit_check,
)
from neteng.test_infra.dne.taac.libs.fpf.fpf_thresholds import ACTIVE as _THR

# ODS discard/congestion counters on the GTSW "industrial cards".
_ODS_REDUCE = r"groupby(entity, (\S+?\.\S+?)\..*, %1),sum"
_ODS_IN_DST_NULL_KEY = (
    r"regex(fboss.agent.eth.*discards.sum.60),filter(.*in_dst_null.*)"
)
_ODS_IN_DISCARD_KEY = r"regex(fboss.agent.eth.*discards.sum.60),filter(.*in_discard.*)"
_ODS_IN_CONGESTION_KEY = (
    r"regex(fboss.agent.eth.*congestion.*sum.60),filter(.*in_congestion_discards.sum.*)"
)
_ODS_OUT_CONGESTION_KEY = r"regex(fboss.agent.eth.*congestion.*sum.60),filter(.*out_congestion_discards.sum.*)"


def build_flap_disrupt_postchecks(
    *,
    observer_gtsws: list[str],
    hrt_memory_hosts: list[str],
    prefix_count: int,
    skip_ssh: bool,
) -> list:
    """Return the disrupt-window postchecks for a cont-flap config (see module doc)."""
    checks = []

    # SSH/device-shell checks — identical to stable state.
    if not skip_ssh:
        checks.extend(
            [
                create_bgp_session_establish_check(
                    min_established_pct=0.5, check_id="flap_disrupt_bgp_establish"
                ),
                create_systemctl_active_state_check(
                    services_json=["bgpd", "fsdb", "wedge_agent", "qsfp_service"]
                ),
                create_unclean_exit_check(),
                create_device_core_dumps_check(use_start_time=True),
                create_memory_utilization_check(
                    threshold=_THR.mem_util_default_bytes,
                    threshold_by_service=dict(_THR.mem_util_by_service),
                    start_time_jq_var="test_case_start_time",
                ),
            ]
        )

    # HRT process health — same as stable (system memory now 9 GiB via ACTIVE).
    checks.append(
        create_fpf_hrt_system_memory_check(
            hosts=hrt_memory_hosts, check_id="flap_disrupt_hrt_mem"
        )
    )
    checks.append(
        create_fpf_hrt_driver_disconnect_check(
            hosts=hrt_memory_hosts, check_id="flap_disrupt_hrt_driver"
        )
    )

    # BGP RIB + FSDB ribMap convergence — same as stable (uplinks untouched), per GTSW.
    for lane_id, gtsw in enumerate(observer_gtsws):
        lane_map = {str(lane_id): gtsw}
        checks.append(
            create_fpf_fsdb_ribmap_convergence_check(
                lane_map=lane_map,
                expected_matched=prefix_count,
                use_live_collectors=True,
                check_id=f"flap_disrupt_fsdb_convergence_lane{lane_id}",
            )
        )
        checks.append(
            create_fpf_bgp_rib_convergence_check(
                lane_map=lane_map,
                expected_matched=prefix_count,
                use_live_collectors=True,
                check_id=f"flap_disrupt_bgp_convergence_lane{lane_id}",
            )
        )

    # ODS: ALL counters informational during the flap window. in_dst_null /
    # in_discard AND in/out_congestion discards are all EXPECTED while downlinks
    # flap (parallel flaps across 8 GTSWs cause egress microbursts), so capture
    # the peaks for the record but never fail. Congestion stays HARD ==0 in the
    # longevity / stable playbook (generic v2 builder), which is where a real
    # steady-state congestion regression must surface.
    ods_entity_desc = ",".join(observer_gtsws)
    checks.extend(
        [
            create_fpf_ods_counter_check(
                entity_desc=ods_entity_desc,
                key_desc=_ODS_IN_DST_NULL_KEY,
                validation_expr=">= 1",
                reduce_desc=_ODS_REDUCE,
                aggregate="max",
                require="any",
                informational=True,
                counter_name="in_dst_null discards (expected during flaps, captured)",
                check_id="flap_disrupt_ods_in_dst_null",
            ),
            create_fpf_ods_counter_check(
                entity_desc=ods_entity_desc,
                key_desc=_ODS_IN_DISCARD_KEY,
                validation_expr=">= 1",
                reduce_desc=_ODS_REDUCE,
                aggregate="max",
                require="any",
                informational=True,
                counter_name="in_discard discards (expected during flaps, captured)",
                check_id="flap_disrupt_ods_in_discard",
            ),
            create_fpf_ods_counter_check(
                entity_desc=ods_entity_desc,
                key_desc=_ODS_IN_CONGESTION_KEY,
                validation_expr=">= 1",
                reduce_desc=_ODS_REDUCE,
                aggregate="max",
                require="any",
                informational=True,
                counter_name="in_congestion discards (expected during flaps, captured)",
                check_id="flap_disrupt_ods_in_congestion",
            ),
            create_fpf_ods_counter_check(
                entity_desc=ods_entity_desc,
                key_desc=_ODS_OUT_CONGESTION_KEY,
                validation_expr=">= 1",
                reduce_desc=_ODS_REDUCE,
                aggregate="max",
                require="any",
                informational=True,
                counter_name="out_congestion discards (expected during flaps, captured)",
                check_id="flap_disrupt_ods_out_congestion",
            ),
        ]
    )

    return checks
