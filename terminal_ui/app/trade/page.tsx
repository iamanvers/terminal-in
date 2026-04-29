'use client'
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  api,
  type Instrument, type JournalEntry, type LearnerParams, type OrchestratorResult, type OrchestratorState,
  type PortfolioSummary, type Position, type SignalRec, type Trade, type TradeStats,
} from '@/lib/api'
import { useSocketEvent, useTickMap } from '@/hooks/useSocket'
import Badge from '@/components/primitives/Badge'

// ── Helpers ───────────────────────────────────────────────────────────────────

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
  if (s < 60)    return `${s}s`
  if (s < 3600)  return `${Math.floor(s/60)}m`
  if (s < 86400) return `${Math.floor(s/3600)}h ${Math.floor((s%3600)/60)}m`
  return `${Math.floor(s/86400)}d`
}

function fmtINR(n: number, dec = 0) {
  return '₹' + Math.abs(n).toLocaleString('en-IN', { maximumFractionDigits: dec, minimumFractionDigits: dec })
}

function PnlSpan({ v, prefix = '' }: { v: number | null | undefined; prefix?: string }) {
  if (v == null) return <span style={{ color: '#444' }}>—</span>
  const color = v > 0 ? '#4ade80' : v < 0 ? '#f87171' : '#555'
  return <span style={{ color }}>{prefix}{v >= 0 ? '+' : '-'}{fmtINR(v)}</span>
}

function ReasonBadge({ reason }: { reason: string | null | undefined }) {
  if (!reason) return <span style={{ color: '#444', fontSize: 10 }}>—</span>
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

// EV color: 0-1 = grey, 1-2 = yellow, 2+ = green
function evColor(ev: number) {
  if (ev >= 2.0) return '#4ade80'
  if (ev >= 1.2) return '#fbbf24'
  return '#555'
}

function SidePill({ side }: { side: string }) {
  const isBuy = side === 'BUY'
  const isSell = side === 'SELL'
  if (!isBuy && !isSell) return <span style={{ color: '#444', fontSize: 10 }}>{side}</span>
  return (
    <span style={{
      fontSize: 10, fontWeight: 700, padding: '1px 6px', borderRadius: 3,
      background: isBuy ? '#052e16' : '#3b0000',
      color: isBuy ? '#4ade80' : '#f87171',
      border: `1px solid ${isBuy ? '#14532d' : '#7f1d1d'}`,
    }}>{side}</span>
  )
}

// ── Stats Strip ───────────────────────────────────────────────────────────────

function StatsStrip({ summary, stats }: { summary: PortfolioSummary | null; stats: TradeStats | null }) {
  const eq      = summary?.equity ?? 0
  const peak    = summary?.peak_equity ?? eq
  const dayPnl  = summary?.daily_pnl ?? 0
  const dd      = summary?.drawdown ?? 0
  const wr      = stats?.win_rate ?? 0
  const openPos = summary?.open_positions ?? 0
  const vix     = summary?.india_vix ?? 0

  const cards = [
    { label: 'EQUITY',    val: <span style={{ color: '#e5e5e5', fontWeight: 700 }}>{fmtINR(eq)}</span>,             sub: `Peak ${fmtINR(peak)}` },
    { label: 'DAY P&L',   val: <PnlSpan v={dayPnl} />,                                                              sub: `${stats?.today_trades ?? 0} trades` },
    { label: 'DRAWDOWN',  val: <span style={{ color: dd > 0.10 ? '#f87171' : dd > 0.05 ? '#fbbf24' : '#555' }}>-{(dd*100).toFixed(2)}%</span>, sub: 'max 20%' },
    { label: 'WIN RATE',  val: <span style={{ color: wr >= 0.5 ? '#4ade80' : '#f87171', fontWeight: 700 }}>{(wr*100).toFixed(0)}%</span>,        sub: `${stats?.wins ?? 0}W / ${stats?.losses ?? 0}L` },
    { label: 'TOTAL P&L', val: <PnlSpan v={stats?.total_pnl ?? null} />,                                            sub: `${stats?.total_trades ?? 0} closed` },
    { label: 'POSITIONS', val: <span style={{ color: openPos >= 8 ? '#f87171' : '#e5e5e5', fontWeight: 700 }}>{openPos}/10</span>,               sub: `VIX ${vix.toFixed(1)}` },
  ]

  return (
    <div style={{ display: 'flex', gap: 6, flexShrink: 0, padding: '6px 0' }}>
      {cards.map(c => (
        <div key={c.label} style={{ flex: 1, background: '#111', border: '1px solid #1e1e1e', borderRadius: 4, padding: '6px 10px' }}>
          <div style={{ fontSize: 9, color: '#444', letterSpacing: '0.1em', marginBottom: 3 }}>{c.label}</div>
          <div style={{ fontSize: 16, lineHeight: 1 }}>{c.val}</div>
          <div style={{ fontSize: 9, color: '#333', marginTop: 3 }}>{c.sub}</div>
        </div>
      ))}
    </div>
  )
}

// ── Agent Cockpit ─────────────────────────────────────────────────────────────

function AgentCockpit({
  tokenMap,
  onFire,
}: {
  tokenMap: TokenMap
  onFire: (r: OrchestratorResult) => void
}) {
  const [state,    setState]   = useState<OrchestratorState | null>(null)
  const [signals,  setSignals] = useState<SignalRec[]>([])
  const [journal,  setJournal] = useState<JournalEntry[]>([])
  const [scanning, setScanning] = useState(false)
  const [tab,      setTab]     = useState<'opps' | 'signals' | 'journal'>('opps')

  const scanDone = useSocketEvent<OrchestratorState & { fired: number; top_results: OrchestratorResult[] } | null>('orchestrator_scan_done', null)
  const liveApproved = useSocketEvent<Record<string, unknown> | null>('order_approved', null)
  const liveRejected = useSocketEvent<Record<string, unknown> | null>('order_rejected', null)

  useEffect(() => {
    api.orchestratorState().then(setState).catch(() => {})
    api.signals(30).then(setSignals).catch(() => {})
    api.journal(40).then(setJournal).catch(() => {})
  }, [])

  // Live scan results — replace state instantly
  useEffect(() => {
    if (!scanDone) return
    setScanning(false)
    setState({ scan_count: scanDone.scan_count, last_scan_ts: scanDone.last_scan_ts, results: scanDone.top_results ?? [] })
  }, [scanDone])

  // Refresh journal when a trade closes (new journal entry created by broker)
  const tradeClosed = useSocketEvent<{ trade_id: string } | null>('trade_closed', null)
  useEffect(() => {
    if (!tradeClosed) return
    api.journal(40).then(setJournal).catch(() => {})
  }, [tradeClosed])

  // Signal feed: deduplicate by instrument_token (keep latest per symbol)
  function addSignal(rec: SignalRec) {
    setSignals(prev => {
      const filtered = prev.filter(r => r.instrument_token !== rec.instrument_token)
      return [rec, ...filtered].slice(0, 40)
    })
  }

  useEffect(() => {
    if (!liveApproved) return
    const token = Number(liveApproved.instrument_id ?? liveApproved.instrument_token ?? 0)
    addSignal({
      decision_id: String(Date.now()), signal_id: String(liveApproved.signal_id ?? ''),
      strategy_id: String(liveApproved.strategy_id ?? ''), instrument_token: token,
      symbol: tokenMap[token] ?? null, approved: 1, reason: null, decided_at: Date.now(),
      side: (liveApproved.side as 'BUY' | 'SELL') ?? null,
      confidence: Number(liveApproved.confidence ?? 0), regime: String(liveApproved.regime ?? ''),
      regime_confidence: null, trigger_rule: null, trade_id: null, trade_pnl: null, fill_price: null,
    })
  }, [liveApproved, tokenMap])

  useEffect(() => {
    if (!liveRejected) return
    const token = Number(liveRejected.instrument_id ?? liveRejected.instrument_token ?? 0)
    addSignal({
      decision_id: String(Date.now()), signal_id: String(liveRejected.signal_id ?? ''),
      strategy_id: String(liveRejected.strategy_id ?? ''), instrument_token: token,
      symbol: tokenMap[token] ?? null, approved: 0, reason: String(liveRejected.reason ?? ''),
      decided_at: Date.now(), side: (liveRejected.side as 'BUY' | 'SELL') ?? null,
      confidence: Number(liveRejected.confidence ?? 0), regime: String(liveRejected.regime ?? ''),
      regime_confidence: null, trigger_rule: null, trade_id: null, trade_pnl: null, fill_price: null,
    })
  }, [liveRejected, tokenMap])

  async function triggerScan() {
    setScanning(true)
    await api.orchestratorScan().catch(() => {})
    // WS event (scanDone effect) will call setScanning(false) when results arrive.
    // Hard timeout fallback after 10s in case the WS event is lost.
    setTimeout(() => setScanning(false), 10_000)
  }

  const lastScanAge = state?.last_scan_ts
    ? (() => { const s = Math.floor((Date.now() - state.last_scan_ts) / 1000); return s < 60 ? `${s}s ago` : `${Math.floor(s/60)}m ago` })()
    : 'never'

  const results = state?.results ?? []
  const tradeable = results.filter(r => r.side !== 'NEUTRAL' && r.side !== 'SKIP' && r.ev >= 1.2)
  const watching  = results.filter(r => r.side === 'NEUTRAL' || r.ev < 1.2)

  return (
    <div className="panel h-full" style={{ display: 'flex', flexDirection: 'column', minHeight: 0 }}>
      {/* Header */}
      <div className="panel-header justify-between" style={{ flexShrink: 0 }}>
        <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span className="accent">▸</span>
          <span>AGENT COCKPIT</span>
          <span style={{ fontSize: 8, padding: '2px 5px', borderRadius: 3, background: '#001a00', color: '#4ade80', border: '1px solid #14532d', letterSpacing: '0.1em' }}>⚡ AUTO</span>
        </span>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <span style={{ fontSize: 9, color: '#444' }}>scan #{state?.scan_count ?? 0} · {lastScanAge}</span>
          <button onClick={triggerScan} disabled={scanning} style={{
            fontSize: 9, padding: '2px 8px', borderRadius: 3, cursor: scanning ? 'wait' : 'pointer',
            background: scanning ? '#111' : '#1a1f0a', border: `1px solid ${scanning ? '#2a2a2a' : '#4ade80'}`,
            color: scanning ? '#444' : '#4ade80',
          }}>
            {scanning ? '⟳ scanning…' : '⟳ SCAN NOW'}
          </button>
        </div>
      </div>

      {/* Tab bar */}
      <div style={{ display: 'flex', gap: 2, padding: '4px 8px', borderBottom: '1px solid #1a1a1a', flexShrink: 0 }}>
        {(['opps', 'signals', 'journal'] as const).map(t => (
          <button key={t} onClick={() => setTab(t)} style={{
            fontSize: 9, padding: '2px 8px', borderRadius: 3, border: 'none', cursor: 'pointer',
            background: tab === t ? '#1a1a1a' : 'transparent',
            color: tab === t ? '#e5e5e5' : '#444',
            fontWeight: tab === t ? 700 : 400, letterSpacing: '0.08em',
          }}>
            {t === 'opps'
              ? `OPPORTUNITIES ${tradeable.length > 0 ? `(${tradeable.length})` : ''}`
              : t === 'signals'
                ? `SIGNAL LOG (${signals.length})`
                : `JOURNAL (${journal.length})`}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div style={{ flex: 1, minHeight: 0, overflow: 'auto' }}>
        {tab === 'opps' ? (
          <div style={{ padding: '4px 0' }}>
            {results.length === 0 ? (
              <p style={{ color: '#333', fontSize: 11, textAlign: 'center', marginTop: 16 }}>
                {scanning
                  ? '⟳ Scanning all instruments…'
                  : state?.scan_count
                    ? 'All instruments NEUTRAL — no setups above EV threshold'
                    : 'No scan yet — click SCAN NOW'}
              </p>
            ) : (
              <>
                {tradeable.length > 0 && (
                  <div style={{ padding: '4px 8px 2px', fontSize: 9, color: '#4ade80', letterSpacing: '0.08em' }}>
                    TOP SETUPS
                  </div>
                )}
                {tradeable.map(r => <OppRow key={r.symbol} r={r} onFire={onFire} />)}
                {watching.length > 0 && (
                  <div style={{ padding: '8px 8px 2px', fontSize: 9, color: '#444', letterSpacing: '0.08em', borderTop: tradeable.length ? '1px solid #161616' : 'none', marginTop: tradeable.length ? 4 : 0 }}>
                    WATCHING
                  </div>
                )}
                {watching.map(r => <OppRow key={r.symbol} r={r} onFire={onFire} dim />)}
              </>
            )}
          </div>
        ) : tab === 'signals' ? (
          <div style={{ padding: '4px 0' }}>
            {signals.length === 0
              ? <p style={{ color: '#333', fontSize: 11, textAlign: 'center', marginTop: 16 }}>No signals yet</p>
              : signals.map(s => <SignalRow key={s.decision_id} s={s} tokenMap={tokenMap} />)
            }
          </div>
        ) : (
          <div style={{ padding: '4px 0' }}>
            {journal.length === 0
              ? <p style={{ color: '#333', fontSize: 11, textAlign: 'center', marginTop: 16 }}>No journal entries yet</p>
              : journal.map(j => <JournalRow key={j.journal_id} j={j} tokenMap={tokenMap} />)
            }
          </div>
        )}
      </div>
    </div>
  )
}

function OppRow({ r, onFire, dim = false }: { r: OrchestratorResult; onFire: (r: OrchestratorResult) => void; dim?: boolean }) {
  const isActive = r.side !== 'NEUTRAL' && r.side !== 'SKIP' && r.ev >= 1.2
  const isBuy  = r.side === 'BUY'
  const isSell = r.side === 'SELL'
  const accent = isBuy ? '#4ade80' : isSell ? '#f87171' : '#444'

  return (
    <div style={{
      borderLeft: `2px solid ${isActive ? accent : '#1e1e1e'}`,
      margin: '2px 8px',
      padding: '5px 7px',
      borderRadius: '0 3px 3px 0',
      background: '#0d0d0d',
      opacity: dim ? 0.55 : 1,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ display: 'flex', gap: 5, alignItems: 'center' }}>
          <span style={{ fontSize: 12, fontWeight: 700, color: '#e5e5e5' }}>{r.symbol}</span>
          {isActive && <SidePill side={r.side} />}
          {!isActive && <span style={{ fontSize: 10, color: '#444' }}>{r.verdict}</span>}
        </div>
        <div style={{ display: 'flex', gap: 5, alignItems: 'center' }}>
          {isActive && (
            <span style={{ fontSize: 10, fontWeight: 700, color: evColor(r.ev) }}>
              EV {r.ev.toFixed(2)}
            </span>
          )}
          {isActive && (
            <button
              onClick={() => onFire(r)}
              style={{
                fontSize: 9, padding: '2px 7px', borderRadius: 3, cursor: 'pointer',
                background: isBuy ? '#052e16' : '#3b0000',
                border: `1px solid ${isBuy ? '#14532d' : '#7f1d1d'}`,
                color: isBuy ? '#4ade80' : '#f87171',
                fontWeight: 700, letterSpacing: '0.06em',
              }}
            >FIRE</button>
          )}
        </div>
      </div>
      {isActive && (
        <div style={{ marginTop: 3, display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
          <span style={{ fontSize: 9, color: '#888' }}>₹{r.price.toFixed(0)}</span>
          <span style={{ fontSize: 9, color: '#555' }}>conf {(r.confidence * 100).toFixed(0)}%</span>
          <span style={{ fontSize: 9, color: '#555' }}>R:R {r.rr?.toFixed(1) ?? '—'}</span>
          <span style={{ fontSize: 9, color: '#555' }}>RSI {r.rsi}</span>
          {r.lenses?.length > 0 && (
            <span style={{ fontSize: 9, color: '#666' }}>
              {r.lenses.map(l => l.strategy).join('+')}
            </span>
          )}
        </div>
      )}
      {!isActive && r.side === 'NEUTRAL' && (
        <div style={{ fontSize: 9, color: '#333', marginTop: 2 }}>
          RSI {r.rsi} · {r.ret_20d > 0 ? '+' : ''}{r.ret_20d?.toFixed(1)}% 20d
        </div>
      )}
    </div>
  )
}

function SignalRow({ s, tokenMap }: { s: SignalRec; tokenMap: TokenMap }) {
  const label   = s.symbol ?? tokenMap[s.instrument_token] ?? `#${s.instrument_token}`
  const conf    = s.confidence ? `${(s.confidence * 100).toFixed(0)}%` : ''
  const ts      = new Date(s.decided_at).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  const approved = s.approved === 1

  return (
    <div style={{
      borderLeft: `2px solid ${approved ? '#16a34a' : '#444'}`,
      margin: '2px 8px', padding: '4px 6px',
      borderRadius: '0 3px 3px 0', background: '#0d0d0d',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between' }}>
        <span style={{ fontSize: 11, fontWeight: 700, color: '#e5e5e5' }}>{label}</span>
        <span style={{ fontSize: 9, color: '#333' }}>{ts}</span>
      </div>
      <div style={{ display: 'flex', gap: 4, marginTop: 2, alignItems: 'center', flexWrap: 'wrap' }}>
        {s.side && <SidePill side={s.side} />}
        <span style={{ fontSize: 10, color: '#666' }}>{s.strategy_id}</span>
        {conf && <span style={{ fontSize: 9, color: '#555' }}>conf {conf}</span>}
        {approved
          ? <span style={{ fontSize: 9, color: '#4ade80' }}>⚡ fired</span>
          : <span style={{ fontSize: 9, color: '#555' }}>✗ {s.reason?.replace(/_/g, ' ')}</span>}
      </div>
    </div>
  )
}

function JournalRow({ j, tokenMap }: { j: JournalEntry; tokenMap: TokenMap }) {
  const label   = j.instrument_token ? (tokenMap[j.instrument_token] ?? `#${j.instrument_token}`) : '—'
  const pnl     = j.net_pnl ?? null
  const pnlPos  = pnl != null && pnl > 0
  const status  = j.review_status ?? 'pending'
  const statusColor = status === 'reviewed' ? '#4ade80' : status === 'pending' ? '#fbbf24' : '#555'
  const rating  = j.rating ? '★'.repeat(Math.min(5, j.rating)) + '☆'.repeat(Math.max(0, 5 - j.rating)) : null

  return (
    <div style={{
      borderLeft: `2px solid ${pnlPos ? '#16a34a' : pnl != null && pnl < 0 ? '#7f1d1d' : '#1e1e1e'}`,
      margin: '2px 8px', padding: '5px 7px',
      borderRadius: '0 3px 3px 0', background: '#0d0d0d',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ display: 'flex', gap: 5, alignItems: 'center' }}>
          <span style={{ fontSize: 12, fontWeight: 700, color: '#e5e5e5' }}>{label}</span>
          {j.side && <SidePill side={j.side} />}
          {j.strategy_id && <span style={{ fontSize: 9, color: '#555' }}>{j.strategy_id}</span>}
        </div>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          {pnl != null && <PnlSpan v={pnl} />}
          <span style={{ fontSize: 8, color: statusColor, letterSpacing: '0.06em' }}>{status.toUpperCase()}</span>
        </div>
      </div>
      {j.entry_reason && (
        <div style={{ fontSize: 9, color: '#666', marginTop: 3, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          ↳ {j.entry_reason}
        </div>
      )}
      {j.exit_reason && (
        <div style={{ fontSize: 9, color: '#555', marginTop: 1 }}>
          <ReasonBadge reason={j.exit_reason} />
        </div>
      )}
      {(j.lesson || j.manual_notes) && (
        <div style={{ fontSize: 9, color: '#4b5563', marginTop: 3, fontStyle: 'italic', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {j.lesson || j.manual_notes}
        </div>
      )}
      {rating && (
        <div style={{ fontSize: 9, color: '#854d0e', marginTop: 2 }}>{rating}</div>
      )}
    </div>
  )
}

// ── Open Positions ─────────────────────────────────────────────────────────────

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
          ? <p style={{ color: '#333', textAlign: 'center', marginTop: 12, fontSize: 11 }}>No open positions</p>
          : (
            <table>
              <thead>
                <tr>
                  <th>Symbol</th><th>Side</th><th>Qty</th>
                  <th>Entry</th><th>Live</th><th>Unreal</th><th>%</th>
                  <th>→SL</th><th>→Tgt</th><th>Age</th><th></th>
                </tr>
              </thead>
              <tbody>
                {positions.map(pos => {
                  const tick   = ticks[pos.instrument_id]
                  const live   = tick?.last_price ?? null
                  const sign   = pos.side === 'BUY' ? 1 : -1
                  const unr    = live != null ? sign * (live - pos.entry_price) * pos.quantity : null
                  const unrPct = live != null ? sign * (live / pos.entry_price - 1) * 100 : null
                  const toSl   = live != null && pos.stop_loss
                    ? (pos.side === 'BUY' ? (live - pos.stop_loss) / live * 100 : (pos.stop_loss - live) / live * 100) : null
                  const toTgt  = live != null && pos.target
                    ? (pos.side === 'BUY' ? (pos.target - live) / live * 100 : (live - pos.target) / live * 100) : null
                  const openedMs = pos.opened_at ? new Date(pos.opened_at).getTime() : Date.now()
                  const isClos   = closing.has(pos.trade_id)
                  const label    = sym(pos.instrument_id, tokenMap)

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
                      <td style={{ color: toSl != null && toSl < 0.5 ? '#f87171' : '#666', fontSize: 10 }}>
                        {toSl != null ? `${toSl.toFixed(2)}%` : '—'}
                      </td>
                      <td style={{ color: '#4ade80', fontSize: 10 }}>
                        {toTgt != null ? `${toTgt.toFixed(2)}%` : '—'}
                      </td>
                      <td style={{ color: '#555', fontSize: 10 }}>{age(openedMs)}</td>
                      <td>
                        <button onClick={() => !isClos && closePos(pos.trade_id)} disabled={isClos}
                          style={{ padding: '2px 6px', fontSize: 10, cursor: isClos ? 'wait' : 'pointer',
                                   background: '#1a0000', border: '1px solid #7f1d1d', color: '#f87171', borderRadius: 3 }}>
                          {isClos ? '…' : '✕'}
                        </button>
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
  const [trades, setTrades]  = useState<Trade[]>([])
  const [filter, setFilter]  = useState('')
  const tradeClosed = useSocketEvent<Trade | null>('trade_closed', null)

  useEffect(() => { api.tradesClosed(80).then(setTrades).catch(() => {}) }, [refresh])
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
          placeholder="filter…"
          style={{ background: '#111', border: '1px solid #1e1e1e', color: '#666', fontSize: 10, padding: '2px 6px', borderRadius: 3, width: 90 }} />
      </div>
      <div className="panel-body" style={{ flex: 1, minHeight: 0, overflow: 'auto' }}>
        {rows.length === 0
          ? <p style={{ color: '#333', textAlign: 'center', marginTop: 12, fontSize: 11 }}>No closed trades</p>
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

// ── Order Ticket ──────────────────────────────────────────────────────────────

function OrderTicket({
  instruments, tokenMap, prefill, equity, onFilled,
}: {
  instruments: Instrument[]
  tokenMap: TokenMap
  prefill: { symbol: string; side: 'BUY' | 'SELL'; sl?: number; target?: number } | null
  equity: number
  onFilled: () => void
}) {
  const [symbol,  setSymbol]  = useState('')
  const [search,  setSearch]  = useState('')
  const [side,    setSide]    = useState<'BUY' | 'SELL'>('BUY')
  const [qty,     setQty]     = useState('')
  const [sl,      setSl]      = useState('')
  const [target,  setTarget]  = useState('')
  const [lp,      setLp]      = useState('')
  const [loading, setLoading] = useState(false)
  const [msg,     setMsg]     = useState<{ ok: boolean; text: string } | null>(null)
  const [confirm, setConfirm] = useState(false)
  const ticks = useTickMap()

  useEffect(() => {
    if (!prefill) return
    setSymbol(prefill.symbol); setSearch(prefill.symbol); setSide(prefill.side)
    if (prefill.sl)     setSl(prefill.sl.toFixed(2))
    if (prefill.target) setTarget(prefill.target.toFixed(2))
    setMsg(null); setConfirm(false)
  }, [prefill])

  const eqInstruments = instruments.filter(i => i.type === 'EQ' || i.type === 'INDEX')
  const filtered = search ? eqInstruments.filter(i => i.symbol.toLowerCase().startsWith(search.toLowerCase())) : eqInstruments
  const showDrop = search.length > 0 && filtered.length > 0 && filtered[0].symbol !== search

  const selInst    = eqInstruments.find(i => i.symbol === symbol)
  const livePrice  = selInst ? ticks[selInst.token]?.last_price : null

  function autoSL(pct: number) {
    if (!livePrice) return
    const p = lp ? parseFloat(lp) : livePrice
    setSl((side === 'BUY' ? p * (1 - pct) : p * (1 + pct)).toFixed(2))
  }
  function autoTarget(pct: number) {
    if (!livePrice) return
    const p = lp ? parseFloat(lp) : livePrice
    setTarget((side === 'BUY' ? p * (1 + pct) : p * (1 - pct)).toFixed(2))
  }
  function autoSize() {
    if (!livePrice) return
    const p    = lp ? parseFloat(lp) : livePrice
    const cap  = Math.min(equity * 0.05, 100_000)
    setQty(String(Math.max(1, Math.floor(cap / p))))
  }

  const notional = livePrice && qty ? (parseFloat(qty) || 0) * livePrice : null
  const slPrice  = sl     ? parseFloat(sl)     : null
  const risk     = slPrice && livePrice && qty ? Math.abs((livePrice - slPrice) * (parseFloat(qty) || 0)) : null
  const rrText   = slPrice && target && livePrice
    ? (() => {
        const r = Math.abs(livePrice - slPrice)
        const w = Math.abs(parseFloat(target) - livePrice)
        return r > 0 ? `R:R ${(w/r).toFixed(1)}` : ''
      })() : ''

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
    } finally { setLoading(false) }
  }

  const inp = {
    width: '100%', background: '#161616', border: '1px solid #242424',
    color: '#e5e5e5', fontSize: 12, padding: '4px 7px', borderRadius: 3,
    boxSizing: 'border-box' as const,
  }

  return (
    <div className="panel h-full" style={{ display: 'flex', flexDirection: 'column' }}>
      <div className="panel-header justify-between">
        <span><span className="accent">▸</span> ORDER TICKET</span>
        {livePrice != null && symbol && (
          <span style={{ fontSize: 11, color: '#4ade80' }}>{symbol} ₹{livePrice.toFixed(2)}</span>
        )}
      </div>
      <div style={{ padding: '8px 10px', display: 'flex', flexDirection: 'column', gap: 6, flex: 1, overflow: 'auto' }}>
        {/* Symbol */}
        <div style={{ position: 'relative' }}>
          <label style={{ fontSize: 9, color: '#444', display: 'block', marginBottom: 2 }}>SYMBOL</label>
          <input value={search} onChange={e => { setSearch(e.target.value); setSymbol('') }}
            placeholder="type to search…" style={{ ...inp, color: symbol ? '#4ade80' : '#e5e5e5' }} />
          {showDrop && (
            <div style={{ position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 50,
                          background: '#161616', border: '1px solid #2a2a2a', borderRadius: 3,
                          maxHeight: 140, overflow: 'auto' }}>
              {filtered.slice(0, 10).map(i => (
                <div key={i.token} onClick={() => { setSymbol(i.symbol); setSearch(i.symbol) }}
                  style={{ padding: '4px 8px', fontSize: 11, cursor: 'pointer', color: '#ccc' }}
                  onMouseEnter={e => (e.currentTarget.style.background = '#1e1e1e')}
                  onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}>
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

        {/* Qty */}
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
            <label style={{ fontSize: 9, color: '#444' }}>QTY</label>
            <button onClick={autoSize} disabled={!livePrice}
              style={{ fontSize: 9, color: '#555', background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}>
              auto-size
            </button>
          </div>
          <input type="number" min="1" value={qty} onChange={e => setQty(e.target.value)} placeholder="0" style={inp} />
          {notional != null && (
            <div style={{ fontSize: 9, color: '#444', marginTop: 2 }}>
              {fmtINR(notional)} notional{risk != null ? ` · Risk ${fmtINR(risk)}` : ''}{rrText ? ` · ${rrText}` : ''}
            </div>
          )}
        </div>

        {/* SL */}
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

        {/* Target */}
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

        {/* Submit */}
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
              background: loading || !symbol || !qty ? '#1a1a1a' : (side === 'BUY' ? '#14532d' : '#7f1d1d'),
              color: loading || !symbol || !qty ? '#333' : (side === 'BUY' ? '#4ade80' : '#f87171'),
            }}>{loading ? 'SENDING…' : `PLACE ${side}`}
          </button>
        )}

        {msg && (
          <div style={{ fontSize: 11, padding: '4px 7px', borderRadius: 3,
                        background: msg.ok ? '#0a1f0a' : '#1f0a0a',
                        color: msg.ok ? '#4ade80' : '#f87171',
                        border: `1px solid ${msg.ok ? '#14532d' : '#7f1d1d'}` }}>
            {msg.text}
          </div>
        )}
      </div>
    </div>
  )
}

// ── Learning Engine ───────────────────────────────────────────────────────────

function LearnerPanel({ stats, refresh }: { stats: TradeStats | null; refresh: number }) {
  const [params, setParams]   = useState<LearnerParams[]>([])
  const paramsUpdate = useSocketEvent<LearnerParams | null>('learner_params_updated', null)
  const eodReset     = useSocketEvent<{ date: string; equity: number } | null>('settlement_eod_reset', null)
  const [lastEvent,  setLastEvent] = useState<string | null>(null)

  useEffect(() => { api.learnerParams().then(setParams).catch(() => {}) }, [refresh])
  useEffect(() => {
    if (!paramsUpdate) return
    setParams(prev => {
      const i = prev.findIndex(p => p.strategy_id === paramsUpdate.strategy_id)
      if (i >= 0) { const n = [...prev]; n[i] = paramsUpdate; return n }
      return [...prev, paramsUpdate]
    })
  }, [paramsUpdate])
  useEffect(() => {
    if (eodReset) setLastEvent(`EOD reset ${eodReset.date} · equity ₹${Math.round(eodReset.equity).toLocaleString('en-IN')}`)
  }, [eodReset])

  // Settlement countdown
  const istOffset   = 5.5 * 60 * 60 * 1000
  const now         = new Date()
  const istNow      = new Date(now.getTime() + istOffset - now.getTimezoneOffset() * 60000)
  const settToday   = new Date(istNow); settToday.setHours(15, 30, 0, 0)
  const msToSett    = settToday.getTime() - istNow.getTime()
  const settLabel   = msToSett > 0
    ? `EOD in ${Math.floor(msToSett / 3600000)}h ${Math.floor((msToSett % 3600000) / 60000)}m`
    : 'post-market'

  // Strategy attribution
  const byStrat = stats?.by_strategy
    ? Object.entries(stats.by_strategy).sort((a, b) => b[1].pnl - a[1].pnl)
    : []

  return (
    <div className="panel h-full" style={{ display: 'flex', flexDirection: 'column', minHeight: 0 }}>
      <div className="panel-header justify-between">
        <span><span className="accent">▸</span> LEARNING ENGINE</span>
        <span style={{ fontSize: 9, color: '#444' }}>{settLabel}</span>
      </div>
      <div className="panel-body" style={{ flex: 1, minHeight: 0, overflow: 'auto' }}>
        {lastEvent && (
          <div style={{ fontSize: 9, color: '#a78bfa', background: '#1a0a2e', padding: '3px 8px', marginBottom: 6, borderRadius: 3 }}>
            {lastEvent}
          </div>
        )}

        {/* Attribution */}
        {byStrat.length > 0 && (
          <>
            <div style={{ fontSize: 9, color: '#444', letterSpacing: '0.08em', padding: '2px 0 4px' }}>ATTRIBUTION</div>
            <table style={{ fontSize: 10, marginBottom: 8 }}>
              <thead><tr><th>Strategy</th><th>N</th><th>WR</th><th>P&L</th></tr></thead>
              <tbody>
                {byStrat.map(([sid, rec]) => (
                  <tr key={sid}>
                    <td style={{ color: '#ccc', fontSize: 10 }}>{sid}</td>
                    <td style={{ color: '#555', fontSize: 10 }}>{rec.trades}</td>
                    <td style={{ fontSize: 10, color: rec.win_rate >= 0.5 ? '#4ade80' : '#f87171' }}>
                      {(rec.win_rate * 100).toFixed(0)}%
                    </td>
                    <td><PnlSpan v={rec.pnl} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}

        {/* Adaptive params */}
        {params.length > 0 && (
          <>
            <div style={{ fontSize: 9, color: '#444', letterSpacing: '0.08em', padding: '2px 0 4px' }}>ADAPTIVE PARAMS</div>
            <table style={{ fontSize: 10 }}>
              <thead>
                <tr>
                  <th>Strat</th>
                  <th title="Min confidence">Conf</th>
                  <th title="SL multiplier">SL×</th>
                  <th title="Bayesian WR">BWR</th>
                  <th title="Trades">N</th>
                </tr>
              </thead>
              <tbody>
                {params.sort((a, b) => a.strategy_id.localeCompare(b.strategy_id)).map(p => (
                  <tr key={p.strategy_id}>
                    <td style={{ color: '#ccc', fontWeight: 600 }}>{p.strategy_id}</td>
                    <td style={{ color: p.min_confidence > 0.55 ? '#f87171' : p.min_confidence < 0.40 ? '#4ade80' : '#888' }}>
                      {(p.min_confidence * 100).toFixed(0)}%
                    </td>
                    <td style={{ color: p.sl_multiplier > 2 ? '#fb923c' : '#888' }}>{p.sl_multiplier.toFixed(1)}×</td>
                    <td style={{ color: p.bayes_wr >= 0.55 ? '#4ade80' : p.bayes_wr < 0.40 ? '#f87171' : '#888' }}>
                      {(p.bayes_wr * 100).toFixed(0)}%
                    </td>
                    <td style={{ color: '#555' }}>{p.n_trades}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}

        {params.length === 0 && byStrat.length === 0 && (
          <p style={{ color: '#333', textAlign: 'center', marginTop: 12, fontSize: 11 }}>Accumulating trades…</p>
        )}
      </div>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function TradePage() {
  const [summary,  setSummary]  = useState<PortfolioSummary | null>(null)
  const [stats,    setStats]    = useState<TradeStats | null>(null)
  const [refresh,  setRefresh]  = useState(0)
  // Prefill: symbol + side from signal click or orchestrator FIRE
  const [prefill,  setPrefill]  = useState<{ symbol: string; side: 'BUY' | 'SELL'; sl?: number; target?: number } | null>(null)

  const { instruments, tokenMap } = useInstrumentMap()
  const pnlUpdate = useSocketEvent<{ equity: number; daily_pnl: number } | null>('pnl_update', null)

  function loadMeta() {
    api.portfolio().then(setSummary).catch(() => {})
    api.tradeStats().then(setStats).catch(() => {})
  }

  useEffect(() => { loadMeta() }, [refresh])
  useEffect(() => {
    if (!pnlUpdate) return
    setSummary(prev => prev ? { ...prev, equity: pnlUpdate.equity, daily_pnl: pnlUpdate.daily_pnl } : prev)
  }, [pnlUpdate])

  function handleFilled() { setTimeout(() => setRefresh(r => r + 1), 600) }

  // Prefill order ticket from orchestrator FIRE button
  function handleFire(r: OrchestratorResult) {
    const symbol = r.symbol
    if (!symbol || r.side === 'NEUTRAL' || r.side === 'SKIP') return
    setPrefill({
      symbol,
      side: r.side as 'BUY' | 'SELL',
      sl:     r.suggested_sl   > 0 ? r.suggested_sl   : undefined,
      target: r.suggested_target > 0 ? r.suggested_target : undefined,
    })
  }

  return (
    <div style={{
      flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column',
      overflow: 'hidden', padding: '6px 10px', gap: 6,
    }}>
      {/* Stats strip */}
      <StatsStrip summary={summary} stats={stats} />

      {/* Main grid: left=agent cockpit (tall), center=positions+trades, right=order+learner */}
      <div style={{
        flex: 1, minHeight: 0, display: 'grid',
        gridTemplateColumns: '380px 1fr 280px',
        gridTemplateRows: '1fr 1fr',
        gap: 6,
      }}>
        {/* Left col: Agent Cockpit (spans both rows) */}
        <div style={{ gridRow: '1 / 3', gridColumn: '1 / 2', minHeight: 0, overflow: 'hidden' }}>
          <AgentCockpit tokenMap={tokenMap} onFire={handleFire} />
        </div>

        {/* Center-top: Open positions */}
        <div style={{ gridRow: '1 / 2', gridColumn: '2 / 3', minHeight: 0, overflow: 'hidden' }}>
          <OpenPositions tokenMap={tokenMap} refresh={refresh} />
        </div>

        {/* Center-bottom: Closed trades */}
        <div style={{ gridRow: '2 / 3', gridColumn: '2 / 3', minHeight: 0, overflow: 'hidden' }}>
          <ClosedTrades tokenMap={tokenMap} refresh={refresh} />
        </div>

        {/* Right-top: Order ticket */}
        <div style={{ gridRow: '1 / 2', gridColumn: '3 / 4', minHeight: 0, overflow: 'hidden' }}>
          <OrderTicket
            instruments={instruments}
            tokenMap={tokenMap}
            prefill={prefill}
            equity={summary?.equity ?? 1_000_000}
            onFilled={handleFilled}
          />
        </div>

        {/* Right-bottom: Learning engine + attribution */}
        <div style={{ gridRow: '2 / 3', gridColumn: '3 / 4', minHeight: 0, overflow: 'hidden' }}>
          <LearnerPanel stats={stats} refresh={refresh} />
        </div>
      </div>
    </div>
  )
}
