"""
FnOPaperBroker — lot-based paper execution for index derivatives (PRD P2, Stage 3).

Separate from the cash PaperBroker (derivatives differ in every dimension), but
runs on the SAME account: it reserves/release capital and applies realized P&L
through the injected cash broker, so the desk has one equity, not two.

Mechanics:
- Orders are LOT-based. Stored qty = lots × lot_size, entry_price = the premium,
  so the standard P&L (exit − entry) × qty × side-sign IS option premium P&L.
- F&O instruments are synthetic (no live tick on the option token), so positions
  are MARKED THEORETICALLY: on every underlying tick we recompute each option's
  Black-Scholes premium from the live spot + India VIX, check premium SL/target,
  and mark P&L. Clearly a model, never a traded price (REAL-DATA-ONLY intact —
  nothing is written to ohlcv_*; underlying ticks are the only real input).
- Long option: debit = premium × qty reserved from the shared account (that IS
  the max loss). Short option / future: a SPAN-approx margin is reserved — the
  rigorous per-contract SPAN gate lands in Stage 4; here it's a labeled estimate.
- Expiry square-off: at/after expiry the position settles at INTRINSIC value.

Persisted to the `trades` table (metadata.segment='FNO') so it survives restarts
and flows into the holdings/statement assembly unchanged.
"""

import json
import logging
import time
from datetime import datetime, timezone
from threading import Lock

from terminal_in.bus import bus
from terminal_in.agents.control import registry
from terminal_in.execution.options_pricing import bs_price, bs_greeks
from terminal_in.execution.vol_surface import skew_iv
from terminal_in.risk.span_margin import span_margin
from terminal_in.risk.event_calendar import calendar as event_cal
from terminal_in.data_ingest import fno_instruments as fno
from terminal_in.data_ingest.iv_estimator import iv_for_underlying

log = logging.getLogger(__name__)

IST = timezone(fno.IST.utcoffset(None))
VIX_TOKEN = 264969
COMMISSION = 20.0           # flat ₹20/order (entry + exit charged)
SLIPPAGE_PCT = 0.0010       # options are wider — 0.10% on the premium

# F&O-specific risk caps (the cash 30%-rule doesn't apply to derivatives).
MAX_FNO_POSITIONS  = 15     # total open derivative legs
MAX_PER_EXPIRY     = 8      # concentration in one expiry
MAX_SHORT_OPTIONS  = 6      # short-gamma exposure (short legs lose on big moves)
MAX_FNO_MARGIN_PCT = 0.50   # total F&O margin ≤ 50% of account equity

# Portfolio-level greek caps — equity-normalized so they compose across
# underlyings (a NIFTY delta and a RELIANCE delta are not in the same units, but
# their ₹-notionals are). Checked on the prospective book = open legs + new leg.
# Index lot notionals are large vs a ₹10L retail book, so the delta cap is a
# runaway-concentration backstop (directional leverage), not a per-lot limit —
# the real F&O tail risks (short-gamma, vega) are capped tightly below.
MAX_NET_DELTA_PCT   = 4.00  # |net delta notional| ≤ 400% of equity (directional)
MAX_SHORT_GAMMA_PCT = 0.05  # net short-gamma loss on a GAMMA_SHOCK gap ≤ 5% equity
MAX_NET_VEGA_PCT    = 0.02  # |net vega| (₹ per 1 vol point) ≤ 2% of equity
GAMMA_SHOCK         = 0.02  # 2% underlying gap used to price short-gamma risk


class FnOPaperBroker:
    def __init__(self, db, config, cash_broker):
        self._db = db
        self._config = config
        self._cash = cash_broker          # shared-account owner
        self._positions: dict[str, dict] = {}
        self._lock = Lock()
        self._spot: dict[int, float] = {}  # underlying_token → last spot
        self._vix: float = 14.0

        registry.register('FNO_BROKER', 'system', 'F&O Paper Broker')
        self._restore_from_db()

        bus.subscribe('ticks.*', self._on_tick)
        log.info('FnOPaperBroker initialised (open=%d)', len(self._positions))

    # ── Persistence ───────────────────────────────────────────────────────────

    def _restore_from_db(self):
        try:
            for t in self._db.get_open_trades():
                try:
                    meta = json.loads(t.get('metadata_json') or '{}')
                except Exception:
                    meta = {}
                if meta.get('segment') != 'FNO':
                    continue
                tid = t['trade_id']
                self._positions[tid] = {
                    'trade_id': tid,
                    'instrument_id': t['instrument_token'],
                    'underlying': meta.get('underlying', ''),
                    'underlying_token': int(meta.get('underlying_token') or 0),
                    'opt_type': meta.get('opt_type', 'CE'),
                    'strike': float(meta.get('strike') or 0),
                    'expiry': meta.get('expiry', ''),
                    'lot_size': int(meta.get('lot_size') or 1),
                    'lots': int(meta.get('lots') or 0),
                    'side': t['side'],
                    'quantity': t['quantity'],
                    'entry_price': t['entry_price'],
                    'stop_loss': float(t.get('stop_loss') or 0),
                    'target': float(t.get('target') or 0),
                    'margin': float(meta.get('margin') or 0),
                    'tradingsymbol': meta.get('tradingsymbol', ''),
                    'opened_at': t.get('opened_at', ''),
                }
                self._cash.reserve_capital(float(meta.get('margin') or 0))
            if self._positions:
                log.info('FnOPaperBroker: restored %d open F&O positions', len(self._positions))
        except Exception:
            log.exception('FnOPaperBroker: restore failed')

    # ── Pricing helpers ───────────────────────────────────────────────────────

    def _iv(self, label: str, underlying_token: int) -> float:
        """ATM IV anchor in DECIMAL: India VIX for indices, realized vol for stocks."""
        iv_pct, _ = iv_for_underlying(label, self._db, self._vix, underlying_token)
        return max(iv_pct, 1.0) / 100.0

    def _iv_at(self, label: str, underlying_token: int, spot: float,
               strike: float, t: float) -> float:
        """Per-strike IV: the ATM anchor adjusted by the skew surface (flat at ATM,
        and a no-op when VOL_SURFACE=false). One source of truth for the leg's IV —
        pricing, SPAN margin, and greeks all use the same value."""
        return skew_iv(self._iv(label, underlying_token), spot, strike, t)

    def _price(self, pos: dict, spot: float) -> float:
        t = fno._t_years(pos['expiry'])
        iv = self._iv_at(pos['underlying'], pos['underlying_token'], spot, pos['strike'], t)
        return bs_price(spot, pos['strike'], t, iv, pos['opt_type'])

    def _current_spot(self, underlying_token: int) -> float:
        if underlying_token in self._spot:
            return self._spot[underlying_token]
        cached = bus.get_cached(f'ticks.{underlying_token}')
        if cached and float(cached.get('last_price', 0)) > 0:
            return float(cached['last_price'])
        try:
            df = self._db.get_ohlcv_1d(underlying_token, limit=1)
            if df is not None and len(df):
                return float(df['close'].iloc[-1])
        except Exception:
            pass
        return 0.0

    # ── Order placement ───────────────────────────────────────────────────────

    def place_order(self, order: dict) -> dict:
        """order: {underlying, expiry, strike, opt_type, side, lots,
                   sl_premium?, target_premium?}. Returns a result dict."""
        label = str(order.get('underlying', '')).upper()
        opt_type = str(order.get('opt_type', 'CE')).upper()
        side = str(order.get('side', 'BUY')).upper()
        try:
            lots = int(order.get('lots', 1))
            strike = float(order.get('strike', 0))
        except (TypeError, ValueError):
            return {'ok': False, 'error': 'invalid lots/strike'}
        expiry = str(order.get('expiry', ''))

        if label not in fno._BY_LABEL:
            return {'ok': False, 'error': f'unknown underlying {label}'}
        if lots <= 0:
            return {'ok': False, 'error': 'lots must be >= 1'}
        if opt_type not in ('CE', 'PE', 'FUT'):
            return {'ok': False, 'error': 'opt_type must be CE/PE/FUT'}

        inst = fno.make_instrument(label, expiry, strike, opt_type)
        spot = self._current_spot(inst.underlying_token)
        if spot <= 0:
            return {'ok': False, 'error': 'no underlying spot — cannot price'}

        t = fno._t_years(expiry)
        iv = self._iv_at(label, inst.underlying_token, spot, strike, t)
        raw_premium = bs_price(spot, strike, t, iv, opt_type)
        # slippage against the taker
        premium = raw_premium * (1 + SLIPPAGE_PCT * (1 if side == 'BUY' else -1))
        premium = max(premium, 0.05)
        qty = lots * inst.lot_size

        # Capital to reserve: long option = the premium actually PAID (max loss,
        # slippage included); short option / future = scenario-based SPAN-approx.
        if side == 'BUY' and opt_type in ('CE', 'PE'):
            margin = round(premium * qty, 2)
            span = {'margin': margin, 'scan_loss': margin, 'exposure': 0.0}
        else:
            span = span_margin(spot, strike, t, iv, opt_type, side, qty)
            margin = span['margin']      # reserve and release the SAME value

        equity = getattr(self._cash, 'equity', 0) or 0
        leg_greeks = self._greeks_of(spot, strike, t, iv, opt_type, side, qty)
        risk_ok, risk_reason = self._risk_check(expiry, opt_type, side, margin,
                                                leg_greeks=leg_greeks, equity=equity)
        if not risk_ok:
            return {'ok': False, 'error': risk_reason}

        if not self._cash.reserve_capital(margin):
            return {'ok': False, 'error': f'insufficient capital for margin ₹{margin:,.0f}'}

        trade_id = f"FNO_{inst.tradingsymbol}_{int(time.time()*1000)}"
        pos = {
            'trade_id': trade_id,
            'instrument_id': inst.token,
            'underlying': label,
            'underlying_token': inst.underlying_token,
            'opt_type': opt_type,
            'strike': strike,
            'expiry': expiry,
            'lot_size': inst.lot_size,
            'lots': lots,
            'side': side,
            'quantity': qty,
            'entry_price': round(premium, 2),
            'stop_loss': float(order.get('sl_premium') or 0),
            'target': float(order.get('target_premium') or 0),
            'margin': margin,
            'tradingsymbol': inst.tradingsymbol,
            'opened_at': datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            self._positions[trade_id] = pos
        self._persist_open(pos)
        bus.publish('fno.trade.opened', pos)
        log.info('FNO FILL: %s %s %dx%d @%.2f (margin %.0f)',
                 side, inst.tradingsymbol, lots, inst.lot_size, premium, margin)
        return {'ok': True, 'trade_id': trade_id, 'premium': round(premium, 2),
                'qty': qty, 'margin': margin,
                'scan_loss': span['scan_loss'], 'exposure': span['exposure'],
                'margin_approx': True,
                'tradingsymbol': inst.tradingsymbol, 'theoretical': True}

    def _risk_check(self, expiry: str, opt_type: str, side: str, margin: float,
                    leg_greeks: dict | None = None, equity: float | None = None):
        """F&O-specific pre-trade caps. Returns (ok, reason).

        Count/margin caps always run. The event-day limit and portfolio greek
        caps run only when ``leg_greeks`` is supplied (the live order path) — the
        prospective book is the open legs plus this new leg.
        """
        if equity is None:
            equity = getattr(self._cash, 'equity', 0) or 0
        is_short = side == 'SELL' and opt_type in ('CE', 'PE')

        # Event-day limits: full blackout on a 0-mask event (e.g. Budget); near
        # any event (expiry Thursday / RBI / FOMC) refuse NEW short-gamma legs —
        # selling premium into a known vol event is the classic blow-up.
        if leg_greeks is not None:
            mask = event_cal.mask()
            if mask <= 0.0:
                return False, 'event blackout — no new F&O entries today'
            if mask < 1.0 and is_short:
                return False, f'event-day risk (mask {mask:.2f}) — no new short-gamma legs'

        with self._lock:
            poss = list(self._positions.values())
        if len(poss) >= MAX_FNO_POSITIONS:
            return False, f'max F&O positions ({MAX_FNO_POSITIONS}) reached'
        if sum(1 for p in poss if p['expiry'] == expiry) >= MAX_PER_EXPIRY:
            return False, f'max positions per expiry ({MAX_PER_EXPIRY}) for {expiry}'
        if is_short and sum(1 for p in poss
                            if p['side'] == 'SELL' and p['opt_type'] in ('CE', 'PE')) >= MAX_SHORT_OPTIONS:
            return False, f'max short-option (short-gamma) legs ({MAX_SHORT_OPTIONS}) reached'
        used = sum(p['margin'] for p in poss)
        if equity > 0 and (used + margin) > equity * MAX_FNO_MARGIN_PCT:
            return False, (f'F&O margin cap — would use ₹{used + margin:,.0f} '
                           f'> {MAX_FNO_MARGIN_PCT:.0%} of equity')

        # Portfolio greek caps (prospective book) — equity-normalized.
        if leg_greeks is not None and equity > 0:
            agg = self._aggregate_greeks(poss)
            net_delta = agg['delta_notional'] + leg_greeks['delta_notional']
            net_gamma = agg['gamma_pnl']      + leg_greeks['gamma_pnl']
            net_vega  = agg['vega_rupees']    + leg_greeks['vega_rupees']
            if abs(net_delta) > equity * MAX_NET_DELTA_PCT:
                return False, (f'net delta notional ₹{net_delta:,.0f} '
                               f'> {MAX_NET_DELTA_PCT:.0%} of equity')
            if net_gamma < 0 and abs(net_gamma) > equity * MAX_SHORT_GAMMA_PCT:
                return False, (f'net short-gamma loss ₹{abs(net_gamma):,.0f} on a '
                               f'{GAMMA_SHOCK:.0%} gap > {MAX_SHORT_GAMMA_PCT:.0%} of equity')
            if abs(net_vega) > equity * MAX_NET_VEGA_PCT:
                return False, (f'net vega ₹{net_vega:,.0f}/vol-pt '
                               f'> {MAX_NET_VEGA_PCT:.0%} of equity')
        return True, ''

    # ── Greeks (portfolio risk) ────────────────────────────────────────────────

    def _greeks_of(self, spot: float, strike: float, t: float, iv: float,
                   opt_type: str, side: str, qty: int) -> dict:
        """Position-level, sign-adjusted, qty-weighted greek contributions.
        delta/vega/theta are in ₹ terms; gamma is expressed as the (signed) P&L
        from a GAMMA_SHOCK underlying gap (negative = short-gamma loss)."""
        g = bs_greeks(spot, strike, t, iv, opt_type)
        sign = 1 if side == 'BUY' else -1
        return {
            'delta_units':    sign * g['delta'] * qty,
            'delta_notional': sign * g['delta'] * qty * spot,
            'gamma_pnl':      sign * 0.5 * g['gamma'] * (GAMMA_SHOCK * spot) ** 2 * qty,
            'vega_rupees':    sign * g['vega'] * qty,
            'theta_rupees':   sign * g['theta'] * qty,
        }

    def _leg_greeks(self, pos: dict, spot: float) -> dict:
        t = fno._t_years(pos['expiry'])
        iv = self._iv_at(pos['underlying'], pos['underlying_token'], spot, pos['strike'], t)
        return self._greeks_of(spot, pos['strike'], t, iv,
                               pos['opt_type'], pos['side'], pos['quantity'])

    def _aggregate_greeks(self, poss: list[dict]) -> dict:
        agg = {'delta_units': 0.0, 'delta_notional': 0.0, 'gamma_pnl': 0.0,
               'vega_rupees': 0.0, 'theta_rupees': 0.0}
        for p in poss:
            spot = self._current_spot(int(p.get('underlying_token', 0) or 0))
            if spot <= 0:
                continue
            try:
                g = self._leg_greeks(p, spot)
            except Exception:
                continue
            for k in agg:
                agg[k] += g[k]
        return agg

    def portfolio_greeks(self) -> dict:
        """Net book greeks for the UI / risk strip (theoretical, labeled)."""
        with self._lock:
            poss = list(self._positions.values())
        agg = self._aggregate_greeks(poss)
        equity = getattr(self._cash, 'equity', 0) or 0
        return {
            'net_delta':         round(agg['delta_units'], 1),
            'net_delta_notional': round(agg['delta_notional'], 0),
            'net_gamma_2pct':    round(agg['gamma_pnl'], 0),
            'net_vega':          round(agg['vega_rupees'], 0),
            'net_theta':         round(agg['theta_rupees'], 0),
            'delta_pct_equity':  round(agg['delta_notional'] / equity, 3) if equity > 0 else None,
            'theoretical': True,
        }

    def _persist_open(self, pos: dict):
        meta = {k: pos[k] for k in ('underlying', 'underlying_token', 'opt_type',
                                    'strike', 'expiry', 'lot_size', 'lots',
                                    'margin', 'tradingsymbol')}
        meta['segment'] = 'FNO'
        try:
            self._db.insert_trade({
                'trade_id': pos['trade_id'],
                'strategy_id': 'FNO',
                'instrument_token': pos['instrument_id'],
                'side': pos['side'],
                'quantity': pos['quantity'],
                'entry_price': pos['entry_price'],
                'stop_loss': pos['stop_loss'],
                'target': pos['target'],
                'opened_at': pos['opened_at'],
                'metadata': meta,
                'is_paper': True,
            })
        except Exception:
            log.exception('FnOPaperBroker: persist open failed')

    # ── Mark-to-market + exits on underlying ticks ─────────────────────────────

    def _on_tick(self, payload: dict):
        token = payload.get('instrument_token') or payload.get('token')
        price = float(payload.get('last_price', 0) or 0)
        if token is None or price <= 0:
            return
        if int(token) == VIX_TOKEN:
            self._vix = price
            return
        self._spot[int(token)] = price

        to_close = []
        now = datetime.now(IST)
        with self._lock:
            for tid, pos in list(self._positions.items()):
                if pos['underlying_token'] != int(token):
                    continue
                # expiry square-off (settle at intrinsic)
                try:
                    exp = datetime.fromisoformat(pos['expiry']).replace(
                        tzinfo=IST, hour=15, minute=30)
                    if now >= exp:
                        intrinsic = self._intrinsic(pos, price)
                        to_close.append((tid, pos.copy(), intrinsic, 'expiry'))
                        continue
                except Exception:
                    pass
                prem = self._price(pos, price)
                reason = self._check_exit(pos, prem)
                if reason:
                    to_close.append((tid, pos.copy(), prem, reason))

        for tid, pos, exit_prem, reason in to_close:
            self._close(tid, pos, exit_prem, reason)

    def _intrinsic(self, pos: dict, spot: float) -> float:
        if pos['opt_type'] == 'CE':
            return max(0.0, spot - pos['strike'])
        if pos['opt_type'] == 'PE':
            return max(0.0, pos['strike'] - spot)
        return spot  # FUT settles at spot

    def _check_exit(self, pos: dict, premium: float):
        sl, tgt = pos['stop_loss'], pos['target']
        if pos['side'] == 'BUY':      # long: stop below, target above (premium)
            if sl > 0 and premium <= sl:
                return 'stop_loss'
            if tgt > 0 and premium >= tgt:
                return 'target'
        else:                          # short: stop above, target below
            if sl > 0 and premium >= sl:
                return 'stop_loss'
            if tgt > 0 and premium <= tgt:
                return 'target'
        return None

    # ── Close ──────────────────────────────────────────────────────────────────

    def close_position(self, trade_id: str, reason: str = 'manual') -> dict:
        with self._lock:
            pos = self._positions.get(trade_id)
        if not pos:
            return {'ok': False, 'error': 'unknown trade_id'}
        spot = self._current_spot(pos['underlying_token'])
        prem = self._price(pos, spot) if spot > 0 else pos['entry_price']
        self._close(trade_id, pos.copy(), prem, reason)
        return {'ok': True}

    def _close(self, trade_id: str, pos: dict, exit_premium: float, reason: str):
        with self._lock:
            if trade_id not in self._positions:
                return
            self._positions.pop(trade_id, None)
        self._cash.release_capital(pos['margin'])

        slip = exit_premium * SLIPPAGE_PCT * (-1 if pos['side'] == 'BUY' else 1)
        fill = max(exit_premium + slip, 0.0)
        sign = 1 if pos['side'] == 'BUY' else -1
        gross = sign * (fill - pos['entry_price']) * pos['quantity']
        net = gross - COMMISSION * 2
        self._cash.apply_external_pnl(net)

        closed_at = datetime.now(timezone.utc).isoformat()
        try:
            self._db.close_trade(trade_id, {
                'exit_price': round(fill, 2), 'pnl': net,
                'exit_reason': reason, 'closed_at': closed_at,
                'costs': COMMISSION * 2,
            })
        except Exception:
            log.exception('FnOPaperBroker: persist close failed')

        bus.publish('fno.trade.closed', {**pos, 'exit_price': round(fill, 2),
                                          'pnl': round(net, 2), 'exit_reason': reason})
        log.info('FNO CLOSE: %s reason=%s pnl=%.2f', pos['tradingsymbol'], reason, net)

    # ── Read API ───────────────────────────────────────────────────────────────

    def positions(self) -> list[dict]:
        out = []
        with self._lock:
            poss = list(self._positions.values())
        for pos in poss:
            spot = self._current_spot(pos['underlying_token'])
            mark = self._price(pos, spot) if spot > 0 else pos['entry_price']
            sign = 1 if pos['side'] == 'BUY' else -1
            upnl = sign * (mark - pos['entry_price']) * pos['quantity']
            g = self._leg_greeks(pos, spot) if spot > 0 else {
                'delta_units': 0.0, 'theta_rupees': 0.0, 'vega_rupees': 0.0, 'gamma_pnl': 0.0}
            out.append({**pos, 'mark': round(mark, 2),
                        'unrealized': round(upnl, 2), 'spot': round(spot, 2),
                        'delta': round(g['delta_units'], 1),
                        'theta': round(g['theta_rupees'], 0),
                        'vega': round(g['vega_rupees'], 0),
                        'gamma_2pct': round(g['gamma_pnl'], 0),
                        'theoretical': True})
        return out

    @property
    def open_positions(self) -> list[dict]:
        return self.positions()
