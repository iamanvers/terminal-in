"""
StrategyEngine — wires DSA + all strategies + EventBus.
Subscribes to ticks and regime updates, builds MarketContext, evaluates strategies,
emits signals to 'strategy.signal' topic for the RiskSupervisor to gate.
"""

import logging
from datetime import datetime, timezone
from threading import Lock
from typing import Optional

import pandas as pd

from terminal_in.bus import bus
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

        bus.subscribe('regime.update', self._on_regime_update)
        bus.subscribe('event.mask', self._on_event_mask)
        log.info('StrategyEngine initialised with %d strategies', len(ALL_STRATEGIES))

    def _on_regime_update(self, payload: dict):
        pass  # regime is re-read from classifier.current_state each eval cycle

    def _on_event_mask(self, payload: dict):
        self._event_mask = float(payload.get('mask', 1.0))

    def _build_context(self) -> MarketContext:
        now = datetime.now(timezone.utc)

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

        # Build OHLCV cache: load from DB for each tracked symbol
        ohlcv: dict[int, dict[str, pd.DataFrame]] = {}
        nifty_token = self._instruments.get('NIFTY 50', 256265)
        for sym, token in self._instruments.items():
            ohlcv[token] = {}
            try:
                df_1d = self._db.get_ohlcv_1d(token=token, limit=300)
                if not df_1d.empty:
                    ohlcv[token]['1d'] = df_1d
                df_1m = self._db.get_ohlcv_1m(token=token, limit=500)
                if not df_1m.empty:
                    ohlcv[token]['1m'] = df_1m
                    # Build 5m from 1m
                    ohlcv[token]['5m'] = _resample_5m(df_1m)
            except Exception:
                log.debug('OHLCV fetch failed for %s', sym)

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

            for strategy in ALL_STRATEGIES:
                if ctx.event_mask < 0.5:
                    continue
                if ctx.regime not in strategy.valid_regimes:
                    continue

                alloc = self._dsa.allocation(strategy.id)
                if alloc < 0.02:
                    log.debug('Strategy %s allocation too low (%.3f) — skipped', strategy.id, alloc)
                    continue

                try:
                    signal = strategy.evaluate(ctx)
                except Exception:
                    log.exception('Strategy %s evaluation error', strategy.id)
                    continue

                if signal is None:
                    continue

                # Scale quantity by DSA allocation
                signal.quantity = max(int(signal.quantity * alloc), 1)
                signal.metadata['dsa_alloc'] = round(alloc, 3)

                log.info('Signal: %s %s %s qty=%d conf=%.2f regime=%s',
                         signal.strategy_id, signal.side,
                         signal.instrument_id, signal.quantity,
                         signal.confidence, signal.regime)

                bus.publish('strategy.signal', signal.__dict__ if not hasattr(signal, '__dataclass_fields__') else _signal_to_dict(signal))

        # Publish updated regime
        bus.publish('regime.update', {
            'regime': ctx.regime,
            'confidence': ctx.regime_confidence,
            'india_vix': ctx.india_vix,
            'size_multiplier': ctx.size_multiplier,
            'ts': now.isoformat(),
        })

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
