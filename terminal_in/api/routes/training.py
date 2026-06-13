"""Recursive model-training endpoints (Module 4)."""

import json
import logging

from flask import Blueprint, jsonify, request

bp  = Blueprint('training', __name__, url_prefix='/api/training')
log = logging.getLogger(__name__)

_trainer = None
_db      = None


def init(trainer=None, db=None):
    global _trainer, _db
    _trainer = trainer
    _db      = db


@bp.route('/status')
def status():
    if _trainer is None:
        return jsonify({'state': 'unavailable'})
    return jsonify(_trainer.get_state())


@bp.route('/runs')
def runs():
    if _trainer is None:
        return jsonify([])
    limit = int(request.args.get('limit', 20))
    rows = _trainer.get_runs(limit=limit)
    for r in rows:
        if r.get('dataset_counts_json'):
            try:
                r['dataset_counts'] = json.loads(r['dataset_counts_json'])
            except Exception:
                pass
        r.pop('dataset_counts_json', None)
    return jsonify(rows)


@bp.route('/progress')
def progress():
    """Live progress for the newest run — parses run_dir/train.log (tqdm step
    bar + loss lines). Reads the file, not orchestrator state, so it works for
    DETACHED runs (e.g. the long 3B run launched outside Flask) too."""
    import re
    from pathlib import Path
    runs_dir = Path('./data/training/runs')
    if not runs_dir.exists():
        return jsonify({'active': False})
    dirs = sorted([d for d in runs_dir.iterdir() if d.is_dir()],
                  key=lambda d: d.stat().st_mtime, reverse=True)
    for d in dirs[:5]:
        logp = d / 'train.log'
        if not logp.exists():
            continue
        try:
            txt = logp.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            continue
        idx = txt.rfind('Starting training')
        if idx < 0:
            continue                      # model still loading / tokenizing
        seg = txt[idx:]
        # tqdm training bar:  12%|█▏ | 42/350 [12:30<1:30:00, 18.5s/it]
        steps = re.findall(r'(\d+)/(\d+)\s*\[([\d:]+)<([^,]+),\s*([\d.]+)s/it\]', seg)
        losses = re.findall(r"'loss':\s*([\d.]+)", seg)
        done = 'DONE' in txt or 'training complete' in txt.lower()
        last = steps[-1] if steps else None
        return jsonify({
            'active': not done,
            'run_id': d.name,
            'global_step': int(last[0]) if last else 0,
            'max_steps':   int(last[1]) if last else None,
            'elapsed':     last[2] if last else None,
            'eta':         last[3].strip() if last else None,
            'sec_per_step': float(last[4]) if last else None,
            'loss':        float(losses[-1]) if losses else None,
            'losses':      [float(x) for x in losses[-50:]],
            'updated_ms':  int(logp.stat().st_mtime * 1000),
        })
    return jsonify({'active': False})


@bp.route('/start', methods=['POST'])
def start():
    if _trainer is None:
        return jsonify({'ok': False, 'error': 'trainer unavailable'}), 503
    body = request.get_json(silent=True) or {}
    try:
        max_steps = int(body.get('max_steps', -1))
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'invalid max_steps'}), 400
    result = _trainer.start(max_steps=max_steps)
    return jsonify(result), (200 if result.get('ok') else 409)


@bp.route('/stop', methods=['POST'])
def stop():
    if _trainer is None:
        return jsonify({'ok': False, 'error': 'trainer unavailable'}), 503
    return jsonify(_trainer.stop())


# ── Daily reports (on-demand; scheduler fires 08:55 / 15:45 IST itself) ─────

@bp.route('/report/run', methods=['POST'])
def report_run():
    from terminal_in.reporting import daily_report
    body = request.get_json(silent=True) or {}
    kind = body.get('kind', 'eod')
    if kind not in ('pre_open', 'eod'):
        return jsonify({'ok': False, 'error': 'kind must be pre_open|eod'}), 400
    result = daily_report.generate(_db, kind, email=bool(body.get('email', True)))
    return jsonify({'ok': True, **result})

_deploying = {'active': False, 'result': None, 'error': None}


@bp.route('/deploy', methods=['POST'])
def deploy():
    """Deploy a trained adapter as an Ollama model (merge->GGUF->quantize->create).
    Body: {"run_id": "..."} — uses that run's adapter dir. Runs in a worker
    thread; poll GET /api/training/deploy for status."""
    if _db is None:
        return jsonify({'error': 'unavailable'}), 503
    if _deploying['active']:
        return jsonify({'error': 'a deploy is already running'}), 409
    body = request.get_json(silent=True) or {}
    run_id = body.get('run_id', '')
    row = None
    with _db.conn() as c:
        row = c.execute('SELECT adapter_dir, status FROM training_runs WHERE run_id=?',
                        (run_id,)).fetchone()
    if row is None or row['status'] != 'completed' or not row['adapter_dir']:
        return jsonify({'error': f'no completed run with id {run_id}'}), 404

    from threading import Thread
    from terminal_in.agents.training import deploy as _dep

    def _work(adapter_dir):
        try:
            _deploying['result'] = _dep.deploy_adapter(adapter_dir)
        except Exception as e:
            log.exception('deploy failed')
            _deploying['error'] = str(e)[:400]
        finally:
            _deploying['active'] = False

    _deploying.update(active=True, result=None, error=None)
    Thread(target=_work, args=(row['adapter_dir'],), daemon=True, name='deploy').start()
    return jsonify({'ok': True, 'run_id': run_id})


@bp.route('/deploy', methods=['GET'])
def deploy_status():
    return jsonify(_deploying)
