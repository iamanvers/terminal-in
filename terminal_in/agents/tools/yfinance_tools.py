"""
yfinance-based financial data tools used by the FinancialAgent.
Each function is a standalone tool that can be called by the LLM.
"""

import logging
from functools import lru_cache
from datetime import datetime, timezone, timedelta

import pandas as pd

log = logging.getLogger(__name__)

_IST = timezone(timedelta(hours=5, minutes=30))


def _yf_import():
    try:
        import yfinance as yf
        return yf
    except ImportError:
        raise RuntimeError('yfinance not installed. Run: pip install yfinance')


def get_stock_data(symbol: str, period: str = '3mo') -> dict:
    """
    Fetch OHLCV data and compute RSI, EMA, volume, momentum indicators.
    symbol: NSE ticker e.g. RELIANCE, INFY
    period: 1d | 5d | 1mo | 3mo | 6mo | 1y
    """
    yf = _yf_import()
    yf_sym = f'{symbol.upper()}.NS'
    try:
        ticker = yf.Ticker(yf_sym)
        hist = ticker.history(period=period, auto_adjust=True)
        if hist.empty:
            return {'error': f'No data for {symbol}', 'symbol': symbol}

        close  = hist['Close']
        volume = hist['Volume']
        high   = hist['High']
        low    = hist['Low']

        # EMAs
        ema9  = close.ewm(span=9,  adjust=False).mean()
        ema21 = close.ewm(span=21, adjust=False).mean()
        ema50 = close.ewm(span=50, adjust=False).mean()

        # RSI-14
        delta = close.diff()
        gain  = delta.clip(lower=0).rolling(14).mean()
        loss  = (-delta.clip(upper=0)).rolling(14).mean()
        rsi   = 100 - (100 / (1 + gain / loss.replace(0, 1e-9)))

        # MACD
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd  = ema12 - ema26
        macd_signal = macd.ewm(span=9, adjust=False).mean()

        # ATR-14
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low  - close.shift()).abs(),
        ], axis=1).max(axis=1)
        atr = tr.rolling(14).mean()

        # 52-week high/low
        w52 = min(len(close), 252)
        w52_high = close.tail(w52).max()
        w52_low  = close.tail(w52).min()

        # Volume MA-20
        vol_ma20 = volume.rolling(20).mean()

        # Bollinger Bands (20,2)
        bb_mid  = close.rolling(20).mean()
        bb_std  = close.rolling(20).std()
        bb_up   = bb_mid + 2 * bb_std
        bb_low_ = bb_mid - 2 * bb_std

        cur  = close.iloc[-1]
        prev = close.iloc[-2] if len(close) >= 2 else cur

        # Trend determination
        if cur > ema21.iloc[-1] > ema50.iloc[-1]:
            trend = 'UPTREND'
        elif cur < ema21.iloc[-1] < ema50.iloc[-1]:
            trend = 'DOWNTREND'
        else:
            trend = 'SIDEWAYS'

        rsi_val = rsi.iloc[-1]
        if rsi_val > 70:
            rsi_signal = 'OVERBOUGHT'
        elif rsi_val < 30:
            rsi_signal = 'OVERSOLD'
        elif rsi_val > 60:
            rsi_signal = 'BULLISH_MOMENTUM'
        elif rsi_val < 40:
            rsi_signal = 'BEARISH_MOMENTUM'
        else:
            rsi_signal = 'NEUTRAL'

        vol_ratio = float(volume.iloc[-1] / vol_ma20.iloc[-1]) if vol_ma20.iloc[-1] > 0 else 1.0

        return {
            'symbol':          symbol.upper(),
            'price':           round(float(cur), 2),
            'change_1d_pct':   round((cur / prev - 1) * 100, 2),
            'change_1m_pct':   round((cur / close.iloc[-22] - 1) * 100, 2) if len(close) >= 22 else None,
            'ema9':            round(float(ema9.iloc[-1]), 2),
            'ema21':           round(float(ema21.iloc[-1]), 2),
            'ema50':           round(float(ema50.iloc[-1]), 2),
            'rsi_14':          round(float(rsi_val), 1),
            'rsi_signal':      rsi_signal,
            'macd':            round(float(macd.iloc[-1]), 3),
            'macd_signal':     round(float(macd_signal.iloc[-1]), 3),
            'macd_histogram':  round(float(macd.iloc[-1] - macd_signal.iloc[-1]), 3),
            'atr_14':          round(float(atr.iloc[-1]), 2),
            'bb_upper':        round(float(bb_up.iloc[-1]), 2),
            'bb_mid':          round(float(bb_mid.iloc[-1]), 2),
            'bb_lower':        round(float(bb_low_.iloc[-1]), 2),
            'bb_pct':          round(float((cur - bb_low_.iloc[-1]) / (bb_up.iloc[-1] - bb_low_.iloc[-1])), 2) if bb_up.iloc[-1] != bb_low_.iloc[-1] else 0.5,
            '52w_high':        round(float(w52_high), 2),
            '52w_low':         round(float(w52_low), 2),
            'pct_from_52w_high': round((cur / w52_high - 1) * 100, 1),
            'pct_from_52w_low':  round((cur / w52_low - 1) * 100, 1),
            'volume_ratio':    round(vol_ratio, 2),
            'trend':           trend,
            'data_points':     len(close),
        }
    except Exception as e:
        log.warning(f'get_stock_data({symbol}): {e}')
        return {'error': str(e), 'symbol': symbol}


def get_fundamentals(symbol: str) -> dict:
    """Get PE ratio, market cap, EPS, dividend yield, book value for an NSE stock."""
    yf = _yf_import()
    yf_sym = f'{symbol.upper()}.NS'
    try:
        ticker = yf.Ticker(yf_sym)
        info   = ticker.info or {}

        def _safe(key, default=None):
            v = info.get(key)
            return v if v is not None else default

        market_cap = _safe('marketCap', 0)
        return {
            'symbol':           symbol.upper(),
            'name':             _safe('longName', symbol),
            'sector':           _safe('sector', 'Unknown'),
            'industry':         _safe('industry', 'Unknown'),
            'market_cap_cr':    round(market_cap / 1e7, 0) if market_cap else None,
            'pe_ratio':         _safe('trailingPE'),
            'forward_pe':       _safe('forwardPE'),
            'pb_ratio':         _safe('priceToBook'),
            'ps_ratio':         _safe('priceToSalesTrailing12Months'),
            'eps_ttm':          _safe('trailingEps'),
            'eps_forward':      _safe('forwardEps'),
            'dividend_yield':   round(_safe('dividendYield', 0) * 100, 2) if _safe('dividendYield') else 0,
            'roe':              _safe('returnOnEquity'),
            'debt_to_equity':   _safe('debtToEquity'),
            'current_ratio':    _safe('currentRatio'),
            'revenue_growth':   _safe('revenueGrowth'),
            'earnings_growth':  _safe('earningsGrowth'),
            'book_value':       _safe('bookValue'),
            '52w_high':         _safe('fiftyTwoWeekHigh'),
            '52w_low':          _safe('fiftyTwoWeekLow'),
            'beta':             _safe('beta'),
            'float_shares':     _safe('floatShares'),
            'analyst_target':   _safe('targetMeanPrice'),
            'analyst_rating':   _safe('recommendationKey', 'N/A'),
        }
    except Exception as e:
        log.warning(f'get_fundamentals({symbol}): {e}')
        return {'error': str(e), 'symbol': symbol}


def scan_momentum(symbols: list[str], top_n: int = 10) -> list[dict]:
    """
    Scan a list of symbols for momentum signals.
    Returns top-N ranked by momentum score.
    """
    results = []
    for sym in symbols:
        data = get_stock_data(sym, period='1mo')
        if 'error' in data:
            continue
        # Momentum score: RSI position + trend + volume
        score = 0.0
        if data['trend'] == 'UPTREND':
            score += 40
        elif data['trend'] == 'SIDEWAYS':
            score += 10
        rsi = data['rsi_14']
        if 55 <= rsi <= 72:
            score += 30
        elif rsi > 72:
            score += 10
        elif rsi > 45:
            score += 15
        if data['volume_ratio'] > 1.5:
            score += 20
        elif data['volume_ratio'] > 1.2:
            score += 10
        pct_52w = data['pct_from_52w_high']
        if -5 <= pct_52w <= 0:
            score += 10  # Near 52W high breakout
        results.append({**data, 'momentum_score': round(score, 1)})
    results.sort(key=lambda x: x['momentum_score'], reverse=True)
    return results[:top_n]


def scan_breakout(symbols: list[str], top_n: int = 10) -> list[dict]:
    """Scan for 52-week high breakout candidates."""
    results = []
    for sym in symbols:
        data = get_stock_data(sym, period='1y')
        if 'error' in data:
            continue
        pct_from_high = data['pct_from_52w_high']
        if -3 <= pct_from_high <= 2 and data['volume_ratio'] > 1.2:
            data['breakout_score'] = round(100 + pct_from_high * 5 + data['volume_ratio'] * 10, 1)
            results.append(data)
    results.sort(key=lambda x: x['breakout_score'], reverse=True)
    return results[:top_n]


def scan_rsi_oversold(symbols: list[str], top_n: int = 10) -> list[dict]:
    """Scan for RSI oversold mean-reversion candidates."""
    results = []
    for sym in symbols:
        data = get_stock_data(sym, period='3mo')
        if 'error' in data:
            continue
        if data['rsi_14'] < 35 and data['price'] > data['ema50']:
            data['reversion_score'] = round(35 - data['rsi_14'], 1)
            results.append(data)
    results.sort(key=lambda x: x['reversion_score'], reverse=True)
    return results[:top_n]


def get_index_data() -> dict:
    """Fetch key NSE/global index data."""
    yf = _yf_import()
    indices = {
        'NIFTY 50':    '^NSEI',
        'BANKNIFTY':   '^NSEBANK',
        'INDIA VIX':   '^INDIAVIX',
        'SENSEX':      '^BSESN',
        'S&P 500':     '^GSPC',
        'NASDAQ':      '^IXIC',
        'DOW JONES':   '^DJI',
        'NIKKEI':      '^N225',
        'FTSE 100':    '^FTSE',
        'USD/INR':     'INR=X',
    }
    result = {}
    for name, sym in indices.items():
        try:
            t = yf.Ticker(sym)
            h = t.history(period='2d')
            if not h.empty:
                cur  = float(h['Close'].iloc[-1])
                prev = float(h['Close'].iloc[-2]) if len(h) >= 2 else cur
                result[name] = {
                    'price': round(cur, 2),
                    'change_pct': round((cur / prev - 1) * 100, 2),
                }
        except Exception:
            pass
    return result
