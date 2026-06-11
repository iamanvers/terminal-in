'use client'
import { useConnStatus } from '@/hooks/useSocket'

export default function StatusDot({ connected: _ }: { connected?: boolean }) {
  const status = useConnStatus()
  const color  = status === 'connected' ? '#2DBD80' : status === 'reconnecting' ? '#0094FB' : '#F2495C'
  const label  = status === 'connected' ? 'LIVE' : status === 'reconnecting' ? 'RECONNECTING…' : 'DISCONNECTED'
  return (
    <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
      <span style={{
        width: 6, height: 6, borderRadius: '50%', background: color, display: 'inline-block', flexShrink: 0,
        animation: status === 'connected' ? 'pulse 2s ease-in-out infinite' : status === 'reconnecting' ? 'blink .9s ease-in-out infinite' : 'none',
      }} />
      <span style={{ fontSize: 10, color, letterSpacing: '.06em' }}>{label}</span>
    </span>
  )
}
