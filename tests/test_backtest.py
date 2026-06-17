"""Unit tests for the backtest engine v2 (terminal_in/backtest/engine.py).

These exercise the PURE functions (indicators, regime hysteresis, lens rules)
and the report/output contract with constructed in-memory frames passed directly
to the helpers. No synthetic data is persisted to ohlcv_* tables or the tick path
— the REAL-DATA-ONLY mandate is about live/stored market data, not unit fixtures.
"""

import numpy as np
import pandas as pd

from terminal_in.backtest.engine import (
    _indicators, _regime_series, _lenses, _report, Trade, CAPITAL,
    _split_by_conf_gate,
)


def _frame(n=300, base=100.0, trend=0.0):
    idx = pd.date_range(end=pd.Timestamp('2024-01-01'), periods=n, freq='D')
    close = base + np.arange(n) * trend
    return pd.DataFrame({
        'open': close, 'high': close + 1.0, 'low': close - 1.0,
        'close': close, 'volume': 1000.0,
    }, index=idx)


# ── indicators ────────────────────────────────────────────────────────────────

def test_indicators_columns():
    out = _indicators(_frame(120, trend=0.2))
    for col in ('rsi', 'ema20', 'ema50', 'atr', 'hh252', 'vol_avg20'):
        assert col in out.columns
    # RSI bounded 0..100, filled (no NaN leak)
    assert out['rsi'].between(0, 100).all()
    assert not out['rsi'].isna().any()


def test_indicators_rsi_high_on_uptrend():
    # Rising trend WITH minor pullbacks (a monotonic series has zero down-days
    # → RSI is undefined → the real point is: net gains dominate losses).
    n = 120
    idx = pd.date_range(end=pd.Timestamp('2024-01-01'), periods=n, freq='D')
    # 4 up-days (+1.2) for every down-day (-0.8): real losses exist, but gains
    # dominate → RSI should sit well above 60.
    deltas = np.where(np.arange(n) % 5 == 4, -0.8, 1.2)
    close = 100.0 + np.cumsum(deltas)
    df = pd.DataFrame({'open': close, 'high': close + 1, 'low': close - 1,
                       'close': close, 'volume': 1000.0}, index=idx)
    out = _indicators(df)
    assert float(out['rsi'].iloc[-1]) > 60      # persistent gains → high RSI


# ── regime hysteresis (3 consecutive days before a switch) ─────────────────────

def test_regime_hysteresis_requires_three_days():
    # 60 flat days (sideways) then a strong up-move; the regime must NOT flip on
    # the first qualifying day — it needs 3 consecutive.
    n = 80
    idx = pd.date_range(end=pd.Timestamp('2024-01-01'), periods=n, freq='D')
    close = np.concatenate([np.full(60, 100.0), 100.0 + np.arange(20) * 3.0])
    nifty = pd.DataFrame({'open': close, 'high': close + 1, 'low': close - 1,
                          'close': close, 'volume': 1.0}, index=idx)
    regimes = _regime_series(nifty, None)
    seq = [regimes[d] for d in idx]
    # Somewhere after the move starts it becomes bullish, but not instantly.
    assert 'sideways' in seq
    # The switch to a bull regime lags the raw signal by >=2 extra days.
    first_bull = next((i for i, r in enumerate(seq) if r in ('bull', 'strong_bull')), None)
    assert first_bull is None or first_bull >= 62


def test_regime_high_vol_on_vix_spike():
    n = 40
    idx = pd.date_range(end=pd.Timestamp('2024-01-01'), periods=n, freq='D')
    close = np.full(n, 100.0)
    nifty = pd.DataFrame({'open': close, 'high': close + 1, 'low': close - 1,
                          'close': close, 'volume': 1.0}, index=idx)
    vix_close = np.concatenate([np.full(30, 14.0), np.full(10, 30.0)])  # spike >25
    vix = pd.DataFrame({'open': vix_close, 'high': vix_close, 'low': vix_close,
                        'close': vix_close, 'volume': 1.0}, index=idx)
    regimes = _regime_series(nifty, vix)
    assert regimes[idx[-1]] == 'high_vol'


# ── lens rules ─────────────────────────────────────────────────────────────────

def test_lens_s4_fires_on_oversold():
    row = pd.Series({'close': 95.0, 'rsi': 28.0, 'ema20': 100.0, 'ema50': 105.0,
                     'hh252': 120.0, 'vol': 1000.0, 'vol_avg20': 1000.0})
    lenses = dict(_lenses(row, 'sideways'))
    assert 'S4' in lenses
    assert 0 < lenses['S4'] <= 0.90


def test_lens_s2_blocked_in_bear():
    # price at a fresh 52w high with volume, but bear regime must suppress S2
    row = pd.Series({'close': 121.0, 'rsi': 60.0, 'ema20': 110.0, 'ema50': 105.0,
                     'hh252': 120.0, 'vol': 2000.0, 'vol_avg20': 1000.0})
    assert 'S2' not in dict(_lenses(row, 'bear'))
    assert 'S2' in dict(_lenses(row, 'bull'))


# ── LLM confidence gate (planner='llm' cost control) ───────────────────────────

def _cand(sym, conf):
    return {'symbol': sym, 'conf_smoothed': conf, 'ev': 1.5}


def test_conf_gate_splits_strong_from_ambiguous():
    elig = [_cand('A', 0.70), _cand('B', 0.55), _cand('C', 0.60), _cand('D', 0.45)]
    strong, ambiguous = _split_by_conf_gate(elig, 0.60)
    # >= gate auto-passes (no LLM); < gate is sent to the judge
    assert {c['symbol'] for c in strong} == {'A', 'C'}
    assert {c['symbol'] for c in ambiguous} == {'B', 'D'}


def test_conf_gate_disabled_sends_everything_to_judge():
    elig = [_cand('A', 0.90), _cand('B', 0.50)]
    strong, ambiguous = _split_by_conf_gate(elig, 0.0)
    assert strong == []
    assert len(ambiguous) == 2            # gate off → LLM judges the whole batch


def test_conf_gate_all_strong_spends_no_llm():
    elig = [_cand('A', 0.80), _cand('B', 0.75)]
    strong, ambiguous = _split_by_conf_gate(elig, 0.60)
    assert len(strong) == 2 and ambiguous == []   # no ambiguous → no LLM call this scan


# ── report / output contract ───────────────────────────────────────────────────

def _trade(pnl, exit_date='2024-01-10', strat='S4', regime='sideways'):
    return Trade('TCS', strat, 'BUY', '2024-01-01', 100.0, 98.0, 105.0, 10,
                 regime=regime, ev=1.5, exit_date=exit_date, exit_price=101.0,
                 exit_reason='target' if pnl > 0 else 'stop_loss', pnl=pnl)


def test_report_contract_and_curve_cap(tmp_path, monkeypatch):
    import terminal_in.backtest.engine as eng
    monkeypatch.setattr(eng, 'OUT_DIR', tmp_path)

    closed = [_trade(500), _trade(-200), _trade(300, exit_date='2025-02-02')]
    # 1000 daily equity points → curve must be downsampled to <= 301
    dates = pd.date_range('2023-01-01', periods=1000, freq='D')
    daily = [(str(d)[:10], CAPITAL + i) for i, d in enumerate(dates)]

    r = eng._report(closed, daily, days=1000, regimes={}, dates=list(dates))

    for k in ('equity_curve', 'recent_trades', 'symbols_tested', 'capital',
              'return_pct', 'sharpe', 'max_drawdown_pct', 'per_lens',
              'per_regime', 'walk_forward_years', 'trades'):
        assert k in r
    assert len(r['equity_curve']) <= 301
    assert r['trades']['n'] == 3
    assert r['trades']['win_rate'] == round(2 / 3, 3)
    # walk-forward splits by exit year
    assert set(r['walk_forward_years']) == {'2024', '2025'}
    # recent_trades capped at 60 and newest-first
    assert len(r['recent_trades']) == 3
    assert r['recent_trades'][0]['exit_date'] == '2025-02-02'
