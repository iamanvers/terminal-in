"""
Phase 2 — PEAD-family event features (orthogonal to OHLCV technicals).

For each candidate at bar `d`, compute from information KNOWN AT d ONLY (events
whose announce_date <= d), using the point-in-time NSE event archive
(data_ingest/events.py) + real price series:

  evt_days_since_results   trading days since the last results filing (capped)
  evt_reaction_gap         the results-day abnormal return (market's immediate read)
  evt_drift_so_far         cumulative abnormal return (vs NIFTY) since that filing → d
  evt_pre_post_vol_ratio   realized vol since the filing ÷ vol in the 20d before it
  evt_in_drift_window      1 if 1..60 trading days past the filing (classic PEAD window)
  evt_recent_results       1 if a results filing landed in the last 5 trading days

CONSENSUS-DEPENDENT features are emitted NULL and flagged, never backfilled:
  earnings_surprise / surprise-reaction sign-agreement — no free point-in-time
  consensus exists for Indian names, so these CANNOT be computed honestly.
  `event_consensus_coverage()` reports 0%.

POINT-IN-TIME: a feature at d uses only the most recent results event with
announce_date <= d and price bars up to d. Nothing here is written to ohlcv_*.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

# Consensus-free event features fed to the D₀ head (constant/null ones excluded).
EVENT_FEATURES = ['evt_days_since_results', 'evt_reaction_gap', 'evt_drift_so_far',
                  'evt_pre_post_vol_ratio', 'evt_in_drift_window', 'evt_recent_results']
DRIFT_WINDOW = 60          # classic post-earnings-announcement-drift horizon (days)
DSR_CAP = 999              # 'no recent results' sentinel for days-since


def _nifty_logret(db, dates_index) -> pd.Series:
    from terminal_in.data_ingest.instruments import KNOWN_TOKENS
    tok = KNOWN_TOKENS.get('NIFTY 50')
    if tok is None:
        return pd.Series(0.0, index=dates_index)
    df = db.get_ohlcv_1d_all([tok], limit=4000).get(tok)
    if df is None or df.empty:
        return pd.Series(0.0, index=dates_index)
    return np.log(df['close']).diff().reindex(dates_index).fillna(0.0)


def add_event_features(cand: pd.DataFrame, db, events: pd.DataFrame | None = None) -> pd.DataFrame:
    """Return a COPY of the candidate dataset with evt_* columns added, computed
    point-in-time per row. Rows with no prior results event get the no-event
    defaults (days_since=DSR_CAP, gaps/drift 0)."""
    from terminal_in.data_ingest import events as EV
    from terminal_in.data_ingest.instruments import KNOWN_TOKENS, registry
    if events is None:
        events = EV.load_events()
    out = cand.copy()
    for c in EVENT_FEATURES:
        out[c] = (DSR_CAP if c == 'evt_days_since_results' else 0.0)
    if events is None or len(events) == 0:
        out['earnings_surprise'] = np.nan
        out['evt_has_consensus'] = 0
        log.warning('event_features: empty archive — evt_* left at no-event defaults')
        return out

    registry.load_stubs()
    sym2tok = {s: t for s, t in KNOWN_TOKENS.items()}
    results = events[events['event_type'] == 'results'].copy()
    res_by_sym = {s: g['announce_date'].sort_values().tolist()
                  for s, g in results.groupby('symbol')}

    # price context per symbol (real bars only)
    syms = out['symbol'].unique().tolist()
    all_1d = db.get_ohlcv_1d_all([sym2tok[s] for s in syms if s in sym2tok], limit=4000)
    nifty_lr = None
    px: dict[str, dict] = {}
    for s in syms:
        tok = sym2tok.get(s)
        df = all_1d.get(tok) if tok else None
        if df is None or df.empty:
            continue
        close = df['close']
        lr = np.log(close).diff().fillna(0.0)
        if nifty_lr is None:
            nifty_lr = _nifty_logret(db, close.index)
        nlr = nifty_lr.reindex(close.index).fillna(0.0)
        abn = (lr - nlr).cumsum()                 # cumulative abnormal log-return
        dates = [str(x)[:10] for x in close.index]
        px[s] = {'dates': dates, 'pos': {dt: i for i, dt in enumerate(dates)},
                 'close': close.to_numpy(float), 'ret': lr.to_numpy(float),
                 'abn_cum': abn.to_numpy(float)}

    import bisect
    vals = {c: [] for c in EVENT_FEATURES}
    for r in out.itertuples(index=False):
        sym, d = r.symbol, r.date
        ctx = px.get(sym)
        res_dates = res_by_sym.get(sym)
        feat = {'evt_days_since_results': DSR_CAP, 'evt_reaction_gap': 0.0,
                'evt_drift_so_far': 0.0, 'evt_pre_post_vol_ratio': 0.0,
                'evt_in_drift_window': 0.0, 'evt_recent_results': 0.0}
        if ctx is not None and res_dates:
            # most recent results event with announce_date <= d (point-in-time)
            k = bisect.bisect_right(res_dates, d) - 1
            if k >= 0 and d in ctx['pos']:
                e_date = res_dates[k]
                # event trade day = first bar with date >= e_date
                ei = bisect.bisect_left(ctx['dates'], e_date)
                di = ctx['pos'][d]
                if 0 < ei <= di < len(ctx['close']):
                    dsr = di - ei
                    feat['evt_days_since_results'] = float(min(dsr, DSR_CAP))
                    feat['evt_reaction_gap'] = float(ctx['ret'][ei])
                    feat['evt_drift_so_far'] = float(ctx['abn_cum'][di] - ctx['abn_cum'][ei])
                    feat['evt_in_drift_window'] = 1.0 if 1 <= dsr <= DRIFT_WINDOW else 0.0
                    feat['evt_recent_results'] = 1.0 if dsr <= 5 else 0.0
                    pre = ctx['ret'][max(0, ei - 20):ei]
                    post = ctx['ret'][ei:di + 1]
                    if len(pre) >= 5 and len(post) >= 2 and pre.std() > 1e-9:
                        feat['evt_pre_post_vol_ratio'] = float(post.std() / pre.std())
        for c in EVENT_FEATURES:
            vals[c].append(feat[c])
    for c in EVENT_FEATURES:
        out[c] = vals[c]
    out['earnings_surprise'] = np.nan      # invariant (c): no PIT consensus → null
    out['evt_has_consensus'] = 0
    return out


def event_consensus_coverage(cand_with_events: pd.DataFrame) -> float:
    """% of rows with a point-in-time consensus (→ a real earnings_surprise).
    Honest answer here is 0.0 — no free PIT consensus for Indian names."""
    if 'evt_has_consensus' not in cand_with_events:
        return 0.0
    return round(float(cand_with_events['evt_has_consensus'].mean()) * 100, 2)
