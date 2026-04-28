"""
Extract instrument symbol mentions from news headlines/body.
Matches against a known symbol list. Case-insensitive whole-word match.
"""

import re
from typing import Optional

# Symbols to scan for — extend as tracked universe grows
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

_PATTERNS = {sym: re.compile(rf'\b{re.escape(sym)}\b', re.IGNORECASE) for sym in WATCHLIST}


def extract_instruments(text: str) -> list[str]:
    if not text:
        return []
    found = [sym for sym, pat in _PATTERNS.items() if pat.search(text)]
    return found


def classify_impact(score: float, sentiment: str) -> str:
    if score >= 0.85:
        return 'high'
    if score >= 0.60:
        return 'medium'
    return 'low'
