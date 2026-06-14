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
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2, position: 'relative' }}>
      <span style={{ fontSize: 18, fontWeight: 700, color, fontVariantNumeric: 'tabular-nums' }}>{n}</span>
      <span style={{ fontSize: 8.5, color: C.dim, letterSpacing: '.06em' }}>{label}</span>
      {drop != null && drop > 0 && (
        <span style={{ position: 'absolute', top: -2, right: 2, fontSize: 8, color: C.red }}>−{drop}</span>
      )}
    </div>
  )
}

export default function TradePipelinePanel({ defaultSegment = 'ALL', compact = false }:
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
        TRADE PIPELINE <span style={{ color: '#4A4F57', fontSize: 9 }}>SIGNAL → GATE → OPEN → SETTLED</span>
        <span style={{ marginLeft: 'auto', display: 'inline-flex', gap: 2 }}>
          {(['ALL', 'EQ', 'FNO'] as const).map(s => (
            <button key={s} onClick={() => setSeg(s)}
              style={{ fontSize: 9, fontWeight: 700, padding: '2px 8px', borderRadius: 3, cursor: 'pointer', border: 'none',
                background: seg === s ? C.accent : 'transparent', color: seg === s ? '#fff' : C.muted }}>{s}</button>
          ))}
        </span>
      </div>

      {/* Funnel */}
      {f && (
        <div style={{ display: 'flex', alignItems: 'center', padding: '10px 12px', borderBottom: `1px solid ${C.border}`, flexShrink: 0 }}>
          <FunnelBox label="SIGNALED" n={f.signaled} color={C.text} />
          <Arrow />
          <FunnelBox label="APPROVED" n={f.approved} color={C.blue} drop={f.rejected} />
          <Arrow />
          <FunnelBox label="OPEN" n={f.open} color={C.accentBright} />
          <Arrow />
          <FunnelBox label="CLOSED" n={f.closed} color={C.teal} />
        </div>
      )}

      {/* Lifecycle list */}
      <div className="panel-body" style={{ flex: 1, minHeight: 0, overflow: 'auto', padding: 6 }}>
        {items.length === 0 ? (
          <div style={{ padding: 24, textAlign: 'center', fontSize: 10.5, color: C.muted }}>
            No recent trade activity{seg !== 'ALL' ? ` for ${seg}` : ''}.
          </div>
        ) : items.map((it, i) => <Row key={it.trade_id ?? `r${i}`} it={it} compact={compact} />)}
      </div>
    </div>
  )
}

function Arrow() {
  return <span style={{ color: C.dim, fontSize: 13, padding: '0 2px', flexShrink: 0 }}>→</span>
}

function Row({ it, compact }: { it: PipelineItem; compact: boolean }) {
  const st = STAGE[it.stage] ?? STAGE.closed
  const pnlCol = it.pnl == null ? C.muted : it.pnl >= 0 ? C.green : C.red
  const when = it.stage === 'rejected' || it.stage === 'open' ? it.opened_at : it.closed_at
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 8px', marginBottom: 4,
      background: C.card, border: `1px solid ${C.border}`, borderRadius: 4, borderLeft: `2px solid ${st.color}` }}>
      <span style={{ fontSize: 8, fontWeight: 700, color: it.segment === 'FNO' ? C.warn : C.steel, width: 26, flexShrink: 0 }}>{it.segment}</span>
      <span style={{ fontSize: 10.5, fontWeight: 600, color: C.text, minWidth: 0, flex: compact ? 1 : 0, width: compact ? undefined : 130, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{it.symbol}</span>
      <span style={{ fontSize: 9, color: it.side === 'BUY' ? C.green : it.side === 'SELL' ? C.red : C.muted, width: 30, flexShrink: 0 }}>{it.side}</span>
      {!compact && <span style={{ fontSize: 9, color: C.muted, width: 44, flexShrink: 0 }}>{it.strategy}</span>}
      <span style={{ fontSize: 8.5, fontWeight: 700, color: st.color, background: `${st.color}14`, border: `1px solid ${st.color}33`, borderRadius: 3, padding: '1px 6px', flexShrink: 0 }}>{st.label}</span>
      {it.exit_reason && it.stage !== 'open' && <span style={{ fontSize: 8.5, color: C.dim, flexShrink: 0 }}>{it.exit_reason}</span>}
      <span style={{ marginLeft: 'auto', fontSize: 10, fontWeight: 600, color: pnlCol, fontVariantNumeric: 'tabular-nums', flexShrink: 0 }}>
        {it.pnl != null ? fmtINR(it.pnl) : ''}
      </span>
      <span style={{ fontSize: 8.5, color: C.dim, width: 26, textAlign: 'right', flexShrink: 0 }}>{ago(when)}</span>
    </div>
  )
}
