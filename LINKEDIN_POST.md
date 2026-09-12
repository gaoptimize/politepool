# LinkedIn post

## The code (21 lines, self-contained, paste as-is)

```python
import ctypes, os, sys
from concurrent.futures import ProcessPoolExecutor

BELOW_NORMAL = 0x00004000

def lower_priority():
    """Yield to the human at the keyboard. Then use the whole machine."""
    if sys.platform == "win32":
        k = ctypes.windll.kernel32
        k.GetCurrentProcess.restype = ctypes.c_void_p           # <-- see below
        k.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        k.SetPriorityClass(k.GetCurrentProcess(), BELOW_NORMAL)
    else:
        os.nice(10)

def _init():
    lower_priority()
    for var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ[var] = "1"        # one BLAS thread per process, not N*N

def polite_map(fn, items, workers=None):
    workers = workers or max(1, (os.cpu_count() or 2) - 2)
    with ProcessPoolExecutor(max_workers=workers, initializer=_init) as pool:
        return list(pool.map(fn, items))          # order preserved
```

---

## Draft caption

I had a 24-core workstation and I was running four workers on it.

Not because of memory, not because of Amdahl. Out of politeness. A
normal-priority process pool makes your own desktop stutter — mouse lag,
sluggish browser, the editor hitching while you type — so I'd throttle the
pool and leave three-quarters of the machine idle.

You don't have to choose. Drop the workers to below-normal priority and the
OS preempts them the instant anything interactive wants the CPU. Microseconds.
No polling, no monitor process, nothing to tune. Then use the whole machine.

21 lines, above.

Two things I got wrong on the way, which are the interesting part:

**1. The obvious Windows snippet silently does nothing.**

```python
kernel32.SetPriorityClass(kernel32.GetCurrentProcess(), 0x4000)
```

ctypes defaults the return type of GetCurrentProcess to c_int, which truncates
the 64-bit pseudo-handle. SetPriorityClass then fails with no exception and no
warning. The priority simply never changes and you believe it did. I only
caught it because I asserted on the return value instead of trusting it.
Declaring restype/argtypes fixes it.

**2. Sizing by cores while ignoring RAM.**

A pool that sizes itself from cpu_count() will cheerfully spawn 30 workers,
and on Windows each one is a fresh interpreter re-importing your whole stack.
Cores are the obvious limit. Memory is the one that bites.

On my box: 4.1s serial → 0.6s across 30 low-priority workers, byte-identical
results, and the desktop stayed responsive the whole time.

None of this is new — os.nice is decades old and psutil documents all of it.
It's just the combination, with the footguns removed. Full version with tests
is MIT on GitHub: https://github.com/gaoptimize/politepool

#Python #Multiprocessing #PerformanceEngineering

---

## Notes before you post

- **Don't claim novelty.** These mechanisms are old and well documented. The
  post works because it's a specific, useful, honest fix with two real bugs
  in it — not because it's a breakthrough. If it goes up as a breakthrough,
  someone will reply "this is just nice() plus cpu_percent()" and be right.
- The ctypes gotcha is the strongest hook. It's concrete, surprising, and
  costs the reader nothing to verify.
- Swap in your own benchmark numbers if yours differ; mine are a 13900K.
- The 21-line version above has no memory cap and no serial fallback — it's
  the teaching version. Point at the repo for the one you'd actually deploy.
