"""
DecisionMemory — persistent audit trail of every agent trade decision,
with hindsight evaluation of the roads not taken.

Every scan's candidates and planner verdicts land in the agent_decisions
table. A background loop later re-prices each decision: did a rejected
candidate go on to hit its target ("would_win"), its stop ("would_lose"),
or neither ("flat")? Fired decisions are joined to actual trade P&L.

context_block() compresses recent decisions + rejection-hindsight stats
into a few prompt lines for the TradePlanner, closing the feedback loop:
the LLM judge sees how its past calls worked out.
"""

import json
import logging
import time
import uuid
from threading import Event

from terminal_in.bus import bus

log = logging.getLogger(__name__)

HINDSIGHT_MIN_AGE_S  = 4 * 3600    # don't judge a decision younger than 4h
HINDSIGHT_MAX_AGE_S  = 72 * 3600   # too old to re-price reliably
HINDSIGHT_LOOP_S     = 900         # evaluation cadence
WIN_FRACTION         = 0.6         # ret >= 60% of target distance → would_win
LOSS_FRACTION        = 0.6         # ret <= -60% of SL distance → would_lose


class DecisionMemory:
    def __init__(self, db):
        self._db = db

    # ── Recording ──────────────────────────────────────────────────────────

    def record_scan(self, scan_id: int, candidates: list[dict],
                    verdicts: dict[str, dict], mode: str,
                    latency_ms: int | None,
                    regime: str, india_vix: float) -> None:
        """
        candidates: actionable candidate dicts from the orchestrator (annotated
        by CandidateTracker). verdicts: {symbol: {action, reason, size_factor,
        signal_id?}} — covers fired/approved/rejected/filtered.
        """
        now_ms = int(time.time() * 1000)
        rows = []
        for c in candidates:
            symbol = c.get('symbol', '?')
            v = verdicts.get(symbol, {})
            price = float(c.get('price') or 0.0)
            sl    = float(c.get('suggested_sl') or 0.0)
            tgt   = float(c.get('suggested_target') or 0.0)
            rows.append({
                'decision_id':       uuid.uuid4().hex[:16],
                'scan_id':           scan_id,
                'decided_at':        now_ms,
                'instrument_token':  int(c.get('token') or 0),
                'symbol':            symbol,
                'side':              c.get('side', '?'),
                'ev':                float(c.get('ev') or 0.0),
                'confidence':        float(c.get('confidence') or 0.0),
                'persistence':       int(c.get('persistence') or 0),
                'price_at_decision': price,
                'sl_pct':            abs(price - sl) / price if price > 0 and sl > 0 else None,
                'target_pct':        abs(tgt - price) / price if price > 0 and tgt > 0 else None,
                'lenses_json':       json.dumps([l.get('strategy') for l in c.get('lenses', [])]),
                'regime':            regime,
                'india_vix':         india_vix,
                'planner_action':    v.get('action', 'filtered'),
                'planner_reason':    v.get('reason', c.get('filter_reason', '')),
                'size_factor':       float(v.get('size_factor', 1.0)),
                'planner_mode':      mode,
                'llm_latency_ms':    latency_ms,
                'signal_id':         v.get('signal_id'),
            })
        try:
            self._db.insert_agent_decisions(rows)
        except Exception:
            log.exception('DecisionMemory: failed to persist %d decisions', len(rows))

    # ── Prompt context ─────────────────────────────────────────────────────

    def context_block(self, n: int = 10) -> str:
        """Compact text block of recent decided-and-judged decisions for the
        planner prompt, plus aggregate rejection-hindsight stats."""
        try:
            recent = self._db.get_recent_agent_decisions(limit=80)
        except Exception:
            return ''

        lines = []
        judged = [d for d in recent if d.get('hindsight_outcome')]
        for d in judged[:n]:
            ret = d.get('hindsight_ret_pct')
            ret_s = f'{ret*100:+.1f}%' if ret is not None else '?'
            lines.append(
                f"{d['symbol']} {d['side']} {d['planner_action']}"
                f"{' (' + (d.get('planner_reason') or '')[:40] + ')' if d.get('planner_reason') else ''}"
                f" -> {ret_s} {d['hindsight_outcome']}"
            )

        rejected = [d for d in judged if d['planner_action'] in ('reject', 'filtered')]
        if rejected:
            ww = sum(1 for d in rejected if d['hindsight_outcome'] == 'would_win')
            wl = sum(1 for d in rejected if d['hindsight_outcome'] == 'would_lose')
            fl = len(rejected) - ww - wl
            lines.append(f'Recent rejections hindsight: {ww} would-win / {wl} would-lose / {fl} flat')

        return '\n'.join(lines)

    # ── Hindsight loop ─────────────────────────────────────────────────────

    def run_hindsight(self, stop_event: Event):
        log.info('DecisionMemory hindsight loop started (every %ds)', HINDSIGHT_LOOP_S)
        while not stop_event.is_set():
            try:
                self._evaluate_pending()
            except Exception:
                log.exception('Hindsight evaluation failed (non-fatal)')
            stop_event.wait(HINDSIGHT_LOOP_S)

    def _evaluate_pending(self):
        now_ms = int(time.time() * 1000)
        pending = self._db.get_decisions_pending_hindsight(
            older_than_ms=now_ms - HINDSIGHT_MIN_AGE_S * 1000,
            newer_than_ms=now_ms - HINDSIGHT_MAX_AGE_S * 1000,
        )
        if not pending:
            return

        judged = 0
        for d in pending:
            price0 = float(d.get('price_at_decision') or 0.0)
            if price0 <= 0:
                self._db.update_decision_hindsight(d['decision_id'], 0.0, 'flat')
                continue

            # Fired decisions: join to the actual trade outcome via signal lineage
            if d.get('signal_id'):
                outcome = self._actual_outcome(d['signal_id'])
                if outcome is not None:
                    self._db.update_decision_hindsight(d['decision_id'], outcome[0], outcome[1])
                    judged += 1
                    continue
                # trade still open — leave pending for the next pass

            price_now = self._current_price(int(d['instrument_token']))
            if price_now <= 0:
                continue

            sign = 1.0 if d['side'] == 'BUY' else -1.0
            ret = sign * (price_now - price0) / price0

            tgt_pct = float(d.get('target_pct') or 0.02)
            sl_pct  = float(d.get('sl_pct') or 0.012)
            if ret >= WIN_FRACTION * tgt_pct:
                outcome_s = 'would_win'
            elif ret <= -LOSS_FRACTION * sl_pct:
                outcome_s = 'would_lose'
            else:
                outcome_s = 'flat'
            self._db.update_decision_hindsight(d['decision_id'], round(ret, 5), outcome_s)
            judged += 1

        if judged:
            log.info('Hindsight: judged %d decisions', judged)

    def _actual_outcome(self, signal_id: str) -> tuple[float, str] | None:
        try:
            lineage = self._db.get_signal_lineage(signal_id)
            if not lineage:
                return None
            pnl = lineage.get('trade_pnl')
            if pnl is None:
                return None
            return (float(pnl), 'actual_win' if float(pnl) > 0 else 'actual_loss')
        except Exception:
            return None

    def _current_price(self, token: int) -> float:
        tick = bus.get_cached(f'ticks.{token}') or {}
        price = float(tick.get('last_price') or 0.0)
        if price > 0:
            return price
        try:
            df = self._db.get_ohlcv_1d(token, limit=1)
            if df is not None and not df.empty:
                return float(df['close'].iloc[-1])
        except Exception:
            pass
        return 0.0
