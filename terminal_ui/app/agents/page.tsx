'use client'
import React, { useCallback, useEffect, useRef, useState } from 'react'
import {
  api, AgentState, AuditEntry, DecisionRecord, EventRecord,
  KillSwitchState, RegimeState, PortfolioSummary, SignalLineage,
  SystemHealth, Scorecard, LearnerParams, OrchestratorState, OrchestratorResult,
  AgentQueryResponse, NSESymbol,
  PlannerState, PlannerVerdict, AgentDecision, SupervisorState, BackendHealth,
} from '@/lib/api'
import { getSocket } from '@/lib/socket'

// ─────────────────────────────────────────────────────────────────────────────
// CSS
// ─────────────────────────────────────────────────────────────────────────────
const CSS = `
@keyframes pulse-ring  { 0%{transform:scale(1);opacity:.7} 70%,100%{transform:scale(2.4);opacity:0} }
@keyframes pulse-core  { 0%,100%{transform:scale(1)} 50%{transform:scale(1.18)} }
@keyframes blink       { 0%,100%{opacity:1} 50%{opacity:.35} }
@keyframes sweep-in    { from{opacity:0;transform:translateY(-4px)} to{opacity:1;transform:translateY(0)} }
.ap-run .ring  { animation: pulse-ring 2s cubic-bezier(.215,.61,.355,1) infinite }
.ap-run .core  { animation: pulse-core 2s ease-in-out infinite }
.ap-err .core  { animation: blink 1s ease-in-out infinite }
.row-in        { animation: sweep-in .2s ease-out }
::-webkit-scrollbar            { width:4px; height:4px }
::-webkit-scrollbar-track      { background:#0A0A0A }
::-webkit-scrollbar-thumb      { background:#2A2A2A; border-radius:2px }
::-webkit-scrollbar-thumb:hover{ background:#3A3A3A }
`
function StyleTag() { return <style dangerouslySetInnerHTML={{ __html: CSS }} /> }

// ─────────────────────────────────────────────────────────────────────────────
// Constants
// ─────────────────────────────────────────────────────────────────────────────
const C = {
  bg: '#070707', card: '#0C0C0C', panel: '#0D0D0D',
  border: '#161616', border2: '#1E1E1E',
  text: '#D0D0D0', sub: '#888', muted: '#444', dim: '#1E1E1E',
  green: '#00C853', red: '#E53935', amber: '#F7931E',
  blue: '#1E88E5', purple: '#AB47BC', teal: '#00BCD4',
  run: '#00C853', warn: '#F7931E', err: '#E53935', idle: '#2A2A2A',
}

const STATUS_C: Record<string, string> = {
  running: C.run, paused: C.warn, error: C.err, idle: C.idle,
}

const AGENT_DESC: Record<string, string> = {
  ENGINE:       'Strategy Evaluation Loop · 60s cycle',
  GATE:         'M2 Pre-Trade Risk Gate · 12 checks',
  BROKER:       'Paper Fill Simulator · 0.03% slip + ₹20',
  ORCHESTRATOR: 'Multi-Lens Agentic Scanner',
  S1: 'Opening Range Breakout (index)',
  S2: '52-Week High/Low Breakout',
  S3: 'Midcap Momentum Breakout',
  S4: 'RSI Mean Reversion',
  S5: 'EMA Pullback',
  S6: 'Pairs Cointegration',
  S8: 'VIX Spike Asymmetry',
  S9: 'Hawkes Process Momentum',
}

const AGENT_ICON: Record<string, string> = {
  ENGINE: '⚙', GATE: '🛡', BROKER: '📋', ORCHESTRATOR: '🔮',
  S1: '⊙', S2: '△', S3: '◈', S4: '↺', S5: '⊿', S6: '⇌', S8: '⚡', S9: '∿',
}

// ─────────────────────────────────────────────────────────────────────────────
// Formatters
// ─────────────────────────────────────────────────────────────────────────────
function fmtAge(s: number) {
  if (s < 60) return `${s}s`
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`
  return `${Math.floor(s / 3600)}h`
}
function fmtN(n: number) { return n >= 1e6 ? `${(n/1e6).toFixed(1)}M` : n >= 1000 ? `${(n/1000).toFixed(1)}k` : String(n) }
function fmtTs(ms: number) { return new Date(ms).toLocaleTimeString('en-IN', { hour12: false }) }
function fmtPct(n: number) { return `${(n * 100).toFixed(1)}%` }
function ageC(s: number) { return s < 30 ? C.run : s < 90 ? C.warn : C.err }
function isNSEOpen() {
  const d = new Date(Date.now() + 5.5 * 3600_000)
  const m = d.getUTCHours() * 60 + d.getUTCMinutes()
  const dow = d.getUTCDay()
  return dow >= 1 && dow <= 5 && m >= 9 * 60 + 15 && m <= 15 * 60 + 30
}

// ─────────────────────────────────────────────────────────────────────────────
// Primitives
// ─────────────────────────────────────────────────────────────────────────────
function Dot({ status, size = 8 }: { status: string; size?: number }) {
  const color = STATUS_C[status] ?? C.idle
  const cls = status === 'running' ? 'ap-run' : status === 'error' ? 'ap-err' : ''
  return (
    <span className={cls} style={{ position: 'relative', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: size + 8, height: size + 8, flexShrink: 0 }}>
      <span className="ring" style={{ position: 'absolute', width: size, height: size, borderRadius: '50%', background: color, opacity: 0 }} />
      <span className="core" style={{ width: size, height: size, borderRadius: '50%', background: color, zIndex: 1 }} />
    </span>
  )
}

function Chip({ label, value, color }: { label: string; value: React.ReactNode; color?: string }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <span style={{ fontSize: 8, color: '#333', letterSpacing: '.07em', textTransform: 'uppercase' }}>{label}</span>
      <span style={{ fontSize: 11, fontWeight: 600, color: color ?? C.text, fontVariantNumeric: 'tabular-nums' }}>{value}</span>
    </div>
  )
}

function Btn({ label, onClick, busy = false, danger = false, disabled = false, full = false, variant = 'default' }:
  { label: string; onClick: () => void; busy?: boolean; danger?: boolean; disabled?: boolean; full?: boolean; variant?: 'default' | 'ghost' | 'primary' }) {
  const bg = danger ? '#1A0808' : variant === 'primary' ? '#0A1A0A' : 'transparent'
  const clr = danger ? C.err : variant === 'primary' ? C.run : C.warn
  const bdr = danger ? '#E5393533' : variant === 'primary' ? '#00C85333' : '#2A2A2A'
  return (
    <button disabled={busy || disabled} onClick={onClick} style={{
      width: full ? '100%' : undefined,
      fontSize: 9, fontWeight: 700, letterSpacing: '.06em', padding: '5px 10px',
      border: `1px solid ${bdr}`, borderRadius: 3, cursor: (busy || disabled) ? 'default' : 'pointer',
      background: bg, color: clr, opacity: (busy || disabled) ? 0.35 : 1, transition: 'opacity .15s',
    }}>{label}</button>
  )
}

function AllocBar({ pct, color = C.amber }: { pct: number; color?: string }) {
  const w = Math.min(100, Math.max(0, pct * 100))
  return (
    <div style={{ height: 3, background: '#111', borderRadius: 2, overflow: 'hidden' }}>
      <div style={{ height: '100%', width: `${w.toFixed(1)}%`, background: color, borderRadius: 2, transition: 'width .4s ease' }} />
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Command Strip (52px status bar)
// ─────────────────────────────────────────────────────────────────────────────
function CommandStrip({ health, regime, portfolio, globalPaused, decisions }:
  { health: SystemHealth | null; regime: RegimeState | null; portfolio: PortfolioSummary | null; globalPaused: boolean; decisions: DecisionRecord[] }) {
  const marketOpen = isNSEOpen()
  const hPct = health?.health_pct ?? 0
  const hColor = globalPaused ? C.err : (health?.errored ?? 0) > 0 ? C.err : hPct >= 100 ? C.run : C.warn

  const approved = decisions.filter(d => d.approved === 1).length
  const filled = decisions.filter(d => d.trade_id !== null).length
  const approvalRate = decisions.length > 0 ? approved / decisions.length : null
  const regC = regime?.regime?.includes('bull') ? C.run : regime?.regime?.includes('bear') ? C.err : C.warn

  return (
    <div style={{ display: 'flex', alignItems: 'center', background: C.panel, border: `1px solid ${globalPaused ? '#E5393533' : C.border}`, borderRadius: 5, height: 52, flexShrink: 0, overflow: 'hidden' }}>
      {/* System health */}
      <div style={{ padding: '0 16px', borderRight: `1px solid ${C.border}`, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2, minWidth: 76, height: '100%', justifyContent: 'center' }}>
        <span style={{ fontSize: 18, fontWeight: 800, color: hColor, lineHeight: 1, fontVariantNumeric: 'tabular-nums' }}>{hPct}<span style={{ fontSize: 10 }}>%</span></span>
        <span style={{ fontSize: 7, color: hColor, letterSpacing: '.1em', fontWeight: 700 }}>
          {globalPaused ? 'KILL ACTIVE' : (health?.errored ?? 0) > 0 ? 'DEGRADED' : hPct >= 100 ? 'NOMINAL' : 'PARTIAL'}
        </span>
      </div>
      <Cell label="MARKET" value={marketOpen ? 'OPEN' : 'CLOSED'} color={marketOpen ? C.run : '#555'} />
      <Cell label="REGIME" value={(regime?.regime ?? 'unknown').toUpperCase().replace(/_/g, ' ')} color={regC} />
      <Cell label="VIX" value={regime ? regime.india_vix.toFixed(2) : '—'} color={regime && regime.india_vix > 22 ? C.err : regime && regime.india_vix > 18 ? C.warn : C.sub} />
      <Cell label="EQUITY" value={portfolio ? `₹${(portfolio.equity / 1000).toFixed(1)}k` : '—'} />
      <Cell label="DAY P&L" value={portfolio ? `${portfolio.daily_pnl >= 0 ? '+' : ''}₹${portfolio.daily_pnl.toFixed(0)}` : '—'}
        color={portfolio ? portfolio.daily_pnl >= 0 ? C.run : C.err : undefined} />
      <Cell label="DRAWDOWN" value={portfolio ? `${(portfolio.drawdown * 100).toFixed(2)}%` : '—'}
        color={portfolio && portfolio.drawdown > 0.05 ? C.err : portfolio && portfolio.drawdown > 0.02 ? C.warn : '#444'} />
      {/* Decision pipeline */}
      <div style={{ padding: '0 14px', borderLeft: `1px solid ${C.border}`, height: '100%', display: 'flex', alignItems: 'center', gap: 12 }}>
        <PCell label="SIGNALS" n={decisions.length} />
        <span style={{ color: '#1E1E1E', fontSize: 9 }}>→</span>
        <PCell label="APPROVED" n={approved} color={C.run} />
        <span style={{ color: '#1E1E1E', fontSize: 9 }}>→</span>
        <PCell label="FILLED" n={filled} color={C.teal} />
        {approvalRate !== null && (
          <div style={{ paddingLeft: 10, borderLeft: '1px solid #1A1A1A' }}>
            <div style={{ fontSize: 7, color: '#333', letterSpacing: '.07em' }}>GATE PASS</div>
            <div style={{ fontSize: 13, fontWeight: 700, color: approvalRate > 0.5 ? C.run : C.warn, fontVariantNumeric: 'tabular-nums' }}>
              {(approvalRate * 100).toFixed(0)}<span style={{ fontSize: 8 }}>%</span>
            </div>
          </div>
        )}
      </div>
      <Cell label="AGENTS" value={health ? `${health.healthy}/${health.total}` : '—'} color={hColor} />
      {globalPaused && (
        <div style={{ marginLeft: 'auto', padding: '0 16px', flexShrink: 0 }}>
          <span style={{ fontSize: 9, color: C.err, fontWeight: 800, background: '#1A0808', border: '1px solid #E5393544', borderRadius: 3, padding: '4px 10px', letterSpacing: '.08em' }}>⬛ KILL SWITCH ACTIVE</span>
        </div>
      )}
    </div>
  )
}

function Cell({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div style={{ padding: '0 12px', borderRight: `1px solid ${C.border}`, height: '100%', display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: 2, flexShrink: 0 }}>
      <span style={{ fontSize: 7, color: '#333', letterSpacing: '.07em' }}>{label}</span>
      <span style={{ fontSize: 11, fontWeight: 600, color: color ?? C.text, fontVariantNumeric: 'tabular-nums' }}>{value}</span>
    </div>
  )
}

function PCell({ label, n, color }: { label: string; n: number; color?: string }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
      <span style={{ fontSize: 13, fontWeight: 700, color: color ?? C.sub, fontVariantNumeric: 'tabular-nums' }}>{n}</span>
      <span style={{ fontSize: 7, color: '#333', letterSpacing: '.07em' }}>{label}</span>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Left Rail
// ─────────────────────────────────────────────────────────────────────────────
type Filter = 'all' | 'strategy' | 'risk' | 'execution' | 'orchestrator'
const FILTER_LABELS: Array<{ key: Filter; label: string }> = [
  { key: 'all',          label: 'ALL AGENTS' },
  { key: 'strategy',     label: 'STRATEGIES' },
  { key: 'orchestrator', label: 'ORCHESTRATOR' },
  { key: 'risk',         label: 'SYSTEM' },
  { key: 'execution',    label: 'EXECUTION' },
]

function LeftRail({ agents, filter, onFilter, riskState, instruments, onRefresh, globalPaused, onOpenQuery }:
  { agents: AgentState[]; filter: Filter; onFilter: (f: Filter) => void; riskState: KillSwitchState | null; instruments: Array<{symbol:string;token:number}>; onRefresh: () => void; globalPaused: boolean; onOpenQuery: () => void }) {
  const [busy, setBusy] = useState(false)
  const [blockToken, setBlockToken] = useState('')
  const [actionBusy, setActionBusy] = useState<string | null>(null)
  const [lastAction, setLastAction] = useState<string | null>(null)

  async function act(fn: () => Promise<unknown>) {
    setBusy(true); try { await fn() } finally { setBusy(false); onRefresh() }
  }

  async function trigger(key: string, fn: () => Promise<unknown>) {
    setActionBusy(key)
    setLastAction(null)
    try {
      await fn()
      setLastAction(key)
      setTimeout(() => setLastAction(null), 3000)
    } finally {
      setActionBusy(null)
      onRefresh()
    }
  }

  const runCount   = agents.filter(a => a.status === 'running').length
  const errCount   = agents.filter(a => a.status === 'error').length
  const pauseCount = agents.filter(a => a.status === 'paused').length

  const counts: Record<string, number> = { all: agents.length }
  for (const a of agents) {
    const k = a.agent_type === 'system' ? 'risk' : a.agent_type === 'orchestrator' ? 'orchestrator' : a.agent_type
    counts[k] = (counts[k] ?? 0) + 1
  }
  counts.execution = agents.filter(a => a.agent_id === 'BROKER').length

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10, width: 196, flexShrink: 0 }}>
      {/* Agent groups */}
      <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 5, overflow: 'hidden' }}>
        <div style={{ padding: '7px 12px', borderBottom: `1px solid ${C.border}`, fontSize: 8, color: '#333', letterSpacing: '.08em', display: 'flex', justifyContent: 'space-between' }}>
          AGENT GROUPS
          <span style={{ color: runCount > 0 ? C.run : '#333' }}>{runCount} RUN</span>
        </div>
        {FILTER_LABELS.map(({ key, label }) => (
          <button key={key} onClick={() => onFilter(key)} style={{
            width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            padding: '6px 12px', background: filter === key ? '#F7931E0A' : 'transparent',
            border: 'none', borderLeft: `2px solid ${filter === key ? C.warn : 'transparent'}`,
            cursor: 'pointer', fontSize: 9, fontWeight: filter === key ? 700 : 500,
            color: filter === key ? C.warn : '#555', letterSpacing: '.06em', textAlign: 'left',
          }}>
            {label}
            <span style={{ fontSize: 8, color: '#222' }}>{counts[key] ?? 0}</span>
          </button>
        ))}
        <div style={{ padding: '7px 12px', borderTop: `1px solid ${C.border}`, display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 4, background: '#080808' }}>
          {[{ n: runCount, c: C.run, l: 'RUN' }, { n: pauseCount, c: C.warn, l: 'PAUSE' }, { n: errCount, c: errCount > 0 ? C.err : '#222', l: 'ERROR' }].map(x => (
            <div key={x.l} style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: x.c, fontVariantNumeric: 'tabular-nums' }}>{x.n}</div>
              <div style={{ fontSize: 7, color: '#2A2A2A', letterSpacing: '.06em' }}>{x.l}</div>
            </div>
          ))}
        </div>
      </div>

      {/* On-demand actions */}
      <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 5, padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 5 }}>
        <div style={{ fontSize: 8, color: '#333', letterSpacing: '.08em', marginBottom: 2 }}>TRIGGER AGENTS</div>
        {[
          { key: 'engine',       label: '⟳ FORCE ENGINE EVAL',      fn: () => api.agentForceEval('ENGINE') },
          { key: 'orchestrator', label: '🔮 RUN ORCHESTRATOR SCAN',  fn: () => api.orchestratorScan() },
        ].map(({ key, label, fn }) => {
          const isBusy = actionBusy === key
          const done   = lastAction === key
          return (
            <button key={key} disabled={isBusy} onClick={() => trigger(key, fn)} style={{
              width: '100%', fontSize: 9, fontWeight: 700, letterSpacing: '.05em',
              padding: '6px 8px', textAlign: 'left',
              border: `1px solid ${done ? '#00C85344' : '#1A1A1A'}`,
              borderRadius: 3, cursor: isBusy ? 'default' : 'pointer',
              background: done ? '#001A00' : '#080808',
              color: isBusy ? '#444' : done ? C.run : C.warn,
              opacity: isBusy ? 0.5 : 1, transition: 'all .15s',
            }}>
              {isBusy ? '…' : done ? '✓ ' + label.split(' ').slice(1).join(' ') : label}
            </button>
          )
        })}
        {/* Per-instrument analysis */}
        <div style={{ fontSize: 7, color: '#222', letterSpacing: '.07em', marginTop: 3 }}>ANALYSE INSTRUMENT</div>
        <div style={{ display: 'flex', gap: 5 }}>
          <select id="analyse-select" style={{ flex: 1, fontSize: 9, background: '#080808', border: `1px solid ${C.border}`, borderRadius: 3, color: '#555', padding: '4px 6px' }}>
            {instruments.map(i => <option key={i.token} value={i.symbol}>{i.symbol}</option>)}
          </select>
          <button
            disabled={actionBusy === 'analyse'}
            onClick={() => {
              const sel = (document.getElementById('analyse-select') as HTMLSelectElement)?.value
              if (sel) trigger('analyse', () => api.analyse(sel))
            }}
            style={{ fontSize: 9, fontWeight: 700, padding: '4px 8px', background: '#0A0A0A', border: '1px solid #1A1A1A', borderRadius: 3, color: C.amber, cursor: 'pointer' }}
          >
            RUN
          </button>
        </div>
        {lastAction === 'analyse' && (
          <div style={{ fontSize: 8, color: C.run }}>✓ Analysis triggered</div>
        )}
      </div>

      {/* AI Analyst shortcut */}
      <div style={{ background: C.panel, border: `1px solid #1A2A1A`, borderRadius: 5, padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 5 }}>
        <div style={{ fontSize: 8, color: '#2A4A2A', letterSpacing: '.08em', marginBottom: 2 }}>FINANCIAL AGENT</div>
        <button onClick={onOpenQuery} style={{
          width: '100%', fontSize: 9, fontWeight: 700, letterSpacing: '.05em',
          padding: '7px 8px', textAlign: 'left',
          border: `1px solid #1A3A1A`, borderRadius: 3, cursor: 'pointer',
          background: '#0A1A0A', color: C.run,
        }}>◈ OPEN AI ANALYST</button>
        <div style={{ fontSize: 7, color: '#1E1E1E', lineHeight: 1.4 }}>
          Natural language queries powered by Ollama open-source LLMs + yfinance data
        </div>
      </div>

      {/* Risk command */}
      <div style={{ background: C.panel, border: `1px solid ${globalPaused ? '#E5393533' : C.border}`, borderRadius: 5, padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 6 }}>
        <div style={{ fontSize: 8, color: '#333', letterSpacing: '.08em', marginBottom: 2 }}>RISK COMMAND</div>
        <Btn label={globalPaused ? '✓ ALL PAUSED' : '⏸ PAUSE ALL'} onClick={() => act(() => api.riskGlobalPause())} busy={busy} disabled={globalPaused} full variant="primary" />
        <Btn label="▶ RESUME ALL" onClick={() => act(() => api.riskGlobalResume())} busy={busy} disabled={!globalPaused} full />
        <Btn label="⬛ KILL ALL — EMERGENCY" onClick={() => { if (confirm('Kill All: pause all agents and close all positions?')) act(() => api.riskKillAll()) }} busy={busy} full danger />

        {(riskState?.blocked_tokens ?? []).length > 0 && (
          <div style={{ borderTop: `1px solid ${C.border}`, paddingTop: 7, marginTop: 2 }}>
            <div style={{ fontSize: 7, color: '#333', letterSpacing: '.07em', marginBottom: 5 }}>BLOCKED SYMBOLS</div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 3 }}>
              {riskState!.blocked_tokens.map(tok => {
                const sym = instruments.find(i => i.token === tok)?.symbol ?? String(tok)
                return (
                  <span key={tok} style={{ fontSize: 8, background: '#1A0808', border: '1px solid #E5393522', borderRadius: 3, padding: '2px 5px', color: C.err, display: 'flex', alignItems: 'center', gap: 3 }}>
                    {sym}
                    <button onClick={() => act(() => api.riskUnblockSymbol(tok))} style={{ background: 'none', border: 'none', color: C.err, cursor: 'pointer', padding: 0, fontSize: 9, lineHeight: 1 }}>✕</button>
                  </span>
                )
              })}
            </div>
          </div>
        )}
        <select value={blockToken} onChange={e => setBlockToken(e.target.value)} style={{ width: '100%', fontSize: 9, background: '#080808', border: `1px solid ${C.border}`, borderRadius: 3, color: '#555', padding: '4px 6px' }}>
          <option value="">— block symbol —</option>
          {instruments.map(i => <option key={i.token} value={String(i.token)}>{i.symbol}</option>)}
        </select>
        {blockToken && <Btn label="BLOCK SELECTED SYMBOL" onClick={async () => { await act(() => api.riskBlockSymbol(Number(blockToken))); setBlockToken('') }} busy={busy} full danger />}
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Pipeline Funnel
// ─────────────────────────────────────────────────────────────────────────────
function PipelineFunnel({ agents, decisions }: { agents: AgentState[]; decisions: DecisionRecord[] }) {
  const scanned  = agents.filter(a => a.agent_type === 'strategy').reduce((s, a) => s + a.eval_count, 0)
  const signals  = agents.filter(a => a.agent_type === 'strategy').reduce((s, a) => s + a.signal_count, 0)
  const evaluated = decisions.length
  const approved  = decisions.filter(d => d.approved === 1).length
  const filled    = decisions.filter(d => d.trade_id !== null).length
  const steps = [
    { label: 'EVALS',     n: scanned,   color: '#334' },
    { label: 'SIGNALS',   n: signals,   color: C.amber },
    { label: 'DECISIONS', n: evaluated, color: '#556' },
    { label: 'APPROVED',  n: approved,  color: C.run },
    { label: 'FILLED',    n: filled,    color: C.teal },
  ]
  const max = Math.max(...steps.map(s => s.n), 1)
  return (
    <div style={{ display: 'flex', alignItems: 'stretch', gap: 1, background: '#080808', border: `1px solid ${C.border}`, borderRadius: 4, overflow: 'hidden', height: 44 }}>
      {steps.map((s, i) => {
        const cr = i > 0 && steps[i-1].n > 0 ? `${(s.n / steps[i-1].n * 100).toFixed(0)}%` : null
        return (
          <div key={s.label} style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center', padding: '0 10px', borderRight: i < steps.length - 1 ? `1px solid ${C.border}` : undefined, position: 'relative', overflow: 'hidden' }}>
            <div style={{ position: 'absolute', bottom: 0, left: 0, height: `${(s.n / max) * 100}%`, width: '100%', background: `${s.color}18`, transition: 'height .5s ease' }} />
            <div style={{ position: 'relative', display: 'flex', alignItems: 'baseline', gap: 4 }}>
              <span style={{ fontSize: 13, fontWeight: 800, color: s.color, fontVariantNumeric: 'tabular-nums' }}>{fmtN(s.n)}</span>
              {cr && <span style={{ fontSize: 8, color: '#444' }}>{cr}</span>}
            </div>
            <span style={{ position: 'relative', fontSize: 7, color: '#333', letterSpacing: '.07em' }}>{s.label}</span>
          </div>
        )
      })}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Orchestrator Results — the actual agentic output
// ─────────────────────────────────────────────────────────────────────────────
function OrchestratorPanel({ state, onScan }: { state: OrchestratorState | null; onScan: () => void }) {
  const [scanning, setScanning] = useState(false)
  const [expandedSym, setExpandedSym] = useState<string | null>(null)

  async function triggerScan() {
    setScanning(true)
    try { await api.orchestratorScan() } finally { setScanning(false) }
  }

  const results = state?.results ?? []
  const lastScan = state?.last_scan_ts ? new Date(state.last_scan_ts * 1000).toLocaleTimeString('en-IN', { hour12: false }) : null
  const actionable = results.filter(r => r.side !== 'NEUTRAL' && r.side !== 'SKIP')

  const sideC = (side: string) => side === 'BUY' ? C.run : side === 'SELL' ? C.err : side === 'SKIP' ? '#2A2A2A' : C.sub

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 0, background: C.panel, border: `1px solid ${C.border}`, borderRadius: 5, overflow: 'hidden' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', padding: '8px 12px', borderBottom: `1px solid ${C.border}`, background: '#080808', gap: 10 }}>
        <span style={{ fontSize: 9, color: '#3A3A3A', letterSpacing: '.09em', fontWeight: 700, flex: 1 }}>
          🔮 ORCHESTRATOR · MULTI-LENS SCAN
        </span>
        {lastScan && <span style={{ fontSize: 8, color: '#2A2A2A', fontVariantNumeric: 'tabular-nums' }}>last scan {lastScan}</span>}
        {state && <span style={{ fontSize: 8, color: C.amber }}>{state.scan_count} scans</span>}
        <span style={{ fontSize: 8, color: C.run }}>{actionable.length} actionable</span>
        <Btn label={scanning ? 'SCANNING…' : '⟳ SCAN NOW'} onClick={triggerScan} busy={scanning} variant="primary" />
      </div>

      {results.length === 0 ? (
        <div style={{ padding: '32px 16px', textAlign: 'center', color: '#2A2A2A', fontSize: 10 }}>
          {state === null
            ? 'Orchestrator not started — backend server must be running'
            : 'No scan results yet — click SCAN NOW or wait for auto-scan'}
        </div>
      ) : (
        <div style={{ maxHeight: 320, overflowY: 'auto' }}>
          {/* Column headers */}
          <div style={{ display: 'grid', gridTemplateColumns: '80px 56px 70px 60px 56px 56px 56px 56px 1fr', gap: 0, padding: '5px 12px', borderBottom: `1px solid #111`, background: '#060606', position: 'sticky', top: 0 }}>
            {['SYMBOL','SIDE','VERDICT','CONF','EV','RSI','RET 20D','REGIME','SUMMARY'].map(h => (
              <span key={h} style={{ fontSize: 7, color: '#2A2A2A', letterSpacing: '.06em' }}>{h}</span>
            ))}
          </div>
          {results.map(r => (
            <div key={r.symbol}>
              <div
                onClick={() => setExpandedSym(prev => prev === r.symbol ? null : r.symbol)}
                style={{
                  display: 'grid', gridTemplateColumns: '80px 56px 70px 60px 56px 56px 56px 56px 1fr', gap: 0,
                  padding: '6px 12px', borderBottom: `1px solid #0D0D0D`,
                  background: expandedSym === r.symbol ? '#F7931E05' : r.side === 'BUY' ? '#00C85305' : r.side === 'SELL' ? '#E5393505' : 'transparent',
                  cursor: 'pointer', alignItems: 'center',
                }}
              >
                <span style={{ fontSize: 9, fontWeight: 700, color: '#D0D0D0' }}>{r.symbol}</span>
                <span style={{ fontSize: 9, fontWeight: 800, color: sideC(r.side) }}>{r.side}</span>
                <span style={{ fontSize: 8, color: sideC(r.side), fontWeight: 600 }}>{r.verdict}</span>
                <span style={{ fontSize: 9, color: r.confidence >= 0.6 ? C.run : r.confidence >= 0.45 ? C.warn : C.sub, fontVariantNumeric: 'tabular-nums' }}>{(r.confidence * 100).toFixed(0)}%</span>
                <span style={{ fontSize: 9, color: r.ev > 0 ? C.run : C.err, fontVariantNumeric: 'tabular-nums' }}>{r.ev > 0 ? '+' : ''}{r.ev.toFixed(2)}</span>
                <span style={{ fontSize: 9, color: r.rsi < 35 ? C.run : r.rsi > 65 ? C.err : C.sub, fontVariantNumeric: 'tabular-nums' }}>{r.rsi.toFixed(1)}</span>
                <span style={{ fontSize: 9, color: r.ret_20d > 0 ? C.run : C.err, fontVariantNumeric: 'tabular-nums' }}>{r.ret_20d > 0 ? '+' : ''}{(r.ret_20d * 100).toFixed(1)}%</span>
                <span style={{ fontSize: 8, color: C.sub, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.regime}</span>
                <span style={{ fontSize: 8, color: '#555', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', paddingLeft: 8 }}>{r.summary}</span>
              </div>
              {expandedSym === r.symbol && (
                <div className="row-in" style={{ padding: '10px 16px', background: '#0A0A0A', borderBottom: `1px solid ${C.border}`, display: 'flex', gap: 20, flexWrap: 'wrap' }}>
                  {/* Price levels */}
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 5, minWidth: 160 }}>
                    <div style={{ fontSize: 7, color: '#333', letterSpacing: '.08em', marginBottom: 2 }}>PRICE LEVELS</div>
                    <div style={{ display: 'flex', gap: 12 }}>
                      <Chip label="CMP" value={`₹${r.price.toFixed(2)}`} color={C.text} />
                      <Chip label="SL" value={`₹${r.suggested_sl.toFixed(2)}`} color={C.err} />
                      <Chip label="TARGET" value={`₹${r.suggested_target.toFixed(2)}`} color={C.run} />
                      {r.rr && <Chip label="R:R" value={r.rr.toFixed(2)} color={r.rr >= 2 ? C.run : C.warn} />}
                    </div>
                  </div>
                  {/* Strategy lenses */}
                  {r.lenses && r.lenses.length > 0 && (
                    <div style={{ flex: 1, minWidth: 200 }}>
                      <div style={{ fontSize: 7, color: '#333', letterSpacing: '.08em', marginBottom: 6 }}>STRATEGY LENSES</div>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                        {r.lenses.map((l, i) => (
                          <div key={i} style={{ display: 'grid', gridTemplateColumns: '32px 80px 44px 1fr', gap: 6, alignItems: 'center' }}>
                            <span style={{ fontSize: 8, color: C.warn, fontWeight: 700 }}>{l.strategy}</span>
                            <span style={{ fontSize: 8, color: sideC(l.side), fontWeight: 600 }}>{l.side}</span>
                            <span style={{ fontSize: 8, color: l.confidence >= 0.55 ? C.run : C.sub, fontVariantNumeric: 'tabular-nums' }}>{(l.confidence * 100).toFixed(0)}%</span>
                            <span style={{ fontSize: 8, color: '#555', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{l.detail}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Agent Cards
// ─────────────────────────────────────────────────────────────────────────────
function SystemAgentCard({ agent, scorecard, onRefresh, selected, onClick }:
  { agent: AgentState; scorecard?: Scorecard; onRefresh: () => void; selected: boolean; onClick: () => void }) {
  const [thresh, setThresh] = useState(String(agent.confidence_threshold))
  const [busy, setBusy] = useState(false)
  useEffect(() => { setThresh(String(agent.confidence_threshold)) }, [agent.confidence_threshold])
  async function act(fn: () => Promise<unknown>) { setBusy(true); try { await fn() } finally { setBusy(false); onRefresh() } }
  const isPaused = agent.status === 'paused'

  return (
    <div onClick={onClick} style={{
      background: agent.status === 'error' ? '#0E0808' : isPaused ? '#0E0A06' : '#0E0E0E',
      border: `1px solid ${agent.status === 'error' ? '#E5393522' : isPaused ? '#F7931E22' : selected ? '#F7931E18' : C.border}`,
      borderRadius: 5, padding: '11px 13px', cursor: 'pointer', display: 'flex', flexDirection: 'column', gap: 9,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <Dot status={agent.status} size={8} />
        <span style={{ fontSize: 15, color: '#1E1E1E' }}>{AGENT_ICON[agent.agent_id] ?? '◯'}</span>
        <div style={{ flex: 1 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
            <span style={{ fontSize: 11, fontWeight: 800, color: '#E0E0E0', letterSpacing: '.03em' }}>{agent.agent_id}</span>
            <span style={{ fontSize: 7, color: C.warn, background: '#F7931E11', border: '1px solid #F7931E22', borderRadius: 2, padding: '0 5px', letterSpacing: '.05em' }}>
              {agent.agent_type.toUpperCase()}
            </span>
          </div>
          <div style={{ fontSize: 8, color: '#3A3A3A', marginTop: 1 }}>{AGENT_DESC[agent.agent_id] ?? agent.description}</div>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 2 }}>
          <span style={{ fontSize: 8, color: STATUS_C[agent.status], fontWeight: 700, letterSpacing: '.06em' }}>{agent.status.toUpperCase()}</span>
          <span style={{ fontSize: 8, color: ageC(agent.heartbeat_age_s) }}>HB {fmtAge(agent.heartbeat_age_s)}</span>
        </div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 8, background: '#080808', borderRadius: 3, padding: '7px 10px' }}>
        <Chip label="EVALS"     value={fmtN(agent.eval_count)} />
        <Chip label="SIGNALS"   value={fmtN(agent.signal_count)} />
        <Chip label="LAST EVAL" value={agent.last_eval_ts ? fmtTs(agent.last_eval_ts) : '—'} />
        <Chip label="CONF ≥"   value={agent.confidence_threshold.toFixed(2)} color={C.warn} />
      </div>
      {scorecard && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 8, padding: '6px 10px', background: '#0A0A0A', borderRadius: 3, border: '1px solid #111' }}>
          <Chip label="TRADES" value={String(scorecard.total_trades)} />
          <Chip label="BAY WR" value={fmtPct(scorecard.bayesian_wr)} color={scorecard.bayesian_wr > 0.5 ? C.run : C.warn} />
          <Chip label="EXPECT" value={`₹${scorecard.expectancy.toFixed(0)}`} color={scorecard.expectancy > 0 ? C.run : C.err} />
          <Chip label="P&L"    value={`₹${scorecard.total_pnl.toFixed(0)}`} color={scorecard.total_pnl >= 0 ? C.run : C.err} />
        </div>
      )}
      {agent.status === 'error' && agent.last_error && (
        <div style={{ fontSize: 8, color: C.err, background: '#1A0808', border: '1px solid #E5393522', borderRadius: 3, padding: '5px 8px', wordBreak: 'break-all' }}>⚠ {agent.last_error}</div>
      )}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }} onClick={e => e.stopPropagation()}>
        <Btn label={isPaused ? '▶ RESUME' : '⏸ PAUSE'} busy={busy}
          onClick={() => act(isPaused ? () => api.agentResume(agent.agent_id) : () => api.agentPause(agent.agent_id))} />
        {agent.agent_id === 'ENGINE' && (
          <Btn label="⟳ FORCE EVAL" busy={busy} onClick={() => act(() => api.agentForceEval(agent.agent_id))} variant="primary" />
        )}
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 5 }}>
          <span style={{ fontSize: 8, color: '#333' }}>conf≥</span>
          <input type="number" min="0" max="1" step="0.01" value={thresh} onChange={e => setThresh(e.target.value)}
            style={{ width: 44, fontSize: 9, background: '#080808', border: `1px solid ${C.border}`, borderRadius: 3, color: '#777', padding: '2px 4px' }} />
          <Btn label="SET" busy={busy} onClick={() => { const v = parseFloat(thresh); if (!isNaN(v)) act(() => api.agentSetThreshold(agent.agent_id, v)) }} />
        </div>
      </div>
    </div>
  )
}

function StrategyCard({ agent, scorecard, learner, alloc, onRefresh, selected, onClick }:
  { agent: AgentState; scorecard?: Scorecard; learner?: LearnerParams; alloc: number; onRefresh: () => void; selected: boolean; onClick: () => void }) {
  const [busy, setBusy] = useState(false)
  async function act(fn: () => Promise<unknown>) { setBusy(true); try { await fn() } finally { setBusy(false); onRefresh() } }
  const isPaused = agent.status === 'paused'

  return (
    <div onClick={onClick} style={{
      background: agent.status === 'error' ? '#0E0808' : isPaused ? '#0E0A06' : C.card,
      border: `1px solid ${agent.status === 'error' ? '#E5393522' : isPaused ? '#F7931E22' : selected ? '#F7931E22' : C.border}`,
      borderRadius: 4, padding: '10px 11px', cursor: 'pointer', display: 'flex', flexDirection: 'column', gap: 7,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <Dot status={agent.status} size={6} />
        <span style={{ fontSize: 10, color: '#1E1E1E' }}>{AGENT_ICON[agent.agent_id] ?? '◯'}</span>
        <span style={{ fontSize: 11, fontWeight: 800, color: '#E0E0E0', flex: 1 }}>{agent.agent_id}</span>
        <span style={{ fontSize: 7, color: ageC(agent.heartbeat_age_s) }}>{fmtAge(agent.heartbeat_age_s)}</span>
      </div>
      <div style={{ fontSize: 8, color: '#3A3A3A', marginTop: -3 }}>{AGENT_DESC[agent.agent_id] ?? agent.description}</div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 6 }}>
        <Chip label="EVALS"  value={fmtN(agent.eval_count)} />
        <Chip label="SIGS"   value={fmtN(agent.signal_count)} />
        <Chip label="CONF≥" value={agent.confidence_threshold.toFixed(2)} color={C.warn} />
      </div>
      {scorecard && (
        <div style={{ background: '#080808', borderRadius: 3, padding: '5px 8px', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
          <Chip label="BAY WR" value={fmtPct(scorecard.bayesian_wr)} color={scorecard.bayesian_wr > 0.5 ? C.run : C.warn} />
          <Chip label="P&L" value={`₹${scorecard.total_pnl.toFixed(0)}`} color={scorecard.total_pnl >= 0 ? C.run : C.err} />
        </div>
      )}
      {/* Real DSA allocation */}
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
          <span style={{ fontSize: 7, color: '#2A2A2A', letterSpacing: '.07em' }}>DSA ALLOC</span>
          <span style={{ fontSize: 7, color: alloc > 0 ? C.amber : '#2A2A2A' }}>{alloc > 0 ? `${(alloc * 100).toFixed(1)}%` : 'no data'}</span>
        </div>
        <AllocBar pct={alloc} />
      </div>
      {learner && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 5, background: '#080808', borderRadius: 3, padding: '5px 7px' }}>
          <Chip label="KELLY" value={learner.kelly_fraction.toFixed(2)} color={C.teal} />
          <Chip label="SL ×" value={learner.sl_multiplier.toFixed(2)} />
        </div>
      )}
      {agent.status === 'error' && agent.last_error && (
        <div style={{ fontSize: 7, color: C.err, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>⚠ {agent.last_error}</div>
      )}
      <div style={{ display: 'flex', gap: 5 }} onClick={e => e.stopPropagation()}>
        <Btn label={isPaused ? '▶' : '⏸'} busy={busy}
          onClick={() => act(isPaused ? () => api.agentResume(agent.agent_id) : () => api.agentPause(agent.agent_id))} />
        <span style={{ fontSize: 8, color: '#2A2A2A', marginLeft: 'auto', alignSelf: 'center' }}>{fmtN(agent.signal_count)} sigs</span>
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Strategy Scoreboard Tab
// ─────────────────────────────────────────────────────────────────────────────
const SCOLS = '68px 96px 56px 60px 56px 64px 72px 60px 68px 60px'

function ScoreboardView({ scorecards, learnerParams, agents, allocations }:
  { scorecards: Scorecard[]; learnerParams: LearnerParams[]; agents: AgentState[]; allocations: Record<string, number> }) {
  const lpMap: Record<string, LearnerParams> = {}
  for (const lp of learnerParams) lpMap[lp.strategy_id] = lp
  const sorted = [...scorecards].sort((a, b) => b.total_pnl - a.total_pnl)
  const totalPnl    = sorted.reduce((s, r) => s + r.total_pnl, 0)
  const totalTrades = sorted.reduce((s, r) => s + r.total_trades, 0)
  const avgBWR      = sorted.length > 0 ? sorted.reduce((s, r) => s + r.bayesian_wr, 0) / sorted.length : 0

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden' }}>
      {/* Summary */}
      <div style={{ display: 'flex', gap: 20, padding: '10px 14px', background: '#080808', borderBottom: `1px solid ${C.border}`, flexShrink: 0 }}>
        <Chip label="TOTAL P&L"     value={`₹${totalPnl.toFixed(0)}`}  color={totalPnl >= 0 ? C.run : C.err} />
        <Chip label="TOTAL TRADES"  value={String(totalTrades)} />
        <Chip label="AVG BAYES WR"  value={fmtPct(avgBWR)} color={avgBWR > 0.5 ? C.run : C.warn} />
        <Chip label="STRATEGIES"    value={String(sorted.length)} />
      </div>
      {/* Header */}
      <div style={{ display: 'grid', gridTemplateColumns: SCOLS, padding: '5px 12px', background: '#080808', borderBottom: `1px solid #1A1A1A`, flexShrink: 0 }}>
        {['STRATEGY','DESCRIPTION','TRADES','BAY WR','WIN RT','EXPECT','P&L','AVG WIN','AVG LOSS','ALLOC'].map(h => (
          <span key={h} style={{ fontSize: 7, color: '#2A2A2A', letterSpacing: '.07em' }}>{h}</span>
        ))}
      </div>
      <div style={{ flex: 1, overflowY: 'auto' }}>
        {sorted.length === 0
          ? <div style={{ textAlign: 'center', color: '#222', fontSize: 10, padding: 40 }}>No strategy data yet — accumulates during live session</div>
          : sorted.map(sc => {
            const agent = agents.find(a => a.agent_id === sc.strategy_id)
            const alloc = allocations[sc.strategy_id] ?? 0
            return (
              <div key={sc.strategy_id} style={{ display: 'grid', gridTemplateColumns: SCOLS, padding: '7px 12px', borderBottom: `1px solid ${C.border}`, alignItems: 'center' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                  <Dot status={agent?.status ?? 'idle'} size={5} />
                  <span style={{ fontSize: 9, fontWeight: 700, color: '#D8D8D8' }}>{sc.strategy_id}</span>
                </div>
                <span style={{ fontSize: 8, color: '#3A3A3A' }}>{AGENT_DESC[sc.strategy_id] ?? ''}</span>
                <span style={{ fontSize: 10, color: C.text, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{sc.total_trades}</span>
                <span style={{ fontSize: 10, color: sc.bayesian_wr > 0.5 ? C.run : C.warn, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{fmtPct(sc.bayesian_wr)}</span>
                <span style={{ fontSize: 10, color: sc.win_rate > 0.5 ? C.run : C.warn, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{fmtPct(sc.win_rate)}</span>
                <span style={{ fontSize: 10, color: sc.expectancy >= 0 ? C.run : C.err, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{`₹${sc.expectancy.toFixed(0)}`}</span>
                <span style={{ fontSize: 10, color: sc.total_pnl >= 0 ? C.run : C.err, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{`₹${sc.total_pnl.toFixed(0)}`}</span>
                <span style={{ fontSize: 10, color: C.run, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{`₹${sc.avg_win.toFixed(0)}`}</span>
                <span style={{ fontSize: 10, color: C.err, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{`₹${Math.abs(sc.avg_loss).toFixed(0)}`}</span>
                <div style={{ paddingLeft: 4 }}>
                  <div style={{ fontSize: 8, color: alloc > 0 ? C.amber : '#2A2A2A', marginBottom: 2 }}>{alloc > 0 ? `${(alloc * 100).toFixed(1)}%` : '—'}</div>
                  <AllocBar pct={alloc} />
                </div>
              </div>
            )
          })
        }
      </div>
      {/* Learner params */}
      {learnerParams.length > 0 && (
        <div style={{ borderTop: `1px solid ${C.border}`, flexShrink: 0 }}>
          <div style={{ padding: '7px 12px', fontSize: 8, color: '#333', letterSpacing: '.08em', background: '#080808', borderBottom: `1px solid ${C.border}` }}>ADAPTIVE LEARNER PARAMS</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(340px,1fr))', gap: 1, background: C.border, maxHeight: 180, overflowY: 'auto' }}>
            {learnerParams.map(lp => (
              <div key={lp.strategy_id} style={{ background: '#080808', padding: '8px 12px', display: 'grid', gridTemplateColumns: '72px 1fr', gap: 8 }}>
                <div>
                  <div style={{ fontSize: 9, fontWeight: 700, color: '#D0D0D0' }}>{lp.strategy_id}</div>
                  <div style={{ fontSize: 7, color: '#333' }}>n={lp.n_trades}</div>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5,1fr)', gap: 8 }}>
                  <Chip label="CONF≥"  value={lp.min_confidence.toFixed(2)} color={C.warn} />
                  <Chip label="KELLY"  value={lp.kelly_fraction.toFixed(2)} color={C.teal} />
                  <Chip label="SL ×"   value={lp.sl_multiplier.toFixed(2)} />
                  <Chip label="TGT ×"  value={lp.target_multiplier.toFixed(2)} color={C.run} />
                  <Chip label="BAYES"  value={fmtPct(lp.bayes_wr)} color={lp.bayes_wr > 0.5 ? C.run : C.warn} />
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Pipeline Tab
// ─────────────────────────────────────────────────────────────────────────────
const DCOLS = '52px 18px 64px 76px 1fr 60px 56px 60px'

function DecisionRow({ d, onClick, selected }: { d: DecisionRecord; onClick: () => void; selected: boolean }) {
  const approved = d.approved === 1
  return (
    <div className="row-in" onClick={onClick} style={{
      display: 'grid', gridTemplateColumns: DCOLS, alignItems: 'center', gap: 8,
      padding: '6px 12px', background: selected ? '#F7931E08' : 'transparent',
      borderLeft: `2px solid ${selected ? C.warn : 'transparent'}`,
      borderBottom: `1px solid ${C.border}`, cursor: 'pointer',
    }}>
      <span style={{ fontSize: 8, color: '#3A3A3A', fontVariantNumeric: 'tabular-nums' }}>{fmtTs(d.decided_at)}</span>
      <span style={{ fontSize: 10, color: approved ? C.run : C.err, fontWeight: 800 }}>{approved ? '✓' : '✗'}</span>
      <span style={{ fontSize: 9, color: C.warn, fontWeight: 600 }}>{d.strategy_id ?? '—'}</span>
      <span style={{ fontSize: 9, color: '#888' }}>{String(d.instrument_token)}</span>
      <span style={{ fontSize: 8, color: '#555', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {approved
          ? `${d.side ?? '?'} conf:${(d.confidence ?? 0).toFixed(2)} [${d.regime ?? '?'}] ${d.trigger_rule ?? ''}`
          : d.reason ?? 'rejected'}
      </span>
      <span style={{ fontSize: 8, color: d.fill_price ? C.teal : '#333', textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
        {d.fill_price ? `₹${d.fill_price.toFixed(1)}` : '—'}
      </span>
      <span style={{ fontSize: 8, color: d.trade_pnl != null ? (d.trade_pnl >= 0 ? C.run : C.err) : '#333', textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
        {d.trade_pnl != null ? `${d.trade_pnl >= 0 ? '+' : ''}₹${d.trade_pnl.toFixed(0)}` : '—'}
      </span>
      <span style={{ fontSize: 7, color: d.trade_id ? C.teal : approved ? C.run : '#2A2A2A', letterSpacing: '.04em' }}>
        {d.trade_id ? 'FILLED' : approved ? 'PENDING' : 'REJECTED'}
      </span>
    </div>
  )
}

function PipelineTab({ agents, decisions, selectedId, onSelect }:
  { agents: AgentState[]; decisions: DecisionRecord[]; selectedId: string | null; onSelect: (id: string) => void }) {
  const [stratFilter, setStratFilter] = useState('ALL')
  const strategies = Array.from(new Set(decisions.map(d => d.strategy_id).filter(Boolean))) as string[]
  const filtered = stratFilter === 'ALL' ? decisions : decisions.filter(d => d.strategy_id === stratFilter)
  const approved  = filtered.filter(d => d.approved === 1)
  const rejected  = filtered.filter(d => d.approved === 0)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden' }}>
      <div style={{ padding: '10px 12px', borderBottom: `1px solid ${C.border}`, flexShrink: 0 }}>
        <PipelineFunnel agents={agents} decisions={decisions} />
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 12px', borderBottom: `1px solid ${C.border}`, background: '#080808', flexShrink: 0 }}>
        <span style={{ fontSize: 8, color: '#333', letterSpacing: '.07em' }}>STRATEGY</span>
        {['ALL', ...strategies].map(s => (
          <button key={s} onClick={() => setStratFilter(s)} style={{
            fontSize: 8, padding: '2px 7px', borderRadius: 3,
            border: `1px solid ${stratFilter === s ? C.warn : '#1A1A1A'}`,
            background: stratFilter === s ? '#F7931E11' : 'transparent',
            color: stratFilter === s ? C.warn : '#444', cursor: 'pointer', fontWeight: stratFilter === s ? 700 : 400,
          }}>{s}</button>
        ))}
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 14 }}>
          <span style={{ fontSize: 8, color: C.run }}>{approved.length} approved</span>
          <span style={{ fontSize: 8, color: C.err }}>{rejected.length} rejected</span>
          {filtered.length > 0 && <span style={{ fontSize: 8, color: C.teal }}>{(approved.length / filtered.length * 100).toFixed(0)}% pass</span>}
        </div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: DCOLS, gap: 8, padding: '5px 12px', background: '#080808', borderBottom: `1px solid #1A1A1A`, flexShrink: 0 }}>
        {['TIME','','STRATEGY','SYMBOL','DETAILS','FILL','P&L','STATUS'].map(h => (
          <span key={h} style={{ fontSize: 7, color: '#2A2A2A', letterSpacing: '.07em' }}>{h}</span>
        ))}
      </div>
      <div style={{ flex: 1, overflowY: 'auto' }}>
        {filtered.length === 0
          ? <div style={{ textAlign: 'center', color: '#2A2A2A', fontSize: 10, padding: 40 }}>No decisions yet — strategy engine must generate signals first</div>
          : filtered.map(d => (
            <DecisionRow key={d.decision_id} d={d}
              onClick={() => onSelect(d.signal_id)}
              selected={selectedId === d.signal_id} />
          ))}
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// EventBus Broadcast Tab
// ─────────────────────────────────────────────────────────────────────────────
const TOPIC_COLOR: Record<string, string> = {
  'trade.opened': C.run, 'trade.closed': C.sub, 'order.approved': '#4CAF50',
  'order.rejected': C.err, 'strategy.signal': C.amber, 'kill_switch': C.err,
  'pnl': '#2A2A2A', 'regime': '#2A2A2A', 'ticks': '#1A1A1A', 'scorecard': '#3A3A3A',
}

function BroadcastTab({ events }: { events: EventRecord[] }) {
  const [paused, setPaused] = useState(false)
  const [search, setSearch] = useState('')
  const [topicFilter, setTopicFilter] = useState('ALL')
  const topics = Array.from(new Set(events.map(e => e.topic.split('.')[0]))).slice(0, 10)
  const filtered = events.filter(e => {
    if (topicFilter !== 'ALL' && !e.topic.startsWith(topicFilter)) return false
    if (search && !e.topic.includes(search) && !e.summary.includes(search)) return false
    return true
  })

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '7px 12px', borderBottom: `1px solid ${C.border}`, background: '#080808', flexShrink: 0 }}>
        <button onClick={() => setPaused(p => !p)} style={{
          fontSize: 8, padding: '2px 10px', borderRadius: 3,
          border: `1px solid ${paused ? C.warn : '#1A1A1A'}`,
          background: paused ? '#F7931E11' : 'transparent',
          color: paused ? C.warn : '#444', cursor: 'pointer', fontWeight: 700,
        }}>{paused ? '▶ RESUME' : '⏸ PAUSE'}</button>
        <input value={search} onChange={e => setSearch(e.target.value)} placeholder="search…"
          style={{ flex: 1, maxWidth: 180, fontSize: 9, background: '#0A0A0A', border: `1px solid ${C.border}`, borderRadius: 3, color: '#888', padding: '3px 8px', outline: 'none' }} />
        {['ALL', ...topics].slice(0, 9).map(t => (
          <button key={t} onClick={() => setTopicFilter(t)} style={{
            fontSize: 7, padding: '2px 6px', borderRadius: 3,
            border: `1px solid ${topicFilter === t ? C.amber : '#1A1A1A'}`,
            background: topicFilter === t ? '#F7931E0A' : 'transparent',
            color: topicFilter === t ? C.amber : '#333', cursor: 'pointer', letterSpacing: '.04em',
          }}>{t.toUpperCase()}</button>
        ))}
        <span style={{ marginLeft: 'auto', fontSize: 8, color: '#2A2A2A' }}>{filtered.length}</span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '56px 176px 1fr 52px', gap: 8, padding: '5px 12px', background: '#080808', borderBottom: `1px solid #1A1A1A`, flexShrink: 0 }}>
        {['TIME','TOPIC','SUMMARY','SEV'].map(h => <span key={h} style={{ fontSize: 7, color: '#2A2A2A', letterSpacing: '.07em' }}>{h}</span>)}
      </div>
      <div style={{ flex: 1, overflowY: 'auto' }}>
        {filtered.length === 0
          ? <div style={{ textAlign: 'center', color: '#2A2A2A', fontSize: 10, padding: 40 }}>No events recorded yet</div>
          : filtered.map((e, i) => (
            <div key={i} style={{ display: 'grid', gridTemplateColumns: '56px 176px 1fr 52px', gap: 8, padding: '5px 12px', borderBottom: `1px solid #0D0D0D`, alignItems: 'baseline' }}>
              <span style={{ fontSize: 8, color: '#2A2A2A', fontVariantNumeric: 'tabular-nums' }}>{fmtTs(e.ts)}</span>
              <span style={{ fontSize: 8, color: TOPIC_COLOR[e.topic] ?? TOPIC_COLOR[e.topic.split('.')[0]] ?? '#555', fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{e.topic}</span>
              <span style={{ fontSize: 8, color: '#555', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{e.summary}</span>
              <span style={{ fontSize: 7, color: e.severity === 'critical' ? C.err : e.severity === 'warn' ? C.warn : e.severity === 'success' ? C.run : '#2A2A2A', letterSpacing: '.05em' }}>{e.severity?.toUpperCase()}</span>
            </div>
          ))}
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Inspector (right rail)
// ─────────────────────────────────────────────────────────────────────────────
function KV({ k, v, color }: { k: string; v: React.ReactNode; color?: string }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, padding: '1px 0' }}>
      <span style={{ color: '#2A2A2A', flexShrink: 0, fontSize: 8 }}>{k}</span>
      <span style={{ color: color ?? C.text, textAlign: 'right', wordBreak: 'break-all', fontSize: 9 }}>{v}</span>
    </div>
  )
}

function InspectorSection({ label, color, children }: { label: string; color?: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ fontSize: 8, color: color ?? '#2A2A2A', letterSpacing: '.08em', fontWeight: 700, marginBottom: 5, borderBottom: `1px solid ${C.border}`, paddingBottom: 3 }}>{label}</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>{children}</div>
    </div>
  )
}

function SignalLineageView({ lineage }: { lineage: SignalLineage }) {
  const approved = lineage.risk_approved === 1
  const checks = lineage.risk_checks ?? {}
  const checkEntries = Object.entries(checks)
  const passing = checkEntries.filter(([, v]) => v as boolean).length

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 0, fontSize: 9 }}>
      <div style={{ fontWeight: 800, color: '#E0E0E0', fontSize: 10, letterSpacing: '.03em', marginBottom: 12 }}>SIGNAL LINEAGE</div>
      <InspectorSection label="MARKET CONTEXT">
        <KV k="Symbol" v={String(lineage.instrument_token)} />
        <KV k="Side" v={lineage.side ?? '—'} color={lineage.side === 'BUY' ? C.run : C.err} />
        <KV k="Regime" v={lineage.regime ?? '—'} />
        <KV k="India VIX" v={lineage.india_vix?.toFixed(2) ?? '—'} />
        <KV k="Regime Conf" v={(lineage.regime_confidence ?? 0).toFixed(2)} />
      </InspectorSection>
      <InspectorSection label="SIGNAL">
        <KV k="Strategy" v={lineage.strategy_id ?? '—'} color={C.warn} />
        <KV k="Trigger" v={lineage.trigger_rule ?? '—'} />
        <KV k="Confidence" v={(lineage.confidence ?? 0).toFixed(3)} color={C.run} />
        <KV k="Generated" v={lineage.generated_at ? fmtTs(lineage.generated_at) : '—'} />
      </InspectorSection>
      {lineage.indicators && Object.keys(lineage.indicators).length > 0 && (
        <InspectorSection label="INDICATORS">
          {Object.entries(lineage.indicators).map(([k, v]) => (
            <KV key={k} k={k} v={typeof v === 'number' ? v.toFixed(3) : String(v)} />
          ))}
        </InspectorSection>
      )}
      <InspectorSection label={`RISK GATE (${passing}/${checkEntries.length}) ${approved ? '✓ PASS' : '✗ FAIL'}`} color={approved ? C.run : C.err}>
        {checkEntries.map(([k, v]) => (
          <div key={k} style={{ display: 'flex', gap: 5, alignItems: 'center' }}>
            <span style={{ fontSize: 9, color: (v as boolean) ? C.run : C.err, minWidth: 10, fontWeight: 700 }}>{(v as boolean) ? '✓' : '✗'}</span>
            <span style={{ fontSize: 8, color: (v as boolean) ? '#3A3A3A' : '#666' }}>{k}</span>
          </div>
        ))}
        {lineage.risk_reason && <div style={{ fontSize: 8, color: C.err, marginTop: 4, padding: '4px 6px', background: '#1A0808', borderRadius: 3 }}>{lineage.risk_reason}</div>}
      </InspectorSection>
      {lineage.fill_price && (
        <InspectorSection label="FILL">
          <KV k="Fill price" v={`₹${lineage.fill_price.toFixed(2)}`} color={C.teal} />
        </InspectorSection>
      )}
      {lineage.trade_pnl != null && (
        <InspectorSection label="OUTCOME">
          <KV k="P&L" v={`${lineage.trade_pnl >= 0 ? '+' : ''}₹${lineage.trade_pnl.toFixed(0)}`} color={lineage.trade_pnl >= 0 ? C.run : C.err} />
          {lineage.trade_exit_reason && <KV k="Exit" v={lineage.trade_exit_reason} />}
          {lineage.trade_closed_at && <KV k="Closed" v={fmtTs(lineage.trade_closed_at)} />}
        </InspectorSection>
      )}
    </div>
  )
}

function AgentInspector({ agent, onRefresh }: { agent: AgentState; onRefresh: () => void }) {
  const [thresh, setThresh] = useState(String(agent.confidence_threshold))
  const [busy, setBusy] = useState(false)
  useEffect(() => { setThresh(String(agent.confidence_threshold)) }, [agent.confidence_threshold])
  async function act(fn: () => Promise<unknown>) { setBusy(true); try { await fn() } finally { setBusy(false); onRefresh() } }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <Dot status={agent.status} size={8} />
        <div>
          <div style={{ fontSize: 11, fontWeight: 800, color: '#E0E0E0' }}>{agent.agent_id}</div>
          <div style={{ fontSize: 8, color: '#3A3A3A' }}>{AGENT_DESC[agent.agent_id] ?? agent.description}</div>
        </div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, background: '#080808', borderRadius: 4, padding: '8px' }}>
        <Chip label="STATUS"    value={agent.status.toUpperCase()} color={STATUS_C[agent.status]} />
        <Chip label="HEARTBEAT" value={fmtAge(agent.heartbeat_age_s)} color={ageC(agent.heartbeat_age_s)} />
        <Chip label="EVALS"     value={fmtN(agent.eval_count)} />
        <Chip label="SIGNALS"   value={fmtN(agent.signal_count)} />
        <Chip label="LAST EVAL" value={agent.last_eval_ts ? fmtTs(agent.last_eval_ts) : '—'} />
        <Chip label="CONF≥"    value={agent.confidence_threshold.toFixed(3)} color={C.warn} />
      </div>
      {agent.last_error && (
        <div style={{ fontSize: 8, color: C.err, background: '#1A0808', borderRadius: 3, padding: '6px 8px', wordBreak: 'break-all' }}>⚠ {agent.last_error}</div>
      )}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
        <Btn label={agent.status === 'paused' ? '▶ RESUME AGENT' : '⏸ PAUSE AGENT'} busy={busy} full
          onClick={() => act(agent.status === 'paused' ? () => api.agentResume(agent.agent_id) : () => api.agentPause(agent.agent_id))} />
        {agent.agent_id === 'ENGINE' && (
          <Btn label="⟳ FORCE EVALUATE NOW" busy={busy} full variant="primary" onClick={() => act(() => api.agentForceEval(agent.agent_id))} />
        )}
        <div style={{ display: 'flex', gap: 5, alignItems: 'center', marginTop: 2 }}>
          <span style={{ fontSize: 8, color: '#333', flexShrink: 0 }}>conf ≥</span>
          <input type="number" min="0" max="1" step="0.01" value={thresh} onChange={e => setThresh(e.target.value)}
            style={{ flex: 1, fontSize: 9, background: '#080808', border: `1px solid ${C.border}`, borderRadius: 3, color: '#888', padding: '3px 5px' }} />
          <Btn label="SET" busy={busy} onClick={() => { const v = parseFloat(thresh); if (!isNaN(v)) act(() => api.agentSetThreshold(agent.agent_id, v)) }} />
        </div>
      </div>
    </div>
  )
}

function AuditLog({ entries }: { entries: AuditEntry[] }) {
  const AUD_C: Record<string, string> = { GLOBAL_PAUSE: C.err, GLOBAL_RESUME: C.run, BLOCK_SYMBOL: C.warn, UNBLOCK_SYMBOL: '#4CAF50', KILL_ALL: C.err }
  return (
    <div>
      <div style={{ fontSize: 8, color: '#2A2A2A', letterSpacing: '.08em', marginBottom: 6, fontWeight: 700 }}>KILL SWITCH AUDIT</div>
      {entries.length === 0
        ? <span style={{ fontSize: 8, color: '#1E1E1E' }}>No audit events</span>
        : entries.map((e, i) => (
          <div key={i} style={{ fontSize: 8, display: 'grid', gridTemplateColumns: '52px 1fr', gap: 5, borderBottom: `1px solid #0D0D0D`, padding: '3px 0' }}>
            <span style={{ color: '#2A2A2A', fontVariantNumeric: 'tabular-nums' }}>{fmtTs(e.ts)}</span>
            <div>
              <span style={{ color: AUD_C[e.action] ?? '#444', fontWeight: 700, marginRight: 5 }}>{e.action}</span>
              <span style={{ color: '#333' }}>{e.detail}</span>
            </div>
          </div>
        ))}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Financial Agent Query Panel
// ─────────────────────────────────────────────────────────────────────────────
type ConvMsg = {
  role: 'user' | 'assistant' | 'error'
  content: string
  toolCalls?: AgentQueryResponse['tool_calls']
  model?: string
  online?: boolean
}

const QUICK_QUERIES = [
  { label: 'Market overview', q: 'Give me a quick overview of current Indian market conditions — NIFTY, BANKNIFTY, VIX, and global indices' },
  { label: 'Momentum scan', q: 'Scan top 20 NSE large-cap stocks for momentum signals and give me the top 5 setups' },
  { label: 'Breakout watch', q: 'Which NSE large-cap stocks are near 52-week high breakout with strong volume?' },
  { label: 'Oversold quality', q: 'Find quality large-cap stocks that are RSI oversold but still above EMA50' },
  { label: 'Analyse RELIANCE', q: 'Give me a full technical and fundamental analysis of RELIANCE' },
  { label: 'Banking sector', q: 'Compare HDFCBANK, ICICIBANK, SBIN and AXISBANK technically — which is strongest?' },
]

function renderAnswer(text: string) {
  return text.split('\n').map((line, i) => {
    const parts = line.split(/(\*\*[^*]+\*\*)/)
    return (
      <div key={i} style={{ minHeight: 4 }}>
        {parts.map((p, j) =>
          p.startsWith('**') && p.endsWith('**')
            ? <strong key={j} style={{ color: '#D8D8D8', fontWeight: 700 }}>{p.slice(2, -2)}</strong>
            : <span key={j}>{p}</span>
        )}
      </div>
    )
  })
}

function ToolCallAccordion({ calls }: { calls: AgentQueryResponse['tool_calls'] }) {
  const [open, setOpen] = useState(false)
  if (!calls || calls.length === 0) return null
  return (
    <div style={{ marginTop: 8, border: `1px solid #1A1A1A`, borderRadius: 3, overflow: 'hidden' }}>
      <button onClick={() => setOpen(o => !o)} style={{
        width: '100%', display: 'flex', alignItems: 'center', gap: 6, padding: '5px 8px',
        background: '#080808', border: 'none', cursor: 'pointer', textAlign: 'left',
      }}>
        <span style={{ fontSize: 8, color: C.teal }}>⚙ {calls.length} tool call{calls.length > 1 ? 's' : ''}</span>
        <span style={{ fontSize: 8, color: '#2A2A2A', marginLeft: 4 }}>{calls.map(c => c.tool).join(', ')}</span>
        <span style={{ fontSize: 9, color: '#333', marginLeft: 'auto' }}>{open ? '▲' : '▼'}</span>
      </button>
      {open && (
        <div style={{ background: '#050505', borderTop: '1px solid #111' }}>
          {calls.map((tc, i) => (
            <div key={i} style={{ borderBottom: '1px solid #0D0D0D', padding: '7px 10px' }}>
              <div style={{ fontSize: 8, color: C.amber, fontWeight: 700, marginBottom: 3 }}>{tc.tool}({JSON.stringify(tc.args)})</div>
              <pre style={{ fontSize: 7, color: '#3A3A3A', overflow: 'auto', maxHeight: 120, margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
                {JSON.stringify(tc.result, null, 2)}
              </pre>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function FinancialAgentPanel() {
  const [messages, setMessages]       = useState<ConvMsg[]>([])
  const [input, setInput]             = useState('')
  const [loading, setLoading]         = useState(false)
  const [ollamaOnline, setOllama]     = useState<boolean | null>(null)
  const [symQuery, setSymQuery]       = useState('')
  const [symResults, setSymResults]   = useState<NSESymbol[]>([])
  const [symSearching, setSymSearching] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    api.ollamaStatus().then(s => setOllama(s.online)).catch(() => setOllama(false))
  }, [])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  async function send(text: string) {
    if (!text.trim() || loading) return
    const userMsg: ConvMsg = { role: 'user', content: text.trim() }
    setMessages(prev => [...prev, userMsg])
    setInput('')
    setLoading(true)
    try {
      const history = messages.slice(-10).map(m => ({ role: m.role === 'error' ? 'user' : m.role, content: m.content }))
      const resp = await api.agentQuery(text.trim(), history)
      setOllama(resp.online)
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: resp.answer || '(no response)',
        toolCalls: resp.tool_calls,
        model: resp.model,
        online: resp.online,
      }])
    } catch (e) {
      setMessages(prev => [...prev, { role: 'error', content: String(e) }])
    } finally {
      setLoading(false)
    }
  }

  async function searchSymbols(q: string) {
    setSymQuery(q)
    if (!q.trim()) { setSymResults([]); return }
    setSymSearching(true)
    try {
      const res = await api.symbolSearch(q)
      setSymResults(res)
    } catch { setSymResults([]) }
    finally { setSymSearching(false) }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden' }}>
      {/* Header */}
      <div style={{ padding: '8px 14px', borderBottom: `1px solid ${C.border}`, background: '#080808', flexShrink: 0, display: 'flex', alignItems: 'center', gap: 10 }}>
        <span style={{ fontSize: 9, color: '#3A3A3A', fontWeight: 700, letterSpacing: '.08em', flex: 1 }}>
          ◈ FINANCIAL AGENT — NSE/BSE AI ANALYST
        </span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
          <span style={{ width: 6, height: 6, borderRadius: '50%', background: ollamaOnline === null ? C.warn : ollamaOnline ? C.run : C.err, display: 'inline-block' }} />
          <span style={{ fontSize: 8, color: ollamaOnline === null ? C.warn : ollamaOnline ? C.run : '#666' }}>
            {ollamaOnline === null ? 'CHECKING…' : ollamaOnline ? 'OLLAMA ONLINE' : 'OLLAMA OFFLINE — RULE-BASED MODE'}
          </span>
        </div>
        {!ollamaOnline && ollamaOnline !== null && (
          <span style={{ fontSize: 7, color: '#333', background: '#111', border: '1px solid #1A1A1A', borderRadius: 3, padding: '2px 7px' }}>
            run: ollama serve
          </span>
        )}
      </div>

      {/* Two-column body: chat + symbol search */}
      <div style={{ flex: 1, minHeight: 0, display: 'flex', gap: 0 }}>

        {/* Chat column */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', borderRight: `1px solid ${C.border}` }}>
          {/* Quick queries */}
          <div style={{ padding: '8px 12px', borderBottom: `1px solid ${C.border}`, flexShrink: 0, display: 'flex', gap: 5, flexWrap: 'wrap', background: '#080808' }}>
            {QUICK_QUERIES.map(q => (
              <button key={q.label} onClick={() => send(q.q)} disabled={loading} style={{
                fontSize: 8, padding: '3px 9px', borderRadius: 10,
                border: `1px solid #1E1E1E`, background: '#0A0A0A',
                color: loading ? '#2A2A2A' : C.amber, cursor: loading ? 'default' : 'pointer',
                letterSpacing: '.04em', transition: 'all .1s',
              }}>{q.label}</button>
            ))}
          </div>

          {/* Messages */}
          <div style={{ flex: 1, overflowY: 'auto', padding: '12px', display: 'flex', flexDirection: 'column', gap: 14 }}>
            {messages.length === 0 && (
              <div style={{ textAlign: 'center', padding: '40px 20px' }}>
                <div style={{ fontSize: 28, color: '#1A1A1A', marginBottom: 12 }}>◈</div>
                <div style={{ fontSize: 10, color: '#2A2A2A', letterSpacing: '.08em', marginBottom: 6 }}>NSE/BSE FINANCIAL ANALYST</div>
                <div style={{ fontSize: 8, color: '#1A1A1A' }}>Ask about stocks, scans, market overview, technical or fundamental analysis</div>
              </div>
            )}
            {messages.map((m, i) => (
              <div key={i} style={{ display: 'flex', flexDirection: 'column', alignItems: m.role === 'user' ? 'flex-end' : 'flex-start', gap: 4 }}>
                {m.role === 'user' && (
                  <div style={{ maxWidth: '80%', background: '#0E1A0E', border: '1px solid #1A2A1A', borderRadius: '8px 8px 2px 8px', padding: '8px 12px' }}>
                    <div style={{ fontSize: 9, color: '#8A8A8A', marginBottom: 3 }}>YOU</div>
                    <div style={{ fontSize: 10, color: '#D0D0D0', lineHeight: 1.6 }}>{m.content}</div>
                  </div>
                )}
                {(m.role === 'assistant' || m.role === 'error') && (
                  <div style={{ maxWidth: '92%', width: '92%' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                      <span style={{ fontSize: 7, color: m.role === 'error' ? C.err : C.teal, fontWeight: 700, letterSpacing: '.07em' }}>
                        {m.role === 'error' ? '✗ ERROR' : '◈ AGENT'}
                      </span>
                      {m.model && <span style={{ fontSize: 7, color: '#2A2A2A' }}>{m.model}</span>}
                      {m.online === false && <span style={{ fontSize: 7, color: '#3A3A3A' }}>rule-based</span>}
                    </div>
                    <div style={{
                      background: m.role === 'error' ? '#1A0808' : '#0A0D0A',
                      border: `1px solid ${m.role === 'error' ? '#E5393522' : '#1A2A1A'}`,
                      borderRadius: '2px 8px 8px 8px', padding: '10px 14px',
                      fontSize: 10, color: m.role === 'error' ? C.err : '#C8C8C8',
                      lineHeight: 1.65,
                    }}>
                      {renderAnswer(m.content)}
                    </div>
                    {m.toolCalls && m.toolCalls.length > 0 && <ToolCallAccordion calls={m.toolCalls} />}
                  </div>
                )}
              </div>
            ))}
            {loading && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 0' }}>
                <div style={{ display: 'flex', gap: 4 }}>
                  {[0,1,2].map(j => (
                    <div key={j} style={{
                      width: 5, height: 5, borderRadius: '50%', background: C.teal,
                      animation: `blink 1.2s ease-in-out ${j * 0.2}s infinite`,
                    }} />
                  ))}
                </div>
                <span style={{ fontSize: 8, color: '#333' }}>agent thinking…</span>
              </div>
            )}
            <div ref={bottomRef} />
          </div>

          {/* Input */}
          <div style={{ padding: '10px 12px', borderTop: `1px solid ${C.border}`, flexShrink: 0, background: '#080808', display: 'flex', gap: 8 }}>
            <input
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(input) } }}
              placeholder="Ask about NSE stocks, market conditions, technical setups…"
              disabled={loading}
              style={{
                flex: 1, fontSize: 10, background: '#0A0A0A', border: `1px solid ${C.border2}`,
                borderRadius: 4, color: C.text, padding: '8px 12px', outline: 'none',
                opacity: loading ? 0.5 : 1,
              }}
            />
            <button
              onClick={() => send(input)}
              disabled={loading || !input.trim()}
              style={{
                fontSize: 9, fontWeight: 700, padding: '8px 16px', borderRadius: 4,
                border: `1px solid ${C.run}33`, background: '#0A1A0A',
                color: loading || !input.trim() ? '#333' : C.run,
                cursor: loading || !input.trim() ? 'default' : 'pointer',
              }}
            >
              {loading ? '…' : 'SEND'}
            </button>
            {messages.length > 0 && (
              <button onClick={() => setMessages([])} style={{
                fontSize: 9, padding: '8px 10px', borderRadius: 4,
                border: '1px solid #1A1A1A', background: 'transparent',
                color: '#333', cursor: 'pointer',
              }}>CLR</button>
            )}
          </div>
        </div>

        {/* Symbol search panel */}
        <div style={{ width: 220, display: 'flex', flexDirection: 'column', overflow: 'hidden', background: '#080808' }}>
          <div style={{ padding: '8px 10px', borderBottom: `1px solid ${C.border}`, flexShrink: 0 }}>
            <div style={{ fontSize: 8, color: '#2A2A2A', letterSpacing: '.08em', marginBottom: 6 }}>NSE SYMBOL LOOKUP</div>
            <input
              value={symQuery}
              onChange={e => searchSymbols(e.target.value)}
              placeholder="Search ticker or name…"
              style={{
                width: '100%', fontSize: 9, background: '#0A0A0A', border: `1px solid ${C.border}`,
                borderRadius: 3, color: '#888', padding: '5px 8px', outline: 'none', boxSizing: 'border-box',
              }}
            />
          </div>
          <div style={{ flex: 1, overflowY: 'auto' }}>
            {symSearching && <div style={{ padding: '8px 10px', fontSize: 8, color: '#2A2A2A' }}>searching…</div>}
            {!symSearching && symResults.length === 0 && symQuery && (
              <div style={{ padding: '8px 10px', fontSize: 8, color: '#1E1E1E' }}>no matches</div>
            )}
            {!symSearching && symResults.length === 0 && !symQuery && (
              <div style={{ padding: '12px 10px', display: 'flex', flexDirection: 'column', gap: 4 }}>
                <div style={{ fontSize: 7, color: '#1E1E1E', letterSpacing: '.07em', marginBottom: 4 }}>QUICK ASK</div>
                {['RELIANCE', 'HDFCBANK', 'TCS', 'INFY', 'SBIN'].map(sym => (
                  <button key={sym} onClick={() => send(`Full technical analysis of ${sym}`)}
                    disabled={loading} style={{
                      fontSize: 9, padding: '4px 8px', textAlign: 'left',
                      background: '#0A0A0A', border: '1px solid #141414', borderRadius: 3,
                      color: loading ? '#2A2A2A' : C.warn, cursor: loading ? 'default' : 'pointer',
                    }}>
                    {sym}
                  </button>
                ))}
              </div>
            )}
            {symResults.map(s => (
              <div key={s.symbol} style={{ borderBottom: `1px solid #0D0D0D` }}>
                <button
                  onClick={() => send(`Full technical and fundamental analysis of ${s.symbol}`)}
                  disabled={loading}
                  style={{
                    width: '100%', padding: '7px 10px', background: 'transparent', border: 'none',
                    textAlign: 'left', cursor: loading ? 'default' : 'pointer', display: 'flex', flexDirection: 'column', gap: 1,
                  }}
                >
                  <span style={{ fontSize: 9, fontWeight: 700, color: C.warn }}>{s.symbol}</span>
                  <span style={{ fontSize: 7, color: '#3A3A3A', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '100%' }}>{s.name}</span>
                  <span style={{ fontSize: 7, color: '#2A2A2A' }}>{s.series}</span>
                </button>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Page
// ─────────────────────────────────────────────────────────────────────────────
// ─────────────────────────────────────────────────────────────────────────────
// Trade Planner (LLM judge) panel
// ─────────────────────────────────────────────────────────────────────────────
function PlannerModeBadge({ mode, model, latencyMs }: { mode: string; model?: string | null; latencyMs?: number | null }) {
  const cfg = mode === 'llm'
    ? { color: C.green, label: `LLM · ${model ?? '?'} · ${latencyMs != null ? (latencyMs / 1000).toFixed(1) + 's' : '—'}` }
    : mode === 'degraded'
    ? { color: C.amber, label: 'DEGRADED — deterministic high bar (Ollama unreachable)' }
    : mode === 'off'
    ? { color: C.muted, label: 'PLANNER OFF' }
    : { color: C.muted, label: 'AWAITING FIRST SCAN' }
  return (
    <span style={{
      fontSize: 8, fontWeight: 700, letterSpacing: '.06em', padding: '2px 8px',
      borderRadius: 3, border: `1px solid ${cfg.color}44`, color: cfg.color,
      background: `${cfg.color}0A`,
    }}>{cfg.label}</span>
  )
}

function PlannerPanel({ state }: { state: PlannerState | null }) {
  const verdict = (state?.last_verdict ?? {}) as PlannerVerdict
  const items = verdict.verdicts ?? []
  return (
    <div>
      <div style={{ fontSize: 8, color: '#2A2A2A', letterSpacing: '.09em', fontWeight: 700, marginBottom: 8, display: 'flex', alignItems: 'center', gap: 8 }}>
        ⚖ TRADE PLANNER — LLM JUDGE
        <PlannerModeBadge mode={state?.mode ?? 'idle'} model={state?.model} latencyMs={state?.last_latency_ms} />
        {verdict.ts ? <span style={{ fontSize: 8, color: '#333' }}>scan #{verdict.scan_id} · {fmtTs(verdict.ts)}</span> : null}
        <div style={{ flex: 1, height: 1, background: '#111' }} />
      </div>
      {items.length === 0 ? (
        <div style={{ fontSize: 9, color: '#333', padding: '8px 4px' }}>
          No verdicts yet — the planner rules on each orchestrator batch (one LLM call per scan).
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          {items.map((v, i) => (
            <div key={`${v.symbol}-${i}`} className="row-in" style={{
              display: 'flex', alignItems: 'baseline', gap: 10, padding: '6px 10px',
              background: C.card, border: `1px solid ${C.border}`, borderRadius: 4,
              borderLeft: `2px solid ${v.action === 'approve' ? C.green : C.red}`,
            }}>
              <span style={{
                fontSize: 8, fontWeight: 800, letterSpacing: '.06em', minWidth: 52,
                color: v.action === 'approve' ? C.green : C.red,
              }}>{v.action === 'approve' ? '✓ APPROVE' : '✕ REJECT'}</span>
              <span style={{ fontSize: 10, fontWeight: 700, color: C.text, minWidth: 84 }}>{v.symbol}</span>
              <span style={{ fontSize: 9, color: v.side === 'BUY' ? C.green : C.red, minWidth: 30 }}>{v.side ?? ''}</span>
              {v.ev != null && <span style={{ fontSize: 9, color: C.sub, minWidth: 56 }}>EV {v.ev.toFixed(2)}</span>}
              {v.action === 'approve' && v.size_factor !== 1.0 && (
                <span style={{ fontSize: 9, color: C.amber, minWidth: 44 }}>size ×{v.size_factor.toFixed(2)}</span>
              )}
              <span style={{ fontSize: 9, color: '#666', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                title={v.reason}>{v.reason}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Trading Supervisor (control loop) panel
// ─────────────────────────────────────────────────────────────────────────────
function SupervisorPanel({ state }: { state: SupervisorState | null }) {
  const suppressed = Object.entries(state?.suppressed_lenses ?? {})
  const throttle = state?.throttle_level ?? 0
  const consec = state?.consec_losses ?? 0
  const allQuiet = suppressed.length === 0 && throttle === 0
  return (
    <div>
      <div style={{ fontSize: 8, color: '#2A2A2A', letterSpacing: '.09em', fontWeight: 700, marginBottom: 8, display: 'flex', alignItems: 'center', gap: 8 }}>
        ⟲ SUPERVISOR — CONTROL LOOP
        {throttle > 0 && (
          <span style={{ fontSize: 8, fontWeight: 700, padding: '2px 8px', borderRadius: 3, border: `1px solid ${C.amber}44`, color: C.amber, background: `${C.amber}0A` }}>
            THROTTLED L{throttle}
          </span>
        )}
        <div style={{ flex: 1, height: 1, background: '#111' }} />
      </div>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        {allQuiet ? (
          <span style={{ fontSize: 9, color: '#333' }}>
            All lenses active · consecutive losses: {consec} · breaker at 3 (per lens) / throttle at 5 / hard stop at 8
          </span>
        ) : (
          <>
            {suppressed.map(([lens, secs]) => (
              <span key={lens} style={{
                fontSize: 9, fontWeight: 700, padding: '4px 10px', borderRadius: 4,
                border: `1px solid ${C.red}44`, color: C.red, background: `${C.red}0A`,
              }}>
                {lens} suppressed · {Math.max(1, Math.round(secs / 60))}m left
              </span>
            ))}
            <span style={{ fontSize: 9, color: '#555' }}>consecutive losses: {consec}</span>
          </>
        )}
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Decision log tab (planner decisions + hindsight)
// ─────────────────────────────────────────────────────────────────────────────
const HINDSIGHT_C: Record<string, string> = {
  would_win: C.red, would_lose: C.green, flat: C.muted,
  actual_win: C.green, actual_loss: C.red,
}

function DecisionLogTab({ decisions }: { decisions: AgentDecision[] }) {
  const [missedOnly, setMissedOnly] = useState(false)
  const rows = missedOnly
    ? decisions.filter(d => d.planner_action !== 'fired' && d.planner_action !== 'approve' && d.hindsight_outcome === 'would_win')
    : decisions
  const th: React.CSSProperties = { fontSize: 8, color: '#2A2A2A', letterSpacing: '.08em', fontWeight: 700, textAlign: 'left', padding: '6px 8px', position: 'sticky', top: 0, background: C.panel }
  const td: React.CSSProperties = { fontSize: 9, padding: '5px 8px', borderTop: `1px solid #111`, whiteSpace: 'nowrap' }
  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px', borderBottom: `1px solid ${C.border}`, flexShrink: 0 }}>
        <span style={{ fontSize: 9, color: '#555' }}>
          Every candidate the agents ruled on — and what the market did next. Rejections that would have won are the cost of caution; track them.
        </span>
        <div style={{ flex: 1 }} />
        <button onClick={() => setMissedOnly(m => !m)} style={{
          fontSize: 8, fontWeight: 700, padding: '3px 10px', borderRadius: 3, cursor: 'pointer',
          border: `1px solid ${missedOnly ? C.amber : C.border2}`,
          background: missedOnly ? '#F7931E0A' : 'transparent',
          color: missedOnly ? C.amber : '#555',
        }}>MISSED WINNERS</button>
      </div>
      <div style={{ flex: 1, overflowY: 'auto' }}>
        {rows.length === 0 ? (
          <div style={{ padding: 40, textAlign: 'center', fontSize: 9, color: '#333' }}>
            {missedOnly ? 'No missed winners in the recent log.' : 'No decisions recorded yet — they appear after the first planner-ruled scan.'}
          </div>
        ) : (
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead><tr>
              <th style={th}>TIME</th><th style={th}>SYMBOL</th><th style={th}>SIDE</th>
              <th style={th}>EV</th><th style={th}>CONF</th><th style={th}>PERSIST</th>
              <th style={th}>ACTION</th><th style={th}>MODE</th><th style={th}>HINDSIGHT</th><th style={th}>REASON</th>
            </tr></thead>
            <tbody>
              {rows.map(d => {
                const actionC = d.planner_action === 'approve' || d.planner_action === 'fired' ? C.green
                  : d.planner_action === 'reject' ? C.red : C.muted
                const hc = d.hindsight_outcome ? HINDSIGHT_C[d.hindsight_outcome] ?? C.muted : '#2A2A2A'
                return (
                  <tr key={d.decision_id}>
                    <td style={{ ...td, color: '#555' }}>{fmtTs(d.decided_at)}</td>
                    <td style={{ ...td, color: C.text, fontWeight: 700 }}>{d.symbol}</td>
                    <td style={{ ...td, color: d.side === 'BUY' ? C.green : C.red }}>{d.side}</td>
                    <td style={{ ...td, color: C.sub }}>{d.ev?.toFixed(2) ?? '—'}</td>
                    <td style={{ ...td, color: C.sub }}>{d.confidence != null ? `${(d.confidence * 100).toFixed(0)}%` : '—'}</td>
                    <td style={{ ...td, color: C.sub }}>{d.persistence ?? '—'}</td>
                    <td style={{ ...td, color: actionC, fontWeight: 700 }}>{d.planner_action.toUpperCase()}</td>
                    <td style={{ ...td, color: d.planner_mode === 'llm' ? C.teal : d.planner_mode === 'degraded' ? C.amber : '#444' }}>{d.planner_mode}</td>
                    <td style={{ ...td, color: hc, fontWeight: 600 }}>
                      {d.hindsight_outcome
                        ? `${d.hindsight_ret_pct != null ? `${(d.hindsight_ret_pct * 100).toFixed(1)}% ` : ''}${d.hindsight_outcome}`
                        : 'pending'}
                    </td>
                    <td style={{ ...td, color: '#666', maxWidth: 320, overflow: 'hidden', textOverflow: 'ellipsis' }} title={d.planner_reason ?? ''}>
                      {d.planner_reason}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

type Tab = 'matrix' | 'judge' | 'pipeline' | 'scoreboard' | 'broadcast' | 'query'
type SelType = { kind: 'agent'; id: string } | { kind: 'signal'; signalId: string }

export default function AgentsPage() {
  const [tab,           setTab]          = useState<Tab>('matrix')
  const [filter,        setFilter]       = useState<Filter>('all')
  const [agents,        setAgents]       = useState<AgentState[]>([])
  const [decisions,     setDecisions]    = useState<DecisionRecord[]>([])
  const [events,        setEvents]       = useState<EventRecord[]>([])
  const [audit,         setAudit]        = useState<AuditEntry[]>([])
  const [riskState,     setRisk]         = useState<KillSwitchState | null>(null)
  const [health,        setHealth]       = useState<SystemHealth | null>(null)
  const [regime,        setRegime]       = useState<RegimeState | null>(null)
  const [portfolio,     setPortfolio]    = useState<PortfolioSummary | null>(null)
  const [instruments,   setInstruments]  = useState<Array<{symbol:string;token:number}>>([])
  const [scorecards,    setScorecards]   = useState<Scorecard[]>([])
  const [learnerParams, setLearnerParams] = useState<LearnerParams[]>([])
  const [allocations,   setAllocations]  = useState<Record<string, number>>({})
  const [orchState,     setOrchState]    = useState<OrchestratorState | null>(null)
  const [plannerState,  setPlannerState] = useState<PlannerState | null>(null)
  const [supState,      setSupState]     = useState<SupervisorState | null>(null)
  const [agentDecisions, setAgentDecisions] = useState<AgentDecision[]>([])
  const [backendHealth, setBackendHealth] = useState<BackendHealth | null>(null)
  const [selected,      setSelected]     = useState<SelType | null>(null)
  const [lineage,       setLineage]      = useState<SignalLineage | null>(null)
  const [lineageLoading, setLineageLoading] = useState(false)
  const [loading,        setLoading]      = useState(true)
  const [backendDown,    setBackendDown]  = useState(false)

  const load = useCallback(async () => {
    const [a, r, au, ins, h, reg, port, sc, lp, alloc, orch, plan, sup, bh] = await Promise.allSettled([
      api.agents(),
      api.riskState(),
      api.agentAudit(100),
      api.instruments(),
      api.agentHealth(),
      api.regime(),
      api.portfolio(),
      api.scorecards(),
      api.learnerParams(),
      api.allocations(),
      api.orchestratorState(),
      api.plannerState(),
      api.supervisorState(),
      api.backendHealth(),
    ])
    const anyOk = [a, r, au, ins, h, reg, port, sc, lp, alloc, orch].some(x => x.status === 'fulfilled')
    setBackendDown(!anyOk)
    if (a.status === 'fulfilled')     setAgents(a.value)
    if (r.status === 'fulfilled')     setRisk(r.value)
    if (au.status === 'fulfilled')    setAudit(au.value)
    if (ins.status === 'fulfilled')   setInstruments(ins.value.map(i => ({ symbol: i.symbol, token: i.token })))
    if (h.status === 'fulfilled')     setHealth(h.value)
    if (reg.status === 'fulfilled')   setRegime(reg.value)
    if (port.status === 'fulfilled')  setPortfolio(port.value)
    if (sc.status === 'fulfilled')    setScorecards(sc.value)
    if (lp.status === 'fulfilled')    setLearnerParams(lp.value)
    if (alloc.status === 'fulfilled') setAllocations(alloc.value)
    if (orch.status === 'fulfilled')  setOrchState(orch.value)
    if (plan.status === 'fulfilled')  setPlannerState(plan.value)
    if (sup.status === 'fulfilled')   setSupState(sup.value)
    if (bh.status === 'fulfilled')    setBackendHealth(bh.value)
    setLoading(false)
  }, [])

  const loadDecisions = useCallback(async () => {
    const [d, ad] = await Promise.allSettled([api.decisions(100), api.plannerDecisions(100)])
    if (d.status === 'fulfilled')  setDecisions(d.value)
    if (ad.status === 'fulfilled') setAgentDecisions(ad.value)
  }, [])

  const loadEvents = useCallback(async () => {
    const e = await api.busEvents(300).catch(() => [])
    setEvents(e)
  }, [])

  useEffect(() => { load() }, [load])
  useEffect(() => { loadDecisions() }, [loadDecisions])
  useEffect(() => { if (tab === 'broadcast') loadEvents() }, [tab, loadEvents])

  // WebSocket live updates — debounced 800ms so a burst of events doesn't fire 11 calls each
  useEffect(() => {
    const s = getSocket()
    let allTimer: ReturnType<typeof setTimeout> | null = null
    let decTimer: ReturnType<typeof setTimeout> | null = null
    const debounceAll = () => { if (allTimer) clearTimeout(allTimer); allTimer = setTimeout(() => { load(); loadDecisions() }, 800) }
    const debounceDecisions = () => { if (decTimer) clearTimeout(decTimer); decTimer = setTimeout(loadDecisions, 800) }
    s.on('agent_status_changed',   debounceAll)
    s.on('kill_switch_global_pause', debounceAll)
    s.on('order_approved',         debounceDecisions)
    s.on('trade_closed',           debounceDecisions)
    s.on('orchestrator_scan_done', debounceAll)
    s.on('scorecard_update',       debounceAll)
    s.on('learner_params_updated', debounceAll)
    s.on('planner_verdict',        debounceAll)
    s.on('supervisor_throttle',    debounceAll)
    return () => {
      s.off('agent_status_changed',   debounceAll)
      s.off('kill_switch_global_pause', debounceAll)
      s.off('order_approved',         debounceDecisions)
      s.off('trade_closed',           debounceDecisions)
      s.off('orchestrator_scan_done', debounceAll)
      s.off('scorecard_update',       debounceAll)
      s.off('learner_params_updated', debounceAll)
      s.off('planner_verdict',        debounceAll)
      s.off('supervisor_throttle',    debounceAll)
      if (allTimer) clearTimeout(allTimer)
      if (decTimer) clearTimeout(decTimer)
    }
  }, [load, loadDecisions])

  // Polling fallback
  useEffect(() => {
    const t = setInterval(() => {
      load()
      loadDecisions()
      if (tab === 'broadcast') loadEvents()
    }, 10_000)
    return () => clearInterval(t)
  }, [load, loadDecisions, loadEvents, tab])

  // Lineage fetch
  useEffect(() => {
    if (!selected || selected.kind !== 'signal') { setLineage(null); return }
    setLineageLoading(true)
    api.lineage(selected.signalId)
      .then(l => { setLineage(l); setLineageLoading(false) })
      .catch(() => setLineageLoading(false))
  }, [selected])

  const globalPaused = riskState?.global_pause ?? false

  const filteredAgents = agents.filter(a => {
    if (filter === 'all')          return true
    if (filter === 'strategy')     return a.agent_type === 'strategy'
    if (filter === 'orchestrator') return a.agent_type === 'orchestrator'
    if (filter === 'risk')         return a.agent_type === 'system'
    if (filter === 'execution')    return a.agent_id === 'BROKER'
    return true
  })

  const systemAgents = filteredAgents.filter(a => a.agent_type === 'system' || a.agent_id === 'BROKER')
  const orchAgents   = filteredAgents.filter(a => a.agent_type === 'orchestrator')
  const stratAgents  = filteredAgents.filter(a => a.agent_type === 'strategy')

  const scMap: Record<string, Scorecard>     = {}
  for (const sc of scorecards) scMap[sc.strategy_id] = sc
  const lpMap: Record<string, LearnerParams> = {}
  for (const lp of learnerParams) lpMap[lp.strategy_id] = lp

  const selectedAgent = selected?.kind === 'agent' ? agents.find(a => a.agent_id === selected.id) ?? null : null

  const TABS: Array<{ key: Tab; label: string }> = [
    { key: 'matrix',     label: 'MATRIX' },
    { key: 'judge',      label: '⚖ DECISION LOG' },
    { key: 'pipeline',   label: 'PIPELINE' },
    { key: 'scoreboard', label: 'SCOREBOARD' },
    { key: 'broadcast',  label: 'BROADCAST' },
    { key: 'query',      label: '◈ AI ANALYST' },
  ]

  return (
    <>
      <StyleTag />
      <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', gap: 8, padding: '10px 14px', background: C.bg, overflow: 'hidden' }}>

        <CommandStrip health={health} regime={regime} portfolio={portfolio} globalPaused={globalPaused} decisions={decisions} />

        {/* Tab bar */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 0, background: C.panel, border: `1px solid ${C.border}`, borderRadius: 5, overflow: 'hidden', flexShrink: 0 }}>
          {TABS.map(({ key, label }) => (
            <button key={key} onClick={() => setTab(key)} style={{
              padding: '8px 20px', fontSize: 9, fontWeight: tab === key ? 800 : 500, letterSpacing: '.09em',
              background: 'transparent', border: 'none',
              borderBottom: `2px solid ${tab === key ? C.warn : 'transparent'}`,
              color: tab === key ? C.warn : '#3A3A3A', cursor: 'pointer',
            }}>{label}</button>
          ))}
          <div style={{ flex: 1 }} />
          {tab === 'matrix' && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '0 12px', borderLeft: `1px solid ${C.border}` }}>
              <span style={{ fontSize: 8, color: '#2A2A2A' }}>FILTER:</span>
              {FILTER_LABELS.map(({ key, label }) => (
                <button key={key} onClick={() => setFilter(key)} style={{
                  fontSize: 8, padding: '2px 7px', borderRadius: 3,
                  border: `1px solid ${filter === key ? C.warn : 'transparent'}`,
                  background: filter === key ? '#F7931E0A' : 'transparent',
                  color: filter === key ? C.warn : '#444', cursor: 'pointer',
                }}>{label}</button>
              ))}
            </div>
          )}
          {backendHealth && backendHealth.degraded.length > 0 && (
            <span title={`Degraded subsystems: ${backendHealth.degraded.join(', ')}`} style={{
              fontSize: 8, fontWeight: 700, letterSpacing: '.06em', padding: '2px 8px', marginRight: 8,
              borderRadius: 3, border: `1px solid ${C.amber}44`, color: C.amber, background: `${C.amber}0A`,
              alignSelf: 'center',
            }}>
              ⚠ DEGRADED: {backendHealth.degraded.map(d => d.replace(/_/g, ' ')).join(' · ')}
            </span>
          )}
          <button onClick={() => { load(); loadDecisions(); if (tab === 'broadcast') loadEvents() }}
            style={{ padding: '8px 14px', fontSize: 9, color: '#3A3A3A', background: 'none', border: 'none', cursor: 'pointer', borderLeft: `1px solid ${C.border}` }}>
            ↺ REFRESH
          </button>
        </div>

        {/* 3-col layout */}
        <div style={{ flex: 1, minHeight: 0, display: 'grid', gridTemplateColumns: '196px 1fr auto', gap: 8 }}>

          {/* Left rail */}
          <div style={{ overflowY: 'auto' }}>
            <LeftRail agents={agents} filter={filter} onFilter={setFilter}
              riskState={riskState} instruments={instruments} onRefresh={load} globalPaused={globalPaused}
              onOpenQuery={() => setTab('query')} />
          </div>

          {/* Center */}
          <div style={{ minHeight: 0, overflow: 'hidden', display: 'flex', flexDirection: 'column', background: C.panel, border: `1px solid ${C.border}`, borderRadius: 5 }}>

            {/* MATRIX */}
            {tab === 'matrix' && (
              <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 0 }}>
                {/* Pipeline funnel */}
                <div style={{ padding: '10px 12px', borderBottom: `1px solid ${C.border}`, flexShrink: 0 }}>
                  <PipelineFunnel agents={agents} decisions={decisions} />
                </div>
                <div style={{ padding: '12px', display: 'flex', flexDirection: 'column', gap: 14 }}>
                  {/* Orchestrator scan results — the core agentic output */}
                  <OrchestratorPanel state={orchState} onScan={load} />

                  {/* LLM judge verdicts on the latest candidate batch */}
                  <PlannerPanel state={plannerState} />

                  {/* Closed-loop control: lens breakers + throttle */}
                  <SupervisorPanel state={supState} />

                  {/* System agents */}
                  {systemAgents.length > 0 && (
                    <div>
                      <div style={{ fontSize: 8, color: '#2A2A2A', letterSpacing: '.09em', fontWeight: 700, marginBottom: 8, display: 'flex', alignItems: 'center', gap: 8 }}>
                        SYSTEM + EXECUTION
                        <span style={{ fontSize: 8, color: '#1E1E1E', border: '1px solid #1A1A1A', borderRadius: 10, padding: '0 6px' }}>{systemAgents.length}</span>
                        <div style={{ flex: 1, height: 1, background: '#111' }} />
                      </div>
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(280px,1fr))', gap: 8 }}>
                        {systemAgents.map(a => (
                          <SystemAgentCard key={a.agent_id} agent={a} scorecard={scMap[a.agent_id]}
                            onRefresh={load}
                            onClick={() => setSelected(sel => sel?.kind === 'agent' && sel.id === a.agent_id ? null : { kind: 'agent', id: a.agent_id })}
                            selected={selected?.kind === 'agent' && selected.id === a.agent_id} />
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Orchestrator cards */}
                  {orchAgents.length > 0 && (
                    <div>
                      <div style={{ fontSize: 8, color: '#2A2A2A', letterSpacing: '.09em', fontWeight: 700, marginBottom: 8, display: 'flex', alignItems: 'center', gap: 8 }}>
                        ORCHESTRATOR <div style={{ flex: 1, height: 1, background: '#111' }} />
                      </div>
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(280px,1fr))', gap: 8 }}>
                        {orchAgents.map(a => (
                          <SystemAgentCard key={a.agent_id} agent={a} scorecard={scMap[a.agent_id]}
                            onRefresh={load}
                            onClick={() => setSelected(sel => sel?.kind === 'agent' && sel.id === a.agent_id ? null : { kind: 'agent', id: a.agent_id })}
                            selected={selected?.kind === 'agent' && selected.id === a.agent_id} />
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Strategy agents */}
                  {stratAgents.length > 0 && (
                    <div>
                      <div style={{ fontSize: 8, color: '#2A2A2A', letterSpacing: '.09em', fontWeight: 700, marginBottom: 8, display: 'flex', alignItems: 'center', gap: 8 }}>
                        STRATEGIES
                        <span style={{ fontSize: 8, color: '#1E1E1E', border: '1px solid #1A1A1A', borderRadius: 10, padding: '0 6px' }}>{stratAgents.length}</span>
                        <div style={{ flex: 1, height: 1, background: '#111' }} />
                      </div>
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(196px,1fr))', gap: 7 }}>
                        {stratAgents.map(a => (
                          <StrategyCard key={a.agent_id} agent={a}
                            scorecard={scMap[a.agent_id]}
                            learner={lpMap[a.agent_id]}
                            alloc={allocations[a.agent_id] ?? 0}
                            onRefresh={load}
                            onClick={() => setSelected(sel => sel?.kind === 'agent' && sel.id === a.agent_id ? null : { kind: 'agent', id: a.agent_id })}
                            selected={selected?.kind === 'agent' && selected.id === a.agent_id} />
                        ))}
                      </div>
                    </div>
                  )}

                  {filteredAgents.length === 0 && (
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column', gap: 8, padding: 80 }}>
                      {loading ? (
                        <>
                          <div style={{ width: 28, height: 28, border: '2px solid #1E1E1E', borderTopColor: C.warn, borderRadius: '50%', animation: 'spin .8s linear infinite' }} />
                          <style dangerouslySetInnerHTML={{ __html: '@keyframes spin{to{transform:rotate(360deg)}}' }} />
                          <span style={{ fontSize: 9, color: '#333', letterSpacing: '.08em' }}>CONNECTING TO BACKEND…</span>
                        </>
                      ) : backendDown ? (
                        <>
                          <span style={{ fontSize: 24, opacity: .3 }}>⚡</span>
                          <span style={{ fontSize: 10, color: C.err, letterSpacing: '.08em' }}>BACKEND NOT RUNNING</span>
                          <span style={{ fontSize: 8, color: '#333' }}>Run: <code style={{ color: C.amber }}>.venv/Scripts/python.exe -m terminal_in.main</code></span>
                        </>
                      ) : (
                        <>
                          <span style={{ fontSize: 24, opacity: .2 }}>◯</span>
                          <span style={{ fontSize: 10, color: '#333', letterSpacing: '.08em' }}>NO AGENTS ACTIVE</span>
                          <span style={{ fontSize: 8, color: '#1A1A1A' }}>Backend is running but no agents are registered yet</span>
                        </>
                      )}
                    </div>
                  )}
                </div>
              </div>
            )}

            {tab === 'judge' && <DecisionLogTab decisions={agentDecisions} />}

            {tab === 'pipeline' && (
              <PipelineTab agents={agents} decisions={decisions}
                selectedId={selected?.kind === 'signal' ? selected.signalId : null}
                onSelect={sid => setSelected(sel => sel?.kind === 'signal' && sel.signalId === sid ? null : { kind: 'signal', signalId: sid })} />
            )}

            {tab === 'scoreboard' && (
              <ScoreboardView scorecards={scorecards} learnerParams={learnerParams} agents={agents} allocations={allocations} />
            )}

            {tab === 'broadcast' && <BroadcastTab events={events} />}

            {tab === 'query' && <FinancialAgentPanel />}
          </div>

          {/* Right inspector */}
          <div style={{ width: 268, display: 'flex', flexDirection: 'column', background: C.panel, border: `1px solid ${C.border}`, borderRadius: 5, overflow: 'hidden', flexShrink: 0 }}>
            {selected ? (
              <>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 12px', borderBottom: `1px solid ${C.border}`, flexShrink: 0 }}>
                  <span style={{ fontSize: 8, color: '#333', letterSpacing: '.09em', fontWeight: 700 }}>
                    {selected.kind === 'agent' ? 'AGENT DETAIL' : 'SIGNAL LINEAGE'}
                  </span>
                  <button onClick={() => setSelected(null)} style={{ background: 'none', border: 'none', color: '#444', cursor: 'pointer', fontSize: 12 }}>✕</button>
                </div>
                <div style={{ flex: 1, overflowY: 'auto', padding: '12px' }}>
                  {selected.kind === 'agent' && selectedAgent && <AgentInspector agent={selectedAgent} onRefresh={load} />}
                  {selected.kind === 'signal' && (
                    lineageLoading
                      ? <div style={{ color: '#2A2A2A', fontSize: 9, textAlign: 'center', padding: 24 }}>Loading lineage…</div>
                      : lineage
                        ? <SignalLineageView lineage={lineage} />
                        : <div style={{ color: '#2A2A2A', fontSize: 9, textAlign: 'center', padding: 24 }}>Lineage not found</div>
                  )}
                </div>
              </>
            ) : (
              <div style={{ padding: '8px 12px', borderBottom: `1px solid ${C.border}`, flexShrink: 0 }}>
                <span style={{ fontSize: 8, color: '#333', letterSpacing: '.09em', fontWeight: 700 }}>SELECT AGENT OR SIGNAL</span>
              </div>
            )}
            {/* Kill switch audit — always visible */}
            <div style={{ borderTop: `1px solid ${C.border}`, padding: '10px 12px', maxHeight: 220, overflowY: 'auto', flexShrink: 0 }}>
              <AuditLog entries={audit} />
            </div>
          </div>

        </div>
      </div>
    </>
  )
}
