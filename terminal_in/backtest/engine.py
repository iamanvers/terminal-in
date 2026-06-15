"""
Backtest engine v2 (PRD P2) — replay real daily OHLCV through the
deterministic core of the live pipeline, with formula parity against
the live orchestrator (v1 used a fixed R:R that starved S2/S5):

  market regime (heuristic classifier rules on NIFTY 50 + INDIA VIX,
                 3-day hysteresis — i.e. exactly degraded/heuristic mode)
    → lens signals (S2 52w breakout · S4 RSI reversion · S5 EMA pullback
                    · MOM volume surge — live conditions + confidences,
                    regime multiplier applied, WR prior 0.5 ⇒ factor 1.0)
    → EV = avg_conf × R:R × vol_factor × convergence_bonus   (live formula)
    → persistence filter (>=2 consecutive days, same side)
    → deterministic planner bar (EV >= 1.2, conf >= 0.45 — the same
      stricter bar the live planner uses in degraded mode)
    → gate-lite (max positions, sector floor+cap, one position/symbol)
    → fills with next-day open entry, SL/target = ±1.5/2.5 ATR (live),
      exits on daily bars (stop checked BEFORE target — conservative)

Strictly real data: reads ohlcv_1d from the live DB; refuses to run on
fewer than 250 bars per symbol. No lookahead: signals computed on bar t
execute at bar t+1's open; the regime on day t uses closes up to t.

v2 scope notes (PRD): long-only (cash segment — S4/S8 SELL legs and
intraday S1 excluded); the LLM planner is represented by its
deterministic degraded bar; NEWS lens needs historical headlines we
don't retain. Walk-forward = yearly splits reported separately.

CLI:
  .venv/Scripts/python.exe -m terminal_in.backtest.engine            # full run
  .venv/Scripts/python.exe -m terminal_in.backtest.engine --days 250
"""

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

OUT_DIR = Path('./data/backtests')

# Mirror the live bars (orchestrator / signal_filters / planner degraded mode)
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

# orchestrator._REGIME_MULT — confidence multiplier, not a gate
REGIME_MULT = {'strong_bull': 1.20, 'bull': 1.10, 'sideways': 0.90,
               'bear': 0.80, 'strong_bear': 0.70, 'high_vol': 0.75}


@dataclass
class Trade:
    symbol: str
    strategy: str           # lens convergence set, e.g. 'S2+MOM'
    side: str
    entry_date: str
    entry: float
    sl: float
    target: float
    qty: int
    regime: str = ''
    ev: float = 0.0
    exit_date: str = ''
    exit_price: float = 0.0
    exit_reason: str = ''
    pnl: float = 0.0
    judge: str = 'degraded'   # which judge approved this entry: 'llm' | 'degraded'
    size_factor: float = 1.0  # planner size multiplier applied to Kelly qty


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
    vol = df['volume'] if 'volume' in df.columns else pd.Series(0.0, index=df.index)
    out['vol'] = vol
    out['vol_avg20'] = vol.rolling(20, min_periods=5).mean()
    delta = c.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    out['rsi'] = (100 - 100 / (1 + rs)).fillna(50)
    out['ema20'] = c.ewm(span=20, adjust=False).mean()
    out['ema50'] = c.ewm(span=50, adjust=False).mean()
    out['hh252'] = df['high'].rolling(252, min_periods=100).max()
    tr = pd.concat([df['high'] - df['low'],
                    (df['high'] - c.shift()).abs(),
                    (df['low'] - c.shift()).abs()], axis=1).max(axis=1)
    out['atr'] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    return out


# ── Market regime: classifier._classify_heuristic rules + 3-day hysteresis ───

def _regime_series(nifty: pd.DataFrame | None, vix: pd.DataFrame | None) -> dict:
    """date → regime name. Heuristic-mode parity: 21d log-ret vol + 20d return
    + VIX level, raw call only switches after holding 3 consecutive days."""
    if nifty is None or len(nifty) < 30:
        return {}
    close = nifty['close']
    vix_close = vix['close'] if vix is not None else None

    log_rets = np.log(close).diff()
    vol21 = log_rets.rolling(21, min_periods=10).std() * np.sqrt(252)
    ret20 = (close / close.shift(20) - 1).clip(-0.25, 0.25)

    out: dict = {}
    current, pending, pend_n = 'sideways', None, 0
    for d in close.index:
        av = float(vol21.get(d, np.nan))
        r2 = float(ret20.get(d, np.nan))
        vx = float(vix_close.get(d, 0.0)) if vix_close is not None and d in vix_close.index else 0.0
        if np.isnan(r2):
            out[d] = current
            continue
        if vx > 25 or (not np.isnan(av) and av > 0.40):
            raw = 'high_vol'
        elif r2 > 0.06:
            raw = 'strong_bull'
        elif r2 > 0.02:
            raw = 'bull'
        elif r2 < -0.06:
            raw = 'strong_bear'
        elif r2 < -0.02:
            raw = 'bear'
        else:
            raw = 'sideways'
        if raw == current:
            pending, pend_n = None, 0
        elif raw == pending:
            pend_n += 1
            if pend_n >= 3:
                current, pending, pend_n = raw, None, 0
        else:
            pending, pend_n = raw, 1
        out[d] = current
    return out


# ── Lens evaluation: live orchestrator conditions, BUY side ──────────────────

def _lenses(row: pd.Series, regime: str) -> list[tuple[str, float]]:
    """Returns [(lens, confidence)] — confidences mirror orchestrator._scan_symbol
    with strategy WR at the uninformed prior (0.7 + 0.6×0.5 = 1.0)."""
    mult = REGIME_MULT.get(regime, 1.0)
    price, rsi = float(row['close']), float(row['rsi'])
    ema20, ema50 = float(row['ema20']), float(row['ema50'])
    hh252 = float(row['hh252']) if not np.isnan(row['hh252']) else 0.0
    vol_now = float(row['vol'])
    vol_avg = float(row['vol_avg20']) if row['vol_avg20'] and not np.isnan(row['vol_avg20']) else 1.0
    vol_factor = min(2.5, vol_now / max(vol_avg, 1.0))

    out: list[tuple[str, float]] = []

    # S2: 52-week breakout (blocked in bear regimes, like live)
    if hh252 > 0 and price > hh252 * 0.990 and regime not in ('bear', 'strong_bear'):
        vol_ok = vol_now > vol_avg * 1.3
        base = 0.65 if (price >= hh252 and vol_ok) else 0.44
        out.append(('S2', min(base * mult, 0.90)))

    # S4: RSI oversold reversion (fires in all regimes, like live)
    if rsi < 38:
        base = min(0.48 + (38 - rsi) / 38 * 0.38, 0.86)
        out.append(('S4', min(base * mult, 0.90)))

    # S5: EMA pullback in an uptrend
    if price > ema50:
        prox = abs(price - ema20) / max(ema20, 1)
        if prox < 0.025 and 36 <= rsi <= 64:
            base = 0.52 + (1 - prox / 0.025) * 0.15
            out.append(('S5', min(base * mult, 0.90)))

    # MOM: above EMA20 on a volume surge
    if price > ema20 and vol_factor > 1.5:
        cross = (price / ema20 - 1) * 100
        if 0.1 < cross < 2.5:
            out.append(('MOM', min(0.48 * mult, 0.75)))

    return out


def run_backtest(db=None, days: int = 730, symbols: list[str] | None = None,
                 planner: str = 'degraded', max_llm_calls: int = 150,
                 progress_cb=None, should_stop=None) -> dict:
    """Replay the live decision core. `planner`:
      'degraded' — the deterministic planner bar (fast, reproducible; default)
      'llm'      — the REAL TradePlanner LLM judge in the loop (sampled up to
                   max_llm_calls Ollama calls; degraded for batches past budget).
    Both routes go through TradePlanner.judge_batch — true formula parity.

    progress_cb(frac, info) is called periodically (frac 0..1); should_stop() →
    True aborts early and reports the partial result (used by the cancel button)."""
    if db is None:
        from terminal_in.config import load_config
        from terminal_in.db import DB
        db = DB(load_config().sqlite_path)
    from terminal_in.data_ingest.instruments import KNOWN_TOKENS, registry
    registry.load_stubs()

    planner = planner if planner in ('degraded', 'llm') else 'degraded'

    eq_tokens = {t: s for s, t in KNOWN_TOKENS.items()
                 if registry.sector(t) not in ('index',)}
    if symbols:
        eq_tokens = {t: s for t, s in eq_tokens.items() if s in symbols}

    # index series for the market regime + per-day VIX (planner context)
    idx_tokens = [KNOWN_TOKENS.get('NIFTY 50'), KNOWN_TOKENS.get('INDIA VIX')]
    all_1d = db.get_ohlcv_1d_all(list(eq_tokens) + [t for t in idx_tokens if t],
                                 limit=days + 300)
    regimes = _regime_series(all_1d.get(idx_tokens[0]), all_1d.get(idx_tokens[1]))
    vix_df = all_1d.get(idx_tokens[1])
    vix_by_date = {d: float(v) for d, v in vix_df['close'].items()} if vix_df is not None else {}

    data: dict[str, pd.DataFrame] = {}
    for tok, sym in eq_tokens.items():
        df = all_1d.get(tok)
        if df is None or len(df) < 250:
            continue
        data[sym] = _indicators(df)

    if not data:
        raise RuntimeError('backtest: no symbols with >=250 real daily bars')

    # ── the judge: the actual TradePlanner, detached from the live bus ──
    from terminal_in.config import load_config
    from terminal_in.agents.trade_planner import TradePlanner
    judge = TradePlanner(db, load_config(), memory=None, attach_bus=False)
    ollama_ok = False
    if planner == 'llm':
        ollama_ok = judge._ollama_available()
        if ollama_ok:
            judge._warmup()
            log.info('backtest: planner=llm — LLM judge in the loop (budget=%d calls)', max_llm_calls)
        else:
            log.warning('backtest: planner=llm requested but Ollama unavailable → degraded baseline')

    # unified calendar (no lookahead: act on t at t+1 open)
    dates = sorted(set().union(*[set(d.index) for d in data.values()]))
    dates = dates[-days:]
    sectors = {s: registry.sector(t) for t, s in eq_tokens.items()}

    equity = CAPITAL
    positions: dict[str, Position] = {}
    closed: list[Trade] = []
    persist: dict[str, int] = {}            # symbol → consecutive candidate days
    daily_equity: list[tuple[str, float]] = []
    llm_calls = 0                           # batches LLM-judged (sampling counter)
    degraded_calls = 0

    n_steps = len(dates) - 1
    stopped = False
    for i, d in enumerate(dates[:-1]):
        # cooperative cancel — checked EVERY step (cheap), so a cancel lands within
        # one in-flight LLM call (≤ the 25s call timeout), not 15 slow steps later.
        if should_stop is not None and should_stop():
            stopped = True
            log.info('backtest: cancelled at day %d/%d', i, n_steps)
            break
        if i % 10 == 0 and progress_cb is not None:
            progress_cb(i / max(n_steps, 1), {
                'day': i, 'total': n_steps, 'date': str(d)[:10],
                'llm_calls': llm_calls, 'trades': len(closed),
                'open': len(positions)})
        nxt = dates[i + 1]
        regime = regimes.get(d, 'sideways')

        # ── exits on today's bar (stop before target — conservative) ──
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

        # ── eligible candidates on bar d (orchestrator EV bar + persistence) ──
        seen_today: set[str] = set()
        eligible: list[dict] = []
        for sym, df in data.items():
            if d not in df.index or nxt not in df.index:
                continue
            row = df.loc[d]
            lenses = _lenses(row, regime)
            if not lenses:
                continue
            seen_today.add(sym)
            persist[sym] = persist.get(sym, 0) + 1
            if sym in positions or persist[sym] < PERSIST_N:
                continue

            price = float(row['close'])
            atr = float(row['atr'])
            vol_now = float(row['vol'])
            vol_avg = float(row['vol_avg20']) if row['vol_avg20'] and not np.isnan(row['vol_avg20']) else 1.0
            vol_factor = min(2.5, vol_now / max(vol_avg, 1.0))

            avg_conf = sum(c for _, c in lenses) / len(lenses)
            conv_bonus = 1.0 + (len(lenses) - 1) * 0.10
            sl, tgt = price - 1.5 * atr, price + 2.5 * atr      # live multiples
            rr = (tgt - price) / max(price - sl, 1e-9)
            ev = avg_conf * rr * vol_factor * conv_bonus        # live formula

            if ev < MIN_EV or avg_conf < MIN_CONF:              # orchestrator eligibility
                continue
            eligible.append({
                'symbol': sym, 'side': 'BUY', 'ev': round(ev, 3),
                'confidence': round(avg_conf, 3), 'conf_smoothed': round(avg_conf, 3),
                'persistence': persist[sym], 'rr': round(rr, 2), 'rsi': float(row['rsi']),
                'vol_factor': round(vol_factor, 2), 'price': price,
                'lenses': [{'strategy': l} for l, _ in lenses],
                'atr': atr, 'strat': '+'.join(l for l, _ in lenses),
            })

        # ── the judge rules on the batch (LLM sampled within budget, else degraded) ──
        if eligible:
            use_llm = planner == 'llm' and ollama_ok and llm_calls < max_llm_calls
            batch = {
                'scan_id': i, 'regime': regime,
                'india_vix': vix_by_date.get(d, 0.0), 'equity': equity, 'throttle': 0,
                'open_positions': [
                    {'symbol': s, 'side': p.trade.side, 'qty': p.trade.qty,
                     'unrealized': (float(data[s].loc[d]['close']) - p.trade.entry) * p.trade.qty
                                   if d in data[s].index else 0.0}
                    for s, p in positions.items()],
                'candidates': eligible,
            }
            # backtest LLM calls are tight + no-retry so a long horizon doesn't
            # spend 2×60s per batch; verdicts are short so num_predict is small.
            verdicts, mode, _lat = judge.judge_batch(
                batch, use_llm=use_llm, timeout_s=25, retry=False, num_predict=220)
            if mode == 'llm':
                llm_calls += 1
            else:
                degraded_calls += 1

            by_sym = {c['symbol']: c for c in eligible}
            approved = [v for v in verdicts if v.action == 'approve' and v.symbol in by_sym]
            approved.sort(key=lambda v: by_sym[v.symbol]['ev'], reverse=True)
            for v in approved:
                c = by_sym[v.symbol]
                if len(positions) >= MAX_POSITIONS:                  # gate-lite
                    continue
                sec = sectors.get(v.symbol, 'other')
                sec_n = sum(1 for p in positions.values() if p.sector == sec) + 1
                if sec_n > SECTOR_FLOOR and sec_n / (len(positions) + 1) > SECTOR_CAP:
                    continue
                entry = float(data[v.symbol].loc[nxt]['open']) * (1 + SLIPPAGE)
                atr = c['atr']
                sl_f, tgt_f = entry - 1.5 * atr, entry + 2.5 * atr   # re-anchored on fill
                qty = max(1, int((equity * RISK_PER_TRADE) / entry * v.size_factor))
                t = Trade(v.symbol, c['strat'], 'BUY', str(nxt)[:10], entry, sl_f, tgt_f, qty,
                          regime=regime, ev=c['ev'], judge=mode, size_factor=round(v.size_factor, 2))
                positions[v.symbol] = Position(t, sec)
                equity -= COST_PER_TRADE

        # reset persistence for symbols that produced no candidate today
        for sym in list(persist):
            if sym not in seen_today:
                persist[sym] = 0

        mark = equity + sum(
            (float(data[s].loc[d]['close']) - p.trade.entry) * p.trade.qty
            for s, p in positions.items() if d in data[s].index)
        daily_equity.append((str(d)[:10], mark))

    if progress_cb is not None:
        progress_cb(1.0, {'day': n_steps, 'total': n_steps, 'llm_calls': llm_calls,
                          'trades': len(closed), 'open': len(positions)})
    planner_meta = {'mode': planner, 'ollama_available': ollama_ok,
                    'llm_batches': llm_calls, 'degraded_batches': degraded_calls,
                    'llm_budget': max_llm_calls, 'cancelled': stopped}
    return _report(closed, daily_equity, days, regimes, dates, planner_meta)


def _report(closed: list[Trade], daily_equity: list, days: int,
            regimes: dict, dates: list, planner_meta: dict | None = None) -> dict:
    eq = pd.Series({d: v for d, v in daily_equity})
    rets = eq.pct_change().dropna()
    dd = (eq / eq.cummax() - 1).min() if len(eq) else 0.0
    sharpe = float(rets.mean() / rets.std() * np.sqrt(252)) if len(rets) > 20 and rets.std() > 0 else 0.0

    def stats(trades):
        if not trades:
            return {'n': 0}
        wins = [t for t in trades if t.pnl > 0]
        return {'n': len(trades),
                'win_rate': round(len(wins) / len(trades), 3),
                'total_pnl': round(sum(t.pnl for t in trades)),
                'avg_pnl': round(sum(t.pnl for t in trades) / len(trades))}

    # per-lens attribution: a convergence trade credits every member lens
    lens_names = sorted({l for t in closed for l in t.strategy.split('+')})
    per_lens = {l: stats([t for t in closed if l in t.strategy.split('+')])
                for l in lens_names}
    per_regime = {r: stats([t for t in closed if t.regime == r])
                  for r in sorted({t.regime for t in closed})}
    # who judged the entry: 'llm' vs 'degraded' (the v3 agentic-replay split)
    per_judge = {j: stats([t for t in closed if t.judge == j])
                 for j in sorted({t.judge for t in closed})}
    by_year: dict[str, list] = {}
    for t in closed:
        by_year.setdefault(t.exit_date[:4], []).append(t)

    window = [d for d in dates if d in regimes]
    regime_days = pd.Series([regimes[d] for d in window]).value_counts().to_dict() if window else {}

    # Equity curve for charting — downsample to <=300 points so the payload
    # stays small regardless of horizon (10y daily = ~2,470 points).
    curve = [{'date': d, 'equity': round(float(v))} for d, v in daily_equity]
    if len(curve) > 300:
        step = len(curve) // 300 + 1
        curve = curve[::step] + [curve[-1]]

    # Most-recent closed trades (newest first) for the UI table.
    recent = [
        {'symbol': t.symbol, 'lens': t.strategy, 'side': t.side, 'regime': t.regime,
         'entry_date': t.entry_date, 'exit_date': t.exit_date,
         'entry': round(t.entry, 2), 'exit': round(t.exit_price, 2),
         'ev': t.ev, 'exit_reason': t.exit_reason, 'pnl': round(t.pnl),
         'judge': t.judge, 'size_factor': t.size_factor}
        for t in sorted(closed, key=lambda x: x.exit_date, reverse=True)[:60]
    ]

    pm = planner_meta or {'mode': 'degraded'}
    result = {
        'ts': int(time.time() * 1000), 'days': days,
        'engine': f"v3-{pm.get('mode', 'degraded')}",
        'capital': CAPITAL,
        'final_equity': round(float(eq.iloc[-1])) if len(eq) else CAPITAL,
        'return_pct': round((float(eq.iloc[-1]) / CAPITAL - 1) * 100, 2) if len(eq) else 0,
        'max_drawdown_pct': round(float(dd) * 100, 2),
        'sharpe': round(sharpe, 2),
        'trades': stats(closed),
        'per_lens': per_lens,
        'per_regime': per_regime,
        'per_judge': per_judge,
        'planner': pm,
        'regime_days': regime_days,
        'walk_forward_years': {y: stats(ts) for y, ts in sorted(by_year.items())},
        'equity_curve': curve,
        'recent_trades': recent,
        'symbols_tested': len({t.symbol for t in closed}),
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
    ap.add_argument('--planner', choices=['degraded', 'llm'], default='degraded',
                    help="'llm' puts the real Ollama planner in the loop (sampled)")
    ap.add_argument('--max-llm-calls', type=int, default=400)
    args = ap.parse_args()
    r = run_backtest(days=args.days, planner=args.planner, max_llm_calls=args.max_llm_calls)
    print(json.dumps({k: v for k, v in r.items() if k != 'path'}, indent=1))
    print('->', r['path'])
