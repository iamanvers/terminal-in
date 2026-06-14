"""
F&O instrument model + option-chain builder (PRD P2 — F&O execution).

Derivatives get their OWN instrument model, separate from the cash universe:
lot-based, expiry-dated, strike-keyed. This module turns the sourced contract
specs (contract_specs.py) + a REAL underlying spot + REAL India VIX into a
deterministic option chain whose premiums/greeks are THEORETICAL (Black-Scholes,
see options_pricing.py) and labeled as such — never traded prices.

In live mode this is replaced/enriched by the Kite instruments dump (real tokens,
OI, IV, LTP). Paper mode builds the chain analytically so the full execution
pipeline (chain → lot fills → expiry square-off → SPAN gate) is exercisable
without a live options feed, without ever fabricating market data.

Tokens are SYNTHETIC, deterministic ints in a high band (≥ 9·10¹¹) so they never
collide with the real 6-digit Kite tokens in KNOWN_TOKENS.
"""

import hashlib
from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta, timezone

from terminal_in.data_ingest.contract_specs import INDEX_CONTRACTS
from terminal_in.execution.options_pricing import price_and_greeks

IST = timezone(timedelta(hours=5, minutes=30))

# Strike spacing per underlying (NSE conventions).
STRIKE_INTERVAL = {'NIFTY': 50, 'BANKNIFTY': 100, 'FINNIFTY': 50}

# label → spec (lot_size, tokens, expiry rules) from the sourced contract specs.
_BY_LABEL = {c['label']: c for c in INDEX_CONTRACTS}

# Expiry weekday by name (Mon=0 … Sun=6).
_WD = {'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3,
       'friday': 4, 'saturday': 5, 'sunday': 6}

_TOKEN_BASE = 900_000_000_000   # synthetic-token band floor


@dataclass
class FnOInstrument:
    token: int
    tradingsymbol: str
    underlying: str          # label, e.g. 'NIFTY'
    underlying_token: int
    expiry: str              # ISO date
    strike: float            # 0 for FUT
    opt_type: str            # 'CE' | 'PE' | 'FUT'
    lot_size: int


# ── Expiry calendar ───────────────────────────────────────────────────────────

def _last_weekday_of_month(year: int, month: int, weekday: int) -> date:
    if month == 12:
        nxt = date(year + 1, 1, 1)
    else:
        nxt = date(year, month + 1, 1)
    d = nxt - timedelta(days=1)
    while d.weekday() != weekday:
        d -= timedelta(days=1)
    return d


def _next_weekday_on_or_after(d: date, weekday: int) -> date:
    delta = (weekday - d.weekday()) % 7
    return d + timedelta(days=delta)


def _monthly_weekday(label: str) -> int:
    spec = _BY_LABEL.get(label, {})
    txt = (spec.get('monthly_expiry') or 'last Thursday').lower()
    for name, wd in _WD.items():
        if name in txt:
            return wd
    return 3  # Thursday default


def expiries(label: str, today: date | None = None, months: int = 3) -> list[dict]:
    """Upcoming expiries for an underlying: the weekly series (NIFTY only, per
    current NSE rules) + the next `months` monthly expiries. Each tagged kind."""
    today = today or datetime.now(IST).date()
    spec = _BY_LABEL.get(label)
    if spec is None:
        return []
    out: list[dict] = []
    seen: set[str] = set()

    # Weekly (only where the spec defines a weekly expiry weekday)
    weekly = spec.get('weekly_expiry')
    if weekly:
        wd = _WD.get(weekly.lower(), 3)
        d = _next_weekday_on_or_after(today, wd)
        # next 4 weeklies
        for _ in range(4):
            iso = d.isoformat()
            if iso not in seen:
                out.append({'date': iso, 'kind': 'weekly'})
                seen.add(iso)
            d += timedelta(days=7)

    # Monthly series
    mwd = _monthly_weekday(label)
    y, m = today.year, today.month
    for _ in range(months + 1):
        exp = _last_weekday_of_month(y, m, mwd)
        if exp >= today:
            iso = exp.isoformat()
            out.append({'date': iso, 'kind': 'monthly'} if iso not in seen
                       else {'date': iso, 'kind': 'monthly'})
            seen.add(iso)
        m += 1
        if m > 12:
            m, y = 1, y + 1

    # De-dup (a weekly can coincide with the monthly) and sort
    uniq: dict[str, dict] = {}
    for e in out:
        # monthly label wins if a date is both
        if e['date'] not in uniq or e['kind'] == 'monthly':
            uniq[e['date']] = e
    return sorted(uniq.values(), key=lambda e: e['date'])


def _t_years(expiry_iso: str, now: datetime | None = None) -> float:
    now = now or datetime.now(IST)
    exp = datetime.fromisoformat(expiry_iso).replace(tzinfo=IST, hour=15, minute=30)
    secs = (exp - now).total_seconds()
    return max(secs, 0.0) / (365.0 * 24 * 3600)


# ── Token + symbol synthesis ──────────────────────────────────────────────────

def synth_token(label: str, expiry_iso: str, strike: float, opt_type: str) -> int:
    key = f'{label}|{expiry_iso}|{strike:.0f}|{opt_type}'.encode()
    h = int(hashlib.md5(key).hexdigest()[:12], 16)
    return _TOKEN_BASE + (h % 90_000_000_000)


def _tradingsymbol(label: str, expiry_iso: str, strike: float, opt_type: str) -> str:
    d = datetime.fromisoformat(expiry_iso)
    stamp = d.strftime('%y%b').upper()           # e.g. 26JAN
    if opt_type == 'FUT':
        return f'{label}{stamp}FUT'
    return f'{label}{stamp}{int(strike)}{opt_type}'


def make_instrument(label: str, expiry_iso: str, strike: float, opt_type: str) -> FnOInstrument:
    spec = _BY_LABEL[label]
    return FnOInstrument(
        token=synth_token(label, expiry_iso, strike, opt_type),
        tradingsymbol=_tradingsymbol(label, expiry_iso, strike, opt_type),
        underlying=label,
        underlying_token=spec['token'],
        expiry=expiry_iso,
        strike=float(strike),
        opt_type=opt_type,
        lot_size=int(spec['lot_size']),
    )


# ── Chain builder ─────────────────────────────────────────────────────────────

def atm_strike(label: str, spot: float) -> float:
    iv_step = STRIKE_INTERVAL.get(label, 50)
    return round(spot / iv_step) * iv_step


def build_chain(label: str, spot: float, vix: float, expiry_iso: str,
                n_strikes: int = 10, now: datetime | None = None) -> dict:
    """Theoretical option chain around ATM. `vix` is India VIX in PERCENT
    (the IV proxy); premiums/greeks are Black-Scholes, labeled theoretical."""
    if label not in _BY_LABEL:
        raise ValueError(f'unknown underlying {label}')
    spec = _BY_LABEL[label]
    step = STRIKE_INTERVAL.get(label, 50)
    iv = max(vix, 1.0) / 100.0
    t = _t_years(expiry_iso, now)
    atm = atm_strike(label, spot)

    rows = []
    for k in range(-n_strikes, n_strikes + 1):
        strike = atm + k * step
        if strike <= 0:
            continue
        ce = price_and_greeks(spot, strike, t, iv, 'CE')
        pe = price_and_greeks(spot, strike, t, iv, 'PE')
        ce['token'] = synth_token(label, expiry_iso, strike, 'CE')
        pe['token'] = synth_token(label, expiry_iso, strike, 'PE')
        rows.append({
            'strike': strike,
            'is_atm': strike == atm,
            'moneyness': 'ATM' if strike == atm else ('ITM' if strike < spot else 'OTM'),
            'CE': ce,
            'PE': pe,
            # OI / real-IV / volume are live-only; null in paper (never fabricated)
            'oi': None, 'iv_real': None, 'volume': None,
        })

    return {
        'underlying': label,
        'underlying_symbol': spec['symbol'],
        'spot': round(spot, 2),
        'atm_strike': atm,
        'expiry': expiry_iso,
        't_years': round(t, 5),
        'iv_used_pct': round(vix, 2),
        'iv_source': 'INDIA VIX (theoretical IV proxy)',
        'lot_size': int(spec['lot_size']),
        'strike_interval': step,
        'rows': rows,
        'theoretical': True,
        'note': 'Premiums/greeks are Black-Scholes theoretical (real spot + India '
                'VIX as IV). Not traded prices; OI/real-IV are live-only.',
    }


def instrument_dict(inst: FnOInstrument) -> dict:
    return asdict(inst)
