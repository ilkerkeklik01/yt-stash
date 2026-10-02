"""Thread-pool helper that stays responsive to Ctrl+C on every operating system."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, wait
from typing import TypeVar

T = TypeVar("T")
R = TypeVar("R")

_POLL_SECONDS = 0.2


def map_interruptible(
    fn: Callable[[T], R],
    items: Sequence[T],
    workers: int,
    *,
    on_abort: Callable[[], None] | None = None,
    wait_on_abort: bool = True,
) -> list[R]:
    """Run ``fn`` over ``items`` with up to ``workers`` threads; results keep input order.

    Waiting with a short timeout (instead of blocking on a future) lets the main thread
    receive KeyboardInterrupt promptly, also on Windows.

    On Ctrl+C, ``on_abort`` is called so running tasks can stop early, queued tasks are
    cancelled, and KeyboardInterrupt is re-raised — after running tasks return if
    ``wait_on_abort`` is true (a second Ctrl+C stops that wait). An exception raised by
    ``fn`` itself propagates once all tasks have finished.
    """
    if not items:
        return []
    pool = ThreadPoolExecutor(max_workers=max(1, min(workers, len(items))))
    try:
        futures = [pool.submit(fn, item) for item in items]
        pending = set(futures)
        while pending:
            _done, pending = wait(pending, timeout=_POLL_SECONDS)
        results = [future.result() for future in futures]
    except BaseException:
        if on_abort:
            on_abort()
        try:
            pool.shutdown(wait=wait_on_abort, cancel_futures=True)
        except KeyboardInterrupt:
            pool.shutdown(wait=False, cancel_futures=True)
        raise
    pool.shutdown()
    return results
