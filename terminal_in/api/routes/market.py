"""Market data, regime, and news endpoints."""

import json as _json

from flask import Blueprint, jsonify, request

bp = Blueprint('market', __name__, url_prefix='/api/market')

_db = None


def init(db):
    global _db
    _db = db


@bp.route('/regime')
def regime():
    from terminal_in.bus import bus
    cached = bus.get_cached('regime.update') or {}
    return jsonify(cached)


@bp.route('/ohlcv/<symbol>')
def ohlcv(symbol):
    if _db is None:
        return jsonify([])
    from terminal_in.data_ingest.instruments import registry
    token = registry.token(symbol)
    if token is None:
        return jsonify([])  # unknown symbol → empty, not 404
    timeframe = request.args.get('tf', '1d')
    limit = int(request.args.get('limit', 200))
    if timeframe == '1d':
        df = _db.get_ohlcv_1d(token=token, limit=limit)
        if df.empty:
            return jsonify([])
        df = df.reset_index()
        df['bucket_date'] = df['bucket_date'].dt.strftime('%Y-%m-%d')
    else:
        # Fetch more 1m bars when resampling to coarser timeframe
        minutes = int(timeframe.rstrip('m')) if timeframe != '1m' else 1
        fetch_limit = limit * minutes
        df = _db.get_ohlcv_1m(token=token, limit=min(fetch_limit, 5000))
        if df.empty:
            return jsonify([])
        if timeframe != '1m':
            # minutes already computed above
            try:
                df = df.resample(f'{minutes}min').agg(
                    {'open': 'first', 'high': 'max', 'low': 'min',
                     'close': 'last', 'volume': 'sum'}
                ).dropna()
            except Exception:
                pass  # fall back to raw 1m
        import pandas as pd
        df = df.reset_index()
        # Robust ms conversion across pandas versions (2.x returns ms-res datetimes)
        epoch = pd.Timestamp('1970-01-01', tz='UTC')
        df['bucket_time'] = (df['bucket_time'] - epoch) // pd.Timedelta('1ms')
    return jsonify(df.to_dict(orient='records'))


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
    """Return 90-day daily OHLCV for any yfinance ticker (for global quote mini-charts)."""
    symbol = request.args.get('symbol', '')
    if not symbol:
        return jsonify([])
    try:
        import yfinance as yf
        from datetime import date, timedelta
        end = date.today()
        start = end - timedelta(days=90)
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
