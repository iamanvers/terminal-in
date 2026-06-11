"""
TERMINAL//IN — main entrypoint.
Starts all threads: data ingest, news, strategy engine, risk, Flask/SocketIO.
"""

import logging
import signal
import sys
import time
from threading import Event, Thread

from terminal_in.config import load_config
from terminal_in.db import DB
from terminal_in.persistence import MetadataRepo, ArtifactStore

log = logging.getLogger(__name__)

_stop_event = Event()


def _setup_logging(level: str):
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format='%(asctime)s %(levelname)-8s %(name)s — %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )


def _handle_signal(sig, frame):
    log.info('Shutdown signal received (%s)', sig)
    _stop_event.set()


def _apply_low_latency():
    """Opt-in (LOW_LATENCY=1): raise process priority so the tick/scan path
    isn't preempted by background apps. Pair with PYTHON_JIT=1 (Python 3.14
    experimental JIT) — set before interpreter start, see start.ps1."""
    import os
    if os.environ.get('LOW_LATENCY') != '1':
        return
    try:
        if sys.platform == 'win32':
            import ctypes
            HIGH_PRIORITY_CLASS = 0x00000080
            ctypes.windll.kernel32.SetPriorityClass(
                ctypes.windll.kernel32.GetCurrentProcess(), HIGH_PRIORITY_CLASS)
            log.info('LOW_LATENCY: process priority set to HIGH')
        else:
            os.nice(-10)
            log.info('LOW_LATENCY: niceness lowered to -10')
    except Exception:
        log.warning('LOW_LATENCY: could not raise process priority (non-fatal)')


def main():
    cfg = load_config()
    _setup_logging(cfg.log_level)
    log.info('TERMINAL//IN starting — mode=%s', cfg.mode)
    _apply_low_latency()

    # Catch crashes in ANY daemon thread — a dead component must be visible,
    # not silent (errors land in the ring buffer → /api/health → UI badge)
    from terminal_in import errors as _errors
    _errors.install_thread_hook()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    # ── Persistence layer ─────────────────────────────────────────────────────
    db = DB(cfg.sqlite_path)
    metadata = MetadataRepo(cfg.duckdb_path)
    artifacts = ArtifactStore(cfg.artifacts_dir)
    log.info('Data dir: %s', cfg.data_dir)

    # ── Instruments ──────────────────────────────────────────────────────────
    from terminal_in.data_ingest.instruments import registry
    kite = None
    if cfg.use_kite_live:
        try:
            from kiteconnect import KiteConnect
            kite = KiteConnect(api_key=cfg.kite_api_key)
            kite.set_access_token(cfg.kite_access_token)
            registry.load_from_kite(kite)
            log.info('Kite instruments loaded')
        except Exception:
            log.exception('Kite init failed — falling back to stubs')
            registry.load_stubs()
    else:
        registry.load_stubs()
        log.info('Paper mode — stub instruments loaded')

    instruments = {sym: registry.token(sym) for sym in cfg.tracked_symbols if registry.token(sym)}
    db.upsert_instruments([
        {'symbol': sym, 'token': tok, 'exchange': 'NSE', 'instrument_type': 'EQ'}
        for sym, tok in instruments.items()
    ])

    # ── Data streamer ─────────────────────────────────────────────────────────
    threads = []
    streamer = None
    if cfg.use_kite_live and kite is not None:
        from terminal_in.data_ingest.streamer import KiteStreamer
        streamer = KiteStreamer(
            api_key=cfg.kite_api_key,
            access_token=cfg.kite_access_token,
            instrument_tokens=list(instruments.values()),
            db=db,
        )
        t = Thread(target=streamer.run, daemon=True, name='kite-streamer')
        threads.append(t)
    else:
        _start_yf_live_feed(instruments, _stop_event, db=db)
        # Real data only — no synthetic seeding. Historical bars come from the
        # yfinance backfill below; intraday 1m bars from live tick aggregation.
        from terminal_in.data_ingest.paper_tick_agg import PaperTickAggregator
        _tick_agg = PaperTickAggregator(db=db)

    # ── OHLCV historical fill (async, best-effort) ────────────────────────────
    _start_ohlcv_backfill(db, instruments, cfg)

    # ── News fetcher (RSS feeds always; NewsAPI added when key configured) ────
    from terminal_in.news.fetcher import NewsFetcher
    news_fetcher = NewsFetcher(api_key=cfg.newsapi_key, db=db)
    threads.append(Thread(target=news_fetcher.run, daemon=True, name='news-fetcher'))

    # ── Strategy engine ───────────────────────────────────────────────────────
    # Pre-seed the regime cache so /api/regime never returns {} before the
    # engine's first evaluation cycle (~60s after boot).
    from terminal_in.bus import bus
    from datetime import datetime, timezone
    bus.publish('regime.update', {
        'regime': 'sideways',
        'confidence': 0.0,
        'india_vix': 15.0,
        'size_multiplier': 0.7,
        'ts': datetime.now(timezone.utc).isoformat(),
        'startup_default': True,
    })

    from terminal_in.strategy_engine.engine import StrategyEngine
    engine = StrategyEngine(db=db, instruments=instruments, config=cfg)
    t = Thread(target=engine.run_loop, args=(_stop_event,), daemon=True, name='strategy-engine')
    threads.append(t)

    # ── Strategy learner (adaptive params — must init before gate) ────────────
    from terminal_in.agents.strategy_learner import StrategyLearner
    learner = StrategyLearner(db=db, dsa=engine._dsa)

    # ── Trade orchestrator (agentic scan + rank + auto-fire) ──────────────────
    from terminal_in.agents.orchestrator import TradeOrchestrator
    orchestrator = TradeOrchestrator(db=db, instruments=instruments, config=cfg, learner=learner)
    threads.append(Thread(target=orchestrator.run, args=(_stop_event,), daemon=True, name='orchestrator'))

    # ── Decision memory + hindsight loop (audit trail of agent decisions) ─────
    from terminal_in.agents.decision_memory import DecisionMemory
    memory = DecisionMemory(db=db)
    threads.append(Thread(target=memory.run_hindsight, args=(_stop_event,), daemon=True, name='hindsight'))

    # ── Trade planner (LLM judge between orchestrator and risk gate) ──────────
    from terminal_in.agents.trade_planner import TradePlanner
    planner = TradePlanner(db=db, config=cfg, memory=memory, learner=learner)
    threads.append(Thread(target=planner.run, args=(_stop_event,), daemon=True, name='planner'))

    # ── Trading supervisor (closed-loop lens breaker + throttle) ──────────────
    from terminal_in.agents.supervisor import TradingSupervisor
    trading_supervisor = TradingSupervisor(db=db, config=cfg)
    threads.append(Thread(target=trading_supervisor.run, args=(_stop_event,), daemon=True, name='supervisor'))

    # ── Recursive training orchestrator (manual trigger via /api/training) ────
    from terminal_in.agents.training.recursive import TrainingOrchestrator
    trainer = TrainingOrchestrator(db=db, config=cfg)

    # ── Daily report scheduler (pre-open brief 08:55 / EOD report 15:45 IST) ──
    from terminal_in.reporting.daily_report import ReportScheduler
    report_scheduler = ReportScheduler(db=db)
    threads.append(Thread(target=report_scheduler.run, args=(_stop_event,), daemon=True, name='reports'))

    # ── Risk supervisor ───────────────────────────────────────────────────────
    from terminal_in.risk.gate import RiskSupervisor
    supervisor = RiskSupervisor(db=db, config=cfg, learner=learner)

    # ── Trade analyst ─────────────────────────────────────────────────────────
    from terminal_in.risk.m3_analyst import TradeAnalyst
    analyst = TradeAnalyst(db=db)

    # ── Broker ────────────────────────────────────────────────────────────────
    if cfg.use_kite_live and kite is not None:
        from terminal_in.execution.kite_broker import KiteBroker
        broker = KiteBroker(kite=kite, db=db, config=cfg)
    else:
        from terminal_in.execution.paper_broker import PaperBroker
        broker = PaperBroker(db=db, config=cfg)

    # ── Settlement service (EOD auto-close + daily P&L reset) ─────────────────
    from terminal_in.execution.settlement import SettlementService
    settlement = SettlementService(db=db, broker=broker, supervisor=supervisor, metadata=metadata)
    threads.append(Thread(target=settlement.run, args=(_stop_event,), daemon=True, name='settlement'))

    # ── Flask API ─────────────────────────────────────────────────────────────
    from terminal_in.api.app import create_app
    flask_app, sio = create_app({
        'db': db,
        'metadata': metadata,
        'artifacts': artifacts,
        'supervisor': supervisor,
        'broker': broker,
        'engine': engine,
        'dsa': engine._dsa,
        'analyst': analyst,
        'learner': learner,
        'orchestrator': orchestrator,
        'planner': planner,
        'trading_supervisor': trading_supervisor,
        'memory': memory,
        'trainer': trainer,
        'instruments': instruments,
        'jwt_secret': cfg.jwt_secret,
    })

    # Start all daemon threads
    for t in threads:
        t.start()
    if streamer is not None:
        pass  # KiteStreamer.run() manages its own thread internally

    # Fail fast with a clear message if the API port is already taken
    # (e.g. a previous instance still running) instead of a raw traceback.
    import socket as _socket
    try:
        probe = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        probe.bind(('0.0.0.0', 5000))
        probe.close()
    except OSError:
        log.error('Port 5000 is already in use — is another TERMINAL//IN instance running? '
                  'Stop it (or: netstat -ano | findstr :5000) and restart.')
        sys.exit(1)

    log.info('All components started — API on http://0.0.0.0:5000')

    # Start Flask in main thread (blocks until stop)
    flask_thread = Thread(
        target=lambda: sio.run(flask_app, host='0.0.0.0', port=5000, use_reloader=False,
                               log_output=False, allow_unsafe_werkzeug=True),
        daemon=True,
        name='flask',
    )
    flask_thread.start()

    # Wait for stop signal
    _stop_event.wait()
    log.info('Shutting down...')

    if streamer:
        streamer.stop()
    if news_fetcher:
        news_fetcher.stop()
    if hasattr(broker, 'stop'):
        broker.stop()
    metadata.close()

    log.info('TERMINAL//IN stopped cleanly')


def _start_yf_live_feed(instruments: dict, stop_event: Event, db=None):
    """Start real-time price feed via yfinance. No synthetic noise."""
    from terminal_in.data_ingest.yf_live import YFLiveFeed
    feed = YFLiveFeed(instruments=instruments, db=db)
    Thread(target=feed.run, args=(stop_event,), daemon=True, name='yf-live-feed').start()


def _start_ohlcv_backfill(db, instruments: dict, cfg):
    """
    Non-blocking gap-aware OHLCV backfill.
    1. Runs immediately on startup — fills any gaps since last stored date per symbol.
    2. Schedules a daily refresh every 24 h so the DB stays current even across long downtimes.
    """
    from terminal_in.data_ingest.yf_fetcher import backfill, backfill_intraday
    token_map = {tok: sym for sym, tok in instruments.items()}

    def _fill(label: str):
        try:
            n = backfill(db, token_map)          # smart gap-aware, skips up-to-date symbols
            if n > 0:
                log.info('yfinance daily backfill [%s] — %d symbols updated', label, n)
            n5 = backfill_intraday(db, token_map, interval='5m')
            if n5 > 0:
                log.info('yfinance 5m intraday backfill [%s] — %d symbols updated', label, n5)
        except Exception:
            log.exception('OHLCV backfill [%s] failed (non-fatal)', label)

    def _periodic_refresh():
        """Refresh once at startup, then every 24 h."""
        _fill('startup')
        while not _stop_event.is_set():
            _stop_event.wait(timeout=86400)   # 24 hours
            if not _stop_event.is_set():
                _fill('daily-refresh')

    Thread(target=_periodic_refresh, daemon=True, name='ohlcv-backfill').start()


if __name__ == '__main__':
    main()
