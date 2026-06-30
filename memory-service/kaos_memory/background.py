"""Bounded fire-and-forget background runner for off-path memory work.

Long-term extraction, consolidation and forgetting run off the request path. This
runner bounds their concurrency, retries transient failures a fixed number of times,
and gives up cleanly (without crashing the service) when retries are exhausted,
recording the give-up for observability. Pending work drains on shutdown.

The service handlers are synchronous (FastAPI runs them on a threadpool), so the
runner is thread-based: a ``ThreadPoolExecutor`` caps concurrency at ``concurrency``
workers. This is the natural fit for the sync server model and gives the same
bounded-concurrency, bounded-retry, graceful-drain guarantees.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional

logger = logging.getLogger("kaos.memory.background")

#: Invoked when a task gives up after exhausting retries (the exception is passed).
GiveupHook = Callable[[BaseException], None]


class BackgroundRunner:
    """Runs thunks on a bounded threadpool with bounded retry and graceful drain."""

    def __init__(
        self,
        concurrency: int = 4,
        max_retries: int = 2,
        retry_delay: float = 0.0,
        on_giveup: Optional[GiveupHook] = None,
    ) -> None:
        if concurrency < 1:
            raise ValueError("concurrency must be >= 1")
        self.concurrency = concurrency
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.on_giveup = on_giveup
        self.failures = 0
        self._executor = ThreadPoolExecutor(max_workers=concurrency)

    def submit(self, thunk: Callable[[], None]) -> None:
        """Schedule ``thunk`` to run off the response path. Never blocks the caller."""
        self._executor.submit(self._run_with_retry, thunk)

    # Usable directly as a Scheduler (Callable[[thunk], None]).
    __call__ = submit

    def _run_with_retry(self, thunk: Callable[[], None]) -> None:
        attempts = self.max_retries + 1
        last: Optional[BaseException] = None
        for attempt in range(attempts):
            try:
                thunk()
                return
            except Exception as exc:  # bounded retry; never propagate out of the worker
                last = exc
                if attempt + 1 < attempts and self.retry_delay:
                    time.sleep(self.retry_delay)
        self.failures += 1
        logger.warning("background task gave up after %d attempts: %s", attempts, last)
        if self.on_giveup is not None and last is not None:
            try:
                self.on_giveup(last)
            except Exception:  # never let the give-up hook crash a worker
                logger.exception("on_giveup hook raised")

    def shutdown(self, wait: bool = True) -> None:
        """Drain pending work and stop accepting new tasks."""
        self._executor.shutdown(wait=wait)
