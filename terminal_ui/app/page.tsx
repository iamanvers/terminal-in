'use client'
import { useState, useEffect, useRef } from 'react'
import dynamic from 'next/dynamic'
import MarketDataPanel    from '@/components/panels/MarketDataPanel'
import StrategyBookPanel  from '@/components/panels/StrategyBookPanel'
import PositionsPanel     from '@/components/panels/PositionsPanel'
import SignalFeedPanel    from '@/components/panels/SignalFeedPanel'
import RiskDashboardPanel from '@/components/panels/RiskDashboardPanel'
import ChatPanel          from '@/components/panels/ChatPanel'
import { api }            from '@/lib/api'

const ChartPanel = dynamic(() => import('@/components/panels/ChartPanel'), { ssr: false })

// ── Loading screen ────────────────────────────────────────────────────────────
const STEPS = [
  'Connecting to backend…',
  'Loading market data…',
  'Initializing strategy engine…',
  'Fetching regime state…',
  'Syncing portfolio…',
  'Ready.',
]

function BootScreen({ error }: { error: boolean }) {
  const [step, setStep] = useState(0)
  const [dots, setDots] = useState(0)

  useEffect(() => {
    if (error) return
    const t = setInterval(() => setStep(s => Math.min(s + 1, STEPS.length - 2)), 900)
    return () => clearInterval(t)
  }, [error])

  useEffect(() => {
    const t = setInterval(() => setDots(d => (d + 1) % 4), 400)
    return () => clearInterval(t)
  }, [])

  const dotStr = '.'.repeat(dots)

  return (
    <div style={{
      flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column',
      alignItems: 'center', justifyContent: 'center',
      background: '#070707', gap: 0,
    }}>
      {/* Logo */}
      <div style={{ marginBottom: 32, textAlign: 'center' }}>
        <div style={{
          fontSize: 28, fontWeight: 900, letterSpacing: '.18em',
          color: error ? '#E53935' : '#D0D0D0',
          fontFamily: 'monospace',
        }}>
          TERMINAL<span style={{ color: error ? '#E53935' : '#F7931E' }}>//</span>IN
        </div>
        <div style={{ fontSize: 9, color: '#2A2A2A', letterSpacing: '.2em', marginTop: 5 }}>
          NSE · BSE · ALGORITHMIC TRADING
        </div>
      </div>

      {/* Status block */}
      <div style={{
        border: `1px solid ${error ? '#E5393533' : '#1A1A1A'}`,
        borderRadius: 6, padding: '20px 32px', minWidth: 360,
        background: error ? '#0E0808' : '#0A0A0A',
        display: 'flex', flexDirection: 'column', gap: 14, alignItems: 'center',
      }}>
        {error ? (
          <>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ color: '#E53935', fontSize: 16 }}>⚡</span>
              <span style={{ fontSize: 11, color: '#E53935', fontWeight: 700, letterSpacing: '.08em' }}>
                BACKEND NOT RUNNING
              </span>
            </div>
            <div style={{ fontSize: 9, color: '#555', textAlign: 'center', lineHeight: 1.7 }}>
              The Python backend is not reachable at{' '}
              <code style={{ color: '#888', background: '#111', padding: '1px 5px', borderRadius: 3 }}>
                localhost:5000
              </code>
            </div>
            <div style={{
              background: '#111', border: '1px solid #1A1A1A', borderRadius: 4,
              padding: '10px 14px', fontFamily: 'monospace', fontSize: 9, color: '#F7931E',
              lineHeight: 1.8, width: '100%',
            }}>
              <div style={{ color: '#333', marginBottom: 4 }}># Start the backend</div>
              <div>.venv\Scripts\python.exe -m terminal_in.main</div>
              <div style={{ color: '#333', marginTop: 6, marginBottom: 4 }}># Or use the launcher</div>
              <div>.\start.ps1</div>
            </div>
            <button
              onClick={() => window.location.reload()}
              style={{
                fontSize: 9, fontWeight: 700, letterSpacing: '.08em', padding: '7px 20px',
                border: '1px solid #E5393544', borderRadius: 4,
                background: '#1A0808', color: '#E53935', cursor: 'pointer',
              }}
            >
              ↺ RETRY CONNECTION
            </button>
          </>
        ) : (
          <>
            {/* Spinner */}
            <div style={{ position: 'relative', width: 36, height: 36 }}>
              <div style={{
                position: 'absolute', inset: 0, borderRadius: '50%',
                border: '2px solid #141414',
                borderTopColor: '#F7931E',
                animation: 'spin 0.9s linear infinite',
              }} />
              <style dangerouslySetInnerHTML={{ __html: '@keyframes spin { to { transform: rotate(360deg) } }' }} />
            </div>
            {/* Step log */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 3, width: '100%' }}>
              {STEPS.slice(0, step + 1).map((s, i) => (
                <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ fontSize: 9, color: i < step ? '#2A4A2A' : '#F7931E', minWidth: 12 }}>
                    {i < step ? '✓' : '›'}
                  </span>
                  <span style={{ fontSize: 9, color: i < step ? '#2A4A2A' : '#888', fontVariantNumeric: 'tabular-nums' }}>
                    {i === step ? s.replace('…', dotStr || '…') : s.replace('…', '')}
                  </span>
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────
type ReadyState = 'loading' | 'ready' | 'error'

export default function TerminalPage() {
  const [readyState, setReadyState] = useState<ReadyState>('loading')
  const [chartIdx,   setChartIdx]   = useState(0)
  const resolvedRef = useRef(false)

  useEffect(() => {
    // Probe the three critical endpoints that gate the dashboard render.
    // If any succeed, the backend is up. Retries with backoff so a backend
    // that is still booting doesn't flash a false "BACKEND NOT RUNNING".
    let cancelled = false
    const ATTEMPTS = 5
    const ATTEMPT_TIMEOUT_MS = 4000
    const BACKOFF_MS = [0, 1500, 2500, 4000, 5000]

    const probeOnce = (): Promise<boolean> => {
      const timeout = new Promise<never>((_, reject) =>
        setTimeout(() => reject(new Error('timeout')), ATTEMPT_TIMEOUT_MS)
      )
      return Promise.race([
        Promise.allSettled([api.regime(), api.instruments(), api.portfolio()]),
        timeout,
      ])
        .then(results => (results as PromiseSettledResult<unknown>[]).some(r => r.status === 'fulfilled'))
        .catch(() => false)
    }

    const run = async () => {
      for (let attempt = 0; attempt < ATTEMPTS && !cancelled; attempt++) {
        if (BACKOFF_MS[attempt]) await new Promise(r => setTimeout(r, BACKOFF_MS[attempt]))
        if (cancelled) return
        const ok = await probeOnce()
        if (cancelled || resolvedRef.current) return
        if (ok) {
          resolvedRef.current = true
          setReadyState('ready')
          return
        }
      }
      if (!cancelled && !resolvedRef.current) {
        resolvedRef.current = true
        setReadyState('error')
      }
    }
    run()
    return () => { cancelled = true }
  }, [])

  // Keyboard: 1–6 switch chart symbol
  useEffect(() => {
    if (readyState !== 'ready') return
    const handler = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLSelectElement) return
      const n = Number(e.key)
      if (n >= 1 && n <= 6) setChartIdx(n - 1)
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [readyState])

  if (readyState !== 'ready') {
    return <BootScreen error={readyState === 'error'} />
  }

  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>

      {/* ── Risk strip ───────────────────────────────────────── */}
      <div style={{ height: 52, flexShrink: 0, borderBottom: '1px solid #1E1E1E' }}>
        <RiskDashboardPanel />
      </div>

      {/* ── Main grid — breathing room + rounded panels to match the
             other modules (1px fused grid read as cramped/MVP) ───── */}
      <div style={{
        flex: 1, minHeight: 0,
        display: 'grid',
        gridTemplateColumns: 'minmax(220px, 250px) 1fr minmax(280px, 320px)',
        gridTemplateRows: 'minmax(0, 1fr) 190px 210px',
        gap: 7,
        padding: '7px 9px',
        background: '#070707',
        overflow: 'hidden',
      }}>
        {/* Col 1, rows 1+2: Market Data (with tabs) */}
        <div style={{ gridRow: '1 / 3', gridColumn: 1, overflow: 'hidden', minHeight: 0 }}>
          <MarketDataPanel onChartSelect={setChartIdx} />
        </div>

        {/* Col 2, row 1: Chart */}
        <div style={{ gridRow: 1, gridColumn: 2, overflow: 'hidden', minHeight: 0 }}>
          <ChartPanel symbolIdx={chartIdx} setSymbolIdx={setChartIdx} />
        </div>

        {/* Col 3, row 1: Chat */}
        <div style={{ gridRow: 1, gridColumn: 3, overflow: 'hidden', minHeight: 0 }}>
          <ChatPanel />
        </div>

        {/* Col 2, row 2: Positions */}
        <div style={{ gridRow: 2, gridColumn: 2, overflow: 'hidden', minHeight: 0 }}>
          <PositionsPanel />
        </div>

        {/* Col 3, row 2: Best Signals */}
        <div style={{ gridRow: 2, gridColumn: 3, overflow: 'hidden', minHeight: 0 }}>
          <StrategyBookPanel />
        </div>

        {/* Row 3: Signal Feed full width */}
        <div style={{ gridRow: 3, gridColumn: '1 / 4', overflow: 'hidden', minHeight: 0 }}>
          <SignalFeedPanel />
        </div>
      </div>
    </div>
  )
}
