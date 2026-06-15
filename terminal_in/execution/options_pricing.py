"""
Black-Scholes options pricing + greeks — pure stdlib (no scipy/new deps).

WHY THIS EXISTS / DATA HONESTY: NSE option premiums, OI and IV are only available
from a live Kite feed. In paper mode we have no live options tape, so we price
each contract THEORETICALLY from REAL inputs — the live underlying spot and India
VIX (which *is* the 30-day implied vol of NIFTY options) as the IV proxy. These
are clearly labeled `theoretical=True` everywhere and are NEVER written to ohlcv_*
tables, never presented as traded prices, and never fed to the lenses as bars.
This is exactly how an option desk values an illiquid strike, and it mirrors the
already-shipped FUT_MARGIN_BAND estimate discipline (labeled model, not a quote).
In live mode, real Kite LTP/OI/IV replace these theoretical values.

Inputs: spot & strike in index points; t_years = year-fraction to expiry;
iv as a DECIMAL (0.14 = 14%); r = risk-free decimal. India VIX is quoted in
percent, so callers pass vix/100.
"""

import math

RISK_FREE = 0.065   # ~India repo/T-bill; a labeled assumption, not a market quote


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _d1_d2(spot: float, strike: float, t: float, iv: float, r: float):
    vol_t = iv * math.sqrt(t)
    d1 = (math.log(spot / strike) + (r + 0.5 * iv * iv) * t) / vol_t
    return d1, d1 - vol_t


def bs_price(spot: float, strike: float, t_years: float, iv: float,
             opt_type: str, r: float = RISK_FREE) -> float:
    """Theoretical premium. opt_type ∈ {'CE','PE','FUT'}. Degenerate inputs
    (expiry, zero vol) fall back to intrinsic value / forward."""
    opt_type = opt_type.upper()
    if opt_type == 'FUT':
        # Index futures fair value = spot · e^{rT} (cost-of-carry, no dividend term)
        return spot * math.exp(r * max(t_years, 0.0))
    if t_years <= 0 or iv <= 0 or spot <= 0 or strike <= 0:
        if opt_type == 'CE':
            return max(0.0, spot - strike)
        return max(0.0, strike - spot)
    d1, d2 = _d1_d2(spot, strike, t_years, iv, r)
    disc = math.exp(-r * t_years)
    if opt_type == 'CE':
        return spot * _norm_cdf(d1) - strike * disc * _norm_cdf(d2)
    return strike * disc * _norm_cdf(-d2) - spot * _norm_cdf(-d1)


def bs_greeks(spot: float, strike: float, t_years: float, iv: float,
              opt_type: str, r: float = RISK_FREE) -> dict:
    """delta, gamma, theta (per CALENDAR day), vega (per 1 vol point = 1%)."""
    opt_type = opt_type.upper()
    if opt_type == 'FUT':
        return {'delta': 1.0, 'gamma': 0.0, 'theta': 0.0, 'vega': 0.0}
    if t_years <= 0 or iv <= 0 or spot <= 0 or strike <= 0:
        intrinsic_delta = (1.0 if (opt_type == 'CE' and spot > strike)
                           else -1.0 if (opt_type == 'PE' and spot < strike) else 0.0)
        return {'delta': intrinsic_delta, 'gamma': 0.0, 'theta': 0.0, 'vega': 0.0}
    d1, d2 = _d1_d2(spot, strike, t_years, iv, r)
    disc = math.exp(-r * t_years)
    pdf = _norm_pdf(d1)
    sqrt_t = math.sqrt(t_years)

    gamma = pdf / (spot * iv * sqrt_t)
    vega = spot * pdf * sqrt_t / 100.0           # per 1% vol
    if opt_type == 'CE':
        delta = _norm_cdf(d1)
        theta = (-(spot * pdf * iv) / (2 * sqrt_t)
                 - r * strike * disc * _norm_cdf(d2)) / 365.0
    else:
        delta = _norm_cdf(d1) - 1.0
        theta = (-(spot * pdf * iv) / (2 * sqrt_t)
                 + r * strike * disc * _norm_cdf(-d2)) / 365.0
    return {'delta': delta, 'gamma': gamma, 'theta': theta, 'vega': vega}


def implied_vol(price: float, spot: float, strike: float, t_years: float,
                opt_type: str, r: float = RISK_FREE) -> float | None:
    """Back out the implied vol (decimal) from a REAL traded premium via bisection.
    Used in live mode to turn a Kite LTP into a real IV — a derived-from-real
    quantity, not a fabricated one. Returns None when the price is below intrinsic
    or outside a solvable range (so callers surface 'n/a' rather than guess)."""
    opt_type = opt_type.upper()
    if opt_type == 'FUT' or price is None or price <= 0 or t_years <= 0 or spot <= 0 or strike <= 0:
        return None
    intrinsic = max(0.0, spot - strike) if opt_type == 'CE' else max(0.0, strike - spot)
    if price < intrinsic - 1e-6:
        return None                       # arbitrage / stale quote — don't invent an IV
    lo, hi = 1e-4, 5.0                     # 0.01% .. 500% vol bracket
    if bs_price(spot, strike, t_years, hi, opt_type, r) < price:
        return None                        # price implies vol beyond the bracket
    for _ in range(60):                    # bisection → ~1e-15 convergence
        mid = 0.5 * (lo + hi)
        if bs_price(spot, strike, t_years, mid, opt_type, r) < price:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def price_and_greeks(spot: float, strike: float, t_years: float, iv: float,
                     opt_type: str, r: float = RISK_FREE) -> dict:
    """Convenience: premium + greeks in one dict, rounded for transport."""
    px = bs_price(spot, strike, t_years, iv, opt_type, r)
    g = bs_greeks(spot, strike, t_years, iv, opt_type, r)
    return {
        'premium': round(px, 2),
        'delta': round(g['delta'], 4),
        'gamma': round(g['gamma'], 6),
        'theta': round(g['theta'], 3),
        'vega': round(g['vega'], 3),
        'theoretical': True,
    }
