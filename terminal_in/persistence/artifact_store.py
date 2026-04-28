"""
ArtifactStore — local file-based storage for large artefacts.

Manages:
  artifacts/backtests/       — equity curves, drawdown curves, trade logs (JSON/CSV)
  artifacts/models/          — trained model files (.pkl)
  artifacts/reports/         — generated HTML/PDF reports
  artifacts/strategy_versions/ — strategy parameter snapshots (JSON)
  artifacts/daily_debriefs/  — end-of-day summaries (.md and .json)
  artifacts/exports/         — CSV/Excel exports for external use

All write methods return the Path where the file was saved.
"""

import json
import logging
import pickle
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)

_SUBDIRS = [
    'backtests', 'models', 'reports',
    'strategy_versions', 'daily_debriefs', 'exports',
]


class ArtifactStore:
    def __init__(self, base_dir: str | Path):
        self._base = Path(base_dir)
        self._base.mkdir(parents=True, exist_ok=True)
        for sub in _SUBDIRS:
            (self._base / sub).mkdir(exist_ok=True)
        log.info('ArtifactStore ready at %s', self._base)

    # ── Generic helpers ────────────────────────────────────────────────────

    def save_json(self, category: str, name: str, data: Any) -> Path:
        path = self._base / category / f'{name}.json'
        path.write_text(json.dumps(data, indent=2, default=str), encoding='utf-8')
        return path

    def load_json(self, category: str, name: str) -> Optional[Any]:
        path = self._base / category / f'{name}.json'
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding='utf-8'))
        except Exception:
            log.exception('ArtifactStore: failed to load %s', path)
            return None

    def save_markdown(self, category: str, name: str, content: str) -> Path:
        path = self._base / category / f'{name}.md'
        path.write_text(content, encoding='utf-8')
        return path

    def list_artifacts(self, category: str,
                        suffix: str = '') -> list[Path]:
        d = self._base / category
        pattern = f'*{suffix}' if suffix else '*'
        return sorted(d.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)

    # ── Models ─────────────────────────────────────────────────────────────

    def save_model(self, name: str, obj: Any) -> Path:
        path = self._base / 'models' / f'{name}.pkl'
        path.write_bytes(pickle.dumps(obj, protocol=pickle.HIGHEST_PROTOCOL))
        log.info('ArtifactStore: model saved → %s', path)
        return path

    def load_model(self, name: str) -> Optional[Any]:
        path = self._base / 'models' / f'{name}.pkl'
        if not path.exists():
            return None
        try:
            return pickle.loads(path.read_bytes())
        except Exception:
            log.exception('ArtifactStore: failed to load model %s', name)
            return None

    def model_exists(self, name: str) -> bool:
        return (self._base / 'models' / f'{name}.pkl').exists()

    # ── Backtests ──────────────────────────────────────────────────────────

    def save_backtest(self, run_id: str, data: dict) -> Path:
        """Save full backtest result including equity curve and trade log."""
        return self.save_json('backtests', run_id, data)

    def load_backtest(self, run_id: str) -> Optional[dict]:
        return self.load_json('backtests', run_id)

    def save_equity_curve(self, run_id: str, curve: list[dict]) -> Path:
        """curve: [{date, equity, benchmark_equity}, ...]"""
        return self.save_json('backtests', f'{run_id}_equity_curve', curve)

    def save_drawdown_curve(self, run_id: str, curve: list[dict]) -> Path:
        """curve: [{date, drawdown_pct}, ...]"""
        return self.save_json('backtests', f'{run_id}_drawdown', curve)

    # ── Daily debriefs ─────────────────────────────────────────────────────

    def save_daily_debrief(self, date: str, summary: dict,
                            markdown: Optional[str] = None) -> dict[str, Path]:
        """
        Save daily debrief as both JSON and Markdown.
        Returns dict with 'json' and 'md' paths.
        """
        json_path = self.save_json('daily_debriefs', date, summary)
        md_path = None
        if markdown:
            md_path = self.save_markdown('daily_debriefs', date, markdown)
        return {'json': json_path, 'md': md_path}

    def load_daily_debrief(self, date: str) -> Optional[dict]:
        return self.load_json('daily_debriefs', date)

    def list_daily_debriefs(self) -> list[str]:
        """Return sorted list of debrief dates (most recent first)."""
        paths = self.list_artifacts('daily_debriefs', '.json')
        return [p.stem for p in paths]

    # ── Strategy versions ──────────────────────────────────────────────────

    def save_strategy_version(self, strategy_id: str, version: str,
                               params: dict) -> Path:
        name = f'{strategy_id}_v{version}_{_now_str()}'
        return self.save_json('strategy_versions', name, {
            'strategy_id': strategy_id,
            'version': version,
            'parameters': params,
            'saved_at': _now_str(),
        })

    # ── Reports ────────────────────────────────────────────────────────────

    def save_report(self, name: str, content: str,
                     fmt: str = 'md') -> Path:
        path = self._base / 'reports' / f'{name}.{fmt}'
        path.write_text(content, encoding='utf-8')
        return path

    # ── Exports ────────────────────────────────────────────────────────────

    def save_csv_export(self, name: str, rows: list[dict]) -> Path:
        import csv
        path = self._base / 'exports' / f'{name}.csv'
        if not rows:
            path.write_text('', encoding='utf-8')
            return path
        with path.open('w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        return path

    def path_for(self, category: str, name: str,
                  ext: str = 'json') -> Path:
        """Return the full path for an artifact without writing it."""
        return self._base / category / f'{name}.{ext}'


def _now_str() -> str:
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')
