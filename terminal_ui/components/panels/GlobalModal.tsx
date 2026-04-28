'use client'
import { useEffect, useRef, useState } from 'react'
import { api, type GlobalQuote } from '@/lib/api'

type Row = Record<string, number | string>

function Sparkline({ rows, up }: { rows: Row[]; up: boolean }) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    if (!canvasRef.current || rows.length < 2) return
    const canvas = canvasRef.current
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    const closes = rows.map(r => Number(r.close)).filter(Boolean)
    if (closes.length < 2) return
    const w = canvas.width, h = canvas.height
    const min = Math.min(...closes), max = Math.max(...closes)
    const range = max - min || 1
    const color = up ? '#00C853' : '#D32F2F'
    ctx.clearRect(0, 0, w, h)
    const grad = ctx.createLinearGradient(0, 0, 0, h)
    grad.addColorStop(0, color + '30')
    grad.addColorStop(1, color + '00')
    ctx.beginPath()
    closes.forEach((c, i) => {
      const x = (i / (closes.length - 1)) * w
      const y = h - ((c - min) / range) * (h - 8) - 4
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)
    })
    ctx.lineTo(w, h); ctx.lineTo(0, h); ctx.closePath()
    ctx.fillStyle = grad; ctx.fill()
    ctx.beginPath()
    closes.forEach((c, i) => {
      const x = (i / (closes.length - 1)) * w
      const y = h - ((c - min) / range) * (h - 8) - 4
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)
    })
    ctx.strokeStyle = color; ctx.lineWidth = 1.5; ctx.stroke()
  }, [rows, up])
  return <canvas ref={canvasRef} width={480} height={80} style={{ width: '100%', height: 80, display: 'block' }} />
}

const CATEGORY_LABEL: Record<string, string> = {
  global: 'Global Index', fx: 'FX Rate (vs INR)', commod: 'Commodity',
  risk: 'Risk Indicator', bse: 'BSE Index',
}

export default function GlobalModal({ quote, onClose }: { quote: GlobalQuote; onClose: () => void }) {
  const [history, setHistory] = useState<Row[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.globalHistory(quote.symbol)
      .then(d => { setHistory(d); setLoading(false) })
      .catch(() => setLoading(false))
  }, [quote.symbol])

  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [onClose])

  const up = quote.change >= 0
  const chgColor = up ? '#00C853' : '#D32F2F'
  const fmt = (v: number) =>
    quote.category === 'fx' ? v.toFixed(4) : v.toLocaleString('en-IN', { maximumFractionDigits: 2 })

  const high90 = history.length ? Math.max(...history.map(r => Number(r.high))) : null
  const low90  = history.length ? Math.min(...history.map(r => Number(r.low)))  : null
  const oldest = history.length ? Number(history[0].close) : null
  const ret90  = oldest && oldest > 0 ? ((quote.price - oldest) / oldest * 100) : null

  return (
    <div
      style={{ position: 'fixed', inset: 0, zIndex: 1000, background: 'rgba(0,0,0,0.80)', backdropFilter: 'blur(3px)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
      onClick={onClose}
    >
      <div
        style={{ background: '#0C0C0C', border: '1px solid #2A2A2A', borderRadius: 6, width: 520, maxHeight: '80vh', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div style={{ padding: '14px 18px', borderBottom: '1px solid #1A1A1A', display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 4 }}>
              <span style={{ fontSize: 13, fontWeight: 700, color: '#E0E0E0', letterSpacing: '0.06em' }}>{quote.label}</span>
              <span style={{ fontSize: 22, fontWeight: 700, color: '#F0F0F0', fontVariantNumeric: 'tabular-nums' }}>{fmt(quote.price)}</span>
              <span style={{ fontSize: 13, fontWeight: 600, color: chgColor }}>
                {up ? '+' : ''}{quote.change.toFixed(2)}%
              </span>
            </div>
            <span style={{ fontSize: 9, color: '#333', letterSpacing: '0.06em' }}>{CATEGORY_LABEL[quote.category] ?? quote.category.toUpperCase()} · {quote.symbol} · DELAYED</span>
          </div>
          <button onClick={onClose} style={{ color: '#444', background: 'none', border: 'none', cursor: 'pointer', fontSize: 20, lineHeight: 1 }}>✕</button>
        </div>

        {/* Stats row */}
        {(high90 !== null) && (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', borderBottom: '1px solid #1A1A1A' }}>
            {[
              { label: '90d High', value: fmt(high90!) },
              { label: '90d Low',  value: fmt(low90!)  },
              { label: '90d Return', value: ret90 !== null ? `${ret90 > 0 ? '+' : ''}${ret90.toFixed(2)}%` : '—', color: ret90 !== null ? (ret90 >= 0 ? '#00C853' : '#D32F2F') : undefined },
            ].map(({ label, value, color }) => (
              <div key={label} style={{ padding: '8px 14px', borderRight: '1px solid #1A1A1A' }}>
                <div style={{ fontSize: 8, color: '#444', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 3 }}>{label}</div>
                <div style={{ fontSize: 12, fontWeight: 600, color: color ?? '#C0C0C0', fontVariantNumeric: 'tabular-nums' }}>{value}</div>
              </div>
            ))}
          </div>
        )}

        {/* Sparkline */}
        <div style={{ padding: '12px 18px', borderBottom: '1px solid #1A1A1A' }}>
          <div style={{ fontSize: 9, color: '#333', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8 }}>90-Day Price</div>
          {loading
            ? <div style={{ height: 80, display: 'flex', alignItems: 'center', justifyContent: 'center' }}><span style={{ fontSize: 10, color: '#333' }}>loading…</span></div>
            : history.length < 2
              ? <div style={{ height: 80, display: 'flex', alignItems: 'center', justifyContent: 'center' }}><span style={{ fontSize: 10, color: '#333' }}>no history</span></div>
              : <Sparkline rows={history} up={up} />
          }
        </div>

        {/* Date range footer */}
        {history.length > 0 && (
          <div style={{ padding: '6px 18px', display: 'flex', justifyContent: 'space-between' }}>
            <span style={{ fontSize: 8, color: '#2A2A2A' }}>{String(history[0].date)}</span>
            <span style={{ fontSize: 8, color: '#2A2A2A' }}>{String(history[history.length - 1].date)}</span>
          </div>
        )}
      </div>
    </div>
  )
}
