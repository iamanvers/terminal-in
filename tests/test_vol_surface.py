"""Unit tests for the per-underlying skew vol surface (execution/vol_surface.py).

Pure-maths checks: ATM is the anchor, equity-index negative skew (OTM puts richer),
clamps, term factor, and the VOL_SURFACE=false flat fallback.
"""

import math

import pytest

from terminal_in.execution import vol_surface as VS
from terminal_in.execution.options_pricing import bs_price


@pytest.fixture(autouse=True)
def _surface_on(monkeypatch):
    monkeypatch.setenv('VOL_SURFACE', 'true')


def test_atm_returns_anchor_unchanged():
    # strike == spot → k=0 → no skew, no smile → exactly the ATM anchor
    assert VS.skew_iv(0.14, 20000.0, 20000.0, 0.08) == pytest.approx(0.14, abs=1e-9)


def test_negative_skew_puts_richer_than_calls():
    spot, atm = 20000.0, 0.14
    otm_put_iv  = VS.skew_iv(atm, spot, 18000.0, 0.08)   # strike < spot
    otm_call_iv = VS.skew_iv(atm, spot, 22000.0, 0.08)   # strike > spot
    assert otm_put_iv > atm > otm_call_iv                # equity-index negative skew


def test_disabled_is_flat(monkeypatch):
    monkeypatch.setenv('VOL_SURFACE', 'false')
    for strike in (16000.0, 20000.0, 24000.0):
        assert VS.skew_iv(0.14, 20000.0, strike, 0.08) == 0.14   # bit-for-bit flat


def test_degenerate_inputs_return_anchor():
    assert VS.skew_iv(0.0, 20000.0, 19000.0, 0.08) == 0.0
    assert VS.skew_iv(0.14, 0.0, 19000.0, 0.08) == 0.14
    assert VS.skew_iv(0.14, 20000.0, 0.0, 0.08) == 0.14


def test_iv_clamped_to_band():
    # an absurd deep-OTM put can't push IV past the cap, nor below the floor
    iv_lo = VS.skew_iv(0.06, 20000.0, 40000.0, 0.08)     # far OTM call → lower IV
    iv_hi = VS.skew_iv(0.50, 20000.0, 1000.0, 0.02)      # far OTM put, short tenor
    assert VS.IV_FLOOR <= iv_lo <= VS.IV_CAP
    assert VS.IV_FLOOR <= iv_hi <= VS.IV_CAP


def test_short_tenor_skew_is_steeper():
    spot, atm, strike = 20000.0, 0.14, 18000.0
    short = VS.skew_iv(atm, spot, strike, 0.02)          # ~1 week
    long  = VS.skew_iv(atm, spot, strike, 1.0)           # 1 year
    # both above ATM (put), but the short tenor has the steeper skew
    assert short > long > atm


def test_skew_makes_otm_put_premium_richer_than_flat():
    # the whole point: a skewed OTM put prices higher than the flat-VIX premium
    spot, atm, strike, t = 20000.0, 0.14, 18000.0, 0.08
    flat_px = bs_price(spot, strike, t, atm, 'PE')
    skew_px = bs_price(spot, strike, t, VS.skew_iv(atm, spot, strike, t), 'PE')
    assert skew_px > flat_px
