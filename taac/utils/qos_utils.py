# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe

from enum import IntEnum


class ClassOfService(IntEnum):
    BRONZE = 1
    SILVER = 2
    GOLD = 3
    ICP = 4
    NC = 5


QUEUE_DSCP_BIT_MAP = {
    ClassOfService.BRONZE: 10,
    ClassOfService.SILVER: 0,
    ClassOfService.GOLD: 18,
    ClassOfService.ICP: 35,
    ClassOfService.NC: 48,
}
