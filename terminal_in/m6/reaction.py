"""
Backdated event-reaction sensitivity model — a STRUCTURAL PRIOR for the D₀ head.

For each (event_type × VIX_regime) cell, learn the empirical reaction distribution
from CLEAN price around dated events (no news-text archive needed): immediate gap,
H-day abnormal drift, realized-vol multiple, directional hit-rate, n. The same
event is a different event across VIX regimes, so EVERYTHING is conditioned on VIX.

Surprise magnitude, when consensus is missing, is proxied by the market's own
immediate reaction (|gap|) — "how big was this news."

NO-CIRCULARITY FENCE (PR-blocking): the matrix that scores a walk-forward fold is
fit ONLY on events whose H-day window resolved strictly BEFORE the fold's test
start. `walk_forward_oos` asserts no fitting event post-dates the test window.

Thin cells (n below a threshold) are flagged untrustworthy and reported, not hidden.
Nothing here is written to ohlcv_*.
"""

from __future__ import annotations

import bisect
import logging

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

# VIX regime buckets — the same event is a different event across these.
VIX_EDGES = [0, 15, 20, 25, 1e9]
VIX_LABELS = ['<15', '15-20', '20-25', '>25']
HORIZON = 20
MIN_CELL_N = 30          # below this a cell's stats are flagged untrustworthy
EVENT_TYPES = ('results', 'guidance', 'rating_change', 'corp_action', 'regulatory')


def _vix_bucket(v: float) -> str:
    return VIX_LABELS[max(0, bisect.bisect_right(VIX_EDGES, v) - 1)]


def build_records(events: pd.DataFrame, db, horizon: int = HORIZON) -> pd.DataFrame:
    """One row per dated event with its clean-price reaction context:
    {symbol, event_type, announce_date, resolved_date, vix_bucket, gap, drift,
     vol_mult}. drift = abnormal (vs NIFTY) cumulative return over `horizon`."""
    from terminal_in.data_ingest.instruments import KNOWN_TOKENS, registry
    registry.load_stubs()
    sym2tok = {s: t for s, t in KNOWN_TOKENS.items()}
    syms = [s for s in events['symbol'].unique() if s in sym2tok]
    toks = [sym2tok[s] for s in syms] + [KNOWN_TOKENS.get('NIFTY 50'), KNOWN_TOKENS.get('INDIA VIX')]
    all_1d = db.get_ohlcv_1d_all([t for t in toks if t], limit=4000)
    nifty = all_1d.get(KNOWN_TOKENS.get('NIFTY 50'))
    vix = all_1d.get(KNOWN_TOKENS.get('INDIA VIX'))
    nlr_full = np.log(nifty['close']).diff().fillna(0.0) if nifty is not None else None
    vix_map = {str(d)[:10]: float(v) for d, v in vix['close'].items()} if vix is not None else {}

    rows = []
    for s in syms:
        df = all_1d.get(sym2tok[s])
        if df is None or df.empty:
            continue
        dates = [str(x)[:10] for x in df.index]
        pos = {dt: i for i, dt in enumerate(dates)}
        ret = np.log(df['close']).diff().fillna(0.0).to_numpy(float)
        nlr = (nlr_full.reindex(df.index).fillna(0.0).to_numpy(float)
               if nlr_full is not None else np.zeros(len(df)))
        abn = (ret - nlr).cumsum()
        ev_s = events[events['symbol'] == s]
        for r in ev_s.itertuples(index=False):
            ad = r.announce_date
            ei = bisect.bisect_left(dates, ad)
            if ei <= 0 or ei + horizon >= len(dates):
                continue                       # need a full pre+post window
            gap = float(ret[ei])
            drift = float(abn[ei + horizon] - abn[ei])
            pre, post = ret[max(0, ei - 20):ei], ret[ei:ei + horizon + 1]
            vol_mult = float(post.std() / pre.std()) if len(pre) >= 5 and pre.std() > 1e-9 else np.nan
            vb = _vix_bucket(vix_map.get(dates[ei], 14.0))
            rows.append({'symbol': s, 'event_type': r.event_type, 'announce_date': ad,
                         'resolved_date': dates[ei + horizon], 'vix_bucket': vb,
                         'gap': gap, 'drift': drift, 'vol_mult': vol_mult})
    return pd.DataFrame(rows)


def reaction_table(records: pd.DataFrame) -> pd.DataFrame:
    """Aggregate records → the legible (event_type × VIX) sensitivity matrix.
    hit_rate = P(drift continues the immediate gap's sign) — PEAD vs reversal."""
    if len(records) == 0:
        return pd.DataFrame()
    g = records.copy()
    g['cont'] = (np.sign(g['drift']) == np.sign(g['gap'])).astype(float)
    out = (g.groupby(['event_type', 'vix_bucket'])
             .agg(n=('drift', 'size'), mean_gap=('gap', 'mean'), mean_drift=('drift', 'mean'),
                  vol_mult=('vol_mult', 'mean'), hit_rate=('cont', 'mean'))
             .reset_index())
    out['untrustworthy'] = out['n'] < MIN_CELL_N
    return out


def walk_forward_oos(records: pd.DataFrame, horizon: int = HORIZON) -> dict:
    """Fence-checked OOS test: for each calendar-year fold, fit the table on events
    resolved BEFORE the fold start, predict each test event's drift SIGN from its
    cell's mean_drift, and measure OOS directional hit-rate + expected-vs-realized
    drift correlation. Answers: does the sensitivity hold OOS or was it in-sample
    noise?  ASSERTS no fitting event post-dates the test window."""
    if len(records) == 0:
        return {'note': 'no event records'}
    years = sorted({d[:4] for d in records['announce_date']})
    per_fold, all_pred, all_real = [], [], []
    for y in years:
        start = f'{y}-01-01'
        train = records[records['resolved_date'] < start]
        test = records[(records['announce_date'] >= start) & (records['announce_date'] < f'{int(y)+1}-01-01')]
        if len(train) < 100 or len(test) == 0:
            continue
        assert train['resolved_date'].max() < start, (
            f'LEAK: fold {y} train resolved {train["resolved_date"].max()} >= {start}')
        tbl = reaction_table(train).set_index(['event_type', 'vix_bucket'])
        preds, reals = [], []
        for r in test.itertuples(index=False):
            key = (r.event_type, r.vix_bucket)
            if key not in tbl.index:
                continue
            exp = tbl.loc[key, 'mean_drift']
            preds.append(exp); reals.append(r.drift)
        if len(preds) >= 20:
            preds, reals = np.array(preds), np.array(reals)
            hit = float((np.sign(preds) == np.sign(reals)).mean())
            corr = float(np.corrcoef(preds, reals)[0, 1]) if preds.std() and reals.std() else 0.0
            per_fold.append({'fold': y, 'n_test': len(preds), 'oos_dir_hit': round(hit, 3),
                             'oos_corr_exp_real': round(corr, 4)})
            all_pred += preds.tolist(); all_real += reals.tolist()
    ap, ar = np.array(all_pred), np.array(all_real)
    pooled = {
        'oos_dir_hit_rate': round(float((np.sign(ap) == np.sign(ar)).mean()), 3) if len(ap) else None,
        'oos_corr_expected_realized_drift': round(float(np.corrcoef(ap, ar)[0, 1]), 4) if len(ap) > 2 and ap.std() and ar.std() else None,
        'n_oos_events': int(len(ap)),
    }
    return {'per_fold': per_fold, 'pooled': pooled}


def print_table(tbl: pd.DataFrame):
    if len(tbl) == 0:
        print('  (no events)'); return
    print(f"  {'event_type':<14}{'VIX':<8}{'n':>6}{'gap%':>8}{'drift%':>9}"
          f"{'volx':>7}{'hit%':>7}  flag")
    for r in tbl.sort_values(['event_type', 'vix_bucket']).itertuples(index=False):
        print(f"  {r.event_type:<14}{r.vix_bucket:<8}{r.n:>6}{r.mean_gap*100:>8.2f}"
              f"{r.mean_drift*100:>9.2f}{r.vol_mult:>7.2f}{r.hit_rate*100:>7.1f}"
              f"  {'THIN' if r.untrustworthy else ''}")
