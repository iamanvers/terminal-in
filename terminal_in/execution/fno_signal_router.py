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

from terminal_in.bus import bus
from terminal_in.agents.control import kill_switch
from terminal_in.market_hours import is_market_open
from terminal_in.data_ingest import fno_instruments as fno

log = logging.getLogger(__name__)

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
        if not is_market_open():
            log.debug('FnO route skipped — market closed (%s %s)', strat, label)
            return
        if kill_switch.global_pause:
            log.info('FnO route skipped — kill switch engaged (%s %s)', strat, label)
            return

        side = str(sig.get('side', 'BUY')).upper()
        opt_type = 'CE' if side == 'BUY' else 'PE'   # bullish→call, bearish→put

        exps = fno.expiries(label)
        if not exps:
            return
        expiry = exps[0]['date']                    # nearest expiry
        spot = self._fno._current_spot(
            next(c['token'] for c in fno.INDEX_CONTRACTS if c['label'] == label))
        if spot <= 0:
            log.warning('FnO route: no spot for %s', label)
            return
        strike = fno.atm_strike(label, spot)

        meta = sig.get('metadata') or {}
        try:
            lots = max(1, int(meta.get('fno_lots', 1)))
        except (TypeError, ValueError):
            lots = 1

        result = self._fno.place_order({
            'underlying': label, 'expiry': expiry, 'strike': strike,
            'opt_type': opt_type, 'side': 'BUY', 'lots': lots,
        })
        if result.get('ok'):
            self._routed += 1
            log.info('FnO ROUTE [%s]: %s %s → BUY %d×%s @%.2f',
                     strat, side, label, lots, result['tradingsymbol'], result['premium'])
            bus.publish('fno.signal.routed', {
                'strategy_id': strat, 'underlying': label, 'index_side': side,
                'expressed_as': f"BUY {opt_type}", 'strike': strike,
                'tradingsymbol': result['tradingsymbol'], 'premium': result['premium'],
                'lots': lots, 'margin': result['margin'],
            })
        else:
            log.info('FnO ROUTE rejected [%s %s]: %s', strat, label, result.get('error'))

    @property
    def routed_count(self) -> int:
        return self._routed
