'use client'
import { THEME } from '@/lib/theme'
import React, { useCallback, useEffect, useRef, useState } from 'react'
import {
  api, type Instrument, type JournalEntry, type LearnerParams,
  type OrchestratorResult, type OrchestratorState, type PortfolioSummary,
  type Position, type Scorecard, type SignalRec, type Trade, type TradeStats,
} from '@/lib/api'
import { useSocketEvent, useTickMap } from '@/hooks/useSocket'
import HoldingsPanel from '@/components/panels/HoldingsPanel'
import TradePipelinePanel from '@/components/panels/TradePipelinePanel'

// ── Palette ───────────────────────────────────────────────────────────────────
const C = THEME

const CSS = `
@keyframes flash-up   { 0%{background:#2DBD8030}100%{background:transparent} }
@keyframes flash-down { 0%{background:#F2495C30}100%{background:transparent} }
.flash-up   { animation: flash-up   0.7s ease-out }
.flash-down { animation: flash-down 0.7s ease-out }
::-webkit-scrollbar { width:3px;height:3px }
::-webkit-scrollbar-track { background:#080808 }
::-webkit-scrollbar-thumb { background:#333841;border-radius:2px }
`
const StyleTag = () => <style dangerouslySetInnerHTML={{ __html: CSS }} />

// ── Helpers ───────────────────────────────────────────────────────────────────
function inr(v: number, dec = 0) {
  return '₹' + Math.abs(v).toLocaleString('en-IN', { maximumFractionDigits: dec, minimumFractionDigits: dec })
}
function Pnl({ v, dec = 0, size = 11 }: { v: number | null | undefined; dec?: number; size?: number }) {
  if (v == null) return <span style={{ color: C.dim }}>—</span>
  const col = v > 0 ? C.green : v < 0 ? C.red : C.muted
  return <span style={{ color: col, fontSize: size, fontVariantNumeric: 'tabular-nums' }}>
    {v >= 0 ? '+' : '−'}{inr(Math.abs(v), dec)}
  </span>
}
function Pct({ v }: { v: number | null | undefined }) {
  if (v == null) return <span style={{ color: C.dim }}>—</span>
  const col = v > 0 ? C.green : v < 0 ? C.red : C.muted
  return <span style={{ color: col, fontSize: 10.5, fontVariantNumeric: 'tabular-nums' }}>
    {v >= 0 ? '+' : ''}{v.toFixed(2)}%
  </span>
}
function ageFmt(ms: number): string {
  const s = Math.floor((Date.now() - ms) / 1000)
  if (s < 60) return `${s}s`
  if (s < 3600) return `${Math.floor(s/60)}m`
  if (s < 86400) return `${Math.floor(s/3600)}h${Math.floor((s%3600)/60)}m`
  return `${Math.floor(s/86400)}d`
}
function tsFmt(ms: number) {
  return new Date(ms).toLocaleTimeString('en-IN', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })
}
function durFmt(entryMs: number, exitMs: number | undefined): string {
  if (!exitMs) return ageFmt(entryMs)
  const s = Math.floor((exitMs - entryMs) / 1000)
  if (s < 60) return `${s}s`
  if (s < 3600) return `${Math.floor(s/60)}m`
  return `${Math.floor(s/3600)}h${Math.floor((s%3600)/60)}m`
}

type TokenMap = Record<number, string>
function useSym(token: number, map: TokenMap) { return map[token] ?? `#${token}` }

function useInstrumentMap() {
  const [instruments, setInstruments] = useState<Instrument[]>([])
  useEffect(() => { api.instruments().then(setInstruments).catch(() => {}) }, [])
  const tokenMap: TokenMap = {}
  for (const i of instruments) tokenMap[i.token] = i.symbol
  return { instruments, tokenMap }
}

// ── Primitives ────────────────────────────────────────────────────────────────
function Side({ v }: { v: string }) {
  const buy = v === 'BUY'
  return (
    <span style={{
      fontSize: 10, fontWeight: 700, padding: '1px 5px', borderRadius: 2,
      background: buy ? '#001a08' : '#1a0004',
      color: buy ? C.green : C.red,
      border: `1px solid ${buy ? '#2DBD8033' : '#F2495C33'}`,
      letterSpacing: '.05em',
    }}>{v}</span>
  )
}

function ReasBadge({ r }: { r: string | null | undefined }) {
  if (!r) return <span style={{ color: C.dim, fontSize: 10 }}>—</span>
  const MAP: Record<string, [string, string]> = {
    stop_loss: ['#2a0000', C.red], target: ['#002a0a', C.green],
    time_exit: ['#00112a', C.blue], manual: ['#1a0d00', C.amber],
    eod_settlement: ['#140022', C.purple],
  }
  const [bg, fg] = MAP[r] ?? ['#1C1F25', C.muted]
  return <span style={{ fontSize: 10, background: bg, color: fg, padding: '1px 5px', borderRadius: 2, whiteSpace: 'nowrap' }}>
    {r.replace(/_/g, ' ')}
  </span>
}

function DistBar({ pct, col, w = 52 }: { pct: number; col: string; w?: number }) {
  return (
    <div style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
      <div style={{ width: w, height: 3, background: '#181818', borderRadius: 2, overflow: 'hidden' }}>
        <div style={{ width: `${Math.max(0, Math.min(100, pct))}%`, height: '100%', background: col, borderRadius: 2 }} />
      </div>
    </div>
  )
}

function MetricCard({ label, value, sub, color }: { label: string; value: React.ReactNode; sub?: string; color?: string }) {
  return (
    <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 4, padding: '7px 10px' }}>
      <div style={{ fontSize: 9.5, color: C.dim, letterSpacing: '.08em', marginBottom: 3 }}>{label}</div>
      <div style={{ fontSize: 15, fontWeight: 700, color: color ?? C.text, lineHeight: 1 }}>{value}</div>
      {sub && <div style={{ fontSize: 9.5, color: C.muted, marginTop: 3 }}>{sub}</div>}
    </div>
  )
}

// ── Account Bar ───────────────────────────────────────────────────────────────
function AccountBar({
  summary, stats, unrealized,
}: {
  summary: PortfolioSummary | null
  stats: TradeStats | null
  unrealized: number
}) {
  const eq      = summary?.equity ?? 0
  const dayPnl  = summary?.daily_pnl ?? 0
  const dd      = summary?.drawdown ?? 0
  const wr      = stats?.win_rate ?? 0
  const realized = (stats?.total_pnl ?? 0) - unrealized

  const chips = [
    { label: 'EQUITY',    v: <span style={{ fontWeight: 700 }}>{inr(eq)}</span>,              c: C.text,  sub: `peak ${inr(summary?.peak_equity ?? eq)}` },
    { label: 'UNREAL',    v: <Pnl v={unrealized} />,                                           c: unrealized >= 0 ? C.green : C.red, sub: `${summary?.open_positions ?? 0} positions` },
    { label: 'REALIZED',  v: <Pnl v={realized} />,                                             c: realized >= 0 ? C.green : C.red,  sub: `${stats?.total_trades ?? 0} closed` },
    { label: 'DAY P&L',   v: <Pnl v={dayPnl} />,                                              c: dayPnl >= 0 ? C.green : C.red, sub: `${stats?.today_trades ?? 0} trades today` },
    { label: 'WIN RATE',  v: `${(wr*100).toFixed(1)}%`,                                        c: wr >= 0.6 ? C.green : wr >= 0.4 ? C.amber : C.red, sub: `${stats?.wins ?? 0}W / ${stats?.losses ?? 0}L` },
    { label: 'DRAWDOWN',  v: `${(dd*100).toFixed(2)}%`,                                        c: dd > 0.10 ? C.red : dd > 0.05 ? C.amber : C.muted, sub: 'limit 20%' },
    { label: 'INDIA VIX', v: (summary?.india_vix ?? 0).toFixed(1),                              c: (summary?.india_vix ?? 0) > 25 ? C.red : (summary?.india_vix ?? 0) > 18 ? C.amber : C.text, sub: 'volatility index' },
  ]

  return (
    <div style={{ display: 'flex', alignItems: 'stretch', background: 'rgba(12,13,16,0.82)', backdropFilter: 'blur(7px)', borderBottom: `1px solid ${C.border}`, flexShrink: 0, height: 52 }}>
      {/* Module + mode badge */}
      <div style={{ padding: '0 16px', borderRight: `1px solid ${C.border}`, display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center', gap: 2, minWidth: 86 }}>
        <span style={{ fontSize: 10.5, fontWeight: 700, color: C.text, letterSpacing: '.1em' }}>EQUITIES</span>
        <span style={{ fontSize: 9.5, fontWeight: 700, color: C.amber, letterSpacing: '.1em', background: '#06182B', border: `1px solid ${C.amber}33`, borderRadius: 3, padding: '1px 6px' }}>PAPER · CASH</span>
      </div>
      {chips.map(c => (
        <div key={c.label} style={{ flex: 1, padding: '0 12px', borderRight: `1px solid ${C.border}`, display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: 2 }}>
          <span style={{ fontSize: 9, color: C.dim, letterSpacing: '.07em' }}>{c.label}</span>
          <span style={{ fontSize: 13, lineHeight: 1, color: c.c, fontVariantNumeric: 'tabular-nums' }}>{c.v}</span>
          <span style={{ fontSize: 9.5, color: C.muted }}>{c.sub}</span>
        </div>
      ))}
    </div>
  )
}

// ── Left Rail ─────────────────────────────────────────────────────────────────
function LeftRail({
  filter, onFilter, stats, scorecards,
}: {
  filter: string
  onFilter: (s: string) => void
  stats: TradeStats | null
  scorecards: Scorecard[]
}) {
  const byStrat = stats?.by_strategy ? Object.entries(stats.by_strategy).sort((a, b) => b[1].pnl - a[1].pnl) : []
  const maxPnl = Math.max(...byStrat.map(([, r]) => Math.abs(r.pnl)), 1)

  const STRATS = ['ALL', ...byStrat.map(([id]) => id).filter(Boolean)]

  // EOD countdown
  const nowIST = () => {
    const d = new Date(Date.now() + 5.5*3600_000)
    const h = d.getUTCHours(), m = d.getUTCMinutes()
    const close = 15*60+30, now = h*60+m
    if (now < 9*60+15) return `opens in ${Math.floor((9*60+15-now)/60)}h${(9*60+15-now)%60}m`
    if (now <= close)   return `EOD in ${Math.floor((close-now)/60)}h${(close-now)%60}m`
    return 'post-market'
  }

  return (
    <div style={{ width: 190, flexShrink: 0, display: 'flex', flexDirection: 'column', gap: 8, overflowY: 'auto' }}>
      {/* Strategy filter */}
      <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 4, overflow: 'hidden' }}>
        <div style={{ padding: '7px 10px', borderBottom: `1px solid ${C.border}`, fontSize: 9.5, color: C.dim, letterSpacing: '.08em', fontWeight: 700 }}>FILTER BY STRATEGY</div>
        {STRATS.map(s => (
          <button key={s} onClick={() => onFilter(s)} style={{
            width: '100%', textAlign: 'left', display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            padding: '6px 10px', background: filter === s ? '#0094FB0A' : 'transparent',
            borderLeft: `2px solid ${filter === s ? C.amber : 'transparent'}`,
            border: 'none', cursor: 'pointer', fontSize: 10, fontWeight: filter === s ? 700 : 400,
            color: filter === s ? C.amber : C.sub, letterSpacing: '.04em',
          }}>
            <span>{s}</span>
            {s !== 'ALL' && stats?.by_strategy?.[s] && (
              <Pnl v={stats.by_strategy[s].pnl} size={9} />
            )}
          </button>
        ))}
      </div>

      {/* Attribution bars */}
      {byStrat.length > 0 && (
        <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 4, padding: '8px 10px' }}>
          <div style={{ fontSize: 9.5, color: C.dim, letterSpacing: '.08em', fontWeight: 700, marginBottom: 8 }}>TOP ATTRIBUTION</div>
          {byStrat.slice(0, 3).map(([sid, rec]) => (
            <div key={sid} style={{ marginBottom: 8 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
                <span style={{ fontSize: 10, color: C.text, fontWeight: 600 }}>{sid}</span>
                <span style={{ fontSize: 9.5, color: rec.win_rate >= 0.5 ? C.green : C.red }}>{(rec.win_rate*100).toFixed(0)}% WR</span>
              </div>
              <div style={{ height: 4, background: '#1C1F25', borderRadius: 2, overflow: 'hidden' }}>
                <div style={{
                  width: `${Math.abs(rec.pnl) / maxPnl * 100}%`,
                  height: '100%', borderRadius: 2,
                  background: rec.pnl >= 0 ? C.green : C.red,
                }} />
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 2 }}>
                <span style={{ fontSize: 9.5, color: C.muted }}>{rec.trades} trades</span>
                <Pnl v={rec.pnl} size={8} />
              </div>
            </div>
          ))}
          {byStrat.length > 3 && (
            <div style={{ fontSize: 9, color: C.muted, marginTop: 2 }}>
              +{byStrat.length - 3} more in PERFORMANCE tab
            </div>
          )}
        </div>
      )}

      {/* Risk summary */}
      <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 4, padding: '8px 10px' }}>
        <div style={{ fontSize: 9.5, color: C.dim, letterSpacing: '.08em', fontWeight: 700, marginBottom: 8 }}>SESSION</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <span style={{ fontSize: 9.5, color: C.muted }}>Today trades</span>
            <span style={{ fontSize: 10, color: C.text }}>{stats?.today_trades ?? 0}</span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <span style={{ fontSize: 9.5, color: C.muted }}>Today P&L</span>
            <Pnl v={stats?.today_pnl ?? null} size={9} />
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <span style={{ fontSize: 9.5, color: C.muted }}>Best trade</span>
            <Pnl v={stats?.best_trade_pnl ?? null} size={9} />
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <span style={{ fontSize: 9.5, color: C.muted }}>Worst trade</span>
            <Pnl v={stats?.worst_trade_pnl ?? null} size={9} />
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <span style={{ fontSize: 9.5, color: C.muted }}>Avg win</span>
            <Pnl v={stats?.avg_win ?? null} size={9} />
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <span style={{ fontSize: 9.5, color: C.muted }}>Avg loss</span>
            <Pnl v={stats?.avg_loss ?? null} size={9} />
          </div>
          <div style={{ borderTop: `1px solid ${C.border}`, paddingTop: 5, display: 'flex', justifyContent: 'space-between' }}>
            <span style={{ fontSize: 9.5, color: C.muted }}>{nowIST()}</span>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Positions Blotter ─────────────────────────────────────────────────────────
const PCOLS = 'minmax(153px, 1.4fr) 54px 66px 47px 83px 83px 83px 66px 94px 71px 57px 42px'

function PositionsTable({
  positions, ticks, tokenMap, filter, onSelect, selectedId, onClose,
}: {
  positions: Position[]
  ticks: ReturnType<typeof useTickMap>
  tokenMap: TokenMap
  filter: string
  onSelect: (id: string) => void
  selectedId: string | null
  onClose: (id: string) => void
}) {
  const [closing, setClosing] = useState<Set<string>>(new Set())
  const prevPrices = useRef<Record<number, number>>({})
  const [flashMap, setFlashMap] = useState<Record<string, 'up' | 'down'>>({})

  // Flash effect when live price changes
  useEffect(() => {
    const next: Record<string, 'up' | 'down'> = {}
    for (const pos of positions) {
      const cur = ticks[pos.instrument_id]?.last_price
      const prev = prevPrices.current[pos.instrument_id]
      if (cur != null && prev != null && cur !== prev) {
        next[pos.trade_id] = cur > prev ? 'up' : 'down'
      }
      if (cur != null) prevPrices.current[pos.instrument_id] = cur
    }
    if (Object.keys(next).length > 0) {
      setFlashMap(next)
      setTimeout(() => setFlashMap({}), 700)
    }
  }, [ticks, positions])

  async function close(id: string) {
    setClosing(p => new Set(p).add(id))
    try { await api.closePosition(id) } catch { /* ignore */ }
    finally { setClosing(p => { const s = new Set(p); s.delete(id); return s }) }
  }

  const rows = filter === 'ALL' ? positions : positions.filter(p => p.strategy_id === filter)

  const TH = ({ children, align = 'left' }: { children?: React.ReactNode; align?: string }) => (
    <span style={{ fontSize: 9.5, color: C.dim, letterSpacing: '.07em', textAlign: align as never }}>{children}</span>
  )

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: C.panel, border: `1px solid ${C.border}`, borderRadius: 4, overflow: 'hidden' }}>
      <div style={{ display: 'flex', alignItems: 'center', padding: '6px 10px', borderBottom: `1px solid ${C.border}`, flexShrink: 0, gap: 8 }}>
        <span style={{ fontSize: 10.5, fontWeight: 700, color: C.text, letterSpacing: '.06em' }}>OPEN POSITIONS</span>
        <span style={{ fontSize: 10, color: rows.length > 7 ? C.red : C.muted }}>{rows.length}/10</span>
        {rows.length > 0 && (
          <span style={{ fontSize: 10, color: C.muted, marginLeft: 4 }}>
            Unreal:&nbsp;
            <Pnl v={rows.reduce((s, p) => {
              const live = ticks[p.instrument_id]?.last_price
              if (!live) return s
              return s + (p.side === 'BUY' ? 1 : -1) * (live - p.entry_price) * p.quantity
            }, 0)} />
          </span>
        )}
      </div>
      {/* One scroll area for header + rows so a wide table scrolls INSIDE the
          panel (header sticky) instead of extending past it / getting clipped */}
      <div style={{ flex: 1, minHeight: 0, overflow: 'auto' }}>
       <div style={{ minWidth: 'max-content' }}>
      {/* Header */}
      <div style={{ display: 'grid', gridTemplateColumns: PCOLS, gap: 0, padding: '4px 10px', background: '#080808', position: 'sticky', top: 0, zIndex: 1 }}>
        <TH>INSTRUMENT</TH><TH>SIDE</TH><TH>STRAT</TH><TH align="right">QTY</TH>
        <TH align="right">ENTRY</TH><TH align="right">CMP</TH><TH align="right">UNREAL</TH>
        <TH>%</TH><TH>SL DIST ▸</TH><TH>TGT DIST ▸</TH><TH align="right">AGE</TH><TH></TH>
      </div>
      <div>
        {rows.length === 0 ? (
          <div style={{ textAlign: 'center', color: C.dim, fontSize: 10.5, padding: 32 }}>No open positions</div>
        ) : rows.map(pos => {
          const live  = ticks[pos.instrument_id]?.last_price ?? null
          const sign  = pos.side === 'BUY' ? 1 : -1
          const unr   = live != null ? sign * (live - pos.entry_price) * pos.quantity : null
          const unrPct = live != null ? sign * (live / pos.entry_price - 1) * 100 : null
          const toSL  = live != null && pos.stop_loss ? (pos.side === 'BUY' ? (live - pos.stop_loss) / live * 100 : (pos.stop_loss - live) / live * 100) : null
          const toTgt = live != null && pos.target ? (pos.side === 'BUY' ? (pos.target - live) / live * 100 : (live - pos.target) / live * 100) : null
          const openMs = pos.opened_at ? new Date(pos.opened_at).getTime() : Date.now()
          const sel = selectedId === pos.trade_id
          const flash = flashMap[pos.trade_id]
          const isClosing = closing.has(pos.trade_id)

          return (
            <div key={pos.trade_id}
              className={flash === 'up' ? 'flash-up' : flash === 'down' ? 'flash-down' : ''}
              onClick={() => onSelect(pos.trade_id)}
              style={{
                display: 'grid', gridTemplateColumns: PCOLS, gap: 0, padding: '6px 10px',
                borderBottom: `1px solid ${C.border}`, cursor: 'pointer', alignItems: 'center',
                background: sel ? '#0094FB08' : (unr != null && unr > 0) ? '#2DBD800A' : (unr != null && unr < 0) ? '#F2495C0A' : 'transparent',
                // accent as inset shadow, not border-left — a left border adds 2px
                // to the box and shifts every column off the (borderless) header
                boxShadow: `inset 2px 0 0 0 ${sel ? C.amber : (unr != null && unr > 0) ? '#2DBD8033' : (unr != null && unr < 0) ? '#F2495C33' : 'transparent'}`,
                opacity: isClosing ? 0.4 : 1,
              }}>
              <span style={{ fontSize: 11.5, fontWeight: 700, color: C.text }}>{useSym(pos.instrument_id, tokenMap)}</span>
              <Side v={pos.side} />
              <span style={{ fontSize: 10, color: C.amber }}>{pos.strategy_id}</span>
              <span style={{ fontSize: 10.5, color: C.sub, textAlign: 'right' }}>{pos.quantity}</span>
              <span style={{ fontSize: 10.5, color: C.muted, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{pos.entry_price.toFixed(2)}</span>
              <span style={{ fontSize: 11.5, fontWeight: 600, color: C.text, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{live?.toFixed(2) ?? '—'}</span>
              <span style={{ textAlign: 'right' }}><Pnl v={unr} /></span>
              <Pct v={unrPct} />
              <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                {toSL != null && <>
                  <DistBar pct={toSL / 3 * 100} col={toSL < 0.5 ? C.red : toSL < 1.5 ? C.amber : C.green} />
                  <span style={{ fontSize: 9.5, color: toSL < 0.5 ? C.red : C.muted }}>{toSL.toFixed(2)}%</span>
                </>}
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                {toTgt != null && <>
                  <DistBar pct={(1 - toTgt / 5) * 100} col={toTgt < 1 ? C.green : C.blue} />
                  <span style={{ fontSize: 9.5, color: toTgt < 1 ? C.green : C.muted }}>{toTgt.toFixed(2)}%</span>
                </>}
              </div>
              <span style={{ fontSize: 10, color: C.muted, textAlign: 'right' }}>{ageFmt(openMs)}</span>
              <button onClick={e => { e.stopPropagation(); !isClosing && close(pos.trade_id) }} disabled={isClosing}
                style={{ fontSize: 10, padding: '2px 5px', borderRadius: 2, border: `1px solid ${C.red}44`, background: '#1A0404', color: C.red, cursor: 'pointer' }}>
                {isClosing ? '…' : '✕'}
              </button>
            </div>
          )
        })}
      </div>
       </div>
      </div>
    </div>
  )
}

// ── Trade History ──────────────────────────────────────────────────────────────
const HCOLS = '66px minmax(142px, 1.4fr) 54px 66px 83px 83px 94px 59px 106px'

function TradeHistory({
  trades, tokenMap, filter, onSelect, selectedId,
}: {
  trades: Trade[]
  tokenMap: TokenMap
  filter: string
  onSelect: (id: string) => void
  selectedId: string | null
}) {
  const [search, setSearch] = useState('')

  const rows = trades
    .filter(t => filter === 'ALL' || t.strategy_id === filter)
    .filter(t => !search || (tokenMap[t.instrument_token] ?? '').toLowerCase().includes(search.toLowerCase()) || (t.strategy_id ?? '').toLowerCase().includes(search.toLowerCase()))

  const TH = ({ children, align = 'left' }: { children?: React.ReactNode; align?: string }) => (
    <span style={{ fontSize: 9.5, color: C.dim, letterSpacing: '.07em', textAlign: align as never }}>{children}</span>
  )

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: C.panel, border: `1px solid ${C.border}`, borderRadius: 4, overflow: 'hidden' }}>
      <div style={{ display: 'flex', alignItems: 'center', padding: '6px 10px', borderBottom: `1px solid ${C.border}`, flexShrink: 0, gap: 8 }}>
        <span style={{ fontSize: 10.5, fontWeight: 700, color: C.text, letterSpacing: '.06em' }}>CLOSED TRADES</span>
        <span style={{ fontSize: 10, color: C.muted }}>{rows.length}</span>
        <input value={search} onChange={e => setSearch(e.target.value)} placeholder="filter…"
          style={{ marginLeft: 'auto', background: '#0C0D10', border: `1px solid ${C.border}`, color: C.sub, fontSize: 10, padding: '2px 7px', borderRadius: 3, width: 80 }} />
      </div>
      <div style={{ flex: 1, minHeight: 0, overflow: 'auto' }}>
       <div style={{ minWidth: 'max-content' }}>
      <div style={{ display: 'grid', gridTemplateColumns: HCOLS, gap: 0, padding: '4px 10px', background: '#080808', position: 'sticky', top: 0, zIndex: 1 }}>
        <TH>TIME</TH><TH>INSTRUMENT</TH><TH>SIDE</TH><TH>STRAT</TH>
        <TH align="right">ENTRY</TH><TH align="right">EXIT</TH><TH align="right">P&L</TH><TH>DUR</TH><TH>REASON</TH>
      </div>
      <div>
        {rows.length === 0
          ? <div style={{ textAlign: 'center', color: C.dim, fontSize: 10.5, padding: 24 }}>No closed trades</div>
          : rows.map(t => {
            const sel = selectedId === t.trade_id
            const entMs = typeof t.entry_time === 'number' ? t.entry_time : new Date(t.entry_time ?? 0).getTime()
            const extMs = typeof t.exit_time === 'number' ? t.exit_time : (t.exit_time ? new Date(t.exit_time).getTime() : undefined)
            return (
              <div key={t.trade_id} onClick={() => onSelect(t.trade_id)}
                style={{
                  display: 'grid', gridTemplateColumns: HCOLS, gap: 0, padding: '5px 10px',
                  borderBottom: `1px solid ${C.border}`, cursor: 'pointer', alignItems: 'center',
                  background: sel ? '#0094FB08' : 'transparent',
                  // inset shadow keeps the row geometry identical to the header
                  boxShadow: `inset 2px 0 0 0 ${sel ? C.amber : (t.net_pnl ?? 0) > 0 ? '#2DBD8022' : '#F2495C22'}`,
                }}>
                <span style={{ fontSize: 9.5, color: C.muted, fontVariantNumeric: 'tabular-nums' }}>{extMs ? tsFmt(extMs) : '—'}</span>
                <span style={{ fontSize: 10.5, fontWeight: 700, color: C.text }}>{useSym(t.instrument_token, tokenMap)}</span>
                <Side v={t.side} />
                <span style={{ fontSize: 10, color: C.amber }}>{t.strategy_id}</span>
                <span style={{ fontSize: 10.5, color: C.muted, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{t.entry_price.toFixed(2)}</span>
                <span style={{ fontSize: 10.5, color: C.muted, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{t.exit_price?.toFixed(2) ?? '—'}</span>
                <span style={{ textAlign: 'right' }}><Pnl v={t.net_pnl} /></span>
                <span style={{ fontSize: 10, color: C.muted }}>{durFmt(entMs, extMs)}</span>
                <ReasBadge r={t.exit_reason} />
              </div>
            )
          })
        }
      </div>
       </div>
      </div>
    </div>
  )
}

// ── Book View ─────────────────────────────────────────────────────────────────
function BookView({ positions, trades, ticks, tokenMap, filter, selectedId, onSelect }: {
  positions: Position[]; trades: Trade[]; ticks: ReturnType<typeof useTickMap>
  tokenMap: TokenMap; filter: string; selectedId: string | null
  onSelect: (id: string, kind: 'position' | 'trade') => void
}) {
  const [closing, setClosing] = useState<Set<string>>(new Set())
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', gap: 6 }}>
      <div style={{ flex: '0 0 auto', maxHeight: '34%', minHeight: 0, overflow: 'auto' }}>
        <HoldingsPanel segment="EQ" />
      </div>
      <div style={{ flex: '1 1 0', minHeight: 0, overflow: 'hidden' }}>
        <PositionsTable positions={positions} ticks={ticks} tokenMap={tokenMap} filter={filter}
          onSelect={id => onSelect(id, 'position')} selectedId={selectedId}
          onClose={async id => { setClosing(p => new Set(p).add(id)); try { await api.closePosition(id) } catch { /**/ } finally { setClosing(p => { const s = new Set(p); s.delete(id); return s }) } }}
        />
      </div>
      <div style={{ flex: '0 0 32%', minHeight: 0, overflow: 'hidden' }}>
        <TradeHistory trades={trades} tokenMap={tokenMap} filter={filter}
          onSelect={id => onSelect(id, 'trade')} selectedId={selectedId} />
      </div>
    </div>
  )
}

// ── Equity Curve ─────────────────────────────────────────────────────────────
function EquityCurve({ snapshots }: { snapshots: Record<string, number>[] }) {
  const containerRef = useRef<HTMLDivElement>(null)
  if (snapshots.length < 2) return (
    <div style={{ height: 80, display: 'flex', alignItems: 'center', justifyContent: 'center', color: C.dim, fontSize: 10.5 }}>Accumulating equity data…</div>
  )
  const eqs = snapshots.map(s => s.equity)
  const min = Math.min(...eqs), max = Math.max(...eqs)
  const range = max - min || 1
  const W = 1000, H = 80
  const pts = eqs.map((e, i) => `${(i / (eqs.length - 1)) * W},${H - ((e - min) / range) * (H - 8)}`)
  const pathD = pts.join(' ')
  const fillD = `M${pts[0]} L${pts.slice(1).join(' L')} L${W},${H} L0,${H} Z`
  const isUp = eqs[eqs.length - 1] >= eqs[0]
  const col = isUp ? C.green : C.red
  return (
    <div ref={containerRef} style={{ width: '100%', height: 80 }}>
      <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
        <defs>
          <linearGradient id="eqg" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={col} stopOpacity=".25" />
            <stop offset="100%" stopColor={col} stopOpacity=".02" />
          </linearGradient>
        </defs>
        <path d={fillD} fill="url(#eqg)" />
        <polyline points={pathD} fill="none" stroke={col} strokeWidth="1.5" />
      </svg>
    </div>
  )
}

// ── Performance View ──────────────────────────────────────────────────────────
function PerformanceView({ stats, scorecards, snapshots }: {
  stats: TradeStats | null; scorecards: Scorecard[]; snapshots: Record<string, number>[]
}) {
  const byStrat = stats?.by_strategy ? Object.entries(stats.by_strategy).sort((a, b) => b[1].pnl - a[1].pnl) : []

  const metrics = [
    { l: 'TOTAL P&L',    v: <Pnl v={stats?.total_pnl ?? null} size={18} />,                       sub: `${stats?.total_trades ?? 0} closed trades` },
    { l: 'WIN RATE',     v: <span style={{ color: (stats?.win_rate ?? 0) >= 0.5 ? C.green : C.red, fontWeight: 700 }}>{((stats?.win_rate ?? 0)*100).toFixed(1)}%</span>, sub: `${stats?.wins ?? 0}W  ${stats?.losses ?? 0}L` },
    { l: 'EXPECTANCY',   v: <Pnl v={scorecards.length ? scorecards.reduce((s,sc) => s + sc.expectancy, 0) / scorecards.length : null} size={18} />, sub: 'avg per trade' },
    { l: 'AVG WIN',      v: <Pnl v={stats?.avg_win ?? null} size={18} />,                          sub: 'per winning trade' },
    { l: 'AVG LOSS',     v: <Pnl v={stats?.avg_loss ?? null} size={18} />,                         sub: 'per losing trade' },
    { l: 'BEST TRADE',   v: <Pnl v={stats?.best_trade_pnl ?? null} size={18} />,                   sub: 'single trade max' },
    { l: 'TODAY P&L',    v: <Pnl v={stats?.today_pnl ?? null} size={18} />,                        sub: `${stats?.today_trades ?? 0} trades today` },
    { l: 'WORST TRADE',  v: <Pnl v={stats?.worst_trade_pnl ?? null} size={18} />,                  sub: 'single trade min' },
  ]

  return (
    <div style={{ height: '100%', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 12 }}>
      {/* Equity curve */}
      <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 4, overflow: 'hidden' }}>
        <div style={{ padding: '6px 10px', borderBottom: `1px solid ${C.border}`, display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 10.5, fontWeight: 700, color: C.text }}>EQUITY CURVE</span>
          <span style={{ fontSize: 10, color: C.muted }}>{snapshots.length} snapshots</span>
          {snapshots.length >= 2 && (
            <span style={{ marginLeft: 'auto', fontSize: 10, color: C.muted }}>
              <Pnl v={(snapshots.at(-1)?.equity ?? 0) - (snapshots[0]?.equity ?? 0)} size={9} />
            </span>
          )}
        </div>
        <div style={{ padding: '8px 10px' }}>
          <EquityCurve snapshots={snapshots} />
        </div>
      </div>

      {/* Metrics grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6 }}>
        {metrics.map(m => (
          <MetricCard key={m.l} label={m.l} value={m.v} sub={m.sub} />
        ))}
      </div>

      {/* Strategy scorecards */}
      {scorecards.length > 0 && (
        <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 4, overflow: 'hidden' }}>
          <div style={{ padding: '6px 10px', borderBottom: `1px solid ${C.border}`, fontSize: 10.5, fontWeight: 700, color: C.text }}>STRATEGY SCORECARDS</div>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ background: '#080808' }}>
                  {['STRATEGY','TRADES','WIN RATE','BAYES WR','EXPECTANCY','AVG WIN','AVG LOSS','TOTAL P&L'].map(h => (
                    <th key={h} style={{ fontSize: 9.5, color: C.dim, letterSpacing: '.07em', padding: '5px 10px', fontWeight: 400, textAlign: 'left', borderBottom: `1px solid ${C.border}` }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {scorecards.sort((a, b) => b.total_pnl - a.total_pnl).map(sc => (
                  <tr key={sc.strategy_id} style={{ borderBottom: `1px solid ${C.border}` }}>
                    <td style={{ padding: '6px 10px', fontSize: 10.5, fontWeight: 700, color: C.amber }}>{sc.strategy_id}</td>
                    <td style={{ padding: '6px 10px', fontSize: 10.5, color: C.sub }}>{sc.total_trades}</td>
                    <td style={{ padding: '6px 10px', fontSize: 10.5, color: sc.win_rate >= 0.5 ? C.green : C.red }}>{(sc.win_rate*100).toFixed(1)}%</td>
                    <td style={{ padding: '6px 10px', fontSize: 10.5, color: sc.bayesian_wr >= 0.5 ? C.green : C.red }}>{(sc.bayesian_wr*100).toFixed(1)}%</td>
                    <td style={{ padding: '6px 10px' }}><Pnl v={sc.expectancy} size={10} /></td>
                    <td style={{ padding: '6px 10px' }}><Pnl v={sc.avg_win} size={10} /></td>
                    <td style={{ padding: '6px 10px' }}><Pnl v={sc.avg_loss} size={10} /></td>
                    <td style={{ padding: '6px 10px' }}><Pnl v={sc.total_pnl} size={10} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Attribution detail */}
      {byStrat.length > 0 && (
        <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 4, overflow: 'hidden' }}>
          <div style={{ padding: '6px 10px', borderBottom: `1px solid ${C.border}`, fontSize: 10.5, fontWeight: 700, color: C.text }}>STRATEGY ATTRIBUTION</div>
          <div style={{ padding: '10px' }}>
            {byStrat.map(([sid, rec]) => {
              const pnlAbs = Math.abs(rec.pnl)
              const maxAbs = Math.max(...byStrat.map(([, r]) => Math.abs(r.pnl)), 1)
              return (
                <div key={sid} style={{ marginBottom: 10 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                    <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                      <span style={{ fontSize: 10.5, fontWeight: 700, color: C.amber, minWidth: 36 }}>{sid}</span>
                      <span style={{ fontSize: 10, color: C.muted }}>{rec.trades} trades</span>
                      <span style={{ fontSize: 10, color: rec.win_rate >= 0.5 ? C.green : C.red }}>{(rec.win_rate*100).toFixed(0)}% WR</span>
                    </div>
                    <Pnl v={rec.pnl} size={11} />
                  </div>
                  <div style={{ height: 5, background: '#1C1F25', borderRadius: 2, overflow: 'hidden' }}>
                    <div style={{ width: `${pnlAbs / maxAbs * 100}%`, height: '100%', background: rec.pnl >= 0 ? C.green : C.red, borderRadius: 2 }} />
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Signals View (Orchestrator + Signal Feed) ─────────────────────────────────
function SignalsView({ tokenMap }: { tokenMap: TokenMap }) {
  const [state,    setState]   = useState<OrchestratorState | null>(null)
  const [signals,  setSignals] = useState<SignalRec[]>([])
  const [scanning, setScanning] = useState(false)
  const [tab, setTab] = useState<'opps' | 'signals'>('opps')

  const scanDone = useSocketEvent<(OrchestratorState & { fired: number; top_results: OrchestratorResult[] }) | null>('orchestrator_scan_done', null)
  const approved = useSocketEvent<Record<string, unknown> | null>('order_approved', null)
  const rejected = useSocketEvent<Record<string, unknown> | null>('order_rejected', null)

  useEffect(() => {
    api.orchestratorState().then(setState).catch(() => {})
    api.signals(50).then(setSignals).catch(() => {})
  }, [])

  useEffect(() => {
    if (!scanDone) return
    setScanning(false)
    setState({ scan_count: scanDone.scan_count, last_scan_ts: scanDone.last_scan_ts, results: scanDone.top_results ?? [] })
  }, [scanDone])

  function ingestSignal(raw: Record<string, unknown>, ok: boolean) {
    const token = Number(raw.instrument_id ?? raw.instrument_token ?? 0)
    setSignals(prev => {
      const filtered = prev.filter(r => r.instrument_token !== token)
      return [{
        decision_id: String(Date.now()), signal_id: String(raw.signal_id ?? ''),
        strategy_id: String(raw.strategy_id ?? ''), instrument_token: token,
        symbol: tokenMap[token] ?? null, approved: ok ? 1 : 0,
        reason: ok ? null : String(raw.reason ?? ''), decided_at: Date.now(),
        side: (raw.side as 'BUY' | 'SELL') ?? null,
        confidence: Number(raw.confidence ?? 0), regime: String(raw.regime ?? ''),
        regime_confidence: null, trigger_rule: null, trade_id: null, trade_pnl: null, fill_price: null,
      }, ...filtered].slice(0, 60)
    })
  }
  useEffect(() => { if (approved) ingestSignal(approved, true)  }, [approved, tokenMap])
  useEffect(() => { if (rejected) ingestSignal(rejected, false) }, [rejected, tokenMap])

  async function scan() {
    setScanning(true)
    await api.orchestratorScan().catch(() => {})
    setTimeout(() => setScanning(false), 12_000)
  }

  const results   = state?.results ?? []
  const tradeable = results.filter(r => r.side !== 'NEUTRAL' && r.side !== 'SKIP' && r.ev >= 1.2)
  const watching  = results.filter(r => r.side === 'NEUTRAL' || r.ev < 1.2)
  const lastAge   = state?.last_scan_ts ? (() => { const s = Math.floor((Date.now() - state.last_scan_ts)/1000); return s < 60 ? `${s}s` : `${Math.floor(s/60)}m` })() + ' ago' : 'never'

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', gap: 6 }}>
      {/* Scan header */}
      <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 4, padding: '7px 12px', display: 'flex', alignItems: 'center', gap: 10, flexShrink: 0 }}>
        <span style={{ fontSize: 10.5, fontWeight: 700, color: C.text }}>ORCHESTRATOR</span>
        <span style={{ fontSize: 10, color: C.muted }}>scan #{state?.scan_count ?? 0} · {lastAge}</span>
        <span style={{ fontSize: 10, color: tradeable.length > 0 ? C.green : C.muted }}>
          {tradeable.length > 0 ? `⚡ ${tradeable.length} setups` : 'no setups'}
        </span>
        <button onClick={scan} disabled={scanning} style={{
          marginLeft: 'auto', fontSize: 10, padding: '3px 12px', borderRadius: 3,
          background: scanning ? '#0A0B0D' : '#001A08', border: `1px solid ${scanning ? C.border : C.green}`,
          color: scanning ? C.muted : C.green, cursor: scanning ? 'wait' : 'pointer', fontWeight: 700, letterSpacing: '.06em',
        }}>{scanning ? '⟳ SCANNING…' : '⟳ SCAN NOW'}</button>
        <div style={{ display: 'flex', gap: 0 }}>
          {(['opps','signals'] as const).map(t => (
            <button key={t} onClick={() => setTab(t)} style={{
              fontSize: 10, padding: '3px 10px', background: tab === t ? '#23272E' : 'transparent',
              border: 'none', color: tab === t ? C.text : C.muted, cursor: 'pointer', fontWeight: tab === t ? 700 : 400,
              borderBottom: `2px solid ${tab === t ? C.amber : 'transparent'}`,
            }}>
              {t === 'opps' ? `OPPORTUNITIES${tradeable.length > 0 ? ` (${tradeable.length})` : ''}` : `SIGNALS (${signals.length})`}
            </button>
          ))}
        </div>
      </div>

      {/* Content — solid surface so the cards/rows don't float over the page
          mesh (it showed through the gaps as a grid over the signals list).
          The mesh stays visible in the page gutters around this panel. */}
      <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', background: C.bg, border: `1px solid ${C.border}`, borderRadius: 4, padding: 6 }}>
        {tab === 'opps' ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {results.length === 0 && (
              <div style={{ textAlign: 'center', color: C.dim, fontSize: 10.5, padding: 32 }}>
                {scanning ? '⟳ Scanning all instruments…' : 'No scan yet — click SCAN NOW or wait for auto-scan'}
              </div>
            )}
            {tradeable.map(r => <OppCard key={r.symbol} r={r} />)}
            {watching.length > 0 && tradeable.length > 0 && <div style={{ fontSize: 9.5, color: C.dim, padding: '8px 0 4px', letterSpacing: '.07em', borderTop: `1px solid ${C.border}` }}>WATCHING ({watching.length})</div>}
            {watching.map(r => <OppCard key={r.symbol} r={r} dim />)}
          </div>
        ) : (
          <div>
            {signals.length === 0
              ? <div style={{ textAlign: 'center', color: C.dim, fontSize: 10.5, padding: 32 }}>No signals yet</div>
              : signals.map(s => <SigRow key={s.decision_id} s={s} tokenMap={tokenMap} />)
            }
          </div>
        )}
      </div>
    </div>
  )
}

function OppCard({ r, dim = false }: { r: OrchestratorResult; dim?: boolean }) {
  const isBuy  = r.side === 'BUY', isSell = r.side === 'SELL'
  const active = (isBuy || isSell) && r.ev >= 1.2
  const col    = isBuy ? C.green : isSell ? C.red : C.muted
  return (
    <div style={{
      background: C.panel, border: `1px solid ${active ? col + '33' : C.border}`,
      borderLeft: `3px solid ${active ? col : C.border}`, borderRadius: 4,
      padding: '8px 12px', opacity: dim ? 0.5 : 1, marginBottom: 4,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <span style={{ fontSize: 13, fontWeight: 700, color: C.text }}>{r.symbol}</span>
          {active && <Side v={r.side} />}
          <span style={{ fontSize: 10, color: C.muted }}>₹{r.price.toFixed(0)}</span>
        </div>
        {active && (
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <span style={{ fontSize: 10.5, fontWeight: 700, color: r.ev >= 2 ? C.green : r.ev >= 1.5 ? C.amber : C.muted }}>EV {r.ev.toFixed(2)}</span>
            <span style={{ fontSize: 10, color: C.sub }}>R:R {r.rr?.toFixed(1) ?? '—'}</span>
          </div>
        )}
      </div>
      {active && (
        <div style={{ display: 'flex', gap: 10, marginTop: 6, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 10, color: C.muted }}>conf {(r.confidence*100).toFixed(0)}%</span>
          <span style={{ fontSize: 10, color: C.muted }}>regime {r.regime}</span>
          <span style={{ fontSize: 10, color: C.muted }}>RSI {r.rsi}</span>
          <span style={{ fontSize: 10, color: C.muted }}>SL {r.suggested_sl > 0 ? inr(r.suggested_sl, 0) : '—'}</span>
          <span style={{ fontSize: 10, color: C.muted }}>Tgt {r.suggested_target > 0 ? inr(r.suggested_target, 0) : '—'}</span>
          {r.lenses?.length > 0 && <span style={{ fontSize: 10, color: C.dim }}>{r.lenses.map(l => l.strategy).join('＋')}</span>}
        </div>
      )}
      {!active && <div style={{ fontSize: 10, color: C.dim, marginTop: 2 }}>RSI {r.rsi} · {r.ret_20d > 0 ? '+' : ''}{r.ret_20d?.toFixed(1)}% 20d · {r.verdict}</div>}
    </div>
  )
}

function SigRow({ s, tokenMap }: { s: SignalRec; tokenMap: TokenMap }) {
  const label = s.symbol ?? tokenMap[s.instrument_token] ?? `#${s.instrument_token}`
  const ok    = s.approved === 1
  return (
    <div style={{
      display: 'grid', gridTemplateColumns: '52px 14px 100px 56px 56px 1fr',
      gap: 8, padding: '5px 10px', borderBottom: `1px solid ${C.border}`,
      alignItems: 'center', background: ok ? '#2DBD800A' : 'transparent',
    }}>
      <span style={{ fontSize: 9.5, color: C.dim, fontVariantNumeric: 'tabular-nums' }}>{tsFmt(s.decided_at)}</span>
      <span style={{ fontSize: 10.5, color: ok ? C.green : C.red, fontWeight: 700 }}>{ok ? '✓' : '✗'}</span>
      <span style={{ fontSize: 10.5, fontWeight: 700, color: C.text }}>{label}</span>
      {s.side ? <Side v={s.side} /> : <span />}
      <span style={{ fontSize: 10, color: C.amber }}>{s.strategy_id}</span>
      <span style={{ fontSize: 10, color: ok ? C.muted : C.red, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {ok ? `conf ${((s.confidence ?? 0)*100).toFixed(0)}% · ${s.regime ?? ''}` : s.reason ?? 'rejected'}
      </span>
    </div>
  )
}

// ── Trade Inspector (Right Rail) ──────────────────────────────────────────────
function TradeInspector({
  kind, id, positions, trades, ticks, tokenMap, onClose, instruments, equity,
}: {
  kind: 'position' | 'trade' | 'order' | null
  id: string | null
  positions: Position[]
  trades: Trade[]
  ticks: ReturnType<typeof useTickMap>
  tokenMap: TokenMap
  onClose: () => void
  instruments: Instrument[]
  equity: number
}) {
  const [orderTab, setOrderTab] = useState(false)

  const pos   = kind === 'position' ? positions.find(p => p.trade_id === id) : null
  const trade = kind === 'trade'    ? trades.find(t => t.trade_id === id)    : null
  const showOrder = kind === 'order' || orderTab

  const live  = pos ? ticks[pos.instrument_id]?.last_price ?? null : null
  const sign  = pos?.side === 'BUY' ? 1 : -1
  const unr   = pos && live != null ? sign * (live - pos.entry_price) * pos.quantity : null
  const unrPct = pos && live != null ? sign * (live / pos.entry_price - 1) * 100 : null
  const toSL  = pos && live != null && pos.stop_loss ? Math.abs(live - pos.stop_loss) / live * 100 * (pos.side === 'BUY' ? 1 : -1) * (live > pos.stop_loss ? 1 : -1) : null
  const toTgt = pos && live != null && pos.target ? Math.abs(pos.target - live) / live * 100 : null

  const [prefill, setPrefill] = useState<{ symbol: string; side: 'BUY'|'SELL'; sl?: number; target?: number } | null>(null)

  return (
    <div style={{ width: 270, height: '100%', display: 'flex', flexDirection: 'column', background: C.panel, border: `1px solid ${C.border}`, borderRadius: 4, overflow: 'hidden' }}>
      <div style={{ display: 'flex', alignItems: 'center', padding: '7px 12px', borderBottom: `1px solid ${C.border}`, flexShrink: 0 }}>
        <span style={{ fontSize: 10, color: C.muted, letterSpacing: '.07em', fontWeight: 700, flex: 1 }}>
          {showOrder ? 'ORDER TICKET' : kind === 'position' ? 'POSITION DETAIL' : kind === 'trade' ? 'TRADE DETAIL' : 'ORDER TICKET'}
        </span>
        {!showOrder && <button onClick={() => setOrderTab(true)} style={{ fontSize: 10, color: C.amber, background: 'none', border: `1px solid ${C.amber}33`, borderRadius: 3, padding: '2px 7px', cursor: 'pointer', marginRight: 6 }}>⊕ ORDER</button>}
        {showOrder && kind !== 'order' && <button onClick={() => setOrderTab(false)} style={{ fontSize: 10, color: C.muted, background: 'none', border: 'none', cursor: 'pointer', marginRight: 6 }}>← BACK</button>}
        <button onClick={onClose} style={{ background: 'none', border: 'none', color: C.muted, cursor: 'pointer', fontSize: 12.5 }}>✕</button>
      </div>

      <div style={{ flex: 1, overflowY: 'auto', padding: '10px 12px' }}>
        {showOrder ? (
          <InlineOrderTicket instruments={instruments} equity={equity} prefill={prefill} ticks={ticks} />
        ) : pos ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 16, fontWeight: 700, color: C.text }}>{useSym(pos.instrument_id, tokenMap)}</span>
              <Side v={pos.side} />
              <span style={{ fontSize: 10, color: C.amber, fontWeight: 600 }}>{pos.strategy_id}</span>
            </div>
            <div style={{ background: '#080808', borderRadius: 4, padding: '10px' }}>
              <div style={{ fontSize: 20, fontWeight: 700, marginBottom: 2 }}><Pnl v={unr} size={20} /></div>
              <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                <Pct v={unrPct} />
                <span style={{ fontSize: 10, color: C.muted }}>{pos.quantity} shares</span>
              </div>
            </div>
            {[
              ['Entry price', pos.entry_price.toFixed(2)],
              ['Live price', live?.toFixed(2) ?? '—'],
              ['Quantity', pos.quantity],
              ['Stop loss', pos.stop_loss?.toFixed(2) ?? '—'],
              ['Target', pos.target?.toFixed(2) ?? '—'],
              ['Dist to SL', toSL != null ? `${toSL.toFixed(2)}%` : '—'],
              ['Dist to Tgt', toTgt != null ? `${toTgt.toFixed(2)}%` : '—'],
              ['Regime', pos.regime ?? '—'],
              ['Age', pos.opened_at ? ageFmt(new Date(pos.opened_at).getTime()) : '—'],
            ].map(([k, v]) => (
              <div key={String(k)} style={{ display: 'flex', justifyContent: 'space-between', padding: '3px 0', borderBottom: `1px solid ${C.border}` }}>
                <span style={{ fontSize: 10, color: C.muted }}>{k}</span>
                <span style={{ fontSize: 10, color: C.text, fontVariantNumeric: 'tabular-nums' }}>{String(v)}</span>
              </div>
            ))}
            <button onClick={() => { setPrefill({ symbol: useSym(pos.instrument_id, tokenMap), side: pos.side === 'BUY' ? 'SELL' : 'BUY' }); setOrderTab(true) }}
              style={{ marginTop: 4, padding: '7px', width: '100%', fontSize: 10.5, fontWeight: 700, borderRadius: 3, cursor: 'pointer', background: pos.side === 'BUY' ? '#1A0004' : '#001A08', color: pos.side === 'BUY' ? C.red : C.green, border: `1px solid ${pos.side === 'BUY' ? C.red + '44' : C.green + '44'}` }}>
              CLOSE POSITION
            </button>
          </div>
        ) : trade ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 15, fontWeight: 700, color: C.text }}>{useSym(trade.instrument_token, tokenMap)}</span>
              <Side v={trade.side} />
              <span style={{ fontSize: 10, color: C.amber }}>{trade.strategy_id}</span>
            </div>
            <div style={{ background: '#080808', borderRadius: 4, padding: '10px' }}>
              <div style={{ fontSize: 20, fontWeight: 700 }}><Pnl v={trade.net_pnl} size={20} /></div>
            </div>
            {[
              ['Entry', trade.entry_price.toFixed(2)],
              ['Exit', trade.exit_price?.toFixed(2) ?? '—'],
              ['Qty', trade.quantity],
              ['Duration', trade.exit_time ? durFmt(trade.entry_time, typeof trade.exit_time === 'number' ? trade.exit_time : new Date(trade.exit_time).getTime()) : '—'],
              ['Exit reason', trade.exit_reason ?? '—'],
              ['Regime', trade.regime_at_entry ?? '—'],
              ['Confidence', trade.confidence != null ? `${(trade.confidence*100).toFixed(0)}%` : '—'],
            ].map(([k, v]) => (
              <div key={String(k)} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', borderBottom: `1px solid ${C.border}` }}>
                <span style={{ fontSize: 10, color: C.muted }}>{k}</span>
                <span style={{ fontSize: 10, color: C.text, fontVariantNumeric: 'tabular-nums' }}>{String(v)}</span>
              </div>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  )
}

// ── Inline Order Ticket ───────────────────────────────────────────────────────
function InlineOrderTicket({
  instruments, equity, prefill, ticks,
}: {
  instruments: Instrument[]
  equity: number
  prefill: { symbol: string; side: 'BUY'|'SELL'; sl?: number; target?: number } | null
  ticks: ReturnType<typeof useTickMap>
}) {
  const [sym2,    setSym]     = useState(prefill?.symbol ?? '')
  const [search,  setSearch]  = useState(prefill?.symbol ?? '')
  const [side,    setSide]    = useState<'BUY'|'SELL'>(prefill?.side ?? 'BUY')
  const [qty,     setQty]     = useState('')
  const [sl,      setSl]      = useState(prefill?.sl?.toFixed(2) ?? '')
  const [target,  setTarget]  = useState(prefill?.target?.toFixed(2) ?? '')
  const [loading, setLoading] = useState(false)
  const [msg,     setMsg]     = useState<{ ok: boolean; text: string } | null>(null)
  const [confirm, setConfirm] = useState(false)

  useEffect(() => {
    if (!prefill) return
    setSym(prefill.symbol); setSearch(prefill.symbol); setSide(prefill.side)
    if (prefill.sl) setSl(prefill.sl.toFixed(2))
    if (prefill.target) setTarget(prefill.target.toFixed(2))
  }, [prefill])

  const inst   = instruments.find(i => i.symbol === sym2)
  const live   = inst ? ticks[inst.token]?.last_price : null
  // Equities module: cash instruments only — indices/VIX live in the F&O module
  const filt   = search ? instruments.filter(i => i.type === 'EQ' && i.symbol.toLowerCase().startsWith(search.toLowerCase())) : []
  const showD  = filt.length > 0 && filt[0].symbol !== search

  function autoSz() {
    if (!live) return
    const cap = Math.min(equity * 0.05, 100_000)
    setQty(String(Math.max(1, Math.floor(cap / live))))
  }

  const notional = live && qty ? parseFloat(qty) * live : null
  const rr = sl && target && live ? (() => {
    const r = Math.abs(live - parseFloat(sl)), w = Math.abs(parseFloat(target) - live)
    return r > 0 ? `R:R ${(w/r).toFixed(1)}` : ''
  })() : ''

  async function submit() {
    if (!sym2 || !qty) return
    if (!confirm) { setConfirm(true); return }
    setLoading(true); setMsg(null); setConfirm(false)
    try {
      const res = await api.manualOrder({ symbol: sym2, side, quantity: parseInt(qty), stop_loss: sl ? parseFloat(sl) : undefined, target: target ? parseFloat(target) : undefined })
      if (res.ok) { setMsg({ ok: true, text: `Filled ${side} ${qty}× ${sym2}` }); setQty(''); setSl(''); setTarget('') }
      else setMsg({ ok: false, text: res.error ?? 'Rejected' })
    } catch { setMsg({ ok: false, text: 'Network error' }) }
    finally { setLoading(false) }
  }

  const inp = { width: '100%', background: '#0C0D10', border: `1px solid ${C.border}`, color: C.text, fontSize: 11.5, padding: '4px 7px', borderRadius: 3, boxSizing: 'border-box' as const }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {live != null && sym2 && <div style={{ fontSize: 11.5, color: C.green, fontWeight: 600 }}>{sym2} ₹{live.toFixed(2)}</div>}
      <div style={{ position: 'relative' }}>
        <label style={{ fontSize: 9.5, color: C.dim, display: 'block', marginBottom: 2 }}>SYMBOL</label>
        <input value={search} onChange={e => { setSearch(e.target.value); setSym('') }} placeholder="search…" style={{ ...inp, color: sym2 ? C.green : C.text }} />
        {showD && (
          <div style={{ position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 50, background: '#1C1F25', border: `1px solid ${C.border2}`, borderRadius: 3, maxHeight: 120, overflow: 'auto' }}>
            {filt.slice(0, 8).map(i => (
              <div key={i.token} onClick={() => { setSym(i.symbol); setSearch(i.symbol) }}
                style={{ padding: '4px 8px', fontSize: 10.5, cursor: 'pointer', color: C.sub }}
                onMouseEnter={e => (e.currentTarget.style.background = '#23272E')}
                onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}>
                {i.symbol}
              </div>
            ))}
          </div>
        )}
      </div>
      <div style={{ display: 'flex', gap: 5 }}>
        {(['BUY','SELL'] as const).map(s => (
          <button key={s} onClick={() => setSide(s)} style={{
            flex: 1, padding: '5px 0', fontSize: 10.5, fontWeight: 700, cursor: 'pointer', borderRadius: 3, border: 'none', letterSpacing: '.07em',
            background: side === s ? (s === 'BUY' ? '#001A08' : '#1A0004') : '#1C1F25',
            color: side === s ? (s === 'BUY' ? C.green : C.red) : C.muted,
          }}>{s}</button>
        ))}
      </div>
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
          <label style={{ fontSize: 9.5, color: C.dim }}>QTY</label>
          <button onClick={autoSz} disabled={!live} style={{ fontSize: 9.5, color: C.muted, background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}>auto-size</button>
        </div>
        <input type="number" min="1" value={qty} onChange={e => setQty(e.target.value)} placeholder="0" style={inp} />
        {notional != null && <div style={{ fontSize: 9.5, color: C.muted, marginTop: 2 }}>{inr(notional)} notional{rr ? ` · ${rr}` : ''}</div>}
      </div>
      <div>
        <label style={{ fontSize: 9.5, color: C.red, display: 'block', marginBottom: 2 }}>STOP LOSS</label>
        <input type="number" value={sl} onChange={e => setSl(e.target.value)} placeholder="0.00" style={{ ...inp, color: C.red }} />
      </div>
      <div>
        <label style={{ fontSize: 9.5, color: C.green, display: 'block', marginBottom: 2 }}>TARGET</label>
        <input type="number" value={target} onChange={e => setTarget(e.target.value)} placeholder="0.00" style={{ ...inp, color: C.green }} />
      </div>
      {confirm ? (
        <div style={{ display: 'flex', gap: 5 }}>
          <button onClick={submit} style={{ flex: 2, padding: '7px 0', fontSize: 10.5, fontWeight: 700, borderRadius: 3, cursor: 'pointer', border: 'none', background: side === 'BUY' ? '#001A08' : '#1A0004', color: side === 'BUY' ? C.green : C.red }}>CONFIRM {side}</button>
          <button onClick={() => setConfirm(false)} style={{ flex: 1, padding: '7px 0', fontSize: 10.5, borderRadius: 3, cursor: 'pointer', border: `1px solid ${C.border}`, background: '#0A0B0D', color: C.muted }}>CANCEL</button>
        </div>
      ) : (
        <button onClick={submit} disabled={loading || !sym2 || !qty} style={{
          padding: '7px 0', fontSize: 10.5, fontWeight: 700, borderRadius: 3, letterSpacing: '.07em',
          cursor: loading || !sym2 || !qty ? 'not-allowed' : 'pointer', border: 'none',
          background: loading || !sym2 || !qty ? '#1C1F25' : (side === 'BUY' ? '#001A08' : '#1A0004'),
          color: loading || !sym2 || !qty ? C.dim : (side === 'BUY' ? C.green : C.red),
        }}>{loading ? 'SENDING…' : `PLACE ${side}`}</button>
      )}
      {msg && <div style={{ fontSize: 10.5, padding: '4px 7px', borderRadius: 3, background: msg.ok ? '#001A08' : '#1A0004', color: msg.ok ? C.green : C.red, border: `1px solid ${msg.ok ? C.green + '44' : C.red + '44'}` }}>{msg.text}</div>}
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────
type Tab  = 'book' | 'performance' | 'signals' | 'pipeline'
type Sel  = { kind: 'position' | 'trade'; id: string } | { kind: 'order' } | null

export default function TradePage() {
  const [tab,        setTab]       = useState<Tab>('book')
  const [filter,     setFilter]    = useState('ALL')
  // Order ticket open by default — the cockpit should be immediately tradeable
  const [sel,        setSel]       = useState<Sel>({ kind: 'order' })
  const [positions,  setPositions] = useState<Position[]>([])
  const [trades,     setTrades]    = useState<Trade[]>([])
  const [summary,    setSummary]   = useState<PortfolioSummary | null>(null)
  const [stats,      setStats]     = useState<TradeStats | null>(null)
  const [scorecards, setScorecards] = useState<Scorecard[]>([])
  const [snapshots,  setSnapshots] = useState<Record<string, number>[]>([])
  const ticks = useTickMap()
  const { instruments, tokenMap } = useInstrumentMap()

  const pnlUp  = useSocketEvent<{ equity: number; daily_pnl: number } | null>('pnl_update', null)
  const opened = useSocketEvent<Position | null>('trade_opened', null)
  const closed = useSocketEvent<{ trade_id: string } | null>('trade_closed', null)

  const load = useCallback(async () => {
    const [p, t, s, st, sc, sn] = await Promise.allSettled([
      api.positions(), api.tradesClosed(100), api.portfolio(), api.tradeStats(), api.scorecards(), api.portfolioSnapshots(90),
    ])
    if (p.status  === 'fulfilled') setPositions(p.value)
    if (t.status  === 'fulfilled') setTrades(t.value)
    if (s.status  === 'fulfilled') setSummary(s.value)
    if (st.status === 'fulfilled') setStats(st.value)
    if (sc.status === 'fulfilled') setScorecards(sc.value)
    if (sn.status === 'fulfilled') setSnapshots(sn.value)
  }, [])

  useEffect(() => { load() }, [load])
  useEffect(() => { const t = setInterval(load, 15_000); return () => clearInterval(t) }, [load])
  useEffect(() => { if (pnlUp) setSummary(p => p ? { ...p, equity: pnlUp.equity, daily_pnl: pnlUp.daily_pnl } : p) }, [pnlUp])
  useEffect(() => { if (opened) setPositions(p => [opened, ...p.filter(x => x.trade_id !== opened.trade_id)]) }, [opened])
  useEffect(() => { if (closed) { setPositions(p => p.filter(x => x.trade_id !== closed.trade_id)); load() } }, [closed, load])

  // Compute live unrealized
  const unrealized = positions.reduce((s, pos) => {
    const live = ticks[pos.instrument_id]?.last_price
    if (!live) return s
    return s + (pos.side === 'BUY' ? 1 : -1) * (live - pos.entry_price) * pos.quantity
  }, 0)

  const selId = sel && sel.kind !== 'order' ? sel.id : null

  return (
    <>
      <StyleTag />
      <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', background: 'transparent', overflow: 'hidden' }}>
        <AccountBar summary={summary} stats={stats} unrealized={unrealized} />

        <div style={{ flex: 1, minHeight: 0, display: 'flex', gap: 8, padding: '8px 10px', overflow: 'hidden' }}>
          {/* Left rail */}
          <LeftRail filter={filter} onFilter={setFilter} stats={stats} scorecards={scorecards} />

          {/* Center + inspector are static side-by-side panes (the inspector is
              a reserved column, never a floating overlay on the table) */}
          <div style={{ flex: 1, minWidth: 0, minHeight: 0, display: 'flex', gap: 8 }}>

          {/* Center */}
          <div style={{ flex: 1, minWidth: 0, minHeight: 0, display: 'flex', flexDirection: 'column', gap: 6 }}>
            {/* Tab bar */}
            <div style={{ display: 'flex', alignItems: 'center', background: C.panel, border: `1px solid ${C.border}`, borderRadius: 4, overflow: 'hidden', flexShrink: 0, height: 34 }}>
              {(['book', 'performance', 'signals', 'pipeline'] as Tab[]).map(t => (
                <button key={t} onClick={() => setTab(t)} style={{
                  padding: '0 18px', height: '100%', fontSize: 10, fontWeight: tab === t ? 700 : 400,
                  letterSpacing: '.08em', background: 'transparent', border: 'none',
                  borderBottom: `2px solid ${tab === t ? '#0094FB' : 'transparent'}`,
                  color: tab === t ? '#0094FB' : C.muted, cursor: 'pointer', textTransform: 'uppercase',
                }}>{t === 'book' ? `BOOK (${positions.filter(p => filter === 'ALL' || p.strategy_id === filter).length})` : t.toUpperCase()}</button>
              ))}
              <div style={{ flex: 1 }} />
              <button onClick={() => setSel({ kind: 'order' })} style={{
                height: '100%', padding: '0 22px', fontSize: 10.5, fontWeight: 800, background: '#0094FB14',
                border: 'none', borderLeft: `2px solid #0094FB`, color: '#00B9FC', cursor: 'pointer', letterSpacing: '.08em',
              }}>⊕ NEW ORDER</button>
              <button onClick={load} style={{ height: '100%', padding: '0 12px', fontSize: 10, color: C.muted, background: 'none', border: 'none', borderLeft: `1px solid ${C.border}`, cursor: 'pointer' }}>↺</button>
            </div>

            {/* Content */}
            <div style={{ flex: 1, minHeight: 0, overflow: 'hidden' }}>
              {tab === 'book' && (
                <BookView positions={positions} trades={trades} ticks={ticks} tokenMap={tokenMap}
                  filter={filter} selectedId={selId}
                  onSelect={(id, kind) => setSel(s => s?.kind !== 'order' && s?.id === id ? null : { kind, id })}
                />
              )}
              {tab === 'performance' && <PerformanceView stats={stats} scorecards={scorecards} snapshots={snapshots} />}
              {tab === 'signals' && <SignalsView tokenMap={tokenMap} />}
              {tab === 'pipeline' && <TradePipelinePanel defaultSegment="ALL" />}
            </div>
          </div>

          {/* Right inspector — static reserved column (slides in, no overlay) */}
          {sel && (
            <div className="slide-in-right" style={{ flexShrink: 0 }}>
              <TradeInspector
                kind={sel.kind}
                id={sel.kind !== 'order' ? sel.id : null}
                positions={positions} trades={trades} ticks={ticks} tokenMap={tokenMap}
                onClose={() => setSel(null)}
                instruments={instruments} equity={summary?.equity ?? 1_000_000}
              />
            </div>
          )}
          </div>
        </div>
      </div>
    </>
  )
}
