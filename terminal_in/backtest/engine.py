"""
Backtest engine v1 (PRD P2) — replay real daily OHLCV through the
deterministic core of the live pipeline:

  lens signals (S2 52w breakout · S4 RSI reversion · S5 EMA pullback)
    → persistence filter (>=2 consecutive days)
    → deterministic planner bar (EV >= 1.2, conf >= 0.45 — the same
      stricter bar the live planner uses in degraded mode)
    → gate-lite (max positions, sector floor+cap, one position/symbol)
    → fills with next-day open entry, SL/target exits on daily bars
      (stop checked BEFORE target on the same bar — conservative)

Strictly real data: reads ohlcv_1d from the live DB; refuses to run on
fewer than 250 bars per symbol. No lookahead: signals computed on bar t
execute at bar t+1's open.

v1 scope notes (PRD): the LLM planner is represented by its deterministic
degraded bar (replaying actual LLM calls over 2y x 72 symbols is days of
compute); intraday strategies (S1 ORB) need 1m history beyond the 60d we
retain — excluded. Walk-forward = expanding-window yearly splits reported
separately so regime dependence is visible.

CLI:
  .venv/Scripts/python.exe -m terminal_in.backtest.engine            # full run
  .venv/Scripts/python.exe -m terminal_in.backtest.engine --days 250
"""

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

OUT_DIR = Path('./data/backtests')

# Mirror the live bars (signal_filters / planner degraded mode)
MIN_EV         = 1.2
MIN_CONF       = 0.45
PERSIST_N      = 2
MAX_POSITIONS  = 10
SECTOR_CAP     = 0.40
SECTOR_FLOOR   = 2
SLIPPAGE       = 0.0003
COST_PER_TRADE = 20.0
CAPITAL        = 1_000_000.0
RISK_PER_TRADE = 0.05          # 5% of equity notional per position (live default)


@dataclass
class Trade:
    symbol: str
    strategy: str
    side: str
    entry_date: str
    entry: float
    sl: float
    target: float
    qty: int
    exit_date: str = ''
    exit_price: float = 0.0
    exit_reason: str = ''
    pnl: float = 0.0


@dataclass
class Position:
    trade: Trade
    sector: str


def _indicators(df: pd.DataFrame) -> pd.DataFrame:
    c = df['close']
    out = pd.DataFrame(index=df.index)
    out['close'] = c
    out['open'] = df['open']
    out['high'] = df['high']
    out['low'] = df['low']
    delta = c.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    out['rsi'] = (100 - 100 / (1 + rs)).fillna(50)
    out['ema21'] = c.ewm(span=21, adjust=False).mean()
    out['ema50'] = c.ewm(span=50, adjust=False).mean()
    out['hh252'] = c.rolling(252, min_periods=100).max()
    tr = pd.concat([df['high'] - df['low'],
                    (df['high'] - c.shift()).abs(),
                    (df['low'] - c.shift()).abs()], axis=1).max(axis=1)
    out['atr'] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    return out


def _lens_signals(ind: pd.DataFrame) -> pd.DataFrame:
    """Daily lens conditions — same logic family as the live lenses."""
    sig = pd.DataFrame(index=ind.index)
    c, rsi = ind['close'], ind['rsi']
    # S2: 52-week-high breakout (within 1% of the high, trending)
    sig['S2'] = (c >= ind['hh252'] * 0.99) & (c > ind['ema50'])
    # S4: RSI reversion (oversold in an uptrend)
    sig['S4'] = (rsi < 32) & (c > ind['ema50'])
    # S5: EMA pullback (uptrend, pullback to the 21 EMA)
    sig['S5'] = (c > ind['ema50']) & (c < ind['ema21'] * 1.01) & (c > ind['ema21'] * 0.97) & (rsi.between(40, 60))
    return sig


def _confidence(ind_row: pd.Series, lens: str) -> float:
    rsi = float(ind_row['rsi'])
    if lens == 'S4':
        return min(0.9, 0.45 + (32 - rsi) / 40)
    if lens == 'S2':
        return 0.62
    return 0.55


def run_backtest(db=None, days: int = 730, symbols: list[str] | None = None) -> dict:
    if db is None:
        from terminal_in.config import load_config
        from terminal_in.db import DB
        db = DB(load_config().sqlite_path)
    from terminal_in.data_ingest.instruments import KNOWN_TOKENS, registry
    registry.load_stubs()

    eq_tokens = {t: s for s, t in KNOWN_TOKENS.items()
                 if registry.sector(t) not in ('index',)}
    if symbols:
        eq_tokens = {t: s for t, s in eq_tokens.items() if s in symbols}

    all_1d = db.get_ohlcv_1d_all(list(eq_tokens), limit=days + 300)
    data: dict[str, pd.DataFrame] = {}
    for tok, sym in eq_tokens.items():
        df = all_1d.get(tok)
        if df is None or len(df) < 250:
            continue
        ind = _indicators(df)
        ind['sig'] = 0
        data[sym] = pd.concat([ind, _lens_signals(ind)], axis=1)

    if not data:
        raise RuntimeError('backtest: no symbols with >=250 real daily bars')

    # unified calendar (no lookahead: act on t at t+1 open)
    dates = sorted(set().union(*[set(d.index) for d in data.values()]))
    dates = dates[-days:]
    sectors = {s: registry.sector(t) for t, s in eq_tokens.items()}

    equity = CAPITAL
    positions: dict[str, Position] = {}
    closed: list[Trade] = []
    persist: dict[tuple[str, str], int] = {}
    daily_equity: list[tuple[str, float]] = []

    for i, d in enumerate(dates[:-1]):
        nxt = dates[i + 1]
        # ── exits on today's bar ──
        for sym in list(positions):
            pos, df = positions[sym], data[sym]
            if d not in df.index:
                continue
            row = df.loc[d]
            t = pos.trade
            exit_price = None
            if float(row['low']) <= t.sl:
                exit_price, t.exit_reason = t.sl, 'stop_loss'
            elif float(row['high']) >= t.target:
                exit_price, t.exit_reason = t.target, 'target'
            if exit_price is not None:
                fill = exit_price * (1 - SLIPPAGE)
                t.exit_price, t.exit_date = fill, str(d)[:10]
                t.pnl = (fill - t.entry) * t.qty - COST_PER_TRADE
                equity += t.pnl
                closed.append(t)
                del positions[sym]

        # ── new signals on bar d, executed at nxt open ──
        for sym, df in data.items():
            if sym in positions or d not in df.index or nxt not in df.index:
                continue
            row = df.loc[d]
            for lens in ('S2', 'S4', 'S5'):
                if not bool(row[lens]):
                    persist[(sym, lens)] = 0
                    continue
                persist[(sym, lens)] = persist.get((sym, lens), 0) + 1
                if persist[(sym, lens)] < PERSIST_N:
                    continue
                conf = _confidence(row, lens)
                atr = float(row['atr'])
                entry = float(df.loc[nxt]['open']) * (1 + SLIPPAGE)
                sl, target = entry - 1.6 * atr, entry + 2.6 * atr
                rr = (target - entry) / max(entry - sl, 1e-9)
                ev = conf * rr
                if ev < MIN_EV or conf < MIN_CONF:          # planner bar
                    continue
                if len(positions) >= MAX_POSITIONS:          # gate-lite
                    continue
                sec = sectors.get(sym, 'other')
                sec_n = sum(1 for p in positions.values() if p.sector == sec) + 1
                if sec_n > SECTOR_FLOOR and sec_n / (len(positions) + 1) > SECTOR_CAP:
                    continue
                qty = max(1, int((equity * RISK_PER_TRADE) / entry))
                t = Trade(sym, lens, 'BUY', str(nxt)[:10], entry, sl, target, qty)
                positions[sym] = Position(t, sec)
                equity -= COST_PER_TRADE
                break   # one lens per symbol per day

        mark = equity + sum(
            (float(data[s].loc[d]['close']) - p.trade.entry) * p.trade.qty
            for s, p in positions.items() if d in data[s].index)
        daily_equity.append((str(d)[:10], mark))

    return _report(closed, daily_equity, days)


def _report(closed: list[Trade], daily_equity: list, days: int) -> dict:
    eq = pd.Series({d: v for d, v in daily_equity})
    rets = eq.pct_change().dropna()
    dd = (eq / eq.cummax() - 1).min()
    sharpe = float(rets.mean() / rets.std() * np.sqrt(252)) if len(rets) > 20 and rets.std() > 0 else 0.0

    def stats(trades):
        if not trades:
            return {'n': 0}
        wins = [t for t in trades if t.pnl > 0]
        return {'n': len(trades),
                'win_rate': round(len(wins) / len(trades), 3),
                'total_pnl': round(sum(t.pnl for t in trades)),
                'avg_pnl': round(sum(t.pnl for t in trades) / len(trades))}

    per_strategy = {s: stats([t for t in closed if t.strategy == s])
                    for s in sorted({t.strategy for t in closed})}
    # walk-forward visibility: yearly buckets
    by_year: dict[str, list] = {}
    for t in closed:
        by_year.setdefault(t.exit_date[:4], []).append(t)

    result = {
        'ts': int(time.time() * 1000), 'days': days,
        'final_equity': round(float(eq.iloc[-1])) if len(eq) else CAPITAL,
        'return_pct': round((float(eq.iloc[-1]) / CAPITAL - 1) * 100, 2) if len(eq) else 0,
        'max_drawdown_pct': round(float(dd) * 100, 2),
        'sharpe': round(sharpe, 2),
        'trades': stats(closed),
        'per_strategy': per_strategy,
        'walk_forward_years': {y: stats(ts) for y, ts in sorted(by_year.items())},
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f'backtest_{int(time.time())}.json'
    out.write_text(json.dumps(result, indent=1), encoding='utf-8')
    result['path'] = str(out)
    return result


if __name__ == '__main__':
    import argparse
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    ap = argparse.ArgumentParser()
    ap.add_argument('--days', type=int, default=730)
    args = ap.parse_args()
    r = run_backtest(days=args.days)
    print(json.dumps({k: v for k, v in r.items() if k != 'path'}, indent=1))
    print('->', r['path'])
