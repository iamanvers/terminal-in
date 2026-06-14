"""
Implied-volatility proxy for F&O option pricing (PRD P2 — stock F&O).

No live options feed in paper mode means no real IV. We use the best REAL-data
proxy per underlying:
- INDICES (NIFTY/BANKNIFTY/FINNIFTY): India VIX — literally the 30-day implied
  vol of NIFTY options. The correct IV for index options.
- STOCKS: the stock's OWN trailing realized volatility (annualised, from real
  ohlcv_1d), nudged up by a small implied-over-realized premium. This is the
  right call the user flagged — a high-beta midcap is far more volatile than
  NIFTY, so one index VIX for everything would badly mis-price stock options.

Everything is labeled (iv_source) and clearly a proxy — never a quoted IV.
"""

import math

import numpy as np

INDEX_LABELS = {'NIFTY', 'BANKNIFTY', 'FINNIFTY'}

# Implied vol typically trades a touch above trailing realized (vol risk premium).
IV_OVER_REALIZED = 1.10
RV_WINDOW = 30          # trading days
RV_FLOOR_PCT = 8.0      # don't price a stock at near-zero vol
RV_CAP_PCT = 90.0


def realized_vol_pct(df, window: int = RV_WINDOW) -> float | None:
    """Annualised realized volatility (%) from daily closes. None if too little data."""
    if df is None or 'close' not in getattr(df, 'columns', []):
        return None
    close = df['close'].astype(float)
    rets = np.log(close).diff().dropna()
    if len(rets) < 10:
        return None
    daily_sigma = float(rets.tail(window).std())
    if not np.isfinite(daily_sigma) or daily_sigma <= 0:
        return None
    return daily_sigma * math.sqrt(252.0) * 100.0


def iv_for_underlying(label: str, db, vix_pct: float, token: int | None = None) -> tuple[float, str]:
    """Return (iv_pct, source). Indices → India VIX; stocks → realized-vol proxy."""
    label = label.upper()
    if label in INDEX_LABELS:
        return max(vix_pct, 1.0), 'INDIA VIX (index implied vol)'
    if db is not None and token:
        try:
            rv = realized_vol_pct(db.get_ohlcv_1d(token, limit=RV_WINDOW + 15))
        except Exception:
            rv = None
        if rv is not None:
            iv = min(max(rv * IV_OVER_REALIZED, RV_FLOOR_PCT), RV_CAP_PCT)
            return iv, f'{RV_WINDOW}d realized vol ×{IV_OVER_REALIZED:g} (proxy)'
    # fallback: index VIX, flagged
    return max(vix_pct, 1.0), 'INDIA VIX (fallback — no stock history)'
