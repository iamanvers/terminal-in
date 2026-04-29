"""
StrategyLearner — closes the feedback loop between trade outcomes and strategy parameters.

After every REVIEW_EVERY_N trades per strategy:
  - Recomputes min_confidence (tighten when WR is poor, relax when strong)
  - Adjusts SL multiplier (widen when stop-hit rate > 55%)
  - Adjusts target multiplier (reduce when targets rarely reached)
  - Calculates half-Kelly position-size fraction

Gate reads these params instead of hard-coded constants.
DSA is triggered more frequently (every 20 total trades) rather than monthly.
Params persist to the `strategy_params` SQLite table across restarts.
"""

import logging
import time as _time
from typing import Optional

from terminal_in.bus import bus

log = logging.getLogger(__name__)

REVIEW_EVERY_N = 15           # trades per strategy before re-tuning
MIN_TRADES_FOR_TUNING = 5     # guard against overfitting on tiny samples
DSA_REBALANCE_EVERY = 20      # total closed trades before forcing DSA rebalance

CONFIDENCE_FLOOR = 0.30
CONFIDENCE_CEIL  = 0.75
SL_MULT_FLOOR    = 0.8
SL_MULT_CEIL     = 3.0
TGT_MULT_FLOOR   = 1.5
TGT_MULT_CEIL    = 6.0
KELLY_FLOOR      = 0.005   # 0.5 % min
KELLY_CEIL       = 0.20    # 20 % max (half-Kelly applied)

DEFAULT_PARAMS = {
    'min_confidence':   0.45,
    'sl_multiplier':    1.5,
    'target_multiplier': 3.0,
    'kelly_fraction':   0.02,
    'bayes_wr':         0.5,
    'n_trades':         0,
    'updated_at':       0,
}


class StrategyLearner:
    def __init__(self, db, dsa=None):
        self._db  = db
        self._dsa = dsa
        self._params:       dict[str, dict] = {}
        self._batch_counts: dict[str, int]  = {}   # per-strategy since last review
        self._total_closed: int = 0
        self._load_params()
        bus.subscribe('trade.closed', self._on_trade_closed)
        log.info('StrategyLearner initialised (%d param sets loaded)', len(self._params))

    # ── Public API ──────────────────────────────────────────────────────────

    def get_params(self, strategy_id: str) -> dict:
        return self._params.get(strategy_id, DEFAULT_PARAMS.copy())

    def all_params(self) -> list[dict]:
        return [{'strategy_id': sid, **p} for sid, p in self._params.items()]

    # ── Event handling ──────────────────────────────────────────────────────

    def _on_trade_closed(self, trade: dict):
        sid = trade.get('strategy_id', 'MANUAL')
        self._batch_counts[sid] = self._batch_counts.get(sid, 0) + 1
        self._total_closed += 1

        if self._batch_counts[sid] >= REVIEW_EVERY_N:
            self._batch_counts[sid] = 0
            self._tune_strategy(sid)

        # Force DSA rebalance every N total trades — much faster feedback than monthly
        if self._dsa and self._total_closed % DSA_REBALANCE_EVERY == 0:
            from datetime import datetime, timezone
            regime = (bus.get_cached('regime.update') or {}).get('regime', 'sideways')
            try:
                self._dsa._rebalance(datetime.now(timezone.utc), regime)
            except Exception:
                log.exception('StrategyLearner: DSA rebalance failed')

    # ── Core tuning logic ───────────────────────────────────────────────────

    def _tune_strategy(self, strategy_id: str):
        try:
            trades = self._db.get_trades(strategy_id=strategy_id, limit=60)
            closed = [t for t in trades if t.get('exit_price') is not None]
            if len(closed) < MIN_TRADES_FOR_TUNING:
                return

            n     = len(closed)
            wins  = [t for t in closed if (t.get('net_pnl') or 0) > 0]
            losses = [t for t in closed if (t.get('net_pnl') or 0) <= 0]

            # Bayesian win-rate posterior (Beta with uniform prior)
            bayes_wr = (len(wins) + 1) / (n + 2)

            avg_win  = sum(t.get('net_pnl', 0) for t in wins)  / max(len(wins),  1)
            avg_loss = abs(sum(t.get('net_pnl', 0) for t in losses) / max(len(losses), 1))

            # Half-Kelly fraction
            b     = avg_win / max(avg_loss, 1)
            kelly = (b * bayes_wr - (1 - bayes_wr)) / max(b, 0.01)
            kelly = float(max(KELLY_FLOOR, min(KELLY_CEIL, kelly * 0.5)))

            # ── Confidence threshold ─────────────────────────────────────
            cur = self._params.get(strategy_id, DEFAULT_PARAMS.copy())
            cur_conf = cur['min_confidence']
            if bayes_wr < 0.35:
                new_conf = min(CONFIDENCE_CEIL, cur_conf + 0.07)
            elif bayes_wr < 0.45:
                new_conf = min(CONFIDENCE_CEIL, cur_conf + 0.03)
            elif bayes_wr > 0.65:
                new_conf = max(CONFIDENCE_FLOOR, cur_conf - 0.04)
            elif bayes_wr > 0.55:
                new_conf = max(CONFIDENCE_FLOOR, cur_conf - 0.02)
            else:
                new_conf = cur_conf

            # ── SL multiplier ────────────────────────────────────────────
            sl_exits    = sum(1 for t in closed if t.get('exit_reason') == 'stop_loss')
            sl_hit_rate = sl_exits / n
            cur_sl      = cur['sl_multiplier']
            if sl_hit_rate > 0.55:
                new_sl = min(SL_MULT_CEIL, cur_sl * 1.12)
            elif sl_hit_rate < 0.15 and bayes_wr > 0.55:
                new_sl = max(SL_MULT_FLOOR, cur_sl * 0.95)
            else:
                new_sl = cur_sl

            # ── Target multiplier ────────────────────────────────────────
            tgt_hits     = sum(1 for t in closed if t.get('exit_reason') == 'target')
            tgt_hit_rate = tgt_hits / n
            cur_tgt      = cur['target_multiplier']
            if tgt_hit_rate < 0.15 and n >= 15:
                new_tgt = max(TGT_MULT_FLOOR, cur_tgt * 0.92)
            elif tgt_hit_rate > 0.45 and bayes_wr > 0.55:
                new_tgt = min(TGT_MULT_CEIL, cur_tgt * 1.05)
            else:
                new_tgt = cur_tgt

            new_params = {
                'min_confidence':    round(new_conf, 3),
                'sl_multiplier':     round(new_sl,   3),
                'target_multiplier': round(new_tgt,  3),
                'kelly_fraction':    round(kelly,     4),
                'bayes_wr':          round(bayes_wr,  4),
                'n_trades':          n,
                'updated_at':        int(_time.time() * 1000),
            }
            self._params[strategy_id] = new_params
            self._save_params(strategy_id, new_params)

            bus.publish('learner.params_updated', {
                'strategy_id': strategy_id,
                **new_params,
            })
            log.info(
                'StrategyLearner %s → conf=%.3f sl=%.2f× tgt=%.2f× kelly=%.3f '
                '(n=%d wr=%.3f sl_rate=%.2f tgt_rate=%.2f)',
                strategy_id, new_conf, new_sl, new_tgt, kelly,
                n, bayes_wr, sl_hit_rate, tgt_hit_rate,
            )

        except Exception:
            log.exception('StrategyLearner: error tuning %s', strategy_id)

    def _load_params(self):
        try:
            rows = self._db.get_all_strategy_params()
            for row in rows:
                sid = row['strategy_id']
                self._params[sid] = {
                    'min_confidence':    float(row.get('min_confidence',    0.45)),
                    'sl_multiplier':     float(row.get('sl_multiplier',     1.5)),
                    'target_multiplier': float(row.get('target_multiplier', 3.0)),
                    'kelly_fraction':    float(row.get('kelly_fraction',    0.02)),
                    'bayes_wr':          float(row.get('bayes_wr',          0.5)),
                    'n_trades':          int(row.get('n_trades',            0)),
                    'updated_at':        int(row.get('updated_at',          0)),
                }
        except Exception:
            log.exception('StrategyLearner: failed to load params')

    def _save_params(self, strategy_id: str, params: dict):
        try:
            self._db.upsert_strategy_params({'strategy_id': strategy_id, **params})
        except Exception:
            log.exception('StrategyLearner: failed to save params for %s', strategy_id)
