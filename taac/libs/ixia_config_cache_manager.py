# pyre-strict
# Copyright (c) Meta Platforms, Inc. and affiliates.

"""
Cache manager for IxNetwork topology configurations (ixncfg files).

Today's TAAC runs spend 226s (BAG012) to 40+ min (BAG010/011 production scale)
in `create_basic_setup` calling per-API REST setup for the IXIA topology. This
manager replaces that with a `LoadConfig` of a pre-built ixncfg on the API
server — ~10-20s on cache hit.

Cache key shape: `{test_config_name}__{chassis_id}__{config_hash}.ixncfg`
  - test_config_name: different tests need different topologies
  - chassis_id: ixncfg embeds vport↔chassis-port bindings; cross-chassis breaks
  - config_hash: 12-char prefix of sha256(_CACHE_VERSION + IxiaConfig Thrift bytes).
    The hash rolls (and invalidates stale caches) when EITHER the IxiaConfig
    struct content changes OR `_CACHE_VERSION` is bumped. Bump _CACHE_VERSION
    when Python setup logic (`create_basic_setup`, etc.) changes in a way that
    affects the resulting topology even if the IxiaConfig struct is unchanged.

Tier 1 (chassis-local) is implemented but de facto broken — IxNetwork's
SaveConfig does not durably write to arbitrary server paths and the default
storage location is wiped between sessions (bag012 e2e 2026-06-05 spent 9
runs proving the limits). Tier 2 (Manifold) was implemented next and is the
effective cache: on Tier 1 miss we try Manifold, on miss-of-miss fall through
to cold `create_basic_setup`. The Tier 2 save path uses `session.Session.\
DownloadFile` (canonical, used by TAAC pcap path) to pull the just-saved
ixncfg from the server back to the netcastle worker for upload to Manifold;
the Tier 2 load path uses `UploadFile` to stage the downloaded blob server-
side, then `LoadConfig`. Tier 2 sidesteps the chassis-persistence problem
because Manifold is the durable store and the chassis-side file only needs
to live for one `LoadConfig` call.
"""

from __future__ import annotations

import re
import tempfile
import time
from pathlib import Path

from ixia.ixia import types as ixia_types
from ixnetwork_restpy.files import Files
from taac.ixia.taac_ixia import TaacIxia
from taac.utils.oss_taac_constants import TAAC_OSS
from taac.utils.oss_taac_lib_utils import (
    ConsoleFileLogger,
    none_throws,
)
from taac.test_as_a_config import types as taac_types

# NOTE: `manifold_utils` is imported lazily inside `try_load_from_manifold` /
# `save_to_manifold` to keep this OSS-safe `libs/` module free of any
# top-level `internal/` dependency. Per `taac_oss_privacy_rules`, OSS-safe
# files MUST NOT import from `internal/` at module level — otherwise the
# OSS build's Buck dep resolution fails even when callers never invoke the
# Manifold tier. See the lazy-import pattern in `test_setup_orchestrator.py`
# and the `if TAAC_OSS: return` guards in both Tier 2 methods below.


# Chars allowed in sanitized key fragments. Dots are NOT allowed — they get
# replaced with `_` (hostnames like `ixia11.ash6` become `ixia11_ash6`). The
# `.ixncfg` suffix is appended verbatim AFTER sanitization, not preserved
# through it.
_SAFE_KEY_RE = re.compile(r"[^A-Za-z0-9_-]")

# Cache version: bump when Python topology-generation logic changes in a way
# that would affect the saved `.ixncfg` (e.g. new DG/peer/prefix wiring in
# `create_basic_setup`, change in port-config builder, etc.). Bumping
# invalidates ALL existing cached ixncfg files across all testbeds — they'll be
# re-created on the next cold run.
#
# v2 (2026-06-05): dropped IxiaConfig content from the hash. The built
# IxiaConfig embeds runtime chassis-queried state (e.g. logical port numbers
# resolved via `async_get_ixia_logical_port`) that varies run-to-run even for
# an identical TestConfig — observed on bag012.ash6 cold→warm where two
# back-to-back runs of the same TestConfig produced different hashes
# (7ca5ecc43fa6 vs adc161447418), causing warm cache to never hit. Cache is
# now keyed purely by (test_config_name, chassis_id, _CACHE_VERSION), which
# is stable per testbed. The trade-off: cache will NOT auto-invalidate when a
# TestConfig's declarative content (port map, BGP peers) changes — the
# engineer must bump _CACHE_VERSION manually. A follow-up should hash a
# canonical subset of the SOURCE TestConfig (basic_port_configs etc.) to get
# the best of both: stable per run, auto-invalidating per declarative drift.
_CACHE_VERSION = "v2"


def _sanitize(s: str) -> str:
    """Replace any non-alphanumeric/dash/underscore char with `_`."""
    return _SAFE_KEY_RE.sub("_", s)


def compute_cache_key(
    test_config_name: str,
    chassis_id: str,
    ixia_config: ixia_types.IxiaConfig,  # accepted for API back-compat, NOT hashed
) -> str:
    """Stable cache key for a `(test_config_name, chassis_id, _CACHE_VERSION)` triple.

    `ixia_config` is accepted for API back-compat with v1 callers but is NOT
    included in the key — see the docstring on `_CACHE_VERSION` for why.
    """
    # Suppress unused-arg warning while keeping the back-compat signature.
    _ = ixia_config
    return (
        f"{_sanitize(test_config_name)}__"
        f"{_sanitize(chassis_id)}__{_CACHE_VERSION}.ixncfg"
    )


class IxiaConfigCacheManager:
    """3-tier cache manager (Tier 1 chassis-local; Tier 2 Manifold deferred).

    Usage:
        mgr = IxiaConfigCacheManager(ixia, cache_config, logger)
        key = mgr.compute_key(test_config_name, ixia_config)
        if mgr.try_load_from_chassis(key):
            ...skip create_basic_setup, go straight to start_and_verify_protocols
        else:
            ...run create_basic_setup
            mgr.save_to_chassis(key)  # warm cache for next run
    """

    def __init__(
        self,
        ixia: TaacIxia,
        cache_config: taac_types.IxiaConfigCache,
        logger: ConsoleFileLogger,
    ) -> None:
        self._ixia = ixia
        self._cfg = cache_config
        self._logger = logger

    def compute_key(
        self,
        test_config_name: str,
        ixia_config: ixia_types.IxiaConfig,
    ) -> str:
        """Compute cache key including chassis identity (from self._ixia).

        `primary_chassis_ip` is typed as Optional, but at this point in the
        runner flow the IXIA session is established so it must be set; fail
        fast via none_throws if it isn't.
        """
        return compute_cache_key(
            test_config_name,
            none_throws(self._ixia.primary_chassis_ip),
            ixia_config,
        )

    def chassis_path(self, key: str) -> str:
        """Full path of the cache file on the IxNetwork API server."""
        return f"{self._cfg.chassis_local_dir.rstrip('/')}/{key}"

    def try_load_from_chassis(self, key: str) -> bool:
        """Tier 1: try LoadConfig from chassis-local path.

        Delegates to TaacIxia.load_config_from_chassis which already handles
        exceptions, returns bool, and calls start_and_verify_protocols on success.
        Returns True on hit (caller skips create_basic_setup), False on miss.
        """
        path = self.chassis_path(key)
        self._logger.info(f"ixia cache: Tier 1 lookup — trying {path}")
        t0 = time.monotonic()
        loaded = self._ixia.load_config_from_chassis(path)
        elapsed = time.monotonic() - t0
        if loaded:
            self._logger.info(
                f"ixia cache: Tier 1 HIT — loaded in {elapsed:.1f}s "
                f"(would have been ~226s+ via create_basic_setup)"
            )
        else:
            self._logger.info(f"ixia cache: Tier 1 miss after {elapsed:.1f}s")
        return loaded

    def save_to_chassis(self, key: str) -> None:
        """Save current session state to chassis-local cache for next run.

        Delegates to TaacIxia.save_config_to_chassis which handles exceptions
        and returns bool. NEVER raises — cache warming is best-effort.
        """
        path = self.chassis_path(key)
        self._logger.info(f"ixia cache: warming Tier 1 — {path}")
        ok = self._ixia.save_config_to_chassis(path)
        if ok:
            self._logger.info(f"ixia cache: Tier 1 warmed at {path}")
        else:
            self._logger.error(
                "ixia cache: Tier 1 warm-up FAILED. Next run pays cold cost again."
            )

    def manifold_key(self, key: str) -> str:
        """Manifold object key for the same cache key used by Tier 1.

        Stored under `flat/` namespace (no enumeration, fast access).
        """
        return f"flat/{key}"

    async def try_load_from_manifold(self, key: str) -> bool:
        """Tier 2: download blob from Manifold → UploadFile to chassis → LoadConfig.

        Sidesteps the Tier 1 chassis-persistence problem: we always push fresh
        from Manifold, so the chassis-side file only needs to live for the
        duration of one `LoadConfig` call. `Manifold` is the durable backing
        store; the chassis file is a transient staging area.

        Returns True on full success (config loaded + protocols verified),
        False on miss/failure (caller falls through to Tier 3 cold setup).
        Best-effort: never raises. In OSS mode Manifold is unavailable;
        callers fall through to cold setup.
        """
        if TAAC_OSS:
            return False
        bucket = self._cfg.manifold_bucket
        if not bucket:
            return False
        # Lazy import — keeps the OSS build free of an `internal/` Buck dep
        # at module-load time. See top-of-file note.
        from taac.internal.utils.manifold_utils import (
            async_download_file_from_manifold,
        )

        mf_key = self.manifold_key(key)
        self._logger.info(f"ixia cache: Tier 2 lookup — Manifold {bucket}/{mf_key}")
        t0 = time.monotonic()
        # Use a tmp file path under the netcastle worker's /tmp. We delete the
        # pre-created NamedTemporaryFile and let async_download create it
        # fresh — avoids a "destination exists" race.
        with tempfile.NamedTemporaryFile(suffix=".ixncfg", delete=False) as f:
            local_path = Path(f.name)
        local_path.unlink(missing_ok=True)
        try:
            found = await async_download_file_from_manifold(bucket, mf_key, local_path)
            if not found:
                self._logger.info(
                    f"ixia cache: Tier 2 miss after {time.monotonic() - t0:.1f}s"
                )
                return False
            size = local_path.stat().st_size
            self._logger.info(
                f"ixia cache: Tier 2 downloaded {size} bytes; uploading to chassis"
            )
            # Stage on chassis under a stable basename (the cache key itself).
            # Each upload overwrites — fine, IxNetwork can re-import on top.
            self._ixia.session.Session.UploadFile(str(local_path), remote_filename=key)
            # LoadConfig against the just-uploaded basename. IxNetwork resolves
            # the basename in its default storage location server-side.
            self._ixia.session.Ixnetwork.LoadConfig(Files(key, local_file=False))
            # Re-bind vports to physical chassis ports — LoadConfig restores
            # vport `location` attrs but doesn't re-acquire the hardware
            # ports. Without this, `start_and_verify_protocols` raises
            # `BadRequestError: No ports assigned to the Port Group`. True =
            # clear ownership first to handle any stale grabs from prior
            # sessions. Same fix as `taac_ixia.load_config_from_chassis`.
            self._ixia.session.Ixnetwork.AssignPorts(True)
            self._ixia.start_and_verify_protocols()
            elapsed = time.monotonic() - t0
            self._logger.info(
                f"ixia cache: Tier 2 HIT — loaded from Manifold in {elapsed:.1f}s "
                f"(would have been ~226s+ via create_basic_setup)"
            )
            return True
        except Exception as e:
            elapsed = time.monotonic() - t0
            self._logger.info(
                f"ixia cache: Tier 2 load attempt failed after {elapsed:.1f}s "
                f"({type(e).__name__}: {e!r}). Falling through to Tier 3."
            )
            return False
        finally:
            local_path.unlink(missing_ok=True)

    async def save_to_manifold(self, key: str) -> None:
        """Tier 2 warm: SaveConfig server-side → DownloadFile → upload to Manifold.

        Best-effort: any failure is logged and swallowed so cache warm-up never
        breaks a passing test. The next cold run will re-attempt. No-op in OSS.
        """
        if TAAC_OSS:
            return
        bucket = self._cfg.manifold_bucket
        if not bucket:
            return
        # Lazy import — keeps the OSS build free of an `internal/` Buck dep
        # at module-load time. See top-of-file note.
        from taac.internal.utils.manifold_utils import (
            async_upload_file_to_manifold,
        )

        mf_key = self.manifold_key(key)
        self._logger.info(f"ixia cache: warming Tier 2 — Manifold {bucket}/{mf_key}")
        with tempfile.NamedTemporaryFile(suffix=".ixncfg", delete=False) as f:
            local_path = Path(f.name)
        local_path.unlink(missing_ok=True)
        try:
            # Save server-side with the cache key as the basename. Pairs with
            # the LoadConfig(Files(key, local_file=False)) in try_load above.
            self._ixia.session.Ixnetwork.SaveConfig(Files(key, local_file=False))
            # Pull the just-saved file back to the client. `DownloadFile` is
            # the canonical session-level API (TAAC pcap path uses it
            # successfully — see `ixia.py:7507`).
            self._ixia.session.Session.DownloadFile(
                remote_filename=key, local_filename=str(local_path)
            )
            if not local_path.exists() or local_path.stat().st_size == 0:
                self._logger.error(
                    "ixia cache: Tier 2 warm-up FAILED — DownloadFile produced "
                    f"empty/missing local file at {local_path}"
                )
                return
            size = local_path.stat().st_size
            url = await async_upload_file_to_manifold(bucket, mf_key, local_path)
            self._logger.info(f"ixia cache: Tier 2 warmed — {size} bytes -> {url}")
        except Exception as e:
            self._logger.error(
                f"ixia cache: Tier 2 warm-up FAILED ({type(e).__name__}: {e!r}). "
                "Next run pays cold cost again."
            )
        finally:
            local_path.unlink(missing_ok=True)
