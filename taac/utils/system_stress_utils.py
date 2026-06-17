# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import asyncio
import time
import typing as t

from taac.internal.ods_utils import async_query_ods
from taac.utils.driver_factory import async_get_device_driver
from taac.utils.oss_taac_lib_utils import (
    ConsoleFileLogger,
    get_root_logger,
)


LOGGER: ConsoleFileLogger = get_root_logger()


def _parse_memory_value(mem_str: str) -> int:
    """
    Parse memory value from string format to KB.

    Handles formats like:
    - "288236" (KB)
    - "3.3g" (GB)
    - "1.5m" (MB)

    Args:
        mem_str: Memory value as string

    Returns:
        Memory value in KB

    Note:
        Inlined here in Phase 5.0f to break the `utils/` -> `tasks/` cross-layer
        import. The original definition still lives in `tasks/periodic_tasks.py`
        for callers within that module; this is a small enough function (one
        regex-free string parse) that duplication is preferable to introducing
        a third "memory_utils" module just to host one symbol.
    """
    mem_str = mem_str.strip().lower()

    if mem_str.endswith("g"):
        # Convert GB to KB
        return int(float(mem_str[:-1]) * 1024 * 1024)
    elif mem_str.endswith("m"):
        # Convert MB to KB
        return int(float(mem_str[:-1]) * 1024)
    else:
        # Already in KB
        return int(mem_str)


async def async_get_memory_current_pct(
    hostname: str,
    slice: str,
    start_time: int,
    end_time: int,
    pct: t.Optional[int] = None,
) -> float:
    key_desc = f"cgroup.slice.{slice}.memory.current"
    result = await async_query_ods(
        entity_desc=hostname,
        key_desc=key_desc,
        transform_desc=f"pct({pct})" if pct else "",
        start_time=start_time,
        end_time=end_time,
    )
    LOGGER.debug(result)
    return float(list(result[hostname][key_desc].values())[-1])


async def async_collect_peak_cpu_memory(
    hostname: str,
    process_name: str,
    duration_seconds: int,
    interval_seconds: int = 30,
    steady_mem: bool = False,
) -> t.Dict[str, float]:
    """
    Collect CPU and memory samples for a process and return peak values.

    Uses driver's async_get_processes_top() method to collect samples at regular intervals.
    Useful for monitoring resource usage during test iterations.

    Args:
        hostname: Device hostname
        process_name: Process name to monitor (e.g., "bgpd_main")
        duration_seconds: Duration to monitor in seconds
        interval_seconds: Sampling interval in seconds (default: 30s)

    Returns:
        Dict containing:
        - peak_cpu_percent: Peak CPU usage percentage
        - peak_memory_mb: Peak memory usage in megabytes

    Example:
        >>> peak_stats = await async_collect_peak_cpu_memory(
        ...     hostname="rsw1aa.p001.f01.frc3",
        ...     process_name="bgpd_main",
        ...     duration_seconds=600,
        ...     interval_seconds=30
        ... )
        >>> print(f"Peak CPU: {peak_stats['peak_cpu_percent']:.2f}%")
        >>> print(f"Peak Memory: {peak_stats['peak_memory_mb']:.2f}MB")
    """
    driver = await async_get_device_driver(hostname)

    max_cpu = 0.0
    max_memory_mb = 0.0
    sample_count = 0
    start_time = time.time()
    memory_record = []
    steady_memory = 0.0

    LOGGER.info(
        f"Starting CPU/memory monitoring for {process_name} on {hostname} "
        f"(duration={duration_seconds}s, interval={interval_seconds}s)"
    )

    while (time.time() - start_time) < duration_seconds:
        sample_count += 1

        try:
            # Use existing driver method - same as ProcessMonitorTask
            output = await driver.async_get_processes_top()
            processes = output.get("processes", {})

            # Find the target process and get its metrics
            for _pid, process_data in processes.items():
                cmd = process_data.get("cmd", "")
                if process_name in cmd:
                    cpu_pct = float(process_data.get("cpuPct", 0))
                    resident_mem_str = str(process_data.get("residentMem", "0"))

                    # Parse memory using existing utility function
                    # _parse_memory_value returns KB, convert to MB
                    memory_kb = _parse_memory_value(resident_mem_str)
                    memory_mb = memory_kb / 1024.0
                    if steady_mem:
                        memory_record.append(memory_mb)

                    # Track peaks
                    max_cpu = max(max_cpu, cpu_pct)
                    max_memory_mb = max(max_memory_mb, memory_mb)

                    LOGGER.info(
                        f"Sample {sample_count}: {process_name} - "
                        f"CPU={cpu_pct:.2f}%, Memory={memory_mb:.2f}MB"
                    )
                    break

        except Exception as e:
            LOGGER.warning(
                f"Failed to collect sample {sample_count} for {process_name}: {str(e)}"
            )

        # Sleep until next sample
        elapsed = time.time() - start_time
        if elapsed < duration_seconds:
            sleep_time = min(interval_seconds, duration_seconds - elapsed)
            await asyncio.sleep(sleep_time)

    LOGGER.info(
        f"Monitoring completed for {process_name} on {hostname} - "
        f"Peak CPU: {max_cpu:.2f}%, Peak Memory: {max_memory_mb:.2f}MB"
    )
    if steady_mem:
        last_20_percent_mem = len(memory_record) - int(0.2 * len(memory_record))
        steady_memory = sum(memory_record[last_20_percent_mem:]) / (
            len(memory_record) - last_20_percent_mem
        )
        LOGGER.info(f"Steady State Memory: {steady_memory:.2f}MB")

    return {
        "peak_cpu_percent": max_cpu,
        "peak_memory_mb": max_memory_mb,
        "steady_memory_mb": steady_memory,
    }


async def async_get_current_memory_mb(
    hostname: str,
    process_name: str,
) -> float:
    """
    Get current memory usage for a process in MB.

    Quick snapshot (no monitoring period) - useful for checking memory at a specific point in time.

    Args:
        hostname: Device hostname
        process_name: Process name to check (e.g., "bgpd_main")

    Returns:
        float: Current memory usage in MB, or 0.0 if process not found

    Example:
        >>> memory_mb = await async_get_current_memory_mb(
        ...     hostname="eb03.lab.ash6",
        ...     process_name="bgpd_main"
        ... )
        >>> print(f"Current memory: {memory_mb:.2f} MB")
    """
    driver = await async_get_device_driver(hostname)

    try:
        output = await driver.async_get_processes_top()
        processes = output.get("processes", {})

        # Find the target process
        for _pid, process_data in processes.items():
            cmd = process_data.get("cmd", "")
            if process_name in cmd:
                resident_mem_str = str(process_data.get("residentMem", "0"))
                # Parse memory using existing utility (_parse_memory_value returns KB)
                memory_kb = _parse_memory_value(resident_mem_str)
                memory_mb = memory_kb / 1024.0
                return memory_mb

        LOGGER.warning(f"Process {process_name} not found on {hostname}")
        return 0.0

    except Exception as e:
        LOGGER.error(f"Failed to get memory for {process_name} on {hostname}: {str(e)}")
        return 0.0


async def async_get_current_cpu_and_memory(
    hostname: str,
    process_name: str,
) -> t.Dict[str, float]:
    """
    Get current CPU and memory usage for a process.

    Quick snapshot (no monitoring period) - useful for checking stable state.

    Args:
        hostname: Device hostname
        process_name: Process name to check (e.g., "bgpd_main")

    Returns:
        Dict with:
        - cpu_percent: Current CPU usage percentage
        - memory_mb: Current memory usage in MB
        Returns 0.0 for both if process not found

    Example:
        >>> stats = await async_get_current_cpu_and_memory(
        ...     hostname="eb03.lab.ash6",
        ...     process_name="bgpd_main"
        ... )
        >>> print(f"CPU: {stats['cpu_percent']:.2f}%, Memory: {stats['memory_mb']:.2f} MB")
    """
    driver = await async_get_device_driver(hostname)

    try:
        output = await driver.async_get_processes_top()
        processes = output.get("processes", {})

        # Find the target process
        for _pid, process_data in processes.items():
            cmd = process_data.get("cmd", "")
            if process_name in cmd:
                cpu_percent = float(process_data.get("cpuPct", 0))
                resident_mem_str = str(process_data.get("residentMem", "0"))
                # Parse memory using existing utility (_parse_memory_value returns KB)
                memory_kb = _parse_memory_value(resident_mem_str)
                memory_mb = memory_kb / 1024.0

                return {
                    "cpu_percent": cpu_percent,
                    "memory_mb": memory_mb,
                }

        LOGGER.warning(f"Process {process_name} not found on {hostname}")
        return {"cpu_percent": 0.0, "memory_mb": 0.0}

    except Exception as e:
        LOGGER.error(
            f"Failed to get CPU/memory for {process_name} on {hostname}: {str(e)}"
        )
        return {"cpu_percent": 0.0, "memory_mb": 0.0}


async def async_deploy_cpu_stress(
    hostname: str,
    n: int = 5000,
    duration_seconds: int = 3600,
) -> bool:
    """Deploy and launch a CPU stress script on the device via chunked base64."""
    import base64

    from taac.task_definitions import (
        CPU_STRESS_REMOTE_PATH,
        CPU_STRESS_SCRIPT,
    )
    from taac.utils.arista_utils import find_pid_in_output

    b64 = base64.b64encode(CPU_STRESS_SCRIPT.encode()).decode()
    driver = await async_get_device_driver(hostname)

    try:
        LOGGER.info("  Deploying CPU stress script...")
        chunk_size = 120
        chunks = [b64[i : i + chunk_size] for i in range(0, len(b64), chunk_size)]
        for i, chunk in enumerate(chunks):
            op = ">" if i == 0 else ">>"
            await driver.async_run_cmd_on_shell(
                f"bash echo '{chunk}' {op} /tmp/cpu_stress.b64"
            )
        await driver.async_run_cmd_on_shell(
            f"bash base64 -d /tmp/cpu_stress.b64 > {CPU_STRESS_REMOTE_PATH}"
        )
        await driver.async_run_cmd_on_shell("bash rm -f /tmp/cpu_stress.b64")

        LOGGER.info(f"  Launching: python3 cpu_stress.py {n} {duration_seconds}")
        launch_cmd = (
            f"bash sudo su\n"
            f"nohup python3 {CPU_STRESS_REMOTE_PATH} {n} {duration_seconds}"
            f" > /tmp/cpu_stress.log 2>&1 &\n"
            f"exit"
        )
        await driver.async_run_cmd_on_shell(launch_cmd)
        await asyncio.sleep(2)

        check = await driver.async_run_cmd_on_shell("bash pgrep -f cpu_stress.py")
        pid = find_pid_in_output(check)
        if pid:
            LOGGER.info(f"  CPU stress running (PID: {pid})")
            return True
        else:
            LOGGER.warning(
                f"  CPU stress not found after launch (pgrep output: {repr(check)})"
            )
            log_out = await driver.async_run_cmd_on_shell(
                "bash cat /tmp/cpu_stress.log"
            )
            if log_out and log_out.strip():
                LOGGER.warning(f"  cpu_stress.log: {log_out.strip()[:200]}")
            return False
    except Exception as e:
        LOGGER.warning(f"  Failed to deploy CPU stress: {e}")
        return False


async def async_cleanup_cpu_stress(hostname: str) -> None:
    """Kill the CPU stress script on the device."""
    from taac.task_definitions import CPU_STRESS_REMOTE_PATH

    try:
        driver = await async_get_device_driver(hostname)
        await driver.async_run_cmd_on_shell(
            f"bash sudo su\npkill -f {CPU_STRESS_REMOTE_PATH} || true\nexit"
        )
        await driver.async_run_cmd_on_shell(f"bash rm -f {CPU_STRESS_REMOTE_PATH}")
        LOGGER.info("  CPU stress cleaned up")
    except Exception as e:
        LOGGER.warning(f"  Failed to cleanup CPU stress: {e}")
