'use client'
/** Last-resort boundary: catches crashes in the root layout itself. */
export default function GlobalError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <html lang="en">
      <body style={{
        margin: 0, height: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
        flexDirection: 'column', gap: 16, background: '#0A0B0D', fontFamily: 'monospace',
      }}>
        <span style={{ fontSize: 14, fontWeight: 700, color: '#F2495C', letterSpacing: '.1em' }}>
          TERMINAL//IN — FATAL UI ERROR
        </span>
        <code style={{ fontSize: 10.5, color: '#AEB3BB', maxWidth: 560, textAlign: 'center' }}>
          {error.message || 'Unknown error'}
        </code>
        <button onClick={reset} style={{
          fontFamily: 'monospace', fontSize: 10.5, fontWeight: 700, letterSpacing: '.07em',
          padding: '8px 22px', borderRadius: 4, cursor: 'pointer',
          border: '1px solid #FFB02E55', background: '#FFB02E0E', color: '#FFB02E',
        }}>↺ RELOAD TERMINAL</button>
      </body>
    </html>
  )
}
