"""
NSE derivatives contract specifications — sourced constants, one place.

Lot sizes: NSE revises these by circular (download ref: nseindia.com →
Market Data → Securities Available for Trading → F&O lot sizes file).
Values below are per NSE circular effective for 2026 contract months:
  NIFTY 75 · BANKNIFTY 35 · FINNIFTY 65 (revised 2024-12, ref circular
  NSE/FAOP/65648; verify on lot-size revision circulars quarterly).

Margins: index futures initial margin = SPAN + exposure margin. NSE
publishes exact SPAN parameters intraday (nseindia.com → Daily Margin
files); brokers typically quote ~11–14% of notional for index futures.
We carry the *exposure-inclusive floor* published by NSE risk management
(SPAN ≈ 9–12% + 2% exposure) as an ESTIMATE band, clearly labeled — the
exact per-contract SPAN file ingestion lands with F&O execution (PRD P2).
Never present these as exact margin requirements.
"""

INDEX_CONTRACTS = [
    {
        'symbol': 'NIFTY 50', 'token': 256265, 'label': 'NIFTY',
        'lot_size': 75,
        'weekly_expiry': 'Thursday', 'monthly_expiry': 'last Thursday',
    },
    {
        'symbol': 'NIFTY BANK', 'token': 260105, 'label': 'BANKNIFTY',
        'lot_size': 35,
        'weekly_expiry': None, 'monthly_expiry': 'last Wednesday',
    },
    {
        'symbol': 'NIFTY FIN SERVICE', 'token': 257801, 'label': 'FINNIFTY',
        'lot_size': 65,
        'weekly_expiry': None, 'monthly_expiry': 'last Tuesday',
    },
]

# Initial margin band for index futures as a fraction of notional
# (SPAN + exposure). Source: NSE risk-management framework; broker margin
# calculators (Zerodha/Kite) quote within this band. ESTIMATE — see header.
FUT_MARGIN_BAND = (0.11, 0.14)

SOURCE_NOTE = (
    'Lot sizes per NSE F&O lot-size circular (rev. 2024-12, effective 2026 '
    'contracts). Margin band = NSE SPAN + exposure estimate; exact SPAN file '
    'ingestion arrives with P2 F&O execution. Not exact margin requirements.'
)


def specs() -> dict:
    return {
        'contracts': INDEX_CONTRACTS,
        'fut_margin_band': FUT_MARGIN_BAND,
        'source_note': SOURCE_NOTE,
    }
