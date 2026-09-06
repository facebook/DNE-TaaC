#!/usr/bin/env python3
# pyre-unsafe

import asyncio
import os
from unittest import TestCase
from unittest.mock import AsyncMock, MagicMock, patch

from taac.libs import traffic_generator
from taac.libs.traffic_generator import TrafficGenerator
from taac.utils import ixia_utils


class TestIxiaOSSUsername(TestCase):
    def test_uses_oss_environment_username(self) -> None:
        with patch.object(ixia_utils, "TAAC_OSS", True), patch.dict(
            os.environ, {"TAAC_IXIA_USERNAME": "oss-ixia-user"}, clear=False
        ):
            self.assertEqual(ixia_utils.fetch_ixia_username(), "oss-ixia-user")

    def test_preserves_default_when_not_configured(self) -> None:
        with patch.object(ixia_utils, "TAAC_OSS", True), patch.dict(
            os.environ, {}, clear=True
        ):
            self.assertEqual(
                ixia_utils.fetch_ixia_username(), ixia_utils.API_SERVER_USERNAME
            )

    def test_traffic_generator_passes_both_credentials(self) -> None:
        generator = TrafficGenerator(endpoints=[])
        generator.async_create_ixia_config = AsyncMock(return_value=MagicMock())
        generator.dc_has_inband_connectivity = MagicMock(return_value=False)

        with patch.object(
            traffic_generator, "fetch_ixia_username", return_value="ixia-user"
        ), patch.object(
            traffic_generator, "fetch_ixia_password", return_value="ixia-password"
        ), patch.object(traffic_generator, "TaacIxia") as ixia_constructor:
            asyncio.run(generator.async_create_ixia_setup())

        self.assertEqual(ixia_constructor.call_args.kwargs["username"], "ixia-user")
        self.assertEqual(
            ixia_constructor.call_args.kwargs["password"], "ixia-password"
        )
