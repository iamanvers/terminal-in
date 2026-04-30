'use client'
import React from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useTickMap, useConnected } from '@/hooks/useSocket'
import StatusDot from '@/components/primitives/StatusDot'

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

const NAV = [
  { label: 'MARKET',  href: '/'        },
  { label: 'TRADE',   href: '/trade'   },
  { label: 'AGENTS',  href: '/agents'  },
  { label: 'TRAIN',   href: '/train'   },
]

// Stable tick item — only re-renders when its specific price/change differs
const TickerItem = React.memo(
  function TickerItem({ label, price, chg }: { label: string; price: number; chg: number }) {
    return (
      <span style={{ display: 'inline-flex', alignItems: 'baseline', gap: 5, flexShrink: 0, padding: '0 18px' }}>
        <span style={{ fontSize: 8, color: '#444', letterSpacing: '0.05em', textTransform: 'uppercase' }}>{label}</span>
        <span style={{ fontSize: 11, color: '#C0C0C0', fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>
          {price > 0 ? price.toLocaleString('en-IN', { maximumFractionDigits: 0 }) : '—'}
        </span>
        {price > 0 && (
          <span style={{ fontSize: 9, color: chg >= 0 ? '#00C853' : '#D32F2F', fontVariantNumeric: 'tabular-nums' }}>
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

  // Snapshot prices at market open — freeze after close
  const [frozen, setFrozen] = React.useState<Record<number, { price: number; chg: number }>>({})
  React.useEffect(() => {
    setFrozen(prev => {
      const next = { ...prev }
      for (const { token } of TICKER_TOKENS) {
        const p = ticks[token]?.last_price
        if (p === undefined) continue
        if (prev[token] === undefined || marketOpen) {
          next[token] = { price: p, chg: ticks[token]?.change ?? 0 }
        }
      }
      return next
    })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticks])

  const items = TICKER_TOKENS.map(({ label, token }) => ({
    label, token,
    price: frozen[token]?.price ?? 0,
    chg:   frozen[token]?.chg   ?? 0,
  }))

  return (
    <div style={{ height: 24, overflow: 'hidden', background: '#0A0A0A', borderBottom: '1px solid #161616', display: 'flex', alignItems: 'center' }}>
      {!marketOpen && (
        <span style={{ fontSize: 8, color: '#333', letterSpacing: '0.08em', padding: '0 10px', flexShrink: 0, borderRight: '1px solid #161616' }}>
          CLOSED
        </span>
      )}
      {/* Two separate map calls with distinct key namespaces — prevents React fiber reuse that causes animation restart */}
      <div className="ticker-track" style={{ animationPlayState: marketOpen ? 'running' : 'paused' }}>
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
  return (
    <header style={{ height: 32, display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 16px', borderBottom: '1px solid #1E1E1E', background: '#0D0D0D', flexShrink: 0 }}>
      <span style={{ fontFamily: 'monospace', fontWeight: 700, color: '#F7931E', letterSpacing: '0.1em', fontSize: 13, flexShrink: 0 }}>
        TERMINAL<span style={{ color: '#555' }}>//</span>IN
      </span>

      {/* Module navigation tabs */}
      <nav style={{ display: 'flex', gap: 2 }}>
        {NAV.map(({ label, href }) => {
          const active = href === '/' ? pathname === '/' : pathname.startsWith(href)
          return (
            <Link
              key={href}
              href={href}
              style={{
                fontSize: 9, fontWeight: active ? 700 : 500,
                letterSpacing: '0.08em', padding: '4px 14px',
                borderRadius: 3, textDecoration: 'none', cursor: 'pointer',
                background:   active ? '#F7931E18' : 'transparent',
                color:        active ? '#F7931E'   : '#444',
                borderBottom: active ? '2px solid #F7931E' : '2px solid transparent',
                transition: 'color 0.15s',
              }}
            >
              {label}
            </Link>
          )
        })}
      </nav>

      <StatusDot connected={connected} />
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
