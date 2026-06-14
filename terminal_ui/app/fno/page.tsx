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
import React, { useCallback, useEffect, useState } from 'react'
import {
  api, OrchestratorState, OrchestratorResult, RegimeState, SignalRec, Instrument,
  FnOChain, FnOExpiry, FnOUnderlying,
} from '@/lib/api'
import { useTickMap } from '@/hooks/useSocket'
import HoldingsPanel from '@/components/panels/HoldingsPanel'

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

// ── Option chain (Stage 2) ────────────────────────────────────────────────────
function OptionChain() {
  const [unders, setUnders]   = useState<FnOUnderlying[]>([])
  const [under, setUnder]     = useState('NIFTY')
  const [expiry, setExpiry]   = useState<string | undefined>(undefined)
  const [chain, setChain]     = useState<FnOChain | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => { api.fnoUnderlyings().then(d => setUnders(d.underlyings)).catch(() => {}) }, [])

  const loadChain = useCallback(async (u: string, exp?: string) => {
    setLoading(true)
    try {
      const c = await api.fnoChain(u, exp, 12)
      setChain(c)
      if (!exp && c.expiry) setExpiry(c.expiry)
    } catch { setChain(null) } finally { setLoading(false) }
  }, [])

  useEffect(() => { loadChain(under, expiry) /* eslint-disable-next-line */ }, [under])
  // refresh premiums every 15s (theoretical, recomputed from live spot)
  useEffect(() => { const t = setInterval(() => loadChain(under, expiry), 15_000); return () => clearInterval(t) }, [under, expiry, loadChain])

  const exps = chain?.expiries ?? []
  const greekTone = (v: number) => (v >= 0 ? C.green : C.red)

  return (
    <div className="panel" style={{ flex: 1, minHeight: 0, borderRadius: 5, display: 'flex', flexDirection: 'column' }}>
      <div className="panel-header" style={{ flexWrap: 'wrap', gap: 8 }}>
        OPTION CHAIN
        {/* underlying tabs */}
        <span style={{ display: 'inline-flex', gap: 2, marginLeft: 8 }}>
          {(unders.length ? unders.map(u => u.label) : ['NIFTY', 'BANKNIFTY', 'FINNIFTY']).map(l => (
            <button key={l} onClick={() => { setExpiry(undefined); setUnder(l) }}
              style={{ fontSize: 9.5, fontWeight: 700, letterSpacing: '.04em', padding: '3px 9px', border: 'none', cursor: 'pointer', borderRadius: 3,
                background: under === l ? C.accent : 'transparent', color: under === l ? '#fff' : C.sub }}>{l}</button>
          ))}
        </span>
        {/* expiry chips */}
        <span style={{ display: 'inline-flex', gap: 3, marginLeft: 6, flexWrap: 'wrap' }}>
          {exps.slice(0, 6).map(e => (
            <button key={e.date} onClick={() => { setExpiry(e.date); loadChain(under, e.date) }}
              title={e.kind}
              style={{ fontSize: 9, fontWeight: 600, padding: '2px 7px', borderRadius: 3, cursor: 'pointer',
                border: `1px solid ${expiry === e.date ? C.accent : C.border2}`,
                background: expiry === e.date ? '#0094FB18' : 'transparent',
                color: expiry === e.date ? C.accentBright : C.muted }}>
              {new Date(e.date).toLocaleDateString('en-IN', { day: '2-digit', month: 'short' })}
              {e.kind === 'monthly' && <span style={{ color: C.warn, marginLeft: 3 }}>M</span>}
            </button>
          ))}
        </span>
        {chain && <span style={{ marginLeft: 'auto', color: C.muted, fontWeight: 400, fontSize: 9.5 }}>
          spot {chain.spot.toLocaleString('en-IN')} · ATM {chain.atm_strike} · IV {chain.iv_used_pct}% · lot {chain.lot_size}
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
                return (
                  <tr key={r.strike} style={{ background: r.is_atm ? '#0094FB12' : undefined }}>
                    <td style={{ textAlign: 'right', color: greekTone(r.CE.delta) }}>{r.CE.delta.toFixed(2)}</td>
                    <td style={{ textAlign: 'right', color: C.muted }}>{r.CE.theta.toFixed(1)}</td>
                    <td style={{ textAlign: 'right', color: C.text, fontWeight: 600, background: itmCE ? '#2DBD800C' : undefined }}>{r.CE.premium.toFixed(2)}</td>
                    <td style={{ textAlign: 'center', fontWeight: 700, color: r.is_atm ? C.accentBright : C.sub, borderLeft: `1px solid ${C.border}`, borderRight: `1px solid ${C.border}` }}>
                      {r.strike}{r.is_atm && <span style={{ fontSize: 8, color: C.accent, marginLeft: 4 }}>ATM</span>}
                    </td>
                    <td style={{ textAlign: 'left', color: C.text, fontWeight: 600, background: itmPE ? '#F2495C0C' : undefined }}>{r.PE.premium.toFixed(2)}</td>
                    <td style={{ textAlign: 'left', color: C.muted }}>{r.PE.theta.toFixed(1)}</td>
                    <td style={{ textAlign: 'left', color: greekTone(r.PE.delta) }}>{r.PE.delta.toFixed(2)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>
      {chain?.theoretical && (
        <div style={{ fontSize: 9, color: C.dim, padding: '5px 10px', borderTop: `1px solid ${C.border}`, flexShrink: 0 }}>
          *LTP = <strong style={{ color: C.muted }}>theoretical</strong> Black-Scholes premium from live spot + India VIX ({chain.iv_used_pct}%) as IV — not a traded price. OI/real-IV are live-only.
        </div>
      )}
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────
export default function FnoPage() {
  const [regime, setRegime]   = useState<RegimeState | null>(null)
  const [orch, setOrch]       = useState<OrchestratorState | null>(null)
  const [signals, setSignals] = useState<SignalRec[]>([])
  const [view, setView]       = useState<'cockpit' | 'chain'>('cockpit')

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

      {/* View toggle: cockpit (signals + reference) vs the option chain */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '7px 10px 0', flexShrink: 0 }}>
        {([['cockpit', 'COCKPIT'], ['chain', 'OPTION CHAIN']] as const).map(([v, label]) => (
          <button key={v} onClick={() => setView(v)}
            style={{ fontSize: 10, fontWeight: 700, letterSpacing: '.06em', padding: '5px 13px', cursor: 'pointer', borderRadius: 4,
              border: `1px solid ${view === v ? C.accent : C.border}`,
              background: view === v ? '#0094FB14' : 'transparent', color: view === v ? C.accentBright : C.sub }}>
            {label}
          </button>
        ))}
        <span style={{ marginLeft: 'auto', fontSize: 9, color: C.dim }}>derivatives · theoretical pricing (paper)</span>
      </div>

      {view === 'cockpit' ? (
        <div style={{ flex: 1, minHeight: 0, display: 'grid', gridTemplateColumns: '1.3fr 1fr', gap: 8, padding: '8px 10px', overflow: 'hidden' }}>
          <div style={{ minHeight: 0, display: 'flex', flexDirection: 'column', gap: 8 }}>
            <IndexSignals results={orch?.results ?? []} />
            <SignalLog signals={signals} />
          </div>
          <div style={{ minHeight: 0, display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div style={{ flex: '0 0 auto', maxHeight: '42%', overflow: 'auto' }}>
              <HoldingsPanel segment="FNO" />
            </div>
            <div style={{ flex: 1, minHeight: 0, overflow: 'auto' }}>
              <ContractReference />
            </div>
          </div>
        </div>
      ) : (
        <div style={{ flex: 1, minHeight: 0, display: 'flex', padding: '8px 10px', overflow: 'hidden' }}>
          <OptionChain />
        </div>
      )}

      <div style={{ padding: '0 10px 8px', flexShrink: 0 }}>
        <RoadmapStrip />
      </div>
    </div>
  )
}
