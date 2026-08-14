# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict
"""The marker that tags investigation-agent transcript records in the run log.

The investigation agent tees its whole live transcript (thinking blocks, tool
calls, tool results, answers, assembled prompts, token usage) through the TAAC
run logger, so a human watching the console sees the reasoning as it happens.
That same logger feeds ``TaacTestSummary``'s capture handler, and the handler's
whole-run buffer is inlined verbatim into the NEXT investigation's prompt. Left
unmarked, investigation N's transcript (including its rendered verdict) lands
inside investigation N+1's prompt: each investigation both starves the next of
context window and contaminates it with the earlier conclusion.

Every transcript record therefore starts with ``INVESTIGATION_LOG_PREFIX``, and
the capture handler keeps marked records out of its whole-run buffer. The prefix
lives here, in a dependency-free module that both the producer
(``libs/taac_runner.py``'s ``_log_investigation_event``) and the consumer
(``utils/taac_test_summary.py``) depend on, so the two can never drift apart.

Matching is per log RECORD, never per output line: a thinking block is a single
multi-line record whose marker sits only on its first line, so a line-by-line
filter would strip the header and leave the continuation lines orphaned.
"""

from __future__ import annotations

INVESTIGATION_LOG_PREFIX: str = "[investigation]"


def is_investigation_transcript(message: str) -> bool:
    """True if ``message`` is one whole investigation-transcript log record.

    Pass ``logging.LogRecord.getMessage()``, the record's full (possibly
    multi-line) message, not an individual formatted output line.
    """
    return message.startswith(INVESTIGATION_LOG_PREFIX)
