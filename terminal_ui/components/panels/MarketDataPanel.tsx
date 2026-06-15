'use client'
import { useEffect, useState, useCallback, useRef } from 'react'
import { useTickMap } from '@/hooks/useSocket'
import { usePersistedState } from '@/hooks/usePersistedState'
import { api, type GlobalQuote } from '@/lib/api'
import PriceTag from '@/components/primitives/PriceTag'
import InstrumentModal from '@/components/panels/InstrumentModal'
import GlobalModal from '@/components/panels/GlobalModal'

// ── Instrument lists ──────────────────────────────────────────────────────────
const SENSEX30_TOKENS = new Set([
  341249, 738561, 1270529, 408065, 2953217, 492033, 2939009, 779521,
  1510401, 4267265, 60417, 1850625, 2815745, 857857, 897537, 969473,
  2952193, 2977281, 3834113, 633601, 3001089, 895745, 4598529, 4268801,
  3861249, 225537, 356865,
])

const NSE_WATCHLIST = [
  { label: 'NIFTY 50',   token: 256265  },
  { label: 'BANKNIFTY',  token: 260105  },
  { label: 'FINNIFTY',   token: 257801  },
  { label: 'INDIA VIX',  token: 264969  },
  { label: 'NIFTYBEES',  token: 2800641 },
  { label: 'RELIANCE',   token: 738561  },
  { label: 'HDFCBANK',   token: 341249  },
  { label: 'TCS',        token: 2953217 },
  { label: 'INFY',       token: 408065  },
  { label: 'ICICIBANK',  token: 1270529 },
  { label: 'SBIN',       token: 779521  },
  { label: 'AXISBANK',   token: 1510401 },
  { label: 'KOTAKBANK',  token: 492033  },
  { label: 'BAJFINANCE', token: 4267265 },
  { label: 'HINDUNILVR', token: 356865  },
  { label: 'WIPRO',      token: 969473  },
  { label: 'LT',         token: 2939009 },
  { label: 'MARUTI',     token: 2815745 },
  { label: 'ASIANPAINT', token: 60417   },
  { label: 'TATAMOTORS', token: 884737  },
  { label: 'SUNPHARMA',  token: 857857  },
  { label: 'TATASTEEL',  token: 895745  },
  { label: 'POWERGRID',  token: 3834113 },
  { label: 'NTPC',       token: 2977281 },
  { label: 'ONGC',       token: 633601  },
  { label: 'TITAN',      token: 897537  },
  { label: 'HCLTECH',    token: 1850625 },
  { label: 'TECHM',      token: 3465729 },
  { label: 'ADANIPORTS', token: 3861249 },
  { label: 'ULTRACEMCO', token: 2952193 },
  { label: 'NESTLEIND',  token: 4598529 },
  { label: 'JSWSTEEL',   token: 3001089 },
  { label: 'DRREDDY',    token: 225537  },
  { label: 'BAJAJFINSV', token: 4268801 },
  { label: 'DIVISLAB',   token: 2865793 },
  { label: 'HINDALCO',   token: 348929  },
]

type Tab = 'NSE' | 'BSE' | 'GLOBAL' | 'FX' | 'COMMOD' | 'RISK'
const TABS: Tab[] = ['NSE', 'BSE', 'GLOBAL', 'FX', 'COMMOD', 'RISK']
const TAB_CATEGORY: Record<Tab, string | null> = {
  NSE: null, BSE: 'bse', GLOBAL: 'global', FX: 'fx', COMMOD: 'commod', RISK: 'risk',
}

function isNSEOpen(): boolean {
  const d = new Date(Date.now() + 5.5 * 3600_000)
  const day = d.getUTCDay()
  if (day === 0 || day === 6) return false
  const m = d.getUTCHours() * 60 + d.getUTCMinutes()
  return m >= 9 * 60 + 15 && m <= 15 * 60 + 30
}

type PriceMap = Record<number, { price: number; chg: number }>
type Selected = { token: number; label: string } | null

// ── Sparkline ─────────────────────────────────────────────────────────────────
function Sparkline({ prices, up }: { prices: number[]; up: boolean }) {
  if (prices.length < 3) return <span style={{ display: 'inline-block', width: 44 }} />
  const min = Math.min(...prices), max = Math.max(...prices)
  const range = max - min || 1
  const w = 44, h = 16
  const pts = prices.map((p, i) => `${(i / (prices.length - 1)) * w},${h - ((p - min) / range) * h}`).join(' ')
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} style={{ display: 'block' }}>
      <polyline points={pts} fill="none" stroke={up ? '#2DBD80' : '#F2495C'} strokeWidth="1.2" />
    </svg>
  )
}

// ── Skeleton row ──────────────────────────────────────────────────────────────
function SkeletonRow() {
  return (
    <tr>
      <td><div style={{ height: 8, width: 64, background: '#23272E', borderRadius: 3, animation: 'shimmer 1.4s ease-in-out infinite' }} /></td>
      <td><div style={{ height: 8, width: 44, background: '#23272E', borderRadius: 3 }} /></td>
      <td><div style={{ height: 8, width: 52, background: '#23272E', borderRadius: 3, animation: 'shimmer 1.4s ease-in-out infinite' }} /></td>
      <td><div style={{ height: 8, width: 36, background: '#23272E', borderRadius: 3 }} /></td>
    </tr>
  )
}

const SHIMMER_CSS = `
@keyframes shimmer {
  0%,100% { opacity:.4 }
  50%      { opacity:.8 }
}
`

// ── Component ─────────────────────────────────────────────────────────────────
export default function MarketDataPanel({ onChartSelect }: { onChartSelect?: (idx: number) => void }) {
  const ticks = useTickMap()
  const [tab, setTab] = usePersistedState<Tab>('tin.market.watchlistTab', 'NSE')
  const [prices, setPrices]           = useState<PriceMap>({})   // REST-seeded + WS updated
  const [prevPrices, setPrevPrices]   = useState<Record<number, number>>({})
  const [priceHistory, setPriceHistory] = useState<Record<number, number[]>>({})
  const [loading, setLoading]         = useState(true)           // initial REST load
  const [globalQuotes, setGlobalQuotes] = useState<GlobalQuote[]>([])
  const [globalLoading, setGlobalLoading] = useState(false)
  const [selected, setSelected]       = useState<Selected>(null)
  const [selectedGlobal, setSelectedGlobal] = useState<GlobalQuote | null>(null)

  // Seed prices from REST on mount — no waiting for WebSocket.
  // Fetch live ticks and last closes in parallel (no waterfall): live ticks
  // win, OHLCV closes fill the gaps when the market is closed.
  useEffect(() => {
    Promise.allSettled([api.allTicks(), api.lastCloses()]).then(([ticksRes, closesRes]) => {
      const next: PriceMap = {}
      if (ticksRes.status === 'fulfilled') {
        for (const [tokenStr, tick] of Object.entries(ticksRes.value)) {
          const token = Number(tokenStr)
          if (tick.last_price > 0) {
            next[token] = { price: tick.last_price, chg: tick.change ?? 0 }
          }
        }
      }
      if (closesRes.status === 'fulfilled') {
        for (const [tokenStr, rec] of Object.entries(closesRes.value)) {
          const token = Number(tokenStr)
          if (!next[token] && rec.close > 0) {
            next[token] = { price: rec.close, chg: 0 }
          }
        }
      }
      setPrices(next)
      setLoading(false)
    }).catch(() => setLoading(false))
  }, [])

  // Merge live WebSocket ticks into prices (only update if market open OR first fill)
  const marketOpen = isNSEOpen()
  const prevTicksRef = useRef<Record<number, number>>({})

  useEffect(() => {
    setPrices(prev => {
      const next = { ...prev }
      let changed = false
      for (const { token } of NSE_WATCHLIST) {
        const p = ticks[token]?.last_price
        if (!p) continue
        if (prev[token] === undefined || marketOpen) {
          next[token] = { price: p, chg: ticks[token]?.change ?? 0 }
          changed = true
        }
      }
      return changed ? next : prev
    })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticks, marketOpen])

  // Sparkline history — fixed 5s interval during market hours, reading the
  // latest ticks via ref. The effect runs once per market-open transition
  // instead of re-running on every tick event.
  const ticksRef = useRef(ticks)
  ticksRef.current = ticks

  useEffect(() => {
    if (!marketOpen) return
    const interval = setInterval(() => {
      const t = ticksRef.current
      setPrevPrices(prev => {
        const next = { ...prev }
        for (const { token } of NSE_WATCHLIST) {
          const p = t[token]?.last_price
          if (p && prevTicksRef.current[token] !== p) next[token] = prevTicksRef.current[token] ?? p
          if (p) prevTicksRef.current[token] = p
        }
        return next
      })
      setPriceHistory(prev => {
        const next = { ...prev }
        for (const { token } of NSE_WATCHLIST) {
          const p = t[token]?.last_price
          if (!p) continue
          next[token] = [...(next[token] ?? []), p].slice(-50)
        }
        return next
      })
    }, 5000)
    return () => clearInterval(interval)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [marketOpen])

  // Fetch global quotes when tab changes
  const fetchGlobal = useCallback(() => {
    if (globalLoading) return
    setGlobalLoading(true)
    api.globalQuotes().then(data => { setGlobalQuotes(data); setGlobalLoading(false) })
      .catch(() => setGlobalLoading(false))
  }, [globalLoading])

  useEffect(() => {
    if (tab !== 'NSE' && globalQuotes.length === 0) fetchGlobal()
  }, [tab, globalQuotes.length, fetchGlobal])

  const filteredGlobal = TAB_CATEGORY[tab]
    ? globalQuotes.filter(q => q.category === TAB_CATEGORY[tab])
    : []

  const SKELETON_COUNT = 8

  return (
    <div className="panel h-full">
      <style dangerouslySetInnerHTML={{ __html: SHIMMER_CSS }} />

      {/* Tab bar */}
      <div style={{ display: 'flex', borderBottom: '1px solid #333841', background: '#121419', flexShrink: 0 }}>
        {TABS.map(t => (
          <button key={t} onClick={() => setTab(t)} style={{
            flex: 1, padding: '6px 0', fontSize: 9.5, fontWeight: 600,
            letterSpacing: '0.01em', background: 'none', border: 'none', cursor: 'pointer',
            minWidth: 0, overflow: 'hidden',
            color: tab === t ? '#0094FB' : '#71767F',
            borderBottom: tab === t ? '2px solid #0094FB' : '2px solid transparent',
          }}>{t}</button>
        ))}
      </div>

      {/* Market-closed notice — Indian venues only; GLOBAL/FX/COMMOD keep
          their own trading hours and are never 'NSE closed' */}
      {!marketOpen && (tab === 'NSE' || tab === 'BSE') && (
        <div style={{ padding: '3px 8px', background: '#0A0B0D', borderBottom: '1px solid #181B21', display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}>
          <span style={{ width: 5, height: 5, borderRadius: '50%', background: '#4A4F57', display: 'inline-block' }} />
          <span style={{ fontSize: 9.5, color: '#4A4F57', letterSpacing: '.06em' }}>NSE CLOSED · last close prices</span>
        </div>
      )}

      <div className="panel-body">
        {/* ── NSE ─────────────────────────────────────────────────── */}
        {tab === 'NSE' && (
          <table>
            <thead>
              <tr>
                <th>Symbol</th>
                <th style={{ textAlign: 'center' }}>Trend</th>
                <th>Last</th>
                <th>Chg%</th>
              </tr>
            </thead>
            <tbody>
              {loading
                ? Array.from({ length: SKELETON_COUNT }).map((_, i) => <SkeletonRow key={i} />)
                : NSE_WATCHLIST.map(({ label, token }) => {
                    const dp    = prices[token]
                    const price = dp?.price ?? 0
                    const prev  = prevPrices[token]
                    const chg   = dp?.chg ?? 0
                    const hist  = priceHistory[token] ?? []
                    return (
                      <tr key={token} onClick={() => setSelected({ token, label })} style={{ cursor: 'pointer' }}>
                        <td className="text-[11.5px] text-gray-300">{label}</td>
                        <td style={{ padding: '2px 4px' }}>
                          <Sparkline prices={hist} up={chg >= 0} />
                        </td>
                        <td>
                          {price > 0
                            ? <PriceTag value={price} prev={prev} />
                            : <span className="text-muted">—</span>}
                        </td>
                        <td className={chg >= 0 ? 'text-pos' : 'text-neg'}>
                          {price > 0 ? `${chg >= 0 ? '+' : ''}${chg.toFixed(2)}%` : '—'}
                        </td>
                      </tr>
                    )
                  })
              }
            </tbody>
          </table>
        )}

        {/* ── BSE ─────────────────────────────────────────────────── */}
        {tab === 'BSE' && (() => {
          const sensex = globalQuotes.find(q => q.label === 'SENSEX')
          const sensexStocks = NSE_WATCHLIST.filter(w => SENSEX30_TOKENS.has(w.token))
          return (
            <>
              <div style={{ padding: '8px 10px', borderBottom: '1px solid #23272E', display: 'flex', alignItems: 'center', gap: 12 }}>
                <span style={{ fontSize: 10.5, color: '#0094FB', fontWeight: 700, letterSpacing: '0.06em' }}>SENSEX</span>
                {sensex ? (
                  <>
                    <span style={{ fontSize: 14, fontWeight: 700, color: '#ECEEF1', fontVariantNumeric: 'tabular-nums' }}>
                      {sensex.price.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
                    </span>
                    <span style={{ fontSize: 11.5, fontWeight: 600, color: sensex.change >= 0 ? '#2DBD80' : '#F2495C' }}>
                      {sensex.change >= 0 ? '+' : ''}{sensex.change.toFixed(2)}%
                    </span>
                    <span style={{ fontSize: 9.5, color: '#71767F', marginLeft: 'auto' }}>DELAYED</span>
                  </>
                ) : (
                  <button onClick={fetchGlobal} style={{ fontSize: 9.5, color: '#0094FB', background: 'none', border: '1px solid #333', borderRadius: 3, padding: '2px 8px', cursor: 'pointer' }}>
                    {globalLoading ? '…' : 'LOAD'}
                  </button>
                )}
              </div>
              <table>
                <thead>
                  <tr>
                    <th>SENSEX 30</th>
                    <th style={{ textAlign: 'center' }}>Trend</th>
                    <th>Last</th>
                    <th>Chg%</th>
                  </tr>
                </thead>
                <tbody>
                  {loading
                    ? Array.from({ length: 6 }).map((_, i) => <SkeletonRow key={i} />)
                    : sensexStocks.map(({ label, token }) => {
                        const dp    = prices[token]
                        const price = dp?.price ?? 0
                        const prev  = prevPrices[token]
                        const chg   = dp?.chg ?? 0
                        const hist  = priceHistory[token] ?? []
                        return (
                          <tr key={token} onClick={() => setSelected({ token, label })} style={{ cursor: 'pointer' }}>
                            <td className="text-[11.5px] text-gray-300">{label}</td>
                            <td style={{ padding: '2px 4px' }}><Sparkline prices={hist} up={chg >= 0} /></td>
                            <td>{price > 0 ? <PriceTag value={price} prev={prev} /> : <span className="text-muted">—</span>}</td>
                            <td className={chg >= 0 ? 'text-pos' : 'text-neg'}>
                              {price > 0 ? `${chg >= 0 ? '+' : ''}${chg.toFixed(2)}%` : '—'}
                            </td>
                          </tr>
                        )
                      })
                  }
                </tbody>
              </table>
            </>
          )
        })()}

        {/* ── Global / FX / Commod / Risk ──────────────────────────── */}
        {tab !== 'NSE' && tab !== 'BSE' && (
          globalLoading && filteredGlobal.length === 0
            ? (
              <table><thead><tr><th>{tab}</th><th>Price</th><th>Chg%</th></tr></thead>
                <tbody>{Array.from({ length: 5 }).map((_, i) => <SkeletonRow key={i} />)}</tbody>
              </table>
            )
            : filteredGlobal.length === 0
              ? (
                <div style={{ textAlign: 'center', marginTop: 20 }}>
                  <p style={{ color: '#71767F', fontSize: 10.5 }}>No data yet</p>
                  <button onClick={fetchGlobal} style={{ marginTop: 6, fontSize: 10, color: '#0094FB', background: 'none', border: '1px solid #333', borderRadius: 3, padding: '3px 10px', cursor: 'pointer' }}>
                    REFRESH
                  </button>
                </div>
              )
              : (
                <table>
                  <thead>
                    <tr>
                      <th>{tab === 'FX' ? 'Pair' : tab === 'COMMOD' ? 'Commodity' : 'Index'}</th>
                      <th>Price</th>
                      <th>Chg%</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredGlobal.map(q => (
                      <tr key={q.symbol} onClick={() => setSelectedGlobal(q)} style={{ cursor: 'pointer' }}>
                        <td className="text-[11.5px] text-gray-300">{q.label}</td>
                        <td className="text-gray-200">
                          {tab === 'FX' ? q.price.toFixed(4) : q.price.toLocaleString('en-IN', { maximumFractionDigits: 2 })}
                        </td>
                        <td className={q.change >= 0 ? 'text-pos' : 'text-neg'}>
                          {q.change >= 0 ? '+' : ''}{q.change.toFixed(2)}%
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )
        )}

        {tab !== 'NSE' && globalQuotes.length > 0 && (
          <p style={{ fontSize: 9.5, color: '#4A4F57', textAlign: 'center', padding: '4px 0' }}>
            DELAYED · yfinance · 5-min cache
            <button onClick={fetchGlobal} style={{ marginLeft: 8, color: '#4A4F57', background: 'none', border: 'none', cursor: 'pointer', fontSize: 9.5 }}>↺</button>
          </p>
        )}
      </div>

      {selected && (
        <InstrumentModal token={selected.token} label={selected.label}
          onClose={() => setSelected(null)} onChartSelect={onChartSelect} />
      )}
      {selectedGlobal && (
        <GlobalModal quote={selectedGlobal} onClose={() => setSelectedGlobal(null)} />
      )}
    </div>
  )
}
