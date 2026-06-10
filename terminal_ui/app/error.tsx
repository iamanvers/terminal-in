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
      flexDirection: 'column', gap: 14, background: '#070707', padding: 40,
    }}>
      <span style={{ fontFamily: 'monospace', fontSize: 13, fontWeight: 700, color: '#EF4444', letterSpacing: '.1em' }}>
        ⚠ MODULE CRASHED
      </span>
      <div style={{
        maxWidth: 560, padding: '12px 16px', background: '#111', border: '1px solid #2A1313',
        borderRadius: 5, fontFamily: 'monospace', fontSize: 10, color: '#9A9A9A', lineHeight: 1.6,
        overflowWrap: 'break-word',
      }}>
        {error.message || 'Unknown render error'}
        {error.digest && <span style={{ color: '#444' }}> · digest {error.digest}</span>}
      </div>
      <div style={{ display: 'flex', gap: 8 }}>
        <button onClick={reset} style={{
          fontFamily: 'monospace', fontSize: 10, fontWeight: 700, letterSpacing: '.07em',
          padding: '7px 20px', borderRadius: 4, cursor: 'pointer',
          border: '1px solid #F7931E55', background: '#F7931E0E', color: '#F7931E',
        }}>↺ RETRY MODULE</button>
        <button onClick={() => (window.location.href = '/')} style={{
          fontFamily: 'monospace', fontSize: 10, letterSpacing: '.07em',
          padding: '7px 20px', borderRadius: 4, cursor: 'pointer',
          border: '1px solid #242424', background: '#111', color: '#9A9A9A',
        }}>GO TO MARKET</button>
      </div>
      <span style={{ fontFamily: 'monospace', fontSize: 9, color: '#383838' }}>
        Other modules keep running — this boundary contains the failure to one page.
      </span>
    </div>
  )
}
