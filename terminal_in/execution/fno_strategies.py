"""
F&O strategy LEG BUILDERS — pure functions that turn a market view into the list
of legs for a multi-leg combo (placed atomically via FnOPaperBroker.place_combo).

Pure and side-effect-free (no broker, no bus, no DB) so the structure of every
strategy — strikes, sides, option types, lots — is unit-testable in isolation.
Each leg is the dict shape place_combo/place_order accept:
    {underlying, expiry, strike, opt_type, side, lots, sl_premium?, target_premium?}

Strikes are snapped to the real NSE strike interval via fno.strike_interval /
fno.atm_strike, so the structures line up with the actual chain.
"""

from terminal_in.data_ingest import fno_instruments as fno


def _atm_and_step(label: str, spot: float) -> tuple[float, int]:
    return fno.atm_strike(label, spot), fno.strike_interval(label, spot)


def _leg(label, expiry, strike, opt_type, side, lots):
    return {'underlying': label, 'expiry': expiry, 'strike': float(strike),
            'opt_type': opt_type, 'side': side, 'lots': int(lots)}


def vertical_spread_legs(label: str, spot: float, expiry: str, direction: str,
                         width: int = 2, lots: int = 1) -> list[dict]:
    """Risk-DEFINED directional spread (a debit spread):
      BULL → buy ATM call, sell OTM call `width` strikes up  (bull call spread)
      BEAR → buy ATM put,  sell OTM put  `width` strikes down (bear put spread)
    Caps both cost and risk vs a naked long option — the upgrade for the
    directional signal router. `width` is in strike steps."""
    direction = direction.upper()
    atm, step = _atm_and_step(label, spot)
    if direction == 'BULL':
        long_k, short_k, opt = atm, atm + width * step, 'CE'
    elif direction == 'BEAR':
        long_k, short_k, opt = atm, atm - width * step, 'PE'
    else:
        raise ValueError("direction must be 'BULL' or 'BEAR'")
    return [_leg(label, expiry, long_k, opt, 'BUY', lots),
            _leg(label, expiry, short_k, opt, 'SELL', lots)]


def iron_condor_legs(label: str, spot: float, expiry: str, body: int = 2,
                     wing: int = 2, lots: int = 1) -> list[dict]:
    """Range-bound, DEFINED-RISK short-vol structure (the variance-premium harvest):
    short a call `body` steps OTM + long a call `body+wing` steps OTM (call spread),
    and the mirror put spread below. Collects net premium; max loss = wing width −
    credit. The long wings bound the short-gamma/vega the risk caps watch."""
    atm, step = _atm_and_step(label, spot)
    return [
        _leg(label, expiry, atm + body * step,          'CE', 'SELL', lots),
        _leg(label, expiry, atm + (body + wing) * step, 'CE', 'BUY',  lots),
        _leg(label, expiry, atm - body * step,          'PE', 'SELL', lots),
        _leg(label, expiry, atm - (body + wing) * step, 'PE', 'BUY',  lots),
    ]


def short_strangle_legs(label: str, spot: float, expiry: str, otm: int = 3,
                        lots: int = 1) -> list[dict]:
    """UNDEFINED-RISK short strangle: sell an OTM call + an OTM put `otm` steps out.
    Higher credit than the condor but unbounded tails — prefer the condor unless
    the greek caps explicitly allow it."""
    atm, step = _atm_and_step(label, spot)
    return [_leg(label, expiry, atm + otm * step, 'CE', 'SELL', lots),
            _leg(label, expiry, atm - otm * step, 'PE', 'SELL', lots)]


def straddle_legs(label: str, spot: float, expiry: str, lots: int = 1,
                  side: str = 'BUY') -> list[dict]:
    """ATM straddle (call + put, same strike). side='BUY' = long vol (bet on a
    move, e.g. pre-event); side='SELL' = short vol."""
    atm, _ = _atm_and_step(label, spot)
    side = side.upper()
    return [_leg(label, expiry, atm, 'CE', side, lots),
            _leg(label, expiry, atm, 'PE', side, lots)]


def covered_call_legs(label: str, spot: float, expiry: str, otm: int = 3,
                      lots: int = 1) -> list[dict]:
    """The F&O leg of a covered call: SELL an OTM call `otm` steps up. The 'cover'
    is the held cash/long position, tracked on the equity book — this only emits
    the option leg."""
    atm, step = _atm_and_step(label, spot)
    return [_leg(label, expiry, atm + otm * step, 'CE', 'SELL', lots)]


def futures_pair_legs(long_sym: str, short_sym: str, expiry: str,
                      lots_long: int = 1, lots_short: int = 1) -> list[dict]:
    """Market-neutral single-stock FUTURES pair: long the cheap leg, short the rich
    leg. The short leg is FUTURES (not cash) precisely because NSE cash can't carry
    an overnight short. Strike is 0 for futures."""
    return [_leg(long_sym,  expiry, 0.0, 'FUT', 'BUY',  lots_long),
            _leg(short_sym, expiry, 0.0, 'FUT', 'SELL', lots_short)]
