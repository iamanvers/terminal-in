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
from terminal_in.execution.options_pricing import bs_price
from terminal_in.risk.span_margin import span_margin
from terminal_in.data_ingest import fno_instruments as fno

log = logging.getLogger(__name__)

IST = timezone(fno.IST.utcoffset(None))
VIX_TOKEN = 264969
COMMISSION = 20.0           # flat ₹20/order (entry + exit charged)
SLIPPAGE_PCT = 0.0010       # options are wider — 0.10% on the premium


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

    def _price(self, pos: dict, spot: float) -> float:
        t = fno._t_years(pos['expiry'])
        return bs_price(spot, pos['strike'], t, max(self._vix, 1.0) / 100.0, pos['opt_type'])

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
        raw_premium = bs_price(spot, strike, t, max(self._vix, 1.0) / 100.0, opt_type)
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
            span = span_margin(spot, strike, t, max(self._vix, 1.0) / 100.0,
                               opt_type, side, qty)
            margin = span['margin']      # reserve and release the SAME value

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
            out.append({**pos, 'mark': round(mark, 2),
                        'unrealized': round(upnl, 2), 'spot': round(spot, 2),
                        'theoretical': True})
        return out

    @property
    def open_positions(self) -> list[dict]:
        return self.positions()
