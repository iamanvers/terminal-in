"""
PaperBroker — simulated order execution with realistic fill logic.
Subscribes to 'order.approved', simulates fill, publishes 'trade.opened' / 'trade.closed'.
Monitors open positions for SL/target/time_exit against live ticks.
Writes trade journal entries and updates signal lineage on every fill and close.

Session-persistent: restores open positions and equity from DB on every startup.
"""

import json
import logging
import time
from datetime import datetime, timezone
from threading import Lock
from typing import Optional

from terminal_in.bus import bus
from terminal_in.agents.control import registry

log = logging.getLogger(__name__)

SLIPPAGE_PCT = 0.0003    # 0.03% slippage on fills
COMMISSION = 20.0        # flat ₹20 per order (approximate Zerodha)


class PaperBroker:
    def __init__(self, db, config):
        self._db = db
        self._config = config
        self._positions: dict[str, dict] = {}  # trade_id → position
        self._lock = Lock()
        self._equity = config.initial_capital
        self._daily_pnl = 0.0
        self._peak_equity = config.initial_capital
        self._capital_in_use = 0.0  # sum of (qty × entry_price) for open positions

        registry.register('BROKER', 'system', 'Paper Broker')
        # Restore state from DB so session history survives restarts
        self._restore_from_db()

        bus.subscribe('order.approved', self._on_order)
        bus.subscribe('ticks.*', self._on_tick)
        bus.subscribe('trade.close_requested', self._on_close_requested)
        log.info('PaperBroker initialised (equity=%.2f, open=%d)', self._equity, len(self._positions))

    # ── Session persistence ───────────────────────────────────────────────────

    def _restore_from_db(self):
        try:
            # ── 1. Restore equity from all closed trades ──────────────────────
            all_trades = self._db.get_trades(limit=10_000)
            closed = [t for t in all_trades if t.get('exit_price') is not None]
            realized_pnl = sum(t.get('net_pnl') or 0 for t in closed)
            self._equity = self._config.initial_capital + realized_pnl
            self._peak_equity = max(self._equity, self._config.initial_capital)

            # ── 2. Restore today's daily P&L ──────────────────────────────────
            today_start_ms = int(time.time() * 1000) - 86_400_000
            today_closed = [t for t in closed if (t.get('exit_time') or 0) >= today_start_ms]
            self._daily_pnl = sum(t.get('net_pnl') or 0 for t in today_closed)

            # ── 3. Restore open positions ──────────────────────────────────────
            open_trades = self._db.get_open_trades()
            for t in open_trades:
                # SL/target may be in dedicated columns (new) or metadata_json (old)
                sl = float(t.get('stop_loss') or 0)
                target = float(t.get('target') or 0)
                if not sl and not target:
                    try:
                        meta = json.loads(t.get('metadata_json') or '{}')
                        sl = float(meta.get('stop_loss') or 0)
                        target = float(meta.get('target') or 0)
                    except Exception:
                        pass

                self._positions[t['trade_id']] = {
                    'trade_id':     t['trade_id'],
                    'signal_id':    t.get('signal_id'),
                    'strategy_id':  t.get('strategy_id', ''),
                    'instrument_id': t['instrument_token'],
                    'side':         t['side'],
                    'quantity':     t['quantity'],
                    'entry_price':  t['entry_price'],
                    'stop_loss':    sl,
                    'target':       target,
                    'time_exit':    None,
                    'opened_at':    t.get('opened_at', ''),
                    'regime':       t.get('regime_at_entry', ''),
                    'confidence':   t.get('confidence'),
                    'metadata':     {},
                }

            # Restore capital in use from open positions
            for pos in self._positions.values():
                self._capital_in_use += pos['quantity'] * pos['entry_price']

            if open_trades:
                log.info('PaperBroker: restored %d open positions (in_use=%.0f)',
                         len(open_trades), self._capital_in_use)
            log.info('PaperBroker: equity=%.2f daily_pnl=%.2f peak=%.2f',
                     self._equity, self._daily_pnl, self._peak_equity)

        except Exception:
            log.exception('PaperBroker: failed to restore from DB')

    # ── Order handling ────────────────────────────────────────────────────────

    def _on_order(self, payload: dict):
        side = payload.get('side', 'BUY')
        instrument_id = int(payload.get('instrument_id', 0))
        qty = int(payload.get('quantity', 0))
        if qty <= 0:
            return

        cached = bus.get_cached(f'ticks.{instrument_id}')
        if cached:
            raw_price = float(cached.get('last_price', 0.0))
        else:
            raw_price = float(payload.get('limit_price') or payload.get('stop_loss') or 0.0)

        if raw_price <= 0:
            log.warning('PaperBroker: cannot fill — no price for instrument %d', instrument_id)
            return

        # Capital check: prevent buying beyond available cash
        notional = qty * raw_price
        available = self._equity - self._capital_in_use
        if notional > available * 1.05:  # 5% buffer for price slippage
            log.warning('PaperBroker: REJECTED — insufficient capital %.0f for notional %.0f',
                        available, notional)
            bus.publish('order.rejected', {
                **payload, 'reason': f'insufficient_capital={available:.0f}',
            })
            return

        slippage = raw_price * SLIPPAGE_PCT * (1 if side == 'BUY' else -1)
        fill_price = raw_price + slippage

        trade_id = f"{payload.get('strategy_id','X')}_{instrument_id}_{int(time.time()*1000)}"
        signal_id = payload.get('signal_id')

        position = {
            'trade_id':     trade_id,
            'signal_id':    signal_id,
            'strategy_id':  payload.get('strategy_id', ''),
            'instrument_id': instrument_id,
            'side':         side,
            'quantity':     qty,
            'entry_price':  fill_price,
            'stop_loss':    float(payload.get('stop_loss') or 0),
            'target':       float(payload.get('target') or 0),
            'time_exit':    payload.get('time_exit'),
            'opened_at':    datetime.now(timezone.utc).isoformat(),
            'regime':       payload.get('regime', ''),
            'confidence':   payload.get('confidence'),
            'metadata':     payload.get('metadata', {}),
        }

        with self._lock:
            self._positions[trade_id] = position
            self._capital_in_use += qty * fill_price

        try:
            self._db.insert_trade({
                **position,
                'status': 'open',
                'fill_price': fill_price,
            })
        except Exception:
            log.exception('Failed to persist trade open')

        if signal_id:
            try:
                self._db.update_signal_lineage(
                    signal_id,
                    fill_price=fill_price,
                    fill_time=int(time.time() * 1000),
                    trade_id=trade_id,
                )
            except Exception:
                log.exception('Failed to update signal lineage on fill')

        try:
            self._db.upsert_trade_journal({
                'trade_id': trade_id,
                'entry_reason': (
                    f"{payload.get('strategy_id', 'manual')} signal: "
                    f"{side} {instrument_id} @ {fill_price:.2f}"
                ),
                'strategy_rationale': payload.get('metadata', {}).get('rationale', ''),
                'review_status': 'pending',
            })
        except Exception:
            log.exception('Failed to create trade journal entry')

        bus.publish('trade.opened', position)
        log.info('PAPER FILL: %s %s qty=%d @%.2f', side, trade_id, qty, fill_price)

    # ── Manual close ─────────────────────────────────────────────────────────

    def _on_close_requested(self, payload: dict):
        trade_id = payload.get('trade_id')
        reason   = payload.get('reason', 'manual')
        if not trade_id:
            return
        with self._lock:
            pos = self._positions.get(trade_id)
        if not pos:
            log.warning('PaperBroker: close_requested for unknown trade_id=%s', trade_id)
            return
        instrument_id = pos['instrument_id']
        cached = bus.get_cached(f'ticks.{instrument_id}')
        exit_price = float(cached.get('last_price', pos['entry_price'])) if cached else pos['entry_price']
        self._close_position(trade_id, pos.copy(), exit_price, reason)

    # ── Tick monitoring ───────────────────────────────────────────────────────

    def _on_tick(self, payload: dict):
        token = payload.get('instrument_token') or payload.get('token')
        if token is None:
            return
        price = float(payload.get('last_price', 0))
        if price <= 0:
            return

        to_close = []
        with self._lock:
            for trade_id, pos in list(self._positions.items()):
                if pos['instrument_id'] != token:
                    continue
                exit_reason = self._check_exit(pos, price)
                if exit_reason:
                    to_close.append((trade_id, pos.copy(), price, exit_reason))

        for trade_id, pos, exit_price, reason in to_close:
            self._close_position(trade_id, pos, exit_price, reason)

    def _check_exit(self, pos: dict, price: float) -> Optional[str]:
        side = pos['side']
        sl = pos['stop_loss']
        target = pos['target']

        if side == 'BUY':
            if sl > 0 and price <= sl:
                return 'stop_loss'
            if target > 0 and price >= target:
                return 'target'
        else:
            if sl > 0 and price >= sl:
                return 'stop_loss'
            if target > 0 and price <= target:
                return 'target'

        te = pos.get('time_exit')
        if te:
            try:
                te_dt = datetime.fromisoformat(te) if isinstance(te, str) else te
                if datetime.now(timezone.utc) >= te_dt:
                    return 'time_exit'
            except Exception:
                pass

        return None

    def _close_position(self, trade_id: str, pos: dict,
                         exit_price: float, reason: str):
        with self._lock:
            self._positions.pop(trade_id, None)
            freed = pos['quantity'] * pos['entry_price']
            self._capital_in_use = max(0.0, self._capital_in_use - freed)

        slippage = exit_price * SLIPPAGE_PCT * (-1 if pos['side'] == 'BUY' else 1)
        fill_exit = exit_price + slippage

        qty = pos['quantity']
        sign = 1 if pos['side'] == 'BUY' else -1
        gross_pnl = sign * (fill_exit - pos['entry_price']) * qty
        net_pnl = gross_pnl - COMMISSION * 2

        self._daily_pnl += net_pnl
        self._equity += net_pnl
        if self._equity > self._peak_equity:
            self._peak_equity = self._equity

        closed_at = datetime.now(timezone.utc).isoformat()
        closed_trade = {
            **pos,
            'exit_price':  fill_exit,
            'exit_reason': reason,
            'pnl':         net_pnl,
            'closed_at':   closed_at,
        }

        try:
            self._db.close_trade(trade_id, {
                'exit_price':  fill_exit,
                'pnl':         net_pnl,
                'exit_reason': reason,
                'closed_at':   closed_at,
            })
        except Exception:
            log.exception('Failed to persist trade close')

        signal_id = pos.get('signal_id')
        if signal_id:
            try:
                self._db.update_signal_lineage(
                    signal_id,
                    trade_pnl=net_pnl,
                    trade_exit_reason=reason,
                    trade_closed_at=int(time.time() * 1000),
                )
            except Exception:
                log.exception('Failed to update signal lineage on close')

        try:
            self._db.upsert_trade_journal({
                'trade_id': trade_id,
                'exit_reason': reason,
                'review_status': 'pending',
            })
        except Exception:
            log.exception('Failed to update trade journal on close')

        bus.publish('trade.closed', closed_trade)
        bus.publish('pnl.update', {
            'equity':     self._equity,
            'daily_pnl':  self._daily_pnl,
        })

        log.info('PAPER CLOSE: %s reason=%s pnl=%.2f equity=%.2f',
                 trade_id, reason, net_pnl, self._equity)

    def reset_daily_pnl(self):
        self._daily_pnl = 0.0

    @property
    def equity(self) -> float:
        return self._equity

    @property
    def peak_equity(self) -> float:
        return self._peak_equity

    @property
    def daily_pnl(self) -> float:
        return self._daily_pnl

    @property
    def available_capital(self) -> float:
        return max(0.0, self._equity - self._capital_in_use)

    @property
    def capital_in_use(self) -> float:
        return self._capital_in_use

    @property
    def open_positions(self) -> list[dict]:
        with self._lock:
            return list(self._positions.values())
