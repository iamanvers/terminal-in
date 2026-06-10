"""
TrainingOrchestrator — the recursive model-improvement loop (Module 4).

Each cycle:
  1. build_dataset — rebuilds the SFT dataset including the NEWEST closed
     trades and hindsight-judged planner decisions (the system learns from
     its own trading record, not just static corpora)
  2. train — LoRA fine-tune in a SUBPROCESS (keeps the multi-GB model and
     CPU burn out of the backend process) into data/training/runs/<run_id>/
  3. collect — parses trainer_state.json for real loss metrics; no metric
     is ever fabricated — a run without metrics is recorded as such
  4. record — persists the run to the training_runs table and publishes
     'training.status' so the UI tracks progress live

Deploying a finished adapter to Ollama (merge → GGUF → ollama create) is a
separate manual step until llama.cpp is set up — see train_lora.py notes.

Trigger: POST /api/training/start (optionally max_steps for a smoke run).
One run at a time; a second start request while running is rejected.
"""

import json
import logging
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from threading import Lock, Thread

from terminal_in.bus import bus
from terminal_in.agents.control import registry

log = logging.getLogger(__name__)

RUNS_DIR = Path('./data/training/runs')


class TrainingOrchestrator:
    def __init__(self, db, config):
        self._db     = db
        self._config = config
        self._lock   = Lock()
        self._state  = 'idle'   # idle | building_dataset | training | collecting | completed | failed
        self._current_run: dict | None = None
        self._proc: subprocess.Popen | None = None

        registry.register('TRAINER', 'system', 'Recursive Model Training')
        log.info('TrainingOrchestrator initialised')

    # ── Public API ───────────────────────────────────────────────────────────

    def get_state(self) -> dict:
        with self._lock:
            return {
                'state':       self._state,
                'current_run': dict(self._current_run) if self._current_run else None,
            }

    def start(self, max_steps: int = -1) -> dict:
        """Kick off a training cycle. Returns {'ok': bool, 'run_id'|'error'}."""
        with self._lock:
            if self._state not in ('idle', 'completed', 'failed'):
                return {'ok': False, 'error': f'run already in progress ({self._state})'}
            run_id = time.strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:6]
            self._state = 'building_dataset'
            self._current_run = {
                'run_id':     run_id,
                'started_at': int(time.time() * 1000),
                'max_steps':  max_steps,
                'status':     'building_dataset',
            }
        Thread(target=self._run_cycle, args=(run_id, max_steps),
               daemon=True, name=f'training-{run_id}').start()
        return {'ok': True, 'run_id': run_id}

    def stop(self) -> dict:
        """Abort the in-flight training subprocess (dataset step can't be aborted)."""
        with self._lock:
            proc = self._proc
        if proc is not None and proc.poll() is None:
            proc.kill()
            return {'ok': True, 'action': 'killed'}
        return {'ok': False, 'error': 'no training subprocess running'}

    # ── Cycle ────────────────────────────────────────────────────────────────

    def _run_cycle(self, run_id: str, max_steps: int):
        run_dir     = RUNS_DIR / run_id
        dataset_dir = run_dir / 'dataset'
        adapter_dir = run_dir / 'adapter'
        record: dict = {
            'run_id':     run_id,
            'started_at': int(time.time() * 1000),
            'max_steps':  max_steps,
            'dataset_dir': str(dataset_dir),
            'adapter_dir': str(adapter_dir),
        }
        try:
            # 1 — dataset (in-process: light, mostly DB reads + HF cache)
            self._set_state('building_dataset', record)
            from terminal_in.agents.training.prepare_dataset import prepare
            counts = prepare(output_dir=dataset_dir)
            record['dataset_counts'] = counts
            record['dataset_samples'] = counts.get('total', 0)
            log.info('Training %s: dataset built — %s', run_id, counts)

            # 2 — train in a subprocess
            self._set_state('training', record)
            env = {
                **os.environ,
                'PYTHONUTF8':       '1',
                'LORA_DATASET_DIR': str(dataset_dir),
                'LORA_OUTPUT_DIR':  str(adapter_dir),
                'LORA_MAX_STEPS':   str(max_steps),
            }
            log_path = run_dir / 'train.log'
            with open(log_path, 'w', encoding='utf-8') as log_f:
                proc = subprocess.Popen(
                    [sys.executable, '-X', 'utf8', '-m',
                     'terminal_in.agents.training.train_lora'],
                    stdout=log_f, stderr=subprocess.STDOUT, env=env,
                )
                with self._lock:
                    self._proc = proc
                rc = proc.wait()
            with self._lock:
                self._proc = None
            record['train_log'] = str(log_path)
            if rc != 0:
                raise RuntimeError(f'train_lora subprocess exited {rc} — see {log_path}')

            # 3 — collect real metrics from trainer output
            self._set_state('collecting', record)
            metrics = self._collect_metrics(adapter_dir)
            record.update(metrics)

            record['status'] = 'completed'
            record['finished_at'] = int(time.time() * 1000)
            self._set_state('completed', record)
            log.info('Training %s COMPLETE — loss=%s steps=%s',
                     run_id, record.get('final_loss'), record.get('trained_steps'))
        except Exception as e:
            record['status'] = 'failed'
            record['error'] = str(e)[:500]
            record['finished_at'] = int(time.time() * 1000)
            self._set_state('failed', record)
            log.exception('Training %s FAILED', run_id)
        finally:
            self._persist(record)
            registry.heartbeat('TRAINER')

    def _collect_metrics(self, adapter_dir: Path) -> dict:
        """Parse trainer_state.json (written by transformers Trainer) for the
        real loss curve. Returns {} fields as None when unavailable — never
        fabricated."""
        out = {'final_loss': None, 'trained_steps': None, 'epochs': None}
        try:
            candidates = sorted(adapter_dir.rglob('trainer_state.json'),
                                key=lambda p: p.stat().st_mtime, reverse=True)
            if not candidates:
                return out
            state = json.loads(candidates[0].read_text(encoding='utf-8'))
            losses = [h['loss'] for h in state.get('log_history', []) if 'loss' in h]
            if losses:
                out['final_loss'] = round(float(losses[-1]), 4)
                out['initial_loss'] = round(float(losses[0]), 4)
            out['trained_steps'] = state.get('global_step')
            out['epochs'] = state.get('epoch')
        except Exception:
            log.exception('Could not parse trainer_state.json')
        return out

    # ── State + persistence ──────────────────────────────────────────────────

    def _set_state(self, state: str, record: dict):
        with self._lock:
            self._state = state
            record['status'] = state if state not in ('completed', 'failed') else record.get('status', state)
            self._current_run = dict(record)
        bus.publish('training.status', {'state': state, 'run': dict(record)})

    def _persist(self, record: dict):
        try:
            self._db.insert_training_run(record)
        except Exception:
            log.exception('Failed to persist training run %s', record.get('run_id'))

    def get_runs(self, limit: int = 20) -> list[dict]:
        try:
            return self._db.get_training_runs(limit=limit)
        except Exception:
            return []
