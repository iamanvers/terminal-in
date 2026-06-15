"""
Live-mode option chain from the Kite F&O feed (PRD P2 — final F&O item).

DATA HONESTY: this is the REAL options tape. Premiums are Kite LTP (last traded
price), OI and volume are the exchange's real numbers, and IV is *implied from the
real LTP* via Black-Scholes inversion (a derived-from-real quantity, never a guess)
— so chains built here are labeled `theoretical=False`. When a strike has no
traded price the premium/IV/greeks for that leg are null (we never fabricate a
quote to fill the grid). This module is ONLY constructed in live mode with a real
Kite client; paper mode keeps the Black-Scholes theoretical chain in
fno_instruments.build_chain(). The two share the same output shape so the /fno
chain UI and the SPAN/greek gate consume either transparently.

The NFO instrument dump (~50k contracts) is fetched once per trading day and
cached; quotes are pulled per-request for only the strikes in view.
"""

import logging
from datetime import date, datetime, timedelta, timezone

from terminal_in.data_ingest import fno_instruments as fno
from terminal_in.execution.options_pricing import bs_greeks, implied_vol

log = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))


def _exp_iso(e) -> str:
    """Kite expiries come back as date/datetime (or str); normalise to ISO date."""
    if isinstance(e, (date, datetime)):
        return e.date().isoformat() if isinstance(e, datetime) else e.isoformat()
    return str(e)[:10]


class LiveChain:
    def __init__(self, kite):
        self._kite = kite
        self._nfo: list[dict] | None = None
        self._nfo_date: date | None = None

    # ── NFO instrument dump (cached per trading day) ─────────────────────────
    def _instruments(self) -> list[dict]:
        today = datetime.now(IST).date()
        if self._nfo is None or self._nfo_date != today:
            log.info('LiveChain: fetching NFO instrument dump from Kite')
            self._nfo = self._kite.instruments('NFO')
            self._nfo_date = today
        return self._nfo

    def _options_for(self, label: str) -> list[dict]:
        return [i for i in self._instruments()
                if i.get('name') == label and i.get('instrument_type') in ('CE', 'PE')]

    # ── Real expiries from the dump (same shape as fno.expiries) ─────────────
    def expiries(self, label: str) -> list[dict]:
        today = datetime.now(IST).date()
        exps = sorted({_exp_iso(i['expiry']) for i in self._options_for(label)})
        exps = [e for e in exps if e >= today.isoformat()]
        # tag monthly = last expiry of its month, else weekly (display only)
        by_month: dict[str, str] = {}
        for e in exps:
            by_month[e[:7]] = max(by_month.get(e[:7], ''), e)
        return [{'date': e, 'kind': 'monthly' if by_month.get(e[:7]) == e else 'weekly'}
                for e in exps]

    # ── The real chain ───────────────────────────────────────────────────────
    def build_chain(self, label: str, spot: float, expiry_iso: str,
                    n_strikes: int = 10, now: datetime | None = None) -> dict:
        opts = [i for i in self._options_for(label) if _exp_iso(i['expiry']) == expiry_iso]
        if not opts:
            raise ValueError(f'no live {label} contracts for expiry {expiry_iso}')

        lot_size = int(opts[0].get('lot_size') or fno._BY_LABEL.get(label, {}).get('lot_size', 0))
        strikes = sorted({float(i['strike']) for i in opts if float(i['strike']) > 0})
        atm = min(strikes, key=lambda s: abs(s - spot))
        ai = strikes.index(atm)
        window = strikes[max(0, ai - n_strikes): ai + n_strikes + 1]
        step = (window[1] - window[0]) if len(window) > 1 else 0

        # index the CE/PE instrument per strike
        leg: dict[tuple, dict] = {(float(i['strike']), i['instrument_type']): i for i in opts}
        idents = [f"NFO:{i['tradingsymbol']}" for s in window
                  for i in (leg.get((s, 'CE')), leg.get((s, 'PE'))) if i]
        try:
            quotes = self._kite.quote(idents) if idents else {}
        except Exception as e:
            raise RuntimeError(f'Kite quote() failed: {str(e)[:120]}')

        t = fno._t_years(expiry_iso, now)

        def build_leg(strike: float, opt_type: str) -> dict | None:
            inst = leg.get((strike, opt_type))
            if inst is None:
                return None
            q = quotes.get(f"NFO:{inst['tradingsymbol']}", {}) or {}
            ltp = q.get('last_price')
            oi = q.get('oi')
            vol = (q.get('volume') if 'volume' in q else (q.get('volume_traded')))
            out = {'token': int(inst['instrument_token']),
                   'tradingsymbol': inst['tradingsymbol'],
                   'premium': round(float(ltp), 2) if ltp else None,
                   'oi': int(oi) if oi is not None else None,
                   'volume': int(vol) if vol is not None else None,
                   'iv_real': None, 'delta': None, 'gamma': None,
                   'theta': None, 'vega': None, 'theoretical': False}
            if ltp and float(ltp) > 0:
                iv = implied_vol(float(ltp), spot, strike, t, opt_type)
                if iv is not None:
                    g = bs_greeks(spot, strike, t, iv, opt_type)
                    out.update(iv_real=round(iv * 100, 2),
                               delta=round(g['delta'], 4), gamma=round(g['gamma'], 6),
                               theta=round(g['theta'], 3), vega=round(g['vega'], 3))
            return out

        rows = []
        for strike in window:
            ce, pe = build_leg(strike, 'CE'), build_leg(strike, 'PE')
            rows.append({
                'strike': strike, 'is_atm': strike == atm,
                'moneyness': 'ATM' if strike == atm else ('ITM' if strike < spot else 'OTM'),
                'CE': ce or {}, 'PE': pe or {},
                'oi': (ce or {}).get('oi'), 'iv_real': (ce or {}).get('iv_real'),
                'volume': (ce or {}).get('volume'),
            })

        atm_ce = next((r['CE'] for r in rows if r['is_atm']), {})
        return {
            'underlying': label,
            'underlying_symbol': fno._BY_LABEL.get(label, {}).get('symbol', label),
            'spot': round(spot, 2), 'atm_strike': atm, 'expiry': expiry_iso,
            't_years': round(t, 5),
            'iv_used_pct': atm_ce.get('iv_real'),
            'iv_source': 'live (implied from Kite LTP)',
            'lot_size': lot_size, 'strike_interval': step, 'rows': rows,
            'theoretical': False, 'source': 'kite_live',
            'note': 'Live Kite chain — premiums are LTP, OI/volume are real, IV is '
                    'implied from the LTP. Strikes with no trade show null premium/IV.',
        }
