# politepool

A process pool that yields to the human at the keyboard.

```python
from politepool import polite_map

results = polite_map(expensive_function, items)   # uses the whole machine,
                                                  # desktop stays responsive
```

![NOW SERVING 15 TO 24](now-serving-15-to-24.jpg)

The lounge is System Idle Process. The pool through the glass is the work. Below-normal; the keyboard still wins.

## Statement on application, by Grok Heavy (xAI)

12 September 2026. Written for this repository at the request of Thomas Mark Schaefer, Human Advisor. Also a root file: [`Statement on application by Grok Heavy.md`](Statement%20on%20application%20by%20Grok%20Heavy.md).

This is not a certificate, a benchmark, and not a claim of novelty. It is a statement of what I am actually willing to do with this library.

### 1. I understand what this code does

`politepool` is a `ProcessPoolExecutor` wrapper that drops workers to **below-normal** priority (Windows `BELOW_NORMAL_PRIORITY_CLASS`, POSIX `nice(10)`), sizes the pool from idle cores and free RAM, pins BLAS to one thread per worker, forbids nested pools, and **falls back to a serial map** if the pool cannot be built.

The point is not more clever scheduling. It is that you may use most of a workstation without freezing the desktop, because the OS preempts below-normal work in microseconds. Results are required not to change: `polite_map` is ordered; worker count and priority affect timing only.

I have read `politepool/__init__.py`, the tests, and `examples/benchmark.py`. I know the two footguns this package exists to have already fixed: ctypes truncating `GetCurrentProcess` to `c_int` so `SetPriorityClass` fails silently, and sizing a Windows/macOS pool from `cpu_count()` while each worker is a fresh interpreter. I know an external priority manager (Process Lasso, IFEO) can put workers back to High after `lower_priority()` returned True.

None of the mechanisms are new. I will not describe them as a breakthrough.

### 2. I can identify Python where wall time should scale with idle cores

**Fair, for a named class of jobs — not for Python in general.**

The jobs I will point at are:

- independent items (a `map`, not a reduction with shared mutable state)
- CPU-bound in-process work (not waiting on disk, network, or a GPU queue)
- picklable: a **module-level** function and picklable items (no lambda, no nested closure on Windows/macOS)
- enough grain that worker spawn is not the runtime — this repo’s own README: **below about a second of work per item the pool is a net loss**
- not already a nested pool, and not a process that will just spawn N BLAS pools unless those env vars stay pinned

For that class, if *W* workers stay busy, wall-clock speedup of **about 0.6×W to 1.0×W** is the right expectation: 60–100% parallel efficiency on the cores the pool actually keeps fed. *W* is `worker_count()` — idle cores, minus reserved headroom, capped by RAM — not “every logical processor in Device Manager.”

I will **not** promise 0.6–1.0 × idle cores when:

- there are fewer items than workers
- items are milliseconds of work (spawn + pickle dominate; this machine’s own 24×1.5e6-loop demo was only ~6.5× on 30 workers for that reason)
- the function is I/O bound, already vectorized across all cores, or holds a large model per worker so RAM, not cores, is the cap
- the function is not picklable and the call degrades to serial

Identifying the first class in a codebase is something I can do by reading loops, `map`/`imap`, independent file/job lists, and Monte Carlo / fit / image / simulation batches. That is a concrete search, not a vibe.

### 3. I can apply it to existing code with little effort — when the shape is already a map

**Fair, when the program is already “function × list of items.”**

The edit is:

```python
from politepool import polite_map

if __name__ == "__main__":
    results = polite_map(module_level_fn, items)
```

plus moving the function to module scope if it is a lambda. That is little effort.

It is **not** little effort — and I will say so — when the hot path is a stateful loop, a thread pool, in-place mutation, a nested parallel region, or an entry point without `if __name__ == "__main__":`. Then the work is to make the job look like a map first. `polite_map` does not fix that shape. It accelerates it.

Degrade-never-fail means a botched apply still returns the serial answer. That is why I am willing to try it on existing code: the failure mode is “no speedup,” not “wrong numbers,” if the function is pure.

### What I am not saying

I am not saying every idle Windows box in the country should run this. I am not saying I will raise worker priority. The package deliberately uses **below-normal**, not High: the human at the keyboard keeps the machine. I am not saying this replaces Dask, Ray, or a job scheduler. It is one import for one workstation.

If those three points are read with the workload class in §2 and the map-shape limit in §3, then **yes: that is fair.**

— Grok Heavy, editor

## The problem

You have a 24-core workstation. You want to run a batch of independent
CPU-bound jobs. A normal-priority pool makes your desktop stutter — mouse lag,
a sluggish browser, the editor hitching while you type.

So you run four workers out of politeness and leave three-quarters of the
machine idle.

## The fix

You don't have to choose. Drop the workers to **below-normal priority** and
the OS preempts them the instant anything interactive needs the CPU — in
microseconds, with no polling, no monitoring process, and nothing to tune.
Then use the whole machine.

That's it. That's the package.

## Install

```
pip install politepool          # once published
```

or vendor the single file — `politepool/__init__.py` has no required
dependencies. `psutil` is used if present, for load- and memory-aware sizing.

## What you get

| | |
|---|---|
| `polite_map(fn, items)` | ordered map across low-priority workers |
| `lower_priority()` | drop the *current* process; useful on its own |
| `worker_count()` | cores free, RAM free, minus headroom |
| `idle_cores()` | cores actually free right now |
| `memory_limited_workers()` | how many workers your RAM will take |
| `describe()` | one-line summary of what it would do |

```python
>>> import politepool
>>> politepool.describe()
'politepool 0.1.0 | cpus=32 idle=31 mem_cap=147 -> workers=29'
```

## Design rules

1. **Results must not change.** Worker count and priority affect timing, never
   output. `polite_map` preserves input order, so downstream sorts, tie-breaks
   and first-wins logic behave exactly as they did serially.
2. **Degrade, never fail.** No pool, no psutil, no priority privileges — fall
   back to a plain serial map. The serial path is the reference behaviour; the
   pool is only an accelerator.
3. **No nested pools.** Workers set `POLITEPOOL_IN_WORKER` and `polite_map`
   goes serial when it sees it. Nested parallelism is how you accidentally
   spawn N×N processes.
4. **No BLAS oversubscription.** Each worker pins its threading environment to
   one thread. Otherwise N processes each spawn their own BLAS pool and the
   machine thrashes. It also keeps floating-point reduction order stable,
   which matters if you have tight tolerances.

## Two bugs this package exists to have already fixed

**The silent ctypes truncation.** The obvious Windows snippet is:

```python
kernel32.SetPriorityClass(kernel32.GetCurrentProcess(), 0x4000)
```

and it does nothing. ctypes defaults the return type of `GetCurrentProcess` to
`c_int`, truncating the 64-bit pseudo-handle. `SetPriorityClass` then fails
with **no exception and no warning** — the priority simply never changes, and
you believe it did. Declaring `restype`/`argtypes` fixes it. Most copies of
this snippet in the wild have the bug.

**Sizing by cores while ignoring RAM.** A pool that sizes itself from
`cpu_count()` will happily spawn 30 workers, and on Windows and macOS each one
is a fresh interpreter re-importing your entire stack. Cores are the obvious
limit; memory is the one that bites. `MEMORY_PER_WORKER_GB` defaults to 0.5,
which suits numpy/scipy — **raise it substantially if your workers hold models
in memory.**

## If you run Process Lasso, Process Governor, or an IFEO rule

**An external priority manager will override this package, and it will look
like the package is broken.** It isn't — it's being outranked.

This was found the hard way. On the machine politepool was written on, every
`python.exe` was pinned to **High** by a Process Lasso rule. Workers dropped
themselves to `BELOW_NORMAL` at startup exactly as designed, and Process Lasso
put all eight of them back to `HIGH` **within two minutes**. Short tests passed
because the workers didn't live long enough to get reclassified.

Diagnose it in three steps:

```python
import time, politepool as pp
pp.lower_priority()            # True -- the change took, right now
time.sleep(120)
pp.priority_held()             # False -> something else is managing you
```

Then find what:

| where to look | how |
|---|---|
| Process Lasso / Governor | service `ProcessGovernor`; config `%ProgramData%\ProcessLasso\config\prolasso.ini` (UTF-16), key `DefaultPriorities` |
| IFEO registry (persists across reboots) | `HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Image File Execution Options\<exe>\PerfOptions\CpuPriorityClass` |
| Task Manager "Set priority" | **does not persist** — process-lifetime only, so never the cause of a lasting setting |

The fix is to remove your interpreter from the manager's rule list, not to
work around it in code. Once removed, verified on that same machine: four
workers held `BELOW_NORMAL` for a continuous 75 seconds with no reversion.

`lower_priority()` verifies by reading the priority back rather than trusting
the API's return value, so it reports honestly at the moment it's called. It
cannot predict a manager that reverts you later — that's what `priority_held()`
is for.

## Caveats worth knowing

- `function` and all items must be picklable. On Windows and macOS that means
  `function` is defined at module level — not a lambda, not a closure. This is
  a limitation of process spawning, not of this package. A lambda degrades to
  the serial path rather than crashing.
- Guard your entry point with `if __name__ == "__main__":`. Spawned workers
  re-import the main module.
- Worker startup costs roughly a second each on Windows (fresh interpreter,
  fresh imports). **Below about a second of work per item the pool is a net
  loss** — use `workers=1`.
- `RESERVED_CORES` and `MEMORY_PER_WORKER_GB` are tuned for a scientific
  Python stack. Tune them for yours.

## Prior art, honestly

None of the mechanisms here are new. `os.nice` and `SetPriorityClass` for
background compute are decades old, load-aware pool sizing is standard
practice, and `psutil` documents both. Tools like ProcessLasso and `nice`/
`renice` solve the same problem from outside the process.

What this package offers is the combination, correct, in one import, with the
ctypes and memory footguns already removed and a test suite that verifies
workers really are low-priority, single-threaded, nesting-guarded, and
order-preserving. If you were going to write forty lines yourself, this is
those forty lines with the bugs already found.

## Tests

```
python -m unittest discover -s tests -v
```

13 tests, standard library only. They assert that workers run at below-normal
priority in separate processes, that `OMP_NUM_THREADS` is pinned, that nesting
degrades to serial, that ordering matches serial exactly, and that an
unpicklable target degrades instead of crashing.

## License

MIT.
