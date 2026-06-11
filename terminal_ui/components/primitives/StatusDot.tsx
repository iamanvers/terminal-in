'use client'
import { useConnStatus } from '@/hooks/useSocket'

function nseOpen(): boolean {
  const d = new Date(Date.now() + 5.5 * 3600_000)
  const day = d.getUTCDay()
  if (day === 0 || day === 6) return false
  const m = d.getUTCHours() * 60 + d.getUTCMinutes()
  return m >= 9 * 60 + 15 && m <= 15 * 60 + 30
}

// Connection + market state in one place (top right, every screen):
//   LIVE   — connected, NSE session open
//   CLOSED — connected, NSE shut (grey; prices are last close)
//   RECONNECTING / DISCONNECTED — transport state trumps market state
export default function StatusDot({ connected: _ }: { connected?: boolean }) {
  const status = useConnStatus()
  const open = nseOpen()
  const color =
    status !== 'connected' ? (status === 'reconnecting' ? '#0094FB' : '#F2495C')
    : open ? '#2DBD80' : '#71767F'
  const label =
    status === 'reconnecting' ? 'RECONNECTING…'
    : status !== 'connected' ? 'DISCONNECTED'
    : open ? 'LIVE' : 'CLOSED'
  return (
    <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
      <span style={{
        width: 6, height: 6, borderRadius: '50%', background: color, display: 'inline-block', flexShrink: 0,
        animation: status === 'connected' && open ? 'pulse 2s ease-in-out infinite' : status === 'reconnecting' ? 'blink .9s ease-in-out infinite' : 'none',
      }} />
      <span style={{ fontSize: 10, color, letterSpacing: '.06em' }}>{label}</span>
    </span>
  )
}
