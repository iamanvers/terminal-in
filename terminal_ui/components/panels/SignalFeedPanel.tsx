'use client'
import { useEffect, useState } from 'react'
import { api, type NewsItem, type CalendarEvent } from '@/lib/api'
import { useSocketList, useTickMap } from '@/hooks/useSocket'
import Badge from '@/components/primitives/Badge'

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

function relTime(ms: number) {
  const s = Math.max(0, Math.floor((Date.now() - ms) / 1000))
  if (s < 60) return 'now'
  if (s < 3600) return `${Math.floor(s / 60)}m`
  if (s < 86400) return `${Math.floor(s / 3600)}h`
  return `${Math.floor(s / 86400)}d`
}

const SENT_COLOR = { positive: '#2DBD80', negative: '#F2495C', neutral: '#71767F' } as const

function NewsCard({ n }: { n: NewsItem }) {
  const sentColor = SENT_COLOR[n.sentiment] ?? '#71767F'
  const impactColor = n.impact === 'high' ? '#F2495C'
    : n.impact === 'medium' ? '#0094FB' : '#71767F'

  const headline = n.url ? (
    <a href={n.url} target="_blank" rel="noopener noreferrer"
      style={{ color: '#DFE2E7', textDecoration: 'none' }}
      onMouseEnter={e => (e.currentTarget.style.color = '#0094FB')}
      onMouseLeave={e => (e.currentTarget.style.color = '#DFE2E7')}>
      {n.headline}
    </a>
  ) : n.headline

  return (
    <div style={{ padding: '9px 12px', borderBottom: '1px solid #181B21', display: 'flex', gap: 10 }}>
      <div style={{ width: 2, flexShrink: 0, background: `${sentColor}66`, borderRadius: 1 }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <p className="t-headline" style={{ margin: '0 0 4px' }}>{headline}</p>
        <div style={{ display: 'flex', alignItems: 'center', gap: 7, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 10, color: '#565B63', fontVariantNumeric: 'tabular-nums' }}>{relTime(n.published_at)}</span>
          {n.source && <span style={{ fontSize: 10, color: '#4A4F57' }}>{n.source}</span>}
          <span style={{ fontSize: 9.5, fontWeight: 700, color: sentColor, letterSpacing: '0.05em' }}>
            {n.sentiment === 'positive' ? '▲' : n.sentiment === 'negative' ? '▼' : '–'} {n.sentiment.toUpperCase()}
          </span>
          {n.impact === 'high' && (
            <span style={{ fontSize: 9.5, fontWeight: 700, color: impactColor, letterSpacing: '0.05em' }}>HIGH IMPACT</span>
          )}
          {n.instruments?.length > 0 && (
            <div style={{ display: 'flex', gap: 3, flexWrap: 'wrap' }}>
              {n.instruments.slice(0, 3).map((inst, i) => (
                <span key={i} style={{ fontSize: 9.5, color: '#7E838C', background: '#23272E', border: '1px solid #222', borderRadius: 2, padding: '1px 4px' }}>
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

type NewsFilter = 'all' | 'positive' | 'negative' | 'high'

export default function SignalFeedPanel() {
  const [news, setNews]     = useState<NewsItem[]>([])
  const [events, setEvents] = useState<CalendarEvent[]>([])
  const [tab, setTab]       = useState<'signals' | 'news' | 'events'>('signals')
  const [newsFilter, setNewsFilter] = useState<NewsFilter>('all')
  const [tokenName, setTokenName] = useState<Record<number, string>>({})

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

  // Token → symbol from the registry (covers the full universe, no stale map)
  useEffect(() => {
    api.instruments()
      .then(list => setTokenName(Object.fromEntries(list.map(i => [i.token, i.symbol]))))
      .catch(() => {})
  }, [])

  useEffect(() => {
    const loadNews = () => api.news(200).then(setNews).catch(() => {})
    loadNews()
    api.events().then(setEvents).catch(() => {})
    // RSS lands every 15 min server-side; refresh the list each minute
    const t = setInterval(loadNews, 60_000)
    return () => clearInterval(t)
  }, [])

  // Deduplicate by headline, newest first, then apply the active filter
  const seenHeadlines = new Set<string>()
  const allNews = [...liveNews, ...news]
    .filter(n => {
      if (seenHeadlines.has(n.headline)) return false
      seenHeadlines.add(n.headline)
      return true
    })
    .sort((a, b) => b.published_at - a.published_at)
    .filter(n =>
      newsFilter === 'all' ? true
      : newsFilter === 'high' ? n.impact === 'high'
      : n.sentiment === newsFilter)
    .slice(0, 200)

  const newsCountLabel = `${allNews.length}`

  return (
    <div className="panel h-full">
      <div className="panel-header justify-between">
        <span><span className="accent">▸</span> SIGNAL FEED</span>
        <div className="flex gap-2">
          {(['signals', 'news', 'events'] as const).map(t => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`text-[10.5px] px-2 py-0.5 rounded ${tab === t ? 'bg-accent text-black font-bold' : 'text-muted hover:text-gray-300'}`}
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
                <p style={{ color: '#71767F', fontSize: 11.5, textAlign: 'center', marginBottom: 8 }}>No live signals yet — strategies evaluate every 60s</p>
                <p style={{ color: '#71767F', fontSize: 10.5, textAlign: 'center' }}>Market open 09:15 · Paper mode · {Object.keys(ticks).length} tokens streaming</p>
              </div>
            )
            : signals.map((s, i) => {
              const sym    = tokenName[s.instrument_id] ?? `#${s.instrument_id}`
              const full   = STRAT_FULL[s.strategy_id] ?? s.strategy_id
              const liveP  = ticks[s.instrument_id]?.last_price
              const pct    = Math.round(s.confidence * 100)
              const confColor = s.confidence >= 0.7 ? '#2DBD80' : s.confidence >= 0.5 ? '#0094FB' : '#F2495C'
              const sideColor = s.side === 'BUY' ? '#2DBD80' : '#F2495C'
              const rr = (s.target && s.stop_loss && liveP && Math.abs(liveP - s.stop_loss) > 0)
                ? ((s.target - liveP) / (liveP - s.stop_loss)).toFixed(1)
                : null
              return (
                <div
                  key={i}
                  style={{
                    padding: '10px 12px', borderBottom: '1px solid #23272E',
                    borderLeft: `3px solid ${sideColor}`,
                  }}
                >
                  {/* Header: symbol + side + strategy + time */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                    <span style={{ fontSize: 12.5, fontWeight: 700, color: '#ECEEF1' }}>{sym}</span>
                    <Badge variant="side" value={s.side} />
                    <span style={{ fontSize: 10, color: '#0094FB', marginLeft: 2 }}>{s.strategy_id}</span>
                    <span style={{ fontSize: 10, color: '#71767F' }}>· {full}</span>
                    <span style={{ fontSize: 10, color: '#4A4F57', marginLeft: 'auto' }}>{s.ts ? fmtTime(s.ts) : ''}</span>
                  </div>

                  {/* WHY explanation */}
                  <p style={{ margin: '0 0 6px', fontSize: 10.5, color: '#AEB3BB', lineHeight: 1.5 }}>
                    {buildWhy(s)}
                  </p>

                  {/* Price levels + confidence */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 10 }}>
                    {liveP && <span style={{ color: '#7E838C' }}>@ {liveP.toLocaleString('en-IN', { maximumFractionDigits: 0 })}</span>}
                    {s.target    && <span style={{ color: '#2DBD80' }}>T {s.target.toFixed(0)}</span>}
                    {s.stop_loss && <span style={{ color: '#F2495C' }}>SL {s.stop_loss.toFixed(0)}</span>}
                    {rr && <span style={{ color: '#7E838C' }}>R:R {rr}</span>}
                    <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 5 }}>
                      <div style={{ width: 40, height: 3, background: '#23272E', borderRadius: 2 }}>
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
          <>
            <div style={{ display: 'flex', gap: 4, padding: '6px 12px', borderBottom: '1px solid #181B21', position: 'sticky', top: 0, background: 'var(--surface-1, #121419)', zIndex: 1 }}>
              {([['all', 'ALL'], ['positive', '▲ POS'], ['negative', '▼ NEG'], ['high', 'HIGH IMPACT']] as [NewsFilter, string][]).map(([key, label]) => (
                <button key={key} onClick={() => setNewsFilter(key)} style={{
                  fontSize: 9.5, fontWeight: 700, letterSpacing: '0.05em', padding: '2px 8px',
                  borderRadius: 3, cursor: 'pointer',
                  border: `1px solid ${newsFilter === key ? '#0094FB55' : '#333841'}`,
                  background: newsFilter === key ? '#0094FB0E' : 'transparent',
                  color: newsFilter === key ? '#0094FB' : '#565B63',
                }}>{label}</button>
              ))}
            </div>
            {allNews.length === 0
              ? <p className="text-muted text-center mt-4 text-[11.5px]">No news matching this filter yet — RSS feeds refresh every 15 min.</p>
              : allNews.map((n, i) => <NewsCard key={n.id ?? i} n={n} />)}
          </>
        )}

        {/* ── Events ───────────────────────────────────────── */}
        {tab === 'events' && (
          events.length === 0
            ? <p className="text-muted text-center mt-4 text-[11.5px]">No upcoming events</p>
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
