'use client'
import React, { useCallback, useEffect, useRef, useState } from 'react'
import {
  api, AgentState, AuditEntry, DecisionRecord, EventRecord,
  KillSwitchState, RegimeState, PortfolioSummary, SignalLineage,
  SystemHealth, Scorecard, LearnerParams,
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
@keyframes bar-fill    { from{width:0} to{width:var(--w)} }
.ap-run .ring  { animation: pulse-ring 2s cubic-bezier(.215,.61,.355,1) infinite }
.ap-run .core  { animation: pulse-core 2s ease-in-out infinite }
.ap-err .core  { animation: blink 1s ease-in-out infinite }
.row-in        { animation: sweep-in .25s ease-out }
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
  S1: 'Opening Range Breakout',
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

const TOKEN_NAMES: Record<number, string> = {
  256265:'NIFTY 50', 260105:'BANKNIFTY', 257801:'FINNIFTY', 264969:'INDIA VIX',
  738561:'RELIANCE', 341249:'HDFCBANK', 2953217:'TCS', 408065:'INFY',
  1270529:'ICICIBANK', 779521:'SBIN', 1510401:'AXISBANK', 492033:'KOTAKBANK',
  4267265:'BAJFINANCE', 356865:'HINDUNILVR', 969473:'WIPRO', 2800641:'NIFTYBEES',
  2815745:'MARUTI', 3861249:'ADANIPORTS', 2939009:'LT',
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
function symName(token: number) { return TOKEN_NAMES[token] ?? String(token) }
function isNSEOpen() {
  const d = new Date(Date.now() + 5.5 * 3600_000)
  const m = d.getUTCHours() * 60 + d.getUTCMinutes()
  return m >= 9 * 60 + 15 && m <= 15 * 60 + 30
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

function Chip({ label, value, color, wide }: { label: string; value: React.ReactNode; color?: string; wide?: boolean }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: wide ? 72 : undefined }}>
      <span style={{ fontSize: 8, color: '#333', letterSpacing: '.07em', textTransform: 'uppercase' }}>{label}</span>
      <span style={{ fontSize: 11, fontWeight: 600, color: color ?? C.text, fontVariantNumeric: 'tabular-nums' }}>{value}</span>
    </div>
  )
}

function Label({ children, count }: { children: React.ReactNode; count?: number }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
      <span style={{ fontSize: 8, color: '#3A3A3A', letterSpacing: '.1em', fontWeight: 700 }}>{children}</span>
      {count !== undefined && <span style={{ fontSize: 8, color: '#2A2A2A', border: '1px solid #222', borderRadius: 10, padding: '0 6px' }}>{count}</span>}
      <div style={{ flex: 1, height: 1, background: '#161616' }} />
    </div>
  )
}

function Btn({ label, onClick, busy = false, danger = false, disabled = false, full = false, variant = 'default' }:
  { label: string; onClick: () => void; busy?: boolean; danger?: boolean; disabled?: boolean; full?: boolean; variant?: 'default' | 'ghost' | 'primary' }) {
  const bg = danger ? '#1A0808' : variant === 'primary' ? '#0A1A0A' : variant === 'ghost' ? 'transparent' : '#141414'
  const clr = danger ? C.err : variant === 'primary' ? C.run : C.warn
  const bdr = danger ? '#E5393533' : variant === 'primary' ? '#00C85333' : '#2A2A2A'
  return (
    <button disabled={busy || disabled} onClick={onClick} style={{
      width: full ? '100%' : undefined,
      fontSize: 9, fontWeight: 700, letterSpacing: '.06em', padding: '5px 12px',
      border: `1px solid ${bdr}`, borderRadius: 3, cursor: (busy || disabled) ? 'default' : 'pointer',
      background: bg, color: clr, opacity: (busy || disabled) ? 0.35 : 1, transition: 'opacity .15s',
    }}>{label}</button>
  )
}

function AllocBar({ pct, color = C.amber }: { pct: number; color?: string }) {
  return (
    <div style={{ height: 3, background: '#111', borderRadius: 2, overflow: 'hidden' }}>
      <div style={{ height: '100%', width: `${Math.min(100, pct * 100).toFixed(1)}%`, background: color, borderRadius: 2, transition: 'width .4s ease' }} />
    </div>
  )
}

function RateBadge({ rate, label }: { rate: number; label: string }) {
  const c = rate > 5 ? C.run : rate > 1 ? C.warn : '#333'
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 1 }}>
      <span style={{ fontSize: 11, fontWeight: 700, color: c, fontVariantNumeric: 'tabular-nums' }}>{rate.toFixed(1)}</span>
      <span style={{ fontSize: 7, color: '#333', letterSpacing: '.06em' }}>{label}/HR</span>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Command Strip (top 54px bar)
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
    <div style={{ display: 'flex', alignItems: 'center', background: C.panel, border: `1px solid ${hColor}1A`, borderRadius: 5, height: 52, flexShrink: 0, gap: 0, overflow: 'hidden' }}>
      {/* Health score */}
      <div style={{ padding: '0 16px', borderRight: `1px solid ${C.border}`, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2, minWidth: 80, height: '100%', justifyContent: 'center' }}>
        <span style={{ fontSize: 18, fontWeight: 800, color: hColor, lineHeight: 1, fontVariantNumeric: 'tabular-nums' }}>{hPct}<span style={{ fontSize: 11 }}>%</span></span>
        <span style={{ fontSize: 7, color: hColor, letterSpacing: '.1em', fontWeight: 700 }}>
          {globalPaused ? 'KILL ACTIVE' : (health?.errored ?? 0) > 0 ? 'DEGRADED' : hPct >= 100 ? 'NOMINAL' : 'DEGRADED'}
        </span>
      </div>
      {/* Market */}
      <Cell label="MARKET" value={marketOpen ? 'OPEN' : 'CLOSED'} color={marketOpen ? C.run : '#333'} />
      {/* Regime */}
      <Cell label="REGIME" value={(regime?.regime ?? '—').toUpperCase().replace('_', ' ')} color={regC} />
      {/* VIX */}
      <Cell label="INDIA VIX" value={regime ? regime.india_vix.toFixed(2) : '—'} color={regime && regime.india_vix > 22 ? C.err : regime && regime.india_vix > 18 ? C.warn : C.text} />
      {/* Equity */}
      <Cell label="EQUITY" value={portfolio ? `₹${(portfolio.equity / 1000).toFixed(1)}k` : '—'} />
      {/* Day P&L */}
      <Cell label="DAY P&L" value={portfolio ? `${portfolio.daily_pnl >= 0 ? '+' : ''}₹${portfolio.daily_pnl.toFixed(0)}` : '—'}
        color={portfolio ? portfolio.daily_pnl >= 0 ? C.run : C.err : undefined} />
      {/* Drawdown */}
      <Cell label="DRAWDOWN" value={portfolio ? `${(portfolio.drawdown * 100).toFixed(2)}%` : '—'}
        color={portfolio && portfolio.drawdown > 0.05 ? C.err : portfolio && portfolio.drawdown > 0.02 ? C.warn : '#444'} />
      {/* Pipeline */}
      <div style={{ padding: '0 16px', borderLeft: `1px solid ${C.border}`, height: '100%', display: 'flex', alignItems: 'center', gap: 16 }}>
        <PipelineCell label="SIGNALS" n={decisions.length} />
        <span style={{ color: '#222', fontSize: 10 }}>→</span>
        <PipelineCell label="APPROVED" n={approved} color={C.run} />
        <span style={{ color: '#222', fontSize: 10 }}>→</span>
        <PipelineCell label="FILLED" n={filled} color={C.teal} />
        {approvalRate !== null && (
          <div style={{ paddingLeft: 10, borderLeft: '1px solid #1A1A1A' }}>
            <div style={{ fontSize: 7, color: '#333', letterSpacing: '.07em' }}>GATE PASS</div>
            <div style={{ fontSize: 13, fontWeight: 700, color: approvalRate > 0.5 ? C.run : C.warn, fontVariantNumeric: 'tabular-nums' }}>
              {(approvalRate * 100).toFixed(0)}<span style={{ fontSize: 8 }}>%</span>
            </div>
          </div>
        )}
      </div>
      {/* Agents summary */}
      <Cell label="AGENTS" value={health ? `${health.healthy}/${health.total}` : '—'} color={hColor} />
      {/* Kill switch indicator */}
      {globalPaused && (
        <div style={{ marginLeft: 'auto', padding: '0 16px', flexShrink: 0 }}>
          <span style={{ fontSize: 9, color: C.err, fontWeight: 800, background: '#1A0808', border: '1px solid #E5393544', borderRadius: 3, padding: '4px 12px', letterSpacing: '.08em' }}>⬛ KILL SWITCH ACTIVE</span>
        </div>
      )}
    </div>
  )
}

function Cell({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div style={{ padding: '0 14px', borderRight: `1px solid ${C.border}`, height: '100%', display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: 2, flexShrink: 0 }}>
      <span style={{ fontSize: 7, color: '#333', letterSpacing: '.07em' }}>{label}</span>
      <span style={{ fontSize: 12, fontWeight: 600, color: color ?? C.text, fontVariantNumeric: 'tabular-nums', letterSpacing: '.02em' }}>{value}</span>
    </div>
  )
}

function PipelineCell({ label, n, color }: { label: string; n: number; color?: string }) {
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

function LeftRail({ agents, filter, onFilter, riskState, instruments, onRefresh, globalPaused }:
  { agents: AgentState[]; filter: Filter; onFilter: (f: Filter) => void; riskState: KillSwitchState | null; instruments: Array<{symbol:string;token:number}>; onRefresh: () => void; globalPaused: boolean }) {
  const [busy, setBusy] = useState(false)
  const [blockToken, setBlockToken] = useState('')

  async function act(fn: () => Promise<unknown>) {
    setBusy(true); try { await fn() } finally { setBusy(false); onRefresh() }
  }

  const counts: Record<string, number> = { all: agents.length }
  for (const a of agents) {
    const k = a.agent_type === 'system' ? 'risk' : a.agent_type === 'orchestrator' ? 'orchestrator' : a.agent_type
    counts[k] = (counts[k] ?? 0) + 1
  }
  counts.execution = agents.filter(a => a.agent_id === 'BROKER').length

  const runCount  = agents.filter(a => a.status === 'running').length
  const errCount  = agents.filter(a => a.status === 'error').length
  const pauseCount = agents.filter(a => a.status === 'paused').length

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10, width: 200, flexShrink: 0 }}>
      {/* Agent groups */}
      <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 5, overflow: 'hidden' }}>
        <div style={{ padding: '8px 12px', borderBottom: `1px solid ${C.border}`, fontSize: 8, color: '#333', letterSpacing: '.08em', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          AGENT GROUPS
          <span style={{ fontSize: 8, color: C.run }}>{runCount} RUN</span>
        </div>
        {FILTER_LABELS.map(({ key, label }) => (
          <button key={key} onClick={() => onFilter(key)} style={{
            width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            padding: '7px 12px', background: filter === key ? '#F7931E08' : 'transparent',
            border: 'none', borderLeft: `2px solid ${filter === key ? C.warn : 'transparent'}`,
            cursor: 'pointer', fontSize: 9, fontWeight: filter === key ? 700 : 500,
            color: filter === key ? C.warn : '#555', letterSpacing: '.06em', textAlign: 'left',
          }}>
            {label}
            <span style={{ fontSize: 8, color: '#2A2A2A' }}>{counts[key] ?? 0}</span>
          </button>
        ))}
        {/* Status summary */}
        <div style={{ padding: '8px 12px', borderTop: `1px solid ${C.border}`, display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 6, background: '#080808' }}>
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: C.run, fontVariantNumeric: 'tabular-nums' }}>{runCount}</div>
            <div style={{ fontSize: 7, color: '#2A2A2A', letterSpacing: '.06em' }}>RUN</div>
          </div>
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: C.warn, fontVariantNumeric: 'tabular-nums' }}>{pauseCount}</div>
            <div style={{ fontSize: 7, color: '#2A2A2A', letterSpacing: '.06em' }}>PAUSE</div>
          </div>
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: errCount > 0 ? C.err : '#2A2A2A', fontVariantNumeric: 'tabular-nums' }}>{errCount}</div>
            <div style={{ fontSize: 7, color: '#2A2A2A', letterSpacing: '.06em' }}>ERROR</div>
          </div>
        </div>
      </div>

      {/* Risk command */}
      <div style={{ background: C.panel, border: `1px solid ${globalPaused ? '#E5393533' : C.border}`, borderRadius: 5, padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 7 }}>
        <div style={{ fontSize: 8, color: '#333', letterSpacing: '.08em', marginBottom: 2 }}>RISK COMMAND</div>
        <Btn label={globalPaused ? '✓ ALL PAUSED' : '⏸ PAUSE ALL'} onClick={() => act(() => api.riskGlobalPause())} busy={busy} disabled={globalPaused} full variant="primary" />
        <Btn label="▶ RESUME ALL" onClick={() => act(() => api.riskGlobalResume())} busy={busy} disabled={!globalPaused} full />
        <Btn label="⬛ KILL ALL — EMERGENCY" onClick={() => { if (confirm('Kill All: pause all agents and close all positions immediately?')) act(() => api.riskKillAll()) }} busy={busy} full danger />

        {/* Blocked tokens */}
        {(riskState?.blocked_tokens ?? []).length > 0 && (
          <div style={{ borderTop: `1px solid ${C.border}`, paddingTop: 7 }}>
            <div style={{ fontSize: 7, color: '#333', letterSpacing: '.07em', marginBottom: 5 }}>BLOCKED SYMBOLS</div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
              {riskState!.blocked_tokens.map(tok => {
                const sym = instruments.find(i => i.token === tok)?.symbol ?? String(tok)
                return (
                  <span key={tok} style={{ fontSize: 8, background: '#1A0808', border: '1px solid #E5393522', borderRadius: 3, padding: '2px 6px', color: C.err, display: 'flex', alignItems: 'center', gap: 3 }}>
                    {sym}
                    <button onClick={() => act(() => api.riskUnblockSymbol(tok))} style={{ background: 'none', border: 'none', color: C.err, cursor: 'pointer', padding: 0, fontSize: 9 }}>✕</button>
                  </span>
                )
              })}
            </div>
          </div>
        )}

        {/* Block symbol */}
        <select value={blockToken} onChange={e => setBlockToken(e.target.value)} style={{
          width: '100%', fontSize: 9, background: '#080808', border: `1px solid ${C.border}`,
          borderRadius: 3, color: '#555', padding: '4px 6px',
        }}>
          <option value="">— block symbol —</option>
          {instruments.map(i => <option key={i.token} value={String(i.token)}>{i.symbol}</option>)}
        </select>
        {blockToken && (
          <Btn label="BLOCK SELECTED SYMBOL" onClick={async () => { await act(() => api.riskBlockSymbol(Number(blockToken))); setBlockToken('') }} busy={busy} full danger />
        )}
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Pipeline Funnel
// ─────────────────────────────────────────────────────────────────────────────
function PipelineFunnel({ agents, decisions }: { agents: AgentState[]; decisions: DecisionRecord[] }) {
  const scanned   = agents.filter(a => a.agent_type === 'strategy').reduce((s, a) => s + a.eval_count, 0)
  const signals   = agents.filter(a => a.agent_type === 'strategy').reduce((s, a) => s + a.signal_count, 0)
  const evaluated = decisions.length
  const approved  = decisions.filter(d => d.approved === 1).length
  const filled    = decisions.filter(d => d.trade_id !== null).length

  const steps = [
    { label: 'EVALS', n: scanned, color: '#334' },
    { label: 'SIGNALS', n: signals, color: C.amber },
    { label: 'DECISIONS', n: evaluated, color: '#556' },
    { label: 'APPROVED', n: approved, color: C.run },
    { label: 'FILLED', n: filled, color: C.teal },
  ]
  const max = Math.max(...steps.map(s => s.n), 1)

  return (
    <div style={{ display: 'flex', alignItems: 'stretch', gap: 1, background: '#080808', border: `1px solid ${C.border}`, borderRadius: 4, overflow: 'hidden', flexShrink: 0, height: 44 }}>
      {steps.map((s, i) => {
        const convRate = i > 0 && steps[i - 1].n > 0 ? (s.n / steps[i - 1].n * 100).toFixed(0) : null
        return (
          <div key={s.label} style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center', padding: '0 12px', borderRight: i < steps.length - 1 ? `1px solid ${C.border}` : undefined, position: 'relative', overflow: 'hidden' }}>
            {/* fill bar at bottom */}
            <div style={{ position: 'absolute', bottom: 0, left: 0, height: `${(s.n / max) * 100}%`, width: '100%', background: `${s.color}18`, transition: 'height .5s ease' }} />
            <div style={{ position: 'relative', display: 'flex', alignItems: 'baseline', gap: 5 }}>
              <span style={{ fontSize: 14, fontWeight: 800, color: s.color, fontVariantNumeric: 'tabular-nums' }}>{fmtN(s.n)}</span>
              {convRate && <span style={{ fontSize: 8, color: '#444' }}>{convRate}%</span>}
            </div>
            <span style={{ position: 'relative', fontSize: 7, color: '#333', letterSpacing: '.08em' }}>{s.label}</span>
          </div>
        )
      })}
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
  const bColor = agent.status === 'error' ? '#E5393522' : isPaused ? '#F7931E22' : selected ? '#F7931E18' : C.border

  const evalRate = agent.last_eval_ts ? Math.round(agent.eval_count / Math.max(1, (Date.now() - (agent.last_eval_ts - agent.eval_count * 60_000)) / 3_600_000)) : 0
  const sigRate  = agent.last_signal_ts ? (agent.signal_count / Math.max(0.1, agent.heartbeat_age_s / 3600)) : 0

  return (
    <div onClick={onClick} style={{
      background: agent.status === 'error' ? '#0E0808' : isPaused ? '#0E0A06' : '#0E0E0E',
      border: `1px solid ${bColor}`, borderRadius: 5, padding: '12px 14px',
      cursor: 'pointer', display: 'flex', flexDirection: 'column', gap: 10,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <Dot status={agent.status} size={8} />
        <span style={{ fontSize: 16, color: '#222' }}>{AGENT_ICON[agent.agent_id] ?? '◯'}</span>
        <div style={{ flex: 1 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
            <span style={{ fontSize: 12, fontWeight: 800, color: '#E0E0E0', letterSpacing: '.03em' }}>{agent.agent_id}</span>
            <span style={{ fontSize: 8, color: C.warn, background: '#F7931E11', border: '1px solid #F7931E22', borderRadius: 2, padding: '0 5px', letterSpacing: '.05em' }}>
              {agent.agent_type.toUpperCase()}
            </span>
          </div>
          <div style={{ fontSize: 8, color: '#3A3A3A', marginTop: 1 }}>{AGENT_DESC[agent.agent_id] ?? agent.description}</div>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 2 }}>
          <span style={{ fontSize: 8, color: STATUS_C[agent.status], fontWeight: 700, letterSpacing: '.06em' }}>{agent.status.toUpperCase()}</span>
          <span style={{ fontSize: 8, color: ageC(agent.heartbeat_age_s), fontVariantNumeric: 'tabular-nums' }}>HB {fmtAge(agent.heartbeat_age_s)}</span>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 8, background: '#080808', borderRadius: 3, padding: '8px 10px' }}>
        <Chip label="EVALS" value={fmtN(agent.eval_count)} />
        <Chip label="SIGNALS" value={fmtN(agent.signal_count)} />
        <Chip label="LAST EVAL" value={agent.last_eval_ts ? fmtTs(agent.last_eval_ts) : '—'} />
        <Chip label="CONF ≥" value={agent.confidence_threshold.toFixed(2)} color={C.warn} />
      </div>

      {scorecard && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 8, padding: '6px 10px', background: '#0A0A0A', borderRadius: 3, border: '1px solid #111' }}>
          <Chip label="TRADES" value={scorecard.total_trades} />
          <Chip label="BAY WR" value={fmtPct(scorecard.bayesian_wr)} color={scorecard.bayesian_wr > 0.5 ? C.run : C.warn} />
          <Chip label="EXPECT" value={`₹${scorecard.expectancy.toFixed(0)}`} color={scorecard.expectancy > 0 ? C.run : C.err} />
          <Chip label="P&L" value={`₹${scorecard.total_pnl.toFixed(0)}`} color={scorecard.total_pnl >= 0 ? C.run : C.err} />
        </div>
      )}

      {agent.status === 'error' && agent.last_error && (
        <div style={{ fontSize: 8, color: C.err, background: '#1A0808', border: '1px solid #E5393522', borderRadius: 3, padding: '5px 8px', wordBreak: 'break-all' }}>
          ⚠ {agent.last_error}
        </div>
      )}

      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }} onClick={e => (e as unknown as React.MouseEvent).stopPropagation()}>
        <Btn label={isPaused ? '▶ RESUME' : '⏸ PAUSE'} busy={busy}
          onClick={() => act(isPaused ? () => api.agentResume(agent.agent_id) : () => api.agentPause(agent.agent_id))} />
        {agent.agent_id === 'ENGINE' && (
          <Btn label="⟳ FORCE EVAL" busy={busy} onClick={() => act(() => api.agentForceEval(agent.agent_id))} variant="primary" />
        )}
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 5 }}>
          <span style={{ fontSize: 8, color: '#333' }}>conf≥</span>
          <input type="number" min="0" max="1" step="0.01" value={thresh} onChange={e => setThresh(e.target.value)}
            style={{ width: 48, fontSize: 9, background: '#080808', border: `1px solid ${C.border}`, borderRadius: 3, color: '#777', padding: '2px 5px' }} />
          <Btn label="SET" busy={busy} onClick={() => { const v = parseFloat(thresh); if (!isNaN(v)) act(() => api.agentSetThreshold(agent.agent_id, v)) }} />
        </div>
      </div>
    </div>
  )
}

function StrategyCard({ agent, scorecard, learner, onRefresh, selected, onClick }:
  { agent: AgentState; scorecard?: Scorecard; learner?: LearnerParams; onRefresh: () => void; selected: boolean; onClick: () => void }) {
  const [busy, setBusy] = useState(false)
  async function act(fn: () => Promise<unknown>) { setBusy(true); try { await fn() } finally { setBusy(false); onRefresh() } }
  const isPaused = agent.status === 'paused'
  const bColor = agent.status === 'error' ? '#E5393522' : isPaused ? '#F7931E22' : selected ? '#F7931E22' : C.border
  const alloc = scorecard ? (scorecard.total_pnl > 0 ? 0.6 : 0.4) : 0.2

  return (
    <div onClick={onClick} style={{
      background: agent.status === 'error' ? '#0E0808' : isPaused ? '#0E0A06' : C.card,
      border: `1px solid ${bColor}`, borderRadius: 4,
      padding: '10px 11px', cursor: 'pointer', display: 'flex', flexDirection: 'column', gap: 7,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <Dot status={agent.status} size={6} />
        <span style={{ fontSize: 11, color: '#1E1E1E' }}>{AGENT_ICON[agent.agent_id] ?? '◯'}</span>
        <span style={{ fontSize: 11, fontWeight: 800, color: '#E0E0E0', letterSpacing: '.03em', flex: 1 }}>{agent.agent_id}</span>
        <span style={{ fontSize: 7, color: ageC(agent.heartbeat_age_s), fontVariantNumeric: 'tabular-nums' }}>{fmtAge(agent.heartbeat_age_s)}</span>
      </div>

      <div style={{ fontSize: 8, color: '#3A3A3A', marginTop: -3 }}>{AGENT_DESC[agent.agent_id] ?? agent.description}</div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 6 }}>
        <Chip label="EVALS" value={fmtN(agent.eval_count)} />
        <Chip label="SIGS" value={fmtN(agent.signal_count)} />
        <Chip label="CONF" value={agent.confidence_threshold.toFixed(2)} color={C.warn} />
      </div>

      {scorecard && (
        <div style={{ background: '#080808', borderRadius: 3, padding: '6px 8px', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
          <Chip label="BAY WR" value={fmtPct(scorecard.bayesian_wr)} color={scorecard.bayesian_wr > 0.5 ? C.run : C.warn} />
          <Chip label="P&L" value={`₹${scorecard.total_pnl.toFixed(0)}`} color={scorecard.total_pnl >= 0 ? C.run : C.err} />
        </div>
      )}

      {/* DSA allocation approximation bar */}
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
          <span style={{ fontSize: 7, color: '#2A2A2A', letterSpacing: '.07em' }}>DSA ALLOC</span>
          <span style={{ fontSize: 7, color: C.warn }}>{(alloc * 100).toFixed(0)}%</span>
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

      <div style={{ display: 'flex', gap: 5, alignItems: 'center' }} onClick={e => (e as unknown as React.MouseEvent).stopPropagation()}>
        <Btn label={isPaused ? '▶' : '⏸'} busy={busy}
          onClick={() => act(isPaused ? () => api.agentResume(agent.agent_id) : () => api.agentPause(agent.agent_id))} />
        <span style={{ fontSize: 8, color: '#2A2A2A', marginLeft: 'auto' }}>{fmtN(agent.signal_count)} signals</span>
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Strategy Scoreboard Tab
// ─────────────────────────────────────────────────────────────────────────────
const SCOLS = '72px 100px 64px 64px 64px 64px 80px 64px 72px 64px'

function ScoreboardRow({ sc, lp, agents }: { sc: Scorecard; lp?: LearnerParams; agents: AgentState[] }) {
  const agent = agents.find(a => a.agent_id === sc.strategy_id)
  const status = agent?.status ?? 'idle'

  return (
    <div style={{ display: 'grid', gridTemplateColumns: SCOLS, gap: 0, padding: '7px 12px', borderBottom: `1px solid ${C.border}`, alignItems: 'center' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
        <Dot status={status} size={5} />
        <span style={{ fontSize: 9, fontWeight: 700, color: '#D8D8D8' }}>{sc.strategy_id}</span>
      </div>
      <span style={{ fontSize: 8, color: '#3A3A3A' }}>{AGENT_DESC[sc.strategy_id] ?? ''}</span>
      <span style={{ fontSize: 10, fontVariantNumeric: 'tabular-nums', color: C.text, textAlign: 'right' }}>{sc.total_trades}</span>
      <span style={{ fontSize: 10, fontVariantNumeric: 'tabular-nums', color: sc.bayesian_wr > 0.5 ? C.run : C.warn, textAlign: 'right' }}>{fmtPct(sc.bayesian_wr)}</span>
      <span style={{ fontSize: 10, fontVariantNumeric: 'tabular-nums', color: sc.win_rate > 0.5 ? C.run : C.warn, textAlign: 'right' }}>{fmtPct(sc.win_rate)}</span>
      <span style={{ fontSize: 10, fontVariantNumeric: 'tabular-nums', color: sc.expectancy >= 0 ? C.run : C.err, textAlign: 'right' }}>{`₹${sc.expectancy.toFixed(0)}`}</span>
      <span style={{ fontSize: 10, fontVariantNumeric: 'tabular-nums', color: sc.total_pnl >= 0 ? C.run : C.err, textAlign: 'right' }}>{`₹${sc.total_pnl.toFixed(0)}`}</span>
      <span style={{ fontSize: 10, fontVariantNumeric: 'tabular-nums', color: C.run, textAlign: 'right' }}>{`₹${sc.avg_win.toFixed(0)}`}</span>
      <span style={{ fontSize: 10, fontVariantNumeric: 'tabular-nums', color: C.err, textAlign: 'right' }}>{`₹${Math.abs(sc.avg_loss).toFixed(0)}`}</span>
      {/* P&L mini-bar */}
      <div style={{ paddingLeft: 8 }}>
        <div style={{ height: 4, background: '#111', borderRadius: 2, overflow: 'hidden' }}>
          <div style={{ height: '100%', width: `${Math.min(100, Math.abs(sc.total_pnl) / 50_000 * 100).toFixed(1)}%`, background: sc.total_pnl >= 0 ? C.run : C.err, borderRadius: 2 }} />
        </div>
      </div>
    </div>
  )
}

function ScoreboardView({ scorecards, learnerParams, agents }: { scorecards: Scorecard[]; learnerParams: LearnerParams[]; agents: AgentState[] }) {
  const lpMap: Record<string, LearnerParams> = {}
  for (const lp of learnerParams) lpMap[lp.strategy_id] = lp

  const sorted = [...scorecards].sort((a, b) => b.total_pnl - a.total_pnl)
  const totalPnl  = sorted.reduce((s, r) => s + r.total_pnl, 0)
  const totalTrades = sorted.reduce((s, r) => s + r.total_trades, 0)
  const avgBayesWR = sorted.length > 0 ? sorted.reduce((s, r) => s + r.bayesian_wr, 0) / sorted.length : 0

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden' }}>
      {/* Summary strip */}
      <div style={{ display: 'flex', gap: 20, padding: '10px 16px', background: '#080808', borderBottom: `1px solid ${C.border}`, flexShrink: 0 }}>
        <Chip label="TOTAL P&L" value={`₹${totalPnl.toFixed(0)}`} color={totalPnl >= 0 ? C.run : C.err} />
        <Chip label="TOTAL TRADES" value={String(totalTrades)} />
        <Chip label="AVG BAYESIAN WR" value={fmtPct(avgBayesWR)} color={avgBayesWR > 0.5 ? C.run : C.warn} />
        <Chip label="ACTIVE STRATEGIES" value={String(sorted.length)} />
      </div>
      {/* Table header */}
      <div style={{ display: 'grid', gridTemplateColumns: SCOLS, gap: 0, padding: '5px 12px', background: '#080808', borderBottom: `1px solid #1A1A1A`, flexShrink: 0 }}>
        {['STRATEGY', 'DESCRIPTION', 'TRADES', 'BAY WR', 'WIN RT', 'EXPECT', 'P&L', 'AVG WIN', 'AVG LOSS', ''].map(h => (
          <span key={h} style={{ fontSize: 7, color: '#2A2A2A', letterSpacing: '.07em', textAlign: h === '' ? undefined : 'right' }}>{h === 'STRATEGY' || h === 'DESCRIPTION' ? <span style={{ textAlign: 'left', display: 'block' }}>{h}</span> : h}</span>
        ))}
      </div>
      {/* Rows */}
      <div style={{ flex: 1, overflowY: 'auto' }}>
        {sorted.length === 0
          ? <div style={{ textAlign: 'center', color: '#222', fontSize: 10, padding: 40 }}>No strategy data yet — signals accumulate during live session</div>
          : sorted.map(sc => <ScoreboardRow key={sc.strategy_id} sc={sc} lp={lpMap[sc.strategy_id]} agents={agents} />)
        }
      </div>
      {/* Learner Params section */}
      {learnerParams.length > 0 && (
        <div style={{ borderTop: `1px solid ${C.border}`, flexShrink: 0 }}>
          <div style={{ padding: '8px 12px', fontSize: 8, color: '#333', letterSpacing: '.08em', background: '#080808', borderBottom: `1px solid ${C.border}` }}>ADAPTIVE LEARNER PARAMS</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(360px,1fr))', gap: 1, background: C.border, maxHeight: 200, overflowY: 'auto' }}>
            {learnerParams.map(lp => (
              <div key={lp.strategy_id} style={{ background: '#080808', padding: '8px 12px', display: 'grid', gridTemplateColumns: '80px 1fr', gap: 8 }}>
                <div>
                  <div style={{ fontSize: 9, fontWeight: 700, color: '#D0D0D0' }}>{lp.strategy_id}</div>
                  <div style={{ fontSize: 7, color: '#333' }}>n={lp.n_trades}</div>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5,1fr)', gap: 8 }}>
                  <Chip label="CONF≥" value={lp.min_confidence.toFixed(2)} color={C.warn} />
                  <Chip label="KELLY" value={lp.kelly_fraction.toFixed(2)} color={C.teal} />
                  <Chip label="SL ×" value={lp.sl_multiplier.toFixed(2)} />
                  <Chip label="TGT ×" value={lp.target_multiplier.toFixed(2)} color={C.run} />
                  <Chip label="BAYES" value={fmtPct(lp.bayes_wr)} color={lp.bayes_wr > 0.5 ? C.run : C.warn} />
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
// Decisions / Pipeline Tab
// ─────────────────────────────────────────────────────────────────────────────
const DCOLS = '52px 18px 70px 80px 1fr 64px 60px 64px'

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
      <span style={{ fontSize: 9, color: '#888' }}>{symName(d.instrument_token)}</span>
      <span style={{ fontSize: 8, color: '#555', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {approved
          ? `${d.side ?? '?'} conf:${(d.confidence ?? 0).toFixed(2)} [${d.regime ?? '?'}] ${d.trigger_rule ?? ''}`
          : d.reason ?? 'rejected'}
      </span>
      <span style={{ fontSize: 8, color: d.fill_price ? C.teal : '#333', fontVariantNumeric: 'tabular-nums', textAlign: 'right' }}>
        {d.fill_price ? `₹${d.fill_price.toFixed(1)}` : '—'}
      </span>
      <span style={{ fontSize: 8, color: d.trade_pnl != null ? (d.trade_pnl >= 0 ? C.run : C.err) : '#333', fontVariantNumeric: 'tabular-nums', textAlign: 'right' }}>
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
  const approvedFiltered = filtered.filter(d => d.approved === 1)
  const rejectedFiltered = filtered.filter(d => d.approved === 0)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden', gap: 0 }}>
      {/* Funnel */}
      <div style={{ padding: '10px 12px', borderBottom: `1px solid ${C.border}`, flexShrink: 0 }}>
        <PipelineFunnel agents={agents} decisions={decisions} />
      </div>

      {/* Filter bar */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '7px 12px', borderBottom: `1px solid ${C.border}`, background: '#080808', flexShrink: 0 }}>
        <span style={{ fontSize: 8, color: '#333', letterSpacing: '.07em' }}>STRATEGY</span>
        {['ALL', ...strategies].map(s => (
          <button key={s} onClick={() => setStratFilter(s)} style={{
            fontSize: 8, padding: '2px 8px', borderRadius: 3, border: `1px solid ${stratFilter === s ? C.warn : '#1A1A1A'}`,
            background: stratFilter === s ? '#F7931E11' : 'transparent', color: stratFilter === s ? C.warn : '#444',
            cursor: 'pointer', fontWeight: stratFilter === s ? 700 : 400, letterSpacing: '.05em',
          }}>{s}</button>
        ))}
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 16 }}>
          <span style={{ fontSize: 8, color: C.run }}>{approvedFiltered.length} approved</span>
          <span style={{ fontSize: 8, color: C.err }}>{rejectedFiltered.length} rejected</span>
          <span style={{ fontSize: 8, color: filtered.length > 0 ? C.teal : '#333' }}>
            {filtered.length > 0 ? `${(approvedFiltered.length / filtered.length * 100).toFixed(0)}% pass rate` : '—'}
          </span>
        </div>
      </div>

      {/* Header */}
      <div style={{ display: 'grid', gridTemplateColumns: DCOLS, gap: 8, padding: '5px 12px', borderBottom: `1px solid #1A1A1A`, background: '#080808', flexShrink: 0 }}>
        {['TIME', '', 'STRATEGY', 'SYMBOL', 'DETAILS', 'FILL', 'P&L', 'STATUS'].map(h => (
          <span key={h} style={{ fontSize: 7, color: '#2A2A2A', letterSpacing: '.07em' }}>{h}</span>
        ))}
      </div>

      {/* Rows */}
      <div style={{ flex: 1, overflowY: 'auto' }}>
        {filtered.length === 0
          ? <div style={{ textAlign: 'center', color: '#2A2A2A', fontSize: 10, padding: 40 }}>No decisions recorded yet</div>
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
  'order.rejected': C.err, 'strategy.signal': C.amber, 'kill_switch.global_pause': C.err,
  'risk.kill_all': C.err, 'pnl.update': '#2A2A2A', 'regime.update': '#2A2A2A',
  'ticks': '#1A1A1A', 'scorecard.update': '#3A3A3A',
}

function BroadcastTab({ events }: { events: EventRecord[] }) {
  const [pause, setPause] = useState(false)
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
      {/* Controls */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '7px 12px', borderBottom: `1px solid ${C.border}`, background: '#080808', flexShrink: 0 }}>
        <button onClick={() => setPause(p => !p)} style={{
          fontSize: 8, padding: '2px 10px', borderRadius: 3,
          border: `1px solid ${pause ? C.warn : '#1A1A1A'}`,
          background: pause ? '#F7931E11' : 'transparent',
          color: pause ? C.warn : '#444', cursor: 'pointer', fontWeight: 700,
        }}>{pause ? '▶ RESUME' : '⏸ PAUSE'}</button>
        <input value={search} onChange={e => setSearch(e.target.value)} placeholder="search topic / summary…"
          style={{ flex: 1, maxWidth: 200, fontSize: 9, background: '#0A0A0A', border: `1px solid ${C.border}`, borderRadius: 3, color: '#888', padding: '3px 8px', outline: 'none' }} />
        {['ALL', ...topics].slice(0, 8).map(t => (
          <button key={t} onClick={() => setTopicFilter(t)} style={{
            fontSize: 7, padding: '2px 7px', borderRadius: 3,
            border: `1px solid ${topicFilter === t ? C.amber : '#1A1A1A'}`,
            background: topicFilter === t ? '#F7931E0A' : 'transparent',
            color: topicFilter === t ? C.amber : '#333', cursor: 'pointer', letterSpacing: '.04em',
          }}>{t.toUpperCase()}</button>
        ))}
        <span style={{ marginLeft: 'auto', fontSize: 8, color: '#2A2A2A' }}>{filtered.length} events</span>
      </div>

      {/* Header */}
      <div style={{ display: 'grid', gridTemplateColumns: '58px 180px 1fr 56px', gap: 8, padding: '5px 12px', borderBottom: `1px solid #1A1A1A`, background: '#080808', flexShrink: 0 }}>
        {['TIME', 'TOPIC', 'SUMMARY', 'SEV'].map(h => (
          <span key={h} style={{ fontSize: 7, color: '#2A2A2A', letterSpacing: '.07em' }}>{h}</span>
        ))}
      </div>

      <div style={{ flex: 1, overflowY: 'auto' }}>
        {filtered.length === 0
          ? <div style={{ textAlign: 'center', color: '#2A2A2A', fontSize: 10, padding: 40 }}>No events — accumulate after startup</div>
          : filtered.map((e, i) => (
            <div key={i} className="row-in" style={{ display: 'grid', gridTemplateColumns: '58px 180px 1fr 56px', gap: 8, padding: '5px 12px', borderBottom: `1px solid #0D0D0D`, alignItems: 'baseline' }}>
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
// Inspector — Right rail
// ─────────────────────────────────────────────────────────────────────────────
function Section2({ label, labelColor, children }: { label: string; labelColor?: string; children: React.ReactNode }) {
  return (
    <div>
      <div style={{ fontSize: 8, color: labelColor ?? '#2A2A2A', letterSpacing: '.08em', fontWeight: 700, marginBottom: 5, borderBottom: `1px solid ${C.border}`, paddingBottom: 3 }}>{label}</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>{children}</div>
    </div>
  )
}

function Row2({ k, v, color }: { k: string; v: React.ReactNode; color?: string }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, padding: '1px 0' }}>
      <span style={{ color: '#2A2A2A', flexShrink: 0, fontSize: 8 }}>{k}</span>
      <span style={{ color: color ?? C.text, textAlign: 'right', wordBreak: 'break-all', fontSize: 9 }}>{v}</span>
    </div>
  )
}

function SignalLineageView({ lineage }: { lineage: SignalLineage }) {
  const approved = lineage.risk_approved === 1
  const checks = lineage.risk_checks ?? {}
  const checkEntries = Object.entries(checks)
  const passing = checkEntries.filter(([, v]) => v as boolean).length

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12, fontSize: 9 }}>
      <div style={{ fontWeight: 800, color: '#E0E0E0', fontSize: 10, letterSpacing: '.03em' }}>SIGNAL LINEAGE</div>

      <Section2 label="MARKET CONTEXT">
        <Row2 k="Symbol" v={symName(lineage.instrument_token)} />
        <Row2 k="Side" v={lineage.side ?? '—'} color={lineage.side === 'BUY' ? C.run : C.err} />
        <Row2 k="Regime" v={lineage.regime ?? '—'} />
        <Row2 k="India VIX" v={lineage.india_vix?.toFixed(2) ?? '—'} />
        <Row2 k="Regime Conf." v={(lineage.regime_confidence ?? 0).toFixed(2)} />
      </Section2>

      <Section2 label="STRATEGY SIGNAL">
        <Row2 k="Strategy" v={lineage.strategy_id ?? '—'} color={C.warn} />
        <Row2 k="Trigger" v={lineage.trigger_rule ?? '—'} />
        <Row2 k="Confidence" v={(lineage.confidence ?? 0).toFixed(3)} color={C.run} />
        <Row2 k="Generated" v={lineage.generated_at ? fmtTs(lineage.generated_at) : '—'} />
      </Section2>

      {lineage.indicators && Object.keys(lineage.indicators).length > 0 && (
        <Section2 label="INDICATORS">
          {Object.entries(lineage.indicators).map(([k, v]) => (
            <Row2 key={k} k={k} v={typeof v === 'number' ? v.toFixed(3) : String(v)} />
          ))}
        </Section2>
      )}

      <Section2 label={`RISK GATE (${passing}/${checkEntries.length}) ${approved ? '✓ APPROVED' : '✗ REJECTED'}`}
        labelColor={approved ? C.run : C.err}>
        {checkEntries.map(([k, v]) => (
          <div key={k} style={{ display: 'flex', gap: 6, alignItems: 'center', padding: '1px 0' }}>
            <span style={{ fontSize: 9, color: (v as boolean) ? C.run : C.err, minWidth: 10, fontWeight: 700 }}>{(v as boolean) ? '✓' : '✗'}</span>
            <span style={{ fontSize: 8, color: (v as boolean) ? '#3A3A3A' : '#666' }}>{k}</span>
          </div>
        ))}
        {lineage.risk_reason && <div style={{ fontSize: 8, color: C.err, marginTop: 4, padding: '4px 6px', background: '#1A0808', borderRadius: 3 }}>{lineage.risk_reason}</div>}
      </Section2>

      {lineage.fill_price && (
        <Section2 label="ORDER FILL">
          <Row2 k="Fill price" v={`₹${lineage.fill_price.toFixed(2)}`} color={C.teal} />
        </Section2>
      )}

      {lineage.trade_pnl != null && (
        <Section2 label="TRADE OUTCOME">
          <Row2 k="P&L" v={`${lineage.trade_pnl >= 0 ? '+' : ''}₹${lineage.trade_pnl.toFixed(0)}`}
            color={lineage.trade_pnl >= 0 ? C.run : C.err} />
          {lineage.trade_exit_reason && <Row2 k="Exit" v={lineage.trade_exit_reason} />}
          {lineage.trade_closed_at && <Row2 k="Closed" v={fmtTs(lineage.trade_closed_at)} />}
        </Section2>
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
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <Dot status={agent.status} size={8} />
        <span style={{ fontSize: 16, color: '#2A2A2A' }}>{AGENT_ICON[agent.agent_id] ?? '◯'}</span>
        <div>
          <div style={{ fontSize: 11, fontWeight: 800, color: '#E0E0E0' }}>{agent.agent_id}</div>
          <div style={{ fontSize: 8, color: '#3A3A3A' }}>{AGENT_DESC[agent.agent_id] ?? agent.description}</div>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, background: '#080808', borderRadius: 4, padding: '8px' }}>
        <Chip label="STATUS" value={agent.status.toUpperCase()} color={STATUS_C[agent.status]} />
        <Chip label="HEARTBEAT" value={fmtAge(agent.heartbeat_age_s)} color={ageC(agent.heartbeat_age_s)} />
        <Chip label="EVALS" value={fmtN(agent.eval_count)} />
        <Chip label="SIGNALS" value={fmtN(agent.signal_count)} />
        <Chip label="TYPE" value={agent.agent_type.toUpperCase()} />
        <Chip label="CONF≥" value={agent.confidence_threshold.toFixed(3)} color={C.warn} />
      </div>

      {agent.last_eval_ts ? (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, background: '#080808', borderRadius: 4, padding: '8px' }}>
          <Chip label="LAST EVAL" value={fmtTs(agent.last_eval_ts)} />
          {agent.last_signal_ts ? <Chip label="LAST SIGNAL" value={fmtTs(agent.last_signal_ts)} color={C.amber} /> : null}
        </div>
      ) : null}

      {agent.last_error && (
        <div style={{ fontSize: 8, color: C.err, background: '#1A0808', borderRadius: 3, padding: '6px 8px', wordBreak: 'break-all' }}>⚠ {agent.last_error}</div>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
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
  const AUD_C: Record<string, string> = {
    GLOBAL_PAUSE: C.err, GLOBAL_RESUME: C.run, BLOCK_SYMBOL: C.warn, UNBLOCK_SYMBOL: '#4CAF50',
    KILL_ALL: C.err,
  }
  return (
    <div>
      <div style={{ fontSize: 8, color: '#2A2A2A', letterSpacing: '.08em', marginBottom: 6, fontWeight: 700 }}>KILL SWITCH AUDIT</div>
      {entries.length === 0
        ? <span style={{ fontSize: 8, color: '#1E1E1E' }}>No events</span>
        : entries.map((e, i) => (
          <div key={i} style={{ fontSize: 8, display: 'grid', gridTemplateColumns: '52px 1fr', gap: 5, borderBottom: `1px solid #0D0D0D`, padding: '3px 0' }}>
            <span style={{ color: '#2A2A2A', fontVariantNumeric: 'tabular-nums' }}>{fmtTs(e.ts)}</span>
            <div>
              <span style={{ color: AUD_C[e.action] ?? '#444', fontWeight: 700, marginRight: 5 }}>{e.action}</span>
              <span style={{ color: '#333' }}>{e.detail}</span>
            </div>
          </div>
        ))
      }
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Page
// ─────────────────────────────────────────────────────────────────────────────
type Tab = 'matrix' | 'pipeline' | 'scoreboard' | 'broadcast'
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
  const [selected,      setSelected]     = useState<SelType | null>(null)
  const [lineage,       setLineage]      = useState<SignalLineage | null>(null)
  const [lineageLoading, setLineageLoading] = useState(false)

  const load = useCallback(async () => {
    const [a, r, au, ins, h, reg, port, sc, lp] = await Promise.allSettled([
      api.agents(), api.riskState(), api.agentAudit(100), api.instruments(),
      api.agentHealth(), api.regime(), api.portfolio(), api.scorecards(), api.learnerParams(),
    ])
    if (a.status === 'fulfilled')   setAgents(a.value)
    if (r.status === 'fulfilled')   setRisk(r.value)
    if (au.status === 'fulfilled')  setAudit(au.value)
    if (ins.status === 'fulfilled') setInstruments(ins.value.map(i => ({ symbol: i.symbol, token: i.token })))
    if (h.status === 'fulfilled')   setHealth(h.value)
    if (reg.status === 'fulfilled') setRegime(reg.value)
    if (port.status === 'fulfilled') setPortfolio(port.value)
    if (sc.status === 'fulfilled')  setScorecards(sc.value)
    if (lp.status === 'fulfilled')  setLearnerParams(lp.value)
  }, [])

  const loadDecisions = useCallback(async () => {
    const d = await api.decisions(100).catch(() => [])
    setDecisions(d)
  }, [])

  const loadEvents = useCallback(async () => {
    const e = await api.busEvents(300).catch(() => [])
    setEvents(e)
  }, [])

  useEffect(() => { load() }, [load])
  useEffect(() => { loadDecisions() }, [loadDecisions])
  useEffect(() => { if (tab === 'broadcast') loadEvents() }, [tab, loadEvents])

  useEffect(() => {
    const s = getSocket()
    const refresh = () => { load(); loadDecisions() }
    s.on('agent_status_changed', refresh)
    s.on('kill_switch_global_pause', refresh)
    s.on('order_approved', loadDecisions)
    s.on('trade_closed', loadDecisions)
    return () => {
      s.off('agent_status_changed', refresh)
      s.off('kill_switch_global_pause', refresh)
      s.off('order_approved', loadDecisions)
      s.off('trade_closed', loadDecisions)
    }
  }, [load, loadDecisions])

  useEffect(() => {
    const t = setInterval(() => { load(); loadDecisions(); if (tab === 'broadcast') loadEvents() }, 10_000)
    return () => clearInterval(t)
  }, [load, loadDecisions, loadEvents, tab])

  useEffect(() => {
    if (!selected || selected.kind !== 'signal') { setLineage(null); return }
    setLineageLoading(true)
    api.lineage(selected.signalId).then(l => { setLineage(l); setLineageLoading(false) }).catch(() => setLineageLoading(false))
  }, [selected])

  const globalPaused = riskState?.global_pause ?? false

  // Filter agents
  const filteredAgents = agents.filter(a => {
    if (filter === 'all') return true
    if (filter === 'strategy') return a.agent_type === 'strategy'
    if (filter === 'orchestrator') return a.agent_type === 'orchestrator'
    if (filter === 'risk') return a.agent_type === 'system'
    if (filter === 'execution') return a.agent_id === 'BROKER'
    return true
  })

  const systemAgents = filteredAgents.filter(a => a.agent_type === 'system' || a.agent_id === 'BROKER')
  const orchAgents   = filteredAgents.filter(a => a.agent_type === 'orchestrator')
  const stratAgents  = filteredAgents.filter(a => a.agent_type === 'strategy')

  const scMap: Record<string, Scorecard> = {}
  for (const sc of scorecards) scMap[sc.strategy_id] = sc
  const lpMap: Record<string, LearnerParams> = {}
  for (const lp of learnerParams) lpMap[lp.strategy_id] = lp

  const selectedAgent = selected?.kind === 'agent' ? agents.find(a => a.agent_id === selected.id) ?? null : null

  const TABS: Array<{ key: Tab; label: string }> = [
    { key: 'matrix',     label: 'MATRIX' },
    { key: 'pipeline',   label: 'PIPELINE' },
    { key: 'scoreboard', label: 'SCOREBOARD' },
    { key: 'broadcast',  label: 'BROADCAST' },
  ]

  return (
    <>
      <StyleTag />
      <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', gap: 8, padding: '10px 14px', background: C.bg, overflow: 'hidden' }}>

        {/* Command strip */}
        <CommandStrip health={health} regime={regime} portfolio={portfolio} globalPaused={globalPaused} decisions={decisions} />

        {/* Tab bar */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 0, background: C.panel, border: `1px solid ${C.border}`, borderRadius: 5, overflow: 'hidden', flexShrink: 0 }}>
          {TABS.map(({ key, label }) => (
            <button key={key} onClick={() => setTab(key)} style={{
              padding: '8px 22px', fontSize: 9, fontWeight: tab === key ? 800 : 500,
              letterSpacing: '.09em', background: 'transparent', border: 'none',
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
                  fontSize: 8, padding: '2px 8px', borderRadius: 3,
                  border: `1px solid ${filter === key ? C.warn : 'transparent'}`,
                  background: filter === key ? '#F7931E0A' : 'transparent',
                  color: filter === key ? C.warn : '#444', cursor: 'pointer',
                }}>{label}</button>
              ))}
            </div>
          )}
          <button onClick={() => { load(); loadDecisions(); if (tab === 'broadcast') loadEvents() }}
            style={{ padding: '8px 14px', fontSize: 9, color: '#3A3A3A', background: 'none', border: 'none', cursor: 'pointer', borderLeft: `1px solid ${C.border}` }}>
            ↺ REFRESH
          </button>
        </div>

        {/* Main 3-col */}
        <div style={{ flex: 1, minHeight: 0, display: 'grid', gridTemplateColumns: '200px 1fr auto', gap: 8 }}>

          {/* Left rail */}
          <div style={{ overflowY: 'auto' }}>
            <LeftRail agents={agents} filter={filter} onFilter={setFilter}
              riskState={riskState} instruments={instruments} onRefresh={load} globalPaused={globalPaused} />
          </div>

          {/* Center */}
          <div style={{ minHeight: 0, overflow: 'hidden', display: 'flex', flexDirection: 'column', background: C.panel, border: `1px solid ${C.border}`, borderRadius: 5 }}>

            {/* MATRIX */}
            {tab === 'matrix' && (
              <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 0 }}>
                {/* Pipeline funnel strip */}
                <div style={{ padding: '10px 12px', borderBottom: `1px solid ${C.border}`, flexShrink: 0 }}>
                  <PipelineFunnel agents={agents} decisions={decisions} />
                </div>
                <div style={{ padding: '12px', display: 'flex', flexDirection: 'column', gap: 14 }}>
                  {/* System + Execution agents */}
                  {systemAgents.length > 0 && (
                    <div>
                      <Label count={systemAgents.length}>SYSTEM + EXECUTION</Label>
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
                  {/* Orchestrator */}
                  {orchAgents.length > 0 && (
                    <div>
                      <Label count={orchAgents.length}>ORCHESTRATOR</Label>
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
                      <Label count={stratAgents.length}>STRATEGIES</Label>
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(200px,1fr))', gap: 7 }}>
                        {stratAgents.map(a => (
                          <StrategyCard key={a.agent_id} agent={a} scorecard={scMap[a.agent_id]} learner={lpMap[a.agent_id]}
                            onRefresh={load}
                            onClick={() => setSelected(sel => sel?.kind === 'agent' && sel.id === a.agent_id ? null : { kind: 'agent', id: a.agent_id })}
                            selected={selected?.kind === 'agent' && selected.id === a.agent_id} />
                        ))}
                      </div>
                    </div>
                  )}
                  {filteredAgents.length === 0 && (
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column', gap: 8, color: '#222', padding: 80 }}>
                      <span style={{ fontSize: 28, opacity: .3 }}>◯</span>
                      <span style={{ fontSize: 10, letterSpacing: '.08em' }}>NO AGENTS REGISTERED</span>
                      <span style={{ fontSize: 8, color: '#1A1A1A' }}>Start the backend server to register agents</span>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* PIPELINE */}
            {tab === 'pipeline' && (
              <PipelineTab agents={agents} decisions={decisions}
                selectedId={selected?.kind === 'signal' ? selected.signalId : null}
                onSelect={sid => setSelected(sel => sel?.kind === 'signal' && sel.signalId === sid ? null : { kind: 'signal', signalId: sid })} />
            )}

            {/* SCOREBOARD */}
            {tab === 'scoreboard' && (
              <ScoreboardView scorecards={scorecards} learnerParams={learnerParams} agents={agents} />
            )}

            {/* BROADCAST */}
            {tab === 'broadcast' && <BroadcastTab events={events} />}
          </div>

          {/* Right inspector / audit */}
          <div style={{ width: 272, display: 'flex', flexDirection: 'column', background: C.panel, border: `1px solid ${C.border}`, borderRadius: 5, overflow: 'hidden', flexShrink: 0 }}>
            {selected ? (
              <>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 12px', borderBottom: `1px solid ${C.border}`, flexShrink: 0 }}>
                  <span style={{ fontSize: 8, color: '#333', letterSpacing: '.09em', fontWeight: 700 }}>
                    {selected.kind === 'agent' ? 'AGENT DETAIL' : 'SIGNAL LINEAGE'}
                  </span>
                  <button onClick={() => setSelected(null)} style={{ background: 'none', border: 'none', color: '#444', cursor: 'pointer', fontSize: 12 }}>✕</button>
                </div>
                <div style={{ flex: 1, overflowY: 'auto', padding: '12px' }}>
                  {selected.kind === 'agent' && selectedAgent && (
                    <AgentInspector agent={selectedAgent} onRefresh={load} />
                  )}
                  {selected.kind === 'signal' && (
                    lineageLoading
                      ? <div style={{ color: '#2A2A2A', fontSize: 9, textAlign: 'center', padding: 24 }}>Loading lineage…</div>
                      : lineage
                        ? <SignalLineageView lineage={lineage} />
                        : <div style={{ color: '#2A2A2A', fontSize: 9, textAlign: 'center', padding: 24 }}>Lineage not found for this signal</div>
                  )}
                </div>
              </>
            ) : (
              <div style={{ padding: '8px 12px', borderBottom: `1px solid ${C.border}`, flexShrink: 0 }}>
                <span style={{ fontSize: 8, color: '#333', letterSpacing: '.09em', fontWeight: 700 }}>SELECT AGENT OR SIGNAL</span>
              </div>
            )}
            {/* Audit log — always visible at bottom */}
            <div style={{ borderTop: `1px solid ${C.border}`, padding: '10px 12px', maxHeight: 240, overflowY: 'auto', flexShrink: 0 }}>
              <AuditLog entries={audit} />
            </div>
          </div>

        </div>
      </div>
    </>
  )
}
