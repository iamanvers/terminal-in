"""
Thread-safe SQLite wrapper.
Each public method opens and closes its own connection — never share across threads.
Schema is auto-initialised on first instantiation; new columns are migrated on every start.
"""

import json
import logging
import sqlite3
import time as _time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

import pandas as pd

log = logging.getLogger(__name__)

DB_PATH = Path('./data/terminal_runtime.sqlite')
SCHEMA_PATH = Path('./db/init/schema.sql')


class DB:
    def __init__(self, path: Path = DB_PATH):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        schema_sql = SCHEMA_PATH.read_text() if SCHEMA_PATH.exists() else _EMBEDDED_SCHEMA
        with sqlite3.connect(str(self.path)) as conn:
            conn.executescript(schema_sql)
        self._run_migrations()

    def _run_migrations(self) -> None:
        """ADD new columns to existing tables without dropping data."""
        migrations = [
            'ALTER TABLE trades ADD COLUMN signal_id TEXT',
            'ALTER TABLE trades ADD COLUMN order_id TEXT',
            'ALTER TABLE trades ADD COLUMN stop_loss REAL',
            'ALTER TABLE trades ADD COLUMN target REAL',
            # Indexes for query performance
            'CREATE INDEX IF NOT EXISTS idx_trades_exit ON trades(exit_price)',
            'CREATE INDEX IF NOT EXISTS idx_trades_entry_time ON trades(entry_time)',
            'CREATE INDEX IF NOT EXISTS idx_trades_strategy ON trades(strategy_id)',
            'CREATE INDEX IF NOT EXISTS idx_orders_strategy ON orders(strategy_id)',
            'CREATE INDEX IF NOT EXISTS idx_signal_lineage_signal ON signal_lineage(signal_id)',
            'CREATE INDEX IF NOT EXISTS idx_risk_decisions_ts ON risk_decisions(decided_at)',
            # Agent decision memory (planner verdicts + hindsight outcomes)
            '''CREATE TABLE IF NOT EXISTS agent_decisions (
                decision_id       TEXT PRIMARY KEY,
                scan_id           INTEGER NOT NULL,
                decided_at        INTEGER NOT NULL,
                instrument_token  INTEGER NOT NULL,
                symbol            TEXT NOT NULL,
                side              TEXT NOT NULL,
                ev                REAL,
                confidence        REAL,
                persistence       INTEGER,
                price_at_decision REAL,
                sl_pct            REAL,
                target_pct        REAL,
                lenses_json       TEXT,
                regime            TEXT,
                india_vix         REAL,
                planner_action    TEXT NOT NULL,
                planner_reason    TEXT,
                size_factor       REAL DEFAULT 1.0,
                planner_mode      TEXT NOT NULL,
                llm_latency_ms    INTEGER,
                signal_id         TEXT,
                hindsight_at      INTEGER,
                hindsight_ret_pct REAL,
                hindsight_outcome TEXT
            )''',
            'CREATE INDEX IF NOT EXISTS idx_agdec_time ON agent_decisions(decided_at DESC)',
            'CREATE INDEX IF NOT EXISTS idx_agdec_token ON agent_decisions(instrument_token, decided_at DESC)',
            # Recursive training run history
            '''CREATE TABLE IF NOT EXISTS training_runs (
                run_id          TEXT PRIMARY KEY,
                started_at      INTEGER NOT NULL,
                finished_at     INTEGER,
                status          TEXT NOT NULL,
                max_steps       INTEGER,
                dataset_samples INTEGER,
                dataset_counts_json TEXT,
                initial_loss    REAL,
                final_loss      REAL,
                trained_steps   INTEGER,
                epochs          REAL,
                dataset_dir     TEXT,
                adapter_dir     TEXT,
                train_log       TEXT,
                error           TEXT
            )''',
            'CREATE INDEX IF NOT EXISTS idx_training_runs_time ON training_runs(started_at DESC)',
            # Operator settings — DB overrides on top of .env (PRD 5b.2)
            '''CREATE TABLE IF NOT EXISTS app_settings (
                key        TEXT PRIMARY KEY,
                value      TEXT NOT NULL,
                updated_at INTEGER NOT NULL
            )''',
            # Dedup news across restarts and across sources carrying the same story
            # (clean existing dupes first or the unique index creation no-ops)
            'DELETE FROM news_log WHERE id NOT IN (SELECT MIN(id) FROM news_log GROUP BY url)',
            'CREATE UNIQUE INDEX IF NOT EXISTS idx_news_url ON news_log(url)',
        ]
        with sqlite3.connect(str(self.path)) as conn:
            for stmt in migrations:
                try:
                    conn.execute(stmt)
                except sqlite3.OperationalError:
                    pass  # column already exists / index already exists

    @contextmanager
    def conn(self):
        c = sqlite3.connect(str(self.path), timeout=30, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA foreign_keys = ON')
        c.execute('PRAGMA journal_mode = WAL')
        try:
            yield c
        finally:
            c.close()

    # ── Ticks ────────────────────────────────────────────────────────────────

    def insert_ticks_batch(self, ticks: list) -> None:
        def _depth(t, side, field):
            return t.get('depth', {}).get(side, [{}])[0].get(field)

        rows = [
            (
                t.get('time_ms', int(_time.time() * 1000)),
                t['instrument_token'],
                t['last_price'],
                t.get('last_quantity'),
                t.get('volume'),
                _depth(t, 'buy', 'price'),
                _depth(t, 'sell', 'price'),
                _depth(t, 'buy', 'quantity'),
                _depth(t, 'sell', 'quantity'),
                t.get('oi'),
            )
            for t in ticks
        ]
        with self.conn() as c:
            c.executemany(
                '''INSERT OR IGNORE INTO ticks_current
                   (time, instrument_token, last_price, last_quantity, volume,
                    bid_price, ask_price, bid_qty, ask_qty, oi)
                   VALUES (?,?,?,?,?,?,?,?,?,?)''',
                rows,
            )

    def get_recent_ticks(self, token: int, limit: int = 500) -> list:
        with self.conn() as c:
            rows = c.execute(
                'SELECT * FROM ticks_current WHERE instrument_token=? ORDER BY time DESC LIMIT ?',
                (token, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    # ── OHLCV ────────────────────────────────────────────────────────────────

    def insert_ohlcv_1m_batch(self, bars: list) -> None:
        with self.conn() as c:
            c.executemany(
                '''INSERT OR REPLACE INTO ohlcv_1m
                   (bucket_time, instrument_token, open, high, low, close, volume, oi)
                   VALUES (?,?,?,?,?,?,?,?)''',
                [(b['bucket_time'], b['instrument_token'],
                  b['open'], b['high'], b['low'], b['close'], b['volume'], b.get('oi'))
                 for b in bars],
            )

    def insert_ohlcv_1d_batch(self, bars: list) -> None:
        with self.conn() as c:
            c.executemany(
                '''INSERT OR REPLACE INTO ohlcv_1d
                   (bucket_date, instrument_token, open, high, low, close, volume,
                    delivery_pct, fii_net, dii_net)
                   VALUES (?,?,?,?,?,?,?,?,?,?)''',
                [(b['date'], b['instrument_token'],
                  b['open'], b['high'], b['low'], b['close'], b['volume'],
                  b.get('delivery_pct'), b.get('fii_net'), b.get('dii_net'))
                 for b in bars],
            )

    def purge_nontrading_ohlcv_1d(self, token: int, start_date: str, real_dates: set) -> int:
        if not real_dates:
            return 0
        placeholders = ','.join('?' * len(real_dates))
        with self.conn() as c:
            cur = c.execute(
                f'''DELETE FROM ohlcv_1d WHERE instrument_token=?
                    AND bucket_date >= ?
                    AND bucket_date NOT IN ({placeholders})''',
                [token, start_date, *sorted(real_dates)],
            )
            return cur.rowcount

    def get_ohlcv_last_dates(self, tokens: list[int]) -> dict[int, str | None]:
        """Return {token: last_bucket_date_str} for each token. None if no data."""
        if not tokens:
            return {}
        placeholders = ','.join('?' * len(tokens))
        with self.conn() as c:
            rows = c.execute(
                f'SELECT instrument_token, MAX(bucket_date) AS last_date FROM ohlcv_1d '
                f'WHERE instrument_token IN ({placeholders}) GROUP BY instrument_token',
                tokens,
            ).fetchall()
        result: dict[int, str | None] = {t: None for t in tokens}
        for row in rows:
            result[row['instrument_token']] = row['last_date']
        return result

    def get_ohlcv_first_dates(self, tokens: list[int]) -> dict[int, str | None]:
        """Return {token: earliest_bucket_date_str} for each token. None if no data."""
        if not tokens:
            return {}
        placeholders = ','.join('?' * len(tokens))
        with self.conn() as c:
            rows = c.execute(
                f'SELECT instrument_token, MIN(bucket_date) AS first_date FROM ohlcv_1d '
                f'WHERE instrument_token IN ({placeholders}) GROUP BY instrument_token',
                tokens,
            ).fetchall()
        result: dict[int, str | None] = {t: None for t in tokens}
        for row in rows:
            result[row['instrument_token']] = row['first_date']
        return result

    def get_ohlcv_1d(self, token: int, limit: int = 300) -> pd.DataFrame:
        with self.conn() as c:
            rows = c.execute(
                '''SELECT bucket_date, open, high, low, close, volume
                   FROM ohlcv_1d WHERE instrument_token=?
                   ORDER BY bucket_date DESC LIMIT ?''',
                (token, limit),
            ).fetchall()
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame([dict(r) for r in rows])
        df['bucket_date'] = pd.to_datetime(df['bucket_date'])
        df = df.set_index('bucket_date').sort_index()
        return df

    def get_ohlcv_1m(self, token: int, limit: int = 500) -> pd.DataFrame:
        with self.conn() as c:
            rows = c.execute(
                '''SELECT bucket_time, open, high, low, close, volume
                   FROM ohlcv_1m WHERE instrument_token=?
                   ORDER BY bucket_time DESC LIMIT ?''',
                (token, limit),
            ).fetchall()
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame([dict(r) for r in rows])
        df['bucket_time'] = pd.to_datetime(df['bucket_time'], unit='ms', utc=True)
        df = df.set_index('bucket_time').sort_index()
        return df

    # Batch variants: ONE connection + ONE window-function query for the whole
    # universe instead of N round-trips. This is the hot path of every engine
    # cycle and orchestrator scan (72 symbols → 144 connections without these).

    def get_ohlcv_1d_all(self, tokens: list[int], limit: int = 300) -> dict[int, pd.DataFrame]:
        """{token: daily DataFrame} for every token, single query.
        Frames match get_ohlcv_1d exactly (DatetimeIndex, ascending)."""
        if not tokens:
            return {}
        placeholders = ','.join('?' * len(tokens))
        cols = ['instrument_token', 'bucket_date', 'open', 'high', 'low', 'close', 'volume']
        with self.conn() as c:
            cur = c.execute(
                f'''SELECT instrument_token, bucket_date, open, high, low, close, volume
                    FROM (
                      SELECT instrument_token, bucket_date, open, high, low, close, volume,
                             ROW_NUMBER() OVER (PARTITION BY instrument_token
                                                ORDER BY bucket_date DESC) AS rn
                      FROM ohlcv_1d WHERE instrument_token IN ({placeholders})
                    ) WHERE rn <= ?''',
                [*tokens, limit],
            )
            cur.row_factory = None   # raw tuples — skip 20k+ Row->dict conversions
            rows = cur.fetchall()
        if not rows:
            return {}
        df = pd.DataFrame(rows, columns=cols)
        # explicit format: ~10x faster than inference on 20k+ ISO date strings
        df['bucket_date'] = pd.to_datetime(df['bucket_date'], format='%Y-%m-%d')
        out: dict[int, pd.DataFrame] = {}
        for token, grp in df.groupby('instrument_token'):
            out[int(token)] = (grp.drop(columns=['instrument_token'])
                                  .set_index('bucket_date').sort_index())
        return out

    def get_ohlcv_1m_all(self, tokens: list[int], limit: int = 500) -> dict[int, pd.DataFrame]:
        """{token: 1m DataFrame} for every token, single query.
        Frames match get_ohlcv_1m exactly (UTC DatetimeIndex, ascending)."""
        if not tokens:
            return {}
        placeholders = ','.join('?' * len(tokens))
        cols = ['instrument_token', 'bucket_time', 'open', 'high', 'low', 'close', 'volume']
        with self.conn() as c:
            cur = c.execute(
                f'''SELECT instrument_token, bucket_time, open, high, low, close, volume
                    FROM (
                      SELECT instrument_token, bucket_time, open, high, low, close, volume,
                             ROW_NUMBER() OVER (PARTITION BY instrument_token
                                                ORDER BY bucket_time DESC) AS rn
                      FROM ohlcv_1m WHERE instrument_token IN ({placeholders})
                    ) WHERE rn <= ?''',
                [*tokens, limit],
            )
            cur.row_factory = None   # raw tuples — skip 35k+ Row->dict conversions
            rows = cur.fetchall()
        if not rows:
            return {}
        df = pd.DataFrame(rows, columns=cols)
        df['bucket_time'] = pd.to_datetime(df['bucket_time'], unit='ms', utc=True)
        out: dict[int, pd.DataFrame] = {}
        for token, grp in df.groupby('instrument_token'):
            out[int(token)] = (grp.drop(columns=['instrument_token'])
                                  .set_index('bucket_time').sort_index())
        return out

    # ── Trades ───────────────────────────────────────────────────────────────

    def insert_trade(self, trade: dict) -> None:
        token = trade.get('instrument_token') or trade.get('instrument_id', 0)

        entry_time = trade.get('entry_time')
        if entry_time is None:
            opened_at = trade.get('opened_at', '')
            try:
                from datetime import datetime, timezone
                entry_time = int(datetime.fromisoformat(opened_at).timestamp() * 1000)
            except Exception:
                entry_time = int(_time.time() * 1000)

        meta = dict(trade.get('metadata') or {})
        for key in ('stop_loss', 'target', 'time_exit', 'fill_price'):
            if trade.get(key) is not None:
                meta[key] = trade[key]

        with self.conn() as c:
            c.execute(
                '''INSERT OR IGNORE INTO trades
                   (trade_id, signal_id, order_id, strategy_id, instrument_token,
                    side, entry_time, entry_price, quantity,
                    stop_loss, target,
                    regime_at_entry, confidence, metadata_json, is_paper)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (
                    trade['trade_id'],
                    trade.get('signal_id'),
                    trade.get('order_id'),
                    trade.get('strategy_id', ''),
                    token,
                    trade.get('side', 'BUY'),
                    entry_time,
                    trade.get('entry_price', 0.0),
                    trade.get('quantity', 0),
                    float(trade.get('stop_loss') or 0),
                    float(trade.get('target') or 0),
                    trade.get('regime', trade.get('regime_at_entry')),
                    trade.get('confidence'),
                    json.dumps(meta),
                    int(trade.get('is_paper', True)),
                ),
            )

    def close_trade(self, trade_id: str, data: dict) -> None:
        exit_time = data.get('exit_time')
        if exit_time is None:
            closed_at = data.get('closed_at', '')
            try:
                from datetime import datetime
                exit_time = int(datetime.fromisoformat(closed_at).timestamp() * 1000)
            except Exception:
                exit_time = int(_time.time() * 1000)

        net_pnl = data.get('pnl', data.get('net_pnl', 0.0))

        with self.conn() as c:
            c.execute(
                '''UPDATE trades
                   SET exit_time=?, exit_price=?, exit_reason=?,
                       gross_pnl=?, costs=?, net_pnl=?
                   WHERE trade_id=?''',
                (
                    exit_time,
                    data.get('exit_price'),
                    data.get('exit_reason', 'unknown'),
                    net_pnl,
                    data.get('costs', 0.0),
                    net_pnl,
                    trade_id,
                ),
            )

    def get_open_trades(self) -> list:
        with self.conn() as c:
            rows = c.execute(
                'SELECT * FROM trades WHERE exit_time IS NULL ORDER BY entry_time DESC',
            ).fetchall()
        return [dict(r) for r in rows]

    def get_trades(self, strategy_id: Optional[str] = None, limit: int = 200) -> list:
        q = 'SELECT * FROM trades WHERE 1=1'
        params: list = []
        if strategy_id:
            q += ' AND strategy_id=?'
            params.append(strategy_id)
        q += ' ORDER BY entry_time DESC LIMIT ?'
        params.append(limit)
        with self.conn() as c:
            rows = c.execute(q, params).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            if d.get('metadata_json'):
                try:
                    d['metadata'] = json.loads(d['metadata_json'])
                except Exception:
                    d['metadata'] = {}
            result.append(d)
        return result

    def get_trade_by_id(self, trade_id: str) -> Optional[dict]:
        with self.conn() as c:
            row = c.execute('SELECT * FROM trades WHERE trade_id=?', (trade_id,)).fetchone()
        return dict(row) if row else None

    def get_closed_trades(self, limit: int = 50, strategy_id: Optional[str] = None) -> list:
        q = 'SELECT * FROM trades WHERE exit_price IS NOT NULL'
        params: list = []
        if strategy_id:
            q += ' AND strategy_id=?'
            params.append(strategy_id)
        q += ' ORDER BY exit_time DESC LIMIT ?'
        params.append(limit)
        with self.conn() as c:
            rows = c.execute(q, params).fetchall()
        return [dict(r) for r in rows]

    def get_trade_stats_sql(self) -> dict:
        """Compute all trade stats in SQL — no Python-side filtering."""
        today_ms = int(_time.time() * 1000) - 86_400_000
        with self.conn() as c:
            agg = c.execute(
                '''SELECT
                     COUNT(*) AS total_closed,
                     SUM(CASE WHEN net_pnl > 0 THEN 1 ELSE 0 END) AS wins,
                     SUM(CASE WHEN net_pnl <= 0 THEN 1 ELSE 0 END) AS losses,
                     COALESCE(SUM(net_pnl), 0) AS total_pnl,
                     COALESCE(AVG(CASE WHEN net_pnl > 0 THEN net_pnl ELSE NULL END), 0) AS avg_win,
                     COALESCE(AVG(CASE WHEN net_pnl <= 0 THEN net_pnl ELSE NULL END), 0) AS avg_loss,
                     COALESCE(MAX(net_pnl), 0) AS best_pnl,
                     COALESCE(MIN(net_pnl), 0) AS worst_pnl
                   FROM trades WHERE exit_price IS NOT NULL'''
            ).fetchone()
            today = c.execute(
                '''SELECT COUNT(*) AS today_trades,
                          COALESCE(SUM(CASE WHEN exit_price IS NOT NULL THEN net_pnl ELSE 0 END), 0) AS today_pnl
                   FROM trades WHERE entry_time >= ?''',
                (today_ms,),
            ).fetchone()
            by_strat_rows = c.execute(
                '''SELECT strategy_id,
                          COUNT(*) AS trades,
                          SUM(CASE WHEN net_pnl > 0 THEN 1 ELSE 0 END) AS wins,
                          COALESCE(SUM(net_pnl), 0) AS pnl
                   FROM trades WHERE exit_price IS NOT NULL
                   GROUP BY strategy_id''',
            ).fetchall()
        agg = dict(agg)
        today = dict(today)
        total_closed = agg['total_closed'] or 0
        wins = agg['wins'] or 0
        by_strategy = {}
        for r in by_strat_rows:
            r = dict(r)
            sid = r['strategy_id'] or 'MANUAL'
            by_strategy[sid] = {
                'trades': r['trades'],
                'wins': r['wins'],
                'pnl': round(r['pnl'], 2),
                'win_rate': round(r['wins'] / r['trades'], 3) if r['trades'] else 0.0,
            }
        return {
            'total_trades':    total_closed,
            'wins':            wins,
            'losses':          agg['losses'] or 0,
            'win_rate':        round(wins / total_closed, 3) if total_closed else 0.0,
            'total_pnl':       round(agg['total_pnl'], 2),
            'avg_win':         round(agg['avg_win'], 2),
            'avg_loss':        round(agg['avg_loss'], 2),
            'best_trade_pnl':  round(agg['best_pnl'], 2),
            'worst_trade_pnl': round(agg['worst_pnl'], 2),
            'today_trades':    today['today_trades'] or 0,
            'today_pnl':       round(today['today_pnl'], 2),
            'by_strategy':     by_strategy,
        }

    # ── Orders ───────────────────────────────────────────────────────────────

    def insert_order(self, order: dict) -> None:
        now = int(_time.time() * 1000)
        with self.conn() as c:
            c.execute(
                '''INSERT OR IGNORE INTO orders
                   (order_id, signal_id, trade_id, strategy_id, instrument_token,
                    side, quantity, price_at_signal, limit_price, stop_loss, target,
                    confidence, regime, status, risk_checks_json, metadata_json,
                    created_at, updated_at, is_paper)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (
                    order['order_id'],
                    order.get('signal_id'),
                    order.get('trade_id'),
                    order.get('strategy_id', ''),
                    order.get('instrument_token', 0),
                    order.get('side', 'BUY'),
                    order.get('quantity', 0),
                    order.get('price_at_signal'),
                    order.get('limit_price'),
                    order.get('stop_loss'),
                    order.get('target'),
                    order.get('confidence'),
                    order.get('regime'),
                    order.get('status', 'created'),
                    json.dumps(order.get('risk_checks', {})),
                    json.dumps(order.get('metadata', {})),
                    order.get('created_at', now),
                    now,
                    int(order.get('is_paper', True)),
                ),
            )

    def update_order(self, order_id: str, **fields) -> None:
        if not fields:
            return
        now = int(_time.time() * 1000)
        fields['updated_at'] = now
        cols = ', '.join(f'{k}=?' for k in fields)
        with self.conn() as c:
            c.execute(f'UPDATE orders SET {cols} WHERE order_id=?',
                      [*fields.values(), order_id])

    def get_orders(self, status: Optional[str] = None,
                   strategy_id: Optional[str] = None, limit: int = 200) -> list:
        q = 'SELECT * FROM orders WHERE 1=1'
        params: list = []
        if status:
            q += ' AND status=?'
            params.append(status)
        if strategy_id:
            q += ' AND strategy_id=?'
            params.append(strategy_id)
        q += ' ORDER BY created_at DESC LIMIT ?'
        params.append(limit)
        with self.conn() as c:
            rows = c.execute(q, params).fetchall()
        return [dict(r) for r in rows]

    # ── Signal lineage ────────────────────────────────────────────────────────

    def insert_signal_lineage(self, record: dict) -> None:
        now = int(_time.time() * 1000)
        with self.conn() as c:
            c.execute(
                '''INSERT OR IGNORE INTO signal_lineage
                   (lineage_id, signal_id, strategy_id, instrument_token, side,
                    generated_at, regime, regime_confidence, india_vix,
                    indicators_json, trigger_rule, confidence,
                    risk_approved, risk_checks_json, risk_reason, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (
                    record.get('lineage_id', str(uuid.uuid4())),
                    record['signal_id'],
                    record.get('strategy_id'),
                    record.get('instrument_token'),
                    record.get('side'),
                    record.get('generated_at', now),
                    record.get('regime'),
                    record.get('regime_confidence'),
                    record.get('india_vix'),
                    json.dumps(record.get('indicators', {})),
                    record.get('trigger_rule'),
                    record.get('confidence'),
                    int(record.get('risk_approved', 0)),
                    json.dumps(record.get('risk_checks', {})),
                    record.get('risk_reason'),
                    now,
                ),
            )

    def update_signal_lineage(self, signal_id: str, **fields) -> None:
        if not fields:
            return
        # Serialize any dict fields to JSON
        for k, v in fields.items():
            if isinstance(v, dict):
                fields[k] = json.dumps(v)
        cols = ', '.join(f'{k}=?' for k in fields)
        with self.conn() as c:
            c.execute(f'UPDATE signal_lineage SET {cols} WHERE signal_id=?',
                      [*fields.values(), signal_id])

    def get_signal_lineage(self, signal_id: str) -> Optional[dict]:
        with self.conn() as c:
            row = c.execute(
                'SELECT * FROM signal_lineage WHERE signal_id=?', (signal_id,),
            ).fetchone()
        return dict(row) if row else None

    def get_recent_lineage(self, limit: int = 100, strategy_id: Optional[str] = None) -> list:
        q = 'SELECT * FROM signal_lineage WHERE 1=1'
        params: list = []
        if strategy_id:
            q += ' AND strategy_id=?'
            params.append(strategy_id)
        q += ' ORDER BY generated_at DESC LIMIT ?'
        params.append(limit)
        with self.conn() as c:
            rows = c.execute(q, params).fetchall()
        return [dict(r) for r in rows]

    # ── Trade journal ─────────────────────────────────────────────────────────

    def upsert_trade_journal(self, record: dict) -> None:
        now = int(_time.time() * 1000)
        with self.conn() as c:
            c.execute(
                '''INSERT INTO trade_journal
                   (journal_id, trade_id, entry_reason, exit_reason,
                    strategy_rationale, manual_notes, mistake_tags_json,
                    review_status, lesson, rating, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(trade_id) DO UPDATE SET
                     exit_reason=excluded.exit_reason,
                     manual_notes=COALESCE(excluded.manual_notes, trade_journal.manual_notes),
                     mistake_tags_json=COALESCE(excluded.mistake_tags_json, trade_journal.mistake_tags_json),
                     review_status=excluded.review_status,
                     lesson=COALESCE(excluded.lesson, trade_journal.lesson),
                     rating=COALESCE(excluded.rating, trade_journal.rating),
                     updated_at=excluded.updated_at''',
                (
                    record.get('journal_id', str(uuid.uuid4())),
                    record['trade_id'],
                    record.get('entry_reason', ''),
                    record.get('exit_reason'),
                    record.get('strategy_rationale', ''),
                    record.get('manual_notes'),
                    json.dumps(record.get('mistake_tags', [])),
                    record.get('review_status', 'pending'),
                    record.get('lesson'),
                    record.get('rating'),
                    record.get('created_at', now),
                    now,
                ),
            )

    def get_trade_journal(self, trade_id: str) -> Optional[dict]:
        with self.conn() as c:
            row = c.execute(
                'SELECT * FROM trade_journal WHERE trade_id=?', (trade_id,),
            ).fetchone()
        return dict(row) if row else None

    def get_all_journal_entries(self, review_status: Optional[str] = None,
                                limit: int = 200) -> list:
        q = 'SELECT j.*, t.strategy_id, t.instrument_token, t.side, t.entry_price, t.net_pnl ' \
            'FROM trade_journal j LEFT JOIN trades t ON j.trade_id = t.trade_id WHERE 1=1'
        params: list = []
        if review_status:
            q += ' AND j.review_status=?'
            params.append(review_status)
        q += ' ORDER BY j.created_at DESC LIMIT ?'
        params.append(limit)
        with self.conn() as c:
            rows = c.execute(q, params).fetchall()
        return [dict(r) for r in rows]

    # ── Event bus log ─────────────────────────────────────────────────────────

    def log_event(self, topic: str, payload: dict) -> None:
        with self.conn() as c:
            c.execute(
                '''INSERT INTO event_bus_log (event_id, topic, payload_json, published_at)
                   VALUES (?,?,?,?)''',
                (str(uuid.uuid4()), topic, json.dumps(payload, default=str),
                 int(_time.time() * 1000)),
            )

    def get_recent_events(self, topic: Optional[str] = None, limit: int = 200) -> list:
        if topic:
            q = 'SELECT * FROM event_bus_log WHERE topic=? ORDER BY published_at DESC LIMIT ?'
            params = (topic, limit)
        else:
            q = 'SELECT * FROM event_bus_log ORDER BY published_at DESC LIMIT ?'
            params = (limit,)
        with self.conn() as c:
            rows = c.execute(q, params).fetchall()
        return [dict(r) for r in rows]

    # ── Agent state ───────────────────────────────────────────────────────────

    def save_agent_state(self, agent_id: str, state: dict) -> None:
        now = int(_time.time() * 1000)
        with self.conn() as c:
            c.execute(
                '''INSERT INTO agent_state
                   (agent_id, status, last_evaluated_at, last_signal_json,
                    confidence_threshold, last_error, heartbeat_at, metadata_json, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(agent_id) DO UPDATE SET
                     status=excluded.status,
                     last_evaluated_at=excluded.last_evaluated_at,
                     last_signal_json=COALESCE(excluded.last_signal_json, agent_state.last_signal_json),
                     confidence_threshold=excluded.confidence_threshold,
                     last_error=excluded.last_error,
                     heartbeat_at=excluded.heartbeat_at,
                     metadata_json=excluded.metadata_json,
                     updated_at=excluded.updated_at''',
                (
                    agent_id,
                    state.get('status', 'running'),
                    state.get('last_evaluated_at'),
                    json.dumps(state.get('last_signal')) if state.get('last_signal') else None,
                    state.get('confidence_threshold', 0.45),
                    state.get('last_error'),
                    state.get('heartbeat_at', now),
                    json.dumps(state.get('metadata', {})),
                    now,
                ),
            )

    def get_agent_state(self, agent_id: str) -> Optional[dict]:
        with self.conn() as c:
            row = c.execute(
                'SELECT * FROM agent_state WHERE agent_id=?', (agent_id,),
            ).fetchone()
        return dict(row) if row else None

    def get_all_agent_states(self) -> list:
        with self.conn() as c:
            rows = c.execute(
                'SELECT * FROM agent_state ORDER BY agent_id',
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Agent decisions (planner verdicts + hindsight) ───────────────────────

    def insert_agent_decisions(self, rows: list[dict]) -> None:
        if not rows:
            return
        with self.conn() as c:
            c.executemany(
                '''INSERT OR IGNORE INTO agent_decisions
                   (decision_id, scan_id, decided_at, instrument_token, symbol, side,
                    ev, confidence, persistence, price_at_decision, sl_pct, target_pct,
                    lenses_json, regime, india_vix, planner_action, planner_reason,
                    size_factor, planner_mode, llm_latency_ms, signal_id)
                   VALUES (:decision_id,:scan_id,:decided_at,:instrument_token,:symbol,:side,
                           :ev,:confidence,:persistence,:price_at_decision,:sl_pct,:target_pct,
                           :lenses_json,:regime,:india_vix,:planner_action,:planner_reason,
                           :size_factor,:planner_mode,:llm_latency_ms,:signal_id)''',
                rows,
            )

    # ── App settings (operator overrides on .env — PRD 5b.2) ──────────────

    def get_app_settings(self) -> dict:
        with self.conn() as c:
            rows = c.execute('SELECT key, value FROM app_settings').fetchall()
        return {r['key']: r['value'] for r in rows}

    def set_app_setting(self, key: str, value: str) -> None:
        import time as _t
        with self.conn() as c:
            c.execute(
                'INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, ?) '
                'ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at',
                (key, value, int(_t.time() * 1000)),
            )

    def get_recent_agent_decisions(self, limit: int = 50) -> list:
        with self.conn() as c:
            rows = c.execute(
                'SELECT * FROM agent_decisions ORDER BY decided_at DESC LIMIT ?',
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_decisions_pending_hindsight(self, older_than_ms: int, newer_than_ms: int) -> list:
        with self.conn() as c:
            rows = c.execute(
                '''SELECT * FROM agent_decisions
                   WHERE hindsight_outcome IS NULL
                     AND decided_at <= ? AND decided_at >= ?
                   ORDER BY decided_at ASC LIMIT 200''',
                (older_than_ms, newer_than_ms),
            ).fetchall()
        return [dict(r) for r in rows]

    def update_decision_hindsight(self, decision_id: str, ret_pct: float, outcome: str) -> None:
        with self.conn() as c:
            c.execute(
                '''UPDATE agent_decisions
                   SET hindsight_at=?, hindsight_ret_pct=?, hindsight_outcome=?
                   WHERE decision_id=?''',
                (int(_time.time() * 1000), ret_pct, outcome, decision_id),
            )

    # ── Training runs (recursive model training) ─────────────────────────────

    def insert_training_run(self, record: dict) -> None:
        with self.conn() as c:
            c.execute(
                '''INSERT OR REPLACE INTO training_runs
                   (run_id, started_at, finished_at, status, max_steps,
                    dataset_samples, dataset_counts_json, initial_loss, final_loss,
                    trained_steps, epochs, dataset_dir, adapter_dir, train_log, error)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (
                    record.get('run_id'),
                    record.get('started_at'),
                    record.get('finished_at'),
                    record.get('status', 'unknown'),
                    record.get('max_steps'),
                    record.get('dataset_samples'),
                    json.dumps(record.get('dataset_counts')) if record.get('dataset_counts') else None,
                    record.get('initial_loss'),
                    record.get('final_loss'),
                    record.get('trained_steps'),
                    record.get('epochs'),
                    record.get('dataset_dir'),
                    record.get('adapter_dir'),
                    record.get('train_log'),
                    record.get('error'),
                ),
            )

    def update_training_run(self, run_id: str, **fields) -> None:
        """Patch specific columns of an existing run (e.g. status/finished_at/error)."""
        allowed = {'started_at', 'finished_at', 'status', 'max_steps',
                   'dataset_samples', 'initial_loss', 'final_loss', 'trained_steps',
                   'epochs', 'dataset_dir', 'adapter_dir', 'train_log', 'error'}
        cols = {k: v for k, v in fields.items() if k in allowed}
        if not cols:
            return
        sets = ', '.join(f'{k}=?' for k in cols)
        with self.conn() as c:
            c.execute(f'UPDATE training_runs SET {sets} WHERE run_id=?',
                      (*cols.values(), run_id))

    def get_training_runs(self, limit: int = 20) -> list:
        with self.conn() as c:
            rows = c.execute(
                'SELECT * FROM training_runs ORDER BY started_at DESC LIMIT ?',
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Risk decisions ────────────────────────────────────────────────────────

    def insert_risk_decision(self, decision: dict) -> None:
        now = int(_time.time() * 1000)
        with self.conn() as c:
            c.execute(
                '''INSERT OR IGNORE INTO risk_decisions
                   (decision_id, signal_id, strategy_id, instrument_token,
                    approved, checks_json, reason,
                    daily_pnl_at_decision, equity_at_decision,
                    drawdown_at_decision, india_vix_at_decision, decided_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
                (
                    decision.get('decision_id', str(uuid.uuid4())),
                    decision.get('signal_id'),
                    decision.get('strategy_id'),
                    decision.get('instrument_token'),
                    int(decision.get('approved', 0)),
                    json.dumps(decision.get('checks', {})),
                    decision.get('reason'),
                    decision.get('daily_pnl'),
                    decision.get('equity'),
                    decision.get('drawdown'),
                    decision.get('india_vix'),
                    decision.get('decided_at', now),
                ),
            )

    def get_recent_signals(self, limit: int = 40) -> list:
        """Return recent risk decisions joined with signal lineage for the trade recommendations feed."""
        with self.conn() as c:
            rows = c.execute(
                '''SELECT rd.decision_id, rd.signal_id, rd.strategy_id,
                          rd.instrument_token, rd.approved, rd.reason, rd.decided_at,
                          rd.daily_pnl_at_decision, rd.equity_at_decision,
                          sl.side, sl.confidence, sl.regime, sl.regime_confidence,
                          sl.trigger_rule, sl.trade_id, sl.trade_pnl, sl.fill_price
                   FROM risk_decisions rd
                   LEFT JOIN signal_lineage sl ON sl.signal_id = rd.signal_id
                   ORDER BY rd.decided_at DESC LIMIT ?''',
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_risk_decisions(self, strategy_id: Optional[str] = None,
                           limit: int = 200) -> list:
        q = 'SELECT * FROM risk_decisions WHERE 1=1'
        params: list = []
        if strategy_id:
            q += ' AND strategy_id=?'
            params.append(strategy_id)
        q += ' ORDER BY decided_at DESC LIMIT ?'
        params.append(limit)
        with self.conn() as c:
            rows = c.execute(q, params).fetchall()
        return [dict(r) for r in rows]

    # ── Portfolio snapshots ───────────────────────────────────────────────────

    def insert_portfolio_snapshot(self, snapshot: dict) -> None:
        now = int(_time.time() * 1000)
        with self.conn() as c:
            c.execute(
                '''INSERT INTO portfolio_snapshots
                   (snapshot_id, equity, daily_pnl, unrealized_pnl, drawdown,
                    open_positions, recorded_at)
                   VALUES (?,?,?,?,?,?,?)''',
                (
                    snapshot.get('snapshot_id', str(uuid.uuid4())),
                    snapshot.get('equity', 0.0),
                    snapshot.get('daily_pnl', 0.0),
                    snapshot.get('unrealized_pnl', 0.0),
                    snapshot.get('drawdown', 0.0),
                    snapshot.get('open_positions', 0),
                    snapshot.get('recorded_at', now),
                ),
            )

    def get_portfolio_snapshots(self, limit: int = 500) -> list:
        with self.conn() as c:
            rows = c.execute(
                'SELECT * FROM portfolio_snapshots ORDER BY recorded_at DESC LIMIT ?',
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Regimes ──────────────────────────────────────────────────────────────

    def insert_regime(self, time_ms: int, regime: str,
                      confidence: float, size_multiplier: float) -> None:
        with self.conn() as c:
            c.execute(
                '''INSERT OR REPLACE INTO regimes (time, regime, confidence, size_multiplier)
                   VALUES (?,?,?,?)''',
                (time_ms, regime, confidence, size_multiplier),
            )

    def get_latest_regime(self) -> Optional[dict]:
        with self.conn() as c:
            row = c.execute(
                'SELECT * FROM regimes ORDER BY time DESC LIMIT 1',
            ).fetchone()
        return dict(row) if row else None

    # ── News ─────────────────────────────────────────────────────────────────

    def insert_news(self, article: dict) -> None:
        with self.conn() as c:
            c.execute(
                '''INSERT OR IGNORE INTO news_log
                   (published_at, fetched_at, headline, source, url,
                    sentiment, score, instruments_json, impact)
                   VALUES (?,?,?,?,?,?,?,?,?)''',
                (
                    article['published_at'], article['fetched_at'],
                    article['headline'], article.get('source'), article.get('url'),
                    article['sentiment'], article['score'],
                    json.dumps(article.get('instruments', [])),
                    article['impact'],
                ),
            )

    def get_recent_news(self, limit: int = 50) -> list:
        with self.conn() as c:
            rows = c.execute(
                'SELECT * FROM news_log ORDER BY published_at DESC LIMIT ?', (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Instruments ──────────────────────────────────────────────────────────

    def upsert_instruments(self, instruments: list) -> None:
        rows = []
        for i in instruments:
            token = i.get('instrument_token') or i.get('token')
            symbol = i.get('tradingsymbol') or i.get('symbol', '')
            rows.append((
                token, symbol,
                i.get('exchange', 'NSE'),
                i.get('instrument_type', 'EQ'),
                i.get('expiry'), i.get('strike'),
                i.get('lot_size'), i.get('tick_size'), i.get('sector'),
            ))
        with self.conn() as c:
            c.executemany(
                '''INSERT OR REPLACE INTO instruments
                   (instrument_token, symbol, exchange, instrument_type,
                    expiry, strike, lot_size, tick_size, sector)
                   VALUES (?,?,?,?,?,?,?,?,?)''',
                rows,
            )

    def get_instrument(self, symbol: str, exchange: str = 'NSE') -> Optional[dict]:
        with self.conn() as c:
            row = c.execute(
                'SELECT * FROM instruments WHERE symbol=? AND exchange=?', (symbol, exchange),
            ).fetchone()
        return dict(row) if row else None

    # ── DSA state ────────────────────────────────────────────────────────────

    def save_dsa_state(self, allocations: dict) -> None:
        now_ms = int(_time.time() * 1000)
        with self.conn() as c:
            c.executemany(
                '''INSERT OR REPLACE INTO dsa_state (strategy_id, allocation, updated_at)
                   VALUES (?,?,?)''',
                [(sid, float(alloc), now_ms) for sid, alloc in allocations.items()],
            )

    def load_dsa_state(self) -> dict:
        with self.conn() as c:
            rows = c.execute('SELECT strategy_id, allocation FROM dsa_state').fetchall()
        return {r['strategy_id']: r['allocation'] for r in rows}

    # ── Scorecards ───────────────────────────────────────────────────────────

    def upsert_scorecard(self, scorecard: dict) -> None:
        now_ms = int(_time.time() * 1000)
        with self.conn() as c:
            c.execute(
                '''INSERT OR REPLACE INTO scorecards
                   (strategy_id, total_trades, wins, losses, alpha, beta,
                    total_pnl, avg_win, avg_loss, expectancy, outcome_counts, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
                (
                    scorecard['strategy_id'],
                    scorecard.get('total_trades', 0),
                    scorecard.get('wins', 0),
                    scorecard.get('losses', 0),
                    scorecard.get('alpha', 1.0),
                    scorecard.get('beta', 1.0),
                    scorecard.get('total_pnl', 0.0),
                    scorecard.get('avg_win', 0.0),
                    scorecard.get('avg_loss', 0.0),
                    scorecard.get('expectancy', 0.0),
                    scorecard.get('outcome_counts'),
                    now_ms,
                ),
            )

    def get_all_scorecards(self) -> list:
        with self.conn() as c:
            rows = c.execute('SELECT * FROM scorecards ORDER BY strategy_id').fetchall()
        return [dict(r) for r in rows]

    # ── Strategy learner params ───────────────────────────────────────────────

    def upsert_strategy_params(self, params: dict) -> None:
        now = int(_time.time() * 1000)
        with self.conn() as c:
            c.execute(
                '''INSERT OR REPLACE INTO strategy_params
                   (strategy_id, min_confidence, sl_multiplier, target_multiplier,
                    kelly_fraction, bayes_wr, n_trades, updated_at)
                   VALUES (?,?,?,?,?,?,?,?)''',
                (
                    params['strategy_id'],
                    float(params.get('min_confidence',    0.45)),
                    float(params.get('sl_multiplier',     1.5)),
                    float(params.get('target_multiplier', 3.0)),
                    float(params.get('kelly_fraction',    0.02)),
                    float(params.get('bayes_wr',          0.5)),
                    int(params.get('n_trades',            0)),
                    params.get('updated_at', now),
                ),
            )

    def get_all_strategy_params(self) -> list:
        with self.conn() as c:
            rows = c.execute('SELECT * FROM strategy_params ORDER BY strategy_id').fetchall()
        return [dict(r) for r in rows]

    # ── Audit ────────────────────────────────────────────────────────────────

    def audit(self, actor: str, action: str,
              target_type: Optional[str] = None, target_id: Optional[str] = None,
              payload: Optional[dict] = None) -> None:
        with self.conn() as c:
            c.execute(
                '''INSERT INTO audit_log (time, actor, action, target_type, target_id, payload_json)
                   VALUES (?,?,?,?,?,?)''',
                (int(_time.time() * 1000), actor, action, target_type, target_id,
                 json.dumps(payload) if payload else None),
            )


# ── Embedded schema ───────────────────────────────────────────────────────────
# Used when db/init/schema.sql is absent. Must stay in sync with that file.
_EMBEDDED_SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA cache_size = -64000;
PRAGMA mmap_size = 268435456;
PRAGMA temp_store = MEMORY;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS instruments (
    instrument_token INTEGER PRIMARY KEY, symbol TEXT NOT NULL, exchange TEXT NOT NULL,
    instrument_type TEXT NOT NULL, expiry DATE, strike REAL, lot_size INTEGER,
    tick_size REAL, sector TEXT);
CREATE INDEX IF NOT EXISTS idx_inst_symbol ON instruments(symbol, exchange);

CREATE TABLE IF NOT EXISTS ticks_current (
    time INTEGER NOT NULL, instrument_token INTEGER NOT NULL, last_price REAL NOT NULL,
    last_quantity INTEGER, volume INTEGER, bid_price REAL, ask_price REAL,
    bid_qty INTEGER, ask_qty INTEGER, oi INTEGER,
    PRIMARY KEY (instrument_token, time)) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_ticks_time ON ticks_current(time);

CREATE TABLE IF NOT EXISTS ohlcv_1m (
    bucket_time INTEGER NOT NULL, instrument_token INTEGER NOT NULL,
    open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL, close REAL NOT NULL,
    volume INTEGER NOT NULL, oi INTEGER,
    PRIMARY KEY (instrument_token, bucket_time)) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS ohlcv_1d (
    bucket_date TEXT NOT NULL, instrument_token INTEGER NOT NULL,
    open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL, close REAL NOT NULL,
    volume INTEGER NOT NULL, delivery_pct REAL, fii_net REAL, dii_net REAL,
    PRIMARY KEY (instrument_token, bucket_date)) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS trades (
    trade_id TEXT PRIMARY KEY,
    signal_id TEXT,
    order_id TEXT,
    strategy_id TEXT NOT NULL,
    instrument_token INTEGER NOT NULL,
    side TEXT NOT NULL,
    entry_time INTEGER NOT NULL,
    entry_price REAL NOT NULL,
    quantity INTEGER NOT NULL,
    exit_time INTEGER,
    exit_price REAL,
    exit_reason TEXT,
    gross_pnl REAL,
    costs REAL,
    net_pnl REAL,
    regime_at_entry TEXT,
    confidence REAL,
    kite_order_id TEXT,
    metadata_json TEXT,
    is_paper INTEGER NOT NULL DEFAULT 1);
CREATE INDEX IF NOT EXISTS idx_trades_strategy ON trades(strategy_id, entry_time DESC);
CREATE INDEX IF NOT EXISTS idx_trades_open ON trades(strategy_id) WHERE exit_time IS NULL;
CREATE INDEX IF NOT EXISTS idx_trades_time ON trades(entry_time DESC);
CREATE INDEX IF NOT EXISTS idx_trades_signal ON trades(signal_id);

CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY,
    signal_id TEXT,
    trade_id TEXT,
    strategy_id TEXT,
    instrument_token INTEGER,
    side TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    price_at_signal REAL,
    limit_price REAL,
    stop_loss REAL,
    target REAL,
    confidence REAL,
    regime TEXT,
    status TEXT NOT NULL DEFAULT 'created',
    reject_reason TEXT,
    fill_price REAL,
    fill_time INTEGER,
    risk_checks_json TEXT,
    metadata_json TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    is_paper INTEGER NOT NULL DEFAULT 1);
CREATE INDEX IF NOT EXISTS idx_orders_signal ON orders(signal_id);
CREATE INDEX IF NOT EXISTS idx_orders_strategy ON orders(strategy_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);

CREATE TABLE IF NOT EXISTS signal_lineage (
    lineage_id TEXT PRIMARY KEY,
    signal_id TEXT NOT NULL,
    strategy_id TEXT,
    instrument_token INTEGER,
    side TEXT,
    generated_at INTEGER NOT NULL,
    regime TEXT,
    regime_confidence REAL,
    india_vix REAL,
    indicators_json TEXT,
    trigger_rule TEXT,
    confidence REAL,
    risk_approved INTEGER,
    risk_checks_json TEXT,
    risk_reason TEXT,
    order_id TEXT,
    fill_price REAL,
    fill_time INTEGER,
    trade_id TEXT,
    trade_pnl REAL,
    trade_exit_reason TEXT,
    trade_closed_at INTEGER,
    created_at INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS idx_lineage_signal ON signal_lineage(signal_id);
CREATE INDEX IF NOT EXISTS idx_lineage_strategy ON signal_lineage(strategy_id, generated_at DESC);
CREATE INDEX IF NOT EXISTS idx_lineage_time ON signal_lineage(generated_at DESC);

CREATE TABLE IF NOT EXISTS trade_journal (
    journal_id TEXT PRIMARY KEY,
    trade_id TEXT NOT NULL UNIQUE,
    entry_reason TEXT,
    exit_reason TEXT,
    strategy_rationale TEXT,
    manual_notes TEXT,
    mistake_tags_json TEXT,
    review_status TEXT NOT NULL DEFAULT 'pending',
    lesson TEXT,
    rating INTEGER,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS idx_journal_trade ON trade_journal(trade_id);
CREATE INDEX IF NOT EXISTS idx_journal_status ON trade_journal(review_status);

CREATE TABLE IF NOT EXISTS event_bus_log (
    event_id TEXT PRIMARY KEY,
    topic TEXT NOT NULL,
    payload_json TEXT,
    published_at INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS idx_event_topic ON event_bus_log(topic, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_event_time ON event_bus_log(published_at DESC);

CREATE TABLE IF NOT EXISTS agent_state (
    agent_id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'running',
    last_evaluated_at INTEGER,
    last_signal_json TEXT,
    confidence_threshold REAL DEFAULT 0.45,
    last_error TEXT,
    heartbeat_at INTEGER,
    metadata_json TEXT,
    updated_at INTEGER NOT NULL);

CREATE TABLE IF NOT EXISTS risk_decisions (
    decision_id TEXT PRIMARY KEY,
    signal_id TEXT,
    strategy_id TEXT,
    instrument_token INTEGER,
    approved INTEGER NOT NULL,
    checks_json TEXT,
    reason TEXT,
    daily_pnl_at_decision REAL,
    equity_at_decision REAL,
    drawdown_at_decision REAL,
    india_vix_at_decision REAL,
    decided_at INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS idx_riskdec_signal ON risk_decisions(signal_id);
CREATE INDEX IF NOT EXISTS idx_riskdec_strategy ON risk_decisions(strategy_id, decided_at DESC);
CREATE INDEX IF NOT EXISTS idx_riskdec_time ON risk_decisions(decided_at DESC);

CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    equity REAL NOT NULL,
    daily_pnl REAL NOT NULL DEFAULT 0.0,
    unrealized_pnl REAL NOT NULL DEFAULT 0.0,
    drawdown REAL NOT NULL DEFAULT 0.0,
    open_positions INTEGER NOT NULL DEFAULT 0,
    recorded_at INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS idx_pf_snapshot_time ON portfolio_snapshots(recorded_at DESC);

CREATE TABLE IF NOT EXISTS regimes (
    time INTEGER PRIMARY KEY,
    regime TEXT NOT NULL,
    confidence REAL NOT NULL,
    size_multiplier REAL NOT NULL);

CREATE TABLE IF NOT EXISTS scorecards (
    strategy_id TEXT PRIMARY KEY,
    total_trades INTEGER NOT NULL DEFAULT 0,
    wins INTEGER NOT NULL DEFAULT 0,
    losses INTEGER NOT NULL DEFAULT 0,
    alpha REAL NOT NULL DEFAULT 1.0,
    beta REAL NOT NULL DEFAULT 1.0,
    total_pnl REAL NOT NULL DEFAULT 0.0,
    avg_win REAL NOT NULL DEFAULT 0.0,
    avg_loss REAL NOT NULL DEFAULT 0.0,
    expectancy REAL NOT NULL DEFAULT 0.0,
    outcome_counts TEXT,
    updated_at INTEGER NOT NULL DEFAULT 0);

CREATE TABLE IF NOT EXISTS dsa_state (
    strategy_id TEXT PRIMARY KEY,
    allocation REAL NOT NULL DEFAULT 0.125,
    updated_at INTEGER NOT NULL DEFAULT 0);

CREATE TABLE IF NOT EXISTS news_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    published_at INTEGER NOT NULL,
    fetched_at INTEGER NOT NULL,
    headline TEXT NOT NULL,
    source TEXT,
    url TEXT,
    sentiment TEXT NOT NULL,
    score REAL NOT NULL,
    instruments_json TEXT,
    impact TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_news_time ON news_log(published_at DESC);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    time INTEGER NOT NULL,
    actor TEXT,
    action TEXT NOT NULL,
    target_type TEXT,
    target_id TEXT,
    payload_json TEXT);
CREATE INDEX IF NOT EXISTS idx_audit_time ON audit_log(time DESC);

CREATE TABLE IF NOT EXISTS strategy_params (
    strategy_id TEXT PRIMARY KEY,
    min_confidence REAL NOT NULL DEFAULT 0.45,
    sl_multiplier REAL NOT NULL DEFAULT 1.5,
    target_multiplier REAL NOT NULL DEFAULT 3.0,
    kelly_fraction REAL NOT NULL DEFAULT 0.02,
    bayes_wr REAL NOT NULL DEFAULT 0.5,
    n_trades INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL DEFAULT 0);
"""
