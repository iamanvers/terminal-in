"""
Hardware detection + throughput maximization.

detect() — inventory the machine (CPU cores, GPUs, torch device) once at boot.
apply()  — push compute settings to the hardware's limits: thread counts for
           torch/OpenMP/MKL sized to ALL logical cores (the default uses only
           physical cores, which caps Task Manager utilization near 50% on SMT
           CPUs like the Ryzen 7 7730U).

The inventory is published into /api/health so a GPU sitting unused is
visible, never silent. GPU acceleration paths (DirectML for FinBERT, Vulkan
offload for llama.cpp) are P2 — see PRD 5b.4.
"""

import logging
import os
import subprocess
import sys

log = logging.getLogger(__name__)

_inventory: dict = {}


def _detect_windows():
    out = subprocess.run(
        ['powershell', '-NoProfile', '-Command',
         '(Get-CimInstance Win32_Processor).Name; '
         '(Get-CimInstance Win32_Processor).NumberOfCores; '
         '(Get-CimInstance Win32_VideoController).Name'],
        capture_output=True, text=True, timeout=15,
    ).stdout.strip().splitlines()
    cpu = out[0].strip() if out else ''
    physical = int(out[1].strip()) if len(out) > 1 and out[1].strip() else None
    gpus = [g.strip() for g in out[2:] if g.strip()] if len(out) > 2 else []
    return cpu, physical, gpus


def _detect_macos():
    def sc(key):
        return subprocess.run(['sysctl', '-n', key], capture_output=True, text=True, timeout=5).stdout.strip()
    cpu = sc('machdep.cpu.brand_string')                 # e.g. "Apple M2 Pro"
    physical = int(sc('hw.physicalcpu') or 0) or None
    # GPU: skip system_profiler (slow); Apple Silicon is integrated GPU = chip name
    gpus = [cpu] if cpu.startswith('Apple') else []
    return cpu, physical, gpus


def _detect_linux():
    cpu, physical = '', None
    try:
        info = open('/proc/cpuinfo').read()
        for line in info.splitlines():
            if line.startswith('model name'):
                cpu = line.split(':', 1)[1].strip(); break
        cores = {l.split(':')[1].strip() for l in info.splitlines() if l.startswith('core id')}
        physical = len(cores) or None
    except Exception:
        pass
    return cpu, physical, []


def detect() -> dict:
    """One-time hardware inventory. Cached. Cross-platform (Windows/macOS/Linux)."""
    global _inventory
    if _inventory:
        return _inventory

    logical = os.cpu_count() or 4
    physical = logical
    gpus: list[str] = []
    cpu_name = ''
    try:
        if sys.platform == 'win32':
            cpu_name, phys, gpus = _detect_windows()
        elif sys.platform == 'darwin':
            cpu_name, phys, gpus = _detect_macos()
        else:
            cpu_name, phys, gpus = _detect_linux()
        if phys:
            physical = phys
    except Exception:
        log.warning('hw: CPU inventory failed — using os.cpu_count() only')

    cuda = False
    try:
        import torch
        cuda = torch.cuda.is_available()
    except Exception:
        pass

    _inventory = {
        'cpu': cpu_name or 'unknown',
        'cores_physical': physical,
        'cores_logical': logical,
        'gpus': gpus,
        'torch_cuda': cuda,
        # honest accounting: a GPU exists but nothing uses it yet → surface it
        'gpu_unused': bool(gpus) and not cuda,
    }
    return _inventory


def apply(for_training: bool = False) -> dict:
    """Size compute pools to the full machine. Call before heavy torch work.

    Thread env vars must be set before torch/numpy initialize their pools,
    so call this as early as possible in the process.
    """
    inv = detect()
    n = inv['cores_logical']

    # OpenMP / MKL pools — these default to physical cores; use every
    # logical core so sustained math work can exceed the ~50% SMT ceiling
    for var in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS'):
        os.environ.setdefault(var, str(n))

    try:
        import torch
        torch.set_num_threads(n)
        if for_training:
            try:
                torch.set_num_interop_threads(max(2, n // 4))
            except RuntimeError:
                pass  # can only be set once per process, before parallel work
    except Exception:
        pass

    log.info('hw: %s · %d threads engaged · GPUs: %s%s',
             inv['cpu'], n, ', '.join(inv['gpus']) or 'none',
             ' (UNUSED — no CUDA; DirectML/Vulkan path is P2)' if inv['gpu_unused'] else '')
    return inv
