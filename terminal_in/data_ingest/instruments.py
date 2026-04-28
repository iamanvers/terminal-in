"""
Instrument registry — maps symbol names to Kite instrument tokens.
Tokens are fetched from Kite on startup and cached in SQLite.
In paper/replay mode, uses a built-in stub for common indices.
"""

import logging
from typing import Optional

log = logging.getLogger(__name__)

# Kite instrument tokens for common indices (stable, rarely change)
# Actual equity tokens must be fetched from Kite instruments dump
KNOWN_TOKENS: dict[str, int] = {
    # Indices
    'NIFTY 50':          256265,
    'NIFTY BANK':        260105,
    'BANKNIFTY':         260105,   # alias
    'NIFTY FIN SERVICE': 257801,
    'FINNIFTY':          257801,   # alias
    'INDIA VIX':         264969,
    'NIFTYBEES':         2800641,
    # NSE equities (stable tokens)
    'RELIANCE':          738561,
    'HDFCBANK':          341249,
    'TCS':               2953217,
    'INFY':              408065,
    'ICICIBANK':         1270529,
    'KOTAKBANK':         492033,
    'HINDUNILVR':        356865,
    'SBIN':              779521,
    'BAJFINANCE':        4267265,
    'AXISBANK':          1510401,
    'WIPRO':             969473,
    # Additional Nifty 50 large caps
    'LT':                2939009,
    'MARUTI':            2815745,
    'ASIANPAINT':        60417,
    'TATAMOTORS':        884737,
    'SUNPHARMA':         857857,
    'TATASTEEL':         895745,
    'POWERGRID':         3834113,
    'NTPC':              2977281,
    'ONGC':              633601,
    'TITAN':             897537,
    'HCLTECH':           1850625,
    'TECHM':             3465729,
    'ADANIPORTS':        3861249,
    'ULTRACEMCO':        2952193,
    'NESTLEIND':         4598529,
    'JSWSTEEL':          3001089,
    'DRREDDY':           225537,
    'BAJAJFINSV':        4268801,
    'DIVISLAB':          2865793,
    'HINDALCO':          348929,
}


class InstrumentRegistry:
    def __init__(self):
        self._by_symbol: dict[str, dict] = {}
        self._by_token: dict[int, dict] = {}

    def load_from_kite(self, kite) -> None:
        try:
            instruments = kite.instruments('NSE')
            instruments += kite.instruments('NFO')
            for inst in instruments:
                self._index(inst)
            log.info('Loaded %d instruments from Kite', len(self._by_token))
        except Exception:
            log.exception('Failed to load instruments from Kite')

    def load_stubs(self) -> None:
        for symbol, token in KNOWN_TOKENS.items():
            inst = {
                'instrument_token': token,
                'tradingsymbol': symbol,
                'exchange': 'NSE',
                'instrument_type': 'INDEX' if 'NIFTY' in symbol or 'VIX' in symbol else 'EQ',
            }
            self._index(inst)
        log.info('Loaded %d stub instruments', len(self._by_token))

    def _index(self, inst: dict) -> None:
        token = inst['instrument_token']
        symbol = inst['tradingsymbol']
        self._by_token[token] = inst
        self._by_symbol[symbol] = inst

    def token(self, symbol: str) -> Optional[int]:
        inst = self._by_symbol.get(symbol)
        return inst['instrument_token'] if inst else None

    def symbol(self, token: int) -> Optional[str]:
        inst = self._by_token.get(token)
        return inst['tradingsymbol'] if inst else None

    def get_all(self) -> list:
        return list(self._by_token.values())

    def tokens_for_symbols(self, symbols: list[str]) -> list[int]:
        result = []
        for s in symbols:
            t = self.token(s)
            if t:
                result.append(t)
            else:
                log.warning('No token found for symbol: %s', s)
        return result


registry = InstrumentRegistry()
