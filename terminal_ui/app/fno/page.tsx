'use client'
import { THEME } from '@/lib/theme'
/**
 * F&O MODULE — index derivatives cockpit.
 *
 * Separated from the EQUITIES module because derivative instruments behave
 * differently: index underlyings are not cash-tradeable (F&O only), sizing is
 * lot-based, positions carry expiry/greeks, and margining is SPAN-based.
 *
 * Phase 1 (this page): live index complex (NIFTY/BANKNIFTY/FINNIFTY/VIX),
 * index strategy signals from the orchestrator (S1 ORB, S2 52w, S8 VIX fade),
 * and the volatility regime context that drives derivative sizing.
 * Phase 2 (scaffolded below): contract chain, lot-based paper execution,
 * SPAN margin estimation — tracked in the PRD.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { usePersistedState } from '@/hooks/usePersistedState'
import {
  api, OrchestratorState, OrchestratorResult, RegimeState, SignalRec, Instrument,
  FnOChain, FnOExpiry, FnOUnderlying, FnOPosition, FnOGreeks,
} from '@/lib/api'
import { useTickMap } from '@/hooks/useSocket'
import { getSocket } from '@/lib/socket'
import TradePipelinePanel from '@/components/panels/TradePipelinePanel'

const C = THEME

// Fallback only — live values come from /api/market/contract-specs
// (sourced from NSE lot-size circulars; see terminal_in/data_ingest/contract_specs.py)
const INDICES_FALLBACK = [
  { symbol: 'NIFTY 50',          token: 256265, label: 'NIFTY 50',  lot: 75 },
  { symbol: 'NIFTY BANK',        token: 260105, label: 'BANKNIFTY', lot: 35 },
  { symbol: 'NIFTY FIN SERVICE', token: 257801, label: 'FINNIFTY',  lot: 65 },
]
type ContractSpec = { token: number; label: string; lot_size: number }
function useContractSpecs() {
  const [specs, setSpecs] = useState<{ contracts: ContractSpec[]; fut_margin_band: [number, number]; source_note: string } | null>(null)
  useEffect(() => {
    fetch('/api/market/contract-specs').then(r => r.json()).then(setSpecs).catch(() => {})
  }, [])
  const indices = specs?.contracts?.length
    ? specs.contracts.map(c => ({ symbol: c.label, token: c.token, label: c.label, lot: c.lot_size }))
    : INDICES_FALLBACK
  return { indices, marginBand: specs?.fut_margin_band ?? [0.11, 0.14] as [number, number], sourceNote: specs?.source_note ?? '' }
}
const VIX_TOKEN = 264969
const INDEX_TOKENS = new Set([256265, 260105, 257801])

function fmtTs(ms: number) { return new Date(ms).toLocaleTimeString('en-IN', { hour12: false }) }

// ── Index complex strip ───────────────────────────────────────────────────────
function IndexStrip({ regime }: { regime: RegimeState | null }) {
  const { indices: INDICES } = useContractSpecs()
  const ticks = useTickMap()
  const [closes, setCloses] = useState<Record<string, { close: number }>>({})
  useEffect(() => { api.lastCloses().then(c => setCloses(c as never)).catch(() => {}) }, [])

  const vix = ticks[VIX_TOKEN]?.last_price ?? closes[String(VIX_TOKEN)]?.close ?? 0
  const vixColor = vix > 25 ? C.red : vix > 18 ? C.amber : C.green

  return (
    <div style={{ display: 'flex', alignItems: 'stretch', background: 'rgba(12,13,16,0.82)', backdropFilter: 'blur(7px)', borderBottom: `1px solid ${C.border}`, flexShrink: 0, height: 58 }}>
      <div style={{ padding: '0 16px', borderRight: `1px solid ${C.border}`, display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center', gap: 2, minWidth: 86 }}>
        <span style={{ fontSize: 10.5, fontWeight: 700, color: C.text, letterSpacing: '.1em' }}>F&amp;O</span>
        <span style={{ fontSize: 9.5, fontWeight: 700, color: C.purple, letterSpacing: '.1em', background: '#15081A', border: `1px solid ${C.purple}33`, borderRadius: 3, padding: '1px 6px' }}>DERIVATIVES</span>
      </div>
      {INDICES.map(({ token, label, lot }) => {
        const price = ticks[token]?.last_price ?? closes[String(token)]?.close ?? 0
        const chg = ticks[token]?.change ?? 0
        return (
          <div key={token} style={{ flex: 1, padding: '0 14px', borderRight: `1px solid ${C.border}`, display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: 2 }}>
            <span style={{ fontSize: 9.5, color: C.dim, letterSpacing: '.08em' }}>{label} <span style={{ color: '#4A4F57' }}>· LOT {lot}</span></span>
            <span style={{ fontSize: 15, fontWeight: 600, color: C.text, fontVariantNumeric: 'tabular-nums', lineHeight: 1 }}>
              {price > 0 ? price.toLocaleString('en-IN', { maximumFractionDigits: 1 }) : '—'}
            </span>
            <span style={{ fontSize: 10, color: chg >= 0 ? C.green : C.red, fontVariantNumeric: 'tabular-nums' }}>
              {chg >= 0 ? '▲' : '▼'} {Math.abs(chg).toFixed(2)}%
            </span>
          </div>
        )
      })}
      <div style={{ flex: 1, padding: '0 14px', borderRight: `1px solid ${C.border}`, display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: 2 }}>
        <span style={{ fontSize: 9.5, color: C.dim, letterSpacing: '.08em' }}>INDIA VIX</span>
        <span style={{ fontSize: 15, fontWeight: 600, color: vixColor, fontVariantNumeric: 'tabular-nums', lineHeight: 1 }}>{vix > 0 ? vix.toFixed(2) : '—'}</span>
        <span style={{ fontSize: 9.5, color: C.muted }}>{vix > 25 ? 'elevated — size down' : vix > 18 ? 'watchful' : 'calm'}</span>
      </div>
      <div style={{ flex: 1.2, padding: '0 14px', display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: 2 }}>
        <span style={{ fontSize: 9.5, color: C.dim, letterSpacing: '.08em' }}>REGIME · SIZE MULT</span>
        <span style={{ fontSize: 13, fontWeight: 700, color: C.amber, letterSpacing: '.06em', textTransform: 'uppercase', lineHeight: 1 }}>
          {regime?.regime ?? '—'} <span style={{ color: C.sub, fontWeight: 500 }}>× {(regime?.size_multiplier ?? 1).toFixed(1)}</span>
        </span>
        <span style={{ fontSize: 9.5, color: C.muted }}>drives derivative position sizing</span>
      </div>
    </div>
  )
}

// ── F&O book: account summary + live open positions (self-fetching) ──────────
function FnOBook() {
  const [positions, setPositions] = useState<FnOPosition[]>([])
  const [meta, setMeta] = useState<{ unrealized: number; margin_used: number; greeks?: FnOGreeks } | null>(null)
  const load = useCallback(() => {
    api.fnoPositions().then(d => { setPositions(d.positions ?? []); setMeta({ unrealized: d.unrealized, margin_used: d.margin_used, greeks: d.greeks }) }).catch(() => {})
  }, [])
  useEffect(() => { load() }, [load])
  useEffect(() => {
    const s = getSocket()
    const h = () => load()
    for (const ev of ['fno.trade.opened', 'fno.trade.closed', 'fno.signal.routed']) s.on(ev, h)
    const t = setInterval(load, 8000)
    return () => { for (const ev of ['fno.trade.opened', 'fno.trade.closed', 'fno.signal.routed']) s.off(ev, h); clearInterval(t) }
  }, [load])
  const close = (tid: string) => api.fnoClosePosition(tid).then(load)

  const totUpnl = meta?.unrealized ?? 0
  const gk = meta?.greeks
  // real Black-Scholes book greeks from the server; crude fallback only if absent
  const posDelta = gk ? gk.net_delta : positions.reduce((s, p) => s + (p.opt_type === 'CE' ? 1 : p.opt_type === 'PE' ? -1 : 1) * (p.side === 'BUY' ? 1 : -1) * p.lots * p.lot_size * 0.5, 0)

  return (
    <div className="panel" style={{ flex: 1, minHeight: 0, borderRadius: 5, display: 'flex', flexDirection: 'column' }}>
      <div className="panel-header">F&amp;O BOOK <span style={{ color: '#4A4F57' }}>{positions.length} open</span>
        <span style={{ marginLeft: 'auto', color: totUpnl >= 0 ? C.green : C.red, fontWeight: 700 }}>
          {totUpnl >= 0 ? '+' : ''}₹{totUpnl.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
        </span>
      </div>
      {/* account summary */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 8, padding: '9px 12px', borderBottom: `1px solid ${C.border}`, flexShrink: 0 }}>
        <Stat label="UNREALISED" value={`${totUpnl >= 0 ? '+' : ''}₹${Math.abs(totUpnl).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`} color={totUpnl >= 0 ? C.green : C.red} />
        <Stat label="MARGIN USED" value={`₹${((meta?.margin_used ?? 0) / 1e5).toFixed(2)}L`} color={C.warn} />
        <Stat label="NET DELTA" value={posDelta.toFixed(0)} color={posDelta >= 0 ? C.green : C.red} />
      </div>
      {gk && positions.length > 0 && (
        <div style={{ display: 'flex', gap: 14, padding: '5px 12px', borderBottom: `1px solid ${C.border}`, flexShrink: 0,
          fontSize: 9.5, color: C.muted, fontVariantNumeric: 'tabular-nums' }}>
          <span>θ <span style={{ color: gk.net_theta >= 0 ? C.green : C.red }}>{gk.net_theta >= 0 ? '+' : ''}₹{Math.abs(gk.net_theta).toLocaleString('en-IN', { maximumFractionDigits: 0 })}/d</span></span>
          <span>vega <span style={{ color: C.sub }}>₹{Math.abs(gk.net_vega).toLocaleString('en-IN', { maximumFractionDigits: 0 })}/vol</span></span>
          <span title="P&L from a 2% underlying gap (negative = short-gamma risk)">Γ@2% <span style={{ color: gk.net_gamma_2pct >= 0 ? C.green : C.red }}>{gk.net_gamma_2pct >= 0 ? '+' : ''}₹{Math.abs(gk.net_gamma_2pct).toLocaleString('en-IN', { maximumFractionDigits: 0 })}</span></span>
          <span style={{ marginLeft: 'auto', color: C.dim }}>theoretical</span>
        </div>
      )}
      <div className="panel-body" style={{ flex: 1, minHeight: 0, overflow: 'auto', padding: 8 }}>
        {positions.length === 0 ? (
          <div style={{ fontSize: 10.5, color: C.muted, textAlign: 'center', padding: 24 }}>
            No open F&amp;O positions. Switch to <strong style={{ color: C.accentBright }}>OPTION CHAIN</strong> to trade.
          </div>
        ) : positions.map(p => (
          <div key={p.trade_id} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '7px 9px', marginBottom: 5,
            background: C.card, border: `1px solid ${C.border}`, borderRadius: 4, borderLeft: `2px solid ${p.side === 'BUY' ? C.green : C.red}` }}>
            <div style={{ minWidth: 0, flex: 1 }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: C.text, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p.tradingsymbol}</div>
              <div style={{ fontSize: 9, color: C.muted, fontVariantNumeric: 'tabular-nums' }}>{p.side} {p.lots}×{p.lot_size} · entry {p.entry_price} · mark {p.mark}</div>
            </div>
            <div style={{ textAlign: 'right' }}>
              <div style={{ fontSize: 11.5, fontWeight: 700, color: p.unrealized >= 0 ? C.green : C.red, fontVariantNumeric: 'tabular-nums' }}>
                {p.unrealized >= 0 ? '+' : ''}₹{Math.abs(p.unrealized).toLocaleString('en-IN', { maximumFractionDigits: 0 })}
              </div>
              <div style={{ fontSize: 8.5, color: C.dim }}>margin ₹{(p.margin / 1e3).toFixed(0)}k</div>
            </div>
            <button onClick={() => close(p.trade_id)} className="btn" style={{ fontSize: 9, padding: '3px 7px' }} title="square off">✕</button>
          </div>
        ))}
      </div>
    </div>
  )
}
function Stat({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
      <span style={{ fontSize: 8.5, color: C.dim, letterSpacing: '.06em' }}>{label}</span>
      <span style={{ fontSize: 14, fontWeight: 700, color, fontVariantNumeric: 'tabular-nums' }}>{value}</span>
    </div>
  )
}

// ── Index signals (orchestrator lenses on the index complex) ─────────────────
function IndexSignals({ results }: { results: OrchestratorResult[] }) {
  const indexResults = results.filter(r => INDEX_TOKENS.has(r.token))
  return (
    <div className="panel" style={{ borderRadius: 5 }}>
      <div className="panel-header">INDEX STRATEGY SIGNALS <span style={{ color: '#4A4F57' }}>S1 ORB · S2 52W · S8 VIX FADE</span></div>
      <div className="panel-body" style={{ padding: 10 }}>
        {indexResults.length === 0 ? (
          <div style={{ fontSize: 10.5, color: C.muted, padding: 20, textAlign: 'center' }}>
            No index signals this scan — lenses fire on breakouts, oversold RSI, and VIX asymmetry.
          </div>
        ) : indexResults.map(r => (
          <div key={r.token} style={{
            display: 'flex', alignItems: 'baseline', gap: 12, padding: '8px 10px', marginBottom: 6,
            background: C.card, border: `1px solid ${C.border}`, borderRadius: 4,
            borderLeft: `2px solid ${r.side === 'BUY' ? C.green : r.side === 'SELL' ? C.red : C.border2}`,
          }}>
            <span style={{ fontSize: 11.5, fontWeight: 700, color: C.text, minWidth: 90 }}>{r.symbol}</span>
            <span style={{ fontSize: 10.5, fontWeight: 700, color: r.side === 'BUY' ? C.green : r.side === 'SELL' ? C.red : C.muted, minWidth: 70 }}>{r.verdict}</span>
            <span style={{ fontSize: 10.5, color: C.sub, fontVariantNumeric: 'tabular-nums' }}>{r.price.toLocaleString('en-IN')}</span>
            <span style={{ fontSize: 10, color: C.muted }}>RSI {r.rsi.toFixed(0)}</span>
            {r.ev > 0 && <span style={{ fontSize: 10, color: C.amber }}>EV {r.ev.toFixed(2)}</span>}
            <span style={{ fontSize: 10, color: C.muted, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.summary}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Recent index-related signals from the engine ──────────────────────────────
function SignalLog({ signals }: { signals: SignalRec[] }) {
  return (
    <div className="panel" style={{ borderRadius: 5 }}>
      <div className="panel-header">SIGNAL LOG <span style={{ color: '#4A4F57' }}>INDEX COMPLEX</span></div>
      <div className="panel-body">
        {signals.length === 0 ? (
          <div style={{ fontSize: 10.5, color: C.muted, padding: 20, textAlign: 'center' }}>No recent index signals.</div>
        ) : (
          <table>
            <thead><tr><th>TIME</th><th>STRATEGY</th><th>SIDE</th><th>CONF</th><th>STATUS</th></tr></thead>
            <tbody>
              {signals.map(s => (
                <tr key={s.signal_id}>
                  <td style={{ color: C.muted }}>{fmtTs(s.decided_at)}</td>
                  <td style={{ color: C.text }}>{s.strategy_id}</td>
                  <td style={{ color: s.side === 'BUY' ? C.green : C.red }}>{s.side}</td>
                  <td style={{ color: C.sub }}>{s.confidence != null ? `${(s.confidence * 100).toFixed(0)}%` : '—'}</td>
                  <td style={{ color: s.approved ? C.green : C.red }}>{s.approved ? 'APPROVED' : 'REJECTED'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

// ── Contract reference — live notional and margin math per index ─────────────
function ContractReference() {
  const { indices: INDICES, marginBand, sourceNote } = useContractSpecs()
  const ticks = useTickMap()
  const [closes, setCloses] = useState<Record<string, { close: number }>>({})
  const [equity, setEquity] = useState(0)
  useEffect(() => {
    api.lastCloses().then(c => setCloses(c as never)).catch(() => {})
    fetch('/api/portfolio/holdings').then(r => r.json())
      .then(d => setEquity(d?.equity ?? 0)).catch(() => {})
  }, [])

  return (
    <div className="panel" style={{ borderRadius: 5 }}>
      <div className="panel-header">CONTRACT REFERENCE <span style={{ color: '#4A4F57' }}>FUTURES · LIVE NOTIONAL</span></div>
      <div className="panel-body" style={{ padding: 0 }}>
        <table style={{ width: '100%' }}>
          <thead>
            <tr>
              <th style={{ textAlign: 'left', padding: '6px 10px' }}>INDEX</th>
              <th style={{ textAlign: 'right' }}>LOT</th>
              <th style={{ textAlign: 'right' }}>SPOT</th>
              <th style={{ textAlign: 'right' }}>NOTIONAL/LOT</th>
              <th style={{ textAlign: 'right' }}>≈MARGIN/LOT</th>
              <th style={{ textAlign: 'right', paddingRight: 10 }}>MAX LOTS*</th>
            </tr>
          </thead>
          <tbody>
            {INDICES.map(({ token, label, lot }) => {
              const spot = ticks[token]?.last_price ?? closes[String(token)]?.close ?? 0
              const notional = spot * lot
              const margin = notional * ((marginBand[0] + marginBand[1]) / 2)
              const maxLots = margin > 0 && equity > 0 ? Math.floor((equity * 0.25) / margin) : 0
              return (
                <tr key={token}>
                  <td style={{ padding: '6px 10px', fontWeight: 600, color: C.text }}>{label}</td>
                  <td style={{ textAlign: 'right' }}>{lot}</td>
                  <td style={{ textAlign: 'right', color: C.text }}>{spot > 0 ? spot.toLocaleString('en-IN', { maximumFractionDigits: 1 }) : '—'}</td>
                  <td style={{ textAlign: 'right' }}>₹{(notional / 100000).toFixed(1)}L</td>
                  <td style={{ textAlign: 'right', color: C.amber }}>₹{(margin / 100000).toFixed(2)}L</td>
                  <td style={{ textAlign: 'right', paddingRight: 10, color: C.sub }}>{maxLots}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
        <div style={{ fontSize: 9.5, color: C.muted, padding: '6px 10px', borderTop: `1px solid ${C.border}` }}>
          *at 25% of equity per position · margin band {(marginBand[0] * 100).toFixed(0)}–{(marginBand[1] * 100).toFixed(0)}% of notional · {sourceNote || 'NSE SPAN + exposure estimate'}
        </div>
      </div>
    </div>
  )
}

// ── Phase 2 footer strip ──────────────────────────────────────────────────────
function RoadmapStrip() {
  // collapsed to a one-line chip after first view — the roadmap shouldn't
  // burn a permanent row to repeat itself (persisted in localStorage)
  const [open, setOpen] = useState(false)
  useEffect(() => { setOpen(localStorage.getItem('fno_roadmap_seen') !== '1') }, [])
  const dismiss = () => { localStorage.setItem('fno_roadmap_seen', '1'); setOpen(false) }
  const items = ['Contract chain ✓', 'Lot-based fills', 'SPAN margin', 'Multi-leg options (P3)']

  if (!open) {
    return (
      <button onClick={() => setOpen(true)} style={{
        alignSelf: 'flex-start', display: 'inline-flex', alignItems: 'center', gap: 6,
        fontSize: 9.5, fontWeight: 700, letterSpacing: '.07em', padding: '2px 9px',
        background: 'transparent', border: `1px solid ${C.border}`, borderRadius: 3,
        color: C.muted, cursor: 'pointer',
      }}>
        ⓘ EXECUTION · PHASE 2
      </button>
    )
  }
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 8, padding: '7px 12px', flexShrink: 0,
      background: C.card, border: `1px solid ${C.border}`, borderRadius: 5,
    }}>
      <span style={{ fontSize: 9.5, fontWeight: 700, color: C.amber, letterSpacing: '.08em', flexShrink: 0 }}>EXECUTION · PHASE 2</span>
      {items.map(i => (
        <span key={i} style={{ fontSize: 9.5, color: C.muted, border: `1px solid ${C.border2}`, borderRadius: 3, padding: '1px 7px', whiteSpace: 'nowrap' }}>{i}</span>
      ))}
      <span style={{ fontSize: 9.5, color: C.muted, marginLeft: 'auto', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        index signals route via NIFTYBEES until then — see PRD
      </span>
      <button onClick={dismiss} style={{
        background: 'none', border: 'none', color: C.muted, cursor: 'pointer',
        fontSize: 11, padding: '0 2px', flexShrink: 0, lineHeight: 1,
      }} title="Collapse — reopen from the chip">✕</button>
    </div>
  )
}

// ── Option chain + order ticket + positions (Stages 2 + 3b) ───────────────────
type SelectedLeg = { strike: number; opt_type: 'CE' | 'PE'; premium: number; delta: number; theta: number } | null

function OptionChain() {
  const [unders, setUnders]   = useState<FnOUnderlying[]>([])
  const [under, setUnder]     = useState('NIFTY')
  const [expiry, setExpiry]   = useState<string | undefined>(undefined)
  const [chain, setChain]     = useState<FnOChain | null>(null)
  const [loading, setLoading] = useState(false)
  const [leg, setLeg]         = useState<SelectedLeg>(null)
  const [positions, setPositions] = useState<FnOPosition[]>([])
  const [msg, setMsg]         = useState<{ t: string; ok: boolean } | null>(null)

  useEffect(() => { api.fnoUnderlyings().then(d => setUnders(d.underlyings)).catch(() => {}) }, [])

  const loadChain = useCallback(async (u: string, exp?: string) => {
    setLoading(true)
    try {
      const c = await api.fnoChain(u, exp, 12)
      setChain(c)
      if (!exp && c.expiry) setExpiry(c.expiry)
    } catch { setChain(null) } finally { setLoading(false) }
  }, [])

  const loadPositions = useCallback(() => {
    api.fnoPositions().then(d => setPositions(d.positions ?? [])).catch(() => {})
  }, [])

  useEffect(() => { loadChain(under, expiry) /* eslint-disable-next-line */ }, [under])
  useEffect(() => { loadPositions() }, [loadPositions])
  // refresh premiums + marks every 15s (theoretical, recomputed from live spot)
  useEffect(() => {
    const t = setInterval(() => { loadChain(under, expiry); loadPositions() }, 15_000)
    return () => clearInterval(t)
  }, [under, expiry, loadChain, loadPositions])

  const exps = chain?.expiries ?? []
  const greekTone = (v: number) => (v >= 0 ? C.green : C.red)
  const selectCell = (r: FnOChain['rows'][number], side: 'CE' | 'PE') => {
    const leg = side === 'CE' ? r.CE : r.PE
    setLeg({ strike: r.strike, opt_type: side, premium: leg.premium, delta: leg.delta, theta: leg.theta })
  }

  const placeOrder = useCallback(async (side: 'BUY' | 'SELL', lots: number, sl?: number, tgt?: number) => {
    if (!chain || !leg) return
    const res = await api.fnoOrder({
      underlying: chain.underlying, expiry: chain.expiry, strike: leg.strike,
      opt_type: leg.opt_type, side, lots, sl_premium: sl, target_premium: tgt,
    })
    if (res.ok) {
      setMsg({ t: `${side} ${lots} lot${lots > 1 ? 's' : ''} ${res.tradingsymbol} @ ${res.premium} · margin ₹${(res.margin ?? 0).toLocaleString('en-IN')}`, ok: true })
      setLeg(null); loadPositions()
    } else {
      setMsg({ t: res.error ?? 'order rejected', ok: false })
    }
    setTimeout(() => setMsg(null), 5000)
  }, [chain, leg, loadPositions])

  const closePosition = useCallback(async (tid: string) => {
    const res = await api.fnoClosePosition(tid)
    if (!res.ok) setMsg({ t: res.error ?? 'close failed', ok: false })
    loadPositions(); if (!res.ok) setTimeout(() => setMsg(null), 4000)
  }, [loadPositions])

  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex', gap: 8 }}>
      {/* LEFT — chain table */}
      <div className="panel" style={{ flex: 1.7, minHeight: 0, borderRadius: 5, display: 'flex', flexDirection: 'column' }}>
        <div className="panel-header" style={{ flexWrap: 'wrap', gap: 8 }}>
          OPTION CHAIN
          {/* index tabs */}
          <span style={{ display: 'inline-flex', gap: 2, marginLeft: 8 }}>
            {(unders.filter(u => u.kind === 'index').map(u => u.label).concat(unders.length ? [] : ['NIFTY', 'BANKNIFTY', 'FINNIFTY'])).map(l => (
              <button key={l} onClick={() => { setExpiry(undefined); setLeg(null); setUnder(l) }}
                style={{ fontSize: 9.5, fontWeight: 700, letterSpacing: '.04em', padding: '3px 9px', border: 'none', cursor: 'pointer', borderRadius: 3,
                  background: under === l ? C.accent : 'transparent', color: under === l ? '#fff' : C.sub }}>{l}</button>
            ))}
          </span>
          {/* stock dropdown (single-stock F&O) */}
          {unders.some(u => u.kind === 'stock') && (
            <select value={unders.find(u => u.label === under)?.kind === 'stock' ? under : ''}
              onChange={e => { if (e.target.value) { setExpiry(undefined); setLeg(null); setUnder(e.target.value) } }}
              style={{ fontSize: 9.5, fontWeight: 600, padding: '3px 6px', borderRadius: 3, cursor: 'pointer',
                background: unders.find(u => u.label === under)?.kind === 'stock' ? C.accent : C.card,
                color: unders.find(u => u.label === under)?.kind === 'stock' ? '#fff' : C.sub,
                border: `1px solid ${C.border2}` }}>
              <option value="">STOCKS ▾</option>
              {unders.filter(u => u.kind === 'stock').map(u => <option key={u.label} value={u.label}>{u.label}</option>)}
            </select>
          )}
          <span style={{ display: 'inline-flex', gap: 3, marginLeft: 6, flexWrap: 'wrap' }}>
            {exps.slice(0, 6).map(e => (
              <button key={e.date} onClick={() => { setExpiry(e.date); setLeg(null); loadChain(under, e.date) }} title={e.kind}
                style={{ fontSize: 9, fontWeight: 600, padding: '2px 7px', borderRadius: 3, cursor: 'pointer',
                  border: `1px solid ${expiry === e.date ? C.accent : C.border2}`,
                  background: expiry === e.date ? '#0094FB18' : 'transparent',
                  color: expiry === e.date ? C.accentBright : C.muted }}>
                {new Date(e.date).toLocaleDateString('en-IN', { day: '2-digit', month: 'short' })}
                {e.kind === 'monthly' && <span style={{ color: C.warn, marginLeft: 3 }}>M</span>}
              </button>
            ))}
          </span>
          {chain && <span style={{ marginLeft: 'auto', display: 'inline-flex', alignItems: 'center', gap: 6, color: C.muted, fontWeight: 400, fontSize: 9.5 }}>
            {chain.live_error && <span title={chain.live_error} style={{ color: C.warn, fontWeight: 700 }}>⚠ LIVE FEED DOWN — THEORETICAL</span>}
            <span style={{ fontSize: 8.5, fontWeight: 700, letterSpacing: '.06em', padding: '1px 6px', borderRadius: 3,
              color: chain.theoretical ? C.dim : C.teal,
              background: (chain.theoretical ? C.dim : C.teal) + '1A',
              border: `1px solid ${(chain.theoretical ? C.dim : C.teal)}40` }}>
              {chain.theoretical ? 'THEORETICAL' : '● LIVE'}
            </span>
            spot {chain.spot.toLocaleString('en-IN')} · ATM {chain.atm_strike} · IV {chain.iv_used_pct}%
            <span title={chain.iv_source} style={{ color: !chain.theoretical ? C.teal : chain.kind === 'stock' ? C.teal : C.accentBright }}>
              ({!chain.theoretical ? 'live IV' : chain.kind === 'stock' ? 'realized vol' : 'India VIX'})
            </span> · lot {chain.lot_size}
          </span>}
        </div>
        <div className="panel-body" style={{ flex: 1, minHeight: 0, overflow: 'auto', padding: 0 }}>
          {!chain?.available && !loading ? (
            <div style={{ padding: 30, textAlign: 'center', fontSize: 10.5, color: C.muted }}>
              {chain?.error ?? 'No chain — needs a live spot or a stored close for the index.'}
            </div>
          ) : (
            <table style={{ width: '100%', fontVariantNumeric: 'tabular-nums' }}>
              <thead>
                <tr>
                  <th style={{ textAlign: 'right', color: C.green }}>CE Δ</th>
                  <th style={{ textAlign: 'right', color: C.green }}>CE θ</th>
                  <th style={{ textAlign: 'right', color: C.green }}>CE LTP*</th>
                  <th style={{ textAlign: 'center', color: C.text }}>STRIKE</th>
                  <th style={{ textAlign: 'left', color: C.red }}>PE LTP*</th>
                  <th style={{ textAlign: 'left', color: C.red }}>PE θ</th>
                  <th style={{ textAlign: 'left', color: C.red }}>PE Δ</th>
                </tr>
              </thead>
              <tbody>
                {(chain?.rows ?? []).map(r => {
                  const itmCE = r.strike < (chain?.spot ?? 0)
                  const itmPE = r.strike > (chain?.spot ?? 0)
                  const selCE = leg?.strike === r.strike && leg?.opt_type === 'CE'
                  const selPE = leg?.strike === r.strike && leg?.opt_type === 'PE'
                  const cell = (sel: boolean, itm: string) => ({
                    textAlign: 'right' as const, color: C.text, fontWeight: 600, cursor: 'pointer',
                    background: sel ? '#0094FB33' : itm, outline: sel ? `1px solid ${C.accent}` : undefined,
                  })
                  return (
                    <tr key={r.strike} style={{ background: r.is_atm ? '#0094FB12' : undefined }}>
                      <td style={{ textAlign: 'right', color: greekTone(r.CE.delta) }}>{r.CE.delta.toFixed(2)}</td>
                      <td style={{ textAlign: 'right', color: C.muted }}>{r.CE.theta.toFixed(1)}</td>
                      <td onClick={() => selectCell(r, 'CE')} title="click to trade this call"
                        style={cell(selCE, itmCE ? '#2DBD800C' : '')}>{r.CE.premium.toFixed(2)}</td>
                      <td style={{ textAlign: 'center', fontWeight: 700, color: r.is_atm ? C.accentBright : C.sub, borderLeft: `1px solid ${C.border}`, borderRight: `1px solid ${C.border}` }}>
                        {r.strike}{r.is_atm && <span style={{ fontSize: 8, color: C.accent, marginLeft: 4 }}>ATM</span>}
                      </td>
                      <td onClick={() => selectCell(r, 'PE')} title="click to trade this put"
                        style={{ ...cell(selPE, itmPE ? '#F2495C0C' : ''), textAlign: 'left' }}>{r.PE.premium.toFixed(2)}</td>
                      <td style={{ textAlign: 'left', color: C.muted }}>{r.PE.theta.toFixed(1)}</td>
                      <td style={{ textAlign: 'left', color: greekTone(r.PE.delta) }}>{r.PE.delta.toFixed(2)}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
        </div>
        {chain?.theoretical ? (
          <div style={{ fontSize: 9, color: C.dim, padding: '5px 10px', borderTop: `1px solid ${C.border}`, flexShrink: 0 }}>
            *LTP = <strong style={{ color: C.muted }}>theoretical</strong> Black-Scholes premium from live spot + {chain.iv_source} ({chain.iv_used_pct}%) as IV — not a traded price. OI/real-IV are live-only. Click a premium to trade.
          </div>
        ) : chain ? (
          <div style={{ fontSize: 9, color: C.dim, padding: '5px 10px', borderTop: `1px solid ${C.border}`, flexShrink: 0 }}>
            *LTP = <strong style={{ color: C.teal }}>live Kite</strong> last-traded price; OI/volume are real, IV is implied from the LTP. Strikes with no trade show null. Click a premium to trade.
          </div>
        ) : null}
      </div>

      {/* RIGHT — order ticket + positions */}
      <div style={{ flex: '0 0 320px', minHeight: 0, display: 'flex', flexDirection: 'column', gap: 8 }}>
        <OrderTicket leg={leg} chain={chain} onPlace={placeOrder} onClear={() => setLeg(null)} msg={msg} />
        <FnOPositionsPanel positions={positions} onClose={closePosition} />
      </div>
    </div>
  )
}

// ── Payoff-at-expiry diagram for the working order ────────────────────────────
function PayoffChart({ strike, optType, premium, side, qty, spot, breakeven }: {
  strike: number; optType: 'CE' | 'PE'; premium: number; side: 'BUY' | 'SELL'
  qty: number; spot: number; breakeven: number
}) {
  const w = 300, h = 96, pad = 6
  const lo = Math.min(spot, strike, breakeven) * 0.92
  const hi = Math.max(spot, strike, breakeven) * 1.08
  const N = 80
  const pnl = (s: number) => {
    const intrinsic = optType === 'CE' ? Math.max(0, s - strike) : Math.max(0, strike - s)
    const per = side === 'BUY' ? intrinsic - premium : premium - intrinsic
    return per * qty
  }
  const xs = Array.from({ length: N + 1 }, (_, i) => lo + (i / N) * (hi - lo))
  const ys = xs.map(pnl)
  const maxA = Math.max(...ys.map(Math.abs), 1)
  const X = (s: number) => pad + ((s - lo) / (hi - lo)) * (w - 2 * pad)
  const Y = (p: number) => h / 2 - (p / maxA) * (h / 2 - pad)
  const zeroY = Y(0)
  const line = xs.map((s, i) => `${X(s)},${Y(ys[i])}`).join(' ')
  // shade profit (green above 0) and loss (red below) using two clipped polys
  const area = (sign: 1 | -1) => {
    const pts = xs.map((s, i) => `${X(s)},${Y(sign > 0 ? Math.max(0, ys[i]) : Math.min(0, ys[i]))}`)
    return `${X(lo)},${zeroY} ${pts.join(' ')} ${X(hi)},${zeroY}`
  }
  return (
    <svg width="100%" height={h} viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" style={{ display: 'block' }}>
      <polygon points={area(1)} fill="#2DBD8022" />
      <polygon points={area(-1)} fill="#F2495C22" />
      <line x1={pad} y1={zeroY} x2={w - pad} y2={zeroY} stroke={C.border2} strokeWidth={1} vectorEffect="non-scaling-stroke" />
      <polyline points={line} fill="none" stroke={C.accentBright} strokeWidth={1.6} vectorEffect="non-scaling-stroke" />
      {/* spot (white) + breakeven (gold dashed) markers */}
      <line x1={X(spot)} y1={pad} x2={X(spot)} y2={h - pad} stroke={C.text} strokeWidth={1} strokeDasharray="2 2" vectorEffect="non-scaling-stroke" />
      <line x1={X(breakeven)} y1={pad} x2={X(breakeven)} y2={h - pad} stroke={C.warn} strokeWidth={1} strokeDasharray="3 2" vectorEffect="non-scaling-stroke" />
    </svg>
  )
}

// ── Order ticket (decision-support: greeks, breakeven, max P/L, payoff) ───────
function OrderTicket({ leg, chain, onPlace, onClear, msg }: {
  leg: SelectedLeg; chain: FnOChain | null
  onPlace: (side: 'BUY' | 'SELL', lots: number, sl?: number, tgt?: number) => void
  onClear: () => void; msg: { t: string; ok: boolean } | null
}) {
  const [side, setSide] = useState<'BUY' | 'SELL'>('BUY')
  const [lots, setLots] = useState(1)
  const [sl, setSl]     = useState('')
  const [tgt, setTgt]   = useState('')
  const lotSize = chain?.lot_size ?? 0
  const qty = lots * lotSize

  const metrics = useMemo(() => {
    if (!leg || !chain) return null
    const prem = leg.premium, K = leg.strike, isCall = leg.opt_type === 'CE'
    const breakeven = isCall ? K + prem : K - prem
    const debit = prem * qty
    const credit = prem * qty
    // long: max loss = debit, max profit = uncapped (call) / (K-prem)*qty (put)
    // short: max profit = credit, max loss = uncapped (call) / (K-prem)*qty (put)
    let maxLoss: number | null, maxProfit: number | null
    if (side === 'BUY') {
      maxLoss = debit
      maxProfit = isCall ? null : (K - prem) * qty
    } else {
      maxProfit = credit
      maxLoss = isCall ? null : (K - prem) * qty
    }
    const posDelta = leg.delta * qty * (side === 'BUY' ? 1 : -1)
    const posTheta = leg.theta * qty * (side === 'BUY' ? 1 : -1)
    const intrinsic = isCall ? Math.max(0, chain.spot - K) : Math.max(0, K - chain.spot)
    const timeVal = Math.max(0, prem - intrinsic)
    const margin = side === 'BUY' ? debit : Math.max(K * qty * 0.12, credit)  // pre-trade estimate
    return { breakeven, maxLoss, maxProfit, posDelta, posTheta, intrinsic, timeVal, margin, debit, credit }
  }, [leg, chain, side, qty])

  const fmt = (v: number | null) => v == null ? '∞' : `₹${Math.abs(v).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`

  return (
    <div className="panel" style={{ flexShrink: 0, borderRadius: 5 }}>
      <div className="panel-header">ORDER TICKET <span style={{ color: '#4A4F57', fontSize: 9 }}>PAPER</span></div>
      <div className="panel-body" style={{ padding: 12 }}>
        {!leg || !chain || !metrics ? (
          <div style={{ fontSize: 10.5, color: C.muted, padding: '14px 4px', textAlign: 'center' }}>
            Click a CE/PE premium in the chain to build an order — you&apos;ll see the payoff, breakeven and max risk before placing.
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 9 }}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
              <span style={{ fontSize: 13, fontWeight: 700, color: C.text }}>{chain.underlying} {leg.strike} {leg.opt_type}</span>
              <span style={{ fontSize: 10, color: C.muted }}>{new Date(chain.expiry).toLocaleDateString('en-IN', { day: '2-digit', month: 'short' })}</span>
              <span style={{ marginLeft: 'auto', fontSize: 12, fontWeight: 700, color: C.accentBright }}>₹{leg.premium.toFixed(2)}</span>
            </div>
            <div style={{ display: 'flex', gap: 4 }}>
              {(['BUY', 'SELL'] as const).map(s => (
                <button key={s} onClick={() => setSide(s)}
                  style={{ flex: 1, fontSize: 11, fontWeight: 700, padding: '6px 0', borderRadius: 4, cursor: 'pointer',
                    border: `1px solid ${side === s ? (s === 'BUY' ? C.green : C.red) : C.border}`,
                    background: side === s ? (s === 'BUY' ? '#2DBD8018' : '#F2495C18') : 'transparent',
                    color: side === s ? (s === 'BUY' ? C.green : C.red) : C.sub }}>{s}</button>
              ))}
            </div>
            <label style={{ fontSize: 10, color: C.dim }}>LOTS <span style={{ color: C.muted }}>(× {lotSize} = {qty} qty)</span>
              <input type="number" min={1} value={lots} onChange={e => setLots(Math.max(1, parseInt(e.target.value) || 1))} style={inputStyle} />
            </label>

            {/* Payoff at expiry */}
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 8.5, color: C.dim, letterSpacing: '.06em', marginBottom: 2 }}>
                <span>PAYOFF AT EXPIRY</span>
                <span><span style={{ color: C.text }}>┊</span> spot &nbsp; <span style={{ color: C.warn }}>┊</span> breakeven</span>
              </div>
              <PayoffChart strike={leg.strike} optType={leg.opt_type} premium={leg.premium} side={side} qty={qty} spot={chain.spot} breakeven={metrics.breakeven} />
            </div>

            {/* Trade metrics */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '5px 10px', fontSize: 10 }}>
              <Metric2 label="Breakeven" value={`₹${metrics.breakeven.toFixed(0)}`} />
              <Metric2 label={side === 'BUY' ? 'Debit' : 'Credit'} value={fmt(side === 'BUY' ? metrics.debit : metrics.credit)} tone={side === 'BUY' ? C.red : C.green} />
              <Metric2 label="Max profit" value={fmt(metrics.maxProfit)} tone={C.green} />
              <Metric2 label="Max loss" value={fmt(metrics.maxLoss)} tone={C.red} />
              <Metric2 label="Pos. delta" value={metrics.posDelta.toFixed(1)} tone={metrics.posDelta >= 0 ? C.green : C.red} />
              <Metric2 label="Theta/day" value={`₹${metrics.posTheta.toFixed(0)}`} tone={metrics.posTheta >= 0 ? C.green : C.red} />
              <Metric2 label="Time value" value={`₹${metrics.timeVal.toFixed(1)}`} />
              <Metric2 label="≈ Margin" value={fmt(metrics.margin)} />
            </div>

            <div style={{ display: 'flex', gap: 8 }}>
              <label style={{ flex: 1, fontSize: 10, color: C.dim }}>SL prem
                <input type="number" value={sl} onChange={e => setSl(e.target.value)} placeholder="opt." style={inputStyle} /></label>
              <label style={{ flex: 1, fontSize: 10, color: C.dim }}>Target prem
                <input type="number" value={tgt} onChange={e => setTgt(e.target.value)} placeholder="opt." style={inputStyle} /></label>
            </div>
            <div style={{ display: 'flex', gap: 6 }}>
              <button onClick={() => onPlace(side, lots, sl ? parseFloat(sl) : undefined, tgt ? parseFloat(tgt) : undefined)}
                className="btn btn--primary" style={{ flex: 1, fontSize: 11, padding: '7px 0' }}>PLACE {side}</button>
              <button onClick={onClear} className="btn" style={{ fontSize: 11, padding: '7px 10px' }}>✕</button>
            </div>
          </div>
        )}
        {msg && <div style={{ marginTop: 9, fontSize: 10, padding: '6px 8px', borderRadius: 4,
          background: msg.ok ? '#2DBD8014' : '#F2495C14', color: msg.ok ? C.green : C.red,
          border: `1px solid ${msg.ok ? '#2DBD8033' : '#F2495C33'}` }}>{msg.ok ? '✓ ' : '⚠ '}{msg.t}</div>}
      </div>
    </div>
  )
}
function Metric2({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
      <span style={{ color: C.dim }}>{label}</span>
      <span style={{ color: tone ?? C.text, fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>{value}</span>
    </div>
  )
}
const inputStyle: React.CSSProperties = {
  width: '100%', marginTop: 3, padding: '6px 8px', fontSize: 12, fontVariantNumeric: 'tabular-nums',
  background: C.card, border: `1px solid ${C.border2}`, borderRadius: 4, color: C.text, outline: 'none',
}

// ── F&O positions ─────────────────────────────────────────────────────────────
function FnOPositionsPanel({ positions, onClose }: { positions: FnOPosition[]; onClose: (tid: string) => void }) {
  const totUpnl = positions.reduce((s, p) => s + p.unrealized, 0)
  return (
    <div className="panel" style={{ flex: 1, minHeight: 0, borderRadius: 5, display: 'flex', flexDirection: 'column' }}>
      <div className="panel-header">F&amp;O POSITIONS <span style={{ color: '#4A4F57' }}>{positions.length}</span>
        {positions.length > 0 && <span style={{ marginLeft: 'auto', color: totUpnl >= 0 ? C.green : C.red, fontWeight: 700 }}>
          {totUpnl >= 0 ? '+' : ''}₹{totUpnl.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
        </span>}
      </div>
      <div className="panel-body" style={{ flex: 1, minHeight: 0, overflow: 'auto', padding: 8 }}>
        {positions.length === 0 ? (
          <div style={{ fontSize: 10, color: C.muted, textAlign: 'center', padding: 18 }}>No open F&amp;O positions.</div>
        ) : positions.map(p => (
          <div key={p.trade_id} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '7px 8px', marginBottom: 5,
            background: C.card, border: `1px solid ${C.border}`, borderRadius: 4,
            borderLeft: `2px solid ${p.side === 'BUY' ? C.green : C.red}` }}>
            <div style={{ minWidth: 0, flex: 1 }}>
              <div style={{ fontSize: 10.5, fontWeight: 700, color: C.text, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p.tradingsymbol}</div>
              <div style={{ fontSize: 9, color: C.muted, fontVariantNumeric: 'tabular-nums' }}>
                {p.side} {p.lots}×{p.lot_size} · entry {p.entry_price} · mark {p.mark}
              </div>
            </div>
            <div style={{ fontSize: 11, fontWeight: 700, color: p.unrealized >= 0 ? C.green : C.red, fontVariantNumeric: 'tabular-nums' }}>
              {p.unrealized >= 0 ? '+' : ''}{p.unrealized.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
            </div>
            <button onClick={() => onClose(p.trade_id)} className="btn" style={{ fontSize: 9, padding: '3px 7px' }} title="square off">✕</button>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────
export default function FnoPage() {
  const [regime, setRegime]   = useState<RegimeState | null>(null)
  const [orch, setOrch]       = useState<OrchestratorState | null>(null)
  const [signals, setSignals] = useState<SignalRec[]>([])
  const [view, setView]       = usePersistedState<'cockpit' | 'chain' | 'pipeline'>('tin.fno.view', 'cockpit')

  const load = useCallback(async () => {
    const [r, o, s] = await Promise.allSettled([
      api.regime(), api.orchestratorState(), api.signals(60),
    ])
    if (r.status === 'fulfilled') setRegime(r.value)
    if (o.status === 'fulfilled') setOrch(o.value)
    if (s.status === 'fulfilled') {
      setSignals(s.value.filter(x => INDEX_TOKENS.has(x.instrument_token)).slice(0, 30))
    }
  }, [])

  useEffect(() => { load() }, [load])
  useEffect(() => { const t = setInterval(load, 15_000); return () => clearInterval(t) }, [load])

  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', background: 'transparent', overflow: 'hidden' }}>
      <IndexStrip regime={regime} />

      {/* View toggle: cockpit (signals + reference) vs the option chain.
          Solid segmented control on a panel surface — opaque so the mesh never
          shows through (was a translucent strip over the dot-matrix). */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '7px 10px 0', flexShrink: 0 }}>
        <div style={{ display: 'inline-flex', padding: 2, gap: 2, background: C.panel, border: `1px solid ${C.border}`, borderRadius: 6 }}>
          {([['cockpit', 'COCKPIT'], ['chain', 'OPTION CHAIN'], ['pipeline', 'PIPELINE']] as const).map(([v, label]) => (
            <button key={v} onClick={() => setView(v)}
              style={{ fontSize: 10, fontWeight: 700, letterSpacing: '.06em', padding: '5px 15px', cursor: 'pointer', borderRadius: 4, border: 'none',
                background: view === v ? C.accent : 'transparent', color: view === v ? '#fff' : C.sub, transition: 'background .15s' }}>
              {label}
            </button>
          ))}
        </div>
        <span style={{ marginLeft: 'auto', fontSize: 9, color: C.dim }}>derivatives · paper execution</span>
      </div>

      {view === 'cockpit' ? (
        <div style={{ flex: 1, minHeight: 0, display: 'grid', gridTemplateColumns: '1.25fr 1fr', gap: 8, padding: '8px 10px', overflow: 'hidden' }}>
          {/* Left: your derivatives book (hero) + index signals */}
          <div style={{ minHeight: 0, display: 'flex', flexDirection: 'column', gap: 8 }}>
            <FnOBook />
            <div style={{ flex: '0 0 auto', maxHeight: '40%', overflow: 'auto' }}>
              <IndexSignals results={orch?.results ?? []} />
            </div>
          </div>
          {/* Right: futures contract reference + recent index signal log */}
          <div style={{ minHeight: 0, display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div style={{ flexShrink: 0 }}>
              <ContractReference />
            </div>
            <div style={{ flex: 1, minHeight: 0, overflow: 'auto' }}>
              <SignalLog signals={signals} />
            </div>
          </div>
        </div>
      ) : view === 'chain' ? (
        <div style={{ flex: 1, minHeight: 0, display: 'flex', padding: '8px 10px', overflow: 'hidden' }}>
          <OptionChain />
        </div>
      ) : (
        <div style={{ flex: 1, minHeight: 0, display: 'flex', padding: '8px 10px', overflow: 'hidden' }}>
          <TradePipelinePanel defaultSegment="ALL" />
        </div>
      )}

      <div style={{ padding: '0 10px 8px', flexShrink: 0 }}>
        <RoadmapStrip />
      </div>
    </div>
  )
}
