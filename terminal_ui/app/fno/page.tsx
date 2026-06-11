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
} from '@/lib/api'
import { useTickMap } from '@/hooks/useSocket'

const C = THEME

const INDICES = [
  { symbol: 'NIFTY 50',          token: 256265, label: 'NIFTY 50',  lot: 75 },
  { symbol: 'NIFTY BANK',        token: 260105, label: 'BANKNIFTY', lot: 35 },
  { symbol: 'NIFTY FIN SERVICE', token: 257801, label: 'FINNIFTY',  lot: 65 },
]
const VIX_TOKEN = 264969
const INDEX_TOKENS = new Set([256265, 260105, 257801])

function fmtTs(ms: number) { return new Date(ms).toLocaleTimeString('en-IN', { hour12: false }) }

// ── Index complex strip ───────────────────────────────────────────────────────
function IndexStrip({ regime }: { regime: RegimeState | null }) {
  const ticks = useTickMap()
  const [closes, setCloses] = useState<Record<string, { close: number }>>({})
  useEffect(() => { api.lastCloses().then(c => setCloses(c as never)).catch(() => {}) }, [])

  const vix = ticks[VIX_TOKEN]?.last_price ?? closes[String(VIX_TOKEN)]?.close ?? 0
  const vixColor = vix > 25 ? C.red : vix > 18 ? C.amber : C.green

  return (
    <div style={{ display: 'flex', alignItems: 'stretch', background: '#0C0D10', borderBottom: `1px solid ${C.border}`, flexShrink: 0, height: 58 }}>
      <div style={{ padding: '0 16px', borderRight: `1px solid ${C.border}`, display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center', gap: 2, minWidth: 86 }}>
        <span style={{ fontSize: 10.5, fontWeight: 700, color: C.text, letterSpacing: '.1em' }}>F&amp;O</span>
        <span style={{ fontSize: 9.5, fontWeight: 700, color: C.purple, letterSpacing: '.1em', background: '#15081A', border: `1px solid ${C.purple}33`, borderRadius: 3, padding: '1px 6px' }}>DERIVATIVES</span>
      </div>
      {INDICES.map(({ token, label, lot }) => {
        const price = ticks[token]?.last_price ?? closes[String(token)]?.close ?? 0
        const chg = ticks[token]?.change ?? 0
        return (
          <div key={token} style={{ flex: 1, padding: '0 14px', borderRight: `1px solid ${C.border}`, display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: 2 }}>
            <span style={{ fontSize: 9.5, color: C.dim, letterSpacing: '.08em' }}>{label} <span style={{ color: '#3C424B' }}>· LOT {lot}</span></span>
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
      <div className="panel-header">INDEX STRATEGY SIGNALS <span style={{ color: '#3C424B' }}>S1 ORB · S2 52W · S8 VIX FADE</span></div>
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
      <div className="panel-header">SIGNAL LOG <span style={{ color: '#3C424B' }}>INDEX COMPLEX</span></div>
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

// ── Phase 2 scaffold ──────────────────────────────────────────────────────────
function DerivativesRoadmap() {
  const items = [
    { phase: 'P2', title: 'Contract chain', desc: 'NIFTY/BANKNIFTY weekly + monthly option chains, futures curve, OI and IV per strike (Kite Connect instruments dump).' },
    { phase: 'P2', title: 'Lot-based paper execution', desc: 'Orders in lots (NIFTY 75 / BANKNIFTY 35), expiry-aware positions, auto square-off on expiry day.' },
    { phase: 'P2', title: 'SPAN margin estimation', desc: 'Realistic margin blocking for short options / futures instead of the 30% cash notional rule.' },
    { phase: 'P3', title: 'Options strategies', desc: 'Spreads, straddles, iron condors as first-class multi-leg positions with combined greeks and payoff curves.' },
    { phase: 'P3', title: 'FX & commodities', desc: 'CDS currency futures (USDINR), MCX commodities (gold, crude) — then global venues. See PRD roadmap.' },
  ]
  return (
    <div className="panel" style={{ borderRadius: 5 }}>
      <div className="panel-header">DERIVATIVES EXECUTION <span className="chip chip--accent" style={{ marginLeft: 4 }}>PHASE 2 — PLANNED</span></div>
      <div className="panel-body" style={{ padding: 10 }}>
        <div style={{ fontSize: 10.5, color: C.sub, marginBottom: 10, lineHeight: 1.6 }}>
          Index underlyings are F&amp;O-only — the risk gate correctly blocks them as cash trades today.
          Derivative execution lands here as a separate pipeline (lot sizing, expiry, SPAN margin),
          not a bolt-on to the equities path.
        </div>
        {items.map(i => (
          <div key={i.title} style={{ display: 'flex', gap: 10, padding: '7px 0', borderTop: `1px solid ${C.border}`, alignItems: 'baseline' }}>
            <span style={{ fontSize: 9.5, fontWeight: 700, color: i.phase === 'P2' ? C.amber : C.muted, border: `1px solid ${i.phase === 'P2' ? C.amber + '44' : C.border2}`, borderRadius: 3, padding: '1px 6px', flexShrink: 0 }}>{i.phase}</span>
            <div>
              <div style={{ fontSize: 10.5, fontWeight: 700, color: C.text }}>{i.title}</div>
              <div style={{ fontSize: 10, color: C.muted, lineHeight: 1.5 }}>{i.desc}</div>
            </div>
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
    <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', background: C.bg, overflow: 'hidden' }}>
      <IndexStrip regime={regime} />
      <div style={{ flex: 1, minHeight: 0, display: 'grid', gridTemplateColumns: '1.3fr 1fr', gridTemplateRows: '1fr 1fr', gap: 8, padding: '8px 10px', overflow: 'hidden' }}>
        <div style={{ gridRow: '1 / 3', minHeight: 0, display: 'flex', flexDirection: 'column', gap: 8 }}>
          <IndexSignals results={orch?.results ?? []} />
          <SignalLog signals={signals} />
        </div>
        <div style={{ gridRow: '1 / 3', minHeight: 0 }}>
          <DerivativesRoadmap />
        </div>
      </div>
    </div>
  )
}
