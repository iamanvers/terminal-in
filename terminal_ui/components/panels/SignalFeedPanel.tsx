'use client'
import { useEffect, useState } from 'react'
import { api, type NewsItem, type CalendarEvent } from '@/lib/api'
import { useSocketList, useTickMap } from '@/hooks/useSocket'
import Badge from '@/components/primitives/Badge'

const TOKEN_NAME: Record<number, string> = {
  256265: 'NIFTY 50', 260105: 'BANKNIFTY', 257801: 'FINNIFTY',
  264969: 'INDIA VIX', 2800641: 'NIFTYBEES',
  738561: 'RELIANCE', 341249: 'HDFCBANK', 2953217: 'TCS',
  408065: 'INFY', 1270529: 'ICICIBANK', 779521: 'SBIN',
  1510401: 'AXISBANK', 492033: 'KOTAKBANK', 4267265: 'BAJFINANCE',
  356865: 'HINDUNILVR', 969473: 'WIPRO',
  2939009: 'LT', 2815745: 'MARUTI', 60417: 'ASIANPAINT',
  884737: 'TATAMOTORS', 857857: 'SUNPHARMA', 895745: 'TATASTEEL',
  3834113: 'POWERGRID', 2977281: 'NTPC', 633601: 'ONGC',
  897537: 'TITAN', 1850625: 'HCLTECH', 3465729: 'TECHM',
  3861249: 'ADANIPORTS', 2952193: 'ULTRACEMCO', 4598529: 'NESTLEIND',
  3001089: 'JSWSTEEL', 225537: 'DRREDDY', 4268801: 'BAJAJFINSV',
  2865793: 'DIVISLAB', 348929: 'HINDALCO',
}

const STRAT_FULL: Record<string, string> = {
  S1: 'Opening Range Breakout',
  S2: '52-Week Breakout',
  S3: 'Midcap Breakout',
  S4: 'RSI Mean Reversion',
  S5: 'EMA Pullback',
  S6: 'Pairs Cointegration',
  S8: 'VIX Asymmetry',
  S9: 'Hawkes Momentum',
}

type SignalEntry = {
  strategy_id: string
  side: string
  instrument_id: number
  confidence: number
  regime: string
  stop_loss?: number
  target?: number
  metadata?: Record<string, unknown>
  ts?: number
}

function buildWhy(s: SignalEntry): string {
  const m = s.metadata ?? {}
  const n = (v: unknown, d = 2) => v != null ? Number(v).toFixed(d) : '—'
  switch (s.strategy_id) {
    case 'S1': {
      const hi = n(m.orb_high, 0), lo = n(m.orb_low, 0)
      return s.side === 'BUY'
        ? `Price broke above 30-min ORB high (${hi}). Bullish momentum confirmed. Target 3× ATR above entry.`
        : `Price broke below 30-min ORB low (${lo}). Bearish breakdown confirmed. Target 3× ATR below entry.`
    }
    case 'S2':
      return `Price closed above 52-week high (${n(m.high_52w, 0)}) with above-average volume. Breakout momentum in ${s.regime} regime.`
    case 'S3': {
      const bpct = m.breakout_pct ? (Number(m.breakout_pct) * 100).toFixed(2) : '—'
      return `Price broke 20-day high (${n(m.high_20, 0)}) by ${bpct}%. Midcap breakout scan — momentum entry on volume confirmation.`
    }
    case 'S4':
      return s.side === 'BUY'
        ? `RSI-14 at ${n(m.rsi, 1)} — deeply oversold (< 35) in ${s.regime} regime. Statistical mean reversion long.`
        : `RSI-14 at ${n(m.rsi, 1)} — overbought (> 65) in ${s.regime} bear regime. Mean reversion short.`
    case 'S5':
      return `Pulled back to EMA20 (${n(m.ema20, 0)}) while price above EMA50 (${n(m.ema50, 0)}). RSI ${n(m.rsi, 1)} in 40–58 zone — healthy trend continuation.`
    case 'S6':
      return `Pair ${m.pair ?? '?'} — spread z-score ${n(m.zscore, 2)} (β=${n(m.beta, 3)}). Statistically significant divergence. Hedge: ${m.hedge_symbol} ${m.hedge_side}.`
    case 'S8': {
      const sig = String(m.signal ?? '')
      return sig === 'vix_spike_reversal'
        ? `India VIX spiked to ${n(m.india_vix, 1)} (> 25) — extreme fear. Contrarian long: panic selloff reversal expected.`
        : `India VIX at ${n(m.india_vix, 1)} (< 12) in bear regime — complacency warning. Short setup on volatility reversion.`
    }
    case 'S9':
      return `Hawkes process z-score ${n(m.hawkes_z, 2)}, intensity ${n(m.intensity, 4)}. Order-flow clustering detected — momentum continuation signal.`
    default:
      return 'Strategy signal triggered based on current market conditions and regime fit.'
  }
}

function fmtTime(ms: number) {
  return new Date(ms).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })
}

function NewsCard({ n }: { n: NewsItem }) {
  const borderColor = n.sentiment === 'positive' ? '#00C85360'
    : n.sentiment === 'negative' ? '#D32F2F60' : '#2A2A2A'
  const impactColor = n.impact === 'high' ? '#D32F2F'
    : n.impact === 'medium' ? '#F7931E' : '#444'

  return (
    <div style={{ padding: '8px 12px', borderBottom: '1px solid #161616', display: 'flex', gap: 10 }}>
      <div style={{ width: 2, flexShrink: 0, background: borderColor, borderRadius: 1 }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <p style={{ margin: '0 0 4px', fontSize: 11, color: '#d0d0d0', lineHeight: 1.4 }}>{n.headline}</p>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 9, color: '#444' }}>{fmtTime(n.published_at)}</span>
          {n.source && <span style={{ fontSize: 9, color: '#333' }}>· {n.source}</span>}
          <span style={{ fontSize: 9, color: impactColor, textTransform: 'uppercase', letterSpacing: '0.04em' }}>{n.impact}</span>
          {n.instruments?.length > 0 && (
            <div style={{ display: 'flex', gap: 3, flexWrap: 'wrap' }}>
              {n.instruments.slice(0, 3).map((inst, i) => (
                <span key={i} style={{ fontSize: 8, color: '#555', background: '#1A1A1A', border: '1px solid #222', borderRadius: 2, padding: '1px 4px' }}>
                  {inst}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default function SignalFeedPanel() {
  const [news, setNews]     = useState<NewsItem[]>([])
  const [events, setEvents] = useState<CalendarEvent[]>([])
  const [tab, setTab]       = useState<'signals' | 'news' | 'events'>('signals')

  const rawSignals = useSocketList<SignalEntry>('strategy_signal', 60)
  const liveNews   = useSocketList<NewsItem>('news_signal', 30)
  const ticks      = useTickMap()

  // Deduplicate signals: keep most recent per (strategy_id, instrument_id)
  const signals = (() => {
    const m = new Map<string, SignalEntry>()
    for (const s of rawSignals) {
      const key = `${s.strategy_id}:${s.instrument_id}`
      const ex = m.get(key)
      if (!ex || (s.ts ?? 0) > (ex.ts ?? 0)) m.set(key, s)
    }
    return [...m.values()].sort((a, b) => (b.ts ?? 0) - (a.ts ?? 0))
  })()

  useEffect(() => {
    api.news(30).then(setNews).catch(() => {})
    api.events().then(setEvents).catch(() => {})
  }, [])

  // Deduplicate by headline
  const seenHeadlines = new Set<string>()
  const allNews = [...liveNews, ...news].filter(n => {
    if (seenHeadlines.has(n.headline)) return false
    seenHeadlines.add(n.headline)
    return true
  }).slice(0, 50)

  const newsCountLabel = liveNews.length > 0 ? `${liveNews.length} live` : `${allNews.length}`

  return (
    <div className="panel h-full">
      <div className="panel-header justify-between">
        <span><span className="accent">▸</span> SIGNAL FEED</span>
        <div className="flex gap-2">
          {(['signals', 'news', 'events'] as const).map(t => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`text-[10px] px-2 py-0.5 rounded ${tab === t ? 'bg-accent text-black font-bold' : 'text-muted hover:text-gray-300'}`}
            >
              {t === 'signals' ? `SIGNALS (${signals.length})`
                : t === 'news' ? `NEWS (${newsCountLabel})`
                : t.toUpperCase()}
            </button>
          ))}
        </div>
      </div>

      <div className="panel-body">
        {/* ── Signals ──────────────────────────────────────── */}
        {tab === 'signals' && (
          signals.length === 0
            ? (
              <div style={{ padding: '16px 12px' }}>
                <p style={{ color: '#555', fontSize: 11, textAlign: 'center', marginBottom: 8 }}>No live signals yet — strategies evaluate every 60s</p>
                <p style={{ color: '#444', fontSize: 10, textAlign: 'center' }}>Market open 09:15 · Paper mode · {Object.keys(ticks).length} tokens streaming</p>
              </div>
            )
            : signals.map((s, i) => {
              const sym    = TOKEN_NAME[s.instrument_id] ?? `#${s.instrument_id}`
              const full   = STRAT_FULL[s.strategy_id] ?? s.strategy_id
              const liveP  = ticks[s.instrument_id]?.last_price
              const pct    = Math.round(s.confidence * 100)
              const confColor = s.confidence >= 0.7 ? '#00C853' : s.confidence >= 0.5 ? '#F7931E' : '#D32F2F'
              const sideColor = s.side === 'BUY' ? '#00C853' : '#D32F2F'
              const rr = (s.target && s.stop_loss && liveP && Math.abs(liveP - s.stop_loss) > 0)
                ? ((s.target - liveP) / (liveP - s.stop_loss)).toFixed(1)
                : null
              return (
                <div
                  key={i}
                  style={{
                    padding: '10px 12px', borderBottom: '1px solid #161616',
                    borderLeft: `3px solid ${sideColor}`,
                  }}
                >
                  {/* Header: symbol + side + strategy + time */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                    <span style={{ fontSize: 12, fontWeight: 700, color: '#E0E0E0' }}>{sym}</span>
                    <Badge variant="side" value={s.side} />
                    <span style={{ fontSize: 9, color: '#F7931E', marginLeft: 2 }}>{s.strategy_id}</span>
                    <span style={{ fontSize: 9, color: '#444' }}>· {full}</span>
                    <span style={{ fontSize: 9, color: '#333', marginLeft: 'auto' }}>{s.ts ? fmtTime(s.ts) : ''}</span>
                  </div>

                  {/* WHY explanation */}
                  <p style={{ margin: '0 0 6px', fontSize: 10, color: '#999', lineHeight: 1.5 }}>
                    {buildWhy(s)}
                  </p>

                  {/* Price levels + confidence */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 9 }}>
                    {liveP && <span style={{ color: '#666' }}>@ {liveP.toLocaleString('en-IN', { maximumFractionDigits: 0 })}</span>}
                    {s.target    && <span style={{ color: '#00C853' }}>T {s.target.toFixed(0)}</span>}
                    {s.stop_loss && <span style={{ color: '#D32F2F' }}>SL {s.stop_loss.toFixed(0)}</span>}
                    {rr && <span style={{ color: '#666' }}>R:R {rr}</span>}
                    <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 5 }}>
                      <div style={{ width: 40, height: 3, background: '#1A1A1A', borderRadius: 2 }}>
                        <div style={{ width: `${pct}%`, height: '100%', background: confColor, borderRadius: 2 }} />
                      </div>
                      <span style={{ color: confColor }}>{pct}%</span>
                    </div>
                  </div>

                  {/* Regime badge */}
                  {s.regime && (
                    <div style={{ marginTop: 4 }}>
                      <Badge variant="regime" value={s.regime} />
                    </div>
                  )}
                </div>
              )
            })
        )}

        {/* ── News ─────────────────────────────────────────── */}
        {tab === 'news' && (
          allNews.length === 0
            ? <p className="text-muted text-center mt-4 text-[11px]">No news yet…</p>
            : allNews.map((n, i) => <NewsCard key={i} n={n} />)
        )}

        {/* ── Events ───────────────────────────────────────── */}
        {tab === 'events' && (
          events.length === 0
            ? <p className="text-muted text-center mt-4 text-[11px]">No upcoming events</p>
            : (
              <table>
                <thead>
                  <tr><th>Date</th><th>Event</th><th>Mask</th></tr>
                </thead>
                <tbody>
                  {events.map((e, i) => (
                    <tr key={i}>
                      <td className="text-muted">{e.date}</td>
                      <td className="text-gray-300">{e.event}</td>
                      <td className={e.mask < 0.5 ? 'text-neg' : e.mask < 1 ? 'text-accent' : 'text-pos'}>
                        {(e.mask * 100).toFixed(0)}%
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )
        )}
      </div>
    </div>
  )
}
