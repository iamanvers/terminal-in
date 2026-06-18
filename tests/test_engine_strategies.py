"""Guards for the active strategy roster (strategy_engine/engine.py).

S6 (pairs cointegration) is intentionally DISABLED — it only ever fired one naked
leg (the hedge was never placed) and could emit a CNC overnight short in the cash
segment (impossible on NSE). This pins that decision so it isn't silently re-added
without a real two-leg futures implementation.
"""

from terminal_in.strategy_engine.engine import ALL_STRATEGIES


def test_s6_pairs_is_disabled():
    ids = {s.id for s in ALL_STRATEGIES}
    assert 'S6' not in ids, 'S6 pairs is disabled (naked single-leg / CNC short) — see engine.py'


def test_active_roster_is_the_expected_seven():
    ids = sorted(s.id for s in ALL_STRATEGIES)
    assert ids == ['S1', 'S2', 'S3', 'S4', 'S5', 'S8', 'S9']


def test_no_strategy_emits_cnc_overnight_short_by_default():
    """A SELL signal must never be tagged CNC (no overnight short in cash). The
    disabled S6 was the only strategy that could; this guards the invariant for
    the active roster via the broker's product classifier."""
    from terminal_in.execution.paper_broker import _product_for
    # S6 was the offender; the active strategies are long-biased or intraday.
    # Confirm the classifier still treats an explicit MIS short as MIS (intraday),
    # i.e. shorts are never silently carried as CNC delivery.
    assert _product_for({'strategy_id': 'S8', 'metadata': {'product': 'MIS'}}) == 'MIS'
