# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
import asyncio
import time
import typing as t

from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.health_checks.constants import (
    DAILY_TABLE_TRANSFORM_DESC,
)
from taac.internal.ods_utils import (
    async_generate_ods_url,
    async_query_ods,
)
from taac.libs.fpf.fpf_collector_registry import (
    get_test_case_start_time,
)
from neteng.test_infra.dne.taac.utils.common import async_get_fburl_retry, eval_jq
from pyre_extensions import JSON
from taac.health_check.health_check import types as hc_types


def dict(ods_data) -> JSON:
    dict_data = {}
    for hostname, time_series in ods_data.items():
        dict_data[hostname] = {}
        for timestamp, value in time_series.items():
            dict_data[hostname][str(timestamp)] = value
    # pyrefly: ignore [bad-return]
    return dict_data


class GenericOdsHealthCheck(AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]):
    CHECK_NAME = hc_types.CheckName.GENERIC_ODS_CHECK
    LOG_TO_SCUBA = True

    async def _run(  # noqa: C901
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        key_desc = check_params["key_desc"]
        entity_desc = check_params.get("entity_desc", obj.name)
        min_ods_query_duration = int(check_params.get("min_ods_query_duration", 120))
        use_tc_start = check_params.get("use_test_case_start_time", False)
        if use_tc_start:
            tc_start = get_test_case_start_time()
            start_time = int(tc_start) if tc_start else int(time.time())
        else:
            start_time = int(check_params.get("start_time", time.time()))
        # wait x seconds before checking ods data
        sleep_timer = check_params.get("sleep_timer", 120)
        if sleep_timer > 0:
            await asyncio.sleep(sleep_timer)
        end_time = int(time.time())
        if end_time - start_time < min_ods_query_duration:
            start_time = end_time - min_ods_query_duration
        transform_desc = check_params.get("transform_desc", DAILY_TABLE_TRANSFORM_DESC)
        reduce_desc = check_params.get("reduce_desc", "")
        validation_expr = check_params.get("validation_expr")
        custom_jq_expr = check_params.get("custom_jq_expr")
        assert validation_expr or custom_jq_expr
        ods_data = await async_query_ods(
            entity_desc=entity_desc,
            key_desc=key_desc,
            reduce_desc=reduce_desc,
            transform_desc=transform_desc,
            start_time=int(start_time),
            end_time=int(end_time),
        )
        if not ods_data:
            ods_query_url_raw = await async_generate_ods_url(
                entity_desc=entity_desc,
                key_desc=key_desc,
                reduce_desc=reduce_desc,
                transform_desc=transform_desc,
                start_time=int(start_time),
                end_time=int(end_time),
            )
            # A SKIP (no data) is not a failure and does not need a short link;
            # keep the raw ODS URL inline and skip the throttled fburl tier.
            ods_query_url = ods_query_url_raw
            msg = f"ODS query returned no data: {ods_query_url}"
            self.logger.debug(msg)
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.SKIP,
                message=msg,
            )
        is_multi_entity = "," in entity_desc
        counter_name = check_params.get("counter_name", key_desc)
        # By default the (dominant) passing path keeps the raw ODS URL to avoid
        # hammering the throttled fburl service, since this check is reused many
        # times per device per iteration. Callers that run it sparingly (e.g.
        # FPF postchecks) can opt into a short fburl on PASS too.
        shorten_pass_url = check_params.get("shorten_pass_url", False)
        # aggregate="max" evaluates each entity's PEAK over the window against
        # validation_expr (instead of every sample). require="any" passes if at
        # least one entity meets it; "all" (default) needs every entity. This is
        # how "assert a transient event happened" checks (e.g. in_discard loss
        # during a disruption) must work: the counter is 0 at most samples and
        # only spikes on the impacted path, so per-sample / all-entity evaluation
        # would never pass.
        aggregate = check_params.get("aggregate")  # None | "max"
        require = check_params.get("require", "all")  # "all" | "any"
        # When informational, a threshold breach is surfaced as a PASS with an
        # "[INFORMATIONAL]" message (values + ODS link still logged/registered)
        # rather than failing the test — used for expected transient discards
        # during a disruptive restart/coldboot.
        informational = bool(check_params.get("informational", False))
        violations = []
        entity_max_map: t.Dict[str, t.Tuple[float, str]] = {}

        if is_multi_entity:
            entities_to_check = ods_data
        else:
            entities_to_check = {
                entity_desc: ods_data.get(entity_desc, ods_data.get(obj.name, {}))
            }
        for entity_name, entity_data in entities_to_check.items():
            ods_data_dict = dict(entity_data)
            all_values = {}
            for _key_name, ts_data in entity_data.items():
                for ts, val in ts_data.items():
                    all_values[ts] = val
            if all_values:
                # pyrefly: ignore [no-matching-overload]
                max_ts = max(all_values, key=all_values.get)
                max_val = all_values[max_ts]
                max_time_str = time.strftime(
                    "%Y-%m-%d %H:%M:%S", time.localtime(int(max_ts))
                )
                entity_max_map[entity_name] = (max_val, max_time_str)
            else:
                entity_max_map[entity_name] = (0.0, "no data")

            if validation_expr and not aggregate:
                jq_expr = f". | .[] | to_entries | map(select(.value {validation_expr} | not)) | from_entries"
                violation_data = eval_jq(jq_expr, ods_data_dict)  # pyre-ignore
                if violation_data:
                    # Don't log per-timestamp/per-entity violation lines — they
                    # spew hundreds of DEBUG lines for a single failing check.
                    # The one-line collapsed summary below + the per-entity
                    # fail_summary in the FAIL message carry the same info. Only
                    # the count of violations matters here (PASS/FAIL decision).
                    violations.extend(violation_data.items())
            elif custom_jq_expr:
                violation_data = eval_jq(custom_jq_expr, ods_data_dict)  # pyre-ignore
                if violation_data:
                    violations.append(violation_data)

        ods_url_raw = await async_generate_ods_url(
            entity_desc=entity_desc,
            key_desc=key_desc,
            reduce_desc=reduce_desc,
            transform_desc=transform_desc,
            start_time=int(start_time),
            end_time=int(end_time),
        )
        # One-line collapsed summary (instead of the per-timestamp violation
        # spew above, which stays at DEBUG): per-device max + how many met the
        # threshold. Makes "why did this ODS check fail" readable at a glance.
        met = sum(
            1
            for v, _ in entity_max_map.values()
            if not validation_expr or eval(f"{v} {validation_expr}")
        )
        per_device = ", ".join(
            f"{e.split(':')[0].split('.')[0]}={v:.0f}"
            for e, (v, _) in sorted(entity_max_map.items())
        )
        self.logger.info(
            f"  [{counter_name}] {met}/{len(entity_max_map)} entities met "
            f"'{validation_expr or 'n/a'}'"
            f"{f' (require={require})' if aggregate else ''}; "
            f"per-device max: {per_device}"
        )

        # aggregate="max": decide pass/fail on the per-entity PEAK, under the
        # require policy ("any" -> at least one entity meets the expr; "all" ->
        # every entity must). This is the "did a transient event happen on the
        # impacted path" semantic (e.g. in_discard loss during a disable/drain).
        if aggregate == "max":
            n = len(entity_max_map)
            if require == "any":
                aggregate_passed = met >= 1
            else:
                aggregate_passed = n > 0 and met == n
            violations = [] if aggregate_passed else [("aggregate", require)]

        # Resolve the display URL ONCE and reuse it for the log line, the FPF
        # artifact, and the result message — never spew the long ODS URL. FPF
        # callers (shorten_pass_url=True) always get an fburl. Other callers
        # keep the raw URL on the (dominant) passing path to avoid fburl QPS,
        # and only shorten on failure (handled below).
        has_violations = bool(violations)
        display_url = ods_url_raw
        if shorten_pass_url or has_violations:
            try:
                display_url = await async_get_fburl_retry(ods_url_raw)
            except Exception:
                display_url = ods_url_raw

        self.logger.info(f"  [{counter_name}] ODS: {display_url}")

        # FPF callers register the ODS query link into the FPF artifact registry
        # for the consolidated end-of-test summary.
        if shorten_pass_url:
            from taac.libs.fpf.fpf_collector_registry import (
                register_artifact,
            )

            register_artifact("ods", str(counter_name), display_url)

        max_summary = ", ".join(
            f"{e}: {v:.0f}" for e, (v, _) in sorted(entity_max_map.items())
        )

        if has_violations:
            failed_entities = [
                f"{e}: max={v:.0f} at {ts}"
                for e, (v, ts) in sorted(entity_max_map.items())
                if validation_expr and not eval(f"{v} {validation_expr}")
            ]
            fail_summary = (
                "; ".join(failed_entities) if failed_entities else max_summary
            )
            if aggregate == "max":
                # "assert peak met the expr" failed: no (require=any) / not every
                # (require=all) entity's peak satisfied it.
                lead = (
                    f"{counter_name}: no device peak met '{validation_expr}'"
                    if require == "any"
                    else f"{counter_name}: not all device peaks met '{validation_expr}'"
                )
                breach_status = (
                    hc_types.HealthCheckStatus.PASS
                    if informational
                    else hc_types.HealthCheckStatus.FAIL
                )
                prefix = "[INFORMATIONAL] " if informational else ""
                return hc_types.HealthCheckResult(
                    status=breach_status,
                    message=f"{prefix}{lead} — peaks: {max_summary} | ODS: {display_url}",
                )
            if informational:
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.PASS,
                    message=(
                        f"[INFORMATIONAL] {counter_name} over threshold "
                        f"(expected during disruption; not failing) — {fail_summary} "
                        f"| ODS: {display_url}"
                    ),
                )
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=(
                    f"{counter_name} threshold exceeded — {fail_summary} | "
                    f"ODS: {display_url}"
                ),
            )
        if aggregate == "max":
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.PASS,
                message=(
                    f"{counter_name} peak met '{validation_expr}' "
                    f"({require}) — peaks: {max_summary} | ODS: {display_url}"
                ),
            )
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
            message=(
                f"{counter_name} within threshold — {max_summary} | ODS: {display_url}"
            ),
        )
