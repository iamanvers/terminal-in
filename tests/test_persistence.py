"""
Tests for the TERMINAL//IN persistence layer.

Covers:
  - DB (SQLite): new tables and round-trip read/write after re-open
  - MetadataRepo (DuckDB): core methods (skipped if duckdb unavailable)
  - ArtifactStore: save/load/list file artifacts
"""

import json
import time
import uuid
from pathlib import Path

import pytest

from terminal_in.db import DB
from terminal_in.persistence.artifact_store import ArtifactStore

# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_db(tmp_path):
    """Fresh in-memory-equivalent SQLite DB in a temp dir."""
    return DB(tmp_path / 'test.sqlite')


@pytest.fixture
def tmp_artifacts(tmp_path):
    return ArtifactStore(tmp_path / 'artifacts')


@pytest.fixture
def tmp_metadata(tmp_path):
    try:
        from terminal_in.persistence.metadata_repo import MetadataRepo
        repo = MetadataRepo(str(tmp_path / 'test.duckdb'))
        return repo
    except ImportError:
        pytest.skip('duckdb not installed')


# ── DB: orders ────────────────────────────────────────────────────────────────

def test_insert_and_get_order(tmp_db):
    order_id = str(uuid.uuid4())
    signal_id = str(uuid.uuid4())
    tmp_db.insert_order({
        'order_id': order_id,
        'signal_id': signal_id,
        'strategy_id': 'S1',
        'instrument_token': 256265,
        'side': 'BUY',
        'quantity': 10,
        'confidence': 0.72,
        'regime': 'bull',
        'status': 'approved',
    })
    orders = tmp_db.get_orders()
    assert len(orders) == 1
    assert orders[0]['order_id'] == order_id
    assert orders[0]['signal_id'] == signal_id
    assert orders[0]['status'] == 'approved'


def test_update_order_status(tmp_db):
    order_id = str(uuid.uuid4())
    tmp_db.insert_order({
        'order_id': order_id, 'signal_id': None,
        'strategy_id': 'S2', 'instrument_token': 260105,
        'side': 'BUY', 'quantity': 5,
    })
    tmp_db.update_order(order_id, status='filled', fill_price=45000.0)
    orders = tmp_db.get_orders()
    assert orders[0]['status'] == 'filled'
    assert orders[0]['fill_price'] == 45000.0


# ── DB: signal lineage ────────────────────────────────────────────────────────

def test_signal_lineage_round_trip(tmp_db):
    signal_id = str(uuid.uuid4())
    tmp_db.insert_signal_lineage({
        'signal_id': signal_id,
        'strategy_id': 'S5',
        'instrument_token': 1510401,
        'side': 'BUY',
        'generated_at': int(time.time() * 1000),
        'regime': 'bull',
        'confidence': 0.68,
        'risk_approved': True,
        'risk_checks': {'vix_hard_stop': True, 'confidence_ok': True},
    })
    record = tmp_db.get_signal_lineage(signal_id)
    assert record is not None
    assert record['signal_id'] == signal_id
    assert record['risk_approved'] == 1
    checks = json.loads(record['risk_checks_json'])
    assert checks['vix_hard_stop'] is True


def test_lineage_update_with_fill(tmp_db):
    signal_id = str(uuid.uuid4())
    trade_id = f'S5_123456_{int(time.time()*1000)}'
    tmp_db.insert_signal_lineage({
        'signal_id': signal_id, 'strategy_id': 'S5',
        'instrument_token': 1510401, 'side': 'BUY',
        'generated_at': int(time.time() * 1000),
        'risk_approved': True,
    })
    tmp_db.update_signal_lineage(
        signal_id,
        fill_price=1250.50,
        fill_time=int(time.time() * 1000),
        trade_id=trade_id,
    )
    record = tmp_db.get_signal_lineage(signal_id)
    assert record['fill_price'] == pytest.approx(1250.50)
    assert record['trade_id'] == trade_id


def test_lineage_update_with_pnl(tmp_db):
    signal_id = str(uuid.uuid4())
    tmp_db.insert_signal_lineage({
        'signal_id': signal_id, 'strategy_id': 'S4',
        'instrument_token': 408065, 'side': 'SELL',
        'generated_at': int(time.time() * 1000),
        'risk_approved': True,
    })
    tmp_db.update_signal_lineage(
        signal_id, trade_pnl=-320.0, trade_exit_reason='stop_loss',
    )
    record = tmp_db.get_signal_lineage(signal_id)
    assert record['trade_pnl'] == pytest.approx(-320.0)
    assert record['trade_exit_reason'] == 'stop_loss'


def test_get_recent_lineage(tmp_db):
    for i in range(5):
        sid = str(uuid.uuid4())
        tmp_db.insert_signal_lineage({
            'signal_id': sid, 'strategy_id': f'S{i+1}',
            'instrument_token': 256265, 'side': 'BUY',
            'generated_at': int(time.time() * 1000) + i,
            'risk_approved': i % 2 == 0,
        })
    lineage = tmp_db.get_recent_lineage(limit=10)
    assert len(lineage) == 5


# ── DB: trade journal ─────────────────────────────────────────────────────────

def test_trade_journal_upsert_and_read(tmp_db):
    trade_id = f'S1_123_{int(time.time()*1000)}'
    # Insert trade first (FK-like dependency)
    tmp_db.insert_trade({
        'trade_id': trade_id, 'strategy_id': 'S1',
        'instrument_id': 256265, 'side': 'BUY',
        'entry_price': 22000.0, 'quantity': 1,
    })
    tmp_db.upsert_trade_journal({
        'trade_id': trade_id,
        'entry_reason': 'ORB breakout confirmed at 09:20',
        'strategy_rationale': 'S1 triggered on NIFTY gap up',
        'review_status': 'pending',
    })
    journal = tmp_db.get_trade_journal(trade_id)
    assert journal is not None
    assert journal['entry_reason'] == 'ORB breakout confirmed at 09:20'
    assert journal['review_status'] == 'pending'


def test_trade_journal_update_on_close(tmp_db):
    trade_id = f'S2_456_{int(time.time()*1000)}'
    tmp_db.insert_trade({
        'trade_id': trade_id, 'strategy_id': 'S2',
        'instrument_id': 260105, 'side': 'BUY',
        'entry_price': 45000.0, 'quantity': 1,
    })
    # Create on open
    tmp_db.upsert_trade_journal({'trade_id': trade_id, 'entry_reason': 'breakout'})
    # Update on close
    tmp_db.upsert_trade_journal({
        'trade_id': trade_id,
        'exit_reason': 'target',
        'lesson': 'Held through volatility — correct decision',
        'review_status': 'reviewed',
        'rating': 4,
    })
    journal = tmp_db.get_trade_journal(trade_id)
    assert journal['exit_reason'] == 'target'
    assert journal['review_status'] == 'reviewed'
    assert journal['rating'] == 4
    assert journal['entry_reason'] == 'breakout'  # preserved from original


# ── DB: agent state ───────────────────────────────────────────────────────────

def test_agent_state_round_trip(tmp_db):
    tmp_db.save_agent_state('S5', {
        'status': 'running',
        'last_evaluated_at': int(time.time() * 1000),
        'confidence_threshold': 0.55,
        'last_signal': {'side': 'BUY', 'instrument_id': 1510401},
    })
    state = tmp_db.get_agent_state('S5')
    assert state is not None
    assert state['status'] == 'running'
    assert state['confidence_threshold'] == pytest.approx(0.55)
    sig = json.loads(state['last_signal_json'])
    assert sig['side'] == 'BUY'


def test_agent_state_survives_reopen(tmp_path):
    db1 = DB(tmp_path / 'test.sqlite')
    db1.save_agent_state('S1', {'status': 'paused', 'confidence_threshold': 0.6})
    db2 = DB(tmp_path / 'test.sqlite')
    state = db2.get_agent_state('S1')
    assert state['status'] == 'paused'


def test_get_all_agent_states(tmp_db):
    for sid in ['S1', 'S2', 'S3']:
        tmp_db.save_agent_state(sid, {'status': 'running'})
    states = tmp_db.get_all_agent_states()
    assert len(states) == 3
    assert {s['agent_id'] for s in states} == {'S1', 'S2', 'S3'}


# ── DB: risk decisions ────────────────────────────────────────────────────────

def test_risk_decision_persist(tmp_db):
    signal_id = str(uuid.uuid4())
    tmp_db.insert_risk_decision({
        'signal_id': signal_id,
        'strategy_id': 'S8',
        'instrument_token': 264969,
        'approved': True,
        'checks': {'vix_hard_stop': True, 'confidence_ok': True},
        'daily_pnl': -1200.0,
        'equity': 998800.0,
        'drawdown': 0.0012,
        'india_vix': 14.2,
    })
    decisions = tmp_db.get_risk_decisions(strategy_id='S8')
    assert len(decisions) == 1
    d = decisions[0]
    assert d['signal_id'] == signal_id
    assert d['approved'] == 1
    checks = json.loads(d['checks_json'])
    assert checks['confidence_ok'] is True


# ── DB: portfolio snapshots ───────────────────────────────────────────────────

def test_portfolio_snapshot_series(tmp_db):
    base = int(time.time() * 1000)
    for i in range(10):
        tmp_db.insert_portfolio_snapshot({
            'equity': 1_000_000 + i * 500,
            'daily_pnl': i * 500,
            'drawdown': 0.0,
            'open_positions': i % 3,
            'recorded_at': base + i * 60_000,
        })
    snaps = tmp_db.get_portfolio_snapshots(limit=5)
    assert len(snaps) == 5
    assert snaps[0]['equity'] > snaps[-1]['equity']  # most recent first


# ── DB: event bus log ─────────────────────────────────────────────────────────

def test_event_bus_log(tmp_db):
    tmp_db.log_event('strategy.signal', {'strategy_id': 'S1', 'side': 'BUY'})
    tmp_db.log_event('order.approved', {'strategy_id': 'S1'})
    tmp_db.log_event('trade.opened', {'trade_id': 'abc'})
    all_events = tmp_db.get_recent_events()
    assert len(all_events) == 3
    signal_events = tmp_db.get_recent_events(topic='strategy.signal')
    assert len(signal_events) == 1


# ── DB: data persists across restart ─────────────────────────────────────────

def test_full_persistence_round_trip(tmp_path):
    """Write all new table types, close, reopen, verify data is still there."""
    db_path = tmp_path / 'persist_test.sqlite'

    db1 = DB(db_path)
    signal_id = str(uuid.uuid4())
    db1.insert_signal_lineage({
        'signal_id': signal_id, 'strategy_id': 'S9',
        'instrument_token': 256265, 'side': 'BUY',
        'generated_at': int(time.time() * 1000), 'risk_approved': True,
    })
    db1.insert_risk_decision({'signal_id': signal_id, 'strategy_id': 'S9',
                               'approved': True, 'checks': {}})
    db1.save_agent_state('S9', {'status': 'running', 'confidence_threshold': 0.45})

    # Simulate restart by creating a new DB instance on the same file
    db2 = DB(db_path)
    lineage = db2.get_signal_lineage(signal_id)
    assert lineage is not None, 'Signal lineage lost on restart'
    decisions = db2.get_risk_decisions(strategy_id='S9')
    assert len(decisions) == 1, 'Risk decision lost on restart'
    state = db2.get_agent_state('S9')
    assert state['status'] == 'running', 'Agent state lost on restart'


# ── ArtifactStore ─────────────────────────────────────────────────────────────

def test_artifact_store_directories(tmp_artifacts):
    base = tmp_artifacts._base
    for sub in ['backtests', 'models', 'reports',
                'strategy_versions', 'daily_debriefs', 'exports']:
        assert (base / sub).is_dir(), f'{sub} directory missing'


def test_save_and_load_json(tmp_artifacts):
    data = {'run_id': 'abc123', 'sharpe': 1.42, 'trades': 87}
    path = tmp_artifacts.save_json('backtests', 'run_abc123', data)
    assert path.exists()
    loaded = tmp_artifacts.load_json('backtests', 'run_abc123')
    assert loaded['sharpe'] == pytest.approx(1.42)
    assert loaded['trades'] == 87


def test_save_and_load_model(tmp_artifacts):
    model = {'weights': [0.1, 0.2, 0.7], 'type': 'hmm'}
    path = tmp_artifacts.save_model('hmm_v1', model)
    assert path.exists()
    loaded = tmp_artifacts.load_model('hmm_v1')
    assert loaded['type'] == 'hmm'
    assert tmp_artifacts.model_exists('hmm_v1')
    assert not tmp_artifacts.model_exists('nonexistent')


def test_save_daily_debrief(tmp_artifacts):
    summary = {
        'date': '2026-04-28',
        'regime': 'bull',
        'realized_pnl': 4500.0,
        'total_trades': 3,
    }
    md = '# Daily Debrief 2026-04-28\n\nBull market day. 3 trades, +₹4500.'
    paths = tmp_artifacts.save_daily_debrief('2026-04-28', summary, md)
    assert paths['json'].exists()
    assert paths['md'].exists()
    loaded = tmp_artifacts.load_daily_debrief('2026-04-28')
    assert loaded['realized_pnl'] == pytest.approx(4500.0)
    debriefs = tmp_artifacts.list_daily_debriefs()
    assert '2026-04-28' in debriefs


def test_save_csv_export(tmp_artifacts):
    rows = [
        {'trade_id': 'T1', 'pnl': 1200.0, 'side': 'BUY'},
        {'trade_id': 'T2', 'pnl': -300.0, 'side': 'SELL'},
    ]
    path = tmp_artifacts.save_csv_export('trades_export', rows)
    assert path.exists()
    content = path.read_text()
    assert 'trade_id' in content
    assert 'T1' in content


def test_load_missing_artifact_returns_none(tmp_artifacts):
    assert tmp_artifacts.load_json('backtests', 'nonexistent') is None
    assert tmp_artifacts.load_model('nonexistent') is None


# ── MetadataRepo (DuckDB) ─────────────────────────────────────────────────────

def test_metadata_repo_available(tmp_metadata):
    assert tmp_metadata.available


def test_backtest_run_lifecycle(tmp_metadata):
    run_id = tmp_metadata.insert_backtest_run({
        'strategy_id': 'S5',
        'symbols': ['AXISBANK', 'SBIN'],
        'start_date': '2024-01-01',
        'end_date': '2026-01-01',
        'initial_capital': 1_000_000,
    })
    tmp_metadata.complete_backtest_run(run_id, {
        'total_return': 0.34, 'cagr': 0.16, 'sharpe': 1.82,
        'sortino': 2.1, 'max_drawdown': -0.08, 'num_trades': 52,
        'hit_rate': 0.61, 'artifact_path': f'data/artifacts/backtests/{run_id}.json',
    })
    runs = tmp_metadata.get_backtest_runs(strategy_id='S5')
    assert len(runs) == 1
    assert runs[0]['status'] == 'completed'
    assert runs[0]['sharpe'] == pytest.approx(1.82)


def test_dsa_rebalance_history(tmp_metadata):
    tmp_metadata.insert_dsa_rebalance(
        regime='bull',
        allocations={'S1': 0.20, 'S2': 0.15, 'S5': 0.25},
        reason='monthly_rebalance',
    )
    history = tmp_metadata.get_dsa_rebalance_history()
    assert len(history) == 1
    allocs = json.loads(history[0]['allocations_json'])
    assert allocs['S5'] == pytest.approx(0.25)


def test_daily_summary_upsert(tmp_metadata):
    tmp_metadata.upsert_daily_summary({
        'date': '2026-04-28',
        'regime': 'bull',
        'nifty_return': 0.0082,
        'vix_open': 13.4,
        'vix_close': 12.8,
        'total_trades': 4,
        'realized_pnl': 6200.0,
        'drawdown': 0.002,
        'lessons': 'Held through midday chop — right call.',
    })
    summary = tmp_metadata.get_daily_summary('2026-04-28')
    assert summary is not None
    assert summary['realized_pnl'] == pytest.approx(6200.0)
    assert summary['regime'] == 'bull'


def test_agent_evaluation_persist(tmp_metadata):
    tmp_metadata.insert_agent_evaluation({
        'agent_id': 'S5',
        'regime': 'bull',
        'india_vix': 13.2,
        'signal_generated': True,
        'signal_side': 'BUY',
        'signal_confidence': 0.71,
        'signal_instrument': 'AXISBANK',
        'duration_ms': 42,
    })
    evals = tmp_metadata.get_agent_evaluations('S5')
    assert len(evals) == 1
    assert evals[0]['signal_confidence'] == pytest.approx(0.71)


def test_metadata_repo_survives_reopen(tmp_path):
    from terminal_in.persistence.metadata_repo import MetadataRepo
    db_path = str(tmp_path / 'meta.duckdb')

    repo1 = MetadataRepo(db_path)
    run_id = repo1.insert_backtest_run({
        'strategy_id': 'S1', 'start_date': '2025-01-01', 'end_date': '2026-01-01',
    })
    repo1.close()

    repo2 = MetadataRepo(db_path)
    runs = repo2.get_backtest_runs()
    assert len(runs) == 1
    assert runs[0]['run_id'] == run_id
    repo2.close()
