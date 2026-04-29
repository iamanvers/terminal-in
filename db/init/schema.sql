-- TERMINAL//IN — SQLite schema
-- Auto-applied by DB() on first connection. Safe to re-run (IF NOT EXISTS everywhere).

PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA cache_size = -64000;       -- 64 MB page cache
PRAGMA mmap_size = 268435456;     -- 256 MB mmap for fast reads
PRAGMA temp_store = MEMORY;
PRAGMA foreign_keys = ON;

-- ─── INSTRUMENTS ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS instruments (
    instrument_token INTEGER PRIMARY KEY,
    symbol           TEXT    NOT NULL,
    exchange         TEXT    NOT NULL,
    instrument_type  TEXT    NOT NULL,   -- 'EQ', 'FUT', 'CE', 'PE', 'INDEX'
    expiry           DATE,
    strike           REAL,
    lot_size         INTEGER,
    tick_size        REAL,
    sector           TEXT
);

CREATE INDEX IF NOT EXISTS idx_inst_symbol ON instruments(symbol, exchange);

-- ─── TICKS (current month, live) ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ticks_current (
    time             INTEGER NOT NULL,   -- unix epoch ms
    instrument_token INTEGER NOT NULL,
    last_price       REAL    NOT NULL,
    last_quantity    INTEGER,
    volume           INTEGER,
    bid_price        REAL,
    ask_price        REAL,
    bid_qty          INTEGER,
    ask_qty          INTEGER,
    oi               INTEGER,
    PRIMARY KEY (instrument_token, time)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS idx_ticks_time ON ticks_current(time);

-- ─── OHLCV ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ohlcv_1m (
    bucket_time      INTEGER NOT NULL,   -- unix epoch ms
    instrument_token INTEGER NOT NULL,
    open             REAL    NOT NULL,
    high             REAL    NOT NULL,
    low              REAL    NOT NULL,
    close            REAL    NOT NULL,
    volume           INTEGER NOT NULL,
    oi               INTEGER,
    PRIMARY KEY (instrument_token, bucket_time)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS ohlcv_1d (
    bucket_date      TEXT    NOT NULL,   -- ISO date string 'YYYY-MM-DD'
    instrument_token INTEGER NOT NULL,
    open             REAL    NOT NULL,
    high             REAL    NOT NULL,
    low              REAL    NOT NULL,
    close            REAL    NOT NULL,
    volume           INTEGER NOT NULL,
    delivery_pct     REAL,
    fii_net          REAL,
    dii_net          REAL,
    PRIMARY KEY (instrument_token, bucket_date)
) WITHOUT ROWID;

-- ─── TRADES ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS trades (
    trade_id         TEXT    PRIMARY KEY,
    strategy_id      TEXT    NOT NULL,
    instrument_token INTEGER NOT NULL,
    side             TEXT    NOT NULL,   -- 'BUY' or 'SELL'
    entry_time       INTEGER NOT NULL,   -- unix epoch ms
    entry_price      REAL    NOT NULL,
    quantity         INTEGER NOT NULL,
    exit_time        INTEGER,
    exit_price       REAL,
    exit_reason      TEXT,
    gross_pnl        REAL,
    costs            REAL,
    net_pnl          REAL,
    regime_at_entry  TEXT,
    confidence       REAL,
    kite_order_id    TEXT,
    metadata_json    TEXT,
    is_paper         INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_trades_strategy ON trades(strategy_id, entry_time DESC);
CREATE INDEX IF NOT EXISTS idx_trades_open     ON trades(strategy_id) WHERE exit_time IS NULL;
CREATE INDEX IF NOT EXISTS idx_trades_time     ON trades(entry_time DESC);

-- ─── REGIMES ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS regimes (
    time            INTEGER PRIMARY KEY,
    regime          TEXT    NOT NULL,
    confidence      REAL    NOT NULL,
    size_multiplier REAL    NOT NULL
);

-- ─── M3 SCORECARDS (strategy-level, not trade-level) ─────────────────────────
CREATE TABLE IF NOT EXISTS scorecards (
    strategy_id     TEXT    PRIMARY KEY,
    total_trades    INTEGER NOT NULL DEFAULT 0,
    wins            INTEGER NOT NULL DEFAULT 0,
    losses          INTEGER NOT NULL DEFAULT 0,
    alpha           REAL    NOT NULL DEFAULT 1.0,   -- Bayesian Beta prior
    beta            REAL    NOT NULL DEFAULT 1.0,
    total_pnl       REAL    NOT NULL DEFAULT 0.0,
    avg_win         REAL    NOT NULL DEFAULT 0.0,
    avg_loss        REAL    NOT NULL DEFAULT 0.0,
    expectancy      REAL    NOT NULL DEFAULT 0.0,
    outcome_counts  TEXT,                           -- JSON dict
    updated_at      INTEGER NOT NULL DEFAULT 0
);

-- ─── DSA STATE ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS dsa_state (
    strategy_id     TEXT    PRIMARY KEY,
    allocation      REAL    NOT NULL DEFAULT 0.125,
    updated_at      INTEGER NOT NULL DEFAULT 0
);

-- ─── NEWS LOG ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS news_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    published_at    INTEGER NOT NULL,
    fetched_at      INTEGER NOT NULL,
    headline        TEXT    NOT NULL,
    source          TEXT,
    url             TEXT,
    sentiment       TEXT    NOT NULL,
    score           REAL    NOT NULL,
    instruments_json TEXT,
    impact          TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_news_time ON news_log(published_at DESC);

-- ─── AUDIT LOG ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS audit_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    time            INTEGER NOT NULL,
    actor           TEXT,
    action          TEXT    NOT NULL,
    target_type     TEXT,
    target_id       TEXT,
    payload_json    TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_time ON audit_log(time DESC);

-- ─── ORDERS ─────────────────────────────────────────────────────────────────
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
    is_paper INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_orders_signal   ON orders(signal_id);
CREATE INDEX IF NOT EXISTS idx_orders_strategy ON orders(strategy_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_orders_status   ON orders(status);

-- ─── SIGNAL LINEAGE ──────────────────────────────────────────────────────────
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
    created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_lineage_signal   ON signal_lineage(signal_id);
CREATE INDEX IF NOT EXISTS idx_lineage_strategy ON signal_lineage(strategy_id, generated_at DESC);
CREATE INDEX IF NOT EXISTS idx_lineage_time     ON signal_lineage(generated_at DESC);

-- ─── TRADE JOURNAL ───────────────────────────────────────────────────────────
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
    updated_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_journal_trade  ON trade_journal(trade_id);
CREATE INDEX IF NOT EXISTS idx_journal_status ON trade_journal(review_status);

-- ─── EVENT BUS LOG ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS event_bus_log (
    event_id TEXT PRIMARY KEY,
    topic TEXT NOT NULL,
    payload_json TEXT,
    published_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_event_topic ON event_bus_log(topic, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_event_time  ON event_bus_log(published_at DESC);

-- ─── AGENT STATE ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS agent_state (
    agent_id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'running',
    last_evaluated_at INTEGER,
    last_signal_json TEXT,
    confidence_threshold REAL DEFAULT 0.45,
    last_error TEXT,
    heartbeat_at INTEGER,
    metadata_json TEXT,
    updated_at INTEGER NOT NULL
);

-- ─── RISK DECISIONS ──────────────────────────────────────────────────────────
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
    decided_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_riskdec_signal   ON risk_decisions(signal_id);
CREATE INDEX IF NOT EXISTS idx_riskdec_strategy ON risk_decisions(strategy_id, decided_at DESC);
CREATE INDEX IF NOT EXISTS idx_riskdec_time     ON risk_decisions(decided_at DESC);

-- ─── PORTFOLIO SNAPSHOTS ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    equity REAL NOT NULL,
    daily_pnl REAL NOT NULL DEFAULT 0.0,
    unrealized_pnl REAL NOT NULL DEFAULT 0.0,
    drawdown REAL NOT NULL DEFAULT 0.0,
    open_positions INTEGER NOT NULL DEFAULT 0,
    recorded_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_pf_snapshot_time ON portfolio_snapshots(recorded_at DESC);

-- ─── STRATEGY LEARNER PARAMS ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS strategy_params (
    strategy_id       TEXT    PRIMARY KEY,
    min_confidence    REAL    NOT NULL DEFAULT 0.45,
    sl_multiplier     REAL    NOT NULL DEFAULT 1.5,
    target_multiplier REAL    NOT NULL DEFAULT 3.0,
    kelly_fraction    REAL    NOT NULL DEFAULT 0.02,
    bayes_wr          REAL    NOT NULL DEFAULT 0.5,
    n_trades          INTEGER NOT NULL DEFAULT 0,
    updated_at        INTEGER NOT NULL DEFAULT 0
);
