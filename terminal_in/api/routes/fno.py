"""F&O endpoints (PRD P2 — F&O execution). Serves the contract model + the
theoretical option chain to the /fno module. Spot and India VIX come from REAL
sources (live tick cache → DB last close); premiums are Black-Scholes theoretical
and labeled. Live-mode Kite chain ingestion replaces the theoretical layer later.
"""

import logging

from flask import Blueprint, jsonify, request

from terminal_in.bus import bus
from terminal_in.data_ingest.contract_specs import FUT_MARGIN_BAND
from terminal_in.data_ingest import fno_instruments as fno
from terminal_in.data_ingest.iv_estimator import iv_for_underlying

bp  = Blueprint('fno', __name__, url_prefix='/api/fno')
log = logging.getLogger(__name__)

_db = None
_fno_broker = None
_live_chain = None        # LiveChain (kite) — only in live mode
VIX_TOKEN = 264969


def init(db=None, fno_broker=None, kite=None):
    global _db, _fno_broker, _live_chain
    _db = db
    _fno_broker = fno_broker
    if kite is not None:
        try:
            from terminal_in.data_ingest.fno_live_chain import LiveChain
            _live_chain = LiveChain(kite)
            log.info('F&O: live Kite chain ingestion enabled')
        except Exception:
            log.exception('F&O: LiveChain init failed — theoretical chain only')
            _live_chain = None


def _spot(token: int) -> tuple[float, str]:
    """Live tick → DB last close. Returns (price, source)."""
    cached = bus.get_cached(f'ticks.{token}')
    if cached and float(cached.get('last_price', 0)) > 0:
        return float(cached['last_price']), 'live'
    if _db is not None:
        try:
            df = _db.get_ohlcv_1d(token, limit=1)
            if df is not None and len(df):
                return float(df['close'].iloc[-1]), 'last_close'
        except Exception:
            pass
    return 0.0, 'unavailable'


def _vix() -> tuple[float, str]:
    return _spot(VIX_TOKEN)


@bp.route('/underlyings')
def underlyings():
    """Tradeable F&O underlyings (indices + single stocks) with live spot."""
    out = []
    for c in fno.CONTRACTS:
        spot, src = _spot(c['token'])
        out.append({
            'label': c['label'], 'symbol': c['symbol'], 'token': c['token'],
            'lot_size': c['lot_size'],
            'kind': 'index' if fno.is_index(c['label']) else 'stock',
            'strike_interval': fno.strike_interval(c['label'], spot or 1000),
            'spot': round(spot, 2), 'spot_source': src,
            'weekly': bool(c.get('weekly_expiry')),
        })
    return jsonify({'underlyings': out, 'fut_margin_band': FUT_MARGIN_BAND})


@bp.route('/expiries')
def expiries():
    label = (request.args.get('underlying') or 'NIFTY').upper()
    if _live_chain is not None:
        try:
            exps = _live_chain.expiries(label)
            if exps:
                return jsonify({'underlying': label, 'expiries': exps, 'source': 'kite_live'})
        except Exception as e:
            log.warning('F&O live expiries failed for %s: %s', label, str(e)[:120])
    return jsonify({'underlying': label, 'expiries': fno.expiries(label)})


@bp.route('/chain')
def chain():
    label = (request.args.get('underlying') or 'NIFTY').upper()
    try:
        n = max(3, min(int(request.args.get('strikes', 10)), 25))
    except (TypeError, ValueError):
        n = 10

    if label not in fno._BY_LABEL:
        return jsonify({'error': f'unknown underlying {label}'}), 404

    token = fno._BY_LABEL[label]['token']
    spot, spot_src = _spot(token)
    if spot <= 0:
        return jsonify({'available': False,
                        'error': 'no spot (no live tick and no stored close)',
                        'underlying': label}), 503
    # ── Live Kite chain (real LTP/OI/volume, IV implied from LTP) ──
    live_error = None
    if _live_chain is not None:
        try:
            exps = _live_chain.expiries(label)
            expiry = request.args.get('expiry') or (exps[0]['date'] if exps else None)
            if not expiry:
                raise RuntimeError('no live expiries')
            data = _live_chain.build_chain(label, spot, expiry, n_strikes=n)
            data.update({
                'available': True,
                'kind': 'index' if fno.is_index(label) else 'stock',
                'spot_source': spot_src, 'expiries': exps,
            })
            return jsonify(data)
        except Exception as e:
            # No silent fallback: log + surface that live ingestion failed and we
            # dropped to the theoretical chain, so the UI can badge it.
            live_error = str(e)[:160]
            log.warning('F&O live chain failed for %s (%s) — theoretical fallback', label, live_error)

    vix, _ = _vix()
    if vix <= 0:
        vix = 14.0  # labeled assumption when VIX feed is cold
    # IV proxy: India VIX for indices; the stock's own realized vol for stocks.
    iv_pct, iv_src = iv_for_underlying(label, _db, vix, token)

    exps = fno.expiries(label)
    expiry = request.args.get('expiry')
    if not expiry:
        expiry = exps[0]['date'] if exps else None
    if not expiry:
        return jsonify({'available': False, 'error': 'no expiries', 'underlying': label}), 503

    data = fno.build_chain(label, spot, iv_pct, expiry, n_strikes=n, iv_source=iv_src)
    data.update({
        'available': True,
        'kind': 'index' if fno.is_index(label) else 'stock',
        'spot_source': spot_src,
        'expiries': exps,
        **({'live_error': live_error} if live_error else {}),
    })
    return jsonify(data)


# ── Paper execution (Stage 3) ──────────────────────────────────────────────────

@bp.route('/order', methods=['POST'])
def place_order():
    """Place a lot-based F&O paper order. Body: {underlying, expiry, strike,
    opt_type, side, lots, sl_premium?, target_premium?}."""
    if _fno_broker is None:
        return jsonify({'ok': False, 'error': 'F&O paper broker unavailable (live mode?)'}), 503
    body = request.get_json(silent=True) or {}
    result = _fno_broker.place_order(body)
    return jsonify(result), (200 if result.get('ok') else 400)


@bp.route('/positions')
def positions():
    if _fno_broker is None:
        return jsonify({'positions': [], 'available': False})
    poss = _fno_broker.positions()
    return jsonify({
        'positions': poss, 'available': True,
        'count': len(poss),
        'unrealized': round(sum(p['unrealized'] for p in poss), 2),
        'margin_used': round(sum(p['margin'] for p in poss), 2),
        'greeks': _fno_broker.portfolio_greeks(),
    })


@bp.route('/close', methods=['POST'])
def close():
    if _fno_broker is None:
        return jsonify({'ok': False, 'error': 'unavailable'}), 503
    body = request.get_json(silent=True) or {}
    trade_id = body.get('trade_id', '')
    if not trade_id:
        return jsonify({'ok': False, 'error': 'trade_id required'}), 400
    return jsonify(_fno_broker.close_position(trade_id, reason='manual'))
