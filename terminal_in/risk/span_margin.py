"""
SPAN-approximation margin for index F&O (PRD P2, Stage 4).

Real SPAN (Standard Portfolio Analysis of Risk) computes initial margin as the
worst-case loss of a position across a GRID of price and volatility shift
scenarios, plus an exposure add-on. NSE publishes the exact daily SPAN parameter
files; we don't ingest those in paper mode, so this is a faithful *approximation*
built from the same idea using our Black-Scholes pricer and an India-VIX-derived
scan range. It is clearly labeled an estimate (like FUT_MARGIN_BAND) and is the
per-segment margin model the F&O broker/gate uses, replacing the cash 30%-notional
rule which is meaningless for derivatives.

Method:
- Long option: margin = the premium paid. The premium IS the max loss — no SPAN.
- Short option / future: scan the underlying ±scan_range across 7 price steps and
  ±a relative vol shift (2 vol scenarios), reprice with Black-Scholes, take the
  WORST loss for the position over the grid (SPAN's "scanning risk"), then add an
  exposure margin (% of notional). That's the initial margin.

scan_range is a ~2-day, ~3.5σ move implied by India VIX, floored/capped so the
numbers stay in a realistic broker band. All labeled `approx=True`.
"""

import math

from terminal_in.execution.options_pricing import bs_price

# SPAN-style scenario parameters (approximation — not NSE's exact daily file).
PRICE_SCAN_SIGMAS = 3.5          # adverse move size in stdevs
SCAN_HORIZON_DAYS = 2            # margin period of risk
VOL_SCAN_REL      = 0.25         # ± relative vol shift SPAN scans
PRICE_STEPS       = (-1.0, -2 / 3, -1 / 3, 0.0, 1 / 3, 2 / 3, 1.0)
SCAN_FLOOR_PCT    = 0.05         # floor on price-scan range (% of spot)
SCAN_CAP_PCT      = 0.15         # cap on price-scan range
EXPOSURE_PCT      = 0.02         # exposure add-on (% of notional)


def scan_range(spot: float, iv: float) -> float:
    """Adverse price move (index points) = N·σ over the margin horizon, from
    the VIX-implied vol, floored/capped to a realistic band."""
    sigma_1d = iv / math.sqrt(252.0)
    move_pct = sigma_1d * math.sqrt(SCAN_HORIZON_DAYS) * PRICE_SCAN_SIGMAS
    move_pct = max(SCAN_FLOOR_PCT, min(move_pct, SCAN_CAP_PCT))
    return spot * move_pct


def span_margin(spot: float, strike: float, t_years: float, iv: float,
                opt_type: str, side: str, qty: int) -> dict:
    """Initial margin for ONE F&O position. iv as a decimal (0.14 = 14%).
    Returns {margin, scan_loss, exposure, approx}."""
    opt_type, side = opt_type.upper(), side.upper()
    entry_val = bs_price(spot, strike, t_years, iv, opt_type)

    # Long option: the premium is the whole risk.
    if side == 'BUY' and opt_type in ('CE', 'PE'):
        m = entry_val * qty
        return {'margin': round(m, 2), 'scan_loss': round(m, 2),
                'exposure': 0.0, 'approx': True}

    rng = scan_range(spot, iv)
    sign = 1 if side == 'BUY' else -1     # +1 long future, -1 short option/future
    worst_loss = 0.0
    for ps in PRICE_STEPS:
        s = max(spot + ps * rng, 0.01)
        for vs in (1 + VOL_SCAN_REL, 1 - VOL_SCAN_REL):
            val = bs_price(s, strike, t_years, iv * vs, opt_type)
            # P&L of the position in this scenario; a loss is negative
            pnl = sign * (val - entry_val)
            worst_loss = min(worst_loss, pnl)
    scan_loss = abs(worst_loss) * qty

    notional = (spot if opt_type == 'FUT' else strike) * qty
    exposure = notional * EXPOSURE_PCT
    margin = scan_loss + exposure
    return {'margin': round(margin, 2), 'scan_loss': round(scan_loss, 2),
            'exposure': round(exposure, 2), 'approx': True}
