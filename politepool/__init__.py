"""politepool -- a process pool that yields to the human at the keyboard.

The problem this solves is mundane and extremely common: you have a 24-core
workstation, you want to run a batch of independent CPU-bound jobs, and a
normal-priority pool makes your desktop stutter. So you run four workers out
of politeness and leave most of the machine idle.

You do not have to choose. Drop the workers to below-normal priority and the
OS preempts them the instant anything interactive needs the CPU -- in
microseconds, with no polling, no monitoring process, and nothing to tune.
Then use the whole machine.

    from politepool import polite_map

    results = polite_map(expensive_function, items)

Design rules, in order of importance:

  1. RESULTS MUST NOT CHANGE. Worker count and priority affect timing, never
     output. `polite_map` preserves input order, so any downstream sort,
     tie-break, or first-wins logic behaves exactly as it did serially.

  2. DEGRADE, NEVER FAIL. If a pool cannot be created, if psutil is missing,
     if the priority call fails -- fall back to a plain serial map. The
     serial path is the reference behaviour; the pool is only an accelerator.

  3. NO NESTED POOLS. Workers set POLITEPOOL_IN_WORKER, and polite_map
     degrades to a serial map when it sees it. Nested parallelism is how you
     accidentally spawn N*N processes.

  4. NO BLAS OVERSUBSCRIPTION. Each worker pins its threading environment to
     a single thread. Without this, N processes each spawn their own BLAS
     thread pool and the machine thrashes. It also keeps floating-point
     reduction order stable, which matters if you have tight tolerances.

MIT licensed. No required dependencies; psutil is used if present.
"""

from __future__ import annotations

import os
import sys

__version__ = "0.1.0"

__all__ = [
    "polite_map",
    "lower_priority",
    "priority_held",
    "current_priority",
    "worker_count",
    "idle_cores",
    "memory_limited_workers",
    "in_worker",
    "describe",
]

#: Cores left for the human, always.
RESERVED_CORES = 2

#: Rough resident cost of one worker once your stack is imported. 0.5 GB suits
#: numpy/scipy. Raise it substantially if your workers hold models in memory.
MEMORY_PER_WORKER_GB = 0.5

#: Windows BELOW_NORMAL_PRIORITY_CLASS. Deliberately not IDLE_PRIORITY_CLASS:
#: idle-priority work can be starved indefinitely by trivial background
#: activity, and we want the job to finish.
BELOW_NORMAL_PRIORITY_CLASS = 0x00004000

#: POSIX niceness increment. 10 is a firm yield without being unkillable.
POSIX_NICE_INCREMENT = 10

#: Environment variable that pins the worker count explicitly.
WORKERS_ENV = "POLITEPOOL_WORKERS"

_IN_WORKER_ENV = "POLITEPOOL_IN_WORKER"

_THREAD_VARS = (
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
)


def current_priority():
    """This process's priority: a Windows priority class, or POSIX niceness."""
    try:
        if sys.platform == "win32":
            import ctypes

            kernel32 = ctypes.windll.kernel32
            kernel32.GetCurrentProcess.restype = ctypes.c_void_p
            kernel32.GetCurrentProcess.argtypes = []
            kernel32.GetPriorityClass.argtypes = [ctypes.c_void_p]
            kernel32.GetPriorityClass.restype = ctypes.c_uint
            return kernel32.GetPriorityClass(kernel32.GetCurrentProcess())
        return os.nice(0)
    except Exception:
        return None


def priority_held() -> bool:
    """Is this process still at lowered priority?

    Call it *later* -- an external priority manager (Process Lasso, Process
    Governor, an IFEO rule) can reassign priority seconds after the process
    starts, long after ``lower_priority`` returned True. See the README
    section on external priority managers.
    """
    observed = current_priority()
    if observed is None:
        return False
    if sys.platform == "win32":
        return observed in (BELOW_NORMAL_PRIORITY_CLASS, 0x00000040)  # below/idle
    return observed > 0


def lower_priority(verify: bool = True) -> bool:
    """Drop this process to below-normal priority. Returns True on success.

    With ``verify`` (the default) the new priority is read back and compared
    rather than trusting the API's return value. This is what catches the
    ctypes truncation bug below -- and it is a general lesson: an API that
    reports success is not evidence that the state changed.

    NOTE: a True here means the change took *at this instant*. An external
    priority manager can revert it seconds later. Use ``priority_held()``
    after a delay if you need to know it stuck.

    Windows uses ctypes; everything else uses os.nice. No third-party
    dependency either way.

    The ctypes signatures are declared explicitly and that is not cosmetic.
    Without them ctypes defaults the return of ``GetCurrentProcess`` to
    ``c_int``, which truncates the 64-bit pseudo-handle, and
    ``SetPriorityClass`` then fails *silently* -- no exception, no warning,
    the priority simply never changes. Most two-line snippets of this on the
    internet have that bug.

    Priority is an optimisation, never a correctness requirement, so every
    failure here is swallowed and reported through the return value.
    """
    try:
        if sys.platform == "win32":
            import ctypes

            kernel32 = ctypes.windll.kernel32
            kernel32.GetCurrentProcess.restype = ctypes.c_void_p
            kernel32.GetCurrentProcess.argtypes = []
            kernel32.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint]
            kernel32.SetPriorityClass.restype = ctypes.c_int
            ok = bool(kernel32.SetPriorityClass(
                kernel32.GetCurrentProcess(), BELOW_NORMAL_PRIORITY_CLASS))
            if not ok:
                return False
            if not verify:
                return True
            return current_priority() == BELOW_NORMAL_PRIORITY_CLASS
        before = os.nice(0)
        os.nice(POSIX_NICE_INCREMENT)
        if not verify:
            return True
        return os.nice(0) > before
    except Exception:
        return False


def idle_cores(sample_seconds: float = 0.3) -> int:
    """Cores actually free right now, rather than cores that exist.

    Needs psutil to measure. Without it, assume the machine is idle and let
    :data:`RESERVED_CORES` supply the margin.
    """
    total = os.cpu_count() or 1
    try:
        import psutil

        busy_fraction = psutil.cpu_percent(interval=sample_seconds) / 100.0
        return max(1, int(round(total * (1.0 - busy_fraction))))
    except Exception:
        return total


def memory_limited_workers() -> int:
    """Cap the pool by free RAM, not just by cores.

    A self-sizing pool that ignores memory is a footgun. On Windows and macOS
    every worker is a fresh interpreter that re-imports your entire stack, so
    30 workers can be tens of gigabytes before any real work begins. Cores are
    the obvious limit; memory is the one that actually bites.
    """
    try:
        import psutil

        available_gb = psutil.virtual_memory().available / (1024.0 ** 3)
        return max(1, int(available_gb / MEMORY_PER_WORKER_GB))
    except Exception:
        return os.cpu_count() or 1


def in_worker() -> bool:
    """True if called inside a politepool worker process."""
    return os.environ.get(_IN_WORKER_ENV) == "1"


def worker_count() -> int:
    """How many workers to use.

    An explicit ``POLITEPOOL_WORKERS`` is honoured exactly -- reproducibility
    runs and benchmarks want to pin it. Otherwise size to whatever is
    genuinely free in cores, in memory, and after the reserved headroom.
    """
    if in_worker():
        return 1
    raw = os.environ.get(WORKERS_ENV)
    if raw:
        try:
            return max(1, min(int(raw), os.cpu_count() or 1))
        except ValueError:
            pass
    total = os.cpu_count() or 1
    return max(1, min(idle_cores(), total - RESERVED_CORES,
                      memory_limited_workers()))


def _init_worker() -> None:
    os.environ[_IN_WORKER_ENV] = "1"
    for name in _THREAD_VARS:
        os.environ[name] = "1"
    lower_priority()


def polite_map(function, items, workers: int | None = None, quiet: bool = False):
    """Map ``function`` over ``items`` across low-priority worker processes.

    Returns a list in the same order as ``items``.

    ``function`` and every item must be picklable, which on Windows and macOS
    means ``function`` has to be defined at module level -- not a lambda, not
    a closure, not nested in another function. This is a limitation of process
    spawning, not of this package.

    Guard your entry point with ``if __name__ == "__main__":`` for the same
    reason: spawned workers re-import the main module.
    """
    payload = list(items)
    if not payload:
        return []

    count = worker_count() if workers is None else max(1, int(workers))
    if count <= 1 or len(payload) == 1 or in_worker():
        return [function(item) for item in payload]

    from concurrent.futures import ProcessPoolExecutor

    try:
        with ProcessPoolExecutor(max_workers=min(count, len(payload)),
                                 initializer=_init_worker) as pool:
            return list(pool.map(function, payload))
    except Exception as error:
        if not quiet:
            print("[politepool] pool unavailable ({}: {}); running serially"
                  .format(type(error).__name__, error))
        return [function(item) for item in payload]


def describe() -> str:
    """One-line summary of what politepool would do right now."""
    return ("politepool {} | cpus={} idle={} mem_cap={} -> workers={}{}"
            .format(__version__, os.cpu_count(), idle_cores(),
                    memory_limited_workers(), worker_count(),
                    " (inside worker: serial)" if in_worker() else ""))
