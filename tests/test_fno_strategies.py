"""F&O strategy leg-builders (pure) + atomic multi-leg place_combo."""

import pytest

from terminal_in.execution import fno_strategies as S
from terminal_in.execution import fno_paper_broker as fpb
from terminal_in.execution.fno_paper_broker import FnOPaperBroker
from terminal_in.data_ingest import fno_instruments as fno

# reuse the broker fakes
from tests.test_fno_broker import FakeCash, FakeDB


# ── pure leg-builder structure ──────────────────────────────────────────────────

def test_vertical_bull_call_spread_structure():
    legs = S.vertical_spread_legs('NIFTY', 22013, '2026-08-27', 'BULL', width=2, lots=1)
    assert len(legs) == 2
    assert all(l['opt_type'] == 'CE' for l in legs)
    buy, sell = [l for l in legs if l['side'] == 'BUY'][0], [l for l in legs if l['side'] == 'SELL'][0]
    assert sell['strike'] > buy['strike']                     # sell the higher strike
    assert sell['strike'] - buy['strike'] == 2 * fno.strike_interval('NIFTY', 22013)


def test_vertical_bear_put_spread_structure():
    legs = S.vertical_spread_legs('NIFTY', 22013, '2026-08-27', 'BEAR', width=3, lots=1)
    assert all(l['opt_type'] == 'PE' for l in legs)
    buy = [l for l in legs if l['side'] == 'BUY'][0]
    sell = [l for l in legs if l['side'] == 'SELL'][0]
    assert sell['strike'] < buy['strike']                     # sell the lower strike (bear put)


def test_iron_condor_structure():
    legs = S.iron_condor_legs('NIFTY', 22000, '2026-08-27', body=2, wing=2, lots=1)
    assert len(legs) == 4
    calls = sorted([l for l in legs if l['opt_type'] == 'CE'], key=lambda l: l['strike'])
    puts = sorted([l for l in legs if l['opt_type'] == 'PE'], key=lambda l: l['strike'])
    # call spread: short the nearer (lower) call, long the farther (higher) call
    assert calls[0]['side'] == 'SELL' and calls[1]['side'] == 'BUY'
    # put spread: short the nearer (higher) put, long the farther (lower) put
    assert puts[1]['side'] == 'SELL' and puts[0]['side'] == 'BUY'


def test_futures_pair_structure():
    legs = S.futures_pair_legs('RELIANCE', 'INFY', '2026-08-27', lots_long=1, lots_short=1)
    assert {l['opt_type'] for l in legs} == {'FUT'}
    assert all(l['strike'] == 0.0 for l in legs)
    long_leg = [l for l in legs if l['side'] == 'BUY'][0]
    short_leg = [l for l in legs if l['side'] == 'SELL'][0]
    assert long_leg['underlying'] == 'RELIANCE' and short_leg['underlying'] == 'INFY'


def test_straddle_and_covered_call():
    st = S.straddle_legs('NIFTY', 22000, '2026-08-27', lots=1, side='BUY')
    assert {l['opt_type'] for l in st} == {'CE', 'PE'} and all(l['side'] == 'BUY' for l in st)
    assert st[0]['strike'] == st[1]['strike']                 # same ATM strike
    cc = S.covered_call_legs('NIFTY', 22000, '2026-08-27', otm=3, lots=1)
    assert len(cc) == 1 and cc[0]['side'] == 'SELL' and cc[0]['opt_type'] == 'CE'
    assert cc[0]['strike'] > 22000                            # OTM call


# ── atomic multi-leg placement ───────────────────────────────────────────────────

def _broker(equity=1_000_000.0):
    b = FnOPaperBroker(db=FakeDB(), config=None, cash_broker=FakeCash(equity))
    b._vix = 14.0
    return b


def test_place_combo_iron_condor_opens_all_four(monkeypatch):
    monkeypatch.setattr(fpb.event_cal, 'mask', lambda *a, **k: 1.0)
    b = _broker()
    b._spot[256265] = 22000.0
    legs = S.iron_condor_legs('NIFTY', 22000.0, '2026-08-27', body=2, wing=2, lots=1)
    r = b.place_combo(legs, {'kind': 'iron_condor'})
    assert r['ok'], r.get('error')
    assert r['n_legs'] == 4 and len(b.positions()) == 4
    # all four legs share one combo_id
    assert len({p['combo_id'] for p in b.positions()}) == 1
    # bulk margin reserved == sum of leg margins (to rounding)
    assert b._cash.reserved == pytest.approx(r['margin'], abs=1.0)


def test_place_combo_is_atomic_on_cap_breach(monkeypatch):
    """A combo that breaches a cap opens NOTHING (no partial fills)."""
    monkeypatch.setattr(fpb.event_cal, 'mask', lambda *a, **k: 1.0)
    b = _broker(equity=50_000.0)              # tiny account
    b._spot[256265] = 22000.0
    # a big short strangle's SPAN margin will blow the 50%-margin cap
    legs = S.short_strangle_legs('NIFTY', 22000.0, '2026-08-27', otm=3, lots=10)
    r = b.place_combo(legs)
    assert not r['ok']
    assert len(b.positions()) == 0                   # nothing opened
    assert b._cash.reserved == pytest.approx(0.0, abs=1e-6)   # no margin held


def test_place_combo_futures_pair_long_short(monkeypatch):
    monkeypatch.setattr(fpb.event_cal, 'mask', lambda *a, **k: 1.0)
    b = _broker()
    rel = fno._BY_LABEL['RELIANCE']['token']
    inf = fno._BY_LABEL['INFY']['token']
    b._spot[rel] = 1300.0
    b._spot[inf] = 1500.0
    legs = S.futures_pair_legs('RELIANCE', 'INFY', '2026-08-27', 1, 1)
    r = b.place_combo(legs, {'kind': 'futures_pair'})
    assert r['ok'], r.get('error')
    sides = {p['underlying']: p['side'] for p in b.positions()}
    assert sides == {'RELIANCE': 'BUY', 'INFY': 'SELL'}
