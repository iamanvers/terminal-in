'use client'
import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { THEME } from '@/lib/theme'
import { api, PipelineItem, TradePipeline } from '@/lib/api'
import { getSocket } from '@/lib/socket'

const C = THEME

/**
 * Trade execution → settlement pipeline, for BOTH equities and F&O. Shows the
 * funnel (signal → gate → open → closed/settled) and the live lifecycle of each
 * trade. Self-fetching; refreshes on trade events.
 */

const STAGE: Record<string, { label: string; color: string }> = {
  rejected: { label: 'REJECTED', color: C.red },
  open:     { label: 'OPEN',     color: C.accentBright },
  closed:   { label: 'CLOSED',   color: C.sub },
  settled:  { label: 'SETTLED',  color: C.teal },
}

function fmtINR(v: number | null | undefined) {
  if (v == null) return '—'
  const a = Math.abs(v)
  const s = a >= 1e5 ? `₹${(a / 1e5).toFixed(2)}L` : a >= 1e3 ? `₹${(a / 1e3).toFixed(1)}k` : `₹${a.toFixed(0)}`
  return `${v < 0 ? '-' : ''}${s}`
}
function ago(ms: number | null) {
  if (!ms) return ''
  const s = Math.round((Date.now() - ms) / 1000)
  if (s < 60) return `${s}s`
  if (s < 3600) return `${Math.floor(s / 60)}m`
  if (s < 86400) return `${Math.floor(s / 3600)}h`
  return `${Math.floor(s / 86400)}d`
}

// One funnel stage box
function FunnelBox({ label, n, color, drop }: { label: string; n: number; color: string; drop?: number }) {
  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 3, position: 'relative',
      padding: '8px 4px', background: C.card, border: `1px solid ${C.border}`, borderRadius: 5 }}>
      <span style={{ fontSize: 22, fontWeight: 700, color, fontVariantNumeric: 'tabular-nums', lineHeight: 1 }}>{n}</span>
      <span style={{ fontSize: 9.5, color: C.sub, letterSpacing: '.07em', fontWeight: 600 }}>{label}</span>
      {drop != null && drop > 0 && (
        <span style={{ position: 'absolute', top: 4, right: 6, fontSize: 9, fontWeight: 700, color: C.red }}>−{drop} rej</span>
      )}
    </div>
  )
}

export default function TradePipelinePanel({ defaultSegment = 'ALL' }:
  { defaultSegment?: 'ALL' | 'EQ' | 'FNO'; compact?: boolean }) {
  const [data, setData] = useState<TradePipeline | null>(null)
  const [seg, setSeg]   = useState<'ALL' | 'EQ' | 'FNO'>(defaultSegment)

  const load = useCallback(() => { api.tradePipeline(40).then(setData).catch(() => {}) }, [])
  useEffect(() => { load() }, [load])
  useEffect(() => {
    const s = getSocket()
    const h = () => load()
    for (const ev of ['trade.opened', 'trade.closed', 'fno.trade.opened', 'fno.trade.closed', 'order.rejected'])
      s.on(ev, h)
    const t = setInterval(load, 10_000)
    return () => { for (const ev of ['trade.opened', 'trade.closed', 'fno.trade.opened', 'fno.trade.closed', 'order.rejected']) s.off(ev, h); clearInterval(t) }
  }, [load])

  const items = useMemo(() => (data?.items ?? []).filter(i => seg === 'ALL' || i.segment === seg), [data, seg])
  const f = data?.funnel

  return (
    <div className="panel" style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
      <div className="panel-header">
        TRADE PIPELINE
        <span style={{ marginLeft: 'auto', display: 'inline-flex', gap: 2 }}>
          {(['ALL', 'EQ', 'FNO'] as const).map(s => (
            <button key={s} onClick={() => setSeg(s)}
              style={{ fontSize: 9.5, fontWeight: 700, padding: '3px 10px', borderRadius: 3, cursor: 'pointer', border: 'none',
                background: seg === s ? C.accent : 'transparent', color: seg === s ? '#fff' : C.muted }}>{s}</button>
          ))}
        </span>
      </div>

      {/* Funnel — boxed stages with legible arrows */}
      {f && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '12px 14px', borderBottom: `1px solid ${C.border}`, flexShrink: 0 }}>
          <FunnelBox label="SIGNALED" n={f.signaled} color={C.text} />
          <Arrow />
          <FunnelBox label="APPROVED" n={f.approved} color={C.blue} drop={f.rejected} />
          <Arrow />
          <FunnelBox label="OPEN" n={f.open} color={C.accentBright} />
          <Arrow />
          <FunnelBox label="SETTLED" n={f.closed} color={C.teal} />
        </div>
      )}

      {/* Lifecycle table — proper headers + aligned columns */}
      <div className="panel-body" style={{ flex: 1, minHeight: 0, overflow: 'auto', padding: 0 }}>
        {items.length === 0 ? (
          <div style={{ padding: 28, textAlign: 'center', fontSize: 11, color: C.muted }}>
            No recent trade activity{seg !== 'ALL' ? ` for ${seg}` : ''}.
          </div>
        ) : (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontVariantNumeric: 'tabular-nums' }}>
            <thead>
              <tr style={{ position: 'sticky', top: 0, background: C.panel, zIndex: 1 }}>
                <Th>SEG</Th><Th>SYMBOL</Th><Th>SIDE</Th><Th>STRATEGY</Th><Th>STAGE</Th>
                <Th>DETAIL</Th><Th right>QTY</Th><Th right>ENTRY</Th><Th right>EXIT</Th>
                <Th right>P&amp;L</Th><Th right>AGE</Th>
              </tr>
            </thead>
            <tbody>
              {items.map((it, i) => <Row key={it.trade_id ?? `r${i}`} it={it} />)}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

function Th({ children, right }: { children: React.ReactNode; right?: boolean }) {
  return (
    <th style={{ textAlign: right ? 'right' : 'left', fontSize: 9, fontWeight: 700, letterSpacing: '.06em',
      color: C.dim, padding: '7px 10px', borderBottom: `1px solid ${C.border}`, whiteSpace: 'nowrap' }}>{children}</th>
  )
}

function Arrow() {
  return <span style={{ color: C.accentBright, fontSize: 18, lineHeight: 1, flexShrink: 0, opacity: 0.7 }}>→</span>
}

function Row({ it }: { it: PipelineItem }) {
  const st = STAGE[it.stage] ?? STAGE.closed
  const pnlCol = it.pnl == null ? C.muted : it.pnl >= 0 ? C.green : C.red
  const when = it.stage === 'rejected' || it.stage === 'open' ? it.opened_at : it.closed_at
  const td: React.CSSProperties = { padding: '7px 10px', fontSize: 11, borderBottom: `1px solid ${C.border}`, whiteSpace: 'nowrap' }
  const tdR: React.CSSProperties = { ...td, textAlign: 'right' }
  return (
    <tr>
      {/* stage colour as an inset shadow (does not shift the cell like a tr
          border-left does under border-collapse — that was the misalignment) */}
      <td style={{ ...td, paddingLeft: 10, boxShadow: `inset 2px 0 0 0 ${st.color}` }}><span style={{ fontSize: 9, fontWeight: 700, color: it.segment === 'FNO' ? C.warn : C.steel }}>{it.segment}</span></td>
      <td style={{ ...td, color: C.text, fontWeight: 600, maxWidth: 150, overflow: 'hidden', textOverflow: 'ellipsis' }}>{it.symbol}</td>
      <td style={{ ...td, color: it.side === 'BUY' ? C.green : it.side === 'SELL' ? C.red : C.muted, fontWeight: 600 }}>{it.side || '—'}</td>
      <td style={{ ...td, color: C.sub }}>{it.strategy || '—'}</td>
      <td style={td}>
        <span style={{ fontSize: 9, fontWeight: 700, color: st.color, background: `${st.color}1A`, border: `1px solid ${st.color}40`, borderRadius: 3, padding: '2px 7px' }}>{st.label}</span>
      </td>
      <td style={{ ...td, color: C.muted, fontSize: 10, maxWidth: 170, overflow: 'hidden', textOverflow: 'ellipsis' }}>{it.exit_reason ?? ''}</td>
      <td style={{ ...tdR, color: C.sub }}>{it.qty ?? '—'}</td>
      <td style={{ ...tdR, color: C.sub }}>{it.entry != null ? it.entry.toFixed(2) : '—'}</td>
      <td style={{ ...tdR, color: C.sub }}>{it.exit != null ? it.exit.toFixed(2) : '—'}</td>
      <td style={{ ...tdR, color: pnlCol, fontWeight: 700 }}>{it.pnl != null ? fmtINR(it.pnl) : '—'}</td>
      <td style={{ ...tdR, color: C.dim, fontSize: 10 }}>{ago(when)}</td>
    </tr>
  )
}
