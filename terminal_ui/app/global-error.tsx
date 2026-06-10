'use client'
/** Last-resort boundary: catches crashes in the root layout itself. */
export default function GlobalError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <html lang="en">
      <body style={{
        margin: 0, height: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
        flexDirection: 'column', gap: 16, background: '#070707', fontFamily: 'monospace',
      }}>
        <span style={{ fontSize: 14, fontWeight: 700, color: '#EF4444', letterSpacing: '.1em' }}>
          TERMINAL//IN — FATAL UI ERROR
        </span>
        <code style={{ fontSize: 10, color: '#9A9A9A', maxWidth: 560, textAlign: 'center' }}>
          {error.message || 'Unknown error'}
        </code>
        <button onClick={reset} style={{
          fontFamily: 'monospace', fontSize: 10, fontWeight: 700, letterSpacing: '.07em',
          padding: '8px 22px', borderRadius: 4, cursor: 'pointer',
          border: '1px solid #F7931E55', background: '#F7931E0E', color: '#F7931E',
        }}>↺ RELOAD TERMINAL</button>
      </body>
    </html>
  )
}
