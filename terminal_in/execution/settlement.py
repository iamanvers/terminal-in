"""
SettlementService — manages the market open/close lifecycle.

Schedule (IST):
  09:14  fire settlement.day_open  → resets daily counters on supervisor
  15:29  square off ONLY MIS (intraday) positions with exit_reason='mis_square_off';
         CNC (delivery) positions CARRY overnight and exit only on SL/target.
         (The legacy 'eod_settlement' bulldozer that closed ALL positions — and
         caused naked single-leg churn — was removed; that reason is now history-only.)
  15:30  record equity snapshot to DB, reset broker's daily_pnl

In paper mode this still runs so that:
  - Positions accumulated through the day are closed at EOD
  - Daily P&L resets cleanly for the next session
  - Equity curve snapshots are recorded
"""

import logging
import uuid
from datetime import datetime, time as dtime, timedelta, timezone
from threading import Event

from terminal_in.bus import bus

log = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

MARKET_OPEN_IST = dtime(9, 14, 0)   # reset counters just before 9:15
EOD_CLOSE_IST   = dtime(15, 29, 0)  # close all positions 1 min before close
EOD_RESET_IST   = dtime(15, 30, 0)  # snapshot equity + reset daily P&L


class SettlementService:
    def __init__(self, db, broker, supervisor, metadata=None):
        self._db         = db
        self._broker     = broker
        self._supervisor = supervisor
        self._metadata   = metadata

        # Tracks which lifecycle events have fired today to prevent double-firing
        self._day_opened: set = set()
        self._day_closed: set = set()
        self._day_reset:  set = set()
        log.info('SettlementService initialised')

    def run(self, stop_event: Event):
        log.info('SettlementService loop started')
        while not stop_event.is_set():
            try:
                self._tick()
            except Exception:
                log.exception('SettlementService tick error')
            stop_event.wait(timeout=30)
        log.info('SettlementService loop stopped')

    def _tick(self):
        now_ist = datetime.now(IST)
        today   = now_ist.date()
        t       = now_ist.time()

        if t >= MARKET_OPEN_IST and today not in self._day_opened:
            self._day_opened.add(today)
            self._on_day_open(today)

        if t >= EOD_CLOSE_IST and today not in self._day_closed:
            self._day_closed.add(today)
            self._on_eod_close(today)

        if t >= EOD_RESET_IST and today not in self._day_reset:
            self._day_reset.add(today)
            self._on_eod_reset(today)

    # ── Lifecycle handlers ─────────────────────────────────────────────────

    def _on_day_open(self, today):
        log.info('Settlement: day open %s — resetting daily counters', today)
        if self._supervisor and hasattr(self._supervisor, 'reset_daily'):
            self._supervisor.reset_daily()
        bus.publish('settlement.day_open', {'date': str(today)})

    def _on_eod_close(self, today):
        """Real settlement mechanics: only MIS (intraday) products are squared
        off by the broker at the close. CNC (delivery) positions CARRY
        overnight and exit only when the market actually trades through their
        stop-loss or target — never by an arbitrary EOD bulldozer."""
        positions = self._broker.open_positions if self._broker else []
        mis = [p for p in positions if p.get('product', 'CNC') == 'MIS']
        cnc = len(positions) - len(mis)
        log.info('Settlement: EOD square-off %d MIS position(s); %d CNC carry overnight (%s)',
                 len(mis), cnc, today)
        for pos in mis:
            bus.publish('trade.close_requested', {
                'trade_id': pos['trade_id'],
                'reason':   'mis_square_off',
            })
        bus.publish('settlement.eod_close', {
            'date':              str(today),
            'positions_closed':  len(mis),
            'positions_carried': cnc,
        })

    def _on_eod_reset(self, today):
        equity    = self._broker.equity    if self._broker else 0.0
        daily_pnl = self._broker._daily_pnl if self._broker else 0.0
        positions = self._broker.open_positions if self._broker else []

        # Mark-to-market the carried positions at the day's closing prices
        unrealized = 0.0
        for pos in positions:
            cached = bus.get_cached(f"ticks.{pos['instrument_id']}") or {}
            last = float(cached.get('last_price') or 0)
            if last > 0:
                sign = 1 if pos['side'] == 'BUY' else -1
                unrealized += sign * (last - pos['entry_price']) * pos['quantity']

        # Record snapshot to DB
        try:
            peak = getattr(self._broker, 'peak_equity', equity)
            dd   = (peak - equity) / peak if peak > 0 else 0.0
            self._db.insert_portfolio_snapshot({
                'snapshot_id':    str(uuid.uuid4()),
                'equity':         equity,
                'daily_pnl':      daily_pnl,
                'unrealized_pnl': round(unrealized, 2),
                'drawdown':       dd,
                'open_positions': len(positions),
            })
        except Exception:
            log.exception('Settlement: failed to record equity snapshot')

        # Reset daily P&L on broker
        if self._broker and hasattr(self._broker, 'reset_daily_pnl'):
            self._broker.reset_daily_pnl()

        log.info('Settlement: EOD reset complete (equity=%.2f daily_pnl=%.2f)', equity, daily_pnl)
        bus.publish('settlement.eod_reset', {
            'date':      str(today),
            'equity':    equity,
            'daily_pnl': daily_pnl,
        })
