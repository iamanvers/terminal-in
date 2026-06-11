'use client'
import { THEME } from '@/lib/theme'
/**
 * LEARN MODULE — curated market education.
 * External resources (Varsity, Investopedia, quant reading) organized by
 * track, plus the glossary of concepts this terminal itself uses.
 */
import React, { useState } from 'react'

const C = THEME

type Resource = { title: string; url: string; desc: string; level: 'beginner' | 'intermediate' | 'advanced' }
type Track = { id: string; label: string; color: string; blurb: string; resources: Resource[] }

const TRACKS: Track[] = [
  {
    id: 'foundations', label: 'FOUNDATIONS', color: C.green,
    blurb: 'Market mechanics, instruments, and how Indian markets actually work.',
    resources: [
      { title: 'Varsity — Introduction to Stock Markets', url: 'https://zerodha.com/varsity/module/introduction-to-stock-markets/', desc: 'The canonical free Indian-markets course. Exchanges, IPOs, settlement, market participants.', level: 'beginner' },
      { title: 'Varsity — Technical Analysis', url: 'https://zerodha.com/varsity/module/technical-analysis/', desc: 'Candlesticks, support/resistance, volumes, indicators — the vocabulary this terminal’s lenses speak.', level: 'beginner' },
      { title: 'Varsity — Fundamental Analysis', url: 'https://zerodha.com/varsity/module/fundamental-analysis/', desc: 'Reading annual reports, ratios, DCF — the long-horizon counterweight to technicals.', level: 'intermediate' },
      { title: 'Investopedia — Stock Market Basics', url: 'https://www.investopedia.com/articles/basics/06/invest1000.asp', desc: 'Global reference for any term you hit anywhere in this app.', level: 'beginner' },
    ],
  },
  {
    id: 'derivatives', label: 'F&O / DERIVATIVES', color: C.purple,
    blurb: 'Futures, options, greeks, and strategies — required before the F&O module goes live in P2.',
    resources: [
      { title: 'Varsity — Futures Trading', url: 'https://zerodha.com/varsity/module/futures-trading/', desc: 'Contracts, margins (SPAN), leverage, settlement — exactly the machinery the F&O module will implement.', level: 'intermediate' },
      { title: 'Varsity — Options Theory for Professionals', url: 'https://zerodha.com/varsity/module/option-theory/', desc: 'Greeks, moneyness, volatility smile. The best free options text for Indian markets.', level: 'intermediate' },
      { title: 'Varsity — Option Strategies', url: 'https://zerodha.com/varsity/module/option-strategies/', desc: 'Spreads, straddles, condors — the multi-leg playbook planned for P3.', level: 'advanced' },
      { title: 'Investopedia — Options Greeks Guide', url: 'https://www.investopedia.com/trading/getting-to-know-the-greeks/', desc: 'Delta/gamma/theta/vega in plain language.', level: 'intermediate' },
    ],
  },
  {
    id: 'quant', label: 'QUANT & SYSTEMATIC', color: C.blue,
    blurb: 'The discipline behind this terminal: signals, risk, backtesting, and market microstructure.',
    resources: [
      { title: 'Varsity — Trading Systems', url: 'https://zerodha.com/varsity/module/trading-systems/', desc: 'Building rule-based systems — the philosophy behind the 8 strategies here.', level: 'intermediate' },
      { title: 'Varsity — Risk Management & Trading Psychology', url: 'https://zerodha.com/varsity/module/risk-management-trading-psychology/', desc: 'Position sizing, drawdowns, Kelly — why the M2 gate exists.', level: 'intermediate' },
      { title: 'Investopedia — Quantitative Trading', url: 'https://www.investopedia.com/terms/q/quantitative-trading.asp', desc: 'Survey of systematic approaches: stat-arb, momentum, mean reversion.', level: 'intermediate' },
      { title: 'HRT — Insights & Engineering Blog', url: 'https://www.hudsonrivertrading.com/hrtbeat/', desc: 'How a top prop firm thinks about markets, latency, and research. Aspirational reading for the low-latency roadmap.', level: 'advanced' },
      { title: 'QuantStart — Articles', url: 'https://www.quantstart.com/articles/', desc: 'Free deep-dives on backtesting, statistical arbitrage, and portfolio construction in Python.', level: 'advanced' },
    ],
  },
  {
    id: 'terminal', label: 'THIS TERMINAL', color: C.amber,
    blurb: 'The concepts TERMINAL//IN itself runs on — what the badges, gates, and verdicts mean.',
    resources: [
      { title: 'Expected Value (EV) ranking', url: 'https://www.investopedia.com/terms/e/expected-value.asp', desc: 'EV = confidence × reward:risk × volume factor × lens convergence. Signals fire only above EV 1.2 with hysteresis.', level: 'beginner' },
      { title: 'Kelly Criterion (position sizing)', url: 'https://www.investopedia.com/terms/k/kellycriterion.asp', desc: 'The orchestrator sizes at fractional Kelly, scaled by the regime multiplier.', level: 'intermediate' },
      { title: 'Hidden Markov Models (regime)', url: 'https://www.investopedia.com/terms/r/regime-switching-models.asp', desc: 'The 6-state regime classifier (strong_bull → high_vol) that scales all position sizing.', level: 'advanced' },
      { title: 'Bayesian win-rate updating', url: 'https://www.investopedia.com/terms/b/bayes-theorem.asp', desc: 'How the StrategyLearner and DSA weight strategies by their actual record, not hope.', level: 'intermediate' },
    ],
  },
]

const LEVEL_C = { beginner: C.green, intermediate: C.amber, advanced: '#F2495C' } as const

export default function LearnPage() {
  const [track, setTrack] = useState<string>(TRACKS[0].id)
  const active = TRACKS.find(t => t.id === track) ?? TRACKS[0]

  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', gap: 8, padding: '10px 14px', background: C.bg, overflow: 'hidden' }}>
      <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 5, padding: '12px 16px', flexShrink: 0 }}>
        <div className="t-display" style={{ fontSize: 17 }}>Market Education</div>
        <div className="t-prose" style={{ fontSize: 11.5, marginTop: 2 }}>
          Curated free resources — Zerodha Varsity for Indian-market depth, Investopedia for reference,
          and the quant reading behind this terminal’s design. All links open externally.
        </div>
      </div>

      {/* Track selector */}
      <div style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
        {TRACKS.map(t => (
          <button key={t.id} onClick={() => setTrack(t.id)} style={{
            fontSize: 10, fontWeight: 700, letterSpacing: '.08em', padding: '7px 16px',
            borderRadius: 4, cursor: 'pointer',
            border: `1px solid ${track === t.id ? t.color + '66' : C.border}`,
            background: track === t.id ? `${t.color}0E` : C.panel,
            color: track === t.id ? t.color : C.muted,
          }}>{t.label}</button>
        ))}
      </div>

      <div style={{ fontSize: 10.5, color: C.muted, padding: '0 2px', flexShrink: 0 }}>{active.blurb}</div>

      {/* Resource cards */}
      <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(330px, 1fr))', gap: 8, alignContent: 'start' }}>
        {active.resources.map(r => (
          <a key={r.url} href={r.url} target="_blank" rel="noopener noreferrer" style={{
            display: 'block', padding: '12px 14px', background: C.card,
            border: `1px solid ${C.border}`, borderRadius: 5, textDecoration: 'none',
            transition: 'border-color .12s',
          }}
            onMouseEnter={e => (e.currentTarget.style.borderColor = active.color + '66')}
            onMouseLeave={e => (e.currentTarget.style.borderColor = C.border)}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
              <span className="t-headline" style={{ color: C.text, fontWeight: 700, flex: 1 }}>{r.title}</span>
              <span style={{ fontSize: 9.5, fontWeight: 700, letterSpacing: '.06em', color: LEVEL_C[r.level], flexShrink: 0 }}>
                {r.level.toUpperCase()}
              </span>
            </div>
            <div className="t-prose" style={{ fontSize: 11.5, marginTop: 5 }}>{r.desc}</div>
            <div style={{ fontSize: 10, color: C.muted, marginTop: 7 }}>{new URL(r.url).hostname} ↗</div>
          </a>
        ))}
      </div>
    </div>
  )
}
