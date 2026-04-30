'use client'
import { useEffect, useState } from 'react'
import { api, type Position } from '@/lib/api'
import { useSocketEvent } from '@/hooks/useSocket'
import { useTickMap } from '@/hooks/useSocket'
import Badge from '@/components/primitives/Badge'
import clsx from 'clsx'

function isNSEOpen(): boolean {
  const d = new Date(Date.now() + 5.5 * 3600_000)
  const m = d.getUTCHours() * 60 + d.getUTCMinutes()
  return m >= 9 * 60 + 15 && m <= 15 * 60 + 30
}

export default function PositionsPanel() {
  const [positions, setPositions] = useState<Position[]>([])
  const ticks = useTickMap()
  const marketOpen = isNSEOpen()
  const tradeOpened  = useSocketEvent<Position | null>('trade_opened', null)
  const tradeClosed  = useSocketEvent<{ trade_id: string } | null>('trade_closed', null)

  useEffect(() => {
    api.positions().then(setPositions).catch(() => {})
  }, [])

  useEffect(() => {
    if (tradeOpened) setPositions(prev => [tradeOpened, ...prev])
  }, [tradeOpened])

  useEffect(() => {
    if (tradeClosed) setPositions(prev => prev.filter(p => p.trade_id !== tradeClosed.trade_id))
  }, [tradeClosed])

  function unrealised(pos: Position): number | null {
    if (!marketOpen) return null  // freeze after market close
    const tick = ticks[pos.instrument_id]
    if (!tick) return null
    const price = tick.last_price
    const sign = pos.side === 'BUY' ? 1 : -1
    return sign * (price - pos.entry_price) * pos.quantity
  }

  return (
    <div className="panel h-full">
      <div className="panel-header justify-between">
        <span><span className="accent">▸</span> OPEN POSITIONS</span>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {!marketOpen && <span style={{ fontSize: 8, color: '#555', letterSpacing: '0.06em' }}>MARKET CLOSED</span>}
          <span className="text-muted">{positions.length} open</span>
        </div>
      </div>
      <div className="panel-body">
        {positions.length === 0
          ? <p className="text-muted text-center mt-4 text-[11px]">No open positions</p>
          : (
            <table>
              <thead>
                <tr>
                  <th>Strat</th>
                  <th>Side</th>
                  <th>Qty</th>
                  <th>Entry</th>
                  <th>Mkt</th>
                  <th>Unreal</th>
                  <th>SL</th>
                </tr>
              </thead>
              <tbody>
                {positions.map(pos => {
                  const unr = unrealised(pos)
                  const mkt = ticks[pos.instrument_id]?.last_price
                  return (
                    <tr key={pos.trade_id}>
                      <td className="text-accent">{pos.strategy_id}</td>
                      <td><Badge variant="side" value={pos.side} /></td>
                      <td>{pos.quantity}</td>
                      <td className="text-gray-300">{pos.entry_price.toFixed(2)}</td>
                      <td className="text-gray-300">{mkt ? mkt.toFixed(2) : '—'}</td>
                      <td className={clsx(
                        unr === null ? 'text-muted' : unr >= 0 ? 'text-pos' : 'text-neg'
                      )}>
                        {unr === null ? '—' : `${unr >= 0 ? '+' : ''}${unr.toFixed(0)}`}
                      </td>
                      <td className="text-neg">{pos.stop_loss?.toFixed(2) ?? '—'}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )
        }
      </div>
    </div>
  )
}
