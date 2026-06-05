# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe
import asyncio
import typing as t

from taac.constants import TestTopology
from taac.health_checks.abstract_health_check import (
    AbstractTopologyHealthCheck,
)
from taac.utils.driver_factory import async_get_device_driver
from taac.health_check.health_check import types as hc_types


class OpenrKvstoreConsistencyHealthCheck(
    AbstractTopologyHealthCheck[hc_types.BaseHealthCheckIn]
):
    """
    Validates that the Open/R KvStore kv-signature is identical
    across all devices in the topology. All switches in the same area
    must produce the same hash when in sync.
    """

    # TODO: Update to the real CheckName once added to health_check.thrift
    CHECK_NAME = hc_types.CheckName.OPENR_KVSTORE_CONSISTENCY_CHECK

    async def _run(
        self,
        obj: TestTopology,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        hostnames = list(obj.device_names)
        if len(hostnames) < 2:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.SKIP,
                message="Need at least 2 devices to check KvStore consistency",
            )

        drivers = await asyncio.gather(
            *[async_get_device_driver(hostname) for hostname in hostnames]
        )
        hostname_to_driver = dict(zip(hostnames, drivers))

        signatures = await asyncio.gather(
            *[
                # pyre-fixme[16]: `AbstractSwitch` has no attribute
                #  `async_get_openr_kvstore_kv_signature`.
                hostname_to_driver[h].async_get_openr_kvstore_kv_signature()
                for h in hostnames
            ]
        )
        host_signatures = dict(zip(hostnames, signatures))

        all_areas: t.Set[str] = set()
        for sig_dict in signatures:
            all_areas.update(sig_dict.keys())

        failure_reasons = []
        for area in sorted(all_areas):
            area_sigs = {}
            for hostname, sig_dict in host_signatures.items():
                if area in sig_dict:
                    area_sigs[hostname] = sig_dict[area]

            if len(area_sigs) < 2:
                continue

            unique_sigs = set(area_sigs.values())
            if len(unique_sigs) > 1:
                details = ", ".join(f"{h}={s[:16]}..." for h, s in area_sigs.items())
                failure_reasons.append(
                    f"Area '{area}' has mismatched kv-signatures: {details}"
                )

        if failure_reasons:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message="KvStore consistency check FAILED: "
                + "; ".join(failure_reasons),
            )

        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
            message=f"KvStore consistent across {len(hostnames)} device(s) "
            f"in {len(all_areas)} area(s)",
        )
