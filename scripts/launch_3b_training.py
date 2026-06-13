"""One-off launcher: detached full 3B LoRA run via the recursive orchestrator.

Run DETACHED (not Flask-owned) so it survives backend restarts and the exe
boot-test (which needs :5000 free). Writes an initial in-progress row so the
/train history shows it immediately; the orchestrator re-persists final metrics
on completion (INSERT OR REPLACE on run_id).

Recipe (set via env before launching — see the kickoff command):
  LORA_BASE_MODEL=Qwen/Qwen2.5-3B-Instruct  LORA_DTYPE=bf16
  LORA_BATCH_SIZE=1  LORA_GRAD_ACCUM=16  LORA_MAX_SEQ_LEN=384
  HF_HUB_DISABLE_XET=1  HF_HUB_DOWNLOAD_TIMEOUT=30  PYTHONUTF8=1
"""

import os
import time
import uuid

from terminal_in.config import load_config
from terminal_in.db import DB
from terminal_in.agents.training.recursive import TrainingOrchestrator

MAX_STEPS = int(os.environ.get('LORA_MAX_STEPS', '350'))  # ~1 epoch, the proven full-run size


def main() -> None:
    cfg = load_config()
    db = DB(cfg.sqlite_path)
    run_id = time.strftime('%Y%m%d_%H%M%S') + '_3b_' + uuid.uuid4().hex[:4]

    # initial visible row (status 'training') — final metrics overwrite it
    db.insert_training_run({
        'run_id': run_id,
        'started_at': int(time.time() * 1000),
        'status': 'training',
        'max_steps': MAX_STEPS,
    })
    print(f'LAUNCH 3B base={os.environ.get("LORA_BASE_MODEL")} run={run_id} '
          f'steps={MAX_STEPS}', flush=True)

    orch = TrainingOrchestrator(db, cfg)
    orch._run_cycle(run_id, MAX_STEPS)
    print(f'DONE {run_id}', flush=True)


if __name__ == '__main__':
    main()
