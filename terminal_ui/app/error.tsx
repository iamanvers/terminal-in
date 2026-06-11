'use client'
/**
 * Route-level error boundary — a crash in any page renders this recoverable
 * panel instead of a white screen or an unstyled Next.js overlay.
 */
import { useEffect } from 'react'

export default function Error({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => { console.error('[terminal-in] page error:', error) }, [error])

  return (
    <div style={{
      flex: 1, minHeight: 0, display: 'flex', alignItems: 'center', justifyContent: 'center',
      flexDirection: 'column', gap: 14, background: '#0A0B0D', padding: 40,
    }}>
      <span style={{ fontFamily: 'monospace', fontSize: 13, fontWeight: 700, color: '#E5484D', letterSpacing: '.1em' }}>
        ⚠ MODULE CRASHED
      </span>
      <div style={{
        maxWidth: 560, padding: '12px 16px', background: '#14161A', border: '1px solid #2A1313',
        borderRadius: 5, fontFamily: 'monospace', fontSize: 10.5, color: '#9BA3AD', lineHeight: 1.6,
        overflowWrap: 'break-word',
      }}>
        {error.message || 'Unknown render error'}
        {error.digest && <span style={{ color: '#5F6772' }}> · digest {error.digest}</span>}
      </div>
      <div style={{ display: 'flex', gap: 8 }}>
        <button onClick={reset} style={{
          fontFamily: 'monospace', fontSize: 10.5, fontWeight: 700, letterSpacing: '.07em',
          padding: '7px 20px', borderRadius: 4, cursor: 'pointer',
          border: '1px solid #4E80B455', background: '#4E80B40E', color: '#4E80B4',
        }}>↺ RETRY MODULE</button>
        <button onClick={() => (window.location.href = '/')} style={{
          fontFamily: 'monospace', fontSize: 10.5, letterSpacing: '.07em',
          padding: '7px 20px', borderRadius: 4, cursor: 'pointer',
          border: '1px solid #2B303A', background: '#14161A', color: '#9BA3AD',
        }}>GO TO MARKET</button>
      </div>
      <span style={{ fontFamily: 'monospace', fontSize: 10, color: '#3C424B' }}>
        Other modules keep running — this boundary contains the failure to one page.
      </span>
    </div>
  )
}
