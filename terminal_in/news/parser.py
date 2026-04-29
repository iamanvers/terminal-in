"""
Extract instrument symbol mentions from news headlines/body.

Relevance rules:
  - Macro entities (NIFTY, BANKNIFTY, RBI, SEBI, NSE, BSE, VIX):
    tagged on any mention in headline OR body.
  - Individual equities:
    tagged if present in the HEADLINE, or mentioned 2+ times in the body.
    A single passing body mention ("RELIANCE gained 0.2%") is not enough.
"""

import re

WATCHLIST = [
    'NIFTY', 'BANKNIFTY', 'FINNIFTY', 'VIX',
    'RELIANCE', 'HDFCBANK', 'TCS', 'INFY', 'ICICIBANK',
    'KOTAKBANK', 'HINDUNILVR', 'SBIN', 'BAJFINANCE', 'AXISBANK',
    'WIPRO', 'LTIM', 'TITAN', 'MARUTI', 'ONGC', 'NTPC',
    'ADANIENT', 'ADANIPORTS', 'TATAMOTORS', 'TATASTEEL',
    'JSWSTEEL', 'POWERGRID', 'SUNPHARMA', 'DRREDDY', 'CIPLA',
    'ULTRACEMCO', 'GRASIM', 'ASIANPAINT',
    'RBI', 'SEBI', 'NSE', 'BSE',
]

# Macro / market-wide entities — relevant even with a single body mention
_MACRO = frozenset({'NIFTY', 'BANKNIFTY', 'FINNIFTY', 'VIX', 'RBI', 'SEBI', 'NSE', 'BSE'})

_PATTERNS = {sym: re.compile(rf'\b{re.escape(sym)}\b', re.IGNORECASE) for sym in WATCHLIST}


def extract_instruments(headline: str, body: str = '') -> list[str]:
    """
    headline — article title (required).
    body     — article description/summary (optional).
    Returns a deduplicated list of relevant ticker symbols.
    """
    found = []
    for sym, pat in _PATTERNS.items():
        in_headline = bool(pat.search(headline))
        if in_headline:
            found.append(sym)
            continue
        # Not in headline — apply relaxed rules
        if sym in _MACRO:
            if body and pat.search(body):
                found.append(sym)
        else:
            # Equity: body-only mention only counts if it appears 2+ times
            if body and len(pat.findall(body)) >= 2:
                found.append(sym)
    return found


def classify_impact(score: float, sentiment: str) -> str:
    if score >= 0.85:
        return 'high'
    if score >= 0.60:
        return 'medium'
    return 'low'
