"""
Tests for the shared Indian-equity transaction-cost model (execution/costs.py).

Each component is asserted against a hand-computed value for a known notional
across all four (side × segment) combinations, plus the MIS brokerage cap and
the no-silent-fallback contract.
"""

import pytest

from terminal_in.execution.costs import cost_breakdown


# Hand-computed for notional = ₹1,00,000 (see comments per component):
#   exchange_txn = 0.0000297 * 100000 = 2.97   (both branches)
#   sebi         = 0.000001  * 100000 = 0.10   (both branches)
N = 100_000.0


def test_cnc_buy():
    b = cost_breakdown(N, 'BUY', 'CNC')
    assert b['brokerage']    == pytest.approx(0.0)          # CNC delivery = free
    assert b['stt']          == pytest.approx(100.0)        # 0.1% both sides
    assert b['exchange_txn'] == pytest.approx(2.97)
    assert b['sebi']         == pytest.approx(0.10)
    assert b['stamp']        == pytest.approx(15.0)         # 0.015% buy only
    assert b['gst']          == pytest.approx(0.18 * (0 + 2.97 + 0.10))   # 0.5526
    assert b['total']        == pytest.approx(118.6226)


def test_cnc_sell():
    b = cost_breakdown(N, 'SELL', 'CNC')
    assert b['brokerage']    == pytest.approx(0.0)
    assert b['stt']          == pytest.approx(100.0)        # 0.1% both sides
    assert b['exchange_txn'] == pytest.approx(2.97)
    assert b['sebi']         == pytest.approx(0.10)
    assert b['stamp']        == pytest.approx(0.0)          # no stamp on sell
    assert b['gst']          == pytest.approx(0.5526)
    assert b['total']        == pytest.approx(103.6226)


def test_mis_buy():
    b = cost_breakdown(N, 'BUY', 'MIS')
    assert b['brokerage']    == pytest.approx(20.0)         # min(0.03%*N=30, 20)
    assert b['stt']          == pytest.approx(0.0)          # MIS STT is sell-only
    assert b['exchange_txn'] == pytest.approx(2.97)
    assert b['sebi']         == pytest.approx(0.10)
    assert b['stamp']        == pytest.approx(3.0)          # 0.003% buy only
    assert b['gst']          == pytest.approx(0.18 * (20 + 2.97 + 0.10))  # 4.1526
    assert b['total']        == pytest.approx(30.2226)


def test_mis_sell():
    b = cost_breakdown(N, 'SELL', 'MIS')
    assert b['brokerage']    == pytest.approx(20.0)
    assert b['stt']          == pytest.approx(25.0)         # 0.025% sell only
    assert b['exchange_txn'] == pytest.approx(2.97)
    assert b['sebi']         == pytest.approx(0.10)
    assert b['stamp']        == pytest.approx(0.0)
    assert b['gst']          == pytest.approx(4.1526)
    assert b['total']        == pytest.approx(52.2226)


def test_mis_brokerage_below_cap():
    # Small notional → 0.03% is below the ₹20 cap, so brokerage scales linearly.
    b = cost_breakdown(10_000.0, 'BUY', 'MIS')
    assert b['brokerage'] == pytest.approx(3.0)             # 0.0003 * 10000 = 3 < 20


def test_total_equals_component_sum():
    b = cost_breakdown(N, 'SELL', 'MIS')
    parts = b['brokerage'] + b['stt'] + b['exchange_txn'] + b['sebi'] + b['stamp'] + b['gst']
    assert b['total'] == pytest.approx(parts)


def test_notional_is_sign_agnostic():
    assert cost_breakdown(-N, 'BUY', 'CNC')['total'] == pytest.approx(
        cost_breakdown(N, 'BUY', 'CNC')['total'])


def test_rejects_bad_side():
    with pytest.raises(ValueError):
        cost_breakdown(N, 'HOLD', 'CNC')


def test_rejects_bad_segment():
    with pytest.raises(ValueError):
        cost_breakdown(N, 'BUY', 'NRML')
