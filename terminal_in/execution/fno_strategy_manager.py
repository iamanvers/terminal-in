"""
FnOStrategyManager — fires the multi-leg F&O strategies on a periodic scan.

Strategies (all eval-gated CAPABILITIES, conservative + capped — not tuned alpha):
  - Variance harvest  : range-bound regime + a harvestable VIX band → iron condor
                        on NIFTY (defined-risk short-vol; harvests the variance
                        risk premium the literature documents for index options).
  - Futures pair      : a cointegrated stock pair diverges (|z|>=2) → long the
                        cheap leg / short the rich leg, BOTH in single-stock
                        FUTURES (a cash short can't carry overnight).
  - Covered call      : a held cash long in an F&O name → sell an OTM call against
                        it (income; the 'cover' is the equity position).
  - Event straddle    : a scheduled event is imminent → long ATM straddle (bets on
                        vol EXPANSION, orthogonal to direction; defined risk).

The manager only decides WHEN. Every structure is placed atomically through
fno_broker.place_combo, which runs the combo-level risk caps (net greeks / margin /
event blackout) and decides IF it's safe. Dedupe is reconciled from the live book
each scan (survives restarts): one structure of each kind per underlying at a time.

Toggle per kind via env FNO_HARVEST/FNO_PAIR/FNO_COVERED_CALL/FNO_EVENT_STRADDLE
(all default ON in paper); FNO_MANAGER_INTERVAL_S sets the cadence (default 300s).
"""

import logging
import os
from itertools import combinations

import numpy as np

from terminal_in.bus import bus
from terminal_in.agents.control import kill_switch, trading_mode
from terminal_in.market_hours import is_market_open
from terminal_in.data_ingest import fno_instruments as fno
from terminal_in.data_ingest.contract_specs import STOCK_FNO_LOTS
from terminal_in.execution import fno_strategies as strats
from terminal_in.risk.event_calendar import calendar as event_cal

log = logging.getLogger(__name__)

NIFTY_TOKEN = 256265
VIX_HARVEST_LO = 12.0     # below this, no premium worth the tail
VIX_HARVEST_HI = 22.0     # above this, vol stress — don't sell into it
COINT_LOOKBACK = 60
Z_ENTRY = 2.0
PAIR_MAX_CANDIDATES = 12


# ── pure triggers (unit-testable) ────────────────────────────────────────────────

def variance_harvest_due(regime: str, vix: float, has_condor: bool,
                         lo: float = VIX_HARVEST_LO, hi: float = VIX_HARVEST_HI) -> bool:
    """Harvest the variance premium only in calm, RANGE-BOUND tape with VIX in a
    sane band, and never stack a second condor."""
    return (not has_condor) and regime in ('sideways',) and lo <= float(vix) <= hi


def cointegration_z(close_a: np.ndarray, close_b: np.ndarray,
                    lookback: int = COINT_LOOKBACK) -> float | None:
    """Spread z-score of A vs beta·B over the lookback (S6 math). None if too short."""
    a = np.asarray(close_a, float)
    b = np.asarray(close_b, float)
    n = min(len(a), len(b))
    if n < max(20, lookback // 3):
        return None
    a, b = a[-min(n, lookback):], b[-min(n, lookback):]
    beta = np.polyfit(b, a, 1)[0]
    spread = a - beta * b
    sd = float(np.std(spread))
    if sd < 1e-8:
        return None
    return (spread[-1] - float(np.mean(spread))) / sd


def event_straddle_due(mask: float, has_straddle: bool) -> bool:
    """A scheduled event is near (0 < mask < 1) but not a full blackout (mask==0).
    Long vol into the event; defined risk, so allowed even on event days."""
    return (not has_straddle) and 0.0 < float(mask) < 1.0


def covered_call_candidates(holdings: list, fno_names: set, lot_sizes: dict) -> list:
    """Held cash LONGS in F&O names with >= 1 lot of size — eligible to write a call
    against. Returns [(symbol, lots)]."""
    out = []
    for h in holdings:
        sym = h.get('symbol') or h.get('underlying')
        if not sym or sym not in fno_names or str(h.get('side', 'BUY')).upper() != 'BUY':
            continue
        lot = int(lot_sizes.get(sym, 0) or 0)
        qty = int(h.get('quantity', 0) or 0)
        if lot > 0 and qty >= lot:
            out.append((sym, qty // lot))
    return out


class FnOStrategyManager:
    def __init__(self, db, fno_broker, cash_broker, config=None):
        self._db = db
        self._fno = fno_broker
        self._cash = cash_broker
        self._config = config
        self._fired = 0
        log.info('FnOStrategyManager initialised')

    # — env toggles —
    @staticmethod
    def _on(name: str) -> bool:
        return os.environ.get(name, 'true').lower() in ('1', 'true', 'yes')

    def _interval(self) -> int:
        try:
            return max(60, int(os.environ.get('FNO_MANAGER_INTERVAL_S', '300')))
        except ValueError:
            return 300

    # — book reconciliation (dedupe survives restarts) —
    def _book(self) -> list:
        try:
            return self._fno.positions()
        except Exception:
            return []

    def _has_nifty_condor(self, book) -> bool:
        # a short NIFTY option leg ⇒ a short-vol structure is already on
        return any(p.get('underlying') == 'NIFTY' and p.get('side') == 'SELL'
                   and p.get('opt_type') in ('CE', 'PE') for p in book)

    def _has_fut_pair(self, book) -> bool:
        return any(p.get('opt_type') == 'FUT' for p in book)

    def _has_nifty_straddle(self, book) -> bool:
        longs = [p for p in book if p.get('underlying') == 'NIFTY' and p.get('side') == 'BUY']
        return any(p['opt_type'] == 'CE' for p in longs) and any(p['opt_type'] == 'PE' for p in longs)

    def _short_call_symbols(self, book) -> set:
        return {p.get('underlying') for p in book
                if p.get('side') == 'SELL' and p.get('opt_type') == 'CE'}

    def _regime_vix(self) -> tuple[str, float]:
        r = bus.get_cached('regime.update') or {}
        return str(r.get('regime', 'sideways')), float(r.get('india_vix', self._fno._vix or 14.0))

    # ── the scan ─────────────────────────────────────────────────────────────────

    def scan(self) -> dict:
        """One pass over all enabled F&O strategies. Returns a summary dict."""
        if not (is_market_open() and trading_mode.auto_trade and not kill_switch.global_pause):
            return {'skipped': 'gate'}
        book = self._book()
        regime, vix = self._regime_vix()
        fired = {}

        if self._on('FNO_HARVEST') and variance_harvest_due(regime, vix, self._has_nifty_condor(book)):
            fired['iron_condor'] = self._fire_condor()
        if self._on('FNO_PAIR') and not self._has_fut_pair(book):
            fired['futures_pair'] = self._fire_pair()
        if self._on('FNO_EVENT_STRADDLE') and event_straddle_due(event_cal.mask(), self._has_nifty_straddle(book)):
            fired['event_straddle'] = self._fire_straddle()
        if self._on('FNO_COVERED_CALL'):
            fired['covered_call'] = self._fire_covered_calls(book)

        fired = {k: v for k, v in fired.items() if v}
        if fired:
            self._fired += 1
        return {'regime': regime, 'vix': round(vix, 2), 'fired': fired}

    # ── firers ───────────────────────────────────────────────────────────────────

    def _near_expiry(self, label: str) -> str | None:
        exps = fno.expiries(label)
        return exps[0]['date'] if exps else None

    def _fire_condor(self):
        spot = self._fno._current_spot(NIFTY_TOKEN)
        expiry = self._near_expiry('NIFTY')
        if spot <= 0 or not expiry:
            return None
        legs = strats.iron_condor_legs('NIFTY', spot, expiry, body=3, wing=2, lots=1)
        r = self._fno.place_combo(legs, {'kind': 'iron_condor'})
        return r.get('combo_id') if r.get('ok') else None

    def _fire_straddle(self):
        spot = self._fno._current_spot(NIFTY_TOKEN)
        expiry = self._near_expiry('NIFTY')
        if spot <= 0 or not expiry:
            return None
        legs = strats.straddle_legs('NIFTY', spot, expiry, lots=1, side='BUY')
        r = self._fno.place_combo(legs, {'kind': 'event_straddle'})
        return r.get('combo_id') if r.get('ok') else None

    def _fire_pair(self):
        names = [s for s in STOCK_FNO_LOTS if fno._BY_LABEL.get(s)]
        tok = {s: fno._BY_LABEL[s]['token'] for s in names}
        closes = {}
        for s in names:
            try:
                df = self._db.get_ohlcv_1d(tok[s], limit=COINT_LOOKBACK + 5)
                if df is not None and len(df) >= 20:
                    closes[s] = df['close'].values.astype(float)
            except Exception:
                continue
        cand = [p for p in combinations(sorted(closes), 2)][:PAIR_MAX_CANDIDATES]
        for a, b in cand:
            z = cointegration_z(closes[a], closes[b])
            if z is None or abs(z) < Z_ENTRY:
                continue
            long_sym, short_sym = (b, a) if z > 0 else (a, b)   # long cheap, short rich
            expiry = self._near_expiry(long_sym)
            if not expiry:
                continue
            legs = strats.futures_pair_legs(long_sym, short_sym, expiry, 1, 1)
            r = self._fno.place_combo(legs, {'kind': 'futures_pair',
                                             'z': round(float(z), 2),
                                             'pair': f'{long_sym}/{short_sym}'})
            if r.get('ok'):
                return r.get('combo_id')
        return None

    def _fire_covered_calls(self, book):
        holdings = []
        try:
            holdings = self._cash.open_positions
        except Exception:
            pass
        fno_names = set(STOCK_FNO_LOTS)
        already = self._short_call_symbols(book)
        fired = []
        for sym, _lots in covered_call_candidates(holdings, fno_names, STOCK_FNO_LOTS):
            if sym in already:
                continue
            spot = self._fno._current_spot(fno._BY_LABEL[sym]['token'])
            expiry = self._near_expiry(sym)
            if spot <= 0 or not expiry:
                continue
            legs = strats.covered_call_legs(sym, spot, expiry, otm=3, lots=1)
            r = self._fno.place_combo(legs, {'kind': 'covered_call', 'symbol': sym})
            if r.get('ok'):
                fired.append(r.get('combo_id'))
        return fired or None

    # ── loop ───────────────────────────────────────────────────────────────────

    def run(self, stop_event):
        log.info('FnOStrategyManager loop started (interval=%ds)', self._interval())
        # let the feeds/regime warm up before the first pass
        stop_event.wait(timeout=45)
        while not stop_event.is_set():
            try:
                out = self.scan()
                if out.get('fired'):
                    log.info('FnOStrategyManager fired: %s', out['fired'])
            except Exception:
                log.exception('FnOStrategyManager scan error')
            stop_event.wait(timeout=self._interval())
        log.info('FnOStrategyManager loop stopped')
