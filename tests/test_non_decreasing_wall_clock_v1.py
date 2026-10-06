from __future__ import annotations

import sys
import threading
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import non_decreasing_wall_clock_v1 as wall_clock  # noqa: E402
from non_decreasing_wall_clock_v1 import ClockStepError, NonDecreasingWallClock  # noqa: E402


BASE_NS = 1_790_000_000_000_000_000


def _raw(values):
    iterator = iter(values)
    return lambda: next(iterator)


class NonDecreasingWallClockTests(unittest.TestCase):
    def test_two_millisecond_step_back_is_clamped_to_one_nanosecond_after_previous(self) -> None:
        clock = NonDecreasingWallClock(raw_ns=_raw([BASE_NS, BASE_NS - 2_000_000, BASE_NS + 1]))
        observed = [clock.now_ns() for _ in range(3)]
        self.assertEqual(observed, [BASE_NS, BASE_NS + 1, BASE_NS + 2])
        self.assertTrue(all(left < right for left, right in zip(observed, observed[1:])))
        self.assertEqual(clock.max_clamp_ns(), 2_000_001)

    def test_forward_raw_stamps_pass_unchanged_without_clamp(self) -> None:
        clock = NonDecreasingWallClock(raw_ns=_raw([BASE_NS, BASE_NS + 5, BASE_NS + 9]))
        self.assertEqual([clock.now_ns() for _ in range(3)], [BASE_NS, BASE_NS + 5, BASE_NS + 9])
        self.assertEqual(clock.max_clamp_ns(), 0)

    def test_step_back_beyond_ten_milliseconds_fails_closed(self) -> None:
        clock = NonDecreasingWallClock(raw_ns=_raw([BASE_NS, BASE_NS - 11_000_000]))
        self.assertEqual(clock.now_ns(), BASE_NS)
        with self.assertRaisesRegex(ClockStepError, "stepped back beyond the bounded clamp"):
            clock.now_ns()
        self.assertTrue(issubclass(ClockStepError, RuntimeError))
        self.assertEqual(clock.max_clamp_ns(), 0)

    def test_exactly_ten_millisecond_step_back_is_still_clamped(self) -> None:
        clock = NonDecreasingWallClock(raw_ns=_raw([BASE_NS, BASE_NS - 10_000_000]))
        clock.now_ns()
        self.assertEqual(clock.now_ns(), BASE_NS + 1)
        self.assertEqual(clock.max_clamp_ns(), 10_000_001)

    def test_invalid_raw_source_fails_closed(self) -> None:
        for value in (-1, 1.5, True, None):
            with self.subTest(value=value):
                clock = NonDecreasingWallClock(raw_ns=lambda value=value: value)
                with self.assertRaises(ClockStepError):
                    clock.now_ns()

    def test_concurrent_stamps_are_unique_and_strictly_increasing_per_thread(self) -> None:
        clock = NonDecreasingWallClock(raw_ns=lambda: BASE_NS)
        stamps: list[list[int]] = [[] for _ in range(8)]
        barrier = threading.Barrier(len(stamps))

        def worker(index: int) -> None:
            barrier.wait()
            for _ in range(2_000):
                stamps[index].append(clock.now_ns())

        threads = [threading.Thread(target=worker, args=(index,)) for index in range(len(stamps))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        merged = [value for values in stamps for value in values]
        self.assertEqual(len(set(merged)), len(merged))
        self.assertEqual(sorted(merged), list(range(BASE_NS, BASE_NS + len(merged))))
        for values in stamps:
            self.assertTrue(all(left < right for left, right in zip(values, values[1:])))
        self.assertEqual(clock.max_clamp_ns(), len(merged) - 1)

    def test_process_clock_is_one_shared_instance_behind_wall_time_ns(self) -> None:
        self.assertIs(wall_clock.process_wall_clock(), wall_clock.process_wall_clock())
        replacement = NonDecreasingWallClock(raw_ns=_raw([BASE_NS, BASE_NS - 2_000_000]))
        with mock.patch.object(wall_clock, "_PROCESS_CLOCK", replacement):
            self.assertIs(wall_clock.process_wall_clock(), replacement)
            self.assertEqual([wall_clock.wall_time_ns(), wall_clock.wall_time_ns()], [BASE_NS, BASE_NS + 1])
        self.assertEqual(replacement.max_clamp_ns(), 2_000_001)

    def test_default_raw_source_is_realtime_nanoseconds(self) -> None:
        clock = NonDecreasingWallClock()
        first = clock.now_ns()
        self.assertIs(type(first), int)
        self.assertLess(first, clock.now_ns())


if __name__ == "__main__":
    unittest.main()
