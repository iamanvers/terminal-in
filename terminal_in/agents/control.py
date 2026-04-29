"""
AgentRegistry  — live state (status/heartbeat/evals/signals/threshold) for every agent.
KillSwitch     — global pause, per-symbol block, kill-all, audit trail.

Both are module-level singletons; import and use directly:

    from terminal_in.agents.control import registry, kill_switch
"""

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from threading import Lock
from typing import Optional

from terminal_in.bus import bus

log = logging.getLogger(__name__)

_STRATEGY_DESCRIPTIONS = {
    'S1': 'Intraday Opening Range Breakout',
    'S2': '52-Week High Breakout',
    'S3': 'Midcap Momentum Breakout',
    'S4': 'RSI Mean Reversion',
    'S5': 'EMA Pullback',
    'S6': 'Pairs Cointegration',
    'S8': 'VIX Spike Asymmetry',
    'S9': 'Hawkes Process Momentum',
    'ORCHESTRATOR': 'Multi-Lens Agentic Scanner',
    'ENGINE':       'Strategy Engine Loop',
    'GATE':         'M2 Risk Supervisor',
    'BROKER':       'Paper Broker',
}


@dataclass
class AgentState:
    agent_id:             str
    agent_type:           str    # 'strategy' | 'orchestrator' | 'system'
    description:          str    = ''
    status:               str    = 'idle'   # running | paused | error | idle
    last_heartbeat:       float  = field(default_factory=time.time)
    last_eval_ts:         float  = 0.0
    last_signal_ts:       float  = 0.0
    eval_count:           int    = 0
    signal_count:         int    = 0
    confidence_threshold: float  = 0.45
    last_error:           str    = ''

    def to_dict(self) -> dict:
        now = time.time()
        return {
            'agent_id':             self.agent_id,
            'agent_type':           self.agent_type,
            'description':          self.description,
            'status':               self.status,
            'last_heartbeat':       int(self.last_heartbeat * 1000),
            'heartbeat_age_s':      int(now - self.last_heartbeat),
            'last_eval_ts':         int(self.last_eval_ts * 1000),
            'last_signal_ts':       int(self.last_signal_ts * 1000),
            'eval_count':           self.eval_count,
            'signal_count':         self.signal_count,
            'confidence_threshold': round(self.confidence_threshold, 3),
            'last_error':           self.last_error,
        }


class AgentRegistry:
    def __init__(self):
        self._agents: dict[str, AgentState] = {}
        self._lock = Lock()

    def register(self, agent_id: str, agent_type: str,
                 description: str = '', confidence_threshold: float = 0.45):
        desc = description or _STRATEGY_DESCRIPTIONS.get(agent_id, '')
        with self._lock:
            if agent_id not in self._agents:
                self._agents[agent_id] = AgentState(
                    agent_id=agent_id,
                    agent_type=agent_type,
                    description=desc,
                    confidence_threshold=confidence_threshold,
                    last_heartbeat=time.time(),
                )

    # ── Called by agents during their normal work cycle ───────────────────────

    def heartbeat(self, agent_id: str):
        with self._lock:
            s = self._agents.get(agent_id)
            if s and s.status != 'paused':
                s.last_heartbeat = time.time()
                s.status = 'running'

    def record_eval(self, agent_id: str):
        with self._lock:
            s = self._agents.get(agent_id)
            if s:
                s.eval_count += 1
                s.last_eval_ts = time.time()
                s.last_heartbeat = time.time()
                if s.status != 'paused':
                    s.status = 'running'

    def record_signal(self, agent_id: str):
        with self._lock:
            s = self._agents.get(agent_id)
            if s:
                s.signal_count += 1
                s.last_signal_ts = time.time()

    def record_error(self, agent_id: str, error: str):
        with self._lock:
            s = self._agents.get(agent_id)
            if s:
                s.status = 'error'
                s.last_error = str(error)[:300]

    # ── Control operations (called by API routes) ─────────────────────────────

    def pause(self, agent_id: str):
        with self._lock:
            s = self._agents.get(agent_id)
            if s:
                s.status = 'paused'
        log.warning('Agent %s PAUSED', agent_id)
        bus.publish('agent.status_changed', {'agent_id': agent_id, 'status': 'paused'})

    def resume(self, agent_id: str):
        with self._lock:
            s = self._agents.get(agent_id)
            if s:
                s.status = 'running'
                s.last_heartbeat = time.time()
        log.info('Agent %s RESUMED', agent_id)
        bus.publish('agent.status_changed', {'agent_id': agent_id, 'status': 'running'})

    def set_threshold(self, agent_id: str, threshold: float):
        clamped = round(max(0.0, min(1.0, threshold)), 3)
        with self._lock:
            s = self._agents.get(agent_id)
            if s:
                s.confidence_threshold = clamped
        log.info('Agent %s confidence threshold → %.3f', agent_id, clamped)
        bus.publish('agent.threshold_changed', {'agent_id': agent_id, 'threshold': clamped})

    # ── Query helpers ─────────────────────────────────────────────────────────

    def is_paused(self, agent_id: str) -> bool:
        with self._lock:
            s = self._agents.get(agent_id)
            return s is not None and s.status == 'paused'

    def get_threshold(self, agent_id: str) -> float:
        with self._lock:
            s = self._agents.get(agent_id)
            return s.confidence_threshold if s else 0.45

    def get_all(self) -> list[dict]:
        with self._lock:
            return [s.to_dict() for s in self._agents.values()]

    def get(self, agent_id: str) -> Optional[dict]:
        with self._lock:
            s = self._agents.get(agent_id)
            return s.to_dict() if s else None


class KillSwitch:
    """
    Global risk controls. Checks are enforced inside RiskSupervisor.gate()
    at the very top — before any other check — so they cannot be bypassed.
    """

    def __init__(self):
        self._lock = Lock()
        self._global_pause: bool = False
        self._blocked_tokens: set[int] = set()
        self._audit: deque = deque(maxlen=500)

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def global_pause(self) -> bool:
        return self._global_pause

    def is_blocked(self, token: int) -> bool:
        return int(token) in self._blocked_tokens

    # ── Engage / disengage ────────────────────────────────────────────────────

    def engage_global_pause(self, reason: str = 'manual'):
        with self._lock:
            self._global_pause = True
            self._log_action('GLOBAL_PAUSE', reason)
        log.warning('KILL SWITCH: GLOBAL PAUSE ENGAGED — %s', reason)
        bus.publish('kill_switch.global_pause', {'paused': True, 'reason': reason})

    def disengage_global_pause(self, reason: str = 'manual'):
        with self._lock:
            self._global_pause = False
            self._log_action('GLOBAL_RESUME', reason)
        log.info('KILL SWITCH: global pause DISENGAGED — %s', reason)
        bus.publish('kill_switch.global_pause', {'paused': False, 'reason': reason})

    def block_symbol(self, token: int, reason: str = 'manual'):
        token = int(token)
        with self._lock:
            self._blocked_tokens.add(token)
            self._log_action('BLOCK_SYMBOL', f'token={token} {reason}')
        log.warning('KILL SWITCH: symbol %d BLOCKED', token)

    def unblock_symbol(self, token: int):
        token = int(token)
        with self._lock:
            self._blocked_tokens.discard(token)
            self._log_action('UNBLOCK_SYMBOL', f'token={token}')
        log.info('KILL SWITCH: symbol %d UNBLOCKED', token)

    # ── State ─────────────────────────────────────────────────────────────────

    def get_state(self) -> dict:
        with self._lock:
            return {
                'global_pause':   self._global_pause,
                'blocked_tokens': list(self._blocked_tokens),
            }

    def get_audit(self, limit: int = 50) -> list[dict]:
        with self._lock:
            entries = list(reversed(self._audit))
        return entries[:limit]

    def _log_action(self, action: str, detail: str):
        self._audit.append({
            'ts':     int(time.time() * 1000),
            'action': action,
            'detail': detail,
        })


# Module-level singletons
registry   = AgentRegistry()
kill_switch = KillSwitch()
