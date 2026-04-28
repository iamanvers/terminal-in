"""
Market intelligence chat endpoint.
Parses user intent, pulls live context from bus/db, runs FinBERT on user text,
and accepts override commands (stop loss multiplier, position sizes, strategy weights).
"""
import logging
import re

from flask import Blueprint, jsonify, request

bp = Blueprint('chat', __name__, url_prefix='/api/chat')
log = logging.getLogger(__name__)

_db = None

# Runtime overrides — published to bus so engine can pick them up
_overrides: dict = {}

KNOWN_SYMBOLS: dict[str, str] = {
    'nifty 50': 'NIFTY 50', 'nifty50': 'NIFTY 50', 'nifty': 'NIFTY 50',
    'banknifty': 'BANKNIFTY', 'bank nifty': 'BANKNIFTY',
    'finnifty': 'FINNIFTY',
    'reliance': 'RELIANCE',
    'hdfcbank': 'HDFCBANK', 'hdfc': 'HDFCBANK',
    'tcs': 'TCS',
    'infy': 'INFY', 'infosys': 'INFY',
    'icicibank': 'ICICIBANK', 'icici': 'ICICIBANK',
    'sbin': 'SBIN', 'sbi': 'SBIN',
    'axisbank': 'AXISBANK', 'axis': 'AXISBANK',
    'kotakbank': 'KOTAKBANK', 'kotak': 'KOTAKBANK',
    'bajfinance': 'BAJFINANCE', 'bajaj finance': 'BAJFINANCE',
    'hindunilvr': 'HINDUNILVR', 'hul': 'HINDUNILVR',
    'wipro': 'WIPRO',
    'vix': 'INDIA VIX', 'india vix': 'INDIA VIX',
}

STRAT_NAMES: dict[str, str] = {
    'orb': 'S1', 'opening range': 'S1',
    '52w': 'S2', '52 week': 'S2',
    'breakout': 'S3', 'bkt': 'S3',
    'rsi': 'S4', 'reversion': 'S4',
    'ema': 'S5', 'pullback': 'S5',
    'pair': 'S6', 'pairs': 'S6', 'cointegration': 'S6',
    'hawkes': 'S9', 'momentum': 'S9', 'hwk': 'S9',
}

STRAT_DESC = {
    'S1': 'ORB (Opening Range Breakout)',
    'S2': '52W (52-Week Breakout)',
    'S3': 'BKT (Midcap Breakout)',
    'S4': 'RSI (Mean Reversion)',
    'S5': 'EMA (Pullback to EMA)',
    'S6': 'PAIR (Pairs Cointegration)',
    'S8': 'VIX (Volatility Asymmetry)',
    'S9': 'HWK (Hawkes Momentum)',
}

REGIME_DESC = {
    'strong_bull': 'Strong uptrend — all strategies at full capacity. Favour breakouts.',
    'bull':        'Bullish trend with moderate momentum. S1/S2/S3 well-suited.',
    'sideways':    'Range-bound. Reversion strategies (S4/S5) outperform breakouts.',
    'bear':        'Bearish. Reduce position sizes. Tighter stops. Avoid new longs.',
    'strong_bear': 'Aggressive downtrend. Capital preservation mode. Minimal new positions.',
    'high_vol':    'Elevated volatility. S8 (VIX fade) is primary signal source. Wider stops.',
    'unknown':     'Regime classifier warming up — insufficient data.',
}


def init(db):
    global _db
    _db = db


# ── Helpers ──────────────────────────────────────────────────────────────────

def _finbert(text: str) -> dict:
    try:
        from terminal_in.news import sentiment as sent
        return sent.score(text)
    except Exception:
        return {'sentiment': 'neutral', 'score': 0.0}


def _get_portfolio() -> dict:
    if not _db:
        return {}
    try:
        return _db.get_portfolio_summary() or {}
    except Exception:
        return {}


def _get_news() -> list:
    if not _db:
        return []
    try:
        return _db.get_recent_news(limit=15) or []
    except Exception:
        return []


def _detect_symbol(msg: str) -> tuple[str | None, str | None]:
    """Returns (symbol, keyword) if a known symbol is mentioned."""
    for kw, sym in sorted(KNOWN_SYMBOLS.items(), key=lambda x: -len(x[0])):
        if kw in msg:
            return sym, kw
    return None, None


# ── Intent handlers ───────────────────────────────────────────────────────────

def _handle_regime(regime: dict) -> str:
    r     = regime.get('regime', 'unknown')
    conf  = regime.get('confidence', 0) * 100
    vix   = regime.get('india_vix', 0)
    size  = regime.get('size_multiplier', 1.0)
    lines = [
        f'Regime: {r.upper()} ({conf:.0f}% confidence)',
        REGIME_DESC.get(r, ''),
        '',
        f'India VIX: {vix:.1f}  |  Size multiplier: {size:.2f}×',
    ]
    if vix > 25:
        lines.append(f'⚠ VIX > 25 — hard stop on new positions if VIX breaches 30.')
    return '\n'.join(lines)


def _handle_signals(signals: list, regime: dict) -> str:
    if not signals:
        r = regime.get('regime', 'sideways')
        hints = {
            'strong_bull': 'Consider S1 (ORB) on index opens and S3 (Breakout) on equities.',
            'bull':        'S2 (52W Breakout) and S5 (EMA Pullback) well-suited to this regime.',
            'sideways':    'S4 (RSI Reversion) performs best in range-bound conditions.',
            'bear':        'Limit new longs. S8 (VIX fade) on volatility spikes only.',
            'strong_bear': 'Avoid new positions. Wait for regime shift confirmation.',
            'high_vol':    'S8 (VIX Asymmetry) is the primary signal source in high-vol regimes.',
        }
        return f'No live signals at this moment (strategies scan every 60s).\n\n{hints.get(r, "Monitor for regime shift.")}'

    top = sorted(signals, key=lambda s: s.get('confidence', 0), reverse=True)[:5]
    lines = [f'Top {len(top)} signal{"s" if len(top) > 1 else ""} right now:\n']
    for s in top:
        sid   = s.get('strategy_id', '?')
        side  = s.get('side', '?')
        token = s.get('instrument_id', 0)
        conf  = s.get('confidence', 0) * 100
        tgt   = s.get('target')
        sl    = s.get('stop_loss')
        reg   = s.get('regime', '')
        from terminal_in.data_ingest.instruments import registry
        sym = registry.symbol(token) or f'#{token}'
        line = f'  {STRAT_DESC.get(sid, sid)} on {sym}: {side} @ {conf:.0f}% conf'
        if tgt: line += f'  |  T {tgt:.0f}'
        if sl:  line += f'  |  SL {sl:.0f}'
        if reg: line += f'  [{reg}]'
        lines.append(line)
    return '\n'.join(lines)


def _handle_symbol(symbol: str, keyword: str, regime: dict, signals: list, news: list) -> str:
    from terminal_in.bus import bus
    from terminal_in.data_ingest.instruments import registry

    token = registry.token(symbol)
    tick  = bus.get_cached(f'ticks.{token}') or {} if token else {}
    price = tick.get('last_price', 0)
    chg   = tick.get('change', 0)

    sym_signals = [s for s in signals if s.get('instrument_id') == token]
    sym_news    = [n for n in news
                   if keyword in (n.get('headline', '') + ' '.join(n.get('instruments', []))).lower()]

    lines = [f'{symbol} — Current Analysis\n']
    if price:
        lines.append(f'Price: ₹{price:,.2f}  ({("+" if chg >= 0 else "")}{chg:.2f}%)')

    r = regime.get('regime', 'unknown')
    lines.append(f'Market regime: {r}')

    if sym_signals:
        lines.append('\nActive strategy signals:')
        for s in sym_signals[:3]:
            sid  = s.get('strategy_id', '?')
            conf = s.get('confidence', 0) * 100
            side = s.get('side', '?')
            tgt  = s.get('target')
            sl   = s.get('stop_loss')
            line = f'  {STRAT_DESC.get(sid, sid)}: {side}  {conf:.0f}% conf'
            if tgt: line += f'  T {tgt:.0f}'
            if sl:  line += f'  SL {sl:.0f}'
            lines.append(line)
    else:
        lines.append('\nNo active signals for this instrument.')

    if sym_news:
        lines.append('\nRecent headlines:')
        for n in sym_news[:3]:
            arrow = '↑' if n.get('sentiment') == 'positive' else '↓' if n.get('sentiment') == 'negative' else '→'
            lines.append(f'  {arrow} {n.get("headline", "")[:75]}')

    # Synthesis
    if sym_signals:
        buys  = [s for s in sym_signals if s.get('side') == 'BUY']
        sells = [s for s in sym_signals if s.get('side') == 'SELL']
        avg   = sum(s.get('confidence', 0) for s in sym_signals) / len(sym_signals)
        if len(buys) > len(sells) and avg > 0.55:
            lines.append(f'\n→ Lean BULLISH on {symbol}  (avg confidence {avg*100:.0f}%)')
        elif len(sells) > len(buys) and avg > 0.55:
            lines.append(f'\n→ Lean BEARISH on {symbol}  (avg confidence {avg*100:.0f}%)')
        else:
            lines.append(f'\n→ Mixed signals on {symbol}. Monitor closely.')
    elif chg > 1.5:
        lines.append(f'\n→ Positive momentum (+{chg:.2f}%). Watch for pullback entry if regime supports.')
    elif chg < -1.5:
        lines.append(f'\n→ Declining today ({chg:.2f}%). Avoid catching falling knives in bear regime.')

    return '\n'.join(lines)


def _handle_portfolio(portfolio: dict, regime: dict) -> str:
    equity    = portfolio.get('equity', 0)
    pnl       = portfolio.get('daily_pnl', 0)
    dd        = portfolio.get('drawdown', 0) * 100
    positions = portfolio.get('open_positions', 0)
    trades    = portfolio.get('daily_trades', 0)
    r         = regime.get('regime', 'unknown')
    size      = regime.get('size_multiplier', 1.0)

    lines = [
        'Portfolio Status\n',
        f'Equity:        ₹{equity:,.0f}',
        f'Day P&L:       {"+" if pnl >= 0 else ""}₹{pnl:,.0f}',
        f'Drawdown:      {dd:.2f}%',
        f'Open positions:{positions}',
        f'Day trades:    {trades}',
        '',
        f'Regime: {r}  |  Size multiplier: {size:.2f}×',
    ]
    if dd > 15:
        lines.append(f'\n⚠ Drawdown at {dd:.1f}% — circuit breaker triggers at 20%.')
    overrides_active = [k for k in _overrides if not k.startswith('_')]
    if overrides_active:
        lines.append(f'\nActive overrides: {", ".join(overrides_active)}')
    return '\n'.join(lines)


def _handle_news(news: list) -> str:
    if not news:
        return 'No recent news available.'
    pos = sum(1 for n in news if n.get('sentiment') == 'positive')
    neg = sum(1 for n in news if n.get('sentiment') == 'negative')
    neu = len(news) - pos - neg
    lines = [f'Last {len(news)} news items: {pos} positive  {neg} negative  {neu} neutral\n']
    for n in news[:6]:
        arrow = '↑' if n.get('sentiment') == 'positive' else '↓' if n.get('sentiment') == 'negative' else '→'
        lines.append(f'{arrow} {n.get("headline", "")[:78]}')
    bias = (pos - neg) / len(news) if news else 0
    if bias > 0.3:
        lines.append('\n→ Predominantly positive news flow. Supports risk-on posture.')
    elif bias < -0.3:
        lines.append('\n→ Predominantly negative news flow. Risk-off tone.')
    else:
        lines.append('\n→ Mixed news flow — no strong directional bias from headlines.')
    return '\n'.join(lines)


def _handle_stop_override(msg: str, regime: dict) -> dict:
    nums      = re.findall(r'(\d+(?:\.\d+)?)', msg)
    direction = 'increase' if any(k in msg for k in ('increase', 'widen', 'wider', 'loosen')) else 'reduce'
    pct       = float(nums[0]) if nums else 10.0
    mult      = round((1 + pct / 100) if direction == 'increase' else (1 - pct / 100), 3)
    mult      = max(0.5, min(2.0, mult))

    _overrides['stop_loss_multiplier'] = mult
    try:
        from terminal_in.bus import bus
        bus.publish('config.override', {'stop_loss_multiplier': mult})
    except Exception:
        pass

    vix = regime.get('india_vix', 0)
    note = f'\nNote: VIX at {vix:.1f} — wider stops appropriate given volatility.' if vix > 20 and direction == 'increase' else ''
    msg_out = (
        f'Stop loss override applied\n\n'
        f'All stop losses {direction}d by {pct:.0f}%\n'
        f'Multiplier: {mult:.3f}×{note}'
    )
    return {'message': msg_out, 'type': 'command_applied', 'override': {'stop_loss_multiplier': mult}}


def _handle_size_override(msg: str, regime: dict) -> dict:
    nums      = re.findall(r'(\d+(?:\.\d+)?)', msg)
    direction = 'increase' if any(k in msg for k in ('increase', 'larger', 'more', 'add', 'raise')) else 'reduce'
    pct       = float(nums[0]) if nums else 20.0
    mult      = round((1 + pct / 100) if direction == 'increase' else (1 - pct / 100), 3)
    mult      = max(0.1, min(2.0, mult))

    _overrides['position_size_multiplier'] = mult
    try:
        from terminal_in.bus import bus
        bus.publish('config.override', {'position_size_multiplier': mult})
    except Exception:
        pass

    regime_size = regime.get('size_multiplier', 1.0)
    effective   = round(regime_size * mult, 3)
    msg_out = (
        f'Position size override applied\n\n'
        f'Sizes {direction}d by {pct:.0f}%\n'
        f'User multiplier:   {mult:.2f}×\n'
        f'Regime multiplier: {regime_size:.2f}×\n'
        f'Effective:         {effective:.2f}×'
    )
    return {'message': msg_out, 'type': 'command_applied', 'override': {'position_size_multiplier': mult}}


def _handle_strategy_weight(msg: str) -> dict:
    direction = 'overweight' if 'overweight' in msg else 'underweight'
    sid = None
    for kw, s in sorted(STRAT_NAMES.items(), key=lambda x: -len(x[0])):
        if kw in msg:
            sid = s
            break
    if not sid:
        available = '  '.join(f'{v} ({k})' for k, v in STRAT_DESC.items())
        return {'message': f'Specify which strategy to {direction}.\nAvailable: {available}', 'type': 'info'}

    nums  = re.findall(r'(\d+(?:\.\d+)?)', msg)
    pct   = float(nums[0]) if nums else 10.0
    delta = round(pct / 100 if direction == 'overweight' else -pct / 100, 3)

    _overrides.setdefault('allocation_deltas', {})[sid] = delta
    try:
        from terminal_in.bus import bus
        bus.publish('config.override', {'allocation_deltas': {sid: delta}})
    except Exception:
        pass

    return {
        'message': (
            f'Strategy weight override applied\n\n'
            f'{STRAT_DESC.get(sid, sid)} {direction}ed by {pct:.0f}%\n'
            f'Change applies on next DSA rebalance cycle.'
        ),
        'type': 'command_applied',
        'override': {'strategy': sid, 'delta': delta},
    }


def _handle_default(regime: dict, signals: list, portfolio: dict) -> str:
    r       = regime.get('regime', 'unknown')
    conf    = regime.get('confidence', 0) * 100
    vix     = regime.get('india_vix', 0)
    equity  = portfolio.get('equity', 0)
    pnl     = portfolio.get('daily_pnl', 0)
    lines = [
        'Market Intelligence\n',
        f'Regime: {r.upper()}  ({conf:.0f}% confidence)',
        f'VIX:    {vix:.1f}',
    ]
    if equity:
        lines.append(f'Portfolio: ₹{equity:,.0f}  |  Day P&L: {"+" if pnl >= 0 else ""}₹{pnl:,.0f}')
    lines.append(f'Live signals: {len(signals)}')
    lines += [
        '',
        'Ask me about:',
        '  • Market regime and conditions',
        '  • Best current trade signals',
        '  • Any instrument (NIFTY, RELIANCE, VIX …)',
        '  • Portfolio and risk status',
        '  • Recent news sentiment',
        '  • Override commands:',
        '    "increase stop loss by 10%"',
        '    "reduce position size by 20%"',
        '    "overweight RSI by 15%"',
    ]
    return '\n'.join(lines)


# ── Endpoint ─────────────────────────────────────────────────────────────────

@bp.route('', methods=['POST'])
def chat():
    data    = request.get_json() or {}
    message = data.get('message', '').strip()
    if not message:
        return jsonify({'message': 'Please enter a message.', 'type': 'error'})

    msg     = message.lower()
    context = data.get('context', {})

    # Context from frontend (preferred) or server-side fallback
    signals = context.get('signals', [])
    try:
        from terminal_in.bus import bus
        regime = context.get('regime') or bus.get_cached('regime.update') or {}
    except Exception:
        regime = context.get('regime') or {}
    portfolio = context.get('portfolio') or _get_portfolio()
    news      = _get_news()

    # FinBERT on user text
    finbert = _finbert(message)

    # Route intent
    if any(k in msg for k in ('stop loss', 'stop-loss', ' sl ')):
        result = _handle_stop_override(msg, regime)
    elif any(k in msg for k in ('position size', 'position sizing', 'size by', 'reduce size', 'increase size')):
        result = _handle_size_override(msg, regime)
    elif any(k in msg for k in ('overweight', 'underweight')):
        result = _handle_strategy_weight(msg)
    else:
        # Symbol match
        sym, kw = _detect_symbol(msg)
        if sym:
            text = _handle_symbol(sym, kw, regime, signals, news)
            result = {'message': text, 'type': 'symbol_analysis'}
        elif any(k in msg for k in ('signal', 'trade', 'best trade', 'what to trade', 'opportunity', 'recommend', 'suggestion')):
            result = {'message': _handle_signals(signals, regime), 'type': 'signals'}
        elif any(k in msg for k in ('regime', 'condition', 'state', 'outlook', 'forecast', 'market')):
            result = {'message': _handle_regime(regime), 'type': 'regime'}
        elif any(k in msg for k in ('portfolio', 'position', 'pnl', 'profit', 'loss', 'drawdown', 'equity', 'risk', 'capital')):
            result = {'message': _handle_portfolio(portfolio, regime), 'type': 'portfolio'}
        elif any(k in msg for k in ('news', 'headline', 'event')):
            result = {'message': _handle_news(news), 'type': 'news'}
        else:
            result = {'message': _handle_default(regime, signals, portfolio), 'type': 'summary'}

    result['finbert'] = finbert
    return jsonify(result)


@bp.route('/overrides', methods=['GET'])
def get_overrides():
    return jsonify(_overrides)


@bp.route('/overrides', methods=['DELETE'])
def clear_overrides():
    _overrides.clear()
    try:
        from terminal_in.bus import bus
        bus.publish('config.override', {'_clear': True})
    except Exception:
        pass
    return jsonify({'status': 'cleared'})
