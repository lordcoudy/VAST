"""One strictly increasing wall clock per process for ordered legacy stamps.

Python twin of native ``vast::NonDecreasingWallClock``: the host CLOCK_REALTIME
was observed stepping back ~2 ms (WSL time sync).  Each stamp is
``max(previous + 1 ns, raw)``; a backward raw step beyond 10 ms fails closed and
the largest applied clamp is retained for the process evidence.
"""

from __future__ import annotations

import threading
import time
from typing import Callable


MAXIMUM_BACKWARD_STEP_NS = 10_000_000


class ClockStepError(RuntimeError):
    """The host wall clock stepped back beyond the bounded clamp."""


class NonDecreasingWallClock:
    def __init__(self, raw_ns: Callable[[], int] = time.time_ns) -> None:
        self._raw_ns = raw_ns
        self._lock = threading.Lock()
        self._last: int | None = None
        self._max_clamp = 0

    def now_ns(self) -> int:
        with self._lock:
            raw = self._raw_ns()
            if type(raw) is not int or raw < 0:
                raise ClockStepError("host wall clock returned an invalid raw stamp")
            last = self._last
            if last is not None and raw + MAXIMUM_BACKWARD_STEP_NS < last:
                raise ClockStepError("host wall clock stepped back beyond the bounded clamp")
            value = raw if last is None or raw > last else last + 1
            self._last = value
            self._max_clamp = max(self._max_clamp, value - raw)
            return value

    def max_clamp_ns(self) -> int:
        with self._lock:
            return self._max_clamp


_PROCESS_CLOCK = NonDecreasingWallClock()


def process_wall_clock() -> NonDecreasingWallClock:
    return _PROCESS_CLOCK


def wall_time_ns() -> int:
    return _PROCESS_CLOCK.now_ns()


__all__ = [
    "MAXIMUM_BACKWARD_STEP_NS",
    "ClockStepError",
    "NonDecreasingWallClock",
    "process_wall_clock",
    "wall_time_ns",
]
