"""
PortfolioLedger — a persistent, human-readable statement of the current
portfolio, written to data/portfolio.md.

Regenerated on every trade open/close and at EOD settlement, so the file on
disk always answers "what do we hold, at what marks, and how did we get
here" without opening the UI. The same data backs the planned HOLDINGS
panel on the EQUITIES and F&O pages (PRD: next build).
"""

import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock

from terminal_in.bus import bus

log = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))
LEDGER_PATH = Path('./data/portfolio.md')
_DEBOUNCE_S = 5.0


class PortfolioLedger:
    def __init__(self, db, broker):
        self._db = db
        self._broker = broker
        self._lock = Lock()
        self._last_write = 0.0

        bus.subscribe('trade.opened', self._on_event)
        bus.subscribe('trade.closed', self._on_event)
        bus.subscribe('settlement.eod_reset', self._on_event)
        # initial statement at boot
        try:
            self.write()
        except Exception:
            log.exception('PortfolioLedger: initial write failed')
        log.info('PortfolioLedger initialised → %s', LEDGER_PATH)

    def _on_event(self, _payload=None):
        now = time.monotonic()
        with self._lock:
            if now - self._last_write < _DEBOUNCE_S:
                return
            self._last_write = now
        try:
            self.write()
        except Exception:
            log.exception('PortfolioLedger: write failed')

    def _mark(self, token: int, fallback: float) -> float:
        tick = bus.get_cached(f'ticks.{token}') or {}
        price = float(tick.get('last_price') or 0)
        return price if price > 0 else fallback

    def write(self) -> Path:
        b = self._broker
        now = datetime.now(IST)
        positions = b.open_positions
        equity = b.equity
        in_use = b.capital_in_use
        cash = b.available_capital

        unrealized = 0.0
        pos_lines = []
        for p in positions:
            mark = self._mark(p['instrument_id'], p['entry_price'])
            sign = 1 if p['side'] == 'BUY' else -1
            upnl = sign * (mark - p['entry_price']) * p['quantity']
            unrealized += upnl
            sym = self._symbol(p['instrument_id'])
            pos_lines.append(
                f"| {sym} | {p['side']} | {p.get('product', 'CNC')} | {p['quantity']} "
                f"| {p['entry_price']:,.2f} | {mark:,.2f} | {upnl:+,.0f} "
                f"| {p.get('stop_loss', 0):,.2f} | {p.get('target', 0):,.2f} |"
            )

        today_start = int(datetime(now.year, now.month, now.day, tzinfo=IST).timestamp() * 1000)
        closed_today = []
        try:
            closed_today = [t for t in self._db.get_closed_trades(limit=100)
                            if (t.get('exit_time') or 0) >= today_start]
        except Exception:
            pass
        realized_today = sum(float(t.get('net_pnl') or 0) for t in closed_today)

        lines = [
            '# Portfolio Statement — TERMINAL//IN',
            '',
            f'_Generated {now.strftime("%d %b %Y, %H:%M:%S IST")} · paper account_',
            '',
            '## Account',
            '',
            '| Metric | Value |',
            '|---|---|',
            f'| Equity | Rs {equity:,.2f} |',
            f'| Cash available | Rs {cash:,.2f} |',
            f'| Capital deployed | Rs {in_use:,.2f} |',
            f'| Unrealized P&L (marked) | Rs {unrealized:+,.2f} |',
            f'| Realized P&L today | Rs {realized_today:+,.2f} ({len(closed_today)} trades) |',
            f'| Peak equity | Rs {b.peak_equity:,.2f} |',
            '',
            f'## Open Holdings ({len(positions)})',
            '',
        ]
        if positions:
            lines += [
                '| Symbol | Side | Product | Qty | Entry | Mark | Unreal P&L | Stop | Target |',
                '|---|---|---|---|---|---|---|---|---|',
                *pos_lines,
            ]
        else:
            lines.append('_Flat — no open positions._')

        if closed_today:
            lines += ['', f'## Closed Today ({len(closed_today)})', '',
                      '| Symbol | Side | Qty | Entry | Exit | Net P&L | Reason |',
                      '|---|---|---|---|---|---|---|']
            for t in closed_today[:20]:
                lines.append(
                    f"| {self._symbol(t.get('instrument_token', 0))} | {t.get('side', '')} "
                    f"| {t.get('quantity', '')} | {float(t.get('entry_price') or 0):,.2f} "
                    f"| {float(t.get('exit_price') or 0):,.2f} "
                    f"| {float(t.get('net_pnl') or 0):+,.0f} | {t.get('exit_reason', '')} |"
                )

        lines += ['', '---',
                  '_Source of truth: `trades` table (SQLite). Equity = initial capital '
                  '+ all realized P&L; recomputed from the database on every restart._', '']

        LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
        LEDGER_PATH.write_text('\n'.join(lines), encoding='utf-8')
        return LEDGER_PATH

    def _symbol(self, token) -> str:
        try:
            from terminal_in.data_ingest.instruments import registry
            return registry.symbol(int(token)) or str(token)
        except Exception:
            return str(token)
