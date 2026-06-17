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

from terminal_in.execution.costs import cost_breakdown

log = logging.getLogger(__name__)

OUT_DIR = Path('./data/backtests')

# Mirror the live bars (orchestrator / signal_filters / planner degraded mode)
MIN_EV         = 1.2
MIN_CONF       = 0.45
PERSIST_N      = 2
MAX_POSITIONS  = 10
SECTOR_CAP     = 0.40
SECTOR_FLOOR   = 2
SLIPPAGE       = 0.0003        # price adjustment on the fill — NOT a fee (see costs.py)
CAPITAL        = 1_000_000.0
RISK_PER_TRADE = 0.05          # 5% of equity notional per position (live default)

# Hand-tuned lens/exit parameters (NOT fit out-of-sample — see validation.py
# robustness test). Promoted to module globals so the alpha-validation harness
# can perturb them ±20% one at a time and map the net-Sharpe surface.
EMA_FAST     = 20              # fast EMA span (S5 pullback proximity, MOM trigger)
EMA_SLOW     = 50             # slow EMA span (S5 uptrend filter)
RSI_OVERSOLD = 38             # S4 oversold reversion threshold
ATR_SL_MULT  = 1.5           # stop-loss = entry - ATR_SL_MULT × ATR
ATR_TGT_MULT = 2.5           # target    = entry + ATR_TGT_MULT × ATR

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
    pnl: float = 0.0          # NET of all-in transaction costs (both legs)
    judge: str = 'degraded'   # which judge approved this entry: 'llm' | 'degraded'
    size_factor: float = 1.0  # planner size multiplier applied to Kelly qty
    segment: str = 'CNC'      # CNC (delivery) | MIS (intraday) — drives cost model
    cost: float = 0.0         # all-in round-trip transaction cost (entry + exit legs)


@dataclass
class Position:
    trade: Trade
    sector: str


@dataclass
class _Approve:
    """Stand-in verdict for the lenses-only (planner='none') baseline — accept
    the candidate at full size, no judge. Duck-types TradePlanner's Verdict
    (symbol / action / size_factor) for the shared approval loop."""
    symbol: str
    action: str = 'approve'
    size_factor: float = 1.0


def _split_by_conf_gate(eligible: list, gate: float):
    """Split eligible candidates by the LLM confidence gate (planner='llm').
    strong (smoothed conf >= gate) clear the heuristic and are auto-approved with
    NO LLM call; ambiguous (< gate) are batched to the judge. gate <= 0 disables
    the split (everything is ambiguous → the LLM judges the whole batch)."""
    if gate <= 0.0:
        return [], list(eligible)
    strong    = [c for c in eligible if c['conf_smoothed'] >= gate]
    ambiguous = [c for c in eligible if c['conf_smoothed'] <  gate]
    return strong, ambiguous


def _segment(strat: str) -> str:
    """Cost segment for a backtest trade. Only S1 (opening-range breakout) is
    intraday (MIS); every other lens / strategy here is positional delivery
    (CNC) — the backtest carries positions overnight to SL/target, no EOD
    square-off, so CNC is the honest default."""
    return 'MIS' if 'S1' in strat.split('+') else 'CNC'


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
    out['ema20'] = c.ewm(span=EMA_FAST, adjust=False).mean()
    out['ema50'] = c.ewm(span=EMA_SLOW, adjust=False).mean()
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
    if rsi < RSI_OVERSOLD:
        base = min(0.48 + (RSI_OVERSOLD - rsi) / RSI_OVERSOLD * 0.38, 0.86)
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
                 progress_cb=None, should_stop=None, signals: str = 'lenses',
                 full_trades: bool = False, ev_override=None, competence_gate=None,
                 ev_min_override: float = 0.5, llm_conf_gate: float = 0.60) -> dict:
    """Replay the live decision core. `planner`:
      'degraded' — the deterministic planner bar (fast, reproducible; default)
      'llm'      — the REAL TradePlanner LLM judge in the loop (sampled up to
                   max_llm_calls Ollama calls; degraded for batches past budget).
    Both routes go through TradePlanner.judge_batch — true formula parity.

    llm_conf_gate (planner='llm' only): heuristic-confidence gate for the LLM.
    Candidates whose smoothed confidence is >= this clear the heuristic on their
    own and are auto-approved deterministically — no LLM call. Only the AMBIGUOUS
    remainder (below the gate) is batched to the LLM, and a scan with no ambiguous
    candidate spends NO budget. Set 0.0 to disable (LLM judges every batch, the
    old behavior). Backtest-only; the live planner path is unchanged.

    progress_cb(frac, info) is called periodically (frac 0..1); should_stop() →
    True aborts early and reports the partial result (used by the cancel button)."""
    if db is None:
        from terminal_in.config import load_config
        from terminal_in.db import DB
        db = DB(load_config().sqlite_path)
    from terminal_in.data_ingest.instruments import KNOWN_TOKENS, registry
    registry.load_stubs()

    planner = planner if planner in ('none', 'degraded', 'llm') else 'degraded'

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

    # unified calendar (no lookahead: act on t at t+1 open)
    dates = sorted(set().union(*[set(d.index) for d in data.values()]))
    dates = dates[-days:]
    sectors = {s: registry.sector(t) for t, s in eq_tokens.items()}

    # signals='strategies' → replay the REAL strategy_engine classes (S2/S3/S4/S5/
    # S8 daily) via a historical MarketContext, instead of the orchestrator-lens
    # mirror. Zero formula drift — it calls each strategy's own evaluate().
    if signals == 'strategies':
        return _strategy_engine_backtest(
            data, all_1d, eq_tokens, sectors, regimes, vix_by_date, dates, days,
            idx_tokens, progress_cb, should_stop)

    # ── the judge: the actual TradePlanner, detached from the live bus ──
    # planner='none' is the LENSES-ONLY baseline: skip the judge entirely and
    # accept every eligible candidate (orchestrator EV bar already applied) —
    # used by the validation harness to isolate the planner's marginal value.
    from terminal_in.config import load_config
    from terminal_in.agents.trade_planner import TradePlanner
    judge = None if planner == 'none' else TradePlanner(db, load_config(), memory=None, attach_bus=False)
    ollama_ok = False
    if planner == 'llm':
        ollama_ok = judge._ollama_available()
        if ollama_ok:
            judge._warmup()
            log.info('backtest: planner=llm — LLM judge in the loop (budget=%d calls)', max_llm_calls)
        else:
            log.warning('backtest: planner=llm requested but Ollama unavailable → degraded baseline')

    equity = CAPITAL
    positions: dict[str, Position] = {}
    closed: list[Trade] = []
    persist: dict[str, int] = {}            # symbol → consecutive candidate days
    daily_equity: list[tuple[str, float]] = []
    llm_calls = 0                           # batches LLM-judged (sampling counter)
    degraded_calls = 0
    llm_strong_skipped = 0                  # candidates auto-approved past the conf gate (no LLM)
    llm_gate_active = planner == 'llm' and llm_conf_gate > 0.0
    ev_source_counts: dict[str, int] = {}   # M6: 'gbt' | 'heuristic' candidate counts

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
                t.cost += cost_breakdown(fill * t.qty, 'SELL', t.segment)['total']
                t.pnl = (fill - t.entry) * t.qty - t.cost
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
            sl, tgt = price - ATR_SL_MULT * atr, price + ATR_TGT_MULT * atr   # live multiples
            rr = (tgt - price) / max(price - sl, 1e-9)
            ev = avg_conf * rr * vol_factor * conv_bonus        # live (heuristic) formula

            # ── Module 6 hooks (forward-looking judge — Phase C/D₀) ──
            # score/bar default to the heuristic EV; an EV head (D₀) replaces both
            # the value AND the eligibility bar (P-scale, not EV-scale); a
            # competence gate (C) down-weights or ABSTAINS. Never bypass M2 (later).
            lens_names = [l for l, _ in lenses]
            score, bar, ev_src = ev, MIN_EV, 'heuristic'
            ds = str(d)[:10]
            if competence_gate is not None:
                w = competence_gate(lens_names, regime, ds)
                if w is not None and w <= 0.0:
                    continue                                    # abstain
                if w is not None:
                    score *= w
            if ev_override is not None:
                feat = {'symbol': sym, 'ev': ev, 'confidence': avg_conf,
                        'persistence': persist[sym], 'rr': rr, 'rsi': float(row['rsi']),
                        'vol_factor': vol_factor, 'regime': regime,
                        'sector': sectors.get(sym, 'other'), 'n_lenses': len(lenses),
                        'lens_set': '+'.join(sorted(lens_names))}
                ovr = ev_override(feat, ds)
                if ovr is not None:
                    score, bar, ev_src = float(ovr), ev_min_override, 'gbt'

            if score < bar or avg_conf < MIN_CONF:              # eligibility
                continue
            ev_source_counts[ev_src] = ev_source_counts.get(ev_src, 0) + 1
            eligible.append({
                'symbol': sym, 'side': 'BUY', 'ev': round(score, 3),
                'confidence': round(avg_conf, 3), 'conf_smoothed': round(avg_conf, 3),
                'persistence': persist[sym], 'rr': round(rr, 2), 'rsi': float(row['rsi']),
                'vol_factor': round(vol_factor, 2), 'price': price,
                'lenses': [{'strategy': l} for l, _ in lenses],
                'atr': atr, 'strat': '+'.join(l for l, _ in lenses),
            })

        # ── the judge rules on the batch (LLM sampled within budget, else degraded) ──
        if eligible:
            by_sym = {c['symbol']: c for c in eligible}
            if planner == 'none':
                # lenses-only: accept everything that cleared the EV bar, no judge.
                mode = 'lenses'
                approved = [_Approve(c['symbol']) for c in
                            sorted(eligible, key=lambda c: c['ev'], reverse=True)]
            else:
                # Confidence gate (planner='llm'): candidates that clear the gate
                # on heuristic confidence are auto-approved with NO LLM call; only
                # the ambiguous remainder is sent to the judge — and a scan with no
                # ambiguous candidate spends no budget. Disabled (gate 0.0) → the
                # LLM judges the whole batch, as before.
                if llm_gate_active:
                    strong, ambiguous = _split_by_conf_gate(eligible, llm_conf_gate)
                else:
                    strong, ambiguous = [], eligible

                approved = [_Approve(c['symbol']) for c in strong]    # deterministic auto-pass
                llm_strong_skipped += len(strong)

                mode = 'lenses' if strong and not ambiguous else 'degraded'
                if ambiguous:
                    use_llm = planner == 'llm' and ollama_ok and llm_calls < max_llm_calls
                    batch = {
                        'scan_id': i, 'regime': regime,
                        'india_vix': vix_by_date.get(d, 0.0), 'equity': equity, 'throttle': 0,
                        'open_positions': [
                            {'symbol': s, 'side': p.trade.side, 'qty': p.trade.qty,
                             'unrealized': (float(data[s].loc[d]['close']) - p.trade.entry) * p.trade.qty
                                           if d in data[s].index else 0.0}
                            for s, p in positions.items()],
                        'candidates': ambiguous,
                    }
                    # backtest LLM calls are tight + no-retry so a long horizon doesn't
                    # spend 2×60s per batch; verdicts are short so num_predict is small.
                    verdicts, mode, _lat = judge.judge_batch(
                        batch, use_llm=use_llm, timeout_s=25, retry=False, num_predict=220)
                    if mode == 'llm':
                        llm_calls += 1
                    else:
                        degraded_calls += 1
                    approved += [v for v in verdicts if v.action == 'approve' and v.symbol in by_sym]
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
                sl_f, tgt_f = entry - ATR_SL_MULT * atr, entry + ATR_TGT_MULT * atr   # re-anchored on fill
                size_factor = getattr(v, 'size_factor', 1.0)
                qty = max(1, int((equity * RISK_PER_TRADE) / entry * size_factor))
                seg = _segment(c['strat'])
                entry_cost = cost_breakdown(entry * qty, 'BUY', seg)['total']
                # auto-passed strong candidates bypass the LLM → tag them 'lenses'
                # (honest per_judge accounting); only ambiguous verdicts carry `mode`.
                v_judge = 'lenses' if isinstance(v, _Approve) else mode
                t = Trade(v.symbol, c['strat'], 'BUY', str(nxt)[:10], entry, sl_f, tgt_f, qty,
                          regime=regime, ev=c['ev'], judge=v_judge, size_factor=round(size_factor, 2),
                          segment=seg, cost=entry_cost)
                positions[v.symbol] = Position(t, sec)

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
    total_ev = sum(ev_source_counts.values()) or 1
    planner_meta = {'mode': planner, 'ollama_available': ollama_ok,
                    'llm_batches': llm_calls, 'degraded_batches': degraded_calls,
                    'llm_conf_gate': llm_conf_gate if llm_gate_active else None,
                    'llm_strong_skipped': llm_strong_skipped,
                    'llm_budget': max_llm_calls, 'cancelled': stopped,
                    'ev_source': ('gbt' if ev_source_counts.get('gbt', 0) > total_ev / 2
                                  else 'heuristic'),
                    'ev_source_counts': ev_source_counts}
    result = _report(closed, daily_equity, days, regimes, dates, planner_meta)
    if full_trades:
        # full daily equity curve (NOT downsampled) + per-trade stream for the
        # validation harness; neither is persisted in the API payload. pnl is NET.
        result['daily_equity_full'] = [(d, float(v)) for d, v in daily_equity]
        result['all_trades'] = [
            {'symbol': t.symbol, 'lens': t.strategy, 'regime': t.regime,
             'entry_date': t.entry_date, 'exit_date': t.exit_date,
             'entry': t.entry, 'exit': t.exit_price, 'qty': t.qty,
             'pnl': t.pnl, 'cost': t.cost, 'ev': t.ev,
             'ret': (t.pnl / (t.entry * t.qty)) if t.entry * t.qty else 0.0}
            for t in closed]
    return result


class _FastContext:
    """Duck-typed MarketContext for the strategy replay that PRECOMPUTES each
    indicator's full series once and serves O(1) causal slices, instead of the
    base context recomputing RSI/EMA/ATR in a Python loop on every bar of every
    day. Exact parity: these indicators are causal, so f(full)[:pos] == f(full[:pos]).
    ~7x faster on long horizons."""
    def __init__(self, raw_by_token: dict, instruments: dict):
        from terminal_in.strategy_engine.context import _rsi, _ema, _atr, _sma
        self._fns = {'rsi': _rsi, 'ema': _ema, 'atr': _atr, 'sma': _sma}
        self._full = raw_by_token              # token -> full OHLCV df
        self.instruments = instruments         # symbol -> token
        self._cache: dict = {}                 # (token, name) -> full np.array
        self._posc: dict = {}                  # (token, asof) -> int
        # per-day mutable state (set by advance())
        self.now = None; self.regime = 'sideways'; self.regime_confidence = 0.7
        self.india_vix = 14.0; self.event_mask = 1.0; self.size_multiplier = 1.0

    def advance(self, asof, regime, vix, size_mult):
        self.now, self.regime, self.india_vix, self.size_multiplier = asof, regime, vix, size_mult

    def _pos(self, token):
        key = (token, self.now)
        if key not in self._posc:
            df = self._full.get(token)
            self._posc[key] = int(df.index.searchsorted(self.now, side='right')) if df is not None else 0
        return self._posc[key]

    def _full_indicator(self, token, name):
        key = (token, name)
        if key in self._cache:
            return self._cache[key]
        df = self._full[token]
        close = df['close'].values.astype(float)
        if name.startswith(('rsi_', 'ema_', 'sma_')):
            kind, p = name.split('_'); arr = self._fns[kind](close, int(p))
        elif name.startswith('atr_'):
            arr = self._fns['atr'](df['high'].values.astype(float), df['low'].values.astype(float), close, int(name.split('_')[1]))
        elif name == 'volume':
            arr = df['volume'].values.astype(float)
        elif name in ('high_52w', 'low_52w'):
            s = df['high'] if name == 'high_52w' else df['low']
            arr = (s.rolling(252, min_periods=1).max() if name == 'high_52w'
                   else s.rolling(252, min_periods=1).min()).values.astype(float)
        else:
            arr = np.array([])
        self._cache[key] = arr
        return arr

    def last_price(self, symbol):
        tok = self.instruments.get(symbol)
        if tok is None:
            return 0.0
        pos = self._pos(tok)
        if pos <= 0:
            return 0.0
        return float(self._full[tok]['close'].values[pos - 1])

    def ohlcv(self, symbol, timeframe='1d'):
        tok = self.instruments.get(symbol)
        if tok is None:
            return pd.DataFrame()
        return self._full[tok].iloc[:self._pos(tok)]

    def indicator(self, symbol, name, timeframe='1d'):
        tok = self.instruments.get(symbol)
        if tok is None:
            return np.array([])
        pos = self._pos(tok)
        if pos <= 0:
            return np.array([])
        arr = self._full_indicator(tok, name)
        if name in ('high_52w', 'low_52w'):
            return np.array([arr[pos - 1]]) if pos <= len(arr) else np.array([])
        return arr[:pos]


def _strategy_engine_backtest(data, all_1d, eq_tokens, sectors, regimes, vix_by_date,
                              dates, days, idx_tokens, progress_cb=None, should_stop=None) -> dict:
    """Replay the REAL strategy_engine daily classes (S2/S3/S4/S5/S8) via a
    historical MarketContext — calls each strategy's own evaluate(), zero drift.
    Long-only cash (BUY signals); strategy_engine signals bypass the LLM planner
    in live (engine → gate), so we route them straight to gate-lite → t+1 fill.
    Heavier than the lens path (indicators recompute per day) — cancellable."""
    from terminal_in.strategy_engine.engine import ALL_STRATEGIES
    from terminal_in.data_ingest.instruments import KNOWN_TOKENS, registry

    strats = [s for s in ALL_STRATEGIES if getattr(s, 'timeframe', '') == '1d']
    # symbol→token for everything we have bars for (incl. NIFTY 50 / VIX so the
    # index strategies can read them); frames by symbol drive exits + fills.
    sym2tok = {s: t for s, t in KNOWN_TOKENS.items() if all_1d.get(t) is not None and len(all_1d[t]) >= 60}
    tok2sym = {t: s for s, t in sym2tok.items()}
    frames = {s: data.get(s) if data.get(s) is not None else _indicators(all_1d[t]) for s, t in sym2tok.items()}
    raw = {t: all_1d[t] for t in sym2tok.values()}
    ctx = _FastContext(raw, sym2tok)   # precompute indicators once; O(1) per-bar slices

    equity = CAPITAL
    positions: dict[str, Position] = {}
    closed: list[Trade] = []
    daily_equity: list[tuple[str, float]] = []
    n_steps = len(dates) - 1
    stopped = False

    for i, d in enumerate(dates[:-1]):
        if should_stop is not None and should_stop():
            stopped = True; break
        if i % 5 == 0 and progress_cb is not None:
            progress_cb(i / max(n_steps, 1), {'day': i, 'total': n_steps, 'date': str(d)[:10],
                                              'llm_calls': 0, 'trades': len(closed), 'open': len(positions)})
        nxt = dates[i + 1]
        regime = regimes.get(d, 'sideways')

        # exits on today's bar (stop before target — conservative)
        for sym in list(positions):
            df = frames.get(sym)
            if df is None or d not in df.index:
                continue
            row = df.loc[d]; t = positions[sym].trade; px = None
            if float(row['low']) <= t.sl:    px, t.exit_reason = t.sl, 'stop_loss'
            elif float(row['high']) >= t.target: px, t.exit_reason = t.target, 'target'
            if px is not None:
                fill = px * (1 - SLIPPAGE)
                t.exit_price, t.exit_date = fill, str(d)[:10]
                t.cost += cost_breakdown(fill * t.qty, 'SELL', t.segment)['total']
                t.pnl = (fill - t.entry) * t.qty - t.cost
                equity += t.pnl; closed.append(t); del positions[sym]

        # advance the precomputed context to today (no lookahead — slices are <= d)
        ctx.advance(d, regime, float(vix_by_date.get(d, 14.0)), REGIME_MULT.get(regime, 1.0))

        # each real strategy rules; long-only cash → BUY only
        for strat in strats:
            try:
                sig = strat.evaluate(ctx)
            except Exception:
                continue
            if sig is None or sig.side != 'BUY':
                continue
            sym = (sig.metadata or {}).get('symbol') or tok2sym.get(sig.instrument_id)
            if not sym or sym not in frames or nxt not in frames[sym].index or sym in positions:
                continue
            if len(positions) >= MAX_POSITIONS:
                continue
            sec = registry.sector(sym2tok[sym]) or 'other'
            sec_n = sum(1 for p in positions.values() if p.sector == sec) + 1
            if sec_n > SECTOR_FLOOR and sec_n / (len(positions) + 1) > SECTOR_CAP:
                continue
            entry = float(frames[sym].loc[nxt]['open']) * (1 + SLIPPAGE)
            ref = sig.limit_price or ctx.last_price(sym) or entry
            sl_dist = max(ref - sig.stop_loss, ref * 0.002)
            tgt_dist = max(sig.target - ref, ref * 0.003)
            qty = max(1, int((equity * RISK_PER_TRADE) / entry))
            seg = _segment(strat.id)
            entry_cost = cost_breakdown(entry * qty, 'BUY', seg)['total']
            t = Trade(sym, strat.id, 'BUY', str(nxt)[:10], entry, entry - sl_dist, entry + tgt_dist,
                      qty, regime=regime, ev=round(float(sig.confidence), 3), judge='strategy',
                      segment=seg, cost=entry_cost)
            positions[sym] = Position(t, sec)

        mark = equity + sum(
            (float(frames[s].loc[d]['close']) - p.trade.entry) * p.trade.qty
            for s, p in positions.items() if d in frames[s].index)
        daily_equity.append((str(d)[:10], mark))

    if progress_cb is not None:
        progress_cb(1.0, {'day': n_steps, 'total': n_steps, 'llm_calls': 0,
                          'trades': len(closed), 'open': len(positions)})
    meta = {'mode': 'strategy_engine', 'ollama_available': False, 'llm_batches': 0,
            'degraded_batches': 0, 'llm_budget': 0, 'cancelled': stopped,
            'strategies': sorted(s.id for s in strats)}
    return _report(closed, daily_equity, days, regimes, dates, meta)


def _curve_metrics(eq: pd.Series) -> dict:
    """Return / CAGR / max-DD / Sharpe for an equity curve (₹, indexed by date)."""
    if len(eq) == 0:
        return {'return_pct': 0.0, 'cagr_pct': 0.0, 'max_drawdown_pct': 0.0, 'sharpe': 0.0}
    rets = eq.pct_change().dropna()
    dd = (eq / eq.cummax() - 1).min()
    sharpe = float(rets.mean() / rets.std() * np.sqrt(252)) if len(rets) > 20 and rets.std() > 0 else 0.0
    years = max(len(eq) / 252.0, 1e-9)
    final = float(eq.iloc[-1])
    cagr = (final / CAPITAL) ** (1 / years) - 1 if final > 0 else -1.0
    return {'return_pct': round((final / CAPITAL - 1) * 100, 2),
            'cagr_pct': round(cagr * 100, 2),
            'max_drawdown_pct': round(float(dd) * 100, 2),
            'sharpe': round(sharpe, 2)}


def _trade_sharpe(pnls: list[float], n_years: float) -> float:
    """Trade-level Sharpe: per-trade return on capital, annualised by the lens's
    own trade frequency. A per-lens daily equity curve isn't well defined (the
    book overlaps positions), so per-lens risk is measured on the trade stream."""
    if len(pnls) < 2 or n_years <= 0:
        return 0.0
    r = np.array(pnls, dtype=float) / CAPITAL
    if r.std() == 0:
        return 0.0
    trades_per_year = len(pnls) / n_years
    return round(float(r.mean() / r.std() * np.sqrt(trades_per_year)), 2)


def _report(closed: list[Trade], daily_equity: list, days: int,
            regimes: dict, dates: list, planner_meta: dict | None = None) -> dict:
    eq = pd.Series({d: v for d, v in daily_equity})

    # Gross curve = net curve + cumulative transaction cost realised by each date
    # (costs fold into pnl at exit, so net trails gross by the costs booked so far).
    cost_by_date: dict = {}
    for t in closed:
        cost_by_date[t.exit_date] = cost_by_date.get(t.exit_date, 0.0) + t.cost
    gross_vals, run_cost = [], 0.0
    for d, v in daily_equity:
        run_cost += cost_by_date.get(str(d)[:10], 0.0)
        gross_vals.append(v + run_cost)
    gross_eq = pd.Series({d: gv for (d, _), gv in zip(daily_equity, gross_vals)})

    n_years = max(len(eq) / 252.0, 1e-9)
    net_m, gross_m = _curve_metrics(eq), _curve_metrics(gross_eq)
    sharpe = net_m['sharpe']

    def stats(trades):
        if not trades:
            return {'n': 0}
        wins = [t for t in trades if t.pnl > 0]
        net_pnl = sum(t.pnl for t in trades)
        cost = sum(t.cost for t in trades)
        return {'n': len(trades),
                'win_rate': round(len(wins) / len(trades), 3),
                'total_pnl': round(net_pnl),
                'gross_pnl': round(net_pnl + cost),
                'costs': round(cost),
                'avg_pnl': round(net_pnl / len(trades)),
                'net_sharpe': _trade_sharpe([t.pnl for t in trades], n_years),
                'gross_sharpe': _trade_sharpe([t.pnl + t.cost for t in trades], n_years)}

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

    total_costs = sum(t.cost for t in closed)
    # avg round-trip cost in bps of the entry-leg notional (legible drag metric)
    rt_bps = [t.cost / (t.entry * t.qty) * 1e4 for t in closed if t.entry * t.qty > 0]
    costs_block = {
        'total_costs': round(total_costs),
        'pct_of_capital': round(total_costs / CAPITAL * 100, 3),
        'avg_roundtrip_bps': round(float(np.mean(rt_bps)), 2) if rt_bps else 0.0,
        'n_round_trips': len(closed),
    }

    pm = planner_meta or {'mode': 'degraded'}
    result = {
        'ts': int(time.time() * 1000), 'days': days,
        'engine': f"v3-{pm.get('mode', 'degraded')}",
        'capital': CAPITAL,
        'final_equity': round(float(eq.iloc[-1])) if len(eq) else CAPITAL,
        'return_pct': net_m['return_pct'],
        'cagr_pct': net_m['cagr_pct'],
        'max_drawdown_pct': net_m['max_drawdown_pct'],
        'sharpe': sharpe,
        'gross': gross_m,           # same metrics before transaction costs
        'net': net_m,               # explicit net block (mirrors top-level)
        'costs': costs_block,
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
    ap.add_argument('--llm-conf-gate', type=float, default=0.60,
                    help='only candidates BELOW this smoothed confidence go to the '
                         'LLM (planner=llm); strong ones auto-pass. 0 = LLM judges all')
    args = ap.parse_args()
    r = run_backtest(days=args.days, planner=args.planner, max_llm_calls=args.max_llm_calls,
                     llm_conf_gate=args.llm_conf_gate)
    print(json.dumps({k: v for k, v in r.items() if k != 'path'}, indent=1))
    print('->', r['path'])
