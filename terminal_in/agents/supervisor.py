"""
TradingSupervisor — fast closed-loop control system over signal generation.

Complements the slow StrategyLearner (15-trade batch tuning) with reactions
inside 3–8 trades:

  1. Per-lens circuit breaker — a lens (S2/S4/S5/S8/MOM/NEWS) implicated in
     3 consecutive losing orchestrator trades is suppressed for 2h. The
     orchestrator reads 'supervisor.state' from the bus cache at scan start
     and drops suppressed lenses before scoring.
  2. Global throttle — 5 consecutive losses, or daily PnL beyond 60% of the
     loss cap, escalates 'supervisor.throttle' level 1: the orchestrator
     halves its candidate budget and raises MIN_EV 25%; the planner prompt
     is told to be extra selective. Decays after 4h without a new loss.
  3. Hard anomaly — 8 consecutive losses engages the existing KillSwitch
     global pause (gate enforcement + UI resume already exist). Never
     auto-resumes.

Breaker state is in-memory (published to the bus hot cache); restart clears
cooldowns — acceptable in paper mode, and audit_log keeps the history.
"""

import logging
import time
from threading import Event, Lock

from terminal_in.bus import bus
from terminal_in.agents.control import registry, kill_switch

log = logging.getLogger(__name__)

LENS_CONSEC_LOSSES      = 3
LENS_COOLDOWN_S         = 7200    # 2h
THROTTLE_CONSEC_LOSSES  = 5
HARD_STOP_CONSEC_LOSSES = 8
THROTTLE_DECAY_S        = 14400   # 4h without a new loss
DAILY_LOSS_THROTTLE_FRACTION = 0.6


class TradingSupervisor:
    def __init__(self, db, config):
        self._db     = db
        self._config = config
        self._lock   = Lock()

        self._lens_losses: dict[str, int] = {}        # lens → consecutive losses
        self._suppressed_until: dict[str, float] = {} # lens → epoch seconds
        self._consec_losses = 0                       # ORCHESTRATOR-wide
        self._throttle_level = 0
        self._last_loss_ts = 0.0

        registry.register('SUPERVISOR', 'system', 'Closed-Loop Control')
        bus.subscribe('trade.closed', self._on_trade_closed)
        bus.subscribe('settlement.day_open', self._on_day_open)
        log.info('TradingSupervisor initialised (lens breaker=%d losses/%dh, '
                 'throttle=%d, hard stop=%d)',
                 LENS_CONSEC_LOSSES, LENS_COOLDOWN_S // 3600,
                 THROTTLE_CONSEC_LOSSES, HARD_STOP_CONSEC_LOSSES)

    # ── State for orchestrator / API / UI ────────────────────────────────────

    def get_state(self) -> dict:
        now = time.time()
        with self._lock:
            return {
                'suppressed_lenses': {
                    lens: int((until - now))
                    for lens, until in self._suppressed_until.items() if until > now
                },
                'lens_loss_streaks': dict(self._lens_losses),
                'consec_losses':     self._consec_losses,
                'throttle_level':    self._throttle_level,
            }

    # ── Event handlers ───────────────────────────────────────────────────────

    def _on_trade_closed(self, trade: dict):
        try:
            if str(trade.get('strategy_id') or '') != 'ORCHESTRATOR':
                return
            pnl = float(trade.get('pnl') or 0.0)
            lenses = self._trade_lenses(trade)
            if pnl > 0:
                self._on_win(lenses)
            else:
                self._on_loss(lenses)
        except Exception:
            log.exception('Supervisor: trade.closed handling failed')

    def _on_win(self, lenses: list[str]):
        with self._lock:
            self._consec_losses = 0
            for lens in lenses:
                self._lens_losses[lens] = 0
        self._publish_state()

    def _on_loss(self, lenses: list[str]):
        engage_pause = False
        newly_suppressed = []
        with self._lock:
            self._consec_losses += 1
            self._last_loss_ts = time.time()

            for lens in lenses:
                self._lens_losses[lens] = self._lens_losses.get(lens, 0) + 1
                if self._lens_losses[lens] >= LENS_CONSEC_LOSSES:
                    self._suppressed_until[lens] = time.time() + LENS_COOLDOWN_S
                    self._lens_losses[lens] = 0
                    newly_suppressed.append(lens)

            if self._consec_losses >= HARD_STOP_CONSEC_LOSSES:
                engage_pause = True
            elif self._consec_losses >= THROTTLE_CONSEC_LOSSES:
                self._throttle_level = 1

        for lens in newly_suppressed:
            log.warning('SUPERVISOR: lens %s SUPPRESSED for %dh (%d consecutive losses)',
                        lens, LENS_COOLDOWN_S // 3600, LENS_CONSEC_LOSSES)
            self._audit('LENS_SUPPRESSED', f'{lens} for {LENS_COOLDOWN_S}s')
        if self._throttle_level:
            bus.publish('supervisor.throttle', {
                'level': self._throttle_level,
                'reason': f'{self._consec_losses} consecutive losses',
            })
        if engage_pause:
            self._audit('HARD_STOP', f'{self._consec_losses} consecutive losses')
            kill_switch.engage_global_pause(
                f'supervisor: {self._consec_losses} consecutive-loss anomaly')
        self._publish_state()

    def _on_day_open(self, _payload=None):
        with self._lock:
            self._consec_losses = 0
            self._throttle_level = 0
        bus.publish('supervisor.throttle', {'level': 0, 'reason': 'new trading day'})
        self._publish_state()

    # ── Run loop (cooldown expiry, daily-loss throttle, heartbeat) ───────────

    def run(self, stop_event: Event):
        log.info('TradingSupervisor loop started')
        while not stop_event.is_set():
            try:
                self._tick()
            except Exception:
                log.exception('Supervisor tick failed')
            stop_event.wait(60)

    def _tick(self):
        now = time.time()
        changed = False
        with self._lock:
            for lens, until in list(self._suppressed_until.items()):
                if until <= now:
                    del self._suppressed_until[lens]
                    changed = True
                    log.info('SUPERVISOR: lens %s suppression expired', lens)
            if (self._throttle_level
                    and now - self._last_loss_ts > THROTTLE_DECAY_S):
                self._throttle_level = 0
                changed = True
                log.info('SUPERVISOR: throttle decayed (no loss for %dh)',
                         THROTTLE_DECAY_S // 3600)

        # Daily-loss proximity throttle (independent of consecutive losses)
        try:
            pnl_state = bus.get_cached('pnl.update') or {}
            daily_pnl = float(pnl_state.get('daily_pnl') or 0.0)
            equity    = float(pnl_state.get('equity') or self._config.initial_capital)
            loss_cap  = self._config.daily_loss_cap * equity
            if daily_pnl < 0 and abs(daily_pnl) >= DAILY_LOSS_THROTTLE_FRACTION * loss_cap:
                with self._lock:
                    if self._throttle_level == 0:
                        self._throttle_level = 1
                        changed = True
                        self._last_loss_ts = time.time()
                bus.publish('supervisor.throttle', {
                    'level': 1,
                    'reason': f'daily PnL {daily_pnl:,.0f} at '
                              f'{abs(daily_pnl)/loss_cap:.0%} of loss cap',
                })
        except Exception:
            pass

        registry.heartbeat('SUPERVISOR')
        if changed:
            if self._throttle_level == 0:
                bus.publish('supervisor.throttle', {'level': 0, 'reason': 'decay/expiry'})
            self._publish_state()
        else:
            self._publish_state()

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _trade_lenses(self, trade: dict) -> list[str]:
        """Lens attribution from the trade's signal metadata (persisted by gate)."""
        meta = trade.get('metadata') or {}
        if isinstance(meta, str):
            try:
                import json
                meta = json.loads(meta)
            except Exception:
                meta = {}
        lenses = meta.get('lenses') or []
        return [str(l) for l in lenses if l]

    def _publish_state(self):
        bus.publish('supervisor.state', self.get_state())

    def _audit(self, action: str, detail: str):
        try:
            if self._db is not None:
                self._db.audit('SUPERVISOR', action, payload={'detail': detail})
        except Exception:
            pass
