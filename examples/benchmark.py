"""Demonstrate politepool: same results, many cores, responsive desktop.

    python examples/benchmark.py

While it runs, use your machine. Drag a window, scroll a page, type. The
workers are below-normal priority, so the scheduler hands the CPU back the
moment you ask for it -- which is the whole point of running 29 of them
instead of 4.
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import politepool as pp


def work(seed):
    """Deliberately CPU-bound and pure: same input, same output, always."""
    total = 0.0
    value = seed
    for _ in range(1_500_000):
        value = (value * 1103515245 + 12345) % 2147483648
        total += (value % 1000) * 1e-6
    return round(total, 6)


def timed(label, items, workers):
    started = time.perf_counter()
    results = pp.polite_map(work, items, workers=workers)
    elapsed = time.perf_counter() - started
    print("  {:<24} {:>6.1f}s   workers={:<4}".format(label, elapsed, workers))
    return results, elapsed


def main():
    print(pp.describe())
    print()
    items = list(range(24))

    serial, t_serial = timed("serial", items, 1)
    parallel, t_parallel = timed("politepool", items, pp.worker_count())

    print()
    print("  identical results : {}".format(serial == parallel))
    print("  speedup           : {:.2f}x".format(t_serial / max(t_parallel, 1e-9)))
    print()
    print("  Results are identical because worker count and priority affect")
    print("  timing, never output. That is the invariant worth keeping.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
