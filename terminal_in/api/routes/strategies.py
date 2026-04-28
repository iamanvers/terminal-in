"""Strategy and DSA allocation endpoints."""

import logging
import numpy as np
from flask import Blueprint, jsonify

bp = Blueprint('strategies', __name__, url_prefix='/api/strategies')
log = logging.getLogger(__name__)

_dsa = None
_analyst = None
_db = None
_instruments = None


def init(dsa, analyst, db=None, instruments=None):
    global _dsa, _analyst, _db, _instruments
    _dsa = dsa
    _analyst = analyst
    _db = db
    _instruments = instruments


@bp.route('/allocations')
def allocations():
    if _dsa is None:
        return jsonify({})
    return jsonify({sid: round(alloc, 4) for sid, alloc in _dsa._allocations.items()})


@bp.route('/scorecards')
def scorecards():
    if _analyst is None:
        return jsonify([])
    return jsonify(_analyst.all_scorecards())


@bp.route('/scorecards/<strategy_id>')
def scorecard(strategy_id):
    if _analyst is None:
        return jsonify({}), 404
    sc = _analyst.get_scorecard(strategy_id)
    if sc is None:
        return jsonify({'error': 'not found'}), 404
    return jsonify(sc)


@bp.route('/analyse/<symbol>')
def analyse(symbol):
    """
    Agentic per-symbol analysis — runs all strategy lenses and synthesises a recommendation.
    Returns indicators, per-strategy verdicts, and an overall recommendation with reasoning.
    """
    if _db is None or _instruments is None:
        return jsonify({'error': 'not ready'}), 503

    from terminal_in.data_ingest.instruments import registry
    from terminal_in.bus import bus
    from terminal_in.strategy_engine.regime.classifier import classifier

    token = registry.token(symbol)
    if token is None:
        return jsonify({'error': 'unknown symbol'}), 404

    # Load OHLCV
    try:
        df1d = _db.get_ohlcv_1d(token=token, limit=300)
    except Exception:
        df1d = None

    if df1d is None or df1d.empty or len(df1d) < 21:
        return jsonify({'error': 'insufficient data', 'symbol': symbol}), 200

    close = df1d['close'].values.astype(float)
    high  = df1d['high'].values.astype(float)
    low   = df1d['low'].values.astype(float)
    vol   = df1d['volume'].values.astype(float)

    # ── Indicators ──────────────────────────────────────────────────
    def ema(arr, n):
        k, e = 2 / (n + 1), arr[0]
        out = []
        for v in arr:
            e = v * k + e * (1 - k)
            out.append(e)
        return np.array(out)

    def rsi(arr, n=14):
        d = np.diff(arr)
        gains = np.where(d > 0, d, 0.0)
        losses = np.where(d < 0, -d, 0.0)
        ag = np.mean(gains[:n]); al = np.mean(losses[:n])
        result = []
        for i in range(n, len(d)):
            ag = (ag * (n - 1) + gains[i]) / n
            al = (al * (n - 1) + losses[i]) / n
            result.append(100 - 100 / (1 + ag / al) if al > 0 else 100.0)
        return np.array(result)

    def atr(h, l, c, n=14):
        tr = np.maximum(h[1:] - l[1:], np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))
        return float(np.mean(tr[-n:])) if len(tr) >= n else float(np.mean(tr))

    ema20_arr = ema(close, 20)
    ema50_arr = ema(close, 50)
    rsi14_arr = rsi(close, 14)

    price_now  = float(close[-1])
    ema20_now  = float(ema20_arr[-1])
    ema50_now  = float(ema50_arr[-1])
    rsi_now    = float(rsi14_arr[-1]) if len(rsi14_arr) > 0 else 50.0
    high52w    = float(np.max(high[-252:])) if len(high) >= 252 else float(np.max(high))
    low52w     = float(np.min(low[-252:])) if len(low) >= 252 else float(np.min(low))
    atr14      = atr(high, low, close, 14)
    vol_avg20  = float(np.mean(vol[-20:])) if len(vol) >= 20 else float(np.mean(vol))
    vol_last   = float(vol[-1])
    # Clamp to ±25% to guard against synthetic holiday bars in paper mode DB
    raw_ret_20d = (price_now - close[-20]) / close[-20] if len(close) >= 20 else 0.0
    ret_20d = max(-0.25, min(0.25, raw_ret_20d))

    # Current regime + VIX from bus
    regime = classifier.current_state
    cached_regime = bus.get_cached('regime.update') or {}
    vix = float(cached_regime.get('india_vix', 15.0))
    size_mult = float(cached_regime.get('size_multiplier', 1.0))

    # ── Strategy lenses ─────────────────────────────────────────────
    lenses = []

    # S2: 52-week breakout
    if regime in ('strong_bull', 'bull'):
        pct_from_52h = (price_now - high52w) / high52w
        if price_now > high52w * 0.995:
            vol_ok = vol_last > vol_avg20 * 1.3
            lenses.append({
                'strategy': 'S2', 'name': '52-Week Breakout', 'side': 'BUY',
                'triggered': price_now >= high52w,
                'detail': f'Price at {(pct_from_52h*100):.1f}% of 52w high ({high52w:.0f}). Volume {"✓ confirmed" if vol_ok else "weak"}.',
                'confidence': 0.65 if (price_now >= high52w and vol_ok) else 0.40,
            })

    # S4: RSI mean reversion
    if regime in ('bull', 'sideways', 'bear'):
        if rsi_now < 38:
            lenses.append({
                'strategy': 'S4', 'name': 'RSI Mean Reversion', 'side': 'BUY',
                'triggered': True,
                'detail': f'RSI-14 at {rsi_now:.1f} — oversold. ATR-based SL: {(price_now - 1.5*atr14):.0f}, target: {(price_now + 2.5*atr14):.0f}.',
                'confidence': min(0.45 + (38 - rsi_now) / 38 * 0.4, 0.85),
            })
        elif rsi_now > 62 and regime == 'bear':
            lenses.append({
                'strategy': 'S4', 'name': 'RSI Mean Reversion', 'side': 'SELL',
                'triggered': True,
                'detail': f'RSI-14 at {rsi_now:.1f} — overbought in bear regime.',
                'confidence': min(0.45 + (rsi_now - 62) / 38 * 0.4, 0.85),
            })
        else:
            lenses.append({
                'strategy': 'S4', 'name': 'RSI Mean Reversion', 'side': 'NEUTRAL',
                'triggered': False,
                'detail': f'RSI-14 at {rsi_now:.1f} — no reversion setup.',
                'confidence': 0.0,
            })

    # S5: EMA pullback
    if regime in ('strong_bull', 'bull'):
        prox = abs(price_now - ema20_now) / ema20_now
        in_uptrend = price_now > ema50_now
        near_ema20 = prox < 0.025
        rsi_zone = 40 <= rsi_now <= 60
        lenses.append({
            'strategy': 'S5', 'name': 'EMA Pullback', 'side': 'BUY' if (in_uptrend and near_ema20 and rsi_zone) else 'NEUTRAL',
            'triggered': in_uptrend and near_ema20 and rsi_zone,
            'detail': (f'EMA20={ema20_now:.0f}, EMA50={ema50_now:.0f}. '
                       f'Price is {"above" if in_uptrend else "below"} EMA50, '
                       f'{"near" if near_ema20 else f"{prox*100:.1f}% away from"} EMA20. '
                       f'RSI {rsi_now:.1f}.'),
            'confidence': 0.55 + (1 - prox / 0.025) * 0.15 if (in_uptrend and near_ema20 and rsi_zone) else 0.0,
        })

    # S8: VIX asymmetry (index only — skip equities)
    if symbol in ('NIFTY 50', 'NIFTY BANK', 'NIFTY FIN SERVICE'):
        if vix > 22 and regime in ('high_vol', 'bear'):
            lenses.append({'strategy': 'S8', 'name': 'VIX Asymmetry', 'side': 'BUY',
                           'triggered': True, 'confidence': 0.60,
                           'detail': f'India VIX at {vix:.1f} — elevated fear. Contrarian reversal setup.'})
        elif vix < 13 and regime in ('bear', 'strong_bear'):
            lenses.append({'strategy': 'S8', 'name': 'VIX Asymmetry', 'side': 'SELL',
                           'triggered': True, 'confidence': 0.55,
                           'detail': f'India VIX at {vix:.1f} — complacency in bear regime. Short signal.'})

    # ── Synthesis ───────────────────────────────────────────────────
    triggered = [l for l in lenses if l['triggered']]
    buys  = [l for l in triggered if l['side'] == 'BUY']
    sells = [l for l in triggered if l['side'] == 'SELL']

    if not triggered:
        verdict = 'WAIT'
        verdict_color = '#888'
        summary = f'No strategy triggers active. RSI {rsi_now:.0f}, price {ret_20d*100:+.1f}% over 20d. Monitor for breakout or mean-reversion entry.'
    elif len(buys) > len(sells):
        avg_conf = sum(l['confidence'] for l in buys) / len(buys)
        verdict = 'BUY' if avg_conf >= 0.6 else 'LEAN LONG'
        verdict_color = '#00C853'
        strats = ', '.join(l['name'] for l in buys)
        summary = f'{len(buys)} bullish lens{"es" if len(buys)>1 else ""} active ({strats}). Regime: {regime}. Avg confidence {avg_conf*100:.0f}%.'
    else:
        avg_conf = sum(l['confidence'] for l in sells) / len(sells)
        verdict = 'SELL' if avg_conf >= 0.6 else 'LEAN SHORT'
        verdict_color = '#D32F2F'
        strats = ', '.join(l['name'] for l in sells)
        summary = f'{len(sells)} bearish lens{"es" if len(sells)>1 else ""} active ({strats}). Regime: {regime}. Avg confidence {avg_conf*100:.0f}%.'

    stop = round(price_now - 1.5 * atr14, 2) if buys else round(price_now + 1.5 * atr14, 2)
    target = round(price_now + 2.5 * atr14, 2) if buys else round(price_now - 2.5 * atr14, 2)

    return jsonify({
        'symbol': symbol,
        'token': token,
        'price': round(price_now, 2),
        'regime': regime,
        'verdict': verdict,
        'verdict_color': verdict_color,
        'summary': summary,
        'indicators': {
            'rsi_14': round(rsi_now, 1),
            'ema_20': round(ema20_now, 2),
            'ema_50': round(ema50_now, 2),
            'atr_14': round(atr14, 2),
            'high_52w': round(high52w, 2),
            'low_52w': round(low52w, 2),
            'ret_20d_pct': round(ret_20d * 100, 2),
            'vol_vs_avg': round(vol_last / vol_avg20, 2) if vol_avg20 > 0 else 1.0,
            'india_vix': round(vix, 1),
        },
        'suggested_sl': stop,
        'suggested_target': target,
        'lenses': lenses,
    })
