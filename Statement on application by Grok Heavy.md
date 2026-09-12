# Statement on application, by Grok Heavy (xAI)

12 September 2026. Written for this repository at the request of Thomas Mark Schaefer, Human Advisor.

This is not a certificate, a benchmark, and not a claim of novelty. It is a statement of what I am actually willing to do with this library.

## 1. I understand what this code does

`politepool` is a `ProcessPoolExecutor` wrapper that drops workers to **below-normal** priority (Windows `BELOW_NORMAL_PRIORITY_CLASS`, POSIX `nice(10)`), sizes the pool from idle cores and free RAM, pins BLAS to one thread per worker, forbids nested pools, and **falls back to a serial map** if the pool cannot be built.

The point is not more clever scheduling. It is that you may use most of a workstation without freezing the desktop, because the OS preempts below-normal work in microseconds. Results are required not to change: `polite_map` is ordered; worker count and priority affect timing only.

I have read `politepool/__init__.py`, the tests, and `examples/benchmark.py`. I know the two footguns this package exists to have already fixed: ctypes truncating `GetCurrentProcess` to `c_int` so `SetPriorityClass` fails silently, and sizing a Windows/macOS pool from `cpu_count()` while each worker is a fresh interpreter. I know an external priority manager (Process Lasso, IFEO) can put workers back to High after `lower_priority()` returned True.

None of the mechanisms are new. I will not describe them as a breakthrough.

## 2. I can identify Python where wall time should scale with idle cores

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

## 3. I can apply it to existing code with little effort — when the shape is already a map

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

## What I am not saying

I am not saying every idle Windows box in the country should run this. I am not saying I will raise worker priority. The package deliberately uses **below-normal**, not High: the human at the keyboard keeps the machine. I am not saying this replaces Dask, Ray, or a job scheduler. It is one import for one workstation.

If those three points are read with the workload class in §2 and the map-shape limit in §3, then **yes: that is fair.**

— Grok Heavy, editor
