"""
KiteBroker — live order execution via Kite Connect.
Subscribes to 'order.approved', places orders on Zerodha,
handles postbacks via polling, publishes 'trade.opened' / 'trade.closed'.
"""

import logging
import time
from datetime import datetime, timezone
from threading import Lock, Thread
from typing import Optional

from terminal_in.bus import bus

log = logging.getLogger(__name__)

POLL_INTERVAL_S = 5
ORDER_VALIDITY = 'DAY'


class KiteBroker:
    def __init__(self, kite, db, config):
        self._kite = kite
        self._db = db
        self._config = config
        self._pending: dict[str, dict] = {}   # order_id → signal payload
        self._open: dict[str, dict] = {}      # order_id → trade record
        self._lock = Lock()
        self._stop = False
        self._equity = config.initial_capital

        bus.subscribe('order.approved', self._on_order)
        self._poller_thread = Thread(target=self._poll_loop, daemon=True, name='kite-poller')
        self._poller_thread.start()
        log.info('KiteBroker initialised (live mode)')

    def _on_order(self, payload: dict):
        side = payload.get('side', 'BUY')
        instrument_id = int(payload.get('instrument_id', 0))
        qty = int(payload.get('quantity', 0))
        if qty <= 0:
            return

        order_type = payload.get('order_type', 'MARKET')
        limit_price = payload.get('limit_price')
        trigger_price = payload.get('stop_loss') if order_type in ('SL', 'SL-M') else None

        kite_params = dict(
            tradingsymbol=self._token_to_symbol(instrument_id),
            exchange='NSE',
            transaction_type=side,
            quantity=qty,
            order_type=order_type,
            product='MIS',
            validity=ORDER_VALIDITY,
        )
        if limit_price and order_type in ('LIMIT', 'SL'):
            kite_params['price'] = float(limit_price)
        if trigger_price and order_type in ('SL', 'SL-M'):
            kite_params['trigger_price'] = float(trigger_price)

        try:
            order_id = self._kite.place_order(
                variety=self._kite.VARIETY_REGULAR,
                **kite_params,
            )
            log.info('KiteBroker order placed: %s %s qty=%d order_id=%s',
                     side, kite_params['tradingsymbol'], qty, order_id)
            with self._lock:
                self._pending[str(order_id)] = payload
        except Exception:
            log.exception('KiteBroker: order placement failed for instrument %d', instrument_id)

    def _token_to_symbol(self, token: int) -> str:
        from terminal_in.data_ingest.instruments import registry
        sym = registry.symbol(token)
        return sym.replace(' ', '') if sym else str(token)

    def _poll_loop(self):
        while not self._stop:
            try:
                self._check_orders()
            except Exception:
                log.exception('KiteBroker poll error')
            time.sleep(POLL_INTERVAL_S)

    def _check_orders(self):
        with self._lock:
            if not self._pending and not self._open:
                return

        try:
            orders = self._kite.orders()
        except Exception:
            log.exception('Failed to fetch Kite orders')
            return

        for order in orders:
            oid = str(order['order_id'])
            status = order.get('status', '')

            if oid in self._pending and status == 'COMPLETE':
                payload = self._pending.pop(oid)
                fill_price = float(order.get('average_price', 0))
                trade = self._build_trade(oid, payload, fill_price, order)
                with self._lock:
                    self._open[oid] = trade
                try:
                    self._db.insert_trade({**trade, 'status': 'open'})
                except Exception:
                    log.exception('Failed to persist Kite trade open')
                bus.publish('trade.opened', trade)
                log.info('KiteBroker trade opened: %s @%.2f', oid, fill_price)

            elif oid in self._pending and status in ('REJECTED', 'CANCELLED'):
                payload = self._pending.pop(oid)
                log.warning('KiteBroker order %s %s', oid, status)
                bus.publish('order.rejected', {
                    **payload,
                    'reason': f'kite_{status.lower()}',
                    'kite_message': order.get('status_message', ''),
                })

        # Check for SL/target hit on open positions via order book
        positions_raw = []
        try:
            positions_raw = self._kite.positions().get('net', [])
        except Exception:
            pass

        for pos in positions_raw:
            if pos.get('quantity', 0) == 0:
                # Position closed — find matching open order
                sym = pos.get('tradingsymbol', '')
                for oid, trade in list(self._open.items()):
                    if self._token_to_symbol(trade['instrument_id']) == sym:
                        pnl = float(pos.get('pnl', 0))
                        self._handle_position_close(oid, trade, pnl)

    def _build_trade(self, order_id: str, payload: dict, fill_price: float, order: dict) -> dict:
        return {
            'trade_id': order_id,
            'strategy_id': payload.get('strategy_id', ''),
            'instrument_id': int(payload.get('instrument_id', 0)),
            'side': payload.get('side', 'BUY'),
            'quantity': int(order.get('filled_quantity', payload.get('quantity', 0))),
            'entry_price': fill_price,
            'stop_loss': float(payload.get('stop_loss', 0)),
            'target': float(payload.get('target', 0)),
            'time_exit': payload.get('time_exit'),
            'opened_at': datetime.now(timezone.utc).isoformat(),
            'regime': payload.get('regime', ''),
            'metadata': payload.get('metadata', {}),
        }

    def _handle_position_close(self, order_id: str, trade: dict, pnl: float):
        with self._lock:
            self._open.pop(order_id, None)

        closed = {
            **trade,
            'pnl': pnl,
            'exit_reason': 'kite_position_closed',
            'closed_at': datetime.now(timezone.utc).isoformat(),
        }
        try:
            self._db.close_trade(order_id, {
                'pnl': pnl,
                'exit_reason': 'kite_position_closed',
                'closed_at': closed['closed_at'],
            })
        except Exception:
            log.exception('Failed to persist Kite trade close')

        self._equity += pnl
        bus.publish('trade.closed', closed)
        bus.publish('pnl.update', {'equity': self._equity})

    def stop(self):
        self._stop = True

    @property
    def equity(self) -> float:
        return self._equity
