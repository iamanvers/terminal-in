'use client'
import { useEffect, useRef, useState } from 'react'
import { api } from '@/lib/api'
import { useTickMap } from '@/hooks/useSocket'

const SYMBOLS = [
  { label: 'NIFTY 50',  key: 'NIFTY 50',         token: 256265  },
  { label: 'BANKNIFTY', key: 'NIFTY BANK',        token: 260105  },
  { label: 'FINNIFTY',  key: 'NIFTY FIN SERVICE', token: 257801  },
  { label: 'RELIANCE',  key: 'RELIANCE',           token: 738561  },
  { label: 'HDFCBANK',  key: 'HDFCBANK',           token: 341249  },
  { label: 'TCS',       key: 'TCS',                token: 2953217 },
]
const TIMEFRAMES = ['1m', '5m', '1d']

// ── Helpers ───────────────────────────────────────────────────────────────────

function calcEMA(
  bars: { time: unknown; close: number }[],
  period: number,
): { time: unknown; value: number }[] {
  if (bars.length === 0) return []
  const k = 2 / (period + 1)
  const result: { time: unknown; value: number }[] = []
  let ema = bars[0].close
  for (const bar of bars) {
    ema = bar.close * k + ema * (1 - k)
    result.push({ time: bar.time, value: ema })
  }
  return result
}

function istMinutes(): number {
  const now = Date.now()
  const ist = new Date(now + 5.5 * 3600_000)
  return ist.getUTCHours() * 60 + ist.getUTCMinutes()
}

function isMarketOpen(): boolean {
  const now = new Date(Date.now() + 5.5 * 3600_000)
  const day = now.getUTCDay()
  if (day === 0 || day === 6) return false           // weekend
  const mins = now.getUTCHours() * 60 + now.getUTCMinutes()
  return mins >= 9 * 60 + 15 && mins < 15 * 60 + 30 // 09:15–15:30 IST
}

// localStorage cache — per symbol+tf, 5-minute TTL during market; 6-hour TTL at close
const CACHE_TTL_OPEN   = 5  * 60 * 1000
const CACHE_TTL_CLOSED = 6  * 60 * 60 * 1000

function cacheKey(symbol: string, tf: string) {
  return `chart_ohlcv_${symbol.replace(/\s/g, '_')}_${tf}`
}

function readCache(symbol: string, tf: string): Record<string, unknown>[] | null {
  try {
    const raw = localStorage.getItem(cacheKey(symbol, tf))
    if (!raw) return null
    const { rows, ts } = JSON.parse(raw)
    const ttl = isMarketOpen() ? CACHE_TTL_OPEN : CACHE_TTL_CLOSED
    if (Date.now() - ts > ttl) return null
    return rows
  } catch { return null }
}

function writeCache(symbol: string, tf: string, rows: Record<string, unknown>[]) {
  try {
    localStorage.setItem(cacheKey(symbol, tf), JSON.stringify({ rows, ts: Date.now() }))
  } catch { /* quota */ }
}

// ── Types / Props ─────────────────────────────────────────────────────────────

type Props = {
  symbolIdx?: number
  setSymbolIdx?: (idx: number) => void
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function ChartPanel({ symbolIdx: externalIdx, setSymbolIdx: externalSetIdx }: Props) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const chartRef      = useRef<any>(null)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const seriesRef     = useRef<any>(null)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const ema9Ref       = useRef<any>(null)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const ema21Ref      = useRef<any>(null)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const volRef        = useRef<any>(null)
  const containerRef  = useRef<HTMLDivElement>(null)
  const loadCtrRef    = useRef(0)      // increments on every fetch; aborts stale results

  const [internalIdx, setInternalIdx] = useState(0)
  const symbolIdx    = externalIdx    ?? internalIdx
  const setSymbolIdx = externalSetIdx ?? setInternalIdx

  const [tf,          setTf]        = useState('5m')
  const [chartReady,  setChartReady] = useState(false)
  const [loadState,   setLoadState] = useState<'idle' | 'cached' | 'loading' | 'live' | 'error'>('idle')
  const [lastUpdated, setLastUpdated] = useState<number | null>(null)
  const ticks = useTickMap()

  const symbol      = SYMBOLS[symbolIdx].key
  const symbolLabel = SYMBOLS[symbolIdx].label
  const marketOpen  = isMarketOpen()

  // ── Init chart (once) ───────────────────────────────────────────────────────
  useEffect(() => {
    if (!containerRef.current) return
    let cancelled = false
    let cleanup: (() => void) | undefined
    import('lightweight-charts').then(({ createChart, CrosshairMode }) => {
      if (cancelled || !containerRef.current) return
      const chart = createChart(containerRef.current, {
        layout: { background: { color: '#14161A' }, textColor: '#666666' },
        grid:   { vertLines: { color: '#20242B' }, horzLines: { color: '#20242B' } },
        crosshair: { mode: CrosshairMode.Normal },
        rightPriceScale: { borderColor: '#2B303A', scaleMargins: { top: 0.08, bottom: 0.22 } },
        timeScale: { borderColor: '#2B303A', timeVisible: true },
        width:  containerRef.current.clientWidth,
        height: containerRef.current.clientHeight,
      })
      const series = chart.addCandlestickSeries({
        upColor: '#2FBF71', downColor: '#E5484D',
        borderUpColor: '#2FBF71', borderDownColor: '#E5484D',
        wickUpColor: '#2FBF71', wickDownColor: '#E5484D',
      })
      const ema9  = chart.addLineSeries({ color: '#4E80B4', lineWidth: 1, priceLineVisible: false, lastValueVisible: false })
      const ema21 = chart.addLineSeries({ color: '#4488FF', lineWidth: 1, priceLineVisible: false, lastValueVisible: false })

      let vol: unknown = null
      try {
        vol = chart.addHistogramSeries({
          priceFormat: { type: 'volume' }, priceScaleId: 'vol',
          lastValueVisible: false, priceLineVisible: false,
        })
        chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.82, bottom: 0 }, visible: false })
      } catch { /* named price scales not supported */ }

      chartRef.current  = chart
      seriesRef.current = series
      ema9Ref.current   = ema9
      ema21Ref.current  = ema21
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      volRef.current    = vol as any
      setChartReady(true)

      const ro = new ResizeObserver(() => {
        if (!containerRef.current) return
        chart.applyOptions({ width: containerRef.current.clientWidth, height: containerRef.current.clientHeight })
      })
      ro.observe(containerRef.current)
      cleanup = () => { ro.disconnect(); chart.remove() }
    })
    return () => { cancelled = true; cleanup?.(); setChartReady(false) }
  }, [])

  // Update timeVisible when tf changes
  useEffect(() => {
    if (!chartReady || !chartRef.current) return
    chartRef.current.applyOptions({ timeScale: { timeVisible: tf !== '1d' } })
  }, [tf, chartReady])

  // ── Core data loader ────────────────────────────────────────────────────────
  useEffect(() => {
    if (!chartReady || !seriesRef.current) return

    const myLoad = ++loadCtrRef.current

    function applyRows(rows: Record<string, unknown>[], isStale: boolean) {
      if (!seriesRef.current || loadCtrRef.current !== myLoad) return
      if (!rows.length) return

      const isDaily = 'bucket_date' in (rows[0] ?? {})
      const timeKey = isDaily ? 'bucket_date' : 'bucket_time'
      const bars = rows
        .map(r => ({
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          time:   (isDaily
            ? Math.floor(new Date((r[timeKey] as string) + 'T00:00:00Z').getTime() / 1000)
            : Math.floor(Number(r[timeKey]) / 1000) + 19800) as any,
          open:   Number(r.open), high: Number(r.high),
          low:    Number(r.low),  close: Number(r.close),
          volume: Number(r.volume ?? 0),
        }))
        .sort((a, b) => a.time - b.time)

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      seriesRef.current.setData(bars as any)
      chartRef.current?.timeScale().fitContent()

      if (ema9Ref.current)  ema9Ref.current.setData(calcEMA(bars, 9))
      if (ema21Ref.current) ema21Ref.current.setData(calcEMA(bars, 21))
      if (volRef.current) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        volRef.current.setData(bars.map((b: any) => ({
          time: b.time, value: b.volume,
          color: b.close >= b.open ? '#2FBF7118' : '#E5484D18',
        })) as any)
      }

      setLoadState(isStale ? 'cached' : (marketOpen ? 'live' : 'idle'))
      if (!isStale) setLastUpdated(Date.now())
    }

    async function loadFresh() {
      setLoadState('loading')
      try {
        let rows = await api.ohlcv(encodeURIComponent(symbol), tf, 300)
        // Fallback to 1d if requested timeframe has no data yet
        if (!rows.length && tf !== '1d') {
          rows = await api.ohlcv(encodeURIComponent(symbol), '1d', 300)
        }
        if (loadCtrRef.current !== myLoad) return
        if (rows.length) {
          writeCache(symbol, tf, rows)
          applyRows(rows, false)
        } else {
          setLoadState('error')
        }
      } catch {
        if (loadCtrRef.current !== myLoad) return
        setLoadState('error')
      }
    }

    // 1. Serve cached data instantly (no flicker on symbol/tf switch)
    const cached = readCache(symbol, tf)
    if (cached?.length) {
      applyRows(cached, true)
    }

    // 2. Always fetch fresh async on top
    loadFresh()

    // 3. Auto-refresh: 30s if market is open at mount time, 5min if closed.
    //    isMarketOpen() is evaluated once here; symbol/tf/chartReady changes
    //    will re-run this effect, re-evaluating the interval at that point.
    const interval = setInterval(loadFresh, isMarketOpen() ? 30_000 : 300_000)
    return () => clearInterval(interval)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol, tf, chartReady])

  // ── Live tick → realtime candle (market-hours only) ────────────────────────
  useEffect(() => {
    if (!seriesRef.current || tf === '1d') return
    if (!isMarketOpen()) return   // don't append synthetic post-close bars
    const tick = ticks[SYMBOLS[symbolIdx].token]
    if (!tick?.last_price) return

    // Build the current-minute bucket in "IST epoch seconds"
    const nowMs   = Date.now()
    const barTime = Math.floor(nowMs / 1000) - (Math.floor(nowMs / 1000) % 60) + 19800
    try {
      seriesRef.current.update({
        time:  barTime,
        open:  Number(tick.last_price),
        high:  Number(tick.last_price),
        low:   Number(tick.last_price),
        close: Number(tick.last_price),
      })
    } catch { /* series not yet ready */ }
  }, [ticks, tf, symbolIdx])

  // ── Status badge ─────────────────────────────────────────────────────────────
  const badge = (() => {
    if (loadState === 'loading') return { text: 'UPDATING', color: '#9BA3AD', bg: '#14161A' }
    if (loadState === 'error')   return { text: 'NO DATA',  color: '#f87171', bg: '#1a0000' }
    if (loadState === 'cached')  return { text: 'CACHED',   color: '#fb923c', bg: '#1f1000' }
    if (marketOpen)              return { text: 'LIVE',     color: '#4ade80', bg: '#001a00' }
    return { text: 'CLOSED', color: '#5F6772', bg: '#14161A' }
  })()

  const age = lastUpdated
    ? (() => {
        const s = Math.floor((Date.now() - lastUpdated) / 1000)
        return s < 60 ? `${s}s ago` : `${Math.floor(s / 60)}m ago`
      })()
    : null

  return (
    <div className="panel h-full">
      <div className="panel-header justify-between">
        <span>
          <span className="accent">▸</span> CHART ·{' '}
          <span style={{ color: '#E6E9ED' }}>{symbolLabel}</span>
          <span style={{ fontSize: 9.5, color: '#5F6772', marginLeft: 8 }}>
            EMA <span style={{ color: '#4E80B4' }}>9</span> / <span style={{ color: '#4488FF' }}>21</span>
          </span>
        </span>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {/* Market / data status badge */}
          <span style={{
            fontSize: 9.5, padding: '1px 5px', borderRadius: 3, letterSpacing: '0.08em',
            background: badge.bg, color: badge.color,
            border: `1px solid ${badge.color}44`,
          }}>
            {badge.text}{age ? ` · ${age}` : ''}
          </span>

          <select
            value={symbolIdx}
            onChange={e => setSymbolIdx(Number(e.target.value))}
            style={{ background: '#14161A', color: '#ccc', border: '1px solid #2B303A', borderRadius: 3, padding: '0 4px', fontSize: 10.5, outline: 'none' }}
          >
            {SYMBOLS.map((s, i) => <option key={s.key} value={i}>{s.label}</option>)}
          </select>
          <div style={{ display: 'flex', gap: 4 }}>
            {TIMEFRAMES.map(t => (
              <button key={t} onClick={() => setTf(t)}
                style={{
                  padding: '1px 8px', borderRadius: 3, fontSize: 10.5, cursor: 'pointer', border: 'none',
                  background: tf === t ? '#4E80B4' : 'transparent',
                  color:      tf === t ? '#000' : '#9BA3AD',
                  fontWeight: tf === t ? 700 : 400,
                }}>
                {t}
              </button>
            ))}
          </div>
        </div>
      </div>
      <div style={{ flex: 1, position: 'relative', minHeight: 0 }}>
        <div ref={containerRef} style={{ position: 'absolute', inset: 0 }} />
        {loadState === 'error' && (
          <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', pointerEvents: 'none' }}>
            <span style={{ color: '#3C424B', fontSize: 11.5 }}>NO DATA — waiting for OHLCV…</span>
          </div>
        )}
        {loadState === 'loading' && lastUpdated === null && (
          <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', pointerEvents: 'none' }}>
            <span style={{ color: '#3C424B', fontSize: 11.5 }}>loading…</span>
          </div>
        )}
      </div>
    </div>
  )
}
