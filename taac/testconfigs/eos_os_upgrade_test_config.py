# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""Generalized EOS image-upgrade TestConfig factory, usable for any EOS device.

Builds one TestConfig carrying up to two playbooks, selected at run time with
`--regex`:

  eos_os_upgrade                 image swap and reload only
  eos_os_upgrade_config_replace  image swap and reload, then `configure replace`

The second playbook is only built when the caller supplies `config_replace_file`.

Why the config-replace variant exists: `eos_os_upgrade` performs an image swap
ONLY. It deliberately does not run the config, chef/cert, optics-firmware, and
vendor-audit phases that a real `pwm provision` runs after `EOSUpgradePhase`.
That gap bit us on bag001.snc1 — after an image change LACP would not negotiate
and BGP stayed down, and a manual `configure replace` restored it with no
further image change. See `internal/tasks/eos_os_upgrade_task.py`.

Every device-specific value is a REQUIRED argument. Nothing is defaulted, so a
value cannot be silently inherited from an unrelated device. That rule is not
theoretical: carrying a netcode package over from another device
(`arista_eos_4.36.2f-dpe-ctnr`, which is name-scoped in configerator to
cbag001.qzp1 / cpr001.qzp1) put bag001.snc1's SandFapNi agents into a SIGABRT
crash loop and took its entire data plane down. Resolve the right package for a
device with `code-versioner list-files --device <device>`.

No IXIA: none of the checks here need traffic, so `ixia_needed=False` keeps the
run fast and avoids reserving chassis ports.
"""

import typing as t

from taac.playbooks.playbook_definitions import (
    create_eos_os_upgrade_playbook,
    create_eos_os_upgrade_with_config_replace_playbook,
)
from taac.test_as_a_config import types as taac_types


def create_eos_os_upgrade_test_config(
    device_name: str,
    netcode_package: str,
    basset_pool: str,
    test_config_name: str,
    neighbor_endpoints: t.Optional[t.List[str]] = None,
    config_replace_file: t.Optional[str] = None,
    image_file: t.Optional[str] = None,
    expected_version: t.Optional[str] = None,
    skip_if_current: bool = True,
    clear_flash: bool = False,
    stop_after_download: bool = False,
    bgp_min_established_pct: t.Optional[float] = None,
    download_timeout_s: t.Optional[int] = None,
    ssh_wait_s: t.Optional[int] = None,
    warmup_timeout_s: t.Optional[int] = None,
    post_reload_settle_s: t.Optional[int] = None,
    drain: bool = False,
    task_id: t.Optional[str] = None,
) -> t.List[taac_types.TestConfig]:
    """Build the EOS image-upgrade TestConfig for one device.

    Args:
        device_name: DUT hostname.
        netcode_package: netcode package to install, e.g.
            `arista_eos_4.35.2fx-r4.2`. This is the package name as published
            under https://netcode.any.fbinfra.net/dl/image/<package>/, NOT a
            bare EOS version — package names are not derivable from a version
            string (`arista_eos_4.25.1fx-400g-macsec-ga` carries a `-ga` suffix
            the version does not).
        basset_pool: lab reservation pool the DUT belongs to. Pools differ per
            device: bag001.snc1 is in `networkai.test.regression`, while most
            DNE configs use `dne.test`.
        test_config_name: `--test-config` name.
        neighbor_endpoints: hostnames of the DUT's link neighbours, added as
            non-DUT endpoints. REQUIRED for LLDP_CHECK and PORT_STATE_CHECK to
            mean anything: the test bed chunker only populates
            `TestDevice.interfaces` for links whose neighbour is also a declared
            endpoint, so without these both checks assert nothing and report
            PASS. Observed on bag001.snc1, which passed both at PRE_TEST while
            it had 0 links up and 0 LLDP neighbours. When omitted, those two
            checks are left out of the playbooks entirely rather than shipped in
            a form that cannot fail. `dut=False` keeps them out of the DUT list,
            so they add no extra test cases.
        config_replace_file: when set, adds the upgrade+config-replace playbook.
            On-device config in `flash:<name>` form, e.g.
            `flash:config_may4_2026`. Device-specific, so no default.
        image_file: explicit `.swi` within the package; only needed when the
            package publishes more than one.
        expected_version: what `show version` should report afterwards.
            Defaults to the netcode Package.version, which does not always
            match the CLI string.
        skip_if_current: when True (default), a device already on the target
            version is a no-op rather than a failure.
        clear_flash: delete deletable files (including the running `*.swi`)
            from /mnt/flash before downloading. Defaults False: that glob
            removes the image the device is booted from, so a failed download
            would leave it unable to boot. Only enable when the device lacks
            room for both images.
        stop_after_download: download and md5-verify, then stop without writing
            boot-config or reloading. Use to prove the download path on
            hardware without changing what the device boots.
        bgp_min_established_pct: when set, adds an absolute BGP establish check
            with this established/total floor. None (default) omits it, leaving
            the BGP session SNAPSHOT check as the sole BGP signal. Omitting is
            usually right on a lab DUT: bag001.snc1 runs 4 Established out of
            56 configured sessions, so an all-or-nothing check would fail the
            precheck and abort before the device is touched.
        download_timeout_s: per-attempt wget timeout. Task default 900.
        ssh_wait_s: post-reload wait for the device to answer again. Task
            default 1800, sized for a 7808 chassis.
        warmup_timeout_s: EOS `wait-for-warmup` timeout. Task default 900.
        post_reload_settle_s: bounded settle after warmup before postchecks.
            Task default 180. Set 0 for a fixed-configuration device.
        drain: when True, NDS-drain the device first. Requires `task_id`.
        task_id: task number recorded against the drain.

    Returns:
        A single-element list holding the TestConfig.
    """
    task_params: t.Dict[str, t.Any] = {
        "device_name": device_name,
        "netcode_package": netcode_package,
        "skip_if_current": skip_if_current,
        "clear_flash": clear_flash,
        "stop_after_download": stop_after_download,
        "drain": drain,
    }
    for key, value in (
        ("image_file", image_file),
        ("expected_version", expected_version),
        ("download_timeout_s", download_timeout_s),
        ("ssh_wait_s", ssh_wait_s),
        ("warmup_timeout_s", warmup_timeout_s),
        ("post_reload_settle_s", post_reload_settle_s),
        ("task_id", task_id),
    ):
        if value is not None:
            task_params[key] = value

    # Link checks are only meaningful when the DUT's neighbours are in the
    # topology; otherwise they are structurally incapable of failing.
    include_link_checks = bool(neighbor_endpoints)

    playbooks = [
        create_eos_os_upgrade_playbook(
            device_name=device_name,
            netcode_package=netcode_package,
            task_params=task_params,
            include_link_checks=include_link_checks,
            bgp_min_established_pct=bgp_min_established_pct,
        ),
    ]
    if config_replace_file is not None:
        playbooks.append(
            create_eos_os_upgrade_with_config_replace_playbook(
                device_name=device_name,
                netcode_package=netcode_package,
                task_params=task_params,
                config_replace_file=config_replace_file,
                include_link_checks=include_link_checks,
                bgp_min_established_pct=bgp_min_established_pct,
            )
        )

    endpoints = [
        taac_types.Endpoint(name=device_name, dut=True, ixia_needed=False),
    ]
    endpoints.extend(
        taac_types.Endpoint(name=neighbor, dut=False, ixia_needed=False)
        for neighbor in (neighbor_endpoints or [])
    )

    return [
        taac_types.TestConfig(
            name=test_config_name,
            basset_pool=basset_pool,
            endpoints=endpoints,
            playbooks=playbooks,
        )
    ]


# ---------------------------------------------------------------------------
# Device instances. Add one call per EOS DUT you want to qualify.
#
# `arista_eos_4.35.2fx-r4.2` is bag001.snc1's own code-versioner tier image
# (ARISTA_SEINE_FX2_GA) and the only image it is known-healthy on.
#
# WARNING: as of 2026-08-27 bag001.snc1 is running 4.36.2F, so a bare
# `--test-config BAG001_SNC1_EOS_OS_UPGRADE` run is NOT a no-op — it performs a
# real downgrade and reload back to the tier image. That is intentional (it
# restores the device to its pinned image), but it is a live, disruptive
# operation, not a dry run. `skip_if_current` only makes it a no-op once the
# device is actually on the target.
#
# To qualify a different image, override `netcode_package` at the call site so
# the image under test is visible in the diff that runs it.
# ---------------------------------------------------------------------------
BAG001_SNC1_EOS_OS_UPGRADE_TEST_CONFIGS: t.List[taac_types.TestConfig] = (
    create_eos_os_upgrade_test_config(
        device_name="bag001.snc1",
        netcode_package="arista_eos_4.35.2fx-r4.2",
        basset_pool="networkai.test.regression",
        test_config_name="BAG001_SNC1_EOS_OS_UPGRADE",
        # bag001.snc1's real link neighbours: Et5/1-8 -> edsw003.n000,
        # Et6/19-26 -> edsw003.n001. Declaring them is what makes LLDP_CHECK and
        # PORT_STATE_CHECK actually validate anything.
        neighbor_endpoints=[
            "edsw003.n000.l201.snc1",
            "edsw003.n001.l201.snc1",
        ],
        # bag001.snc1's real link neighbours: Et5/1-8 -> edsw003.n000,
        # Et6/19-26 -> edsw003.n001. Declaring them is what makes LLDP_CHECK and
        # PORT_STATE_CHECK actually validate anything.
        config_replace_file="flash:config_may4_2026",
    )
)
