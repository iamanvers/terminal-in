"""F&O Stage 1 tests — Black-Scholes pricing + the option-chain/instrument model."""

import math
from datetime import date

import numpy as np
import pandas as pd
import pytest

from terminal_in.execution.options_pricing import bs_price, bs_greeks, RISK_FREE
from terminal_in.data_ingest import fno_instruments as fno


# ── Black-Scholes pricing ──────────────────────────────────────────────────────

def test_bs_call_put_parity():
    # C - P = S - K·e^{-rT}
    spot, strike, t, iv = 22000.0, 22000.0, 30 / 365, 0.14
    c = bs_price(spot, strike, t, iv, 'CE')
    p = bs_price(spot, strike, t, iv, 'PE')
    lhs = c - p
    rhs = spot - strike * math.exp(-RISK_FREE * t)
    assert abs(lhs - rhs) < 1e-6


def test_bs_premium_positive_and_monotone_in_vol():
    base = bs_price(22000, 22200, 30 / 365, 0.12, 'CE')
    higher = bs_price(22000, 22200, 30 / 365, 0.20, 'CE')
    assert base > 0
    assert higher > base            # vega positive — more vol, dearer option


def test_bs_intrinsic_at_expiry():
    # t=0 → intrinsic value
    assert bs_price(22000, 21500, 0.0, 0.14, 'CE') == pytest.approx(500.0)
    assert bs_price(22000, 22500, 0.0, 0.14, 'CE') == 0.0
    assert bs_price(22000, 22500, 0.0, 0.14, 'PE') == pytest.approx(500.0)


def test_bs_call_delta_bounds():
    deep_itm = bs_greeks(22000, 18000, 30 / 365, 0.14, 'CE')['delta']
    deep_otm = bs_greeks(22000, 26000, 30 / 365, 0.14, 'CE')['delta']
    atm = bs_greeks(22000, 22000, 30 / 365, 0.14, 'CE')['delta']
    assert deep_itm > 0.95
    assert deep_otm < 0.05
    assert 0.4 < atm < 0.65         # ATM call delta ~0.5+


def test_put_delta_negative_and_theta_decay():
    g = bs_greeks(22000, 22000, 30 / 365, 0.14, 'PE')
    assert -1.0 < g['delta'] < 0.0
    assert g['theta'] < 0.0         # long option loses to time
    assert g['vega'] > 0.0
    assert g['gamma'] > 0.0


def test_future_is_forward_with_unit_delta():
    px = bs_price(22000, 0, 30 / 365, 0.14, 'FUT')
    assert px > 22000              # cost-of-carry forward > spot
    assert bs_greeks(22000, 0, 30 / 365, 0.14, 'FUT')['delta'] == 1.0


# ── Expiry calendar ────────────────────────────────────────────────────────────

def test_nifty_weekly_is_thursday():
    today = date(2026, 1, 5)        # a Monday
    exps = fno.expiries('NIFTY', today=today)
    weeklies = [e for e in exps if e['kind'] == 'weekly']
    assert weeklies, 'NIFTY must have weekly expiries'
    for e in weeklies:
        assert date.fromisoformat(e['date']).weekday() == 3   # Thursday
        assert date.fromisoformat(e['date']) >= today


def test_banknifty_has_no_weekly():
    exps = fno.expiries('BANKNIFTY', today=date(2026, 1, 5))
    assert all(e['kind'] == 'monthly' for e in exps)          # weeklies discontinued


def test_monthly_expiry_is_last_target_weekday():
    # NIFTY monthly = last Thursday of the month
    exps = fno.expiries('NIFTY', today=date(2026, 1, 5))
    monthlies = [e for e in exps if e['kind'] == 'monthly']
    assert monthlies
    d = date.fromisoformat(monthlies[0]['date'])
    assert d.weekday() == 3
    # it must be the LAST Thursday — adding 7 days rolls into next month
    from datetime import timedelta
    assert (d + timedelta(days=7)).month != d.month


# ── Chain + instrument model ───────────────────────────────────────────────────

def test_chain_structure_and_atm():
    chain = fno.build_chain('NIFTY', spot=22037.0, iv_pct=14.0,
                            expiry_iso='2026-01-29', n_strikes=5)
    assert chain['theoretical'] is True
    assert chain['atm_strike'] == 22050              # nearest 50
    assert chain['lot_size'] == 75
    assert len(chain['rows']) == 11                  # -5..+5
    atm_rows = [r for r in chain['rows'] if r['is_atm']]
    assert len(atm_rows) == 1
    # OI / real IV are live-only — must be null, never fabricated
    for r in chain['rows']:
        assert r['oi'] is None and r['iv_real'] is None
        assert r['CE']['premium'] >= 0 and r['PE']['premium'] >= 0


def test_synthetic_tokens_dont_collide_with_real():
    # synthetic F&O tokens sit in a high band, far above 6-digit Kite tokens
    tok = fno.synth_token('NIFTY', '2026-01-29', 22000, 'CE')
    assert tok >= 900_000_000_000
    # deterministic
    assert tok == fno.synth_token('NIFTY', '2026-01-29', 22000, 'CE')
    # CE and PE at same strike differ
    assert tok != fno.synth_token('NIFTY', '2026-01-29', 22000, 'PE')


def test_tradingsymbol_format():
    inst = fno.make_instrument('NIFTY', '2026-01-29', 22000, 'CE')
    assert inst.tradingsymbol == 'NIFTY26JAN22000CE'
    assert inst.lot_size == 75
    assert inst.underlying_token == 256265


# ── SPAN-approx margin (Stage 4) ────────────────────────────────────────────────

from terminal_in.risk.span_margin import span_margin, scan_range


def test_span_long_option_margin_is_just_premium():
    from terminal_in.execution.options_pricing import bs_price
    m = span_margin(22000, 22000, 30 / 365, 0.14, 'CE', 'BUY', 75)
    prem = bs_price(22000, 22000, 30 / 365, 0.14, 'CE')
    assert m['margin'] == pytest.approx(prem * 75, rel=1e-6)   # premium = max loss
    assert m['exposure'] == 0.0


def test_span_short_atm_costs_more_than_otm():
    # the whole point of SPAN over a flat %: an ATM short carries MORE risk
    # margin than a far-OTM short (more gamma exposure to the price scan).
    atm = span_margin(22000, 22000, 30 / 365, 0.14, 'CE', 'SELL', 75)['margin']
    otm = span_margin(22000, 24000, 30 / 365, 0.14, 'CE', 'SELL', 75)['margin']
    assert atm > otm > 0


def test_span_short_has_scan_plus_exposure():
    m = span_margin(22000, 22000, 30 / 365, 0.14, 'CE', 'SELL', 75)
    assert m['scan_loss'] > 0 and m['exposure'] > 0
    assert m['margin'] == pytest.approx(m['scan_loss'] + m['exposure'], rel=1e-6)


def test_span_future_margin_in_realistic_band():
    # index future initial margin should land in a sane single/low-double-digit
    # % of notional band (not the cash 30% rule).
    qty, spot = 75, 22000.0
    m = span_margin(spot, 0, 30 / 365, 0.14, 'FUT', 'BUY', qty)['margin']
    pct = m / (spot * qty)
    assert 0.05 <= pct <= 0.18


def test_scan_range_floored_and_capped():
    spot = 22000.0
    assert scan_range(spot, 0.01) == pytest.approx(spot * 0.05)   # tiny vol -> floor 5%
    assert scan_range(spot, 2.0) == pytest.approx(spot * 0.15)    # huge vol -> cap 15%


# ── Stock F&O (single-stock contracts + per-stock IV) ───────────────────────────

from terminal_in.data_ingest.iv_estimator import realized_vol_pct, iv_for_underlying


def test_stock_underlyings_present_and_not_index():
    labels = {c['label'] for c in fno.CONTRACTS}
    assert 'RELIANCE' in labels and 'NIFTY' in labels        # stocks + indices both
    assert fno._BY_LABEL['RELIANCE']['lot_size'] == 500
    assert not fno.is_index('RELIANCE') and fno.is_index('NIFTY')


def test_strike_interval_index_fixed_stock_scales():
    assert fno.strike_interval('NIFTY', 22000) == 50            # fixed for index
    assert fno.strike_interval('RELIANCE', 1400) == 20          # stock: spot-scaled
    assert fno.strike_interval('SBIN', 420) == 10
    assert fno.strike_interval('MARUTI', 12000) == 100


def test_stock_only_monthly_expiry():
    exps = fno.expiries('RELIANCE', today=date(2026, 1, 5))
    assert exps and all(e['kind'] == 'monthly' for e in exps)   # no stock weeklies
    assert date.fromisoformat(exps[0]['date']).weekday() == 3   # last Thursday


class _FakeDB:
    def __init__(self, df): self._df = df
    def get_ohlcv_1d(self, token, limit=40): return self._df


def test_iv_index_uses_vix_stock_uses_realized():
    # build a frame whose realized vol is well above index VIX
    n = 60
    idx = pd.date_range(end=pd.Timestamp('2024-01-01'), periods=n, freq='D')
    rng = np.random.default_rng(0)
    close = 1400 * np.exp(np.cumsum(rng.normal(0, 0.03, n)))     # ~3%/day -> high vol
    df = pd.DataFrame({'open': close, 'high': close, 'low': close,
                       'close': close, 'volume': 1.0}, index=idx)
    db = _FakeDB(df)
    iv_idx, src_idx = iv_for_underlying('NIFTY', db, 14.0, 256265)
    iv_stk, src_stk = iv_for_underlying('RELIANCE', db, 14.0, 738561)
    assert iv_idx == 14.0 and 'VIX' in src_idx
    assert iv_stk > 20.0 and 'realized' in src_stk              # stock vol >> VIX
    assert realized_vol_pct(df) is not None
