'use client'
import { useTickMap, useSocketList, useSocketEvent } from '@/hooks/useSocket'
import Badge from '@/components/primitives/Badge'

const TOKEN_NAME: Record<number, string> = {
  256265: 'NIFTY 50', 260105: 'BANKNIFTY', 257801: 'FINNIFTY',
  264969: 'INDIA VIX', 2800641: 'NIFTYBEES',
  738561: 'RELIANCE', 341249: 'HDFCBANK', 2953217: 'TCS',
  408065: 'INFY', 1270529: 'ICICIBANK', 779521: 'SBIN',
  1510401: 'AXISBANK', 492033: 'KOTAKBANK', 4267265: 'BAJFINANCE',
  356865: 'HINDUNILVR', 969473: 'WIPRO',
  2939009: 'LT', 2815745: 'MARUTI', 60417: 'ASIANPAINT',
  884737: 'TATAMOTORS', 857857: 'SUNPHARMA', 895745: 'TATASTEEL',
  3834113: 'POWERGRID', 2977281: 'NTPC', 633601: 'ONGC',
  897537: 'TITAN', 1850625: 'HCLTECH', 3465729: 'TECHM',
  3861249: 'ADANIPORTS', 2952193: 'ULTRACEMCO', 4598529: 'NESTLEIND',
  3001089: 'JSWSTEEL', 225537: 'DRREDDY', 4268801: 'BAJAJFINSV',
  2865793: 'DIVISLAB', 348929: 'HINDALCO',
}

const STRAT_DESC: Record<string, string> = {
  S1: 'Opening Range Breakout',
  S2: '52-Week Breakout',
  S3: 'Midcap Breakout',
  S4: 'RSI Mean Reversion',
  S5: 'EMA Pullback',
  S6: 'Pairs Cointegration',
  S8: 'VIX Asymmetry',
  S9: 'Hawkes Momentum',
}

type SignalEntry = {
  strategy_id: string
  side: string
  instrument_id: number
  confidence: number
  regime: string
  stop_loss?: number
  target?: number
  metadata?: Record<string, unknown>
  ts?: number
}

function ConfBar({ value }: { value: number }) {
  const pct = Math.round(value * 100)
  const color = value >= 0.7 ? '#00C853' : value >= 0.5 ? '#F7931E' : '#D32F2F'
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
      <div style={{ flex: 1, height: 3, background: '#1A1A1A', borderRadius: 2 }}>
        <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 2 }} />
      </div>
      <span style={{ fontSize: 9, color, minWidth: 28, textAlign: 'right' }}>{pct}%</span>
    </div>
  )
}

export default function StrategyBookPanel() {
  const signals = useSocketList<SignalEntry>('strategy_signal', 30)
  const ticks   = useTickMap()
  // Re-render on new signals
  useSocketEvent<SignalEntry | null>('strategy_signal', null)

  // Deduplicate: keep most recent signal per (strategy_id, instrument_id)
  const dedupMap = new Map<string, SignalEntry>()
  for (const s of signals) {
    const key = `${s.strategy_id}:${s.instrument_id}`
    const existing = dedupMap.get(key)
    if (!existing || (s.ts ?? 0) > (existing.ts ?? 0)) dedupMap.set(key, s)
  }
  const top = [...dedupMap.values()]
    .sort((a, b) => b.confidence - a.confidence)
    .slice(0, 5)

  return (
    <div className="panel h-full">
      <div className="panel-header justify-between">
        <span><span className="accent">▸</span> BEST SIGNALS</span>
        <span style={{ fontSize: 9, color: '#444' }}>{signals.length} total · top 5 shown</span>
      </div>
      <div className="panel-body">
        {top.length === 0 ? (
          <div style={{ padding: '16px 12px' }}>
            <p style={{ color: '#555', fontSize: 11, textAlign: 'center', marginBottom: 8 }}>
              Waiting for strategy signals…
            </p>
            <p style={{ color: '#333', fontSize: 10, textAlign: 'center' }}>
              Strategies evaluate every 60s after market open
            </p>
          </div>
        ) : (
          <div>
            {top.map((s, i) => {
              const sym    = TOKEN_NAME[s.instrument_id] ?? `#${s.instrument_id}`
              const desc   = STRAT_DESC[s.strategy_id]  ?? s.strategy_id
              const liveP  = ticks[s.instrument_id]?.last_price
              const rr     = (s.target && s.stop_loss && liveP)
                ? ((s.target - liveP) / (liveP - s.stop_loss)).toFixed(1)
                : null
              return (
                <div
                  key={i}
                  style={{
                    padding: '10px 12px',
                    borderBottom: '1px solid #161616',
                    borderLeft: `3px solid ${s.side === 'BUY' ? '#00C853' : '#D32F2F'}`,
                  }}
                >
                  {/* Row 1: symbol + side + strategy */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 5 }}>
                    <span style={{ fontSize: 12, fontWeight: 700, color: '#E0E0E0' }}>{sym}</span>
                    <Badge variant="side" value={s.side} />
                    <span style={{ fontSize: 9, color: '#555', marginLeft: 'auto' }}>
                      {s.strategy_id} · {desc}
                    </span>
                  </div>
                  {/* Row 2: confidence bar */}
                  <ConfBar value={s.confidence} />
                  {/* Row 3: price levels */}
                  <div style={{ display: 'flex', gap: 12, marginTop: 5, fontSize: 9 }}>
                    {liveP && (
                      <span style={{ color: '#888' }}>@ {liveP.toFixed(2)}</span>
                    )}
                    {s.target && (
                      <span style={{ color: '#00C853' }}>T {s.target.toFixed(0)}</span>
                    )}
                    {s.stop_loss && (
                      <span style={{ color: '#D32F2F' }}>SL {s.stop_loss.toFixed(0)}</span>
                    )}
                    {rr && (
                      <span style={{ color: '#888', marginLeft: 'auto' }}>R:R {rr}</span>
                    )}
                  </div>
                  {/* Row 4: regime badge */}
                  {s.regime && (
                    <div style={{ marginTop: 4 }}>
                      <Badge variant="regime" value={s.regime} />
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
