'use client'
import { useEffect, useState, useCallback } from 'react'
import { useTickMap } from '@/hooks/useSocket'
import { api, type GlobalQuote } from '@/lib/api'
import PriceTag from '@/components/primitives/PriceTag'
import InstrumentModal from '@/components/panels/InstrumentModal'
import GlobalModal from '@/components/panels/GlobalModal'

// ── SENSEX 30 constituent tokens (subset of NSE, for BSE tab) ─────────────
const SENSEX30_TOKENS = new Set([
  341249,   // HDFCBANK
  738561,   // RELIANCE
  1270529,  // ICICIBANK
  408065,   // INFY
  2953217,  // TCS
  492033,   // KOTAKBANK
  2939009,  // LT
  779521,   // SBIN
  1510401,  // AXISBANK
  4267265,  // BAJFINANCE
  60417,    // ASIANPAINT
  1850625,  // HCLTECH
  2815745,  // MARUTI
  857857,   // SUNPHARMA
  897537,   // TITAN
  969473,   // WIPRO
  2952193,  // ULTRACEMCO
  2977281,  // NTPC
  3834113,  // POWERGRID
  633601,   // ONGC
  3001089,  // JSWSTEEL
  895745,   // TATASTEEL
  4598529,  // NESTLEIND
  4268801,  // BAJAJFINSV
  3861249,  // ADANIPORTS
  225537,   // DRREDDY
  356865,   // HINDUNILVR
])

// ── NSE watchlist ──────────────────────────────────────────────────────────
const NSE_WATCHLIST = [
  // Indices
  { label: 'NIFTY 50',   token: 256265  },
  { label: 'BANKNIFTY',  token: 260105  },
  { label: 'FINNIFTY',   token: 257801  },
  { label: 'INDIA VIX',  token: 264969  },
  { label: 'NIFTYBEES',  token: 2800641 },
  // Nifty 50 equities
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
  const m = d.getUTCHours() * 60 + d.getUTCMinutes()
  return m >= 9 * 60 + 15 && m <= 15 * 60 + 30
}

type Selected = { token: number; label: string } | null
type SelectedGlobal = GlobalQuote | null

function Sparkline({ prices, up }: { prices: number[]; up: boolean }) {
  if (prices.length < 3) return <span style={{ display: 'inline-block', width: 44 }} />
  const min = Math.min(...prices), max = Math.max(...prices)
  const range = max - min || 1
  const w = 44, h = 16
  const pts = prices
    .map((p, i) => `${(i / (prices.length - 1)) * w},${h - ((p - min) / range) * h}`)
    .join(' ')
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} style={{ display: 'block' }}>
      <polyline points={pts} fill="none" stroke={up ? '#00C853' : '#D32F2F'} strokeWidth="1.2" />
    </svg>
  )
}

type Props = {
  onChartSelect?: (symbolIdx: number) => void
}

export default function MarketDataPanel({ onChartSelect }: Props) {
  const ticks = useTickMap()
  const [tab, setTab]       = useState<Tab>('NSE')
  const [prevPrices,   setPrevPrices]   = useState<Record<number, number>>({})
  const [priceHistory, setPriceHistory] = useState<Record<number, number[]>>({})
  const [displayPrices, setDisplayPrices] = useState<Record<number, { price: number; chg: number }>>({})
  const [globalQuotes, setGlobalQuotes] = useState<GlobalQuote[]>([])
  const [globalLoading, setGlobalLoading] = useState(false)
  const [selected, setSelected]             = useState<Selected>(null)
  const [selectedGlobal, setSelectedGlobal] = useState<SelectedGlobal>(null)

  // Freeze displayed prices outside market hours — initial snapshot on first tick, then live during market
  useEffect(() => {
    const open = isNSEOpen()
    setDisplayPrices(prev => {
      const next = { ...prev }
      for (const { token } of NSE_WATCHLIST) {
        const p = ticks[token]?.last_price
        if (p === undefined) continue
        if (prev[token] === undefined || open) {
          next[token] = { price: p, chg: ticks[token]?.change ?? 0 }
        }
      }
      return next
    })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticks])

  // Update sparkline history on each tick — gated to NSE market hours (IST 09:15–15:30)
  useEffect(() => {
    const istMs = Date.now() + 5.5 * 3600_000
    const istDate = new Date(istMs)
    const istMinutes = istDate.getUTCHours() * 60 + istDate.getUTCMinutes()
    const isMarketOpen = istMinutes >= 9 * 60 + 15 && istMinutes <= 15 * 60 + 30

    if (!isMarketOpen) return

    const nextPrev: Record<number, number> = {}
    let prevChanged = false
    setPriceHistory(prev => {
      const merged = { ...prev }
      for (const { token } of NSE_WATCHLIST) {
        const price = ticks[token]?.last_price
        if (price) {
          if (prevPrices[token] !== undefined && prevPrices[token] !== price) {
            nextPrev[token] = prevPrices[token]
            prevChanged = true
          }
          const h = merged[token] ?? []
          merged[token] = [...h, price].slice(-50)
        }
      }
      return merged
    })
    if (prevChanged) setPrevPrices(prev => ({ ...prev, ...nextPrev }))
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticks])

  // Fetch global quotes when switching away from NSE
  const fetchGlobal = useCallback(() => {
    if (globalLoading) return
    setGlobalLoading(true)
    api.globalQuotes().then(data => {
      setGlobalQuotes(data)
      setGlobalLoading(false)
    }).catch(() => setGlobalLoading(false))
  }, [globalLoading])

  useEffect(() => {
    if (tab !== 'NSE' && globalQuotes.length === 0) fetchGlobal()
  }, [tab, globalQuotes.length, fetchGlobal])

  const filteredGlobal = TAB_CATEGORY[tab]
    ? globalQuotes.filter(q => q.category === TAB_CATEGORY[tab])
    : []

  return (
    <div className="panel h-full">
      {/* Tab bar */}
      <div style={{ display: 'flex', borderBottom: '1px solid #1E1E1E', background: '#0D0D0D', flexShrink: 0 }}>
        {TABS.map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            style={{
              flex: 1, padding: '5px 0', fontSize: 9, fontWeight: 600,
              letterSpacing: '0.06em', background: 'none', border: 'none', cursor: 'pointer',
              color:            tab === t ? '#F7931E'   : '#444',
              borderBottom:     tab === t ? '2px solid #F7931E' : '2px solid transparent',
            }}
          >
            {t}
          </button>
        ))}
      </div>

      <div className="panel-body">
        {/* ── NSE live ─────────────────────────────────────────── */}
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
              {NSE_WATCHLIST.map(({ label, token }) => {
                const dp    = displayPrices[token]
                const price = dp?.price ?? 0
                const prev  = prevPrices[token]
                const chg   = dp?.chg ?? 0
                const hist  = priceHistory[token] ?? []
                return (
                  <tr
                    key={token}
                    onClick={() => setSelected({ token, label })}
                    style={{ cursor: 'pointer' }}
                  >
                    <td className="text-[11px] text-gray-300">{label}</td>
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
              })}
            </tbody>
          </table>
        )}

        {/* ── BSE — SENSEX level + SENSEX 30 stocks ────────────── */}
        {tab === 'BSE' && (() => {
          const sensex = globalQuotes.find(q => q.label === 'SENSEX')
          const sensexStocks = NSE_WATCHLIST.filter(w => SENSEX30_TOKENS.has(w.token))
          return (
            <>
              {/* SENSEX index header */}
              <div style={{ padding: '8px 10px', borderBottom: '1px solid #1A1A1A', display: 'flex', alignItems: 'center', gap: 12 }}>
                <span style={{ fontSize: 10, color: '#F7931E', fontWeight: 700, letterSpacing: '0.06em' }}>SENSEX</span>
                {sensex ? (
                  <>
                    <span style={{ fontSize: 14, fontWeight: 700, color: '#E0E0E0', fontVariantNumeric: 'tabular-nums' }}>
                      {sensex.price.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
                    </span>
                    <span style={{ fontSize: 11, fontWeight: 600, color: sensex.change >= 0 ? '#00C853' : '#D32F2F' }}>
                      {sensex.change >= 0 ? '+' : ''}{sensex.change.toFixed(2)}%
                    </span>
                    <span style={{ fontSize: 8, color: '#444', marginLeft: 'auto' }}>DELAYED</span>
                  </>
                ) : (
                  <button onClick={fetchGlobal} style={{ fontSize: 8, color: '#F7931E', background: 'none', border: '1px solid #333', borderRadius: 3, padding: '2px 8px', cursor: 'pointer' }}>
                    LOAD
                  </button>
                )}
              </div>
              {/* SENSEX 30 constituents — live tick data */}
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
                  {sensexStocks.map(({ label, token }) => {
                    const dp    = displayPrices[token]
                    const price = dp?.price ?? 0
                    const prev  = prevPrices[token]
                    const chg   = dp?.chg ?? 0
                    const hist  = priceHistory[token] ?? []
                    return (
                      <tr key={token} onClick={() => setSelected({ token, label })} style={{ cursor: 'pointer' }}>
                        <td className="text-[11px] text-gray-300">{label}</td>
                        <td style={{ padding: '2px 4px' }}><Sparkline prices={hist} up={chg >= 0} /></td>
                        <td>
                          {price > 0 ? <PriceTag value={price} prev={prev} /> : <span className="text-muted">—</span>}
                        </td>
                        <td className={chg >= 0 ? 'text-pos' : 'text-neg'}>
                          {price > 0 ? `${chg >= 0 ? '+' : ''}${chg.toFixed(2)}%` : '—'}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </>
          )
        })()}

        {/* ── Global / FX / Commod / Risk ──────────────────────── */}
        {tab !== 'NSE' && tab !== 'BSE' && (
          globalLoading && filteredGlobal.length === 0
            ? <p style={{ color: '#444', fontSize: 10, textAlign: 'center', marginTop: 20 }}>Fetching via yfinance…</p>
            : filteredGlobal.length === 0
              ? (
                <div style={{ textAlign: 'center', marginTop: 20 }}>
                  <p style={{ color: '#444', fontSize: 10 }}>No data yet</p>
                  <button onClick={fetchGlobal} style={{ marginTop: 6, fontSize: 9, color: '#F7931E', background: 'none', border: '1px solid #333', borderRadius: 3, padding: '3px 10px', cursor: 'pointer' }}>
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
                        <td className="text-[11px] text-gray-300">{q.label}</td>
                        <td className="text-gray-200">
                          {tab === 'FX'
                            ? q.price.toFixed(4)
                            : q.price.toLocaleString('en-IN', { maximumFractionDigits: 2 })}
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
          <p style={{ fontSize: 8, color: '#2A2A2A', textAlign: 'center', padding: '4px 0' }}>
            DELAYED · yfinance · 5-min cache
            <button onClick={fetchGlobal} style={{ marginLeft: 8, color: '#333', background: 'none', border: 'none', cursor: 'pointer', fontSize: 8 }}>↺</button>
          </p>
        )}
      </div>

      {selected && (
        <InstrumentModal
          token={selected.token}
          label={selected.label}
          onClose={() => setSelected(null)}
          onChartSelect={onChartSelect}
        />
      )}
      {selectedGlobal && (
        <GlobalModal
          quote={selectedGlobal}
          onClose={() => setSelectedGlobal(null)}
        />
      )}
    </div>
  )
}
