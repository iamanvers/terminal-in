"""F&O Stage 3 — FnOPaperBroker: lot-based premium P&L, margin, expiry square-off."""

import pytest

from terminal_in.execution.fno_paper_broker import FnOPaperBroker
from terminal_in.risk.span_margin import span_margin


class FakeCash:
    def __init__(self, equity=1_000_000.0):
        self.available = equity
        self.equity = equity
        self.reserved = 0.0
        self.pnl = 0.0
    def reserve_capital(self, amt):
        if amt > self.available:
            return False
        self.available -= amt; self.reserved += amt; return True
    def release_capital(self, amt):
        self.reserved -= amt; self.available += amt
    def apply_external_pnl(self, amt):
        self.pnl += amt; self.available += amt


class FakeDB:
    def __init__(self):
        self.trades = {}
    def get_open_trades(self):
        return [t for t in self.trades.values() if t.get('exit_time') is None]
    def insert_trade(self, t):
        self.trades[t['trade_id']] = {**t, 'exit_time': None,
                                      'metadata_json': __import__('json').dumps(t.get('metadata', {}))}
    def close_trade(self, tid, data):
        if tid in self.trades:
            self.trades[tid]['exit_time'] = 1
            self.trades[tid].update(data)
    def get_ohlcv_1d(self, token, limit=1):
        return None


def _broker():
    b = FnOPaperBroker(db=FakeDB(), config=None, cash_broker=FakeCash())
    b._vix = 14.0
    return b


def test_place_long_call_reserves_premium_debit():
    b = _broker()
    b._spot[256265] = 22000.0
    r = b.place_order({'underlying': 'NIFTY', 'expiry': '2026-08-27',
                       'strike': 22000, 'opt_type': 'CE', 'side': 'BUY', 'lots': 2})
    assert r['ok'] and r['premium'] > 0
    assert r['qty'] == 2 * 75
    # long-option margin == premium debit == premium × qty (to rounding)
    assert r['margin'] == pytest.approx(r['premium'] * r['qty'], abs=r['qty'] * 0.01)
    assert b._cash.reserved == pytest.approx(r['margin'])
    assert len(b.positions()) == 1


def test_long_call_profit_on_spot_rise():
    b = _broker()
    b._spot[256265] = 22000.0
    r = b.place_order({'underlying': 'NIFTY', 'expiry': '2026-08-27',
                       'strike': 22000, 'opt_type': 'CE', 'side': 'BUY', 'lots': 1})
    tid = r['trade_id']
    # spot jumps → call premium rises → close in profit
    b._on_tick({'instrument_token': 256265, 'last_price': 22600.0})
    res = b.close_position(tid, reason='manual')
    assert res['ok']
    assert b._cash.pnl > 0                 # realized profit applied to shared account
    assert b._cash.reserved == pytest.approx(0.0, abs=1e-6)   # margin released


def test_short_option_uses_scenario_span_margin():
    b = _broker()
    b._spot[256265] = 22000.0
    b._vix = 14.0
    r = b.place_order({'underlying': 'NIFTY', 'expiry': '2026-08-27',
                       'strike': 22000, 'opt_type': 'CE', 'side': 'SELL', 'lots': 1})
    # broker margin must equal the SPAN-approx model for this short leg
    from terminal_in.data_ingest import fno_instruments as fno
    t = fno._t_years('2026-08-27')
    expected = span_margin(22000.0, 22000.0, t, 0.14, 'CE', 'SELL', 75)['margin']
    assert r['margin'] == pytest.approx(expected, rel=1e-6)
    assert r['scan_loss'] > 0 and r['exposure'] > 0      # scenario loss + exposure
    assert r['margin_approx'] is True


def test_expiry_square_off_settles_intrinsic():
    b = _broker()
    b._spot[256265] = 22000.0
    r = b.place_order({'underlying': 'NIFTY', 'expiry': '2020-01-30',  # already expired
                       'strike': 21500, 'opt_type': 'CE', 'side': 'BUY', 'lots': 1})
    # a tick after expiry triggers square-off at intrinsic = spot − strike
    b._on_tick({'instrument_token': 256265, 'last_price': 22000.0})
    assert len(b.positions()) == 0          # squared off
    # ITM call (spot 22000 > strike 21500) settles positive vs a tiny entry premium
    assert b._cash.pnl != 0


def test_insufficient_capital_rejected():
    b = FnOPaperBroker(db=FakeDB(), config=None, cash_broker=FakeCash(equity=100.0))
    b._vix = 14.0
    b._spot[260105] = 56000.0
    r = b.place_order({'underlying': 'BANKNIFTY', 'expiry': '2026-08-27',
                       'strike': 56000, 'opt_type': 'PE', 'side': 'SELL', 'lots': 5})
    # rejected for affordability — either the margin cap or the capital reserve
    assert not r['ok'] and ('capital' in r['error'].lower() or 'margin' in r['error'].lower())


def test_vix_tick_updates_iv_not_a_position():
    b = _broker()
    b._on_tick({'instrument_token': 264969, 'last_price': 22.5})
    assert b._vix == 22.5


# ── F&O risk caps ───────────────────────────────────────────────────────────────

from terminal_in.execution.fno_paper_broker import (
    MAX_PER_EXPIRY, MAX_SHORT_OPTIONS, MAX_FNO_MARGIN_PCT)


def test_per_expiry_concentration_cap():
    b = _broker()
    b._positions = {f't{i}': {'expiry': '2030-01-31', 'side': 'BUY',
                              'opt_type': 'CE', 'margin': 100.0}
                    for i in range(MAX_PER_EXPIRY)}
    ok, reason = b._risk_check('2030-01-31', 'CE', 'BUY', 100.0)
    assert not ok and 'per expiry' in reason
    # a different expiry is fine
    assert b._risk_check('2030-02-27', 'CE', 'BUY', 100.0)[0]


def test_short_gamma_cap():
    b = _broker()
    b._positions = {f's{i}': {'expiry': f'2030-{i+1:02d}-01', 'side': 'SELL',
                              'opt_type': 'CE', 'margin': 100.0}
                    for i in range(MAX_SHORT_OPTIONS)}
    ok, reason = b._risk_check('2031-01-01', 'CE', 'SELL', 100.0)
    assert not ok and 'short' in reason.lower()
    # a long leg is unaffected by the short cap
    assert b._risk_check('2031-01-01', 'CE', 'BUY', 100.0)[0]


def test_total_margin_cap():
    b = _broker()  # FakeCash equity = 1,000,000
    half = 1_000_000 * MAX_FNO_MARGIN_PCT
    b._positions = {'big': {'expiry': '2030-01-31', 'side': 'SELL',
                            'opt_type': 'CE', 'margin': half - 1000}}
    ok, reason = b._risk_check('2030-01-31', 'CE', 'SELL', 5000)  # pushes over 50%
    assert not ok and 'margin cap' in reason.lower()


# ── Portfolio greek caps + event-day limits (live-order path) ────────────────────

from terminal_in.execution import fno_paper_broker as fpb


def _leg(side='BUY', opt='CE', delta=0.5, gamma=0.0, vega=0.0, theta=0.0,
         qty=75, spot=22000.0):
    sign = 1 if side == 'BUY' else -1
    return {
        'delta_units': sign * delta * qty,
        'delta_notional': sign * delta * qty * spot,
        'gamma_pnl': sign * 0.5 * gamma * (fpb.GAMMA_SHOCK * spot) ** 2 * qty,
        'vega_rupees': sign * vega * qty,
        'theta_rupees': sign * theta * qty,
    }


def test_event_blackout_blocks_all_entries(monkeypatch):
    b = _broker()
    monkeypatch.setattr(fpb.event_cal, 'mask', lambda *a, **k: 0.0)  # Budget-style
    ok, reason = b._risk_check('2030-01-31', 'CE', 'BUY', 100.0,
                               leg_greeks=_leg(), equity=1_000_000)
    assert not ok and 'blackout' in reason.lower()


def test_event_proximity_blocks_new_shorts_only(monkeypatch):
    b = _broker()
    monkeypatch.setattr(fpb.event_cal, 'mask', lambda *a, **k: 0.5)  # expiry/RBI day
    # a new short-gamma leg is refused
    ok, _ = b._risk_check('2030-01-31', 'CE', 'SELL', 100.0,
                          leg_greeks=_leg('SELL'), equity=1_000_000)
    assert not ok
    # a long (defined-risk) leg is still allowed
    assert b._risk_check('2030-01-31', 'CE', 'BUY', 100.0,
                         leg_greeks=_leg('BUY'), equity=1_000_000)[0]


def test_net_delta_cap(monkeypatch):
    b = _broker()
    monkeypatch.setattr(fpb.event_cal, 'mask', lambda *a, **k: 1.0)
    # one huge directional leg: delta notional = 1 * 7500 qty * 22000 spot ≈ 165M
    ok, reason = b._risk_check('2030-01-31', 'FUT', 'BUY', 100.0,
                               leg_greeks=_leg('BUY', delta=1.0, qty=7500),
                               equity=1_000_000)
    assert not ok and 'delta' in reason.lower()


def test_short_gamma_loss_cap(monkeypatch):
    b = _broker()
    monkeypatch.setattr(fpb.event_cal, 'mask', lambda *a, **k: 1.0)
    # short gamma leg whose 2% gap loss blows past 5% of equity
    # (delta=0 so the delta cap doesn't pre-empt the gamma check)
    ok, reason = b._risk_check('2030-01-31', 'CE', 'SELL', 100.0,
                               leg_greeks=_leg('SELL', delta=0.0, gamma=0.01, qty=7500),
                               equity=1_000_000)
    assert not ok and 'gamma' in reason.lower()


def test_portfolio_greeks_shape():
    b = _broker()
    g = b.portfolio_greeks()
    assert set(g) >= {'net_delta', 'net_vega', 'net_theta', 'net_gamma_2pct'}
    assert g['theoretical'] is True
