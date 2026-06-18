"""
Per-underlying volatility surface (skew by moneyness) — pure stdlib, no new deps.

WHY THIS EXISTS: paper-mode option pricing uses a single India-VIX scalar as the
IV for EVERY strike (no smile, no skew). Equity-index options trade with a marked
negative skew — out-of-the-money puts price richer than ATM, OTM calls cheaper —
plus a mild convex smile on the wings. This module turns the flat ATM anchor into a
strike-dependent IV so the option chain's premiums/greeks and the SPAN-approx margin
are more faithful, while staying THEORETICAL and labeled, with zero new dependency.

DATA HONESTY: this is a *model*, not a quoted surface. The skew/smile coefficients
are labeled estimates (NIFTY-like, as-of 2026 — verify against a real surface once a
live options feed is available), exactly like the FUT_MARGIN_BAND and SPAN-approx
discipline. In LIVE mode, real per-strike IV implied from Kite LTP replaces this
entirely (see data_ingest/fno_live_chain.py). The ATM anchor is preserved exactly
(k=0 -> atm_iv), so ATM pricing and the S1/S8 ATM-option signal router are unaffected.

Disable with VOL_SURFACE=false to fall back to the flat ATM IV (the prior behavior,
bit-for-bit) — the eval gate and any A/B run flip this switch.
"""

import math
import os

# Coefficients in IV-decimal per unit log-moneyness  k = ln(strike / spot).
# Negative skew: OTM puts (k < 0) gain IV, OTM calls (k > 0) lose IV; the smile
# term adds convexity so both far wings turn back up.
SKEW_SLOPE = 0.32      # ~+0.034 IV (3.4 vol pts) at the 90% strike (k=-0.105) over ATM
SMILE_CURV = 0.60      # mild convexity on the wings
IV_FLOOR   = 0.05      # 5%  — clamp floor
IV_CAP     = 2.00      # 200% — clamp cap
K_CLAMP    = 0.40      # clamp |log-moneyness| so deep wings can't explode the model
TERM_REF_T = 0.25      # skew is calibrated near a 3-month tenor
TERM_LO, TERM_HI = 0.60, 1.50   # short-dated steepens, long-dated flattens (capped)


def surface_enabled() -> bool:
    """VOL_SURFACE env (default ON). When off, skew_iv returns the flat ATM anchor,
    restoring the prior flat-VIX pricing exactly."""
    return os.environ.get('VOL_SURFACE', 'true').lower() in ('1', 'true', 'yes')


def skew_iv(atm_iv: float, spot: float, strike: float,
            t_years: float | None = None) -> float:
    """Strike-dependent IV (decimal) from a flat ATM anchor.

    Returns the ATM anchor unchanged at-the-money, on degenerate inputs, or when
    the surface is disabled — so callers can always route through this helper."""
    if atm_iv <= 0 or spot <= 0 or strike <= 0 or not surface_enabled():
        return atm_iv
    k = math.log(strike / spot)
    k = max(-K_CLAMP, min(K_CLAMP, k))
    skew = SKEW_SLOPE * (-k) + SMILE_CURV * (k * k)     # IV offset vs ATM
    if t_years and t_years > 0:                          # term factor on the skew only
        term = max(TERM_LO, min(TERM_HI, math.sqrt(TERM_REF_T / t_years)))
        skew *= term
    return max(IV_FLOOR, min(atm_iv + skew, IV_CAP))
