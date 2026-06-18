"""
F&O backtest — the eval gate for the derivatives strategies (Stage 6).

HEADLINE: the variance-risk-premium harvester (monthly NIFTY short iron condor),
replayed over 10y of REAL NIFTY + India-VIX daily bars. This is the one F&O idea
with a documented structural edge prior, so it's the one worth a proper eval.

DATA HONESTY (read before trusting a number): there is NO free historical option
tape, so every premium here is BLACK-SCHOLES THEORETICAL from the REAL underlying
close + the REAL India VIX (the 30d ATM IV) as the IV anchor, with the same skew
surface the live chain uses. That means: no real bid/ask, no real smile/term
dynamics, no liquidity/early-assignment effects. Theoretical option backtests
SYSTEMATICALLY FLATTER short-premium strategies (they can't see the fat tails and
slippage that bite sellers). Treat the result as an UPPER bound / sanity check, not
a tradeable Sharpe. No synthetic underlying data — only the real close + VIX.

No lookahead: strikes/credit are set from the entry-day close+VIX; the structure is
then held to expiry and realised at the actual expiry-day close. Costs are a
realistic NSE-options estimate (labeled), charged at entry and exit.
"""

import logging
from datetime import date, timedelta

import numpy as np

from terminal_in.data_ingest.instruments import KNOWN_TOKENS
from terminal_in.data_ingest import fno_instruments as fno
from terminal_in.execution.options_pricing import bs_price
from terminal_in.execution.vol_surface import skew_iv

log = logging.getLogger(__name__)

NIFTY_LOT = 75
SLIPPAGE_PCT = 0.0010        # 0.10% on premium, against the taker (same as live broker)

# Realistic NSE-options cost estimate (as-of 2026, verify) — premium-turnover based.
BROKERAGE_LEG = 20.0         # Zerodha flat per leg
STT_OPT_SELL  = 0.000625     # 0.0625% on SELL premium (options STT, sell side)
EXCH_TXN_OPT  = 0.00035      # ~0.035% NSE options premium turnover
SEBI_PCT      = 0.000001
STAMP_OPT_BUY = 0.00003      # 0.003% buy side
GST_PCT       = 0.18


def _last_thursday(y: int, m: int) -> date:
    d = date(y, m, 28)
    while d.month == m:
        d += timedelta(days=1)
    d -= timedelta(days=1)                      # last day of month
    while d.weekday() != 3:                     # back up to Thursday (wd 3)
        d -= timedelta(days=1)
    return d


def _monthly_expiries(start: date, end: date) -> list[date]:
    out, y, m = [], start.year, start.month
    while date(y, m, 1) <= end:
        e = _last_thursday(y, m)
        if start <= e <= end:
            out.append(e)
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out


def _leg_cost(premium_value: float, side: str) -> float:
    """One option leg's statutory + brokerage cost on its premium turnover."""
    stt   = STT_OPT_SELL * premium_value if side == 'SELL' else 0.0
    stamp = STAMP_OPT_BUY * premium_value if side == 'BUY' else 0.0
    exch  = EXCH_TXN_OPT * premium_value
    sebi  = SEBI_PCT * premium_value
    gst   = GST_PCT * (BROKERAGE_LEG + exch)
    return BROKERAGE_LEG + stt + stamp + exch + sebi + gst


def run_fno_backtest(db, strategy: str = 'iron_condor', years: int = 10,
                     short_sd: float = 1.0, wing: int = 4, risk_frac: float = 0.05,
                     capital: float = 1_000_000.0) -> dict:
    """Replay a monthly NIFTY short iron condor over real NIFTY+VIX history.

    Short strikes are placed at the VIX-implied expected move (short_sd × σ√T, the
    principled ~1-SD placement — NOT a fixed step count, which would sit absurdly
    close to ATM and lose every month). wing = spread width in steps beyond the
    shorts. risk_frac sizes lots so defined max loss ≈ risk_frac × equity (compounds).
    See the module docstring for the theoretical-pricing caveat."""
    if strategy != 'iron_condor':
        raise ValueError("only 'iron_condor' is implemented")

    nifty = db.get_ohlcv_1d(KNOWN_TOKENS['NIFTY 50'], limit=10000)
    vix   = db.get_ohlcv_1d(KNOWN_TOKENS['INDIA VIX'], limit=10000)
    if nifty is None or vix is None or len(nifty) < 250:
        raise RuntimeError('fno backtest: need NIFTY + India VIX daily history')

    nclose = nifty['close']
    vclose = vix['close']
    n_dates = list(nclose.index)
    start = (n_dates[-1].date() - timedelta(days=int(years * 365.25)))
    start = max(start, n_dates[0].date())
    expiries = _monthly_expiries(start, n_dates[-1].date())
    if len(expiries) < 6:
        raise RuntimeError('fno backtest: not enough monthly expiries in range')

    step = fno.strike_interval('NIFTY', float(nclose.iloc[-1]))
    equity = capital
    trades, curve = [], []

    def _close_on_or_before(d: date):
        sub = nclose[nclose.index.date <= d]
        return (float(sub.iloc[-1]), sub.index[-1]) if len(sub) else (None, None)

    for i in range(1, len(expiries)):
        entry_target = expiries[i - 1] + timedelta(days=1)   # ~1 month to expiry
        exp = expiries[i]
        # entry = first trading day on/after the previous expiry
        ent = nclose[(nclose.index.date >= entry_target) & (nclose.index.date < exp)]
        if len(ent) == 0:
            continue
        t0 = ent.index[0]
        spot = float(nclose.loc[t0])
        iv = float(vclose.loc[t0]) / 100.0 if t0 in vclose.index else None
        if not spot or not iv or iv <= 0:
            continue
        T = max((exp - t0.date()).days, 1) / 365.0
        atm = round(spot / step) * step

        # shorts at the VIX-implied expected move (~1 SD); wings `wing` steps beyond
        em = spot * iv * (T ** 0.5)                          # 1-SD move to expiry
        short_dist = max(step, round(short_sd * em / step) * step)
        wing_dist = wing * step
        sc, sp = atm + short_dist, atm - short_dist          # short call / put strikes
        legs = [
            (sc,             'CE', 'SELL'),
            (sc + wing_dist, 'CE', 'BUY'),
            (sp,             'PE', 'SELL'),
            (sp - wing_dist, 'PE', 'BUY'),
        ]
        credit_per_unit = 0.0
        entry_cost_unit = 0.0
        for strike, opt, side in legs:
            iv_k = skew_iv(iv, spot, strike, T)
            prem = bs_price(spot, strike, T, iv_k, opt)
            fill = max(prem * (1 + SLIPPAGE_PCT * (1 if side == 'BUY' else -1)), 0.0)
            credit_per_unit += fill if side == 'SELL' else -fill
            entry_cost_unit += _leg_cost(fill, side)
        if credit_per_unit <= 0:
            continue                                   # no premium to harvest

        # size to defined max loss ≈ risk_frac × equity
        max_loss_unit = max(wing_dist - credit_per_unit, step * 0.1)
        lots = max(1, int((equity * risk_frac) / (max_loss_unit * NIFTY_LOT)))
        lots = min(lots, 200)
        qty = lots * NIFTY_LOT

        # realise at expiry close (the actual outcome — not lookahead)
        sx, _ = _close_on_or_before(exp)
        if sx is None:
            continue
        call_loss = max(0.0, min(sx - sc, wing_dist))
        put_loss  = max(0.0, min(sp - sx, wing_dist))
        payoff_unit = call_loss + put_loss             # what the short condor owes
        # exit costs: settle the structure (per-unit, side-symmetric estimate)
        exit_cost_unit = sum(_leg_cost(max(payoff_unit, 1.0), s) for _, _, s in legs) / 4 * 2

        pnl_unit = credit_per_unit - payoff_unit
        gross = pnl_unit * qty
        cost = (entry_cost_unit + exit_cost_unit) * lots
        net = gross - cost
        equity += net
        trades.append({
            'entry_date': str(t0.date()), 'expiry': str(exp), 'spot_entry': round(spot, 1),
            'spot_expiry': round(sx, 1), 'vix': round(iv * 100, 2), 'lots': lots,
            'credit': round(credit_per_unit, 2), 'payoff': round(payoff_unit, 2),
            'gross': round(gross, 0), 'cost': round(cost, 0), 'net': round(net, 0),
            'equity': round(equity, 0), 'win': net > 0,
        })
        curve.append((str(exp), round(equity, 0)))

    return _report(strategy, trades, curve, capital, years)


def _report(strategy, trades, curve, capital, years) -> dict:
    if not trades:
        return {'strategy': strategy, 'trades': 0, 'note': 'no trades generated'}
    nets = np.array([t['net'] for t in trades], float)
    eq = np.array([capital] + [t['equity'] for t in trades], float)
    rets = np.diff(eq) / eq[:-1]
    n = len(trades)
    wins = sum(1 for t in trades if t['win'])
    total_ret = eq[-1] / capital - 1.0
    yrs = max((np.datetime64(trades[-1]['expiry']) - np.datetime64(trades[0]['entry_date']))
              / np.timedelta64(365, 'D'), 1e-9)
    cagr = (eq[-1] / capital) ** (1.0 / yrs) - 1.0
    peak = np.maximum.accumulate(eq)
    max_dd = float((eq / peak - 1.0).min())
    sharpe = float(rets.mean() / rets.std() * np.sqrt(12)) if rets.std() > 1e-12 else 0.0
    by_year: dict = {}
    for t in trades:
        by_year.setdefault(t['expiry'][:4], []).append(t['net'])
    return {
        'strategy': strategy, 'trades': n, 'win_rate': round(wins / n, 3),
        'final_equity': round(float(eq[-1])), 'total_return_pct': round(total_ret * 100, 1),
        'cagr_pct': round(cagr * 100, 2), 'max_drawdown_pct': round(max_dd * 100, 1),
        'sharpe_monthly_ann': round(sharpe, 2),
        'avg_net_per_trade': round(float(nets.mean())), 'avg_credit': round(float(np.mean([t['credit'] for t in trades])), 1),
        'total_cost': round(float(np.sum([t['cost'] for t in trades]))),
        'per_year': {y: {'n': len(v), 'net': round(float(np.sum(v)))} for y, v in sorted(by_year.items())},
        'equity_curve': curve, 'recent_trades': trades[-24:],
        'theoretical': True,
        'caveat': 'Theoretical BS premiums (real spot+VIX); flatters short-premium. Upper bound, not a tradeable Sharpe.',
    }


if __name__ == '__main__':
    import json
    import sys
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    from terminal_in.config import load_config
    from terminal_in.db import DB
    r = run_fno_backtest(DB(load_config().sqlite_path))
    print(json.dumps({k: v for k, v in r.items() if k not in ('equity_curve', 'recent_trades')}, indent=1))
