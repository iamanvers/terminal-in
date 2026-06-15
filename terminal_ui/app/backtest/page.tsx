'use client'
import { THEME } from '@/lib/theme'
/**
 * BACKTEST MODULE (PRD P2) — replay real daily OHLCV through the live decision
 * core (regime → lenses → EV → persistence → TradePlanner → gate-lite →
 * next-open fills) and report it. Strictly real data; no lookahead (a signal on
 * bar t fills at t+1 open). v3 agentic replay: the JUDGE toggle runs the real
 * Ollama planner in the loop (sampled) or the deterministic degraded bar, with a
 * per-judge comparison. Long-only cash segment.
 *
 * This is the keystone eval surface: every strategy claim, and later the
 * LightGBM edge model + the M6 world-model, is gated by walk-forward here.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, BacktestResult, BacktestStat, BacktestProgress } from '@/lib/api'
import { usePersistedState } from '@/hooks/usePersistedState'

const C = THEME

const HORIZONS = [
  { label: '1Y', days: 365 },
  { label: '2Y', days: 730 },
  { label: '5Y', days: 1825 },
  { label: '10Y', days: 3650 },
]

const REGIME_C: Record<string, string> = {
  strong_bull: C.green, bull: C.teal, sideways: C.steel,
  bear: '#E8833A', strong_bear: C.red, high_vol: C.warn,
}

function pnlColor(v: number | undefined) {
  if (v == null || v === 0) return C.muted
  return v > 0 ? C.green : C.red
}
function fmtINR(v: number | undefined) {
  if (v == null) return '—'
  const a = Math.abs(v)
  if (a >= 1e7) return `${v < 0 ? '-' : ''}₹${(a / 1e7).toFixed(2)}Cr`
  if (a >= 1e5) return `${v < 0 ? '-' : ''}₹${(a / 1e5).toFixed(2)}L`
  if (a >= 1e3) return `${v < 0 ? '-' : ''}₹${(a / 1e3).toFixed(1)}k`
  return `${v < 0 ? '-' : ''}₹${a.toFixed(0)}`
}

// ── Equity curve + underwater drawdown band (standard backtest viz) ───────────
function EquityCurve({ data, capital }: { data: { date: string; equity: number }[]; capital: number }) {
  if (data.length < 2) return <div style={{ height: 230, display: 'flex', alignItems: 'center', justifyContent: 'center', color: C.dim, fontSize: 10.5 }}>Run a backtest to see the equity curve.</div>
  const w = 1000, eqH = 168, ddH = 64, gap = 6, pad = 4
  const eqs = data.map(d => d.equity)
  // running drawdown from peak (<=0)
  let peak = -Infinity
  const dd = eqs.map(v => { peak = Math.max(peak, v); return peak > 0 ? v / peak - 1 : 0 })
  const minDD = Math.min(...dd, -1e-9)
  const min = Math.min(...eqs, capital), max = Math.max(...eqs, capital)
  const range = max - min || 1
  const x = (i: number) => (i / (data.length - 1)) * w
  const yE = (v: number) => pad + (1 - (v - min) / range) * (eqH - 2 * pad)
  const yD = (v: number) => eqH + gap + (v / (minDD || -1)) * (ddH - pad)
  const line = data.map((d, i) => `${x(i)},${yE(d.equity)}`).join(' ')
  const area = `0,${yE(min)} ${line} ${w},${yE(min)}`
  const ddArea = `0,${eqH + gap} ${dd.map((v, i) => `${x(i)},${yD(v)}`).join(' ')} ${w},${eqH + gap}`
  const baseY = yE(capital)
  const up = eqs[eqs.length - 1] >= capital
  const col = up ? C.green : C.red
  const H = eqH + gap + ddH
  return (
    <svg width="100%" height={H} viewBox={`0 0 ${w} ${H}`} preserveAspectRatio="none" style={{ display: 'block' }}>
      <defs>
        <linearGradient id="eqfill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={col} stopOpacity="0.20" />
          <stop offset="100%" stopColor={col} stopOpacity="0" />
        </linearGradient>
      </defs>
      <line x1="0" y1={baseY} x2={w} y2={baseY} stroke={C.border2} strokeWidth={1} strokeDasharray="4 4" vectorEffect="non-scaling-stroke" />
      <polygon points={area} fill="url(#eqfill)" />
      <polyline points={line} fill="none" stroke={col} strokeWidth={1.8} vectorEffect="non-scaling-stroke" />
      {/* underwater drawdown */}
      <polygon points={ddArea} fill="#F2495C26" />
      <polyline points={dd.map((v, i) => `${x(i)},${yD(v)}`).join(' ')} fill="none" stroke={C.red} strokeWidth={1} vectorEffect="non-scaling-stroke" />
    </svg>
  )
}

// ── Diverging horizontal-bar attribution (losses left, profits right) ─────────
function HBarAttribution({ title, rows, colorFor }: {
  title: string; rows: [string, BacktestStat][]; colorFor?: (k: string) => string
}) {
  const ordered = rows.filter(([, s]) => s.n > 0).sort((a, b) => (b[1].total_pnl ?? 0) - (a[1].total_pnl ?? 0))
  const maxAbs = Math.max(1, ...ordered.map(([, s]) => Math.abs(s.total_pnl ?? 0)))
  return (
    <div className="panel" style={{ minHeight: 0, display: 'flex', flexDirection: 'column' }}>
      <div className="panel-header">{title}</div>
      <div className="panel-body" style={{ flex: 1, minHeight: 0, overflow: 'auto', padding: '8px 10px', display: 'flex', flexDirection: 'column', gap: 7 }}>
        {ordered.length === 0 ? <div style={{ padding: 16, textAlign: 'center', fontSize: 10, color: C.muted }}>No closed trades.</div> :
          ordered.map(([k, s]) => {
            const pnl = s.total_pnl ?? 0
            const frac = Math.abs(pnl) / maxAbs
            const col = colorFor ? colorFor(k) : (pnl >= 0 ? C.green : C.red)
            return (
              <div key={k} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 10 }}>
                <span style={{ width: 78, flexShrink: 0, color: colorFor ? col : C.text, fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{k}</span>
                {/* diverging bar: center line, profit right / loss left */}
                <div style={{ flex: 1, position: 'relative', height: 14, background: C.card, borderRadius: 2 }}>
                  <div style={{ position: 'absolute', left: '50%', top: 0, bottom: 0, width: 1, background: C.border2 }} />
                  <div style={{ position: 'absolute', top: 2, bottom: 2, borderRadius: 2,
                    background: pnl >= 0 ? C.green : C.red,
                    left: pnl >= 0 ? '50%' : `${50 - frac * 50}%`, width: `${frac * 50}%` }} />
                </div>
                <span style={{ width: 56, flexShrink: 0, textAlign: 'right', color: pnlColor(pnl), fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>{fmtINR(pnl)}</span>
                <span style={{ width: 56, flexShrink: 0, textAlign: 'right', color: C.muted, fontVariantNumeric: 'tabular-nums' }}>{s.n}t·{((s.win_rate ?? 0) * 100).toFixed(0)}%</span>
              </div>
            )
          })}
      </div>
    </div>
  )
}

// ── Walk-forward by year (vertical green/red bars) ────────────────────────────
function YearBars({ rows }: { rows: [string, BacktestStat][] }) {
  const maxAbs = Math.max(1, ...rows.map(([, s]) => Math.abs(s.total_pnl ?? 0)))
  return (
    <div className="panel" style={{ minHeight: 0, display: 'flex', flexDirection: 'column' }}>
      <div className="panel-header">WALK-FORWARD · BY YEAR</div>
      <div className="panel-body" style={{ flex: 1, minHeight: 0, padding: '10px 12px', display: 'flex', alignItems: 'flex-end', gap: 8, overflow: 'auto' }}>
        {rows.length === 0 ? <div style={{ margin: 'auto', fontSize: 10, color: C.muted }}>No closed trades.</div> :
          rows.map(([y, s]) => {
            const pnl = s.total_pnl ?? 0
            const frac = Math.abs(pnl) / maxAbs
            return (
              <div key={y} style={{ flex: 1, minWidth: 34, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 3 }}>
                <span style={{ fontSize: 8.5, color: pnlColor(pnl), fontWeight: 600 }}>{fmtINR(pnl)}</span>
                <div style={{ height: 70, width: '70%', display: 'flex', flexDirection: 'column', justifyContent: 'flex-end' }}>
                  <div style={{ height: `${Math.max(3, frac * 100)}%`, background: pnl >= 0 ? C.green : C.red, borderRadius: '2px 2px 0 0', opacity: 0.85 }} />
                </div>
                <span style={{ fontSize: 9, color: C.text, fontWeight: 600 }}>{y}</span>
                <span style={{ fontSize: 8, color: C.muted }}>{s.n}t·{((s.win_rate ?? 0) * 100).toFixed(0)}%</span>
              </div>
            )
          })}
      </div>
    </div>
  )
}

// ── Regime exposure (how much of the window was spent in each regime) ─────────
function RegimeExposure({ regimeDays, colorFor }: { regimeDays: Record<string, number>; colorFor: (k: string) => string }) {
  const entries = Object.entries(regimeDays).sort((a, b) => b[1] - a[1])
  const total = entries.reduce((s, [, n]) => s + n, 0) || 1
  return (
    <div className="panel" style={{ flexShrink: 0, height: 'auto' }}>
      <div className="panel-header">REGIME EXPOSURE <span style={{ marginLeft: 'auto', color: C.dim, fontWeight: 400, fontSize: 9.5 }}>{total} trading days</span></div>
      <div className="panel-body" style={{ padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 8 }}>
        <div style={{ display: 'flex', height: 16, borderRadius: 3, overflow: 'hidden', border: `1px solid ${C.border}` }}>
          {entries.map(([k, n]) => <div key={k} title={`${k}: ${n}d (${(n / total * 100).toFixed(0)}%)`} style={{ width: `${n / total * 100}%`, background: colorFor(k) }} />)}
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 14px' }}>
          {entries.map(([k, n]) => (
            <span key={k} style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 9.5 }}>
              <span style={{ width: 8, height: 8, borderRadius: 2, background: colorFor(k) }} />
              <span style={{ color: C.sub }}>{k}</span>
              <span style={{ color: C.muted, fontVariantNumeric: 'tabular-nums' }}>{(n / total * 100).toFixed(0)}%</span>
            </span>
          ))}
        </div>
      </div>
    </div>
  )
}

// ── Judge comparison: LLM planner vs the deterministic degraded bar ───────────
// The v3 headline — did putting the real LLM judge in the loop beat the bar?
function JudgeCompare({ perJudge, planner }: {
  perJudge: Record<string, BacktestStat>; planner?: { llm_batches: number; degraded_batches: number; ollama_available: boolean }
}) {
  const llm = perJudge.llm, deg = perJudge.degraded
  if (!llm || !deg || (llm.n ?? 0) === 0) return null   // only meaningful on an LLM run
  const cols: [string, BacktestStat, string][] = [
    ['LLM JUDGE', llm, C.teal],
    ['DEGRADED BAR', deg, C.steel],
  ]
  const llmWR = llm.win_rate ?? 0, degWR = deg.win_rate ?? 0
  const llmAvg = llm.avg_pnl ?? 0, degAvg = deg.avg_pnl ?? 0
  const edge = llmAvg - degAvg
  return (
    <div className="panel" style={{ flexShrink: 0, height: 'auto', borderColor: C.teal + '55' }}>
      <div className="panel-header" style={{ color: C.teal }}>JUDGE COMPARISON · LLM vs DEGRADED
        <span style={{ marginLeft: 'auto', color: C.dim, fontWeight: 400, fontSize: 9.5 }}>
          {planner ? `${planner.llm_batches} batches LLM-judged · ${planner.degraded_batches} degraded` : ''}
        </span>
      </div>
      <div className="panel-body" style={{ padding: '12px 14px', display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>
        {cols.map(([label, s, col]) => (
          <div key={label} style={{ display: 'flex', flexDirection: 'column', gap: 6, padding: '8px 12px', background: C.card, borderRadius: 4, borderLeft: `2px solid ${col}` }}>
            <span style={{ fontSize: 9, color: col, letterSpacing: '.07em', fontWeight: 700 }}>{label}</span>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10.5 }}><span style={{ color: C.muted }}>trades</span><span style={{ color: C.text, fontVariantNumeric: 'tabular-nums' }}>{s.n}</span></div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10.5 }}><span style={{ color: C.muted }}>win rate</span><span style={{ color: (s.win_rate ?? 0) >= 0.5 ? C.green : C.sub, fontVariantNumeric: 'tabular-nums' }}>{((s.win_rate ?? 0) * 100).toFixed(0)}%</span></div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10.5 }}><span style={{ color: C.muted }}>avg trade</span><span style={{ color: pnlColor(s.avg_pnl), fontVariantNumeric: 'tabular-nums' }}>{fmtINR(s.avg_pnl)}</span></div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10.5 }}><span style={{ color: C.muted }}>total P&L</span><span style={{ color: pnlColor(s.total_pnl), fontVariantNumeric: 'tabular-nums', fontWeight: 600 }}>{fmtINR(s.total_pnl)}</span></div>
          </div>
        ))}
        {/* verdict */}
        <div style={{ display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: 6, padding: '8px 12px' }}>
          <span style={{ fontSize: 9, color: C.dim, letterSpacing: '.07em', fontWeight: 700 }}>LLM EDGE (avg trade)</span>
          <span style={{ fontSize: 22, fontWeight: 700, color: edge >= 0 ? C.green : C.red, fontVariantNumeric: 'tabular-nums' }}>{edge >= 0 ? '+' : ''}{fmtINR(edge)}</span>
          <span style={{ fontSize: 9.5, color: C.muted, lineHeight: 1.5 }}>
            {edge >= 0
              ? `the LLM judge's picks averaged ${fmtINR(Math.abs(edge))} more per trade (${(llmWR * 100).toFixed(0)}% vs ${(degWR * 100).toFixed(0)}% WR)`
              : `the degraded bar beat the LLM here by ${fmtINR(Math.abs(edge))}/trade — sample is small, not conclusive`}
          </span>
        </div>
      </div>
    </div>
  )
}

function Metric({ label, value, color, sub }: { label: string; value: string; color: string; sub?: string }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <span style={{ fontSize: 9, color: C.dim, letterSpacing: '.07em' }}>{label}</span>
      <span style={{ fontSize: 18, fontWeight: 700, color, fontVariantNumeric: 'tabular-nums' }}>{value}</span>
      {sub && <span style={{ fontSize: 9, color: C.muted }}>{sub}</span>}
    </div>
  )
}

export default function BacktestPage() {
  const [result, setResult]   = useState<BacktestResult | null>(null)
  const [active, setActive]   = useState(false)
  const [error, setError]     = useState<string | null>(null)
  const [days, setDays]       = usePersistedState('tin.backtest.days', 730)
  const [planner, setPlanner] = usePersistedState<'degraded' | 'llm'>('tin.backtest.planner', 'degraded')
  const [startedMs, setStarted] = useState<number | null>(null)
  const [progress, setProgress] = useState<BacktestProgress | null>(null)
  const [cancelling, setCancelling] = useState(false)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const loadLatest = useCallback(async () => {
    try {
      const r = await api.backtestLatest()
      if (r.available) setResult(r as BacktestResult)
    } catch { /* backend warming */ }
  }, [])

  const poll = useCallback(async () => {
    try {
      const s = await api.backtestStatus()
      setActive(s.active)
      setError(s.error)
      setProgress(s.progress)
      if (s.result) setResult(s.result)
      if (!s.active) {
        setCancelling(false)
        if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
      }
    } catch { /* ignore */ }
  }, [])

  async function cancel() {
    setCancelling(true)
    try { await api.backtestCancel() } catch { /* ignore */ }
  }

  useEffect(() => { loadLatest(); poll() }, [loadLatest, poll])
  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current) }, [])
  // keep polling whenever a run is in flight (covers loading the page mid-run)
  useEffect(() => {
    if (active && !pollRef.current) pollRef.current = setInterval(poll, 2000)
  }, [active, poll])

  async function run() {
    setError(null); setActive(true); setStarted(Date.now()); setProgress(null); setCancelling(false)
    try {
      const res = await api.backtestRun(days, planner)
      if (!res.ok) { setError(res.error ?? 'failed to start'); setActive(false); return }
      if (pollRef.current) clearInterval(pollRef.current)
      pollRef.current = setInterval(poll, 2500)
    } catch { setError('network error'); setActive(false) }
  }

  const elapsed = active && startedMs ? Math.round((Date.now() - startedMs) / 1000) : null
  const r = result
  const lensRows = useMemo(() => Object.entries(r?.per_lens ?? {}), [r])
  const regimeRows = useMemo(() => Object.entries(r?.per_regime ?? {}), [r])
  const wfRows = useMemo(() => Object.entries(r?.walk_forward_years ?? {}).sort(), [r])

  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', gap: 8, padding: '10px 14px', background: 'transparent', overflow: 'hidden' }}>

      {/* Header strip */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, background: C.panel, border: `1px solid ${C.border}`, borderRadius: 5, padding: '10px 14px', flexShrink: 0 }}>
        <div>
          <div className="t-display" style={{ fontSize: 16 }}>Walk-Forward Backtest</div>
          <div className="t-prose" style={{ fontSize: 11.5, marginTop: 2 }}>
            Replays real daily OHLCV through the live decision core — no lookahead, no synthetic data. The keystone eval gate.
          </div>
        </div>
        <div style={{ flex: 1 }} />
        {/* horizon */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 3, alignItems: 'flex-start' }}>
          <span style={{ fontSize: 8, color: C.dim, letterSpacing: '.12em', fontWeight: 700 }}>HORIZON</span>
          <div style={{ display: 'flex', gap: 3, border: `1px solid ${C.border}`, borderRadius: 4, overflow: 'hidden' }}>
            {HORIZONS.map(hz => (
              <button key={hz.days} onClick={() => setDays(hz.days)} disabled={active}
                style={{
                  fontSize: 10, fontWeight: 700, letterSpacing: '.04em', padding: '5px 11px', border: 'none', cursor: active ? 'default' : 'pointer',
                  background: days === hz.days ? C.accent : 'transparent', color: days === hz.days ? C.onAccent : C.sub,
                }}>{hz.label}</button>
            ))}
          </div>
        </div>
        {/* judge: deterministic degraded bar vs the real LLM planner in the loop */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 3, alignItems: 'flex-start' }}>
          <span style={{ fontSize: 8, color: C.dim, letterSpacing: '.12em', fontWeight: 700 }}>JUDGE</span>
          <div style={{ display: 'flex', gap: 3, border: `1px solid ${C.border}`, borderRadius: 4, overflow: 'hidden' }}>
            {([['degraded', 'DEGRADED'], ['llm', 'LLM JUDGE']] as const).map(([k, label]) => (
              <button key={k} onClick={() => setPlanner(k)} disabled={active}
                title={k === 'llm'
                  ? 'Put the real Ollama planner in the loop (sampled — slower)'
                  : 'Deterministic planner bar (fast, reproducible)'}
                style={{
                  fontSize: 10, fontWeight: 700, letterSpacing: '.04em', padding: '5px 11px', border: 'none', cursor: active ? 'default' : 'pointer',
                  background: planner === k ? (k === 'llm' ? C.teal : C.accent) : 'transparent',
                  color: planner === k ? C.onAccent : C.sub,
                }}>{label}</button>
            ))}
          </div>
        </div>
        <button className="btn btn--primary" onClick={run} disabled={active}
          title="Run the backtest over the selected horizon">
          {active ? '◷ RUNNING…' : '▶ RUN BACKTEST'}
        </button>
        {active && (
          <button className="btn" onClick={cancel} disabled={cancelling}
            title="Abort the run and keep the partial result"
            style={{ borderColor: `${C.red}55`, color: C.red, background: '#1A0808' }}>
            {cancelling ? '◷ STOPPING…' : '✕ CANCEL'}
          </button>
        )}
      </div>
      {planner === 'llm' && !active && (
        <div style={{ fontSize: 10, color: days >= 1825 ? C.warn : C.teal, padding: '0 4px', flexShrink: 0 }}>
          ⚖ LLM judge in the loop — the real Ollama planner rules on each decision batch (~150 LLM calls, then the degraded bar). Each call is a few seconds on local hardware, so this is <strong>best on 1–2Y</strong>{days >= 1825 ? ' — a 5–10Y LLM run takes many minutes; use DEGRADED for full-horizon coverage, or cancel anytime.' : '. Cancel anytime.'}
        </div>
      )}

      {error && <div style={{ fontSize: 10.5, color: C.red, padding: '0 4px', flexShrink: 0 }}>⚠ {error}</div>}
      {active && (
        <div style={{ flexShrink: 0, display: 'flex', flexDirection: 'column', gap: 5, padding: '2px 4px 0' }}>
          <style dangerouslySetInnerHTML={{ __html: '@keyframes btbar { 0% { left: -42% } 100% { left: 100% } }' }} />
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: C.muted }}>
            <span>
              ◷ Replaying {days >= 365 ? `${(days / 365).toFixed(0)}y` : `${days}d`}
              {planner === 'llm' ? ' · LLM judge in the loop (this can take minutes)' : ''}
              {progress ? ` · day ${progress.day}/${progress.total}${progress.date ? ` (${progress.date})` : ''} · ${progress.trades} trades${planner === 'llm' ? ` · ${progress.llm_calls} LLM calls` : ''}` : '…'}
            </span>
            <span style={{ fontVariantNumeric: 'tabular-nums' }}>
              {progress ? `${Math.round(progress.frac * 100)}%` : ''}{elapsed != null ? ` · ${elapsed}s` : ''}
            </span>
          </div>
          <div style={{ position: 'relative', height: 3, background: C.card, borderRadius: 2, overflow: 'hidden' }}>
            {progress ? (
              <div style={{ position: 'absolute', top: 0, bottom: 0, left: 0, width: `${Math.max(1, progress.frac * 100)}%`,
                borderRadius: 2, background: planner === 'llm' ? C.teal : C.accent, transition: 'width .4s ease' }} />
            ) : (
              <div style={{ position: 'absolute', top: 0, bottom: 0, width: '42%', borderRadius: 2,
                background: planner === 'llm' ? C.teal : C.accent, animation: 'btbar 1.1s ease-in-out infinite' }} />
            )}
          </div>
        </div>
      )}

      {!r && !active && (
        <div className="panel" style={{ flex: 1 }}><div className="panel-body" style={{ padding: 40, textAlign: 'center', color: C.muted, fontSize: 11 }}>
          No backtest yet. Pick a horizon and run one — results persist across restarts.
        </div></div>
      )}

      {r && (
        <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', gap: 8 }}>
          {/* Summary metrics */}
          <div className="panel" style={{ flexShrink: 0, height: 'auto' }}>
            <div className="panel-header">RESULT
              <span style={{ marginLeft: 8, fontSize: 9, fontWeight: 700, letterSpacing: '.05em', padding: '1px 7px', borderRadius: 3,
                color: r.planner?.mode === 'llm' ? C.teal : C.steel,
                background: (r.planner?.mode === 'llm' ? C.teal : C.steel) + '1A',
                border: `1px solid ${(r.planner?.mode === 'llm' ? C.teal : C.steel)}40` }}>
                {r.planner?.mode === 'llm' ? '⚖ LLM JUDGE' : 'DEGRADED BAR'}
              </span>
              {r.planner?.cancelled && <span style={{ marginLeft: 6, fontSize: 9, fontWeight: 700, color: C.warn }} title="run was cancelled — this is the partial result up to the stop point">⚠ PARTIAL (cancelled)</span>}
              <span style={{ marginLeft: 'auto', color: C.muted, fontWeight: 400 }}>
                {r.engine} · {r.days >= 365 ? `${(r.days / 365).toFixed(0)}y` : `${r.days}d`} · {r.symbols_tested} symbols · {new Date(r.ts).toLocaleString('en-IN', { hour12: false, day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })}
              </span>
            </div>
            <div className="panel-body" style={{ padding: 14, display: 'grid', gridTemplateColumns: 'repeat(6,1fr)', gap: 12 }}>
              <Metric label="RETURN" value={`${r.return_pct > 0 ? '+' : ''}${r.return_pct}%`} color={pnlColor(r.return_pct)} sub={`${fmtINR(r.capital)} → ${fmtINR(r.final_equity)}`} />
              <Metric label="SHARPE" value={r.sharpe.toFixed(2)} color={r.sharpe >= 1 ? C.green : r.sharpe >= 0 ? C.sub : C.red} sub="annualised" />
              <Metric label="MAX DRAWDOWN" value={`${r.max_drawdown_pct}%`} color={r.max_drawdown_pct > -20 ? C.sub : C.red} sub="peak-to-trough" />
              <Metric label="WIN RATE" value={`${((r.trades.win_rate ?? 0) * 100).toFixed(0)}%`} color={(r.trades.win_rate ?? 0) >= 0.5 ? C.green : C.sub} sub={`${r.trades.n} trades`} />
              <Metric label="AVG TRADE" value={fmtINR(r.trades.avg_pnl)} color={pnlColor(r.trades.avg_pnl)} sub="net of costs" />
              <Metric label="TOTAL P&L" value={fmtINR(r.trades.total_pnl)} color={pnlColor(r.trades.total_pnl)} sub="realised" />
            </div>
          </div>

          {/* Judge comparison (LLM runs only) — the v3 headline */}
          {r.per_judge && <JudgeCompare perJudge={r.per_judge} planner={r.planner} />}

          {/* Main split — fills the remaining viewport; each side scrolls
              internally so the page itself never grows a long scrollbar.
              Left: equity + regime + attribution. Right: closed trades. */}
          <div style={{ flex: 1, minHeight: 0, display: 'grid', gridTemplateColumns: '1.45fr 1fr', gap: 8 }}>
            {/* LEFT column */}
            <div style={{ minHeight: 0, display: 'flex', flexDirection: 'column', gap: 8 }}>
              <div className="panel" style={{ flexShrink: 0, height: 'auto' }}>
                <div className="panel-header">EQUITY CURVE
                  <span style={{ marginLeft: 'auto', color: C.dim, fontWeight: 400, fontSize: 9.5 }}>
                    <span style={{ color: C.green }}>━</span> equity · <span style={{ color: C.border2 }}>┈</span> start capital · <span style={{ color: C.red }}>▔</span> drawdown
                  </span>
                </div>
                <div className="panel-body" style={{ padding: '10px 12px' }}>
                  <EquityCurve data={r.equity_curve ?? []} capital={r.capital} />
                </div>
              </div>

              <RegimeExposure regimeDays={r.regime_days ?? {}} colorFor={(k) => REGIME_C[k] ?? C.steel} />

              {/* Attribution: lens | regime | walk-forward — flexes + scrolls */}
              <div style={{ flex: 1, minHeight: 0, display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8 }}>
                <HBarAttribution title="PER-LENS" rows={lensRows} />
                <HBarAttribution title="PER-REGIME" rows={regimeRows} colorFor={(k) => REGIME_C[k] ?? C.steel} />
                <YearBars rows={wfRows} />
              </div>
            </div>

            {/* RIGHT column — closed trades (internal scroll) */}
            <div className="panel" style={{ minHeight: 0, display: 'flex', flexDirection: 'column' }}>
              <div className="panel-header" style={{ flexShrink: 0 }}>CLOSED TRADES <span style={{ marginLeft: 'auto', color: C.muted }}>{r.recent_trades?.length ?? 0} most recent</span></div>
              <div className="panel-body" style={{ flex: 1, minHeight: 0, overflow: 'auto' }}>
                <table>
                  <thead><tr>
                    <th>EXIT</th><th>SYMBOL</th><th>LENS</th><th>JUDGE</th><th>REGIME</th><th>ENTRY</th><th>EXIT</th><th>EV</th><th>WHY</th><th>P&L</th>
                  </tr></thead>
                  <tbody>
                    {(r.recent_trades ?? []).map((t, i) => (
                      <tr key={i}>
                        <td style={{ color: C.muted }}>{t.exit_date}</td>
                        <td style={{ color: C.text, fontWeight: 600 }}>{t.symbol}</td>
                        <td style={{ color: C.sub }}>{t.lens}</td>
                        <td style={{ color: t.judge === 'llm' ? C.teal : C.muted, fontSize: 9.5 }}>
                          {t.judge === 'llm' ? `⚖${t.size_factor != null && t.size_factor !== 1 ? ` ×${t.size_factor}` : ''}` : 'bar'}
                        </td>
                        <td style={{ color: REGIME_C[t.regime] ?? C.steel }}>{t.regime}</td>
                        <td style={{ color: C.sub, fontVariantNumeric: 'tabular-nums' }}>{t.entry}</td>
                        <td style={{ color: C.sub, fontVariantNumeric: 'tabular-nums' }}>{t.exit}</td>
                        <td style={{ color: C.muted, fontVariantNumeric: 'tabular-nums' }}>{t.ev?.toFixed(2)}</td>
                        <td style={{ color: t.exit_reason === 'target' ? C.green : C.red }}>{t.exit_reason}</td>
                        <td style={{ color: pnlColor(t.pnl), fontVariantNumeric: 'tabular-nums', fontWeight: 600 }}>{fmtINR(t.pnl)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          {/* Honesty footnote — scope of the v3 engine */}
          <div style={{ fontSize: 9.5, color: C.dim, padding: '0 4px', flexShrink: 0, lineHeight: 1.4 }}>
            v3 scope: orchestrator EV bar (≥1.2) + ≥2-scan persistence, then the <strong>real TradePlanner</strong> rules each batch — <em>LLM JUDGE</em> puts Ollama in the loop (sampled; degraded past budget / when offline), <em>DEGRADED</em> = deterministic bar (EV ≥ 1.5, conf ≥ 0.50, ≤3/scan). Long-only cash; heuristic-mode regime; NEWS excluded. Signals on bar <em>t</em> fill at <em>t+1</em> open.
          </div>
        </div>
      )}
    </div>
  )
}
