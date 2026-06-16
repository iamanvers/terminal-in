"""
costs.py — single source of truth for Indian-equity transaction costs.

All-in fees and taxes for one executed equity order (NSE cash segment), modelled
on the Zerodha schedule. Used by the paper broker, live execution, and the
backtest so the three can never diverge on what a fill actually costs.

SCOPE: this is fees + statutory taxes ONLY. Slippage is a PRICE adjustment and
lives at the fill site (it is not a fee) — keep it separate.

Rates are NAMED constants, each annotated with its rate and an "as-of 2026,
verify" note. Statutory rates change; never bury a magic number in a formula.
"""

from __future__ import annotations

# ── Brokerage (Zerodha-style) ──────────────────────────────────────────────
# CNC delivery is brokerage-free; MIS intraday is min(0.03% of turnover, ₹20)
# per executed order.  As-of 2026, verify.
BROKERAGE_CNC          = 0.0
BROKERAGE_MIS_PCT      = 0.0003     # 0.03% of notional, per order
BROKERAGE_MIS_CAP      = 20.0       # ₹20 cap, per order

# ── Securities Transaction Tax (STT) ───────────────────────────────────────
# CNC delivery: 0.1% on BOTH buy and sell.  MIS intraday: 0.025% on the SELL
# leg only.  As-of 2026, verify.
STT_CNC_PCT            = 0.001      # 0.1%, both sides
STT_MIS_SELL_PCT       = 0.00025   # 0.025%, sell side only

# ── Exchange transaction charge ────────────────────────────────────────────
# NSE equity, per side of turnover.  As-of 2026, verify.
EXCHANGE_TXN_PCT       = 0.0000297  # 0.00297% of turnover, per side

# ── SEBI turnover fee ──────────────────────────────────────────────────────
# ₹10 per crore of turnover, per side.  As-of 2026, verify.
SEBI_PCT               = 0.000001   # 0.0001% of turnover, per side

# ── Stamp duty ─────────────────────────────────────────────────────────────
# Charged on the BUY leg only.  CNC delivery 0.015%; MIS intraday 0.003%.
# As-of 2026, verify.
STAMP_CNC_BUY_PCT      = 0.00015    # 0.015%, buy side only
STAMP_MIS_BUY_PCT      = 0.00003    # 0.003%, buy side only

# ── GST ────────────────────────────────────────────────────────────────────
# 18% on (brokerage + exchange transaction charge + SEBI fee).  As-of 2026,
# verify.
GST_PCT                = 0.18       # 18%, on brokerage + exchange_txn + sebi


def cost_breakdown(notional: float, side: str, segment: str) -> dict:
    """All-in cost of ONE executed equity fill, segment- and side-aware.

    Args:
        notional: post-slippage fill notional (price × qty), in ₹. Sign-agnostic.
        side: 'BUY' or 'SELL'.
        segment: 'CNC' (delivery) or 'MIS' (intraday).

    Returns:
        dict with keys brokerage, stt, exchange_txn, sebi, stamp, gst, total —
        each a ₹ amount (floats, unrounded).

    Raises ValueError on an unknown side/segment (no silent fallback — repo
    convention is to surface, not guess).
    """
    side = str(side).upper()
    segment = str(segment).upper()
    if side not in ('BUY', 'SELL'):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if segment not in ('CNC', 'MIS'):
        raise ValueError(f"segment must be CNC or MIS, got {segment!r}")

    turnover = abs(float(notional))

    # brokerage
    if segment == 'MIS':
        brokerage = min(BROKERAGE_MIS_PCT * turnover, BROKERAGE_MIS_CAP)
    else:
        brokerage = BROKERAGE_CNC

    # STT
    if segment == 'CNC':
        stt = STT_CNC_PCT * turnover                      # both sides
    else:
        stt = STT_MIS_SELL_PCT * turnover if side == 'SELL' else 0.0

    # exchange transaction charge (per side)
    exchange_txn = EXCHANGE_TXN_PCT * turnover

    # SEBI turnover fee (per side)
    sebi = SEBI_PCT * turnover

    # stamp duty (buy side only)
    if side == 'BUY':
        stamp = (STAMP_CNC_BUY_PCT if segment == 'CNC' else STAMP_MIS_BUY_PCT) * turnover
    else:
        stamp = 0.0

    # GST on brokerage + exchange + sebi
    gst = GST_PCT * (brokerage + exchange_txn + sebi)

    total = brokerage + stt + exchange_txn + sebi + stamp + gst
    return {
        'brokerage':    brokerage,
        'stt':          stt,
        'exchange_txn': exchange_txn,
        'sebi':         sebi,
        'stamp':        stamp,
        'gst':          gst,
        'total':        total,
    }
