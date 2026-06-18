"""Guards for the active strategy roster + the cash-short product invariant.

S6 (pairs cointegration) is ACTIVE as a single-leg relative-value strategy. The
correctness floor it (and any strategy) must respect: a SHORT in the cash segment
is intraday-only — NSE has no overnight CNC delivery short — so every SELL is MIS.
"""

from terminal_in.strategy_engine.engine import ALL_STRATEGIES
from terminal_in.execution.paper_broker import _product_for


def test_active_roster_is_the_expected_eight():
    ids = sorted(s.id for s in ALL_STRATEGIES)
    assert ids == ['S1', 'S2', 'S3', 'S4', 'S5', 'S6', 'S8', 'S9']


def test_cash_short_is_always_mis():
    # a SELL in cash can only be intraday — never an overnight CNC delivery short
    assert _product_for({'strategy_id': 'S6', 'side': 'SELL'}) == 'MIS'
    assert _product_for({'strategy_id': 'S9', 'side': 'SELL'}) == 'MIS'


def test_long_delivery_is_cnc_short_is_not():
    # a positional BUY carries as CNC; the same name as a SELL flips to intraday MIS
    assert _product_for({'strategy_id': 'S6', 'side': 'BUY'}) == 'CNC'
    assert _product_for({'strategy_id': 'S6', 'side': 'SELL'}) == 'MIS'


def test_explicit_mis_and_s1_still_intraday():
    assert _product_for({'strategy_id': 'S1', 'side': 'BUY'}) == 'MIS'
    assert _product_for({'strategy_id': 'S2', 'metadata': {'product': 'MIS'}}) == 'MIS'
    assert _product_for({'strategy_id': 'S2', 'time_exit': 123}) == 'MIS'
