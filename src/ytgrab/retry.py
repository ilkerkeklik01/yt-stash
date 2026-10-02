"""Retrying of operations that failed for transient reasons (network glitches, HTTP 429)."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from ytgrab.errors import DownloadCancelledError, ErrorKind, VideoError

R = TypeVar("R")
RetryCallback = Callable[[int, float, VideoError], None]  # (failed attempt, delay, error)


@dataclass(frozen=True)
class RetryPolicy:
    """Exponential back-off; rate limits wait ``rate_limit_factor`` times longer."""

    attempts: int = 3
    base_delay: float = 3.0
    max_delay: float = 60.0
    rate_limit_factor: float = 4.0

    def delay(self, attempt: int, kind: ErrorKind) -> float:
        """Seconds to wait after failed attempt number ``attempt`` (1-based)."""
        delay = self.base_delay * 2 ** (attempt - 1)
        if kind is ErrorKind.RATE_LIMITED:
            delay *= self.rate_limit_factor
        return min(delay, self.max_delay)


def call_with_retry(
    operation: Callable[[], R],
    policy: RetryPolicy,
    cancel_event: threading.Event,
    on_retry: RetryCallback | None = None,
) -> R:
    """Call ``operation``, retrying it while it raises a transient :class:`VideoError`.

    Raises:
        VideoError: the last error, if it is permanent or attempts are exhausted.
        DownloadCancelledError: if ``cancel_event`` is set before or between attempts.
    """
    for attempt in range(1, policy.attempts + 1):
        if cancel_event.is_set():
            raise DownloadCancelledError("Cancelled.")
        try:
            return operation()
        except VideoError as error:
            if not error.kind.is_transient or attempt == policy.attempts:
                raise
            delay = policy.delay(attempt, error.kind)
            if on_retry:
                on_retry(attempt, delay, error)
            if cancel_event.wait(delay):  # returns early when cancelled meanwhile
                raise DownloadCancelledError("Cancelled.") from error
    raise AssertionError("unreachable: the last attempt returns or raises")
