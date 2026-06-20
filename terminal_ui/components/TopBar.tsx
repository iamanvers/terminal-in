'use client'
import React from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useTickMap, useConnected } from '@/hooks/useSocket'
import { api } from '@/lib/api'
import { getSocket } from '@/lib/socket'
import StatusDot from '@/components/primitives/StatusDot'
import SettingsPanel from '@/components/SettingsPanel'

// Auto-trade toggle: ON = execute signals; OFF = advise-only (signals still
// shown, gate blocks fills). Persisted server-side; synced live over the socket.
function AutoTradeToggle() {
  const [on, setOn] = React.useState<boolean | null>(null)
  React.useEffect(() => {
    api.riskState().then(s => setOn(s.auto_trade !== false)).catch(() => setOn(true))
    const sock = getSocket()
    const h = (m: { auto_trade: boolean }) => setOn(!!m.auto_trade)
    sock.on('trading_mode.auto_trade', h)
    return () => { sock.off('trading_mode.auto_trade', h) }
  }, [])
  if (on === null) return null
  const toggle = async () => { const r = await api.setAutoTrade(!on); setOn(r.auto_trade) }
  return (
    <button onClick={toggle} title={on ? 'Auto-trade ON — click for advise-only' : 'Advise-only — click to enable execution'}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 5, cursor: 'pointer',
        fontSize: 9, fontWeight: 700, letterSpacing: '0.08em', padding: '3px 9px', borderRadius: 999,
        background: on ? '#2DBD8014' : 'transparent',
        border: `1px solid ${on ? '#2DBD8055' : '#71767F55'}`,
        color: on ? '#2DBD80' : '#71767F',
      }}>
      <span style={{ width: 6, height: 6, borderRadius: '50%', background: on ? '#2DBD80' : '#71767F',
        boxShadow: on ? '0 0 6px #2DBD80' : 'none' }} />
      {on ? 'AUTO-TRADE' : 'ADVISE-ONLY'}
    </button>
  )
}

const TICKER_TOKENS = [
  { label: 'NIFTY 50',  token: 256265  },
  { label: 'BANKNIFTY', token: 260105  },
  { label: 'FINNIFTY',  token: 257801  },
  { label: 'INDIA VIX', token: 264969  },
  { label: 'RELIANCE',  token: 738561  },
  { label: 'HDFCBANK',  token: 341249  },
  { label: 'TCS',       token: 2953217 },
  { label: 'INFY',      token: 408065  },
  { label: 'SBIN',      token: 779521  },
  { label: 'AXISBANK',  token: 1510401 },
  { label: 'BAJFINANCE',token: 4267265 },
  { label: 'MARUTI',    token: 2815745 },
  { label: 'LT',        token: 2939009 },
  { label: 'ADANIPORTS',token: 3861249 },
]

// Equities (cash) and F&O (derivatives) are separate modules — the
// instruments behave differently (margining, expiry, lot sizes, greeks).
const NAV = [
  { label: 'MARKET',   href: '/'        },
  { label: 'EQUITIES', href: '/trade'   },
  { label: 'F&O',      href: '/fno'     },
  { label: 'AGENTS',   href: '/agents'  },
  { label: 'TRAIN',    href: '/train'   },
  { label: 'BACKTEST', href: '/backtest'},
  { label: 'LEARN',    href: '/learn'   },
]

// Stable tick item — only re-renders when its specific price/change differs
const TickerItem = React.memo(
  function TickerItem({ label, price, chg }: { label: string; price: number; chg: number }) {
    return (
      <span style={{ display: 'inline-flex', alignItems: 'baseline', gap: 5, flexShrink: 0, padding: '0 18px' }}>
        <span style={{ fontSize: 9.5, color: '#71767F', letterSpacing: '0.05em', textTransform: 'uppercase' }}>{label}</span>
        <span style={{ fontSize: 11.5, color: '#CFD3D9', fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>
          {price > 0 ? price.toLocaleString('en-IN', { maximumFractionDigits: 0 }) : '—'}
        </span>
        {price > 0 && (
          <span style={{ fontSize: 10, color: chg >= 0 ? '#2DBD80' : '#F2495C', fontVariantNumeric: 'tabular-nums' }}>
            {chg >= 0 ? '+' : ''}{chg.toFixed(2)}%
          </span>
        )}
      </span>
    )
  },
  (prev, next) => prev.price === next.price && prev.chg === next.chg,
)

function isNSEOpen(): boolean {
  const d = new Date(Date.now() + 5.5 * 3600_000)
  const m = d.getUTCHours() * 60 + d.getUTCMinutes()
  return m >= 9 * 60 + 15 && m <= 15 * 60 + 30
}

// Isolated ticker component so ticks don't re-render the nav/header
function TickerTape() {
  const ticks = useTickMap()
  const marketOpen = isNSEOpen()

  // prices[token] = { price, chg } — seeded from closes on mount, overwritten by live ticks
  const [prices, setPrices] = React.useState<Record<number, { price: number; chg: number }>>({})

  // On mount: load last close prices so the tape is populated even when market is closed
  React.useEffect(() => {
    api.lastCloses().then(closes => {
      setPrices(prev => {
        const next = { ...prev }
        for (const { token } of TICKER_TOKENS) {
          const rec = closes[String(token)]
          if (rec && rec.close > 0 && !next[token]) {
            // After close, keep showing the last session's % move (not 0.00%)
            next[token] = { price: rec.close, chg: rec.change ?? 0 }
          }
        }
        return next
      })
    }).catch(() => {})
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Merge live WebSocket ticks — only update during market hours (or always fill missing)
  React.useEffect(() => {
    setPrices(prev => {
      const next = { ...prev }
      let changed = false
      for (const { token } of TICKER_TOKENS) {
        const p = ticks[token]?.last_price
        if (!p) continue
        if (!prev[token] || marketOpen) {
          next[token] = { price: p, chg: ticks[token]?.change ?? 0 }
          changed = true
        }
      }
      return changed ? next : prev
    })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticks])

  const items = React.useMemo(() => TICKER_TOKENS.map(({ label, token }) => ({
    label, token,
    price: prices[token]?.price ?? 0,
    chg:   prices[token]?.chg   ?? 0,
  })), [prices])

  return (
    <div style={{ height: 24, overflow: 'hidden', background: 'rgba(10,11,13,0.78)', backdropFilter: 'blur(7px)', borderBottom: '1px solid #23272E', display: 'flex', alignItems: 'center' }}>
      {/* Market state lives in the top-right StatusDot — never inside the tape */}
      {/* Two identical sets with distinct key namespaces for seamless CSS marquee loop */}
      <div className="ticker-track">
        {items.map(({ label, token, price, chg }) => (
          <TickerItem key={`a-${token}`} label={label} price={price} chg={chg} />
        ))}
        {items.map(({ label, token, price, chg }) => (
          <TickerItem key={`b-${token}`} label={label} price={price} chg={chg} />
        ))}
      </div>
    </div>
  )
}

// Static header — never re-renders due to tick updates
function NavHeader() {
  const connected = useConnected()
  const pathname  = usePathname()
  const [settingsOpen, setSettingsOpen] = React.useState(false)
  return (
    <header style={{
      height: 38, display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      padding: '0 18px', borderBottom: '1px solid var(--border-strong, #333841)',
      background: 'rgba(18,20,25,0.82)', backdropFilter: 'blur(7px)', flexShrink: 0,
    }}>
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 9, flexShrink: 0 }}>
        {/* Brand mark (same artwork as the favicon at app/icon.svg) */}
        <svg width="20" height="20" viewBox="0 0 64 64" aria-hidden="true">
          <rect width="64" height="64" rx="14" fill="#111317" />
          <rect x="12" y="30" width="7" height="16" rx="1.5" fill="#004AF8" />
          <rect x="15" y="25" width="1.6" height="21" fill="#004AF8" />
          <rect x="26" y="20" width="7" height="20" rx="1.5" fill="#0094FB" />
          <rect x="29" y="14" width="1.6" height="26" fill="#0094FB" />
          <rect x="40" y="12" width="7" height="16" rx="1.5" fill="#00B9FC" />
          <rect x="43" y="7" width="1.6" height="28" fill="#00B9FC" />
          <path d="M36 56 L44 40" stroke="#ECEEF1" strokeWidth="3.4" strokeLinecap="round" />
          <path d="M45 56 L53 40" stroke="#ECEEF1" strokeWidth="3.4" strokeLinecap="round" />
        </svg>
        <span style={{ fontFamily: 'var(--font-mono, monospace)', fontWeight: 700, color: '#ECEEF1', letterSpacing: '0.12em', fontSize: 13 }}>
          TERMINAL<span style={{ color: '#0094FB' }}>//</span>IN
          <span style={{ fontSize: 9.5, color: '#4A4F57', marginLeft: 10, letterSpacing: '0.08em', fontWeight: 500 }}>NSE · PAPER</span>
        </span>
      </span>

      {/* Module navigation tabs */}
      <nav style={{ display: 'flex', gap: 4, height: '100%', alignItems: 'stretch' }}>
        {NAV.map(({ label, href }) => {
          const active = href === '/' ? pathname === '/' : pathname.startsWith(href)
          return (
            <Link
              key={href}
              href={href}
              style={{
                display: 'flex', alignItems: 'center',
                fontSize: 10.5, fontWeight: active ? 700 : 500,
                letterSpacing: '0.09em', padding: '0 16px',
                textDecoration: 'none', cursor: 'pointer',
                background:   active ? 'var(--accent-soft, #0094FB0E)' : 'transparent',
                color:        active ? '#0094FB' : '#71767F',
                boxShadow:    active ? 'inset 0 -2px 0 #0094FB' : 'none',
                transition: 'color 0.15s, background 0.15s',
              }}
            >
              {label}
            </Link>
          )
        })}
      </nav>

      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 12 }}>
        <AutoTradeToggle />
        <button
          onClick={() => setSettingsOpen(true)}
          aria-label="Settings"
          title="Settings"
          style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 2, display: 'flex', color: '#71767F' }}
          onMouseEnter={e => (e.currentTarget.style.color = '#ECEEF1')}
          onMouseLeave={e => (e.currentTarget.style.color = '#71767F')}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33h.01a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51h.01a1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82v.01a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
          </svg>
        </button>
        <StatusDot connected={connected} />
      </span>
      <SettingsPanel open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </header>
  )
}

export default function TopBar() {
  return (
    <>
      <NavHeader />
      <TickerTape />
    </>
  )
}
