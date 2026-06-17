# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-strict

import typing as t

from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.health_check.health_check import types as hc_types


class FileExistsHealthCheck(AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]):
    """Health check to verify if a file exists on a device."""

    CHECK_NAME: hc_types.CheckName = hc_types.CheckName.FILE_EXISTS_HEALTH_CHECK
    OPERATING_SYSTEMS: t.List[str] = [
        "EOS",
        "FBOSS",
    ]

    async def _check_file_exists(
        self,
        hostname: str,
        file_path: str,
        ls_command: str,
        expect_exists: bool,
    ) -> hc_types.HealthCheckResult:
        """
        Common logic for checking file existence across OS types.

        Args:
            hostname: Device hostname
            file_path: Path to the file to check
            ls_command: The ls command to use (OS-specific)
            expect_exists: Whether the file is expected to exist

        Returns:
            HealthCheckResult indicating whether the file exists as expected
        """
        try:
            # pyrefly: ignore [missing-attribute]
            file_check = await self.driver.async_execute_show_or_configure_cmd_on_shell(
                ls_command
            )

            file_exists = file_check and "No such file" not in file_check

            if file_exists and expect_exists:
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.PASS,
                    message=f"File exists as expected on {hostname}: {file_path}",
                )
            elif not file_exists and not expect_exists:
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.PASS,
                    message=f"File does not exist as expected on {hostname}: {file_path}",
                )
            elif file_exists and not expect_exists:
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.FAIL,
                    message=f"File exists on {hostname} but was not expected: {file_path}",
                )
            else:  # not file_exists and expect_exists
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.FAIL,
                    message=f"File not found on {hostname}: {file_path}",
                )

        except Exception as e:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.ERROR,
                message=f"Error checking file existence on {hostname}: {e}",
            )

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        """
        Default implementation (should not be called due to OS-specific methods).
        """
        raise NotImplementedError(
            "OS-specific method (_run_fboss or _run_arista) should be called"
        )

    async def _run_fboss(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        """
        FBOSS implementation for file existence check.

        Args:
            check_params: Dictionary containing:
                - file_path: Path to the file to check (required)
                - expect_exists: Whether the file is expected to exist (default: True)

        Returns:
            HealthCheckResult indicating whether the file exists as expected
        """
        hostname = obj.name
        file_path = check_params.get("file_path")

        if not file_path:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.ERROR,
                message="file_path parameter is required for FileExistsHealthCheck",
            )

        expect_exists = check_params.get("expect_exists", True)

        # On FBOSS, use ls directly
        check_cmd = f'ls -la "{file_path}"'
        return await self._check_file_exists(
            hostname, file_path, check_cmd, expect_exists
        )

    async def _run_arista(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        """
        Arista EOS implementation for file existence check.

        Args:
            check_params: Dictionary containing:
                - file_path: Path to the file to check (required)
                - expect_exists: Whether the file is expected to exist (default: True)

        Returns:
            HealthCheckResult indicating whether the file exists as expected
        """
        hostname = obj.name
        file_path = check_params.get("file_path")

        if not file_path:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.ERROR,
                message="file_path parameter is required for FileExistsHealthCheck",
            )

        expect_exists = check_params.get("expect_exists", True)

        # On EOS, use bash ls
        check_cmd = f'bash ls -la "{file_path}"'
        return await self._check_file_exists(
            hostname, file_path, check_cmd, expect_exists
        )
