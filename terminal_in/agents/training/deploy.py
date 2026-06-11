"""
Model deploy pipeline (PRD 5c): LoRA adapter → Ollama model.

Chain per deploy:
  1. merge     — peft merge_and_unload into the base model (fp16)
  2. convert   — vendor/llamacpp-src/repo/convert_hf_to_gguf.py → f16 GGUF
  3. quantize  — vendor/llamacpp/llama-quantize.exe → Q4_K_M (~30% size)
  4. create    — ollama create financial-analyst-vN (system prompt from
                 the repo Modelfile, FROM the quantized GGUF)

Each deployed version stays in Ollama for instant rollback; the planner
model is switched via the OLLAMA_MODEL setting (settings panel dropdown),
never automatically. First verified end-to-end 2026-06-12 on the smoke-test
adapter (loss 2.52→1.16): financial-analyst-v1, 637 MB, ~28 tok/s CPU.
"""

import logging
import re
import subprocess
import sys
from pathlib import Path

log = logging.getLogger(__name__)

VENDOR_BIN = Path('./vendor/llamacpp')
CONVERT_PY = Path('./vendor/llamacpp-src/repo/convert_hf_to_gguf.py')
DEPLOY_DIR = Path('./data/training/deploy')
MODELFILE  = Path('./Modelfile')   # repo system prompt — single source


class DeployError(RuntimeError):
    pass


def _run(cmd: list[str], step: str, timeout: int = 1800, cwd: str | None = None) -> None:
    log.info('deploy %s: %s', step, ' '.join(str(c) for c in cmd[:3]) + ' …')
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd)
    if r.returncode != 0:
        tail = (r.stderr or r.stdout or '')[-600:]
        raise DeployError(f'{step} failed (exit {r.returncode}): {tail}')


def _next_version() -> int:
    try:
        out = subprocess.run(['ollama', 'list'], capture_output=True, text=True,
                             timeout=15).stdout
        versions = [int(m) for m in re.findall(r'financial-analyst-v(\d+)', out)]
        return max(versions, default=0) + 1
    except Exception:
        return 1


def deploy_adapter(adapter_dir: str | Path) -> dict:
    """Run the full chain on a trained adapter dir (the one holding
    adapter_config.json). Returns {model, gguf, size_mb}. Blocking — call
    from a worker thread; ~10–20 min on CPU for a 1.1B base."""
    adapter_dir = Path(adapter_dir)
    if not (adapter_dir / 'adapter_config.json').exists():
        # training runs nest the adapter one level down
        nested = adapter_dir / 'adapter'
        if (nested / 'adapter_config.json').exists():
            adapter_dir = nested
        else:
            raise DeployError(f'no adapter_config.json under {adapter_dir}')
    if not CONVERT_PY.exists() or not (VENDOR_BIN / 'llama-quantize.exe').exists():
        raise DeployError('llama.cpp not vendored — see vendor/llamacpp*')

    DEPLOY_DIR.mkdir(parents=True, exist_ok=True)
    version = _next_version()
    merged = DEPLOY_DIR / f'merged-v{version}'
    f16    = DEPLOY_DIR / f'financial-v{version}-f16.gguf'
    q4     = DEPLOY_DIR / f'financial-v{version}-q4_k_m.gguf'
    name   = f'financial-analyst-v{version}'

    # 1. merge (isolated subprocess: torch memory is released on exit)
    merge_code = (
        'import torch\n'
        'from terminal_in import hw; hw.apply(for_training=True)\n'
        'from peft import AutoPeftModelForCausalLM\n'
        'from transformers import AutoTokenizer\n'
        f'm = AutoPeftModelForCausalLM.from_pretrained(r"{adapter_dir}", dtype=torch.float16)\n'
        f'm.merge_and_unload().save_pretrained(r"{merged}")\n'
        f'AutoTokenizer.from_pretrained(r"{adapter_dir}").save_pretrained(r"{merged}")\n'
    )
    _run([sys.executable, '-X', 'utf8', '-c', merge_code], 'merge')

    # 2. convert to GGUF f16
    _run([sys.executable, '-X', 'utf8', str(CONVERT_PY), str(merged),
          '--outfile', str(f16), '--outtype', 'f16'], 'convert')

    # 3. quantize Q4_K_M
    _run([str(VENDOR_BIN / 'llama-quantize.exe'), str(f16), str(q4), 'Q4_K_M'],
         'quantize')

    # 4. ollama create with the repo system prompt
    modelfile = DEPLOY_DIR / f'Modelfile.v{version}'
    src = MODELFILE.read_text(encoding='utf-8')
    modelfile.write_text(
        re.sub(r'^FROM .*$', f'FROM ./{q4.name}', src, count=1, flags=re.M),
        encoding='utf-8')
    # cwd = deploy dir so the Modelfile's relative FROM path resolves
    _run(['ollama', 'create', name, '-f', modelfile.name], 'create',
         cwd=str(DEPLOY_DIR))

    size_mb = q4.stat().st_size // 1048576
    log.info('deploy complete: %s (%d MB). Switch the planner via the '
             'OLLAMA_MODEL setting when the eval clears it.', name, size_mb)
    return {'model': name, 'gguf': str(q4), 'size_mb': size_mb}
