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


def _mark(token: int, fallback: float) -> float:
    tick = bus.get_cached(f'ticks.{token}') or {}
    price = float(tick.get('last_price') or 0)
    return price if price > 0 else fallback


def _sym(token) -> str:
    try:
        from terminal_in.data_ingest.instruments import registry
        return registry.symbol(int(token)) or str(token)
    except Exception:
        return str(token)


def build_statement(db, broker) -> dict:
    """The single portfolio assembly — feeds the md ledger, the
    /api/portfolio/holdings endpoint, and the HOLDINGS panels."""
    now = datetime.now(IST)
    holdings = []
    unrealized = 0.0
    for p in broker.open_positions:
        token = p['instrument_id']
        entry = float(p['entry_price'])
        mark = _mark(token, entry)
        sign = 1 if p['side'] == 'BUY' else -1
        upnl = sign * (mark - entry) * p['quantity']
        unrealized += upnl
        notional = entry * p['quantity']
        holdings.append({
            'token':       token,
            'symbol':      _sym(token),
            'side':        p['side'],
            'product':     p.get('product', 'CNC'),
            'quantity':    p['quantity'],
            'entry_price': entry,
            'mark':        mark,
            'unrealized':  upnl,
            'unrealized_pct': (upnl / notional * 100) if notional else 0.0,
            'stop_loss':   float(p.get('stop_loss') or 0),
            'target':      float(p.get('target') or 0),
            'entry_time':  p.get('entry_time'),
            'strategy_id': p.get('strategy_id'),
        })

    today_start = int(datetime(now.year, now.month, now.day, tzinfo=IST).timestamp() * 1000)
    closed_today = []
    try:
        closed_today = [t for t in db.get_closed_trades(limit=100)
                        if (t.get('exit_time') or 0) >= today_start]
    except Exception:
        pass

    # All-time performance, tagged to the starting capital. broker.equity already
    # = initial_capital + every realized net_pnl, so realized_all_time is the
    # locked-in gain from CLOSED trades; total_* folds in open (unrealized) marks.
    initial = float(getattr(broker, 'initial_capital', 0) or 0)
    equity = float(broker.equity)
    realized_all_time = equity - initial
    total_equity = equity + unrealized

    return {
        'generated_at':   int(now.timestamp() * 1000),
        'equity':         equity,
        'initial_capital': initial,
        'cash':           broker.available_capital,
        'deployed':       broker.capital_in_use,
        'unrealized':     unrealized,
        'realized_today': sum(float(t.get('net_pnl') or 0) for t in closed_today),
        'realized_all_time':  realized_all_time,
        'realized_return_pct': (realized_all_time / initial * 100) if initial else 0.0,
        'total_equity':       total_equity,
        'total_return_pct':   ((total_equity - initial) / initial * 100) if initial else 0.0,
        'peak_equity':    broker.peak_equity,
        'holdings':       holdings,
        'closed_today':   closed_today,
    }


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
        return _mark(token, fallback)

    def write(self) -> Path:
        s = build_statement(self._db, self._broker)
        now = datetime.now(IST)
        positions = s['holdings']
        equity, cash, in_use = s['equity'], s['cash'], s['deployed']
        unrealized, realized_today = s['unrealized'], s['realized_today']
        closed_today = s['closed_today']

        pos_lines = [
            f"| {h['symbol']} | {h['side']} | {h['product']} | {h['quantity']} "
            f"| {h['entry_price']:,.2f} | {h['mark']:,.2f} | {h['unrealized']:+,.0f} "
            f"| {h['stop_loss']:,.2f} | {h['target']:,.2f} |"
            for h in positions
        ]

        lines = [
            '# Portfolio Statement — TERMINAL//IN',
            '',
            f'_Generated {now.strftime("%d %b %Y, %H:%M:%S IST")} · paper account_',
            '',
            '## Account',
            '',
            '| Metric | Value |',
            '|---|---|',
            f"| Initial capital | Rs {s['initial_capital']:,.2f} |",
            f'| Equity (realized) | Rs {equity:,.2f} |',
            f"| All-time return (realized) | Rs {s['realized_all_time']:+,.2f} ({s['realized_return_pct']:+.2f}%) |",
            f"| Total incl. open marks | Rs {s['total_equity']:,.2f} ({s['total_return_pct']:+.2f}%) |",
            f'| Cash available | Rs {cash:,.2f} |',
            f'| Capital deployed | Rs {in_use:,.2f} |',
            f'| Unrealized P&L (open) | Rs {unrealized:+,.2f} |',
            f'| Realized P&L today | Rs {realized_today:+,.2f} ({len(closed_today)} trades) |',
            f"| Peak equity | Rs {s['peak_equity']:,.2f} |",
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
