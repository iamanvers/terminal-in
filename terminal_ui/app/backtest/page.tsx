'use client'
import { THEME } from '@/lib/theme'
/**
 * BACKTEST MODULE (PRD P2) — replay real daily OHLCV through the deterministic
 * core of the live pipeline (regime → lenses → EV → persistence → planner bar →
 * gate-lite → next-open fills) and report it. Strictly real data; no lookahead
 * (a signal on bar t fills at t+1 open). Long-only cash segment; the LLM planner
 * is represented by its deterministic degraded bar (EV ≥ 1.2, conf ≥ 0.45).
 *
 * This is the keystone eval surface: every strategy claim, and later the
 * LightGBM edge model + the M6 world-model, is gated by walk-forward here.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, BacktestResult, BacktestStat } from '@/lib/api'

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

// ── Equity curve (area, with drawdown-from-peak shading) ──────────────────────
function EquityCurve({ data, capital }: { data: { date: string; equity: number }[]; capital: number }) {
  if (data.length < 2) return <div style={{ height: 200, display: 'flex', alignItems: 'center', justifyContent: 'center', color: C.dim, fontSize: 10.5 }}>Run a backtest to see the equity curve.</div>
  const w = 1000, h = 200, pad = 4
  const eqs = data.map(d => d.equity)
  const min = Math.min(...eqs, capital), max = Math.max(...eqs, capital)
  const range = max - min || 1
  const x = (i: number) => (i / (data.length - 1)) * w
  const y = (v: number) => h - pad - ((v - min) / range) * (h - 2 * pad)
  const line = data.map((d, i) => `${x(i)},${y(d.equity)}`)
  const area = `0,${h} ${line.join(' ')} ${w},${h}`
  const baseY = y(capital)
  const last = eqs[eqs.length - 1]
  const up = last >= capital
  const col = up ? C.green : C.red
  return (
    <svg width="100%" height={h} viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" style={{ display: 'block' }}>
      <defs>
        <linearGradient id="eqfill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={col} stopOpacity="0.22" />
          <stop offset="100%" stopColor={col} stopOpacity="0" />
        </linearGradient>
      </defs>
      {/* starting-capital baseline */}
      <line x1="0" y1={baseY} x2={w} y2={baseY} stroke={C.border} strokeWidth={1} strokeDasharray="4 4" vectorEffect="non-scaling-stroke" />
      <polygon points={area} fill="url(#eqfill)" />
      <polyline points={line.join(' ')} fill="none" stroke={col} strokeWidth={1.6} vectorEffect="non-scaling-stroke" />
    </svg>
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

// ── Attribution table (per-lens or per-regime) ───────────────────────────────
function StatTable({ title, rows, colorFor }: {
  title: string
  rows: [string, BacktestStat][]
  colorFor?: (k: string) => string
}) {
  const ordered = rows.filter(([, s]) => s.n > 0).sort((a, b) => (b[1].total_pnl ?? 0) - (a[1].total_pnl ?? 0))
  return (
    <div className="panel" style={{ minHeight: 0 }}>
      <div className="panel-header">{title}</div>
      <div className="panel-body" style={{ overflow: 'auto' }}>
        {ordered.length === 0 ? (
          <div style={{ padding: 18, textAlign: 'center', fontSize: 10, color: C.muted }}>No closed trades.</div>
        ) : (
          <table>
            <thead><tr><th>{title.includes('LENS') ? 'LENS' : 'REGIME'}</th><th>N</th><th>WIN%</th><th>AVG</th><th>TOTAL</th></tr></thead>
            <tbody>
              {ordered.map(([k, s]) => (
                <tr key={k}>
                  <td style={{ color: colorFor ? colorFor(k) : C.text, fontWeight: 600 }}>
                    {colorFor && <span style={{ display: 'inline-block', width: 7, height: 7, borderRadius: 2, background: colorFor(k), marginRight: 6 }} />}
                    {k}
                  </td>
                  <td style={{ color: C.sub }}>{s.n}</td>
                  <td style={{ color: (s.win_rate ?? 0) >= 0.5 ? C.green : C.sub }}>{((s.win_rate ?? 0) * 100).toFixed(0)}%</td>
                  <td style={{ color: pnlColor(s.avg_pnl), fontVariantNumeric: 'tabular-nums' }}>{fmtINR(s.avg_pnl)}</td>
                  <td style={{ color: pnlColor(s.total_pnl), fontVariantNumeric: 'tabular-nums', fontWeight: 600 }}>{fmtINR(s.total_pnl)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

export default function BacktestPage() {
  const [result, setResult]   = useState<BacktestResult | null>(null)
  const [active, setActive]   = useState(false)
  const [error, setError]     = useState<string | null>(null)
  const [days, setDays]       = useState(730)
  const [startedMs, setStarted] = useState<number | null>(null)
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
      if (s.result) setResult(s.result)
      if (!s.active && pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
    } catch { /* ignore */ }
  }, [])

  useEffect(() => { loadLatest(); poll() }, [loadLatest, poll])
  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current) }, [])

  async function run() {
    setError(null); setActive(true); setStarted(Date.now())
    try {
      const res = await api.backtestRun(days)
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
    <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', gap: 8, padding: '10px 14px', background: 'transparent', overflow: 'auto' }}>

      {/* Header strip */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, background: C.panel, border: `1px solid ${C.border}`, borderRadius: 5, padding: '10px 14px', flexShrink: 0 }}>
        <div>
          <div className="t-display" style={{ fontSize: 16 }}>Walk-Forward Backtest</div>
          <div className="t-prose" style={{ fontSize: 11.5, marginTop: 2 }}>
            Replays real daily OHLCV through the live decision core — no lookahead, no synthetic data. The keystone eval gate.
          </div>
        </div>
        <div style={{ flex: 1 }} />
        <div style={{ display: 'flex', gap: 3, border: `1px solid ${C.border}`, borderRadius: 4, overflow: 'hidden' }}>
          {HORIZONS.map(hz => (
            <button key={hz.days} onClick={() => setDays(hz.days)} disabled={active}
              style={{
                fontSize: 10, fontWeight: 700, letterSpacing: '.04em', padding: '5px 11px', border: 'none', cursor: active ? 'default' : 'pointer',
                background: days === hz.days ? C.accent : 'transparent', color: days === hz.days ? '#fff' : C.sub,
              }}>{hz.label}</button>
          ))}
        </div>
        <button className="btn btn--primary" onClick={run} disabled={active}
          title="Run the backtest over the selected horizon (CPU; a few seconds to ~1 min for 10y)">
          {active ? '◷ RUNNING…' : '▶ RUN BACKTEST'}
        </button>
      </div>

      {error && <div style={{ fontSize: 10.5, color: C.red, padding: '0 4px', flexShrink: 0 }}>⚠ {error}</div>}
      {active && <div style={{ fontSize: 10, color: C.muted, padding: '0 4px', flexShrink: 0 }}>◷ Replaying {days >= 365 ? `${(days / 365).toFixed(0)}y` : `${days}d`} across the universe… {elapsed != null ? `${elapsed}s` : ''}</div>}

      {!r && !active && (
        <div className="panel" style={{ flex: 1 }}><div className="panel-body" style={{ padding: 40, textAlign: 'center', color: C.muted, fontSize: 11 }}>
          No backtest yet. Pick a horizon and run one — results persist across restarts.
        </div></div>
      )}

      {r && (
        <>
          {/* Summary metrics */}
          <div className="panel" style={{ flexShrink: 0 }}>
            <div className="panel-header">RESULT
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

          {/* Equity curve */}
          <div className="panel" style={{ flexShrink: 0 }}>
            <div className="panel-header">EQUITY CURVE <span style={{ marginLeft: 'auto', color: C.dim, fontWeight: 400, fontSize: 9.5 }}>dashed = starting capital</span></div>
            <div className="panel-body" style={{ padding: '10px 12px' }}>
              <EquityCurve data={r.equity_curve ?? []} capital={r.capital} />
            </div>
          </div>

          {/* Attribution: lens | regime | walk-forward */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, flexShrink: 0 }}>
            <StatTable title="PER-LENS ATTRIBUTION" rows={lensRows} />
            <StatTable title="PER-REGIME" rows={regimeRows} colorFor={(k) => REGIME_C[k] ?? C.steel} />
            <div className="panel" style={{ minHeight: 0 }}>
              <div className="panel-header">WALK-FORWARD (BY YEAR)</div>
              <div className="panel-body" style={{ overflow: 'auto' }}>
                {wfRows.length === 0 ? <div style={{ padding: 18, textAlign: 'center', fontSize: 10, color: C.muted }}>No closed trades.</div> : (
                  <table>
                    <thead><tr><th>YEAR</th><th>N</th><th>WIN%</th><th>TOTAL P&L</th></tr></thead>
                    <tbody>
                      {wfRows.map(([y, s]) => (
                        <tr key={y}>
                          <td style={{ color: C.text, fontWeight: 600 }}>{y}</td>
                          <td style={{ color: C.sub }}>{s.n}</td>
                          <td style={{ color: (s.win_rate ?? 0) >= 0.5 ? C.green : C.sub }}>{((s.win_rate ?? 0) * 100).toFixed(0)}%</td>
                          <td style={{ color: pnlColor(s.total_pnl), fontVariantNumeric: 'tabular-nums', fontWeight: 600 }}>{fmtINR(s.total_pnl)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            </div>
          </div>

          {/* Recent trades */}
          <div className="panel" style={{ flex: 1, minHeight: 200 }}>
            <div className="panel-header">CLOSED TRADES <span style={{ marginLeft: 'auto', color: C.muted }}>{r.recent_trades?.length ?? 0} most recent</span></div>
            <div className="panel-body" style={{ overflow: 'auto' }}>
              <table>
                <thead><tr>
                  <th>EXIT</th><th>SYMBOL</th><th>LENSES</th><th>REGIME</th><th>ENTRY</th><th>EXIT</th><th>EV</th><th>REASON</th><th>P&L</th>
                </tr></thead>
                <tbody>
                  {(r.recent_trades ?? []).map((t, i) => (
                    <tr key={i}>
                      <td style={{ color: C.muted }}>{t.exit_date}</td>
                      <td style={{ color: C.text, fontWeight: 600 }}>{t.symbol}</td>
                      <td style={{ color: C.sub }}>{t.lens}</td>
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

          {/* Honesty footnote — scope of the v2 engine */}
          <div style={{ fontSize: 10, color: C.dim, padding: '2px 4px', flexShrink: 0 }}>
            v2 scope: long-only cash segment; the LLM planner is represented by its deterministic degraded bar (EV ≥ 1.2, conf ≥ 0.45); regime is heuristic-mode parity (NIFTY + VIX, 3-day hysteresis); NEWS lens excluded (no historical headlines retained). Signals on bar <em>t</em> fill at <em>t+1</em> open; stop is checked before target (conservative).
          </div>
        </>
      )}
    </div>
  )
}
