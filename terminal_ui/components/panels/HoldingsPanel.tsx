'use client'
// HOLDINGS — the portfolio statement panel (PRD P2), shared by EQUITIES and
// F&O. One source of truth: /api/portfolio/holdings (same assembly that
// writes data/portfolio.md). Marks refresh with live ticks.
import React, { useEffect, useState } from 'react'
import { useTickMap } from '@/hooks/useSocket'

type Holding = {
  token: number; symbol: string; side: string; product: string
  quantity: number; entry_price: number; mark: number
  unrealized: number; unrealized_pct: number
  stop_loss: number; target: number; strategy_id?: string
}
type Statement = {
  equity: number; cash: number; deployed: number
  unrealized: number; realized_today: number; peak_equity: number
  holdings: Holding[]
}

const INDEX_TOKENS = new Set([256265, 260105, 257801, 264969])
const inr = (v: number, dec = 0) =>
  v.toLocaleString('en-IN', { minimumFractionDigits: dec, maximumFractionDigits: dec })

function Metric({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div style={{ minWidth: 0 }}>
      <div style={{ fontSize: 9, color: '#71767F', letterSpacing: '0.08em', textTransform: 'uppercase' }}>{label}</div>
      <div style={{ fontSize: 13.5, fontWeight: 700, color: color ?? '#ECEEF1', fontVariantNumeric: 'tabular-nums' }}>{value}</div>
    </div>
  )
}

export default function HoldingsPanel({ segment }: { segment: 'EQ' | 'FNO' }) {
  const [stmt, setStmt] = useState<Statement | null>(null)
  const ticks = useTickMap()

  useEffect(() => {
    let alive = true
    const load = () =>
      fetch('/api/portfolio/holdings').then(r => r.json())
        .then(d => { if (alive && d?.holdings) setStmt(d) }).catch(() => {})
    load()
    const t = setInterval(load, 15000)
    return () => { alive = false; clearInterval(t) }
  }, [])

  const rows = (stmt?.holdings ?? []).filter(h =>
    segment === 'FNO' ? INDEX_TOKENS.has(h.token) : !INDEX_TOKENS.has(h.token))

  // live re-mark from the socket between refreshes
  const marked = rows.map(h => {
    const live = ticks[h.token]?.last_price
    const mark = live && live > 0 ? live : h.mark
    const sign = h.side === 'BUY' ? 1 : -1
    const upnl = sign * (mark - h.entry_price) * h.quantity
    const notional = h.entry_price * h.quantity
    return { ...h, mark, unrealized: upnl, unrealized_pct: notional ? (upnl / notional) * 100 : 0 }
  })
  const unrealized = marked.reduce((a, h) => a + h.unrealized, 0)

  return (
    <div className="panel">
      <div className="panel-header">
        HOLDINGS <span style={{ color: '#4A4F57' }}>{segment === 'EQ' ? 'CASH · CNC/MIS' : 'INDEX COMPLEX'}</span>
      </div>
      <div className="panel-body" style={{ padding: 0 }}>
        {stmt && segment === 'EQ' && (
          <div style={{
            display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 10,
            padding: '10px 12px', borderBottom: '1px solid #23272E',
          }}>
            <Metric label="Equity" value={`₹${inr(stmt.equity)}`} />
            <Metric label="Cash" value={`₹${inr(stmt.cash)}`} />
            <Metric label="Deployed" value={`₹${inr(stmt.deployed)}`} />
            <Metric label="Unrealized" value={`${unrealized >= 0 ? '+' : ''}${inr(unrealized)}`}
              color={unrealized >= 0 ? '#2DBD80' : '#F2495C'} />
            <Metric label="Realized today" value={`${stmt.realized_today >= 0 ? '+' : ''}${inr(stmt.realized_today)}`}
              color={stmt.realized_today >= 0 ? '#2DBD80' : '#F2495C'} />
          </div>
        )}

        {stmt && segment === 'EQ' && (() => {
          // ── COMPOSITION — where the equity actually sits ──
          const palette = ['#0094FB', '#00B9FC', '#006FF9', '#004AF8', '#2DBD80', '#FFB02E']
          const segs = marked.map((h, i) => ({
            label: h.symbol,
            value: Math.abs(h.mark * h.quantity),
            color: palette[i % palette.length],
          }))
          const cash = Math.max(stmt.cash, 0)
          const total = segs.reduce((a, x) => a + x.value, 0) + cash
          if (total <= 0) return null
          const all = [...segs, { label: 'CASH', value: cash, color: '#2A2E36' }]
          return (
            <div style={{ padding: '10px 12px', borderBottom: '1px solid #23272E' }}>
              <div style={{ fontSize: 9, color: '#71767F', letterSpacing: '0.08em', marginBottom: 6 }}>
                COMPOSITION <span style={{ color: '#4A4F57' }}>· % OF EQUITY AT MARK</span>
              </div>
              <div style={{ display: 'flex', height: 14, borderRadius: 4, overflow: 'hidden', border: '1px solid #23272E' }}>
                {all.map(s => s.value > 0 && (
                  <div key={s.label} title={`${s.label} ${(s.value / total * 100).toFixed(1)}%`}
                    style={{ width: `${(s.value / total) * 100}%`, background: s.color, minWidth: s.value > 0 ? 2 : 0 }} />
                ))}
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginTop: 6 }}>
                {all.map(s => s.value > 0 && (
                  <span key={s.label} style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 9.5, color: '#AEB3BB' }}>
                    <span style={{ width: 7, height: 7, borderRadius: 2, background: s.color, display: 'inline-block' }} />
                    {s.label} <span style={{ color: '#71767F', fontVariantNumeric: 'tabular-nums' }}>{(s.value / total * 100).toFixed(1)}%</span>
                  </span>
                ))}
              </div>
            </div>
          )
        })()}

        {marked.length === 0 ? (
          <div style={{ padding: '18px 12px', fontSize: 11, color: '#71767F' }}>
            {segment === 'FNO'
              ? 'No derivative positions. F&O execution (contract chain, lot fills, SPAN margin) arrives in Phase 2 — index signals route through NIFTYBEES until then.'
              : 'Flat — no open cash positions.'}
          </div>
        ) : (
          <table style={{ width: '100%' }}>
            <thead>
              <tr>
                {['SYMBOL', 'SIDE', 'PRODUCT', 'QTY', 'ENTRY', 'MARK', 'UNREAL P&L', '%', 'STOP', 'TARGET'].map(h => (
                  <th key={h} style={{ textAlign: h === 'SYMBOL' ? 'left' : 'right', padding: '6px 10px' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {marked.map(h => (
                <tr key={`${h.token}-${h.side}`}>
                  <td style={{ padding: '6px 10px', fontWeight: 600, color: '#ECEEF1' }}>{h.symbol}</td>
                  <td style={{ textAlign: 'right', color: h.side === 'BUY' ? '#2DBD80' : '#F2495C', fontWeight: 600 }}>{h.side}</td>
                  <td style={{ textAlign: 'right' }}>
                    <span style={{
                      fontSize: 9, padding: '1px 6px', borderRadius: 4, letterSpacing: '0.06em',
                      color: h.product === 'MIS' ? '#FFB02E' : '#0094FB',
                      border: `1px solid ${h.product === 'MIS' ? '#FFB02E44' : '#0094FB44'}`,
                    }}>{h.product}</span>
                  </td>
                  <td style={{ textAlign: 'right' }}>{h.quantity}</td>
                  <td style={{ textAlign: 'right' }}>{inr(h.entry_price, 2)}</td>
                  <td style={{ textAlign: 'right', color: '#ECEEF1' }}>{inr(h.mark, 2)}</td>
                  <td style={{ textAlign: 'right', fontWeight: 700, color: h.unrealized >= 0 ? '#2DBD80' : '#F2495C' }}>
                    {h.unrealized >= 0 ? '+' : ''}{inr(h.unrealized)}
                  </td>
                  <td style={{ textAlign: 'right', color: h.unrealized_pct >= 0 ? '#2DBD80' : '#F2495C' }}>
                    {h.unrealized_pct >= 0 ? '+' : ''}{h.unrealized_pct.toFixed(2)}%
                  </td>
                  <td style={{ textAlign: 'right', color: '#71767F' }}>{h.stop_loss ? inr(h.stop_loss, 2) : '—'}</td>
                  <td style={{ textAlign: 'right', color: '#71767F' }}>{h.target ? inr(h.target, 2) : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
