'use client'
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  api,
  type Instrument, type LearnerParams, type PortfolioSummary, type Position,
  type SignalRec, type Trade, type TradeStats,
} from '@/lib/api'
import { useSocketEvent, useTickMap } from '@/hooks/useSocket'
import Badge from '@/components/primitives/Badge'
import clsx from 'clsx'

// ── tiny helpers ──────────────────────────────────────────────────────────────

type TokenMap = Record<number, string>

function useInstrumentMap(): { instruments: Instrument[]; tokenMap: TokenMap } {
  const [instruments, setInstruments] = useState<Instrument[]>([])
  useEffect(() => { api.instruments().then(setInstruments).catch(() => {}) }, [])
  const tokenMap: TokenMap = {}
  for (const i of instruments) tokenMap[i.token] = i.symbol
  return { instruments, tokenMap }
}

function sym(token: number, map: TokenMap) { return map[token] ?? `#${token}` }

function age(openedMs: number): string {
  const s = Math.floor((Date.now() - openedMs) / 1000)
  if (s < 60)  return `${s}s`
  if (s < 3600) return `${Math.floor(s/60)}m`
  if (s < 86400) return `${Math.floor(s/3600)}h ${Math.floor((s%3600)/60)}m`
  return `${Math.floor(s/86400)}d`
}

function fmtINR(n: number, dec = 0) {
  return '₹' + Math.abs(n).toLocaleString('en-IN', { maximumFractionDigits: dec, minimumFractionDigits: dec })
}

function PnlSpan({ v, prefix = '' }: { v: number | null | undefined; prefix?: string }) {
  if (v == null) return <span className="text-muted">—</span>
  const cls = v > 0 ? 'text-pos' : v < 0 ? 'text-neg' : 'text-muted'
  return <span className={cls}>{prefix}{v >= 0 ? '+' : '-'}{fmtINR(v)}</span>
}

function ReasonBadge({ reason }: { reason: string | null | undefined }) {
  if (!reason) return <span className="text-muted text-[10px]">—</span>
  const cfg: Record<string, { bg: string; fg: string }> = {
    stop_loss:      { bg: '#3b0000', fg: '#f87171' },
    target:         { bg: '#002b00', fg: '#4ade80' },
    time_exit:      { bg: '#001f3b', fg: '#60a5fa' },
    manual:         { bg: '#1f1000', fg: '#fb923c' },
    eod_settlement: { bg: '#1a0a2e', fg: '#a78bfa' },
  }
  const c = cfg[reason] ?? { bg: '#1a1a1a', fg: '#888' }
  return (
    <span style={{ background: c.bg, color: c.fg, padding: '1px 5px', borderRadius: 3, fontSize: 10, whiteSpace: 'nowrap' }}>
      {reason.replace(/_/g, ' ')}
    </span>
  )
}

// ── Stats Strip ───────────────────────────────────────────────────────────────

function StatsStrip({ summary, stats }: { summary: PortfolioSummary | null; stats: TradeStats | null }) {
  const eq       = summary?.equity ?? 0
  const peak     = summary?.peak_equity ?? eq
  const dayPnl   = summary?.daily_pnl ?? 0
  const dd       = summary?.drawdown ?? 0
  const wr       = stats?.win_rate ?? 0
  const todayT   = stats?.today_trades ?? 0
  const openPos  = summary?.open_positions ?? 0
  const vix      = summary?.india_vix ?? 0

  const cards = [
    {
      label: 'EQUITY',
      val: <span style={{ color: '#e5e5e5', fontWeight: 700 }}>{fmtINR(eq)}</span>,
      sub: `Peak ${fmtINR(peak)}`,
    },
    {
      label: 'DAY P&L',
      val: <PnlSpan v={dayPnl} />,
      sub: `${todayT} trades today`,
    },
    {
      label: 'DRAWDOWN',
      val: <span className={dd > 0.1 ? 'text-neg' : dd > 0.05 ? 'text-yellow-500' : 'text-muted'}>
        -{(dd * 100).toFixed(2)}%
      </span>,
      sub: 'max 20%',
    },
    {
      label: 'WIN RATE',
      val: <span style={{ color: wr >= 0.5 ? '#4ade80' : '#f87171', fontWeight: 700 }}>
        {(wr * 100).toFixed(0)}%
      </span>,
      sub: `${stats?.wins ?? 0}W / ${stats?.losses ?? 0}L`,
    },
    {
      label: 'TOTAL P&L',
      val: <PnlSpan v={stats?.total_pnl ?? null} />,
      sub: `${stats?.total_trades ?? 0} closed`,
    },
    {
      label: 'POSITIONS',
      val: <span style={{ color: openPos >= 8 ? '#f87171' : '#e5e5e5', fontWeight: 700 }}>{openPos}/10</span>,
      sub: `VIX ${vix.toFixed(1)}`,
    },
  ]

  return (
    <div style={{ display: 'flex', gap: 6, flexShrink: 0, padding: '6px 0' }}>
      {cards.map(c => (
        <div key={c.label} style={{
          flex: 1, background: '#111', border: '1px solid #1e1e1e',
          borderRadius: 4, padding: '6px 10px',
        }}>
          <div style={{ fontSize: 9, color: '#444', letterSpacing: '0.1em', marginBottom: 3 }}>{c.label}</div>
          <div style={{ fontSize: 16, lineHeight: 1 }}>{c.val}</div>
          <div style={{ fontSize: 9, color: '#333', marginTop: 3 }}>{c.sub}</div>
        </div>
      ))}
    </div>
  )
}

// ── Signal / Recommendation Feed ─────────────────────────────────────────────

function SignalFeed({
  tokenMap,
  onSelect,
}: {
  tokenMap: TokenMap
  onSelect: (symbol: string, side: 'BUY' | 'SELL', confidence: number) => void
}) {
  const [recs, setRecs]   = useState<SignalRec[]>([])
  const liveApproved      = useSocketEvent<Record<string, unknown> | null>('order_approved', null)
  const liveRejected      = useSocketEvent<Record<string, unknown> | null>('order_rejected', null)

  useEffect(() => {
    api.signals(40).then(setRecs).catch(() => {})
  }, [])

  // Prepend live events so the feed updates without polling
  useEffect(() => {
    if (!liveApproved) return
    const token = Number(liveApproved.instrument_id ?? liveApproved.instrument_token ?? 0)
    const rec: SignalRec = {
      decision_id: String(Date.now()),
      signal_id:   String(liveApproved.signal_id ?? ''),
      strategy_id: String(liveApproved.strategy_id ?? ''),
      instrument_token: token,
      symbol: tokenMap[token] ?? null,
      approved: 1,
      reason: null,
      decided_at: Date.now(),
      side: (liveApproved.side as 'BUY' | 'SELL') ?? null,
      confidence: Number(liveApproved.confidence ?? 0),
      regime: String(liveApproved.regime ?? ''),
      regime_confidence: null,
      trigger_rule: null,
      trade_id: null,
      trade_pnl: null,
      fill_price: null,
    }
    setRecs(prev => [rec, ...prev].slice(0, 60))
  }, [liveApproved, tokenMap])

  useEffect(() => {
    if (!liveRejected) return
    const token = Number(liveRejected.instrument_id ?? liveRejected.instrument_token ?? 0)
    const rec: SignalRec = {
      decision_id: String(Date.now()),
      signal_id:   String(liveRejected.signal_id ?? ''),
      strategy_id: String(liveRejected.strategy_id ?? ''),
      instrument_token: token,
      symbol: tokenMap[token] ?? null,
      approved: 0,
      reason: String(liveRejected.reason ?? ''),
      decided_at: Date.now(),
      side: (liveRejected.side as 'BUY' | 'SELL') ?? null,
      confidence: Number(liveRejected.confidence ?? 0),
      regime: String(liveRejected.regime ?? ''),
      regime_confidence: null,
      trigger_rule: null,
      trade_id: null,
      trade_pnl: null,
      fill_price: null,
    }
    setRecs(prev => [rec, ...prev].slice(0, 60))
  }, [liveRejected, tokenMap])

  function handleClick(r: SignalRec) {
    const s = r.symbol ?? tokenMap[r.instrument_token]
    if (!s || !r.side) return
    onSelect(s, r.side, r.confidence ?? 0.5)
  }

  return (
    <div className="panel h-full" style={{ display: 'flex', flexDirection: 'column', minHeight: 0 }}>
      <div className="panel-header">
        <span><span className="accent">▸</span> SIGNALS</span>
        <span style={{ fontSize: 9, color: '#444' }}>{recs.length} recent</span>
      </div>
      <div className="panel-body" style={{ flex: 1, minHeight: 0, overflow: 'auto', padding: '4px 0' }}>
        {recs.length === 0
          ? <p className="text-muted text-center mt-3" style={{ fontSize: 11 }}>No signals yet</p>
          : recs.map(r => {
            const isApproved = r.approved === 1
            const label = r.symbol ?? tokenMap[r.instrument_token] ?? `#${r.instrument_token}`
            const conf  = r.confidence ? `${(r.confidence * 100).toFixed(0)}%` : ''
            const ts    = new Date(r.decided_at).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
            return (
              <div
                key={r.decision_id}
                onClick={() => handleClick(r)}
                title={isApproved ? 'Click to pre-fill order' : r.reason ?? ''}
                style={{
                  borderLeft: `2px solid ${isApproved ? '#16a34a' : '#dc2626'}`,
                  margin: '2px 8px',
                  padding: '4px 6px',
                  borderRadius: '0 3px 3px 0',
                  background: '#0d0d0d',
                  cursor: isApproved ? 'pointer' : 'default',
                  opacity: r.trade_id ? 0.55 : 1,
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: 11, fontWeight: 700, color: '#e5e5e5' }}>{label}</span>
                  <span style={{ fontSize: 9, color: '#444' }}>{ts}</span>
                </div>
                <div style={{ display: 'flex', gap: 4, marginTop: 2, flexWrap: 'wrap', alignItems: 'center' }}>
                  {r.side && <Badge variant="side" value={r.side} />}
                  <span style={{ fontSize: 10, color: '#888' }}>{r.strategy_id}</span>
                  {conf && <span style={{ fontSize: 10, color: '#666' }}>conf {conf}</span>}
                  {r.regime && <span style={{ fontSize: 9, color: '#555' }}>{r.regime}</span>}
                </div>
                {!isApproved && r.reason && (
                  <div style={{ fontSize: 9, color: '#dc2626', marginTop: 2 }}>✗ {r.reason}</div>
                )}
                {isApproved && !r.trade_id && (
                  <div style={{ fontSize: 9, color: '#16a34a', marginTop: 2 }}>⚡ auto-traded</div>
                )}
                {r.trade_pnl != null && (
                  <div style={{ fontSize: 9, marginTop: 2 }}>
                    <PnlSpan v={r.trade_pnl} />
                  </div>
                )}
              </div>
            )
          })
        }
      </div>
    </div>
  )
}

// ── Order Ticket ──────────────────────────────────────────────────────────────

function OrderTicket({
  instruments,
  tokenMap,
  prefill,
  equity,
  onFilled,
}: {
  instruments: Instrument[]
  tokenMap: TokenMap
  prefill: { symbol: string; side: 'BUY' | 'SELL'; confidence: number } | null
  equity: number
  onFilled: () => void
}) {
  const [symbol,   setSymbol]  = useState('')
  const [search,   setSearch]  = useState('')
  const [side,     setSide]    = useState<'BUY' | 'SELL'>('BUY')
  const [qty,      setQty]     = useState('')
  const [sl,       setSl]      = useState('')
  const [target,   setTarget]  = useState('')
  const [lp,       setLp]      = useState('')
  const [loading,  setLoading] = useState(false)
  const [msg,      setMsg]     = useState<{ ok: boolean; text: string } | null>(null)
  const [confirm,  setConfirm] = useState(false)
  const ticks = useTickMap()

  // Apply prefill from signal click
  useEffect(() => {
    if (!prefill) return
    setSymbol(prefill.symbol)
    setSearch(prefill.symbol)
    setSide(prefill.side)
    setMsg(null)
  }, [prefill])

  const equityInstruments = instruments.filter(i => i.type === 'EQ' || i.type === 'INDEX')
  const filtered = search
    ? equityInstruments.filter(i => i.symbol.toLowerCase().startsWith(search.toLowerCase()))
    : equityInstruments
  const showDrop = search.length > 0 && filtered.length > 0 && filtered[0].symbol !== search

  const selInst  = equityInstruments.find(i => i.symbol === symbol)
  const livePrice = selInst ? ticks[selInst.token]?.last_price : null

  function autoSL(pct: number) {
    if (!livePrice) return
    const price = lp ? parseFloat(lp) : livePrice
    const sl = side === 'BUY' ? price * (1 - pct) : price * (1 + pct)
    setSl(sl.toFixed(2))
  }

  function autoTarget(pct: number) {
    if (!livePrice) return
    const price = lp ? parseFloat(lp) : livePrice
    const tgt = side === 'BUY' ? price * (1 + pct) : price * (1 - pct)
    setTarget(tgt.toFixed(2))
  }

  function autoSize() {
    if (!livePrice) return
    const price = lp ? parseFloat(lp) : livePrice
    // Use 5% of equity per trade, capped at ₹1L
    const cap = Math.min(equity * 0.05, 100_000)
    setQty(String(Math.max(1, Math.floor(cap / price))))
  }

  const notional = livePrice && qty ? (parseFloat(qty) || 0) * livePrice : null
  const slPrice  = sl ? parseFloat(sl) : null
  const risk     = slPrice && livePrice && qty
    ? Math.abs((livePrice - slPrice) * (parseFloat(qty) || 0))
    : null
  const rrText   = slPrice && target && livePrice
    ? (() => {
      const risk2   = Math.abs(livePrice - slPrice)
      const reward  = Math.abs(parseFloat(target) - livePrice)
      return risk2 > 0 ? `R:R ${(reward / risk2).toFixed(1)}` : ''
    })()
    : ''

  async function submit() {
    if (!symbol || !qty || !confirm) { setConfirm(true); return }
    setLoading(true); setMsg(null); setConfirm(false)
    try {
      const res = await api.manualOrder({
        symbol, side,
        quantity:    parseInt(qty),
        stop_loss:   sl     ? parseFloat(sl)     : undefined,
        target:      target ? parseFloat(target) : undefined,
        limit_price: lp     ? parseFloat(lp)     : undefined,
      })
      if (res.ok) {
        setMsg({ ok: true, text: `Filled: ${side} ${qty}× ${symbol}` })
        setQty(''); setSl(''); setTarget(''); setLp(''); setSearch(''); setSymbol('')
        onFilled()
      } else {
        setMsg({ ok: false, text: res.error ?? 'Order rejected' })
      }
    } catch {
      setMsg({ ok: false, text: 'Network error' })
    } finally {
      setLoading(false)
    }
  }

  const inp = {
    width: '100%', background: '#161616', border: '1px solid #242424',
    color: '#e5e5e5', fontSize: 12, padding: '4px 7px', borderRadius: 3, boxSizing: 'border-box' as const,
  }

  return (
    <div className="panel h-full" style={{ display: 'flex', flexDirection: 'column' }}>
      <div className="panel-header justify-between">
        <span><span className="accent">▸</span> ORDER TICKET</span>
        {livePrice != null && symbol && (
          <span style={{ fontSize: 11, color: '#4ade80' }}>{symbol} ₹{livePrice.toFixed(2)}</span>
        )}
      </div>

      <div style={{ padding: '8px 10px', display: 'flex', flexDirection: 'column', gap: 7, flex: 1, overflow: 'auto' }}>
        {/* Symbol search */}
        <div style={{ position: 'relative' }}>
          <label style={{ fontSize: 9, color: '#444', display: 'block', marginBottom: 2 }}>SYMBOL</label>
          <input
            value={search}
            onChange={e => { setSearch(e.target.value); setSymbol('') }}
            onFocus={() => {}}
            placeholder="type to search..."
            style={{ ...inp, color: symbol ? '#4ade80' : '#e5e5e5' }}
          />
          {showDrop && (
            <div style={{
              position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 50,
              background: '#161616', border: '1px solid #2a2a2a', borderRadius: 3,
              maxHeight: 160, overflow: 'auto',
            }}>
              {filtered.slice(0, 12).map(i => (
                <div key={i.token}
                  onClick={() => { setSymbol(i.symbol); setSearch(i.symbol) }}
                  style={{ padding: '5px 8px', fontSize: 11, cursor: 'pointer', color: '#ccc' }}
                  onMouseEnter={e => (e.currentTarget.style.background = '#1e1e1e')}
                  onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
                >
                  {i.symbol} <span style={{ fontSize: 9, color: '#444' }}>{i.type}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Side */}
        <div style={{ display: 'flex', gap: 6 }}>
          {(['BUY', 'SELL'] as const).map(s => (
            <button key={s} onClick={() => { setSide(s); setSl(''); setTarget('') }}
              style={{
                flex: 1, padding: '5px 0', fontSize: 11, fontWeight: 700,
                borderRadius: 3, cursor: 'pointer', border: 'none', letterSpacing: '0.08em',
                background: side === s ? (s === 'BUY' ? '#14532d' : '#7f1d1d') : '#1a1a1a',
                color: side === s ? (s === 'BUY' ? '#4ade80' : '#f87171') : '#444',
              }}
            >{s}</button>
          ))}
        </div>

        {/* Qty + auto-size */}
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
            <label style={{ fontSize: 9, color: '#444' }}>QTY</label>
            <button onClick={autoSize} disabled={!livePrice}
              style={{ fontSize: 9, color: '#555', background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}>
              auto-size
            </button>
          </div>
          <input type="number" min="1" value={qty} onChange={e => setQty(e.target.value)}
            placeholder="0" style={inp} />
          {notional != null && (
            <div style={{ fontSize: 9, color: '#444', marginTop: 2 }}>
              Notional {fmtINR(notional)}
              {risk != null && ` · Risk ${fmtINR(risk)}`}
              {rrText && ` · ${rrText}`}
            </div>
          )}
        </div>

        {/* Limit price */}
        <div>
          <label style={{ fontSize: 9, color: '#444', display: 'block', marginBottom: 2 }}>
            LIMIT PRICE <span style={{ color: '#2a2a2a' }}>(blank = market)</span>
          </label>
          <input type="number" value={lp} onChange={e => setLp(e.target.value)}
            placeholder={livePrice ? livePrice.toFixed(2) : 'market'} style={inp} />
        </div>

        {/* SL row */}
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
            <label style={{ fontSize: 9, color: '#f87171' }}>STOP LOSS</label>
            <div style={{ display: 'flex', gap: 4 }}>
              {[0.5, 1, 1.5, 2].map(p => (
                <button key={p} onClick={() => autoSL(p / 100)} disabled={!livePrice}
                  style={{ fontSize: 8, color: '#555', background: 'none', border: '1px solid #1e1e1e', cursor: 'pointer', padding: '1px 4px', borderRadius: 2 }}>
                  -{p}%
                </button>
              ))}
            </div>
          </div>
          <input type="number" value={sl} onChange={e => setSl(e.target.value)} placeholder="0"
            style={{ ...inp, color: '#f87171' }} />
        </div>

        {/* Target row */}
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
            <label style={{ fontSize: 9, color: '#4ade80' }}>TARGET</label>
            <div style={{ display: 'flex', gap: 4 }}>
              {[1, 2, 3, 5].map(p => (
                <button key={p} onClick={() => autoTarget(p / 100)} disabled={!livePrice}
                  style={{ fontSize: 8, color: '#555', background: 'none', border: '1px solid #1e1e1e', cursor: 'pointer', padding: '1px 4px', borderRadius: 2 }}>
                  +{p}%
                </button>
              ))}
            </div>
          </div>
          <input type="number" value={target} onChange={e => setTarget(e.target.value)} placeholder="0"
            style={{ ...inp, color: '#4ade80' }} />
        </div>

        {/* Confirm / Submit */}
        {confirm ? (
          <div style={{ display: 'flex', gap: 6 }}>
            <button onClick={submit} style={{
              flex: 2, padding: '7px 0', fontSize: 11, fontWeight: 700, borderRadius: 3,
              cursor: 'pointer', border: 'none', letterSpacing: '0.06em',
              background: side === 'BUY' ? '#14532d' : '#7f1d1d',
              color: side === 'BUY' ? '#4ade80' : '#f87171',
            }}>CONFIRM {side}</button>
            <button onClick={() => setConfirm(false)} style={{
              flex: 1, padding: '7px 0', fontSize: 11, borderRadius: 3,
              cursor: 'pointer', border: '1px solid #2a2a2a', background: '#111', color: '#666',
            }}>CANCEL</button>
          </div>
        ) : (
          <button onClick={submit} disabled={loading || !symbol || !qty}
            style={{
              padding: '7px 0', fontSize: 11, fontWeight: 700, borderRadius: 3,
              cursor: loading || !symbol || !qty ? 'not-allowed' : 'pointer',
              border: 'none', letterSpacing: '0.08em',
              background: loading || !symbol || !qty ? '#1a1a1a'
                : side === 'BUY' ? '#14532d' : '#7f1d1d',
              color: loading || !symbol || !qty ? '#333'
                : side === 'BUY' ? '#4ade80' : '#f87171',
            }}
          >
            {loading ? 'SENDING...' : `PLACE ${side}`}
          </button>
        )}

        {msg && (
          <div style={{
            fontSize: 11, padding: '4px 7px', borderRadius: 3,
            background: msg.ok ? '#0a1f0a' : '#1f0a0a',
            color: msg.ok ? '#4ade80' : '#f87171',
            border: `1px solid ${msg.ok ? '#14532d' : '#7f1d1d'}`,
          }}>
            {msg.text}
          </div>
        )}
      </div>
    </div>
  )
}

// ── Open Positions ────────────────────────────────────────────────────────────

function OpenPositions({ tokenMap, refresh }: { tokenMap: TokenMap; refresh: number }) {
  const [positions, setPositions] = useState<Position[]>([])
  const [closing,   setClosing]   = useState<Set<string>>(new Set())
  const ticks       = useTickMap()
  const tradeOpened = useSocketEvent<Position | null>('trade_opened', null)
  const tradeClosed = useSocketEvent<{ trade_id: string } | null>('trade_closed', null)

  const load = useCallback(() => {
    api.positions().then(setPositions).catch(() => {})
  }, [])

  useEffect(() => { load() }, [refresh, load])
  useEffect(() => {
    if (tradeOpened) setPositions(prev => [tradeOpened, ...prev.filter(p => p.trade_id !== tradeOpened.trade_id)])
  }, [tradeOpened])
  useEffect(() => {
    if (tradeClosed) {
      setPositions(prev => prev.filter(p => p.trade_id !== tradeClosed.trade_id))
      setClosing(prev => { const s = new Set(prev); s.delete(tradeClosed.trade_id); return s })
    }
  }, [tradeClosed])

  async function closePos(tradeId: string) {
    setClosing(prev => new Set(prev).add(tradeId))
    try { await api.closePosition(tradeId) }
    catch { setClosing(prev => { const s = new Set(prev); s.delete(tradeId); return s }) }
  }

  return (
    <div className="panel h-full" style={{ display: 'flex', flexDirection: 'column', minHeight: 0 }}>
      <div className="panel-header justify-between">
        <span><span className="accent">▸</span> OPEN POSITIONS</span>
        <span style={{ fontSize: 10, color: '#444' }}>{positions.length}/10</span>
      </div>
      <div className="panel-body" style={{ flex: 1, minHeight: 0, overflow: 'auto' }}>
        {positions.length === 0
          ? <p className="text-muted text-center mt-4" style={{ fontSize: 11 }}>No open positions</p>
          : (
            <table>
              <thead>
                <tr>
                  <th>Symbol</th><th>Side</th><th>Qty</th>
                  <th>Entry</th><th>Live</th><th>Unreal</th><th>%</th>
                  <th>→ SL</th><th>→ Tgt</th><th>Age</th><th>Regime</th><th></th>
                </tr>
              </thead>
              <tbody>
                {positions.map(pos => {
                  const tick = ticks[pos.instrument_id]
                  const live = tick?.last_price ?? null
                  const sign = pos.side === 'BUY' ? 1 : -1
                  const unr  = live != null ? sign * (live - pos.entry_price) * pos.quantity : null
                  const unrPct = live != null ? sign * (live / pos.entry_price - 1) * 100 : null
                  const toSl  = live != null && pos.stop_loss
                    ? (pos.side === 'BUY' ? (live - pos.stop_loss) / live * 100 : (pos.stop_loss - live) / live * 100)
                    : null
                  const toTgt = live != null && pos.target
                    ? (pos.side === 'BUY' ? (pos.target - live) / live * 100 : (live - pos.target) / live * 100)
                    : null
                  const openedMs = pos.opened_at ? new Date(pos.opened_at).getTime() : Date.now()
                  const isClos = closing.has(pos.trade_id)
                  const label  = sym(pos.instrument_id, tokenMap)

                  return (
                    <tr key={pos.trade_id} style={{ opacity: isClos ? 0.4 : 1 }}>
                      <td style={{ color: '#e5e5e5', fontWeight: 600 }}>{label}</td>
                      <td><Badge variant="side" value={pos.side} /></td>
                      <td>{pos.quantity}</td>
                      <td style={{ color: '#888' }}>{pos.entry_price.toFixed(2)}</td>
                      <td style={{ color: '#ccc' }}>{live?.toFixed(2) ?? '—'}</td>
                      <td><PnlSpan v={unr} /></td>
                      <td style={{ color: (unrPct ?? 0) >= 0 ? '#4ade80' : '#f87171', fontSize: 10 }}>
                        {unrPct != null ? `${unrPct >= 0 ? '+' : ''}${unrPct.toFixed(2)}%` : '—'}
                      </td>
                      <td style={{ color: toSl != null && toSl < 0.5 ? '#f87171' : '#888', fontSize: 10 }}>
                        {toSl != null ? (toSl < 0 ? <span className="text-neg">{toSl.toFixed(2)}%</span> : `${toSl.toFixed(2)}%`) : '—'}
                      </td>
                      <td style={{ color: '#4ade80', fontSize: 10 }}>
                        {toTgt != null ? `${toTgt.toFixed(2)}%` : '—'}
                      </td>
                      <td style={{ color: '#555', fontSize: 10 }}>{age(openedMs)}</td>
                      <td style={{ color: '#555', fontSize: 10 }}>{pos.regime ?? '—'}</td>
                      <td>
                        <button
                          onClick={() => !isClos && closePos(pos.trade_id)}
                          disabled={isClos}
                          title="Close at market"
                          style={{
                            padding: '2px 6px', fontSize: 10, cursor: isClos ? 'wait' : 'pointer',
                            background: '#1a0000', border: '1px solid #7f1d1d',
                            color: '#f87171', borderRadius: 3,
                          }}
                        >{isClos ? '…' : '✕'}</button>
                      </td>
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

// ── Closed Trades ─────────────────────────────────────────────────────────────

function ClosedTrades({ tokenMap, refresh }: { tokenMap: TokenMap; refresh: number }) {
  const [trades,  setTrades]  = useState<Trade[]>([])
  const [filter,  setFilter]  = useState('')
  const tradeClosed = useSocketEvent<Trade | null>('trade_closed', null)

  useEffect(() => {
    api.tradesClosed(80).then(setTrades).catch(() => {})
  }, [refresh])

  useEffect(() => {
    if (tradeClosed) setTrades(prev => [tradeClosed, ...prev].slice(0, 80))
  }, [tradeClosed])

  const rows = filter
    ? trades.filter(t =>
        (t.strategy_id?.toLowerCase().includes(filter.toLowerCase())) ||
        (tokenMap[t.instrument_token]?.toLowerCase().includes(filter.toLowerCase()))
      )
    : trades

  function duration(t: Trade) {
    if (!t.exit_time || !t.entry_time) return '—'
    const s = Math.floor((t.exit_time - t.entry_time) / 1000)
    if (s < 60)   return `${s}s`
    if (s < 3600) return `${Math.floor(s/60)}m`
    return `${Math.floor(s/3600)}h`
  }

  return (
    <div className="panel h-full" style={{ display: 'flex', flexDirection: 'column', minHeight: 0 }}>
      <div className="panel-header justify-between">
        <span><span className="accent">▸</span> CLOSED TRADES</span>
        <input value={filter} onChange={e => setFilter(e.target.value)}
          placeholder="filter..."
          style={{ background: '#111', border: '1px solid #1e1e1e', color: '#666', fontSize: 10, padding: '2px 6px', borderRadius: 3, width: 90 }} />
      </div>
      <div className="panel-body" style={{ flex: 1, minHeight: 0, overflow: 'auto' }}>
        {rows.length === 0
          ? <p className="text-muted text-center mt-4" style={{ fontSize: 11 }}>No closed trades</p>
          : (
            <table>
              <thead>
                <tr>
                  <th>Symbol</th><th>Side</th><th>Qty</th>
                  <th>Entry</th><th>Exit</th><th>P&L</th>
                  <th>Dur</th><th>Reason</th><th>Strat</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(t => (
                  <tr key={t.trade_id}>
                    <td style={{ color: '#e5e5e5', fontWeight: 600 }}>{sym(t.instrument_token, tokenMap)}</td>
                    <td><Badge variant="side" value={t.side} /></td>
                    <td>{t.quantity}</td>
                    <td style={{ color: '#888' }}>{t.entry_price.toFixed(2)}</td>
                    <td style={{ color: '#888' }}>{t.exit_price?.toFixed(2) ?? '—'}</td>
                    <td><PnlSpan v={t.net_pnl} /></td>
                    <td style={{ color: '#555', fontSize: 10 }}>{duration(t)}</td>
                    <td><ReasonBadge reason={t.exit_reason} /></td>
                    <td style={{ color: '#555', fontSize: 10 }}>{t.strategy_id}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )
        }
      </div>
    </div>
  )
}

// ── Attribution ───────────────────────────────────────────────────────────────

function Attribution({ stats }: { stats: TradeStats | null }) {
  const rows = stats
    ? Object.entries(stats.by_strategy).sort((a, b) => b[1].pnl - a[1].pnl)
    : []

  // Best and worst trade pnl for context
  return (
    <div className="panel h-full" style={{ display: 'flex', flexDirection: 'column', minHeight: 0 }}>
      <div className="panel-header justify-between">
        <span><span className="accent">▸</span> ATTRIBUTION</span>
      </div>
      <div className="panel-body" style={{ flex: 1, minHeight: 0, overflow: 'auto' }}>
        {/* Summary row */}
        {stats && (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 4, marginBottom: 8 }}>
            {[
              { l: 'Best trade', v: stats.best_trade_pnl },
              { l: 'Worst trade', v: stats.worst_trade_pnl },
              { l: 'Avg win', v: stats.avg_win },
              { l: 'Avg loss', v: stats.avg_loss },
            ].map(item => (
              <div key={item.l} style={{ background: '#0d0d0d', padding: '4px 6px', borderRadius: 3 }}>
                <div style={{ fontSize: 9, color: '#444' }}>{item.l}</div>
                <PnlSpan v={item.v} />
              </div>
            ))}
          </div>
        )}

        {rows.length === 0
          ? <p className="text-muted text-center mt-2" style={{ fontSize: 11 }}>No data</p>
          : (
            <table>
              <thead><tr><th>Strategy</th><th>T</th><th>WR</th><th>P&L</th></tr></thead>
              <tbody>
                {rows.map(([sid, rec]) => {
                  const pct = rec.trades > 0 ? rec.pnl / Math.max(1, Math.abs(rec.pnl)) * 100 : 0
                  return (
                    <tr key={sid}>
                      <td>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                          <div style={{
                            width: Math.min(40, Math.abs(pct / 2.5)),
                            height: 3, borderRadius: 2,
                            background: rec.pnl >= 0 ? '#16a34a' : '#dc2626',
                          }} />
                          <span style={{ color: '#e5e5e5', fontSize: 11 }}>{sid}</span>
                        </div>
                      </td>
                      <td style={{ fontSize: 10, color: '#666' }}>{rec.trades}</td>
                      <td style={{ fontSize: 10, color: rec.win_rate >= 0.5 ? '#4ade80' : '#f87171' }}>
                        {(rec.win_rate * 100).toFixed(0)}%
                      </td>
                      <td><PnlSpan v={rec.pnl} /></td>
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

// ── Learner Panel ─────────────────────────────────────────────────────────────

function LearnerPanel({ refresh }: { refresh: number }) {
  const [params, setParams] = useState<LearnerParams[]>([])
  const paramsUpdate = useSocketEvent<LearnerParams | null>('learner_params_updated', null)
  const eodClose = useSocketEvent<{ date: string; positions_closed: number } | null>('settlement_eod_close', null)
  const eodReset = useSocketEvent<{ date: string; equity: number; daily_pnl: number } | null>('settlement_eod_reset', null)

  useEffect(() => {
    api.learnerParams().then(setParams).catch(() => {})
  }, [refresh])

  useEffect(() => {
    if (!paramsUpdate) return
    setParams(prev => {
      const exists = prev.findIndex(p => p.strategy_id === paramsUpdate.strategy_id)
      if (exists >= 0) { const n = [...prev]; n[exists] = paramsUpdate; return n }
      return [...prev, paramsUpdate]
    })
  }, [paramsUpdate])

  const [lastSettlement, setLastSettlement] = useState<string | null>(null)
  useEffect(() => {
    if (eodReset) setLastSettlement(`EOD reset ${eodReset.date} — equity ₹${Math.round(eodReset.equity).toLocaleString('en-IN')}`)
  }, [eodReset])
  useEffect(() => {
    if (eodClose) setLastSettlement(`Closed ${eodClose.positions_closed} positions on ${eodClose.date}`)
  }, [eodClose])

  // Next 15:30 IST
  const now = new Date()
  const istOffset = 5.5 * 60 * 60 * 1000
  const istNow = new Date(now.getTime() + istOffset - now.getTimezoneOffset() * 60000)
  const settlementToday = new Date(istNow)
  settlementToday.setHours(15, 30, 0, 0)
  const msToSettlement = settlementToday.getTime() - istNow.getTime()
  const settlementLabel = msToSettlement > 0
    ? `EOD in ${Math.floor(msToSettlement / 3600000)}h ${Math.floor((msToSettlement % 3600000) / 60000)}m`
    : 'post-market'

  return (
    <div className="panel h-full" style={{ display: 'flex', flexDirection: 'column' }}>
      <div className="panel-header justify-between">
        <span><span className="accent">▸</span> LEARNING ENGINE</span>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <span style={{
            fontSize: 8, padding: '2px 6px', borderRadius: 3, letterSpacing: '0.1em',
            background: '#001a00', color: '#4ade80', border: '1px solid #14532d',
          }}>⚡ AUTO</span>
          <span style={{ fontSize: 9, color: '#444' }}>{settlementLabel}</span>
        </div>
      </div>
      <div className="panel-body" style={{ flex: 1, overflow: 'auto' }}>
        {lastSettlement && (
          <div style={{ fontSize: 9, color: '#a78bfa', background: '#1a0a2e', padding: '3px 8px', marginBottom: 6, borderRadius: 3 }}>
            {lastSettlement}
          </div>
        )}
        {params.length === 0
          ? <p className="text-muted text-center mt-3" style={{ fontSize: 11 }}>Accumulating trades…</p>
          : (
            <table style={{ fontSize: 10 }}>
              <thead>
                <tr>
                  <th>Strat</th>
                  <th title="Min confidence required">Conf↑</th>
                  <th title="SL ATR multiplier">SL×</th>
                  <th title="Target ATR multiplier">Tgt×</th>
                  <th title="Half-Kelly fraction">Kelly</th>
                  <th title="Bayesian win rate">BWR</th>
                  <th title="Trades analyzed">N</th>
                </tr>
              </thead>
              <tbody>
                {params.sort((a, b) => a.strategy_id.localeCompare(b.strategy_id)).map(p => (
                  <tr key={p.strategy_id}>
                    <td style={{ color: '#e5e5e5', fontWeight: 600 }}>{p.strategy_id}</td>
                    <td style={{ color: p.min_confidence > 0.55 ? '#f87171' : p.min_confidence < 0.40 ? '#4ade80' : '#888' }}>
                      {(p.min_confidence * 100).toFixed(0)}%
                    </td>
                    <td style={{ color: p.sl_multiplier > 2 ? '#fb923c' : '#888' }}>{p.sl_multiplier.toFixed(2)}</td>
                    <td style={{ color: '#888' }}>{p.target_multiplier.toFixed(2)}</td>
                    <td style={{ color: p.kelly_fraction > 0.10 ? '#4ade80' : '#888' }}>
                      {(p.kelly_fraction * 100).toFixed(1)}%
                    </td>
                    <td style={{ color: p.bayes_wr >= 0.55 ? '#4ade80' : p.bayes_wr < 0.40 ? '#f87171' : '#888' }}>
                      {(p.bayes_wr * 100).toFixed(0)}%
                    </td>
                    <td style={{ color: '#555' }}>{p.n_trades}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )
        }
      </div>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function TradePage() {
  const [summary,  setSummary]  = useState<PortfolioSummary | null>(null)
  const [stats,    setStats]    = useState<TradeStats | null>(null)
  const [refresh,  setRefresh]  = useState(0)
  const [prefill,  setPrefill]  = useState<{ symbol: string; side: 'BUY' | 'SELL'; confidence: number } | null>(null)

  const { instruments, tokenMap } = useInstrumentMap()

  const pnlUpdate = useSocketEvent<{ equity: number; daily_pnl: number } | null>('pnl_update', null)

  function loadMeta() {
    api.portfolio().then(setSummary).catch(() => {})
    api.tradeStats().then(setStats).catch(() => {})
  }

  useEffect(() => { loadMeta() }, [refresh])

  useEffect(() => {
    if (!pnlUpdate) return
    setSummary(prev => prev
      ? { ...prev, equity: pnlUpdate.equity, daily_pnl: pnlUpdate.daily_pnl }
      : prev
    )
  }, [pnlUpdate])

  function handleFilled() { setTimeout(() => setRefresh(r => r + 1), 600) }

  return (
    <div style={{
      flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column',
      overflow: 'hidden', padding: '6px 10px', gap: 6,
    }}>

      {/* Stats strip */}
      <StatsStrip summary={summary} stats={stats} />

      {/* Main 3-column grid */}
      <div style={{
        flex: 1, minHeight: 0, display: 'grid',
        gridTemplateColumns: '260px 1fr 280px',
        gridTemplateRows: '1fr 1fr',
        gap: 6,
      }}>

        {/* Left-top: Signal feed */}
        <div style={{ gridRow: '1 / 2', gridColumn: '1 / 2', minHeight: 0, overflow: 'hidden' }}>
          <SignalFeed tokenMap={tokenMap} onSelect={(sym, side, conf) => setPrefill({ symbol: sym, side, confidence: conf })} />
        </div>

        {/* Left-bottom: Order ticket */}
        <div style={{ gridRow: '2 / 3', gridColumn: '1 / 2', minHeight: 0, overflow: 'hidden' }}>
          <OrderTicket
            instruments={instruments}
            tokenMap={tokenMap}
            prefill={prefill}
            equity={summary?.equity ?? 1_000_000}
            onFilled={handleFilled}
          />
        </div>

        {/* Center-top: Open positions */}
        <div style={{ gridRow: '1 / 2', gridColumn: '2 / 3', minHeight: 0, overflow: 'hidden' }}>
          <OpenPositions tokenMap={tokenMap} refresh={refresh} />
        </div>

        {/* Center-bottom: Closed trades */}
        <div style={{ gridRow: '2 / 3', gridColumn: '2 / 3', minHeight: 0, overflow: 'hidden' }}>
          <ClosedTrades tokenMap={tokenMap} refresh={refresh} />
        </div>

        {/* Right-top: Attribution */}
        <div style={{ gridRow: '1 / 2', gridColumn: '3 / 4', minHeight: 0, overflow: 'hidden' }}>
          <Attribution stats={stats} />
        </div>

        {/* Right-bottom: Learning engine */}
        <div style={{ gridRow: '2 / 3', gridColumn: '3 / 4', minHeight: 0, overflow: 'hidden' }}>
          <LearnerPanel refresh={refresh} />
        </div>
      </div>
    </div>
  )
}
