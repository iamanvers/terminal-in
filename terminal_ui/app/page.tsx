'use client'
import { useState, useEffect } from 'react'
import dynamic from 'next/dynamic'
import MarketDataPanel    from '@/components/panels/MarketDataPanel'
import StrategyBookPanel  from '@/components/panels/StrategyBookPanel'
import PositionsPanel     from '@/components/panels/PositionsPanel'
import SignalFeedPanel    from '@/components/panels/SignalFeedPanel'
import RiskDashboardPanel from '@/components/panels/RiskDashboardPanel'
import ChatPanel          from '@/components/panels/ChatPanel'

const ChartPanel = dynamic(() => import('@/components/panels/ChartPanel'), { ssr: false })

export default function TerminalPage() {
  const [chartIdx, setChartIdx] = useState(0)

  // Keyboard: 1–6 switch chart symbol
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLSelectElement) return
      const n = Number(e.key)
      if (n >= 1 && n <= 6) setChartIdx(n - 1)
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>

      {/* ── Risk strip ───────────────────────────────────────── */}
      <div style={{ height: 52, flexShrink: 0, borderBottom: '1px solid #1E1E1E' }}>
        <RiskDashboardPanel />
      </div>

      {/* ── Main grid ────────────────────────────────────────── */}
      <div style={{
        flex: 1, minHeight: 0,
        display: 'grid',
        gridTemplateColumns: '240px 1fr 310px',
        gridTemplateRows: '1fr 190px 210px',
        gap: 1,
        background: '#060606',
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
