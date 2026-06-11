"""
M2 — RiskSupervisor pre-trade gate. 12 checks.
Subscribes to 'strategy.signal', runs all checks, publishes to 'order.approved' or 'order.rejected'.
Persists every decision to risk_decisions + signal_lineage tables.
"""

import logging
import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Optional

import numpy as np

from terminal_in.bus import bus
from terminal_in.agents.control import kill_switch, registry
from terminal_in.risk.event_calendar import calendar as event_cal

log = logging.getLogger(__name__)

MAX_OPEN_POSITIONS = 10
MAX_SECTOR_PCT = 0.40          # max fraction of open positions from one sector
MAX_CORR = 0.85
MAX_DAILY_TRADES_LIVE  = 20
MAX_DAILY_TRADES_PAPER = 200
VIX_HARD_STOP = 35.0
VIX_REDUCE_THRESHOLD = 25.0
MIN_CONFIDENCE = 0.45
SIGNAL_DEDUP_WINDOW_S = 300   # skip re-entry for same instrument within 5 min

# Raw index and VIX tokens are not directly tradeable as cash instruments.
# NIFTY/BANKNIFTY/FINNIFTY are F&O-only; VIX is never tradeable.
# NIFTYBEES (2800641) is an ETF and IS tradeable — not blocked.
NON_TRADEABLE = frozenset({264969, 256265, 260105, 257801})

# Sector resolution lives in the instrument registry (symbol-keyed,
# covers the whole tracked universe) — see data_ingest/instruments.py.
def _sector_of(token: int) -> str:
    from terminal_in.data_ingest.instruments import registry
    return registry.sector(int(token or 0))


def _market_open() -> bool:
    """Module-level wrapper so tests can patch market hours."""
    from terminal_in.market_hours import is_market_open
    return is_market_open()


@dataclass
class GateResult:
    approved: bool
    checks: dict[str, bool]
    reason: Optional[str] = None


class RiskSupervisor:
    def __init__(self, db, config, learner=None):
        self._db = db
        self._config = config
        self._learner = learner   # optional StrategyLearner for adaptive confidence
        self._daily_loss: float = 0.0
        self._daily_trades: int = 0
        self._reset_date: Optional[date] = None
        self._peak_equity: float = config.initial_capital
        self._current_equity: float = config.initial_capital
        self._india_vix: float = 15.0
        self._max_daily_trades = MAX_DAILY_TRADES_LIVE if config.is_live else MAX_DAILY_TRADES_PAPER
        # Dedup: instrument_token → timestamp of last approved signal
        self._last_approved: dict[int, float] = {}

        bus.subscribe('strategy.signal', self._on_signal)
        bus.subscribe('regime.update', self._on_regime_update)
        bus.subscribe('pnl.update', self._on_pnl_update)
        registry.register('GATE', 'system', 'M2 Risk Supervisor')
        log.info('RiskSupervisor initialised (max_daily_trades=%d)', self._max_daily_trades)

    def _on_regime_update(self, payload: dict):
        self._india_vix = float(payload.get('india_vix', self._india_vix))

    def _on_pnl_update(self, payload: dict):
        self._current_equity = float(payload.get('equity', self._current_equity))
        if self._current_equity > self._peak_equity:
            self._peak_equity = self._current_equity
        self._daily_loss = float(payload.get('daily_pnl', self._daily_loss))

    def reset_daily(self):
        """Called by SettlementService at market open to reset daily counters."""
        self._daily_loss = 0.0
        self._daily_trades = 0
        self._reset_date = date.today()
        self._last_approved.clear()
        log.info('RiskSupervisor: daily counters reset')

    def _reset_daily_counters(self):
        today = date.today()
        if self._reset_date != today:
            self._daily_loss = 0.0
            self._daily_trades = 0
            self._reset_date = today

    def _on_signal(self, payload: dict):
        self._reset_daily_counters()

        # Stamp every signal with a stable ID so it can be traced end-to-end
        if 'signal_id' not in payload:
            payload['signal_id'] = str(uuid.uuid4())

        signal_id = payload['signal_id']
        now_ms = int(time.time() * 1000)
        drawdown = (self._peak_equity - self._current_equity) / max(self._peak_equity, 1)

        result = self.gate(payload)

        # ── Persist risk decision ──────────────────────────────────────────
        try:
            self._db.insert_risk_decision({
                'signal_id': signal_id,
                'strategy_id': payload.get('strategy_id'),
                'instrument_token': payload.get('instrument_id'),
                'approved': result.approved,
                'checks': result.checks,
                'reason': result.reason,
                'daily_pnl': self._daily_loss,
                'equity': self._current_equity,
                'drawdown': drawdown,
                'india_vix': self._india_vix,
                'decided_at': now_ms,
            })
        except Exception:
            log.exception('Failed to persist risk decision')

        # ── Create signal lineage record ───────────────────────────────────
        try:
            self._db.insert_signal_lineage({
                'signal_id': signal_id,
                'strategy_id': payload.get('strategy_id'),
                'instrument_token': payload.get('instrument_id'),
                'side': payload.get('side'),
                'generated_at': payload.get('generated_at', now_ms),
                'regime': payload.get('regime'),
                'regime_confidence': payload.get('regime_confidence'),
                'india_vix': self._india_vix,
                'indicators': payload.get('indicators', {}),
                'trigger_rule': payload.get('trigger_rule'),
                'confidence': payload.get('confidence'),
                'risk_approved': result.approved,
                'risk_checks': result.checks,
                'risk_reason': result.reason,
            })
        except Exception:
            log.exception('Failed to persist signal lineage')

        if result.approved:
            bus.publish('order.approved', payload)
        else:
            log.info('Signal REJECTED [%s]: %s', result.reason, payload.get('strategy_id'))
            bus.publish('order.rejected', {
                **payload, 'reason': result.reason, 'checks': result.checks,
            })

    def gate(self, signal: dict) -> GateResult:
        checks: dict[str, bool] = {}
        registry.heartbeat('GATE')

        # 0a. Kill switch — global pause (operator-engaged)
        checks['kill_switch_ok'] = not kill_switch.global_pause
        if not checks['kill_switch_ok']:
            return GateResult(False, checks, 'global_pause_engaged')

        # 0b. Symbol block
        instrument_token = int(signal.get('instrument_id', 0))
        checks['symbol_not_blocked'] = not kill_switch.is_blocked(instrument_token)
        if not checks['symbol_not_blocked']:
            return GateResult(False, checks, f'symbol_blocked={instrument_token}')

        # 0c. Non-tradeable instrument (raw indices are F&O only; VIX is never tradeable)
        checks['tradeable_instrument'] = instrument_token not in NON_TRADEABLE
        if not checks['tradeable_instrument']:
            return GateResult(False, checks, f'non_tradeable={instrument_token}')

        # 0d. Market hours — no fills outside the real NSE session, paper or
        # live. A paper fill at a stale midnight price is noise, not simulation.
        checks['market_open'] = _market_open()
        if not checks['market_open']:
            return GateResult(False, checks, 'market_closed')

        # 1. Event mask — skipped in paper mode (we want continuous signal flow for learning)
        if self._config.is_live:
            mask = event_cal.mask()
            checks['event_mask'] = mask > 0.1
            if not checks['event_mask']:
                return GateResult(False, checks, 'event_blackout')
        else:
            checks['event_mask'] = True

        # 2. VIX hard stop
        checks['vix_hard_stop'] = self._india_vix <= VIX_HARD_STOP
        if not checks['vix_hard_stop']:
            return GateResult(False, checks, f'vix_too_high={self._india_vix:.1f}')

        # 3. Drawdown circuit breaker
        if self._peak_equity > 0:
            dd = (self._peak_equity - self._current_equity) / self._peak_equity
        else:
            dd = 0.0
        checks['drawdown_ok'] = dd < self._config.max_dd
        if not checks['drawdown_ok']:
            return GateResult(False, checks, f'max_dd_breached={dd:.3f}')

        # 4. Daily loss cap
        daily_loss_pct = abs(self._daily_loss) / max(self._current_equity, 1)
        checks['daily_loss_ok'] = daily_loss_pct < self._config.daily_loss_cap
        if not checks['daily_loss_ok']:
            return GateResult(False, checks, f'daily_loss_cap={daily_loss_pct:.3f}')

        # 5. Daily trade count
        checks['trade_count_ok'] = self._daily_trades < self._max_daily_trades
        if not checks['trade_count_ok']:
            return GateResult(False, checks, 'max_daily_trades')

        # 6. Confidence threshold — adaptive per strategy via StrategyLearner
        sid = signal.get('strategy_id', '')
        min_conf = MIN_CONFIDENCE
        if self._learner is not None:
            params = self._learner.get_params(sid)
            min_conf = float(params.get('min_confidence', MIN_CONFIDENCE))

        confidence = float(signal.get('confidence', 0.0))
        checks['confidence_ok'] = confidence >= min_conf
        if not checks['confidence_ok']:
            return GateResult(False, checks, f'low_confidence={confidence:.2f}<{min_conf:.2f}')

        # 7. Max open positions
        open_trades = self._db.get_open_trades() if self._db else []
        checks['position_limit_ok'] = len(open_trades) < MAX_OPEN_POSITIONS
        if not checks['position_limit_ok']:
            return GateResult(False, checks, f'max_positions={len(open_trades)}')

        # 8. Duplicate position check (same instrument already open)
        instrument_id = int(signal.get('instrument_id', 0))
        open_instruments = {int(t.get('instrument_token') or 0) for t in open_trades}
        checks['no_duplicate'] = instrument_id not in open_instruments
        if not checks['no_duplicate']:
            return GateResult(False, checks, f'duplicate_instrument={instrument_id}')

        # 8b. Signal dedup — skip same instrument if approved within SIGNAL_DEDUP_WINDOW_S
        import time as _time_
        now_ts = _time_.time()
        last_ts = self._last_approved.get(instrument_id, 0)
        checks['signal_fresh'] = (now_ts - last_ts) >= SIGNAL_DEDUP_WINDOW_S
        if not checks['signal_fresh']:
            age_s = int(now_ts - last_ts)
            return GateResult(False, checks, f'signal_too_recent={age_s}s')

        # 9. Margin check — per-trade notional ≤ 30% of equity.
        # Price source order: live tick → limit_price → stop_loss. A signal with
        # NO resolvable price is rejected — an unknown notional must never pass.
        qty = int(signal.get('quantity', 0))
        price_approx = 0.0
        try:
            from terminal_in.bus import bus as _bus
            cached_tick = _bus.get_cached(f'ticks.{instrument_id}') or {}
            price_approx = float(cached_tick.get('last_price') or 0.0)
        except Exception:
            pass
        if price_approx <= 0:
            price_approx = float(signal.get('limit_price') or signal.get('stop_loss') or 0.0)
        if price_approx <= 0:
            checks['margin_ok'] = False
            return GateResult(False, checks, 'no_price_for_margin_check')
        notional = qty * price_approx
        max_per_trade = self._current_equity * 0.30
        checks['margin_ok'] = notional <= max_per_trade
        if not checks['margin_ok']:
            return GateResult(False, checks, f'notional_too_large={notional:.0f}>{max_per_trade:.0f}')

        # 10. Sector concentration — reject if adding this position would put >40%
        #     of open positions in the same sector (prevents sector crowding)
        checks['sector_ok'] = self._check_sector(instrument_id, open_trades)
        if not checks['sector_ok']:
            return GateResult(False, checks, f'sector_concentration_limit={MAX_SECTOR_PCT:.0%}')

        # 11. Directional correlation — reject if ≥3 open positions are in the same
        #     sector AND same direction as this signal (avoids crowded one-sided bets)
        checks['correlation_ok'] = True
        if len(open_trades) >= 3:
            checks['correlation_ok'] = self._check_correlation(signal, open_trades)
            if not checks['correlation_ok']:
                return GateResult(False, checks, 'directional_crowding_in_sector')

        # 12. VIX reduce (non-blocking — modifies qty, does NOT reject)
        #     vix_size_reduced=True means size was halved due to elevated VIX
        checks['vix_size_reduced'] = self._india_vix > VIX_REDUCE_THRESHOLD
        if checks['vix_size_reduced']:
            signal['quantity'] = max(int(qty * 0.5), 1)

        self._daily_trades += 1
        self._last_approved[instrument_id] = now_ts
        return GateResult(True, checks)

    def _check_sector(self, instrument_id: int, open_trades: list) -> bool:
        """True if adding this instrument stays within the sector concentration limit."""
        if not open_trades:
            return True
        new_sector = _sector_of(instrument_id)
        if new_sector == 'other':
            log.warning('Sector map has no entry for instrument %d — treating as '
                        "'other' (concentration check is weaker for unmapped symbols)",
                        instrument_id)
        if new_sector == 'index':
            return True   # index instruments not subject to sector cap
        sector_count = sum(
            1 for t in open_trades
            if _sector_of(t.get('instrument_token')) == new_sector
        )
        # After adding this trade: (sector_count + 1) / (total + 1)
        projected_pct = (sector_count + 1) / (len(open_trades) + 1)
        return projected_pct <= MAX_SECTOR_PCT

    def _check_correlation(self, signal: dict, open_trades: list) -> bool:
        """
        True if adding this signal is safe.
        Rejects when ≥3 open positions share the same sector AND same direction —
        that indicates a crowded one-sided bet in the same market segment.
        """
        new_side   = signal.get('side', 'BUY')
        new_sector = _sector_of(signal.get('instrument_id', 0))
        if new_sector == 'index':
            return True

        same_dir_sector = sum(
            1 for t in open_trades
            if (t.get('side', '') == new_side
                and _sector_of(t.get('instrument_token')) == new_sector)
        )
        return same_dir_sector < 3

    @property
    def daily_stats(self) -> dict:
        return {
            'daily_pnl': self._daily_loss,
            'daily_trades': self._daily_trades,
            'equity': self._current_equity,
            'peak_equity': self._peak_equity,
            'drawdown': (self._peak_equity - self._current_equity) / max(self._peak_equity, 1),
            'india_vix': self._india_vix,
        }
