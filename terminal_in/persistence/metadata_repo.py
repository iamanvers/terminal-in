"""
MetadataRepo — DuckDB-backed analytical metadata store.

Stores backtest results, strategy performance history, DSA rebalance history,
model training runs, agent evaluations, strategy versions, daily summaries,
regime attribution, and experiment runs.

Gracefully degrades to a no-op stub if DuckDB is not installed.
Install: pip install duckdb>=0.10.0
"""

import json
import logging
import threading
import uuid
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)

try:
    import duckdb
    _DUCKDB_AVAILABLE = True
except ImportError:
    _DUCKDB_AVAILABLE = False
    log.warning(
        'duckdb not installed — MetadataRepo is a no-op. '
        'Run: pip install duckdb>=0.10.0'
    )

_SCHEMA_STMTS = [
    """CREATE TABLE IF NOT EXISTS backtest_runs (
        run_id VARCHAR PRIMARY KEY,
        strategy_id VARCHAR,
        symbols_json VARCHAR,
        start_date VARCHAR,
        end_date VARCHAR,
        initial_capital DOUBLE,
        slippage_pct DOUBLE,
        commission DOUBLE,
        benchmark VARCHAR,
        total_return DOUBLE,
        cagr DOUBLE,
        sharpe DOUBLE,
        sortino DOUBLE,
        max_drawdown DOUBLE,
        drawdown_duration_days INTEGER,
        volatility DOUBLE,
        hit_rate DOUBLE,
        avg_win DOUBLE,
        avg_loss DOUBLE,
        payoff_ratio DOUBLE,
        expectancy DOUBLE,
        num_trades INTEGER,
        exposure_time_pct DOUBLE,
        benchmark_return DOUBLE,
        alpha DOUBLE,
        artifact_path VARCHAR,
        status VARCHAR DEFAULT 'running',
        error_message VARCHAR,
        created_at TIMESTAMP DEFAULT current_timestamp,
        completed_at TIMESTAMP
    )""",

    """CREATE TABLE IF NOT EXISTS backtest_trades (
        trade_id VARCHAR,
        run_id VARCHAR,
        strategy_id VARCHAR,
        symbol VARCHAR,
        side VARCHAR,
        entry_time TIMESTAMP,
        exit_time TIMESTAMP,
        entry_price DOUBLE,
        exit_price DOUBLE,
        quantity INTEGER,
        gross_pnl DOUBLE,
        net_pnl DOUBLE,
        commission DOUBLE,
        slippage_cost DOUBLE,
        regime VARCHAR,
        exit_reason VARCHAR,
        holding_days DOUBLE,
        PRIMARY KEY (trade_id, run_id)
    )""",

    """CREATE TABLE IF NOT EXISTS strategy_performance_history (
        record_id VARCHAR PRIMARY KEY,
        strategy_id VARCHAR NOT NULL,
        date VARCHAR NOT NULL,
        total_trades INTEGER DEFAULT 0,
        wins INTEGER DEFAULT 0,
        losses INTEGER DEFAULT 0,
        win_rate DOUBLE DEFAULT 0.0,
        total_pnl DOUBLE DEFAULT 0.0,
        sharpe DOUBLE,
        max_drawdown DOUBLE,
        allocation DOUBLE,
        regime VARCHAR,
        updated_at TIMESTAMP DEFAULT current_timestamp
    )""",

    """CREATE TABLE IF NOT EXISTS dsa_rebalance_history (
        rebalance_id VARCHAR PRIMARY KEY,
        rebalanced_at TIMESTAMP NOT NULL,
        regime VARCHAR,
        allocations_json VARCHAR,
        reason VARCHAR,
        total_strategies INTEGER DEFAULT 0
    )""",

    """CREATE TABLE IF NOT EXISTS regime_attribution (
        record_id VARCHAR PRIMARY KEY,
        date VARCHAR NOT NULL,
        regime VARCHAR NOT NULL,
        strategy_id VARCHAR NOT NULL,
        num_trades INTEGER DEFAULT 0,
        total_pnl DOUBLE DEFAULT 0.0,
        win_rate DOUBLE DEFAULT 0.0,
        avg_confidence DOUBLE DEFAULT 0.0
    )""",

    """CREATE TABLE IF NOT EXISTS model_training_runs (
        run_id VARCHAR PRIMARY KEY,
        model_name VARCHAR NOT NULL,
        model_type VARCHAR DEFAULT 'hmm',
        version VARCHAR,
        training_start VARCHAR,
        training_end VARCHAR,
        features_json VARCHAR,
        n_regimes INTEGER,
        training_samples INTEGER,
        convergence_status VARCHAR,
        validation_metrics_json VARCHAR,
        artifact_path VARCHAR,
        trained_at TIMESTAMP DEFAULT current_timestamp,
        notes VARCHAR
    )""",

    """CREATE TABLE IF NOT EXISTS feature_importance (
        record_id VARCHAR PRIMARY KEY,
        model_run_id VARCHAR NOT NULL,
        feature VARCHAR NOT NULL,
        importance DOUBLE,
        rank INTEGER
    )""",

    """CREATE TABLE IF NOT EXISTS agent_evaluations (
        eval_id VARCHAR PRIMARY KEY,
        agent_id VARCHAR NOT NULL,
        evaluated_at TIMESTAMP NOT NULL,
        regime VARCHAR,
        india_vix DOUBLE,
        signal_generated BOOLEAN DEFAULT FALSE,
        signal_side VARCHAR,
        signal_confidence DOUBLE,
        signal_instrument VARCHAR,
        context_summary_json VARCHAR,
        duration_ms INTEGER
    )""",

    """CREATE TABLE IF NOT EXISTS strategy_versions (
        version_id VARCHAR PRIMARY KEY,
        strategy_id VARCHAR NOT NULL,
        version VARCHAR NOT NULL,
        status VARCHAR DEFAULT 'draft',
        parameters_json VARCHAR,
        description VARCHAR,
        backtest_run_id VARCHAR,
        promotion_notes VARCHAR,
        artifact_path VARCHAR,
        created_at TIMESTAMP DEFAULT current_timestamp,
        promoted_at TIMESTAMP
    )""",

    """CREATE TABLE IF NOT EXISTS daily_summaries (
        summary_id VARCHAR PRIMARY KEY,
        date VARCHAR UNIQUE NOT NULL,
        regime VARCHAR,
        nifty_return DOUBLE,
        vix_open DOUBLE,
        vix_close DOUBLE,
        total_trades INTEGER DEFAULT 0,
        strategy_trades INTEGER DEFAULT 0,
        manual_trades INTEGER DEFAULT 0,
        trades_rejected INTEGER DEFAULT 0,
        realized_pnl DOUBLE DEFAULT 0.0,
        unrealized_pnl DOUBLE DEFAULT 0.0,
        drawdown DOUBLE DEFAULT 0.0,
        best_trade_json VARCHAR,
        worst_trade_json VARCHAR,
        strategies_fired_json VARCHAR,
        risk_events_json VARCHAR,
        lessons VARCHAR,
        artifact_path VARCHAR,
        generated_at TIMESTAMP DEFAULT current_timestamp
    )""",

    """CREATE TABLE IF NOT EXISTS experiment_runs (
        experiment_id VARCHAR PRIMARY KEY,
        experiment_name VARCHAR NOT NULL,
        strategy_id VARCHAR,
        parameters_json VARCHAR,
        results_summary_json VARCHAR,
        backtest_run_ids_json VARCHAR,
        status VARCHAR DEFAULT 'running',
        created_at TIMESTAMP DEFAULT current_timestamp,
        completed_at TIMESTAMP
    )""",
]


class MetadataRepo:
    """
    DuckDB-backed store for analytical metadata.
    All methods are thread-safe via a single connection + lock.
    No-op if DuckDB is unavailable.
    """

    def __init__(self, path: str):
        self._path = path
        self._lock = threading.Lock()
        self._conn = None
        if not _DUCKDB_AVAILABLE:
            return
        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            self._conn = duckdb.connect(path)
            self._init_schema()
            log.info('MetadataRepo ready at %s', path)
        except Exception:
            log.exception('MetadataRepo init failed — metadata persistence disabled')
            self._conn = None

    def _init_schema(self) -> None:
        with self._lock:
            for stmt in _SCHEMA_STMTS:
                try:
                    self._conn.execute(stmt)
                except Exception as e:
                    log.debug('MetadataRepo schema stmt: %s', e)

    def _exec(self, sql: str, params: list | None = None) -> Any:
        if not self._conn:
            return None
        with self._lock:
            try:
                return self._conn.execute(sql, params or [])
            except Exception:
                log.exception('MetadataRepo query failed: %.120s', sql)
                return None

    def _fetch(self, sql: str, params: list | None = None) -> list:
        result = self._exec(sql, params)
        if result is None:
            return []
        try:
            return result.df().to_dict('records')
        except Exception:
            return []

    @property
    def available(self) -> bool:
        return self._conn is not None

    # ── Backtest runs ──────────────────────────────────────────────────────

    def insert_backtest_run(self, run: dict) -> str:
        run_id = run.get('run_id') or str(uuid.uuid4())
        self._exec(
            """INSERT OR REPLACE INTO backtest_runs
               (run_id, strategy_id, symbols_json, start_date, end_date,
                initial_capital, slippage_pct, commission, benchmark, status,
                artifact_path, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,current_timestamp)""",
            [run_id, run.get('strategy_id'), json.dumps(run.get('symbols', [])),
             run.get('start_date'), run.get('end_date'), run.get('initial_capital'),
             run.get('slippage_pct', 0.0003), run.get('commission', 20.0),
             run.get('benchmark', 'NIFTY 50'), run.get('status', 'running'),
             run.get('artifact_path', '')],
        )
        return run_id

    def complete_backtest_run(self, run_id: str, results: dict) -> None:
        self._exec(
            """UPDATE backtest_runs SET
               total_return=?, cagr=?, sharpe=?, sortino=?, max_drawdown=?,
               drawdown_duration_days=?, volatility=?, hit_rate=?, avg_win=?,
               avg_loss=?, payoff_ratio=?, expectancy=?, num_trades=?,
               exposure_time_pct=?, benchmark_return=?, alpha=?,
               status='completed', completed_at=current_timestamp, artifact_path=?
               WHERE run_id=?""",
            [results.get('total_return'), results.get('cagr'), results.get('sharpe'),
             results.get('sortino'), results.get('max_drawdown'),
             results.get('drawdown_duration_days'), results.get('volatility'),
             results.get('hit_rate'), results.get('avg_win'), results.get('avg_loss'),
             results.get('payoff_ratio'), results.get('expectancy'), results.get('num_trades'),
             results.get('exposure_time_pct'), results.get('benchmark_return'),
             results.get('alpha'), results.get('artifact_path', ''), run_id],
        )

    def fail_backtest_run(self, run_id: str, error: str) -> None:
        self._exec(
            "UPDATE backtest_runs SET status='failed', error_message=?, "
            "completed_at=current_timestamp WHERE run_id=?",
            [error, run_id],
        )

    def get_backtest_runs(self, strategy_id: Optional[str] = None,
                          limit: int = 50) -> list:
        if strategy_id:
            return self._fetch(
                "SELECT * FROM backtest_runs WHERE strategy_id=? "
                "ORDER BY created_at DESC LIMIT ?",
                [strategy_id, limit],
            )
        return self._fetch(
            "SELECT * FROM backtest_runs ORDER BY created_at DESC LIMIT ?", [limit],
        )

    def insert_backtest_trades_batch(self, run_id: str, trades: list) -> None:
        if not trades or not self._conn:
            return
        with self._lock:
            try:
                self._conn.execute('BEGIN')
                for t in trades:
                    self._conn.execute(
                        """INSERT OR REPLACE INTO backtest_trades
                           (trade_id, run_id, strategy_id, symbol, side,
                            entry_time, exit_time, entry_price, exit_price, quantity,
                            gross_pnl, net_pnl, commission, slippage_cost,
                            regime, exit_reason, holding_days)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        [t.get('trade_id', str(uuid.uuid4())), run_id,
                         t.get('strategy_id'), t.get('symbol'), t.get('side'),
                         t.get('entry_time'), t.get('exit_time'),
                         t.get('entry_price'), t.get('exit_price'), t.get('quantity'),
                         t.get('gross_pnl'), t.get('net_pnl'), t.get('commission', 20.0),
                         t.get('slippage_cost', 0.0), t.get('regime'),
                         t.get('exit_reason'), t.get('holding_days')],
                    )
                self._conn.execute('COMMIT')
            except Exception:
                self._conn.execute('ROLLBACK')
                log.exception('Failed to insert backtest trades batch')

    # ── Strategy performance history ───────────────────────────────────────

    def upsert_strategy_performance(self, record: dict) -> None:
        self._exec(
            """INSERT OR REPLACE INTO strategy_performance_history
               (record_id, strategy_id, date, total_trades, wins, losses,
                win_rate, total_pnl, sharpe, max_drawdown, allocation,
                regime, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,current_timestamp)""",
            [record.get('record_id') or str(uuid.uuid4()),
             record['strategy_id'], record['date'],
             record.get('total_trades', 0), record.get('wins', 0),
             record.get('losses', 0), record.get('win_rate', 0.0),
             record.get('total_pnl', 0.0), record.get('sharpe'),
             record.get('max_drawdown'), record.get('allocation'),
             record.get('regime')],
        )

    def get_strategy_performance_history(self, strategy_id: str,
                                         days: int = 90) -> list:
        return self._fetch(
            "SELECT * FROM strategy_performance_history "
            "WHERE strategy_id=? ORDER BY date DESC LIMIT ?",
            [strategy_id, days],
        )

    # ── DSA rebalance history ──────────────────────────────────────────────

    def insert_dsa_rebalance(self, regime: str, allocations: dict,
                              reason: str = '') -> None:
        self._exec(
            """INSERT INTO dsa_rebalance_history
               (rebalance_id, rebalanced_at, regime, allocations_json,
                reason, total_strategies)
               VALUES (?,current_timestamp,?,?,?,?)""",
            [str(uuid.uuid4()), regime, json.dumps(allocations),
             reason, len(allocations)],
        )

    def get_dsa_rebalance_history(self, limit: int = 50) -> list:
        return self._fetch(
            "SELECT * FROM dsa_rebalance_history ORDER BY rebalanced_at DESC LIMIT ?",
            [limit],
        )

    # ── Regime attribution ─────────────────────────────────────────────────

    def upsert_regime_attribution(self, record: dict) -> None:
        self._exec(
            """INSERT OR REPLACE INTO regime_attribution
               (record_id, date, regime, strategy_id, num_trades,
                total_pnl, win_rate, avg_confidence)
               VALUES (?,?,?,?,?,?,?,?)""",
            [record.get('record_id') or str(uuid.uuid4()),
             record['date'], record['regime'], record['strategy_id'],
             record.get('num_trades', 0), record.get('total_pnl', 0.0),
             record.get('win_rate', 0.0), record.get('avg_confidence', 0.0)],
        )

    def get_regime_attribution(self, regime: Optional[str] = None,
                                days: int = 90) -> list:
        if regime:
            return self._fetch(
                "SELECT * FROM regime_attribution WHERE regime=? "
                "ORDER BY date DESC LIMIT ?",
                [regime, days],
            )
        return self._fetch(
            "SELECT * FROM regime_attribution ORDER BY date DESC LIMIT ?", [days],
        )

    # ── Model training runs ────────────────────────────────────────────────

    def insert_model_training_run(self, record: dict) -> str:
        run_id = record.get('run_id') or str(uuid.uuid4())
        self._exec(
            """INSERT OR REPLACE INTO model_training_runs
               (run_id, model_name, model_type, version, training_start,
                training_end, features_json, n_regimes, training_samples,
                convergence_status, validation_metrics_json, artifact_path,
                trained_at, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,current_timestamp,?)""",
            [run_id, record['model_name'], record.get('model_type', 'hmm'),
             record.get('version'), record.get('training_start'),
             record.get('training_end'), json.dumps(record.get('features', [])),
             record.get('n_regimes'), record.get('training_samples'),
             record.get('convergence_status'),
             json.dumps(record.get('validation_metrics', {})),
             record.get('artifact_path', ''), record.get('notes', '')],
        )
        return run_id

    def get_model_training_runs(self, model_name: Optional[str] = None) -> list:
        if model_name:
            return self._fetch(
                "SELECT * FROM model_training_runs "
                "WHERE model_name=? ORDER BY trained_at DESC",
                [model_name],
            )
        return self._fetch(
            "SELECT * FROM model_training_runs ORDER BY trained_at DESC",
        )

    def insert_feature_importance_batch(self, model_run_id: str,
                                         features: list[dict]) -> None:
        if not features:
            return
        for i, f in enumerate(sorted(features, key=lambda x: x.get('importance', 0),
                                     reverse=True)):
            self._exec(
                "INSERT OR REPLACE INTO feature_importance "
                "(record_id, model_run_id, feature, importance, rank) "
                "VALUES (?,?,?,?,?)",
                [str(uuid.uuid4()), model_run_id, f['feature'],
                 f.get('importance', 0.0), i + 1],
            )

    # ── Agent evaluations ──────────────────────────────────────────────────

    def insert_agent_evaluation(self, record: dict) -> None:
        self._exec(
            """INSERT INTO agent_evaluations
               (eval_id, agent_id, evaluated_at, regime, india_vix,
                signal_generated, signal_side, signal_confidence,
                signal_instrument, context_summary_json, duration_ms)
               VALUES (?,?,current_timestamp,?,?,?,?,?,?,?,?)""",
            [record.get('eval_id') or str(uuid.uuid4()), record['agent_id'],
             record.get('regime'), record.get('india_vix'),
             bool(record.get('signal_generated', False)),
             record.get('signal_side'), record.get('signal_confidence'),
             record.get('signal_instrument'),
             json.dumps(record.get('context_summary', {})),
             record.get('duration_ms')],
        )

    def get_agent_evaluations(self, agent_id: str, limit: int = 100) -> list:
        return self._fetch(
            "SELECT * FROM agent_evaluations WHERE agent_id=? "
            "ORDER BY evaluated_at DESC LIMIT ?",
            [agent_id, limit],
        )

    # ── Strategy versions ──────────────────────────────────────────────────

    def insert_strategy_version(self, record: dict) -> str:
        version_id = record.get('version_id') or str(uuid.uuid4())
        self._exec(
            """INSERT OR REPLACE INTO strategy_versions
               (version_id, strategy_id, version, status, parameters_json,
                description, backtest_run_id, promotion_notes, artifact_path,
                created_at)
               VALUES (?,?,?,?,?,?,?,?,?,current_timestamp)""",
            [version_id, record['strategy_id'], record['version'],
             record.get('status', 'draft'),
             json.dumps(record.get('parameters', {})),
             record.get('description', ''), record.get('backtest_run_id'),
             record.get('promotion_notes', ''), record.get('artifact_path', '')],
        )
        return version_id

    def get_strategy_versions(self, strategy_id: str) -> list:
        return self._fetch(
            "SELECT * FROM strategy_versions WHERE strategy_id=? "
            "ORDER BY created_at DESC",
            [strategy_id],
        )

    def promote_strategy_version(self, version_id: str, new_status: str,
                                   notes: str = '') -> None:
        self._exec(
            "UPDATE strategy_versions SET status=?, promotion_notes=?, "
            "promoted_at=current_timestamp WHERE version_id=?",
            [new_status, notes, version_id],
        )

    # ── Daily summaries ────────────────────────────────────────────────────

    def upsert_daily_summary(self, record: dict) -> None:
        date = record['date']
        # DELETE+INSERT to handle UNIQUE(date) constraint — DuckDB INSERT OR REPLACE
        # only fires on PRIMARY KEY conflict, not UNIQUE columns.
        self._exec("DELETE FROM daily_summaries WHERE date=?", [date])
        self._exec(
            """INSERT INTO daily_summaries
               (summary_id, date, regime, nifty_return, vix_open, vix_close,
                total_trades, strategy_trades, manual_trades, trades_rejected,
                realized_pnl, unrealized_pnl, drawdown, best_trade_json,
                worst_trade_json, strategies_fired_json, risk_events_json,
                lessons, artifact_path, generated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,current_timestamp)""",
            [record.get('summary_id') or str(uuid.uuid4()), date,
             record.get('regime'), record.get('nifty_return'),
             record.get('vix_open'), record.get('vix_close'),
             record.get('total_trades', 0), record.get('strategy_trades', 0),
             record.get('manual_trades', 0), record.get('trades_rejected', 0),
             record.get('realized_pnl', 0.0), record.get('unrealized_pnl', 0.0),
             record.get('drawdown', 0.0),
             json.dumps(record.get('best_trade')),
             json.dumps(record.get('worst_trade')),
             json.dumps(record.get('strategies_fired', [])),
             json.dumps(record.get('risk_events', [])),
             record.get('lessons', ''), record.get('artifact_path', '')],
        )

    def get_daily_summaries(self, limit: int = 30) -> list:
        return self._fetch(
            "SELECT * FROM daily_summaries ORDER BY date DESC LIMIT ?", [limit],
        )

    def get_daily_summary(self, date: str) -> Optional[dict]:
        rows = self._fetch(
            "SELECT * FROM daily_summaries WHERE date=?", [date],
        )
        return rows[0] if rows else None

    # ── Experiment runs ────────────────────────────────────────────────────

    def insert_experiment_run(self, record: dict) -> str:
        experiment_id = record.get('experiment_id') or str(uuid.uuid4())
        self._exec(
            """INSERT INTO experiment_runs
               (experiment_id, experiment_name, strategy_id, parameters_json,
                results_summary_json, backtest_run_ids_json, status, created_at)
               VALUES (?,?,?,?,?,?,?,current_timestamp)""",
            [experiment_id, record['experiment_name'], record.get('strategy_id'),
             json.dumps(record.get('parameters', {})),
             json.dumps(record.get('results_summary')),
             json.dumps(record.get('backtest_run_ids', [])),
             record.get('status', 'running')],
        )
        return experiment_id

    def complete_experiment_run(self, experiment_id: str,
                                 results_summary: dict) -> None:
        self._exec(
            "UPDATE experiment_runs SET status='completed', "
            "results_summary_json=?, completed_at=current_timestamp "
            "WHERE experiment_id=?",
            [json.dumps(results_summary), experiment_id],
        )

    def get_experiment_runs(self, strategy_id: Optional[str] = None) -> list:
        if strategy_id:
            return self._fetch(
                "SELECT * FROM experiment_runs WHERE strategy_id=? "
                "ORDER BY created_at DESC",
                [strategy_id],
            )
        return self._fetch(
            "SELECT * FROM experiment_runs ORDER BY created_at DESC",
        )

    def close(self) -> None:
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
