"""Point-in-time fundamentals store — the no-lookahead guarantee + fail-closed dating.

The whole reason this store exists is to make a fundamental backtest HONEST, so the
tests hammer the one invariant that matters: a query as-of date D can never see a
filing dated after D.
"""

import pytest

from terminal_in.data_ingest import fundamentals as F


@pytest.fixture(autouse=True)
def _tmp_store(tmp_path, monkeypatch):
    monkeypatch.setattr(F, 'CACHE_DIR', tmp_path)
    monkeypatch.setattr(F, 'STORE', tmp_path / 'pit.parquet')


def _row(symbol, metric, period_end, filing_date, value, **kw):
    return {'symbol': symbol, 'metric': metric, 'period_end': period_end,
            'filing_date': filing_date, 'value': value, **kw}


def test_fail_closed_on_bad_date_or_metric():
    out = F.record_fundamentals([
        _row('RELIANCE', 'net_income', '2018-03-31', '2018-05-04', 36075),   # good
        _row('RELIANCE', 'net_income', '2018-03-31', 'not-a-date', 99999),   # bad date → drop
        _row('RELIANCE', 'made_up_metric', '2018-03-31', '2018-05-04', 1),   # bad metric → drop
        _row('RELIANCE', 'revenue', '2018-03-31', '2018-05-04', None),       # no value → drop
    ])
    assert out['ingested'] == 1
    assert out['dropped_unverifiable'] == 3


def test_get_pit_never_returns_a_future_filing():
    F.record_fundamentals([
        _row('TCS', 'eps', '2018-03-31', '2018-04-19', 67.0),   # FY18 filed Apr-2018
        _row('TCS', 'eps', '2019-03-31', '2019-04-12', 83.0),   # FY19 filed Apr-2019
    ])
    # before ANY filing → nothing public yet
    assert F.get_pit('TCS', 'eps', '2018-01-01') is None
    # between the two filings → only FY18 is public
    assert F.get_pit('TCS', 'eps', '2018-12-31') == 67.0
    # the day BEFORE the FY19 filing → still FY18 (no lookahead into the Apr-12 filing)
    assert F.get_pit('TCS', 'eps', '2019-04-11') == 67.0
    # on/after the FY19 filing → FY19
    assert F.get_pit('TCS', 'eps', '2019-04-12') == 83.0
    assert F.get_pit('TCS', 'eps', '2020-01-01') == 83.0


def test_as_of_snapshot_is_cross_sectional_and_pit():
    F.record_fundamentals([
        _row('A', 'roe' if False else 'net_income', '2020-03-31', '2020-05-01', 100),
        _row('B', 'net_income', '2020-03-31', '2020-07-01', 200),   # filed later
    ])
    snap = F.as_of_snapshot(['A', 'B'], 'net_income', '2020-06-01')
    assert snap == {'A': 100.0}            # B not public until July → excluded


def test_reingest_is_idempotent():
    rows = [_row('INFY', 'revenue', '2021-03-31', '2021-04-14', 100000)]
    F.record_fundamentals(rows)
    F.record_fundamentals(rows)            # same filing again
    df = F.load_fundamentals()
    assert len(df) == 1                    # deduped on (symbol, metric, period_end, filing_date)


def test_freshness_empty_then_populated():
    assert F.freshness()['rows'] == 0
    F.record_fundamentals([_row('SBIN', 'equity', '2022-03-31', '2022-05-13', 280000)])
    fr = F.freshness()
    assert fr['rows'] == 1 and fr['symbols'] == 1 and fr['latest_filing'] == '2022-05-13'
