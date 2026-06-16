"""
Phase 0 — the labeled candidate dataset (Module 6's training substrate).

For EVERY candidate the lenses generate at EVERY bar (NOT just the ones that
fire), record the decision-time feature vector AND the realized forward outcome.
This is what the competence table (C) and the EV head (D₀) learn from — dense
(10y × 72 symbols), unbiased (includes non-fired candidates, so the head sees the
full distribution, not only selection winners), and point-in-time.

POINT-IN-TIME CONTRACT (asserted in tests):
  - features are computed from bars at or before the decision date `d`;
  - the label is computed from bars STRICTLY AFTER the entry (t+1), by walking the
    SL/target path forward up to `horizon` days — exactly the backtest's exit rule
    (stop checked before target, conservative);
  - `outcome_date` is when the label resolved. A row may be used to train a model
    for a walk-forward fold only if `outcome_date` < that fold's test-window start.

Nothing here is written to ohlcv_* or fed back to the lenses — it is a label
table for the judge, per the M6 fences.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from terminal_in.backtest import engine as E
from terminal_in.execution.costs import cost_breakdown

log = logging.getLogger(__name__)

HORIZON_DEFAULT = 20          # trading days to resolve target-before-stop / E[ret]
LENS_COLS = ('S2', 'S4', 'S5', 'MOM')   # multi-hot lens membership columns


def build_candidate_dataset(db=None, days: int = 2470, horizon: int = HORIZON_DEFAULT,
                            symbols: list[str] | None = None,
                            progress_cb=None) -> pd.DataFrame:
    """Return a DataFrame, one row per (symbol, bar) where any lens fired.

    Columns: date, symbol, sector, regime, lens_set, S2/S4/S5/MOM (multi-hot),
    ev, confidence, persistence, rr, rsi, vol_factor, vix, n_lenses, entry, atr,
    fired (heuristic judge would have taken it), outcome (1=target before stop),
    ret_net (net return at exit), exit_reason, outcome_date.
    """
    if db is None:
        from terminal_in.config import load_config
        from terminal_in.db import DB
        db = DB(load_config().sqlite_path)
    from terminal_in.data_ingest.instruments import KNOWN_TOKENS, registry
    registry.load_stubs()

    eq_tokens = {t: s for s, t in KNOWN_TOKENS.items() if registry.sector(t) not in ('index',)}
    if symbols:
        eq_tokens = {t: s for t, s in eq_tokens.items() if s in symbols}
    idx_tokens = [KNOWN_TOKENS.get('NIFTY 50'), KNOWN_TOKENS.get('INDIA VIX')]
    all_1d = db.get_ohlcv_1d_all(list(eq_tokens) + [t for t in idx_tokens if t],
                                 limit=days + 300)
    regimes = E._regime_series(all_1d.get(idx_tokens[0]), all_1d.get(idx_tokens[1]))
    vix_df = all_1d.get(idx_tokens[1])
    vix_by_date = {str(d)[:10]: float(v) for d, v in vix_df['close'].items()} if vix_df is not None else {}
    sectors = {s: registry.sector(t) for t, s in eq_tokens.items()}

    data: dict[str, pd.DataFrame] = {}
    for tok, sym in eq_tokens.items():
        df = all_1d.get(tok)
        if df is None or len(df) < 250:
            continue
        data[sym] = E._indicators(df)
    if not data:
        raise RuntimeError('m6 dataset: no symbols with >=250 real daily bars')

    dates = sorted(set().union(*[set(d.index) for d in data.values()]))[-days:]
    n_steps = len(dates) - 1
    persist: dict[str, int] = {}
    rows: list[dict] = []

    for i, d in enumerate(dates[:-1]):
        if progress_cb is not None and i % 50 == 0:
            progress_cb(i / max(n_steps, 1))
        nxt = dates[i + 1]
        regime = regimes.get(d, 'sideways')
        ds = str(d)[:10]
        seen: set[str] = set()
        for sym, df in data.items():
            if d not in df.index or nxt not in df.index:
                continue
            row = df.loc[d]
            lenses = E._lenses(row, regime)
            if not lenses:
                continue
            seen.add(sym)
            persist[sym] = persist.get(sym, 0) + 1

            price = float(row['close'])
            atr = float(row['atr'])
            vol_now = float(row['vol'])
            vol_avg = float(row['vol_avg20']) if row['vol_avg20'] and not np.isnan(row['vol_avg20']) else 1.0
            vol_factor = min(2.5, vol_now / max(vol_avg, 1.0))
            avg_conf = sum(c for _, c in lenses) / len(lenses)
            conv_bonus = 1.0 + (len(lenses) - 1) * 0.10
            entry = float(df.loc[nxt]['open']) * (1 + E.SLIPPAGE)
            sl = entry - E.ATR_SL_MULT * atr
            tgt = entry + E.ATR_TGT_MULT * atr
            rr = (tgt - entry) / max(entry - sl, 1e-9)
            ev = avg_conf * rr * vol_factor * conv_bonus
            lens_names = [l for l, _ in lenses]

            outcome, ret_net, reason, out_date = _forward_outcome(
                df, nxt, entry, sl, tgt, horizon)
            if out_date is None:
                continue            # not enough forward bars to resolve — drop honestly

            fired = (persist[sym] >= E.PERSIST_N and ev >= E.MIN_EV and avg_conf >= E.MIN_CONF)
            r = {
                'date': ds, 'symbol': sym, 'sector': sectors.get(sym, 'other'),
                'regime': regime, 'lens_set': '+'.join(sorted(lens_names)),
                'ev': ev, 'confidence': avg_conf, 'persistence': persist[sym],
                'rr': rr, 'rsi': float(row['rsi']), 'vol_factor': vol_factor,
                'vix': vix_by_date.get(ds, 0.0), 'n_lenses': len(lenses),
                'entry': entry, 'atr': atr, 'fired': int(fired),
                'outcome': outcome, 'ret_net': ret_net, 'exit_reason': reason,
                'outcome_date': out_date,
            }
            for L in LENS_COLS:
                r[L] = int(L in lens_names)
            rows.append(r)

        for sym in list(persist):       # reset persistence when a symbol goes quiet
            if sym not in seen:
                persist[sym] = 0

    df_out = pd.DataFrame(rows)
    log.info('m6 dataset: %d candidate rows over %d bars / %d symbols',
             len(df_out), len(dates), len(data))
    return df_out


def _forward_outcome(df: pd.DataFrame, entry_date, entry: float, sl: float,
                     tgt: float, horizon: int):
    """Walk forward from entry_date up to `horizon` bars. Stop checked BEFORE
    target (conservative, mirrors the backtest). Returns
    (outcome 1/0, net_return, exit_reason, outcome_date_str) or (..., None) if
    there aren't enough forward bars to resolve."""
    idx = df.index
    try:
        start = idx.get_loc(entry_date)
    except KeyError:
        return 0, 0.0, 'no_entry', None
    end = min(start + horizon, len(idx) - 1)
    if end <= start:
        return 0, 0.0, 'no_forward_bars', None

    exit_px, reason = None, 'horizon'
    for j in range(start, end + 1):
        lo, hi = float(df['low'].iloc[j]), float(df['high'].iloc[j])
        if lo <= sl:
            exit_px, reason = sl, 'stop_loss'
            break
        if hi >= tgt:
            exit_px, reason = tgt, 'target'
            break
    if exit_px is None:                       # neither hit → mark to horizon close
        exit_px = float(df['close'].iloc[end])
    out_date = str(idx[j if exit_px in (sl, tgt) else end])[:10]

    fill = exit_px * (1 - E.SLIPPAGE)
    # net return on one unit of notional (qty cancels): gross less CNC round-trip
    buy_c = cost_breakdown(entry, 'BUY', 'CNC')['total'] / entry
    sell_c = cost_breakdown(fill, 'SELL', 'CNC')['total'] / fill
    ret_net = (fill - entry) / entry - buy_c - sell_c
    return (1 if reason == 'target' else 0), float(ret_net), reason, out_date
