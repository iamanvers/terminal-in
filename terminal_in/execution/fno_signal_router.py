"""
FnOSignalRouter — express index strategy signals as real derivatives (PRD P2, Stage 5).

S1 (ORB) and S8 (VIX fade) fire on index underlyings (NIFTY/BANKNIFTY/FINNIFTY),
which are NON_TRADEABLE in the cash gate — so today they are rejected and never
trade. This router intercepts those index directional signals and expresses them
as defined-risk options on the F&O paper broker:

    BUY  index  →  buy ATM CALL   (bullish, max loss = premium)
    SELL index  →  buy ATM PUT    (bearish, max loss = premium)

Long ATM options (not short premium / futures) are chosen deliberately: capped
risk, no SPAN surprise, and they carry the directional view the lens intended.
The cash gate still rejects the raw-index signal (harmless, logged); this is a
parallel, opt-in F&O path with its own light risk checks (market hours + kill
switch). Cash equity signals are untouched.

Config: `fno_route_index_signals` (default on in paper). Eligible strategies =
FNO_STRATEGIES. Lots default 1, overridable via signal metadata 'fno_lots'.
"""

import logging
import os

from terminal_in.bus import bus
from terminal_in.agents.control import kill_switch, trading_mode
from terminal_in.market_hours import is_market_open
from terminal_in.data_ingest import fno_instruments as fno
from terminal_in.execution import fno_strategies as fno_strats

log = logging.getLogger(__name__)


def _directional_structure() -> str:
    """'spread' (risk-defined debit vertical, default) or 'option' (naked ATM long).
    A debit spread caps premium bleed by selling the far leg; the legacy naked
    long is still available via FNO_DIRECTIONAL_STRUCTURE=option."""
    return os.environ.get('FNO_DIRECTIONAL_STRUCTURE', 'spread').lower()


def _spread_width() -> int:
    try:
        return max(1, int(os.environ.get('FNO_SPREAD_WIDTH', '2')))
    except ValueError:
        return 2

# Index underlying token → F&O label (only these are routed).
UNDERLYING_BY_TOKEN = {c['token']: c['label'] for c in fno.INDEX_CONTRACTS}

# Strategies whose index signals migrate to derivatives (PRD names S1 + S8).
FNO_STRATEGIES = frozenset({'S1', 'S8'})


class FnOSignalRouter:
    def __init__(self, fno_broker, config=None):
        self._fno = fno_broker
        self._config = config
        self._routed = 0
        bus.subscribe('strategy.signal', self._on_signal)
        log.info('FnOSignalRouter initialised (strategies=%s)', sorted(FNO_STRATEGIES))

    def _on_signal(self, sig: dict):
        token = int(sig.get('instrument_id') or sig.get('instrument_token') or 0)
        label = UNDERLYING_BY_TOKEN.get(token)
        if label is None:
            return                                  # not an index underlying
        strat = str(sig.get('strategy_id') or '')
        if strat not in FNO_STRATEGIES:
            return                                  # not a derivative-eligible lens

        # Light risk discipline (the cash gate never sees a tradeable order here).
        if not trading_mode.auto_trade:
            log.debug('FnO route skipped — auto-trade off (%s %s)', strat, label)
            return
        if not is_market_open():
            log.debug('FnO route skipped — market closed (%s %s)', strat, label)
            return
        if kill_switch.global_pause:
            log.info('FnO route skipped — kill switch engaged (%s %s)', strat, label)
            return

        side = str(sig.get('side', 'BUY')).upper()

        exps = fno.expiries(label)
        if not exps:
            return
        expiry = exps[0]['date']                    # nearest expiry
        spot = self._fno._current_spot(
            next(c['token'] for c in fno.INDEX_CONTRACTS if c['label'] == label))
        if spot <= 0:
            log.warning('FnO route: no spot for %s', label)
            return

        meta = sig.get('metadata') or {}
        try:
            lots = max(1, int(meta.get('fno_lots', 1)))
        except (TypeError, ValueError):
            lots = 1

        # Express the directional view as a risk-DEFINED debit spread (default) or
        # a naked ATM long option (legacy). Both carry the lens's direction.
        if _directional_structure() == 'spread':
            direction = 'BULL' if side == 'BUY' else 'BEAR'
            legs = fno_strats.vertical_spread_legs(label, spot, expiry, direction,
                                                   width=_spread_width(), lots=lots)
            result = self._fno.place_combo(legs, {'kind': f'{direction.lower()}_spread',
                                                  'strategy_id': strat})
            expressed = f"{direction} {'call' if side == 'BUY' else 'put'} spread"
        else:
            opt_type = 'CE' if side == 'BUY' else 'PE'   # bullish→call, bearish→put
            result = self._fno.place_order({
                'underlying': label, 'expiry': expiry, 'strike': fno.atm_strike(label, spot),
                'opt_type': opt_type, 'side': 'BUY', 'lots': lots,
            })
            expressed = f"BUY {opt_type}"

        if result.get('ok'):
            self._routed += 1
            log.info('FnO ROUTE [%s]: %s %s → %s (%d lots, margin %.0f)',
                     strat, side, label, expressed, lots, result.get('margin', 0))
            bus.publish('fno.signal.routed', {
                'strategy_id': strat, 'underlying': label, 'index_side': side,
                'expressed_as': expressed, 'lots': lots, 'margin': result.get('margin', 0),
                'combo_id': result.get('combo_id'), 'tradingsymbol': result.get('tradingsymbol'),
                'premium': result.get('premium'),
            })
        else:
            log.info('FnO ROUTE rejected [%s %s]: %s', strat, label, result.get('error'))

    @property
    def routed_count(self) -> int:
        return self._routed
