"""
StrategyEngine — wires DSA + all strategies + EventBus.
Subscribes to ticks and regime updates, builds MarketContext, evaluates strategies,
emits signals to 'strategy.signal' topic for the RiskSupervisor to gate.
"""

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Optional

IST = timezone(timedelta(hours=5, minutes=30))

# Workers for parallel OHLCV loading and strategy evaluation. SQLite reads,
# pandas resampling, and numpy all release the GIL, so threads give real
# concurrency here despite CPython's GIL.
_POOL_WORKERS = 8

import pandas as pd

from terminal_in.bus import bus
from terminal_in.agents.control import registry
from terminal_in.strategy_engine.context import MarketContext
from terminal_in.strategy_engine.dsa import DSA
from terminal_in.strategy_engine.regime.classifier import classifier

from terminal_in.strategy_engine.strategies.s1_intra_orb import S1IntraORB
from terminal_in.strategy_engine.strategies.s2_nifty_52w import S2Nifty52W
from terminal_in.strategy_engine.strategies.s3_midcap_breakout import S3MidcapBreakout
from terminal_in.strategy_engine.strategies.s4_rsi_reversion import S4RSIReversion
from terminal_in.strategy_engine.strategies.s5_mid_pullback import S5MidPullback
from terminal_in.strategy_engine.strategies.s6_pairs_cointegration import S6PairsCointegration
from terminal_in.strategy_engine.strategies.s8_vix_asymmetry import S8VIXAsymmetry
from terminal_in.strategy_engine.strategies.s9_hawkes_cont import S9HawkesCont

log = logging.getLogger(__name__)

ALL_STRATEGIES = [
    S1IntraORB(),
    S2Nifty52W(),
    S3MidcapBreakout(),
    S4RSIReversion(),
    S5MidPullback(),
    S6PairsCointegration(),
    S8VIXAsymmetry(),
    S9HawkesCont(),
]

EVAL_INTERVAL_S = 60   # re-evaluate strategies every 60 seconds


class StrategyEngine:
    def __init__(self, db, instruments: dict[str, int], config=None):
        self._db = db
        self._instruments = instruments  # symbol → token
        self._config = config
        self._dsa = DSA(db=db)
        self._lock = Lock()
        self._last_eval: Optional[datetime] = None
        self._event_mask: float = 1.0
        self._india_vix: float = 15.0
        # (strategy_id, token) → last publish ts: stops the same setup being
        # re-emitted every 60s eval cycle (daily bars barely change intra-day,
        # so without this the gate sees a wall of duplicate signals to reject)
        self._last_published: dict[tuple[str, int], float] = {}

        bus.subscribe('regime.update', self._on_regime_update)
        bus.subscribe('event.mask', self._on_event_mask)

        # Register all strategies in the agent registry
        registry.register('ENGINE', 'system', 'Strategy Engine Loop')
        for s in ALL_STRATEGIES:
            registry.register(s.id, 'strategy')

        log.info('StrategyEngine initialised with %d strategies', len(ALL_STRATEGIES))

    def _on_regime_update(self, payload: dict):
        pass  # regime is re-read from classifier.current_state each eval cycle

    def _on_event_mask(self, payload: dict):
        self._event_mask = float(payload.get('mask', 1.0))

    def _build_context(self) -> MarketContext:
        # REAL clock — always. The old paper-mode hack pinned "now" to 10:30
        # IST so strategies fired 24/7 and filled at stale last-close prices.
        # Paper simulation must obey the same market clock as live trading.
        now = datetime.now(IST)

        # Fetch last prices from bus hot-cache
        last_prices: dict[int, float] = {}
        for sym, token in self._instruments.items():
            cached = bus.get_cached(f'ticks.{token}')
            if cached:
                last_prices[token] = float(cached.get('last_price', 0.0))

        # Fetch VIX
        vix_token = self._instruments.get('INDIA VIX', 264969)
        vix_price = last_prices.get(vix_token, self._india_vix)
        if vix_price > 0:
            self._india_vix = vix_price

        # Build OHLCV cache: TWO batched window-function queries for the whole
        # universe (was 144 sequential per-symbol connections — the slowest
        # part of every eval cycle). 5m resampling fans out across threads.
        nifty_token = self._instruments.get('NIFTY 50', 256265)
        tokens = list(self._instruments.values())
        try:
            all_1d = self._db.get_ohlcv_1d_all(tokens, limit=300)
            all_1m = self._db.get_ohlcv_1m_all(tokens, limit=500)
        except Exception:
            log.exception('Batch OHLCV load failed')
            all_1d, all_1m = {}, {}

        ohlcv: dict[int, dict[str, pd.DataFrame]] = {t: {} for t in tokens}
        for t, df in all_1d.items():
            if not df.empty:
                ohlcv[t]['1d'] = df

        def _resample_one(item: tuple[int, pd.DataFrame]):
            t, df_1m = item
            return t, df_1m, _resample_5m(df_1m)

        with ThreadPoolExecutor(max_workers=_POOL_WORKERS, thread_name_prefix='resample') as pool:
            for t, df_1m, df_5m in pool.map(_resample_one, all_1m.items()):
                if not df_1m.empty:
                    ohlcv[t]['1m'] = df_1m
                    ohlcv[t]['5m'] = df_5m

        # Run regime classification on Nifty daily
        nifty_df = ohlcv.get(nifty_token, {}).get('1d', pd.DataFrame())
        if not nifty_df.empty and len(nifty_df) >= 21:
            close = nifty_df['close'].values.astype(float)
            regime, confidence = classifier.classify(close, self._india_vix)
        else:
            regime = classifier.current_state
            confidence = 0.5

        return MarketContext(
            now=now,
            regime=regime,
            regime_confidence=confidence,
            india_vix=self._india_vix,
            event_mask=self._event_mask,
            size_multiplier=classifier.size_multiplier,
            instruments=self._instruments,
            _ohlcv=ohlcv,
            _last_prices=last_prices,
        )

    def evaluate(self):
        """Evaluate all active strategies and publish signals."""
        now = datetime.now(timezone.utc)
        if self._last_eval is not None:
            elapsed = (now - self._last_eval).total_seconds()
            if elapsed < EVAL_INTERVAL_S:
                return
        self._last_eval = now

        with self._lock:
            ctx = self._build_context()
            self._dsa.maybe_rebalance(now, ctx.regime)

            registry.record_eval('ENGINE')

            # Select runnable strategies, then evaluate them IN PARALLEL.
            # ctx is read-only for strategies; signals are collected and
            # published sequentially afterwards because the risk gate keeps
            # stateful daily counters and must see an ordered stream.
            runnable: list[tuple] = []
            for strategy in ALL_STRATEGIES:
                if registry.is_paused(strategy.id):
                    log.debug('Strategy %s is paused — skipping', strategy.id)
                    continue
                if ctx.event_mask < 0.5:
                    continue
                if ctx.regime not in strategy.valid_regimes:
                    continue
                alloc = self._dsa.allocation(strategy.id)
                if alloc < 0.02:
                    log.debug('Strategy %s allocation too low (%.3f) — skipped', strategy.id, alloc)
                    continue
                runnable.append((strategy, alloc))

            def _eval_one(item: tuple):
                strategy, alloc = item
                try:
                    signal = strategy.evaluate(ctx)
                    registry.record_eval(strategy.id)
                    return strategy, alloc, signal
                except Exception as exc:
                    registry.record_error(strategy.id, str(exc))
                    log.exception('Strategy %s evaluation error', strategy.id)
                    return strategy, alloc, None

            results = []
            if runnable:
                with ThreadPoolExecutor(max_workers=min(_POOL_WORKERS, len(runnable)),
                                        thread_name_prefix='strat') as pool:
                    results = list(pool.map(_eval_one, runnable))

            # Open positions: never signal an instrument we already hold
            try:
                open_tokens = {int(t.get('instrument_token') or 0)
                               for t in self._db.get_open_trades()}
            except Exception:
                open_tokens = set()

            from terminal_in.market_hours import is_market_open
            import time as _time_mod
            market_open = is_market_open()

            # Re-signal policy: a daily-bar setup (S2–S9) is computed from the
            # SAME daily candle all session — re-emitting it is duplication,
            # not information. One signal per (strategy, token) per session.
            # S1 works on 1m bars (genuinely new data) → 30-min cooldown.
            SESSION_S = 6 * 3600 + 15 * 60   # covers a full trading day
            for strategy, alloc, signal in results:
                if signal is None:
                    continue
                if not market_open:
                    log.debug('Signal %s suppressed — market closed', strategy.id)
                    continue
                token = int(getattr(signal, 'instrument_id', 0) or 0)
                if token in open_tokens:
                    continue
                key = (strategy.id, token)
                now_s = _time_mod.time()
                cooldown = 1800 if strategy.id == 'S1' else SESSION_S
                if now_s - self._last_published.get(key, 0) < cooldown:
                    continue
                self._last_published[key] = now_s
                registry.record_signal(strategy.id)
                # Scale quantity by DSA allocation
                signal.quantity = max(int(signal.quantity * alloc), 1)
                signal.metadata['dsa_alloc'] = round(alloc, 3)

                log.info('Signal: %s %s %s qty=%d conf=%.2f regime=%s',
                         signal.strategy_id, signal.side,
                         signal.instrument_id, signal.quantity,
                         signal.confidence, signal.regime)

                payload = signal.__dict__ if not hasattr(signal, '__dataclass_fields__') else _signal_to_dict(signal)
                if os.environ.get('PLANNER_GATES_ENGINE', 'true').lower() in ('1', 'true', 'yes'):
                    # Dual control: deterministic strategy proposed it, the LLM
                    # judge must concur before the risk gate sees it. The
                    # planner's degraded mode (stricter deterministic bar)
                    # covers Ollama outages — never a silent bypass.
                    entry = float(payload.get('limit_price') or payload.get('price') or 0)
                    sl = float(payload.get('stop_loss') or 0)
                    tgt = float(payload.get('target') or 0)
                    rr = abs(tgt - entry) / abs(entry - sl) if entry and sl and abs(entry - sl) > 1e-9 else 1.0
                    conf = float(payload.get('confidence') or 0.5)
                    bus.publish('planner.candidates', {
                        'scan_id': -1, 'source': 'engine',
                        'regime': getattr(self, '_last_regime', None) or 'unknown',
                        'candidates': [{
                            'symbol': payload.get('tradingsymbol') or str(payload.get('instrument_id')),
                            'side': payload.get('side'),
                            'ev': round(conf * rr, 2),
                            'confidence': conf,
                            'persistence': 1,
                            'price': entry,
                            'lenses': [payload.get('strategy_id', 'ENGINE')],
                            'signal': payload,
                        }],
                    })
                else:
                    bus.publish('strategy.signal', payload)

        # Publish updated regime
        bus.publish('regime.update', {
            'regime': ctx.regime,
            'confidence': ctx.regime_confidence,
            'india_vix': ctx.india_vix,
            'size_multiplier': ctx.size_multiplier,
            'ts': now.isoformat(),
        })

    def force_evaluate(self):
        """Reset the rate-limit timer and immediately run a full evaluation cycle."""
        self._last_eval = None
        self.evaluate()

    def run_loop(self, stop_event):
        """Blocking evaluation loop — run in its own thread."""
        log.info('StrategyEngine loop started')
        import time
        while not stop_event.is_set():
            try:
                self.evaluate()
            except Exception:
                log.exception('StrategyEngine loop error')
            stop_event.wait(timeout=10)
        log.info('StrategyEngine loop stopped')


def _resample_5m(df_1m: pd.DataFrame) -> pd.DataFrame:
    if df_1m.empty:
        return pd.DataFrame()
    try:
        df = df_1m.copy()
        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index)
        resampled = df.resample('5min').agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum',
        }).dropna()
        return resampled
    except Exception:
        return pd.DataFrame()


def _signal_to_dict(signal) -> dict:
    from dataclasses import asdict
    try:
        d = asdict(signal)
        if d.get('time_exit') is not None:
            d['time_exit'] = d['time_exit'].isoformat()
        return d
    except Exception:
        return signal.__dict__
