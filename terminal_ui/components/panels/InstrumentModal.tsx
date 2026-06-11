'use client'
import { useEffect, useRef, useState } from 'react'
import { api, type NewsItem } from '@/lib/api'
import { useTickMap, useSocketList } from '@/hooks/useSocket'
import Badge from '@/components/primitives/Badge'

type SignalEntry = {
  strategy_id: string
  side: string
  instrument_id: number
  confidence: number
  regime: string
  stop_loss?: number
  target?: number
  ts?: number
}

type Lens = {
  strategy: string
  name: string
  side: string
  triggered: boolean
  detail: string
  confidence: number
}

type Analysis = {
  symbol: string
  price: number
  regime: string
  verdict: string
  verdict_color: string
  summary: string
  indicators: {
    rsi_14: number
    ema_20: number
    ema_50: number
    atr_14: number
    high_52w: number
    low_52w: number
    ret_20d_pct: number
    vol_vs_avg: number
    india_vix: number
  }
  suggested_sl: number
  suggested_target: number
  lenses: Lens[]
}

type Props = {
  token: number
  label: string
  onClose: () => void
  onChartSelect?: (symbolIdx: number) => void
}

const CHART_SYMBOL_IDX: Record<number, number> = {
  256265: 0, 260105: 1, 257801: 2,
  738561: 3, 341249: 4, 2953217: 5,
}

// Map NSE display label → internal symbol key for the analyse endpoint
const LABEL_TO_SYMBOL: Record<string, string> = {
  'NIFTY 50':   'NIFTY 50',
  'BANKNIFTY':  'NIFTY BANK',
  'FINNIFTY':   'NIFTY FIN SERVICE',
}

function IndicatorCell({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div style={{ padding: '6px 10px', borderRight: '1px solid #20242B', borderBottom: '1px solid #20242B' }}>
      <div style={{ fontSize: 9.5, color: '#5F6772', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 3 }}>{label}</div>
      <div style={{ fontSize: 11.5, fontWeight: 600, color: color ?? '#C3CAD3', fontVariantNumeric: 'tabular-nums' }}>{value}</div>
    </div>
  )
}

export default function InstrumentModal({ token, label, onClose, onChartSelect }: Props) {
  const ticks      = useTickMap()
  const allSignals = useSocketList<SignalEntry>('strategy_signal', 30)
  const [news, setNews]         = useState<NewsItem[]>([])
  const [ohlcv, setOhlcv]       = useState<Record<string, number | string>[]>([])
  const [analysis, setAnalysis] = useState<Analysis | null>(null)
  const [loading, setLoading]   = useState(true)
  const canvasRef = useRef<HTMLCanvasElement>(null)

  const tick  = ticks[token]
  const price = tick?.last_price ?? 0
  const chg   = tick?.change     ?? 0
  const open  = tick?.open       ?? 0

  const signals = allSignals.filter(s => s.instrument_id === token)

  const apiSymbol = LABEL_TO_SYMBOL[label] ?? label

  useEffect(() => {
    const words = label.toLowerCase().split(' ')
    setLoading(true)
    Promise.all([
      api.news(50).then(items =>
        setNews(items.filter(n =>
          n.instruments?.some(inst => words.some(w => inst.toLowerCase().includes(w)))
        ))
      ).catch(() => {}),
      api.ohlcv(encodeURIComponent(apiSymbol), '1d', 60).then(setOhlcv).catch(() => {}),
      api.analyse(apiSymbol).then(d => setAnalysis(d as unknown as Analysis)).catch(() => {}),
    ]).finally(() => setLoading(false))
  }, [token, label, apiSymbol])

  // Close on Escape
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [onClose])

  // Draw sparkline
  useEffect(() => {
    if (!canvasRef.current || ohlcv.length < 2) return
    const canvas = canvasRef.current
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    const closes = ohlcv.map(r => Number(r.close)).filter(Boolean)
    if (closes.length < 2) return
    const w = canvas.width, h = canvas.height
    const min = Math.min(...closes), max = Math.max(...closes)
    const range = max - min || 1
    const color = chg >= 0 ? '#2FBF71' : '#E5484D'
    ctx.clearRect(0, 0, w, h)
    const grad = ctx.createLinearGradient(0, 0, 0, h)
    grad.addColorStop(0, color + '40')
    grad.addColorStop(1, color + '00')
    ctx.beginPath()
    closes.forEach((c, i) => {
      const x = (i / (closes.length - 1)) * w
      const y = h - ((c - min) / range) * (h - 6) - 3
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)
    })
    ctx.lineTo(w, h); ctx.lineTo(0, h); ctx.closePath()
    ctx.fillStyle = grad; ctx.fill()
    ctx.beginPath()
    closes.forEach((c, i) => {
      const x = (i / (closes.length - 1)) * w
      const y = h - ((c - min) / range) * (h - 6) - 3
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)
    })
    ctx.strokeStyle = color; ctx.lineWidth = 1.5; ctx.stroke()
  }, [ohlcv, chg])

  const chartIdx = CHART_SYMBOL_IDX[token]
  const ind = analysis?.indicators
  const high30 = ohlcv.length ? Math.max(...ohlcv.map(r => Number(r.high))) : 0
  const low30  = ohlcv.length ? Math.min(...ohlcv.map(r => Number(r.low)))  : 0

  return (
    <div
      style={{ position: 'fixed', inset: 0, zIndex: 1000, background: 'rgba(0,0,0,0.85)', backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
      onClick={onClose}
    >
      <div
        style={{ background: '#0F1114', border: '1px solid #3C424B', borderRadius: 6, width: '92vw', maxWidth: 1100, maxHeight: '92vh', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}
        onClick={e => e.stopPropagation()}
      >
        {/* ── Header ─────────────────────────────────────────────── */}
        <div style={{ padding: '14px 18px', borderBottom: '1px solid #2B303A', display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexShrink: 0 }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 6 }}>
              <span style={{ fontSize: 14, fontWeight: 700, color: '#E6E9ED', letterSpacing: '0.08em' }}>{label}</span>
              <span style={{ fontSize: 22, fontWeight: 700, color: '#F0F0F0', fontVariantNumeric: 'tabular-nums' }}>
                {price > 0 ? price.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—'}
              </span>
              <span style={{ fontSize: 13, fontWeight: 600, color: chg >= 0 ? '#2FBF71' : '#E5484D' }}>
                {price > 0 ? `${chg >= 0 ? '+' : ''}${chg.toFixed(2)}%` : ''}
              </span>
            </div>
            {analysis && !loading && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <span style={{ fontSize: 13, fontWeight: 700, color: analysis.verdict_color, letterSpacing: '0.12em' }}>
                  {analysis.verdict}
                </span>
                <span style={{ fontSize: 10, color: '#5F6772', maxWidth: 500 }}>{analysis.summary}</span>
              </div>
            )}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
            {chartIdx !== undefined && onChartSelect && (
              <button
                onClick={() => { onChartSelect(chartIdx); onClose() }}
                style={{ fontSize: 10, padding: '4px 12px', background: '#20242B', border: '1px solid #333', borderRadius: 3, color: '#4E80B4', cursor: 'pointer', letterSpacing: '0.06em' }}
              >
                LOAD CHART
              </button>
            )}
            <button onClick={onClose} style={{ color: '#5F6772', background: 'none', border: 'none', cursor: 'pointer', fontSize: 20, lineHeight: 1 }}>✕</button>
          </div>
        </div>

        {/* ── Two-column body ─────────────────────────────────────── */}
        <div style={{ flex: 1, overflowY: 'auto', scrollbarWidth: 'thin', scrollbarColor: '#2B303A transparent', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 0 }}>

          {/* ─ LEFT COLUMN ─ */}
          <div style={{ borderRight: '1px solid #20242B' }}>

            {/* Price stats grid */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', borderBottom: '1px solid #20242B' }}>
              <IndicatorCell label="Open"     value={open   > 0 ? open.toLocaleString('en-IN',   { maximumFractionDigits: 2 }) : '—'} />
              <IndicatorCell label="30d High" value={high30 > 0 ? high30.toLocaleString('en-IN', { maximumFractionDigits: 0 }) : '—'} />
              <IndicatorCell label="30d Low"  value={low30  > 0 ? low30.toLocaleString('en-IN',  { maximumFractionDigits: 0 }) : '—'} />
              <IndicatorCell label="Regime"   value={analysis?.regime?.toUpperCase() ?? '—'} color="#4E80B4" />
            </div>

            {/* Indicators */}
            {ind && (
              <div style={{ borderBottom: '1px solid #20242B' }}>
                <div style={{ padding: '6px 10px', fontSize: 10, color: '#5F6772', textTransform: 'uppercase', letterSpacing: '0.06em', borderBottom: '1px solid #20242B' }}>Technical Indicators</div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)' }}>
                  <IndicatorCell label="RSI-14" value={ind.rsi_14.toFixed(1)} color={ind.rsi_14 < 35 ? '#2FBF71' : ind.rsi_14 > 65 ? '#E5484D' : '#C3CAD3'} />
                  <IndicatorCell label="EMA 20" value={ind.ema_20.toLocaleString('en-IN', { maximumFractionDigits: 0 })} />
                  <IndicatorCell label="EMA 50" value={ind.ema_50.toLocaleString('en-IN', { maximumFractionDigits: 0 })} />
                  <IndicatorCell label="ATR-14" value={ind.atr_14.toFixed(0)} />
                  <IndicatorCell label="52W High" value={ind.high_52w.toLocaleString('en-IN', { maximumFractionDigits: 0 })} />
                  <IndicatorCell label="52W Low" value={ind.low_52w.toLocaleString('en-IN', { maximumFractionDigits: 0 })} />
                  <IndicatorCell label="20d Return" value={`${ind.ret_20d_pct > 0 ? '+' : ''}${ind.ret_20d_pct.toFixed(1)}%`} color={ind.ret_20d_pct > 0 ? '#2FBF71' : '#E5484D'} />
                  <IndicatorCell label="Vol vs Avg" value={`${ind.vol_vs_avg.toFixed(2)}×`} color={ind.vol_vs_avg > 1.5 ? '#4E80B4' : '#C3CAD3'} />
                  <IndicatorCell label="India VIX" value={ind.india_vix.toFixed(1)} color={ind.india_vix > 20 ? '#E5484D' : '#C3CAD3'} />
                </div>
                {analysis && (
                  <div style={{ padding: '8px 10px', borderTop: '1px solid #20242B', display: 'flex', gap: 16, fontSize: 10 }}>
                    <span style={{ color: '#5F6772' }}>SL <span style={{ color: '#E5484D', fontWeight: 600 }}>{analysis.suggested_sl.toLocaleString('en-IN', { maximumFractionDigits: 0 })}</span></span>
                    <span style={{ color: '#5F6772' }}>Target <span style={{ color: '#2FBF71', fontWeight: 600 }}>{analysis.suggested_target.toLocaleString('en-IN', { maximumFractionDigits: 0 })}</span></span>
                    <span style={{ color: '#5F6772' }}>R:R <span style={{ color: '#9BA3AD' }}>{price > 0 && analysis.suggested_sl !== price ? ((analysis.suggested_target - price) / Math.abs(price - analysis.suggested_sl)).toFixed(1) : '—'}</span></span>
                  </div>
                )}
              </div>
            )}

            {/* 60-day sparkline */}
            {ohlcv.length > 2 && (
              <div style={{ padding: '10px', borderBottom: '1px solid #20242B' }}>
                <div style={{ fontSize: 10, color: '#5F6772', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6 }}>60-Day Price</div>
                <canvas ref={canvasRef} width={500} height={64} style={{ width: '100%', height: 64, display: 'block' }} />
              </div>
            )}

            {/* Live strategy signals */}
            <div style={{ padding: '10px' }}>
              <div style={{ fontSize: 10, color: '#5F6772', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8 }}>Live Signals</div>
              {signals.length === 0
                ? <p style={{ fontSize: 10.5, color: '#3C424B', margin: 0 }}>No active signals — engine evaluates every 60s</p>
                : signals.map((s, i) => (
                    <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6, fontSize: 10.5, flexWrap: 'wrap' }}>
                      <span style={{ color: '#4E80B4', minWidth: 32, fontWeight: 600 }}>{s.strategy_id}</span>
                      <Badge variant="side" value={s.side} />
                      <span style={{ color: '#6E7682' }}>{(s.confidence * 100).toFixed(0)}%</span>
                      {s.target    && <span style={{ color: '#2FBF71' }}>T {s.target.toFixed(0)}</span>}
                      {s.stop_loss && <span style={{ color: '#E5484D' }}>SL {s.stop_loss.toFixed(0)}</span>}
                    </div>
                  ))
              }
            </div>
          </div>

          {/* ─ RIGHT COLUMN ─ */}
          <div>
            {/* Strategy analysis lenses */}
            <div style={{ borderBottom: '1px solid #20242B' }}>
              <div style={{ padding: '6px 10px', fontSize: 10, color: '#5F6772', textTransform: 'uppercase', letterSpacing: '0.06em', borderBottom: '1px solid #20242B' }}>
                Strategy Analysis
                {loading && <span style={{ color: '#3C424B', marginLeft: 8 }}>computing…</span>}
              </div>
              {!analysis && !loading && (
                <p style={{ padding: '10px', fontSize: 10.5, color: '#3C424B', margin: 0 }}>No analysis available</p>
              )}
              {analysis?.lenses.map((lens, i) => (
                <div
                  key={i}
                  style={{
                    padding: '10px', borderBottom: '1px solid #111',
                    borderLeft: `3px solid ${lens.triggered ? (lens.side === 'BUY' ? '#2FBF71' : lens.side === 'SELL' ? '#E5484D' : '#4E80B4') : '#20242B'}`,
                    opacity: lens.triggered ? 1 : 0.5,
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                    <span style={{ fontSize: 10, fontWeight: 700, color: '#4E80B4' }}>{lens.strategy}</span>
                    <span style={{ fontSize: 10, color: '#5F6772' }}>{lens.name}</span>
                    {lens.triggered && <Badge variant="side" value={lens.side} />}
                    {!lens.triggered && <span style={{ fontSize: 9.5, color: '#3C424B' }}>NOT TRIGGERED</span>}
                    {lens.triggered && (
                      <span style={{ marginLeft: 'auto', fontSize: 10, color: lens.confidence >= 0.65 ? '#2FBF71' : '#4E80B4' }}>
                        {(lens.confidence * 100).toFixed(0)}%
                      </span>
                    )}
                  </div>
                  <p style={{ margin: 0, fontSize: 10.5, color: '#777', lineHeight: 1.5 }}>{lens.detail}</p>
                </div>
              ))}
            </div>

            {/* Related news */}
            <div>
              <div style={{ padding: '6px 10px', fontSize: 10, color: '#5F6772', textTransform: 'uppercase', letterSpacing: '0.06em', borderBottom: '1px solid #20242B' }}>Related News</div>
              {news.length === 0
                ? <p style={{ padding: '10px', fontSize: 10.5, color: '#3C424B', margin: 0 }}>No related news for {label}</p>
                : news.slice(0, 8).map((n, i) => (
                    <div
                      key={i}
                      style={{
                        padding: '8px 10px', borderBottom: '1px solid #111',
                        borderLeft: `2px solid ${n.sentiment === 'positive' ? '#2FBF7160' : n.sentiment === 'negative' ? '#E5484D60' : '#3C424B'}`,
                      }}
                    >
                      <p style={{ margin: '0 0 3px', fontSize: 10.5, color: '#C8C8C8', lineHeight: 1.45 }}>{n.headline}</p>
                      <div style={{ display: 'flex', gap: 6, fontSize: 9.5, color: '#5F6772', alignItems: 'center' }}>
                        <span>{n.source}</span>
                        <span>·</span>
                        <span>{new Date(n.published_at).toLocaleDateString('en-IN')}</span>
                        <span style={{ color: n.impact === 'high' ? '#E5484D' : n.impact === 'medium' ? '#4E80B4' : '#5F6772', textTransform: 'uppercase' }}>{n.impact}</span>
                      </div>
                    </div>
                  ))
              }
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
