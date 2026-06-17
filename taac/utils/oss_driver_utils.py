#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""
OSS-compatible SSH and reachability utilities for TAAC driver layer.

Replaces Meta-internal dependencies:
  - neteng.netcastle.utils.asyncssh_utils.AsyncSSHClient
  - neteng.netcastle.utils.paramiko_utils.ParamikoClient
  - neteng.netcastle.utils.reachability_utils.wait_for_ping_reachable
  - neteng.netcastle.utils.reachability_utils.wait_for_ssh_reachable
  - neteng.netcastle.utils.deploy_utils.create_dir_if_not_exists

External dependencies (PyPI):
  - asyncssh   (pip install asyncssh)
  - paramiko   (pip install paramiko)

All Meta-internal auth complexity (role certs, keychain secrets, basset
password lookup, justknobs gating) is replaced with standard key-based
SSH auth configured via environment variables:

  TAAC_SSH_KEY  — path to SSH private key (default: ~/.ssh/id_rsa)
  TAAC_SSH_USER — SSH username (default: root)
"""

import asyncio
import logging
import os
import shlex
import subprocess
import time
import typing as t
from types import TracebackType

logger = logging.getLogger(__name__)

_DEFAULT_CMD_TIMEOUT_SEC = 300
_DEFAULT_CONNECT_TIMEOUT_SEC = 30
_DEFAULT_SSH_PORT = 22


def _get_ssh_key_path() -> t.Optional[str]:
    key_path = os.environ.get("TAAC_SSH_KEY")
    if key_path and os.path.isfile(key_path):
        return key_path
    default = os.path.expanduser("~/.ssh/id_rsa")
    if os.path.isfile(default):
        return default
    return None


def _get_ssh_username(override: t.Optional[str] = None) -> str:
    if override:
        return override
    return os.environ.get("TAAC_SSH_USER", "root")


# =============================================================================
# AsyncSSHClient — OSS replacement using asyncssh
# =============================================================================


class AsyncSSHClient:
    """
    Async SSH client using asyncssh with standard key-based auth.

    API-compatible with the Meta-internal AsyncSSHClient for the methods
    used by FbossSwitch:
      - async context manager (__aenter__/__aexit__)
      - async_run(cmd, timeout_sec, print_stdout, block, return_on_msg)
        -> subprocess.CompletedProcess
      - async_exists_and_isfile(remote_path) -> bool

    Usage:
        async with AsyncSSHClient("switch1.example.com") as client:
            result = await client.async_run("show version")
            print(result.stdout)
    """

    def __init__(
        self,
        ssh_entity: t.Union[str, t.Any] = "",
        hostname: t.Optional[str] = None,
        port: int = _DEFAULT_SSH_PORT,
        username: t.Optional[str] = None,
        password: t.Optional[str] = None,
        password_list: t.Optional[t.List[str]] = None,
        force_connect: bool = False,
        timeout: int = _DEFAULT_CONNECT_TIMEOUT_SEC,
        **kwargs,
    ) -> None:
        if isinstance(ssh_entity, str) and ssh_entity:
            self._hostname = ssh_entity
        elif hostname:
            self._hostname = hostname
        else:
            self._hostname = str(ssh_entity)

        self._port = port
        self._username = _get_ssh_username(username)
        self._password = password
        self._password_list = password_list or []
        self._timeout = timeout
        self._conn = None

    async def __aenter__(self) -> "AsyncSSHClient":
        await self.async_connect()
        return self

    async def __aexit__(
        self,
        exc_type: t.Optional[t.Type[BaseException]],
        exc_val: t.Optional[BaseException],
        exc_tb: t.Optional[TracebackType],
    ) -> None:
        self.disconnect()

    async def async_connect(self) -> None:
        import asyncssh

        key_path = _get_ssh_key_path()
        connect_kwargs: t.Dict[str, t.Any] = {
            "host": self._hostname,
            "port": self._port,
            "username": self._username,
            "known_hosts": None,
            "login_timeout": self._timeout,
        }

        if key_path:
            connect_kwargs["client_keys"] = [key_path]

        passwords = []
        if self._password:
            passwords.append(self._password)
        passwords.extend(self._password_list)
        if passwords:
            connect_kwargs["password"] = passwords[0]

        self._conn = await asyncssh.connect(**connect_kwargs)

    def disconnect(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    async def async_get_connection(self):
        if not self._conn:
            await self.async_connect()
        return self._conn

    async def async_run(
        self,
        cmd: str,
        timeout_sec: int = _DEFAULT_CMD_TIMEOUT_SEC,
        print_stdout: bool = False,
        block: bool = True,
        return_on_msg: t.Optional[str] = None,
        **kwargs,
    ) -> subprocess.CompletedProcess:
        """
        Run a command on the remote host.

        Returns subprocess.CompletedProcess with .stdout, .stderr, .returncode
        to match the internal API contract.
        """
        if not self._conn:
            await self.async_connect()

        try:
            result = await asyncio.wait_for(
                # pyrefly: ignore [missing-attribute]
                self._conn.run(cmd, check=False),
                timeout=timeout_sec,
            )
        except asyncio.TimeoutError:
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=124,
                stdout="",
                stderr=f"Command timed out after {timeout_sec}s",
            )

        stdout = result.stdout or ""
        stderr = result.stderr or ""

        if print_stdout and stdout:
            logger.info(stdout)

        return subprocess.CompletedProcess(
            args=cmd,
            returncode=result.exit_status or 0,
            stdout=stdout,
            stderr=stderr,
        )

    async def async_exists_and_isfile(self, remote_path: str) -> bool:
        result = await self.async_run(f"test -f {shlex.quote(remote_path)}")
        return result.returncode == 0

    async def async_exists_and_isdir(self, remote_path: str) -> bool:
        result = await self.async_run(f"test -d {shlex.quote(remote_path)}")
        return result.returncode == 0


# =============================================================================
# ParamikoClient — OSS replacement using paramiko
# =============================================================================


class ParamikoClient:
    """
    Sync SSH client using paramiko with standard key-based auth.

    API-compatible with the Meta-internal ParamikoClient for the methods
    used by FbossSwitch:
      - ParamikoClient(hostname, port, username).run(cmd, ...)
        -> subprocess.CompletedProcess
      - .exists_and_isfile(remote_path) -> bool
      - .exists_and_isdir(remote_path) -> bool
      - .makedirs(directory) -> None
      - context manager support

    Usage:
        with ParamikoClient("switch1.example.com") as client:
            result = client.run("show version")
            print(result.stdout)
    """

    def __init__(
        self,
        ssh_entity: t.Union[str, t.Any] = "",
        hostname: t.Optional[str] = None,
        port: int = _DEFAULT_SSH_PORT,
        username: t.Optional[str] = None,
        password: t.Optional[str] = None,
        password_list: t.Optional[t.List[str]] = None,
        force_connect: bool = False,
        timeout: t.Optional[int] = None,
        **kwargs,
    ) -> None:
        if isinstance(ssh_entity, str) and ssh_entity:
            self._hostname = ssh_entity
        elif hostname:
            self._hostname = hostname
        else:
            self._hostname = str(ssh_entity)

        self._port = port
        self._username = _get_ssh_username(username)
        self._password = password
        self._password_list = password_list or []
        self._timeout = timeout or _DEFAULT_CONNECT_TIMEOUT_SEC
        self._client = None

    def __enter__(self) -> "ParamikoClient":
        self.connect()
        return self

    def __exit__(
        self,
        exc_type: t.Optional[t.Type[BaseException]],
        exc_val: t.Optional[BaseException],
        exc_tb: t.Optional[TracebackType],
    ) -> None:
        self.disconnect()

    def connect(self, num_tries: int = 3) -> "ParamikoClient":
        import paramiko

        self._client = paramiko.SSHClient()
        self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        key_path = _get_ssh_key_path()

        connect_kwargs: t.Dict[str, t.Any] = {
            "hostname": self._hostname,
            "port": self._port,
            "username": self._username,
            "timeout": self._timeout,
            "allow_agent": True,
            "look_for_keys": True,
        }

        if key_path:
            connect_kwargs["key_filename"] = key_path

        passwords = []
        if self._password:
            passwords.append(self._password)
        passwords.extend(self._password_list)
        if passwords:
            connect_kwargs["password"] = passwords[0]

        last_error = None
        for attempt in range(num_tries):
            try:
                self._client.connect(**connect_kwargs)
                return self
            except Exception as e:
                last_error = e
                if attempt < num_tries - 1:
                    time.sleep(2)

        raise ConnectionError(
            f"Failed to SSH to {self._hostname}:{self._port} after "
            f"{num_tries} attempts: {last_error}"
        ) from last_error

    def disconnect(self) -> None:
        if self._client:
            self._client.close()
            self._client = None

    def get_client(self):
        if not self._client:
            self.connect()
        return self._client

    def run(
        self,
        cmd: str,
        timeout_sec: int = _DEFAULT_CMD_TIMEOUT_SEC,
        print_stdout: bool = False,
        block: bool = True,
        return_on_msg: t.Optional[str] = None,
        **kwargs,
    ) -> subprocess.CompletedProcess:
        """
        Run a command on the remote host.

        Returns subprocess.CompletedProcess with .stdout, .stderr, .returncode.
        """
        if not self._client:
            self.connect()

        try:
            # pyrefly: ignore [missing-attribute]
            _, stdout_channel, stderr_channel = self._client.exec_command(
                cmd, timeout=timeout_sec
            )
        except Exception as e:
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=1,
                stdout="",
                stderr=str(e),
            )

        if not block:
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout="", stderr=""
            )

        stdout_data = ""
        stderr_data = ""
        try:
            if return_on_msg:
                chunks = []
                for line in stdout_channel:
                    chunks.append(line)
                    if print_stdout:
                        logger.info(line.rstrip("\n"))
                    if return_on_msg in line:
                        break
                stdout_data = "".join(chunks)
            else:
                stdout_data = stdout_channel.read().decode("utf-8", errors="replace")
                if print_stdout and stdout_data:
                    logger.info(stdout_data)

            stderr_data = stderr_channel.read().decode("utf-8", errors="replace")
            returncode = stdout_channel.channel.recv_exit_status()
        except Exception as e:
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=1,
                stdout=stdout_data,
                stderr=f"{stderr_data}\n{str(e)}",
            )

        return subprocess.CompletedProcess(
            args=cmd,
            returncode=returncode,
            stdout=stdout_data,
            stderr=stderr_data,
        )

    def exists_and_isfile(self, remote_path: str) -> bool:
        result = self.run(f"test -f {shlex.quote(remote_path)}")
        return result.returncode == 0

    def exists_and_isdir(self, remote_path: str) -> bool:
        result = self.run(f"test -d {shlex.quote(remote_path)}")
        return result.returncode == 0

    def makedirs(self, directory: str) -> None:
        self.run(f"mkdir -p {shlex.quote(directory)}")


# =============================================================================
# Reachability utilities
# =============================================================================


def is_host_ping_reachable(
    hostname: str,
    use_ipv6: bool = True,
    ping_logger: t.Optional[logging.Logger] = None,
) -> bool:
    """
    Check if a host responds to ICMP ping.

    Returns True if host is reachable, False otherwise.
    """
    ping_logger = ping_logger or logger
    cmd = ["ping", "-i", "0.5", "-c", "5", "-w", "10", hostname]
    if use_ipv6:
        cmd.append("-6")
    ping_logger.debug(f"Running {' '.join(cmd)}")
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )
        return proc.returncode == 0
    except subprocess.TimeoutExpired:
        return False


def wait_for_ping_reachable(
    ssh_entity: t.Union[str, t.Any],
    num_tries: int = 120,
    sleep_time: int = 5,
    max_duration: int = 600,
) -> bool:
    """
    Wait until a host becomes ping-reachable.

    Polls with retry until the host responds to ping or the timeout is exceeded.

    Args:
        ssh_entity: hostname string (or object with str() conversion)
        num_tries: maximum number of ping attempts
        sleep_time: seconds between attempts
        max_duration: maximum total wall-clock time in seconds

    Returns:
        True if host became reachable

    Raises:
        TimeoutError: if host is not reachable after all attempts
    """
    hostname = str(ssh_entity)
    start_time = time.monotonic()
    attempts = 0

    while attempts < num_tries:
        if is_host_ping_reachable(hostname):
            logger.info(f"{hostname} is ping-reachable after {attempts + 1} attempts")
            return True

        attempts += 1
        elapsed = time.monotonic() - start_time
        if elapsed >= max_duration:
            break
        if attempts < num_tries:
            time.sleep(sleep_time)

    raise TimeoutError(
        f"{hostname} not ping-reachable after {attempts} attempts "
        f"({time.monotonic() - start_time:.0f}s elapsed)"
    )


def is_host_ssh_reachable(
    hostname: str,
    port: int = _DEFAULT_SSH_PORT,
    username: t.Optional[str] = None,
    password: t.Optional[str] = None,
    timeout: int = _DEFAULT_CONNECT_TIMEOUT_SEC,
) -> bool:
    """
    Check if a host is SSH-reachable by attempting a connection and running /bin/true.
    """
    try:
        client = ParamikoClient(
            hostname,
            port=port,
            username=username,
            password=password,
            timeout=timeout,
        )
        client.connect(num_tries=2)
        client.run("/bin/true")
        client.disconnect()
        return True
    except Exception:
        return False


def wait_for_ssh_reachable(
    ssh_entity: t.Union[str, t.Any],
    num_tries: int = 120,
    sleep_time: int = 5,
    max_duration: int = 600,
    port: int = _DEFAULT_SSH_PORT,
    password: t.Optional[str] = None,
    password_list: t.Optional[t.List[str]] = None,
) -> bool:
    """
    Wait until a host becomes SSH-reachable.

    Polls with retry until SSH connection succeeds or timeout is exceeded.

    Args:
        ssh_entity: hostname string (or object with str() conversion)
        num_tries: maximum number of SSH attempts
        sleep_time: seconds between attempts
        max_duration: maximum total wall-clock time in seconds
        port: SSH port
        password: optional SSH password

    Returns:
        True if host became SSH-reachable

    Raises:
        TimeoutError: if host is not SSH-reachable after all attempts
    """
    hostname = str(ssh_entity)
    start_time = time.monotonic()
    attempts = 0

    pw = password
    if not pw and password_list:
        pw = password_list[0]

    while attempts < num_tries:
        if is_host_ssh_reachable(hostname, port=port, password=pw):
            logger.info(f"{hostname} is SSH-reachable after {attempts + 1} attempts")
            return True

        attempts += 1
        elapsed = time.monotonic() - start_time
        if elapsed >= max_duration:
            break
        if attempts < num_tries:
            time.sleep(sleep_time)

    raise TimeoutError(
        f"{hostname} not SSH-reachable after {attempts} attempts "
        f"({time.monotonic() - start_time:.0f}s elapsed)"
    )


# =============================================================================
# File system utilities
# =============================================================================


def create_dir_if_not_exists(
    ssh_entity: t.Union[str, t.Any],
    dest_path: str,
) -> None:
    """
    Create a directory on a remote host if it doesn't already exist.

    Uses SSH to run `mkdir -p` on the remote host.
    """
    hostname = str(ssh_entity)
    with ParamikoClient(hostname) as client:
        if not client.exists_and_isdir(dest_path):
            client.makedirs(directory=dest_path)
