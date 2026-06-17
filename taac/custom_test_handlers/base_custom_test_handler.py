# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import typing as t

from taac.constants import TestTopology
from taac.utils.oss_taac_lib_utils import ConsoleFileLogger


class BaseCustomTestHandler:
    # only run this handler if the test config has any of the following tags
    SUPPORTED_TAGS: t.List[str] = []

    def __init__(
        self,
        test_topology: TestTopology,
        logger: ConsoleFileLogger,
    ) -> None:
        self.test_topology = test_topology
        self.logger = logger

    async def setUp(self) -> None:
        pass

    async def async_test_setUp(self) -> None:
        pass

    async def _async_test_setUp(self) -> None:
        self.logger.debug(
            f"Running async_test_setUp logic for {self.__class__.__name__}"
        )
        try:
            await self.async_test_setUp()
        except Exception as e:
            self.logger.error(f"Failed to run async_test_setUp: {e}")
            raise e

    async def async_test_tearDown(self) -> None:
        pass

    async def _async_test_tearDown(self) -> None:
        self.logger.debug(
            f"Running async_test_tearDown logic for {self.__class__.__name__}"
        )
        try:
            await self.async_test_tearDown()
        except Exception as e:
            self.logger.error(f"Failed to run async_test_tearDown: {e}")
            raise e

    async def async_test_case_setUp(self) -> None:
        pass

    async def _async_test_case_setUp(self) -> None:
        self.logger.debug(
            f"Running async_test_case_setUp logic for {self.__class__.__name__}"
        )
        try:
            await self.async_test_case_setUp()
        except Exception as e:
            self.logger.error(f"Failed to run async_test_case_setUp: {e}")
            raise e

    async def async_test_case_tearDown(
        self,
    ) -> None:
        pass

    async def _async_test_case_tearDown(
        self,
    ) -> None:
        self.logger.debug(
            f"Running async_test_case_tearDown logic for {self.__class__.__name__}"
        )
        try:
            await self.async_test_case_tearDown()
        except Exception as e:
            self.logger.error(f"Failed to run async_test_case_tearDown: {e}")
