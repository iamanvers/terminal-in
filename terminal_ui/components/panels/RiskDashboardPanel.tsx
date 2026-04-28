'use client'
import { useEffect, useState } from 'react'
import { api, type PortfolioSummary, type RegimeState } from '@/lib/api'
import { useSocketEvent } from '@/hooks/useSocket'
import Badge from '@/components/primitives/Badge'
import clsx from 'clsx'

function Stat({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="flex flex-col gap-0.5 px-3 py-2 border-r border-border last:border-r-0">
      <span className="text-[9px] text-muted uppercase tracking-wide">{label}</span>
      <span className={clsx('text-[13px] font-semibold tabular-nums', color ?? 'text-gray-200')}>
        {value}
      </span>
    </div>
  )
}

export default function RiskDashboardPanel() {
  const [summary, setSummary] = useState<PortfolioSummary | null>(null)
  const [regime, setRegime] = useState<RegimeState | null>(null)
  const pnlUpdate = useSocketEvent<Partial<PortfolioSummary> | null>('pnl_update', null)
  const regimeUpdate = useSocketEvent<RegimeState | null>('regime_update', null)

  useEffect(() => {
    Promise.all([api.portfolio(), api.regime()]).then(([p, r]) => {
      setSummary(p)
      setRegime(r)
    }).catch(() => {})
  }, [])

  useEffect(() => {
    if (pnlUpdate) setSummary(prev => prev ? { ...prev, ...pnlUpdate } : prev)
  }, [pnlUpdate])

  useEffect(() => {
    if (regimeUpdate) setRegime(regimeUpdate)
  }, [regimeUpdate])

  const equity     = summary?.equity ?? 0
  const dailyPnl   = summary?.daily_pnl ?? 0
  const drawdown   = summary?.drawdown ?? 0
  const vix        = summary?.india_vix ?? regime?.india_vix ?? 0
  const sizeMult   = regime?.size_multiplier ?? 1.0
  const regimeName = regime?.regime ?? 'unknown'

  const ddPct   = (drawdown * 100).toFixed(2)
  const ddColor = drawdown > 0.15 ? 'text-neg' : drawdown > 0.05 ? 'text-accent' : 'text-pos'
  const pnlColor = dailyPnl >= 0 ? 'text-pos' : 'text-neg'
  const vixColor = vix > 25 ? 'text-neg' : vix > 18 ? 'text-accent' : 'text-pos'

  // Single-row strip — no panel-header, fits in 52px
  return (
    <div style={{ height: '100%', background: '#0D0D0D', display: 'flex', alignItems: 'center', overflow: 'hidden' }}>
      {/* Regime pill on the left */}
      <div style={{ padding: '0 12px', borderRight: '1px solid #1E1E1E', flexShrink: 0, display: 'flex', alignItems: 'center', gap: 6, height: '100%' }}>
        <span style={{ fontSize: 9, color: '#888', textTransform: 'uppercase', letterSpacing: '0.06em' }}>REGIME</span>
        <Badge variant="regime" value={regimeName} />
        {regime && <span style={{ fontSize: 9, color: '#555' }}>{((regime.confidence ?? 0) * 100).toFixed(0)}%</span>}
      </div>
      {/* Stats */}
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', overflowX: 'auto', minWidth: 0 }}>
        <Stat label="Equity"     value={`₹${equity.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`} />
        <Stat label="Day P&L"    value={`${dailyPnl >= 0 ? '+' : ''}₹${dailyPnl.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`} color={pnlColor} />
        <Stat label="Drawdown"   value={`${ddPct}%`} color={ddColor} />
        <Stat label="India VIX"  value={vix > 0 ? vix.toFixed(2) : '—'} color={vixColor} />
        <Stat label="Size ×"     value={sizeMult.toFixed(2)} />
        <Stat label="Positions"  value={String(summary?.open_positions ?? 0)} />
        <Stat label="Day Trades" value={String(summary?.daily_trades ?? 0)} />
      </div>
      {/* Circuit breaker warning */}
      {drawdown > 0.18 && (
        <div style={{ padding: '0 16px', flexShrink: 0 }}>
          <span style={{ color: '#D32F2F', fontSize: 10, fontWeight: 700, animation: 'pulse 1s infinite' }}>
            ▲ DD {(drawdown * 100).toFixed(1)}% — CIRCUIT
          </span>
        </div>
      )}
    </div>
  )
}
