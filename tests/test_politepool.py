"""Tests for politepool. Standard library only: python -m unittest discover -s tests

Worker targets must live at module level to survive pickling under spawn.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import politepool as pp


def square(value):
    return value * value


def worker_report(_index):
    """Report the environment a worker actually runs in."""
    priority = None
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        kernel32.GetPriorityClass.argtypes = [ctypes.c_void_p]
        priority = kernel32.GetPriorityClass(kernel32.GetCurrentProcess())
    else:
        priority = os.nice(0)
    return {
        "pid": os.getpid(),
        "priority": priority,
        "omp": os.environ.get("OMP_NUM_THREADS"),
        "in_worker": os.environ.get("POLITEPOOL_IN_WORKER"),
        "nested_is_serial": pp.polite_map(square, [1, 2, 3]) == [1, 4, 9],
    }


def busy(value):
    """Enough work that the pool actually spawns more than one process."""
    total = 0.0
    for i in range(400_000):
        total += (i % 7) * 0.5
    return (value, os.getpid(), total)


class TestSizing(unittest.TestCase):
    def test_explicit_env_override_is_exact(self):
        os.environ[pp.WORKERS_ENV] = "3"
        try:
            self.assertEqual(pp.worker_count(), 3)
        finally:
            del os.environ[pp.WORKERS_ENV]

    def test_override_is_clamped_to_cpu_count(self):
        os.environ[pp.WORKERS_ENV] = "100000"
        try:
            self.assertLessEqual(pp.worker_count(), os.cpu_count() or 1)
        finally:
            del os.environ[pp.WORKERS_ENV]

    def test_garbage_override_falls_back_to_adaptive(self):
        os.environ[pp.WORKERS_ENV] = "not-a-number"
        try:
            self.assertGreaterEqual(pp.worker_count(), 1)
        finally:
            del os.environ[pp.WORKERS_ENV]

    def test_adaptive_leaves_headroom(self):
        total = os.cpu_count() or 1
        if total <= pp.RESERVED_CORES:
            self.skipTest("machine too small for a headroom assertion")
        self.assertLessEqual(pp.worker_count(), total - pp.RESERVED_CORES)

    def test_helpers_return_positive_ints(self):
        self.assertGreaterEqual(pp.idle_cores(sample_seconds=0.05), 1)
        self.assertGreaterEqual(pp.memory_limited_workers(), 1)


class TestSemantics(unittest.TestCase):
    def test_order_is_preserved(self):
        items = list(range(25))
        self.assertEqual(pp.polite_map(square, items, workers=4),
                         [v * v for v in items])

    def test_matches_serial_exactly(self):
        items = list(range(25))
        self.assertEqual(pp.polite_map(square, items, workers=4),
                         pp.polite_map(square, items, workers=1))

    def test_empty_input(self):
        self.assertEqual(pp.polite_map(square, []), [])

    def test_single_item_stays_serial(self):
        self.assertEqual(pp.polite_map(square, [7], workers=8), [49])

    def test_unpicklable_target_degrades_not_crashes(self):
        result = pp.polite_map(lambda v: v + 1, [1, 2, 3], workers=4, quiet=True)
        self.assertEqual(result, [2, 3, 4])


class TestPriority(unittest.TestCase):
    def test_lower_priority_succeeds_and_is_observable(self):
        self.assertTrue(pp.lower_priority())
        if sys.platform == "win32":
            import ctypes

            kernel32 = ctypes.windll.kernel32
            kernel32.GetCurrentProcess.restype = ctypes.c_void_p
            kernel32.GetPriorityClass.argtypes = [ctypes.c_void_p]
            self.assertEqual(
                kernel32.GetPriorityClass(kernel32.GetCurrentProcess()),
                pp.BELOW_NORMAL_PRIORITY_CLASS)

    def test_workers_are_low_priority_pinned_and_guarded(self):
        reports = pp.polite_map(worker_report, list(range(4)), workers=4)
        self.assertEqual(len(reports), 4)
        for report in reports:
            self.assertNotEqual(report["pid"], os.getpid())
            self.assertEqual(report["omp"], "1")
            self.assertEqual(report["in_worker"], "1")
            self.assertTrue(report["nested_is_serial"])
            if sys.platform == "win32":
                self.assertEqual(report["priority"], pp.BELOW_NORMAL_PRIORITY_CLASS)

    def test_pool_really_spawns_multiple_processes(self):
        if (os.cpu_count() or 1) < 4:
            self.skipTest("needs at least 4 cores")
        results = pp.polite_map(busy, list(range(8)), workers=4)
        self.assertEqual([r[0] for r in results], list(range(8)))
        self.assertGreater(len({r[1] for r in results}), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
