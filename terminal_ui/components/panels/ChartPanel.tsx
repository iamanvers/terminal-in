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

// EMA calculation
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

type Props = {
  symbolIdx?: number
  setSymbolIdx?: (idx: number) => void
}

export default function ChartPanel({ symbolIdx: externalIdx, setSymbolIdx: externalSetIdx }: Props) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const chartRef    = useRef<any>(null)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const seriesRef   = useRef<any>(null)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const ema9Ref     = useRef<any>(null)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const ema21Ref    = useRef<any>(null)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const volRef      = useRef<any>(null)
  const containerRef  = useRef<HTMLDivElement>(null)

  const [internalIdx, setInternalIdx] = useState(0)
  const symbolIdx    = externalIdx    ?? internalIdx
  const setSymbolIdx = externalSetIdx ?? setInternalIdx

  const [tf, setTf]             = useState('5m')
  const [hasData, setHasData]   = useState(true)
  const [chartReady, setChartReady] = useState(false)
  const ticks = useTickMap()

  const symbol      = SYMBOLS[symbolIdx].key
  const symbolLabel = SYMBOLS[symbolIdx].label

  // Init chart once
  useEffect(() => {
    if (!containerRef.current) return
    let cancelled = false
    let cleanup: (() => void) | undefined
    import('lightweight-charts').then(({ createChart, CrosshairMode }) => {
      if (cancelled || !containerRef.current) return
      const chart = createChart(containerRef.current, {
        layout: { background: { color: '#111111' }, textColor: '#666666' },
        grid:   { vertLines: { color: '#161616' }, horzLines: { color: '#161616' } },
        crosshair: { mode: CrosshairMode.Normal },
        rightPriceScale: { borderColor: '#1E1E1E', scaleMargins: { top: 0.08, bottom: 0.22 } },
        timeScale: { borderColor: '#1E1E1E', timeVisible: true },
        width:  containerRef.current.clientWidth,
        height: containerRef.current.clientHeight,
      })

      const series = chart.addCandlestickSeries({
        upColor: '#00C853', downColor: '#D32F2F',
        borderUpColor: '#00C853', borderDownColor: '#D32F2F',
        wickUpColor: '#00C853', wickDownColor: '#D32F2F',
      })

      const ema9 = chart.addLineSeries({
        color: '#F7931E', lineWidth: 1,
        priceLineVisible: false, lastValueVisible: false,
      })
      const ema21 = chart.addLineSeries({
        color: '#4488FF', lineWidth: 1,
        priceLineVisible: false, lastValueVisible: false,
      })

      let vol: unknown = null
      try {
        vol = chart.addHistogramSeries({
          priceFormat: { type: 'volume' },
          priceScaleId: 'vol',
          lastValueVisible: false,
          priceLineVisible: false,
        })
        chart.priceScale('vol').applyOptions({
          scaleMargins: { top: 0.82, bottom: 0 },
          visible: false,
        })
      } catch { /* named price scales not supported in this build */ }

      chartRef.current  = chart
      seriesRef.current = series
      ema9Ref.current   = ema9
      ema21Ref.current  = ema21
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      volRef.current    = vol as any
      setChartReady(true)

      const ro = new ResizeObserver(() => {
        if (!containerRef.current) return
        chart.applyOptions({
          width:  containerRef.current.clientWidth,
          height: containerRef.current.clientHeight,
        })
      })
      ro.observe(containerRef.current)
      cleanup = () => { ro.disconnect(); chart.remove() }
    })
    return () => { cancelled = true; cleanup?.(); setChartReady(false) }
  }, [])

  // Update timeVisible when tf changes (daily = date-only, intraday = IST time)
  useEffect(() => {
    if (!chartReady || !chartRef.current) return
    chartRef.current.applyOptions({ timeScale: { timeVisible: tf !== '1d' } })
  }, [tf, chartReady])

  // Load OHLCV + compute EMAs + volume
  useEffect(() => {
    if (!chartReady || !seriesRef.current) return
    const loadData = async () => {
      let rows = await api.ohlcv(encodeURIComponent(symbol), tf, 300)
      // Fallback to 1d if current timeframe has no data (e.g. outside market hours)
      if (!rows.length && tf !== '1d') {
        rows = await api.ohlcv(encodeURIComponent(symbol), '1d', 300)
      }
      if (!seriesRef.current) return
      if (!rows.length) { setHasData(false); return }
      setHasData(true)
      processRows(rows)
    }
    const processRows = (rows: Record<string, unknown>[]) => {
      if (!seriesRef.current) return
      // Detect which time key the API returned (handles 1d fallback)
      const isDaily = 'bucket_date' in (rows[0] ?? {})
      const timeKey = isDaily ? 'bucket_date' : 'bucket_time'
      const bars = rows
        .map((r: Record<string, unknown>) => ({
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          time:   (isDaily
            // Daily: anchor to midnight UTC so the chart shows the correct calendar date
            ? Math.floor(new Date((r[timeKey] as string) + 'T00:00:00Z').getTime() / 1000)
            // Intraday: shift forward by IST offset (+5:30h) so the chart displays IST times
            : Math.floor(Number(r[timeKey]) / 1000) + 19800) as any,
          open:   Number(r.open), high: Number(r.high),
          low:    Number(r.low),  close: Number(r.close),
          volume: Number(r.volume ?? 0),
        }))
        .sort((a: { time: number }, b: { time: number }) => a.time - b.time)

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      seriesRef.current.setData(bars as any)
      chartRef.current?.timeScale().fitContent()

      // EMAs
      if (ema9Ref.current)  ema9Ref.current.setData(calcEMA(bars, 9))
      if (ema21Ref.current) ema21Ref.current.setData(calcEMA(bars, 21))

      // Volume histogram
      if (volRef.current) {
        const volData = bars.map((b: { time: unknown; close: number; open: number; volume: number }) => ({
          time:  b.time,
          value: b.volume,
          color: b.close >= b.open ? '#00C85318' : '#D32F2F18',
        }))
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        volRef.current.setData(volData as any)
      }
    }
    loadData().catch(() => setHasData(false))
  }, [symbol, tf, chartReady])

  // Push live tick as realtime candle — only during NSE market hours (IST 09:15–15:30)
  useEffect(() => {
    if (!seriesRef.current || tf === '1d') return
    const tick = ticks[SYMBOLS[symbolIdx].token]
    if (!tick?.last_price) return

    // IST = UTC + 5:30. Compute IST time-of-day to gate live updates.
    const nowMs   = Date.now()
    const istMs   = nowMs + 5.5 * 3600_000
    const istDate = new Date(istMs)
    const istTotalMinutes = istDate.getUTCHours() * 60 + istDate.getUTCMinutes()
    const OPEN  = 9 * 60 + 15   // 09:15 IST
    const CLOSE = 15 * 60 + 30  // 15:30 IST
    if (istTotalMinutes < OPEN || istTotalMinutes > CLOSE) return

    const barTime = Math.floor(nowMs / 1000) - (Math.floor(nowMs / 1000) % 60) + 19800
    try {
      seriesRef.current.update({
        time: barTime, open: Number(tick.last_price),
        high: Number(tick.last_price), low: Number(tick.last_price), close: Number(tick.last_price),
      })
    } catch { /* series not ready */ }
  }, [ticks, tf, symbolIdx])

  return (
    <div className="panel h-full">
      <div className="panel-header justify-between">
        <span>
          <span className="accent">▸</span> CHART ·{' '}
          <span style={{ color: '#E0E0E0' }}>{symbolLabel}</span>
          <span style={{ fontSize: 8, color: '#555', marginLeft: 8 }}>
            EMA <span style={{ color: '#F7931E' }}>9</span> / <span style={{ color: '#4488FF' }}>21</span>
          </span>
        </span>
        <div style={{ display: 'flex', gap: 8 }}>
          <select
            value={symbolIdx}
            onChange={e => setSymbolIdx(Number(e.target.value))}
            style={{ background: '#111111', color: '#ccc', border: '1px solid #1E1E1E', borderRadius: 3, padding: '0 4px', fontSize: 10, outline: 'none' }}
          >
            {SYMBOLS.map((s, i) => <option key={s.key} value={i}>{s.label}</option>)}
          </select>
          <div style={{ display: 'flex', gap: 4 }}>
            {TIMEFRAMES.map(t => (
              <button key={t} onClick={() => setTf(t)}
                style={{
                  padding: '1px 8px', borderRadius: 3, fontSize: 10, cursor: 'pointer', border: 'none',
                  background: tf === t ? '#F7931E' : 'transparent',
                  color:      tf === t ? '#000' : '#888',
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
        {!hasData && (
          <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <span style={{ color: '#888', fontSize: 11 }}>NO DATA — waiting for OHLCV…</span>
          </div>
        )}
      </div>
    </div>
  )
}
