"""F&O backtest engine — pure helpers + the report contract (no DB)."""

from datetime import date

from terminal_in.backtest import fno_engine as F


def test_last_thursday_known_months():
    # July 2026: last Thursday is the 30th; Aug 2026: the 27th
    assert F._last_thursday(2026, 7) == date(2026, 7, 30)
    assert F._last_thursday(2026, 8) == date(2026, 8, 27)
    assert F._last_thursday(2026, 7).weekday() == 3


def test_monthly_expiries_are_all_thursdays_in_range():
    exps = F._monthly_expiries(date(2025, 1, 1), date(2025, 12, 31))
    assert len(exps) == 12
    assert all(e.weekday() == 3 for e in exps)
    assert exps == sorted(exps)


def test_leg_cost_side_asymmetry():
    sell = F._leg_cost(100_000.0, 'SELL')
    buy = F._leg_cost(100_000.0, 'BUY')
    assert sell > 0 and buy > 0
    assert sell > buy                      # options STT (sell side) dominates the stamp (buy)


def test_report_contract_and_winrate():
    trades = [
        {'entry_date': '2024-01-01', 'expiry': '2024-01-25', 'net': 500, 'cost': 50,
         'credit': 40, 'equity': 1_000_500, 'win': True},
        {'entry_date': '2024-02-01', 'expiry': '2024-02-29', 'net': -300, 'cost': 50,
         'credit': 35, 'equity': 1_000_200, 'win': False},
        {'entry_date': '2024-03-01', 'expiry': '2024-03-28', 'net': 200, 'cost': 50,
         'credit': 38, 'equity': 1_000_400, 'win': True},
    ]
    r = F._report('iron_condor', trades, [(t['expiry'], t['equity']) for t in trades],
                  capital=1_000_000.0, years=1)
    assert r['trades'] == 3
    assert r['win_rate'] == round(2 / 3, 3)
    assert r['theoretical'] is True
    for k in ('cagr_pct', 'max_drawdown_pct', 'sharpe_monthly_ann', 'total_cost', 'per_year'):
        assert k in r


def test_report_empty():
    r = F._report('iron_condor', [], [], 1_000_000.0, 10)
    assert r['trades'] == 0
