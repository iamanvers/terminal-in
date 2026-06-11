'use client'
import { useEffect, useState } from 'react'
import { api, type RegimeState } from '@/lib/api'
import { useSocketEvent } from '@/hooks/useSocket'

// All 6 HMM regimes with their size multipliers, colors, and descriptions.
const REGIMES = [
  { name: 'strong_bull', label: 'STRONG BULL', color: '#3FD487', mult: 1.2, desc: 'Trending hard up' },
  { name: 'bull',        label: 'BULL',        color: '#2FBF71', mult: 1.0, desc: 'Uptrend normal' },
  { name: 'sideways',    label: 'SIDEWAYS',    color: '#4E80B4', mult: 0.7, desc: 'Range-bound' },
  { name: 'bear',        label: 'BEAR',        color: '#EF5350', mult: 0.5, desc: 'Downtrend' },
  { name: 'strong_bear', label: 'STRONG BEAR', color: '#A13238', mult: 0.3, desc: 'Hard down minimal' },
  { name: 'high_vol',    label: 'HIGH VOL',    color: '#B07CC6', mult: 0.2, desc: 'VIX elevated' },
]

export default function RiskDashboardPanel() {
  const [regime, setRegime] = useState<RegimeState | null>(null)
  const regimeUpdate = useSocketEvent<RegimeState | null>('regime_update', null)

  useEffect(() => {
    // Retry a few times — the backend pre-seeds a default regime, but if the
    // first fetch races the boot, don't leave the strip stuck on "unknown".
    let cancelled = false
    const tryFetch = (attempt: number) => {
      api.regime()
        .then(r => { if (!cancelled && r && r.regime) setRegime(r) })
        .catch(() => {
          if (!cancelled && attempt < 3) setTimeout(() => tryFetch(attempt + 1), 2000 * (attempt + 1))
        })
    }
    tryFetch(0)
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    if (regimeUpdate) setRegime(regimeUpdate)
  }, [regimeUpdate])

  const current = regime?.regime ?? 'unknown'
  const conf    = regime ? Math.round((regime.confidence ?? 0) * 100) : null
  const vix     = regime?.india_vix ?? 0
  const sizeMul = regime?.size_multiplier ?? 1.0

  const currentDef = REGIMES.find(r => r.name === current)

  return (
    <div style={{ height: '100%', background: '#0A0B0D', display: 'flex', alignItems: 'center', overflow: 'hidden', gap: 0 }}>

      {/* Current regime — large pill on the left */}
      <div style={{
        padding: '0 16px', height: '100%', flexShrink: 0,
        display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: 2,
        borderRight: '1px solid #20242B',
        background: currentDef ? `${currentDef.color}08` : 'transparent',
      }}>
        <span style={{ fontSize: 9, color: '#3C424B', letterSpacing: '.09em' }}>REGIME</span>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
          <span style={{
            fontSize: 13, fontWeight: 800, letterSpacing: '.04em',
            color: currentDef?.color ?? '#9BA3AD',
          }}>
            {currentDef?.label ?? current.replace(/_/g, ' ').toUpperCase()}
          </span>
          {conf !== null && (
            <span style={{ fontSize: 9.5, color: '#5F6772', fontVariantNumeric: 'tabular-nums' }}>{conf}%</span>
          )}
        </div>
      </div>

      {/* Size multiplier + VIX */}
      <div style={{ padding: '0 14px', height: '100%', flexShrink: 0, display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: 2, borderRight: '1px solid #20242B' }}>
        <span style={{ fontSize: 9, color: '#3C424B', letterSpacing: '.09em' }}>SIZE ×</span>
        <span style={{ fontSize: 13, fontWeight: 700, color: currentDef?.color ?? '#9BA3AD', fontVariantNumeric: 'tabular-nums' }}>
          {sizeMul.toFixed(2)}
        </span>
      </div>
      <div style={{ padding: '0 14px', height: '100%', flexShrink: 0, display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: 2, borderRight: '1px solid #20242B' }}>
        <span style={{ fontSize: 9, color: '#3C424B', letterSpacing: '.09em' }}>INDIA VIX</span>
        <span style={{ fontSize: 13, fontWeight: 700, fontVariantNumeric: 'tabular-nums', color: vix > 25 ? '#EF5350' : vix > 18 ? '#4E80B4' : '#9BA3AD' }}>
          {vix > 0 ? vix.toFixed(2) : '—'}
        </span>
      </div>

      {/* Regime legend — scrollable horizontal, all 6 states with full names */}
      <div style={{ flex: 1, height: '100%', display: 'flex', alignItems: 'stretch', overflowX: 'auto', minWidth: 0 }}>
        {REGIMES.map(r => {
          const active = r.name === current
          return (
            <div key={r.name} style={{
              display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: 1,
              padding: '0 14px', flexShrink: 0,
              borderRight: '1px solid #191C21',
              background: active ? `${r.color}0D` : 'transparent',
              borderBottom: active ? `2px solid ${r.color}` : '2px solid transparent',
              transition: 'background .2s',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                <span style={{
                  width: active ? 6 : 4, height: active ? 6 : 4, borderRadius: '50%', flexShrink: 0,
                  background: active ? r.color : '#3C424B',
                  boxShadow: active ? `0 0 5px ${r.color}88` : 'none',
                  transition: 'all .2s',
                }} />
                <span style={{ fontSize: active ? 10 : 8, fontWeight: active ? 800 : 500, color: active ? r.color : '#3C424B', letterSpacing: '.04em', whiteSpace: 'nowrap' }}>
                  {r.label}
                </span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, paddingLeft: 11 }}>
                <span style={{ fontSize: 9.5, color: active ? `${r.color}99` : '#2B303A', fontVariantNumeric: 'tabular-nums', fontWeight: 600 }}>
                  size ×{r.mult}
                </span>
                <span style={{ fontSize: 9, color: active ? '#5F6772' : '#20242B', whiteSpace: 'nowrap' }}>
                  {r.desc}
                </span>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
