"""Market data, regime, and news endpoints."""

import json as _json
import time as _time_mod
from datetime import datetime, timezone, timedelta

from flask import Blueprint, jsonify, request

bp = Blueprint('market', __name__, url_prefix='/api/market')

_db = None

# ── In-process OHLCV response cache ──────────────────────────────────────────
# Keyed by (symbol, tf, limit). 10s TTL during market, 5min outside.
_ohlcv_cache: dict = {}

_IST = timezone(timedelta(hours=5, minutes=30))


def _is_nse_open() -> bool:
    t = datetime.now(_IST)
    if t.weekday() >= 5:
        return False
    m = t.hour * 60 + t.minute
    return 9 * 60 + 15 <= m <= 15 * 60 + 30


def _cache_ttl() -> int:
    return 10 if _is_nse_open() else 300


def _cache_get(key: str):
    entry = _ohlcv_cache.get(key)
    if not entry:
        return None
    ts, data = entry
    if _time_mod.time() - ts > _cache_ttl():
        del _ohlcv_cache[key]
        return None
    return data


def _cache_set(key: str, data):
    # Prune old entries to cap memory (~200 keys max)
    if len(_ohlcv_cache) > 200:
        oldest = min(_ohlcv_cache, key=lambda k: _ohlcv_cache[k][0])
        del _ohlcv_cache[oldest]
    _ohlcv_cache[key] = (_time_mod.time(), data)


def init(db):
    global _db
    _db = db


@bp.route('/regime')
def regime():
    from terminal_in.bus import bus
    cached = bus.get_cached('regime.update') or {}
    return jsonify(cached)


@bp.route('/ticks')
def all_ticks():
    """Return all current tick snapshots from EventBus hot cache."""
    from terminal_in.bus import bus
    from terminal_in.data_ingest.instruments import registry
    result = {}
    for inst in registry.get_all():
        token = inst['instrument_token']
        cached = bus.get_cached(f'ticks.{token}')
        if cached:
            result[str(token)] = cached
    return jsonify(result)


@bp.route('/ohlcv/<symbol>')
def ohlcv(symbol):
    if _db is None:
        return jsonify([])

    timeframe = request.args.get('tf', '1d')
    limit = int(request.args.get('limit', 200))

    # Check in-process cache first
    cache_key = f'{symbol}:{timeframe}:{limit}'
    cached = _cache_get(cache_key)
    if cached is not None:
        return jsonify(cached)

    from terminal_in.data_ingest.instruments import registry
    token = registry.token(symbol)
    if token is None:
        return jsonify([])

    if timeframe == '1d':
        df = _db.get_ohlcv_1d(token=token, limit=limit)
        if df.empty:
            return jsonify([])
        df = df.reset_index()
        df['bucket_date'] = df['bucket_date'].dt.strftime('%Y-%m-%d')
    else:
        minutes = int(timeframe.rstrip('m')) if timeframe != '1m' else 1
        fetch_limit = min(limit * minutes * 2, 10000)  # fetch extra to cover filtering
        df = _db.get_ohlcv_1m(token=token, limit=fetch_limit)
        if df.empty:
            return jsonify([])

        # ── Filter to NSE market hours (IST 09:15–15:30, Mon–Fri) ────────────
        # df.index is UTC-aware DatetimeIndex
        df_ist = df.tz_convert('Asia/Kolkata')
        tod = df_ist.index.hour * 60 + df_ist.index.minute
        dow = df_ist.index.dayofweek  # 0=Mon … 4=Fri
        market_mask = (tod >= 9 * 60 + 15) & (tod <= 15 * 60 + 30) & (dow < 5)
        df = df[market_mask]
        if df.empty:
            return jsonify([])

        if timeframe != '1m':
            try:
                df = df.resample(f'{minutes}min').agg(
                    {'open': 'first', 'high': 'max', 'low': 'min',
                     'close': 'last', 'volume': 'sum'}
                ).dropna()
            except Exception:
                pass

        # Trim to requested limit after resampling
        if len(df) > limit:
            df = df.iloc[-limit:]

        import pandas as pd
        df = df.reset_index()
        epoch = pd.Timestamp('1970-01-01', tz='UTC')
        df['bucket_time'] = (df['bucket_time'] - epoch) // pd.Timedelta('1ms')

    result = df.to_dict(orient='records')
    _cache_set(cache_key, result)
    return jsonify(result)


@bp.route('/closes')
def last_closes():
    """Return the most recent daily close price for every registered instrument.

    Used by the UI as a fallback when live ticks are unavailable (market closed).
    Response: { "<token>": { "close": float, "date": "YYYY-MM-DD" }, ... }
    """
    if _db is None:
        return jsonify({})
    from terminal_in.data_ingest.instruments import registry
    result = {}
    for inst in registry.get_all():
        token = inst['instrument_token']
        try:
            df = _db.get_ohlcv_1d(token=token, limit=2)
            if not df.empty:
                result[str(token)] = {
                    'close': float(df['close'].iloc[-1]),
                    'date': str(df.index[-1].date()),
                }
        except Exception:
            pass
    return jsonify(result)


@bp.route('/news')
def news():
    if _db is None:
        return jsonify([])
    limit = int(request.args.get('limit', 50))
    rows = _db.get_recent_news(limit=limit)
    for row in rows:
        raw = row.get('instruments_json', '[]') or '[]'
        try:
            row['instruments'] = _json.loads(raw)
        except Exception:
            row['instruments'] = []
    return jsonify(rows)


@bp.route('/global')
def global_quotes():
    try:
        from terminal_in.data_ingest.global_quotes import get_quotes
        return jsonify(get_quotes())
    except Exception:
        return jsonify([])


@bp.route('/global_history')
def global_history():
    """Return 90-day daily OHLCV for any yfinance ticker."""
    symbol = request.args.get('symbol', '')
    if not symbol:
        return jsonify([])
    try:
        import yfinance as yf
        from datetime import date
        end = date.today()
        from datetime import timedelta as td
        start = end - td(days=90)
        hist = yf.Ticker(symbol).history(start=start.isoformat(), end=end.isoformat(), interval='1d', auto_adjust=True)
        if hist.empty:
            return jsonify([])
        rows = []
        for idx, row in hist.iterrows():
            rows.append({
                'date':   str(idx.date()),
                'open':   round(float(row['Open']), 4),
                'high':   round(float(row['High']), 4),
                'low':    round(float(row['Low']),  4),
                'close':  round(float(row['Close']), 4),
                'volume': int(row.get('Volume', 0)),
            })
        return jsonify(rows)
    except Exception:
        return jsonify([])


@bp.route('/tick/<symbol>')
def last_tick(symbol):
    from terminal_in.bus import bus
    from terminal_in.data_ingest.instruments import registry
    token = registry.token(symbol)
    if token is None:
        return jsonify({'error': 'unknown symbol'}), 404
    cached = bus.get_cached(f'ticks.{token}') or {}
    return jsonify(cached)


@bp.route('/instruments')
def instruments():
    from terminal_in.data_ingest.instruments import registry
    result = []
    for inst in registry.get_all():
        result.append({
            'symbol': inst['tradingsymbol'],
            'token':  inst['instrument_token'],
            'type':   inst.get('instrument_type', 'EQ'),
        })
    result.sort(key=lambda x: x['symbol'])
    return jsonify(result)

@bp.route('/contract-specs')
def contract_specs():
    """NSE index derivative specs (sourced constants — see module docstring)."""
    from terminal_in.data_ingest.contract_specs import specs
    return jsonify(specs())

