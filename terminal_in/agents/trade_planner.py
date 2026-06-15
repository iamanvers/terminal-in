"""
TradePlanner — the LLM judge that sits between the orchestrator's
deterministic lens scanner and the M2 risk gate.

Flow (when config.planner_enabled):
  orchestrator publishes 'planner.candidates' (one batch per scan, ≤5 eligible
  candidates + portfolio/regime context) instead of firing directly.
  The planner makes ONE LLM call per scan (Ollama, format=json) asking the
  model to approve/reject/size each candidate with reasoning, validates the
  verdicts, then publishes approved ones as 'strategy.signal' — which flow
  through the existing 12-check risk gate unchanged. The planner can never
  bypass risk; it can only veto or shrink.

Degraded mode (Ollama down / timeout / unparseable output after retry):
  deterministic verdicts with a STRICTER bar than the orchestrator's own
  (EV ≥ 1.25× MIN_EV, persistence ≥ 2, smoothed conf ≥ MIN_CONF + 0.05),
  flagged planner_mode='degraded' on every event, decision row, and signal —
  never silent, never random.

All verdicts (approve/reject, both modes) are persisted via DecisionMemory,
whose hindsight loop later scores them — and that history is fed back into
the next prompt. The judge sees how its past judgements played out.
"""

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass
from threading import Condition, Event

import requests

from terminal_in.bus import bus
from terminal_in.agents.control import registry

log = logging.getLogger(__name__)

OLLAMA_BASE  = os.environ.get('OLLAMA_HOST', 'http://localhost:11434')
OLLAMA_MODEL = os.environ.get('OLLAMA_MODEL', 'qwen2.5:3b')

PLAN_TIMEOUT_S   = int(os.environ.get('PLANNER_TIMEOUT_S', '60'))  # << 120s scan interval
PROBE_TIMEOUT_S  = 3
MAX_APPROVED     = 3
SIZE_FACTOR_MIN  = 0.25
SIZE_FACTOR_MAX  = 1.5

# Degraded-mode deterministic high bar (stricter than orchestrator MIN_*)
DEGRADED_MIN_EV          = 1.5    # 1.25 × orchestrator MIN_EV (1.2)
DEGRADED_MIN_PERSISTENCE = 2
DEGRADED_MIN_CONF        = 0.50   # MIN_CONF (0.45) + 0.05

_SYSTEM_PROMPT = """You are the final trade judge for an NSE algorithmic trading desk.
Deterministic strategy lenses have pre-screened these candidates. Your job is to pick
only the trades worth making. Capital preservation beats activity: approving everything
is a failure mode, and so is approving correlated bets. Consider regime fit, lens
convergence, persistence across scans, portfolio concentration, and the hindsight record
of past decisions provided.

Respond with ONLY this JSON schema:
{"decisions":[{"symbol":"RELIANCE","action":"approve","size_factor":1.0,"reason":"3 lenses agree, 2-scan persistence, no conflicting news"}],"market_note":"one line on overall conditions"}

Rules:
- action must be "approve" or "reject" for EVERY candidate listed
- size_factor between 0.25 and 1.5 (1.0 = orchestrator's Kelly size; shrink when unsure)
- approve at most {max_approved} candidates; reject the rest with a reason
- reason must cite specifics (lenses, RSI, persistence, regime, portfolio overlap)
- write a fresh reason in your own words for each decision — NEVER copy text
  from the PAST DECISIONS section; it is outcome history, not a template"""


@dataclass
class Verdict:
    symbol: str
    action: str          # 'approve' | 'reject'
    size_factor: float
    reason: str


class TradePlanner:
    def __init__(self, db, config, memory, learner=None, attach_bus=True):
        self._db      = db
        self._config  = config
        self._memory  = memory
        self._learner = learner

        self._cond     = Condition()
        self._session  = requests.Session()  # keep-alive to Ollama across calls
        self._pending: dict | None = None   # latest-wins batch queue
        self._last_verdict: dict = {}
        self._mode: str = 'idle'            # llm | degraded | off | idle
        self._last_latency_ms: int | None = None
        self._plan_count = 0

        # attach_bus=False → standalone judge (backtest replay): no registry
        # entry, no live 'planner.candidates' subscription. judge_batch() and
        # the LLM/degraded path work identically without the bus.
        if attach_bus:
            registry.register('PLANNER', 'orchestrator', 'LLM Trade Judge')
            bus.subscribe('planner.candidates', self._enqueue)
            log.info('TradePlanner initialised (model=%s, timeout=%ds)', OLLAMA_MODEL, PLAN_TIMEOUT_S)

    # ── Public state for API/UI ──────────────────────────────────────────────

    def get_state(self) -> dict:
        return {
            'mode':            self._mode,
            'model':           OLLAMA_MODEL,
            'plan_count':      self._plan_count,
            'last_latency_ms': self._last_latency_ms,
            'last_verdict':    self._last_verdict,
        }

    # ── Batch intake (latest-wins) ───────────────────────────────────────────

    def _enqueue(self, batch: dict):
        with self._cond:
            if self._pending is not None:
                # Merge instead of dropping: engine signals and orchestrator
                # scans share this queue — a candidate must never be lost to
                # a race. Newest features win per symbol.
                merged = {c['symbol']: c for c in self._pending.get('candidates', [])}
                for c in batch.get('candidates', []):
                    merged[c['symbol']] = c
                batch = {**self._pending, **batch,
                         'candidates': list(merged.values())}
                log.info('Planner: merged pending batch (%d candidates)',
                         len(batch['candidates']))
            self._pending = batch
            self._cond.notify()

    def run(self, stop_event: Event):
        log.info('TradePlanner loop started')
        self._warmup()
        while not stop_event.is_set():
            with self._cond:
                while self._pending is None and not stop_event.is_set():
                    self._cond.wait(timeout=2.0)
                    registry.alive('PLANNER')   # waiting, not stopped — keep HB fresh
                batch, self._pending = self._pending, None
            if batch is None or stop_event.is_set():
                continue
            try:
                self._plan(batch)
                registry.heartbeat('PLANNER')
            except Exception:
                log.exception('Planner: planning round failed')

    # ── Planning round ───────────────────────────────────────────────────────

    def _plan(self, batch: dict) -> None:
        if not (batch.get('candidates') or []):
            return
        verdicts, mode, latency_ms = self.judge_batch(batch, use_llm=True)
        if not verdicts:
            return
        if mode == 'degraded':
            log.warning('Planner: DEGRADED mode — deterministic high-bar verdicts '
                        '(Ollama unavailable or output invalid)')
        self._mode = mode
        self._last_latency_ms = latency_ms
        self._plan_count += 1
        self._emit(batch, verdicts, mode, latency_ms)

    def judge_batch(self, batch: dict, use_llm: bool = True) -> tuple[list[Verdict], str, int]:
        """Rule on a candidate batch and return (verdicts, mode, latency_ms).

        Pure: no bus publish, no DecisionMemory write — so the backtest engine
        can replay the EXACT live judging logic (formula parity). `use_llm=False`
        forces the deterministic degraded bar without probing Ollama (lets a
        backtest run a clean degraded baseline, or skip the LLM once a sampling
        budget is spent)."""
        candidates = batch.get('candidates') or []
        if not candidates:
            return [], 'idle', 0

        t0 = time.monotonic()
        verdicts: list[Verdict] | None = None
        mode = 'degraded'

        if use_llm and self._ollama_available():
            raw = self._call_llm(self._build_messages(batch))
            if raw is not None:
                verdicts = self._validate(raw, candidates)
                if verdicts is None:
                    # one retry with the parse error surfaced to the model
                    raw2 = self._call_llm(self._build_messages(batch, retry_note=(
                        'Your previous output was not valid against the schema. '
                        'Return ONLY the JSON object, no prose.')))
                    if raw2 is not None:
                        verdicts = self._validate(raw2, candidates)
            if verdicts is not None:
                mode = 'llm'

        if verdicts is None:
            verdicts = self._degraded_verdicts(candidates)

        return verdicts, mode, int((time.monotonic() - t0) * 1000)

    # ── Prompt construction ──────────────────────────────────────────────────

    def _build_messages(self, batch: dict, retry_note: str = '') -> list[dict]:
        lines = []
        for c in batch.get('candidates', []):
            lenses = '+'.join(l.get('strategy', '?') for l in c.get('lenses', []))
            lines.append(
                f"{c.get('symbol')} {c.get('side')} ev={c.get('ev', 0):.2f} "
                f"conf={c.get('conf_smoothed', c.get('confidence', 0)):.2f} "
                f"persist={c.get('persistence', 0)} lenses={lenses or 'none'} "
                f"rr={c.get('rr', 0):.1f} rsi={c.get('rsi', 50):.0f} "
                f"vol={c.get('vol_factor', 1):.1f}x price={c.get('price', 0):.1f}"
            )

        positions = batch.get('open_positions') or []
        pos_lines = [
            f"{p.get('symbol', '?')} {p.get('side', '?')} qty={p.get('qty', 0)} "
            f"upnl={p.get('unrealized', 0):+.0f}"
            for p in positions
        ] or ['none']

        memory_block = ''
        if self._memory is not None:
            memory_block = self._memory.context_block(10)

        throttle = batch.get('throttle', 0)
        user = (
            f"REGIME: {batch.get('regime', '?')} | VIX: {batch.get('india_vix', 0):.1f} "
            f"| EQUITY: {batch.get('equity', 0):,.0f}\n"
            + (f"SYSTEM THROTTLED (recent losses) — be extra selective.\n" if throttle else '')
            + f"OPEN POSITIONS:\n" + '\n'.join(pos_lines) + '\n'
            + f"CANDIDATES:\n" + '\n'.join(lines)
            + (f"\nPAST DECISIONS (hindsight):\n{memory_block}" if memory_block else '')
            + (f"\n{retry_note}" if retry_note else '')
        )
        return [
            {'role': 'system', 'content': _SYSTEM_PROMPT.replace('{max_approved}', str(MAX_APPROVED))},
            {'role': 'user', 'content': user},
        ]

    # ── Ollama client ────────────────────────────────────────────────────────

    def _warmup(self):
        """Load the model into Ollama's memory at startup so the first real
        planning call doesn't spend ~30s on cold load inside its timeout."""
        if not self._ollama_available():
            return
        try:
            self._session.post(
                f'{OLLAMA_BASE}/api/generate',
                json={'model': OLLAMA_MODEL, 'prompt': 'ok', 'stream': False,
                      'options': {'num_predict': 1}},
                timeout=PLAN_TIMEOUT_S,
            )
            log.info('Planner: model %s warmed up', OLLAMA_MODEL)
        except Exception as e:
            log.debug('Planner warmup failed (non-fatal): %s', str(e)[:80])

    def _ollama_available(self) -> bool:
        try:
            r = self._session.get(f'{OLLAMA_BASE}/api/tags', timeout=PROBE_TIMEOUT_S)
            return r.status_code == 200
        except Exception:
            return False

    def _call_llm(self, messages: list[dict]) -> str | None:
        try:
            r = self._session.post(
                f'{OLLAMA_BASE}/api/chat',
                json={
                    'model':    OLLAMA_MODEL,
                    'messages': messages,
                    'stream':   False,
                    'format':   'json',
                    'options':  {'temperature': 0.1, 'num_predict': 500},
                },
                timeout=PLAN_TIMEOUT_S,
            )
            r.raise_for_status()
            return (r.json().get('message') or {}).get('content') or None
        except Exception as e:
            log.warning('Planner: LLM call failed: %s', str(e)[:120])
            return None

    # ── Verdict validation ───────────────────────────────────────────────────

    def _validate(self, raw: str, candidates: list[dict]) -> list[Verdict] | None:
        try:
            data = json.loads(raw)
            decisions = data.get('decisions')
            if not isinstance(decisions, list):
                return None
        except Exception:
            return None

        by_symbol = {c['symbol']: c for c in candidates}
        verdicts: dict[str, Verdict] = {}
        for d in decisions:
            if not isinstance(d, dict):
                continue
            sym = str(d.get('symbol', '')).strip().upper()
            if sym not in by_symbol:
                continue  # hallucinated symbol — drop
            action = str(d.get('action', '')).lower()
            if action not in ('approve', 'reject'):
                continue
            try:
                sf = float(d.get('size_factor', 1.0))
            except (TypeError, ValueError):
                sf = 1.0
            sf = max(SIZE_FACTOR_MIN, min(SIZE_FACTOR_MAX, sf))
            verdicts[sym] = Verdict(
                symbol=sym, action=action, size_factor=sf,
                reason=str(d.get('reason', ''))[:300],
            )

        if not verdicts:
            return None

        # Candidates the LLM ignored default to reject (it must rule on all)
        for sym in by_symbol:
            if sym not in verdicts:
                verdicts[sym] = Verdict(sym, 'reject', 1.0, 'not selected by planner')

        # Enforce the approve cap: keep highest-EV approvals
        approved = [v for v in verdicts.values() if v.action == 'approve']
        if len(approved) > MAX_APPROVED:
            approved.sort(key=lambda v: by_symbol[v.symbol].get('ev', 0), reverse=True)
            for v in approved[MAX_APPROVED:]:
                v.action = 'reject'
                v.reason = f'approve cap ({MAX_APPROVED}) — outranked. ' + v.reason

        return list(verdicts.values())

    # ── Degraded mode ────────────────────────────────────────────────────────

    def _degraded_verdicts(self, candidates: list[dict]) -> list[Verdict]:
        verdicts = []
        approved = 0
        for c in sorted(candidates, key=lambda x: x.get('ev', 0), reverse=True):
            ok = (approved < MAX_APPROVED
                  and float(c.get('ev', 0)) >= DEGRADED_MIN_EV
                  and int(c.get('persistence', 0)) >= DEGRADED_MIN_PERSISTENCE
                  and float(c.get('conf_smoothed', c.get('confidence', 0))) >= DEGRADED_MIN_CONF)
            if ok:
                approved += 1
                verdicts.append(Verdict(
                    c['symbol'], 'approve', 1.0,
                    'degraded: deterministic high-bar pass (Ollama unavailable)'))
            else:
                verdicts.append(Verdict(
                    c['symbol'], 'reject', 1.0,
                    'degraded: below deterministic high bar (Ollama unavailable)'))
        return verdicts

    # ── Emission ─────────────────────────────────────────────────────────────

    def _emit(self, batch: dict, verdicts: list[Verdict], mode: str, latency_ms: int) -> None:
        by_symbol = {c['symbol']: c for c in batch.get('candidates', [])}
        verdict_records: dict[str, dict] = {}
        fired = 0

        for v in verdicts:
            c = by_symbol.get(v.symbol)
            record = {'action': v.action, 'reason': v.reason, 'size_factor': v.size_factor}
            if v.action == 'approve' and c is not None:
                signal = dict(c.get('signal') or {})
                if signal:
                    signal_id = uuid.uuid4().hex[:16]
                    qty = max(1, int(int(signal.get('quantity', 1)) * v.size_factor))
                    signal['quantity']  = qty
                    signal['signal_id'] = signal_id
                    meta = dict(signal.get('metadata') or {})
                    meta['planner'] = {
                        'action': v.action, 'reason': v.reason,
                        'size_factor': v.size_factor, 'mode': mode,
                        'latency_ms': latency_ms,
                    }
                    signal['metadata'] = meta
                    bus.publish('strategy.signal', signal)
                    registry.record_signal('PLANNER')
                    record['signal_id'] = signal_id
                    fired += 1
                    log.info('PLANNER APPROVE [%s]: %s %s sf=%.2f — %s',
                             mode, c.get('side'), v.symbol, v.size_factor, v.reason[:80])
            verdict_records[v.symbol] = record

        payload = {
            'scan_id':    batch.get('scan_id'),
            'ts':         int(time.time() * 1000),
            'mode':       mode,
            'model':      OLLAMA_MODEL if mode == 'llm' else None,
            'latency_ms': latency_ms,
            'fired':      fired,
            'verdicts': [
                {'symbol': v.symbol, 'side': (by_symbol.get(v.symbol) or {}).get('side'),
                 'action': v.action, 'size_factor': v.size_factor, 'reason': v.reason,
                 'ev': (by_symbol.get(v.symbol) or {}).get('ev')}
                for v in verdicts
            ],
        }
        self._last_verdict = payload
        bus.publish('planner.verdict', payload)

        if self._memory is not None:
            self._memory.record_scan(
                scan_id=int(batch.get('scan_id') or 0),
                candidates=list(by_symbol.values()),
                verdicts=verdict_records,
                mode=mode,
                latency_ms=latency_ms,
                regime=str(batch.get('regime') or '?'),
                india_vix=float(batch.get('india_vix') or 0.0),
            )
