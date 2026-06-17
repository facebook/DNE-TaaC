# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe

"""Setup/teardown tasks for FPF ib_write_bw (RDMA) data-plane traffic.

FpfStartIbTrafficTask: SSHes to a server host and one or more client hosts,
    starts long-lived ``ib_write_bw`` (server first, then clients), confirms the
    processes are up, waits for traffic to settle, then validates via ODS that
    each host is cumulatively egressing above a threshold. Raises (failing the
    setup task, which aborts the test) with a clear per-host message if traffic
    is not flowing. On success the traffic is LEFT RUNNING for the rest of the
    test.

FpfStopIbTrafficTask: best-effort teardown that kills ib_write_bw on all hosts.

Egress validation (ODS), per host running traffic:
    entity    = the rtptest host(s) (comma-joined)
    key       = regex(system.beth[0123].tx-bytes-phy.rate)   (beth0-3 tx, B/s)
    transform = formula(/ $1 125000000),avg(60),latest        (B/s -> Gbps)
    reduce    = sum,groupbytag(entity, hostname)              (sum lanes / host)
Each hostname's resulting value must exceed ``min_egress_gbps`` (default 10),
i.e. >=10 Gbps cumulative egress across all lanes per host.

Usage in TestConfig:
    setup_tasks=[create_fpf_start_ib_traffic_task(server=..., clients=[...])],
    teardown_tasks=[create_fpf_stop_ib_traffic_task(server=..., clients=[...])],
"""

import asyncio
import re
import time
import typing as t

from taac.internal.driver.lab_ssh_transport import (
    async_exec as lab_ssh_async_exec,
    lab_ssh_transport_enabled,
    LabSshTransportError,
)
from taac.internal.ods_utils import (
    async_generate_ods_url,
    async_query_ods,
)
from taac.libs.fpf.fpf_collector_registry import register_artifact
from taac.tasks.base_task import BaseTask
from taac.utils.common import async_get_fburl
from taac.utils.oss_taac_lib_utils import get_root_logger

logger = get_root_logger()

IB_WRITE_BW_BIN = "/usr/bin/ib_write_bw"

# ib_write_bw defaults (match scripts/pavanpatil/fpf_host_signal_test.py).
DEFAULT_DEVICE = "mlx5_34"  # VF1 (planes 0-3); mlx5_35 is VF2 (planes 4-7)
DEFAULT_PORT = 15000
DEFAULT_MSG_SIZE = 4096
DEFAULT_QP = 4
DEFAULT_TCLASS = 224
DEFAULT_ITERS = 1000

# The RoCEv2 GID index (-x) is NOT hardcoded — it is discovered per host from
# `show_gids` by selecting the bveth interface's v2 global GID (the production
# VF prefix row). The 3rd whitespace field of that line is the index.
#   e.g. `show_gids | grep bveth0 | grep v2 | grep 2401`
#        -> "mlx5_34  1  3  2401:db00:...:0001  v2  bveth0"  => -x 3
DEFAULT_GID_IFACE = "bveth0"  # VF1->bveth0; VF2->bveth1
DEFAULT_GID_PREFIX = "2401"  # production VF GID prefix marker
_GID_INDEX_FIELD = 2  # 0-based: DEV PORT INDEX GID VER netdev

# ODS egress-validation defaults.
DEFAULT_KEY_DESC = "regex(system.beth[0123].tx-bytes-phy.rate)"
DEFAULT_TRANSFORM_DESC = "formula(/ $1 125000000),avg(1m),latest"
DEFAULT_REDUCE_DESC = "sum,groupbytag(entity, hostname)"
DEFAULT_MIN_EGRESS_GBPS = 10.0
DEFAULT_SETTLE_SEC = 120
DEFAULT_ODS_WINDOW_SEC = 120

_SERVER_LOG = "/tmp/ib_write_bw_server.log"
_CLIENT_LOG = "/tmp/ib_write_bw_client.log"

# Conservative allowlists to keep params out of the shell command grammar.
_HOSTNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_DEVICE_RE = re.compile(r"^[A-Za-z0-9_]+$")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_:.-]+$")


def _validate_hostname(host: str) -> str:
    if not isinstance(host, str) or not _HOSTNAME_RE.match(host):
        raise ValueError(f"Invalid/unsafe hostname for ib_write_bw task: {host!r}")
    return host


def _validate_device(device: str) -> str:
    if not isinstance(device, str) or not _DEVICE_RE.match(device):
        raise ValueError(f"Invalid/unsafe RDMA device for ib_write_bw task: {device!r}")
    return device


def _validate_token(value: str, what: str) -> str:
    if not isinstance(value, str) or not _TOKEN_RE.match(value):
        raise ValueError(f"Invalid/unsafe {what} for ib_write_bw task: {value!r}")
    return value


def build_show_gids_cmd(
    gid_iface: str = DEFAULT_GID_IFACE, gid_prefix: str = DEFAULT_GID_PREFIX
) -> str:
    """Build the show_gids probe command selecting the v2 global GID row."""
    _validate_token(gid_iface, "gid_iface")
    _validate_token(gid_prefix, "gid_prefix")
    return f"show_gids | grep {gid_iface} | grep v2 | grep {gid_prefix}"


def parse_gid_index(show_gids_output: str) -> int:
    """Parse the GID index (3rd field) from a `show_gids` filtered line.

    Example line: "mlx5_34  1  3  2401:db00:...:0001  v2  bveth0" -> 3.
    If multiple lines match, the last is used.
    """
    lines = [ln for ln in show_gids_output.splitlines() if ln.strip()]
    if not lines:
        raise ValueError("show_gids returned no matching GID row")
    fields = lines[-1].split()
    if len(fields) <= _GID_INDEX_FIELD:
        raise ValueError(f"unparseable show_gids line: {lines[-1]!r}")
    return int(fields[_GID_INDEX_FIELD])


def to_fqdn(host: str) -> str:
    """Ensure hostname has a .facebook.com suffix for SSH connection."""
    return host if host.endswith(".facebook.com") else f"{host}.facebook.com"


# These GPU/RTP lab hosts are reached as root via the caller's SSH cert/agent
# (Meta SSH CA), exactly like scripts/pavanpatil/fpf_host_signal_test.py. The
# asyncssh keyfile path (AsyncSSHClient) does NOT carry that cert and fails with
# "Permission denied for user root", so we shell out to the `ssh` CLI which
# does. BatchMode=yes keeps it non-interactive.
SSH_USER = "root"
_SSH_OPTS = [
    "-o",
    "StrictHostKeyChecking=no",
    "-o",
    "ConnectTimeout=10",
    "-o",
    "BatchMode=yes",
]


async def async_ssh_run(
    host: str, cmd: str, timeout_sec: int = 30
) -> t.Tuple[int, str, str]:
    """Run ``cmd`` on ``host`` as root. Returns (rc, out, err).

    Two modes (mirrors the FbossSwitch driver, but with the correct non-agent
    fallback for GPU/RTP hosts):
      * ``TAAC_SSH_VIA_LAB_SSH=1`` -> route through the lab-ssh daemon (CoreSSH,
        runs outside the agent sandbox). Required for AI-agent runs, where the
        sush2 gate blocks the in-process/CLI ssh below.
      * unset -> the ``ssh`` CLI (picks up the caller's Meta SSH-CA cert; the
        asyncssh keyfile path the driver falls back to does NOT carry that cert
        and fails as root on these GPU hosts — see the SSH_USER note above).

    Module-level (not a method) so it is an easy monkeypatch seam for tests.
    """
    _validate_hostname(host)
    if lab_ssh_transport_enabled():
        try:
            res = await lab_ssh_async_exec(
                host=to_fqdn(host),
                command=cmd,
                timeout_sec=timeout_sec,
                username=SSH_USER,
            )
        except LabSshTransportError as e:
            return (-1, "", f"lab-ssh transport error on {host}: {e}")
        rc = 124 if res.timed_out else res.exit_code
        return (rc, res.stdout, res.stderr)
    proc = await asyncio.create_subprocess_exec(
        "ssh",
        *_SSH_OPTS,
        f"{SSH_USER}@{to_fqdn(host)}",
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=timeout_sec)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        return (124, "", f"ssh timed out after {timeout_sec}s")
    rc = proc.returncode if proc.returncode is not None else -1
    return (rc, out_b.decode(errors="replace"), err_b.decode(errors="replace"))


def build_ib_write_bw_cmd(
    device: str = DEFAULT_DEVICE,
    gid_index: int = 3,
    port: int = DEFAULT_PORT,
    msg_size: int = DEFAULT_MSG_SIZE,
    qp: int = DEFAULT_QP,
    tclass: int = DEFAULT_TCLASS,
    iters: int = DEFAULT_ITERS,
    server: t.Optional[str] = None,
) -> str:
    """Build the ib_write_bw command. If ``server`` is set, it's a client cmd."""
    _validate_device(device)
    cmd = (
        f"{IB_WRITE_BW_BIN} -S 0 --report_gbits"
        f" -d {device} -m {int(msg_size)} -x {int(gid_index)} --qp {int(qp)}"
        f" -a -F --tclass {int(tclass)} -p {int(port)} --ipv6-addr -n {int(iters)}"
        f" -b --run_infinitely"
    )
    if server is not None:
        cmd += f" {_validate_hostname(server)}"
    return cmd


class FpfStartIbTrafficTask(BaseTask):
    NAME = "fpf_start_ib_traffic"

    async def _ssh_run(
        self, host: str, cmd: str, timeout_sec: int = 30
    ) -> t.Tuple[int, str, str]:
        return await async_ssh_run(host, cmd, timeout_sec=timeout_sec)

    async def _resolve_gid_index(
        self, host: str, gid_iface: str, gid_prefix: str
    ) -> int:
        """Discover the RoCEv2 GID index (-x) for ``host`` via show_gids."""
        probe = build_show_gids_cmd(gid_iface, gid_prefix)
        rc, out, err = await self._ssh_run(host, probe)
        if rc != 0 or not out.strip():
            raise Exception(
                f"[FpfStartIbTraffic] could not determine GID index on {host} via "
                f"`{probe}` (rc={rc}): {err.strip() or out.strip() or 'no output'}"
            )
        gid_index = parse_gid_index(out)
        logger.info(
            f"[FpfStartIbTraffic] {host}: GID index -x={gid_index} "
            f"(from {gid_iface}/v2/{gid_prefix})"
        )
        return gid_index

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        server = _validate_hostname(params["server"])
        clients = [_validate_hostname(c) for c in params["clients"]]
        if not clients:
            raise ValueError("fpf_start_ib_traffic requires at least one client host")
        device = _validate_device(params.get("device", DEFAULT_DEVICE))
        # GID index is discovered per host from show_gids unless explicitly set.
        gid_override = params.get("gid_index")
        gid_iface = _validate_token(
            params.get("gid_iface", DEFAULT_GID_IFACE), "gid_iface"
        )
        gid_prefix = _validate_token(
            params.get("gid_prefix", DEFAULT_GID_PREFIX), "gid_prefix"
        )
        port = int(params.get("port", DEFAULT_PORT))
        msg_size = int(params.get("msg_size", DEFAULT_MSG_SIZE))
        qp = int(params.get("qp", DEFAULT_QP))
        tclass = int(params.get("tclass", DEFAULT_TCLASS))
        iters = int(params.get("iters", DEFAULT_ITERS))
        settle_sec = int(params.get("settle_sec", DEFAULT_SETTLE_SEC))
        min_egress_gbps = float(params.get("min_egress_gbps", DEFAULT_MIN_EGRESS_GBPS))
        ods_window_sec = int(params.get("ods_window_sec", DEFAULT_ODS_WINDOW_SEC))
        key_desc = params.get("key_desc", DEFAULT_KEY_DESC)
        transform_desc = params.get("transform_desc", DEFAULT_TRANSFORM_DESC)
        reduce_desc = params.get("reduce_desc", DEFAULT_REDUCE_DESC)

        all_hosts = [server, *clients]
        gid_note = (
            f"gid=override({int(gid_override)})"
            if gid_override is not None
            else f"gid=show_gids({gid_iface}/v2/{gid_prefix})"
        )
        logger.info(
            f"[FpfStartIbTraffic] server={server} clients={clients} "
            f"device={device} {gid_note} port={port}; "
            f"settle={settle_sec}s, threshold={min_egress_gbps:.1f} Gbps/host"
        )

        async def _gid_for(host: str) -> int:
            if gid_override is not None:
                return int(gid_override)
            return await self._resolve_gid_index(host, gid_iface, gid_prefix)

        # Clean any stale ib_write_bw on every host first (best-effort).
        for host in all_hosts:
            await self._ssh_run(host, "pkill -f ib_write_bw 2>/dev/null || true")
        await asyncio.sleep(1)

        # Start server, then each client, in the background. The RoCEv2 GID
        # index (-x) is resolved per host (each host's own show_gids).
        server_gid = await _gid_for(server)
        server_cmd = build_ib_write_bw_cmd(
            device, server_gid, port, msg_size, qp, tclass, iters
        )
        server_full = f"setsid nohup {server_cmd} > {_SERVER_LOG} 2>&1 & echo $!"
        logger.info(f"[FpfStartIbTraffic] {server} SERVER cmd: {server_full}")
        rc, out, err = await self._ssh_run(server, server_full)
        if rc != 0:
            raise Exception(
                f"[FpfStartIbTraffic] failed to start server on {server} "
                f"(rc={rc}): {err.strip() or out.strip()}"
            )
        logger.info(f"[FpfStartIbTraffic] server started on {server} pid={out.strip()}")
        await asyncio.sleep(2)

        for host in clients:
            client_gid = await _gid_for(host)
            client_cmd = build_ib_write_bw_cmd(
                device, client_gid, port, msg_size, qp, tclass, iters, server=server
            )
            client_full = f"setsid nohup {client_cmd} > {_CLIENT_LOG} 2>&1 & echo $!"
            logger.info(f"[FpfStartIbTraffic] {host} CLIENT cmd: {client_full}")
            rc, out, err = await self._ssh_run(host, client_full)
            if rc != 0:
                raise Exception(
                    f"[FpfStartIbTraffic] failed to start client on {host} "
                    f"(rc={rc}): {err.strip() or out.strip()}"
                )
            logger.info(
                f"[FpfStartIbTraffic] client started on {host} pid={out.strip()}"
            )
            await asyncio.sleep(1)

        # Confirm the process is actually up on every host.
        await asyncio.sleep(2)
        not_running: t.List[str] = []
        for host in all_hosts:
            _, out, _ = await self._ssh_run(host, "pgrep -c ib_write_bw || echo 0")
            count = out.strip() or "0"
            logger.info(f"[FpfStartIbTraffic] {host}: {count} ib_write_bw process(es)")
            if count == "0":
                not_running.append(host)
        if not_running:
            raise Exception(
                "[FpfStartIbTraffic] ib_write_bw not running after start on: "
                + ", ".join(not_running)
                + f" (check {_SERVER_LOG}/{_CLIENT_LOG} on the hosts)"
            )

        # Let traffic ramp, then validate egress via ODS.
        logger.info(
            f"[FpfStartIbTraffic] waiting {settle_sec}s for traffic to settle "
            f"before ODS egress validation"
        )
        await asyncio.sleep(settle_sec)

        end_time = int(time.time())
        start_time = end_time - ods_window_sec
        entity_desc = ",".join(all_hosts)
        logger.info(
            f"[FpfStartIbTraffic] querying ODS egress for {entity_desc} "
            f"key={key_desc} window {start_time}->{end_time}"
        )
        ods_data = await async_query_ods(
            entity_desc=entity_desc,
            key_desc=key_desc,
            reduce_desc=reduce_desc,
            transform_desc=transform_desc,
            start_time=start_time,
            end_time=end_time,
        )
        ods_url = await async_generate_ods_url(
            entity_desc=entity_desc,
            key_desc=key_desc,
            reduce_desc=reduce_desc,
            transform_desc=transform_desc,
            start_time=start_time,
            end_time=end_time,
        )
        ods_url = await async_get_fburl(ods_url)
        register_artifact("ods", "ib_write_bw egress (setup)", ods_url)

        # Per-host latest egress in Gbps (entities are regrouped to hostname).
        egress_by_host: t.Dict[str, float] = {}
        for entity, key_data in (ods_data or {}).items():
            latest_val: t.Optional[float] = None
            latest_ts = -1
            for _key_name, ts_data in key_data.items():
                for ts, val in ts_data.items():
                    if ts > latest_ts:
                        latest_ts, latest_val = ts, val
            if latest_val is not None:
                egress_by_host[entity] = latest_val

        violations: t.List[str] = []
        pass_details: t.List[str] = []
        # Match each requested host against the grouped ODS entities. With
        # `groupbytag(entity, hostname)` ODS returns entities shaped like
        # "HOSTNAME::rtptest1555.mwg2:sum" (tag prefix + :reduce suffix), so we
        # match on the host's short label appearing anywhere in the entity.
        for host in all_hosts:
            short = host.split(".")[0]
            val = egress_by_host.get(host)
            if val is None:
                for ent, v in egress_by_host.items():
                    if host in ent or short in ent:
                        val = v
                        break
            if val is None:
                violations.append(f"{host}: no ODS egress data")
            elif val <= min_egress_gbps:
                violations.append(f"{host}: {val:.2f} Gbps <= {min_egress_gbps:.1f}")
            else:
                pass_details.append(f"{host}: {val:.2f} Gbps")

        for detail in pass_details:
            logger.info(f"[FpfStartIbTraffic] [PASS] {detail}")
        for v in violations:
            logger.info(f"[FpfStartIbTraffic] [FAIL] {v}")

        if violations:
            raise Exception(
                f"[FpfStartIbTraffic] egress below {min_egress_gbps:.1f} Gbps/host — "
                + "; ".join(violations)
                + (f" | OK: {'; '.join(pass_details)}" if pass_details else "")
                + f" | ODS: {ods_url}"
            )
        logger.info(
            f"[FpfStartIbTraffic] SUCCESS — all {len(all_hosts)} host(s) egressing "
            f">{min_egress_gbps:.1f} Gbps: {'; '.join(pass_details)} | ODS: {ods_url}"
        )


class FpfStopIbTrafficTask(BaseTask):
    NAME = "fpf_stop_ib_traffic"

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        server = _validate_hostname(params["server"])
        clients = [_validate_hostname(c) for c in params.get("clients", [])]
        all_hosts = [server, *clients]
        logger.info(f"[FpfStopIbTraffic] stopping ib_write_bw on {all_hosts}")
        for host in all_hosts:
            try:
                await async_ssh_run(
                    host, "pkill -f ib_write_bw 2>/dev/null || true", timeout_sec=30
                )
                logger.info(f"[FpfStopIbTraffic] stopped on {host}")
            except Exception as e:
                logger.error(f"[FpfStopIbTraffic] {host}: stop best-effort failed: {e}")
