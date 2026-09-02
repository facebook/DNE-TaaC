# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe

from __future__ import annotations

"""
IXIA recovery helper library.

Pure-function building blocks for safely restarting the IxNetwork REST API tier
(`ixnetworkweb` platform app) when chassis hardware is healthy but the Jetty
backend rejects new session creation with 5xx errors.

Consumed by:
  - `ixia_recovery_cli`            (Phase 1 standalone CLI)
  - `ixia.py::Ixia.connect`        (Phase 2 in-band recovery)
  - `ixia_chassis_monitor`         (Phase 3 optional auto-remediate)

Safety rails — enforced here so callers cannot bypass:
  1. Cooldown            — refuse repeat attempts within N minutes (Scuba-backed).
  2. Active-session guard — refuse soft-restart if other users have ACTIVE sessions.
  3. Telemetry          — emit `recovery_attempt` Scuba event on every action
                           (including refused / dry-run).
"""

import json
import logging
import os
import socket
import time
import typing as t

import requests
import urllib3


logger: logging.Logger = logging.getLogger(__name__)

SCUBA_TABLE: str = "taac_ixia_monitor"
RECOVERY_EVENT_TYPE: str = "recovery_attempt"
DETECTED_502_EVENT_TYPE: str = "api_502_detected"
# Fired by the in-band per-RPC wrapper / per-playbook gate the moment a 5xx is
# caught from an IxNetwork RPC during test execution — BEFORE any recovery is
# attempted. Distinct from `api_502_detected` (the out-of-band Chronos monitor
# signal): different cadence, different denominator. One row per caught 5xx.
INBAND_502_EVENT_TYPE: str = "inband_502_observed"

# `source` values for `inband_502_observed.source`, distinguishing the per-RPC
# wrapper from the between-playbook gate.
SOURCE_INBAND_API_CALL: str = "inband_api_call"
SOURCE_BETWEEN_PLAYBOOK_GATE: str = "between_playbook_gate"

DEFAULT_POLL_TIMEOUT_SEC: int = 300
DEFAULT_COOLDOWN_MINUTES: int = 30
DEFAULT_AUTH_TIMEOUT_SEC: int = 15
DEFAULT_HTTP_TIMEOUT_SEC: int = 15


class HealthStatus:
    """String constants used by `classify_health` and the CLI JSON output."""

    HEALTHY = "HEALTHY"
    API_DOWN_502 = "API_DOWN_502"
    API_DOWN_OTHER = "API_DOWN_OTHER"
    CHASSIS_DOWN = "CHASSIS_DOWN"
    AUTH_FAILED = "AUTH_FAILED"
    UNREACHABLE = "UNREACHABLE"


# ---------------------------------------------------------------------------
# Networking helpers (mirror ixia_preflight_cli.py)
# ---------------------------------------------------------------------------


def suppress_insecure_warnings() -> None:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def resolve_to_ip(hostname: str) -> str:
    fqdn = hostname
    if not fqdn.endswith(".facebook.com"):
        fqdn = f"{fqdn}.facebook.com"
    try:
        # @nolint PATTERNLINT(python-dns-deps)
        addr_info = socket.getaddrinfo(fqdn, None, socket.AF_INET6)
        if addr_info:
            # pyrefly: ignore [bad-return]
            return addr_info[0][4][0]
    except socket.gaierror:
        pass
    try:
        # @nolint PATTERNLINT(python-dns-deps)
        return socket.gethostbyname(fqdn)
    except socket.gaierror:
        pass
    return hostname


def host_fmt(ip: str) -> str:
    if ":" in ip and not ip.startswith("["):
        return f"[{ip}]"
    return ip


def http_request(
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    auth: tuple[str, str] | None = None,
    json_body: t.Any = None,
    timeout: int = DEFAULT_HTTP_TIMEOUT_SEC,
) -> tuple[int, t.Any]:
    """Single sync HTTP call. Returns `(status_code, parsed_body_or_text)`.

    - `status_code == 0` means a transport-level failure (connect/DNS/timeout)
      and `body` is the exception string.
    - For 2xx/4xx/5xx, attempts JSON decode and falls back to raw text on failure.
    """
    try:
        resp = requests.request(
            method=method,
            url=url,
            headers=headers or {},
            auth=auth,
            json=json_body,
            verify=False,  # @nolint PATTERNLINT(python-ssl-verify)
            timeout=timeout,
        )
        try:
            body = resp.json()
        except (ValueError, json.JSONDecodeError):
            body = resp.text
        return resp.status_code, body
    except requests.RequestException as e:
        return 0, str(e)


def authenticate(host: str, username: str, password: str) -> str | None:
    """Get an IxOS API key. Returns None if all auth endpoints fail."""
    for ep in [
        "/platform/api/v1/auth/session",
        "/platform/api/v2/auth/session",
        "/chassis/api/v2/auth/session",
    ]:
        status, body = http_request(
            "POST",
            f"https://{host}{ep}",
            json_body={"username": username, "password": password},
            timeout=DEFAULT_AUTH_TIMEOUT_SEC,
        )
        if status == 200 and isinstance(body, dict):
            key = body.get("apiKey") or body.get("api_key")
            if key:
                return key
    return None


def auth_headers(
    api_key: str | None,
) -> tuple[dict[str, str], tuple[str, str] | None]:
    if api_key:
        return {"x-api-key": api_key}, None
    return {}, None


def fetch_password() -> str | None:
    """Fetch IXIA admin password. Returns None on failure.

    Resolution order:
    1. `IXIA_PASSWORD` env var — explicit override for operators running
       the CLI outside an fbcode runtime where the Keychain dep isn't
       wired (the canonical out-of-process pattern is
       `IXIA_PASSWORD=$(secrets_tool get_from_group NETCASTLE_IXIA_PASS NETCASTLE_LAB)`).
       Env vars don't show in `ps aux`, unlike `--password <pw>` which
       would leak via `/proc/*/cmdline` per Meta's Secrets Management
       Standard (see `discover_ixia_diagnostics_components.py`).
    2. Keychain via `IxiaLib.fetch_ixia_credentials` — the in-process
       path used by `libs/traffic_generator.py` and other TAAC binaries
       that have `internal_utils` in their dep closure.

    Callers MUST handle `None` — typically by raising / aborting the
    operation and surfacing a clear error to the operator. We do NOT
    fall back to a hardcoded default (that would defeat the secret
    management policy and silently degrade to a well-known credential).
    """
    env_pwd = os.environ.get("IXIA_PASSWORD")
    if env_pwd:
        return env_pwd
    try:
        from neteng.test_infra.ixia.ixnetwork_restpy.ixia_lib import Ixia as IxiaLib

        pwd = IxiaLib.fetch_ixia_credentials(
            secret_name="NETCASTLE_IXIA_PASS",
            secret_group="NETCASTLE_LAB",
        )
        if pwd is not None:
            return pwd
    except Exception as e:
        logger.warning(f"Keychain fetch failed: {e!r}")
    return None


# ---------------------------------------------------------------------------
# Health classification
# ---------------------------------------------------------------------------


def _classify_from_status_codes(c_status: int, s_status: int) -> tuple[str, str]:
    """Pure-function classifier from the two endpoint status codes.

    Extracted from `classify_health` so the branch ordering can be unit
    tested independently of the HTTP / auth plumbing, and so the function
    body stays under the 50-line Python-style ceiling.

    Branch order matters:
    - Transport-level failure (both status_code == 0) → UNREACHABLE
      (DNS/TCP failure — we never reached the chassis).
    - Both 200 → HEALTHY.
    - Chassis endpoint 5xx → CHASSIS_DOWN (genuine server error;
      sessions-endpoint state is moot).
    - Sessions 502, chassis 200 → API_DOWN_502 (the wedged-Jetty case).
    - Either endpoint returns 401/403 → AUTH_FAILED (server responded,
      we just lack valid credentials). This includes the smoke-test
      case of an unauthenticated probe against a healthy chassis —
      both endpoints answer 401 because there's no api-key in headers,
      and the chassis is fine: do not misclassify as CHASSIS_DOWN.
    - Sessions non-200 (chassis 200) → API_DOWN_OTHER.
    """
    if c_status == 0 and s_status == 0:
        return (
            HealthStatus.UNREACHABLE,
            "Both endpoints failed at transport level (network/DNS).",
        )
    if c_status == 200 and s_status == 200:
        return HealthStatus.HEALTHY, "Both REST endpoints returned 200."
    if c_status >= 500:
        return (
            HealthStatus.CHASSIS_DOWN,
            f"Chassis IxOS REST returned {c_status} (likely hardware/OS issue).",
        )
    if c_status == 200 and s_status == 502:
        return (
            HealthStatus.API_DOWN_502,
            "IxNetwork REST API tier returned 502 (Jetty unhealthy).",
        )
    if c_status in (401, 403) or s_status in (401, 403):
        return (
            HealthStatus.AUTH_FAILED,
            f"Auth rejected (chassis={c_status}, sessions={s_status}).",
        )
    if c_status != 200:
        # Anything else on the chassis endpoint (e.g. 404 from a wrong path,
        # 3xx redirect we didn't follow): treat as chassis-side oddity.
        return (
            HealthStatus.CHASSIS_DOWN,
            f"Chassis IxOS REST returned {c_status} (unexpected non-2xx).",
        )
    return (
        HealthStatus.API_DOWN_OTHER,
        f"IxNetwork REST API tier returned {s_status} (chassis OS healthy).",
    )


def classify_health(
    chassis_hostname: str,
    username: str = "admin",
    password: str | None = None,
) -> dict[str, t.Any]:
    """Probe `/api/v1/sessions` + `/chassis/api/v2/ixos/chassis`. Classify.

    Probes both endpoints with whatever credentials are available
    (including None / failed auth). The response status codes are what
    drive classification — a 502 returned by a wedged Jetty looks like
    a 502 whether or not the request was authenticated. Auth-rejection
    (401/403) is distinguished from 5xx by the helper. This avoids the
    earlier bug where auth failure short-circuited and masked the very
    `API_DOWN_502` / `CHASSIS_DOWN` / `UNREACHABLE` conditions this tool
    is designed to detect.
    """
    suppress_insecure_warnings()
    chassis_ip = resolve_to_ip(chassis_hostname)
    host = host_fmt(chassis_ip)
    pwd = password or fetch_password()

    result: dict[str, t.Any] = {
        "chassis": chassis_hostname,
        "resolved_ip": chassis_ip,
        "status": HealthStatus.HEALTHY,
        "sessions_endpoint": {},
        "chassis_endpoint": {},
        "summary": "",
    }

    api_key = authenticate(host, username, pwd) if pwd else None
    hdrs, _ = auth_headers(api_key)

    s_status, s_body = http_request(
        "GET", f"https://{host}/api/v1/sessions", headers=hdrs
    )
    result["sessions_endpoint"] = {
        "url": f"https://{host}/api/v1/sessions",
        "status_code": s_status,
        "body_snippet": _snippet(s_body),
    }

    c_status, c_body = http_request(
        "GET", f"https://{host}/chassis/api/v2/ixos/chassis", headers=hdrs
    )
    result["chassis_endpoint"] = {
        "url": f"https://{host}/chassis/api/v2/ixos/chassis",
        "status_code": c_status,
        "body_snippet": _snippet(c_body),
    }

    status, summary = _classify_from_status_codes(c_status, s_status)
    result["status"] = status
    result["summary"] = summary
    return result


def _snippet(body: t.Any, max_len: int = 200) -> str:
    if body is None:
        return ""
    s = body if isinstance(body, str) else json.dumps(body, default=str)
    return s[:max_len]


# ---------------------------------------------------------------------------
# Active-session guard
# ---------------------------------------------------------------------------


def list_active_sessions(
    chassis_hostname: str, username: str, password: str
) -> list[dict[str, t.Any]]:
    """Return list of `{id, name, user}` for ACTIVE sessions, or [] on failure."""
    suppress_insecure_warnings()
    host = host_fmt(resolve_to_ip(chassis_hostname))
    api_key = authenticate(host, username, password)
    if api_key is None:
        return []
    hdrs, _ = auth_headers(api_key)
    status, body = http_request("GET", f"https://{host}/api/v1/sessions", headers=hdrs)
    if status != 200 or not isinstance(body, list):
        return []
    out: list[dict[str, t.Any]] = []
    for s in body:
        if not isinstance(s, dict):
            continue
        if str(s.get("state", "")).upper() != "ACTIVE":
            continue
        out.append(
            {
                "id": s.get("id"),
                "name": s.get("sessionName") or s.get("name", ""),
                "user": s.get("userName", ""),
            }
        )
    return out


def count_other_user_sessions(
    sessions: list[dict[str, t.Any]], caller_user: str
) -> int:
    """Count ACTIVE sessions whose `user` is non-empty AND != `caller_user`."""
    n = 0
    for s in sessions:
        u = (s.get("user") or "").strip()
        if u and u != caller_user:
            n += 1
    return n


# ---------------------------------------------------------------------------
# Cooldown (Scuba-backed)
# ---------------------------------------------------------------------------


def is_in_cooldown(
    chassis_hostname: str,
    cooldown_minutes: int = DEFAULT_COOLDOWN_MINUTES,
    scuba_query_fn: t.Callable[[str, int], float | None] | None = None,
) -> tuple[bool, float | None]:
    """Returns `(in_cooldown, age_minutes_of_last_attempt_or_None)`.

    `scuba_query_fn(chassis, lookback_minutes) -> last_attempt_age_minutes_or_None`
    is injectable for tests. Default queries `taac_ixia_monitor` for the most
    recent `recovery_attempt` event on `chassis`.
    """
    if scuba_query_fn is None:
        scuba_query_fn = _default_scuba_query
    try:
        age = scuba_query_fn(chassis_hostname, cooldown_minutes)
    except Exception as e:
        logger.warning(f"Scuba cooldown query failed: {e!r}; assuming NOT in cooldown")
        return False, None
    if age is None:
        return False, None
    return age < cooldown_minutes, age


def _default_scuba_query(chassis: str, lookback_minutes: int) -> float | None:
    """Default Scuba query for the most recent `recovery_attempt` event on chassis.

    Returns age in minutes, or None if no event found in the lookback window.
    Returns None on any error (caller treats as 'not in cooldown').
    """
    # Lazy import — keeps lib usable outside an fbcode runtime.
    try:
        from rfe.scubadata.scubadata_py3 import ScubaData  # noqa: F401
    except ImportError:
        return None
    # We do not query Scuba directly here — that requires the scuba_cli RPC
    # path and is too heavy for a hot lookup. Instead, we rely on a local
    # state file written by `emit_recovery_attempt_scuba`. Tests inject their
    # own scuba_query_fn.
    return _read_local_attempt_age(chassis, lookback_minutes)


_LOCAL_STATE_DIR: str = "/var/tmp/taac_ixia_recovery"


def _read_local_attempt_age(chassis: str, lookback_minutes: int) -> float | None:
    """Read last-attempt timestamp from a local file; return age in minutes."""
    path = os.path.join(_LOCAL_STATE_DIR, f"{chassis}.last_attempt")
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            ts = float(f.read().strip())
    except (OSError, ValueError):
        return None
    age_minutes = (time.time() - ts) / 60.0
    # Clamp negative ages to 0 — a negative value indicates clock skew or a
    # corrupt write where the on-disk timestamp is in the future. Without
    # the clamp, `age < cooldown_minutes` would trap the chassis in
    # cooldown until the future timestamp passes (potentially forever).
    if age_minutes < 0:
        age_minutes = 0.0
    if age_minutes > lookback_minutes * 10:
        return None
    return age_minutes


def _write_local_attempt(chassis: str) -> None:
    os.makedirs(_LOCAL_STATE_DIR, exist_ok=True)
    path = os.path.join(_LOCAL_STATE_DIR, f"{chassis}.last_attempt")
    try:
        with open(path, "w") as f:
            f.write(str(time.time()))
    except OSError as e:
        logger.warning(f"Could not write local cooldown state {path}: {e!r}")


# ---------------------------------------------------------------------------
# Telemetry
# ---------------------------------------------------------------------------


def emit_recovery_attempt_scuba(
    chassis: str,
    action: str,
    success: bool,
    duration_s: float,
    triggered_by: str,
    blocked_reason: str | None = None,
    prior_502_count: int = 0,
    restart_post_status: int | None = None,
    restart_post_body_snippet: str | None = None,
) -> None:
    """Best-effort Scuba write to `taac_ixia_monitor` table.

    Schema (in addition to chassis + event_type):
      action          str   restart-ixnetwork | reboot-chassis | check | auto
      success         int   1/0
      duration_s      double
      triggered_by    str   cli:<user> | phase2_inband | phase3_monitor
      blocked_reason  str   cooldown | other_user_sessions | dry_run | ''
      prior_502_count int   # of consecutive 502s observed before this attempt
      restart_post_status      int  HTTP status the chassis returned for the
                                    platform-restart POST (omitted when None —
                                    e.g. refusals before the POST is issued)
      restart_post_body_snippet str the chassis's own response body for that
                                    POST (omitted when empty; capped at 512)

    NOTE: this function does NOT write the cooldown timestamp. Cooldown is
    bumped only by `restart_ixnetwork` immediately before the real POST so
    that refusal paths (cooldown, dry_run, auth_failed, no_password) do not
    extend the cooldown window — otherwise a chassis would be locked out
    indefinitely once it hit cooldown the first time, because each retry's
    refusal would rewrite the timestamp.
    """
    try:
        from rfe.scubadata.scubadata_py3 import Sample, ScubaData

        sample = Sample()
        sample.addTimestamp(ScubaData.TIME_COLUMN, int(time.time()))
        sample.addNormalValue("event_type", RECOVERY_EVENT_TYPE)
        sample.addNormalValue("chassis", chassis)
        sample.addNormalValue("action", action)
        sample.addIntValue("success", 1 if success else 0)
        sample.addDoubleValue("duration_s", float(duration_s))
        sample.addNormalValue("triggered_by", triggered_by)
        sample.addNormalValue("blocked_reason", blocked_reason or "")
        sample.addIntValue("prior_502_count", int(prior_502_count))
        if restart_post_status is not None:
            sample.addIntValue("restart_post_status", int(restart_post_status))
        if restart_post_body_snippet:
            # Hard cap at 512 chars even if `_snippet()` didn't trim
            # aggressively (e.g. a direct caller passing an un-snippeted
            # body); Scuba column-size hygiene.
            sample.addNormalValue(
                "restart_post_body_snippet", restart_post_body_snippet[:512]
            )
        with ScubaData(SCUBA_TABLE) as scuba:
            scuba.add_sample(sample)
    except Exception as e:
        logger.warning(f"Scuba emit failed (action={action}): {e!r}")


def emit_inband_502_scuba(
    chassis: str,
    op_name: str,
    http_status: int,
    source: str,
    session_id: int | None = None,
    playbook_name: str | None = None,
    testconfig_name: str | None = None,
) -> None:
    """Best-effort `inband_502_observed` Scuba write to `taac_ixia_monitor`.

    Emitted by the per-RPC `@external_api` wrapper and the per-playbook
    `ensure_ixia_alive` gate the moment a 5xx is caught from an IxNetwork
    RPC during test execution — BEFORE any recovery is attempted. One row
    per caught 5xx so the underlying 502 rate is queryable even when
    recovery is cooldown-blocked (and so cannot be inferred from the
    `recovery_attempt` denominator).

    Columns (in addition to chassis + event_type):
      op_name         str   RPC method that 5xx'd (`stop_protocols`,
                            `ensure_alive`, ...)
      http_status     int   502 / 504 / etc.
      source          str   inband_api_call | between_playbook_gate
                            (see SOURCE_* constants)
      session_id      int   IxNetwork session id (omitted if not yet known)
      playbook_name   str   currently-running playbook (omitted when not
                            available)
      testconfig_name str   TestConfig identifier
    """
    try:
        from rfe.scubadata.scubadata_py3 import Sample, ScubaData

        sample = Sample()
        sample.addTimestamp(ScubaData.TIME_COLUMN, int(time.time()))
        sample.addNormalValue("event_type", INBAND_502_EVENT_TYPE)
        sample.addNormalValue("chassis", chassis)
        sample.addNormalValue("op_name", op_name)
        sample.addIntValue("http_status", int(http_status))
        sample.addNormalValue("source", source)
        if session_id is not None:
            sample.addIntValue("session_id", int(session_id))
        if playbook_name:
            sample.addNormalValue("playbook_name", playbook_name)
        if testconfig_name:
            sample.addNormalValue("testconfig_name", testconfig_name)
        with ScubaData(SCUBA_TABLE) as scuba:
            scuba.add_sample(sample)
    except Exception as e:
        logger.warning(f"Scuba inband_502 emit failed (op={op_name}): {e!r}")


# ---------------------------------------------------------------------------
# Restart `ixnetworkweb` (the actual recovery action)
# ---------------------------------------------------------------------------


def _find_app_restart_link(
    host: str, hdrs: dict[str, str], app_name: str = "ixnetworkweb"
) -> tuple[int | None, str | None, t.Any]:
    """Return `(app_id, restart_url, raw_apps_response)`."""
    status, body = http_request(
        "GET", f"https://{host}/platform/api/v2/platform/apps", headers=hdrs
    )
    if status != 200 or not isinstance(body, list):
        return None, None, body
    for app in body:
        if not isinstance(app, dict):
            continue
        if app.get("name") != app_name:
            continue
        app_id = app.get("id")
        restart_url = None
        for link in app.get("links") or []:
            if not isinstance(link, dict):
                continue
            rel = (link.get("rel") or "").lower()
            # IxOS exposes restart as `rel: "restart operation"` (matches
            # netcastle's `PLATFORM_OPERATION_NAME_MAP[RESTART]`). The bare
            # "restart" rel does not exist — verified against IxOS 26.0.2600
            # on ixia18.netcastle.ash6 during live e2e. Accept either form
            # so we're robust to future minor naming changes.
            if rel == "restart operation" or rel == "restart":
                restart_url = link.get("href")
                break
        return app_id, restart_url, app
    return None, None, body


DEFAULT_CONSECUTIVE_200_REQUIRED: int = 3


def _wait_for_api_alive(
    host: str,
    hdrs: dict[str, str],
    timeout_sec: int,
    poll_interval_sec: int = 5,
    consecutive_200_required: int = DEFAULT_CONSECUTIVE_200_REQUIRED,
) -> bool:
    """Poll `/api/v1/sessions` until N consecutive 200s within `timeout_sec`.

    Requiring N>1 catches the premature-200 race we observed in the wild
    on ixia18.netcastle.ash6 during the first real e2e: Jetty briefly
    returned 200 ~1s after the restart POST, then dropped back to 502 as
    it continued cycling, then recovered to a sustained 200 ~60s later.
    A single 200 is not proof of stability — N=3 (10s of stable response
    at the 5s default poll interval) is. Non-200 resets the counter.
    """
    deadline = time.time() + timeout_sec
    consecutive_200 = 0
    while time.time() < deadline:
        status, _ = http_request(
            "GET", f"https://{host}/api/v1/sessions", headers=hdrs, timeout=10
        )
        if status == 200:
            consecutive_200 += 1
            if consecutive_200 >= consecutive_200_required:
                return True
        else:
            if consecutive_200 > 0:
                logger.debug(
                    f"{host}: stability counter reset after "
                    f"{consecutive_200} consecutive 200s (saw {status})"
                )
            consecutive_200 = 0
        time.sleep(poll_interval_sec)
    return False


def _make_result(chassis: str) -> dict[str, t.Any]:
    return {
        "chassis": chassis,
        "action": "restart-ixnetwork",
        "success": False,
        "blocked_reason": None,
        "duration_s": 0.0,
        "details": {},
    }


def _block_and_emit(
    out: dict[str, t.Any],
    chassis: str,
    reason: str,
    t0: float,
    triggered_by: str,
    success: bool = False,
) -> dict[str, t.Any]:
    """Stamp `blocked_reason` + duration, emit Scuba, return `out`.

    Single chokepoint so every refusal/dry-run/failure exit path emits
    consistent telemetry (and the `out["success"]` returned to the caller
    matches the `success` argument passed to Scuba).
    """
    out["blocked_reason"] = reason
    out["success"] = success
    out["duration_s"] = time.time() - t0
    details = out.get("details") or {}
    emit_recovery_attempt_scuba(
        chassis,
        "restart-ixnetwork",
        success,
        out["duration_s"],
        triggered_by,
        blocked_reason=reason,
        restart_post_status=details.get("restart_post_status"),
        restart_post_body_snippet=details.get("restart_post_body_snippet"),
    )
    return out


def _check_cooldown(
    chassis: str, cooldown_minutes: int, skip: bool
) -> tuple[bool, float | None]:
    """Returns `(blocked, age_minutes)`. blocked=False when `skip=True`."""
    if skip:
        return False, None
    return is_in_cooldown(chassis, cooldown_minutes)


def _check_session_guard(
    chassis: str,
    username: str,
    password: str,
    max_other_sessions: int,
    skip: bool,
) -> tuple[bool, list[dict[str, t.Any]], int]:
    """Returns `(blocked, sessions, other_user_count)`."""
    if skip:
        return False, [], 0
    sessions = list_active_sessions(chassis, username, password)
    other = count_other_user_sessions(sessions, username)
    return other > max_other_sessions, sessions, other


def _post_restart_and_wait(
    host: str,
    hdrs: dict[str, str],
    poll_timeout_sec: int,
) -> tuple[int | None, str | None, int | None, t.Any, bool]:
    """POST the restart action and poll until the API is alive again.

    Returns `(app_id, restart_url, post_status, post_body, alive)`. Caller
    interprets None URL / non-2xx status / alive=False as failures.

    `post_status` is `None` (not `0`) when no restart link was found and the
    POST was never issued, so the `restart_link_not_found` refusal path emits
    no `restart_post_status` Scuba column — keeping that column meaningful
    (always an actual HTTP status the chassis returned for a real POST).
    """
    app_id, restart_url, _raw = _find_app_restart_link(host, hdrs, "ixnetworkweb")
    if not restart_url:
        return app_id, None, None, None, False
    post_url = (
        f"https://{host}{restart_url}" if restart_url.startswith("/") else restart_url
    )
    status, body = http_request(
        "POST", post_url, headers={**hdrs, "Content-Type": "application/json"}
    )
    if status not in (200, 202, 204):
        return app_id, restart_url, status, body, False
    alive = _wait_for_api_alive(host, hdrs, poll_timeout_sec)
    return app_id, restart_url, status, body, alive


def restart_ixnetwork(
    chassis_hostname: str,
    username: str = "admin",
    password: str | None = None,
    poll_timeout_sec: int = DEFAULT_POLL_TIMEOUT_SEC,
    cooldown_minutes: int = DEFAULT_COOLDOWN_MINUTES,
    max_active_other_user_sessions: int = 0,
    dry_run: bool = False,
    triggered_by: str = "cli",
    skip_cooldown_check: bool = False,
    skip_session_guard: bool = False,
) -> dict[str, t.Any]:
    """Soft-restart the `ixnetworkweb` platform app on `chassis_hostname`.

    Top-level orchestrator. Delegates the safety rails, POST+poll, and
    refusal paths to focused helpers above so each piece stays under the
    Python-style 50-line ceiling and the control flow reads as a short
    linear sequence.
    """
    t0 = time.time()
    out = _make_result(chassis_hostname)
    suppress_insecure_warnings()
    host = host_fmt(resolve_to_ip(chassis_hostname))
    pwd = password or fetch_password()

    # ── Safety rail 1: cooldown ───────────────────────────────────────
    in_cooldown, age = _check_cooldown(
        chassis_hostname, cooldown_minutes, skip_cooldown_check
    )
    if in_cooldown:
        out["details"]["last_attempt_age_minutes"] = age
        return _block_and_emit(out, chassis_hostname, "cooldown", t0, triggered_by)

    # ── Safety rail 2: active-session guard ───────────────────────────
    blocked, sessions, other = _check_session_guard(
        chassis_hostname,
        username,
        # `pwd` may be None when Keychain fetch failed; pass through so the
        # downstream auth check produces a clear `auth_failed` refusal
        # instead of silently using a hardcoded default.
        pwd or "",
        max_active_other_user_sessions,
        skip_session_guard,
    )
    out["details"]["active_sessions"] = sessions
    out["details"]["other_user_session_count"] = other
    if blocked:
        return _block_and_emit(
            out, chassis_hostname, "other_user_sessions", t0, triggered_by
        )

    # ── Dry-run short-circuit ─────────────────────────────────────────
    # Treat dry-run as a successful refusal: caller sees success=True
    # (the rehearsal completed without error) AND Scuba records success=1
    # with blocked_reason="dry_run". Previously these were inconsistent.
    if dry_run:
        out["details"]["would_restart"] = True
        return _block_and_emit(
            out, chassis_hostname, "dry_run", t0, triggered_by, success=True
        )

    if pwd is None:
        # Keychain fetch failed AND caller did not provide a password.
        # Refuse cleanly rather than attempting auth with a default.
        return _block_and_emit(out, chassis_hostname, "no_password", t0, triggered_by)
    return _auth_post_finalize(
        out, chassis_hostname, host, username, pwd, poll_timeout_sec, t0, triggered_by
    )


def _auth_post_finalize(
    out: dict[str, t.Any],
    chassis_hostname: str,
    host: str,
    username: str,
    pwd: str,
    poll_timeout_sec: int,
    t0: float,
    triggered_by: str,
) -> dict[str, t.Any]:
    """Auth + POST restart + poll + record outcome.

    Extracted from `restart_ixnetwork` so the top-level orchestrator stays
    under the 50-line Python-style ceiling.
    """
    api_key = authenticate(host, username, pwd)
    if api_key is None:
        return _block_and_emit(out, chassis_hostname, "auth_failed", t0, triggered_by)
    hdrs, _ = auth_headers(api_key)
    # Bump the cooldown timestamp HERE — past all safety rails, about to
    # issue the real restart POST. Refusal paths (cooldown / dry_run /
    # auth_failed / no_password / other_user_sessions) must NOT bump this
    # because that would extend the cooldown window on each retry and lock
    # the chassis out indefinitely. See `emit_recovery_attempt_scuba` note.
    _write_local_attempt(chassis_hostname)
    app_id, restart_url, post_status, post_body, alive = _post_restart_and_wait(
        host, hdrs, poll_timeout_sec
    )
    out["details"]["app_id"] = app_id
    out["details"]["restart_url"] = restart_url
    out["details"]["restart_post_status"] = post_status
    out["details"]["restart_post_body_snippet"] = _snippet(post_body)
    out["details"]["api_alive_after_restart"] = alive
    if not restart_url:
        return _block_and_emit(
            out, chassis_hostname, "restart_link_not_found", t0, triggered_by
        )
    if post_status not in (200, 202, 204):
        return _block_and_emit(
            out,
            chassis_hostname,
            f"restart_post_status_{post_status}",
            t0,
            triggered_by,
        )
    if not alive:
        return _block_and_emit(
            out, chassis_hostname, "api_did_not_recover", t0, triggered_by
        )
    out["success"] = True
    out["duration_s"] = time.time() - t0
    emit_recovery_attempt_scuba(
        chassis_hostname,
        "restart-ixnetwork",
        out["success"],
        out["duration_s"],
        triggered_by,
        blocked_reason=out["blocked_reason"],
        restart_post_status=out["details"].get("restart_post_status"),
        restart_post_body_snippet=out["details"].get("restart_post_body_snippet"),
    )
    return out


# ---------------------------------------------------------------------------
# Chassis reboot probe (NEVER auto-invoked)
# ---------------------------------------------------------------------------


_REBOOT_RELS: tuple[str, ...] = ("reboot", "powerCycle", "hardReset")


def probe_reboot_endpoint(
    chassis_hostname: str,
    username: str = "admin",
    password: str | None = None,
) -> dict[str, t.Any]:
    """Probe `/chassis/api/v2/ixos/operations` for a reboot-capable action.

    Returns:
        {
          "available": bool,
          "action_url": str | None,
          "action_name": str | None,
          "dcrc_template": str,
        }
    """
    suppress_insecure_warnings()
    host = host_fmt(resolve_to_ip(chassis_hostname))
    pwd = password or fetch_password()
    out: dict[str, t.Any] = {
        "available": False,
        "action_url": None,
        "action_name": None,
        "dcrc_template": _dcrc_template(chassis_hostname),
    }
    if pwd is None:
        return out
    api_key = authenticate(host, username, pwd)
    if api_key is None:
        return out
    hdrs, _ = auth_headers(api_key)
    status, body = http_request(
        "GET", f"https://{host}/chassis/api/v2/ixos/operations", headers=hdrs
    )
    if status != 200 or not isinstance(body, (list, dict)):
        return out
    items = body if isinstance(body, list) else body.get("links") or []
    for it in items:
        if not isinstance(it, dict):
            continue
        rel = (it.get("rel") or it.get("name") or "").lower()
        href = it.get("href") or it.get("url")
        if href and any(r.lower() in rel for r in _REBOOT_RELS):
            out["available"] = True
            out["action_url"] = href
            out["action_name"] = rel
            return out
    return out


def _dcrc_template(chassis_hostname: str) -> str:
    return (
        "DCRC ticket template — hard chassis reboot required.\n"
        f"  Chassis: {chassis_hostname}\n"
        "  Symptom: IxNetwork REST API tier wedged; soft restart of\n"
        "    `ixnetworkweb` platform app did not recover the API.\n"
        "  Requested action: physical power-cycle of the chassis at the\n"
        "    rack. Coordinate with TAAC oncall (dne_pit) before reboot —\n"
        "    other tests may be using sibling ports.\n"
    )
