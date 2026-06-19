"""
Alpha-validation harness — is the backtest's apparent edge real, or an artifact?

This module does NOT try to make the numbers look good. It is built to FALSIFY the
edge: benchmark it against passive + random, correct for the fact that 8 strategies
were tried on ONE history, test per-strategy statistical significance, isolate the
LLM/training contribution, perturb every hand-tuned parameter, and measure how
concentrated the P&L is in one year / one regime.

HONEST SCOPE (read first):
  - The live backtest has NO out-of-sample period. Every gate (MIN_EV, MIN_CONF,
    PERSIST_N, RSI/EMA/ATR levels) is a hand-set constant chosen by a human over
    THIS SAME 10y history. So everything here is IN-SAMPLE; these tests are the
    only honest signal available without re-architecting data into point-in-time.
  - The 72-symbol universe is today's large-cap list backtested to 2016 →
    survivorship + selection bias. yfinance auto_adjust=True is retroactive, NOT
    point-in-time. We REPORT the late-listers rather than silently include them.
  - The fine-tuned-adapter-vs-base OOS test CANNOT be run here (no point-in-time
    data; the adapter trains partly on its own recent trades; the backtest never
    loads the adapter). We say so plainly instead of faking a number.

CLI:
  .venv/Scripts/python.exe -m terminal_in.backtest.validation --days 2470
  .venv/Scripts/python.exe -m terminal_in.backtest.validation --days 2470 --llm
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from statistics import NormalDist

import numpy as np
import pandas as pd

from terminal_in.backtest import engine
from terminal_in.backtest.engine import run_backtest, CAPITAL
from terminal_in.execution.costs import cost_breakdown

log = logging.getLogger(__name__)
_N = NormalDist()

# Round-trip CNC cost as a fraction of notional (constant — CNC brokerage is 0 and
# every other component is linear in turnover). Used for the passive/random nulls.
_BUY_FRAC  = cost_breakdown(1.0, 'BUY',  'CNC')['total']
_SELL_FRAC = cost_breakdown(1.0, 'SELL', 'CNC')['total']
_RT_FRAC   = _BUY_FRAC + _SELL_FRAC

# Short-leg round-trip cost for a market-neutral book IN THE INDIAN CONTEXT.
# You CANNOT hold a short in the cash segment overnight (no naked delivery short);
# the short leg must be a single-stock FUTURE (F&O-eligible names only) or thin SLB.
# Stock-futures round trip is CHEAPER than cash delivery: no stamp-heavy STT
# (STT 0.0125% sell-side only), lower exchange charge. ~6 bps round trip — an
# ESTIMATE, as-of 2026, verify; flagged everywhere it's used.
_FUT_RT_FRAC = 0.0006

# Hand-tuned parameters to perturb in the robustness test (engine global → ±20%).
# PERSIST_N is integer; ±20% of 2 rounds back to 2, so we step it 1/3 explicitly.
_PERTURB = {
    'MIN_EV':       (engine.MIN_EV,       0.20),
    'MIN_CONF':     (engine.MIN_CONF,     0.20),
    'ATR_SL_MULT':  (engine.ATR_SL_MULT,  0.20),
    'ATR_TGT_MULT': (engine.ATR_TGT_MULT, 0.20),
    'RSI_OVERSOLD': (engine.RSI_OVERSOLD, 0.20),
    'EMA_FAST':     (engine.EMA_FAST,     0.20),
    'EMA_SLOW':     (engine.EMA_SLOW,     0.20),
}


# ── metrics ──────────────────────────────────────────────────────────────────

def _curve_stats(eq: np.ndarray, n_years: float) -> dict:
    """CAGR / Sharpe / Sortino / max-DD / Calmar from an equity array (₹)."""
    eq = np.asarray(eq, dtype=float)
    if len(eq) < 3 or eq[0] <= 0:
        return {'cagr': 0.0, 'sharpe': 0.0, 'sortino': 0.0, 'max_dd': 0.0, 'calmar': 0.0}
    rets = np.diff(eq) / eq[:-1]
    sd = rets.std()
    downside = rets[rets < 0].std() if (rets < 0).any() else 0.0
    sharpe = float(rets.mean() / sd * np.sqrt(252)) if sd > 0 else 0.0
    sortino = float(rets.mean() / downside * np.sqrt(252)) if downside > 0 else 0.0
    peak = np.maximum.accumulate(eq)
    max_dd = float((eq / peak - 1).min())
    cagr = float((eq[-1] / eq[0]) ** (1 / max(n_years, 1e-9)) - 1)
    calmar = float(cagr / abs(max_dd)) if max_dd < 0 else 0.0
    return {'cagr': cagr, 'sharpe': sharpe, 'sortino': sortino,
            'max_dd': max_dd, 'calmar': calmar}


def _trade_sharpe(rets: np.ndarray, n_years: float) -> float:
    """Annualised trade-level Sharpe (matches engine._trade_sharpe)."""
    rets = np.asarray(rets, dtype=float)
    if len(rets) < 2 or rets.std() == 0 or n_years <= 0:
        return 0.0
    tpy = len(rets) / n_years
    return float(rets.mean() / rets.std() * np.sqrt(tpy))


# ── data load (mirror the engine's universe + window) ────────────────────────

def _load(db, days: int):
    from terminal_in.data_ingest.instruments import KNOWN_TOKENS, registry
    registry.load_stubs()
    eq_tokens = {t: s for s, t in KNOWN_TOKENS.items() if registry.sector(t) not in ('index',)}
    nifty_tok = KNOWN_TOKENS.get('NIFTY 50')
    all_1d = db.get_ohlcv_1d_all(list(eq_tokens) + ([nifty_tok] if nifty_tok else []),
                                 limit=days + 300)
    uni, first_listing = {}, {}
    for t, s in eq_tokens.items():
        df = all_1d.get(t)
        if df is None or len(df) < 250:
            continue
        uni[s] = df['close']
        first_listing[s] = str(df.index[0])[:10]
    nifty = all_1d.get(nifty_tok)
    dates = sorted(set().union(*[set(c.index) for c in uni.values()]))[-days:]
    return uni, nifty, dates, first_listing


def _load_research(db, days: int) -> dict:
    """Research universe (Nifty Midcap 150 set) closes — for the WIDE cross-sectional
    test. SURVIVORSHIP-BIASED: the membership seed is a current snapshot, so this is
    today's survivors backtested to 2016 (loudly flagged in the caller's output)."""
    from terminal_in.data_ingest.index_membership import RESEARCH_BY_TOKEN
    all_1d = db.get_ohlcv_1d_all(list(RESEARCH_BY_TOKEN), limit=days + 300)
    out = {}
    for t, s in RESEARCH_BY_TOKEN.items():
        df = all_1d.get(t)
        if df is not None and len(df) >= 250:
            out[s] = df['close']
    return out


# ── 1. BENCHMARKS ────────────────────────────────────────────────────────────

def benchmarks(uni, nifty, dates, all_trades, n_years, null_runs, rng):
    win = [d for d in dates]
    out = {}

    # buy-and-hold NIFTY (one-time round-trip cost; one-time cost ≈ no Sharpe effect)
    if nifty is not None and len(nifty) > 10:
        s = nifty['close'].reindex(win).ffill().dropna()
        eq = CAPITAL * (s.values / s.values[0])
        st = _curve_stats(eq, n_years)
        st['net_total_return'] = float((1 - _BUY_FRAC) * (eq[-1] / eq[0]) * (1 - _SELL_FRAC) - 1)
        out['buy_hold_nifty'] = st
    else:
        out['buy_hold_nifty'] = {'note': 'NIFTY series unavailable — cannot benchmark'}

    # equal-weight buy-and-hold of the universe (symbols present at window start)
    start = win[0]
    present = {s: c for s, c in uni.items() if start in c.index}
    if present:
        cols = []
        for s, c in present.items():
            r = c.reindex(win).ffill()
            r = r / r.loc[start]
            cols.append(r.values)
        eqw = CAPITAL * np.nanmean(np.vstack(cols), axis=0)
        eqw = eqw[~np.isnan(eqw)]
        st = _curve_stats(eqw, n_years)
        st['net_total_return'] = float((1 - _BUY_FRAC) * (eqw[-1] / eqw[0]) * (1 - _SELL_FRAC) - 1)
        st['n_symbols'] = len(present)
        out['equal_weight_universe'] = st

    # null: same entry dates + holding lengths, RANDOM symbol from the universe.
    # Tests whether the lens SELECTION beats random selection on identical timing.
    syms = list(uni.keys())
    arrs = {s: uni[s].values.astype(float) for s in syms}
    pos = {s: {str(dd)[:10]: i for i, dd in enumerate(uni[s].index)} for s in syms}
    dpos = {str(dd)[:10]: i for i, dd in enumerate(win)}
    strat_rets = np.array([t['ret'] for t in all_trades], dtype=float)
    strat_ts = _trade_sharpe(strat_rets, n_years)
    strat_mean = float(strat_rets.mean()) if len(strat_rets) else 0.0

    # Candidate symbols for each (entry_date, holding_len) are identical across all
    # null runs, so resolve them ONCE: per spec, the array of achievable net returns
    # (one per eligible symbol). Each run then just samples one return per spec.
    spec_returns = []
    for t in all_trades:
        ed, xd = t['entry_date'], t['exit_date']
        if ed not in dpos or xd not in dpos:
            continue
        L = max(1, dpos[xd] - dpos[ed])
        rets = [arrs[s][pos[s][ed] + L] / arrs[s][pos[s][ed]] - 1 - _RT_FRAC
                for s in syms if ed in pos[s] and pos[s][ed] + L < len(arrs[s])]
        if rets:
            spec_returns.append(np.array(rets))

    null_ts, null_mean = [], []
    for _ in range(null_runs):
        rr = np.array([sr[rng.integers(len(sr))] for sr in spec_returns])
        if len(rr) > 1:
            null_ts.append(_trade_sharpe(rr, n_years))
            null_mean.append(float(rr.mean()))
    null_ts = np.array(null_ts) if null_ts else np.array([0.0])
    out['null_random'] = {
        'runs': len(null_ts),
        'strategy_trade_sharpe': round(strat_ts, 3),
        'null_sharpe_mean': round(float(null_ts.mean()), 3),
        'null_sharpe_p95': round(float(np.percentile(null_ts, 95)), 3),
        'strategy_percentile_vs_null': round(float((null_ts < strat_ts).mean() * 100), 1),
        'strategy_mean_ret': round(strat_mean, 5),
        'null_mean_ret_mean': round(float(np.mean(null_mean)) if null_mean else 0.0, 5),
        'note': 'null = same entry dates + holding lengths, random symbol; close-to-close, '
                'no SL/target (random entries have none); net of CNC round-trip cost.',
    }
    return out, strat_ts


# ── 2. MULTIPLE-TESTING CORRECTION ───────────────────────────────────────────

def _per_lens_returns(all_trades) -> dict:
    """lens → per-trade net return array (convergence trade credits each member)."""
    out: dict[str, list] = {}
    for t in all_trades:
        for l in t['lens'].split('+'):
            out.setdefault(l, []).append(t['ret'])
    return {l: np.array(v, dtype=float) for l, v in out.items() if len(v) >= 2}


def deflated_sharpe(per_lens, n_trials: int) -> dict:
    """Deflated Sharpe Ratio (Bailey & López de Prado 2014).

    For each lens treated as the selected one out of `n_trials`, compute the
    probability its TRUE per-trade Sharpe > 0 after deflating for (a) the number
    of trials, (b) non-normal returns (skew/kurtosis), (c) sample length.
    DSR > 0.95 ⇒ survives at 5%.
    """
    # per-trade (non-annualised) Sharpe of each lens — DSR works in return units
    sr = {l: (r.mean() / r.std()) for l, r in per_lens.items() if r.std() > 0}
    if len(sr) < 2:
        return {'note': 'need ≥2 lenses for the cross-trial variance term'}
    var_sr = float(np.var(list(sr.values()), ddof=1))
    euler = 0.5772156649
    # expected max Sharpe under the null of zero true skill across n_trials
    z1 = _N.inv_cdf(1 - 1.0 / n_trials)
    z2 = _N.inv_cdf(1 - 1.0 / (n_trials * np.e))
    sr0 = np.sqrt(var_sr) * ((1 - euler) * z1 + euler * z2)

    res = {}
    for l, r in per_lens.items():
        n = len(r)
        s = r.std()
        if s == 0 or n < 3:
            res[l] = {'dsr': 0.0, 'n': n, 'survives': False}
            continue
        srl = r.mean() / s
        g3 = float(((r - r.mean()) ** 3).mean() / s ** 3)            # skew
        g4 = float(((r - r.mean()) ** 4).mean() / s ** 4)            # kurtosis (raw)
        denom = np.sqrt(max(1e-12, 1 - g3 * srl + (g4 - 1) / 4 * srl ** 2))
        dsr = _N.cdf((srl - sr0) * np.sqrt(n - 1) / denom)
        res[l] = {'dsr': round(float(dsr), 4), 'sharpe_per_trade': round(float(srl), 4),
                  'n': n, 'survives': bool(dsr > 0.95)}
    return {'n_trials': n_trials, 'sr0_haircut_per_trade': round(float(sr0), 4),
            'per_lens': res}


def white_reality_check(per_lens, n_boot: int, rng) -> dict:
    """Single-step max-statistic bootstrap (White's Reality Check flavour).

    Null: no lens has mean return > 0. Statistic = max over lenses of the
    studentised mean t = mean/(std/√n). Resample each lens's own returns with
    replacement, RECENTRE to impose the null, recompute max-t → null dist of the
    family-wise maximum. p = P(max_t* ≥ observed max_t).

    Limitation (stated, not hidden): lenses are resampled independently (iid), not
    block-bootstrapped on a shared timeline, so cross-lens contemporaneous
    correlation is not modelled. It is a family-wise screen, not a timeline RC.
    """
    obs, centred = {}, {}
    for l, r in per_lens.items():
        n = len(r); s = r.std()
        obs[l] = (r.mean() / (s / np.sqrt(n))) if s > 0 else 0.0
        centred[l] = r - r.mean()
    obs_max = max(obs.values()) if obs else 0.0
    maxes = np.empty(n_boot)
    for b in range(n_boot):
        m = -np.inf
        for l, c in centred.items():
            n = len(c); s = c.std()
            if s == 0:
                continue
            samp = c[rng.integers(0, n, n)]
            t = samp.mean() / (s / np.sqrt(n))
            if t > m:
                m = t
        maxes[b] = m if np.isfinite(m) else 0.0
    p_family = float((maxes >= obs_max).mean())
    per = {l: {'t': round(float(obs[l]), 3),
               'p_familywise': round(float((maxes >= obs[l]).mean()), 4),
               'survives': bool((maxes >= obs[l]).mean() < 0.05)}
           for l in obs}
    return {'observed_max_t': round(obs_max, 3), 'p_familywise_best': round(p_family, 4),
            'n_boot': n_boot, 'per_lens': per}


# ── 3. PER-STRATEGY SIGNIFICANCE ─────────────────────────────────────────────

def significance(per_lens, n_years: float) -> dict:
    res = {}
    for l, r in per_lens.items():
        n = len(r); s = r.std()
        mean = float(r.mean())
        tstat = float(mean / (s / np.sqrt(n))) if s > 0 else 0.0
        sr_pt = (mean / s) if s > 0 else 0.0                       # per-trade Sharpe
        se_sr = np.sqrt((1 + 0.5 * sr_pt ** 2) / n)                # Lo (2002) SE
        z = sr_pt / se_sr if se_sr > 0 else 0.0
        res[l] = {'n': n, 'mean_ret': round(mean, 5), 't_stat': round(tstat, 2),
                  'sharpe_annual': round(_trade_sharpe(r, n_years), 3),
                  'sharpe_per_trade': round(sr_pt, 4), 'se_sharpe': round(float(se_sr), 4),
                  'sharpe_z': round(float(z), 2), 'noise': bool(abs(z) < 2)}
    return res


# ── 4. LLM / planner marginal value ──────────────────────────────────────────

def planner_isolation(db, days, run_llm, max_llm_calls, n_years):
    out = {}
    modes = [('lenses_only', 'none'), ('planner_degraded', 'degraded')]
    if run_llm:
        modes.append(('planner_llm', 'llm'))
    rets = {}
    for label, mode in modes:
        r = run_backtest(db=db, days=days, planner=mode, max_llm_calls=max_llm_calls,
                         full_trades=True)
        arr = np.array([t['ret'] for t in r['all_trades']], dtype=float)
        rets[label] = arr
        out[label] = {'net_sharpe': r['sharpe'], 'net_return_pct': r['return_pct'],
                      'trade_sharpe': round(_trade_sharpe(arr, n_years), 3),
                      'n_trades': r['trades']['n'],
                      'planner_mode': r['planner']['mode']}
    # marginal value vs lenses-only, with a noise band (SE of Sharpe difference)
    base = rets.get('lenses_only')
    if base is not None and len(base) > 2:
        sr_b = base.mean() / base.std() if base.std() > 0 else 0.0
        se_b = np.sqrt((1 + 0.5 * sr_b ** 2) / len(base))
        for label in ('planner_degraded', 'planner_llm'):
            if label not in rets:
                continue
            a = rets[label]
            sr_a = a.mean() / a.std() if a.std() > 0 else 0.0
            se_a = np.sqrt((1 + 0.5 * sr_a ** 2) / len(a))
            band = 2 * np.sqrt(se_a ** 2 + se_b ** 2)              # ~2σ of the diff
            delta = sr_a - sr_b
            out[label]['delta_sharpe_vs_lenses_per_trade'] = round(float(delta), 4)
            out[label]['noise_band_2se'] = round(float(band), 4)
            out[label]['beats_noise'] = bool(abs(delta) > band)
    out['_training_loop'] = (
        'NOT TESTABLE here. The fine-tuned adapter is never loaded by the backtest, '
        'there is no point-in-time data, and the SFT set includes the system\'s OWN '
        'recent trades + hindsight labels — so any in-sample "improvement" would be '
        'circular. Adapter-vs-base must be judged on a held-out FORWARD window with '
        'frozen weights; that harness does not exist yet. Highest overfit risk.')
    return out


# ── 5. ROBUSTNESS / OVERFIT FRAGILITY ────────────────────────────────────────

def robustness(db, days, base_sharpe):
    out = {'baseline_net_sharpe': base_sharpe, 'params': {}}
    originals = {k: getattr(engine, k) for k in _PERTURB}
    try:
        for name, (val, frac) in _PERTURB.items():
            row = {}
            for tag, mult in (('minus20', 1 - frac), ('plus20', 1 + frac)):
                newv = val * mult
                newv = type(val)(round(newv)) if isinstance(val, int) else newv
                setattr(engine, name, newv)
                r = run_backtest(db=db, days=days, planner='degraded')
                row[tag] = {'value': newv, 'net_sharpe': r['sharpe'],
                            'return_pct': r['return_pct']}
            setattr(engine, name, val)
            sharpes = [base_sharpe, row['minus20']['net_sharpe'], row['plus20']['net_sharpe']]
            row['spread'] = round(max(sharpes) - min(sharpes), 3)
            # fragile = a ±20% nudge erases most of the baseline edge or flips it
            row['fragile'] = bool(min(row['minus20']['net_sharpe'],
                                      row['plus20']['net_sharpe']) < base_sharpe * 0.5)
            out['params'][name] = row
    finally:
        for k, v in originals.items():
            setattr(engine, k, v)
    # PERSIST_N stepped explicitly (±20% of 2 rounds back to 2)
    pn = engine.PERSIST_N
    row = {}
    for tag, nv in (('to_1', max(1, pn - 1)), ('to_3', pn + 1)):
        engine.PERSIST_N = nv
        r = run_backtest(db=db, days=days, planner='degraded')
        row[tag] = {'value': nv, 'net_sharpe': r['sharpe'], 'return_pct': r['return_pct']}
    engine.PERSIST_N = pn
    out['params']['PERSIST_N'] = row
    return out


# ── 6. REGIME & TIME CONCENTRATION ───────────────────────────────────────────

def concentration(result) -> dict:
    def share(by: dict) -> tuple[str, float, float]:
        pos = {k: v.get('total_pnl', 0) for k, v in by.items() if v.get('n', 0) > 0}
        tot = sum(pos.values())
        if not pos or tot <= 0:
            return ('—', 0.0, tot)
        best = max(pos, key=pos.get)
        return (best, pos[best] / tot, tot)

    by_year, by_reg = result.get('walk_forward_years', {}), result.get('per_regime', {})
    yb, yshare, ytot = share(by_year)
    rb, rshare, rtot = share(by_reg)

    # worst rolling 12-month return off the (downsampled) equity curve
    curve = result.get('equity_curve', [])
    worst_12m = None
    if len(curve) > 5:
        eq = np.array([p['equity'] for p in curve], dtype=float)
        pts_per_year = max(2, int(len(eq) / max(result['days'] / 252, 1)))
        worst = 1e9
        for i in range(len(eq) - pts_per_year):
            worst = min(worst, eq[i + pts_per_year] / eq[i] - 1)
        worst_12m = round(float(worst), 4) if worst < 1e9 else None
    return {
        'best_year': yb, 'best_year_pnl_share': round(yshare, 3),
        'best_regime': rb, 'best_regime_pnl_share': round(rshare, 3),
        'best_year_dominates': bool(yshare > 0.5),
        'best_regime_dominates': bool(rshare > 0.5),
        'worst_rolling_12m_return': worst_12m,
        'note': 'rolling-12m off the ≤300-pt downsampled curve (approximate).',
    }


# ── survivorship: which symbols did not exist / trade in 2016 ────────────────

def survivorship(first_listing: dict, cutoff: str | None = None) -> dict:
    """Flag symbols that first traded materially after the data floor.

    The DB's deepest bar (~10y backfill) is itself a floor: blue-chips all show
    that date because that's where history was fetched from, NOT their listing.
    So we anchor the cutoff to floor + ~90d and flag only symbols that begin
    clearly later — those are genuine late-listers (post-floor IPOs). The deeper,
    UNquantifiable bias is that the universe is today's survivors: names relegated
    or delisted from the index over the window are absent and invisible here.
    """
    if not first_listing:
        return {'note': 'no symbols'}
    floor = min(first_listing.values())
    if cutoff is None:
        fy, fm = int(floor[:4]), int(floor[5:7])             # first day of next month
        cutoff = f'{fy}-{fm + 1:02d}-01' if fm < 12 else f'{fy + 1}-01-01'
    late = {s: d for s, d in first_listing.items() if d > cutoff}
    return {'data_floor': floor, 'cutoff': cutoff, 'n_universe': len(first_listing),
            'n_at_data_floor': sum(1 for d in first_listing.values() if d <= cutoff),
            'n_listed_after_floor': len(late),
            'late_listers': dict(sorted(late.items(), key=lambda kv: kv[1], reverse=True)),
            'note': 'first DB bar per symbol; cutoff anchored ~1 month past the data '
                    'floor to separate true post-floor IPOs from the backfill boundary. '
                    'yfinance auto_adjust=True (retroactive) — NOT point-in-time. '
                    'Index-exit/delisted names are absent entirely (unmeasurable here).'}


# ── orchestration ────────────────────────────────────────────────────────────

def validate(db=None, days: int = 2470, run_llm: bool = False, max_llm_calls: int = 150,
             null_runs: int = 1000, n_boot: int = 2000, n_trials: int = 8,
             seed: int = 7) -> dict:
    if db is None:
        from terminal_in.config import load_config
        from terminal_in.db import DB
        db = DB(load_config().sqlite_path)
    rng = np.random.default_rng(seed)
    t0 = time.time()

    log.info('validation: baseline run (degraded) …')
    base = run_backtest(db=db, days=days, planner='degraded', full_trades=True)
    all_trades = base['all_trades']
    n_years = max(base['days'] / 252.0, 1e-9)
    base_sharpe = base['sharpe']
    # strategy curve stats on the FULL daily curve — same basis as the benchmarks
    strat_eq = np.array([v for _, v in base['daily_equity_full']], dtype=float)
    strat_stats = _curve_stats(strat_eq, n_years)

    uni, nifty, dates, _windowed = _load(db, days)
    # true first-listing dates (full history, NOT the windowed load) for survivorship
    from terminal_in.data_ingest.instruments import KNOWN_TOKENS, registry
    eq_tokens = {t: s for s, t in KNOWN_TOKENS.items() if registry.sector(t) not in ('index',)}
    firsts = db.get_ohlcv_first_dates(list(eq_tokens))
    first_listing = {eq_tokens[t]: str(d)[:10] for t, d in firsts.items() if d}
    per_lens = _per_lens_returns(all_trades)

    log.info('validation: benchmarks + %d null runs …', null_runs)
    bench, strat_ts = benchmarks(uni, nifty, dates, all_trades, n_years, null_runs, rng)
    bh = bench.get('buy_hold_nifty', {})
    beats_bh = (isinstance(bh, dict) and 'sharpe' in bh and base_sharpe > bh['sharpe'])

    report = {
        'ts': int(time.time() * 1000), 'days': days, 'n_years': round(n_years, 2),
        'n_trades': base['trades']['n'], 'symbols': base['symbols_tested'],
        'headline': _headline(base, bh, beats_bh),
        'strategy_net': {'cagr_pct': base.get('cagr_pct'), 'sharpe': base_sharpe,
                         'sortino': round(strat_stats['sortino'], 3),
                         'calmar': round(strat_stats['calmar'], 3),
                         'max_dd_pct': base['max_drawdown_pct'],
                         'return_pct': base['return_pct'],
                         'gross': base.get('gross'), 'costs': base.get('costs')},
        'benchmarks': bench,
        'beats_buy_hold_nifty': beats_bh,
        'multiple_testing': {
            'deflated_sharpe': deflated_sharpe(per_lens, n_trials),
            'reality_check': white_reality_check(per_lens, n_boot, rng),
        },
        'significance': significance(per_lens, n_years),
        'planner_isolation': planner_isolation(db, days, run_llm, max_llm_calls, n_years),
        'robustness': robustness(db, days, base_sharpe),
        'concentration': concentration(base),
        'survivorship': survivorship(first_listing),
        'elapsed_s': round(time.time() - t0, 1),
    }
    return report


def _headline(base, bh, beats_bh) -> str:
    if not isinstance(bh, dict) or 'sharpe' not in bh:
        return 'NO BENCHMARK: NIFTY series unavailable — cannot judge alpha.'
    d = base['sharpe'] - bh['sharpe']
    if beats_bh:
        return (f"Strategy net Sharpe {base['sharpe']:.2f} vs buy-hold NIFTY "
                f"{bh['sharpe']:.2f} (+{d:.2f}). Beats passive — but see deflation/"
                f"significance/concentration before calling it alpha.")
    return (f"NO ALPHA: strategy net Sharpe {base['sharpe']:.2f} does NOT beat "
            f"buy-and-hold NIFTY {bh['sharpe']:.2f} ({d:+.2f}) net of costs.")


def _print(r: dict):
    P = print
    P('\n' + '=' * 78)
    P('ALPHA VALIDATION —', r['days'], 'days /', r['n_years'], 'y /', r['n_trades'],
      'trades /', r['symbols'], 'symbols')
    P('=' * 78)
    P('\n>>> ' + r['headline'] + '\n')

    bh = r['benchmarks'].get('buy_hold_nifty', {})
    ew = r['benchmarks'].get('equal_weight_universe', {})
    s = r['strategy_net']
    P('BENCHMARKS (net of costs)        CAGR    Sharpe   Sortino   MaxDD    Calmar')
    def line(name, m):
        if 'sharpe' not in m:
            P(f'  {name:<28}{m.get("note","n/a")}'); return
        P(f'  {name:<28}{m.get("cagr",0)*100:6.2f}%  {m["sharpe"]:6.2f}  '
          f'{m["sortino"]:7.2f}  {m["max_dd"]*100:6.2f}%  {m["calmar"]:6.2f}')
    line('STRATEGY (net)', {'cagr': (s.get('cagr_pct') or 0)/100, 'sharpe': s['sharpe'],
                            'sortino': s.get('sortino', 0.0), 'max_dd': s['max_dd_pct']/100,
                            'calmar': s.get('calmar', 0.0)})
    line('Buy-hold NIFTY', bh)
    line('Equal-weight universe', ew)
    nr = r['benchmarks'].get('null_random', {})
    P(f'\nNULL (random symbols, same timing, {nr.get("runs",0)} runs):')
    P(f'  strategy trade-Sharpe {nr.get("strategy_trade_sharpe")} vs null mean '
      f'{nr.get("null_sharpe_mean")} (p95 {nr.get("null_sharpe_p95")}) -> '
      f'{nr.get("strategy_percentile_vs_null")}th percentile')

    P('\nMULTIPLE TESTING')
    dsr = r['multiple_testing']['deflated_sharpe']
    P(f'  Deflated Sharpe (N={dsr.get("n_trials")} trials, haircut '
      f'{dsr.get("sr0_haircut_per_trade")}/trade):')
    for l, v in (dsr.get('per_lens') or {}).items():
        P(f'    {l:<6} DSR={v["dsr"]:.3f}  n={v["n"]:<5} '
          f'{"SURVIVES" if v["survives"] else "dies"}')
    rc = r['multiple_testing']['reality_check']
    P(f'  Reality-Check family-wise p(best) = {rc.get("p_familywise_best")} '
      f'(max-t {rc.get("observed_max_t")})')
    for l, v in (rc.get('per_lens') or {}).items():
        P(f'    {l:<6} t={v["t"]:<7} p_fw={v["p_familywise"]:.3f} '
          f'{"survives" if v["survives"] else "dies"}')

    P('\nPER-STRATEGY SIGNIFICANCE (flag: Sharpe < 2 SE from zero)')
    for l, v in r['significance'].items():
        P(f'  {l:<6} n={v["n"]:<5} mean={v["mean_ret"]:+.4f} t={v["t_stat"]:+6.2f} '
          f'SR={v["sharpe_annual"]:+.2f} z={v["sharpe_z"]:+.2f} '
          f'{"** NOISE **" if v["noise"] else "ok"}')

    P('\nPLANNER ISOLATION (net Sharpe; marginal vs lenses-only)')
    pi = r['planner_isolation']
    for label in ('lenses_only', 'planner_degraded', 'planner_llm'):
        if label not in pi:
            continue
        v = pi[label]
        extra = ''
        if 'delta_sharpe_vs_lenses_per_trade' in v:
            extra = (f"  d={v['delta_sharpe_vs_lenses_per_trade']:+.4f} "
                     f"band+/-{v['noise_band_2se']:.4f} "
                     f"{'REAL' if v['beats_noise'] else 'within noise'}")
        P(f'  {label:<18} net_sharpe={v["net_sharpe"]:+.2f} '
          f'ret={v["net_return_pct"]:+.1f}% n={v["n_trades"]}{extra}')
    P('  training-loop: ' + pi['_training_loop'][:96] + '...')

    P('\nROBUSTNESS (±20% one-at-a-time; baseline net Sharpe '
      f'{r["robustness"]["baseline_net_sharpe"]:+.2f})')
    for name, row in r['robustness']['params'].items():
        keys = [k for k in row if isinstance(row[k], dict)]
        cells = '  '.join(f'{k}={row[k]["net_sharpe"]:+.2f}' for k in keys)
        flag = ' << FRAGILE' if row.get('fragile') else ''
        P(f'  {name:<14} {cells}{flag}')

    c = r['concentration']
    P('\nCONCENTRATION')
    P(f'  best year {c["best_year"]} = {c["best_year_pnl_share"]*100:.0f}% of net P&L'
      f'{"  << >50%" if c["best_year_dominates"] else ""}')
    P(f'  best regime {c["best_regime"]} = {c["best_regime_pnl_share"]*100:.0f}% of net P&L'
      f'{"  << >50%" if c["best_regime_dominates"] else ""}')
    P(f'  worst rolling 12m return = '
      f'{c["worst_rolling_12m_return"]*100 if c["worst_rolling_12m_return"] is not None else float("nan"):.1f}%')

    sv = r['survivorship']
    P('\nSURVIVORSHIP / DATA HONESTY')
    P(f'  data floor {sv.get("data_floor")} ({sv.get("n_at_data_floor")} symbols start here '
      f'= backfill boundary, not listing).')
    P(f'  {sv.get("n_listed_after_floor")}/{sv["n_universe"]} first traded AFTER the floor '
      f'(true late-listers). Universe = today\'s survivors; delisted/relegated names absent.')
    if sv['late_listers']:
        items = list(sv['late_listers'].items())[:14]
        P('   ' + ', '.join(f'{s}({d})' for s, d in items))
    P('=' * 78 + '\n')


# ════════════════════════════════════════════════════════════════════════════
# MODULE 6 — Phase C (competence) + Phase D₀ (GBT EV head) OOS validation
# ════════════════════════════════════════════════════════════════════════════

def _judge_stats(result: dict, n_years: float) -> dict:
    eq = np.array([v for _, v in result['daily_equity_full']], dtype=float)
    st = _curve_stats(eq, n_years)
    rets = np.array([t['ret'] for t in result['all_trades']], dtype=float)
    st['net_sharpe'] = result['sharpe']           # daily-curve Sharpe (headline)
    st['return_pct'] = result['return_pct']
    st['n'] = result['trades']['n']
    st['trade_sharpe'] = _trade_sharpe(rets, n_years)
    st['ev_source'] = result.get('planner', {}).get('ev_source', 'heuristic')
    st['_rets'] = rets
    return st


def _regime_regression(flat: dict, cand: dict) -> dict:
    """Per-regime mean net trade-return: flat vs candidate. Reports the worst
    regression in percentage points (gate: no >5pt category regression)."""
    def by_regime(res):
        d: dict[str, list] = {}
        for t in res['all_trades']:
            d.setdefault(t['regime'], []).append(t['ret'])
        return {k: float(np.mean(v)) for k, v in d.items() if v}
    a, b = by_regime(flat), by_regime(cand)
    rows, worst = {}, 0.0
    for reg in sorted(set(a) | set(b)):
        fa, fb = a.get(reg, 0.0), b.get(reg, 0.0)
        reg_pp = (fa - fb) * 100        # positive = candidate regressed
        rows[reg] = {'flat': round(fa, 4), 'cand': round(fb, 4), 'regress_pp': round(reg_pp, 2)}
        worst = max(worst, reg_pp)
    return {'per_regime': rows, 'worst_regression_pp': round(worst, 2),
            'passes_5pt': bool(worst <= 5.0)}


def validate_m6(db=None, days: int = 2470, horizon: int = 20, n_trials: int = 8,
                competence_mode: str = 'veto', seed: int = 7) -> dict:
    """Phase C + D₀ out-of-sample validation, gated through this harness."""
    from terminal_in.m6.dataset import build_candidate_dataset, LENS_COLS
    from terminal_in.m6.competence import CompetenceTable, THRESHOLD_DEFAULT
    from terminal_in.m6 import ev_head as EV

    if db is None:
        from terminal_in.config import load_config
        from terminal_in.db import DB
        db = DB(load_config().sqlite_path)
    t0 = time.time()
    n_years = max(days / 252.0, 1e-9)

    log.info('m6: building candidate dataset …')
    ds = build_candidate_dataset(db=db, days=days, horizon=horizon)

    # ── baselines + judges, all same data/costs ──
    log.info('m6: baseline (flat heuristic) …')
    flat = run_backtest(db=db, days=days, planner='none', full_trades=True)
    ct = CompetenceTable(ds, threshold=THRESHOLD_DEFAULT)
    log.info('m6: competence-gated backtest …')
    comp = run_backtest(db=db, days=days, planner='none', full_trades=True,
                        competence_gate=ct.gate(competence_mode))
    log.info('m6: walk-forward EV-head training …')
    wf = EV.WalkForwardEV(ds, seed=seed)
    folds = wf.train_folds()
    log.info('m6: GBT-EV-head backtest …')
    gbt = run_backtest(db=db, days=days, planner='none', full_trades=True,
                       ev_override=wf.ev_override())

    s_flat, s_comp, s_gbt = (_judge_stats(flat, n_years), _judge_stats(comp, n_years),
                             _judge_stats(gbt, n_years))

    # benchmark: buy-and-hold NIFTY (same loader as the main harness)
    uni, nifty, dates, _ = _load(db, days)
    bh = benchmarks(uni, nifty, dates, flat['all_trades'], n_years, 1, np.random.default_rng(seed))[0]
    bh_sharpe = bh.get('buy_hold_nifty', {}).get('sharpe', float('nan'))

    # ── Phase C: abstention attribution (point-in-time competence on the dataset) ──
    ann = ct.annotate(ds)
    fired = ann[ann['fired'] == 1]
    kept = fired[~fired['comp_abstain']]
    abst = fired[fired['comp_abstain']]
    def blk(g):
        r = g['ret_net'].to_numpy(float)
        return {'n': int(len(r)), 'mean_ret': round(float(r.mean()), 5) if len(r) else 0.0,
                'trade_sharpe': _trade_sharpe(r, n_years), 'win_rate': round(float((r > 0).mean()), 3) if len(r) else 0.0}
    phase_c = {
        'threshold': THRESHOLD_DEFAULT, 'mode': competence_mode,
        'flat': {'net_sharpe': s_flat['net_sharpe'], 'return_pct': s_flat['return_pct'],
                 'sortino': round(s_flat['sortino'], 3), 'max_dd': round(s_flat['max_dd'], 4),
                 'calmar': round(s_flat['calmar'], 3), 'n': s_flat['n']},
        'competence': {'net_sharpe': s_comp['net_sharpe'], 'return_pct': s_comp['return_pct'],
                       'sortino': round(s_comp['sortino'], 3), 'max_dd': round(s_comp['max_dd'], 4),
                       'calmar': round(s_comp['calmar'], 3), 'n': s_comp['n']},
        'abstention': {
            'abstain_rate_of_fired': round(float(len(abst) / max(len(fired), 1)), 3),
            'all_fired': blk(fired), 'kept': blk(kept), 'abstained': blk(abst)},
        'beats_flat_sharpe': bool(s_comp['net_sharpe'] >= s_flat['net_sharpe']),
        'abstention_value_additive': bool(len(abst) > 0 and abst['ret_net'].mean() < kept['ret_net'].mean()),
    }

    # ── Phase D₀: feature importance, echo guard, calibration, gates ──
    last_fold = max((f for f in folds if f['trained']), key=lambda f: f['n_train'], default=None)
    feat_imp, echo, calib = {}, {}, []
    if last_fold is not None:
        year = last_fold['fold']; start = last_fold['train_cutoff']
        train = ds[ds['outcome_date'] < start]
        test = ds[(ds['date'] >= start) & (ds['date'] < f'{int(year) + 1}-01-01')]
        all_head, fired_head = EV.fit_echo_pair(train, seed=seed)
        if all_head is not None:
            feat_imp = all_head.feature_importance()
            calib = all_head.calibration(test) if len(test) else []
        if all_head is not None and fired_head is not None and len(test):
            pa = np.array([all_head.predict(r)[0] for r in test.to_dict('records')])
            pf = np.array([fired_head.predict(r)[0] for r in test.to_dict('records')])
            corr = float(np.corrcoef(pa, pf)[0, 1]) if pa.std() and pf.std() else 0.0
            echo = {'fold': year, 'pred_corr_all_vs_fired': round(corr, 3),
                    'mean_abs_diff': round(float(np.abs(pa - pf).mean()), 4),
                    'diverges': bool(corr < 0.8)}
    top2 = list(feat_imp)[:2]
    relearned_heuristic = bool(set(top2) <= {'ev', 'confidence'})

    # gate (c): deflated Sharpe on the GBT judge's per-lens trades
    gbt_per_lens = _per_lens_returns(gbt['all_trades'])
    dsr = deflated_sharpe(gbt_per_lens, n_trials)
    dsr_survivors = [l for l, v in (dsr.get('per_lens') or {}).items() if v.get('survives')]
    reg_reg = _regime_regression(flat, gbt)

    phase_d0 = {
        'folds': folds,
        'fallback_candidate_frac': round(gbt['planner']['ev_source_counts'].get('heuristic', 0) /
                                         max(sum(gbt['planner']['ev_source_counts'].values()), 1), 3),
        'heuristic': {'net_sharpe': s_flat['net_sharpe'], 'return_pct': s_flat['return_pct'],
                      'sortino': round(s_flat['sortino'], 3), 'calmar': round(s_flat['calmar'], 3)},
        'gbt': {'net_sharpe': s_gbt['net_sharpe'], 'return_pct': s_gbt['return_pct'],
                'sortino': round(s_gbt['sortino'], 3), 'max_dd': round(s_gbt['max_dd'], 4),
                'calmar': round(s_gbt['calmar'], 3), 'n': s_gbt['n'], 'ev_source': s_gbt['ev_source']},
        'feature_importance': feat_imp, 'relearned_heuristic': relearned_heuristic,
        'echo_guard': echo, 'calibration': calib,
        'regime_regression': reg_reg,
        'deflated_sharpe': dsr, 'dsr_survivors': dsr_survivors,
        'gate_a_beats_heuristic': bool(s_gbt['net_sharpe'] > s_flat['net_sharpe'] and reg_reg['passes_5pt']),
        'gate_b_beats_buyhold': bool(s_gbt['net_sharpe'] > bh_sharpe),
        'gate_c_survives_dsr': bool(len(dsr_survivors) > 0),
    }
    return {'ts': int(time.time() * 1000), 'days': days, 'n_years': round(n_years, 2),
            'dataset_rows': int(len(ds)), 'horizon': horizon,
            'buy_hold_nifty_sharpe': round(float(bh_sharpe), 3) if bh_sharpe == bh_sharpe else None,
            'phase_c': phase_c, 'phase_d0': phase_d0, 'elapsed_s': round(time.time() - t0, 1)}


def validate_event_ablation(db=None, days: int = 2470, horizon: int = 20,
                            n_trials: int = 8, seed: int = 7) -> dict:
    """Phase 3 ablation: does the orthogonal EVENT plane add OOS lift to the D₀
    head? Runs the GBT-EV judge two ways under identical per-fold walk-forward
    fencing — (i) technical features only, (ii) technical + PEAD event features —
    and reports the delta + whether it survives multiple-testing. If it doesn't
    add net lift, the honest verdict is to drop the event features."""
    from terminal_in.m6.dataset import build_candidate_dataset
    from terminal_in.m6 import ev_head as EV
    from terminal_in.m6.event_features import (add_event_features, EVENT_FEATURES,
                                               event_consensus_coverage)
    from terminal_in.data_ingest import events as EVT

    if db is None:
        from terminal_in.config import load_config
        from terminal_in.db import DB
        db = DB(load_config().sqlite_path)
    t0 = time.time()
    n_years = max(days / 252.0, 1e-9)

    log.info('event-ablation: dataset + event features …')
    ds = build_candidate_dataset(db=db, days=days, horizon=horizon)
    ev_archive = EVT.load_events()
    ds = add_event_features(ds, db, ev_archive)
    consensus_pct = event_consensus_coverage(ds)

    # technical-only vs technical+event, same fences
    log.info('event-ablation: training + backtesting technical-only …')
    wf_t = EV.WalkForwardEV(ds, seed=seed, extra_num=[])
    wf_t.train_folds()
    tech = run_backtest(db=db, days=days, planner='none', full_trades=True,
                        ev_override=wf_t.ev_override())
    log.info('event-ablation: training + backtesting technical+event …')
    wf_e = EV.WalkForwardEV(ds, seed=seed, extra_num=EVENT_FEATURES)
    wf_e.train_folds()
    evt = run_backtest(db=db, days=days, planner='none', full_trades=True,
                       ev_override=wf_e.ev_override())

    s_t, s_e = _judge_stats(tech, n_years), _judge_stats(evt, n_years)
    rets_t, rets_e = s_t['_rets'], s_e['_rets']
    sr_t = rets_t.mean() / rets_t.std() if len(rets_t) > 1 and rets_t.std() else 0.0
    sr_e = rets_e.mean() / rets_e.std() if len(rets_e) > 1 and rets_e.std() else 0.0
    band = 2 * np.sqrt((1 + 0.5 * sr_t ** 2) / max(len(rets_t), 1) +
                       (1 + 0.5 * sr_e ** 2) / max(len(rets_e), 1))
    delta = sr_e - sr_t

    uni, nifty, dates, _ = _load(db, days)
    bh = benchmarks(uni, nifty, dates, tech['all_trades'], n_years, 1, np.random.default_rng(seed))[0]
    bh_sharpe = bh.get('buy_hold_nifty', {}).get('sharpe', float('nan'))

    # event-feature importance + the PEAD core check: does the immediate reaction
    # predict the subsequent realized outcome? (our consensus-free 'surprise→drift')
    last = max((f for f in wf_e.folds if f['trained']), key=lambda f: f['n_train'], default=None)
    feat_imp_evt = {}
    if last is not None:
        train = ds[ds['outcome_date'] < last['train_cutoff']]
        head = EV.GBTEvHead(seed, extra_num=EVENT_FEATURES).fit(train)
        fi = head.feature_importance()
        feat_imp_evt = {k: v for k, v in fi.items() if k.startswith('evt_')}
    in_win = ds[ds['evt_in_drift_window'] == 1.0]
    reaction_drift = {
        'rows_in_drift_window': int(len(in_win)),
        'corr_reaction_gap_vs_forward_ret': round(float(np.corrcoef(
            in_win['evt_reaction_gap'], in_win['ret_net'])[0, 1]), 4) if len(in_win) > 50 and in_win['evt_reaction_gap'].std() else 0.0,
        'mean_fwd_ret_pos_reaction': round(float(in_win[in_win['evt_reaction_gap'] > 0]['ret_net'].mean()), 5) if len(in_win) else 0.0,
        'mean_fwd_ret_neg_reaction': round(float(in_win[in_win['evt_reaction_gap'] < 0]['ret_net'].mean()), 5) if len(in_win) else 0.0,
    }

    dsr_e = deflated_sharpe(_per_lens_returns(evt['all_trades']), n_trials)
    reg = _regime_regression(tech, evt)
    delta_survives = bool(abs(delta) > band and delta > 0)
    return {
        'ts': int(time.time() * 1000), 'days': days, 'n_years': round(n_years, 2),
        'horizon': horizon, 'dataset_rows': int(len(ds)),
        'events': {'archive_rows': int(len(ev_archive)),
                   'symbols_with_events': int(ev_archive['symbol'].nunique()) if len(ev_archive) else 0,
                   'pit_consensus_pct': consensus_pct,
                   'by_type': ev_archive['event_type'].value_counts().to_dict() if len(ev_archive) else {}},
        'buy_hold_nifty_sharpe': round(float(bh_sharpe), 3) if bh_sharpe == bh_sharpe else None,
        'technical_only': {'net_sharpe': s_t['net_sharpe'], 'return_pct': s_t['return_pct'],
                           'sortino': round(s_t['sortino'], 3), 'calmar': round(s_t['calmar'], 3),
                           'n': s_t['n'], 'trade_sharpe_per_trade': round(float(sr_t), 4)},
        'technical_plus_event': {'net_sharpe': s_e['net_sharpe'], 'return_pct': s_e['return_pct'],
                                 'sortino': round(s_e['sortino'], 3), 'calmar': round(s_e['calmar'], 3),
                                 'n': s_e['n'], 'trade_sharpe_per_trade': round(float(sr_e), 4)},
        'delta_trade_sharpe': round(float(delta), 4), 'noise_band_2se': round(float(band), 4),
        'event_adds_oos_lift': delta_survives,
        'event_feature_importance': feat_imp_evt,
        'reaction_drift_calibration': reaction_drift,
        'deflated_sharpe_event': {'survivors': [l for l, v in (dsr_e.get('per_lens') or {}).items() if v.get('survives')]},
        'regime_regression': reg,
        'verdict_drop_event_features': bool(not delta_survives),
        'elapsed_s': round(time.time() - t0, 1),
    }


def validate_longshort(db=None, days: int = 2470, horizon: int = 20, quantile: float = 0.2,
                       seed: int = 7, wide: bool = False) -> dict:
    """A1 + A2 — cross-sectional, market-neutral test (the right frame for selection
    skill: discriminate BETWEEN names, don't try to out-return a bull index).

    A1: cross-sectional Information Coefficient — each rebalance, rank names by a
        signal and Spearman-correlate against the forward `horizon`-day return.
        Mean IC + IC-IR (mean/std·√n) per signal; OOS by year. If IC≈0, stop.
    A2: dollar-neutral book — long top quantile / short bottom quantile, equal
        weight, rebalanced every `horizon` days. INDIAN CONTEXT: the short leg is a
        single-stock future (F&O names), priced at _FUT_RT_FRAC; the long leg is
        cash CNC. Benchmark is ZERO (cash) — a neutral book's bar, not NIFTY.

    Signals tested are clean cross-sectional factors (no lookahead): 12-1 momentum
    and 1-month reversal — both documented on NSE — so this measures whether the
    UNIVERSE has harvestable cross-sectional dispersion at all, before blaming the
    lens machinery."""
    from scipy.stats import spearmanr
    if db is None:
        from terminal_in.config import load_config
        from terminal_in.db import DB
        db = DB(load_config().sqlite_path)
    n_years = max(days / 252.0, 1e-9)
    uni, _nifty, dates, _fl = _load(db, days)
    if wide:
        uni = {**uni, **_load_research(db, days)}   # + Nifty Midcap 150 research set

    # aligned close matrix (names × dates)
    syms = sorted(uni.keys())
    M = pd.DataFrame({s: uni[s].reindex(dates) for s in syms}).astype(float)
    idx = list(range(252, len(dates) - horizon, horizon))   # rebalance points

    def signal_at(i, kind):
        c0, c21, c252 = M.iloc[i], M.iloc[i - 21], M.iloc[i - 252]
        if kind == 'mom_12_1':
            return c21 / c252 - 1.0                          # 12m return skipping last month
        return -(c0 / c21 - 1.0)                             # 1-month reversal

    results = {}
    for kind in ('mom_12_1', 'reversal_1m'):
        ics, periods, eq, equity = [], [], [], 1.0
        prev_long, prev_short, turns = set(), set(), []
        for i in idx:
            sig = signal_at(i, kind)
            fwd = M.iloc[i + horizon] / M.iloc[i] - 1.0
            ok = sig.notna() & fwd.notna()
            if ok.sum() < 10:
                continue
            s, f = sig[ok], fwd[ok]
            ic = spearmanr(s, f).correlation
            if ic == ic:
                ics.append((str(dates[i])[:10], float(ic)))
            n_q = max(2, int(len(s) * quantile))
            longs = set(s.nlargest(n_q).index)
            shorts = set(s.nsmallest(n_q).index)
            spread = float(f[list(longs)].mean() - f[list(shorts)].mean())
            # turnover vs previous book → cost on the replaced fraction (both legs)
            tl = 1.0 - len(longs & prev_long) / max(len(longs), 1)
            ts = 1.0 - len(shorts & prev_short) / max(len(shorts), 1)
            turns.append((tl + ts) / 2)
            cost = tl * _RT_FRAC + ts * _FUT_RT_FRAC
            net = spread - cost                              # 1x long + 1x short on NAV
            equity *= (1 + net)
            periods.append({'date': str(dates[i])[:10], 'spread': round(spread, 5),
                            'net': round(net, 5)})
            eq.append(equity)
            prev_long, prev_short = longs, shorts

        ic_vals = np.array([v for _, v in ics])
        net_rets = np.array([p['net'] for p in periods])
        ppy = 252 / horizon
        sharpe = float(net_rets.mean() / net_rets.std() * np.sqrt(ppy)) if len(net_rets) > 2 and net_rets.std() else 0.0
        eqa = np.array(eq)
        dd = float((eqa / np.maximum.accumulate(eqa) - 1).min()) if len(eqa) else 0.0
        ic_ir = float(ic_vals.mean() / ic_vals.std() * np.sqrt(len(ic_vals))) if len(ic_vals) > 2 and ic_vals.std() else 0.0
        # OOS by year (IC is the cleanest per-fold cut)
        by_year = {}
        for d, v in ics:
            by_year.setdefault(d[:4], []).append(v)
        results[kind] = {
            'mean_ic': round(float(ic_vals.mean()), 5) if len(ic_vals) else 0.0,
            'ic_ir': round(ic_ir, 3), 'n_rebalances': len(ic_vals),
            'ls_net_sharpe': round(sharpe, 3),
            'ls_total_return_pct': round((equity - 1) * 100, 2),
            'ls_max_dd_pct': round(dd * 100, 2),
            'avg_turnover': round(float(np.mean(turns)), 3) if turns else 0.0,
            'mean_gross_spread_per_period': round(float(np.mean([p['spread'] for p in periods])), 5) if periods else 0.0,
            'ic_by_year': {y: round(float(np.mean(v)), 4) for y, v in sorted(by_year.items())},
        }
    return {'ts': int(time.time() * 1000), 'days': days, 'n_years': round(n_years, 2),
            'horizon': horizon, 'quantile': quantile, 'n_symbols': len(syms),
            'universe': 'wide_large72+midcap150' if wide else 'large72',
            'short_leg_cost_frac_estimate': _FUT_RT_FRAC,
            'long_leg_cost_frac': round(_RT_FRAC, 5), 'signals': results,
            'survivorship_warning': ('WIDE universe membership is a CURRENT SNAPSHOT '
                                     '(today\'s survivors back to 2016) — IC/spread are '
                                     'UPWARD-BIASED until dated reconstitution incl. '
                                     'delisted names lands.') if wide else None,
            'india_note': 'short leg = single-stock FUTURES (F&O names only); cash '
                          'segment cannot hold overnight shorts. Benchmark = 0 (cash).'}


def validate_longshort_directional(db=None, days: int = 2470, horizon: int = 21,
                                   quantile: float = 0.2, seed: int = 7,
                                   wide: bool = False) -> dict:
    """#1 — directional long/short across OUR signals, with the honest benchmark
    baked in. For each cross-sectional signal (incl. the system's own lens score),
    rank names and report, per signal:
      - IC-IR (cross-sectional skill),
      - LONG-ONLY top-quantile vs the EQUAL-WEIGHT universe (the *correct* long-only
        benchmark — raw return vs cap-weighted NIFTY flatters via the size effect),
      - SHORT-LEG contribution (equal-weight − bottom-quantile; >0 ⇒ shorting helps,
        <0 ⇒ shorting DRAGS — what we found for reversal),
      - market-neutral L/S net Sharpe + the long leg's beta to NIFTY.
    Answers 'what does shorting our signals actually do, OOS' without any live
    short-execution plumbing (this is a research probe; benchmark for L/S = 0)."""
    from scipy.stats import spearmanr
    if db is None:
        from terminal_in.config import load_config
        from terminal_in.db import DB
        db = DB(load_config().sqlite_path)
    from terminal_in.data_ingest.instruments import KNOWN_TOKENS, registry
    registry.load_stubs()
    ppy = 252 / horizon

    eq_tokens = {t: s for s, t in KNOWN_TOKENS.items() if registry.sector(t) not in ('index',)}
    if wide:
        from terminal_in.data_ingest.index_membership import RESEARCH_BY_TOKEN
        eq_tokens = {**eq_tokens, **RESEARCH_BY_TOKEN}
    nifty_tok, vix_tok = KNOWN_TOKENS.get('NIFTY 50'), KNOWN_TOKENS.get('INDIA VIX')
    all_1d = db.get_ohlcv_1d_all(list(eq_tokens) + [t for t in (nifty_tok, vix_tok) if t], limit=days + 320)
    regimes = engine._regime_series(all_1d.get(nifty_tok), all_1d.get(vix_tok))
    nif = all_1d.get(nifty_tok)

    ind = {}                                    # per-name indicator frames (for lens score)
    closes = {}
    for t, s in eq_tokens.items():
        df = all_1d.get(t)
        if df is None or len(df) < 300:
            continue
        ind[s] = engine._indicators(df)
        closes[s] = df['close']
    dates = sorted(set().union(*[set(c.index) for c in closes.values()]))[-days:]
    M = pd.DataFrame({s: closes[s].reindex(dates) for s in closes}).astype(float)
    nser = nif['close'].reindex(dates).astype(float) if nif is not None else None
    idx = list(range(252, len(M) - horizon, horizon))

    def lens_score_row(i):
        d = dates[i]; reg = regimes.get(d, 'sideways'); out = {}
        for s, fr in ind.items():
            if d not in fr.index:
                continue
            lst = engine._lenses(fr.loc[d], reg)
            out[s] = float(sum(c for _, c in lst))     # 0 if no lens fires
        return pd.Series(out)

    def sig_at(i, kind):
        if kind == 'mom_12_1':
            return M.iloc[i - 21] / M.iloc[i - 252] - 1.0
        if kind == 'reversal_1m':
            return -(M.iloc[i] / M.iloc[i - 21] - 1.0)
        return lens_score_row(i)                       # 'lens_score'

    res = {}
    for kind in ('lens_score', 'reversal_1m', 'mom_12_1'):
        ics, lo, ew, ls, lo_b, nf = [], [], [], [], [], []
        prevL = set()
        for i in idx:
            sig = sig_at(i, kind); fwd = M.iloc[i + horizon] / M.iloc[i] - 1.0
            ok = sig.notna() & fwd.notna()
            if ok.sum() < 10:
                continue
            s, f = sig[ok], fwd[ok]
            if s.std() == 0:
                continue
            c = spearmanr(s, f).correlation
            if c == c:
                ics.append(c)
            nq = max(2, int(len(s) * quantile))
            top, bot = set(s.nlargest(nq).index), set(s.nsmallest(nq).index)
            tf, bf, mf = f[list(top)].mean(), f[list(bot)].mean(), f.mean()
            tl = 1.0 - len(top & prevL) / max(len(top), 1)
            lo.append(tf - tl * _RT_FRAC); ew.append(mf); ls.append((tf - bf) - tl * (_RT_FRAC + _FUT_RT_FRAC))
            lo_b.append(tf); nf.append(nser.iloc[i + horizon] / nser.iloc[i] - 1.0 if nser is not None else 0.0)
            prevL = top
        ic = np.array(ics); lo_a, ew_a, ls_a, nf_a = map(np.array, (lo, ew, ls, nf))

        def shp(x): return float(x.mean() / x.std() * np.sqrt(ppy)) if len(x) > 2 and x.std() else 0.0
        beta = float(np.cov(np.array(lo_b), nf_a)[0, 1] / np.var(nf_a)) if len(nf_a) > 2 and np.var(nf_a) else 0.0
        res[kind] = {
            'ic_ir': round(float(ic.mean() / ic.std() * np.sqrt(len(ic))), 2) if len(ic) > 2 and ic.std() else 0.0,
            'long_only_sharpe': round(shp(lo_a), 2),
            'long_minus_equalweight_per_reb': round(float(lo_a.mean() - ew_a.mean()), 5),
            'long_minus_ew_sharpe': round(shp(lo_a - ew_a), 2),
            'short_leg_contribution_per_reb': 0.0,     # filled cleanly in the 2nd pass
            'shorting_helps': None,
            'ls_net_sharpe': round(shp(ls_a), 2),
            'long_beta_to_nifty': round(beta, 2),
            'n_reb': len(lo_a),
        }
        # short-leg contribution = equal-weight − bottom-quantile forward return
        # (recompute cleanly): >0 means the names we'd short underperform (shorting helps)
        # derived from stored arrays below
    # second pass for a clean short-leg number (bottom-quantile fwd) — recompute
    for kind in res:
        bot_fwd = []
        for i in idx:
            sig = sig_at(i, kind); fwd = M.iloc[i + horizon] / M.iloc[i] - 1.0
            ok = sig.notna() & fwd.notna()
            if ok.sum() < 10:
                continue
            s, f = sig[ok], fwd[ok]
            if s.std() == 0:
                continue
            nq = max(2, int(len(s) * quantile))
            bot_fwd.append((f.mean(), f[list(set(s.nsmallest(nq).index))].mean()))
        if bot_fwd:
            mkt = np.array([m for m, _ in bot_fwd]); btm = np.array([b for _, b in bot_fwd])
            res[kind]['short_leg_contribution_per_reb'] = round(float(mkt.mean() - btm.mean()), 5)
            res[kind]['shorting_helps'] = bool(mkt.mean() - btm.mean() > 0)
    return {'ts': int(time.time() * 1000), 'days': days, 'n_years': round(days / 252.0, 2),
            'horizon': horizon, 'n_symbols': int(M.shape[1]), 'signals': res,
            'note': 'long-only judged vs EQUAL-WEIGHT (not NIFTY); short-leg contribution '
                    '= equal-weight − bottom-quantile fwd ret (>0 = shorting helps). L/S '
                    'benchmark = 0; short leg would need futures (capacity-gated).'}


def _print_longshort_directional(r: dict):
    P = print
    P('\n' + '=' * 84)
    P(f'DIRECTIONAL LONG/SHORT ACROSS OUR SIGNALS — {r["days"]}d / {r["n_years"]}y / '
      f'{r["n_symbols"]} names / H={r["horizon"]}d')
    P('=' * 84)
    P(f'  {r["note"]}')
    P(f"\n  {'signal':<14}{'IC-IR':>7}{'LO Shp':>8}{'LO-EW Shp':>11}{'short helps':>13}"
      f"{'L/S Shp':>9}{'beta':>7}")
    for k, v in r['signals'].items():
        sh = ('+' if v['shorting_helps'] else '') + f'{v["short_leg_contribution_per_reb"]:+.4f}'
        P(f"  {k:<14}{v['ic_ir']:>7.2f}{v['long_only_sharpe']:>8.2f}{v['long_minus_ew_sharpe']:>11.2f}"
          f"{sh:>13}{v['ls_net_sharpe']:>9.2f}{v['long_beta_to_nifty']:>7.2f}")
    P('\n  Read: LO-EW Sharpe ≤ 0 ⇒ no alpha vs equal-weight (raw long-only is just '
      'size/beta).\n        short helps < 0 ⇒ shorting the disliked names DRAGS (no short edge).')
    P('=' * 84 + '\n')


# ── hardened reversal book: realistic costs + impact + DSR + dynamic variants ──

_REV_HORIZONS = [5, 10, 21, 42, 63]          # reversal search space (DSR deflates for it)
_MOM_HORIZONS = [126, 189, 252, 378, 504]    # momentum FORMATION search space (skip last 21d)
_IMPACT_C = 0.5                              # square-root impact coefficient (~lit)
_BORROW_FRAC = 0.0003                        # stock-futures roll/borrow per rebalance (est, flagged)
_REVERSAL_REGIMES = ('sideways', 'high_vol', 'bear', 'strong_bear')  # a-priori: reversal favours non-(strong-)bull tape
_MOMENTUM_REGIMES = ('strong_bull', 'bull', 'sideways')              # a-priori: momentum favours trending/low-vol tape


def _xs_signal(M, i, k, kind):
    """Cross-sectional signal at rebalance i over lookback k. reversal_1m = negative
    k-day return; mom_12_1 = formation return over [i-k, i-21] (canonical skip-last-month).
    The sign convention makes nlargest = the long leg for both."""
    if kind == 'mom_12_1':
        return M.iloc[i - 21] / M.iloc[i - k] - 1.0
    return -(M.iloc[i] / M.iloc[i - k] - 1.0)


def _ls_records(M, vol20, advM, regimes, dates, idx, k, q, kind='reversal_1m'):
    """Per-rebalance long/short book for a k-lookback cross-sectional signal (reversal
    or 12-1 momentum). Returns dicts with the sets, gross spread, per-leg turnover,
    traded-name impact unit, regime."""
    recs, prev_l, prev_s = [], set(), set()
    for i in idx:
        sig = _xs_signal(M, i, k, kind)
        fwd = M.iloc[i + 21] / M.iloc[i] - 1.0      # fixed 21d hold (the book's cadence)
        ok = sig.notna() & fwd.notna()
        if ok.sum() < 10:
            continue
        s, f = sig[ok], fwd[ok]
        nq = max(2, int(len(s) * q))
        longs, shorts = set(s.nlargest(nq).index), set(s.nsmallest(nq).index)
        tl = 1.0 - len(longs & prev_l) / max(len(longs), 1)
        ts = 1.0 - len(shorts & prev_s) / max(len(shorts), 1)
        spread = float(f[list(longs)].mean() - f[list(shorts)].mean())
        # impact unit per leg: mean over names of sigma·sqrt(1/ADV) (×sqrt(capital/n) later)
        d = str(dates[i])[:10]
        def imp_unit(names):
            xs = []
            for nm in names:
                adv = advM.at[dates[i], nm] if dates[i] in advM.index else np.nan
                sg = vol20.at[dates[i], nm] if dates[i] in vol20.index else np.nan
                if adv and adv == adv and adv > 0 and sg == sg:
                    xs.append(sg / np.sqrt(adv))
            return float(np.mean(xs)) if xs else 0.0
        recs.append({'date': d, 'spread': spread, 'tl': tl, 'ts': ts,
                     'n_long': len(longs), 'n_short': len(shorts),
                     'imp_l': imp_unit(longs), 'imp_s': imp_unit(shorts),
                     'regime': regimes.get(dates[i], 'sideways')})
        prev_l, prev_s = longs, shorts
    return recs


def _net_series(recs, capital=1_000_000.0, impact=True, regime_filter=None):
    """Net periodic returns of the dollar-neutral book under a capital level (for
    impact), explicit costs (long cash CNC + short futures + borrow), optional
    sqrt-impact, and optional regime gating (flat when regime not favoured)."""
    out = []
    for r in recs:
        if regime_filter is not None and r['regime'] not in regime_filter:
            out.append(0.0)                          # stand aside, no cost
            continue
        cost = r['tl'] * _RT_FRAC + r['ts'] * (_FUT_RT_FRAC + _BORROW_FRAC)
        imp = 0.0
        if impact:
            imp = (r['tl'] * r['imp_l'] * np.sqrt(capital / max(r['n_long'], 1)) +
                   r['ts'] * r['imp_s'] * np.sqrt(capital / max(r['n_short'], 1))) * _IMPACT_C
        out.append(r['spread'] - cost - imp)
    return np.array(out)


def _sharpe(rets, ppy):
    rets = np.asarray(rets)
    return float(rets.mean() / rets.std() * np.sqrt(ppy)) if len(rets) > 2 and rets.std() else 0.0


def _dsr_single(best_rets, all_srs, n_trials):
    """Deflated Sharpe (Bailey & López de Prado) for the best of `n_trials`
    horizon searches. all_srs = per-period Sharpe of each horizon (for the
    cross-trial variance); best_rets = the winner's per-period return series."""
    r = np.asarray(best_rets)
    if len(r) < 3 or r.std() == 0:
        return 0.0
    sr = r.mean() / r.std()
    var_sr = float(np.var(all_srs, ddof=1)) if len(all_srs) > 1 else sr ** 2
    euler = 0.5772156649
    sr0 = np.sqrt(max(var_sr, 1e-12)) * ((1 - euler) * _N.inv_cdf(1 - 1.0 / n_trials) +
                                         euler * _N.inv_cdf(1 - 1.0 / (n_trials * np.e)))
    s = r.std()
    g3 = float(((r - r.mean()) ** 3).mean() / s ** 3)
    g4 = float(((r - r.mean()) ** 4).mean() / s ** 4)
    denom = np.sqrt(max(1e-12, 1 - g3 * sr + (g4 - 1) / 4 * sr ** 2))
    return round(float(_N.cdf((sr - sr0) * np.sqrt(len(r) - 1) / denom)), 4)


def validate_longshort_hardened(db=None, days: int = 2470, horizon: int = 20,
                                quantile: float = 0.2, seed: int = 7,
                                kind: str = 'reversal_1m', wide: bool = False) -> dict:
    """Step-1 hardening of a cross-sectional book (reversal OR 12-1 momentum): does
    the headline IC-IR survive realistic costs + market impact (capacity) +
    multiple-testing deflation, and do the fenced DYNAMIC variants help? `wide` merges
    the Nifty Midcap research universe (survivorship-flagged)."""
    from scipy.stats import spearmanr
    if db is None:
        from terminal_in.config import load_config
        from terminal_in.db import DB
        db = DB(load_config().sqlite_path)
    n_years = max(days / 252.0, 1e-9)
    ppy = 252 / horizon
    horizons = _MOM_HORIZONS if kind == 'mom_12_1' else _REV_HORIZONS
    fav_regimes = _MOMENTUM_REGIMES if kind == 'mom_12_1' else _REVERSAL_REGIMES

    from terminal_in.data_ingest.instruments import KNOWN_TOKENS, registry
    registry.load_stubs()
    eq_tokens = {t: s for s, t in KNOWN_TOKENS.items() if registry.sector(t) not in ('index',)}
    if wide:
        from terminal_in.data_ingest.index_membership import RESEARCH_BY_TOKEN
        eq_tokens = {**eq_tokens, **RESEARCH_BY_TOKEN}
    nifty_tok, vix_tok = KNOWN_TOKENS.get('NIFTY 50'), KNOWN_TOKENS.get('INDIA VIX')
    all_1d = db.get_ohlcv_1d_all(list(eq_tokens) + [t for t in (nifty_tok, vix_tok) if t], limit=days + 320)
    regimes = engine._regime_series(all_1d.get(nifty_tok), all_1d.get(vix_tok))

    closes, dollarvol = {}, {}
    for t, s in eq_tokens.items():
        df = all_1d.get(t)
        if df is None or len(df) < 300:
            continue
        closes[s] = df['close']
        dollarvol[s] = (df['close'] * df['volume']) if 'volume' in df else df['close'] * 0.0
    dates = sorted(set().union(*[set(c.index) for c in closes.values()]))[-days:]
    M = pd.DataFrame({s: closes[s].reindex(dates) for s in closes}).astype(float)
    DV = pd.DataFrame({s: dollarvol[s].reindex(dates) for s in dollarvol}).astype(float)
    advM = DV.rolling(20, min_periods=5).mean()
    vol20 = np.log(M).diff().rolling(20, min_periods=5).std()
    warmup = max(252, max(horizons) + 1)
    idx = list(range(warmup, len(M) - horizon, horizon))

    # per-horizon books + IC (for DSR cross-trial variance + the dynamic pick)
    per_h, srs = {}, []
    for k in horizons:
        recs = _ls_records(M, vol20, advM, regimes, dates, idx, k, quantile, kind)
        base = _net_series(recs, impact=False)            # explicit-cost only (per-period SR)
        ic = []
        for i in idx:
            sig = _xs_signal(M, i, k, kind); fwd = M.iloc[i + horizon] / M.iloc[i] - 1.0
            ok = sig.notna() & fwd.notna()
            if ok.sum() >= 10:
                c = spearmanr(sig[ok], fwd[ok]).correlation
                if c == c:
                    ic.append((str(dates[i])[:10], float(c)))
        per_h[k] = {'recs': recs, 'net': base, 'ic': ic,
                    'sr': (base.mean() / base.std()) if base.std() else 0.0,
                    'ic_ir': round(float(np.mean([v for _, v in ic]) / np.std([v for _, v in ic]) * np.sqrt(len(ic))), 3) if len(ic) > 2 else 0.0}
        srs.append(per_h[k]['sr'])

    best_k = max(horizons, key=lambda k: per_h[k]['ic_ir'])
    best = per_h[best_k]

    # capacity curve: net Sharpe vs assumed AUM (sqrt impact)
    capacity = {}
    for cap in (1e6, 1e7, 1e8, 1e9):
        nets = _net_series(best['recs'], capital=cap, impact=True)
        capacity[f'{cap:.0e}'] = {'net_sharpe': round(_sharpe(nets, ppy), 3),
                                  'total_return_pct': round((np.prod(1 + nets) - 1) * 100, 1)}

    # deflated Sharpe for the best horizon (deflated for the horizon search)
    dsr = _dsr_single(best['net'], srs, n_trials=len(horizons))

    # DYNAMIC 1 — walk-forward horizon selection (pick best IC-IR over prior years)
    rebal_dates = [str(dates[i])[:10] for i in idx]
    dyn = []
    for j, d in enumerate(rebal_dates):
        yr = d[:4]
        # train = horizons' IC over rebalances strictly before this year
        best_train, best_ir = best_k, -1e9
        for k in horizons:
            past = [v for dd, v in per_h[k]['ic'] if dd[:4] < yr]
            if len(past) > 3:
                ir = np.mean(past) / (np.std(past) + 1e-9) * np.sqrt(len(past))
                if ir > best_ir:
                    best_ir, best_train = ir, k
        dyn.append(per_h[best_train]['net'][j] if j < len(per_h[best_train]['net']) else 0.0)
    dyn = np.array(dyn[:len(best['net'])])

    # DYNAMIC 2 — regime-conditioned (a-priori favoured tape for this factor)
    regime_nets = _net_series(best['recs'], impact=False, regime_filter=fav_regimes)
    traded = float(np.mean([1.0 if r['regime'] in fav_regimes else 0.0 for r in best['recs']]))

    return {'ts': int(time.time() * 1000), 'days': days, 'n_years': round(n_years, 2),
            'kind': kind, 'universe': 'wide_large72+midcap150' if wide else 'large72',
            'survivorship_warning': ('WIDE universe is a CURRENT SNAPSHOT (today\'s '
                                     'survivors back to 2016) — UPWARD-BIASED, esp. for '
                                     'momentum, until dated reconstitution lands.') if wide else None,
            'n_symbols': int(M.shape[1]), 'horizon': horizon, 'best_horizon': best_k,
            'per_horizon_ic_ir': {k: per_h[k]['ic_ir'] for k in horizons},
            'costs': {'long_cnc_rt': round(_RT_FRAC, 5), 'short_fut_rt': _FUT_RT_FRAC,
                      'borrow_per_reb': _BORROW_FRAC, 'impact_c': _IMPACT_C},
            'base_net_sharpe_at_1M': round(_sharpe(_net_series(best['recs'], 1e6, impact=True), ppy), 3),
            'capacity_curve': capacity,
            'deflated_sharpe': dsr, 'dsr_survives': bool(dsr > 0.95),
            'dynamic_walkforward': {'net_sharpe': round(_sharpe(dyn, ppy), 3),
                                    'total_return_pct': round((np.prod(1 + dyn) - 1) * 100, 1)},
            'regime_conditioned': {'net_sharpe': round(_sharpe(regime_nets, ppy), 3),
                                   'total_return_pct': round((np.prod(1 + regime_nets) - 1) * 100, 1),
                                   'fraction_in_market': round(traded, 2)},
            'note': 'Long cash CNC + short single-stock futures (+borrow). Impact = '
                    '0.5·σ·√(notional/ADV). Benchmark = 0. DSR deflates for the horizon search.'}


def _print_longshort_hardened(r: dict):
    P = print
    P('\n' + '=' * 78)
    label = {'mom_12_1': '12-1 MOMENTUM', 'reversal_1m': 'REVERSAL'}.get(r.get('kind', 'reversal_1m'), r.get('kind'))
    P(f'{label} BOOK — HARDENED ({r["days"]}d / {r["n_years"]}y / {r["n_symbols"]} names, '
      f'{r.get("universe", "large72")}, best horizon {r["best_horizon"]}d)')
    P('=' * 78)
    if r.get('survivorship_warning'):
        P(f'  ⚠ {r["survivorship_warning"]}')
    P(f'  costs: long {r["costs"]["long_cnc_rt"]*100:.3f}%/rt · short {r["costs"]["short_fut_rt"]*100:.3f}%'
      f'+borrow {r["costs"]["borrow_per_reb"]*100:.3f}%/reb · impact c={r["costs"]["impact_c"]}')
    P(f'  per-horizon IC-IR: ' + '  '.join(f'{k}d:{v:+.2f}' for k, v in r['per_horizon_ic_ir'].items()))
    P(f'\n  CAPACITY (net Sharpe vs assumed AUM, sqrt-impact):')
    for cap, v in r['capacity_curve'].items():
        P(f'    {cap:>7}  net Sharpe {v["net_sharpe"]:+.2f}   total {v["total_return_pct"]:+.1f}%')
    P(f'\n  DEFLATED SHARPE (best-of-{len(r["per_horizon_ic_ir"])} horizons): {r["deflated_sharpe"]:.3f}  '
      f'→ {"SURVIVES" if r["dsr_survives"] else "DIES (best-of-search not significant)"}')
    d, rg = r['dynamic_walkforward'], r['regime_conditioned']
    P(f'  DYNAMIC walk-forward horizon pick: net Sharpe {d["net_sharpe"]:+.2f}  total {d["total_return_pct"]:+.1f}%')
    P(f'  REGIME-conditioned ({rg["fraction_in_market"]*100:.0f}% in-market): '
      f'net Sharpe {rg["net_sharpe"]:+.2f}  total {rg["total_return_pct"]:+.1f}%')
    P('=' * 78 + '\n')


def _print_longshort(r: dict):
    P = print
    P('\n' + '=' * 78)
    P(f'CROSS-SECTIONAL MARKET-NEUTRAL TEST (A1 IC + A2 long/short) — '
      f'{r["days"]}d / {r["n_years"]}y / {r["n_symbols"]} names / H={r["horizon"]}d')
    P('=' * 78)
    P(f'  India: {r["india_note"]}')
    P(f'  long-leg cost {r["long_leg_cost_frac"]*100:.3f}%/rt (cash CNC) · '
      f'short-leg {r["short_leg_cost_frac_estimate"]*100:.3f}%/rt (futures, ESTIMATE)')
    for kind, v in r['signals'].items():
        P(f'\n  {kind.upper()}')
        P(f'    A1  mean IC {v["mean_ic"]:+.4f}  IC-IR {v["ic_ir"]:+.2f}  '
          f'({v["n_rebalances"]} rebalances)  — IC≈0 ⇒ no cross-sectional skill')
        P(f'    A2  L/S net Sharpe {v["ls_net_sharpe"]:+.2f}  total {v["ls_total_return_pct"]:+.1f}%  '
          f'maxDD {v["ls_max_dd_pct"]:+.1f}%  turnover {v["avg_turnover"]*100:.0f}%/reb  '
          f'(benchmark = 0)')
        P(f'    IC by year: ' + '  '.join(f'{y}:{ic:+.3f}' for y, ic in v['ic_by_year'].items()))
    P('=' * 78 + '\n')


def _print_event_ablation(r: dict):
    P = print
    P('\n' + '=' * 78)
    P(f'EVENT-PLANE ABLATION (PEAD) — {r["days"]}d / {r["n_years"]}y / '
      f'{r["dataset_rows"]} candidates / horizon {r["horizon"]}d')
    P('=' * 78)
    e = r['events']
    P(f'\nEVENT ARCHIVE: {e["archive_rows"]} announcements, {e["symbols_with_events"]} symbols, '
      f'PIT consensus {e["pit_consensus_pct"]}% (→ earnings_surprise NULL, by design)')
    P(f'  by type: {e["by_type"]}')
    bh = r['buy_hold_nifty_sharpe']
    t, v = r['technical_only'], r['technical_plus_event']
    P('\nABLATION (OOS, same per-fold walk-forward fences):')
    P(f'  TECHNICAL ONLY   net_sharpe {t["net_sharpe"]:+.2f}  ret {t["return_pct"]:+.1f}%  '
      f'sortino {t["sortino"]:+.2f}  n={t["n"]}')
    P(f'  TECH + EVENT     net_sharpe {v["net_sharpe"]:+.2f}  ret {v["return_pct"]:+.1f}%  '
      f'sortino {v["sortino"]:+.2f}  n={v["n"]}')
    P(f'  buy-hold NIFTY   net_sharpe {bh:+.2f}' if bh is not None else '  buy-hold NIFTY n/a')
    P(f'  Δ trade-Sharpe (event - tech) = {r["delta_trade_sharpe"]:+.4f}  '
      f'noise band ±{r["noise_band_2se"]:.4f}  → '
      f'{"REAL LIFT" if r["event_adds_oos_lift"] else "WITHIN NOISE"}')
    fi = r['event_feature_importance']
    P('  event-feature importance: ' + (', '.join(f'{k}={x}' for k, x in fi.items()) if fi else 'none'))
    rd = r['reaction_drift_calibration']
    P(f'  PEAD check (in-drift-window n={rd["rows_in_drift_window"]}): '
      f'corr(reaction, fwd-ret)={rd["corr_reaction_gap_vs_forward_ret"]}  | '
      f'fwd-ret after +reaction {rd["mean_fwd_ret_pos_reaction"]:+.4f} vs '
      f'-reaction {rd["mean_fwd_ret_neg_reaction"]:+.4f}')
    P(f'  deflated-Sharpe survivors (event judge): {r["deflated_sharpe_event"]["survivors"] or "NONE"}')
    P(f'  worst per-regime regression {r["regime_regression"]["worst_regression_pp"]:+.2f}pp')
    P(f'\n  VERDICT: event features add OOS lift = {r["event_adds_oos_lift"]}  → '
      f'{"KEEP" if r["event_adds_oos_lift"] else "DROP (report the null, no narrative)"}')
    P('=' * 78 + '\n')


def _print_m6(r: dict):
    P = print
    P('\n' + '=' * 78)
    P(f'MODULE 6 VALIDATION — Phase C + D₀ — {r["days"]}d / {r["n_years"]}y / '
      f'{r["dataset_rows"]} candidate rows / horizon {r["horizon"]}d')
    P('=' * 78)
    bh = r['buy_hold_nifty_sharpe']

    c = r['phase_c']
    P(f'\nPHASE C — competence (threshold {c["threshold"]}, mode={c["mode"]})')
    P(f'  FLAT        net_sharpe {c["flat"]["net_sharpe"]:+.2f}  ret {c["flat"]["return_pct"]:+.1f}%  '
      f'sortino {c["flat"]["sortino"]:+.2f}  calmar {c["flat"]["calmar"]:+.2f}  n={c["flat"]["n"]}')
    P(f'  COMPETENCE  net_sharpe {c["competence"]["net_sharpe"]:+.2f}  ret {c["competence"]["return_pct"]:+.1f}%  '
      f'sortino {c["competence"]["sortino"]:+.2f}  calmar {c["competence"]["calmar"]:+.2f}  n={c["competence"]["n"]}')
    a = c['abstention']
    P(f'  abstain rate (of fired) {a["abstain_rate_of_fired"]*100:.0f}%  | mean net-ret  '
      f'all-fired {a["all_fired"]["mean_ret"]:+.4f}  kept {a["kept"]["mean_ret"]:+.4f}  '
      f'ABSTAINED {a["abstained"]["mean_ret"]:+.4f}')
    P(f'  GATE: beats-flat-Sharpe={c["beats_flat_sharpe"]}  '
      f'abstention-removes-net-negative={c["abstention_value_additive"]}')

    d = r['phase_d0']
    P(f'\nPHASE D₀ — GBT forward-EV head (OOS, {d["fallback_candidate_frac"]*100:.0f}% heuristic-fallback candidates)')
    P('  per-fold fences (train cutoff must precede test span):')
    for f in d['folds']:
        P(f'    {f["fold"]}  train<{f["train_cutoff"]}  n_train={f["n_train"]:<6} '
          f'trained={f["trained"]}  test {f["test_span"]}  leak_ok={f["cutoff_ok"]}')
    P(f'  HEURISTIC   net_sharpe {d["heuristic"]["net_sharpe"]:+.2f}  ret {d["heuristic"]["return_pct"]:+.1f}%  '
      f'sortino {d["heuristic"]["sortino"]:+.2f}  calmar {d["heuristic"]["calmar"]:+.2f}')
    P(f'  GBT-EV      net_sharpe {d["gbt"]["net_sharpe"]:+.2f}  ret {d["gbt"]["return_pct"]:+.1f}%  '
      f'sortino {d["gbt"]["sortino"]:+.2f}  calmar {d["gbt"]["calmar"]:+.2f}  n={d["gbt"]["n"]}')
    P(f'  buy-hold NIFTY net_sharpe {bh:+.2f}' if bh is not None else '  buy-hold NIFTY n/a')
    fi = d['feature_importance']
    P('  feature importance (top): ' + ', '.join(f'{k}={v}' for k, v in list(fi.items())[:6]))
    if d['relearned_heuristic']:
        P('    ** ev/conf dominate — head largely RELEARNED the heuristic; little added **')
    if d['echo_guard']:
        e = d['echo_guard']
        P(f"  echo guard (fold {e['fold']}): corr(all,fired)={e['pred_corr_all_vs_fired']} "
          f"|Δ|={e['mean_abs_diff']}  {'DIVERGES (selection bias)' if e['diverges'] else 'consistent'}")
    if d['calibration']:
        P('  calibration (pred->realized): ' +
          '  '.join(f'{b["pred"]}->{b["realized"]}(n{b["n"]})' for b in d['calibration']))
    rr = d['regime_regression']
    P(f'  worst per-regime regression {rr["worst_regression_pp"]:+.2f}pp (<=5pt: {rr["passes_5pt"]})')
    P(f'  deflated-Sharpe survivors: {d["dsr_survivors"] or "NONE"}')
    P(f'  GATES: (a) beats heuristic + no>5pt regress = {d["gate_a_beats_heuristic"]}  | '
      f'(b) beats buy-hold = {d["gate_b_beats_buyhold"]}  | (c) survives DSR = {d["gate_c_survives_dsr"]}')
    P('=' * 78 + '\n')


if __name__ == '__main__':
    import sys
    try:                                  # Windows console is cp1252; force UTF-8
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    ap = argparse.ArgumentParser(description='Alpha-validation harness for the backtest.')
    ap.add_argument('--days', type=int, default=2470)
    ap.add_argument('--llm', action='store_true', help='also run the LLM judge isolation (slow)')
    ap.add_argument('--max-llm-calls', type=int, default=150)
    ap.add_argument('--null-runs', type=int, default=1000)
    ap.add_argument('--boot', type=int, default=2000)
    ap.add_argument('--trials', type=int, default=8, help='strategies tried (DSR deflation)')
    ap.add_argument('--m6', action='store_true', help='run the Module 6 (Phase C + D₀) validation')
    ap.add_argument('--events', action='store_true', help='run the event-plane (PEAD) ablation')
    ap.add_argument('--longshort', action='store_true', help='run the cross-sectional market-neutral test (A1 IC + A2 L/S)')
    ap.add_argument('--hard', action='store_true', help='with --longshort: hardened costs + impact/capacity + DSR + dynamic variants')
    ap.add_argument('--wide', action='store_true', help='with --longshort: include the Nifty Midcap 150 research universe (survivorship-flagged)')
    ap.add_argument('--mom', action='store_true', help='with --longshort --hard: harden the 12-1 MOMENTUM book instead of reversal')
    ap.add_argument('--longshort-directional', action='store_true', help='directional L/S across our signals (incl. lens score) vs equal-weight + beta')
    ap.add_argument('--horizon', type=int, default=20, help='m6 label horizon (trading days)')
    ap.add_argument('--competence-mode', choices=['veto', 'weight'], default='veto')
    ap.add_argument('--json', action='store_true', help='dump full JSON instead of the report')
    args = ap.parse_args()
    if args.longshort_directional:
        r = validate_longshort_directional(days=args.days, horizon=args.horizon, wide=args.wide)
        print(json.dumps(r, indent=1, default=str)) if args.json else _print_longshort_directional(r)
    elif args.longshort and args.hard:
        r = validate_longshort_hardened(days=args.days, horizon=args.horizon,
                                        kind='mom_12_1' if args.mom else 'reversal_1m',
                                        wide=args.wide)
        print(json.dumps(r, indent=1, default=str)) if args.json else _print_longshort_hardened(r)
    elif args.longshort:
        r = validate_longshort(days=args.days, horizon=args.horizon, wide=args.wide)
        print(json.dumps(r, indent=1, default=str)) if args.json else _print_longshort(r)
    elif args.events:
        r = validate_event_ablation(days=args.days, horizon=args.horizon, n_trials=args.trials)
        print(json.dumps(r, indent=1, default=str)) if args.json else _print_event_ablation(r)
    elif args.m6:
        r = validate_m6(days=args.days, horizon=args.horizon, n_trials=args.trials,
                        competence_mode=args.competence_mode)
        print(json.dumps(r, indent=1, default=str)) if args.json else _print_m6(r)
    else:
        r = validate(days=args.days, run_llm=args.llm, max_llm_calls=args.max_llm_calls,
                     null_runs=args.null_runs, n_boot=args.boot, n_trials=args.trials)
        print(json.dumps(r, indent=1, default=str)) if args.json else _print(r)
