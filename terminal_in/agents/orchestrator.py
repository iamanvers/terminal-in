"""
TradeOrchestrator — aggressive RoI-maximizing scan agent.

Every SCAN_INTERVAL_S seconds (default 120), or on-demand via bus event:
  1. Scans all tracked instruments using multi-strategy lenses
  2. Scores each setup by Expected Value: EV = confidence × (reward/risk) × vol_factor
  3. Learns from past trades — weights confidence by Bayesian win-rate per strategy
  4. Integrates recent news sentiment as an independent signal lens
  5. Fires top-K setups as 'strategy.signal' events through the M2 risk gate
  6. Publishes 'orchestrator.scan_done' with ranked results for the UI

Design notes:
  - Regime adjusts CONFIDENCE (multiplier), not whether a lens fires at all.
    A 52w-high in a sideways market is still worth noting — just at lower conviction.
  - On-demand scans run in a daemon thread so the HTTP request returns immediately.
  - scan_done is always published, even on error, so the UI always exits scanning state.
"""

import json as _json
import logging
import time as _time
from datetime import timezone, timedelta
from threading import Event, Thread

import numpy as np

from terminal_in.bus import bus
from terminal_in.agents.control import registry

log = logging.getLogger(__name__)

SCAN_INTERVAL_S    = 120   # seconds between automatic scans
TOP_K              = 3     # max signals emitted per scan
MIN_EV             = 1.2   # minimum EV to fire a signal
MIN_CONF           = 0.45  # minimum base confidence to fire
SIGNAL_DEDUP_S     = 300   # don't re-signal same instrument within 5 min
NEWS_WINDOW_H      = 48    # hours of news history to consider
IST                = timezone(timedelta(hours=5, minutes=30))

# Regime multiplier on base confidence (not a gate)
_REGIME_MULT: dict[str, float] = {
    'strong_bull': 1.20,
    'bull':        1.10,
    'sideways':    0.90,
    'bear':        0.80,
    'strong_bear': 0.70,
    'high_vol':    0.75,
}


class TradeOrchestrator:
    def __init__(self, db, instruments: dict, config, learner=None):
        self._db          = db
        self._instruments = instruments   # {symbol: token}
        self._config      = config
        self._learner     = learner
        self._results:    list[dict] = []
        self._last_scan   = 0.0
        self._scan_count  = 0
        self._last_signal: dict[int, float] = {}  # token → last signal ts

        registry.register('ORCHESTRATOR', 'orchestrator')
        bus.subscribe('orchestrator.scan_now', self._on_scan_now)
        log.info('TradeOrchestrator initialised (%d instruments)', len(instruments))

    # ── Public API ────────────────────────────────────────────────────────────

    def get_state(self) -> dict:
        return {
            'scan_count':   self._scan_count,
            'last_scan_ts': int(self._last_scan * 1000),
            'results':      self._results,
        }

    # ── Run loop ──────────────────────────────────────────────────────────────

    def run(self, stop_event: Event):
        stop_event.wait(20)   # let other services warm up first
        while not stop_event.is_set():
            self._scan_safe()
            stop_event.wait(SCAN_INTERVAL_S)

    def _on_scan_now(self, _payload=None):
        """On-demand trigger — run in a daemon thread so Flask request returns immediately."""
        log.info('Orchestrator: on-demand scan triggered')
        Thread(target=self._scan_safe, daemon=True, name='orch-scan-demand').start()

    def _scan_safe(self):
        """Wrapper that always publishes scan_done, even on exception."""
        try:
            self._scan()
        except Exception:
            log.exception('Orchestrator scan error')
            bus.publish('orchestrator.scan_done', {
                'scan_count':   self._scan_count,
                'last_scan_ts': int(_time.time() * 1000),
                'fired':        0,
                'top_results':  [],
            })

    # ── Core scan ─────────────────────────────────────────────────────────────

    def _scan(self):
        from terminal_in.strategy_engine.regime.classifier import classifier

        now    = _time.time()
        regime = classifier.current_state
        cached = bus.get_cached('regime.update') or {}
        vix    = float(cached.get('india_vix', 15.0))
        size_m = float(cached.get('size_multiplier', 1.0))

        # Regime confidence multiplier (not a gate)
        regime_mult = _REGIME_MULT.get(regime, 1.0)

        # Open positions — skip instruments already held
        try:
            open_trades = self._db.get_open_trades()
            open_tokens = {int(t.get('instrument_token') or 0) for t in open_trades}
        except Exception:
            open_tokens = set()

        # Strategy Bayesian WR from learner
        strategy_wr: dict[str, float] = {}
        if self._learner:
            for p in self._learner.all_params():
                strategy_wr[p['strategy_id']] = float(p.get('bayes_wr', 0.5))

        # Pre-fetch recent news once (avoid N DB queries per symbol)
        recent_news: list[dict] = []
        try:
            raw_news = self._db.get_recent_news(limit=100)
            cutoff_ms = (now - NEWS_WINDOW_H * 3600) * 1000
            for n in raw_news:
                if (n.get('published_at') or 0) < cutoff_ms:
                    continue
                instr = _json.loads(n.get('instruments_json') or '[]')
                recent_news.append({
                    'published_at': int(n.get('published_at') or 0),
                    'headline':     n.get('headline', ''),
                    'sentiment':    n.get('sentiment', 'neutral'),
                    'score':        float(n.get('score') or 0),
                    'instruments':  instr,
                })
        except Exception:
            log.debug('Orchestrator: could not load recent news', exc_info=False)

        candidates = []
        for symbol, token in self._instruments.items():
            if token in open_tokens:
                candidates.append({
                    'symbol': symbol, 'token': token, 'side': 'SKIP',
                    'verdict': 'OPEN', 'ev': 0.0, 'confidence': 0.0,
                    'price': 0.0, 'regime': regime, 'lenses': [],
                    'rsi': 50.0, 'ret_20d': 0.0,
                    'suggested_sl': 0, 'suggested_target': 0,
                    'summary': 'Position already open',
                })
                continue
            try:
                result = self._analyse_symbol(
                    symbol, token, regime, regime_mult, vix, size_m, strategy_wr,
                    recent_news, now,
                )
                if result:
                    candidates.append(result)
            except Exception:
                log.debug('Orchestrator: analyse failed for %s', symbol, exc_info=True)

        # Sort: actionable setups by EV desc, NEUTRAL/SKIP last
        candidates.sort(
            key=lambda r: r.get('ev', 0) if r.get('side') not in ('NEUTRAL', 'SKIP') else -1,
            reverse=True,
        )
        self._results = candidates
        self._scan_count += 1
        self._last_scan = now

        # Fire top-K high-EV signals
        fired = 0
        for c in candidates:
            if fired >= TOP_K:
                break
            if c.get('side') in ('NEUTRAL', 'SKIP', None):
                continue
            if c.get('ev', 0) < MIN_EV:
                break
            if c.get('confidence', 0) < MIN_CONF:
                continue

            token = int(c['token'])
            if now - self._last_signal.get(token, 0) < SIGNAL_DEDUP_S:
                continue

            price = float(c.get('price', 0))
            if price <= 0:
                continue

            sl  = float(c.get('suggested_sl', 0))
            tgt = float(c.get('suggested_target', 0))

            kelly = 0.025
            if self._learner:
                params = self._learner.get_params('ORCHESTRATOR')
                kelly  = float(params.get('kelly_fraction', 0.025))

            equity   = float(cached.get('equity') or self._config.initial_capital)
            notional = equity * kelly * size_m
            qty      = max(1, int(notional / price))

            signal = {
                'strategy_id':   'ORCHESTRATOR',
                'instrument_id': token,
                'side':          c['side'],
                'quantity':      qty,
                'limit_price':   price,
                'stop_loss':     sl,
                'target':        tgt,
                'confidence':    round(float(c.get('confidence', MIN_CONF)), 3),
                'regime':        regime,
                'trigger_rule':  c.get('verdict'),
                'generated_at':  int(now * 1000),
                'metadata': {
                    'source':    'orchestrator',
                    'ev':        round(c.get('ev', 0), 3),
                    'rationale': c.get('summary', ''),
                    'lenses':    [l.get('strategy') for l in c.get('lenses', [])],
                },
            }
            bus.publish('strategy.signal', signal)
            self._last_signal[token] = now
            fired += 1
            log.info('ORCHESTRATOR SIGNAL: %s %s EV=%.2f conf=%.2f',
                     c['side'], c['symbol'], c.get('ev', 0), c.get('confidence', 0))

        bus.publish('orchestrator.scan_done', {
            'scan_count':   self._scan_count,
            'last_scan_ts': int(now * 1000),
            'fired':        fired,
            'top_results':  candidates[:12],
        })
        log.info('Orchestrator scan #%d: %d candidates, %d fired (regime=%s)',
                 self._scan_count, len(candidates), fired, regime)

    # ── Symbol analysis ───────────────────────────────────────────────────────

    def _analyse_symbol(self,
                        symbol: str, token: int,
                        regime: str, regime_mult: float,
                        vix: float, size_m: float,
                        strategy_wr: dict[str, float],
                        recent_news: list[dict],
                        now: float) -> dict | None:

        # ── Try to load daily OHLCV ───────────────────────────────────────────
        try:
            df1d = self._db.get_ohlcv_1d(token=token, limit=300)
        except Exception:
            df1d = None

        # Live price from tick cache (always available in paper mode)
        cached_tick = bus.get_cached(f'ticks.{token}') or {}
        live_price  = float(cached_tick.get('last_price') or 0)

        has_ohlcv = df1d is not None and not df1d.empty and len(df1d) >= 5

        if not has_ohlcv:
            if live_price <= 0:
                return None
            # Minimal result — show live price with no technical lenses
            news_lens = self._news_lens(symbol, recent_news, now, strategy_wr, live_price)
            lenses = [news_lens] if news_lens else []
            if lenses:
                side = lenses[0]['side']
                conf = lenses[0]['confidence']
                atr_est = live_price * 0.01
                sl  = round(live_price - 1.5 * atr_est, 2) if side == 'BUY' else round(live_price + 1.5 * atr_est, 2)
                tgt = round(live_price + 2.5 * atr_est, 2) if side == 'BUY' else round(live_price - 2.5 * atr_est, 2)
                ev  = round(conf * (abs(tgt - live_price) / max(abs(live_price - sl), 0.01)) * 1.0, 3)
                return {
                    'symbol': symbol, 'token': token, 'price': round(live_price, 2),
                    'regime': regime, 'side': side, 'verdict': 'NEWS',
                    'confidence': round(conf, 3), 'ev': ev,
                    'rsi': 50.0, 'ret_20d': 0.0,
                    'suggested_sl': sl, 'suggested_target': tgt,
                    'atr14': round(atr_est, 2), 'rr': round(ev / conf, 2) if conf > 0 else 0,
                    'vol_factor': 1.0,
                    'summary': lenses[0]['detail'],
                    'lenses': lenses,
                }
            return {
                'symbol': symbol, 'token': token, 'price': round(live_price, 2),
                'regime': regime, 'side': 'NEUTRAL', 'verdict': 'NO OHLCV',
                'confidence': 0.0, 'ev': 0.0, 'rsi': 50.0, 'ret_20d': 0.0,
                'suggested_sl': 0, 'suggested_target': 0,
                'summary': f'No OHLCV data. Live tick: {live_price:.2f}',
                'lenses': [],
            }

        close = df1d['close'].values.astype(float)
        high  = df1d['high'].values.astype(float)
        low   = df1d['low'].values.astype(float)
        vol   = df1d['volume'].values.astype(float)

        price = live_price if live_price > 0 else float(close[-1])

        def _ema(arr, n):
            k, e = 2.0 / (n + 1), float(arr[0])
            out = []
            for v in arr:
                e = v * k + e * (1 - k)
                out.append(e)
            return np.array(out)

        def _rsi(arr, n=14):
            d = np.diff(arr.astype(float))
            gains  = np.where(d > 0, d, 0.0)
            losses = np.where(d < 0, -d, 0.0)
            if len(gains) < n:
                return np.array([50.0])
            ag = np.mean(gains[:n])
            al = np.mean(losses[:n])
            result = []
            for i in range(n, len(d)):
                ag = (ag * (n - 1) + gains[i]) / n
                al = (al * (n - 1) + losses[i]) / n
                result.append(100 - 100 / (1 + ag / al) if al > 0 else 100.0)
            return np.array(result) if result else np.array([50.0])

        def _atr(h, l, c, n=14):
            tr = np.maximum(h[1:] - l[1:],
                            np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
            return float(np.mean(tr[-n:])) if len(tr) >= n else float(np.mean(tr)) if len(tr) else price * 0.01

        ema20 = _ema(close, 20)
        ema50 = _ema(close, min(50, len(close)))
        rsi14 = _rsi(close, min(14, len(close) - 1))

        ema20_v = float(ema20[-1])
        ema50_v = float(ema50[-1])
        rsi_v   = float(rsi14[-1])
        atr14   = _atr(high, low, close, min(14, len(close) - 1))
        high52w = float(np.max(high[-252:])) if len(high) >= 252 else float(np.max(high))
        low52w  = float(np.min(low[-252:])) if len(low) >= 252 else float(np.min(low))
        vol_avg = float(np.mean(vol[-20:])) if len(vol) >= 20 else float(np.mean(vol)) if len(vol) else 1.0
        vol_now = float(vol[-1]) if len(vol) else 1.0
        ret_20d = max(-0.25, min(0.25, (price - close[-20]) / close[-20])) if len(close) >= 20 else 0.0

        vol_factor = min(2.5, vol_now / max(vol_avg, 1.0))

        lenses: list[dict] = []

        # ── S2: 52-week breakout (regime adjusts confidence, not gate) ─────────
        pct_52h = (price - high52w) / max(high52w, 1)
        if price > high52w * 0.990 and regime not in ('bear', 'strong_bear'):
            vol_ok    = vol_now > vol_avg * 1.3
            base_conf = 0.65 if (price >= high52w and vol_ok) else 0.44
            conf      = base_conf * regime_mult * (0.7 + 0.6 * strategy_wr.get('S2', 0.5))
            lenses.append({
                'strategy':   'S2',
                'side':       'BUY',
                'triggered':  True,
                'confidence': round(min(conf, 0.90), 3),
                'detail':     f'At {pct_52h*100:.1f}% of 52w-high ({high52w:.0f}). Vol {"✓" if vol_ok else "weak"}.',
            })

        # ── S4: RSI mean reversion (fires in all regimes) ─────────────────────
        if rsi_v < 38:
            base_conf = min(0.48 + (38 - rsi_v) / 38 * 0.38, 0.86)
            conf      = base_conf * regime_mult * (0.7 + 0.6 * strategy_wr.get('S4', 0.5))
            lenses.append({
                'strategy':   'S4',
                'side':       'BUY',
                'triggered':  True,
                'confidence': round(min(conf, 0.90), 3),
                'detail':     f'RSI {rsi_v:.1f} — oversold.',
            })
        elif rsi_v > 63 and regime in ('bear', 'strong_bear', 'sideways'):
            base_conf = min(0.48 + (rsi_v - 63) / 37 * 0.38, 0.86)
            conf      = base_conf * regime_mult * (0.7 + 0.6 * strategy_wr.get('S4', 0.5))
            lenses.append({
                'strategy':   'S4',
                'side':       'SELL',
                'triggered':  True,
                'confidence': round(min(conf, 0.90), 3),
                'detail':     f'RSI {rsi_v:.1f} — overbought.',
            })

        # ── S5: EMA pullback (requires uptrend; regime adjusts confidence) ─────
        if price > ema50_v:
            prox = abs(price - ema20_v) / max(ema20_v, 1)
            if prox < 0.025 and 36 <= rsi_v <= 64:
                base_conf = 0.52 + (1 - prox / 0.025) * 0.15
                conf      = base_conf * regime_mult * (0.7 + 0.6 * strategy_wr.get('S5', 0.5))
                lenses.append({
                    'strategy':   'S5',
                    'side':       'BUY',
                    'triggered':  True,
                    'confidence': round(min(conf, 0.90), 3),
                    'detail':     f'Near EMA20 ({ema20_v:.0f}). RSI {rsi_v:.1f}.',
                })

        # ── S8: VIX asymmetry (indices only — self-gating by VIX level) ────────
        if symbol in ('NIFTY 50', 'NIFTY BANK', 'NIFTY FIN SERVICE'):
            if vix > 22 and regime in ('high_vol', 'bear', 'strong_bear'):
                lenses.append({
                    'strategy':   'S8',
                    'side':       'BUY',
                    'triggered':  True,
                    'confidence': round(0.60 * regime_mult, 3),
                    'detail':     f'VIX {vix:.1f} — elevated fear. Contrarian reversal.',
                })
            elif vix < 13 and regime in ('bear', 'strong_bear'):
                lenses.append({
                    'strategy':   'S8',
                    'side':       'SELL',
                    'triggered':  True,
                    'confidence': round(0.55 * regime_mult, 3),
                    'detail':     f'VIX {vix:.1f} — complacency in down-trend.',
                })

        # ── Momentum surge: above EMA20 with strong volume ────────────────────
        if price > ema20_v and vol_factor > 1.5:
            ema20_cross = (price / ema20_v - 1) * 100
            if 0.1 < ema20_cross < 2.5:
                conf = 0.48 * regime_mult * (0.7 + 0.6 * strategy_wr.get('ORCHESTRATOR', 0.5))
                lenses.append({
                    'strategy':   'MOM',
                    'side':       'BUY',
                    'triggered':  True,
                    'confidence': round(min(conf, 0.75), 3),
                    'detail':     f'Momentum: +{ema20_cross:.1f}% above EMA20, vol {vol_factor:.1f}×.',
                })

        # ── NEWS sentiment lens ───────────────────────────────────────────────
        news_lens = self._news_lens(symbol, recent_news, now, strategy_wr, price)
        if news_lens:
            lenses.append(news_lens)

        triggered = [l for l in lenses if l.get('triggered')]
        if not triggered:
            return {
                'symbol': symbol, 'token': token, 'price': round(price, 2),
                'regime': regime, 'side': 'NEUTRAL', 'verdict': 'WAIT',
                'confidence': 0.0, 'ev': 0.0,
                'rsi': round(rsi_v, 1), 'ret_20d': round(ret_20d * 100, 1),
                'suggested_sl': 0, 'suggested_target': 0,
                'summary': f'No setup. RSI {rsi_v:.0f}, {ret_20d*100:+.1f}% 20d.',
                'lenses': [],
            }

        buys  = [l for l in triggered if l['side'] == 'BUY']
        sells = [l for l in triggered if l['side'] == 'SELL']

        if len(buys) >= len(sells):
            side    = 'BUY'
            signals = buys
            sl      = round(price - 1.5 * atr14, 2)
            tgt     = round(price + 2.5 * atr14, 2)
        else:
            side    = 'SELL'
            signals = sells
            sl      = round(price + 1.5 * atr14, 2)
            tgt     = round(price - 2.5 * atr14, 2)

        avg_conf   = sum(l['confidence'] for l in signals) / len(signals)
        conv_bonus = 1.0 + (len(signals) - 1) * 0.10   # +10% per agreeing lens
        risk_pts   = abs(price - sl)
        reward_pts = abs(tgt - price)
        rr         = reward_pts / max(risk_pts, 0.01)
        ev         = avg_conf * rr * vol_factor * conv_bonus

        verdict = ('BUY' if avg_conf >= 0.60 else 'LEAN LONG') if side == 'BUY' \
            else ('SELL' if avg_conf >= 0.60 else 'LEAN SHORT')

        strats  = '+'.join(l['strategy'] for l in signals)
        summary = (f'{strats} → {side}. Regime: {regime}. '
                   f'Conf {avg_conf*100:.0f}%. R:R {rr:.1f}×. EV {ev:.2f}.')

        return {
            'symbol':           symbol,
            'token':            token,
            'price':            round(price, 2),
            'regime':           regime,
            'side':             side,
            'verdict':          verdict,
            'confidence':       round(avg_conf, 3),
            'ev':               round(ev, 3),
            'rsi':              round(rsi_v, 1),
            'ret_20d':          round(ret_20d * 100, 1),
            'suggested_sl':     sl,
            'suggested_target': tgt,
            'atr14':            round(atr14, 2),
            'rr':               round(rr, 2),
            'vol_factor':       round(vol_factor, 2),
            'summary':          summary,
            'lenses':           triggered,
        }

    def _news_lens(self, symbol: str, recent_news: list[dict],
                   now: float, strategy_wr: dict[str, float],
                   price: float) -> dict | None:
        """
        Compute a weighted sentiment score from recent news tagged to this symbol.
        Returns a lens dict if sentiment is strong enough (|net| >= 0.25), else None.
        """
        symbol_news = [
            n for n in recent_news
            if symbol in (n.get('instruments') or [])
        ]
        if not symbol_news:
            return None

        net = 0.0
        wt  = 0.0
        for n in symbol_news[-6:]:
            age_h = (now - n['published_at'] / 1000) / 3600
            decay = max(0.15, 1.0 - age_h / float(NEWS_WINDOW_H))
            sign  = 1 if n['sentiment'] == 'positive' else (-1 if n['sentiment'] == 'negative' else 0)
            net  += sign * float(n['score']) * decay
            wt   += decay

        if wt == 0 or abs(net / wt) < 0.25:
            return None

        ns      = net / wt
        side    = 'BUY' if ns > 0 else 'SELL'
        s_wr    = strategy_wr.get('NEWS', 0.5)
        conf    = min(0.30 + abs(ns) * 0.55, 0.68) * (0.7 + 0.6 * s_wr)
        n_count = len(symbol_news)

        return {
            'strategy':   'NEWS',
            'side':       side,
            'triggered':  True,
            'confidence': round(conf, 3),
            'detail':     (f'{"Positive" if ns > 0 else "Negative"} news sentiment '
                           f'({n_count} article{"s" if n_count > 1 else ""}, '
                           f'net={ns:+.2f}, decay-weighted).'),
        }
