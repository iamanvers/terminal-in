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

log = logging.getLogger(__name__)

_inventory: dict = {}


def detect() -> dict:
    """One-time hardware inventory. Cached."""
    global _inventory
    if _inventory:
        return _inventory

    logical = os.cpu_count() or 4
    physical = logical
    gpus: list[str] = []
    cpu_name = ''
    try:
        out = subprocess.run(
            ['powershell', '-NoProfile', '-Command',
             '(Get-CimInstance Win32_Processor).Name; '
             '(Get-CimInstance Win32_Processor).NumberOfCores; '
             '(Get-CimInstance Win32_VideoController).Name'],
            capture_output=True, text=True, timeout=15,
        ).stdout.strip().splitlines()
        if len(out) >= 2:
            cpu_name = out[0].strip()
            physical = int(out[1].strip() or physical)
            gpus = [g.strip() for g in out[2:] if g.strip()]
    except Exception:
        log.warning('hw: WMI inventory failed — using os.cpu_count() only')

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
