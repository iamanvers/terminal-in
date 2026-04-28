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


def main():
    cfg = load_config()
    _setup_logging(cfg.log_level)
    log.info('TERMINAL//IN starting — mode=%s', cfg.mode)

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
        _start_paper_tick_feed(instruments, _stop_event, db=db)
        # Seed synthetic OHLCV so charts have data immediately in paper mode
        from terminal_in.data_ingest.paper_ohlcv import seed as _seed_ohlcv
        _seed_ohlcv(db, list(instruments.values()))

    # ── OHLCV historical fill (async, best-effort) ────────────────────────────
    _start_ohlcv_backfill(db, instruments, cfg)

    # ── News fetcher ─────────────────────────────────────────────────────────
    news_fetcher = None
    if cfg.newsapi_key:
        from terminal_in.news.fetcher import NewsFetcher
        news_fetcher = NewsFetcher(api_key=cfg.newsapi_key, db=db)
        t = Thread(target=news_fetcher.run, daemon=True, name='news-fetcher')
        threads.append(t)

    # ── Strategy engine ───────────────────────────────────────────────────────
    from terminal_in.strategy_engine.engine import StrategyEngine
    engine = StrategyEngine(db=db, instruments=instruments, config=cfg)
    t = Thread(target=engine.run_loop, args=(_stop_event,), daemon=True, name='strategy-engine')
    threads.append(t)

    # ── Risk supervisor ───────────────────────────────────────────────────────
    from terminal_in.risk.gate import RiskSupervisor
    supervisor = RiskSupervisor(db=db, config=cfg)

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

    # ── Flask API ─────────────────────────────────────────────────────────────
    from terminal_in.api.app import create_app
    flask_app, sio = create_app({
        'db': db,
        'metadata': metadata,
        'artifacts': artifacts,
        'supervisor': supervisor,
        'broker': broker,
        'dsa': engine._dsa,
        'analyst': analyst,
        'instruments': instruments,
        'jwt_secret': cfg.jwt_secret,
    })

    # Start all daemon threads
    for t in threads:
        t.start()
    if streamer is not None:
        pass  # KiteStreamer.run() manages its own thread internally

    log.info('All components started — API on http://0.0.0.0:5000')

    # Start Flask in main thread (blocks until stop)
    flask_thread = Thread(
        target=lambda: sio.run(flask_app, host='0.0.0.0', port=5000, use_reloader=False, log_output=False, allow_unsafe_werkzeug=True),
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


def _start_paper_tick_feed(instruments: dict, stop_event: Event, db=None):
    """Simulate tick feed. Initialises prices from last DB close so new stocks match real data."""
    import random
    from terminal_in.bus import bus
    from terminal_in.data_ingest.paper_ohlcv import _SEED_PRICES

    def _init_price(token: int) -> float:
        if db is not None:
            try:
                df = db.get_ohlcv_1d(token=token, limit=1)
                if not df.empty:
                    return float(df['close'].iloc[-1])
            except Exception:
                pass
        return _SEED_PRICES.get(token, 1000.0)

    def _feed():
        import time as _time
        # Pre-seed all prices from DB before streaming starts
        prices: dict[int, float] = {token: _init_price(token) for _, token in instruments.items()}
        opens:  dict[int, float] = {}   # session open — change% calculated against this

        while not stop_event.is_set():
            for sym, token in instruments.items():
                base = prices.get(token, _SEED_PRICES.get(token, 1000.0))

                if token not in opens:
                    opens[token] = base   # lock in session open on first tick

                price = base * (1 + random.gauss(0, 0.0002))
                prices[token] = price
                open_px = opens[token]
                change_pct = round((price - open_px) / open_px * 100, 2) if open_px else 0.0

                bus.publish(f'ticks.{token}', {
                    'instrument_token': token,
                    'last_price': round(price, 2),
                    'change': change_pct,          # real session change %
                    'open': round(open_px, 2),
                    'timestamp': int(_time.time() * 1000),
                })
            stop_event.wait(timeout=1.0)

    Thread(target=_feed, daemon=True, name='paper-tick-feed').start()


def _start_ohlcv_backfill(db, instruments: dict, cfg):
    """Non-blocking backfill of daily OHLCV via yfinance."""
    def _fill():
        try:
            from terminal_in.data_ingest.yf_fetcher import backfill
            token_map = {tok: sym for sym, tok in instruments.items()}
            n = backfill(db, token_map, days=730)
            if n > 0:
                log.info('yfinance OHLCV backfill complete — %d symbols', n)
        except Exception:
            log.exception('OHLCV backfill failed (non-fatal)')

    Thread(target=_fill, daemon=True, name='ohlcv-backfill').start()


if __name__ == '__main__':
    main()
